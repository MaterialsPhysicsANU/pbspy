"""
StreamBackend: shared RPC logic for backends that talk the pbspy wire protocol
over some duplex byte stream.

:class:`~pbspy._server_backend.ServerBackend` connects over a plain TCP socket. A future
backend that talks directly to a Server over an SSH subprocess's stdin/stdout pipes (the
way the pre-0.0.10 ``SSHBackend`` did) would reuse this same RPC machinery — only how the
stream is opened differs between transports.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO

import pbspy._protocol as proto
from pbspy._backend import Backend

if TYPE_CHECKING:
    from pbspy import Job

__all__ = ["StreamBackend"]


class StreamBackend(Backend):
    """
    Backend that exchanges length-prefixed pickle frames over a duplex byte stream.

    Subclasses implement :meth:`_open_stream` (and optionally :meth:`_close_stream`) to
    provide the transport; everything else (auth handshake, ping, submit/wait/result RPCs,
    reconnect-on-failure) is shared.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._stream: BinaryIO | None = None
        self._lock = threading.Lock()
        self._connect()

    def _open_stream(self) -> BinaryIO:
        """Open the transport and return a readable+writable stream. Implemented by subclasses."""
        raise NotImplementedError

    def _close_stream(self) -> None:
        """Release any transport resources beyond the stream itself. Implemented by subclasses."""

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

    def exec(self, command: list[str], stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
        """
        Execute an arbitrary command on the server via SSH.

        Requires the server to be started with ``--allow-exec``.

        Args:
            command: Command and arguments to execute.
            stdin: Optional data to pass as standard input.

        Returns:
            A tuple of ``(returncode, stdout, stderr)``.

        Raises:
            RuntimeError: If the server rejects the request.
        """
        response = self._rpc(proto.ExecRequest(command=command, stdin=stdin))
        if isinstance(response, proto.ErrorResponse):
            raise RuntimeError(f"Server error: {response.message}")
        if not isinstance(response, proto.ExecResponse):
            raise RuntimeError(f"Unexpected response: {response!r}")
        return response.returncode, response.stdout, response.stderr

    def _connect(self) -> None:
        """Open the transport, authenticate if required, and verify liveness with a ping."""
        stream = self._open_stream()
        try:
            if self._api_key is not None:
                proto.send_frame(stream, proto.AuthRequest(api_key=self._api_key))
                auth_resp = proto.recv_frame(stream)
                if isinstance(auth_resp, proto.ErrorResponse):
                    raise RuntimeError(f"pbspy-server auth failed: {auth_resp.message}")
                if not isinstance(auth_resp, proto.AuthOkResponse):
                    raise RuntimeError(f"pbspy-server returned unexpected auth response: {auth_resp!r}")

            proto.send_frame(stream, proto.PingRequest())
            pong = proto.recv_frame(stream)
            if not isinstance(pong, proto.PongResponse):
                raise RuntimeError(f"pbspy-server returned unexpected response to ping: {pong!r}")
        except (OSError, EOFError) as exc:
            try:
                stream.close()
            except OSError:
                pass
            self._close_stream()
            raise RuntimeError(f"pbspy-server did not respond to ping: {exc}") from exc
        except RuntimeError:
            try:
                stream.close()
            except OSError:
                pass
            self._close_stream()
            raise
        self._stream = stream

    def _reconnect(self) -> None:
        """Close the current connection and establish a fresh one."""
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        self._close_stream()
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
        self._close_stream()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
