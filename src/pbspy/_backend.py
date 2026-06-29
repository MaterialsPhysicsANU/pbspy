"""
Backend abstract base class.

Concrete backends: :class:`~pbspy._local_backend.LocalBackend` (default,
in-process) and :class:`~pbspy._server_backend.ServerBackend` (remote via TCP).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pbspy import Job

__all__ = ["Backend"]


class Backend(ABC):
    """
    Abstract base class for PBS operation backends.

    All methods that touch PBS (qsub, qstat, file reading) go through a
    Backend so the same :class:`~pbspy.JobDescription` / :class:`~pbspy.Job`
    API works both locally and over SSH.
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

        Args:
            jobs: List of :class:`~pbspy.Job` objects.
            on_update: Optional callback ``(job_id, state)`` on each status
                change.  *state* is ``None`` when the job has finished.
        """
        ...

    @abstractmethod
    def get_result(self, job: object) -> object:
        """
        Return the :class:`~pbspy.JobResult` for a completed job.
        """
        ...
