"""Health and readiness reporting primitives.

Two distinct concepts (a standard operational distinction):

- **Liveness**: is the process up and able to serve at all? (cheap, no
  dependencies). Used by orchestrators to decide whether to restart a pod.
- **Readiness**: are the dependencies (database, redis, storage) healthy enough
  to serve real traffic? Used by load balancers to decide whether to route.

This module defines the data structures; the actual dependency probes are wired
in the API layer where the concrete adapters are available, keeping this module
dependency-free and reusable by both the API and the worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class HealthStatus(StrEnum):
    """Coarse health states for a component or the system as a whole."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(slots=True)
class ComponentHealth:
    """Health of a single dependency (e.g. ``database``)."""

    name: str
    status: HealthStatus
    detail: str | None = None


@dataclass(slots=True)
class HealthReport:
    """Aggregate health across all probed components."""

    status: HealthStatus
    components: list[ComponentHealth] = field(default_factory=list)

    @classmethod
    def from_components(cls, components: list[ComponentHealth]) -> HealthReport:
        """Derive the overall status from the worst component status."""

        if any(c.status is HealthStatus.UNHEALTHY for c in components):
            overall = HealthStatus.UNHEALTHY
        elif any(c.status is HealthStatus.DEGRADED for c in components):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY
        return cls(status=overall, components=components)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "components": [
                {"name": c.name, "status": c.status.value, "detail": c.detail}
                for c in self.components
            ],
        }
