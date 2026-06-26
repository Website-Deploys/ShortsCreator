"""Health and readiness endpoints.

- ``GET /health/live``  - liveness: the process is up. Cheap, no dependencies.
- ``GET /health/ready`` - readiness: probe dependencies (database, storage) and
  report aggregate health. Returns 200 when healthy/degraded and 503 when
  unhealthy, so load balancers route correctly.

These power orchestrator and load-balancer probes and the team's at-a-glance
operational view.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from olympus.api.dependencies import DbSessionDep, StorageDep
from olympus.platform.logging import get_logger
from olympus.platform.monitoring import ComponentHealth, HealthReport, HealthStatus

log = get_logger(__name__)
router = APIRouter()


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    """Return 200 if the process is running. No dependencies are checked."""

    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness probe")
async def ready(
    session: DbSessionDep, storage: StorageDep, response: Response
) -> dict[str, object]:
    """Probe critical dependencies and report aggregate readiness."""

    components: list[ComponentHealth] = []

    # Database probe.
    try:
        await session.execute(text("SELECT 1"))
        components.append(ComponentHealth("database", HealthStatus.HEALTHY))
    except Exception as exc:
        log.warning("readiness_database_unhealthy", error=str(exc))
        components.append(
            ComponentHealth("database", HealthStatus.UNHEALTHY, detail=str(exc))
        )

    # Storage probe (a cheap existence check on a sentinel key).
    try:
        await storage.exists("__healthcheck__")
        components.append(ComponentHealth("storage", HealthStatus.HEALTHY))
    except Exception as exc:
        log.warning("readiness_storage_unhealthy", error=str(exc))
        components.append(
            ComponentHealth("storage", HealthStatus.UNHEALTHY, detail=str(exc))
        )

    report: HealthReport = HealthReport.from_components(components)
    if report.status is HealthStatus.UNHEALTHY:
        response.status_code = 503
    return report.to_dict()
