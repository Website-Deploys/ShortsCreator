"""Tests for the Clip Planner: pipeline, stages, ranking, duplicates, blueprints.

These verify the *honest* contract of clip planning:
- With real Cognitive + Story + Virality output, the planner produces ranked,
  fully-specified editing blueprints (valid timelines, evidence on every plan).
- Without that evidence, it returns zero clips with an explanation (or stages
  report ``UNAVAILABLE`` with a reason) - never a fabricated clip.
- Work persists after every stage, runs resume, single stages re-run, genuine
  failures surface, and cancellation is cooperative.
- The Clip Planner begins automatically once the Virality Engine completes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import planning_service_provider, project_service_provider
from olympus.data.repositories import (
    StorageAnalysisRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageStoryRepository,
    StorageViralityRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.planning import (
    PlanningAnalyzer,
    PlanningOutcome,
    PlanningProgressReporter,
    PlanningStageContext,
)
from olympus.domain.entities.analysis import Analysis, AnalysisStatus, StageResult, StageStatus
from olympus.domain.entities.planning import (
    PLANNING_STAGE_ORDER,
    PlanningStageResult,
    PlanningStageStatus,
    PlanningStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.planning import build_default_planning_analyzers
from olympus.planning.analyzers import DuplicateDetectionAnalyzer, RankingAnalyzer
from olympus.planning.pipeline import ClipPlanningPipeline
from olympus.services.planning import ClipPlannerService
from olympus.services.projects import ProjectService
from olympus.services.virality import ViralityService
from olympus.story import StoryPipeline, build_default_story_analyzers
from olympus.utils import new_id, utc_now
from olympus.virality import ViralityPipeline, build_default_virality_analyzers

TRANSCRIPT = [
    {
        "start": 0.0,
        "end": 7.0,
        "speaker": "spk_0",
        "text": "Why do most people fail at productivity? I struggled with this for years.",
    },
    {
        "start": 7.0,
        "end": 16.0,
        "speaker": "spk_0",
        "text": "Honestly, um, I tried like every app and basically nothing really worked.",
    },
    {
        "start": 16.0,
        "end": 30.0,
        "speaker": "spk_0",
        "text": "The real problem was treating every task as equally urgent and important.",
    },
    {
        "start": 30.0,
        "end": 45.0,
        "speaker": "spk_0",
        "text": "For example, I would answer emails while writing reports at the same time.",
    },
    {
        "start": 45.0,
        "end": 62.0,
        "speaker": "spk_0",
        "text": "But then I discovered time blocking, dedicating calendar slots to tasks.",
    },
    {
        "start": 62.0,
        "end": 78.0,
        "speaker": "spk_0",
        "text": "As I mentioned earlier, the focus issue was killing me, and this fixed it.",
    },
    {
        "start": 78.0,
        "end": 95.0,
        "speaker": "spk_0",
        "text": "So it turns out the reason people fail at productivity is a lack of structure.",
    },
    {
        "start": 95.0,
        "end": 108.0,
        "speaker": "spk_0",
        "text": "What I learned is that constraints create freedom. Thanks for watching!",
    },
]


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


@pytest.fixture
def planning_repo(storage: LocalStorage) -> StoragePlanningRepository:
    return StoragePlanningRepository(storage)


def _project() -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Planner Test",
        source_filename="clip.mp4",
        storage_key="uploads/u1/source.mp4",
        size_bytes=1024,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=108.0,
        width=1080,
        height=1920,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _analysis(*, with_transcript: bool) -> Analysis:
    now = utc_now()
    stages = [
        StageResult(
            stage="video_inspection",
            status=StageStatus.COMPLETED,
            version="1",
            data={"duration_seconds": 108.0, "width": 1080, "height": 1920, "fps": 30},
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


async def _story_from(storage: LocalStorage, analysis: Analysis):
    pipeline = StoryPipeline(build_default_story_analyzers(), StorageStoryRepository(storage))
    return await pipeline.run(_project(), storage, analysis=analysis)


async def _virality_from(storage: LocalStorage, analysis: Analysis, story):
    pipeline = ViralityPipeline(
        build_default_virality_analyzers(), StorageViralityRepository(storage)
    )
    return await pipeline.run(_project(), storage, analysis=analysis, story=story)


async def _upstream(storage: LocalStorage, *, with_transcript: bool):
    analysis = _analysis(with_transcript=with_transcript)
    story = await _story_from(storage, analysis)
    virality = await _virality_from(storage, analysis, story)
    return analysis, story, virality


def _pipeline(repo: StoragePlanningRepository, **kw: object) -> ClipPlanningPipeline:
    return ClipPlanningPipeline(build_default_planning_analyzers(), repo, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Structure & honesty
# --------------------------------------------------------------------------- #
async def test_pipeline_runs_all_stages_and_persists(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    analysis, story, virality = await _upstream(storage, with_transcript=True)
    project = _project()
    result = await _pipeline(planning_repo).run(
        project, storage, analysis=analysis, story=story, virality=virality
    )
    assert [s.stage for s in result.stages] == list(PLANNING_STAGE_ORDER)
    assert all(s.is_terminal for s in result.stages)
    reloaded = await planning_repo.load(project.id)
    assert reloaded is not None
    assert [s.stage for s in reloaded.stages] == list(PLANNING_STAGE_ORDER)


async def test_zero_clips_without_transcript_is_honest(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    analysis, story, virality = await _upstream(storage, with_transcript=False)
    result = await _pipeline(planning_repo).run(
        _project(), storage, analysis=analysis, story=story, virality=virality
    )
    # No transcript -> no localized signals -> candidate generation is unavailable.
    assert result.stage("candidate_generation").status is PlanningStageStatus.UNAVAILABLE
    # The summary still completes and explains the zero-clip outcome honestly.
    summary = result.stage("planning_summary")
    assert summary.status is PlanningStageStatus.COMPLETED
    assert summary.data["plan_count"] == 0
    assert summary.data["zero_reason"]
    assert "transcript" in summary.data["zero_reason"].lower()


async def test_pipeline_with_transcript_produces_plans(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    analysis, story, virality = await _upstream(storage, with_transcript=True)
    result = await _pipeline(planning_repo).run(
        _project(), storage, analysis=analysis, story=story, virality=virality
    )
    ranking = result.stage("ranking")
    assert ranking.status is PlanningStageStatus.COMPLETED
    plans = ranking.data["plans"]
    assert len(plans) >= 1
    assert result.status is PlanningStatus.COMPLETED


# --------------------------------------------------------------------------- #
# Plan / blueprint / timeline validation
# --------------------------------------------------------------------------- #
async def test_plans_have_valid_timelines_and_blueprints(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    analysis, story, virality = await _upstream(storage, with_transcript=True)
    result = await _pipeline(planning_repo).run(
        _project(), storage, analysis=analysis, story=story, virality=virality
    )
    plans = result.stage("ranking").data["plans"]
    required_blueprint_keys = {
        "opening_hook",
        "closing_payoff",
        "title_suggestion",
        "subtitle_style",
        "aspect_ratio",
        "pacing",
        "silence_removal",
        "jump_cuts",
        "scene_cuts",
        "zoom_suggestions",
        "crop_suggestions",
        "speaker_switches",
        "camera_focus",
        "caption_timing",
        "emphasis_moments",
        "replay_moments",
        "retention_risks",
        "continuation_possibility",
        "estimated_complexity",
        "platform_suitability",
    }
    for plan in plans:
        # Timeline validity.
        assert 0.0 <= plan["start"] < plan["end"] <= 108.0
        assert 8.0 <= plan["duration"] <= 75.0
        assert plan["start_frame"] < plan["end_frame"]
        # Identity, scores, evidence.
        assert plan["id"].startswith("clip_")
        assert 0.0 <= plan["quality_score"] <= 1.0
        assert plan["evidence"]
        assert plan["explanation"]
        # Complete blueprint.
        assert required_blueprint_keys <= set(plan["blueprint"])
        # Caption timing is real transcript-derived timing.
        for cap in plan["blueprint"]["caption_timing"]:
            assert cap["start"] <= cap["end"]
        # Platform suitability covers all three platforms.
        assert set(plan["blueprint"]["platform_suitability"]) == {
            "youtube_shorts",
            "tiktok",
            "instagram_reels",
        }


async def test_ranking_orders_by_quality_with_reasons(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    project = _project()
    ctx = PlanningStageContext(
        project=project,
        storage=storage,
        results={
            "blueprint_generation": PlanningStageResult(
                stage="blueprint_generation",
                status=PlanningStageStatus.COMPLETED,
                data={
                    "plans": [
                        {
                            "id": "clip_a",
                            "quality_score": 0.5,
                            "confidence": 0.6,
                            "scores": {"hook": 0.4, "retention": 0.5, "editing_complexity": 0.2},
                        },
                        {
                            "id": "clip_b",
                            "quality_score": 0.8,
                            "confidence": 0.7,
                            "scores": {"hook": 0.9, "retention": 0.7, "editing_complexity": 0.2},
                        },
                    ]
                },
            )
        },
    )
    outcome = await RankingAnalyzer().analyze(ctx, lambda _v: None)
    plans = outcome.data["plans"]
    assert [p["id"] for p in plans] == ["clip_b", "clip_a"]
    assert plans[0]["rank"] == 1 and plans[1]["rank"] == 2
    assert outcome.data["ranking_reasons"]
    assert outcome.data["ranking_reasons"][0]["higher"] == "clip_b"


async def test_duplicate_detection_merges_overlaps(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    project = _project()
    ctx = PlanningStageContext(
        project=project,
        storage=storage,
        results={
            "clip_scoring": PlanningStageResult(
                stage="clip_scoring",
                status=PlanningStageStatus.COMPLETED,
                data={
                    "candidates": [
                        {"start": 0.0, "end": 30.0, "quality_score": 0.8, "scores": {}},
                        {"start": 2.0, "end": 31.0, "quality_score": 0.6, "scores": {}},  # overlaps
                        {"start": 60.0, "end": 80.0, "quality_score": 0.7, "scores": {}},
                    ]
                },
            )
        },
    )
    outcome = await DuplicateDetectionAnalyzer().analyze(ctx, lambda _v: None)
    assert outcome.data["survivor_count"] == 2
    assert outcome.data["duplicate_count"] == 1
    dup = outcome.data["duplicates"][0]
    assert dup["iou"] >= 0.5
    # The kept survivor records the merged clip as a ranked alternative.
    kept = next(c for c in outcome.data["candidates"] if c["id"] == dup["duplicate_of"])
    assert kept["alternatives"]


# --------------------------------------------------------------------------- #
# Orchestration: resume, retry, cancel, rerun
# --------------------------------------------------------------------------- #
async def test_resume_skips_completed_stages(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    analysis, story, virality = await _upstream(storage, with_transcript=True)
    project = _project()
    pipeline = _pipeline(planning_repo)
    first = await pipeline.run(project, storage, analysis=analysis, story=story, virality=virality)
    ts = first.stage("planning_summary").completed_at
    second = await pipeline.run(project, storage, analysis=analysis, story=story, virality=virality)
    assert second.stage("planning_summary").completed_at == ts  # reused, not re-run


async def test_failed_stage_is_retried_and_surfaces(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    attempts = {"n": 0}

    class _Flaky(PlanningAnalyzer):
        name = "candidate_generation"
        version = "1"

        async def analyze(
            self, ctx: PlanningStageContext, report: PlanningProgressReporter
        ) -> PlanningOutcome:
            attempts["n"] += 1
            raise RuntimeError("boom")

    analyzers = build_default_planning_analyzers()
    analyzers[0] = _Flaky()
    pipeline = ClipPlanningPipeline(analyzers, planning_repo, retry_backoff_seconds=0.0)
    result = await pipeline.run(_project(), storage, analysis=None, story=None, virality=None)
    stage = result.stage("candidate_generation")
    assert stage.status is PlanningStageStatus.FAILED
    assert stage.attempts == 3
    assert attempts["n"] == 3
    assert result.status is PlanningStatus.FAILED


async def test_cancellation_marks_remaining_cancelled(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    result = await _pipeline(planning_repo).run(
        _project(), storage, analysis=None, story=None, virality=None, cancel_event=cancel
    )
    assert result.status is PlanningStatus.CANCELLED
    assert all(s.status is PlanningStageStatus.CANCELLED for s in result.stages)


async def test_rerun_only_targets_one_stage(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    analysis, story, virality = await _upstream(storage, with_transcript=True)
    project = _project()
    pipeline = _pipeline(planning_repo)
    await pipeline.run(project, storage, analysis=analysis, story=story, virality=virality)
    rerun = await pipeline.run(
        project,
        storage,
        analysis=analysis,
        story=story,
        virality=virality,
        only={"planning_summary"},
    )
    assert rerun.stage("planning_summary").status is PlanningStageStatus.COMPLETED


async def test_repository_roundtrip_and_delete(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    analysis, story, virality = await _upstream(storage, with_transcript=True)
    project = _project()
    await _pipeline(planning_repo).run(
        project, storage, analysis=analysis, story=story, virality=virality
    )
    loaded = await planning_repo.load(project.id)
    assert loaded is not None
    assert loaded.stage("ranking").data["plans"]
    await planning_repo.delete(project.id)
    assert await planning_repo.load(project.id) is None


# --------------------------------------------------------------------------- #
# Service lifecycle (loads cognitive + story + virality as input)
# --------------------------------------------------------------------------- #
async def _seed_and_service(storage: LocalStorage) -> tuple[ClipPlannerService, Project]:
    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)

    analysis = _analysis(with_transcript=True)
    analysis.project_id = project.id
    analysis_repo = StorageAnalysisRepository(storage)
    await analysis_repo.save_index(analysis)
    for stage in analysis.stages:
        await analysis_repo.save_stage(project.id, stage)

    story = await _story_from(storage, analysis)
    story_repo = StorageStoryRepository(storage)
    story.project_id = project.id
    await story_repo.save_index(story)
    for stage in story.stages:
        await story_repo.save_stage(project.id, stage)

    virality = await _virality_from(storage, analysis, story)
    virality_repo = StorageViralityRepository(storage)
    virality.project_id = project.id
    await virality_repo.save_index(virality)
    for stage in virality.stages:
        await virality_repo.save_stage(project.id, stage)

    service = ClipPlannerService(
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    return service, project


async def test_service_start_list_and_get_plan(storage: LocalStorage) -> None:
    service, project = await _seed_and_service(storage)
    await service.start(project)
    for _ in range(300):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)
    planning = await service.get_planning(project.id)
    assert planning is not None
    assert planning.status is PlanningStatus.COMPLETED

    plans = await service.list_plans(project.id)
    assert plans and len(plans) >= 1
    plan = await service.get_plan(project.id, plans[0]["id"])
    assert plan is not None
    assert plan["id"] == plans[0]["id"]
    assert "blueprint" in plan
    assert await service.get_plan(project.id, "clip_does_not_exist") is None


async def test_service_summary_and_unknown_stage(storage: LocalStorage) -> None:
    from olympus.platform.errors import ValidationError

    service, project = await _seed_and_service(storage)
    rerun = await service.rerun_stage(project, "planning_summary")
    assert rerun.stage("planning_summary").status is PlanningStageStatus.COMPLETED
    summary = await service.get_summary(project.id)
    assert summary is not None
    assert "plan_count" in summary
    with pytest.raises(ValidationError):
        await service.rerun_stage(project, "nonsense")


async def test_virality_completion_triggers_planning(storage: LocalStorage) -> None:
    """The Clip Planner begins automatically when the Virality Engine finishes."""

    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    analysis = _analysis(with_transcript=True)
    analysis.project_id = project.id
    analysis_repo = StorageAnalysisRepository(storage)
    await analysis_repo.save_index(analysis)
    for stage in analysis.stages:
        await analysis_repo.save_stage(project.id, stage)
    story = await _story_from(storage, analysis)
    story_repo = StorageStoryRepository(storage)
    story.project_id = project.id
    await story_repo.save_index(story)
    for stage in story.stages:
        await story_repo.save_stage(project.id, stage)

    virality_repo = StorageViralityRepository(storage)
    planning_repo = StoragePlanningRepository(storage)
    planner = ClipPlannerService(
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )

    async def _on_complete(proj: Project, _v: object) -> None:
        await planner.start(proj)

    virality_service = ViralityService(
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        on_complete=_on_complete,
    )
    await virality_service.start(project)

    for _ in range(500):
        planning = await planning_repo.load(project.id)
        if planning is not None and planning.status is PlanningStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)
    planning = await planning_repo.load(project.id)
    assert planning is not None
    assert planning.status is PlanningStatus.COMPLETED


async def test_list_plans_empty_when_zero_clips(
    storage: LocalStorage, planning_repo: StoragePlanningRepository
) -> None:
    """A terminal pipeline with zero clips returns an empty list (not an error)."""

    analysis, story, virality = await _upstream(storage, with_transcript=False)
    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    await _pipeline(planning_repo).run(
        project, storage, analysis=analysis, story=story, virality=virality
    )
    service = ClipPlannerService(
        planning_repo=planning_repo,
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=project_repo,
        storage=storage,
    )
    plans = await service.list_plans(project.id)
    assert plans == []
    assert await service.list_plans("proj_missing") is None


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_planning_api_flow(app: object, tmp_path: Path) -> None:
    store = LocalStorage(root=str(tmp_path))
    project = _project()

    async def _seed() -> None:
        await StorageProjectRepository(store).save(project)
        analysis = _analysis(with_transcript=True)
        analysis.project_id = project.id
        analysis_repo = StorageAnalysisRepository(store)
        await analysis_repo.save_index(analysis)
        for stage in analysis.stages:
            await analysis_repo.save_stage(project.id, stage)
        story = await _story_from(store, analysis)
        story_repo = StorageStoryRepository(store)
        story.project_id = project.id
        await story_repo.save_index(story)
        for stage in story.stages:
            await story_repo.save_stage(project.id, stage)
        virality = await _virality_from(store, analysis, story)
        virality_repo = StorageViralityRepository(store)
        virality.project_id = project.id
        await virality_repo.save_index(virality)
        for stage in virality.stages:
            await virality_repo.save_stage(project.id, stage)

    asyncio.run(_seed())

    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[planning_service_provider] = lambda: ClipPlannerService(
        planning_repo=StoragePlanningRepository(store),
        virality_repo=StorageViralityRepository(store),
        story_repo=StorageStoryRepository(store),
        analysis_repo=StorageAnalysisRepository(store),
        project_repo=StorageProjectRepository(store),
        storage=store,
    )

    with TestClient(app) as client:
        run = client.post(f"/api/v1/projects/{project.id}/planning/run")
        assert run.status_code == 202

        final = None
        for _ in range(100):
            resp = client.get(f"/api/v1/projects/{project.id}/planning")
            if resp.status_code == 200:
                final = resp.json()
                if final["status"] in ("completed", "failed", "cancelled"):
                    break
        assert final is not None
        assert final["status"] == "completed"
        assert final["total_stages"] == len(PLANNING_STAGE_ORDER)

        plans = client.get(f"/api/v1/projects/{project.id}/planning/plans").json()
        assert plans["plan_count"] >= 1
        first_id = plans["plans"][0]["id"]

        one = client.get(f"/api/v1/projects/{project.id}/planning/plans/{first_id}")
        assert one.status_code == 200
        assert one.json()["plan"]["id"] == first_id

        summary = client.get(f"/api/v1/projects/{project.id}/planning/summary")
        assert summary.status_code == 200
        assert "plan_count" in summary.json()["summary"]

        rerun = client.post(f"/api/v1/projects/{project.id}/planning/stages/ranking/rerun")
        assert rerun.status_code == 200
        cancel = client.post(f"/api/v1/projects/{project.id}/planning/cancel")
        assert cancel.status_code == 202
