"""Tests for the Editing Engine: pipeline, stages, timelines, validation.

These verify the *honest* contract of edit-timeline generation:
- With real Cognitive + Story + Virality + Clip Planner output, the engine
  assembles real, validated, non-destructive edit timelines (clip-relative
  events, each with a reason, confidence, and evidence).
- Without approved clips it returns no timelines with an explanation; stages
  report ``UNAVAILABLE`` with a reason and undeterminable decisions are
  ``UNKNOWN`` - never a fabricated edit.
- Work persists after every stage, runs resume, single stages re-run, genuine
  failures surface, and cancellation is cooperative.
- The Editing Engine begins automatically once the Clip Planner completes.
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import editing_service_provider, project_service_provider
from olympus.data.repositories import (
    StorageAnalysisRepository,
    StorageEditingRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageStoryRepository,
    StorageViralityRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.editing import (
    EditingAnalyzer,
    EditingOutcome,
    EditingProgressReporter,
    EditingStageContext,
)
from olympus.domain.entities.analysis import Analysis, AnalysisStatus, StageResult, StageStatus
from olympus.domain.entities.editing import (
    EDITING_STAGE_ORDER,
    EditingStageStatus,
    EditingStatus,
)
from olympus.domain.entities.planning import (
    ClipPlanningAnalysis,
    PlanningStageResult,
    PlanningStageStatus,
    PlanningStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.editing import build_default_editing_analyzers
from olympus.editing.pipeline import EditingPipeline
from olympus.planning import ClipPlanningPipeline, build_default_planning_analyzers
from olympus.services.editing import EditingService
from olympus.services.planning import ClipPlannerService
from olympus.services.projects import ProjectService
from olympus.story import StoryPipeline, build_default_story_analyzers
from olympus.trends import (
    build_editing_trend_guidance,
    build_evergreen_snapshot,
    match_trend_patterns,
)
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
def editing_repo(storage: LocalStorage) -> StorageEditingRepository:
    return StorageEditingRepository(storage)


def _project() -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Editing Test",
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


def _analysis(
    *,
    with_transcript: bool,
    width: int = 1080,
    height: int = 1920,
    face_data: dict[str, Any] | None = None,
) -> Analysis:
    now = utc_now()
    stages = [
        StageResult(
            stage="video_inspection",
            status=StageStatus.COMPLETED,
            version="1",
            data={"duration_seconds": 108.0, "width": width, "height": height, "fps": 30},
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
    if face_data is not None:
        stages.append(
            StageResult(
                stage="face_detection",
                status=StageStatus.COMPLETED,
                version="1",
                data=face_data,
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
    return await StoryPipeline(
        build_default_story_analyzers(), StorageStoryRepository(storage)
    ).run(_project(), storage, analysis=analysis)


async def _virality_from(storage: LocalStorage, analysis: Analysis, story):
    return await ViralityPipeline(
        build_default_virality_analyzers(), StorageViralityRepository(storage)
    ).run(_project(), storage, analysis=analysis, story=story)


async def _planning_from(storage: LocalStorage, analysis: Analysis, story, virality):
    return await ClipPlanningPipeline(
        build_default_planning_analyzers(), StoragePlanningRepository(storage)
    ).run(_project(), storage, analysis=analysis, story=story, virality=virality)


async def _upstream(storage: LocalStorage, *, with_transcript: bool):
    analysis = _analysis(with_transcript=with_transcript)
    story = await _story_from(storage, analysis)
    virality = await _virality_from(storage, analysis, story)
    planning = await _planning_from(storage, analysis, story, virality)
    return analysis, story, virality, planning


def _pipeline(repo: StorageEditingRepository, **kw: object) -> EditingPipeline:
    return EditingPipeline(build_default_editing_analyzers(), repo, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Hand-built planning (deterministic multi-clip / edge tests)
# --------------------------------------------------------------------------- #
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
        "quality_score": 0.7,
        "confidence": 0.6,
        "explanation": "test clip",
        "evidence": [],
        "alternatives": [],
        "blueprint": {
            "opening_hook": {"text": "Why do people fail?", "timestamp": start, "evidence": "q"},
            "pacing": {"value": "fast", "reason": "dense"},
            "aspect_ratio": {"value": "9:16", "reason": "vertical"},
            "subtitle_style": {"style": "karaoke", "reason": "fast"},
            "title_suggestion": {"text": "Why people fail", "basis": "hook"},
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


# --------------------------------------------------------------------------- #
# Structure & honesty
# --------------------------------------------------------------------------- #
async def test_pipeline_runs_all_stages_and_persists(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis, story, virality, planning = await _upstream(storage, with_transcript=True)
    project = _project()
    result = await _pipeline(editing_repo).run(
        project, storage, analysis=analysis, story=story, virality=virality, planning=planning
    )
    assert [s.stage for s in result.stages] == list(EDITING_STAGE_ORDER)
    assert all(s.is_terminal for s in result.stages)
    assert result.status is EditingStatus.COMPLETED
    reloaded = await editing_repo.load(project.id)
    assert reloaded is not None
    assert [s.stage for s in reloaded.stages] == list(EDITING_STAGE_ORDER)


async def test_no_clips_is_honest(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis, story, virality, planning = await _upstream(storage, with_transcript=False)
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, story=story, virality=virality, planning=planning
    )
    # No approved clips -> timeline initialization is honestly unavailable.
    assert result.stage("timeline_initialization").status is EditingStageStatus.UNAVAILABLE
    # Validation still completes with zero timelines (a valid, honest result).
    validation = result.stage("timeline_validation")
    assert validation.status is EditingStageStatus.COMPLETED
    assert validation.data["timeline_count"] == 0
    assert validation.data["report"]["valid"] is True


async def test_real_timelines_assembled_and_valid(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis, story, virality, planning = await _upstream(storage, with_transcript=True)
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, story=story, virality=virality, planning=planning
    )
    validation = result.stage("timeline_validation")
    assert validation.status is EditingStageStatus.COMPLETED
    timelines = validation.data["timelines"]
    assert len(timelines) >= 1
    assert validation.data["report"]["valid"] is True

    tl = timelines[0]
    kinds = {t["kind"] for t in tl["tracks"]}
    assert kinds == {"video", "audio", "caption", "markers"}
    # The base video clip spans the full clip duration (continuity).
    video = next(t for t in tl["tracks"] if t["kind"] == "video")
    base = next(e for e in video["events"] if e["type"] == "source_clip")
    assert base["start"] == 0.0
    assert abs(base["end"] - tl["duration"]) < 0.05
    editing_v2 = tl["metadata"]["editing_v2"]
    assert editing_v2["version"] == "2"
    assert editing_v2["motion_intelligence_v2"]["decision"]["motion_style"]
    assert editing_v2["motion_plan"]["events"] == editing_v2["motion_intelligence_v2"][
        "effect_plan"
    ]["effects"]
    assert editing_v2["voice_enhancement_plan"]["applied_at_render"] is True
    assert editing_v2["video_enhancement_plan"]["applied_at_render"] is True
    assert editing_v2["caption_style"]["renderer"] == "ass"
    # Every event is timestamped with a reason and evidence key.
    for track in tl["tracks"]:
        for ev in track["events"]:
            assert ev["start"] <= ev["end"]
            assert 0.0 <= ev["start"] <= tl["duration"] + 0.05
            assert "reason" in ev and "confidence" in ev and "evidence" in ev


# --------------------------------------------------------------------------- #
# Per-stage behaviour (deterministic, hand-built planning)
# --------------------------------------------------------------------------- #
async def test_speech_cleanup_identifies_fillers_only(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )
    cleanup = result.stage("speech_cleanup")
    assert cleanup.status is EditingStageStatus.COMPLETED
    items = cleanup.data["clips"][0]["items"]
    types = {i["type"] for i in items}
    assert "filler_word" in types  # 'um' in the transcript is identified
    # Breathing is honestly UNKNOWN (no audio model), never fabricated.
    assert cleanup.data["clips"][0]["breathing"]["status"] == "unknown"


async def test_captions_are_timed_and_never_overlap(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with([_make_plan("clip_a", 0.0, 50.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )
    timeline = result.stage("timeline_validation").data["timelines"][0]
    captions = next(t for t in timeline["tracks"] if t["kind"] == "caption")["events"]
    assert captions, "expected real caption events from the transcript"
    ordered = sorted(captions, key=lambda c: c["start"])
    for a, b in itertools.pairwise(ordered):
        assert a["end"] <= b["start"] + 1e-6  # no overlaps
    assert result.stage("timeline_validation").data["report"]["valid"] is True


async def test_pan_is_unknown_without_subject_tracking(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])  # no speaker switches
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )
    pan = result.stage("pan_planner").data["clips"][0]
    assert pan["status"] == "unknown"
    assert pan["pans"] == []
    assert "tracking" in pan["reason"].lower()


async def test_crop_is_9_16_from_real_dimensions(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    # Vertical source -> no horizontal crop needed.
    analysis = _analysis(with_transcript=True, width=1080, height=1920)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )
    crop = result.stage("crop_planner").data["clips"][0]["crop"]
    assert crop["target_aspect"] == "9:16"
    assert crop["x_offset"] == 0  # already vertical

    # Horizontal source -> a real center crop region is computed.
    analysis_h = _analysis(with_transcript=True, width=1920, height=1080)
    repo2 = StorageEditingRepository(storage)
    result2 = await EditingPipeline(build_default_editing_analyzers(), repo2).run(
        _project(), storage, analysis=analysis_h, planning=planning
    )
    crop2 = result2.stage("crop_planner").data["clips"][0]["crop"]
    assert crop2["x_offset"] > 0
    assert crop2["width"] < 1920


async def test_single_face_tracking_plan_created_from_detections(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(
        with_transcript=True,
        width=1920,
        height=1080,
        face_data=_face_frames(),
    )
    planning = _planning_with([_make_plan("clip_a", 0.0, 8.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )

    timeline = result.stage("timeline_validation").data["timelines"][0]
    plan = timeline["metadata"]["face_tracking_plan"]
    assert plan["mode"] == "single_face_tracking"
    assert plan["applied_to_render"] is False
    assert len(plan["crop_keyframes"]) >= 2
    assert timeline["metadata"]["crop"]["subject_aware"] is True
    motion = timeline["metadata"]["motion_intelligence_v2"]
    assert motion["decision"]["should_apply_motion"] is True
    assert motion["effect_plan"]["effects"]
    assert timeline["metadata"]["editing_v2"]["motion_plan"]["source"] == (
        "motion_intelligence_v2"
    )


async def test_two_face_tracking_uses_two_speaker_stack_without_association(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(
        with_transcript=True,
        width=1920,
        height=1080,
        face_data=_face_frames(two_faces=True),
    )
    planning = _planning_with([_make_plan("clip_a", 0.0, 8.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )

    plan = result.stage("timeline_validation").data["timelines"][0]["metadata"][
        "face_tracking_plan"
    ]
    assert plan["mode"] == "two_speaker_stack"
    assert len(plan["tracked_faces"]) == 2
    assert len(plan["layout_regions"]) == 2
    assert plan["input_analysis"]["active_speaker_evidence_available"] is False
    motion = result.stage("timeline_validation").data["timelines"][0]["metadata"][
        "motion_intelligence_v2"
    ]
    assert motion["decision"]["should_apply_motion"] is False
    assert motion["decision"]["disabled_reason"] == "layout_complexity"


async def test_low_confidence_faces_fallback_to_center_crop(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(
        with_transcript=True,
        width=1920,
        height=1080,
        face_data=_face_frames(confidence=0.2),
    )
    planning = _planning_with([_make_plan("clip_a", 0.0, 8.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )

    plan = result.stage("timeline_validation").data["timelines"][0]["metadata"][
        "face_tracking_plan"
    ]
    assert plan["mode"] == "center_fallback"
    assert plan["fallback_reason"] == "sparse_or_low_confidence_faces"


async def test_music_beats_unknown_and_hook_decision_present(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )
    music = result.stage("music_planner").data["clips"][0]
    assert music["beats"]["status"] == "unknown"  # no audio analysis
    types = {m["type"] for m in music["markers"]}
    assert {"music_intro", "music_ending"} <= types
    hook = result.stage("hook_enhancement").data["clips"][0]["decision"]
    assert hook["type"] in (
        "fast_start",
        "no_changes",
        "preview",
        "cold_open",
        "punch_in_caption_pop",
        "unknown",
    )
    timeline = result.stage("timeline_validation").data["timelines"][0]
    hook_editing = timeline["metadata"]["editing_v2"]["hook_editing"]
    assert hook_editing["hook_motion_event"]["type"] == "hook_punch_zoom"
    assert hook_editing["hook_sfx_event"]["safe_default"] is True


async def test_editing_consumes_upstream_story_virality_planning_guidance(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    plan = _make_plan("clip_a", 0.0, 40.0)
    trend_snapshot = build_evergreen_snapshot(
        {"primary": "education_tutorial", "confidence": 0.9}
    )
    trend_match = match_trend_patterns(
        "Why do people fail? The biggest mistake is missing the payoff because it matters.",
        trend_snapshot,
        {"primary": "education_tutorial", "confidence": 0.9},
    )
    editing_trend = build_editing_trend_guidance(
        trend_snapshot,
        {"primary": "education_tutorial", "confidence": 0.9},
        trend_match,
    )
    plan["story_id"] = "story_test_1"
    plan["candidate_id"] = "story_test_1"
    plan["planning_story_integration"] = {"story_guidance_used": True}
    plan["blueprint"].update(
        {
            "hook_v2": {
                "category": "curiosity_gap",
                "hook_line": "Why do people fail?",
                "score": 0.82,
            },
            "caption_decision_v2": {"style": "bold_hook"},
            "music_decision_v2": {"enabled": True, "category": "neutral bed"},
            "sound_effect_plan_v2": {"enabled": True, "effects": []},
            "v2_metadata": {"editing_intensity": "balanced", "content_category": "education"},
            "story_v2_guidance": {
                "story_guidance_used": True,
                "story_guidance_source": "story_analysis_v2",
                "story_id": "story_test_1",
                "story_shape": "problem_solution",
                "payoff": "Constraints create freedom.",
                "completeness_score": 0.86,
                "context_risk": 0.1,
                "planning_guidance": {"context_caption": "A productivity mistake"},
                "editing_guidance": {
                    "caption_emphasis_words": ["productivity"],
                    "music_mood": "subtle tension",
                    "ending_hold_recommendation": 0.25,
                },
            },
            "planning_story_integration": {"story_guidance_used": True},
            "editing_guidance_v2": {"source": "story_analysis_v2+planning_v2"},
            "internet_trend_research_v2": trend_snapshot,
            "trend_match_v2": trend_match,
            "editing_trend_guidance": editing_trend,
            "planning_trend_integration": {
                "trend_guidance_used": True,
                "trend_snapshot_id": trend_snapshot["snapshot_id"],
            },
        }
    )
    result = await _pipeline(editing_repo).run(
        _project(),
        storage,
        analysis=_analysis(with_transcript=True),
        planning=_planning_with([plan]),
    )

    timeline = result.stage("timeline_validation").data["timelines"][0]
    editing = timeline["metadata"]["editing_v2"]
    assert editing["editing_guidance_consumed"]["story_used"] is True
    assert "productivity" in editing["caption_style"]["highlight_words"]
    assert editing["music_plan"]["mood"] == "subtle tension"
    assert editing["ending_hold"]["duration_s"] == 0.25
    assert editing["editing_guidance_consumed"]["trend_used"] is True
    assert editing["editing_trend_guidance"]["trend_snapshot_id"] == trend_snapshot["snapshot_id"]
    assert editing["pacing_profile"]["profile"] == "structured_clarity"
    assert editing["sfx_plan"]["density"] == "low"
    assert timeline["metadata"]["unified_clip_intelligence"]["story"]["story_shape"] == (
        "problem_solution"
    )
    assert timeline["metadata"]["unified_clip_intelligence"]["trend_research"][
        "snapshot_id"
    ] == trend_snapshot["snapshot_id"]


def _face_frames(*, confidence: float = 0.88, two_faces: bool = False) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    for time, x in ((0.0, 760), (2.0, 860), (4.0, 940), (6.0, 980)):
        faces = [
            {
                "face_id": "speaker_a",
                "bbox": {"x": x, "y": 210, "width": 260, "height": 320},
                "confidence": confidence,
            }
        ]
        if two_faces:
            faces.append(
                {
                    "face_id": "speaker_b",
                    "bbox": {"x": 1220, "y": 230, "width": 250, "height": 310},
                    "confidence": confidence,
                }
            )
        frames.append({"timestamp": time, "faces": faces})
    return {"frames": frames}


async def test_multiple_clips_each_get_a_timeline(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with(
        [_make_plan("clip_a", 0.0, 30.0, rank=1), _make_plan("clip_b", 60.0, 95.0, rank=2)]
    )
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )
    validation = result.stage("timeline_validation").data
    assert validation["timeline_count"] == 2
    ids = {t["clip_id"] for t in validation["timelines"]}
    assert ids == {"clip_a", "clip_b"}
    assert validation["report"]["valid"] is True


async def test_large_timeline_validates(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    # A dense 70s transcript with many short segments -> a large, valid timeline.
    segments = [
        {
            "start": float(i * 2),
            "end": float(i * 2 + 2),
            "speaker": "spk_0",
            "text": f"This is sentence number {i} about productivity and focus, here we go.",
        }
        for i in range(35)
    ]
    now = utc_now()
    analysis = Analysis(
        project_id="placeholder",
        pipeline_version="1",
        status=AnalysisStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            StageResult(
                stage="video_inspection",
                status=StageStatus.COMPLETED,
                version="1",
                data={"duration_seconds": 70.0, "width": 1080, "height": 1920, "fps": 30},
            ),
            StageResult(
                stage="speech_transcription",
                status=StageStatus.COMPLETED,
                version="1",
                data={"segments": segments},
            ),
        ],
    )
    planning = _planning_with([_make_plan("clip_big", 0.0, 70.0)])
    result = await _pipeline(editing_repo).run(
        _project(), storage, analysis=analysis, planning=planning
    )
    timeline = result.stage("timeline_validation").data["timelines"][0]
    captions = next(t for t in timeline["tracks"] if t["kind"] == "caption")["events"]
    assert len(captions) >= 35  # many captions
    assert result.stage("timeline_validation").data["report"]["valid"] is True


# --------------------------------------------------------------------------- #
# Orchestration: resume, retry, cancel, rerun
# --------------------------------------------------------------------------- #
async def test_resume_skips_completed_stages(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    project = _project()
    pipeline = _pipeline(editing_repo)
    first = await pipeline.run(project, storage, analysis=analysis, planning=planning)
    ts = first.stage("timeline_validation").completed_at
    second = await pipeline.run(project, storage, analysis=analysis, planning=planning)
    assert second.stage("timeline_validation").completed_at == ts  # reused, not re-run


async def test_failed_stage_is_retried_and_surfaces(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    attempts = {"n": 0}

    class _Flaky(EditingAnalyzer):
        name = "timeline_initialization"
        version = "1"

        async def analyze(
            self, ctx: EditingStageContext, report: EditingProgressReporter
        ) -> EditingOutcome:
            attempts["n"] += 1
            raise RuntimeError("boom")

    analyzers = build_default_editing_analyzers()
    analyzers[0] = _Flaky()
    pipeline = EditingPipeline(analyzers, editing_repo, retry_backoff_seconds=0.0)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    result = await pipeline.run(
        _project(), storage, analysis=_analysis(with_transcript=True), planning=planning
    )
    stage = result.stage("timeline_initialization")
    assert stage.status is EditingStageStatus.FAILED
    assert stage.attempts == 3
    assert attempts["n"] == 3
    assert result.status is EditingStatus.FAILED


async def test_cancellation_marks_remaining_cancelled(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    result = await _pipeline(editing_repo).run(
        _project(),
        storage,
        analysis=_analysis(with_transcript=True),
        planning=_planning_with([_make_plan("clip_a", 0.0, 40.0)]),
        cancel_event=cancel,
    )
    assert result.status is EditingStatus.CANCELLED
    assert all(s.status is EditingStageStatus.CANCELLED for s in result.stages)


async def test_rerun_only_targets_one_stage(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    project = _project()
    pipeline = _pipeline(editing_repo)
    await pipeline.run(project, storage, analysis=analysis, planning=planning)
    rerun = await pipeline.run(
        project, storage, analysis=analysis, planning=planning, only={"timeline_validation"}
    )
    assert rerun.stage("timeline_validation").status is EditingStageStatus.COMPLETED


async def test_repository_roundtrip_and_delete(
    storage: LocalStorage, editing_repo: StorageEditingRepository
) -> None:
    analysis = _analysis(with_transcript=True)
    planning = _planning_with([_make_plan("clip_a", 0.0, 40.0)])
    project = _project()
    await _pipeline(editing_repo).run(project, storage, analysis=analysis, planning=planning)
    loaded = await editing_repo.load(project.id)
    assert loaded is not None
    assert loaded.stage("timeline_validation").data["timelines"]
    await editing_repo.delete(project.id)
    assert await editing_repo.load(project.id) is None


# --------------------------------------------------------------------------- #
# Service lifecycle (loads all four upstream analyses)
# --------------------------------------------------------------------------- #
async def _seed_and_service(storage: LocalStorage) -> tuple[EditingService, Project]:
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

    planning = await _planning_from(storage, analysis, story, virality)
    planning_repo = StoragePlanningRepository(storage)
    planning.project_id = project.id
    await planning_repo.save_index(planning)
    for stage in planning.stages:
        await planning_repo.save_stage(project.id, stage)

    service = EditingService(
        editing_repo=StorageEditingRepository(storage),
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    return service, project


async def test_service_start_list_get_events_validation(storage: LocalStorage) -> None:
    service, project = await _seed_and_service(storage)
    await service.start(project)
    for _ in range(400):
        if not service.is_running(project.id):
            break
        await asyncio.sleep(0.01)
    editing = await service.get_editing(project.id)
    assert editing is not None
    assert editing.status is EditingStatus.COMPLETED

    timelines = await service.list_timelines(project.id)
    assert timelines and len(timelines) >= 1
    clip_id = timelines[0]["clip_id"]

    timeline = await service.get_timeline(project.id, clip_id)
    assert timeline is not None and timeline["clip_id"] == clip_id

    events = await service.timeline_events(project.id, clip_id)
    assert events and all("track" in e for e in events)

    report = await service.validation_report(project.id)
    assert report is not None and "valid" in report
    assert await service.get_timeline(project.id, "clip_missing") is None


async def test_service_rerun_and_unknown_stage(storage: LocalStorage) -> None:
    from olympus.platform.errors import ValidationError

    service, project = await _seed_and_service(storage)
    rerun = await service.rerun_stage(project, "timeline_validation")
    assert rerun.stage("timeline_validation").status is EditingStageStatus.COMPLETED
    with pytest.raises(ValidationError):
        await service.rerun_stage(project, "nonsense")


async def test_planning_completion_triggers_editing(storage: LocalStorage) -> None:
    """The Editing Engine begins automatically when the Clip Planner finishes."""

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

    planning_repo = StoragePlanningRepository(storage)
    editing_repo = StorageEditingRepository(storage)
    editing_service = EditingService(
        editing_repo=editing_repo,
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )

    async def _on_complete(proj: Project, _planning: object) -> None:
        await editing_service.start(proj)

    planner = ClipPlannerService(
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        on_complete=_on_complete,
    )
    await planner.start(project)

    for _ in range(600):
        editing = await editing_repo.load(project.id)
        if editing is not None and editing.status is EditingStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)
    editing = await editing_repo.load(project.id)
    assert editing is not None
    assert editing.status is EditingStatus.COMPLETED


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_editing_api_flow(app: object, tmp_path: Path) -> None:
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
        planning = await _planning_from(store, analysis, story, virality)
        planning_repo = StoragePlanningRepository(store)
        planning.project_id = project.id
        await planning_repo.save_index(planning)
        for stage in planning.stages:
            await planning_repo.save_stage(project.id, stage)

    asyncio.run(_seed())

    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[editing_service_provider] = lambda: EditingService(
        editing_repo=StorageEditingRepository(store),
        planning_repo=StoragePlanningRepository(store),
        virality_repo=StorageViralityRepository(store),
        story_repo=StorageStoryRepository(store),
        analysis_repo=StorageAnalysisRepository(store),
        project_repo=StorageProjectRepository(store),
        storage=store,
    )

    with TestClient(app) as client:
        run = client.post(f"/api/v1/projects/{project.id}/editing/run")
        assert run.status_code == 202

        final = None
        for _ in range(100):
            resp = client.get(f"/api/v1/projects/{project.id}/editing")
            if resp.status_code == 200:
                final = resp.json()
                if final["status"] in ("completed", "failed", "cancelled"):
                    break
        assert final is not None
        assert final["status"] == "completed"
        assert final["total_stages"] == len(EDITING_STAGE_ORDER)

        timelines = client.get(f"/api/v1/projects/{project.id}/editing/timelines").json()
        assert timelines["timeline_count"] >= 1
        clip_id = timelines["timelines"][0]["clip_id"]

        one = client.get(f"/api/v1/projects/{project.id}/editing/timelines/{clip_id}")
        assert one.status_code == 200
        assert one.json()["timeline"]["clip_id"] == clip_id

        events = client.get(f"/api/v1/projects/{project.id}/editing/timelines/{clip_id}/events")
        assert events.status_code == 200
        assert events.json()["event_count"] >= 1

        validation = client.get(f"/api/v1/projects/{project.id}/editing/validation")
        assert validation.status_code == 200
        assert "valid" in validation.json()["report"]

        rerun = client.post(f"/api/v1/projects/{project.id}/editing/stages/zoom_planner/rerun")
        assert rerun.status_code == 200
        cancel = client.post(f"/api/v1/projects/{project.id}/editing/cancel")
        assert cancel.status_code == 202
