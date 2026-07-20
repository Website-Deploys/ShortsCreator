"""BOBA Whole Video Understanding V1 contracts, engine, integration, and validator tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaCandidateV1,
    BobaContextPayoffLinkV1,
    BobaCreativeDirector,
    BobaEmotionalBeatV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaScout,
    BobaSectionScoreV1,
    BobaShortabilityHintV1,
    BobaSignalUsageV1,
    BobaStoryArcV1,
    BobaTopicSegmentV1,
    BobaWholeVideoUnderstandingEngine,
    BobaWholeVideoUnderstandingV1,
    build_whole_video_memory_summary,
)
from olympus.boba.whole_video import whole_video_memory_record
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]


def _segments() -> list[dict[str, Any]]:
    return [
        {
            "start": 0.0,
            "end": 5.0,
            "text": "Why does focus fail even when the goal matters?",
            "speaker": "host",
        },
        {
            "start": 5.0,
            "end": 12.0,
            "text": "The reason is that vague tasks create friction and confusion.",
            "speaker": "host",
        },
        {
            "start": 12.0,
            "end": 18.0,
            "text": "Um, you know, basically this thing is kind of hard, yeah.",
            "speaker": "host",
        },
        {
            "start": 18.0,
            "end": 25.0,
            "text": "Now let's move to a simple three-step focus system.",
            "speaker": "host",
        },
        {
            "start": 25.0,
            "end": 33.0,
            "text": "First define one visible action, then remove every competing task.",
            "speaker": "host",
        },
        {
            "start": 33.0,
            "end": 41.0,
            "text": "Wow, the unexpected result is calmer work and faster progress!",
            "speaker": "host",
        },
        {
            "start": 41.0,
            "end": 49.0,
            "text": "Finally, that's why a specific next action restores focus.",
            "speaker": "host",
        },
    ]


def _story() -> dict[str, Any]:
    return {
        "schema": "story_analysis_v2",
        "primary_themes": ["focus", "specific action", "friction"],
        "topic_sections": [
            {
                "section_id": "topic_problem",
                "start": 0.0,
                "end": 18.0,
                "title": "Why Focus Fails",
                "summary": "A question introduces vague tasks as the source of friction.",
                "story_potential": 0.72,
                "evidence": ["Why does focus fail even when the goal matters?"],
            },
            {
                "section_id": "topic_system",
                "start": 18.0,
                "end": 49.0,
                "title": "Specific Action System",
                "summary": "A three-step system leads to a clear practical payoff.",
                "story_potential": 0.88,
                "evidence": ["A specific next action restores focus."],
            },
        ],
        "micro_stories": [
            {
                "story_id": "story_focus",
                "start": 0.0,
                "end": 49.0,
                "summary": "A focus problem is explained and resolved with one specific action.",
                "completeness_score": 0.88,
                "setup": {
                    "setup_start": 0.0,
                    "setup_end": 5.0,
                    "setup_text": "Why does focus fail even when the goal matters?",
                    "confidence": 0.8,
                },
                "context": {"score": 0.2, "reason": "The question supplies enough context."},
                "tension": {
                    "unresolved_question": "What removes the friction?",
                    "confidence": 0.76,
                },
                "turning_point": {
                    "time": 18.0,
                    "end": 25.0,
                    "text": "The speaker introduces a concrete system.",
                    "confidence": 0.72,
                },
                "payoff": {
                    "payoff_present": True,
                    "payoff_start": 41.0,
                    "payoff_end": 49.0,
                    "payoff_text": "A specific next action restores focus.",
                    "payoff_strength": 0.86,
                },
                "ending": {
                    "final_line": "A specific next action restores focus.",
                    "final_line_strength": 0.84,
                },
                "risks": [],
            }
        ],
        "emotional_timeline": [
            {
                "start": 0.0,
                "end": 5.0,
                "emotion": "curiosity",
                "intensity": 0.72,
                "evidence": "The opening asks a concrete question.",
            },
            {
                "start": 33.0,
                "end": 41.0,
                "emotion": "surprise",
                "intensity": 0.8,
                "evidence": "The result is described as unexpected.",
            },
        ],
        "filler_sections": [
            {"start": 12.0, "end": 18.0, "reason": "High filler ratio."}
        ],
        "repeated_sections": [
            {"start": 12.0, "end": 18.0, "reason": "Repeated low-value wording."}
        ],
    }


def _analysis() -> dict[str, Any]:
    return {
        "contract_version": "analysis_signals_v2",
        "audio_energy": {
            "timeline": {
                "events": [
                    {"start_seconds": 0.0, "end_seconds": 18.0, "score": 0.45},
                    {"start_seconds": 33.0, "end_seconds": 49.0, "score": 0.82},
                ]
            }
        },
    }


def _planning() -> dict[str, Any]:
    return {
        "selected_plans": [
            {
                "clip_id": "clip_focus",
                "start": 18.0,
                "end": 49.0,
                "selected_reason": "Complete system-to-payoff arc.",
                "confidence": 0.82,
            }
        ]
    }


def _understanding(**updates: Any) -> BobaWholeVideoUnderstandingV1:
    payload = {
        "project_id": "proj_whole_video",
        "source_id": "uploads/proj_whole_video/source.mp4",
        "video_duration_seconds": 49.0,
        "transcript_segments": _segments(),
        "analysis_signals_v2": _analysis(),
        "story_artifact": _story(),
        "virality_artifact": {
            "heatmap": [{"start": 33.0, "end": 49.0, "heat": 0.85}]
        },
        "planning_artifact": _planning(),
    }
    payload.update(updates)
    return BobaWholeVideoUnderstandingEngine().build(**payload)


def _project(project_id: str = "proj_whole_video") -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="Whole Video Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=49.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def test_whole_video_contract_serializes() -> None:
    result = _understanding()
    assert BobaWholeVideoUnderstandingV1.model_validate_json(result.model_dump_json()) == result


def test_topic_segment_contract_serializes() -> None:
    item = _understanding().topic_timeline[0]
    assert BobaTopicSegmentV1.model_validate_json(item.model_dump_json()) == item


def test_story_arc_contract_serializes() -> None:
    arc = _understanding().story_arc
    assert BobaStoryArcV1.model_validate_json(arc.model_dump_json()) == arc


def test_emotional_beat_contract_serializes() -> None:
    beat = _understanding().emotional_beats[0]
    assert BobaEmotionalBeatV1.model_validate_json(beat.model_dump_json()) == beat


def test_context_payoff_link_contract_serializes() -> None:
    link = _understanding().context_payoff_map[0]
    assert BobaContextPayoffLinkV1.model_validate_json(link.model_dump_json()) == link


def test_section_score_contract_serializes() -> None:
    score = _understanding().section_scores[0]
    assert BobaSectionScoreV1.model_validate_json(score.model_dump_json()) == score


def test_shortability_hint_contract_serializes() -> None:
    hint = _understanding().shortability_hints[0]
    assert BobaShortabilityHintV1.model_validate_json(hint.model_dump_json()) == hint


def test_signal_usage_contract_serializes() -> None:
    usage = _understanding().signal_usage
    assert BobaSignalUsageV1.model_validate_json(usage.model_dump_json()) == usage


def test_topic_timeline_groups_transcript_sections() -> None:
    result = _understanding(
        story_artifact={},
        analysis_signals_v2={},
        virality_artifact={},
        planning_artifact={},
    )
    assert len(result.topic_timeline) >= 2
    assert result.topic_timeline[0].end_seconds <= result.topic_timeline[-1].end_seconds
    assert result.signal_usage.fallback_used is True


def test_story_arc_detects_setup_and_payoff() -> None:
    arc = _understanding().story_arc
    assert arc.setup
    assert arc.payoff
    assert "restores focus" in arc.payoff[0].summary.casefold()


def test_emotional_beats_use_heuristic_fallback_status() -> None:
    result = _understanding(story_artifact={}, analysis_signals_v2={})
    assert result.emotional_beats
    assert result.signal_usage.fallback_used is True
    assert any("heuristic" in item for item in result.emotional_beats[0].source_signals)


def test_context_payoff_links_setup_to_later_payoff() -> None:
    link = _understanding().context_payoff_map[0]
    assert link.context_start_seconds < link.payoff_start_seconds
    assert link.standalone_clip_possible is True


def test_section_scoring_detects_filler_and_repetition() -> None:
    result = _understanding()
    problem = next(item for item in result.section_scores if item.section_id == "topic_problem")
    assert problem.filler_score >= 0.3
    assert problem.repetition_score > 0.0


def test_shortability_hints_identify_standalone_moments() -> None:
    result = _understanding()
    assert any(
        hint.suggested_clip_type in {"payoff_clip", "candidate_for_short", "possible_hook"}
        for hint in result.shortability_hints
    )


def test_missing_analysis_signals_degrade_gracefully() -> None:
    result = _understanding(analysis_signals_v2={})
    assert result.signal_usage.analysis_signals_used is False
    assert "analysis_signals_v2" in result.signal_usage.unavailable_signals
    assert result.topic_timeline


def test_missing_transcript_fails_clearly() -> None:
    with pytest.raises(ValidationError, match="requires transcript segments"):
        BobaWholeVideoUnderstandingEngine().build(
            project_id="proj_missing_transcript",
            transcript_segments=[],
        )


def test_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_whole_video_understanding(_understanding())
    loaded = store.load_whole_video_understanding(result.project_id)
    payload = json.loads(store.whole_video_understanding_path(result.project_id).read_text())
    assert loaded is not None
    assert loaded.project_id == result.project_id
    assert payload["schema_version"] == "boba_whole_video_understanding_v1"


def test_memory_summary_excludes_full_transcript() -> None:
    secret_line = "PRIVATE FULL TRANSCRIPT SENTENCE THAT MUST NEVER ENTER MEMORY"
    segments = [*_segments(), {"start": 49.0, "end": 55.0, "text": secret_line}]
    result = _understanding(transcript_segments=segments, video_duration_seconds=55.0)
    summary = build_whole_video_memory_summary(result)
    record = whole_video_memory_record(summary)
    encoded = json.dumps(
        {"summary": summary.model_dump(mode="json"), "record": record.model_dump(mode="json")}
    )
    assert secret_line not in encoded
    assert "transcript_segments" not in encoded


def test_creative_director_can_optionally_consume_understanding(tmp_path: Path) -> None:
    understanding = _understanding()
    signals = {
        "selected_plans": [
            {
                "clip_id": "clip_focus",
                "start": 18.0,
                "end": 49.0,
                "hook_line": "Use one specific action.",
            }
        ],
        "transcript_available": True,
        "transcript_segments": _segments(),
        "whole_video_understanding": understanding.model_dump(mode="json"),
        "safety_status": "low",
    }
    brief = BobaCreativeDirector(BobaMemoryStore(tmp_path / "boba")).create_briefs(
        understanding.project_id, signals
    )[0]
    assert brief.whole_video_understanding_used is True
    assert brief.understanding_guidance


def test_scout_can_use_saved_project_understanding(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    understanding = store.save_whole_video_understanding(_understanding())
    scout = BobaScout(store)
    scout.create_candidate(
        BobaCandidateV1(
            candidate_id="candidate_linked_project",
            title="Why one specific action restores focus",
            duration_seconds=49.0,
            metadata={"topic": "focus", "project_id": understanding.project_id},
            rights_status="permission_confirmed",
            permission_confirmed=True,
        )
    )
    score = scout.score_candidate("candidate_linked_project")
    assert any("whole-video" in reason for reason in score.reasons)
    assert any("saved local Olympus artifacts" in warning for warning in score.warnings)


def test_api_route_returns_saved_understanding(
    app: FastAPI, tmp_path: Path
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    project = _project()
    asyncio.run(StorageProjectRepository(storage).save(project))
    store.save_whole_video_understanding(_understanding())
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{project.id}/whole-video-understanding"
        )
    assert response.status_code == 200
    assert response.json()["primary_topic"]


@pytest.mark.parametrize("argument", ["--self-check", "--synthetic-project"])
def test_validator_modes_pass(argument: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_whole_video_understanding.py"),
            argument,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"passed": true' in result.stdout.casefold()


def test_engine_makes_no_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = _understanding()
    assert result.signal_usage.transcript_used is True


def test_validator_reports_stay_under_ignored_work() -> None:
    from tools.validate_boba_whole_video_understanding import REPORT_DIR

    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_whole_video_understanding"
    assert "media" not in REPORT_DIR.parts
