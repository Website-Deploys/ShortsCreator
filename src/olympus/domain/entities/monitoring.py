"""Production Monitoring & Analytics entities.

The operational layer that lets Olympus monitor itself like a real production
SaaS: system health, engine performance, queue state, storage, failures, usage,
cost estimation, audit logs, and alerts. It is **purely observational** - it
reads the real, persisted execution state the engines, workflow, and library
already wrote, and never modifies any of them.

Honesty-first: every figure is a *measured* value. Anything that cannot be
measured in this environment (e.g. system memory without psutil, LLM token
usage that is not instrumented) is reported as ``None`` / UNKNOWN, never
fabricated. Cost is always an explicit *estimate*, never billing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

# Reuse the platform's existing health vocabulary (do not redefine it).
from olympus.platform.monitoring.health import HealthStatus

__all__ = [
    "AdminSnapshot",
    "Alert",
    "AlertSeverity",
    "AuditAction",
    "AuditEntry",
    "CostEstimate",
    "EngineHealth",
    "EngineMetrics",
    "FailureRecord",
    "FailureSummary",
    "HealthStatus",
    "QueueSnapshot",
    "StorageAnalytics",
    "StoragePoint",
    "SystemMetrics",
    "UsageStats",
    "WorkflowAnalytics",
]


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
class AlertSeverity(StrEnum):
    """Severity of an informational alert."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class Alert:
    """An informational alert derived from measured state (no notifications)."""

    id: str
    severity: AlertSeverity
    category: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity.value,
            "category": self.category,
            "message": self.message,
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------------- #
# Engine metrics
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class EngineMetrics:
    """Measured performance metrics for one engine, aggregated across projects.

    Times are in milliseconds. ``None`` means the value could not be measured
    from the persisted state (UNKNOWN), never a fabricated zero.
    """

    engine: str
    runs: int = 0  # number of projects this engine produced output for
    stage_executions: int = 0  # total stage executions observed
    completed: int = 0
    failed: int = 0
    unavailable: int = 0
    cancelled: int = 0
    retries: int = 0
    avg_execution_ms: float | None = None
    p95_execution_ms: float | None = None
    total_execution_ms: float = 0.0
    avg_wait_ms: float | None = None  # queue wait (from workflow jobs), if any
    avg_queue_delay_ms: float | None = None
    avg_confidence: float | None = None
    throughput_per_hour: float | None = None
    concurrent_executions: int = 0  # current, from the live queue

    @property
    def completion_rate(self) -> float | None:
        total = self.completed + self.failed + self.cancelled
        return round(self.completed / total, 4) if total else None

    @property
    def failure_rate(self) -> float | None:
        total = self.completed + self.failed + self.cancelled
        return round(self.failed / total, 4) if total else None

    @property
    def cancellation_rate(self) -> float | None:
        total = self.completed + self.failed + self.cancelled
        return round(self.cancelled / total, 4) if total else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "runs": self.runs,
            "stage_executions": self.stage_executions,
            "completed": self.completed,
            "failed": self.failed,
            "unavailable": self.unavailable,
            "cancelled": self.cancelled,
            "retries": self.retries,
            "avg_execution_ms": self.avg_execution_ms,
            "p95_execution_ms": self.p95_execution_ms,
            "total_execution_ms": round(self.total_execution_ms, 2),
            "avg_wait_ms": self.avg_wait_ms,
            "avg_queue_delay_ms": self.avg_queue_delay_ms,
            "avg_confidence": self.avg_confidence,
            "throughput_per_hour": self.throughput_per_hour,
            "concurrent_executions": self.concurrent_executions,
            "completion_rate": self.completion_rate,
            "failure_rate": self.failure_rate,
            "cancellation_rate": self.cancellation_rate,
        }


@dataclass(slots=True)
class EngineHealth:
    """A coarse health verdict for one engine, from its measured metrics."""

    engine: str
    status: HealthStatus
    detail: str
    failure_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "status": self.status.value,
            "detail": self.detail,
            "failure_rate": self.failure_rate,
        }


# --------------------------------------------------------------------------- #
# Workflow analytics
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class WorkflowAnalytics:
    """Aggregate analytics across all project workflows (measured)."""

    total_workflows: int = 0
    completed: int = 0
    failed: int = 0
    running: int = 0
    avg_duration_ms: float | None = None
    avg_idle_ms: float | None = None  # time not spent executing a stage
    critical_path: list[dict[str, Any]] = field(default_factory=list)  # slowest stages
    engine_bottlenecks: list[dict[str, Any]] = field(default_factory=list)
    slowest_projects: list[dict[str, Any]] = field(default_factory=list)
    fastest_projects: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_workflows": self.total_workflows,
            "completed": self.completed,
            "failed": self.failed,
            "running": self.running,
            "avg_duration_ms": self.avg_duration_ms,
            "avg_idle_ms": self.avg_idle_ms,
            "critical_path": self.critical_path,
            "engine_bottlenecks": self.engine_bottlenecks,
            "slowest_projects": self.slowest_projects,
            "fastest_projects": self.fastest_projects,
        }


