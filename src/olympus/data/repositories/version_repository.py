"""Storage-backed version repository (append-only engine-output snapshots).

Lives entirely under the library's own ``library/versions/{project_id}/{engine}/``
namespace - it never modifies any engine's data. Each engine+project keeps an
``index.json`` of version metadata plus one ``v{n}.json`` per captured payload.
Captures are deduplicated by content checksum and are append-only: history is
never overwritten.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from olympus.domain.contracts.library import VersionRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.library import VersionRecord
from olympus.platform.logging import get_logger
from olympus.utils import utc_now

log = get_logger(__name__)


def _engine_prefix(project_id: str, engine: str) -> str:
    return f"library/versions/{project_id}/{engine}"


def _checksum(payload: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    )


class StorageVersionRepository(VersionRepository):
    """Persist append-only, deduplicated version snapshots in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def capture(
        self,
        project_id: str,
        engine: str,
        payload: dict[str, Any],
        *,
        status: str | None,
        summary: dict[str, Any],
    ) -> VersionRecord | None:
        records = await self.list_versions(project_id, engine)
        checksum = _checksum(payload)
        if records and records[-1].checksum == checksum:
            return None  # unchanged since last capture - no new version
        version = len(records) + 1
        record = VersionRecord(
            project_id=project_id,
            engine=engine,
            version=version,
            created_at=utc_now(),
            checksum=checksum,
            status=status,
            summary=summary,
        )
        prefix = _engine_prefix(project_id, engine)
        await self._storage.put(
            f"{prefix}/v{version}.json",
            json.dumps(payload, default=str).encode("utf-8"),
            content_type="application/json",
        )
        records.append(record)
        await self._storage.put(
            f"{prefix}/index.json",
            json.dumps([r.to_dict() for r in records]).encode("utf-8"),
            content_type="application/json",
        )
        return record

    async def list_engines(self, project_id: str) -> list[str]:
        prefix = f"library/versions/{project_id}/"
        engines: set[str] = set()
        for key in await self._storage.list_keys(prefix):
            rest = key[len(prefix) :]
            if "/" in rest:
                engines.add(rest.split("/", 1)[0])
        return sorted(engines)

    async def list_versions(self, project_id: str, engine: str) -> list[VersionRecord]:
        key = f"{_engine_prefix(project_id, engine)}/index.json"
        if not await self._storage.exists(key):
            return []
        try:
            raw = json.loads(await self._storage.get(key))
        except (json.JSONDecodeError, ValueError):
            return []
        return [VersionRecord.from_dict(r) for r in raw if isinstance(r, dict)]

    async def get_payload(
        self, project_id: str, engine: str, version: int
    ) -> dict[str, Any] | None:
        key = f"{_engine_prefix(project_id, engine)}/v{version}.json"
        if not await self._storage.exists(key):
            return None
        try:
            data = json.loads(await self._storage.get(key))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None

    async def delete(self, project_id: str) -> None:
        for key in await self._storage.list_keys(f"library/versions/{project_id}/"):
            await self._storage.delete(key)
