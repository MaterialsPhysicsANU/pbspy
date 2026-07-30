import shutil
import subprocess
from collections.abc import Callable

import pytest

from pbspy import Backend, Job, JobDescription, JobResult, LocalBackend


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
        self.deleted: list[list[str]] = []

    def submit(self, script: str, name: str | None = None) -> tuple[str, str]:
        self.submitted.append((script, name))
        job_name = name or "mock_job"
        job_id = "99999.mock"
        self.results[job_id] = JobResult(exit_code=0, output="mock output\n")
        return job_id, job_name

    def wait(self, jobs: list[Job], on_update: Callable[[str, str | None], None] | None = None) -> None:
        self.waited.append(list(jobs))

    def get_result(self, job: Job) -> JobResult:
        return self.results.get(job.job_id, JobResult(exit_code=None))

    def delete(self, job_ids: list[str]) -> None:
        self.deleted.append(list(job_ids))


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

    result = job.result()

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

    results = Job.result_all([job_a, job_b])

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
    """Backend and LocalBackend are importable from pbspy."""
    assert issubclass(LocalBackend, Backend)


def test_default_submissions_share_local_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default submissions share a backend so wait_all can group their polling."""
    submitted = iter([("1.mock", "job_a"), ("2.mock", "job_b")])
    monkeypatch.setattr(LocalBackend, "submit", lambda *_args, **_kwargs: next(submitted))

    job_a = JobDescription(name="job_a").submit()
    job_b = JobDescription(name="job_b").submit()

    assert job_a.backend is job_b.backend


def test_submit_carries_output_and_error_paths() -> None:
    """JobDescription.submit() propagates output_path/error_path to the returned Job."""
    mock = _MockBackend()
    jd = JobDescription(
        name="test_job",
        output_path="/scratch/project/job.out",
        error_path="/scratch/project/job.err",
    )
    jd.add_command(["echo", "hello"])

    job = jd.submit(backend=mock)

    assert job.output_path == "/scratch/project/job.out"
    assert job.error_path == "/scratch/project/job.err"


def test_submit_default_paths_are_none() -> None:
    """When output_path/error_path are not set, Job gets None for both."""
    mock = _MockBackend()
    jd = JobDescription(name="test_job")
    jd.add_command(["echo", "hello"])

    job = jd.submit(backend=mock)

    assert job.output_path is None
    assert job.error_path is None


def test_pbs_get_result_uses_custom_paths() -> None:
    """pbs_get_result reads from custom output_path/error_path when set."""
    from pbspy._pbs_core import PBSRunner, pbs_get_result

    class _FileTrackingRunner(PBSRunner):
        def __init__(self) -> None:
            super().__init__()
            self.read_paths: list[str] = []

        def read_file(self, path: str) -> str:
            self.read_paths.append(path)
            if "out" in path:
                return "custom stdout\n"
            return "custom stderr\n"

        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            # Override to avoid real qstat calls
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    runner = _FileTrackingRunner()
    job = Job(
        job_id="123.mock",
        job_name="myjob",
        output_path="/scratch/job.out",
        error_path="/scratch/job.err",
    )

    result = pbs_get_result(job, runner=runner)

    # Should read from custom paths, not default names
    assert "/scratch/job.out" in runner.read_paths
    assert "/scratch/job.err" in runner.read_paths
    assert result.output == "custom stdout\n"
    assert result.error == "custom stderr\n"


def test_pbs_get_result_uses_default_paths_when_none() -> None:
    """pbs_get_result falls back to {job_name}.o{job_id} when paths are None."""
    from pbspy._pbs_core import PBSRunner, pbs_get_result

    class _FileTrackingRunner(PBSRunner):
        def __init__(self) -> None:
            super().__init__()
            self.read_paths: list[str] = []

        def read_file(self, path: str) -> str:
            self.read_paths.append(path)
            return ""

        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    runner = _FileTrackingRunner()
    job = Job(
        job_id="456.mock",
        job_name="defaultjob",
        output_path=None,
        error_path=None,
    )

    result = pbs_get_result(job, runner=runner)

    assert "defaultjob.o456" in runner.read_paths
    assert "defaultjob.e456" in runner.read_paths
    assert result.output == ""
    assert result.error == ""


# ---------------------------------------------------------------------------
# pbs_get_states / pbs_delete / Job.cancel
# ---------------------------------------------------------------------------


def test_pbs_get_states_single_qstat_call() -> None:
    """pbs_get_states issues exactly one qstat call for multiple job ids."""
    from pbspy._pbs_core import PBSRunner, pbs_get_states

    class _RecordingRunner(PBSRunner):
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            self.calls.append(cmd)
            stdout = (
                b"Job id            Name             User              Time Use S Queue\n"
                b"----------------  ---------------- ----------------  -------- - -----\n"
                b"123.gadi-pbs      job_a            user00            00:00:12 R normal\n"
                b"124.gadi-pbs      job_b            user00            00:00:00 Q normal\n"
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=b"")

    runner = _RecordingRunner()
    states = pbs_get_states(["123.gadi-pbs", "124.gadi-pbs", "125.gadi-pbs"], runner=runner)

    assert len(runner.calls) == 1
    assert runner.calls[0] == ["qstat", "123.gadi-pbs", "124.gadi-pbs", "125.gadi-pbs"]
    assert states == {
        "123.gadi-pbs": "R",
        "124.gadi-pbs": "Q",
        "125.gadi-pbs": None,  # not listed => finished
    }


def test_pbs_get_states_empty_list() -> None:
    """pbs_get_states with no job ids makes no qstat call and returns an empty dict."""
    from pbspy._pbs_core import PBSRunner, pbs_get_states

    class _FailIfCalledRunner(PBSRunner):
        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            raise AssertionError("qstat should not be called for an empty job list")

    assert pbs_get_states([], runner=_FailIfCalledRunner()) == {}


def test_pbs_delete_single_qdel_call() -> None:
    """pbs_delete issues exactly one qdel call for multiple job ids."""
    from pbspy._pbs_core import PBSRunner, pbs_delete

    class _RecordingRunner(PBSRunner):
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    runner = _RecordingRunner()
    pbs_delete(["123.gadi-pbs", "124.gadi-pbs"], runner=runner)

    assert len(runner.calls) == 1
    assert runner.calls[0] == ["qdel", "123.gadi-pbs", "124.gadi-pbs"]


def test_pbs_delete_idempotent_for_finished_jobs() -> None:
    """pbs_delete does not raise when qdel reports the job has already finished."""
    from pbspy._pbs_core import PBSRunner, pbs_delete

    class _FinishedRunner(PBSRunner):
        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"qdel: Job has finished 123.gadi-pbs")

    pbs_delete(["123.gadi-pbs"], runner=_FinishedRunner())  # should not raise


def test_pbs_delete_idempotent_for_unknown_jobs() -> None:
    """pbs_delete does not raise when qdel reports an unknown job id."""
    from pbspy._pbs_core import PBSRunner, pbs_delete

    class _UnknownRunner(PBSRunner):
        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"qdel: Unknown Job Id 123.gadi-pbs")

    pbs_delete(["123.gadi-pbs"], runner=_UnknownRunner())  # should not raise


def test_pbs_delete_raises_on_other_errors() -> None:
    """pbs_delete raises for genuine errors (not the finished/unknown cases)."""
    from pbspy._pbs_core import PBSRunner, pbs_delete

    class _BrokenRunner(PBSRunner):
        def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"qdel: permission denied")

    with pytest.raises(RuntimeError, match="permission denied"):
        pbs_delete(["123.gadi-pbs"], runner=_BrokenRunner())


def test_job_cancel_calls_backend_delete() -> None:
    """Job.cancel() delegates to backend.delete([job_id])."""
    mock = _MockBackend()
    job = Job(job_id="123.mock", job_name="job_a", backend=mock)

    job.cancel()

    assert mock.deleted == [["123.mock"]]
