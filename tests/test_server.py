"""
Integration tests for pbspy_server.server.

Spins up a real server (in a background thread) with mocked PBS operations so
that no ``qsub``/``qstat`` installation is needed.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import BinaryIO, cast
from unittest.mock import MagicMock, patch

import pytest

import pbspy._protocol as proto
from pbspy import Job, JobResult
from pbspy_server.server import run_server

# ---------------------------------------------------------------------------
# Fixture: running server
# ---------------------------------------------------------------------------

_WAIT_TIMEOUT = 5.0  # seconds to wait for server address file to appear


def _wait_for_server(addr_path: Path, timeout: float = _WAIT_TIMEOUT) -> None:
    """Wait until the server address file appears (server is bound and ready)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if addr_path.exists():
            return
        time.sleep(0.05)
    raise TimeoutError(f"Server addr file {addr_path} did not appear within {timeout}s")


def _read_addr(addr_path: Path) -> tuple[str, int, str]:
    data = json.loads(addr_path.read_text())
    return data["host"], int(data["port"]), data["token"]


class ServerHandle:
    """Handle to a running test server."""

    def __init__(self, addr_path: Path) -> None:
        self.addr_path = addr_path

    def connect(self, timeout: float | None = None) -> BinaryIO:
        """Open an authenticated TCP connection and return a binary file-like object."""
        host, port, token = _read_addr(self.addr_path)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        if timeout is not None:
            sock.settimeout(timeout)
        f = cast(BinaryIO, sock.makefile("rwb", buffering=0))
        # Close the socket object so that when the SocketIO is GC'd it properly
        # calls _real_close() (via _decref_socketios). Without this, the socket
        # FD leaks and Python emits a ResourceWarning.
        sock.close()
        proto.send_frame(f, proto.AuthRequest(token=token))
        auth_resp = proto.recv_frame(f)
        assert isinstance(auth_resp, proto.AuthOkResponse), f"Auth failed: {auth_resp!r}"
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
    with patch("pbspy_server.server.core.pbs_submit", return_value=("100.mock", "test_job")) as m:
        yield m


@pytest.fixture()
def mock_check_finished() -> Generator[MagicMock, None, None]:
    """Patch _check_job_finished to report jobs as never finished (default)."""
    with patch("pbspy_server.server._check_job_finished", return_value=None) as m:
        yield m


@pytest.fixture()
def mock_pbs_get_result() -> Generator[MagicMock, None, None]:
    with patch(
        "pbspy_server.server.core.pbs_get_result",
        return_value=JobResult(exit_code=0, output="hello\n"),
    ) as m:
        yield m


@pytest.fixture()
def server(
    tmp_path: Path,
    mock_pbs_submit: MagicMock,
    mock_check_finished: MagicMock,
    mock_pbs_get_result: MagicMock,
) -> Generator[ServerHandle, None, None]:
    addr_path = tmp_path / "test.addr"

    t = threading.Thread(
        target=run_server,
        kwargs={"addr_path": addr_path, "poll_interval": 0.1},
        daemon=True,
    )
    t.start()
    _wait_for_server(addr_path)
    yield ServerHandle(addr_path)
    # Server exits on its own once no clients + no jobs (shutdown test).
    # For other tests, give it a moment to clean up.
    t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Ping / pong
# ---------------------------------------------------------------------------


def test_ping(server: ServerHandle) -> None:
    response = server.rpc(proto.PingRequest())
    assert isinstance(response, proto.PongResponse)


# ---------------------------------------------------------------------------
# Auth — rejection cases
# ---------------------------------------------------------------------------


