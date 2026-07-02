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
def mock_get_states() -> Generator[MagicMock, None, None]:
    """Patch core.pbs_get_states to report jobs as still running (never finished) by default."""
    state = {"value": "R"}

    def _get_states(job_ids: list[str], runner: object = None) -> dict[str, str | None]:
        return dict.fromkeys(job_ids, state["value"])

    with patch("pbspy.server.server.core.pbs_get_states", side_effect=_get_states) as m:
        m.state = state
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
    mock_get_states: MagicMock,
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
def server_with_key(
    mock_pbs_submit: MagicMock,
    mock_get_states: MagicMock,
    mock_pbs_get_result: MagicMock,
) -> Generator[ServerHandle, None, None]:
    port_q: queue.SimpleQueue[int] = queue.SimpleQueue()
    stop = threading.Event()

    t = threading.Thread(
        target=run_server,
        kwargs={
            "port": 0,
            "poll_interval": 0.1,
            "api_key": "secret",
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
            # Return None immediately so the very first poll marks the job finished.
            patch("pbspy.server.server.core.pbs_get_states", return_value={"done.mock": None}),
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


def test_wait_receives_status_update_then_done(server: ServerHandle, mock_get_states: MagicMock) -> None:
    """
    Submit a job, start waiting, then let the poll loop (0.1s interval) detect
    the job as finished and push WaitDoneResponse back to the client.
    """
    server.rpc(proto.SubmitRequest(script="#!/bin/bash", name="test_job"))

    job = Job(job_id="100.mock", job_name="test_job")
    stream = server.connect(timeout=5.0)
    proto.send_frame(stream, proto.WaitRequest(jobs=[job]))

    # Allow the poll loop to mark the job as finished.
    mock_get_states.state["value"] = None

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
# Auth tests
# ---------------------------------------------------------------------------


def test_auth_required_with_api_key(server_with_key: ServerHandle) -> None:
    """Connecting without sending AuthRequest first should fail."""
    stream = server_with_key.connect()
    # Send a PingRequest directly (no auth)
    proto.send_frame(stream, proto.PingRequest())
    response = proto.recv_frame(stream)
    stream.close()
    assert isinstance(response, proto.ErrorResponse)
    assert "Authentication failed" in response.message


def test_auth_wrong_key(server_with_key: ServerHandle) -> None:
    """Sending the wrong API key should fail."""
    stream = server_with_key.connect()
    proto.send_frame(stream, proto.AuthRequest(api_key="wrong"))
    response = proto.recv_frame(stream)
    stream.close()
    assert isinstance(response, proto.ErrorResponse)
    assert "Authentication failed" in response.message


def test_auth_correct_key(server_with_key: ServerHandle) -> None:
    """Correct API key followed by a ping should work."""
    stream = server_with_key.connect()
    proto.send_frame(stream, proto.AuthRequest(api_key="secret"))
    auth_resp = proto.recv_frame(stream)
    assert isinstance(auth_resp, proto.AuthOkResponse)

    proto.send_frame(stream, proto.PingRequest())
    pong = proto.recv_frame(stream)
    stream.close()
    assert isinstance(pong, proto.PongResponse)


def test_server_backend_auth_end_to_end(server_with_key: ServerHandle) -> None:
    """ServerBackend with the correct api_key should connect and submit successfully."""
    from pbspy._server_backend import ServerBackend

    backend = ServerBackend(server_with_key.host, server_with_key.port, api_key="secret")
    job_id, job_name = backend.submit("#!/bin/bash\necho hi", name="test_job")
    backend.close()
    assert job_id == "100.mock"
    assert job_name == "test_job"


def test_server_backend_auth_wrong_key(server_with_key: ServerHandle) -> None:
    """ServerBackend with a wrong api_key should raise RuntimeError on connect."""
    from pbspy._server_backend import ServerBackend

    with pytest.raises(RuntimeError, match="auth failed"):
        ServerBackend(server_with_key.host, server_with_key.port, api_key="wrong")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_returns_delete_response(server: ServerHandle) -> None:
    """DeleteRequest should call core.pbs_delete once and return DeleteResponse."""
    with patch("pbspy.server.server.core.pbs_delete") as mock_delete:
        response = server.rpc(proto.DeleteRequest(job_ids=["100.mock", "101.mock"]))
    assert isinstance(response, proto.DeleteResponse)
    mock_delete.assert_called_once()
    args, kwargs = mock_delete.call_args
    assert args[0] == ["100.mock", "101.mock"]


def test_delete_propagates_errors(server: ServerHandle) -> None:
    """If core.pbs_delete raises, the server should send back an ErrorResponse."""
    with patch("pbspy.server.server.core.pbs_delete", side_effect=RuntimeError("boom")):
        response = server.rpc(proto.DeleteRequest(job_ids=["100.mock"]))
    assert isinstance(response, proto.ErrorResponse)
    assert "boom" in response.message


def test_server_backend_delete_end_to_end(server: ServerHandle) -> None:
    """ServerBackend.delete() sends one DeleteRequest and returns without error."""
    from pbspy._server_backend import ServerBackend

    with patch("pbspy.server.server.core.pbs_delete") as mock_delete:
        backend = ServerBackend(server.host, server.port)
        backend.delete(["100.mock"])
        backend.close()
    mock_delete.assert_called_once()
