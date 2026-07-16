"""Workflow orchestration contracts (ports).

These abstractions let the Workflow Engine persist state, queue and schedule
jobs, run engines, publish events, and track workers without binding to any
concrete technology. The current implementations are storage-backed and
in-process; each contract is shaped so a distributed implementation (e.g. a
Redis-backed queue, a remote worker tier) can replace it later without touching
the orchestration logic or any engine.

The Workflow Engine *only orchestrates*: the sole bridge to real work is
:class:`EngineRunner`, which drives an existing engine's service to a genuine
terminal state and reports it. No contract here produces fabricated progress.
"""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from olympus.domain.entities.project import Project
from olympus.domain.entities.workflow import Job, WorkerInfo, Workflow, WorkflowEvent


class WorkflowRepository(abc.ABC):
    """Durable persistence for workflows (the graph of jobs + history).

    One workflow per project. Persisting the whole workflow (jobs included) makes
    the system crash-recoverable: on restart, in-flight workflows are reloaded
    and resumed, finished jobs are never re-run, and cancelled jobs stay
    cancelled.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> Workflow | None:
        """Load a project's workflow, or ``None`` if none exists."""

    @abc.abstractmethod
    async def save(self, workflow: Workflow) -> None:
        """Persist the workflow (overwrites)."""

    @abc.abstractmethod
    async def list_active_project_ids(self) -> list[str]:
        """Return the project ids of all non-terminal workflows (for recovery)."""

    @abc.abstractmethod
    async def list_all(self) -> list[Workflow]:
        """Return every persisted workflow, including terminal jobs."""

    @abc.abstractmethod
    async def load_by_job_id(self, job_id: str) -> Workflow | None:
        """Load a workflow by its durable top-level job id."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete a project's workflow (idempotent)."""


@dataclass(slots=True)
class QueueStats:
    """A snapshot of the queue/scheduler state for observability."""

    ready: int = 0
    running: int = 0
    pending: int = 0
    delayed: int = 0
    completed: int = 0
    failed: int = 0
    dead: int = 0
    blocked: int = 0
    cancelled: int = 0
    cancel_requested: int = 0
    stale: int = 0
    active_workflows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "running": self.running,
            "pending": self.pending,
            "delayed": self.delayed,
            "completed": self.completed,
            "failed": self.failed,
            "dead": self.dead,
            "blocked": self.blocked,
            "cancelled": self.cancelled,
            "cancel_requested": self.cancel_requested,
            "stale": self.stale,
            "active_workflows": self.active_workflows,
        }


class JobQueue(abc.ABC):
    """A queue of runnable jobs across all active workflows.

    Supports FIFO, priority ordering, delayed/scheduled jobs (via a job's
    ``available_at``/``scheduled_for``), and dependency gating (a job is only
    claimable once its dependencies have completed). The current implementation
    is storage-backed and claims atomically in-process; the contract is
    deliberately Redis-friendly (``claim``/``complete``/``fail``/``requeue``).
    """

    @abc.abstractmethod
    async def claim(self, worker_id: str) -> Job | None:
        """Atomically claim the next runnable job for a worker, or ``None``."""

    @abc.abstractmethod
    async def complete(self, job: Job, result: dict[str, Any]) -> None:
        """Mark a claimed job completed with its result."""

    @abc.abstractmethod
    async def fail(self, job: Job, error: str) -> None:
        """Mark a claimed job failed; the scheduler decides retry vs. dead."""

    @abc.abstractmethod
    async def requeue(self, job: Job, *, reason: str) -> None:
        """Return a job to the runnable pool (e.g. after worker loss)."""

    @abc.abstractmethod
    async def heartbeat(self, job: Job, worker_id: str) -> None:
        """Persist a running job heartbeat and renew its local lease."""

    @abc.abstractmethod
    async def cancel(self, job: Job, *, reason: str) -> None:
        """Acknowledge cooperative cancellation at a safe execution point."""

    @abc.abstractmethod
    async def stats(self) -> QueueStats:
        """Return a snapshot of queue/scheduler counts."""


class EventBus(abc.ABC):
    """An internal publish/subscribe event bus (future plugins subscribe here)."""

    @abc.abstractmethod
    def subscribe(self, handler: Callable[[WorkflowEvent], Awaitable[None]]) -> None:
        """Register an async handler invoked for every published event."""

    @abc.abstractmethod
    async def publish(self, event: WorkflowEvent) -> None:
        """Publish an event to all subscribers (handler errors are isolated)."""


@dataclass(slots=True)
class EngineRunResult:
    """The genuine terminal outcome of driving one engine for a project."""

    status: str  # "completed" | "failed" | "cancelled"
    summary: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class EngineRunner(abc.ABC):
    """The single bridge from orchestration to real engine work.

    A runner drives one engine (via its existing service) to a *genuine* terminal
    state and reports it. It never simulates work and never marks an engine done
    speculatively. Runners are idempotent: driving an engine that already
    finished simply observes its completed state (so the Workflow Engine
    coexists with the engines' own completion chaining without double work).
    """

    #: The engine/stage this runner executes.
    engine: str = ""

    @abc.abstractmethod
    async def run(self, project: Project, job: Job) -> EngineRunResult:
        """Drive the engine for ``project`` to completion and report the outcome."""


class WorkerRegistry(abc.ABC):
    """Tracks worker registration and health for recovery and observability."""

    @abc.abstractmethod
    async def register(self, worker_id: str) -> WorkerInfo:
        """Register a worker (or return the existing registration)."""

    @abc.abstractmethod
    async def heartbeat(self, worker_id: str, *, current_job_id: str | None) -> None:
        """Record a worker's liveness and its current job."""

    @abc.abstractmethod
    async def mark_offline(self, worker_id: str) -> None:
        """Mark a worker offline (missed heartbeats / shutdown)."""

    @abc.abstractmethod
    async def list_workers(self) -> list[WorkerInfo]:
        """Return all known workers and their health."""
