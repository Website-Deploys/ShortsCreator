"""Storage-backed metrics-snapshot repository (storage trend series).

Persists an append-only series of storage snapshots at
``monitoring/snapshots/storage.json``. Points are deduplicated per hour bucket so
repeated dashboard loads don't flood the series. The trend starts empty and
accumulates only real captured points - it never back-fills fabricated history.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.monitoring import MetricsSnapshotRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.monitoring import StoragePoint
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_KEY = "monitoring/snapshots/storage.json"
_CAP = 500


class StorageMetricsSnapshotRepository(MetricsSnapshotRepository):
    """Append-only storage snapshot series persisted in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def _read(self) -> list[StoragePoint]:
        if not await self._storage.exists(_KEY):
            return []
        try:
            raw = json.loads(await self._storage.get(_KEY))
        except (json.JSONDecodeError, ValueError):
            return []
        return [StoragePoint.from_dict(p) for p in raw if isinstance(p, dict)]

    async def append(self, point: StoragePoint) -> None:
        points = await self._read()
        # Deduplicate per hour bucket: replace the last point if it's in the
        # same hour, so the series has at most one point per hour.
        bucket = point.ts.strftime("%Y-%m-%dT%H")
        if points and points[-1].ts.strftime("%Y-%m-%dT%H") == bucket:
            points[-1] = point
        else:
            points.append(point)
        points = points[-_CAP:]
        await self._storage.put(
            _KEY,
            json.dumps([p.to_dict() for p in points]).encode("utf-8"),
            content_type="application/json",
        )

    async def list(self, *, limit: int = 200) -> list[StoragePoint]:
        points = await self._read()
        return points[-limit:]
