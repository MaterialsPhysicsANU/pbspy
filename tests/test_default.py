import shutil
from collections.abc import Callable

import pytest

from pbspy import Backend, Job, JobDescription, JobResult, LocalBackend, SSHBackend


@pytest.mark.skipif(shutil.which("qsub") is None, reason="qsub not available")
def test_default() -> None:
    job_description = (
        JobDescription()
        .add_command(["echo", "a"])
        .add_command(["echo", "b"])
        .add_command(["echo", "c"])
        .add_command(["echo", "d"])
        .add_command(["echo", "e"])
    )
    print(job_description.script())
    result = job_description.submit().result()
    assert result.exit_code == 0
    assert result.output == "a\nb\nc\nd\ne\n"
    # assert result.error == ""


# ---------------------------------------------------------------------------
# Mock backend tests — do not require qsub/qstat
# ---------------------------------------------------------------------------


class _MockBackend(Backend):
    """In-process backend that records calls without invoking PBS."""

    def __init__(self) -> None:
        self.submitted: list[tuple[str, str | None]] = []
        self.waited: list[list[Job]] = []
        self.results: dict[str, JobResult] = {}

    def submit(self, script: str, name: str | None = None) -> tuple[str, str]:
        self.submitted.append((script, name))
        job_name = name or "mock_job"
        job_id = "99999.mock"
        self.results[job_id] = JobResult(exit_code=0, output="mock output\n")
        return job_id, job_name

    def wait(
        self, jobs: list[Job], on_update: Callable[[str, str | None], None] | None = None, progress: bool = True
    ) -> None:
        self.waited.append(list(jobs))

    def get_result(self, job: object) -> object:
        assert isinstance(job, Job)
        return self.results.get(job.job_id, JobResult(exit_code=None))


def test_mock_backend_submit() -> None:
    """JobDescription.submit() uses the provided backend."""
    mock = _MockBackend()
    jd = JobDescription(name="test_job", ncpus=1, walltime="00:01:00")
    jd.add_command(["echo", "hello"])

    job = jd.submit(backend=mock)

    assert len(mock.submitted) == 1
    script, _ = mock.submitted[0]
    assert "echo hello" in script
    assert job.job_id == "99999.mock"
    assert job.job_name == "test_job"
    assert job.backend is mock


def test_mock_backend_result() -> None:
    """Job.result() delegates to the backend."""
    mock = _MockBackend()
    jd = JobDescription(name="test_job")
    jd.add_command(["echo", "hello"])
    job = jd.submit(backend=mock)

    result = job.result(progress=False)

    assert len(mock.waited) == 1
    assert result.exit_code == 0
    assert result.output == "mock output\n"


def test_mock_backend_result_all() -> None:
    """Job.result_all() groups jobs and returns all results."""
    mock = _MockBackend()
    mock.results["1.mock"] = JobResult(exit_code=0, output="A\n")
    mock.results["2.mock"] = JobResult(exit_code=0, output="B\n")

    job_a = Job(job_id="1.mock", job_name="job_a", backend=mock)
    job_b = Job(job_id="2.mock", job_name="job_b", backend=mock)

    results = Job.result_all([job_a, job_b], progress=False)

    assert len(results) == 2
    assert results[0].output == "A\n"
    assert results[1].output == "B\n"


def test_script_generation_unchanged() -> None:
    """script() output is unchanged from the original implementation."""
    jd = JobDescription(
        name="myjob",
        project="ab01",
        queue="normal",
        ncpus=4,
        mem="16GB",
        walltime="01:00:00",
        wd=True,
    )
    jd.add_command(["echo", "hello world"])
    script = jd.script()

    assert "#PBS -N myjob" in script
    assert "#PBS -P ab01" in script
    assert "#PBS -q normal" in script
    assert "#PBS -l ncpus=4" in script
    assert "#PBS -l mem=16GB" in script
    assert "#PBS -l walltime=01:00:00" in script
    assert "#PBS -l wd" in script
    assert "echo 'hello world'" in script


def test_backend_classes_importable() -> None:
    """Backend, LocalBackend, SSHBackend are importable from pbspy."""
    assert issubclass(LocalBackend, Backend)
    assert issubclass(SSHBackend, Backend)
