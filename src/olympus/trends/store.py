"""Durable project-artifact and cache persistence for Trend Research V2."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from olympus.domain.contracts.storage import StoragePort

_CACHE_KEY = re.compile(r"^[a-f0-9]{32,64}$")
_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{3,160}$")


class TrendSnapshotStore:
    """Persist snapshots through Olympus' existing storage abstraction."""

    def __init__(self, storage: StoragePort, *, cache_dir: str = "work/trend_cache") -> None:
        self._storage = storage
        normalized = cache_dir.replace("\\", "/").strip("/")
        self._cache_dir = normalized or "work/trend_cache"

    @staticmethod
    def project_key(project_id: str) -> str:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValueError("Invalid project id for trend artifact storage.")
        return f"trend/{project_id}/trend_research_v2.json"

    def cache_key(self, cache_key: str) -> str:
        if not _CACHE_KEY.fullmatch(cache_key):
            raise ValueError("Invalid trend cache key.")
        return f"{self._cache_dir}/trend_snapshot_{cache_key}.json"

    async def load_project(self, project_id: str) -> dict[str, Any] | None:
        return await self._load_json(self.project_key(project_id))

    async def save_project(self, project_id: str, snapshot: dict[str, Any]) -> None:
        await self._save_json(self.project_key(project_id), snapshot)

    async def load_cache(self, cache_key: str) -> dict[str, Any] | None:
        return await self._load_json(self.cache_key(cache_key))

    async def save_cache(self, cache_key: str, snapshot: dict[str, Any]) -> None:
        await self._save_json(self.cache_key(cache_key), snapshot)

    async def _load_json(self, key: str) -> dict[str, Any] | None:
        if not await self._storage.exists(key):
            return None
        try:
            value = json.loads((await self._storage.get(key)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    async def _save_json(self, key: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=True, sort_keys=True).encode("utf-8")
        await self._storage.put(key, payload, content_type="application/json")


def snapshot_is_fresh(snapshot: dict[str, Any], now: datetime) -> bool:
    """Return whether a cached snapshot is reusable at ``now``."""

    if snapshot.get("fallback_used") is True and not snapshot.get("expires_at"):
        return True
    expires = _snapshot_expiry(snapshot, now)
    if expires is None:
        return False
    return expires > now


def snapshot_is_stale_usable(
    snapshot: dict[str, Any],
    now: datetime,
    *,
    allowed_hours: int,
) -> bool:
    """Return whether an expired live snapshot is within the explicit stale window."""

    live_origin = bool(
        snapshot.get("live_research_succeeded") is True
        or snapshot.get("internet_available") is True
        or (
            snapshot.get("provider_used") not in {None, "evergreen", "disabled"}
            and snapshot.get("cache_status") in {"fresh", "live_refreshed", "cached"}
        )
    )
    if allowed_hours <= 0 or not live_origin:
        return False
    expires = _snapshot_expiry(snapshot, now)
    return expires is not None and expires <= now <= expires + timedelta(hours=allowed_hours)


def _snapshot_expiry(snapshot: dict[str, Any], now: datetime) -> datetime | None:
    expires_at = snapshot.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at:
        return None
    try:
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if expires.tzinfo is None and now.tzinfo is not None:
        expires = expires.replace(tzinfo=now.tzinfo)
    return expires
