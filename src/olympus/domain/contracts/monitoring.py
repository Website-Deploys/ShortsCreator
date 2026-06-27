"""Monitoring contracts (ports).

The monitoring system is observational: it derives almost everything from the
real execution state the engines/workflow/library already persisted. It owns
only two small, additive stores of its own - an append-only audit log for any
monitoring-recorded actions, and a metrics-snapshot series used to show storage
trends over time. Both live under a dedicated ``monitoring/`` storage namespace
that nothing else touches.
"""

from __future__ import annotations

import abc

from olympus.domain.entities.monitoring import AuditEntry, StoragePoint


class AuditRepository(abc.ABC):
    """Append-only, immutable audit log for monitoring-recorded actions.

    Derived audit entries (reconstructed from persisted workflow/library state)
    are merged in by the service; this store persists only entries the monitoring
    layer explicitly records, and never updates or deletes them.
    """

    @abc.abstractmethod
    async def append(self, entry: AuditEntry) -> None:
        """Append one immutable audit entry."""

    @abc.abstractmethod
    async def list(self, *, limit: int = 500) -> list[AuditEntry]:
        """Return recorded audit entries, newest first."""


class MetricsSnapshotRepository(abc.ABC):
    """A time series of storage snapshots used to render trends over time.

    Snapshots are append-only points; the series starts empty and accumulates as
    snapshots are captured (so a trend reflects only real, captured history - it
    never back-fills fabricated points).
    """

    @abc.abstractmethod
    async def append(self, point: StoragePoint) -> None:
        """Append a storage snapshot point (deduplicated per time bucket)."""

    @abc.abstractmethod
    async def list(self, *, limit: int = 200) -> list[StoragePoint]:
        """Return captured snapshot points, oldest first."""
