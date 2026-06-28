"""Workers and the worker pool - real, in-process job execution.

A :class:`Worker` is an async loop that claims a job from the queue, loads the
project, runs the bound engine via its runner, and reports the genuine outcome
back to the queue - heart-beating throughout so its liveness is observable. The
:class:`InMemoryWorkerRegistry` tracks every worker's registration and health.

The :class:`WorkerPool` runs N workers plus a health monitor that detects a lost
worker (crashed task or stale heartbeat), requeues the job it was running
(recovery), marks it offline, and starts a replacement (restart). Shutdown is
cooperative. Cross-process crash recovery (requeuing orphaned RUNNING jobs on
restart) is handled by the WorkflowService; this module handles in-process
worker health. The contracts allow a distributed worker tier to replace this.
"""

from __future__ import annotations

import asyncio
import contextlib

from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.workflow import EngineRunner, EventBus, JobQueue, WorkerRegistry
from olympus.domain.entities.workflow import (
    EventType,
    Job,
    WorkerInfo,
    WorkerStatus,
    Workflow,
    WorkflowEvent,
)
from olympus.platform.logging import get_logger
from olympus.utils import new_id, utc_now

log = get_logger(__name__)


class InMemoryWorkerRegistry(WorkerRegistry):
    """Tracks worker registration and health in process memory."""

    def __init__(self) -> None:
        self._workers: dict[str, WorkerInfo] = {}

    async def register(self, worker_id: str) -> WorkerInfo:
        info = self._workers.get(worker_id)
        if info is None:
            info = WorkerInfo(
                worker_id=worker_id,
                status=WorkerStatus.IDLE,
                registered_at=utc_now(),
                last_heartbeat=utc_now(),
            )
            self._workers[worker_id] = info
        return info

    async def heartbeat(self, worker_id: str, *, current_job_id: str | None) -> None:
        info = self._workers.get(worker_id)
        if info is None:
            return
        info.last_heartbeat = utc_now()
        info.current_job_id = current_job_id
        info.status = WorkerStatus.BUSY if current_job_id else WorkerStatus.IDLE

    async def mark_offline(self, worker_id: str) -> None:
        info = self._workers.get(worker_id)
        if info is not None:
            info.status = WorkerStatus.OFFLINE
            info.current_job_id = None

    async def list_workers(self) -> list[WorkerInfo]:
        return list(self._workers.values())

    def record_completion(self, worker_id: str, *, failed: bool) -> None:
        info = self._workers.get(worker_id)
        if info is None:
            return
        if failed:
            info.jobs_failed += 1
        else:
            info.jobs_completed += 1


