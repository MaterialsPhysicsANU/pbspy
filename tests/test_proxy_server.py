"""
Integration tests for pbspy.server.proxy_server.

ProxyServer never parses the pbspy wire protocol -- it just relays bytes to a real Server
over an SSH-like subprocess. These tests spin up a real `run_server()` (with mocked PBS
operations, as in test_server.py) plus a `run_proxy_server()` pointed at it, substituting a
small Python script for `_ssh_command` so no real `ssh` binary or network access is needed.
The same protocol-level assertions used against a direct Server connection are re-run against
the ProxyServer's port to verify the relay is transparent.
"""

from __future__ import annotations

import queue
import socket
import sys
import threading
import time
from collections.abc import Callable, Generator
from typing import BinaryIO, cast
from unittest.mock import MagicMock, patch

import pytest

import pbspy._protocol as proto
from pbspy import Job, JobResult
from pbspy._server_backend import ServerBackend
from pbspy.server import run_proxy_server, run_server
from tests.test_server import ServerHandle

_WAIT_TIMEOUT = 5.0


def _wait_for(condition: Callable[[], bool], timeout: float = _WAIT_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


# A stand-in for `ssh -W localhost:<port> <host>`: connects to the given local port and
# splices stdin/stdout with that socket, exactly as `ssh -W` would over an SSH channel.
_FAKE_SSH_SOURCE = """
import os, select, socket, sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("127.0.0.1", port))
stdin_fd = sys.stdin.buffer.fileno()
stdout_fd = sys.stdout.buffer.fileno()
sock_fd = sock.fileno()

while True:
    readable, _, exceptional = select.select([stdin_fd, sock_fd], [], [stdin_fd, sock_fd])
    if exceptional:
        break
    done = False
    for fd in readable:
        if fd == stdin_fd:
            data = os.read(stdin_fd, 65536)
            if not data:
                done = True
                break
            sock.sendall(data)
        elif fd == sock_fd:
            data = sock.recv(65536)
            if not data:
                done = True
                break
            os.write(stdout_fd, data)
    if done:
        break
"""


def _fake_ssh_command(remote_port: int) -> list[str]:
    return [sys.executable, "-c", _FAKE_SSH_SOURCE, str(remote_port)]


@pytest.fixture()
def mock_pbs_submit() -> Generator[MagicMock, None, None]:
    with patch("pbspy.server.server.core.pbs_submit", return_value=("100.mock", "test_job")) as m:
        yield m


@pytest.fixture()
def mock_check_finished() -> Generator[MagicMock, None, None]:
    with patch("pbspy.server.server._check_job_finished", return_value=None) as m:
        yield m


@pytest.fixture()
def mock_pbs_get_result() -> Generator[MagicMock, None, None]:
    with patch(
        "pbspy.server.server.core.pbs_get_result",
        return_value=JobResult(exit_code=0, output="hello\n"),
    ) as m:
        yield m


@pytest.fixture()
def real_server(
    mock_pbs_submit: MagicMock,
    mock_check_finished: MagicMock,
    mock_pbs_get_result: MagicMock,
) -> Generator[ServerHandle, None, None]:
    port_q: queue.SimpleQueue[int] = queue.SimpleQueue()
    stop = threading.Event()

    t = threading.Thread(
        target=run_server,
        kwargs={"port": 0, "poll_interval": 0.1, "_ready_callback": port_q.put, "_stop_event": stop},
        daemon=True,
    )
    t.start()
    port = port_q.get(timeout=_WAIT_TIMEOUT)
    yield ServerHandle("127.0.0.1", port)
    stop.set()
    t.join(timeout=2.0)


@pytest.fixture()
def proxy_server(real_server: ServerHandle) -> Generator[ServerHandle, None, None]:
    port_q: queue.SimpleQueue[int] = queue.SimpleQueue()
    stop = threading.Event()

    t = threading.Thread(
        target=run_proxy_server,
        kwargs={
            "ssh_host": "unused",
            "port": 0,
            "remote_port": real_server.port,
            "_ssh_command": _fake_ssh_command(real_server.port),
            "_ready_callback": port_q.put,
            "_stop_event": stop,
        },
        daemon=True,
    )
    t.start()
    port = port_q.get(timeout=_WAIT_TIMEOUT)
    yield ServerHandle("127.0.0.1", port)
    stop.set()
    t.join(timeout=2.0)


def test_ping_through_proxy(proxy_server: ServerHandle) -> None:
    response = proxy_server.rpc(proto.PingRequest())
    assert isinstance(response, proto.PongResponse)


def test_submit_through_proxy(proxy_server: ServerHandle) -> None:
    response = proxy_server.rpc(proto.SubmitRequest(script="#!/bin/bash\necho hi", name="test_job"))
    assert isinstance(response, proto.SubmittedResponse)
    assert response.job.job_id == "100.mock"
    assert response.job.job_name == "test_job"


def test_result_through_proxy(proxy_server: ServerHandle) -> None:
    job = Job(job_id="100.mock", job_name="test_job")
    response = proxy_server.rpc(proto.ResultRequest(job=job))
    assert isinstance(response, proto.ResultResponse)
    assert response.result.exit_code == 0
    assert response.result.output == "hello\n"


def test_server_backend_works_unmodified_through_proxy(proxy_server: ServerHandle) -> None:
    """ServerBackend, with no awareness of ProxyServer, should work exactly as against a Server."""
    backend = ServerBackend(proxy_server.host, proxy_server.port)
    job_id, job_name = backend.submit("#!/bin/bash\necho hi", name="test_job")
    backend.close()
    assert job_id == "100.mock"
    assert job_name == "test_job"


def test_closing_client_terminates_relay_subprocess(real_server: ServerHandle) -> None:
    """When a client disconnects, the spawned ssh-stand-in subprocess should be cleaned up."""
    import subprocess

    spawned: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def _tracking_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        proc: subprocess.Popen[bytes] = real_popen(*args, **kwargs)  # type: ignore[call-overload]
        spawned.append(proc)
        return proc

    port_q: queue.SimpleQueue[int] = queue.SimpleQueue()
    stop = threading.Event()

    with patch("pbspy.server.proxy_server.subprocess.Popen", side_effect=_tracking_popen):
        t = threading.Thread(
            target=run_proxy_server,
            kwargs={
                "ssh_host": "unused",
                "port": 0,
                "remote_port": real_server.port,
                "_ssh_command": _fake_ssh_command(real_server.port),
                "_ready_callback": port_q.put,
                "_stop_event": stop,
            },
            daemon=True,
        )
        t.start()
        port = port_q.get(timeout=_WAIT_TIMEOUT)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", port))
        stream = cast("BinaryIO", sock.makefile("rwb", buffering=0))
        sock.close()
        proto.send_frame(stream, proto.PingRequest())
        assert _wait_for(lambda: len(spawned) > 0), "subprocess not spawned in time"
        stream.close()
        assert _wait_for(lambda: spawned[0].poll() is not None), "subprocess not cleaned up after client disconnect"

        stop.set()
        t.join(timeout=2.0)

    assert spawned, "expected a subprocess to have been spawned"
    assert spawned[0].poll() is not None, "subprocess should have been terminated after client disconnect"
