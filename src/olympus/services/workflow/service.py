"""The Workflow service - the orchestration boundary of Olympus.

This service owns the complete lifecycle of every project as a recoverable graph
of jobs, and is the one place that coordinates the engines. It composes the
durable repository, the in-memory active-workflow cache, the scheduler, the job
queue, the event bus, the worker registry, and the worker pool, and exposes the
operator surface: start / pause / resume / cancel, status & history, per-job
status & logs, retry-job & retry-workflow, worker and scheduler introspection,
and crash recovery.

It *only orchestrates*. The sole bridge to real work is the engine runners, which
drive the existing engine services to genuine terminal states. It never
fabricates progress, never re-runs finished jobs, and never resurrects cancelled
ones. The engines and their APIs are untouched.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.workflow import EngineRunner, WorkflowRepository
from olympus.domain.entities.project import Project
from olympus.domain.entities.workflow import (
    WORKFLOW_STAGES,
    EventType,
    Job,
    JobPriority,
    JobStatus,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)
from olympus.jobs.checkpoints import CheckpointValidator
from olympus.jobs.contracts import workflow_to_durable_job
from olympus.jobs.locks import LocalJobLockManager
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.utils import new_id, utc_now
from olympus.workflow import (
    InMemoryEventBus,
    InMemoryWorkerRegistry,
    RepositoryJobQueue,
    Scheduler,
    WorkerPool,
)

log = get_logger(__name__)


class WorkflowService:
    """Coordinates the full project lifecycle across every engine."""

    def __init__(
        self,
        *,
        repository: WorkflowRepository,
        project_repo: ProjectRepository,
        runners: dict[str, EngineRunner],
        concurrency: int = 2,
        max_attempts: int = 3,
        backoff_base_seconds: float = 2.0,
        heartbeat_interval_seconds: float = 10.0,
        stale_after_seconds: float = 120.0,
        run_in_process: bool = True,
        worker_poll_interval_seconds: float = 0.02,
        lock_manager: LocalJobLockManager | None = None,
        checkpoint_validator: CheckpointValidator | None = None,
        max_logs_tail_chars: int = 8000,
    ) -> None:
        self._repo = repository
        self._projects = project_repo
        self._runners = runners
        self._max_attempts = max_attempts
        self._stale_after_seconds = stale_after_seconds
        self._run_in_process = run_in_process
        self._leases = lock_manager
        self._checkpoints = checkpoint_validator
        self._max_logs_tail_chars = max_logs_tail_chars

        self._workflows: dict[str, Workflow] = {}
        self._lock = asyncio.Lock()
        self._scheduler = Scheduler(backoff_base_seconds=backoff_base_seconds)
        self._bus = InMemoryEventBus()
        self._registry = InMemoryWorkerRegistry()
        self._queue = RepositoryJobQueue(
            workflows=self._workflows,
            lock=self._lock,
            scheduler=self._scheduler,
            repository=repository,
            event_bus=self._bus,
            lock_manager=lock_manager,
            stale_after_seconds=stale_after_seconds,
        )
        self._pool = WorkerPool(
            queue=self._queue,
            runners=runners,
            project_repo=project_repo,
            registry=self._registry,
            event_bus=self._bus,
            workflows=self._workflows,
            concurrency=concurrency,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            worker_timeout_seconds=stale_after_seconds,
            idle_sleep=worker_poll_interval_seconds,
            checkpoint_validator=checkpoint_validator,
        )

    # -- event subscription (plugins) ----------------------------------------
    def subscribe(self, handler: Callable[[WorkflowEvent], Awaitable[None]]) -> None:
        self._bus.subscribe(handler)

    # -- pool lifecycle -------------------------------------------------------
    def start_pool(self, *, force: bool = False) -> bool:
        if not self._run_in_process and not force:
            return False
        self._pool.start()
        return True

    async def stop_pool(self) -> None:
        await self._pool.stop()

    # -- workflow construction ------------------------------------------------
    def _build_workflow(
        self,
        project: Project,
        *,
        requested_by: str = "api",
        source: str = "project",
        idempotency_key: str | None = None,
    ) -> Workflow:
        now = utc_now()
        workflow_id = new_id("wf")
        jobs = [
            Job(
                job_id=new_id("job"),
                workflow_id=workflow_id,
                project_id=project.id,
                engine=spec.engine,
                stage=spec.stage,
                priority=int(JobPriority.NORMAL),
                status=JobStatus.PENDING,
                depends_on=spec.depends_on,
                max_attempts=self._max_attempts,
                created_at=now,
            )
            for spec in WORKFLOW_STAGES
        ]
        return Workflow(
            workflow_id=workflow_id,
            project_id=project.id,
            status=WorkflowStatus.PENDING,
            created_at=now,
            updated_at=now,
            jobs=jobs,
            requested_by=requested_by,
            source=source,
            idempotency_key=idempotency_key or f"project_pipeline:{project.id}",
        )

    async def _get_cached_or_load(self, project_id: str) -> Workflow | None:
        wf = self._workflows.get(project_id)
        if wf is not None:
            return wf
        wf = await self._repo.load(project_id)
        if wf is not None:
            self._workflows[project_id] = wf
        return wf

    # -- start / resume -------------------------------------------------------
    async def start(
        self,
        project: Project,
        *,
        restart: bool = False,
        requested_by: str = "api",
        source: str = "project",
        idempotency_key: str | None = None,
    ) -> Workflow:
        """Create (or resume) the project's workflow and begin execution."""

        events: list[WorkflowEvent] = []
        creation_lock: tuple[str, str] | None = None
        try:
            async with self._lock:
                wf = await self._get_cached_or_load(project.id)
                if wf is None or restart:
                    candidate = self._build_workflow(
                        project,
                        requested_by=requested_by,
                        source=source,
                        idempotency_key=idempotency_key,
                    )
                    if self._leases is not None:
                        lock_key = f"create:project_pipeline:{project.id}"
                        acquired = await asyncio.to_thread(
                            self._leases.try_acquire,
                            lock_key,
                            candidate.workflow_id,
                            stale_after_seconds=self._stale_after_seconds,
                        )
                        if not acquired:
                            concurrent = await self._repo.load(project.id)
                            if concurrent is not None:
                                self._workflows[project.id] = concurrent
                                return concurrent
                            raise ValidationError(
                                "A project pipeline job is already being created.",
                                details={"project_id": project.id},
                            )
                        creation_lock = (lock_key, candidate.workflow_id)
                    wf = candidate
                self._workflows[project.id] = wf
                if wf.status in (
                    WorkflowStatus.COMPLETED,
                    WorkflowStatus.FAILED,
                    WorkflowStatus.CANCELLED,
                ):
                    return wf  # use retry_workflow to re-run a finished workflow
                wf.status = WorkflowStatus.RUNNING
                wf.updated_at = utc_now()
                self._scheduler.reconcile(wf, now=utc_now())
                ev = WorkflowEvent(
                    ts=utc_now(), type=EventType.WORKFLOW_STARTED, message="workflow started"
                )
                wf.record(ev)
                events.append(ev)
                await self._repo.save(wf)
        finally:
            if self._leases is not None and creation_lock is not None:
                await asyncio.to_thread(self._leases.release, *creation_lock)
        self.start_pool()
        await self._emit(events)
        return wf

    async def resume(self, project_id: str) -> Workflow:
        events: list[WorkflowEvent] = []
        async with self._lock:
            wf = await self._require(project_id)
            if any(job.status is JobStatus.CANCEL_REQUESTED for job in wf.jobs):
                raise ValidationError(
                    "Cancellation is still pending; resume after the active stage stops.",
                    details={"project_id": project_id},
                )
            if wf.status in (
                WorkflowStatus.PAUSED,
                WorkflowStatus.CANCELLED,
                WorkflowStatus.FAILED,
            ):
                if wf.status in (WorkflowStatus.CANCELLED, WorkflowStatus.FAILED):
                    await self._prepare_resume(wf)
                wf.status = WorkflowStatus.RUNNING
                wf.cancellation_requested = False
                wf.cancellation_requested_at = None
                wf.cancellation_reason = None
                wf.updated_at = utc_now()
                self._scheduler.reconcile(wf, now=utc_now())
                ev = WorkflowEvent(
                    ts=utc_now(), type=EventType.WORKFLOW_RESUMED, message="workflow resumed"
                )
                wf.record(ev)
                events.append(ev)
                await self._repo.save(wf)
        self.start_pool()
        await self._emit(events)
        return await self._require_cached(project_id)

    # -- pause / cancel -------------------------------------------------------
    async def pause(self, project_id: str) -> Workflow:
        return await self._transition(
            project_id,
            allowed={WorkflowStatus.RUNNING, WorkflowStatus.PENDING},
            new_status=WorkflowStatus.PAUSED,
            event=EventType.WORKFLOW_PAUSED,
            message="workflow paused",
        )

    async def cancel(self, project_id: str) -> Workflow:
        events: list[WorkflowEvent] = []
        async with self._lock:
            wf = await self._require(project_id)
            if wf.status in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED):
                return wf
            now = utc_now()
            wf.status = WorkflowStatus.CANCELLED
            wf.cancellation_requested = True
            wf.cancellation_requested_at = now
            wf.cancellation_reason = "cancelled by operator"
            for job in wf.jobs:
                if not job.is_terminal:
                    job.cancellation_requested = True
                    job.cancellation_requested_at = now
                    job.cancellation_reason = wf.cancellation_reason
                    if job.status is JobStatus.RUNNING:
                        job.status = JobStatus.CANCEL_REQUESTED
                    else:
                        job.status = JobStatus.CANCELLED
                        job.finished_at = now
            wf.updated_at = now
            ev = WorkflowEvent(
                ts=now,
                type=EventType.WORKFLOW_CANCELLED,
                message="workflow cancellation requested",
            )
            wf.record(ev)
            events.append(ev)
            await self._repo.save(wf)
        await self._emit(events)
        return await self._require_cached(project_id)

    async def _transition(
        self,
        project_id: str,
        *,
        allowed: set[WorkflowStatus],
        new_status: WorkflowStatus,
        event: EventType,
        message: str,
    ) -> Workflow:
        events: list[WorkflowEvent] = []
        async with self._lock:
            wf = await self._require(project_id)
            if wf.status in allowed:
                wf.status = new_status
                wf.updated_at = utc_now()
                ev = WorkflowEvent(ts=utc_now(), type=event, message=message)
                wf.record(ev)
                events.append(ev)
                await self._repo.save(wf)
        await self._emit(events)
        return await self._require_cached(project_id)

    # -- retry ----------------------------------------------------------------
    async def retry_job(self, project_id: str, job_id: str) -> Workflow:
        async with self._lock:
            wf = await self._require(project_id)
            job = wf.job_by_id(job_id)
            if job is None:
                raise NotFoundError("Job not found.", details={"job_id": job_id})
            if job.status not in (JobStatus.FAILED, JobStatus.DEAD, JobStatus.BLOCKED):
                raise ValidationError(
                    "Only failed, dead, or blocked jobs can be retried.",
                    details={"job_id": job_id, "status": job.status.value},
                )
            self._reset_job(job)
            # Unblock downstream jobs so the workflow can proceed past the retry.
            for downstream in wf.jobs:
                if downstream.status is JobStatus.BLOCKED:
                    self._reset_job(downstream)
            if wf.status is WorkflowStatus.FAILED:
                wf.status = WorkflowStatus.RUNNING
            wf.retry_count += 1
            wf.updated_at = utc_now()
            self._scheduler.reconcile(wf, now=utc_now())
            wf.record(
                WorkflowEvent(
                    ts=utc_now(),
                    type=EventType.JOB_READY,
                    message=f"job {job.stage} retried by operator",
                    stage=job.stage,
                    job_id=job.job_id,
                )
            )
            await self._repo.save(wf)
        self.start_pool()
        return await self._require_cached(project_id)

    async def retry_workflow(self, project_id: str) -> Workflow:
        async with self._lock:
            wf = await self._require(project_id)
            changed = False
            for job in wf.jobs:
                if job.status in (JobStatus.FAILED, JobStatus.DEAD, JobStatus.BLOCKED):
                    self._reset_job(job)
                    changed = True
            if not changed:
                return wf
            wf.status = WorkflowStatus.RUNNING
            wf.retry_count += 1
            wf.updated_at = utc_now()
            self._scheduler.reconcile(wf, now=utc_now())
            wf.record(
                WorkflowEvent(
                    ts=utc_now(),
                    type=EventType.WORKFLOW_RESUMED,
                    message="workflow retried by operator",
                )
            )
            await self._repo.save(wf)
        self.start_pool()
        return await self._require_cached(project_id)

    @staticmethod
    def _reset_job(job: Job) -> None:
        job.status = JobStatus.PENDING
        job.attempts = 0
        job.error = None
        job.finished_at = None
        job.started_at = None
        job.available_at = None
        job.worker_id = None
        job.heartbeat_at = None
        job.cancellation_requested = False
        job.cancellation_requested_at = None
        job.cancellation_reason = None

    # -- recovery -------------------------------------------------------------
    async def recover(self) -> int:
        """Reload non-terminal workflows and requeue orphaned RUNNING jobs.

        Called on startup. A job that was ``RUNNING`` when the process died has no
        live worker, so it is returned to ``READY`` to be picked up again.
        Finished jobs are left untouched (never re-run); cancelled stay cancelled.
        """

        recovered = 0
        async with self._lock:
            for project_id in await self._repo.list_active_project_ids():
                wf = await self._repo.load(project_id)
                if wf is None:
                    continue
                project = await self._projects.get(project_id)
                if project is not None:
                    await self._validate_completed_checkpoints(wf, project)
                for job in wf.jobs:
                    if job.status in {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED} and (
                        wf.cancellation_requested or job.cancellation_requested
                    ):
                        now = utc_now()
                        job.status = JobStatus.CANCELLED
                        job.finished_at = now
                        job.worker_id = None
                        job.heartbeat_at = now
                        wf.status = WorkflowStatus.CANCELLED
                        wf.stale_running_detected = True
                        wf.recovery_reason = (
                            f"Stage {job.stage} cancellation finalized after restart."
                        )
                        wf.updated_at = now
                        if self._leases is not None:
                            await asyncio.to_thread(
                                self._leases.force_release,
                                f"job:{job.job_id}",
                            )
                        recovered += 1
                        wf.record(
                            WorkflowEvent(
                                ts=now,
                                type=EventType.JOB_CANCELLED,
                                message=(
                                    f"job {job.stage} cancellation finalized after restart"
                                ),
                                stage=job.stage,
                                job_id=job.job_id,
                            )
                        )
                    elif job.status is JobStatus.RUNNING:
                        job.status = JobStatus.STALE
                        wf.stale_running_detected = True
                        wf.recovery_reason = (
                            f"Stage {job.stage} lost its in-process worker during restart."
                        )
                        wf.record(
                            WorkflowEvent(
                                ts=utc_now(),
                                type=EventType.JOB_STALE,
                                message=f"job {job.stage} marked stale after restart",
                                stage=job.stage,
                                job_id=job.job_id,
                            )
                        )
                        if self._leases is not None:
                            await asyncio.to_thread(
                                self._leases.force_release,
                                f"job:{job.job_id}",
                            )
                        job.status = JobStatus.READY
                        job.worker_id = None
                        job.started_at = None
                        job.heartbeat_at = None
                        recovered += 1
                        wf.record(
                            WorkflowEvent(
                                ts=utc_now(),
                                type=EventType.JOB_READY,
                                message=f"job {job.stage} requeued after restart",
                                stage=job.stage,
                                job_id=job.job_id,
                            )
                        )
                self._workflows[project_id] = wf
                await self._repo.save(wf)
        if self._workflows:
            self.start_pool()
        log.info("workflow_recovery", recovered_jobs=recovered, workflows=len(self._workflows))
        return recovered

    # -- read -----------------------------------------------------------------
    async def get(self, project_id: str) -> Workflow | None:
        return await self._get_cached_or_load(project_id)

    async def list_jobs(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        persisted = await self._repo.list_all()
        by_id = {item.workflow_id: item for item in persisted}
        by_id.update({item.workflow_id: item for item in self._workflows.values()})
        workflows = sorted(by_id.values(), key=lambda item: item.created_at, reverse=True)
        jobs = [
            workflow_to_durable_job(item, max_logs_tail_chars=self._max_logs_tail_chars)
            for item in workflows
            if project_id is None or item.project_id == project_id
        ]
        return [item for item in jobs if status is None or item["status"] == status]

    async def get_durable_job(self, job_id: str) -> dict[str, Any] | None:
        workflow = self._cached_by_job_id(job_id) or await self._repo.load_by_job_id(job_id)
        if workflow is None:
            return None
        return workflow_to_durable_job(
            workflow,
            max_logs_tail_chars=self._max_logs_tail_chars,
        )

    async def cancel_by_job_id(self, job_id: str) -> dict[str, Any]:
        workflow = await self._require_job(job_id)
        updated = await self.cancel(workflow.project_id)
        return workflow_to_durable_job(updated, max_logs_tail_chars=self._max_logs_tail_chars)

    async def retry_by_job_id(self, job_id: str) -> dict[str, Any]:
        workflow = await self._require_job(job_id)
        updated = await self.retry_workflow(workflow.project_id)
        return workflow_to_durable_job(updated, max_logs_tail_chars=self._max_logs_tail_chars)

    async def resume_by_job_id(self, job_id: str) -> dict[str, Any]:
        workflow = await self._require_job(job_id)
        updated = await self.resume(workflow.project_id)
        return workflow_to_durable_job(updated, max_logs_tail_chars=self._max_logs_tail_chars)

    async def durable_events(self, job_id: str) -> list[dict[str, Any]] | None:
        workflow = self._cached_by_job_id(job_id) or await self._repo.load_by_job_id(job_id)
        return [event.to_dict() for event in workflow.history] if workflow is not None else None

    async def durable_logs(self, job_id: str) -> list[dict[str, Any]] | None:
        workflow = self._cached_by_job_id(job_id) or await self._repo.load_by_job_id(job_id)
        if workflow is None:
            return None
        return [
            {**line.to_dict(), "stage": job.stage, "stage_id": job.job_id}
            for job in workflow.jobs
            for line in job.logs
        ]

    async def history(self, project_id: str) -> list[WorkflowEvent] | None:
        wf = await self._get_cached_or_load(project_id)
        return wf.history if wf is not None else None

    async def get_job(self, project_id: str, job_id: str) -> Job | None:
        wf = await self._get_cached_or_load(project_id)
        return wf.job_by_id(job_id) if wf is not None else None

    async def job_logs(self, project_id: str, job_id: str) -> list[dict[str, Any]] | None:
        job = await self.get_job(project_id, job_id)
        return [line.to_dict() for line in job.logs] if job is not None else None

    async def workers(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in await self._registry.list_workers()]

    async def scheduler_status(self) -> dict[str, Any]:
        stats = await self._queue.stats()
        return {
            "queue": stats.to_dict(),
            "pool_running": self._pool.running,
            "worker_count": len(await self._registry.list_workers()),
        }

    async def delete(self, project_id: str) -> None:
        async with self._lock:
            wf = self._workflows.get(project_id)
            if wf is not None and wf.status not in (
                WorkflowStatus.COMPLETED,
                WorkflowStatus.CANCELLED,
                WorkflowStatus.FAILED,
            ):
                wf.status = WorkflowStatus.CANCELLED
                for job in wf.jobs:
                    if not job.is_terminal:
                        job.status = JobStatus.CANCELLED
            self._workflows.pop(project_id, None)
            await self._repo.delete(project_id)

    # -- test/operational helper ---------------------------------------------
    async def wait_for(self, project_id: str, *, timeout: float = 10.0) -> Workflow:
        """Wait until the workflow reaches a terminal state (or timeout)."""

        waited = 0.0
        step = 0.02
        while waited < timeout:
            async with self._lock:
                wf = await self._get_cached_or_load(project_id)
            if wf is not None and wf.status in (
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            ):
                return wf
            await asyncio.sleep(step)
            waited += step
        return await self._require_cached(project_id)

    # -- helpers --------------------------------------------------------------
    async def _require(self, project_id: str) -> Workflow:
        wf = await self._get_cached_or_load(project_id)
        if wf is None:
            raise NotFoundError("No workflow for this project.", details={"id": project_id})
        return wf

    async def _require_cached(self, project_id: str) -> Workflow:
        wf = self._workflows.get(project_id) or await self._repo.load(project_id)
        if wf is None:
            raise NotFoundError("No workflow for this project.", details={"id": project_id})
        return wf

    async def _require_job(self, job_id: str) -> Workflow:
        workflow = self._cached_by_job_id(job_id) or await self._repo.load_by_job_id(job_id)
        if workflow is None:
            raise NotFoundError("Durable job not found.", details={"job_id": job_id})
        self._workflows[workflow.project_id] = workflow
        return workflow

    def _cached_by_job_id(self, job_id: str) -> Workflow | None:
        return next(
            (
                workflow
                for workflow in self._workflows.values()
                if workflow.workflow_id == job_id
            ),
            None,
        )

    async def _prepare_resume(self, workflow: Workflow) -> None:
        project = await self._projects.get(workflow.project_id)
        if project is not None:
            await self._validate_completed_checkpoints(workflow, project)
        for job in workflow.jobs:
            if job.status in (
                JobStatus.CANCELLED,
                JobStatus.CANCEL_REQUESTED,
                JobStatus.STALE,
                JobStatus.FAILED,
                JobStatus.DEAD,
                JobStatus.BLOCKED,
            ):
                self._reset_job(job)
        self._scheduler.reconcile(workflow, now=utc_now())

    async def _validate_completed_checkpoints(
        self,
        workflow: Workflow,
        project: Project,
    ) -> None:
        if self._checkpoints is None:
            return
        invalid_at: int | None = None
        for index, job in enumerate(workflow.jobs):
            if job.status is not JobStatus.COMPLETED:
                continue
            checkpoint = (
                await self._checkpoints.validate_existing(job, workflow.project_id)
                if job.checkpoint
                else await self._checkpoints.inspect(project, job)
            )
            job.checkpoint = checkpoint
            if not checkpoint.get("valid"):
                invalid_at = index
                warning = f"Checkpoint for {job.stage} is missing, stale, or invalid."
                job.warnings.append(warning)
                workflow.result_warnings.append(warning)
                break
        if invalid_at is None:
            return
        for job in workflow.jobs[invalid_at:]:
            self._reset_job(job)
        workflow.recovery_reason = f"Resuming from {workflow.jobs[invalid_at].stage}."

    async def _emit(self, events: list[WorkflowEvent]) -> None:
        for event in events:
            await self._bus.publish(event)
