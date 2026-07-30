"""
Backend abstract base class.

The built-in :class:`~pbspy._local_backend.LocalBackend` runs PBS operations
in-process. Alternate implementations can provide other execution mechanisms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pbspy import Job, JobResult

__all__ = ["Backend"]


class Backend(ABC):
    """
    Abstract base class for PBS operation backends.

    All methods that touch PBS (qsub, qstat, qdel, and file reading) go through
    a backend so callers can supply a different implementation without changing
    the :class:`~pbspy.JobDescription` / :class:`~pbspy.Job` API.
    """

    @abstractmethod
    def submit(self, script: str, name: str | None = None) -> tuple[str, str]:
        """
        Submit a PBS job script.

        Returns:
            ``(job_id, job_name)``
        """
        ...

    @abstractmethod
    def wait(
        self,
        jobs: list[Job],
        on_update: Callable[[str, str | None], None] | None = None,
    ) -> None:
        """
        Wait for *jobs* to finish.

        :param jobs: List of :class:`~pbspy.Job` objects.
        :param on_update: Optional callback ``(job_id, state)`` on each status
            change. *state* is ``None`` when the job has finished.
        """
        ...

    @abstractmethod
    def get_result(self, job: Job) -> JobResult:
        """
        Return the :class:`~pbspy.JobResult` for a completed job.
        """
        ...

    @abstractmethod
    def delete(self, job_ids: list[str]) -> None:
        """
        Cancel (``qdel``) the given jobs.

        :param job_ids: Job ids to cancel.
        """
        ...
