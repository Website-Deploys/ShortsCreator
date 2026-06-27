"""The Workflow Orchestration Engine - Olympus's central nervous system.

Coordinates the complete project lifecycle across every engine
(upload -> cognitive -> story -> virality -> planning -> editing -> rendering ->
optimization) as an explicit, recoverable graph of jobs executed by a pool of
workers. It owns scheduling, dependencies, priority, retries with backoff, dead
jobs, cancellation, pause/resume, crash recovery, an internal event bus, and live
status.

It *only orchestrates*: the sole bridge to real work is the engine runners, which
drive the existing engine services to genuine terminal states. It never
fabricates progress, never redesigns an engine, and never bypasses one - the
engines remain independently replaceable and their own APIs keep working. The
queue, event bus, and worker abstractions are shaped so a distributed
implementation (Redis, remote workers) can replace the in-process one later.
"""

from olympus.workflow.events import InMemoryEventBus
from olympus.workflow.queue import RepositoryJobQueue
from olympus.workflow.runners import (
    ServiceEngineRunner,
    UploadRunner,
    build_service_runner,
)
from olympus.workflow.scheduler import Scheduler
from olympus.workflow.workers import InMemoryWorkerRegistry, Worker, WorkerPool

__all__ = [
    "InMemoryEventBus",
    "InMemoryWorkerRegistry",
    "RepositoryJobQueue",
    "Scheduler",
    "ServiceEngineRunner",
    "UploadRunner",
    "Worker",
    "WorkerPool",
    "build_service_runner",
]
