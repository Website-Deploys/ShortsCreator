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
from olympus.jobs.locks import LocalJobLockManager
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
        lock_manager: LocalJobLockManager | None = None,
        stale_after_seconds: float = 120.0,
    ) -> None:
        self._workflows = workflows
        self._lock = lock
        self._scheduler = scheduler
        self._repo = repository
        self._bus = event_bus
        self._leases = lock_manager
        self._stale_after = stale_after_seconds

    async def claim(self, worker_id: str) -> Job | None:
        events: list[WorkflowEvent] = []
        claimed: Job | None = None
        async with self._lock:
            now = utc_now()
            candidates: list[tuple[Job, Workflow]] = []
            for wf in self._workflows.values():
                if wf.status is not WorkflowStatus.RUNNING:
                    continue
                self._scheduler.reconcile(wf, now=now)
                for job in self._scheduler.runnable(wf, now=now):
                    candidates.append((job, wf))
            candidates.sort(key=lambda item: (-item[0].priority, item[0].created_at or now))
            selected: tuple[Job, Workflow] | None = None
            for candidate, workflow in candidates:
                if self._leases is not None:
                    acquired = await asyncio.to_thread(
                        self._leases.try_acquire,
                        f"job:{candidate.job_id}",
                        worker_id,
                        stale_after_seconds=self._stale_after,
                    )
                    if not acquired:
                        continue
                selected = (candidate, workflow)
                break
            if selected is not None:
                claimed, wf = selected
                claimed.status = JobStatus.RUNNING
                claimed.worker_id = worker_id
                claimed.started_at = now
                claimed.heartbeat_at = now
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
        lease_owner = job.worker_id
        try:
            async with self._lock:
                now = utc_now()
                wf = self._workflows.get(job.project_id)
                if wf is None:
                    return
                if job.status in (JobStatus.CANCELLED, JobStatus.CANCEL_REQUESTED):
                    self._cancel_job(
                        wf,
                        job,
                        now,
                        job.cancellation_reason or "cancel requested",
                    )
                    cancelled = self._event(
                        EventType.JOB_CANCELLED,
                        job,
                        f"job {job.stage} cancelled",
                    )
                    wf.record(cancelled)
                    events.append(cancelled)
                else:
                    checkpoint = result.get("checkpoint")
                    if isinstance(checkpoint, dict):
                        job.checkpoint = checkpoint
                        job.warnings = list(
                            dict.fromkeys(job.warnings + _strings(checkpoint.get("warnings")))
                        )
                    job.status = JobStatus.COMPLETED
                    job.finished_at = now
                    job.heartbeat_at = now
                    job.result = result
                    job.error = None
                    wf.updated_at = now
                    done = self._event(
                        EventType.JOB_COMPLETED,
                        job,
                        f"job {job.stage} completed",
                    )
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
        finally:
            await self._release(job, lease_owner)
        await self._emit(events)

    async def fail(self, job: Job, error: str) -> None:
        events: list[WorkflowEvent] = []
        lease_owner = job.worker_id
        try:
            async with self._lock:
                now = utc_now()
                wf = self._workflows.get(job.project_id)
                if wf is None:
                    return
                if job.status in (JobStatus.CANCELLED, JobStatus.CANCEL_REQUESTED):
                    self._cancel_job(wf, job, now, job.cancellation_reason or error)
                    event = self._event(
                        EventType.JOB_CANCELLED,
                        job,
                        f"job {job.stage} cancelled",
                    )
                else:
                    job.error = error
                    job.errors.append(error)
                    job.finished_at = now
                    job.heartbeat_at = now
                    job.status = JobStatus.FAILED
                    will_retry = self._scheduler.on_failure(job, now=now)
                    if will_retry:
                        event = self._event(
                            EventType.JOB_RETRYING,
                            job,
                            (
                                f"job {job.stage} failed "
                                f"(attempt {job.attempts}/{job.max_attempts}); retrying"
                            ),
                            detail={"error": error, "available_at": _iso(job.available_at)},
                        )
                    else:
                        event = self._event(
                            EventType.JOB_DEAD,
                            job,
                            f"job {job.stage} dead after {job.attempts} attempts",
                            detail={"error": error},
                        )
                wf.record(event)
                events.append(event)
                wf.updated_at = now
                self._scheduler.reconcile(wf, now=now)
                events += self._settle(wf)
                await self._repo.save(wf)
        finally:
            await self._release(job, lease_owner)
        await self._emit(events)

    async def requeue(self, job: Job, *, reason: str) -> None:
        events: list[WorkflowEvent] = []
        lease_owner = job.worker_id
        try:
            async with self._lock:
                now = utc_now()
                wf = self._workflows.get(job.project_id)
                if wf is None or job.is_terminal:
                    return
                job.status = JobStatus.READY
                job.worker_id = None
                job.started_at = None
                job.heartbeat_at = None
                wf.updated_at = now
                event = self._event(
                    EventType.JOB_READY,
                    job,
                    f"job {job.stage} requeued ({reason})",
                )
                wf.record(event)
                events.append(event)
                await self._repo.save(wf)
        finally:
            await self._release(job, lease_owner)
        await self._emit(events)

    async def heartbeat(self, job: Job, worker_id: str) -> None:
        async with self._lock:
            wf = self._workflows.get(job.project_id)
            if wf is None or job.worker_id != worker_id or job.is_terminal:
                return
            job.heartbeat_at = utc_now()
            wf.updated_at = job.heartbeat_at
            await self._repo.save(wf)
        if self._leases is not None:
            await asyncio.to_thread(
                self._leases.heartbeat,
                f"job:{job.job_id}",
                worker_id,
            )

    async def cancel(self, job: Job, *, reason: str) -> None:
        events: list[WorkflowEvent] = []
        lease_owner = job.worker_id
        try:
            async with self._lock:
                wf = self._workflows.get(job.project_id)
                if wf is None or job.status is JobStatus.CANCELLED:
                    return
                now = utc_now()
                self._cancel_job(wf, job, now, reason)
                event = self._event(
                    EventType.JOB_CANCELLED,
                    job,
                    f"job {job.stage} cancelled",
                )
                wf.record(event)
                events.append(event)
                await self._repo.save(wf)
        finally:
            await self._release(job, lease_owner)
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
            case JobStatus.CANCEL_REQUESTED:
                s.cancel_requested += 1
            case JobStatus.STALE:
                s.stale += 1

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
    def _cancel_job(wf: Workflow, job: Job, now: datetime, reason: str) -> None:
        job.status = JobStatus.CANCELLED
        job.finished_at = now
        job.heartbeat_at = now
        job.worker_id = None
        job.cancellation_requested = True
        job.cancellation_reason = reason
        wf.status = WorkflowStatus.CANCELLED
        wf.cancellation_requested = True
        for pending in wf.jobs:
            if pending is not job and not pending.is_terminal:
                pending.status = JobStatus.CANCELLED
                pending.finished_at = now
        wf.updated_at = now

    async def _release(self, job: Job, owner: str | None) -> None:
        if self._leases is None or not owner:
            return
        await asyncio.to_thread(
            self._leases.release,
            f"job:{job.job_id}",
            owner,
        )

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


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
