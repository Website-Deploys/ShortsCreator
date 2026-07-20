"""BOBA Candidate Clip Discovery V1 contracts, engine, API, and validator tests."""

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
    BobaBoundarySuggestionV1,
    BobaCandidateClipDiscoveryEngine,
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
    BobaCandidateDiscoverySignalUsageV1,
    BobaCandidateDiversitySummaryV1,
    BobaCandidateEvidenceV1,
    BobaCreativeDirector,
    BobaIntegration,
    BobaMemoryStore,
    BobaRejectedWindowV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]


def _segments() -> list[dict[str, Any]]:
    lines = [
        "Nobody talks about why vague goals make focus harder.",
        "The problem is that every unclear task creates another decision.",
        "However, one visible action removes that hidden friction.",
        "First write the smallest action that can be completed today.",
        "Then suddenly the workload feels smaller and momentum returns.",
        "Finally, that's why clarity beats motivation when work feels stuck.",
        "The truth is most productivity advice starts too late.",
        "What happened next surprised the entire team during the second test.",
        "We removed half the checklist and completion speed doubled.",
        "I realized the useful system was the simplest one.",
        "The reason this works is that visible progress reduces uncertainty.",
        "Finally, the payoff is calmer work with fewer abandoned tasks.",
    ]
    return [
        {"start": index * 10.0, "end": (index + 1) * 10.0, "text": text}
        for index, text in enumerate(lines)
    ]


def _understanding() -> dict[str, Any]:
    return {
        "schema_version": "boba_whole_video_understanding_v1",
        "project_id": "proj_discovery",
        "source_id": "uploads/proj_discovery/source.mp4",
        "video_duration_seconds": 120.0,
        "topic_timeline": [
            {
                "segment_id": "topic_focus",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "topic": "Focus friction",
                "summary": "Why unclear tasks create hidden friction.",
                "confidence": 0.84,
            },
            {
                "segment_id": "topic_experiment",
                "start_seconds": 40.0,
                "end_seconds": 80.0,
                "topic": "Momentum experiment",
                "summary": "A simpler checklist changes performance.",
                "confidence": 0.82,
            },
            {
                "segment_id": "topic_payoff",
                "start_seconds": 80.0,
                "end_seconds": 120.0,
                "topic": "Clarity payoff",
                "summary": "Visible progress reduces uncertainty.",
                "confidence": 0.88,
            },
        ],
        "emotional_beats": [
            {
                "beat_id": "emotion_surprise",
                "start_seconds": 70.0,
                "end_seconds": 90.0,
                "emotion_label": "surprise",
                "intensity": 0.82,
                "reason": "The experiment has an unexpected result.",
                "confidence": 0.78,
            }
        ],
        "context_payoff_map": [
            {
                "link_id": "link_payoff",
                "context_start_seconds": 90.0,
                "context_end_seconds": 100.0,
                "payoff_start_seconds": 100.0,
                "payoff_end_seconds": 120.0,
                "description": "The reason resolves with a calmer-work payoff.",
                "standalone_clip_possible": True,
                "setup_required": True,
                "confidence": 0.86,
            }
        ],
        "section_scores": [
            {
                "section_id": "section_focus",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "importance_score": 0.8,
                "clarity_score": 0.82,
                "energy_score": 0.58,
                "novelty_score": 0.7,
                "shortability_score": 0.84,
                "filler_score": 0.08,
                "repetition_score": 0.1,
                "reasons": ["Clear problem and turn."],
            },
            {
                "section_id": "section_experiment",
                "start_seconds": 40.0,
                "end_seconds": 80.0,
                "importance_score": 0.78,
                "clarity_score": 0.8,
                "energy_score": 0.82,
                "novelty_score": 0.76,
                "shortability_score": 0.86,
                "filler_score": 0.12,
                "repetition_score": 0.08,
                "reasons": ["Unexpected experiment result."],
            },
            {
                "section_id": "section_filler",
                "start_seconds": 52.0,
                "end_seconds": 67.0,
                "importance_score": 0.2,
                "clarity_score": 0.3,
                "energy_score": 0.2,
                "novelty_score": 0.1,
                "shortability_score": 0.2,
                "filler_score": 0.8,
                "repetition_score": 0.78,
                "reasons": ["Repeated filler."],
            },
            {
                "section_id": "section_payoff",
                "start_seconds": 80.0,
                "end_seconds": 120.0,
                "importance_score": 0.88,
                "clarity_score": 0.9,
                "energy_score": 0.68,
                "novelty_score": 0.72,
                "shortability_score": 0.9,
                "filler_score": 0.04,
                "repetition_score": 0.08,
                "reasons": ["Complete explanation and payoff."],
            },
        ],
        "shortability_hints": [
            {
                "hint_id": "hint_focus",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "suggested_clip_type": "possible_hook",
                "hook_potential": 0.88,
                "setup_needed": False,
                "payoff_strength": 0.5,
                "recommended_action": "consider",
                "reason": "A contrarian opening leads to a clear explanation.",
            },
            {
                "hint_id": "hint_experiment",
                "start_seconds": 40.0,
                "end_seconds": 80.0,
                "suggested_clip_type": "candidate_for_short",
                "hook_potential": 0.72,
                "setup_needed": False,
                "payoff_strength": 0.62,
                "recommended_action": "consider",
                "reason": "A surprising experiment creates a standalone result.",
            },
            {
                "hint_id": "hint_payoff",
                "start_seconds": 80.0,
                "end_seconds": 120.0,
                "suggested_clip_type": "payoff_clip",
                "hook_potential": 0.65,
                "setup_needed": True,
                "payoff_strength": 0.9,
                "recommended_action": "include_setup",
                "reason": "The final explanation contains the clearest payoff.",
            },
        ],
    }


