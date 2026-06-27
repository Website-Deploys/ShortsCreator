"""Workflow orchestration entities - the central lifecycle model of Olympus.

Every prior engine runs independently. The Workflow Engine is the coordination
layer that owns a project's *complete* lifecycle as an explicit, recoverable
graph of jobs - one job per engine stage - executed in dependency order by a
pool of workers. It orchestrates; it never does an engine's work itself and it
never fabricates progress (a job reflects the real terminal state of the engine
it drove).

These are technology-free dataclasses (storage and transport are other layers'
concern):

- :class:`Job` - one unit of work bound to one engine stage, with its status,
  attempts, dependencies, logs, timings, and result.
- :class:`Workflow` - the per-project graph of jobs, its overall status, current
  stage, execution history, and derived progress/estimates/execution graph.
- :class:`WorkerInfo` - a worker's registration and health.
- :class:`WorkflowEvent` - an entry on the internal event stream / history.

Honesty is built in: a job is ``COMPLETED`` only when the engine genuinely
finished, ``FAILED`` on a real error, ``DEAD`` when retries are exhausted,
``BLOCKED`` when an upstream dependency cannot complete, and ``CANCELLED`` when
the operator cancels. Nothing is ever marked done speculatively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any


class JobStatus(StrEnum):
    """Lifecycle status of a single job (honest, never fabricated)."""

    PENDING = "pending"  # created; dependencies not yet satisfied
    READY = "ready"  # dependencies satisfied; awaiting a worker
    RUNNING = "running"  # claimed by a worker and executing
    COMPLETED = "completed"  # the engine genuinely finished
    FAILED = "failed"  # a real error occurred (may retry)
    CANCELLED = "cancelled"  # the operator cancelled
    DEAD = "dead"  # retries exhausted; will not run again
    BLOCKED = "blocked"  # an upstream dependency can never complete


# Statuses from which a job will never run again.
JOB_TERMINAL: frozenset[JobStatus] = frozenset(
    {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.DEAD, JobStatus.BLOCKED}
)


class JobPriority(IntEnum):
    """Job priority. Higher value is scheduled first (FIFO within a level)."""

    LOW = 10
    NORMAL = 50
    HIGH = 100


class WorkflowStatus(StrEnum):
    """Overall status of a project's workflow."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


WORKFLOW_TERMINAL: frozenset[WorkflowStatus] = frozenset(
    {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
)


class WorkerStatus(StrEnum):
    """Health status of a worker."""

    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class EventType(StrEnum):
    """Internal event-bus event types (future plugins subscribe by type).

    The per-stage "XFinished" events the product describes (UploadFinished,
    AnalysisFinished, ...) are emitted as :attr:`STAGE_FINISHED` carrying the
    ``stage`` and a friendly ``name`` in the payload, so a plugin can react to any
    stage without the enum needing a member per engine.
    """

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    JOB_READY = "job_ready"
    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_RETRYING = "job_retrying"
    JOB_DEAD = "job_dead"
    JOB_CANCELLED = "job_cancelled"
    JOB_BLOCKED = "job_blocked"
    STAGE_FINISHED = "stage_finished"
    WORKER_REGISTERED = "worker_registered"
    WORKER_OFFLINE = "worker_offline"
    WORKER_RECOVERED = "worker_recovered"


@dataclass(frozen=True, slots=True)
class StageSpec:
    """A static description of one workflow stage (engine + ordering + label)."""

    stage: str
    engine: str
    label: str
    depends_on: tuple[str, ...]
    estimate_seconds: float


# The canonical Olympus lifecycle. A linear DAG today (each stage depends on the
# previous), but modelled as explicit dependencies so the graph can branch later
# without changing the scheduler. ``engine`` maps the stage to the service that
# executes it; "upload" is validated (the file already exists) rather than run.
WORKFLOW_STAGES: tuple[StageSpec, ...] = (
    StageSpec("upload", "upload", "Upload", (), 1.0),
    StageSpec("cognitive", "cognitive", "Cognitive Analysis", ("upload",), 30.0),
    StageSpec("story", "story", "Story Analysis", ("cognitive",), 20.0),
    StageSpec("virality", "virality", "Virality Analysis", ("story",), 15.0),
    StageSpec("planning", "planning", "Clip Planner", ("virality",), 15.0),
    StageSpec("editing", "editing", "Editing", ("planning",), 20.0),
    StageSpec("rendering", "rendering", "Rendering", ("editing",), 60.0),
    StageSpec("optimization", "optimization", "Optimization", ("rendering",), 30.0),
)

STAGE_BY_NAME: dict[str, StageSpec] = {s.stage: s for s in WORKFLOW_STAGES}

# Friendly per-stage "finished" event names (carried in STAGE_FINISHED payloads).
STAGE_FINISHED_NAMES: dict[str, str] = {
    "upload": "UploadFinished",
    "cognitive": "AnalysisFinished",
    "story": "StoryFinished",
    "virality": "ViralityFinished",
    "planning": "PlanningFinished",
    "editing": "EditingFinished",
    "rendering": "RenderingFinished",
    "optimization": "OptimizationFinished",
}


@dataclass(slots=True)
class LogLine:
    """A single structured log line attached to a job."""

    ts: datetime
    level: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"ts": self.ts.isoformat(), "level": self.level, "message": self.message}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LogLine:
        return cls(
            ts=_parse_dt(raw.get("ts")) or _utc(),
            level=raw.get("level", "info"),
            message=raw.get("message", ""),
        )


