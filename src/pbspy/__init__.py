"""
Utilities for PBS job submission and output retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Self, TypeAlias

from pbspy._backend import Backend
from pbspy._local_backend import LocalBackend
from pbspy._server_backend import ServerBackend

# Shared LocalBackend instance so all locally-submitted jobs are grouped together
# when calling Job.wait_all() / Job.result_all(), restoring concurrent polling.
_DEFAULT_LOCAL_BACKEND = LocalBackend()

__all__ = [
    "JobDescription",
    "Job",
    "JobResult",
    "QueueLimits",
    "QueueLimitsMap",
    "Backend",
    "LocalBackend",
    "ServerBackend",
    "gadi",
]


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

    backend: Backend = field(default=_DEFAULT_LOCAL_BACKEND, repr=False, compare=False)
    """The backend used to submit and track this job."""

    def __getstate__(self) -> dict[str, Any]:
        """Exclude backend from pickling (it carries live sockets)."""
        state = self.__dict__.copy()
        del state["backend"]
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore job state, assigning the default local backend."""
        self.__dict__.update(state)
        self.backend = _DEFAULT_LOCAL_BACKEND

    def wait(self, progress: bool = True) -> None:
        """
        Wait for the job to complete.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        self.backend.wait([self], progress=progress)

    def result(self, progress: bool = True) -> JobResult:
        """
        Waits for the job to complete and returns the result.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        self.wait(progress=progress)
        return self.backend.get_result(self)  # type: ignore[return-value]

    @staticmethod
    def wait_all(jobs: list[Job], progress: bool = True) -> None:
        """
        Waits for multiple jobs to complete.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        if not jobs:
            return
        # Group by backend so each backend can wait for its own jobs efficiently
        _wait_all_grouped(jobs, progress=progress)

    @staticmethod
    def result_all(jobs: list[Job], progress: bool = True) -> list[JobResult]:
        """
        Waits for multiple jobs to complete and returns their results.

        Args:
            progress (bool): Whether or not to print the state of the job and status on exit.
        """
        Job.wait_all(jobs, progress=progress)
        return [job.backend.get_result(job) for job in jobs]  # type: ignore[misc]


def _wait_all_grouped(jobs: list[Job], progress: bool) -> None:
    """Group jobs by backend identity and wait per group."""
    groups: dict[int, tuple[Backend, list[Job]]] = {}
    for job in jobs:
        bid = id(job.backend)
        if bid not in groups:
            groups[bid] = (job.backend, [])
        groups[bid][1].append(job)
    for backend, group in groups.values():
        backend.wait(group, progress=progress)


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

    output_path: str | None = None
    """Path for the job's stdout output file. Example: ``/scratch/project/job.out``"""

    error_path: str | None = None
    """Path for the job's stderr error file. Example: ``/scratch/project/job.err``"""

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
        from pbspy._pbs_core import format_job_script

        return format_job_script(
            name=self.name,
            project=self.project,
            queue=self.queue,
            ncpus=self.ncpus,
            mem=self.mem,
            jobfs=self.jobfs,
            walltime=self.walltime,
            storage=self.storage,
            wd=self.wd,
            output_path=self.output_path,
            error_path=self.error_path,
            afterok_ids=[job.job_id for job in self.afterok],
            commands=self.commands,
        )

    def submit(self, backend: Backend | None = None) -> Job:
        """
        Submits the job to the PBS queue.

        Args:
            backend: The backend to use for submission.  Defaults to
                :class:`~pbspy.LocalBackend` (runs ``qsub`` locally).
                Pass a :class:`~pbspy.ServerBackend` instance to submit via
                a pbspy-server daemon.
        """
        if backend is None:
            backend = LocalBackend()

        job_script = self.script()
        job_id, job_name = backend.submit(job_script, self.name)

        if self.name is None:
            self.name = job_name

        return Job(job_name=job_name, job_id=job_id, description=self.description, backend=backend)
