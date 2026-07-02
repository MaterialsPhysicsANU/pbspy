"""Tests for the pickle framing helpers in pbspy._protocol."""

from __future__ import annotations

import io
import pickle

import pytest

import pbspy._protocol as proto
from pbspy import Job, JobResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def roundtrip(obj: object) -> object:
    """Serialise *obj* into a BytesIO buffer, then deserialise and return it."""
    buf = io.BytesIO()
    proto.send_frame(buf, obj)
    buf.seek(0)
    return proto.recv_frame(buf)


# ---------------------------------------------------------------------------
# Request types
# ---------------------------------------------------------------------------


def test_roundtrip_ping() -> None:
    result = roundtrip(proto.PingRequest())
    assert isinstance(result, proto.PingRequest)


def test_roundtrip_submit_request() -> None:
    req = proto.SubmitRequest(script="#!/bin/bash\necho hi", name="myjob")
    result = roundtrip(req)
    assert isinstance(result, proto.SubmitRequest)
    assert result.script == req.script
    assert result.name == req.name


def test_roundtrip_submit_request_no_name() -> None:
    req = proto.SubmitRequest(script="#!/bin/bash")
    result = roundtrip(req)
    assert isinstance(result, proto.SubmitRequest)
    assert result.name is None


def test_roundtrip_wait_request() -> None:
    jobs = [Job(job_id="1.gadi", job_name="a"), Job(job_id="2.gadi", job_name="b")]
    req = proto.WaitRequest(jobs=jobs)
    result = roundtrip(req)
    assert isinstance(result, proto.WaitRequest)
    assert [j.job_id for j in result.jobs] == ["1.gadi", "2.gadi"]


def test_roundtrip_result_request() -> None:
    job = Job(job_id="42.gadi", job_name="myjob")
    req = proto.ResultRequest(job=job)
    result = roundtrip(req)
    assert isinstance(result, proto.ResultRequest)
    assert result.job.job_id == "42.gadi"


def test_roundtrip_delete_request() -> None:
    req = proto.DeleteRequest(job_ids=["1.gadi", "2.gadi"])
    result = roundtrip(req)
    assert isinstance(result, proto.DeleteRequest)
    assert result.job_ids == ["1.gadi", "2.gadi"]


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------


def test_roundtrip_pong() -> None:
    assert isinstance(roundtrip(proto.PongResponse()), proto.PongResponse)


def test_roundtrip_submitted_response() -> None:
    job = Job(job_id="99.gadi", job_name="submitted")
    resp = proto.SubmittedResponse(job=job)
    result = roundtrip(resp)
    assert isinstance(result, proto.SubmittedResponse)
    assert result.job.job_id == "99.gadi"


def test_roundtrip_status_update() -> None:
    job = Job(job_id="1.gadi")
    resp = proto.StatusUpdateResponse(job=job, state="R")
    result = roundtrip(resp)
    assert isinstance(result, proto.StatusUpdateResponse)
    assert result.state == "R"


def test_roundtrip_status_update_finished() -> None:
    job = Job(job_id="1.gadi")
    resp = proto.StatusUpdateResponse(job=job, state=None)
    result = roundtrip(resp)
    assert isinstance(result, proto.StatusUpdateResponse)
    assert result.state is None


def test_roundtrip_wait_done() -> None:
    jobs = [Job(job_id="1.gadi"), Job(job_id="2.gadi")]
    resp = proto.WaitDoneResponse(jobs=jobs)
    result = roundtrip(resp)
    assert isinstance(result, proto.WaitDoneResponse)
    assert len(result.jobs) == 2


def test_roundtrip_result_response() -> None:
    job = Job(job_id="5.gadi", job_name="myjob")
    job_result = JobResult(exit_code=0, output="hello\n", error="", stats={"CPU": "1s"})
    resp = proto.ResultResponse(job=job, result=job_result)
    result = roundtrip(resp)
    assert isinstance(result, proto.ResultResponse)
    assert result.result.exit_code == 0
    assert result.result.output == "hello\n"
    assert result.result.stats == {"CPU": "1s"}


def test_roundtrip_error_response() -> None:
    resp = proto.ErrorResponse(message="something went wrong")
    result = roundtrip(resp)
    assert isinstance(result, proto.ErrorResponse)
    assert result.message == "something went wrong"


def test_roundtrip_delete_response() -> None:
    result = roundtrip(proto.DeleteResponse())
    assert isinstance(result, proto.DeleteResponse)


# ---------------------------------------------------------------------------
# Framing edge cases
# ---------------------------------------------------------------------------


def test_eof_on_empty_stream() -> None:
    buf = io.BytesIO(b"")
    with pytest.raises(EOFError):
        proto.recv_frame(buf)


def test_eof_on_truncated_header() -> None:
    buf = io.BytesIO(b"\x00\x00")  # Only 2 bytes of a 4-byte header
    with pytest.raises(EOFError):
        proto.recv_frame(buf)


def test_eof_on_truncated_body() -> None:
    data = pickle.dumps(proto.PingRequest())
    # Write a header claiming a longer body than we provide
    header = len(data).to_bytes(4, "big")
    buf = io.BytesIO(header + data[:2])  # body truncated
    with pytest.raises(EOFError):
        proto.recv_frame(buf)


def test_multiple_frames_in_sequence() -> None:
    buf = io.BytesIO()
    proto.send_frame(buf, proto.PingRequest())
    proto.send_frame(buf, proto.PongResponse())
    proto.send_frame(buf, proto.ErrorResponse(message="test"))
    buf.seek(0)

    assert isinstance(proto.recv_frame(buf), proto.PingRequest)
    assert isinstance(proto.recv_frame(buf), proto.PongResponse)
    err = proto.recv_frame(buf)
    assert isinstance(err, proto.ErrorResponse)
    assert err.message == "test"


def test_large_object_roundtrip() -> None:
    """Frames larger than a typical network buffer must reassemble correctly."""
    big_output = "x" * 500_000
    result_obj = JobResult(exit_code=0, output=big_output)
    job = Job(job_id="big.gadi", job_name="bigtest")
    resp = proto.ResultResponse(job=job, result=result_obj)
    result = roundtrip(resp)
    assert isinstance(result, proto.ResultResponse)
    assert len(result.result.output) == 500_000
