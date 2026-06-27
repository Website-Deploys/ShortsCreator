"""Storage-backed library metadata repository (favorites, tags, archive).

Holds the library's own additive metadata at ``library/meta/{project_id}.json``.
This is the only place archive state, favorites, and tags live - they are never
written back onto any engine output or the project record, keeping the whole
subsystem additive and the engines untouched.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.library import LibraryMetaRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.library import ProjectLibraryMeta
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_PREFIX = "library/meta/"
_SUFFIX = ".json"


def _key(project_id: str) -> str:
    return f"{_PREFIX}{project_id}{_SUFFIX}"


class StorageLibraryMetaRepository(LibraryMetaRepository):
    """Persist per-project library metadata as JSON documents."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def get(self, project_id: str) -> ProjectLibraryMeta:
        key = _key(project_id)
        if not await self._storage.exists(key):
            return ProjectLibraryMeta(project_id=project_id)
        try:
            raw = json.loads(await self._storage.get(key))
            return ProjectLibraryMeta.from_dict(raw)
        except (json.JSONDecodeError, KeyError, ValueError):
            return ProjectLibraryMeta(project_id=project_id)

    async def save(self, meta: ProjectLibraryMeta) -> None:
        await self._storage.put(
            _key(meta.project_id),
            json.dumps(meta.to_dict()).encode("utf-8"),
            content_type="application/json",
        )

    async def list_all(self) -> list[ProjectLibraryMeta]:
        out: list[ProjectLibraryMeta] = []
        for key in await self._storage.list_keys(_PREFIX):
            if not key.endswith(_SUFFIX):
                continue
            try:
                out.append(ProjectLibraryMeta.from_dict(json.loads(await self._storage.get(key))))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return out

    async def delete(self, project_id: str) -> None:
        key = _key(project_id)
        if await self._storage.exists(key):
            await self._storage.delete(key)
