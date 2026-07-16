"""BOBA Core Brain V1 contracts, memory, reasoning, API, CLI, and integration tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaBrain,
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionBus,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaIntegration,
    BobaLearningNoteV1,
    BobaMemoryStore,
    BobaObservationV1,
    create_editorial_policy,
    get_boba_constitution,
    rank_candidates,
)
from olympus.boba.contracts import BobaCandidateInsightV1
from olympus.boba.reasoning import (
    explain_candidate_comparison,
    explain_clip_rejection,
    explain_clip_selection,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now


def _project(project_id: str = "proj_boba") -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=180.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _signals(**updates: Any) -> dict[str, Any]:
    signals: dict[str, Any] = {
        "project": {"source_type": "upload", "duration_seconds": 180.0},
        "transcript_available": True,
        "visual_signals_available": True,
        "face_signals_available": True,
        "speaker_signals_available": True,
        "trend_signals_available": True,
        "safety_signals_available": True,
        "personalization_signals_available": True,
        "render_manifest_available": True,
        "planning_candidates_available": True,
        "editing_timelines_available": True,
        "safety_status": "low",
        "main_topics": ["discipline", "attention"],
        "story_threads": ["problem to lesson"],
    }
    signals.update(updates)
    return signals


def _decision(project_id: str = "proj_boba", **updates: Any) -> BobaDecisionV1:
    payload: dict[str, Any] = {
        "decision_id": "decision_one",
        "project_id": project_id,
        "decision_type": "clip_candidate_ranking",
        "question": "Which candidate should be recommended?",
        "answer": "Recommend the complete story candidate.",
        "confidence": 0.8,
        "input_signals": {"story": {"complete": True}, "planning": {"rank": 1}},
        "reasoning": {
            "summary": "The candidate preserves setup and payoff.",
            "evidence": ["Story completeness 0.84", "Payoff 0.82"],
            "tradeoffs": ["A louder alternative had weaker context."],
            "rejected_options": ["candidate_two"],
            "risks": ["Face detection is unavailable."],
            "explanation_for_user": "BOBA recommends the complete story candidate.",
        },
        "output_directive": {
            "target_system": "planning",
            "directive_type": "candidate_ranking_advisory",
            "parameters": {"candidate_id": "candidate_one"},
            "priority": 60,
            "constraints": ["Advisory only", "Never override safety"],
        },
    }
    payload.update(updates)
    return BobaDecisionV1.model_validate(payload)


def _observation(
    project_id: str = "proj_boba",
    summary: str = "Signal observed",
) -> BobaObservationV1:
    return BobaObservationV1(
        observation_id="observation_one",
        project_id=project_id,
        source="planning",
        observation_type="project_signal",
        summary=summary,
        evidence=["Persisted planning artifact"],
        confidence=0.8,
        safe_to_learn=True,
    )


def _candidate(candidate_id: str, start: float, end: float, **scores: float) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "start": start,
        "end": end,
        "scores": scores,
    }


def test_contracts_round_trip_json(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    state = BobaBrain(store).create_brain_state("proj_contract", _signals())
    decision = _decision("proj_contract")
    observation = _observation("proj_contract")
    note = BobaLearningNoteV1(
        note_id="note_one",
        project_id="proj_contract",
        source="explicit_feedback",
        lesson="Complete story clips were preferred in this project.",
        confidence=0.6,
        applies_to=["planning"],
        safety_checked=True,
    )
    insight = BobaCandidateInsightV1(
        candidate_id="candidate_one",
        source_start=0,
        source_end=30,
        duration=30,
        overall_recommendation=0.8,
    )
    ranking = BobaClipRankingV1(
        project_id="proj_contract",
        candidate_count=1,
        ranked_candidates=[insight],
        reasoning_summary="Complete story ranked first.",
    )
    policy = create_editorial_policy("proj_contract", "clip_one", {}, {})

    assert BobaBrainStateV1.model_validate_json(state.model_dump_json()) == state
    assert BobaDecisionV1.model_validate_json(decision.model_dump_json()) == decision
    assert BobaObservationV1.model_validate_json(observation.model_dump_json()) == observation
    assert BobaLearningNoteV1.model_validate_json(note.model_dump_json()) == note
    assert BobaClipRankingV1.model_validate_json(ranking.model_dump_json()) == ranking
    assert BobaEditorialPolicyV1.model_validate_json(policy.model_dump_json()) == policy


def test_constitution_has_safety_and_explanation_requirements() -> None:
    constitution = get_boba_constitution()
    forbidden = " ".join(constitution["forbidden_behaviors"]).lower()

    assert len(constitution["principles"]) >= 20
    assert "copy exact scripts" in forbidden
    assert "bypass copyright" in forbidden
    assert "bypass drm" in forbidden
    assert "override safety blockers" in forbidden
    assert len(constitution["explanation_requirements"]) >= 5


def test_brain_complete_signals_create_honest_ready_state(tmp_path: Path) -> None:
    state = BobaBrain(BobaMemoryStore(tmp_path)).create_brain_state("proj_ready", _signals())

    assert state.mode == "advise"
    assert state.confidence == 1.0
    assert state.source_understanding.missing_signals == []
    assert state.result.ready_for_planning is True
    assert state.result.ready_for_editing is True
    assert state.result.ready_for_rendering is True
    assert any("advisory" in warning for warning in state.result.warnings)


def test_brain_detects_missing_face_trend_fallback_and_manual_review(tmp_path: Path) -> None:
    state = BobaBrain(BobaMemoryStore(tmp_path)).create_brain_state(
        "proj_partial",
        _signals(
            transcript_available=False,
            visual_signals_available=False,
            face_signals_available=False,
            trend_fallback_used=True,
            safety_manual_review_required=True,
            render_manifest_available=False,
            planning_candidates_available=False,
            editing_timelines_available=False,
        ),
    )

    assert "face_detection" in state.source_understanding.missing_signals
    assert any("fallback" in item.lower() for item in state.source_understanding.warnings)
    assert any("manual review" in item.lower() for item in state.source_understanding.warnings)
    assert state.result.ready_for_planning is False
    assert state.result.ready_for_editing is False
    assert state.result.ready_for_rendering is False


def test_memory_saves_appends_truncates_and_loads(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path, max_excerpt_chars=80)
    brain = BobaBrain(store)
    state = brain.create_brain_state("proj_memory", _signals())
    decision = _decision("proj_memory")
    observation = _observation("proj_memory", "word " * 80)
    note = BobaLearningNoteV1(
        note_id="note_one",
        project_id="proj_memory",
        learning_scope="creator",
        source="explicit_feedback",
        lesson="Use complete story arcs.",
        confidence=0.5,
        applies_to=["planning"],
    )
    store.append_decision(decision)
    store.append_observation(observation)
    store.append_learning_note(note)

    assert store.load_brain_state(state.project_id) is not None
    assert store.list_decisions(state.project_id)[0].decision_id == decision.decision_id
    assert len(store.list_observations(state.project_id)[-1].summary) <= 80
    assert "interface-only" in store.list_learning_notes(state.project_id)[0].warnings[0]
    assert not list(tmp_path.rglob("*.tmp"))


def test_memory_rejects_secrets_and_handles_missing_project(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path)
    unsafe = _decision("proj_secret")
    unsafe.output_directive.parameters = {"api_key": "not-allowed"}

    with pytest.raises(ValidationError):
        store.append_decision(unsafe)
    assert store.load_brain_state("proj_missing") is None
    assert store.list_decisions("proj_missing") == []
    assert store.list_observations("proj_missing") == []


def test_decision_bus_validates_explanation_confidence_and_advisory_route(tmp_path: Path) -> None:
    bus = BobaDecisionBus(BobaMemoryStore(tmp_path))
    decision = _decision()
    routed = bus.register_decision(decision.project_id, decision)

    assert routed["delivery"] == "advisory"
    assert routed["consumed"] is False
    assert bus.list_project_decisions(decision.project_id) == [decision]
    assert bus.summarize_decisions(decision.project_id)["applied"] is False

    missing_confidence = decision.model_dump(mode="json")
    missing_confidence.pop("confidence")
    with pytest.raises(ValidationError):
        bus.validate_decision(missing_confidence)

    missing_evidence = decision.model_copy(deep=True)
    missing_evidence.reasoning.evidence = []
    with pytest.raises(ValidationError):
        bus.validate_decision(missing_evidence)


def test_decision_bus_cannot_override_safety(tmp_path: Path) -> None:
    bus = BobaDecisionBus(BobaMemoryStore(tmp_path))
    decision = _decision()
    decision.output_directive.parameters = {"override_safety": True}
    with pytest.raises(ValidationError):
        bus.validate_decision(decision)

    safety_claim = _decision()
    safety_claim.output_directive.target_system = "safety"
    safety_claim.output_directive.parameters = {"status": "safe"}
    with pytest.raises(ValidationError):
        bus.validate_decision(safety_claim)


def test_reasoning_selection_rejection_and_comparison_are_editorial() -> None:
    strong = {
        "candidate_id": "strong",
        "hook_strength": 0.9,
        "story_completeness": 0.85,
        "payoff_strength": 0.8,
        "overall_recommendation": 0.82,
    }
    weak = {
        "candidate_id": "weak",
        "payoff_strength": 0.1,
        "context_requirement": 0.8,
        "duplicate_risk": 0.7,
        "overall_recommendation": 0.25,
    }
    context = {"missing_signals": ["face detection unavailable"]}

    selection = explain_clip_selection(strong, context)
    rejection = explain_clip_rejection(weak, context)
    comparison = explain_candidate_comparison(strong, weak, context)

    for explanation in (selection, rejection, comparison):
        assert explanation["evidence"]
        assert explanation["tradeoffs"]
        assert explanation["risks"]
        assert explanation["explanation_for_user"]
        assert 0 < explanation["confidence"] <= 1
    assert "recommend" in selection["summary"].lower()
    assert "not prioritize" in rejection["summary"].lower()
    assert "strong" in comparison["summary"]


def test_ranking_prefers_complete_candidate_and_detects_quality_risks() -> None:
    candidates = [
        _candidate(
            "strong",
            10,
            45,
            hook=0.9,
            story_completion=0.88,
            payoff=0.85,
            emotion=0.7,
            trend_fit=0.6,
        ),
        {
            **_candidate(
                "weak",
                11,
                40,
                hook=0.3,
                story_completion=0.2,
                payoff=0.1,
            ),
            "context_requirement": 0.85,
            "boundary_risk": True,
        },
    ]
    ranking = rank_candidates("proj_rank", candidates)

    assert ranking.ranked_candidates[0].candidate_id == "strong"
    weak = next(item for item in ranking.rejected_candidates if item.candidate_id == "weak")
    assert any("payoff" in item for item in weak.warnings)
    assert any("context" in item for item in weak.warnings)
    assert any("boundary" in item for item in weak.warnings)
    assert ranking.duplicate_groups


def test_ranking_detects_already_used_range_and_timeline_clustering() -> None:
    ranking = rank_candidates(
        "proj_used",
        [
            _candidate("one", 10, 40, hook=0.8, story_completion=0.8, payoff=0.8),
            _candidate("two", 50, 80, hook=0.75, story_completion=0.75, payoff=0.75),
            _candidate("three", 90, 120, hook=0.7, story_completion=0.7, payoff=0.7),
        ],
        used_source_ranges=[{"start": 9, "end": 41}],
    )

    one = next(
        item
        for item in [*ranking.ranked_candidates, *ranking.rejected_candidates]
        if item.candidate_id == "one"
    )
    assert one.duplicate_risk > 0.8
    assert any("source range" in warning for warning in one.warnings)
    assert any("timeline" in warning for warning in ranking.warnings)


def test_editorial_policy_motivational_and_podcast_are_speech_first() -> None:
    motivational = create_editorial_policy(
        "proj_policy",
        "clip_motivation",
        {"content_niche": "motivational", "hook_strength": 0.9, "emotion": 0.8},
        {"face_layout_available": True, "transcript_available": True},
    )
    podcast = create_editorial_policy(
        "proj_policy",
        "clip_podcast",
        {"content_niche": "podcast", "hook_strength": 0.6},
        {"face_layout_available": False, "transcript_available": True},
    )

    assert motivational.pacing == "fast"
    assert motivational.motion_directives["enabled"] is True
    assert podcast.pacing == "balanced"
    assert podcast.motion_directives["enabled"] is False
    assert podcast.motion_directives["disable_reason"] == "face_or_layout_signals_unavailable"
    for policy in (motivational, podcast):
        assert policy.music_directives["ducking_priority"] == "speech_first"
        assert policy.ending_directives["avoid_cutting_final_word"] is True
        assert 0.3 <= policy.ending_directives["postroll_seconds"] <= 0.7


@pytest.mark.asyncio
async def test_integration_tolerates_missing_artifacts_and_generates_partial_brain(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project("proj_partial_artifacts")
    await StorageProjectRepository(storage).save(project)
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))

    signals = await integration.collect_project_signals(project.id)
    state = await integration.generate_boba_for_project(project.id)

    assert signals["transcript_available"] is False
    assert state.project_id == project.id
    assert state.result.ready_for_planning is False
    assert integration.store.list_decisions(project.id)


@pytest.mark.asyncio
async def test_integration_compact_summary_attaches_without_mutating_old_projects(
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project("proj_compact")
    await StorageProjectRepository(storage).save(project)
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))
    await integration.generate_boba_for_project(project.id)
    integration.store.save_candidate_ranking(
        rank_candidates(
            project.id,
            [_candidate("clip_one", 0, 30, hook=0.8, story_completion=0.8, payoff=0.8)],
        )
    )
    policy = create_editorial_policy(project.id, "clip_one", {}, {})
    integration.store.save_editorial_policy(policy)

    attached = integration.attach_boba_to_unified_clip_intelligence(
        project.id, "clip_one", {"clip_id": "clip_one"}
    )
    old = unified_clip_intelligence(plan={"id": "old_plan", "start": 0, "end": 20})

    assert attached["boba"]["advisory_only"] is True
    assert attached["boba"]["applied"] is False
    assert old["boba"] == {}


def test_api_brain_decisions_and_missing_project(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project("proj_api_boba")
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))

    async def seed() -> None:
        await StorageProjectRepository(storage).save(project)

    import asyncio

    asyncio.run(seed())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        brain = client.get(f"/api/v1/boba/projects/{project.id}/brain")
        decisions = client.get(f"/api/v1/boba/projects/{project.id}/decisions")
        missing = client.get("/api/v1/boba/projects/proj_missing/brain")

    assert brain.status_code == 200
    assert brain.json()["mode"] == "advise"
    assert decisions.status_code == 200
    assert decisions.json()["count"] >= 1
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "argument",
    [
        "--self-check",
        "--simulate-project",
        "--simulate-ranking",
        "--simulate-editorial-policy",
    ],
)
def test_cli_validation_modes(argument: str) -> None:
    completed = subprocess.run(
        [sys.executable, "tools/validate_boba_core.py", argument],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["passed"] is True
