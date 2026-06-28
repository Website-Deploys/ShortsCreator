"""The repository-backed job queue.

Operates over the set of *active* workflows held in memory (and mirrored to the
workflow repository for crash recovery). Claims are atomic within the process via
a single async lock; the queue selects the globally best runnable job across all
active workflows (priority desc, then FIFO), respecting dependency gating and
delayed/scheduled timers through the :class:`Scheduler`.

Every transition is persisted immediately (so a crash loses no decisions) and
emitted on the event bus after the lock is released (so a subscriber can never
deadlock the queue). The contract is Redis-friendly: a distributed
implementation can replace this without changing workers or the service.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from olympus.domain.contracts.workflow import (
    EventBus,
    JobQueue,
    QueueStats,
    WorkflowRepository,
)
from olympus.domain.entities.workflow import (
    STAGE_FINISHED_NAMES,
    EventType,
    Job,
    JobStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)
from olympus.platform.logging import get_logger
from olympus.utils import utc_now
from olympus.workflow.scheduler import Scheduler

log = get_logger(__name__)


class RepositoryJobQueue(JobQueue):
    """Atomic, dependency-aware job queue over the active in-memory workflows."""

    def __init__(
        self,
        *,
        workflows: dict[str, Workflow],
        lock: asyncio.Lock,
        scheduler: Scheduler,
        repository: WorkflowRepository,
        event_bus: EventBus,
    ) -> None:
        self._workflows = workflows
        self._lock = lock
        self._scheduler = scheduler
        self._repo = repository
        self._bus = event_bus

    async def claim(self, worker_id: str) -> Job | None:
        events: list[WorkflowEvent] = []
        claimed: Job | None = None
        async with self._lock:
            now = utc_now()
            best: tuple[Job, Workflow] | None = None
            for wf in self._workflows.values():
                if wf.status is not WorkflowStatus.RUNNING:
                    continue
                self._scheduler.reconcile(wf, now=now)
                for job in self._scheduler.runnable(wf, now=now):
                    if best is None or self._better(job, best[0], now):
                        best = (job, wf)
            if best is not None:
                claimed, wf = best
                claimed.status = JobStatus.RUNNING
                claimed.worker_id = worker_id
                claimed.started_at = now
                claimed.attempts += 1
                wf.updated_at = now
                event = self._event(
                    EventType.JOB_STARTED, claimed, f"job {claimed.stage} started on {worker_id}"
                )
                wf.record(event)
                events.append(event)
                await self._repo.save(wf)
        await self._emit(events)
        return claimed

    @staticmethod
    def _better(candidate: Job, current: Job, now: datetime) -> bool:
        ckey = (-candidate.priority, candidate.created_at or now)
        bkey = (-current.priority, current.created_at or now)
        return ckey < bkey

    async def complete(self, job: Job, result: dict[str, Any]) -> None:
        events: list[WorkflowEvent] = []
        async with self._lock:
            now = utc_now()
            wf = self._workflows.get(job.project_id)
            if wf is None:
                return
            # Respect cancellation: a finishing worker never resurrects a
            # cancelled job ("cancelled jobs stay cancelled").
            if job.status is JobStatus.CANCELLED:
                return
            job.status = JobStatus.COMPLETED
            job.finished_at = now
            job.result = result
            job.error = None
            wf.updated_at = now
            done = self._event(EventType.JOB_COMPLETED, job, f"job {job.stage} completed")
            stage_done = self._event(
                EventType.STAGE_FINISHED,
                job,
                f"{STAGE_FINISHED_NAMES.get(job.stage, job.stage)}",
                detail={"name": STAGE_FINISHED_NAMES.get(job.stage, job.stage)},
            )
            wf.record(done)
            wf.record(stage_done)
            events += [done, stage_done]
            self._scheduler.reconcile(wf, now=now)
            events += self._settle(wf)
            await self._repo.save(wf)
        await self._emit(events)

    async def fail(self, job: Job, error: str) -> None:
        events: list[WorkflowEvent] = []
        async with self._lock:
            now = utc_now()
            wf = self._workflows.get(job.project_id)
            if wf is None:
                return
            if job.status is JobStatus.CANCELLED:
                return
            job.error = error
            job.finished_at = now
            job.status = JobStatus.FAILED
            will_retry = self._scheduler.on_failure(job, now=now)
            if will_retry:
                ev = self._event(
                    EventType.JOB_RETRYING,
                    job,
                    f"job {job.stage} failed (attempt {job.attempts}/{job.max_attempts}); retrying",
                    detail={"error": error, "available_at": _iso(job.available_at)},
                )
            else:
                ev = self._event(
                    EventType.JOB_DEAD,
                    job,
                    f"job {job.stage} dead after {job.attempts} attempts",
                    detail={"error": error},
                )
            wf.record(ev)
            events.append(ev)
            wf.updated_at = now
            self._scheduler.reconcile(wf, now=now)
            events += self._settle(wf)
            await self._repo.save(wf)
        await self._emit(events)

    async def requeue(self, job: Job, *, reason: str) -> None:
        events: list[WorkflowEvent] = []
        async with self._lock:
            now = utc_now()
            wf = self._workflows.get(job.project_id)
            if wf is None or job.is_terminal:
                return
            job.status = JobStatus.READY
            job.worker_id = None
            job.started_at = None
            wf.updated_at = now
            ev = self._event(EventType.JOB_READY, job, f"job {job.stage} requeued ({reason})")
            wf.record(ev)
            events.append(ev)
            await self._repo.save(wf)
        await self._emit(events)

    async def stats(self) -> QueueStats:
        async with self._lock:
            s = QueueStats()
            now = utc_now()
            for wf in self._workflows.values():
                if wf.status is WorkflowStatus.RUNNING:
                    s.active_workflows += 1
                for job in wf.jobs:
                    self._tally(s, job, now)
            return s

    @staticmethod
    def _tally(s: QueueStats, job: Job, now: datetime) -> None:
        match job.status:
            case JobStatus.READY:
                s.ready += 1
            case JobStatus.RUNNING:
                s.running += 1
            case JobStatus.PENDING:
                if job.available_at is not None and now < job.available_at:
                    s.delayed += 1
                else:
                    s.pending += 1
            case JobStatus.COMPLETED:
                s.completed += 1
            case JobStatus.FAILED:
                s.failed += 1
            case JobStatus.DEAD:
                s.dead += 1
            case JobStatus.BLOCKED:
                s.blocked += 1
            case JobStatus.CANCELLED:
                s.cancelled += 1

    def _settle(self, wf: Workflow) -> list[WorkflowEvent]:
        """Recompute the workflow's overall status; emit terminal events."""

        events: list[WorkflowEvent] = []
        if wf.status in (WorkflowStatus.PAUSED, WorkflowStatus.CANCELLED):
            return events
        overall = self._scheduler.overall_status(wf)
        if overall is WorkflowStatus.COMPLETED and wf.status is not WorkflowStatus.COMPLETED:
            wf.status = WorkflowStatus.COMPLETED
            ev = WorkflowEvent(
                ts=utc_now(), type=EventType.WORKFLOW_COMPLETED, message="workflow completed"
            )
            wf.record(ev)
            events.append(ev)
        elif overall is WorkflowStatus.FAILED and wf.status is not WorkflowStatus.FAILED:
            wf.status = WorkflowStatus.FAILED
            ev = WorkflowEvent(
                ts=utc_now(), type=EventType.WORKFLOW_FAILED, message="workflow failed"
            )
            wf.record(ev)
            events.append(ev)
        return events

    @staticmethod
    def _event(
        etype: EventType, job: Job, message: str, *, detail: dict[str, Any] | None = None
    ) -> WorkflowEvent:
        return WorkflowEvent(
            ts=utc_now(),
            type=etype,
            message=message,
            stage=job.stage,
            job_id=job.job_id,
            detail=detail or {},
        )

    async def _emit(self, events: list[WorkflowEvent]) -> None:
        for event in events:
            await self._bus.publish(event)


def _iso(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None
