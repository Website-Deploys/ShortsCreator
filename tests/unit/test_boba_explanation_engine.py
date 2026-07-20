"""BOBA Explanation Engine V1 contracts, evidence, API, and validator tests."""

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
from tools.validate_boba_explanation_engine import (
    REPORT_DIR,
    build_synthetic_explanation_inputs,
    build_synthetic_explanations,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaClipExplanationV1,
    BobaExplanationEngine,
    BobaExplanationEvidenceV1,
    BobaExplanationSetV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaProjectExplanationV1,
    BobaSignalExplanationV1,
    BobaUncertaintySummaryV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_explanation_engine"


def _result(project_id: str = PROJECT_ID) -> BobaExplanationSetV1:
    return build_synthetic_explanations(project_id)


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Explanation Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
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


def _all_explanations(result: BobaExplanationSetV1) -> list[BobaClipExplanationV1]:
    return [
        *result.candidate_explanations,
        *result.ranking_explanations,
        *result.editorial_explanations,
    ]


def _clean_supported_result() -> BobaExplanationSetV1:
    understanding, discovery, ranking, decisions, briefs, signals = (
        build_synthetic_explanation_inputs("proj_explanation_clean")
    )
    candidate = discovery.candidates[0].model_copy(update={"warnings": []})
    discovery = discovery.model_copy(
        update={"candidates": [candidate], "warnings": [], "limitations": []}
    )
    ranked = ranking.ranked_candidates[0]
    ranked = ranked.model_copy(
        update={
            "risk_warnings": [],
            "improvement_suggestions": [],
            "score_breakdown": ranked.score_breakdown.model_copy(
                update={"repetition_penalty": 0.0, "overlap_penalty": 0.0}
            ),
        }
    )
    ranking = ranking.model_copy(
        update={
            "ranked_candidates": [ranked],
            "recommended_clip_ids": [ranked.candidate_id],
            "backup_clip_ids": [],
            "rejected_clip_ids": [],
            "rejected_candidates": [],
            "warnings": [],
            "limitations": [],
        }
    )
    decision = next(
        item for item in decisions.decisions if item.candidate_id == ranked.candidate_id
    )
    decision = decision.model_copy(
        update={
            "risk_review": decision.risk_review.model_copy(
                update={"warnings": [], "blockers": []}
            ),
            "improvement_notes": [],
        }
    )
    decisions = decisions.model_copy(
        update={
            "decisions": [decision],
            "selected_clip_ids": [decision.candidate_id],
            "rejected_clip_ids": [],
            "production_order": [decision.candidate_id],
            "warnings": [],
            "limitations": [],
        }
    )
    understanding = understanding.model_copy(update={"warnings": [], "limitations": []})
    signals.update(
        {
            "whole_video_understanding": understanding.model_dump(mode="json"),
            "candidate_clip_discovery": discovery.model_dump(mode="json"),
            "clip_ranking": ranking.model_dump(mode="json"),
            "editorial_decisions": decisions.model_dump(mode="json"),
        }
    )
    return BobaExplanationEngine().explain_from_signals(
        "proj_explanation_clean",
        signals,
        whole_video_understanding=understanding,
        candidate_discovery=discovery,
        clip_ranking=ranking,
        editorial_decisions=decisions,
        creative_briefs=briefs,
        memory={"source_summary": "Bounded advisory preference."},
    )


def test_explanation_set_contract_serializes() -> None:
    result = _result()
    payload = json.loads(result.model_dump_json())
    assert payload["schema_version"] == "boba_explanation_engine_v1"
    assert BobaExplanationSetV1.model_validate(payload) == result


def test_clip_explanation_contract_serializes() -> None:
    clip = _all_explanations(_result())[0]
    assert BobaClipExplanationV1.model_validate(clip.model_dump(mode="json")) == clip


def test_evidence_contract_serializes() -> None:
    clip = _all_explanations(_result())[0]
    assert BobaExplanationEvidenceV1.model_validate(
        clip.evidence[0].model_dump(mode="json")
    ) == clip.evidence[0]


def test_project_explanation_contract_serializes() -> None:
    result = _result()
    assert BobaProjectExplanationV1.model_validate(
        result.project_summary.model_dump(mode="json")
    ) == result.project_summary


def test_signal_explanation_contract_serializes() -> None:
    result = _result()
    assert BobaSignalExplanationV1.model_validate(
        result.signal_explanation.model_dump(mode="json")
    ) == result.signal_explanation


def test_uncertainty_summary_contract_serializes() -> None:
    result = _result()
    assert BobaUncertaintySummaryV1.model_validate(
        result.uncertainty_summary.model_dump(mode="json")
    ) == result.uncertainty_summary


def test_discovery_explanation_uses_saved_discovery_reason() -> None:
    result = _result()
    explanation = result.candidate_explanations[0]
    assert "Synthetic local editorial-decision evidence" in explanation.short_summary
    assert any(
        item.source_field == "candidates[].discovery_reason"
        for item in explanation.evidence
    )


def test_ranking_explanation_uses_saved_score_breakdown() -> None:
    explanation = _result().ranking_explanations[0]
    assert "92.0/100" in explanation.short_summary
    assert any(item.source_field.endswith("hook_score") for item in explanation.evidence)
    assert any(item.source_field.endswith("total_score") for item in explanation.evidence)


def test_editorial_explanation_uses_selection_and_direction() -> None:
    result = _result()
    explanation = next(
        item
        for item in result.editorial_explanations
        if item.candidate_id == "must_make_truth" and item.explanation_type == "editorial"
    )
    assert "selected" in explanation.short_summary.casefold()
    assert any("hook strategy" in reason.casefold() for reason in explanation.key_reasons)
    assert any(item.source_artifact == "editorial_decision" for item in explanation.evidence)


def test_rejected_candidate_has_explicit_explanation() -> None:
    rejections = [
        item for item in _all_explanations(_result()) if item.explanation_type == "rejection"
    ]
    assert any(item.candidate_id == "reject_fragment" for item in rejections)
    assert all(item.key_reasons for item in rejections)


def test_blocked_candidate_explains_saved_blocker() -> None:
    readiness = next(
        item
        for item in _result().editorial_explanations
        if item.candidate_id == "rights_risk" and item.explanation_type == "render_readiness"
    )
    assert "blocked" in readiness.short_summary.casefold()
    assert any("rights" in reason.casefold() for reason in readiness.key_reasons)


def test_render_readiness_is_separate_from_editorial_selection() -> None:
    result = _result()
    candidate_items = [
        item for item in result.editorial_explanations if item.candidate_id == "must_make_truth"
    ]
    assert {item.explanation_type for item in candidate_items} == {
        "editorial",
        "render_readiness",
    }
    assert any("not proof" in item.detailed_explanation.casefold() for item in candidate_items)


def test_missing_artifacts_become_limitations_instead_of_claims() -> None:
    result = BobaExplanationEngine().explain(project_id="proj_missing")
    assert not result.candidate_explanations
    assert not result.ranking_explanations
    assert any("unavailable" in item.casefold() for item in result.limitations)
    assert result.uncertainty_summary.uncertainty_level == "high"


def test_unavailable_analysis_signals_are_reported() -> None:
    result = BobaExplanationEngine().explain(
        project_id="proj_missing_signals",
        analysis_signal_health={
            "transcript_available": False,
            "face_signals_available": False,
            "speaker_signals_available": False,
            "visual_signals_available": False,
        },
    )
    assert "transcript" in result.signal_explanation.signals_missing
    assert "face_signals" in result.signal_explanation.signals_missing
    assert result.project_summary.unavailable_signals


def test_uncertainty_rises_when_core_evidence_is_missing() -> None:
    levels = {"low": 0, "medium": 1, "high": 2}
    supported = _clean_supported_result()
    missing = BobaExplanationEngine().explain(project_id="proj_uncertain")
    assert levels[missing.uncertainty_summary.uncertainty_level] > levels[
        supported.uncertainty_summary.uncertainty_level
    ]


def test_all_evidence_snippets_are_bounded() -> None:
    evidence = [
        item
        for explanation in _all_explanations(_result())
        for item in explanation.evidence
    ]
    assert evidence
    assert all(0 < len(item.snippet) <= 300 for item in evidence)


def test_explanations_do_not_store_full_transcript() -> None:
    result = _result()
    encoded = result.model_dump_json()
    full_transcript = (
        "The hidden problem is why this system kept failing. "
        "Every vague handoff created another avoidable decision. "
        "One explicit rule removed those repeated choices. "
        "The payoff is a system the team can finally trust."
    )
    assert "transcript_segments" not in encoded
    assert full_transcript.casefold() not in encoded.casefold()


def test_project_summary_names_top_recommendation_and_human_review() -> None:
    summary = _result().project_summary
    assert summary.overall_summary
    assert "must make truth" in summary.top_recommendation_reason.casefold()
    assert summary.human_review_notes


def test_explanation_persistence_round_trips_json(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_explanations(_result())
    payload = json.loads(store.explanation_path(PROJECT_ID).read_text())
    assert store.load_explanations(PROJECT_ID) == result
    assert payload["schema_version"] == "boba_explanation_engine_v1"
    assert "transcript_segments" not in payload


def test_integration_surfaces_saved_explanation_artifact(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_explanations(_result())
    signals = asyncio.run(BobaIntegration(storage, store).collect_project_signals(PROJECT_ID))
    assert signals["explanations_available"] is True
    assert signals["explanations"]["schema_version"] == "boba_explanation_engine_v1"


def test_api_routes_create_and_return_saved_explanations(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    understanding, discovery, ranking, decisions, briefs, _signals = (
        build_synthetic_explanation_inputs(PROJECT_ID)
    )
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_whole_video_understanding(understanding)
    store.save_candidate_clip_discovery(discovery)
    store.save_clip_ranking(ranking)
    store.save_editorial_decisions(decisions)
    for brief in briefs:
        store.save_creative_brief(brief)
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(f"/api/v1/boba/projects/{PROJECT_ID}/explanations")
        saved = client.get(f"/api/v1/boba/projects/{PROJECT_ID}/explanations")
    assert created.status_code == 200
    assert saved.status_code == 200
    assert created.json()["project_summary"] == saved.json()["project_summary"]


def test_frontend_contract_and_panel_are_present() -> None:
    types = (ROOT / "frontend" / "src" / "lib" / "types.ts").read_text(encoding="utf-8")
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "interface BobaExplanationSetV1" in types
    assert "BOBA Explanation Engine" in panel
    assert "Evidence and source fields" in panel
    assert "no rendered proof or audience-performance prediction" in panel


def test_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_explanation_engine.py"),
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
            str(ROOT / "tools" / "validate_boba_explanation_engine.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"evidence_bounded": true' in result.stdout.casefold()
    assert '"rendering_triggered": false' in result.stdout.casefold()


def test_explanation_generation_does_not_trigger_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert _result().candidate_explanations


def test_explanation_generation_makes_no_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    assert _result().signal_explanation.signals_used


def test_reports_and_media_are_not_staged() -> None:
    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_explanation_engine"
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


def test_explanation_json_does_not_leak_local_paths_or_claim_rendering() -> None:
    encoded = _result().model_dump_json()
    assert "D:\\" not in encoded
    assert "media_path" not in encoded
    assert "rendered successfully" not in encoded.casefold()
    assert "does not inspect or render media" in encoded.casefold()
