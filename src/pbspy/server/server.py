"""
pbspy-server daemon.

Listens on a configured TCP port, accepts connections from :class:`~pbspy.ServerBackend`
clients, and dispatches pickled requests from :mod:`pbspy._protocol`.

PBS operations (qsub, qstat, file reads) are executed via SSH to a remote
supercomputer when ``ssh_host`` is provided, or locally when omitted.

A background thread polls ``qstat`` every 60 seconds for all unfinished jobs
and pushes :class:`StatusUpdateResponse` frames to any clients waiting on
those jobs.  Job state is held in memory and is not persisted across restarts.
"""

from __future__ import annotations

import logging
import signal
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO, cast

import pbspy._pbs_core as core
import pbspy._protocol as proto
from pbspy import Job, JobResult

__all__ = ["run_server"]

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 60.0  # seconds between qstat polls


@dataclass
class _JobRecord:
    """In-memory record of a submitted job's current state."""

    job_id: str
    job_name: str | None = None
    finished: bool = False


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

    def __init__(self, runner: core.PBSRunner) -> None:
        self.runner = runner
        self.lock = threading.Lock()
        self.jobs: dict[str, _JobRecord] = {}
        self.subscriptions: dict[str, list[_WaitSubscription]] = {}

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


def _poll_loop(
    state: _ServerState,
    stop_event: threading.Event,
    poll_interval: float = _POLL_INTERVAL,
) -> None:
    """Background thread: polls qstat for all unfinished jobs."""
    while not stop_event.wait(timeout=poll_interval):
        try:
            with state.lock:
                unfinished = [r for r in state.jobs.values() if not r.finished]
            for record in unfinished:
                job = Job(job_id=record.job_id, job_name=record.job_name)
                if _check_job_finished(record.job_id, state.runner) is not None:
                    with state.lock:
                        record.finished = True
                    state.notify_finished(record.job_id, job)
        except Exception:
            logger.exception("Error in poll loop")


def _check_job_finished(job_id: str, runner: core.PBSRunner) -> int | None:
    """Return exit code if job has finished, else None."""
    process = runner.run(["qstat", job_id])
    if process.returncode != 0:
        stdout = process.stdout.decode("utf-8")
        if job_id not in stdout or "has finished" in process.stderr.decode("utf-8"):
            return core.try_get_exit_code(job_id, runner) or 0
    return None


def _handle_connection(conn: socket.socket, state: _ServerState) -> None:
    """Handle a single client connection in its own thread."""
    stream = cast(BinaryIO, conn.makefile("rwb", buffering=0))
    try:
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
                    job_id, job_name = core.pbs_submit(request.script, request.name, runner=state.runner)
                    job = Job(job_id=job_id, job_name=job_name)
                    with state.lock:
                        state.jobs[job_id] = _JobRecord(job_id=job_id, job_name=job_name)
                    proto.send_frame(stream, proto.SubmittedResponse(job=job))

                elif isinstance(request, proto.WaitRequest):
                    sub = _WaitSubscription(request.jobs, stream)
                    # Check state and register subscription atomically so notify_finished()
                    # cannot fire between the two steps and leave us waiting on a job
                    # that is already done.
                    with state.lock:
                        for job in request.jobs:
                            record = state.jobs.get(job.job_id)
                            if record and record.finished:
                                sub.pending.discard(job.job_id)
                        if sub.pending:
                            for job_id in sub.pending:
                                state.subscriptions.setdefault(job_id, []).append(sub)
                    if sub.pending:
                        sub.done.wait()
                    else:
                        proto.send_frame(stream, proto.WaitDoneResponse(jobs=request.jobs))

                elif isinstance(request, proto.ResultRequest):
                    result: JobResult = core.pbs_get_result(request.job, runner=state.runner)
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


def run_server(
    host: str = "0.0.0.0",
    port: int = 9876,
    ssh_host: str | None = None,
    ssh_user: str | None = None,
    ssh_args: list[str] | None = None,
    poll_interval: float = _POLL_INTERVAL,
    _stop_event: threading.Event | None = None,
    _ready_callback: Callable[[int], None] | None = None,
) -> None:
    """
    Start the pbspy-server daemon.

    Runs in the foreground; use your OS's service manager (systemd, nohup,
    etc.) to run it as a background service.

    When *ssh_host* is provided, all PBS operations (qsub, qstat, file reads)
    are executed on that host via SSH.  Otherwise they run locally.

    Args:
        host: Local address to bind (default ``"0.0.0.0"``).
        port: TCP port to listen on (default 9876; pass 0 for OS-assigned).
        ssh_host: Supercomputer hostname to SSH into for PBS commands.
        ssh_user: SSH username (combined with *ssh_host* as ``user@host``).
        ssh_args: Extra arguments forwarded to the ``ssh`` command.
        poll_interval: Seconds between qstat polls (default 60).
    """
    destination: str | None = None
    ssh_prefix: list[str] | None = None
    if ssh_host is not None:
        destination = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
        ssh_prefix = ["ssh", *(ssh_args or []), destination]

    runner = core.PBSRunner(ssh_prefix)
    state = _ServerState(runner=runner)

    stop_event = _stop_event or threading.Event()

    poll_thread = threading.Thread(
        target=_poll_loop, args=(state, stop_event), kwargs={"poll_interval": poll_interval}, daemon=True
    )
    poll_thread.start()

    if threading.current_thread() is threading.main_thread():

        def _handle_signal(signum: int, frame: object) -> None:
            logger.info("Received signal %d, shutting down", signum)
            stop_event.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(16)
    srv.settimeout(1.0)

    actual_port = srv.getsockname()[1]
    logger.info("pbspy-server listening on %s:%d", host, actual_port)
    if ssh_host:
        logger.info("PBS commands will run via SSH on %s", destination)

    if _ready_callback is not None:
        _ready_callback(actual_port)

    try:
        while not stop_event.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            t = threading.Thread(target=_handle_connection, args=(conn, state), daemon=True)
            t.start()
    finally:
        srv.close()
        _cancel_all_subscriptions(state)
        logger.info("pbspy-server stopped")
