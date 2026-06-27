"""The workflow scheduler - pure dependency/priority/retry logic.

Given a workflow's jobs, the scheduler decides what is runnable and in what
order, and how a failed job transitions (retry with backoff, or die). It is
deliberately pure and deterministic (no I/O, no clock side-effects beyond a
passed-in ``now``), so it is trivially testable and gives identical results on
replay - the foundation of crash recovery.

Rules:
- A ``PENDING`` job becomes ``READY`` when every dependency is ``COMPLETED`` and
  its ``available_at``/``scheduled_for`` time (if any) has arrived.
- If any dependency is ``FAILED``/``DEAD``/``CANCELLED``/``BLOCKED``, the job is
  ``BLOCKED`` (it can never run).
- Runnable jobs are ordered by priority (desc) then creation time (asc) - i.e.
  priority queue with FIFO tie-breaking.
- On failure, a job retries (with exponential backoff via ``available_at``)
  until ``max_attempts`` is reached, after which it is ``DEAD``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from olympus.domain.entities.workflow import (
    JobStatus,
    Workflow,
    WorkflowStatus,
)

# Exponential backoff base (seconds): attempt 1 -> 2s, 2 -> 4s, 3 -> 8s ...
RETRY_BACKOFF_BASE_SECONDS = 2.0
RETRY_BACKOFF_CAP_SECONDS = 300.0

_DEP_FAILED = {JobStatus.FAILED, JobStatus.DEAD, JobStatus.CANCELLED, JobStatus.BLOCKED}


class Scheduler:
    """Computes job readiness, ordering, and retry transitions for a workflow."""

    def __init__(
        self,
        *,
        backoff_base_seconds: float = RETRY_BACKOFF_BASE_SECONDS,
        backoff_cap_seconds: float = RETRY_BACKOFF_CAP_SECONDS,
    ) -> None:
        self._backoff_base = backoff_base_seconds
        self._backoff_cap = backoff_cap_seconds

    def backoff_seconds(self, attempts: int) -> float:
        """Exponential backoff for the given (1-based) attempt count, capped."""

        return min(self._backoff_cap, self._backoff_base * (2 ** max(0, attempts - 1)))
    def reconcile(self, workflow: Workflow, *, now: datetime) -> None:
        """Advance job statuses based on dependencies and timers (in place).

        Promotes satisfied ``PENDING`` jobs to ``READY``, blocks jobs whose
        dependencies can never complete, and re-arms retry-delayed jobs whose
        backoff has elapsed. Does not claim or run anything.
        """

        if workflow.status in (WorkflowStatus.PAUSED, WorkflowStatus.CANCELLED):
            return
        by_stage = {j.stage: j for j in workflow.jobs}
        for job in workflow.jobs:
            if job.status not in (JobStatus.PENDING, JobStatus.READY):
                continue
            deps = [by_stage.get(dep) for dep in job.depends_on]
            if any(d is None or d.status in _DEP_FAILED for d in deps):
                job.status = JobStatus.BLOCKED
                continue
            deps_done = all(d is not None and d.status is JobStatus.COMPLETED for d in deps)
            timer_ready = self._timer_ready(job.available_at, job.scheduled_for, now)
            if deps_done and timer_ready:
                if job.status is JobStatus.PENDING:
                    job.status = JobStatus.READY
            elif job.status is JobStatus.READY and not timer_ready:
                # A retry-delayed job that was prematurely ready: hold it.
                job.status = JobStatus.PENDING

    @staticmethod
    def _timer_ready(
        available_at: datetime | None, scheduled_for: datetime | None, now: datetime
    ) -> bool:
        if available_at is not None and now < available_at:
            return False
        return not (scheduled_for is not None and now < scheduled_for)

    def runnable(self, workflow: Workflow, *, now: datetime) -> list:
        """Return this workflow's claimable jobs, best-first (priority, then FIFO)."""

        if workflow.status is not WorkflowStatus.RUNNING:
            return []
        ready = [
            j
            for j in workflow.jobs
            if j.status is JobStatus.READY
            and self._timer_ready(j.available_at, j.scheduled_for, now)
        ]
        ready.sort(key=lambda j: (-j.priority, j.created_at or now))
        return ready

    def on_failure(self, job, *, now: datetime) -> bool:
        """Apply a failure to a job. Returns ``True`` if it will retry, else dead.

        The job's ``attempts`` is assumed already incremented for this run.
        """

        if job.attempts < job.max_attempts:
            job.status = JobStatus.PENDING
            job.worker_id = None
            job.available_at = now + timedelta(seconds=self.backoff_seconds(job.attempts))
            return True
        job.status = JobStatus.DEAD
        job.finished_at = now
        return False

    def overall_status(self, workflow: Workflow) -> WorkflowStatus:
        """Derive the workflow's honest overall status from its jobs.

        Paused/cancelled are sticky operator states and are decided by the
        service, not here; this computes RUNNING/COMPLETED/FAILED.
        """

        jobs = workflow.jobs
        if not jobs:
            return WorkflowStatus.PENDING
        if all(j.status is JobStatus.COMPLETED for j in jobs):
            return WorkflowStatus.COMPLETED
        blocked = any(j.status in (JobStatus.DEAD, JobStatus.BLOCKED) for j in jobs)
        in_flight = any(
            j.status in (JobStatus.PENDING, JobStatus.READY, JobStatus.RUNNING) for j in jobs
        )
        # No more progress possible once a stage is dead/blocked and nothing runnable.
        if blocked and not in_flight:
            return WorkflowStatus.FAILED
        return WorkflowStatus.RUNNING
