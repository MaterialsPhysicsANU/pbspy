"""
Utilities for PBS job submission and output retrieval.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Self, TypeAlias

from rich.progress import Progress, TextColumn, TimeElapsedColumn

__all__ = ["JobDescription", "Job", "JobResult", "QueueLimits", "QueueLimitsMap", "gadi"]


def _get_job_name(job_id: str) -> str:
    process = subprocess.run(
        ["qstat", "-fx", job_id],
        capture_output=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"Failed to get job status: {process.stderr.decode('utf-8')}")
    output = process.stdout.decode("utf-8")

    # Grab the exit code
    # NOTE: This is not always immediately set when the job finishes...
    re_match = re.search(r"Job_Name = ([^\s]+)", output)
    if re_match is not None:
        group = re_match.group(1)
        assert group
        return group
    else:
        raise RuntimeError("Could not retrieve job name")


def _try_get_exit_code(job_id: str) -> int | None:
    """
    Retrieves the exit code of a job with the given job ID.

    Args:
        job_id (str): The ID of the job.

    Returns:
        int | None: The exit code of the job if available, None otherwise.
    """
    # Get the exit code
    process = subprocess.run(
        ["qstat", "-fx", job_id],
        capture_output=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"Failed to get job status: {process.stderr.decode('utf-8')}")
    output = process.stdout.decode("utf-8")

    # Grab the exit code
    # NOTE: This is not always immediately set when the job finishes...
    exit_code_match = re.search(r"Exit_status = (\d+)", output)
    if exit_code_match is not None:
        exit_code_group = exit_code_match.group(1)
        assert exit_code_group
        return int(exit_code_group)
    else:
        raise RuntimeError("Could not get exit code")


def _pbs_wait_for_jobs(jobs: list[Job], progress: bool = True) -> None:
    """
    Waits for the PBS jobs to complete.

    Args:
        jobs (list[Job]): A list of Job objects representing the PBS jobs.
        progress (bool): Whether or not to print the state of the job and status on exit.

    Returns:
        None
    """
    if progress:
        _pbs_wait_for_jobs_with_progress(jobs)
    else:
        _pbs_wait_for_jobs_quiet(jobs)


def _pbs_wait_for_jobs_quiet(jobs: list[Job]) -> None:
    """
    Waits for the PBS jobs to complete.

    Args:
        jobs (list[Job]): A list of Job objects representing the PBS jobs.

    Returns:
        None
    """
    task_done = [False] * len(jobs)
    while not all(task_done):
        time.sleep(60)
        for i, job in enumerate(jobs):
            if task_done[i]:
                continue
            process = subprocess.run(
                ["qstat", job.job_id],
                capture_output=True,
            )
            if process.returncode != 0:
                output = process.stdout.decode("utf-8")
                if job.job_id not in output or "has finished" in process.stderr.decode("utf-8"):
                    task_done[i] = True
            # else:
            # raise RuntimeError(f"Failed to check job status: {process.stderr.decode('utf-8')}")


def _pbs_wait_for_jobs_with_progress(jobs: list[Job]) -> None:
    """
    Waits for the PBS jobs to complete.

    Args:
        jobs (list[Job]): A list of Job objects representing the PBS jobs.

    Returns:
        None
    """
    last_check = time.time()
    with Progress(
        TimeElapsedColumn(),
        TextColumn("[progress.description]{task.description}"),
        auto_refresh=False,
    ) as progress:
        tasks = [progress.add_task(f"{job.job_id} {job.job_name} {job.description or ''}", total=1) for job in jobs]
        task_done = [False] * len(jobs)
        while not all(task_done):
            time.sleep(1)
            if time.time() - last_check > 60:
                last_check = time.time()
                for i, (job, task) in enumerate(zip(jobs, tasks, strict=False)):
                    if task_done[i]:
                        continue
                    process = subprocess.run(
                        ["qstat", job.job_id],
                        capture_output=True,
                    )
                    if process.returncode != 0:
                        output = process.stdout.decode("utf-8")
                        if job.job_id not in output or "has finished" in process.stderr.decode("utf-8"):
                            task_done[i] = True
                            progress.advance(task)
                            progress.update(task, visible=False)

                            # Try and get the exit code
                            exit_code = _try_get_exit_code(job.job_id)
                            if exit_code is None:
                                output_status = "[yellow]?"
                            else:
                                output_status = "[green]✓" if exit_code == 0 else "[red]✗"
                            progress.console.print(
                                f'{output_status} {job.job_id} {job.job_name} {job.description or ""}'
                            )
                    # else:
                    # raise RuntimeError(f"Failed to check job status: {process.stderr.decode('utf-8')}")
            progress.refresh()


@dataclass
class JobResult:
    """
    The result (stdout, stderr, etc.) of a completed PBS job.
    """

    exit_code: int | None = None
    """The exit code of the job if it could be determined, ``None`` otherwise."""

    output: str = ""
    """The job output (stdout).

    PBS stats are separated from the job output into ``stats``.
    """

    error: str = ""
    """The job error (stderr)."""

    stats: dict[str, str] | None = None
    """PBS stats extracted from the job output."""


@dataclass(kw_only=True)
class Job:
    """A PBS job."""

    job_name: str | None = None
    """The job name."""

    job_id: str
    """The job identifier."""

    description: str | None = None
    """A description of the job for progress updates. Unused by PBS."""

    def wait(self, progress: bool = True) -> None:
        """
        Wait for the job to complete.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        _pbs_wait_for_jobs([self], progress=progress)

    def _result_no_wait(self) -> JobResult:
        """
        Return the result of a job without waiting.

        If the job has not completed, this method will raise an error.
        """

        # Get output and error file
        job_id_num = self.job_id.split(".")[0]  # Remove .gadi-pbspy suffix
        output_file = f"{self.job_name}.o{job_id_num}"
        error_file = f"{self.job_name}.e{job_id_num}"
        try:
            with open(output_file) as f:
                output = f.read()
        except FileNotFoundError:
            output = ""
        try:
            with open(error_file) as f:
                error = f.read()
        except FileNotFoundError:
            error = ""

        # Try and process the output
        output_split = output.split(
            "\n======================================================================================\n"
        )
        exit_code = None
        if len(output_split) == 3:
            output = output_split[0]
            stats = output_split[1].strip()
            stats = "\n".join(stats.split("\n")[1:])  # Skip first line "Resource usage on .."
            pbs_stats = dict()
            pattern = re.compile(r"\s*([^:]+):\s*([^\s]+)")
            for match in pattern.finditer(stats):
                key = match.group(1).strip()
                value = match.group(2).strip()
                pbs_stats[key] = value
                if key == "Exit Status":
                    exit_code_match = re.search(r"^\d+", value)
                    if exit_code_match is not None:
                        exit_code = int(exit_code_match.group())
        else:
            pbs_stats = None

        if exit_code is None:
            exit_code = _try_get_exit_code(self.job_id)

        return JobResult(exit_code=exit_code, output=output, error=error, stats=pbs_stats)

    def result(self, progress: bool = True) -> JobResult:
        """
        Waits for the job to complete and returns the result.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        self.wait(progress=progress)
        return self._result_no_wait()

    @staticmethod
    def wait_all(jobs: list[Job], progress: bool = True) -> None:
        """
        Waits for multiple jobs to complete.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        _pbs_wait_for_jobs(jobs, progress=progress)

    @staticmethod
    def result_all(jobs: list[Job], progress: bool = True) -> list[JobResult]:
        """
        Waits for multiple jobs to complete and returns their results.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        _pbs_wait_for_jobs(jobs, progress=progress)
        return [job._result_no_wait() for job in jobs]


@dataclass(kw_only=True)
class QueueLimits:
    """Represents the resource limits of a queue."""

    cpus_per_node: int
    """The number of CPUs per node."""

    max_mem_per_node: int
    """The maximum memory per node (in GB)."""

    max_jobfs_per_node: int
    """The maximum JOBFS per node (in GB)."""


QueueLimitsMap: TypeAlias = dict[str, QueueLimits]
"""
A map of queue names to queue limits.
"""


@dataclass(kw_only=True)
class JobDescription:
    """A description of a PBS job for submission."""

    name: str | None = None
    """The job name.

    Note that PBS systems have constraints on valid job names.
    A job will be rejected if the name is not valid.
    """

    description: str | None = None
    """A description of the job for progress updates. Unused by PBS."""

    commands: list[str | list[str]] = field(default_factory=list)
    """A list of commands to be executed in the job."""

    project: str | None = None
    """The project under which to run the job."""

    queue: str | None = None
    """The name of the queue to submit the job to."""

    ncpus: int | None = None
    """The number of CPUs required for the job."""

    mem: str | None = None
    """The amount of memory required for the job. Example: ``100GB``"""

    jobfs: str | None = None
    """The amount of job file system space required for the job. Example: ``1GB``."""

    walltime: str | None = None
    """The maximum walltime for the job. Example: ``00:05:00``."""

    storage: str | None = None
    """The storage requirements for the job. Example: ``10GB``."""

    wd: bool = True
    """A flag indicating whether the working directory should be used."""

    afterok: list[Job] = field(default_factory=list)
    """A list of jobs that this job depends on."""

    @classmethod
    def from_nodes(cls, nnodes: int, queue: str, queue_limits: QueueLimits, **kwargs: Any) -> JobDescription:
        """
        Creates a job description that uses all available resources for some number of nodes.
        """
        kwargs["ncpus"] = nnodes * queue_limits.cpus_per_node
        if "mem" not in kwargs:
            kwargs["mem"] = f"{nnodes * queue_limits.max_mem_per_node}GB"
        if "jobfs" not in kwargs:
            kwargs["jobfs"] = f"{nnodes * queue_limits.max_jobfs_per_node}GB"
        return cls(queue=queue, **kwargs)

    def add_command(self, command: str | list[str]) -> Self:
        """
        Adds a command to the list of commands for the job.
        """
        self.commands.append(command)
        return self

    def add_commands(self, commands: list[str | list[str]]) -> Self:
        """
        Adds a list of commands to the job.
        """
        for command in commands:
            self.add_command(command)
        return self

    def script(self) -> str:
        """
        Generate a PBS job script based on job description.
        """
        commands: list[str] = []
        for command in self.commands:
            if isinstance(command, str):
                commands.append(command)
            elif isinstance(command, list):
                commands.append(" ".join(shlex.quote(arg) for arg in command))
        commands_str = "\n".join(commands)

        job_script = f"""#!/bin/bash
{f"#PBS -P {self.project}" if self.project else ""}
{f"#PBS -N {self.name}" if self.name else ""}
{f"#PBS -q {self.queue}" if self.queue else ""}
{f"#PBS -l ncpus={self.ncpus}" if self.ncpus else ""}
{f"#PBS -l mem={self.mem}" if self.mem else ""}
{f"#PBS -l jobfs={self.jobfs}" if self.jobfs else ""}
{f"#PBS -l walltime={self.walltime}" if self.walltime else ""}
{f"#PBS -l storage={self.storage}" if self.storage else ""}
{"#PBS -l wd" if self.wd else ""}
{f'#PBS -W depend=afterok:{":".join([job.job_id for job in self.afterok])}' if len(self.afterok) > 0 else ""}
{commands_str}
"""
        return job_script

    def submit(self) -> Job:
        """
        Submits the job to the PBS queue using ``qsub``.
        """
        job_script = self.script()

        process = subprocess.Popen(
            ["qsub"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(input=job_script.encode("utf-8"))

        if process.returncode != 0:
            raise RuntimeError(f'Failed to submit job: {stderr.strip().decode("utf-8")}')
        job_id = stdout.strip().decode("utf-8")

        if self.name is None:
            self.name = _get_job_name(job_id)

        return Job(job_name=self.name, job_id=job_id, description=self.description)
