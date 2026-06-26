"""
pbspy-server command-line entry point.

Usage::

    pbspy-server [--host HOST] [--port PORT] [--ssh-host HOST] [--ssh-user USER]
                 [--ssh-arg ARG ...] [--api-key KEY] [--allow-exec]

    pbspy-server --proxy-to HOST [--remote-port PORT] [--host HOST] [--port PORT]
                 [--ssh-arg ARG ...]
"""

from __future__ import annotations

import argparse
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pbspy-server",
        description="PBS job server daemon for pbspy.",
    )
    parser.add_argument(
        "--ssh-host",
        metavar="HOST",
        default=os.environ.get("PBSPY_SSH_HOST"),
        help="Supercomputer hostname to SSH into for PBS commands.",
    )
    parser.add_argument(
        "--ssh-user",
        metavar="USER",
        default=os.environ.get("PBSPY_SSH_USER"),
        help="SSH username on the supercomputer.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        metavar="HOST",
        help="Local address to bind (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9876,
        metavar="PORT",
        help="TCP port to listen on (default: 9876).",
    )
    parser.add_argument(
        "--ssh-arg",
        dest="ssh_args",
        action="append",
        metavar="ARG",
        help="Extra SSH argument (may be repeated, e.g. --ssh-arg=-i --ssh-arg=/path/to/key).",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        default=os.environ.get("PBSPY_API_KEY"),
        help="Require clients to authenticate with this key (env: PBSPY_API_KEY).",
    )
    parser.add_argument(
        "--allow-exec",
        action="store_true",
        default=os.environ.get("PBSPY_ALLOW_EXEC", "").lower() in ("1", "true", "yes"),
        help="Allow clients to execute arbitrary SSH commands (env: PBSPY_ALLOW_EXEC; disabled by default).",
    )
    parser.add_argument(
        "--proxy-to",
        metavar="HOST",
        default=os.environ.get("PBSPY_PROXY_TO"),
        help=(
            "Run as a ProxyServer instead of a Server: relay each client connection to a remote "
            "Server via `ssh -W localhost:<remote-port> HOST` (env: PBSPY_PROXY_TO)."
        ),
    )
    parser.add_argument(
        "--remote-port",
        type=int,
        default=int(os.environ.get("PBSPY_REMOTE_PORT", "9876")),
        metavar="PORT",
        help="Port the remote Server is listening on, used with --proxy-to (default: 9876).",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.proxy_to is not None:
        from pbspy.server import run_proxy_server

        run_proxy_server(
            ssh_host=args.proxy_to,
            host=args.host,
            port=args.port,
            remote_port=args.remote_port,
            ssh_args=args.ssh_args,
        )
    else:
        from pbspy.server import run_server

        run_server(
            host=args.host,
            port=args.port,
            ssh_host=args.ssh_host,
            ssh_user=args.ssh_user,
            ssh_args=args.ssh_args,
            api_key=args.api_key,
            allow_exec=args.allow_exec,
        )


if __name__ == "__main__":
    main()
