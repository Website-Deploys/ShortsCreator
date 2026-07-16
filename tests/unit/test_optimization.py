"""Tests for the Optimization Engine: pipeline, stages, packages, downloads.

These verify the *honest* contract of post-render optimization:
- With a real render manifest + the upstream engines' output, the engine produces
  real, explained results: copyright-free music recommendations (with license),
  optimized captions (measured reading speed), titles/descriptions/hashtags from
  the real transcript, per-platform export specs, quality evaluation graded only
  from real signals, export variants, and downloadable publish packages (caption
  files + metadata written to storage).
- Without a render it reports ``UNAVAILABLE`` with a precise reason at load, and
  audio/visual enhancement is ``UNAVAILABLE`` (no model) - never fabricated. Any
  value that cannot be determined (audio/visual quality, thumbnail image scores)
  is ``UNKNOWN``.
- Work persists after every stage, runs resume, single stages re-run, and
  cancellation is cooperative.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import (
    optimization_service_provider,
    project_service_provider,
    storage_provider,
)
from olympus.data.repositories import (
    StorageAnalysisRepository,
    StorageEditingRepository,
    StorageOptimizationRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageStoryRepository,
    StorageViralityRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.analysis import Analysis, AnalysisStatus, StageResult, StageStatus
from olympus.domain.entities.optimization import (
    OPTIMIZATION_STAGE_ORDER,
    OptimizationStageStatus,
    OptimizationStatus,
)
from olympus.domain.entities.planning import (
    ClipPlanningAnalysis,
    PlanningStageResult,
    PlanningStageStatus,
    PlanningStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.rendering import RenderedVideo, RenderManifest, RenderStatus
from olympus.editing import build_default_editing_analyzers
from olympus.editing.pipeline import EditingPipeline
from olympus.optimization import build_default_optimization_analyzers
from olympus.optimization.pipeline import OptimizationPipeline
from olympus.services.optimization import OptimizationService
from olympus.services.projects import ProjectService
from olympus.utils import new_id, utc_now

TRANSCRIPT = [
    {"start": 0.0, "end": 7.0, "speaker": "spk_0",
     "text": "Why do most people fail at productivity? I struggled with this for years."},
    {"start": 7.0, "end": 16.0, "speaker": "spk_0",
     "text": "Honestly, um, I tried like every app and basically nothing really worked."},
    {"start": 16.0, "end": 30.0, "speaker": "spk_0",
     "text": "The real problem was treating every task as equally urgent and important."},
    {"start": 30.0, "end": 45.0, "speaker": "spk_0",
     "text": "For example, I would answer emails while writing reports at the same time."},
    {"start": 45.0, "end": 62.0, "speaker": "spk_0",
     "text": "But then I discovered time blocking, dedicating calendar slots to tasks."},
    {"start": 62.0, "end": 78.0, "speaker": "spk_0",
     "text": "As I mentioned earlier, the focus issue was killing me, and this fixed it."},
]

# A tiny, real byte payload standing in for a rendered MP4 file in storage. The
# engine never decodes it; it only needs to exist for file-presence/download.
_FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomFAKE-RENDER-FIXTURE"


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


@pytest.fixture
def optimization_repo(storage: LocalStorage) -> StorageOptimizationRepository:
    return StorageOptimizationRepository(storage)


def _project() -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Optimization Test",
        source_filename="clip.mp4",
        storage_key="uploads/u1/source.mp4",
        size_bytes=1024,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=78.0,
        width=1080,
        height=1920,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _analysis(*, with_transcript: bool = True) -> Analysis:
    now = utc_now()
    stages = [
        StageResult(
            stage="video_inspection",
            status=StageStatus.COMPLETED,
            version="1",
            data={"duration_seconds": 78.0, "width": 1080, "height": 1920, "fps": 30},
        )
    ]
    if with_transcript:
        stages.append(
            StageResult(
                stage="speech_transcription",
                status=StageStatus.COMPLETED,
                version="1",
                data={"language": "en", "confidence": 0.9, "segments": TRANSCRIPT},
            )
        )
    return Analysis(
        project_id="placeholder",
        pipeline_version="1",
        status=AnalysisStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=stages,
    )


def _make_plan(clip_id: str, start: float, end: float, *, rank: int = 1) -> dict[str, Any]:
    return {
        "id": clip_id,
        "rank": rank,
        "source_video": {"filename": "clip.mp4", "storage_key": "uploads/u1/source.mp4"},
        "start": start,
        "end": end,
        "duration": end - start,
        "start_frame": int(start * 30),
        "end_frame": int(end * 30),
        "fps": 30,
        "scores": {"hook": 0.7, "editing_complexity": 0.3},
        "quality_score": 0.72,
        "confidence": 0.6,
        "explanation": "test clip",
        "evidence": [],
        "alternatives": [],
        "blueprint": {
            "opening_hook": {"text": "Why do people fail?", "timestamp": start, "evidence": "q"},
            "pacing": {"value": "fast", "reason": "dense"},
            "aspect_ratio": {"value": "9:16", "reason": "vertical"},
            "subtitle_style": {"style": "karaoke", "reason": "fast"},
            "title_suggestion": {"text": "Why people fail at productivity", "basis": "hook"},
            "zoom_suggestions": [{"timestamp": start + 5, "reason": "emphasize"}],
            "emphasis_moments": [{"timestamp": start + 5, "reason": "dense"}],
            "replay_moments": [{"timestamp": end - 3, "reason": "payoff"}],
            "retention_risks": [{"timestamp": start + 8, "reason": "slow passage"}],
            "speaker_switches": {"switches": [], "note": "single speaker"},
            "scene_cuts": {"cuts": [], "note": "no scene model"},
        },
    }


def _planning_with(plans: list[dict[str, Any]]) -> ClipPlanningAnalysis:
    now = utc_now()
    return ClipPlanningAnalysis(
        project_id="placeholder",
        pipeline_version="1",
        status=PlanningStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            PlanningStageResult(
                stage="ranking",
                status=PlanningStageStatus.COMPLETED,
                data={"plan_count": len(plans), "plans": plans},
            )
        ],
    )


async def _editing_from(storage: LocalStorage, analysis: Analysis, planning: ClipPlanningAnalysis):
    return await EditingPipeline(
        build_default_editing_analyzers(), StorageEditingRepository(storage)
    ).run(_project(), storage, analysis=analysis, planning=planning)


def _render_manifest(project_id: str, clip_ids: list[str]) -> RenderManifest:
    now = utc_now()
    return RenderManifest(
        project_id=project_id,
        status=RenderStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        renderer="ffmpeg",
        renders=[
            RenderedVideo(
                clip_id=cid,
                storage_key=f"render/{project_id}/{cid}.mp4",
                plan_id=cid,
                rank=1,
                width=1080,
                height=1920,
                duration=40.0,
                fps=30.0,
                video_codec="h264",
                audio_codec="aac",
                has_audio=True,
                bitrate_kbps=12000,
                size_bytes=len(_FAKE_MP4),
            )
            for cid in clip_ids
        ],
    )


async def _write_render(storage: LocalStorage, manifest: RenderManifest) -> None:
    """Persist a real render manifest + MP4 fixtures the way the Rendering Engine would."""

    await storage.put(
        f"render/{manifest.project_id}/index.json",
        json.dumps(manifest.to_dict()).encode("utf-8"),
        content_type="application/json",
    )
    for r in manifest.renders:
        await storage.put(r.storage_key, _FAKE_MP4, content_type="video/mp4")


def _pipeline(repo: StorageOptimizationRepository, **kw: object) -> OptimizationPipeline:
    return OptimizationPipeline(build_default_optimization_analyzers(), repo, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Structure & honesty
# --------------------------------------------------------------------------- #
async def test_pipeline_runs_all_stages_and_persists(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    project = _project()
    manifest = _render_manifest(project.id, ["clip_a"])
    await _write_render(storage, manifest)

    result = await _pipeline(optimization_repo).run(
        project, storage, renders=manifest, analysis=analysis, planning=planning, editing=editing
    )
    assert [s.stage for s in result.stages] == list(OPTIMIZATION_STAGE_ORDER)
    assert all(s.is_terminal for s in result.stages)
    assert result.status is OptimizationStatus.COMPLETED
    reloaded = await optimization_repo.load(project.id)
    assert reloaded is not None
    assert [s.stage for s in reloaded.stages] == list(OPTIMIZATION_STAGE_ORDER)


async def test_load_render_unavailable_without_manifest(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    result = await _pipeline(optimization_repo).run(
        _project(), storage, renders=None, analysis=analysis, planning=planning, editing=editing
    )
    load = result.stage("load_render")
    assert load.status is OptimizationStageStatus.UNAVAILABLE
    assert "Rendering Engine" in (load.reason or "")
    # Audio/visual enhancement is honestly unavailable too (no render, no model).
    assert result.stage("voice_enhancement").status is OptimizationStageStatus.UNAVAILABLE
    assert result.stage("visual_enhancement").status is OptimizationStageStatus.UNAVAILABLE
    # But upstream-derived stages still run for real.
    assert result.stage("caption_optimization").status is OptimizationStageStatus.COMPLETED
    assert result.stage("music_recommendation").status is OptimizationStageStatus.COMPLETED


async def test_load_render_completed_with_manifest(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    project = _project()
    manifest = _render_manifest(project.id, ["clip_a"])
    await _write_render(storage, manifest)
    result = await _pipeline(optimization_repo).run(
        project, storage, renders=manifest, analysis=analysis, planning=planning, editing=editing
    )
    load = result.stage("load_render")
    assert load.status is OptimizationStageStatus.COMPLETED
    assert load.data["render_count"] == 1
    assert load.data["renders"][0]["file_present"] is True
    assert load.data["renders"][0]["aspect_ratio"] == "9:16"


async def test_audio_and_visual_enhancement_unavailable_with_reasons(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    project = _project()
    manifest = _render_manifest(project.id, ["clip_a"])
    await _write_render(storage, manifest)
    result = await _pipeline(optimization_repo).run(
        project, storage, renders=manifest, analysis=analysis, planning=planning, editing=editing
    )
    # Even WITH a render, enhancement is unavailable because no model is installed.
    for stage in ("voice_enhancement", "noise_reduction", "sharpening", "color_refinement"):
        s = result.stage(stage)
        assert s.status is OptimizationStageStatus.UNAVAILABLE
        assert (s.reason and "model" in s.reason.lower()) or "toolchain" in (s.reason or "").lower()


async def test_music_recommendation_is_real_and_licensed(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    result = await _pipeline(optimization_repo).run(
        _project(), storage, analysis=analysis, planning=planning, editing=editing
    )
    music = result.stage("music_recommendation")
    assert music.status is OptimizationStageStatus.COMPLETED
    clip = music.data["clips"][0]
    assert clip["recommendations"], "expected at least one royalty-free recommendation"
    top = clip["recommendations"][0]
    assert top["track"]["license"]  # license always attached
    assert top["track"]["source"]
    assert top["score"] is not None
    # Provider availability is reported honestly (future providers unavailable).
    statuses = {p["provider"]: p["available"] for p in music.data["provider_statuses"]}
    assert statuses["local_royalty_free"] is True
    assert statuses["epidemic_sound"] is False


async def test_caption_optimization_measures_reading_speed(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    result = await _pipeline(optimization_repo).run(
        _project(), storage, analysis=analysis, planning=planning, editing=editing
    )
    caps = result.stage("caption_optimization")
    assert caps.status is OptimizationStageStatus.COMPLETED
    clip = caps.data["clips"][0]
    assert clip["caption_count"] >= 1
    cap = clip["captions"][0]
    assert "reading_speed_cps" in cap and cap["rating"] in (
        "comfortable", "brisk", "too_fast", "unknown"
    )
    assert 1 <= len(cap["lines"]) <= 2  # balanced line breaks


async def test_quality_evaluation_grades_real_signals_and_marks_unknown(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    result = await _pipeline(optimization_repo).run(
        _project(), storage, analysis=analysis, planning=planning, editing=editing
    )
    quality = result.stage("quality_evaluation")
    assert quality.status is OptimizationStageStatus.COMPLETED
    dims = {d["dimension"]: d for d in quality.data["clips"][0]["dimensions"]}
    # Audio/visual quality cannot be graded -> honest UNKNOWN (score is None).
    assert dims["audio_quality"]["score"] is None
    assert dims["visual_quality"]["score"] is None
    # Caption quality is graded from a real measurement.
    assert dims["caption_quality"]["score"] is not None
    # Story quality is grounded in the planner's quality score.
    assert dims["story_quality"]["score"] is not None
    summary = quality.data["clips"][0]["summary"]
    assert "audio_quality" in summary["unknown_dimensions"]


async def test_variants_and_platform_specs(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    result = await _pipeline(optimization_repo).run(
        _project(), storage, analysis=analysis, planning=planning, editing=editing
    )
    variants = result.stage("variant_generation").data["clips"][0]["variants"]
    assert {v["id"] for v in variants} == {"A", "B", "C", "D"}
    for v in variants:
        assert v["confidence"] is not None and v["expected_strengths"]

    platform = result.stage("platform_optimization").data
    assert set(platform["platform_order"]) >= {
        "youtube_shorts", "tiktok", "instagram_reels", "facebook_reels", "snapchat_spotlight"
    }
    assert platform["clips"][0]["targets"][0]["duration_fits"] is True


async def test_publish_package_writes_real_assets(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    project = _project()
    manifest = _render_manifest(project.id, ["clip_a"])
    await _write_render(storage, manifest)
    result = await _pipeline(optimization_repo).run(
        project, storage, renders=manifest, analysis=analysis, planning=planning, editing=editing
    )
    upload_stage = result.stage("upload_metadata_v2").data["clips"][0]
    assert upload_stage["source"] == "optimization_backfill"
    assert upload_stage["upload_metadata_v2"]["youtube_shorts"]["title"]
    pkg = result.stage("publish_package_creation").data
    assert pkg["package_count"] == 1
    package = pkg["packages"][0]
    by_kind = {a["kind"]: a for a in package["assets"]}
    # Caption + metadata + quality assets are real and present in storage.
    for kind in (
        "captions_srt",
        "captions_vtt",
        "metadata",
        "upload_metadata_v2",
        "quality_report",
    ):
        assert by_kind[kind]["status"] == "available"
        assert await storage.exists(by_kind[kind]["storage_key"])
    # The MP4 references the real render; the thumbnail is honestly unavailable.
    assert by_kind["optimized_mp4"]["status"] == "available"
    assert by_kind["thumbnail"]["status"] == "unavailable"
    # The SRT we wrote is a valid, non-empty subtitle document.
    srt = (await storage.get(by_kind["captions_srt"]["storage_key"])).decode("utf-8")
    assert "-->" in srt


async def test_publish_package_mp4_unavailable_without_render(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    result = await _pipeline(optimization_repo).run(
        _project(), storage, renders=None, analysis=analysis, planning=planning, editing=editing
    )
    package = result.stage("publish_package_creation").data["packages"][0]
    by_kind = {a["kind"]: a for a in package["assets"]}
    assert by_kind["optimized_mp4"]["status"] == "unavailable"
    assert by_kind["metadata"]["status"] == "available"  # text assets still real


async def test_final_validation_lists_unavailable_stages(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    result = await _pipeline(optimization_repo).run(
        _project(), storage, renders=None, analysis=analysis, planning=planning, editing=editing
    )
    report = result.stage("final_validation").data
    unavailable = {u["stage"] for u in report["unavailable_stages"]}
    assert "load_render" in unavailable
    assert "voice_enhancement" in unavailable


# --------------------------------------------------------------------------- #
# Orchestration: resume, cancel, rerun, repo
# --------------------------------------------------------------------------- #
async def test_resume_skips_completed_stages(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    project = _project()
    pipeline = _pipeline(optimization_repo)
    first = await pipeline.run(
        project, storage, analysis=analysis, planning=planning, editing=editing
    )
    ts = first.stage("variant_generation").completed_at
    second = await pipeline.run(
        project, storage, analysis=analysis, planning=planning, editing=editing
    )
    assert second.stage("variant_generation").completed_at == ts  # reused, not re-run


async def test_cancellation_marks_remaining_cancelled(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    result = await _pipeline(optimization_repo).run(
        _project(), storage, analysis=_analysis(), cancel_event=cancel
    )
    assert result.status is OptimizationStatus.CANCELLED
    assert all(s.status is OptimizationStageStatus.CANCELLED for s in result.stages)


async def test_rerun_only_targets_one_stage(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    project = _project()
    pipeline = _pipeline(optimization_repo)
    await pipeline.run(project, storage, analysis=analysis, planning=planning, editing=editing)
    rerun = await pipeline.run(
        project, storage, analysis=analysis, planning=planning, editing=editing,
        only={"quality_evaluation"},
    )
    assert rerun.stage("quality_evaluation").status is OptimizationStageStatus.COMPLETED


async def test_repository_roundtrip_and_delete(
    storage: LocalStorage, optimization_repo: StorageOptimizationRepository
) -> None:
    analysis = _analysis()
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    editing = await _editing_from(storage, analysis, planning)
    project = _project()
    await _pipeline(optimization_repo).run(
        project, storage, analysis=analysis, planning=planning, editing=editing
    )
    loaded = await optimization_repo.load(project.id)
    assert loaded is not None
    assert loaded.stage("publish_package_creation").data["package_count"] == 1
    await optimization_repo.delete(project.id)
    assert await optimization_repo.load(project.id) is None


# --------------------------------------------------------------------------- #
# Service lifecycle
# --------------------------------------------------------------------------- #
async def _seed_and_service(
    storage: LocalStorage, *, with_render: bool = True
) -> tuple[OptimizationService, Project]:
    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)

    analysis = _analysis()
    analysis.project_id = project.id
    analysis_repo = StorageAnalysisRepository(storage)
    await analysis_repo.save_index(analysis)
    for stage in analysis.stages:
        await analysis_repo.save_stage(project.id, stage)

    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    planning.project_id = project.id
    planning_repo = StoragePlanningRepository(storage)
    await planning_repo.save_index(planning)
    for stage in planning.stages:
        await planning_repo.save_stage(project.id, stage)

    editing = await _editing_from(storage, analysis, planning)
    editing_repo = StorageEditingRepository(storage)
    editing.project_id = project.id
    await editing_repo.save_index(editing)
    for stage in editing.stages:
        await editing_repo.save_stage(project.id, stage)

    if with_render:
        await _write_render(storage, _render_manifest(project.id, ["clip_a"]))

    service = OptimizationService(
        optimization_repo=StorageOptimizationRepository(storage),
        render_repo=StorageRenderManifestRepository(storage),
        editing_repo=editing_repo,
        planning_repo=planning_repo,
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    return service, project


async def _await_done(service: OptimizationService, project_id: str) -> None:
    for _ in range(600):
        if not service.is_running(project_id):
            break
        await asyncio.sleep(0.01)


async def test_service_start_and_reads(storage: LocalStorage) -> None:
    service, project = await _seed_and_service(storage)
    await service.start(project)
    await _await_done(service, project.id)

    optimization = await service.get_optimization(project.id)
    assert optimization is not None and optimization.status is OptimizationStatus.COMPLETED

    quality = await service.quality_report(project.id)
    assert quality is not None and quality["clips"]
    variants = await service.variants(project.id)
    assert variants is not None and variants["clips"]
    music = await service.music_recommendations(project.id)
    assert music is not None and music["clips"]

    packages = await service.list_packages(project.id)
    assert packages and len(packages) == 1
    package = await service.get_package(project.id, "clip_a")
    assert package is not None and package["clip_id"] == "clip_a"

    asset = await service.resolve_asset(project.id, "clip_a", "metadata")
    assert asset is not None and asset["status"] == "available"
    thumb = await service.resolve_asset(project.id, "clip_a", "thumbnail")
    assert thumb is not None and thumb["status"] == "unavailable"


async def test_service_rerun_and_unknown_stage(storage: LocalStorage) -> None:
    from olympus.platform.errors import ValidationError

    service, project = await _seed_and_service(storage)
    rerun = await service.rerun_stage(project, "quality_evaluation")
    assert rerun.stage("quality_evaluation").status is OptimizationStageStatus.COMPLETED
    with pytest.raises(ValidationError):
        await service.rerun_stage(project, "nonsense")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_optimization_api_flow(app: object, tmp_path: Path) -> None:
    store = LocalStorage(root=str(tmp_path))
    project = _project()

    async def _seed() -> None:
        await StorageProjectRepository(store).save(project)
        analysis = _analysis()
        analysis.project_id = project.id
        analysis_repo = StorageAnalysisRepository(store)
        await analysis_repo.save_index(analysis)
        for stage in analysis.stages:
            await analysis_repo.save_stage(project.id, stage)
        planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
        planning.project_id = project.id
        planning_repo = StoragePlanningRepository(store)
        await planning_repo.save_index(planning)
        for stage in planning.stages:
            await planning_repo.save_stage(project.id, stage)
        editing = await _editing_from(store, analysis, planning)
        editing_repo = StorageEditingRepository(store)
        editing.project_id = project.id
        await editing_repo.save_index(editing)
        for stage in editing.stages:
            await editing_repo.save_stage(project.id, stage)
        await _write_render(store, _render_manifest(project.id, ["clip_a"]))

    asyncio.run(_seed())

    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[storage_provider] = lambda: store
    app.dependency_overrides[optimization_service_provider] = lambda: OptimizationService(
        optimization_repo=StorageOptimizationRepository(store),
        render_repo=StorageRenderManifestRepository(store),
        editing_repo=StorageEditingRepository(store),
        planning_repo=StoragePlanningRepository(store),
        virality_repo=StorageViralityRepository(store),
        story_repo=StorageStoryRepository(store),
        analysis_repo=StorageAnalysisRepository(store),
        project_repo=StorageProjectRepository(store),
        storage=store,
    )

    with TestClient(app) as client:
        run = client.post(f"/api/v1/projects/{project.id}/optimization/run")
        assert run.status_code == 202

        final = None
        for _ in range(100):
            resp = client.get(f"/api/v1/projects/{project.id}/optimization")
            if resp.status_code == 200:
                final = resp.json()
                if final["status"] in ("completed", "failed", "cancelled"):
                    break
        assert final is not None
        assert final["status"] == "completed"
        assert final["total_stages"] == len(OPTIMIZATION_STAGE_ORDER)

        quality = client.get(f"/api/v1/projects/{project.id}/optimization/quality")
        assert quality.status_code == 200 and quality.json()["report"]["clips"]
        variants = client.get(f"/api/v1/projects/{project.id}/optimization/variants")
        assert variants.status_code == 200
        music = client.get(f"/api/v1/projects/{project.id}/optimization/music")
        assert music.status_code == 200

        packages = client.get(f"/api/v1/projects/{project.id}/optimization/packages").json()
        assert packages["package_count"] == 1
        clip_id = packages["packages"][0]["clip_id"]

        meta = client.get(
            f"/api/v1/projects/{project.id}/optimization/packages/{clip_id}/metadata"
        )
        assert meta.status_code == 200
        assert meta.json()["clip_id"] == clip_id  # real metadata JSON served

        srt = client.get(
            f"/api/v1/projects/{project.id}/optimization/packages/{clip_id}/assets/captions_srt"
        )
        assert srt.status_code == 200 and "-->" in srt.text

        # The thumbnail honestly cannot exist here -> 404 with the reason.
        thumb = client.get(
            f"/api/v1/projects/{project.id}/optimization/packages/{clip_id}/thumbnail"
        )
        assert thumb.status_code == 404

        rerun = client.post(
            f"/api/v1/projects/{project.id}/optimization/stages/variant_generation/rerun"
        )
        assert rerun.status_code == 200
        cancel = client.post(f"/api/v1/projects/{project.id}/optimization/cancel")
        assert cancel.status_code == 202
