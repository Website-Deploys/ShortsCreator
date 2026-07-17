"""Canonical render-manifest artifact paths and storage resolution."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.platform.errors import StorageError


def canonical_render_manifest_path(project_id: str) -> str:
    """Return the storage-relative durable render checkpoint path."""

    return f"render/{project_id}/run/index.json"


def legacy_render_manifest_path(project_id: str) -> str:
    """Return the pre-handoff published-manifest path."""

    return f"render/{project_id}/index.json"


def render_manifest_stage_path(project_id: str) -> str:
    """Return the full render-manifest stage artifact path."""

    return f"render/{project_id}/run/stages/generate_render_manifest.json"


@dataclass(slots=True)
class RenderManifestResolution:
    """Resolved checkpoint artifact plus the manifest payload it proves."""

    project_id: str
    stored_artifact_path: str | None
    canonical_path: str
    legacy_path: str
    stage_path: str
    storage_root: str | None
    artifact_path: str | None = None
    manifest_source_path: str | None = None
    artifact_data: bytes | None = None
    artifact_payload: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    searched_paths: list[str] = field(default_factory=list)
    resolved_physical_paths: list[str] = field(default_factory=list)
    path_exists: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def manifest_exists(self) -> bool:
        return self.manifest is not None


@dataclass(slots=True)
class _ReadArtifact:
    path: str
    exists: bool
    resolved_path: str
    data: bytes | None = None
    payload: dict[str, Any] | None = None
    error: str | None = None


def _storage_root(storage: StoragePort) -> str | None:
    return storage.local_path("")


def _resolved_path(storage: StoragePort, path: str, storage_root: str | None) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate.resolve())
    local = storage.local_path(path)
    if local:
        return str(Path(local).resolve())
    if storage_root:
        return str((Path(storage_root) / path).resolve())
    return path


async def _read_artifact(
    storage: StoragePort,
    path: str,
    *,
    storage_root: str | None,
) -> _ReadArtifact:
    candidate = Path(path)
    resolved = _resolved_path(storage, path, storage_root)
    try:
        if candidate.is_absolute():
            exists = await asyncio.to_thread(candidate.is_file)
            data = await asyncio.to_thread(candidate.read_bytes) if exists else None
        else:
            exists = await storage.exists(path)
            data = await storage.get(path) if exists else None
    except (OSError, StorageError, ValueError) as exc:
        return _ReadArtifact(
            path=path,
            exists=False,
            resolved_path=resolved,
            error=f"{type(exc).__name__}: {exc}",
        )
    if not exists or data is None:
        return _ReadArtifact(path=path, exists=False, resolved_path=resolved)
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        return _ReadArtifact(
            path=path,
            exists=True,
            resolved_path=resolved,
            data=data,
            error=f"Checkpoint JSON is corrupt: {type(exc).__name__}: {exc}",
        )
    if not isinstance(payload, dict):
        return _ReadArtifact(
            path=path,
            exists=True,
            resolved_path=resolved,
            data=data,
            error="Checkpoint JSON is not an object.",
        )
    return _ReadArtifact(
        path=path,
        exists=True,
        resolved_path=resolved,
        data=data,
        payload=payload,
    )


def _manifest_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(payload.get("renders"), list):
        return payload
    for key in ("render_manifest", "manifest"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("manifest")
        if isinstance(nested, dict):
            return nested
    return None


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


async def resolve_render_manifest(
    storage: StoragePort,
    project_id: str,
    *,
    stored_artifact_path: str | None = None,
) -> RenderManifestResolution:
    """Resolve a manifest through stored, canonical, legacy, and stage paths."""

    canonical = canonical_render_manifest_path(project_id)
    legacy = legacy_render_manifest_path(project_id)
    stage = render_manifest_stage_path(project_id)
    root = _storage_root(storage)
    resolution = RenderManifestResolution(
        project_id=project_id,
        stored_artifact_path=stored_artifact_path,
        canonical_path=canonical,
        legacy_path=legacy,
        stage_path=stage,
        storage_root=root,
    )
    candidates: list[str] = []
    if stored_artifact_path and stored_artifact_path != legacy:
        _append_unique(candidates, stored_artifact_path)
    _append_unique(candidates, canonical)
    _append_unique(candidates, legacy)

    canonical_artifact: _ReadArtifact | None = None
    for path in candidates:
        _append_unique(resolution.searched_paths, path)
        artifact = await _read_artifact(storage, path, storage_root=root)
        resolution.path_exists[path] = artifact.exists
        _append_unique(resolution.resolved_physical_paths, artifact.resolved_path)
        if path == canonical:
            canonical_artifact = artifact
        if artifact.error:
            resolution.errors.append(f"{path}: {artifact.error}")
            continue
        if artifact.payload is None:
            continue
        manifest = _manifest_from_payload(artifact.payload)
        if manifest is None:
            continue
        resolution.artifact_path = path
        resolution.manifest_source_path = path
        resolution.artifact_data = artifact.data
        resolution.artifact_payload = artifact.payload
        resolution.manifest = manifest
        if path == legacy:
            resolution.warnings.append(
                "Using legacy render manifest fallback; canonical run/index.json was unavailable."
            )
        return resolution

    _append_unique(resolution.searched_paths, stage)
    stage_artifact = await _read_artifact(storage, stage, storage_root=root)
    resolution.path_exists[stage] = stage_artifact.exists
    _append_unique(resolution.resolved_physical_paths, stage_artifact.resolved_path)
    if stage_artifact.error:
        resolution.errors.append(f"{stage}: {stage_artifact.error}")
    if stage_artifact.payload is not None:
        manifest = _manifest_from_payload(stage_artifact.payload)
        if manifest is not None:
            checkpoint_artifact = (
                canonical_artifact
                if canonical_artifact is not None and canonical_artifact.payload is not None
                else stage_artifact
            )
            resolution.artifact_path = (
                canonical if checkpoint_artifact is canonical_artifact else stage
            )
            resolution.manifest_source_path = stage
            resolution.artifact_data = checkpoint_artifact.data
            resolution.artifact_payload = checkpoint_artifact.payload
            resolution.manifest = manifest
            resolution.warnings.append(
                "Recovered render manifest from the canonical run stage artifact."
            )
            return resolution

    if canonical_artifact is not None and canonical_artifact.exists:
        resolution.warnings.append(
            "Canonical render run index exists but contains no render manifest reference."
        )
    return resolution
