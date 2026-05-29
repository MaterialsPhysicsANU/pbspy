"""
pbspy-server daemon.

Listens on a TCP socket (hostname:random-port), writes the address to
``~/.pbspy/server.addr`` so that any login node can find and connect to it,
accepts one connection per client, and dispatches pickled requests from
:mod:`pbspy._protocol`.

A background thread polls ``qstat`` every 60 seconds for all unfinished jobs
and pushes :class:`StatusUpdateResponse` frames to any clients waiting on
those jobs.  Job state is held in memory for the daemon's lifetime; it is not
persisted across restarts.
"""

from __future__ import annotations

import json
import logging
import secrets
import signal
import socket
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

import pbspy._pbs_core as core
import pbspy._protocol as proto
from pbspy import Job, JobResult

__all__ = ["run_server"]

logger = logging.getLogger(__name__)

_ADDR_PATH = Path.home() / ".pbspy" / "server.addr"
_POLL_INTERVAL = 60.0  # seconds between qstat polls


@dataclass
class _JobRecord:
    """In-memory record of a submitted job's current state."""

    job_id: str
    job_name: str | None = None
    state: str | None = None  # "Q", "R", "E", "F"
    exit_code: int | None = None


class _WaitSubscription:
    """Tracks a client waiting for a set of jobs to finish."""

    def __init__(self, jobs: list[Job], stream: BinaryIO) -> None:
        self.pending: set[str] = {j.job_id for j in jobs}
        self.jobs_by_id: dict[str, Job] = {j.job_id: j for j in jobs}
        self.stream = stream
        self.lock = threading.Lock()
        self.done = threading.Event()


