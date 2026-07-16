"""Artifact-aware checkpoints for durable workflow stages."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.project import Project
from olympus.domain.entities.workflow import Job
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
            return await self._inspect_render(project.id)
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
            checkpoint = await self._inspect_render(project_id)
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

    async def _inspect_render(self, project_id: str) -> dict[str, Any]:
        manifest_key = f"render/{project_id}/index.json"
        checkpoint = await self._inspect_json_index(manifest_key)
        if not checkpoint["valid"]:
            checkpoint["artifact_version"] = None
            return checkpoint
        manifest = checkpoint.pop("payload", {})
        renders = manifest.get("renders")
        if not isinstance(renders, list) or not renders:
            checkpoint["valid"] = False
            checkpoint["warnings"].append("Render manifest contains no MP4 outputs.")
            checkpoint["rendered_clip_count"] = 0
            return checkpoint
        errors: list[str] = []
        for render in renders:
            if not isinstance(render, dict):
                errors.append("Render manifest contains an invalid clip entry.")
                continue
            key = render.get("storage_key")
            if not isinstance(key, str) or not await self._storage.exists(key):
                errors.append(f"Rendered MP4 is missing: {key or '<no storage key>'}.")
                continue
            data = await self._storage.get(key)
            expected_size = render.get("size_bytes")
            if expected_size is not None and int(expected_size) != len(data):
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
        if errors:
            checkpoint["valid"] = False
            checkpoint["warnings"].extend(errors)
        return checkpoint

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
