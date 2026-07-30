"""
LocalBackend: direct in-process calls to :mod:`pbspy._pbs_core`.

This is the default backend when running on a host with PBS access.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pbspy._pbs_core as core
from pbspy._backend import Backend

if TYPE_CHECKING:
    from pbspy import Job, JobResult

__all__ = ["LocalBackend"]


class LocalBackend(Backend):
    """
    Backend that calls PBS commands directly in the current process.

    This is the default backend; it requires ``qsub`` and ``qstat`` to be
    available on ``PATH``.
    """

    def submit(self, script: str, name: str | None = None) -> tuple[str, str]:
        """Submit *script* via ``qsub`` and return ``(job_id, job_name)``."""
        return core.pbs_submit(script, name)

    def wait(
        self,
        jobs: list[Job],
        on_update: Callable[[str, str | None], None] | None = None,
    ) -> None:
        """Wait for *jobs* to finish."""
        core.pbs_wait_for_jobs(jobs, on_update)

    def get_result(self, job: Job) -> JobResult:
        """Return the :class:`~pbspy.JobResult` for a completed job."""
        return core.pbs_get_result(job)

    def delete(self, job_ids: list[str]) -> None:
        """Cancel (``qdel``) the given jobs."""
        core.pbs_delete(job_ids)