class _ServerState:
    """Shared mutable state accessed by both connection threads and the poll thread."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.lock = threading.Lock()
        self.active_connections: int = 0
        self._ever_had_connection: bool = False
        self.jobs: dict[str, _JobRecord] = {}
        self.subscriptions: dict[str, list[_WaitSubscription]] = {}

    def add_subscription(self, sub: _WaitSubscription) -> None:
        with self.lock:
            for job_id in sub.pending:
                self.subscriptions.setdefault(job_id, []).append(sub)

    def notify_finished(self, job_id: str, job: Job) -> None:
        """Mark job_id as done in all waiting subscriptions, sending frames as needed."""
        with self.lock:
            subs = self.subscriptions.pop(job_id, [])
        for sub in subs:
            with sub.lock:
                try:
                    proto.send_frame(sub.stream, proto.StatusUpdateResponse(job=job, state=None))
                except OSError:
                    pass
                sub.pending.discard(job_id)
                if not sub.pending:
                    try:
                        proto.send_frame(sub.stream, proto.WaitDoneResponse(jobs=list(sub.jobs_by_id.values())))
                    except OSError:
                        pass
                    sub.done.set()


def _cancel_all_subscriptions(state: _ServerState) -> None:
    """Signal all waiting subscriptions to unblock their connection threads (for shutdown)."""
    with state.lock:
        subs_by_id = dict(state.subscriptions)
        state.subscriptions.clear()
    seen: set[int] = set()
    for subs in subs_by_id.values():
        for sub in subs:
            if id(sub) not in seen:
                seen.add(id(sub))
                sub.done.set()


def _should_shutdown(state: _ServerState) -> bool:
    """Return True when the daemon has nothing left to do and can exit."""
    with state.lock:
        if not state._ever_had_connection:
            return False
        if state.active_connections > 0:
            return False
        return not any(r.state != "F" for r in state.jobs.values())


def _poll_loop(state: _ServerState, stop_event: threading.Event, poll_interval: float = _POLL_INTERVAL) -> None:
    """Background thread: polls qstat for all unfinished jobs."""
    while not stop_event.wait(timeout=poll_interval):
        try:
            with state.lock:
                unfinished = [r for r in state.jobs.values() if r.state != "F"]
            for record in unfinished:
                job = Job(job_id=record.job_id, job_name=record.job_name)
                result = _check_job_finished(record.job_id)
                if result is not None:
                    with state.lock:
                        record.state = "F"
                        record.exit_code = result
                    state.notify_finished(record.job_id, job)
            if _should_shutdown(state):
                logger.info("No active connections and no unfinished jobs; shutting down")
                stop_event.set()
        except Exception:
            logger.exception("Error in poll loop")


def _check_job_finished(job_id: str) -> int | None:
    """Return exit code if job has finished, else None."""
    process = subprocess.run(["qstat", job_id], capture_output=True)
    if process.returncode != 0:
        stdout = process.stdout.decode("utf-8")
        if job_id not in stdout or "has finished" in process.stderr.decode("utf-8"):
            return core.try_get_exit_code(job_id) or 0
    return None


def _handle_connection(conn: socket.socket, state: _ServerState, stop_event: threading.Event) -> None:
    """Handle a single client connection in its own thread."""
    with state.lock:
        state.active_connections += 1
        state._ever_had_connection = True
    stream = cast(BinaryIO, conn.makefile("rwb", buffering=0))
    try:
        # First frame must be a valid AuthRequest.
        try:
            auth = proto.recv_frame(stream)
        except EOFError:
            return
        if not isinstance(auth, proto.AuthRequest) or auth.token != state.token:
            logger.warning("Connection rejected: invalid or missing auth token")
            try:
                proto.send_frame(stream, proto.ErrorResponse(message="Authentication failed"))
            except OSError:
                pass
            return
        proto.send_frame(stream, proto.AuthOkResponse())

        while True:
            try:
                request = proto.recv_frame(stream)
            except EOFError:
                break
            except Exception:
                logger.exception("Error receiving frame")
                break

            try:
                if isinstance(request, proto.PingRequest):
                    proto.send_frame(stream, proto.PongResponse())

                elif isinstance(request, proto.SubmitRequest):
                    job_id, job_name = core.pbs_submit(request.script, request.name)
                    job = Job(job_id=job_id, job_name=job_name)
                    with state.lock:
                        state.jobs[job_id] = _JobRecord(job_id=job_id, job_name=job_name, state="Q")
                    proto.send_frame(stream, proto.SubmittedResponse(job=job))

                elif isinstance(request, proto.WaitRequest):
                    sub = _WaitSubscription(request.jobs, stream)
                    # Check state and register subscription atomically so notify_finished()
                    # cannot fire between the two steps and leave us waiting on a job
                    # that is already done.
                    with state.lock:
                        for job in request.jobs:
                            record = state.jobs.get(job.job_id)
                            if record and record.state == "F":
                                sub.pending.discard(job.job_id)
                        if sub.pending:
                            for job_id in sub.pending:
                                state.subscriptions.setdefault(job_id, []).append(sub)
                    if sub.pending:
                        sub.done.wait()
                    else:
                        proto.send_frame(stream, proto.WaitDoneResponse(jobs=request.jobs))

                elif isinstance(request, proto.ResultRequest):
                    result: JobResult = core.pbs_get_result(request.job)
                    proto.send_frame(stream, proto.ResultResponse(job=request.job, result=result))

                else:
                    proto.send_frame(stream, proto.ErrorResponse(message=f"Unknown request type: {type(request)}"))

            except Exception as exc:
                logger.exception("Error handling request")
                try:
                    proto.send_frame(stream, proto.ErrorResponse(message=str(exc)))
                except OSError:
                    pass
    finally:
        stream.close()
        conn.close()
        with state.lock:
            state.active_connections -= 1
        if _should_shutdown(state):
            logger.info("Last client disconnected with no unfinished jobs; shutting down")
            stop_event.set()


def run_server(
    addr_path: Path = _ADDR_PATH,
    poll_interval: float = _POLL_INTERVAL,
) -> None:
    """
    Start the pbspy-server daemon.

    Runs in the foreground; the caller is responsible for daemonising the
    process (e.g. ``--daemon`` in :mod:`pbspy_server.__main__` forks and
    calls this in the child).

    The server binds a TCP port on ``0.0.0.0`` (OS chooses a free port) and
    writes a JSON address file to *addr_path* containing the hostname, port,
    and a random auth token.  Clients must send the token as the first frame
    on every connection; connections with an incorrect or missing token are
    rejected immediately.

    Job state is held in memory for the daemon's lifetime and is not
    persisted across restarts.

    Args:
        addr_path: Path for the address file (JSON). Defaults to
            ``~/.pbspy/server.addr``.
        poll_interval: Seconds between qstat polls (default 60). Override in tests.
    """
    addr_path.parent.mkdir(parents=True, exist_ok=True)
    if addr_path.exists():
        addr_path.unlink()

    token = secrets.token_hex(32)
    state = _ServerState(token=token)

    stop_event = threading.Event()
    poll_thread = threading.Thread(
        target=_poll_loop, args=(state, stop_event), kwargs={"poll_interval": poll_interval}, daemon=True
    )
    poll_thread.start()

    # Signal handlers can only be registered from the main thread.
    if threading.current_thread() is threading.main_thread():

        def _handle_signal(signum: int, frame: object) -> None:
            logger.info("Received signal %d, shutting down", signum)
            stop_event.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", 0))
    srv.listen(16)
    srv.settimeout(1.0)

    hostname = socket.gethostname()
    port = srv.getsockname()[1]
    addr_path.write_text(json.dumps({"host": hostname, "port": port, "token": token}))

    logger.info("pbspy-server listening on %s:%d", hostname, port)

    try:
        while not stop_event.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            t = threading.Thread(target=_handle_connection, args=(conn, state, stop_event), daemon=True)
            t.start()
    finally:
        srv.close()
        if addr_path.exists():
            addr_path.unlink()
        _cancel_all_subscriptions(state)
        logger.info("pbspy-server stopped")
