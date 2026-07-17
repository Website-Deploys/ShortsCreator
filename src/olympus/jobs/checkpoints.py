"""Artifact-aware checkpoints for durable workflow stages."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.project import Project
from olympus.domain.entities.workflow import Job
from olympus.platform.errors import StorageError
from olympus.rendering.artifacts import RenderManifestResolution, resolve_render_manifest
from olympus.rendering.command import build_ffprobe_command
from olympus.utils import utc_now

_INDEX_KEYS = {
    "cognitive": "analysis/{project_id}/index.json",
    "story": "story/{project_id}/index.json",
    "virality": "virality/{project_id}/index.json",
    "planning": "planning/{project_id}/index.json",
    "editing": "editing/{project_id}/index.json",
    "optimization": "optimization/{project_id}/index.json",
}


class CheckpointValidator:
    """Build and revalidate stage checkpoints against real stored artifacts."""

    def __init__(self, storage: StoragePort, *, ffprobe_binary: str = "ffprobe") -> None:
        self._storage = storage
        self._ffprobe_binary = ffprobe_binary

    async def inspect(self, project: Project, job: Job) -> dict[str, Any]:
        if job.engine == "upload":
            return await self._inspect_object(project.storage_key, artifact_version="source")
        if job.engine == "rendering":
            stored_path = job.checkpoint.get("artifact_path")
            return await self.inspect_render(
                project.id,
                stored_artifact_path=stored_path if isinstance(stored_path, str) else None,
            )
        template = _INDEX_KEYS.get(job.engine)
        if template is None:
            return self._missing(None, f"No checkpoint mapping exists for {job.engine}.")
        key = template.format(project_id=project.id)
        checkpoint = await self._inspect_json_index(key)
        if checkpoint["valid"]:
            payload = checkpoint.pop("payload", {})
            checkpoint["artifact_version"] = str(payload.get("pipeline_version") or "unknown")
        return checkpoint

    async def validate_existing(self, job: Job, project_id: str) -> dict[str, Any]:
        if job.engine == "rendering":
            stored_path = job.checkpoint.get("artifact_path")
            checkpoint = await self.inspect_render(
                project_id,
                stored_artifact_path=stored_path if isinstance(stored_path, str) else None,
            )
            if not checkpoint["valid"]:
                return checkpoint
            actual_version = str(checkpoint.get("artifact_version") or "unknown")
            expected_version = str(job.checkpoint.get("artifact_version") or actual_version)
            if actual_version != expected_version:
                checkpoint["valid"] = False
                checkpoint["warnings"].append(
                    f"Artifact version changed from {expected_version} to {actual_version}."
                )
            return checkpoint
        key = job.checkpoint.get("artifact_path")
        if not isinstance(key, str) or not key:
            return self._missing(None, "Completed stage has no artifact checkpoint.")
        if job.engine == "upload":
            return await self._inspect_object(
                key,
                artifact_version=str(job.checkpoint.get("artifact_version") or "source"),
            )
        checkpoint = await self._inspect_json_index(key)
        if not checkpoint["valid"]:
            return checkpoint
        payload = checkpoint.pop("payload", {})
        actual_version = str(payload.get("pipeline_version") or "unknown")
        expected_version = str(job.checkpoint.get("artifact_version") or actual_version)
        checkpoint["artifact_version"] = actual_version
        if actual_version != expected_version:
            checkpoint["valid"] = False
            checkpoint["warnings"].append(
                f"Artifact version changed from {expected_version} to {actual_version}."
            )
        return checkpoint

    async def _inspect_json_index(self, key: str) -> dict[str, Any]:
        checkpoint = await self._inspect_object(key)
        if not checkpoint["valid"]:
            return checkpoint
        try:
            payload = json.loads(await self._storage.get(key))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return self._missing(key, "Checkpoint JSON is corrupt.")
        if not isinstance(payload, dict):
            return self._missing(key, "Checkpoint JSON is not an object.")
        if payload.get("status") != "completed":
            checkpoint["valid"] = False
            checkpoint["warnings"].append(
                f"Artifact status is {payload.get('status')!r}, not 'completed'."
            )
        checkpoint["payload"] = payload
        return checkpoint

    async def inspect_render(
        self,
        project_id: str,
        *,
        stored_artifact_path: str | None = None,
    ) -> dict[str, Any]:
        """Validate the canonical render handoff and every referenced MP4."""

        resolution = await resolve_render_manifest(
            self._storage,
            project_id,
            stored_artifact_path=stored_artifact_path,
        )
        if resolution.manifest is None or resolution.artifact_data is None:
            return self._missing_render(resolution)
        manifest = resolution.manifest
        checkpoint = self._render_checkpoint_base(resolution)
        errors: list[str] = []
        artifact_status = (resolution.artifact_payload or {}).get("status")
        if artifact_status != "completed":
            errors.append(
                f"Canonical checkpoint status is {artifact_status!r}, not 'completed'."
            )
        if manifest.get("status") != "completed":
            errors.append(
                f"Render manifest status is {manifest.get('status')!r}, not 'completed'."
            )
        manifest_project_id = manifest.get("project_id")
        if manifest_project_id is not None and str(manifest_project_id) != project_id:
            errors.append(
                "Render manifest project id does not match checkpoint project: "
                f"{manifest_project_id!r}."
            )
        renders = manifest.get("renders")
        if not isinstance(renders, list) or not renders:
            errors.append("Render manifest contains no MP4 outputs.")
            renders = []
        mp4_exists: dict[str, bool] = {}
        mp4_presence: list[bool] = []
        for index, render in enumerate(renders):
            if not isinstance(render, dict):
                errors.append("Render manifest contains an invalid clip entry.")
                mp4_exists[f"<invalid clip entry {index}>"] = False
                mp4_presence.append(False)
                continue
            key = render.get("storage_key")
            try:
                exists = bool(isinstance(key, str) and await self._storage.exists(key))
            except StorageError as exc:
                exists = False
                errors.append(f"Rendered MP4 could not be inspected: {key}: {exc}.")
            mp4_exists[str(key or "<no storage key>")] = exists
            mp4_presence.append(exists)
            if not exists or not isinstance(key, str):
                errors.append(f"Rendered MP4 is missing: {key or '<no storage key>'}.")
                continue
            try:
                data = await self._storage.get(key)
            except StorageError as exc:
                mp4_exists[key] = False
                mp4_presence[-1] = False
                errors.append(f"Rendered MP4 could not be read: {key}: {exc}.")
                continue
            expected_size = render.get("size_bytes")
            if expected_size is not None:
                try:
                    parsed_size = int(expected_size)
                except (TypeError, ValueError):
                    errors.append(f"Rendered MP4 size is invalid in manifest: {key}.")
                else:
                    if parsed_size != len(data):
                        errors.append(f"Rendered MP4 size does not match manifest: {key}.")
            expected_checksum = render.get("checksum")
            if expected_checksum:
                expected_digest = str(expected_checksum).removeprefix("sha256:")
                if hashlib.sha256(data).hexdigest() != expected_digest:
                    errors.append(f"Rendered MP4 checksum does not match manifest: {key}.")
            local_path = self._storage.local_path(key)
            if local_path:
                probe_passed = await asyncio.to_thread(
                    self._ffprobe_passes,
                    Path(local_path),
                )
            else:
                probe_passed = await asyncio.to_thread(self._ffprobe_bytes, data)
            if probe_passed is None:
                errors.append(
                    "Rendered MP4 could not be validated because ffprobe is "
                    f"unavailable: {key}."
                )
            elif not probe_passed:
                errors.append(f"Rendered MP4 failed ffprobe validation: {key}.")
        checkpoint["artifact_version"] = str(
            manifest.get("rendering_version") or manifest.get("timeline_version") or "unknown"
        )
        checkpoint["rendered_clip_count"] = len(renders)
        checkpoint["rendered_artifacts"] = [
            render.get("storage_key") for render in renders if isinstance(render, dict)
        ]
        checkpoint["manifest_exists"] = True
        checkpoint["mp4_files"] = mp4_exists
        checkpoint["mp4_files_exist"] = bool(renders) and all(mp4_presence)
        if errors:
            checkpoint["valid"] = False
            checkpoint["warnings"] = [
                self._render_failure_summary(
                    resolution,
                    manifest_exists=True,
                    mp4_files_exist=bool(checkpoint["mp4_files_exist"]),
                    reasons=errors,
                ),
                *checkpoint["warnings"],
                *errors,
            ]
        return checkpoint

    async def repair_render_checkpoint_artifact_path(
        self,
        job: Job,
        project_id: str,
    ) -> dict[str, Any]:
        """Validate and replace a rendering job's stale artifact path in memory."""

        stored_path = job.checkpoint.get("artifact_path")
        checkpoint = await self.inspect_render(
            project_id,
            stored_artifact_path=stored_path if isinstance(stored_path, str) else None,
        )
        if checkpoint.get("valid"):
            job.checkpoint = checkpoint
        return checkpoint

    def _render_checkpoint_base(
        self,
        resolution: RenderManifestResolution,
    ) -> dict[str, Any]:
        data = resolution.artifact_data or b""
        local_path = self._artifact_local_path(resolution.artifact_path)
        mtime: float | None = None
        if local_path is not None:
            try:
                mtime = local_path.stat().st_mtime
            except OSError:
                mtime = None
        return {
            "checkpoint_key": resolution.artifact_path,
            "artifact_path": resolution.artifact_path,
            "stored_artifact_path": resolution.stored_artifact_path,
            "canonical_expected_path": resolution.canonical_path,
            "legacy_fallback_path": resolution.legacy_path,
            "manifest_source_path": resolution.manifest_source_path,
            "storage_root": resolution.storage_root,
            "searched_paths": resolution.searched_paths,
            "resolved_physical_paths": resolution.resolved_physical_paths,
            "path_exists": resolution.path_exists,
            "artifact_version": None,
            "artifact_checksum": hashlib.sha256(data).hexdigest(),
            "artifact_size_bytes": len(data),
            "artifact_mtime": mtime,
            "validated_at": utc_now().isoformat(),
            "valid": bool(data),
            "manifest_exists": resolution.manifest_exists,
            "mp4_files_exist": False,
            "warnings": [*resolution.warnings, *resolution.errors],
        }

    def _ffprobe_bytes(self, data: bytes) -> bool | None:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(data)
            path = Path(handle.name)
        try:
            return self._ffprobe_passes(path)
        finally:
            with suppress(OSError):
                path.unlink(missing_ok=True)

    def _artifact_local_path(self, artifact_path: str | None) -> Path | None:
        if not artifact_path:
            return None
        path = Path(artifact_path)
        if path.is_absolute():
            return path if path.exists() else None
        local = self._storage.local_path(artifact_path)
        return Path(local) if local else None

    def _missing_render(self, resolution: RenderManifestResolution) -> dict[str, Any]:
        reasons = (
            resolution.errors
            or resolution.warnings
            or ["No usable render manifest was found."]
        )
        artifact_path = resolution.stored_artifact_path or resolution.canonical_path
        return {
            "checkpoint_key": artifact_path,
            "artifact_path": artifact_path,
            "stored_artifact_path": resolution.stored_artifact_path,
            "canonical_expected_path": resolution.canonical_path,
            "legacy_fallback_path": resolution.legacy_path,
            "manifest_source_path": resolution.manifest_source_path,
            "storage_root": resolution.storage_root,
            "searched_paths": resolution.searched_paths,
            "resolved_physical_paths": resolution.resolved_physical_paths,
            "path_exists": resolution.path_exists,
            "artifact_version": None,
            "artifact_checksum": None,
            "artifact_size_bytes": None,
            "artifact_mtime": None,
            "validated_at": utc_now().isoformat(),
            "valid": False,
            "manifest_exists": False,
            "mp4_files_exist": False,
            "mp4_files": {},
            "rendered_clip_count": 0,
            "rendered_artifacts": [],
            "warnings": [
                self._render_failure_summary(
                    resolution,
                    manifest_exists=False,
                    mp4_files_exist=False,
                    reasons=reasons,
                ),
                *resolution.warnings,
                *reasons,
            ],
        }

    @staticmethod
    def _render_failure_summary(
        resolution: RenderManifestResolution,
        *,
        manifest_exists: bool,
        mp4_files_exist: bool,
        reasons: list[str],
    ) -> str:
        return (
            "Render checkpoint validation failed: "
            f"project_id={resolution.project_id}; stage=rendering; "
            f"stored_artifact_path={resolution.stored_artifact_path!r}; "
            f"canonical_expected_path={resolution.canonical_path!r}; "
            f"legacy_fallback_path={resolution.legacy_path!r}; "
            f"storage_root={resolution.storage_root!r}; "
            f"searched_paths={resolution.searched_paths!r}; "
            f"resolved_physical_paths={resolution.resolved_physical_paths!r}; "
            f"manifest_exists={manifest_exists}; mp4_files_exist={mp4_files_exist}; "
            f"reasons={reasons!r}."
        )

    async def _inspect_object(
        self,
        key: str,
        *,
        artifact_version: str | None = None,
    ) -> dict[str, Any]:
        if not await self._storage.exists(key):
            return self._missing(key, "Checkpoint artifact is missing.")
        data = await self._storage.get(key)
        local_path = self._storage.local_path(key)
        mtime: float | None = None
        if local_path:
            try:
                mtime = Path(local_path).stat().st_mtime
            except OSError:
                mtime = None
        return {
            "checkpoint_key": key,
            "artifact_path": key,
            "artifact_version": artifact_version,
            "artifact_checksum": hashlib.sha256(data).hexdigest(),
            "artifact_size_bytes": len(data),
            "artifact_mtime": mtime,
            "validated_at": utc_now().isoformat(),
            "valid": bool(data),
            "warnings": [] if data else ["Checkpoint artifact is empty."],
        }

    def _ffprobe_passes(self, path: Path) -> bool | None:
        binary = shutil.which(self._ffprobe_binary)
        if binary is None:
            return None
        try:
            completed = subprocess.run(
                build_ffprobe_command(binary=binary, path=str(path)),
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if completed.returncode != 0:
            return False
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return False
        streams = payload.get("streams") if isinstance(payload, dict) else None
        return isinstance(streams, list) and any(
            isinstance(stream, dict) and stream.get("codec_type") == "video"
            for stream in streams
        )

    @staticmethod
    def _missing(key: str | None, warning: str) -> dict[str, Any]:
        return {
            "checkpoint_key": key,
            "artifact_path": key,
            "artifact_version": None,
            "artifact_checksum": None,
            "artifact_size_bytes": None,
            "artifact_mtime": None,
            "validated_at": utc_now().isoformat(),
            "valid": False,
            "warnings": [warning],
        }