def _discover(**updates: Any) -> BobaCandidateClipDiscoveryV1:
    payload: dict[str, Any] = {
        "project_id": "proj_discovery",
        "source_id": "uploads/proj_discovery/source.mp4",
        "video_duration_seconds": 120.0,
        "transcript_segments": _segments(),
        "whole_video_understanding": _understanding(),
        "analysis_signals_v2": {
            "audio_energy": {
                "timeline": {
                    "events": [
                        {"start_seconds": 68.0, "end_seconds": 88.0, "score": 0.85}
                    ]
                }
            }
        },
        "story_artifact": {},
        "virality_artifact": {
            "why_this_can_work": "A contrarian hook and surprising payoff create curiosity."
        },
        "planning_artifact": {},
    }
    payload.update(updates)
    return BobaCandidateClipDiscoveryEngine().discover(**payload)


def _project(project_id: str = "proj_discovery") -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="Candidate Discovery Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=120.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def test_discovery_contract_serializes() -> None:
    result = _discover()
    assert BobaCandidateClipDiscoveryV1.model_validate_json(result.model_dump_json()) == result


def test_candidate_clip_contract_serializes() -> None:
    item = _discover().candidates[0]
    assert BobaCandidateClipV1.model_validate_json(item.model_dump_json()) == item


def test_boundary_suggestion_contract_serializes() -> None:
    item = _discover().candidates[0].boundary_suggestion
    assert BobaBoundarySuggestionV1.model_validate_json(item.model_dump_json()) == item


def test_evidence_contract_serializes() -> None:
    item = _discover().candidates[0].evidence
    assert BobaCandidateEvidenceV1.model_validate_json(item.model_dump_json()) == item


def test_rejected_window_contract_serializes() -> None:
    item = _discover().rejected_windows[0]
    assert BobaRejectedWindowV1.model_validate_json(item.model_dump_json()) == item


def test_diversity_summary_contract_serializes() -> None:
    item = _discover().diversity_summary
    assert BobaCandidateDiversitySummaryV1.model_validate_json(item.model_dump_json()) == item


def test_signal_usage_contract_serializes() -> None:
    item = _discover().signal_usage
    assert BobaCandidateDiscoverySignalUsageV1.model_validate_json(item.model_dump_json()) == item


def test_shortability_hints_create_candidates() -> None:
    result = _discover()
    assert any(
        "whole_video_shortability_hint" in item.evidence.source_signals
        for item in result.candidates
    )


