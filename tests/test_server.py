"""
Integration tests for pbspy.server.

Spins up a real server (in a background thread) with mocked PBS operations so
that no ``qsub``/``qstat`` installation is needed.
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from collections.abc import Generator
from typing import BinaryIO, cast
from unittest.mock import MagicMock, patch

import pytest

import pbspy._protocol as proto
from pbspy import Job, JobResult
from pbspy.server import run_server

# ---------------------------------------------------------------------------
# Fixture: running server
# ---------------------------------------------------------------------------

_WAIT_TIMEOUT = 5.0  # seconds to wait for the server to become ready


class ServerHandle:
    """Handle to a running test server."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def connect(self, timeout: float | None = None) -> BinaryIO:
        """Open a TCP connection and return a binary file-like object."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        if timeout is not None:
            sock.settimeout(timeout)
        f = cast(BinaryIO, sock.makefile("rwb", buffering=0))
        # Close the socket object so that when the SocketIO is GC'd it properly
        # calls _real_close() (via _decref_socketios). Without this, the socket
        # FD leaks and Python emits a ResourceWarning.
        sock.close()
        return f

    def rpc(self, request: object) -> object:
        """Send one request, return the first response, then close."""
        stream = self.connect()
        try:
            proto.send_frame(stream, request)
            return proto.recv_frame(stream)
        finally:
            stream.close()


@pytest.fixture()
def mock_pbs_submit() -> Generator[MagicMock, None, None]:
    """Patch pbs_submit to return a fake job without calling qsub."""
    with patch("pbspy.server.server.core.pbs_submit", return_value=("100.mock", "test_job")) as m:
        yield m


@pytest.fixture()
def mock_check_finished() -> Generator[MagicMock, None, None]:
    """Patch _check_job_finished to report jobs as never finished (default)."""
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
def server(
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


# ---------------------------------------------------------------------------
# Ping / pong
# ---------------------------------------------------------------------------


def test_ping(server: ServerHandle) -> None:
    response = server.rpc(proto.PingRequest())
    assert isinstance(response, proto.PongResponse)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def test_submit_returns_job(server: ServerHandle) -> None:
    response = server.rpc(proto.SubmitRequest(script="#!/bin/bash\necho hi", name="test_job"))
    assert isinstance(response, proto.SubmittedResponse)
    assert response.job.job_id == "100.mock"
    assert response.job.job_name == "test_job"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


def test_result_returns_job_result(server: ServerHandle) -> None:
    job = Job(job_id="100.mock", job_name="test_job")
    response = server.rpc(proto.ResultRequest(job=job))
    assert isinstance(response, proto.ResultResponse)
    assert response.result.exit_code == 0
    assert response.result.output == "hello\n"


# ---------------------------------------------------------------------------
# Wait — already finished
# ---------------------------------------------------------------------------


def test_wait_already_finished_returns_immediately() -> None:
    """If the job is already marked F in state, WaitRequest should return without blocking."""
    port_q: queue.SimpleQueue[int] = queue.SimpleQueue()
    stop = threading.Event()

    def _run() -> None:
        with (
            patch("pbspy.server.server.core.pbs_submit", return_value=("done.mock", "done_job")),
            # Return 0 immediately so the very first poll marks the job finished.
            patch("pbspy.server.server._check_job_finished", return_value=0),
            patch("pbspy.server.server.core.pbs_get_result", return_value=JobResult(exit_code=0)),
        ):
            run_server(port=0, poll_interval=0.1, _ready_callback=port_q.put, _stop_event=stop)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    port = port_q.get(timeout=_WAIT_TIMEOUT)
    handle = ServerHandle("127.0.0.1", port)

    # Submit the job, then wait long enough for the poll loop (0.1s) to mark it done.
    handle.rpc(proto.SubmitRequest(script="#!/bin/bash", name="done_job"))

    time.sleep(0.5)  # poll interval is 0.1s; 0.5s is more than enough

    job = Job(job_id="done.mock", job_name="done_job")
    stream = handle.connect()
    proto.send_frame(stream, proto.WaitRequest(jobs=[job]))

    response = proto.recv_frame(stream)
    stream.close()

    assert isinstance(response, proto.WaitDoneResponse)
    assert response.jobs[0].job_id == "done.mock"

    stop.set()
    t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Wait — job finishes during wait
# ---------------------------------------------------------------------------


def test_wait_receives_status_update_then_done(server: ServerHandle, mock_check_finished: MagicMock) -> None:
    """
    Submit a job, start waiting, then let the poll loop (0.1s interval) detect
    the job as finished and push WaitDoneResponse back to the client.
    """
    server.rpc(proto.SubmitRequest(script="#!/bin/bash", name="test_job"))

    job = Job(job_id="100.mock", job_name="test_job")
    stream = server.connect(timeout=5.0)
    proto.send_frame(stream, proto.WaitRequest(jobs=[job]))

    # Allow the poll loop to mark the job as finished.
    mock_check_finished.return_value = 0

    # Collect responses until WaitDoneResponse (or timeout).
    responses = []
    try:
        while True:
            r = proto.recv_frame(stream)
            responses.append(r)
            if isinstance(r, proto.WaitDoneResponse):
                break
    except (EOFError, OSError):
        pass

    stream.close()

    assert any(isinstance(r, proto.WaitDoneResponse) for r in responses), f"Expected WaitDoneResponse; got: {responses}"
