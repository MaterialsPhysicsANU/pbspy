"""
pbspy-server command-line entry point.

Usage::

    pbspy-server [--host HOST] [--port PORT] [--api-key KEY]
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
        "--host",
        default="127.0.0.1",
        metavar="HOST",
        help="Local address to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9876,
        metavar="PORT",
        help="TCP port to listen on (default: 9876).",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        default=os.environ.get("PBSPY_API_KEY"),
        help="Require clients to authenticate with this key (env: PBSPY_API_KEY).",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from pbspy.server import run_server

    run_server(
        host=args.host,
        port=args.port,
        api_key=args.api_key,
    )


if __name__ == "__main__":
    main()
