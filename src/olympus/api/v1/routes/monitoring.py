"""Production Monitoring & Analytics endpoints.

The operational observability surface over everything Olympus runs: system
health, engine performance, workflow analytics, the live queue, storage (with
captured trends), failures, usage, cost estimation, the audit log, alerts, and
the combined admin snapshot.

Every endpoint is strictly read-only over real, persisted execution state. No
endpoint modifies an engine, the workflow, or any of their data, and no figure
is fabricated - unmeasurable values are reported as ``null`` (UNKNOWN).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from olympus.api.dependencies import MonitoringServiceDep
from olympus.api.v1.schemas.monitoring import (
    AdminResponse,
    AlertsResponse,
    AuditResponse,
    CostResponse,
    EnginesResponse,
    FailuresResponse,
    HealthResponse,
    QueueResponse,
    StorageAnalyticsResponse,
    SystemResponse,
    UsageResponse,
    WorkflowAnalyticsResponse,
)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/health", response_model=HealthResponse)
async def get_health(monitoring: MonitoringServiceDep) -> HealthResponse:
    """Overall platform health: engines, system, and queue, from real state."""

    return HealthResponse(**(await monitoring.health()))


@router.get("/engines", response_model=EnginesResponse)
async def get_engines(monitoring: MonitoringServiceDep) -> EnginesResponse:
    """Per-engine performance metrics aggregated across all projects."""

    metrics = await monitoring.engine_metrics()
    return EnginesResponse(engines=[m.to_dict() for m in metrics])


@router.get("/workflows", response_model=WorkflowAnalyticsResponse)
async def get_workflow_analytics(monitoring: MonitoringServiceDep) -> WorkflowAnalyticsResponse:
    """Aggregate workflow analytics: duration, idle, critical path, bottlenecks."""

    return WorkflowAnalyticsResponse(**(await monitoring.workflow_analytics()).to_dict())


@router.get("/queue", response_model=QueueResponse)
async def get_queue(monitoring: MonitoringServiceDep) -> QueueResponse:
    """A live snapshot of the workflow queue and worker pool."""

    return QueueResponse(**(await monitoring.queue()).to_dict())


@router.get("/system", response_model=SystemResponse)
async def get_system(monitoring: MonitoringServiceDep) -> SystemResponse:
    """Measured host metrics (CPU/load/disk/process); unavailable fields are null."""

    return SystemResponse(**monitoring.system_metrics().to_dict())


@router.get("/storage", response_model=StorageAnalyticsResponse)
async def get_storage(
    monitoring: MonitoringServiceDep,
    capture: bool = Query(default=False),
) -> StorageAnalyticsResponse:
    """Storage usage by namespace plus the captured trend series.

    ``capture=true`` appends the current measurement to the trend series.
    """

    analytics = await monitoring.storage_analytics(capture=capture)
    return StorageAnalyticsResponse(**analytics.to_dict())


@router.get("/failures", response_model=FailuresResponse)
async def get_failures(monitoring: MonitoringServiceDep) -> FailuresResponse:
    """Aggregated failure analytics from real persisted FAILED stages and jobs."""

    return FailuresResponse(**(await monitoring.failures()).to_dict())


@router.get("/usage", response_model=UsageResponse)
async def get_usage(monitoring: MonitoringServiceDep) -> UsageResponse:
    """Measured platform usage totals."""

    return UsageResponse(**(await monitoring.usage()).to_dict())


@router.get("/cost", response_model=CostResponse)
async def get_cost(monitoring: MonitoringServiceDep) -> CostResponse:
    """An estimate (never billing) of operational cost from measured work."""

    return CostResponse(**(await monitoring.cost()).to_dict())


@router.get("/audit", response_model=AuditResponse)
async def get_audit(
    monitoring: MonitoringServiceDep,
    limit: int = Query(default=200, ge=1, le=1000),
) -> AuditResponse:
    """The immutable, append-only audit log (derived + recorded), newest first."""

    entries = await monitoring.audit(limit=limit)
    return AuditResponse(count=len(entries), entries=[e.to_dict() for e in entries])


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(monitoring: MonitoringServiceDep) -> AlertsResponse:
    """Informational alerts derived from measured state (no notifications)."""

    alerts = await monitoring.alerts()
    return AlertsResponse(count=len(alerts), alerts=[a.to_dict() for a in alerts])


@router.get("/admin", response_model=AdminResponse)
async def get_admin(monitoring: MonitoringServiceDep) -> AdminResponse:
    """The combined admin dashboard payload (all real, measured)."""

    return AdminResponse(**(await monitoring.admin()).to_dict())
