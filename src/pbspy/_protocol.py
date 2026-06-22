"""
Request and response dataclasses for the pbspy client-server protocol.

Messages are exchanged as length-prefixed pickle frames (see :func:`send_frame`
and :func:`recv_frame`).  Connections optionally require authentication via an
API key (see :class:`AuthRequest`).  When enabled, the server sends an
:class:`AuthOkResponse` on success or an :class:`ErrorResponse` on failure
before accepting any other requests.
"""

from __future__ import annotations

import io
import pickle
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from pbspy import Job, JobResult

__all__ = [
    # Requests
    "AuthRequest",
    "SubmitRequest",
    "WaitRequest",
    "ResultRequest",
    "PingRequest",
    "ExecRequest",
    # Responses
    "AuthOkResponse",
    "SubmittedResponse",
    "StatusUpdateResponse",
    "WaitDoneResponse",
    "ResultResponse",
    "PongResponse",
    "ErrorResponse",
    "ExecResponse",
    # Framing
    "send_frame",
    "recv_frame",
]

_FRAME_HEADER = struct.Struct("!I")  # 4-byte big-endian unsigned int


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@dataclass
class SubmitRequest:
    """Ask the server to submit a PBS job script."""

    script: str
    name: str | None = None


@dataclass
class WaitRequest:
    """
    Ask the server to wait for *jobs* and stream :class:`StatusUpdateResponse`
    messages until all jobs finish, then send :class:`WaitDoneResponse`.
    """

    jobs: list[Job] = field(default_factory=list)


@dataclass
class ResultRequest:
    """Ask the server to return the result of a completed job."""

    job: Job


@dataclass
class AuthRequest:
    """Sent as the first frame on connection when the server requires API key auth."""

    api_key: str | None = None


@dataclass
class PingRequest:
    """Liveness check; server responds with :class:`PongResponse`."""


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


@dataclass
class SubmittedResponse:
    """Returned after a successful :class:`SubmitRequest`."""

    job: Job


@dataclass
class StatusUpdateResponse:
    """
    Streamed periodically during a :class:`WaitRequest`.

    *state* is one of ``"Q"`` (queued), ``"R"`` (running), ``"E"`` (exiting),
    ``"F"`` (finished), or ``None`` when the job has left the qstat queue.
    """

    job: Job
    state: str | None


@dataclass
class WaitDoneResponse:
    """Sent after all jobs in a :class:`WaitRequest` have finished."""

    jobs: list[Job] = field(default_factory=list)


@dataclass
class ResultResponse:
    """Returned after a successful :class:`ResultRequest`."""

    job: Job
    result: JobResult


@dataclass
class PongResponse:
    """Response to :class:`PingRequest`."""


@dataclass
class AuthOkResponse:
    """Sent after a successful :class:`AuthRequest`."""


@dataclass
class ExecRequest:
    """Ask the server to execute an arbitrary command via SSH."""

    command: list[str]
    stdin: bytes | None = None


@dataclass
class ErrorResponse:
    """Returned when the server encounters an error handling a request."""

    message: str


@dataclass
class ExecResponse:
    """Returned after a successful :class:`ExecRequest`."""

    returncode: int
    stdout: bytes
    stderr: bytes


# ---------------------------------------------------------------------------
# Framing helpers
# ---------------------------------------------------------------------------


def send_frame(stream: BinaryIO, obj: object) -> None:
    """
    Serialise *obj* with :mod:`pickle` and write it to *stream* as a
    length-prefixed frame.

    Frame layout: ``[4-byte big-endian length][pickle bytes]``
    """
    data = pickle.dumps(obj)
    stream.write(_FRAME_HEADER.pack(len(data)))
    stream.write(data)
    if hasattr(stream, "flush"):
        stream.flush()


def recv_frame(stream: BinaryIO) -> object:
    """
    Read one length-prefixed frame from *stream* and return the unpickled
    object.

    Raises :class:`EOFError` if the stream is closed before a complete frame
    is received.
    """
    header = _read_exactly(stream, _FRAME_HEADER.size)
    (length,) = _FRAME_HEADER.unpack(header)
    data = _read_exactly(stream, length)
    return pickle.loads(data)  # noqa: S301


def _read_exactly(stream: BinaryIO, n: int) -> bytes:
    buf = io.BytesIO()
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("Stream closed before a complete frame was received")
        buf.write(chunk)
        remaining -= len(chunk)
    return buf.getvalue()
