"""Regression tests for Rendering -> checkpoint -> Optimization handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from olympus.data.repositories import (
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.workflow import EngineRunner, EngineRunResult
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.workflow import WORKFLOW_STAGES, Job, JobStatus, WorkflowStatus
from olympus.jobs import CheckpointValidator
from olympus.rendering.artifacts import (
    canonical_render_manifest_path,
    legacy_render_manifest_path,
    render_manifest_stage_path,
    resolve_render_manifest,
)
from olympus.services.workflow import WorkflowService
from olympus.utils import new_id, utc_now


def _project(project_id: str | None = None) -> Project:
    now = utc_now()
    identifier = project_id or new_id("proj")
    return Project(
        id=identifier,
        name="Render Checkpoint Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{identifier}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=20.0,
        width=1920,
        height=1080,
        status=ProjectStatus.PROCESSING,
        created_at=now,
        updated_at=now,
    )


def _job(project_id: str, *, artifact_path: str | None = None) -> Job:
    job = Job(
        job_id="job_rendering",
        workflow_id="workflow_rendering",
        project_id=project_id,
        engine="rendering",
        stage="rendering",
    )
    if artifact_path:
        job.checkpoint = {"artifact_path": artifact_path, "artifact_version": "11"}
    return job


def _manifest(project_id: str, render_key: str, data: bytes) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "status": "completed",
        "rendering_version": "11",
        "timeline_version": "8",
        "renders": [
            {
                "clip_id": "clip_one",
                "storage_key": render_key,
                "size_bytes": len(data),
                "checksum": f"sha256:{hashlib.sha256(data).hexdigest()}",
            }
        ],
    }


async def _write_canonical_render(
    storage: LocalStorage,
    project_id: str,
    *,
    include_mp4: bool = True,
) -> tuple[str, bytes]:
    render_key = f"render/{project_id}/clips/clip_one.mp4"
    data = b"synthetic-render-checkpoint-bytes"
    if include_mp4:
        await storage.put(render_key, data, content_type="video/mp4")
    payload = {
        "project_id": project_id,
        "pipeline_version": "1",
        "status": "completed",
        "created_at": utc_now().isoformat(),
        "updated_at": utc_now().isoformat(),
        "stages": [],
        "render_manifest": _manifest(project_id, render_key, data),
    }
    await storage.put(
        canonical_render_manifest_path(project_id),
        json.dumps(payload).encode(),
        content_type="application/json",
    )
    return render_key, data


async def _write_legacy_render(storage: LocalStorage, project_id: str) -> None:
    render_key = f"render/{project_id}/clips/legacy.mp4"
    data = b"legacy-render-bytes"
    await storage.put(render_key, data, content_type="video/mp4")
    await storage.put(
        legacy_render_manifest_path(project_id),
        json.dumps(_manifest(project_id, render_key, data)).encode(),
        content_type="application/json",
    )


class _ArtifactRunner(EngineRunner):
    def __init__(
        self,
        engine: str,
        storage: LocalStorage,
        *,
        render_manifest: bool,
    ) -> None:
        self.engine = engine
        self.storage = storage
        self.render_manifest = render_manifest
        self.calls = 0
        self.optimization_saw_manifest = False

    async def run(self, project: Project, job: Job) -> EngineRunResult:
        del job
        self.calls += 1
        if self.engine == "rendering":
            if self.render_manifest:
                await _write_canonical_render(self.storage, project.id)
            else:
                await self.storage.put(
                    canonical_render_manifest_path(project.id),
                    json.dumps(
                        {
                            "project_id": project.id,
                            "pipeline_version": "1",
                            "status": "completed",
                            "stages": [],
                        }
                    ).encode(),
                    content_type="application/json",
                )
        elif self.engine == "optimization":
            manifest = await StorageRenderManifestRepository(self.storage).load(project.id)
            self.optimization_saw_manifest = manifest is not None and bool(manifest.renders)
            if not self.optimization_saw_manifest:
                return EngineRunResult(
                    status="failed",
                    error="optimization could not resolve validated render manifest",
                )
            await self._write_index(project.id)
        elif self.engine != "upload":
            await self._write_index(project.id)
        return EngineRunResult(status="completed", summary={"calls": self.calls})

    async def _write_index(self, project_id: str) -> None:
        prefixes = {
            "cognitive": "analysis",
            "story": "story",
            "virality": "virality",
            "planning": "planning",
            "editing": "editing",
            "optimization": "optimization",
        }
        await self.storage.put(
            f"{prefixes[self.engine]}/{project_id}/index.json",
            json.dumps({"status": "completed", "pipeline_version": "1"}).encode(),
            content_type="application/json",
        )


async def _workflow_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    render_manifest: bool,
) -> tuple[WorkflowService, LocalStorage, Project, dict[str, _ArtifactRunner]]:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    await StorageProjectRepository(storage).save(project)
    await storage.put(project.storage_key, b"source-bytes", content_type="video/mp4")
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)
    runners = {
        spec.engine: _ArtifactRunner(
            spec.engine,
            storage,
            render_manifest=render_manifest,
        )
        for spec in WORKFLOW_STAGES
    }
    service = WorkflowService(
        repository=StorageWorkflowRepository(storage),
        project_repo=StorageProjectRepository(storage),
        runners=runners,
        concurrency=1,
        max_attempts=1,
        backoff_base_seconds=0.01,
        heartbeat_interval_seconds=0.02,
        stale_after_seconds=1.0,
        worker_poll_interval_seconds=0.01,
        checkpoint_validator=validator,
    )
    return service, storage, project, runners


def test_canonical_render_manifest_path() -> None:
    assert canonical_render_manifest_path("proj_one") == "render/proj_one/run/index.json"


def test_legacy_render_manifest_path() -> None:
    assert legacy_render_manifest_path("proj_one") == "render/proj_one/index.json"


@pytest.mark.asyncio
async def test_storage_relative_path_resolves_through_storage_root(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    storage = LocalStorage(root=str(storage_root))
    project = _project()
    await _write_canonical_render(storage, project.id)

    resolved = await resolve_render_manifest(storage, project.id)

    assert resolved.artifact_path == canonical_render_manifest_path(project.id)
    assert resolved.storage_root == str(storage_root.resolve())
    assert str((storage_root / resolved.canonical_path).resolve()) in (
        resolved.resolved_physical_paths
    )


@pytest.mark.asyncio
async def test_absolute_artifact_path_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    render_key = f"render/{project.id}/clips/absolute.mp4"
    data = b"absolute-render-bytes"
    await storage.put(render_key, data, content_type="video/mp4")
    absolute_manifest = tmp_path / "absolute-render-manifest.json"
    absolute_manifest.write_text(
        json.dumps(_manifest(project.id, render_key, data)), encoding="utf-8"
    )
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)

    checkpoint = await validator.validate_existing(
        _job(project.id, artifact_path=str(absolute_manifest)), project.id
    )

    assert checkpoint["valid"] is True
    assert checkpoint["artifact_path"] == str(absolute_manifest)


@pytest.mark.asyncio
async def test_old_wrong_checkpoint_discovers_canonical_run_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    await _write_canonical_render(storage, project.id)
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)

    checkpoint = await validator.validate_existing(
        _job(project.id, artifact_path=legacy_render_manifest_path(project.id)),
        project.id,
    )

    assert checkpoint["valid"] is True
    assert checkpoint["artifact_path"] == canonical_render_manifest_path(project.id)
    assert checkpoint["stored_artifact_path"] == legacy_render_manifest_path(project.id)


@pytest.mark.asyncio
async def test_old_run_recovers_manifest_from_persisted_stage_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    render_key = f"render/{project.id}/clips/stage_recovery.mp4"
    data = b"stage-recovery-render-bytes"
    await storage.put(render_key, data, content_type="video/mp4")
    await storage.put(
        canonical_render_manifest_path(project.id),
        json.dumps(
            {
                "project_id": project.id,
                "pipeline_version": "1",
                "status": "completed",
                "stages": [],
            }
        ).encode(),
        content_type="application/json",
    )
    await storage.put(
        render_manifest_stage_path(project.id),
        json.dumps(
            {
                "stage": "generate_render_manifest",
                "status": "completed",
                "data": {"manifest": _manifest(project.id, render_key, data)},
            }
        ).encode(),
        content_type="application/json",
    )
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)

    checkpoint = await validator.inspect_render(project.id)
    optimization_manifest = await StorageRenderManifestRepository(storage).load(project.id)

    assert checkpoint["valid"] is True
    assert checkpoint["artifact_path"] == canonical_render_manifest_path(project.id)
    assert checkpoint["manifest_source_path"] == render_manifest_stage_path(project.id)
    assert optimization_manifest is not None and len(optimization_manifest.renders) == 1


@pytest.mark.asyncio
async def test_canonical_manifest_outranks_existing_stored_legacy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    await _write_canonical_render(storage, project.id)
    await _write_legacy_render(storage, project.id)
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)

    checkpoint = await validator.validate_existing(
        _job(project.id, artifact_path=legacy_render_manifest_path(project.id)),
        project.id,
    )

    assert checkpoint["valid"] is True
    assert checkpoint["artifact_path"] == canonical_render_manifest_path(project.id)


@pytest.mark.asyncio
async def test_legacy_manifest_remains_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    await _write_legacy_render(storage, project.id)
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)

    checkpoint = await validator.inspect_render(project.id)

    assert checkpoint["valid"] is True
    assert checkpoint["artifact_path"] == legacy_render_manifest_path(project.id)
    assert any("legacy" in warning.lower() for warning in checkpoint["warnings"])


@pytest.mark.asyncio
async def test_missing_manifest_fails_checkpoint_validation(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()

    checkpoint = await CheckpointValidator(storage).inspect_render(project.id)

    assert checkpoint["valid"] is False
    assert checkpoint["manifest_exists"] is False
    assert canonical_render_manifest_path(project.id) in checkpoint["searched_paths"]


@pytest.mark.asyncio
async def test_invalid_json_manifest_fails_validation(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    await storage.put(
        canonical_render_manifest_path(project.id),
        b"{not-json",
        content_type="application/json",
    )

    checkpoint = await CheckpointValidator(storage).inspect_render(project.id)

    assert checkpoint["valid"] is False
    assert any("corrupt" in warning.lower() for warning in checkpoint["warnings"])


@pytest.mark.asyncio
async def test_manifest_with_missing_mp4_fails_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    await _write_canonical_render(storage, project.id, include_mp4=False)
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)

    checkpoint = await validator.inspect_render(project.id)

    assert checkpoint["valid"] is False
    assert checkpoint["manifest_exists"] is True
    assert checkpoint["mp4_files_exist"] is False


@pytest.mark.asyncio
async def test_manifest_with_valid_mp4_passes_when_ffprobe_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = LocalStorage(root=str(tmp_path))
    project = _project()
    await _write_canonical_render(storage, project.id)
    validator = CheckpointValidator(storage)
    monkeypatch.setattr(validator, "_ffprobe_passes", lambda _path: True)

    checkpoint = await validator.inspect_render(project.id)

    assert checkpoint["valid"] is True
    assert checkpoint["artifact_path"] == canonical_render_manifest_path(project.id)
    assert checkpoint["mp4_files_exist"] is True


@pytest.mark.asyncio
async def test_render_stage_cannot_complete_without_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _storage, project, _runners = await _workflow_service(
        tmp_path, monkeypatch, render_manifest=False
    )
    try:
        await service.start(project)
        workflow = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()

    rendering = workflow.job("rendering")
    assert rendering is not None and rendering.status is JobStatus.DEAD
    assert rendering.checkpoint["valid"] is False


@pytest.mark.asyncio
async def test_render_stage_stores_canonical_artifact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _storage, project, _runners = await _workflow_service(
        tmp_path, monkeypatch, render_manifest=True
    )
    try:
        await service.start(project)
        workflow = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()

    rendering = workflow.job("rendering")
    assert rendering is not None and rendering.status is JobStatus.COMPLETED
    assert rendering.checkpoint["artifact_path"] == canonical_render_manifest_path(project.id)


@pytest.mark.asyncio
async def test_optimization_stays_blocked_without_valid_render_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _storage, project, runners = await _workflow_service(
        tmp_path, monkeypatch, render_manifest=False
    )
    try:
        await service.start(project)
        workflow = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()

    optimization = workflow.job("optimization")
    assert workflow.status is WorkflowStatus.FAILED
    assert optimization is not None and optimization.status is JobStatus.BLOCKED
    assert runners["optimization"].calls == 0


@pytest.mark.asyncio
async def test_optimization_unblocks_and_reads_canonical_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _storage, project, runners = await _workflow_service(
        tmp_path, monkeypatch, render_manifest=True
    )
    try:
        await service.start(project)
        workflow = await service.wait_for(project.id, timeout=10)
    finally:
        await service.stop_pool()

    optimization = workflow.job("optimization")
    assert workflow.status is WorkflowStatus.COMPLETED
    assert optimization is not None and optimization.status is JobStatus.COMPLETED
    assert runners["optimization"].optimization_saw_manifest is True


@pytest.mark.asyncio
async def test_repair_helper_updates_old_path_and_rearms_optimization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, storage, project, _runners = await _workflow_service(
        tmp_path, monkeypatch, render_manifest=False
    )
    try:
        await service.start(project)
        failed = await service.wait_for(project.id, timeout=10)
        await service.stop_pool()
        rendering = failed.job("rendering")
        assert rendering is not None
        rendering.checkpoint = {
            "artifact_path": legacy_render_manifest_path(project.id),
            "artifact_version": "11",
        }
        await service._repo.save(failed)
        await _write_canonical_render(storage, project.id)

        repair = await service.repair_render_checkpoint_artifact_path(project.id)
        repaired = await service.get(project.id)
    finally:
        await service.stop_pool()

    assert repair["repaired"] is True
    assert repair["artifact_path"] == canonical_render_manifest_path(project.id)
    assert repaired is not None
    assert repaired.job("rendering").status is JobStatus.COMPLETED  # type: ignore[union-attr]
    assert repaired.job("optimization").status is JobStatus.READY  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_error_message_includes_all_searched_paths(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    stored = legacy_render_manifest_path(project.id)

    checkpoint = await CheckpointValidator(storage).inspect_render(
        project.id, stored_artifact_path=stored
    )

    detail = checkpoint["warnings"][0]
    assert f"project_id={project.id}" in detail
    assert "stage=rendering" in detail
    assert "stored_artifact_path" in detail
    assert "canonical_expected_path" in detail
    assert "legacy_fallback_path" in detail
    assert "storage_root" in detail
    assert "searched_paths" in detail
    assert "manifest_exists=False" in detail
    assert "mp4_files_exist=False" in detail
