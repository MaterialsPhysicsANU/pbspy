"""
pbspy-server command-line entry point.

Usage::

    pbspy-server --daemon    # start server daemon in the foreground
    pbspy-server --proxy     # SSH proxy mode (stdio ↔ socket splice)
    pbspy-server --status    # print server status and exit
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
from pathlib import Path
from typing import BinaryIO, cast

_ADDR_PATH = Path.home() / ".pbspy" / "server.addr"


def _cmd_daemon() -> None:
    from pbspy_server.server import run_server

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_server()


def _cmd_proxy() -> None:
    from pbspy_server.proxy import run_proxy

    run_proxy()


def _cmd_status() -> None:
    if not _ADDR_PATH.exists():
        print("pbspy-server: not running (address file not found)")
        sys.exit(1)

    try:
        import json

        data = json.loads(_ADDR_PATH.read_text())
        host = data["host"]
        port = int(data["port"])
        token = data["token"]
    except (ValueError, KeyError, OSError) as exc:
        print(f"pbspy-server: malformed address file ({exc})")
        sys.exit(1)

    try:
        import pbspy._protocol as proto

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect((host, port))
        f = cast(BinaryIO, sock.makefile("rwb", buffering=0))
        sock.close()
        proto.send_frame(f, proto.AuthRequest(token=token))
        auth_resp = proto.recv_frame(f)
        if not isinstance(auth_resp, proto.AuthOkResponse):
            print(f"pbspy-server: auth failed: {auth_resp!r}")
            f.close()
            sys.exit(1)
        proto.send_frame(f, proto.PingRequest())
        response = proto.recv_frame(f)
        f.close()
        if isinstance(response, proto.PongResponse):
            print(f"pbspy-server: running on {host}:{port}")
        else:
            print(f"pbspy-server: unexpected response: {response!r}")
            sys.exit(1)
    except OSError as exc:
        print(f"pbspy-server: not responding ({exc})")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pbspy-server",
        description="PBS job scheduler server daemon for pbspy.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--daemon", action="store_true", help="Start the server daemon (runs in foreground)")
    group.add_argument("--proxy", action="store_true", help="SSH proxy mode: splice stdin/stdout with server socket")
    group.add_argument("--status", action="store_true", help="Print server status and exit")

    args = parser.parse_args()

    if args.daemon:
        _cmd_daemon()
    elif args.proxy:
        _cmd_proxy()
    elif args.status:
        _cmd_status()


if __name__ == "__main__":
    main()
