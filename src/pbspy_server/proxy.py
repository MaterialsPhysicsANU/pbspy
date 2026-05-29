"""
SSH proxy mode for pbspy-server.

When invoked as ``pbspy-server --proxy`` over an SSH connection, this module:

1. Acquires an exclusive file lock (``~/.pbspy/server.lock``) to prevent two
   proxy processes on different login nodes from racing to start the daemon.
2. Checks whether the server daemon is already running by reading
   ``~/.pbspy/server.addr`` and attempting an authenticated TCP connection.
3. If the daemon is not running, starts it in the background and waits for the
   address file to appear.
4. Splices ``sys.stdin`` / ``sys.stdout`` bytes bidirectionally with the server
   TCP socket so the remote client can talk to the daemon transparently.

Because the address file lives on the shared home filesystem, this works
correctly regardless of which login node the SSH session lands on — the daemon
may be running on a completely different node.
"""

from __future__ import annotations

import fcntl
import json
import os
import select
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import BinaryIO, cast

import pbspy._protocol as proto

__all__ = ["run_proxy"]

_ADDR_PATH = Path.home() / ".pbspy" / "server.addr"
_LOCK_PATH = Path.home() / ".pbspy" / "server.lock"
_STARTUP_TIMEOUT = 10.0  # seconds to wait for daemon to start
_POLL_INTERVAL = 0.1
_BUF_SIZE = 65536


def _read_server_addr() -> tuple[str, int, str] | None:
    """Return ``(hostname, port, token)`` from the JSON addr file, or ``None`` if absent/invalid."""
    if not _ADDR_PATH.exists():
        return None
    try:
        data = json.loads(_ADDR_PATH.read_text())
        return data["host"], int(data["port"]), data["token"]
    except (ValueError, KeyError, OSError):
        return None


def _daemon_alive() -> bool:
    """Return True if the addr file exists and the daemon responds to an auth+ping."""
    addr = _read_server_addr()
    if addr is None:
        return False
    host, port, token = addr
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((host, port))
        f = cast(BinaryIO, sock.makefile("rwb", buffering=0))
        sock.close()
        proto.send_frame(f, proto.AuthRequest(token=token))
        resp = proto.recv_frame(f)
        if not isinstance(resp, proto.AuthOkResponse):
            f.close()
            return False
        proto.send_frame(f, proto.PingRequest())
        resp2 = proto.recv_frame(f)
        f.close()
        return isinstance(resp2, proto.PongResponse)
    except OSError:
        # Stale addr file — remove it so the next caller starts a fresh daemon.
        try:
            _ADDR_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _start_daemon() -> None:
    """Fork the server daemon in the background."""
    subprocess.Popen(
        [sys.executable, "-m", "pbspy_server", "--daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wait_for_daemon(timeout: float = _STARTUP_TIMEOUT) -> None:
    """Block until the daemon is alive or *timeout* seconds have elapsed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _daemon_alive():
            return
        time.sleep(_POLL_INTERVAL)
    raise TimeoutError(f"pbspy-server daemon did not start within {timeout:.0f}s")


def run_proxy() -> None:
    """
    Entry point for ``--proxy`` mode.

    Ensures the daemon is running (starting it if necessary), then authenticates
    and splices stdin/stdout with the server TCP socket until one side closes.
    """
    _ADDR_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Acquire exclusive lock while checking / starting the daemon to prevent
    # two proxy processes on different login nodes from both deciding to start it.
    lock_file = open(_LOCK_PATH, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if not _daemon_alive():
            _start_daemon()
            _wait_for_daemon()
        addr = _read_server_addr()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()

    if addr is None:
        raise RuntimeError("pbspy-server daemon started but address file not found")

    host, port, token = addr
    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.connect((host, port))

    # Authenticate with the daemon before entering the byte-splice loop.
    srv_file = cast(BinaryIO, srv_sock.makefile("rwb", buffering=0))
    proto.send_frame(srv_file, proto.AuthRequest(token=token))
    auth_resp = proto.recv_frame(srv_file)
    srv_file.close()  # File object done; raw socket takes over below
    if not isinstance(auth_resp, proto.AuthOkResponse):
        srv_sock.close()
        raise RuntimeError(f"pbspy-server rejected auth token: {auth_resp!r}")

    stdin_fd = sys.stdin.buffer.fileno()
    srv_fd = srv_sock.fileno()

    # Put stdin in non-blocking mode; stdout remains blocking so writes
    # don't need special partial-write handling.
    _set_nonblocking(stdin_fd)

    try:
        while True:
            readable, _, exceptional = select.select([stdin_fd, srv_fd], [], [stdin_fd, srv_fd], 1.0)
            if exceptional:
                break
            for fd in readable:
                if fd == stdin_fd:
                    data = os.read(stdin_fd, _BUF_SIZE)
                    if not data:
                        return
                    srv_sock.sendall(data)
                elif fd == srv_fd:
                    data = srv_sock.recv(_BUF_SIZE)
                    if not data:
                        return
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
    finally:
        srv_sock.close()


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
