"""Storage-backed render-manifest repository (read + write).

The Optimization Engine discovers the finished MP4s it should optimize by reading
the render manifest at ``render/{project_id}/index.json``; the Rendering Engine -
the manifest's official producer - writes it there once real MP4s exist. This
adapter implements both sides behind the :class:`RenderManifestStore` contract
(which extends the read-only :class:`RenderManifestRepository` the Optimization
Engine depends on).

``load`` returns ``None`` when no manifest exists - the honest signal that the
Rendering Engine has not produced output for this project yet.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.rendering import RenderManifestStore
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.rendering import RenderManifest
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _index_key(project_id: str) -> str:
    return f"render/{project_id}/index.json"


class StorageRenderManifestRepository(RenderManifestStore):
    """Read and write a project's render manifest in object storage.

    Reading is the boundary the Optimization Engine consumes; writing is how the
    Rendering Engine - the manifest's official producer - publishes it once real
    MP4s exist. The manifest lives at ``render/{project_id}/index.json``; deleting
    also removes the rendered clip files and any working artifacts.
    """

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

    async def save(self, manifest: RenderManifest) -> None:
        data = json.dumps(manifest.to_dict(), indent=2).encode("utf-8")
        await self._storage.put(
            _index_key(manifest.project_id), data, content_type="application/json"
        )

    async def delete(self, project_id: str) -> None:
        # Remove the manifest, the rendered clip files, and any working artifacts.
        if await self._storage.exists(_index_key(project_id)):
            await self._storage.delete(_index_key(project_id))
        for prefix in (
            f"render/{project_id}/clips/",
            f"render/{project_id}/metadata/",
            f"render/{project_id}/work/",
        ):
            for key in await self._storage.list_keys(prefix):
                await self._storage.delete(key)
