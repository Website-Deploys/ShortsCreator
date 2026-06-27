"""Tests for the Virality Engine: scoring, analyzers, pipeline, repo, service, API.

These verify the *honest* contract of viral-potential assessment:
- With real Cognitive + Story output, analyzers produce evidence-backed scores
  that always carry confidence and limitations (real computation, not fabrication).
- Without that evidence, stages report ``UNAVAILABLE`` with a reason and emit no
  score/confidence; the summary still completes and lists pending categories.
- Work persists after every stage, runs resume, single stages re-run, genuine
  failures surface, and cancellation is cooperative.
- The Virality Engine begins automatically once the Story Engine completes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import project_service_provider, virality_service_provider
from olympus.data.repositories import (
    StorageAnalysisRepository,
    StorageProjectRepository,
    StorageStoryRepository,
    StorageViralityRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.virality import (
    ViralityAnalyzer,
    ViralityOutcome,
    ViralityProgressReporter,
    ViralityStageContext,
)
from olympus.domain.entities.analysis import Analysis, AnalysisStatus, StageResult, StageStatus
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.story import StoryAnalysis
from olympus.domain.entities.virality import (
    VIRALITY_STAGE_ORDER,
    ViralityStageStatus,
    ViralityStatus,
)
from olympus.services.projects import ProjectService
from olympus.services.story import StoryService
from olympus.services.virality import ViralityService
from olympus.story import StoryPipeline, build_default_story_analyzers
from olympus.utils import new_id, utc_now
from olympus.virality import build_default_virality_analyzers
from olympus.virality.pipeline import ViralityPipeline
from olympus.virality.scoring import CATEGORY_FOR_STAGE

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
def virality_repo(storage: LocalStorage) -> StorageViralityRepository:
    return StorageViralityRepository(storage)


def _project() -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Virality Test",
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
    stages: list[StageResult] = [
        StageResult(
            stage="video_inspection",
            status=StageStatus.COMPLETED,
            version="1",
            data={
                "container": "mp4",
                "duration_seconds": 108.0,
                "width": 1080,
                "height": 1920,
                "aspect_ratio": 0.5625,
                "fps": 30,
            },
        )
    ]
    if with_transcript:
        stages.append(
            StageResult(
                stage="speech_transcription",
                status=StageStatus.COMPLETED,
                version="1",
                data={
                    "language": "en",
                    "confidence": 0.9,
                    "word_count": sum(len(s["text"].split()) for s in TRANSCRIPT),
                    "segments": TRANSCRIPT,
                },
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


async def _story_from(storage: LocalStorage, analysis: Analysis) -> StoryAnalysis:
    """Produce a real StoryAnalysis by running the Story pipeline on the analysis."""

    pipeline = StoryPipeline(build_default_story_analyzers(), StorageStoryRepository(storage))
    return await pipeline.run(_project(), storage, analysis=analysis)


def _pipeline(repo: StorageViralityRepository, **kw: object) -> ViralityPipeline:
    return ViralityPipeline(build_default_virality_analyzers(), repo, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Structure & honesty
# --------------------------------------------------------------------------- #
async def test_pipeline_runs_all_stages_and_persists(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    project = _project()
    result = await _pipeline(virality_repo).run(
        project, storage, analysis=_analysis(with_transcript=False), story=None
    )
    assert [s.stage for s in result.stages] == list(VIRALITY_STAGE_ORDER)
    assert all(s.is_terminal for s in result.stages)
    assert result.status is ViralityStatus.COMPLETED  # unavailable != failed

    reloaded = await virality_repo.load(project.id)
    assert reloaded is not None
    assert [s.stage for s in reloaded.stages] == list(VIRALITY_STAGE_ORDER)


async def test_unavailable_without_transcript_emit_no_score(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    result = await _pipeline(virality_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=False), story=None
    )
    for name in ("hook_strength", "curiosity_gap", "emotional_impact", "novelty", "retention"):
        stage = result.stage(name)
        assert stage is not None
        assert stage.status is ViralityStageStatus.UNAVAILABLE
        assert stage.reason  # a detailed reason
        assert "score" not in stage.data  # never fabricated


async def test_platform_fit_completes_from_real_duration(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    """Platform fit is based on genuine format facts (duration, aspect)."""

    result = await _pipeline(virality_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=False), story=None
    )
    pf = result.stage("platform_fit")
    assert pf is not None and pf.status is ViralityStageStatus.COMPLETED
    assert set(pf.data["platforms"]) == {"youtube_shorts", "tiktok", "instagram_reels"}
    assert 0.0 <= pf.data["score"] <= 1.0
    assert pf.data["vertical"] is True
    assert any(e["type"] == "duration" for e in pf.data["evidence"])


async def test_summary_completes_and_lists_pending(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    result = await _pipeline(virality_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=False), story=None
    )
    summary = result.stage("virality_summary")
    assert summary is not None and summary.status is ViralityStageStatus.COMPLETED
    assert "platform_fit" in summary.data["available_categories"]
    pending = {p["category"] for p in summary.data["pending_categories"]}
    assert "hook" in pending and "emotion" in pending
    # Confidence honestly reflects very low coverage.
    assert summary.data["overall_confidence"] < 0.2
    # No transcript -> no heatmap is fabricated.
    assert summary.data["heatmap"] == []
    assert summary.data["heatmap_note"]


# --------------------------------------------------------------------------- #
# Real, evidence-backed scoring (with transcript + story)
# --------------------------------------------------------------------------- #
async def test_hook_strength_real(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    story = await _story_from(storage, analysis)
    result = await _pipeline(virality_repo).run(_project(), storage, analysis=analysis, story=story)
    hook = result.stage("hook_strength")
    assert hook is not None and hook.status is ViralityStageStatus.COMPLETED
    assert hook.data["score"] > 0
    assert hook.data["hook_type"] == "question"
    assert hook.data["evidence"]
    assert hook.data["limitations"]


async def test_retention_explains_why(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    story = await _story_from(storage, analysis)
    result = await _pipeline(virality_repo).run(_project(), storage, analysis=analysis, story=story)
    ret = result.stage("retention")
    assert ret is not None and ret.status is ViralityStageStatus.COMPLETED
    for point in ret.data["evidence"]:
        assert point["why"]  # every predicted drop-off explains itself


async def test_every_completed_score_has_confidence_evidence_limitations(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    story = await _story_from(storage, analysis)
    result = await _pipeline(virality_repo).run(_project(), storage, analysis=analysis, story=story)
    for stage_name in CATEGORY_FOR_STAGE:  # the 14 scoring stages
        stage = result.stage(stage_name)
        assert stage is not None
        if stage.status is ViralityStageStatus.COMPLETED:
            assert "score" in stage.data
            assert "confidence" in stage.data
            assert "evidence" in stage.data
            assert stage.data.get("limitations")


async def test_summary_aggregates_with_timeline_and_heatmap(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    story = await _story_from(storage, analysis)
    result = await _pipeline(virality_repo).run(_project(), storage, analysis=analysis, story=story)
    summary = result.stage("virality_summary")
    assert summary is not None and summary.status is ViralityStageStatus.COMPLETED
    assert summary.data["overall_score"] is not None
    assert 0.0 <= summary.data["overall_score"] <= 1.0
    assert "hook" in summary.data["category_scores"]
    assert summary.data["timeline"]  # events derived from real story signals
    assert summary.data["heatmap"]  # heat from real density/emotion/payoff
    for cell in summary.data["heatmap"]:
        assert 0.0 <= cell["heat"] <= 1.0
        assert "density" in cell["components"]


async def test_heatmap_intensity_is_derived_not_fabricated(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    story = await _story_from(storage, analysis)
    result = await _pipeline(virality_repo).run(_project(), storage, analysis=analysis, story=story)
    heatmap = result.stage("virality_summary").data["heatmap"]
    # Heat equals the documented weighted combination of its components.
    for cell in heatmap:
        c = cell["components"]
        expected = max(
            0.0,
            min(1.0, 0.5 * c["density"] + 0.2 * c["emotion"] + 0.2 * c["payoff"] + 0.1 * c["hook"]),
        )
        assert abs(cell["heat"] - round(expected, 3)) < 1e-6


# --------------------------------------------------------------------------- #
# Orchestration: resume, retry, cancel, rerun
# --------------------------------------------------------------------------- #
async def test_resume_skips_completed_stages(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    project = _project()
    pipeline = _pipeline(virality_repo)
    analysis = _analysis(with_transcript=False)
    first = await pipeline.run(project, storage, analysis=analysis, story=None)
    pf_first = first.stage("platform_fit").completed_at
    second = await pipeline.run(project, storage, analysis=analysis, story=None)
    assert second.stage("platform_fit").completed_at == pf_first  # reused, not re-run


async def test_failed_stage_is_retried_and_surfaces(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    attempts = {"n": 0}

    class _Flaky(ViralityAnalyzer):
        name = "hook_strength"
        version = "1"

        async def analyze(
            self, ctx: ViralityStageContext, report: ViralityProgressReporter
        ) -> ViralityOutcome:
            attempts["n"] += 1
            raise RuntimeError("boom")

    analyzers = build_default_virality_analyzers()
    analyzers[0] = _Flaky()
    pipeline = ViralityPipeline(analyzers, virality_repo, retry_backoff_seconds=0.0)
    result = await pipeline.run(
        _project(), storage, analysis=_analysis(with_transcript=False), story=None
    )
    stage = result.stage("hook_strength")
    assert stage.status is ViralityStageStatus.FAILED
    assert stage.attempts == 3
    assert attempts["n"] == 3
    assert result.status is ViralityStatus.FAILED


async def test_cancellation_marks_remaining_cancelled(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    result = await _pipeline(virality_repo).run(
        _project(),
        storage,
        analysis=_analysis(with_transcript=False),
        story=None,
        cancel_event=cancel,
    )
    assert result.status is ViralityStatus.CANCELLED
    assert all(s.status is ViralityStageStatus.CANCELLED for s in result.stages)


async def test_rerun_only_targets_one_stage(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    project = _project()
    pipeline = _pipeline(virality_repo)
    analysis = _analysis(with_transcript=False)
    await pipeline.run(project, storage, analysis=analysis, story=None)
    rerun = await pipeline.run(
        project, storage, analysis=analysis, story=None, only={"platform_fit"}
    )
    assert rerun.stage("platform_fit").status is ViralityStageStatus.COMPLETED


async def test_repository_roundtrip_and_delete(
    storage: LocalStorage, virality_repo: StorageViralityRepository
) -> None:
    project = _project()
    analysis = _analysis(with_transcript=True)
    story = await _story_from(storage, analysis)
    await _pipeline(virality_repo).run(project, storage, analysis=analysis, story=story)
    loaded = await virality_repo.load(project.id)
    assert loaded is not None
    assert loaded.stage("virality_summary").data["overall_score"] is not None
    await virality_repo.delete(project.id)
    assert await virality_repo.load(project.id) is None


# --------------------------------------------------------------------------- #
# Service lifecycle (loads cognitive + story analyses as input)
# --------------------------------------------------------------------------- #
async def _service(
    storage: LocalStorage, *, with_transcript: bool
) -> tuple[ViralityService, Project]:
    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)

    analysis_repo = StorageAnalysisRepository(storage)
    analysis = _analysis(with_transcript=with_transcript)
    analysis.project_id = project.id
    await analysis_repo.save_index(analysis)
    for stage in analysis.stages:
        await analysis_repo.save_stage(project.id, stage)

    # Produce and persist a real story analysis as the virality input.
    story = await _story_from(storage, analysis)
    story_repo = StorageStoryRepository(storage)
    story.project_id = project.id
    await story_repo.save_index(story)
    for stage in story.stages:
        await story_repo.save_stage(project.id, stage)

    service = ViralityService(
        virality_repo=StorageViralityRepository(storage),
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    return service, project


async def test_service_start_completes(storage: LocalStorage) -> None:
    service, project = await _service(storage, with_transcript=True)
    await service.start(project)
    for _ in range(300):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)
    virality = await service.get_virality(project.id)
    assert virality is not None
    assert virality.status is ViralityStatus.COMPLETED
    assert virality.stage("hook_strength").status is ViralityStageStatus.COMPLETED


async def test_service_get_summary(storage: LocalStorage) -> None:
    service, project = await _service(storage, with_transcript=True)
    await service.start(project)
    for _ in range(300):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)
    summary = await service.get_summary(project.id)
    assert summary is not None
    assert "overall_score" in summary
    assert summary["overall_score"] is not None


async def test_service_rerun_and_unknown_stage(storage: LocalStorage) -> None:
    from olympus.platform.errors import ValidationError

    service, project = await _service(storage, with_transcript=True)
    virality = await service.rerun_stage(project, "platform_fit")
    assert virality.stage("platform_fit").status is ViralityStageStatus.COMPLETED
    with pytest.raises(ValidationError):
        await service.rerun_stage(project, "nonsense")


async def test_story_completion_triggers_virality(storage: LocalStorage) -> None:
    """The Virality Engine begins automatically when the Story Engine finishes."""

    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    analysis_repo = StorageAnalysisRepository(storage)
    analysis = _analysis(with_transcript=True)
    analysis.project_id = project.id
    await analysis_repo.save_index(analysis)
    for stage in analysis.stages:
        await analysis_repo.save_stage(project.id, stage)

    story_repo = StorageStoryRepository(storage)
    virality_repo = StorageViralityRepository(storage)
    virality_service = ViralityService(
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )

    async def _on_complete(proj: Project, _story: object) -> None:
        await virality_service.start(proj)

    story_service = StoryService(
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        on_complete=_on_complete,
    )
    await story_service.start(project)

    for _ in range(400):
        virality = await virality_repo.load(project.id)
        if virality is not None and virality.status is ViralityStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)
    virality = await virality_repo.load(project.id)
    assert virality is not None
    assert virality.status is ViralityStatus.COMPLETED


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_virality_api_flow(app: object, tmp_path: Path) -> None:
    store = LocalStorage(root=str(tmp_path))
    project = _project()

    async def _seed() -> None:
        await StorageProjectRepository(store).save(project)
        analysis_repo = StorageAnalysisRepository(store)
        analysis = _analysis(with_transcript=True)
        analysis.project_id = project.id
        await analysis_repo.save_index(analysis)
        for stage in analysis.stages:
            await analysis_repo.save_stage(project.id, stage)
        story = await _story_from(store, analysis)
        story_repo = StorageStoryRepository(store)
        story.project_id = project.id
        await story_repo.save_index(story)
        for stage in story.stages:
            await story_repo.save_stage(project.id, stage)

    asyncio.run(_seed())

    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[virality_service_provider] = lambda: ViralityService(
        virality_repo=StorageViralityRepository(store),
        story_repo=StorageStoryRepository(store),
        analysis_repo=StorageAnalysisRepository(store),
        project_repo=StorageProjectRepository(store),
        storage=store,
    )

    with TestClient(app) as client:
        run = client.post(f"/api/v1/projects/{project.id}/virality/run")
        assert run.status_code == 202

        final = None
        for _ in range(100):
            resp = client.get(f"/api/v1/projects/{project.id}/virality")
            if resp.status_code == 200:
                final = resp.json()
                if final["status"] in ("completed", "failed", "cancelled"):
                    break
        assert final is not None
        assert final["status"] == "completed"
        assert final["total_stages"] == len(VIRALITY_STAGE_ORDER)

        summary = client.get(f"/api/v1/projects/{project.id}/virality/summary")
        assert summary.status_code == 200
        assert "overall_score" in summary.json()["summary"]

        rerun = client.post(f"/api/v1/projects/{project.id}/virality/stages/platform_fit/rerun")
        assert rerun.status_code == 200

        cancel = client.post(f"/api/v1/projects/{project.id}/virality/cancel")
        assert cancel.status_code == 202
