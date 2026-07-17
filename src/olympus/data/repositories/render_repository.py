"""Storage-backed render-manifest repository (read + write).

The canonical durable handoff is ``render/{project_id}/run/index.json``. New run
indexes embed the published manifest, while older runs may expose it through the
full ``generate_render_manifest`` stage artifact. The historical
``render/{project_id}/index.json`` publication remains a compatibility fallback.

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
from olympus.rendering.artifacts import (
    canonical_render_manifest_path,
    legacy_render_manifest_path,
    resolve_render_manifest,
)

log = get_logger(__name__)


def _index_key(project_id: str) -> str:
    return legacy_render_manifest_path(project_id)


class StorageRenderManifestRepository(RenderManifestStore):
    """Read and write a project's render manifest in object storage.

    Reading is the boundary the Optimization Engine consumes; writing is how the
    Rendering Engine - the manifest's official producer - publishes it once real
    MP4s exist. Reads prefer the canonical render-run handoff and retain the old
    root manifest only as fallback. Deleting also removes rendered clip files and
    working artifacts.
    """

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def load(self, project_id: str) -> RenderManifest | None:
        resolution = await resolve_render_manifest(self._storage, project_id)
        if resolution.manifest is None:
            if resolution.errors and any(resolution.path_exists.values()):
                raise StorageError(
                    "Stored render manifest is corrupt or incomplete.",
                    details={
                        "project_id": project_id,
                        "searched_paths": resolution.searched_paths,
                        "errors": resolution.errors,
                    },
                )
            return None
        try:
            return RenderManifest.from_dict(resolution.manifest)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                "Stored render manifest is corrupt.",
                details={
                    "project_id": project_id,
                    "artifact_path": resolution.artifact_path,
                    "manifest_source_path": resolution.manifest_source_path,
                },
            ) from exc

    async def save(self, manifest: RenderManifest) -> None:
        payload = manifest.to_dict()
        data = json.dumps(payload, indent=2).encode("utf-8")
        await self._storage.put(
            _index_key(manifest.project_id), data, content_type="application/json"
        )
        canonical = canonical_render_manifest_path(manifest.project_id)
        if await self._storage.exists(canonical):
            try:
                run_index = json.loads(await self._storage.get(canonical))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                raise StorageError(
                    "Canonical render run index is corrupt.",
                    details={"project_id": manifest.project_id, "path": canonical},
                ) from exc
            if not isinstance(run_index, dict):
                raise StorageError(
                    "Canonical render run index is not an object.",
                    details={"project_id": manifest.project_id, "path": canonical},
                )
            run_index["render_manifest"] = payload
            await self._storage.put(
                canonical,
                json.dumps(run_index, indent=2).encode("utf-8"),
                content_type="application/json",
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
