"""
pbspy-server command-line entry point.

Usage::

    pbspy-server [--ssh-host HOST] [--ssh-user USER] [--port PORT] [--ssh-arg ARG ...]
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

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from pbspy.server import run_server

    run_server(
        port=args.port,
        ssh_host=args.ssh_host,
        ssh_user=args.ssh_user,
        ssh_args=args.ssh_args,
    )


if __name__ == "__main__":
    main()
