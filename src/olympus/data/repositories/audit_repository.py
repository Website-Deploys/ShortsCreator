"""Storage-backed, append-only audit repository.

Persists monitoring-recorded audit entries at ``monitoring/audit/log.json`` as an
append-only list. Entries are never updated or deleted - the log only grows
(bounded by a generous cap to keep the document readable). The monitoring
service merges these recorded entries with entries it derives from real
persisted workflow/library state to present the full audit feed.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.monitoring import AuditRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.monitoring import AuditEntry
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_KEY = "monitoring/audit/log.json"
_CAP = 5000


class StorageAuditRepository(AuditRepository):
    """Append-only audit log persisted in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def _read(self) -> list[AuditEntry]:
        if not await self._storage.exists(_KEY):
            return []
        try:
            raw = json.loads(await self._storage.get(_KEY))
        except (json.JSONDecodeError, ValueError):
            return []
        return [AuditEntry.from_dict(e) for e in raw if isinstance(e, dict)]

    async def append(self, entry: AuditEntry) -> None:
        entries = await self._read()
        entries.append(entry)
        entries = entries[-_CAP:]
        await self._storage.put(
            _KEY,
            json.dumps([e.to_dict() for e in entries]).encode("utf-8"),
            content_type="application/json",
        )

    async def list(self, *, limit: int = 500) -> list[AuditEntry]:
        entries = await self._read()
        entries.sort(key=lambda e: e.ts, reverse=True)
        return entries[:limit]
