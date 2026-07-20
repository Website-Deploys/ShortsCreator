"""BOBA Scout, Creative Director, approval learning, API, and validator tests."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api import dependencies
from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaApprovalEventV1,
    BobaApprovalService,
    BobaCandidateV1,
    BobaCreativeBriefV1,
    BobaCreativeDirector,
    BobaIntegration,
    BobaMemoryStore,
    BobaScout,
    BobaScoutScoreV1,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.editing import EditingAnalysis
from olympus.domain.entities.project import Project

ROOT = Path(__file__).resolve().parents[2]


def _candidate(candidate_id: str = "candidate_one", **updates: Any) -> BobaCandidateV1:
    payload: dict[str, Any] = {
        "candidate_id": candidate_id,
        "source_type": "manual_link",
        "title": "Why this unexpected focus mistake changes everything",
        "url": "https://example.com/video",
        "creator": "Example Creator",
        "duration_seconds": 480.0,
        "metadata": {
            "topic": "focus",
            "emotion": "motivational",
            "emotional_potential": 0.75,
            "novelty_score": 0.72,
            "clip_density": 0.8,
        },
        "rights_status": "unknown",
        "permission_confirmed": False,
        "status": "idea_only",
    }
    payload.update(updates)
    return BobaCandidateV1.model_validate(payload)


def _signals(**updates: Any) -> dict[str, Any]:
    signals: dict[str, Any] = {
        "selected_plans": [
            {
                "clip_id": "clip_one",
                "start": 10.0,
                "end": 43.0,
                "hook_line": "Why does focus fail even when you care?",
                "hook_category": "curiosity_gap",
                "scores": {"hook": 0.86, "emotion": 0.72},
                "selected_reason": "Complete problem-to-solution arc with a clear payoff.",
                "story": {"story_shape": "problem_to_solution", "context_risk": 0.2},
                "virality": {
                    "why_this_can_work": "The opening creates a concrete unanswered question."
                },
            }
        ],
        "analysis_signals_v2": {"dominant_emotion": "hopeful"},
        "transcript_available": True,
        "transcript_segments": [
            {
                "start": 10.0,
                "end": 13.0,
                "text": "Why does focus fail even when you care?",
            }
        ],
        "editing_timelines": [
            {"clip_id": "clip_one", "pacing_style": "fast", "edit_style": "punchy"}
        ],
        "safety_status": "low",
        "safety_manual_review_required": False,
    }
    signals.update(updates)
    return signals


def test_candidate_contract_serializes() -> None:
    candidate = _candidate()
    assert BobaCandidateV1.model_validate_json(candidate.model_dump_json()) == candidate


def test_scout_score_contract_serializes() -> None:
    score = BobaScoutScoreV1(
        candidate_id="candidate_one",
        overall_score=0.7,
        hook_potential=0.8,
        emotional_potential=0.7,
        novelty_score=0.6,
        clarity_score=0.7,
        clipping_potential=0.8,
        risk_score=0.1,
        recommended_action="process_now",
    )
    assert BobaScoutScoreV1.model_validate_json(score.model_dump_json()) == score


def test_creative_brief_contract_serializes() -> None:
    brief = BobaCreativeBriefV1(
        clip_id="clip_one",
        project_id="proj_one",
        target_emotion="hopeful",
        hook_type="curiosity_gap",
        curiosity_trigger="Why does focus fail?",
        story_angle="problem_to_solution",
        recommended_duration_seconds=33.0,
        pacing_level="fast",
        caption_style="bold_keyword_emphasis",
        motion_style="controlled_punch_in",
        music_mood="uplifting_momentum",
        why_it_may_work="The question creates a clear open loop.",
    )
    assert BobaCreativeBriefV1.model_validate_json(brief.model_dump_json()) == brief


def test_approval_event_contract_serializes() -> None:
    event = BobaApprovalEventV1(
        event_id="approval_one",
        target_type="candidate",
        target_id="candidate_one",
        decision="approved",
        reason="Strong fit.",
    )
    assert BobaApprovalEventV1.model_validate_json(event.model_dump_json()) == event


def test_unknown_rights_prevents_process_now_recommendation(tmp_path: Path) -> None:
    scout = BobaScout(BobaMemoryStore(tmp_path / "boba"))
    scout.create_candidate(_candidate())
    score = scout.score_candidate("candidate_one")
    assert score.recommended_action == "review_rights_first"
    assert score.risk_score >= 0.7


def test_permission_confirmed_allows_approved_for_processing(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    scout = BobaScout(store)
    scout.create_candidate(
        _candidate(
            rights_status="permission_confirmed",
            permission_confirmed=True,
        )
    )
    event, candidate, _lesson = BobaApprovalService(store).decide_candidate(
        "candidate_one",
        decision="approved",
        approve_for_processing=True,
    )
    assert event.decision == "approved"
    assert candidate.status == "approved_for_processing"


def test_title_curiosity_affects_score(tmp_path: Path) -> None:
    scout = BobaScout(BobaMemoryStore(tmp_path / "boba"))
    scout.create_candidate(_candidate("candidate_curious"))
    scout.create_candidate(
        _candidate(
            "candidate_plain",
            title="A conversation about everyday work",
            metadata={"topic": "work", "clip_density": 0.8},
        )
    )
    curious = scout.score_candidate("candidate_curious")
    plain = scout.score_candidate("candidate_plain")
    assert curious.hook_potential > plain.hook_potential


def test_emotional_metadata_affects_score(tmp_path: Path) -> None:
    scout = BobaScout(BobaMemoryStore(tmp_path / "boba"))
    scout.create_candidate(_candidate("candidate_emotional"))
    scout.create_candidate(
        _candidate(
            "candidate_flat",
            metadata={
                "topic": "focus",
                "emotional_potential": 0.1,
                "novelty_score": 0.72,
                "clip_density": 0.8,
            },
        )
    )
    emotional = scout.score_candidate("candidate_emotional")
    flat = scout.score_candidate("candidate_flat")
    assert emotional.emotional_potential > flat.emotional_potential
    assert emotional.overall_score > flat.overall_score


def test_unknown_rights_generates_warning(tmp_path: Path) -> None:
    scout = BobaScout(BobaMemoryStore(tmp_path / "boba"))
    scout.create_candidate(_candidate())
    score = scout.score_candidate("candidate_one")
    assert any("rights are unknown" in warning.casefold() for warning in score.warnings)


def test_approval_stores_explicit_memory_lesson(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    BobaScout(store).create_candidate(_candidate())
    event, _candidate_value, lesson = BobaApprovalService(store).decide_candidate(
        "candidate_one",
        decision="approved",
        reason="The motivational angle fits.",
    )
    assert event.target_type == "candidate"
    assert lesson.source == "explicit_boba_approval"
    assert lesson.metadata["approval_event_id"] == event.event_id
    assert store.get_record(lesson.memory_id) is not None


def test_rejection_changes_future_scoring(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    scout = BobaScout(store)
    low_emotion = {
        "topic": "focus",
        "emotional_potential": 0.15,
        "novelty_score": 0.5,
        "clip_density": 0.6,
    }
    scout.create_candidate(_candidate("candidate_rejected", metadata=low_emotion))
    scout.create_candidate(_candidate("candidate_future", metadata=low_emotion))
    before = scout.score_candidate("candidate_future").overall_score
    BobaApprovalService(store).decide_candidate(
        "candidate_rejected",
        decision="rejected",
        reason="Too little emotional movement.",
    )
    after = scout.score_candidate("candidate_future").overall_score
    assert after < before


def test_creative_director_reads_analysis_signals(tmp_path: Path) -> None:
    director = BobaCreativeDirector(BobaMemoryStore(tmp_path / "boba"))
    brief = director.create_briefs("proj_one", _signals())[0]
    assert brief.target_emotion == "hopeful"


def test_creative_director_handles_missing_analysis_signals(tmp_path: Path) -> None:
    director = BobaCreativeDirector(BobaMemoryStore(tmp_path / "boba"))
    brief = director.create_briefs(
        "proj_one", _signals(analysis_signals_v2={}, transcript_available=False)
    )[0]
    assert brief.target_emotion == "informative"
    assert any("analysis_signals_v2" in warning for warning in brief.risk_warnings)


def test_creative_brief_includes_hook_strategy(tmp_path: Path) -> None:
    brief = BobaCreativeDirector(BobaMemoryStore(tmp_path / "boba")).create_briefs(
        "proj_one", _signals()
    )[0]
    assert brief.hook_type == "curiosity_gap"
    assert "focus fail" in brief.curiosity_trigger.casefold()
    assert any("hook" in note.casefold() for note in brief.editing_notes)


def test_creative_brief_music_is_mood_metadata_only(tmp_path: Path) -> None:
    brief = BobaCreativeDirector(BobaMemoryStore(tmp_path / "boba")).create_briefs(
        "proj_one", _signals()
    )[0]
    payload = brief.model_dump(mode="json")
    assert payload["music_mood"] == "uplifting_momentum"
    assert "track" not in payload
    assert "song" not in payload


def test_api_rejects_processing_without_permission(app: FastAPI, tmp_path: Path) -> None:
    integration = BobaIntegration(
        LocalStorage(root=str(tmp_path / "storage")),
        BobaMemoryStore(tmp_path / "boba"),
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/boba/candidates", json=_candidate().model_dump(mode="json")
        )
        rejected = client.post(
            "/api/v1/boba/candidates/candidate_one/approve",
            json={"approve_for_processing": True, "reason": "Try to process."},
        )
    assert created.status_code == 200
    assert rejected.status_code == 422
    saved = integration.store.load_scout_candidate("candidate_one")
    assert saved is not None
    assert saved.status == "idea_only"


def test_json_and_csv_candidate_imports_are_local(tmp_path: Path) -> None:
    scout = BobaScout(BobaMemoryStore(tmp_path / "boba"))
    json_path = tmp_path / "candidates.json"
    json_path.write_text(
        json.dumps(
            [
                {
                    "candidate_id": "candidate_json",
                    "title": "A local metadata idea",
                    "rights_status": "unknown",
                }
            ]
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text(
        "candidate_id,title,rights_status,permission_confirmed\n"
        "candidate_csv,Another local idea,unknown,false\n",
        encoding="utf-8",
    )
    assert scout.import_candidates(json_path)[0].source_type == "json_import"
    assert scout.import_candidates(csv_path)[0].source_type == "csv_import"


def test_scout_makes_no_external_calls(tmp_path: Path, monkeypatch: Any) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access was attempted")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    scout = BobaScout(BobaMemoryStore(tmp_path / "boba"))
    scout.create_candidate(_candidate())
    assert scout.score_candidate("candidate_one").candidate_id == "candidate_one"


def test_candidate_processing_status_requires_rights() -> None:
    try:
        _candidate(status="approved_for_processing")
    except ValueError as exc:
        assert "approved_for_processing" in str(exc)
    else:
        raise AssertionError("candidate bypassed the rights gate")


def test_clip_idea_approval_stores_creative_preference(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    BobaCreativeDirector(store).create_briefs("proj_one", _signals())
    event, lesson = BobaApprovalService(store).decide_clip_idea(
        "proj_one",
        "clip_one",
        decision="approved",
        reason="Keep this hook treatment.",
    )
    assert event.target_type == "clip_idea"
    assert lesson.metadata["creative_preferences"]


@pytest.mark.asyncio
async def test_pre_render_hook_generates_briefs_before_render(monkeypatch: Any) -> None:
    events: list[str] = []

    class FakeBoba:
        async def generate_creative_briefs(self, project_id: str) -> list[object]:
            events.append(f"briefs:{project_id}")
            return [object()]

    class FakeRenderer:
        async def start(self, project: Project) -> None:
            events.append(f"render:{project.id}")

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(boba=SimpleNamespace(enabled=True)),
    )
    monkeypatch.setattr(dependencies, "boba_integration_provider", lambda: FakeBoba())
    monkeypatch.setattr(dependencies, "rendering_service_provider", lambda: FakeRenderer())
    project = cast(Project, SimpleNamespace(id="proj_hook"))
    editing = cast(EditingAnalysis, object())
    await dependencies._start_rendering_after_boba(project, editing)
    assert events == ["briefs:proj_hook", "render:proj_hook"]


@pytest.mark.asyncio
async def test_pre_render_hook_does_not_block_render_on_boba_failure(
    monkeypatch: Any,
) -> None:
    rendered: list[str] = []

    class FailingBoba:
        async def generate_creative_briefs(self, _project_id: str) -> list[object]:
            raise RuntimeError("synthetic BOBA failure")

    class FakeRenderer:
        async def start(self, project: Project) -> None:
            rendered.append(project.id)

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(boba=SimpleNamespace(enabled=True)),
    )
    monkeypatch.setattr(dependencies, "boba_integration_provider", lambda: FailingBoba())
    monkeypatch.setattr(dependencies, "rendering_service_provider", lambda: FakeRenderer())
    project = cast(Project, SimpleNamespace(id="proj_fallback"))
    editing = cast(EditingAnalysis, object())
    await dependencies._start_rendering_after_boba(project, editing)
    assert rendered == ["proj_fallback"]


def _run_validator(argument: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/validate_boba_scout_creative_director.py",
            argument,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def test_validator_self_check_passes() -> None:
    assert _run_validator("--self-check")["passed"] is True


def test_validator_synthetic_candidates_pass() -> None:
    report = _run_validator("--synthetic-candidates")
    assert report["passed"] is True
    assert report["download_or_processing_triggered"] is False


def test_validator_synthetic_project_passes() -> None:
    report = _run_validator("--synthetic-project")
    assert report["passed"] is True
    assert report["rendering_triggered"] is False


def test_generated_reports_are_not_tracked() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "--", "work/validation_reports/boba_scout_creative_director"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""