def test_emotional_beats_create_candidates() -> None:
    result = _discover()
    assert any(item.emotion_label == "surprise" for item in result.candidates)


def test_context_payoff_links_create_setup_aware_candidates() -> None:
    result = _discover()
    candidate = next(
        item for item in result.candidates if item.payoff_present and item.setup_required
    )
    assert candidate.context_needed is True
    assert candidate.end_seconds >= 120.0


def test_section_scoring_rejects_filler() -> None:
    result = _discover()
    assert any(item.reason == "high_filler_or_repetition" for item in result.rejected_windows)


def test_transcript_hook_cues_create_candidates() -> None:
    result = _discover(
        whole_video_understanding={},
        analysis_signals_v2={},
        virality_artifact={},
    )
    assert any("transcript_hook_cue" in item.evidence.source_signals for item in result.candidates)


def test_invalid_windows_are_clamped() -> None:
    understanding = {
        "video_duration_seconds": 60.0,
        "shortability_hints": [
            {
                "hint_id": "invalid_bounds",
                "start_seconds": -8.0,
                "end_seconds": 90.0,
                "suggested_clip_type": "candidate_for_short",
                "hook_potential": 0.8,
                "setup_needed": False,
                "payoff_strength": 0.6,
                "recommended_action": "consider",
                "reason": "Bounds need clamping.",
            }
        ],
    }
    result = _discover(
        video_duration_seconds=60.0,
        whole_video_understanding=understanding,
        transcript_segments=_segments()[:6],
        analysis_signals_v2={},
        virality_artifact={},
    )
    assert all(0.0 <= item.start_seconds < item.end_seconds <= 60.0 for item in result.candidates)


def test_too_short_candidates_are_expanded_or_rejected() -> None:
    understanding = {
        "video_duration_seconds": 60.0,
        "shortability_hints": [
            {
                "hint_id": "short",
                "start_seconds": 30.0,
                "end_seconds": 32.0,
                "suggested_clip_type": "possible_hook",
                "hook_potential": 0.8,
                "setup_needed": False,
                "payoff_strength": 0.2,
                "recommended_action": "consider",
                "reason": "Short hook interval.",
            }
        ],
    }
    result = _discover(
        video_duration_seconds=60.0,
        whole_video_understanding=understanding,
        transcript_segments=_segments()[:6],
        analysis_signals_v2={},
        virality_artifact={},
    )
    assert all(item.duration_seconds >= 12.0 for item in result.candidates)


def test_overlong_candidates_are_clamped_and_warned() -> None:
    understanding = {
        "video_duration_seconds": 130.0,
        "shortability_hints": [
            {
                "hint_id": "overlong",
                "start_seconds": 0.0,
                "end_seconds": 125.0,
                "suggested_clip_type": "candidate_for_short",
                "hook_potential": 0.8,
                "setup_needed": False,
                "payoff_strength": 0.4,
                "recommended_action": "consider",
                "reason": "Overlong source interval.",
            }
        ],
    }
    result = _discover(
        video_duration_seconds=130.0,
        whole_video_understanding=understanding,
        transcript_segments=_segments(),
        analysis_signals_v2={},
        virality_artifact={},
    )
    candidate = result.candidates[0]
    assert candidate.duration_seconds <= 90.0
    assert any("Overlong" in warning for warning in candidate.warnings)


def test_duplicate_windows_are_removed() -> None:
    understanding = _understanding()
    understanding["shortability_hints"].append(
        {**understanding["shortability_hints"][0], "hint_id": "duplicate"}
    )
    result = _discover(whole_video_understanding=understanding)
    assert result.diversity_summary.duplicate_windows_removed > 0