def test_auth_rejected_wrong_token(server: ServerHandle) -> None:
    """Connecting with a wrong token must return ErrorResponse and close the connection."""
    host, port, _token = _read_addr(server.addr_path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    f = cast(BinaryIO, sock.makefile("rwb", buffering=0))
    sock.close()

    proto.send_frame(f, proto.AuthRequest(token="wrong-token"))
    resp = proto.recv_frame(f)
    assert isinstance(resp, proto.ErrorResponse)
    # Server should close the connection after rejecting auth.
    try:
        proto.recv_frame(f)
        received_eof = False
    except EOFError:
        received_eof = True
    f.close()
    assert received_eof, "Expected server to close connection after auth failure"


def test_auth_rejected_non_auth_first_frame(server: ServerHandle) -> None:
    """Sending a non-AuthRequest as the first frame must be rejected."""
    host, port, _token = _read_addr(server.addr_path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    f = cast(BinaryIO, sock.makefile("rwb", buffering=0))
    sock.close()

    proto.send_frame(f, proto.PingRequest())  # Wrong first frame
    resp = proto.recv_frame(f)
    assert isinstance(resp, proto.ErrorResponse)
    f.close()


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


def test_wait_already_finished_returns_immediately(tmp_path: Path) -> None:
    """If the job is already marked F in state, WaitRequest should return without blocking."""
    addr_path = tmp_path / "wait-done.addr"
    server_done = threading.Event()

    def _run() -> None:
        with (
            patch("pbspy_server.server.core.pbs_submit", return_value=("done.mock", "done_job")),
            # Return 0 immediately so the very first poll marks the job finished.
            patch("pbspy_server.server._check_job_finished", return_value=0),
            patch("pbspy_server.server.core.pbs_get_result", return_value=JobResult(exit_code=0)),
        ):
            run_server(addr_path=addr_path, poll_interval=0.1)
        server_done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _wait_for_server(addr_path)

    # Submit the job, then wait long enough for the poll loop (0.1s) to mark it done.
    stream = _raw_connect(addr_path)
    proto.send_frame(stream, proto.SubmitRequest(script="#!/bin/bash", name="done_job"))
    proto.recv_frame(stream)
    stream.close()

    time.sleep(0.5)  # poll interval is 0.1s; 0.5s is more than enough

    job = Job(job_id="done.mock", job_name="done_job")
    stream = _raw_connect(addr_path)
    proto.send_frame(stream, proto.WaitRequest(jobs=[job]))

    response = proto.recv_frame(stream)
    stream.close()

    assert isinstance(response, proto.WaitDoneResponse)
    assert response.jobs[0].job_id == "done.mock"

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


# ---------------------------------------------------------------------------
# Shutdown: no jobs + last client disconnects
# ---------------------------------------------------------------------------


def test_shutdown_when_no_jobs_and_no_clients(tmp_path: Path) -> None:
    """
    The server should exit automatically when the last client disconnects
    and there are no unfinished jobs.
    """
    addr_path = tmp_path / "shutdown.addr"

    server_done = threading.Event()

    def _run() -> None:
        with (
            patch("pbspy_server.server.core.pbs_submit", return_value=("1.mock", "j")),
            patch("pbspy_server.server._check_job_finished", return_value=None),
            patch("pbspy_server.server.core.pbs_get_result", return_value=JobResult(exit_code=0)),
        ):
            run_server(addr_path=addr_path)
        server_done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _wait_for_server(addr_path)

    # Connect, ping, and disconnect — no jobs submitted
    stream = _raw_connect(addr_path)
    proto.send_frame(stream, proto.PingRequest())
    proto.recv_frame(stream)
    stream.close()

    assert server_done.wait(timeout=5.0), "Server did not exit after last client disconnected with no jobs"


# ---------------------------------------------------------------------------
# Shutdown: stays alive while jobs pending
# ---------------------------------------------------------------------------


def test_server_stays_alive_while_jobs_pending(tmp_path: Path) -> None:
    """
    If jobs are still unfinished, the server must NOT exit when the last
    client disconnects; it should exit once the poll loop detects them done.
    """
    addr_path = tmp_path / "pending.addr"
    server_done = threading.Event()

    with (
        patch("pbspy_server.server.core.pbs_submit", return_value=("2.mock", "pending_job")) as _,
        patch("pbspy_server.server._check_job_finished", return_value=None) as mock_check,
        patch("pbspy_server.server.core.pbs_get_result", return_value=JobResult(exit_code=0)),
    ):

        def _run() -> None:
            run_server(addr_path=addr_path, poll_interval=0.1)
            server_done.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        _wait_for_server(addr_path)

        # Submit a job then disconnect
        stream = _raw_connect(addr_path)
        proto.send_frame(stream, proto.SubmitRequest(script="#!/bin/bash", name="pending_job"))
        proto.recv_frame(stream)
        stream.close()

        # Server should NOT have shut down yet (jobs still pending)
        assert not server_done.wait(timeout=1.0), "Server exited prematurely while jobs were still pending"

        # Let the poll loop see the job as finished → server should then exit.
        mock_check.return_value = 0
        assert server_done.wait(timeout=5.0), "Server did not exit after all jobs finished"

    t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_connect(addr_path: Path) -> BinaryIO:
    host, port, token = _read_addr(addr_path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    f = cast(BinaryIO, sock.makefile("rwb", buffering=0))
    sock.close()  # Mark closed; SocketIO keeps FD open via _io_refs
    proto.send_frame(f, proto.AuthRequest(token=token))
    auth_resp = proto.recv_frame(f)
    assert isinstance(auth_resp, proto.AuthOkResponse), f"Auth failed: {auth_resp!r}"
    return f
