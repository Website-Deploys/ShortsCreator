"""Tests for the Project Management & Asset Library subsystem.

These verify the library aggregates real engine outputs honestly (assets, clips,
exports, dashboard, storage), that version history is append-only + deduplicated,
that the activity feed reflects real recorded + derived events, that favorites/
tags/archive are additive metadata, and that cleanup removes only what it claims.
Plus the HTTP API. The subsystem never modifies an engine's data - it reads it.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import library_service_provider
from olympus.data.repositories import (
    StorageActivityRepository,
    StorageAnalysisRepository,
    StorageEditingRepository,
    StorageLibraryMetaRepository,
    StorageOptimizationRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageRenderRunRepository,
    StorageStoryRepository,
    StorageVersionRepository,
    StorageViralityRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.analysis import Analysis, AnalysisStatus, StageResult, StageStatus
from olympus.domain.entities.planning import (
    ClipPlanningAnalysis,
    PlanningStageResult,
    PlanningStageStatus,
    PlanningStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.render_pipeline import (
    RENDER_STAGE_ORDER,
    RenderRun,
    RenderRunStatus,
    RenderStageResult,
    RenderStageStatus,
)
from olympus.domain.entities.rendering import RenderedVideo, RenderManifest, RenderStatus
from olympus.editing import build_default_editing_analyzers
from olympus.editing.pipeline import EditingPipeline
from olympus.services.project_management import LibraryService
from olympus.utils import new_id, utc_now

_MP4 = b"\x00\x00\x00\x18ftypmp42LIBRARY-FIXTURE-BYTES-0123456789"
TRANSCRIPT = [
    {
        "start": 0.0,
        "end": 8.0,
        "speaker": "spk_0",
        "text": "Why do most people fail at productivity?",
    },
    {
        "start": 8.0,
        "end": 20.0,
        "speaker": "spk_0",
        "text": "The real problem is treating every task as urgent.",
    },
    {
        "start": 20.0,
        "end": 38.0,
        "speaker": "spk_0",
        "text": "Time blocking changed everything for me.",
    },
]


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


def _project(name: str = "Productivity Tips") -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name=name,
        source_filename="productivity.mp4",
        storage_key=f"uploads/{new_id('u')}/source.mp4",
        size_bytes=len(_MP4),
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=40.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _analysis(pid: str) -> Analysis:
    now = utc_now()
    return Analysis(
        project_id=pid,
        pipeline_version="1",
        status=AnalysisStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            StageResult(
                stage="video_inspection",
                status=StageStatus.COMPLETED,
                version="1",
                data={"duration_seconds": 40.0, "width": 1920, "height": 1080, "fps": 30},
            ),
            StageResult(
                stage="speech_transcription",
                status=StageStatus.COMPLETED,
                version="1",
                data={"language": "en", "confidence": 0.9, "segments": TRANSCRIPT},
            ),
        ],
    )


def _planning(pid: str) -> ClipPlanningAnalysis:
    now = utc_now()
    plan = {
        "id": "clip_a",
        "rank": 1,
        "source_video": {"filename": "productivity.mp4", "storage_key": "uploads/u/source.mp4"},
        "start": 0.0,
        "end": 38.0,
        "duration": 38.0,
        "start_frame": 0,
        "end_frame": 1140,
        "fps": 30,
        "scores": {"hook": 0.7},
        "quality_score": 0.72,
        "confidence": 0.6,
        "explanation": "strong hook",
        "evidence": [],
        "alternatives": [],
        "blueprint": {
            "opening_hook": {"text": "Why do people fail?", "timestamp": 0.0, "evidence": "q"},
            "pacing": {"value": "fast", "reason": "dense"},
            "aspect_ratio": {"value": "9:16", "reason": "vertical"},
            "subtitle_style": {"style": "karaoke", "reason": "fast"},
            "title_suggestion": {"text": "Why people fail at productivity", "basis": "hook"},
            "zoom_suggestions": [{"timestamp": 5.0, "reason": "emphasis"}],
            "scene_cuts": {"cuts": [], "note": "none"},
            "speaker_switches": {"switches": [], "note": "single"},
        },
    }
    return ClipPlanningAnalysis(
        project_id=pid,
        pipeline_version="1",
        status=PlanningStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            PlanningStageResult(
                stage="ranking",
                status=PlanningStageStatus.COMPLETED,
                data={"plan_count": 1, "plans": [plan]},
            )
        ],
    )


async def _save_analysis(storage: LocalStorage, analysis: Analysis) -> None:
    repo = StorageAnalysisRepository(storage)
    await repo.save_index(analysis)
    for s in analysis.stages:
        await repo.save_stage(analysis.project_id, s)


async def _save_planning(storage: LocalStorage, planning: ClipPlanningAnalysis) -> None:
    repo = StoragePlanningRepository(storage)
    await repo.save_index(planning)
    for s in planning.stages:
        await repo.save_stage(planning.project_id, s)


async def _render_manifest(storage: LocalStorage, pid: str) -> RenderManifest:
    now = utc_now()
    key = f"render/{pid}/clips/clip_a.mp4"
    await storage.put(key, _MP4, content_type="video/mp4")
    manifest = RenderManifest(
        project_id=pid,
        status=RenderStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        renderer="ffmpeg",
        render_id=new_id("render"),
        rendering_version="1",
        timeline_version="1",
        renders=[
            RenderedVideo(
                clip_id="clip_a",
                storage_key=key,
                plan_id="clip_a",
                rank=1,
                width=1080,
                height=1920,
                duration=38.0,
                fps=30.0,
                video_codec="h264",
                audio_codec="aac",
                has_audio=True,
                bitrate_kbps=12000,
                size_bytes=len(_MP4),
                checksum="sha256:abc",
                subtitles_included=True,
                timeline_version="1",
            )
        ],
    )
    await StorageRenderManifestRepository(storage).save(manifest)
    return manifest


async def _render_run(storage: LocalStorage, pid: str, *, status: RenderRunStatus) -> None:
    now = utc_now()
    stages = [
        RenderStageResult(stage=s, status=RenderStageStatus.COMPLETED) for s in RENDER_STAGE_ORDER
    ]
    fr = next(s for s in stages if s.stage == "full_resolution_render")
    fr.started_at = now
    fr.completed_at = now + timedelta(seconds=3)
    run = RenderRun(
        project_id=pid,
        pipeline_version="1",
        status=status,
        created_at=now,
        updated_at=now,
        stages=stages,
    )
    repo = StorageRenderRunRepository(storage)
    await repo.save_index(run)
    for s in stages:
        await repo.save_stage(pid, s)


def _service(storage: LocalStorage) -> LibraryService:
    return LibraryService(
        storage=storage,
        project_repo=StorageProjectRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        story_repo=StorageStoryRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        editing_repo=StorageEditingRepository(storage),
        render_manifest_repo=StorageRenderManifestRepository(storage),
        render_run_repo=StorageRenderRunRepository(storage),
        optimization_repo=StorageOptimizationRepository(storage),
        workflow_repo=StorageWorkflowRepository(storage),
        version_repo=StorageVersionRepository(storage),
        activity_repo=StorageActivityRepository(storage),
        meta_repo=StorageLibraryMetaRepository(storage),
    )


async def _seed_full_project(storage: LocalStorage, *, name: str = "Productivity Tips") -> Project:
    """Seed a project with analysis -> editing -> render manifest + run."""

    project = _project(name)
    await StorageProjectRepository(storage).save(project)
    await storage.put(project.storage_key, _MP4, content_type="video/mp4")
    analysis = _analysis(project.id)
    planning = _planning(project.id)
    await _save_analysis(storage, analysis)
    await _save_planning(storage, planning)
    await EditingPipeline(build_default_editing_analyzers(), StorageEditingRepository(storage)).run(
        project, storage, analysis=analysis, planning=planning
    )
    await _render_manifest(storage, project.id)
    await _render_run(storage, project.id, status=RenderRunStatus.COMPLETED)
    return project


# --------------------------------------------------------------------------- #
# Aggregation: assets / clips / exports
# --------------------------------------------------------------------------- #
async def test_asset_library_aggregates_everything(storage: LocalStorage) -> None:
    project = await _seed_full_project(storage)
    svc = _service(storage)
    assets = await svc.assets()
    kinds = {a.kind.value for a in assets}
    assert "source_video" in kinds
    assert "clip" in kinds
    assert "render" in kinds
    assert "export" in kinds
    source = next(a for a in assets if a.kind.value == "source_video")
    assert source.size_bytes == len(_MP4)  # real measured size
    assert all(a.project_id == project.id for a in assets)


async def test_clip_library_has_real_per_clip_facts(storage: LocalStorage) -> None:
    await _seed_full_project(storage)
    svc = _service(storage)
    clips = await svc.clips()
    assert len(clips) == 1
    clip = clips[0]
    assert clip.clip_id == "clip_a"
    assert clip.duration == 38.0
    assert clip.viral_score == 0.72  # planner quality score
    assert clip.status == "rendered"  # a render exists
    assert clip.render_version == "1"


async def test_export_library_has_measured_media_facts(storage: LocalStorage) -> None:
    await _seed_full_project(storage)
    svc = _service(storage)
    exports = await svc.exports()
    assert len(exports) == 1
    e = exports[0]
    assert e.resolution == "1080x1920"
    assert e.codec == "h264"
    assert e.bitrate_kbps == 12000
    assert e.file_size == len(_MP4)
    assert e.download_status == "available"
    assert e.render_time_ms is not None and e.render_time_ms > 0  # from the render run


async def test_clip_unknown_when_not_rendered(storage: LocalStorage) -> None:
    """A planned-but-not-rendered clip reports honest status, no fabricated render."""

    project = _project()
    await StorageProjectRepository(storage).save(project)
    await storage.put(project.storage_key, _MP4, content_type="video/mp4")
    analysis, planning = _analysis(project.id), _planning(project.id)
    await _save_analysis(storage, analysis)
    await _save_planning(storage, planning)
    await EditingPipeline(build_default_editing_analyzers(), StorageEditingRepository(storage)).run(
        project, storage, analysis=analysis, planning=planning
    )
    svc = _service(storage)
    clips = await svc.clips()
    assert clips and clips[0].status == "planned"
    assert clips[0].render_version is None
    exports = await svc.exports()
    assert exports == []  # nothing rendered -> no exports fabricated


# --------------------------------------------------------------------------- #
# Dashboard + storage inspector
# --------------------------------------------------------------------------- #
async def test_dashboard_aggregates_globally(storage: LocalStorage) -> None:
    await _seed_full_project(storage, name="A")
    await _seed_full_project(storage, name="B")
    svc = _service(storage)
    stats = await svc.dashboard()
    assert stats.total_projects == 2
    assert stats.videos_processed == 2  # both have analysis
    assert stats.clips_generated == 2
    assert stats.renders_completed == 2
    assert stats.exports == 2
    assert stats.average_viral_score == 0.72
    assert stats.minutes_analyzed > 0
    assert stats.storage_bytes > 0


async def test_storage_inspector_breaks_down_by_namespace(storage: LocalStorage) -> None:
    project = await _seed_full_project(storage)
    svc = _service(storage)
    breakdowns = await svc.storage(project.id)
    assert len(breakdowns) == 1
    ns = breakdowns[0].namespaces
    assert set(ns).issuperset(
        {"uploads", "analysis", "editing", "renders", "exports", "optimization", "logs"}
    )
    assert ns["renders"] > 0  # the rendered clip file
    assert ns["editing"] > 0  # the editing artifacts
    assert breakdowns[0].total == sum(ns.values())


# --------------------------------------------------------------------------- #
# Version history
# --------------------------------------------------------------------------- #
async def test_version_history_is_append_only_and_deduplicated(storage: LocalStorage) -> None:
    project = await _seed_full_project(storage)
    svc = _service(storage)
    captured = await svc.capture_versions(project.id)
    engines = {v.engine for v in captured}
    assert {"cognitive", "planning", "editing", "rendering"}.issubset(engines)
    assert all(v.version == 1 for v in captured)
    # Re-capturing identical output creates no new versions (history not duplicated).
    again = await svc.capture_versions(project.id)
    assert again == []
    versions = await svc.list_versions(project.id, "editing")
    assert len(versions) == 1
    payload = await svc.get_version(project.id, "editing", 1)
    assert payload is not None and "stages" in payload


# --------------------------------------------------------------------------- #
# Activity feed
# --------------------------------------------------------------------------- #
async def test_activity_feed_reflects_real_events(storage: LocalStorage) -> None:
    project = await _seed_full_project(storage)
    svc = _service(storage)
    await svc.archive(project.id)
    feed = await svc.activity(project.id)
    types = {e.type.value for e in feed}
    assert "project_created" in types  # derived from real project
    assert "project_archived" in types  # recorded PM action


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
async def test_global_search(storage: LocalStorage) -> None:
    await _seed_full_project(storage, name="Productivity Tips")
    svc = _service(storage)
    hits = await svc.search("productivity")
    kinds = {h.kind for h in hits}
    assert "project" in kinds
    # Searching a clip title also returns clip hits.
    clip_hits = await svc.search("why people fail")
    assert any(h.kind == "clip" for h in clip_hits)


# --------------------------------------------------------------------------- #
# Favorites / tags / archive
# --------------------------------------------------------------------------- #
async def test_favorites_tags_archive_are_additive(storage: LocalStorage) -> None:
    project = await _seed_full_project(storage)
    svc = _service(storage)
    await svc.set_project_favorite(project.id, True)
    await svc.add_project_tag(project.id, "Best")
    meta = await svc.add_project_tag(project.id, "best")  # deduped (lowercased)
    assert meta.favorite is True
    assert meta.tags == ["best"]

    # Source asset reflects the project meta.
    source = next(a for a in await svc.assets() if a.kind.value == "source_video")
    assert source.favorite is True and "best" in source.tags

    # Archive hides from default views; archived=True surfaces it; restore brings it back.
    await svc.archive(project.id)
    assert await svc.assets() == []
    archived = await svc.assets(archived=True)
    assert archived and archived[0].archived is True
    await svc.restore(project.id)
    assert await svc.assets() != []


# --------------------------------------------------------------------------- #
# Cleanup tools
# --------------------------------------------------------------------------- #
async def test_cleanup_temp_files(storage: LocalStorage) -> None:
    project = await _seed_full_project(storage)
    await storage.put(
        f"render/{project.id}/work/preview_clip_a.mp4", _MP4, content_type="video/mp4"
    )
    svc = _service(storage)
    result = await svc.cleanup_temp_files(project.id)
    assert len(result.deleted_keys) == 1
    assert result.freed_bytes == len(_MP4)
    assert not await storage.exists(f"render/{project.id}/work/preview_clip_a.mp4")
    # The real rendered clip is untouched.
    assert await storage.exists(f"render/{project.id}/clips/clip_a.mp4")


async def test_cleanup_unused_renders_keeps_referenced(storage: LocalStorage) -> None:
    project = await _seed_full_project(storage)
    await storage.put(f"render/{project.id}/clips/orphan.mp4", _MP4, content_type="video/mp4")
    svc = _service(storage)
    result = await svc.cleanup_unused_renders(project.id)
    assert result.deleted_keys == [f"render/{project.id}/clips/orphan.mp4"]
    assert await storage.exists(f"render/{project.id}/clips/clip_a.mp4")  # referenced -> kept


async def test_cleanup_failed_renders(storage: LocalStorage) -> None:
    project = _project()
    await StorageProjectRepository(storage).save(project)
    await storage.put(f"render/{project.id}/clips/clip_a.mp4", _MP4, content_type="video/mp4")
    await _render_run(storage, project.id, status=RenderRunStatus.FAILED)
    svc = _service(storage)
    result = await svc.cleanup_failed_renders(project.id)
    assert result.deleted_keys  # failed run's clip files removed
    assert not await storage.exists(f"render/{project.id}/clips/clip_a.mp4")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_library_api_flow(app: Any, tmp_path: Path) -> None:
    import asyncio

    store = LocalStorage(root=str(tmp_path))
    project = asyncio.run(_seed_full_project(store))
    app.dependency_overrides[library_service_provider] = lambda: _service(store)

    with TestClient(app) as client:
        dash = client.get("/api/v1/library/dashboard")
        assert dash.status_code == 200 and dash.json()["total_projects"] == 1

        assets = client.get("/api/v1/library/assets")
        assert assets.status_code == 200 and assets.json()["count"] > 0

        clips = client.get("/api/v1/library/clips")
        assert clips.status_code == 200 and clips.json()["clips"][0]["clip_id"] == "clip_a"

        exports = client.get("/api/v1/library/exports")
        assert (
            exports.status_code == 200 and exports.json()["exports"][0]["resolution"] == "1080x1920"
        )

        srch = client.get("/api/v1/library/search", params={"q": "productivity"})
        assert srch.status_code == 200 and srch.json()["count"] > 0

        storage_resp = client.get("/api/v1/library/storage")
        assert storage_resp.status_code == 200 and storage_resp.json()["total_bytes"] > 0

        cap = client.post(f"/api/v1/library/projects/{project.id}/versions/capture")
        assert cap.status_code == 201 and cap.json()["captured"]
        engines = client.get(f"/api/v1/library/projects/{project.id}/versions")
        assert "editing" in engines.json()["engines"]

        fav = client.post(
            f"/api/v1/library/projects/{project.id}/favorite", json={"favorite": True}
        )
        assert fav.status_code == 200 and fav.json()["meta"]["favorite"] is True

        arch = client.post(f"/api/v1/library/projects/{project.id}/archive")
        assert arch.status_code == 200 and arch.json()["meta"]["archived"] is True
        assert client.get("/api/v1/library/assets").json()["count"] == 0  # archived hidden
        client.post(f"/api/v1/library/projects/{project.id}/restore")

        activity = client.get("/api/v1/library/activity")
        assert activity.status_code == 200 and activity.json()["count"] > 0

        cleanup = client.post(
            "/api/v1/library/cleanup/temp-files", params={"project_id": project.id}
        )
        assert cleanup.status_code == 200 and "result" in cleanup.json()
