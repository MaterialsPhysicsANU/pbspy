"""
ServerBackend: communicates with a pbspy-server daemon over a plain TCP connection.

Messages are exchanged as length-prefixed pickle frames (see :mod:`pbspy._protocol`).
The server handles all SSH communication to the supercomputer internally.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO, cast

import pbspy._protocol as proto
from pbspy._backend import Backend

if TYPE_CHECKING:
    from pbspy import Job

__all__ = ["ServerBackend"]


class ServerBackend(Backend):
    """
    Backend that connects to a pbspy-server daemon over TCP.

    The server (started with ``pbspy-server``) runs on any machine with SSH
    access to the supercomputer; this client connects to it directly.

    Args:
        host: Hostname or IP address of the machine running pbspy-server.
        port: TCP port the server is listening on (default: 9876).
        connect_timeout: Seconds to wait for the initial TCP connection.
    """

    def __init__(
        self,
        host: str,
        port: int = 9876,
        connect_timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._stream: BinaryIO | None = None
        self._lock = threading.Lock()
        self._connect()

    def submit(self, script: str, name: str | None = None) -> tuple[str, str]:
        response = self._rpc(proto.SubmitRequest(script=script, name=name))
        if isinstance(response, proto.ErrorResponse):
            raise RuntimeError(f"Server error: {response.message}")
        if not isinstance(response, proto.SubmittedResponse):
            raise RuntimeError(f"Unexpected response: {response!r}")
        return response.job.job_id, response.job.job_name or ""

    def wait(
        self,
        jobs: list[Job],
        on_update: Callable[[str, str | None], None] | None = None,
        progress: bool = True,
    ) -> None:
        if progress:
            self._wait_with_progress(jobs, on_update)
        else:
            self._wait_quiet(jobs, on_update)

    def get_result(self, job: object) -> object:
        response = self._rpc(proto.ResultRequest(job=job))  # type: ignore[arg-type]
        if isinstance(response, proto.ErrorResponse):
            raise RuntimeError(f"Server error: {response.message}")
        if not isinstance(response, proto.ResultResponse):
            raise RuntimeError(f"Unexpected response: {response!r}")
        return response.result

    def _connect(self) -> None:
        """Open a TCP connection to the server and verify liveness with a ping."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._connect_timeout)
        try:
            sock.connect((self._host, self._port))
        except OSError as exc:
            sock.close()
            raise RuntimeError(f"Could not connect to pbspy-server at {self._host}:{self._port}: {exc}") from exc
        sock.settimeout(None)
        self._sock = sock
        self._stream = cast(BinaryIO, sock.makefile("rwb", buffering=0))

        try:
            proto.send_frame(self._stream, proto.PingRequest())
            pong = proto.recv_frame(self._stream)
        except (OSError, EOFError) as exc:
            self._stream.close()
            sock.close()
            raise RuntimeError(f"pbspy-server at {self._host}:{self._port} did not respond to ping: {exc}") from exc
        if not isinstance(pong, proto.PongResponse):
            self._stream.close()
            sock.close()
            raise RuntimeError(f"pbspy-server returned unexpected response to ping: {pong!r}")

    def _reconnect(self) -> None:
        """Close the current connection and establish a fresh one."""
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._connect()

    def _rpc(self, request: object) -> object:
        """Send one request frame and return the first response frame."""
        with self._lock:
            try:
                assert self._stream is not None
                proto.send_frame(self._stream, request)
                return proto.recv_frame(self._stream)
            except (OSError, EOFError):
                self._reconnect()
                assert self._stream is not None
                proto.send_frame(self._stream, request)
                return proto.recv_frame(self._stream)

    def _send(self, request: object) -> None:
        with self._lock:
            assert self._stream is not None
            proto.send_frame(self._stream, request)

    def _recv(self) -> object:
        assert self._stream is not None
        return proto.recv_frame(self._stream)

    def _wait_quiet(
        self,
        jobs: list[Job],
        on_update: Callable[[str, str | None], None] | None,
    ) -> None:
        self._send(proto.WaitRequest(jobs=jobs))
        while True:
            response = self._recv()
            if isinstance(response, proto.StatusUpdateResponse):
                if on_update:
                    on_update(response.job.job_id, response.state)
            elif isinstance(response, proto.WaitDoneResponse):
                return
            elif isinstance(response, proto.ErrorResponse):
                raise RuntimeError(f"Server error while waiting: {response.message}")

    def _wait_with_progress(
        self,
        jobs: list[Job],
        on_update: Callable[[str, str | None], None] | None,
    ) -> None:
        from rich.progress import Progress, TextColumn, TimeElapsedColumn

        self._send(proto.WaitRequest(jobs=jobs))

        with Progress(
            TimeElapsedColumn(),
            TextColumn("[progress.description]{task.description}"),
            auto_refresh=False,
        ) as progress_bar:
            tasks = {
                job.job_id: progress_bar.add_task(
                    f"{job.job_id} {job.job_name or ''} {job.description or ''}",
                    total=1,
                )
                for job in jobs
            }

            while True:
                response = self._recv()
                progress_bar.refresh()

                if isinstance(response, proto.StatusUpdateResponse):
                    job = response.job
                    if response.state is None:
                        task = tasks.get(job.job_id)
                        if task is not None:
                            progress_bar.advance(task)
                            progress_bar.update(task, visible=False)
                        if on_update:
                            on_update(job.job_id, None)
                    elif on_update:
                        on_update(job.job_id, response.state)

                elif isinstance(response, proto.WaitDoneResponse):
                    return

                elif isinstance(response, proto.ErrorResponse):
                    raise RuntimeError(f"Server error while waiting: {response.message}")

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
