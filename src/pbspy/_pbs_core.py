"""
Core PBS operations: qsub submission, qstat polling, and result file reading.

These functions are used by :class:`pbspy.LocalBackend` and are also available
to applications that need lower-level PBS state queries.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pbspy import Job, JobResult

__all__ = [
    "PBSRunner",
    "pbs_submit",
    "pbs_wait_for_jobs",
    "pbs_get_result",
    "pbs_get_states",
    "pbs_delete",
    "try_get_exit_code",
]

_POLL_INTERVAL_SECONDS = 60
_PROGRESS_REFRESH_SECONDS = 1


class PBSRunner:
    """Abstracts command execution and file reading for PBS operations. Runs commands locally."""

    def run(self, cmd: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(cmd, input=input, capture_output=True)

    def read_file(self, path: str) -> str:
        """Read a local file and return its text."""
        result = self.run(["cat", path])
        if result.returncode != 0:
            raise FileNotFoundError(path)
        return result.stdout.decode("utf-8")


_LOCAL_RUNNER = PBSRunner()


def _get_job_name(job_id: str, runner: PBSRunner = _LOCAL_RUNNER) -> str:
    process = runner.run(["qstat", "-fx", job_id])
    if process.returncode != 0:
        raise RuntimeError(f"Failed to get job status: {process.stderr.decode('utf-8')}")
    output = process.stdout.decode("utf-8")
    re_match = re.search(r"Job_Name = ([^\s]+)", output)
    if re_match is not None:
        group = re_match.group(1)
        assert group
        return group
    raise RuntimeError("Could not retrieve job name")


def try_get_exit_code(job_id: str, runner: PBSRunner = _LOCAL_RUNNER) -> int | None:
    """Return the exit status of a finished PBS job, or ``None`` if unavailable."""
    process = runner.run(["qstat", "-fx", job_id])
    if process.returncode != 0:
        raise RuntimeError(f"Failed to get job status: {process.stderr.decode('utf-8')}")
    output = process.stdout.decode("utf-8")
    exit_code_match = re.search(r"Exit_status = (\d+)", output)
    if exit_code_match is not None:
        exit_code_group = exit_code_match.group(1)
        assert exit_code_group
        return int(exit_code_group)
    return None


def pbs_submit(script: str, name: str | None, runner: PBSRunner = _LOCAL_RUNNER) -> tuple[str, str]:
    """
    Submit a PBS job script via ``qsub``.

    Returns:
        A tuple of ``(job_id, job_name)``.
    """
    process = runner.run(["qsub"], input=script.encode("utf-8"))
    if process.returncode != 0:
        raise RuntimeError(f"Failed to submit job: {process.stderr.strip().decode('utf-8')}")
    job_id = process.stdout.strip().decode("utf-8")
    if name is None:
        name = _get_job_name(job_id, runner)
    return job_id, name


def pbs_wait_for_jobs(
    jobs: list[Job],
    on_update: Callable[[str, str | None], None] | None = None,
) -> None:
    """
    Poll qstat until all jobs in *jobs* have finished.

    :param jobs: The jobs to wait for.
    :param on_update: Optional callback invoked on each status change. Called
        as ``on_update(job_id, state)`` where *state* is one of ``"Q"``,
        ``"R"``, ``"E"``, ``"F"`` or ``None`` when the job has disappeared
        from qstat (finished).
    """
    task_done = [False] * len(jobs)
    last_check = time.time() - _POLL_INTERVAL_SECONDS  # poll immediately on first iteration

    while not all(task_done):
        time.sleep(_PROGRESS_REFRESH_SECONDS)
        if time.time() - last_check >= _POLL_INTERVAL_SECONDS:
            last_check = time.time()
            for i, job in enumerate(jobs):
                if task_done[i]:
                    continue
                process = subprocess.run(["qstat", job.job_id], capture_output=True)
                if process.returncode != 0:
                    output = process.stdout.decode("utf-8")
                    if job.job_id not in output or "has finished" in process.stderr.decode("utf-8"):
                        task_done[i] = True
                        if on_update is not None:
                            on_update(job.job_id, None)


def pbs_get_states(job_ids: list[str], runner: PBSRunner = _LOCAL_RUNNER) -> dict[str, str | None]:
    """
    Look up the PBS state of each id in *job_ids* with a single ``qstat`` call.

    Returns:
        A mapping of job id -> state (``"Q"``, ``"R"``, ``"E"``, etc.), or ``None`` when the
        id is no longer listed by ``qstat`` (i.e. the job has finished).
    """
    if not job_ids:
        return {}

    states: dict[str, str | None] = dict.fromkeys(job_ids)
    process = runner.run(["qstat", *job_ids])
    output = process.stdout.decode("utf-8")

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Job id") or line.startswith("---"):
            continue
        fields = line.split()
        if len(fields) < 5:
            continue
        job_id = fields[0]
        if job_id in states:
            states[job_id] = fields[4]

    # Any id not found in the qstat table is left as None (finished / unknown), matching the
    # "job_id not in output or has finished" convention used elsewhere in this module.
    return states


def pbs_delete(job_ids: list[str], runner: PBSRunner = _LOCAL_RUNNER) -> None:
    """
    Cancel jobs via a single ``qdel`` call. Idempotent: already-finished or unknown job ids
    are treated as success rather than raising.
    """
    if not job_ids:
        return

    process = runner.run(["qdel", *job_ids])
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8")
        if "has finished" not in stderr and "Unknown Job Id" not in stderr:
            raise RuntimeError(f"Failed to delete job(s): {stderr.strip()}")


def pbs_get_result(job: Job, runner: PBSRunner = _LOCAL_RUNNER) -> JobResult:
    """
    Read the output/error files for a completed job and return a :class:`~pbspy.JobResult`.

    The job must have already finished; this function does **not** wait.
    """
    from pbspy import JobResult

    job_id_num = job.job_id.split(".")[0]
    output_file = job.output_path or f"{job.job_name}.o{job_id_num}"
    error_file = job.error_path or f"{job.job_name}.e{job_id_num}"

    try:
        output = runner.read_file(output_file)
    except FileNotFoundError:
        output = ""
    try:
        error = runner.read_file(error_file)
    except FileNotFoundError:
        error = ""

    output_split = output.split(
        "\n======================================================================================\n"
    )
    exit_code = None
    pbs_stats: dict[str, str] | None = None
    if len(output_split) == 3:
        output = output_split[0]
        stats_block = output_split[1].strip()
        stats_block = "\n".join(stats_block.split("\n")[1:])  # Skip "Resource usage on .." line
        pbs_stats = {}
        pattern = re.compile(r"\s*([^:]+):\s*([^\s]+)")
        for match in pattern.finditer(stats_block):
            key = match.group(1).strip()
            value = match.group(2).strip()
            pbs_stats[key] = value
            if key == "Exit Status":
                exit_code_match = re.search(r"^\d+", value)
                if exit_code_match is not None:
                    exit_code = int(exit_code_match.group())

    if exit_code is None:
        exit_code = try_get_exit_code(job.job_id, runner)

    return JobResult(exit_code=exit_code, output=output, error=error, stats=pbs_stats)


def format_job_script(
    name: str | None,
    project: str | None,
    queue: str | None,
    ncpus: int | None,
    mem: str | None,
    jobfs: str | None,
    walltime: str | None,
    storage: str | None,
    wd: bool,
    output_path: str | None,
    error_path: str | None,
    afterok_ids: list[str],
    commands: list[str | list[str]],
) -> str:
    """Format a PBS job script from the given parameters."""
    command_strs: list[str] = []
    for command in commands:
        if isinstance(command, str):
            command_strs.append(command)
        elif isinstance(command, list):
            command_strs.append(" ".join(shlex.quote(arg) for arg in command))
    commands_str = "\n".join(command_strs)

    return f"""#!/bin/bash
{f"#PBS -P {project}" if project else ""}
{f"#PBS -N {name}" if name else ""}
{f"#PBS -q {queue}" if queue else ""}
{f"#PBS -l ncpus={ncpus}" if ncpus else ""}
{f"#PBS -l mem={mem}" if mem else ""}
{f"#PBS -l jobfs={jobfs}" if jobfs else ""}
{f"#PBS -l walltime={walltime}" if walltime else ""}
{f"#PBS -l storage={storage}" if storage else ""}
{f"#PBS -o {output_path}" if output_path else ""}
{f"#PBS -e {error_path}" if error_path else ""}
{"#PBS -l wd" if wd else ""}
{f"#PBS -W depend=afterok:{":".join(afterok_ids)}" if afterok_ids else ""}
{commands_str}
"""
