"""
ServerBackend: communicates with a pbspy-server daemon over a plain TCP connection.

Messages are exchanged as length-prefixed pickle frames (see :mod:`pbspy._protocol`).
The server handles all SSH communication to the supercomputer internally.
"""

from __future__ import annotations

import socket
from typing import BinaryIO, cast

from pbspy._stream_backend import StreamBackend

__all__ = ["ServerBackend"]


class ServerBackend(StreamBackend):
    """
    Backend that connects to a pbspy-server daemon over TCP.

    The server (started with ``pbspy-server``) runs on any machine with SSH access to the
    supercomputer; this client connects to it directly. It also works unmodified against a
    ProxyServer (``pbspy-server --proxy-to ...``), since the wire protocol is identical.

    Args:
        host: Hostname or IP address of the machine running pbspy-server.
        port: TCP port the server is listening on (default: 9876).
        connect_timeout: Seconds to wait for the initial TCP connection.
        api_key: API key for authentication (required if the server requires it).
    """

    def __init__(
        self,
        host: str,
        port: int = 9876,
        connect_timeout: float = 10.0,
        api_key: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        super().__init__(api_key=api_key)

    def _open_stream(self) -> BinaryIO:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._connect_timeout)
        try:
            sock.connect((self._host, self._port))
        except OSError as exc:
            sock.close()
            raise RuntimeError(f"Could not connect to pbspy-server at {self._host}:{self._port}: {exc}") from exc
        sock.settimeout(None)
        self._sock = sock
        return cast(BinaryIO, sock.makefile("rwb", buffering=0))

    def _close_stream(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