@dataclass(slots=True)
class Job:
    """One unit of orchestrated work, bound to a single engine stage."""

    job_id: str
    workflow_id: str
    project_id: str
    engine: str
    stage: str
    priority: int = int(JobPriority.NORMAL)
    status: JobStatus = JobStatus.PENDING
    depends_on: tuple[str, ...] = ()  # stage names this job waits for
    attempts: int = 0
    max_attempts: int = 3
    worker_id: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    available_at: datetime | None = None  # earliest run time (delay/backoff)
    scheduled_for: datetime | None = None  # explicit schedule (optional)
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    logs: list[LogLine] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.status in JOB_TERMINAL

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds() * 1000.0
        return None

    def log(self, message: str, *, level: str = "info") -> None:
        self.logs.append(LogLine(ts=_utc(), level=level, message=message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "workflow_id": self.workflow_id,
            "project_id": self.project_id,
            "engine": self.engine,
            "stage": self.stage,
            "priority": self.priority,
            "status": self.status.value,
            "depends_on": list(self.depends_on),
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "available_at": _iso(self.available_at),
            "scheduled_for": _iso(self.scheduled_for),
            "duration_ms": self.duration_ms,
            "error": self.error,
            "result": self.result,
            "logs": [line.to_dict() for line in self.logs],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Job:
        return cls(
            job_id=raw["job_id"],
            workflow_id=raw["workflow_id"],
            project_id=raw["project_id"],
            engine=raw["engine"],
            stage=raw["stage"],
            priority=int(raw.get("priority", int(JobPriority.NORMAL))),
            status=JobStatus(raw.get("status", "pending")),
            depends_on=tuple(raw.get("depends_on", [])),
            attempts=int(raw.get("attempts", 0)),
            max_attempts=int(raw.get("max_attempts", 3)),
            worker_id=raw.get("worker_id"),
            created_at=_parse_dt(raw.get("created_at")),
            started_at=_parse_dt(raw.get("started_at")),
            finished_at=_parse_dt(raw.get("finished_at")),
            available_at=_parse_dt(raw.get("available_at")),
            scheduled_for=_parse_dt(raw.get("scheduled_for")),
            error=raw.get("error"),
            result=raw.get("result", {}) or {},
            logs=[
                LogLine.from_dict(line) for line in raw.get("logs", []) if isinstance(line, dict)
            ],
        )


@dataclass(slots=True)
class WorkflowEvent:
    """An entry on the workflow's execution history / internal event stream."""

    ts: datetime
    type: EventType
    message: str
    stage: str | None = None
    job_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "type": self.type.value,
            "message": self.message,
            "stage": self.stage,
            "job_id": self.job_id,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorkflowEvent:
        return cls(
            ts=_parse_dt(raw.get("ts")) or _utc(),
            type=EventType(raw.get("type", "stage_finished")),
            message=raw.get("message", ""),
            stage=raw.get("stage"),
            job_id=raw.get("job_id"),
            detail=raw.get("detail", {}) or {},
        )


@dataclass(slots=True)
class WorkerInfo:
    """A worker's registration and health snapshot."""

    worker_id: str
    status: WorkerStatus = WorkerStatus.IDLE
    registered_at: datetime | None = None
    last_heartbeat: datetime | None = None
    current_job_id: str | None = None
    jobs_completed: int = 0
    jobs_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "status": self.status.value,
            "registered_at": _iso(self.registered_at),
            "last_heartbeat": _iso(self.last_heartbeat),
            "current_job_id": self.current_job_id,
            "jobs_completed": self.jobs_completed,
            "jobs_failed": self.jobs_failed,
        }


@dataclass(slots=True)
class Workflow:
    """A project's complete, recoverable orchestration graph."""

    workflow_id: str
    project_id: str
    status: WorkflowStatus
    created_at: datetime
    updated_at: datetime
    jobs: list[Job] = field(default_factory=list)
    history: list[WorkflowEvent] = field(default_factory=list)
    retry_count: int = 0

    # -- lookups --------------------------------------------------------------
    def job(self, stage: str) -> Job | None:
        return next((j for j in self.jobs if j.stage == stage), None)

    def job_by_id(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs if j.job_id == job_id), None)

    # -- derived state --------------------------------------------------------
    @property
    def current_stage(self) -> str | None:
        """The stage currently running, else the next not-yet-completed stage."""

        running = next((j for j in self.jobs if j.status is JobStatus.RUNNING), None)
        if running is not None:
            return running.stage
        nxt = next((j for j in self.jobs if not j.is_terminal), None)
        return nxt.stage if nxt else None

    @property
    def completed_stages(self) -> list[str]:
        return [j.stage for j in self.jobs if j.status is JobStatus.COMPLETED]

    @property
    def failed_stages(self) -> list[str]:
        return [j.stage for j in self.jobs if j.status in (JobStatus.FAILED, JobStatus.DEAD)]

    @property
    def pending_stages(self) -> list[str]:
        return [
            j.stage
            for j in self.jobs
            if j.status in (JobStatus.PENDING, JobStatus.READY, JobStatus.RUNNING)
        ]

    @property
    def overall_progress(self) -> float:
        if not self.jobs:
            return 0.0
        done = sum(1 for j in self.jobs if j.status is JobStatus.COMPLETED)
        return round(done / len(self.jobs), 4)

    @property
    def estimated_remaining_seconds(self) -> float:
        """Nominal estimate from per-stage estimates of not-yet-completed stages.

        Deterministic and clearly an *estimate* (uses static per-stage nominal
        durations); never presented as a measured fact.
        """

        remaining = 0.0
        for job in self.jobs:
            if job.status is JobStatus.COMPLETED:
                continue
            spec = STAGE_BY_NAME.get(job.stage)
            if spec is not None:
                remaining += spec.estimate_seconds
        return round(remaining, 2)

    @property
    def total_retries(self) -> int:
        return sum(max(0, j.attempts - 1) for j in self.jobs)

    def execution_graph(self) -> dict[str, Any]:
        """The dependency DAG as nodes + edges, for the dashboard."""

        nodes = [
            {
                "stage": j.stage,
                "engine": j.engine,
                "label": STAGE_BY_NAME.get(j.stage).label if j.stage in STAGE_BY_NAME else j.stage,
                "status": j.status.value,
                "attempts": j.attempts,
                "duration_ms": j.duration_ms,
            }
            for j in self.jobs
        ]
        edges = [{"from": dep, "to": j.stage} for j in self.jobs for dep in j.depends_on]
        return {"nodes": nodes, "edges": edges}

    def record(self, event: WorkflowEvent, *, limit: int = 500) -> None:
        """Append an event to the bounded execution history."""

        self.history.append(event)
        if len(self.history) > limit:
            self.history = self.history[-limit:]

    def index(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "current_stage": self.current_stage,
            "overall_progress": self.overall_progress,
            "completed_stages": self.completed_stages,
            "failed_stages": self.failed_stages,
            "pending_stages": self.pending_stages,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "retry_count": self.retry_count,
            "total_retries": self.total_retries,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.index(),
            "jobs": [j.to_dict() for j in self.jobs],
            "history": [e.to_dict() for e in self.history],
            "execution_graph": self.execution_graph(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Workflow:
        return cls(
            workflow_id=raw["workflow_id"],
            project_id=raw["project_id"],
            status=WorkflowStatus(raw.get("status", "pending")),
            created_at=_parse_dt(raw.get("created_at")) or _utc(),
            updated_at=_parse_dt(raw.get("updated_at")) or _utc(),
            jobs=[Job.from_dict(j) for j in raw.get("jobs", []) if isinstance(j, dict)],
            history=[
                WorkflowEvent.from_dict(e) for e in raw.get("history", []) if isinstance(e, dict)
            ],
            retry_count=int(raw.get("retry_count", 0)),
        )


# -- small datetime helpers (kept local to the entity module) -----------------
def _utc() -> datetime:
    from olympus.utils import utc_now

    return utc_now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
