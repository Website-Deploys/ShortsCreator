"""BOBA Editorial Decision Engine V1 contracts, logic, API, and validator tests."""

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
from tools.validate_boba_editorial_decision import (
    REPORT_DIR,
    build_synthetic_inputs,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaEditingInstructionPacketV1,
    BobaEditorialDecisionEngine,
    BobaEditorialDecisionSetV1,
    BobaEditorialDecisionV1,
    BobaEditorialRiskReviewV1,
    BobaEditorialRiskSummaryV1,
    BobaEditorialSignalUsageV1,
    BobaIntegration,
    BobaMemoryStore,
)
from olympus.boba.clip_ranking import BobaClipRankingV1
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_editorial_decision"


def _source_context(**updates: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "source_type": "upload",
        "external_source": False,
        "rights_status": "local_upload",
        "transcript_available": True,
        "face_signals_available": True,
        "speaker_signals_available": True,
        "visual_signals_available": True,
    }
    context.update(updates)
    return context


def _result(
    *,
    source_context: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
) -> BobaEditorialDecisionSetV1:
    ranking, discovery, briefs = build_synthetic_inputs(PROJECT_ID)
    return BobaEditorialDecisionEngine().decide(
        project_id=PROJECT_ID,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding={
            "section_scores": [
                {
                    "start_seconds": 80.0,
                    "end_seconds": 112.0,
                    "energy_score": 0.92,
                }
            ],
            "emotional_beats": [
                {
                    "start_seconds": 80.0,
                    "end_seconds": 112.0,
                    "intensity": 0.95,
                }
            ],
        },
        creative_briefs=briefs,
        analysis_artifact={"confidence": 0.9, "signals": ["speech", "visual"]},
        story_artifact={
            "micro_stories": [
                {
                    "start": 0.0,
                    "end": 32.0,
                    "story_summary": "A hidden problem resolves into a useful system.",
                }
            ]
        },
        virality_artifact={"hook_score": 0.9, "retention_score": 0.84},
        planning_artifact={
            "selected_plans": [{"start": 0.0, "end": 32.0, "confidence": 0.9}]
        },
        editing_artifact={"timelines": []},
        memory=memory,
        source_context=source_context or _source_context(),
    )


def _decision(result: BobaEditorialDecisionSetV1, candidate_id: str) -> BobaEditorialDecisionV1:
    return next(item for item in result.decisions if item.candidate_id == candidate_id)


def _project() -> Project:
    now = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Editorial Decision Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=340.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def test_decision_set_contract_serializes() -> None:
    result = _result()
    payload = json.loads(result.model_dump_json())
    assert payload["schema_version"] == "boba_editorial_decision_engine_v1"
    assert BobaEditorialDecisionSetV1.model_validate(payload) == result


def test_decision_contract_serializes() -> None:
    decision = _result().decisions[0]
    assert BobaEditorialDecisionV1.model_validate(
        decision.model_dump(mode="json")
    ) == decision


def test_instruction_packet_serializes() -> None:
    packet = _result().decisions[0].editing_instruction_packet
    assert BobaEditingInstructionPacketV1.model_validate(
        packet.model_dump(mode="json")
    ) == packet


def test_risk_review_serializes() -> None:
    review = _decision(_result(), "needs_context").risk_review
    assert BobaEditorialRiskReviewV1.model_validate(
        review.model_dump(mode="json")
    ) == review


def test_risk_summary_serializes() -> None:
    summary = _result().risk_summary
    assert BobaEditorialRiskSummaryV1.model_validate(
        summary.model_dump(mode="json")
    ) == summary


def test_signal_usage_serializes() -> None:
    usage = _result().signal_usage
    assert BobaEditorialSignalUsageV1.model_validate(
        usage.model_dump(mode="json")
    ) == usage
    assert usage.clip_ranking_used is True


def test_must_make_clip_becomes_selected() -> None:
    decision = _decision(_result(), "must_make_truth")
    assert decision.selected is True
    assert decision.production_priority == "immediate"


def test_weak_candidate_needs_revision_or_is_rejected() -> None:
    decision = _decision(_result(), "needs_context")
    assert decision.render_readiness in {"needs_revision", "blocked"}
    assert decision.selected is False


def test_rights_not_allowed_candidate_is_blocked() -> None:
    decision = _decision(_result(), "rights_risk")
    assert decision.render_readiness == "blocked"
    assert decision.production_priority == "do_not_produce"
    assert decision.selected is False


def test_unknown_external_rights_prevent_ready_for_render() -> None:
    result = _result(
        source_context=_source_context(
            source_type="external",
            external_source=True,
            rights_status="unknown",
        )
    )
    decision = _decision(result, "must_make_truth")
    assert decision.risk_review.rights_risk is True
    assert decision.render_readiness != "ready_for_render"


def test_missing_context_creates_risk_warning() -> None:
    decision = _decision(_result(), "needs_context")
    assert decision.risk_review.missing_context is True
    assert any("context" in item.casefold() for item in decision.risk_review.warnings)


def test_weak_payoff_creates_risk_warning() -> None:
    decision = _decision(_result(), "weak_payoff")
    assert decision.risk_review.weak_payoff is True
    assert any("payoff" in item.casefold() for item in decision.risk_review.warnings)


def test_strong_emotional_candidate_gets_emotional_direction() -> None:
    decision = _decision(_result(), "strong_emotional")
    assert decision.final_hook_strategy == "emotional_reveal"
    assert decision.music_mood in {"emotional", "motivational"}
    assert decision.caption_style == "emotional_emphasis"