# --------------------------------------------------------------------------- #
# Queue monitoring
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class QueueSnapshot:
    """A live snapshot of the workflow queue and worker pool (measured)."""

    queued: int = 0
    running: int = 0
    delayed: int = 0
    completed: int = 0
    failed: int = 0
    dead: int = 0
    blocked: int = 0
    cancelled: int = 0
    active_workflows: int = 0
    worker_count: int = 0
    busy_workers: int = 0
    idle_workers: int = 0
    offline_workers: int = 0
    pool_running: bool = False
    stuck_jobs: list[dict[str, Any]] = field(default_factory=list)
    dead_jobs: list[dict[str, Any]] = field(default_factory=list)
    avg_queue_latency_ms: float | None = None
    workers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def worker_utilization(self) -> float | None:
        if self.worker_count == 0:
            return None
        return round(self.busy_workers / self.worker_count, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queued": self.queued,
            "running": self.running,
            "delayed": self.delayed,
            "completed": self.completed,
            "failed": self.failed,
            "dead": self.dead,
            "blocked": self.blocked,
            "cancelled": self.cancelled,
            "active_workflows": self.active_workflows,
            "worker_count": self.worker_count,
            "busy_workers": self.busy_workers,
            "idle_workers": self.idle_workers,
            "offline_workers": self.offline_workers,
            "pool_running": self.pool_running,
            "worker_utilization": self.worker_utilization,
            "stuck_jobs": self.stuck_jobs,
            "dead_jobs": self.dead_jobs,
            "avg_queue_latency_ms": self.avg_queue_latency_ms,
            "workers": self.workers,
        }


# --------------------------------------------------------------------------- #
# System / host metrics
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SystemMetrics:
    """Measured host metrics. ``None`` fields are genuinely unavailable here."""

    cpu_count: int | None = None
    load_avg_1m: float | None = None
    load_avg_5m: float | None = None
    load_avg_15m: float | None = None
    process_cpu_seconds: float | None = None
    process_max_rss_bytes: int | None = None
    system_memory_total_bytes: int | None = None
    system_memory_available_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    disk_free_bytes: int | None = None
    source: str = "stdlib"  # "psutil" when available, else "stdlib"
    unavailable: list[str] = field(default_factory=list)

    @property
    def disk_used_pct(self) -> float | None:
        if self.disk_total_bytes and self.disk_total_bytes > 0 and self.disk_used_bytes is not None:
            return round(self.disk_used_bytes / self.disk_total_bytes, 4)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_count": self.cpu_count,
            "load_avg_1m": self.load_avg_1m,
            "load_avg_5m": self.load_avg_5m,
            "load_avg_15m": self.load_avg_15m,
            "process_cpu_seconds": self.process_cpu_seconds,
            "process_max_rss_bytes": self.process_max_rss_bytes,
            "system_memory_total_bytes": self.system_memory_total_bytes,
            "system_memory_available_bytes": self.system_memory_available_bytes,
            "disk_total_bytes": self.disk_total_bytes,
            "disk_used_bytes": self.disk_used_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_used_pct": self.disk_used_pct,
            "source": self.source,
            "unavailable": self.unavailable,
        }


# --------------------------------------------------------------------------- #
# Storage analytics
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class StoragePoint:
    """One captured point in the storage time series (for trends)."""

    ts: datetime
    total_bytes: int
    namespaces: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "total_bytes": self.total_bytes,
            "namespaces": self.namespaces,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> StoragePoint:
        return cls(
            ts=_parse_dt(raw.get("ts")) or _utc(),
            total_bytes=int(raw.get("total_bytes", 0)),
            namespaces=raw.get("namespaces", {}) or {},
        )


@dataclass(slots=True)
class StorageAnalytics:
    """Current storage usage by namespace plus the captured trend series."""

    total_bytes: int = 0
    namespaces: dict[str, int] = field(default_factory=dict)
    trend: list[StoragePoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_bytes": self.total_bytes,
            "namespaces": self.namespaces,
            "trend": [p.to_dict() for p in self.trend],
        }


# --------------------------------------------------------------------------- #
# Failure analytics
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class FailureRecord:
    """One observed failure (from a real persisted FAILED stage/job)."""

    engine: str
    stage: str
    project_id: str
    ts: datetime | None
    error: str | None
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "stage": self.stage,
            "project_id": self.project_id,
            "ts": self.ts.isoformat() if self.ts else None,
            "error": self.error,
            "attempts": self.attempts,
        }


