"""
ProxyServer: relays pbspy client connections to a Server running elsewhere via SSH.

For each accepted client connection, opens an ``ssh -W localhost:<remote-port> <ssh_host>``
subprocess and splices raw bytes bidirectionally between the client socket and the
subprocess's stdin/stdout. The pbspy wire protocol (see :mod:`pbspy._protocol`) is never
parsed here -- frames pass through untouched and are handled by the real Server, so any
client that works against a Server works identically against a ProxyServer.
"""

from __future__ import annotations

import logging
import os
import select
import signal
import socket
import subprocess
import threading
from collections.abc import Callable

__all__ = ["run_proxy_server"]

logger = logging.getLogger(__name__)

_BUF_SIZE = 65536


def _splice(client: socket.socket, proc: subprocess.Popen[bytes]) -> None:
    """Bidirectionally copy bytes between *client* and *proc*'s stdin/stdout until either closes."""
    assert proc.stdin is not None
    assert proc.stdout is not None
    client_fd = client.fileno()
    stdin_fd = proc.stdin.fileno()
    stdout_fd = proc.stdout.fileno()
    try:
        while True:
            readable, _, exceptional = select.select([client_fd, stdout_fd], [], [client_fd, stdout_fd], 1.0)
            if exceptional or proc.poll() is not None:
                return
            for fd in readable:
                if fd == client_fd:
                    data = client.recv(_BUF_SIZE)
                    if not data:
                        return
                    os.write(stdin_fd, data)
                elif fd == stdout_fd:
                    data = os.read(stdout_fd, _BUF_SIZE)
                    if not data:
                        return
                    client.sendall(data)
    except OSError:
        return


def _handle_connection(conn: socket.socket, ssh_command: list[str]) -> None:
    proc = subprocess.Popen(  # noqa: S603
        ssh_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stderr_chunks: list[bytes] = []
    stderr_pipe = proc.stderr
    assert stderr_pipe is not None

    def _drain_stderr() -> None:
        for chunk in iter(lambda: stderr_pipe.read(4096), b""):
            stderr_chunks.append(chunk)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()
    try:
        _splice(conn, proc)
    finally:
        conn.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        stderr_thread.join(timeout=1.0)
        stderr = b"".join(stderr_chunks)
        if stderr:
            logger.warning("ssh subprocess stderr: %s", stderr.decode(errors="replace").strip())
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()


def run_proxy_server(
    ssh_host: str,
    host: str = "0.0.0.0",
    port: int = 9876,
    remote_port: int = 9876,
    ssh_args: list[str] | None = None,
    _stop_event: threading.Event | None = None,
    _ready_callback: Callable[[int], None] | None = None,
    _ssh_command: list[str] | None = None,
) -> None:
    """
    Start the pbspy ProxyServer.

    Listens on *host*:*port* and, for each client connection, relays bytes to a Server
    reachable at *remote_port* on *ssh_host* via ``ssh -W``. The pbspy wire protocol is never
    inspected -- this is a pure byte relay, so clients connecting to a ProxyServer behave
    identically to clients connecting directly to a Server.

    Args:
        ssh_host: SSH destination of the remote Server (e.g. a persistent-session host
            alias). Combine with *ssh_args* (e.g. ``-J``/``ProxyJump``) if it isn't directly
            reachable from this machine's default SSH configuration.
        host: Local address to bind (default ``"0.0.0.0"``).
        port: TCP port to listen on (default 9876; pass 0 for OS-assigned).
        remote_port: Port the remote Server is listening on (default 9876).
        ssh_args: Extra arguments forwarded to the ``ssh`` command.
    """
    ssh_command = _ssh_command or ["ssh", *(ssh_args or []), "-W", f"localhost:{remote_port}", ssh_host]

    stop_event = _stop_event or threading.Event()

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
    logger.info("pbspy ProxyServer listening on %s:%d, relaying to %s:%d", host, actual_port, ssh_host, remote_port)

    if _ready_callback is not None:
        _ready_callback(actual_port)

    try:
        while not stop_event.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            t = threading.Thread(target=_handle_connection, args=(conn, ssh_command), daemon=True)
            t.start()
    finally:
        srv.close()
        logger.info("pbspy ProxyServer stopped")
