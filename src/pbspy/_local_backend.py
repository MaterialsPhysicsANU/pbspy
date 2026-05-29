"""
LocalBackend: direct in-process calls to :mod:`pbspy._pbs_core`.

No sockets, no IPC, no serialisation.  This is the default backend when
running directly on the supercomputer — it behaves identically to the
original pbspy code but delegates through the :class:`Backend` interface.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.progress import Progress, TextColumn, TimeElapsedColumn

import pbspy._pbs_core as core
from pbspy._backend import Backend

if TYPE_CHECKING:
    from pbspy import Job

__all__ = ["LocalBackend"]

_PROGRESS_REFRESH_HZ = 1.0


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
        progress: bool = True,
    ) -> None:
        """Wait for *jobs* to finish, optionally showing a progress display."""
        if progress:
            self._wait_with_progress(jobs, on_update)
        else:
            core.pbs_wait_for_jobs(jobs, on_update)

    def get_result(self, job: object) -> object:  # job: Job -> JobResult
        """Return the :class:`~pbspy.JobResult` for a completed job."""
        return core.pbs_get_result(job)  # type: ignore[arg-type]

    def _wait_with_progress(
        self,
        jobs: list[Job],
        on_update: Callable[[str, str | None], None] | None,
    ) -> None:
        last_check = time.time() - core._POLL_INTERVAL_SECONDS  # poll immediately

        with Progress(
            TimeElapsedColumn(),
            TextColumn("[progress.description]{task.description}"),
            auto_refresh=False,
        ) as progress_bar:
            tasks = {
                job.job_id: progress_bar.add_task(
                    f"{job.job_id} {job.job_name or ''} {job.description or ''}",
                    total=1,
                )
                for job in jobs
            }
            task_done: dict[str, bool] = {job.job_id: False for job in jobs}

            while not all(task_done.values()):
                time.sleep(1.0 / _PROGRESS_REFRESH_HZ)
                progress_bar.refresh()

                if time.time() - last_check < core._POLL_INTERVAL_SECONDS:
                    continue
                last_check = time.time()

                for job in jobs:
                    if task_done[job.job_id]:
                        continue
                    process = subprocess.run(["qstat", job.job_id], capture_output=True)
                    if process.returncode != 0:
                        stdout = process.stdout.decode("utf-8")
                        if job.job_id not in stdout or "has finished" in process.stderr.decode("utf-8"):
                            task_done[job.job_id] = True
                            progress_bar.advance(tasks[job.job_id])
                            progress_bar.update(tasks[job.job_id], visible=False)

                            exit_code = core.try_get_exit_code(job.job_id)
                            status = (
                                "[green]✓" if exit_code == 0 else "[red]✗" if exit_code is not None else "[yellow]?"
                            )
                            progress_bar.console.print(
                                f"{status} {job.job_id} {job.job_name or ''} {job.description or ''}"
                            )
                            if on_update:
                                on_update(job.job_id, None)