class Worker:
    """One worker: claim -> run engine -> report, heart-beating throughout."""

    def __init__(
        self,
        worker_id: str,
        *,
        queue: JobQueue,
        runners: dict[str, EngineRunner],
        project_repo: ProjectRepository,
        registry: InMemoryWorkerRegistry,
        stop_event: asyncio.Event,
        idle_sleep: float = 0.02,
        heartbeat_interval: float = 0.5,
    ) -> None:
        self.worker_id = worker_id
        self._queue = queue
        self._runners = runners
        self._projects = project_repo
        self._registry = registry
        self._stop = stop_event
        self._idle = idle_sleep
        self._hb = heartbeat_interval

    async def run_forever(self) -> None:
        await self._registry.register(self.worker_id)
        while not self._stop.is_set():
            job = await self._queue.claim(self.worker_id)
            if job is None:
                await self._registry.heartbeat(self.worker_id, current_job_id=None)
                await asyncio.sleep(self._idle)
                continue
            await self._registry.heartbeat(self.worker_id, current_job_id=job.job_id)
            await self._execute(job)
            await self._registry.heartbeat(self.worker_id, current_job_id=None)

    async def _execute(self, job: Job) -> None:
        beat = asyncio.create_task(self._keepalive(job.job_id))
        try:
            project = await self._projects.get(job.project_id)
            runner = self._runners.get(job.engine)
            if project is None:
                await self._queue.fail(job, "project not found")
                self._registry.record_completion(self.worker_id, failed=True)
                return
            if runner is None:
                await self._queue.fail(job, f"no runner registered for engine '{job.engine}'")
                self._registry.record_completion(self.worker_id, failed=True)
                return
            result = await runner.run(project, job)
            if result.ok:
                await self._queue.complete(job, result.summary)
                self._registry.record_completion(self.worker_id, failed=False)
            else:
                await self._queue.fail(job, result.error or "engine reported failure")
                self._registry.record_completion(self.worker_id, failed=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._queue.fail(job, f"{type(exc).__name__}: {exc}")
            self._registry.record_completion(self.worker_id, failed=True)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def _keepalive(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._hb)
            await self._registry.heartbeat(self.worker_id, current_job_id=job_id)


class WorkerPool:
    """Runs N workers + a health monitor (recovery + restart) for one process."""

    def __init__(
        self,
        *,
        queue: JobQueue,
        runners: dict[str, EngineRunner],
        project_repo: ProjectRepository,
        registry: InMemoryWorkerRegistry,
        event_bus: EventBus,
        workflows: dict[str, Workflow],
        concurrency: int = 2,
        worker_timeout_seconds: float = 30.0,
        health_interval_seconds: float = 1.0,
    ) -> None:
        self._queue = queue
        self._runners = runners
        self._projects = project_repo
        self._registry = registry
        self._bus = event_bus
        self._workflows = workflows
        self._concurrency = max(1, concurrency)
        self._timeout = worker_timeout_seconds
        self._health_interval = health_interval_seconds
        self._stop = asyncio.Event()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._monitor: asyncio.Task[None] | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._stop = asyncio.Event()
        for _ in range(self._concurrency):
            self._spawn_worker()
        self._monitor = asyncio.create_task(self._monitor_loop())
        self._running = True
        log.info("worker_pool_started", concurrency=self._concurrency)

    def _spawn_worker(self) -> str:
        worker_id = new_id("worker")
        worker = Worker(
            worker_id,
            queue=self._queue,
            runners=self._runners,
            project_repo=self._projects,
            registry=self._registry,
            stop_event=self._stop,
        )
        self._tasks[worker_id] = asyncio.create_task(worker.run_forever())
        return worker_id

    async def stop(self) -> None:
        if not self._running:
            return
        self._stop.set()
        if self._monitor is not None:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
        for worker_id, task in list(self._tasks.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await self._registry.mark_offline(worker_id)
        self._tasks.clear()
        self._running = False
        log.info("worker_pool_stopped")

    async def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(self._health_interval)
            with contextlib.suppress(Exception):
                await self.check_health()

    async def check_health(self) -> None:
        """Detect lost workers, requeue their jobs, mark offline, and restart.

        Also callable directly (deterministic) in tests by ageing a worker's
        heartbeat.
        """

        now = utc_now()
        for info in await self._registry.list_workers():
            if info.status is WorkerStatus.OFFLINE:
                continue
            task = self._tasks.get(info.worker_id)
            crashed = task is not None and task.done()
            stale = (
                info.last_heartbeat is not None
                and (now - info.last_heartbeat).total_seconds() > self._timeout
            )
            if not (crashed or stale):
                continue
            await self._recover_worker(info, crashed=crashed)

    async def _recover_worker(self, info: WorkerInfo, *, crashed: bool) -> None:
        if info.current_job_id:
            job = self._find_job(info.current_job_id)
            if job is not None and not job.is_terminal:
                await self._queue.requeue(job, reason=f"worker {info.worker_id} lost")
        await self._registry.mark_offline(info.worker_id)
        old_task = self._tasks.pop(info.worker_id, None)
        if old_task is not None and not old_task.done():
            old_task.cancel()
        await self._bus.publish(
            WorkflowEvent(
                ts=utc_now(),
                type=EventType.WORKER_OFFLINE,
                message=f"worker {info.worker_id} offline ({'crashed' if crashed else 'stale'})",
                detail={"worker_id": info.worker_id},
            )
        )
        if not self._stop.is_set():
            new_id_ = self._spawn_worker()
            await self._bus.publish(
                WorkflowEvent(
                    ts=utc_now(),
                    type=EventType.WORKER_RECOVERED,
                    message=f"worker {new_id_} started to replace {info.worker_id}",
                    detail={"replaced": info.worker_id, "worker_id": new_id_},
                )
            )

    def _find_job(self, job_id: str) -> Job | None:
        for wf in self._workflows.values():
            job = wf.job_by_id(job_id)
            if job is not None:
                return job
        return None
