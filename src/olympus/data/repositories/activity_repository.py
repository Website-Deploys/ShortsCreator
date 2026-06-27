"""Storage-backed activity repository (append-only library action log).

Records library-originated actions (archive, cleanup, version capture, favorite,
tag, export download) under ``library/activity/{project_id}.json``. Global,
cross-project actions use ``library/activity/_global.json``. The library merges
these with derived activity (project creation, workflow history) when it builds
the feed, so the feed is always grounded in real recorded or observed state.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.library import ActivityRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.library import ActivityEvent
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_PREFIX = "library/activity/"
_GLOBAL = "_global"
_CAP = 1000


def _key(project_id: str | None) -> str:
    return f"{_PREFIX}{project_id or _GLOBAL}.json"


class StorageActivityRepository(ActivityRepository):
    """Persist activity events as per-project JSON lists in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def _read(self, key: str) -> list[ActivityEvent]:
        if not await self._storage.exists(key):
            return []
        try:
            raw = json.loads(await self._storage.get(key))
        except (json.JSONDecodeError, ValueError):
            return []
        return [ActivityEvent.from_dict(e) for e in raw if isinstance(e, dict)]

    async def append(self, event: ActivityEvent) -> None:
        key = _key(event.project_id)
        events = await self._read(key)
        events.append(event)
        events = events[-_CAP:]
        await self._storage.put(
            key,
            json.dumps([e.to_dict() for e in events]).encode("utf-8"),
            content_type="application/json",
        )

    async def list(self, project_id: str | None = None, *, limit: int = 200) -> list[ActivityEvent]:
        if project_id is not None:
            events = await self._read(_key(project_id))
        else:
            events = []
            for key in await self._storage.list_keys(_PREFIX):
                if key.endswith(".json"):
                    events.extend(await self._read(key))
        events.sort(key=lambda e: e.ts, reverse=True)
        return events[:limit]

    async def delete(self, project_id: str) -> None:
        key = _key(project_id)
        if await self._storage.exists(key):
            await self._storage.delete(key)