@dataclass(slots=True)
class FailureSummary:
    """Aggregated failure analytics (measured, never fabricated causes)."""

    total_failures: int = 0
    by_engine: dict[str, int] = field(default_factory=dict)
    by_exception: dict[str, int] = field(default_factory=dict)
    by_project: dict[str, int] = field(default_factory=dict)
    recent: list[FailureRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_failures": self.total_failures,
            "by_engine": self.by_engine,
            "by_exception": self.by_exception,
            "by_project": self.by_project,
            "recent": [r.to_dict() for r in self.recent],
        }


# --------------------------------------------------------------------------- #
# Cost estimation
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class CostLine:
    """One cost line: the measured quantity, the rate, and the estimated cost."""

    item: str
    quantity: float | None
    unit: str
    rate_usd: float
    estimated_usd: float | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "quantity": self.quantity,
            "unit": self.unit,
            "rate_usd": self.rate_usd,
            "estimated_usd": self.estimated_usd,
            "note": self.note,
        }


@dataclass(slots=True)
class CostEstimate:
    """An estimate (never billing) of operational cost from measured work."""

    lines: list[CostLine] = field(default_factory=list)
    total_usd: float = 0.0
    disclaimer: str = (
        "Estimate only, derived from measured work and configurable rates. Not "
        "billing. Quantities that are not instrumented are shown as UNKNOWN."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "total_usd": round(self.total_usd, 4),
            "disclaimer": self.disclaimer,
        }


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
class AuditAction(StrEnum):
    """The auditable action categories."""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    STAGE_FINISHED = "stage_finished"
    JOB_RETRIED = "job_retried"
    RENDER_EXECUTION = "render_execution"
    OPTIMIZATION_EXECUTION = "optimization_execution"
    PROJECT_ARCHIVED = "project_archived"
    PROJECT_RESTORED = "project_restored"
    CLEANUP = "cleanup"
    VERSION_CAPTURED = "version_captured"
    DOWNLOAD = "download"
    USER_ACTION = "user_action"
    OTHER = "other"


@dataclass(slots=True)
class AuditEntry:
    """One immutable, append-only audit entry."""

    id: str
    ts: datetime
    action: AuditAction
    message: str
    project_id: str | None = None
    source: str = "derived"  # "derived" (from persisted state) | "recorded"
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "action": self.action.value,
            "message": self.message,
            "project_id": self.project_id,
            "source": self.source,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AuditEntry:
        return cls(
            id=raw["id"],
            ts=_parse_dt(raw.get("ts")) or _utc(),
            action=_safe_action(raw.get("action")),
            message=raw.get("message", ""),
            project_id=raw.get("project_id"),
            source=raw.get("source", "recorded"),
            detail=raw.get("detail", {}) or {},
        )


# --------------------------------------------------------------------------- #
# Usage analytics
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class UsageStats:
    """Measured platform usage totals."""

    projects: int = 0
    videos_processed: int = 0
    minutes_analyzed: float = 0.0
    clips: int = 0
    renders: int = 0
    exports: int = 0
    workflows_run: int = 0
    total_stage_executions: int = 0
    busiest_engine: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "projects": self.projects,
            "videos_processed": self.videos_processed,
            "minutes_analyzed": round(self.minutes_analyzed, 2),
            "clips": self.clips,
            "renders": self.renders,
            "exports": self.exports,
            "workflows_run": self.workflows_run,
            "total_stage_executions": self.total_stage_executions,
            "busiest_engine": self.busiest_engine,
        }


# --------------------------------------------------------------------------- #
# Admin snapshot (combined dashboard)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class AdminSnapshot:
    """The combined admin dashboard payload (all real, measured)."""

    overall_health: HealthStatus
    engine_health: list[EngineHealth] = field(default_factory=list)
    system: SystemMetrics | None = None
    queue: QueueSnapshot | None = None
    usage: UsageStats | None = None
    storage_total_bytes: int = 0
    alerts: list[Alert] = field(default_factory=list)
    recent_failures: list[FailureRecord] = field(default_factory=list)
    recent_audit: list[AuditEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_health": self.overall_health.value,
            "engine_health": [e.to_dict() for e in self.engine_health],
            "system": self.system.to_dict() if self.system else None,
            "queue": self.queue.to_dict() if self.queue else None,
            "usage": self.usage.to_dict() if self.usage else None,
            "storage_total_bytes": self.storage_total_bytes,
            "alerts": [a.to_dict() for a in self.alerts],
            "recent_failures": [f.to_dict() for f in self.recent_failures],
            "recent_audit": [a.to_dict() for a in self.recent_audit],
        }


# -- helpers ------------------------------------------------------------------
def _safe_action(value: Any) -> AuditAction:
    try:
        return AuditAction(value)
    except ValueError:
        return AuditAction.OTHER


def _utc() -> datetime:
    from olympus.utils import utc_now

    return utc_now()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