def test_high_overlap_lower_confidence_candidates_are_rejected() -> None:
    understanding = {
        "video_duration_seconds": 80.0,
        "shortability_hints": [
            {
                "hint_id": "strong",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "suggested_clip_type": "payoff_clip",
                "hook_potential": 0.9,
                "setup_needed": False,
                "payoff_strength": 0.9,
                "recommended_action": "consider",
                "reason": "Strong window.",
            },
            {
                "hint_id": "weak",
                "start_seconds": 2.0,
                "end_seconds": 39.0,
                "suggested_clip_type": "candidate_for_short",
                "hook_potential": 0.4,
                "setup_needed": False,
                "payoff_strength": 0.2,
                "recommended_action": "review",
                "reason": "Lower confidence overlap.",
            },
        ],
    }
    result = _discover(
        video_duration_seconds=80.0,
        whole_video_understanding=understanding,
        transcript_segments=_segments()[:8],
        analysis_signals_v2={},
        virality_artifact={},
    )
    assert result.diversity_summary.high_overlap_windows_removed > 0
    assert any(
        item.reason == "high_overlap_lower_confidence" for item in result.rejected_windows
    )


def test_candidate_diversity_is_preserved() -> None:
    result = _discover()
    assert result.diversity_summary.topic_count >= 3
    assert len(result.diversity_summary.candidate_types) >= 2


def test_missing_whole_video_understanding_degrades_gracefully() -> None:
    result = _discover(
        whole_video_understanding={},
        analysis_signals_v2={},
        virality_artifact={},
    )
    assert result.candidates
    assert result.signal_usage.fallback_used is True
    assert result.signal_usage.planning_used is False
    assert "whole_video_understanding" in result.signal_usage.unavailable_signals


def test_missing_transcript_fails_clearly_when_no_other_signals_exist() -> None:
    with pytest.raises(ValidationError, match="timed transcript or upstream"):
        BobaCandidateClipDiscoveryEngine().discover(
            project_id="proj_missing",
            transcript_segments=[],
        )


def test_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_candidate_clip_discovery(_discover())
    loaded = store.load_candidate_clip_discovery(result.project_id)
    payload = json.loads(store.candidate_clip_discovery_path(result.project_id).read_text())
    assert loaded == result
    assert payload["schema_version"] == "boba_candidate_clip_discovery_v1"
    assert "transcript_segments" not in payload


def test_creative_director_can_optionally_consume_discovered_candidates(
    tmp_path: Path,
) -> None:
    discovery = _discover()
    briefs = BobaCreativeDirector(BobaMemoryStore(tmp_path / "boba")).create_briefs(
        discovery.project_id,
        {
            "discovered_candidate_clips": [
                item.model_dump(mode="json") for item in discovery.candidates
            ],
            "transcript_segments": _segments(),
            "whole_video_understanding": _understanding(),
            "safety_status": "unknown",
        },
    )
    assert briefs
    assert briefs[0].clip_id in {item.candidate_id for item in discovery.candidates}


def test_api_route_returns_saved_discovery(app: FastAPI, tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    project = _project()
    asyncio.run(StorageProjectRepository(storage).save(project))
    asyncio.run(
        storage.put(
            f"analysis/{project.id}/stages/speech_transcription.json",
            json.dumps(
                {"status": "completed", "data": {"segments": _segments()}}
            ).encode(),
            content_type="application/json",
        )
    )
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        discovered = client.post(
            f"/api/v1/boba/projects/{project.id}/candidate-clips/discover"
        )
        saved = client.get(f"/api/v1/boba/projects/{project.id}/candidate-clips")
    assert discovered.status_code == 200
    assert saved.status_code == 200
    assert discovered.json()["candidates"] == saved.json()["candidates"]


def test_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_candidate_clip_discovery.py"),
            "--self-check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"passed": true' in result.stdout.casefold()


def test_validator_synthetic_project_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_candidate_clip_discovery.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"candidate_count": 5' in result.stdout


def test_discovery_does_not_trigger_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    result = _discover()
    assert result.candidates


def test_discovery_makes_no_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = _discover()
    assert result.signal_usage.whole_video_understanding_used is True


def test_validator_reports_and_artifacts_stay_under_ignored_work() -> None:
    from tools.validate_boba_candidate_clip_discovery import REPORT_DIR

    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_candidate_clip_discovery"
    assert "media" not in REPORT_DIR.parts
    assert "storage_data" not in REPORT_DIR.parts
