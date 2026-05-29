"""
SSHBackend: communicates with a remote pbspy-server daemon over SSH.

The backend opens an SSH subprocess running ``pbspy-server --proxy`` on the
remote host.  Messages are exchanged as length-prefixed pickle frames (see
:mod:`pbspy._protocol`).  The proxy on the remote end automatically starts the
daemon if it is not already running (emacsclient-style).
"""

from __future__ import annotations

import select
import subprocess
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO, cast

import pbspy._protocol as proto
from pbspy._backend import Backend

if TYPE_CHECKING:
    from pbspy import Job

__all__ = ["SSHBackend"]


class SSHBackend(Backend):
    """
    Backend that submits and tracks PBS jobs on a remote supercomputer via SSH.

    Args:
        host: SSH destination (e.g. ``"user@gadi.nci.org.au"``).
            Any option accepted by ``ssh`` (host aliases, ``-i``, etc.) works
            because the system ``ssh`` binary is used.
        ssh_args: Extra arguments forwarded to the ``ssh`` command (e.g.
            ``["-i", "/path/to/key"]``).
    """

    def __init__(self, host: str, ssh_args: list[str] | None = None) -> None:
        self._host = host
        self._ssh_args = ssh_args or []
        self._proc: subprocess.Popen[bytes] | None = None
        self._stdin: BinaryIO | None = None
        self._stdout: BinaryIO | None = None
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
        """
        Send a WaitRequest and stream StatusUpdateResponse frames until
        WaitDoneResponse is received.  Optionally shows a progress display.
        """

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
        """Start the SSH subprocess and verify the proxy is alive."""
        cmd = ["ssh", *self._ssh_args, self._host, "pbspy-server", "--proxy"]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._stdin = cast(BinaryIO, self._proc.stdin)
        self._stdout = cast(BinaryIO, self._proc.stdout)

        try:
            pong = self._rpc(proto.PingRequest())
        except (OSError, EOFError) as exc:
            stderr_text = self._read_stderr()
            raise RuntimeError(
                f"pbspy-server --proxy did not respond to ping on {self._host!r}: {exc}"
                + (f"\nSSH stderr: {stderr_text}" if stderr_text else "")
            ) from exc
        if not isinstance(pong, proto.PongResponse):
            stderr_text = self._read_stderr()
            raise RuntimeError(
                f"pbspy-server --proxy returned unexpected response: {pong!r}"
                + (f"\nSSH stderr: {stderr_text}" if stderr_text else "")
            )

    def _read_stderr(self) -> str:
        """Non-blocking read of any immediately available stderr from the SSH process."""
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            rlist, _, _ = select.select([self._proc.stderr], [], [], 0.0)
            if rlist:
                return self._proc.stderr.read(4096).decode(errors="replace")
        except OSError:
            pass
        return ""

    def _reconnect(self) -> None:
        """Terminate the current SSH subprocess and establish a fresh connection."""
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._proc = None
        self._connect()

    def _rpc(self, request: object) -> object:
        """Send one request frame and return the first response frame."""
        with self._lock:
            try:
                assert self._stdin is not None
                assert self._stdout is not None
                proto.send_frame(self._stdin, request)
                return proto.recv_frame(self._stdout)
            except (OSError, EOFError):
                # Connection lost — attempt one reconnect then retry.
                self._reconnect()
                assert self._stdin is not None
                assert self._stdout is not None
                proto.send_frame(self._stdin, request)
                return proto.recv_frame(self._stdout)

    def _send(self, request: object) -> None:
        with self._lock:
            assert self._stdin is not None
            proto.send_frame(self._stdin, request)

    def _recv(self) -> object:
        assert self._stdout is not None
        return proto.recv_frame(self._stdout)

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
        """Terminate the SSH subprocess."""
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
