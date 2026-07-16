"""Tests for the Story Engine: heuristics, analyzers, pipeline, repo, service, API.

These verify the *honest* contract of narrative understanding:
- With a real transcript, analyzers produce evidence-backed conclusions that
  carry confidence (real heuristic computation, not fabrication).
- Without a transcript, transcript-dependent stages report ``UNAVAILABLE`` with
  a reason, while aggregating stages (graph, summary) complete and transparently
  list which signals are still pending.
- Work persists after every stage, runs resume, single stages re-run, genuine
  failures surface, and cancellation is cooperative.
- The Story Engine begins automatically once the Cognitive Engine completes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import (
    project_service_provider,
    story_service_provider,
)
from olympus.data.repositories import (
    StorageAnalysisRepository,
    StorageProjectRepository,
    StorageStoryRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.story import (
    StoryAnalyzer,
    StoryOutcome,
    StoryProgressReporter,
    StoryStageContext,
)
from olympus.domain.entities.analysis import (
    Analysis,
    AnalysisStatus,
    StageResult,
    StageStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.story import (
    STORY_STAGE_ORDER,
    StoryStageStatus,
    StoryStatus,
)
from olympus.services.analysis import AnalysisService
from olympus.services.projects import ProjectService
from olympus.services.story import StoryService
from olympus.story import build_default_story_analyzers
from olympus.story.pipeline import StoryPipeline
from olympus.utils import new_id, utc_now

# A small but structurally rich transcript: a question hook, a problem, an
# example, a topic shift, an explicit back-reference, a payoff that answers the
# opening question, and an ending.
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
def story_repo(storage: LocalStorage) -> StorageStoryRepository:
    return StorageStoryRepository(storage)


def _project(duration_seconds: float = 108.0) -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Story Test",
        source_filename="clip.mp4",
        storage_key="uploads/u1/source.mp4",
        size_bytes=1024,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=duration_seconds,
        width=1080,
        height=1920,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _analysis(*, with_transcript: bool) -> Analysis:
    now = utc_now()
    stages: list[StageResult] = []
    if with_transcript:
        word_count = sum(len(s["text"].split()) for s in TRANSCRIPT)
        stages.append(
            StageResult(
                stage="speech_transcription",
                status=StageStatus.COMPLETED,
                version="1",
                data={
                    "language": "en",
                    "confidence": 0.9,
                    "word_count": word_count,
                    "has_word_timestamps": True,
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


def _analysis_from_segments(segments: list[dict[str, object]]) -> Analysis:
    now = utc_now()
    word_count = sum(len(str(s["text"]).split()) for s in segments)
    return Analysis(
        project_id="placeholder",
        pipeline_version="1",
        status=AnalysisStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            StageResult(
                stage="speech_transcription",
                status=StageStatus.COMPLETED,
                version="1",
                data={
                    "language": "en",
                    "confidence": 0.9,
                    "word_count": word_count,
                    "has_word_timestamps": True,
                    "segments": segments,
                },
            )
        ],
    )


def _long_story_segments(duration: float) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    t = 0.0
    lines = [
        "Why do creators miss the best story? The problem is they only check the intro.",
        "For example, one section starts slow but then the real conflict appears.",
        "But then I realized the payoff was hidden after the topic changed.",
        "So it turns out the lesson is to preserve setup, tension, and payoff together.",
    ]
    index = 0
    while t < duration:
        text = f"{lines[index % len(lines)]} Section{index} keyword{index}."
        segments.append(
            {"start": t, "end": min(duration, t + 12.0), "speaker": "spk_0", "text": text}
        )
        t += 12.0
        index += 1
    return segments


def _pipeline(repo: StorageStoryRepository, **kw: object) -> StoryPipeline:
    return StoryPipeline(build_default_story_analyzers(), repo, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Pipeline structure & honesty
# --------------------------------------------------------------------------- #
async def test_pipeline_runs_all_stages_and_persists(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    project = _project()
    story = await _pipeline(story_repo).run(
        project, storage, analysis=_analysis(with_transcript=False)
    )

    assert [s.stage for s in story.stages] == list(STORY_STAGE_ORDER)
    assert all(s.is_terminal for s in story.stages)

    reloaded = await story_repo.load(project.id)
    assert reloaded is not None
    assert [s.stage for s in reloaded.stages] == list(STORY_STAGE_ORDER)


async def test_unavailable_without_transcript(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    project = _project()
    story = await _pipeline(story_repo).run(
        project, storage, analysis=_analysis(with_transcript=False)
    )

    for name in (
        "narrative_segmentation",
        "hook_detection",
        "topic_segmentation",
        "payoff_detection",
        "information_density",
        "context_dependencies",
        "story_analysis_v2",
    ):
        stage = story.stage(name)
        assert stage is not None
        assert stage.status is StoryStageStatus.UNAVAILABLE
        assert stage.reason  # honest explanation
        assert not stage.data  # nothing fabricated

    # Aggregating stages still complete and honestly list pending signals.
    for name in ("story_graph", "story_summary"):
        stage = story.stage(name)
        assert stage is not None
        assert stage.status is StoryStageStatus.COMPLETED
        assert stage.data["pending_signals"]
        assert stage.data["confidence"] == 0.0


async def test_pipeline_without_any_cognitive_analysis(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    # analysis=None must be handled gracefully (no transcript -> honest).
    story = await _pipeline(story_repo).run(_project(), storage, analysis=None)
    assert story.stage("narrative_segmentation").status is StoryStageStatus.UNAVAILABLE
    assert story.status is StoryStatus.COMPLETED  # unavailable != failed


# --------------------------------------------------------------------------- #
# Real, evidence-backed analysis on a transcript
# --------------------------------------------------------------------------- #
async def test_narrative_segmentation_real(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    seg = story.stage("narrative_segmentation")
    assert seg is not None and seg.status is StoryStageStatus.COMPLETED
    sections = seg.data["sections"]
    assert len(sections) >= 2
    assert sections[0]["role"] in ("hook", "introduction")
    assert sections[-1]["role"] in ("ending", "resolution")
    for s in sections:
        assert 0.0 <= s["confidence"] <= 1.0
        assert s["supporting_excerpt"]
        assert s["reason"]


async def test_hook_detection_real(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    hook = story.stage("hook_detection")
    assert hook is not None and hook.status is StoryStageStatus.COMPLETED
    assert hook.data["has_hook"] is True
    assert hook.data["hook_type"] == "question"
    assert hook.data["confidence"] > 0
    assert hook.data["supporting_excerpt"]


async def test_no_hook_is_reported_honestly(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    flat = _analysis(with_transcript=True)
    flat.stage("speech_transcription").data["segments"] = [
        {
            "start": 0.0,
            "end": 6.0,
            "text": "today we will look at the calendar and the tasks on the list.",
        },
        {
            "start": 6.0,
            "end": 12.0,
            "text": "the calendar shows tasks and the list shows tasks for the calendar.",
        },
    ]
    story = await _pipeline(story_repo).run(_project(), storage, analysis=flat)
    hook = story.stage("hook_detection")
    assert hook.status is StoryStageStatus.COMPLETED
    assert hook.data["has_hook"] is False
    assert hook.data["reason"]


async def test_payoff_detection_links_question_to_answer(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    payoff = story.stage("payoff_detection")
    assert payoff is not None and payoff.status is StoryStageStatus.COMPLETED
    rels = payoff.data["relationships"]
    assert len(rels) >= 1
    rel = rels[0]
    assert rel["setup_timestamp"] < rel["payoff_timestamp"]
    assert rel["evidence"]["shared_keywords"]
    assert 0.0 <= rel["confidence"] <= 1.0


async def test_narrative_arc_real(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    arc = story.stage("narrative_arc")
    assert arc is not None and arc.status is StoryStageStatus.COMPLETED
    assert arc.data["has_setup"] is True
    assert isinstance(arc.data["arc_type"], str)
    assert arc.data["role_sequence"]


async def test_emotional_turning_points_estimated_from_transcript(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    emo = story.stage("emotional_turning_points")
    assert emo is not None and emo.status is StoryStageStatus.COMPLETED
    assert emo.data["method"] == "estimated_from_transcript"
    for tp in emo.data["turning_points"]:
        assert tp["confidence"] <= 0.7  # estimates are kept modest


async def test_information_density_real(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    dens = story.stage("information_density")
    assert dens is not None and dens.status is StoryStageStatus.COMPLETED
    windows = dens.data["windows"]
    assert windows
    classifications = {w["classification"] for w in windows}
    assert classifications <= {"dense", "slow", "filler", "repetition", "moderate"}
    for w in windows:
        assert set(w["metrics"]) == {
            "lexical_diversity",
            "entity_density",
            "filler_ratio",
            "repetition_ratio",
        }


async def test_context_dependencies_real(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    ctx = story.stage("context_dependencies")
    assert ctx is not None and ctx.status is StoryStageStatus.COMPLETED
    assert ctx.data["reference_count"] >= 1
    types = {r["type"] for r in ctx.data["references"]}
    assert types & {"explicit_backreference", "term_reintroduction"}


async def test_story_analysis_v2_micro_stories_and_guidance(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    v2 = story.stage("story_analysis_v2")

    assert v2 is not None and v2.status is StoryStageStatus.COMPLETED
    assert v2.data["schema"] == "story_analysis_v2"
    assert v2.data["topic_sections"]
    assert v2.data["micro_stories"]
    assert v2.data["story_quality_summary"]["micro_story_count"] >= 1
    assert any(ms["payoff"]["payoff_present"] for ms in v2.data["micro_stories"])
    assert v2.data["virality_story_guidance"]
    assert v2.data["planning_story_guidance"]
    assert v2.data["editing_story_guidance"]

    recommended = v2.data["recommended_clip_stories"]
    assert recommended
    top = recommended[0]
    assert top["story_shape"] in {
        "problem_solution",
        "question_answer",
        "setup_payoff",
        "tension_release",
        "mistake_lesson",
    }
    assert top["story_completeness_score"]["overall"] >= 0.5
    assert top["boundary_repair"]["repaired_end"] >= top["end"]
    assert top["context_dependency"]["recommended_action"] in {
        "accept",
        "expand_start",
        "add_context_caption",
    }


async def test_story_analysis_v2_downgrades_missing_payoff_fragments(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    weak_segments = [
        {
            "start": 0.0,
            "end": 8.0,
            "speaker": "spk_0",
            "text": "So this and that thing was happening with them over there.",
        },
        {
            "start": 8.0,
            "end": 16.0,
            "speaker": "spk_0",
            "text": "Um yeah basically like we kept talking about the same thing.",
        },
        {
            "start": 16.0,
            "end": 26.0,
            "speaker": "spk_0",
            "text": "And then it was kind of more stuff with no real conclusion",
        },
    ]
    story = await _pipeline(story_repo).run(
        _project(26.0), storage, analysis=_analysis_from_segments(weak_segments)
    )
    v2 = story.stage("story_analysis_v2")

    assert v2.status is StoryStageStatus.COMPLETED
    assert v2.data["micro_stories"]
    assert all(not ms["payoff"]["payoff_present"] for ms in v2.data["micro_stories"])
    assert all(ms["completeness_score"] <= 0.54 for ms in v2.data["micro_stories"])
    assert any(ms["rejection_reason"] == "missing payoff" for ms in v2.data["micro_stories"])
    assert v2.data["weak_sections"]


async def test_story_analysis_v2_long_video_story_map_covers_full_duration(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    duration = 2400.0
    story = await _pipeline(story_repo).run(
        _project(duration),
        storage,
        analysis=_analysis_from_segments(_long_story_segments(duration)),
    )
    v2 = story.stage("story_analysis_v2")
    story_map = v2.data["long_video_story_map"]

    assert v2.status is StoryStageStatus.COMPLETED
    assert story_map["source_duration"] == duration
    assert story_map["section_count"] >= 4
    assert len(story_map["coverage_by_time"]) > 1
    assert story_map["coverage_by_time"][-1]["end"] == duration
    assert story_map["strongest_arcs"]


async def test_story_graph_and_summary_aggregate_real(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True)
    )
    graph = story.stage("story_graph")
    assert graph.status is StoryStageStatus.COMPLETED
    assert graph.data["node_count"] > 0
    assert "narrative_segmentation" in graph.data["available_signals"]

    summary = story.stage("story_summary")
    assert summary.status is StoryStageStatus.COMPLETED
    assert summary.data["main_subject"]
    assert summary.data["story_flow"]
    assert summary.data["confidence"] > 0
    assert "important_moments" in summary.data
    assert summary.data["story_analysis_v2"]["micro_story_count"] >= 1


# --------------------------------------------------------------------------- #
# Orchestration: resume, retry, cancel, rerun
# --------------------------------------------------------------------------- #
async def test_resume_skips_completed_stages(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    project = _project()
    pipeline = _pipeline(story_repo)
    first = await pipeline.run(project, storage, analysis=_analysis(with_transcript=True))
    graph_first = first.stage("story_graph").completed_at

    second = await pipeline.run(project, storage, analysis=_analysis(with_transcript=True))
    assert second.stage("story_graph").completed_at == graph_first  # reused, not re-run


async def test_failed_stage_is_retried_and_surfaces(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    attempts = {"n": 0}

    class _Flaky(StoryAnalyzer):
        name = "narrative_segmentation"
        version = "1"

        async def analyze(
            self, ctx: StoryStageContext, report: StoryProgressReporter
        ) -> StoryOutcome:
            attempts["n"] += 1
            raise RuntimeError("boom")

    analyzers = build_default_story_analyzers()
    analyzers[0] = _Flaky()
    pipeline = StoryPipeline(analyzers, story_repo, retry_backoff_seconds=0.0)
    story = await pipeline.run(_project(), storage, analysis=_analysis(with_transcript=True))

    stage = story.stage("narrative_segmentation")
    assert stage.status is StoryStageStatus.FAILED
    assert stage.attempts == 3  # 1 + 2 retries
    assert attempts["n"] == 3
    assert story.status is StoryStatus.FAILED


async def test_cancellation_marks_remaining_cancelled(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    cancel = asyncio.Event()
    cancel.set()  # cancel before the first stage runs
    story = await _pipeline(story_repo).run(
        _project(), storage, analysis=_analysis(with_transcript=True), cancel_event=cancel
    )
    assert story.status is StoryStatus.CANCELLED
    assert all(s.status is StoryStageStatus.CANCELLED for s in story.stages)


async def test_rerun_only_targets_one_stage(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    project = _project()
    pipeline = _pipeline(story_repo)
    await pipeline.run(project, storage, analysis=_analysis(with_transcript=True))
    rerun = await pipeline.run(
        project, storage, analysis=_analysis(with_transcript=True), only={"hook_detection"}
    )
    assert rerun.stage("hook_detection").status is StoryStageStatus.COMPLETED


async def test_repository_roundtrip_and_delete(
    storage: LocalStorage, story_repo: StorageStoryRepository
) -> None:
    project = _project()
    await _pipeline(story_repo).run(project, storage, analysis=_analysis(with_transcript=True))
    loaded = await story_repo.load(project.id)
    assert loaded is not None
    assert loaded.stage("story_summary").data["main_subject"]
    await story_repo.delete(project.id)
    assert await story_repo.load(project.id) is None


# --------------------------------------------------------------------------- #
# Service lifecycle (loads cognitive analysis as input)
# --------------------------------------------------------------------------- #
async def _service(
    storage: LocalStorage,
) -> tuple[StoryService, StorageAnalysisRepository, Project]:
    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    analysis_repo = StorageAnalysisRepository(storage)
    analysis = _analysis(with_transcript=True)
    analysis.project_id = project.id
    await analysis_repo.save_index(analysis)
    for stage in analysis.stages:
        await analysis_repo.save_stage(project.id, stage)
    service = StoryService(
        story_repo=StorageStoryRepository(storage),
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    return service, analysis_repo, project


async def test_service_start_completes(storage: LocalStorage) -> None:
    service, _, project = await _service(storage)
    await service.start(project)
    for _ in range(200):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)
    story = await service.get_story(project.id)
    assert story is not None
    assert story.status is StoryStatus.COMPLETED
    assert story.stage("narrative_segmentation").status is StoryStageStatus.COMPLETED


async def test_service_get_summary(storage: LocalStorage) -> None:
    service, _, project = await _service(storage)
    await service.start(project)
    for _ in range(200):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)
    summary = await service.get_summary(project.id)
    assert summary is not None
    assert summary["main_subject"]


async def test_service_rerun_and_unknown_stage(storage: LocalStorage) -> None:
    from olympus.platform.errors import ValidationError

    service, _, project = await _service(storage)
    story = await service.rerun_stage(project, "hook_detection")
    assert story.stage("hook_detection").status is StoryStageStatus.COMPLETED
    with pytest.raises(ValidationError):
        await service.rerun_stage(project, "telepathy")


async def test_cognitive_completion_triggers_story(storage: LocalStorage) -> None:
    """The Story Engine begins automatically when the Cognitive Engine finishes."""

    project = _project()
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    analysis_repo = StorageAnalysisRepository(storage)
    story_repo = StorageStoryRepository(storage)

    story_service = StoryService(
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )

    async def _on_complete(proj: Project, _analysis: object) -> None:
        await story_service.start(proj)

    analysis_service = AnalysisService(
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        on_complete=_on_complete,
    )
    await analysis_service.start(project)

    # Wait for cognitive run, then for the chained story run.
    for _ in range(300):
        story = await story_repo.load(project.id)
        if story is not None and story.status is StoryStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)
    story = await story_repo.load(project.id)
    assert story is not None
    assert story.status is StoryStatus.COMPLETED


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_story_api_flow(app: object, tmp_path: Path) -> None:
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

    asyncio.run(_seed())

    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[story_service_provider] = lambda: StoryService(
        story_repo=StorageStoryRepository(store),
        analysis_repo=StorageAnalysisRepository(store),
        project_repo=StorageProjectRepository(store),
        storage=store,
    )

    with TestClient(app) as client:
        run = client.post(f"/api/v1/projects/{project.id}/story/run")
        assert run.status_code == 202

        final = None
        for _ in range(100):
            resp = client.get(f"/api/v1/projects/{project.id}/story")
            if resp.status_code == 200:
                final = resp.json()
                if final["status"] in ("completed", "failed", "cancelled"):
                    break
        assert final is not None
        assert final["status"] == "completed"
        assert final["total_stages"] == len(STORY_STAGE_ORDER)
        assert final["completed_stages"] >= 1

        summary = client.get(f"/api/v1/projects/{project.id}/story/summary")
        assert summary.status_code == 200
        assert summary.json()["summary"]["main_subject"]

        rerun = client.post(f"/api/v1/projects/{project.id}/story/stages/hook_detection/rerun")
        assert rerun.status_code == 200

        cancel = client.post(f"/api/v1/projects/{project.id}/story/cancel")
        assert cancel.status_code == 202
