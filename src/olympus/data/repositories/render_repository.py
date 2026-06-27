"""Storage-backed render-manifest repository (read access).

The Optimization Engine discovers the finished MP4s it should optimize by reading
the render manifest the Rendering Engine durably publishes at
``render/{project_id}/index.json``. This adapter implements the read-only
:class:`RenderManifestRepository` contract over the storage abstraction.

It is intentionally read-only: the Optimization Engine never writes or mutates
renders. ``load`` returns ``None`` when no manifest exists - the honest signal
that the Rendering Engine has not produced output for this project yet (the
common case today, since the Rendering Engine is a separate, future layer). A
database-backed implementation can replace this behind the same contract.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.rendering import RenderManifestRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.rendering import RenderManifest
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _index_key(project_id: str) -> str:
    return f"render/{project_id}/index.json"


class StorageRenderManifestRepository(RenderManifestRepository):
    """Read a project's render manifest from object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def load(self, project_id: str) -> RenderManifest | None:
        key = _index_key(project_id)
        if not await self._storage.exists(key):
            return None
        try:
            raw = json.loads(await self._storage.get(key))
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(
                "Stored render manifest is corrupt.", details={"project_id": project_id}
            ) from exc
        return RenderManifest.from_dict(raw)