def test_educational_candidate_gets_keyword_captions() -> None:
    decision = _decision(_result(), "strong_educational")
    assert decision.final_hook_strategy == "educational_open_loop"
    assert decision.caption_style == "keyword_highlight"


def test_high_energy_candidate_gets_faster_pacing() -> None:
    ranking, discovery, _briefs = build_synthetic_inputs(PROJECT_ID)
    ranked = _decision_candidate(ranking, "strong_emotional").model_copy(
        update={"candidate_type": "high_energy_section"}
    )
    candidate = next(
        item for item in discovery.candidates if item.candidate_id == "strong_emotional"
    ).model_copy(update={"candidate_type": "high_energy_section"})
    compact_ranking = ranking.model_copy(
        update={
            "ranked_candidates": [ranked],
            "recommended_clip_ids": [ranked.candidate_id],
            "backup_clip_ids": [],
            "rejected_clip_ids": [],
        }
    )
    compact_discovery = discovery.model_copy(update={"candidates": [candidate]})
    result = BobaEditorialDecisionEngine().decide(
        project_id=PROJECT_ID,
        clip_ranking=compact_ranking,
        candidate_discovery=compact_discovery,
        whole_video_understanding={
            "emotional_beats": [
                {"start_seconds": 80.0, "end_seconds": 112.0, "intensity": 0.96}
            ]
        },
        source_context=_source_context(),
    )
    assert result.decisions[0].pacing_intensity in {"fast", "aggressive"}


def _decision_candidate(ranking: BobaClipRankingV1, candidate_id: str) -> Any:
    return next(item for item in ranking.ranked_candidates if item.candidate_id == candidate_id)


def test_visual_layout_risk_chooses_safe_motion() -> None:
    result = _result(source_context=_source_context(face_signals_available=False))
    decision = _decision(result, "must_make_truth")
    assert decision.risk_review.visual_layout_risk is True
    assert decision.motion_style in {"stable", "layout_safe"}


def test_music_selection_is_mood_only_without_track_path() -> None:
    valid_moods = {
        "none",
        "motivational",
        "emotional",
        "suspense",
        "energetic",
        "calm",
        "funny",
        "cinematic",
        "educational",
    }
    for decision in _result().decisions:
        assert decision.music_mood in valid_moods
        assert "/" not in decision.music_mood
        assert "\\" not in decision.music_mood
        assert ".mp3" not in decision.model_dump_json().casefold()


def test_instruction_packet_includes_required_directions() -> None:
    packet = _result().decisions[0].editing_instruction_packet
    assert packet.hook_instruction
    assert packet.cut_instruction
    assert packet.caption_instruction
    assert packet.motion_instruction
    assert packet.audio_instruction
    assert packet.pacing_instruction
    assert packet.retention_instruction
    assert packet.risk_instruction


def test_selected_clips_stay_within_three_to_ten() -> None:
    result = _result()
    assert 3 <= len(result.selected_clip_ids) <= 10
    assert len(result.production_order) == len(result.selected_clip_ids)


def test_missing_ranking_artifact_fails_clearly() -> None:
    with pytest.raises(ValidationError, match="requires a saved clip ranking"):
        BobaEditorialDecisionEngine().decide(
            project_id=PROJECT_ID,
            clip_ranking=None,
        )


def test_empty_ranking_artifact_fails_clearly() -> None:
    ranking, _discovery, _briefs = build_synthetic_inputs(PROJECT_ID)
    empty = ranking.model_copy(
        update={
            "ranked_candidates": [],
            "recommended_clip_ids": [],
            "backup_clip_ids": [],
        }
    )
    with pytest.raises(ValidationError, match="cannot use an empty clip ranking"):
        BobaEditorialDecisionEngine().decide(
            project_id=PROJECT_ID,
            clip_ranking=empty,
        )


def test_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    decisions = store.save_editorial_decisions(_result())
    payload = json.loads(store.editorial_decision_path(PROJECT_ID).read_text())
    assert store.load_editorial_decisions(PROJECT_ID) == decisions
    assert payload["schema_version"] == "boba_editorial_decision_engine_v1"
    assert "transcript_segments" not in payload
    assert "media_path" not in payload


def test_api_routes_create_and_return_saved_decisions(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    ranking, discovery, _briefs = build_synthetic_inputs(PROJECT_ID)
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_candidate_clip_discovery(discovery)
    store.save_clip_ranking(ranking)
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(f"/api/v1/boba/projects/{PROJECT_ID}/editorial-decisions")
        saved = client.get(f"/api/v1/boba/projects/{PROJECT_ID}/editorial-decisions")
    assert created.status_code == 200
    assert saved.status_code == 200
    assert created.json()["decisions"] == saved.json()["decisions"]
    signals = asyncio.run(integration.collect_project_signals(PROJECT_ID))
    assert signals["editorial_decisions_available"] is True
    assert signals["editorial_candidate_clips"]


def test_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_editorial_decision.py"),
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
            str(ROOT / "tools" / "validate_boba_editorial_decision.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"decision_count": 8' in result.stdout
    assert '"rendering_triggered": false' in result.stdout.casefold()


def test_editorial_decisions_do_not_trigger_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert _result().decisions


def test_editorial_decisions_make_no_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    assert _result().signal_usage.clip_ranking_used is True


def test_reports_and_media_are_not_staged() -> None:
    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_editorial_decision"
    assert "media" not in REPORT_DIR.parts
    assert "storage_data" not in REPORT_DIR.parts
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    ).stdout.splitlines()
    assert not any(
        path.startswith(("work/", "media/", "storage_data/")) for path in staged
    )
