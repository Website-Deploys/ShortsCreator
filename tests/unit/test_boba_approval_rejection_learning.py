"""BOBA Approval / Rejection Learning V1 behavior and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_approval_rejection_learning import (
    build_synthetic_approval_rejection_artifacts,
    build_synthetic_approval_rejection_events,
    build_synthetic_approval_rejection_learning,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaApprovalLearningCaseV1,
    BobaApprovalRejectionAuditSummaryV1,
    BobaApprovalRejectionLearningSetV1,
    BobaApprovalRejectionLearningV1,
    BobaApprovalRejectionModuleGuidanceV1,
    BobaApprovalRejectionPatternScoreV1,
    BobaApprovalRejectionSignalUsageV1,
    BobaCorrectionMappingV1,
    BobaCreatorFeedbackEventV1,
    BobaCreatorLearningLoopV1,
    BobaDecisionAttributionV1,
    BobaFeedbackFactorV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaProjectMemoryV1,
    BobaRejectionLearningCaseV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_approval_rejection_test"


@lru_cache(maxsize=8)
def _result(
    project_id: str = PROJECT_ID,
) -> BobaApprovalRejectionLearningSetV1:
    return build_synthetic_approval_rejection_learning(project_id)


def _artifacts() -> dict[str, dict[str, Any]]:
    return build_synthetic_approval_rejection_artifacts()


def _events(
    project_id: str = PROJECT_ID,
) -> list[BobaCreatorFeedbackEventV1]:
    return build_synthetic_approval_rejection_events(project_id, _artifacts())


def _event(
    *,
    note: str,
    event_type: str = "rejection",
    target_type: str = "project",
    target_id: str = PROJECT_ID,
    user_action: str = "rejected",
    event_id: str = "creator_feedback_targeted",
) -> BobaCreatorFeedbackEventV1:
    return BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type=event_type,  # type: ignore[arg-type]
        target_type=target_type,  # type: ignore[arg-type]
        target_id=target_id,
        user_action=user_action,  # type: ignore[arg-type]
        note=note,
        artifacts=_artifacts(),
        event_id=event_id,
    )


def _analyze(
    events: list[BobaCreatorFeedbackEventV1],
    *,
    include_artifacts: bool = True,
) -> BobaApprovalRejectionLearningSetV1:
    artifacts = _artifacts() if include_artifacts else {}
    return BobaApprovalRejectionLearningV1().analyze(
        PROJECT_ID,
        events,
        source_id=PROJECT_ID,
        creator_learning={"explicit_feedback_only": True},
        boba_memory={"explicit_feedback_only": True},
        clip_ranking=artifacts.get("clip_ranking"),
        editorial_decision=artifacts.get("editorial_decision"),
        explanation=artifacts.get("explanation"),
        creative_direction=artifacts.get("creative_direction"),
        clip_briefs=artifacts.get("clip_briefs"),
        hook_retention=artifacts.get("hook_retention"),
        caption_motion=artifacts.get("caption_motion"),
        music_mood=artifacts.get("music_mood"),
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Approval Rejection Test",
        source_filename="synthetic-source.mp4",
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


def _integration(
    tmp_path: Path,
    project_id: str = PROJECT_ID,
) -> tuple[BobaIntegration, BobaMemoryStore]:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    asyncio.run(StorageProjectRepository(storage).save(_project(project_id)))
    return BobaIntegration(storage, store), store


def _pattern(
    result: BobaApprovalRejectionLearningSetV1,
    category: str,
    text: str,
) -> BobaApprovalRejectionPatternScoreV1:
    return next(
        item
        for item in result.pattern_scores
        if item.category == category and text in item.summary.casefold()
    )


def test_01_learning_set_contract_serializes() -> None:
    result = _result()
    assert BobaApprovalRejectionLearningSetV1.model_validate_json(
        result.model_dump_json()
    ) == result


def test_02_approval_case_contract_serializes() -> None:
    case = _result().approval_cases[0]
    assert BobaApprovalLearningCaseV1.model_validate(case.model_dump()) == case


def test_03_rejection_case_contract_serializes() -> None:
    case = _result().rejection_cases[0]
    assert BobaRejectionLearningCaseV1.model_validate(case.model_dump()) == case


def test_04_feedback_factor_contract_serializes() -> None:
    factor = _result().approval_cases[0].approval_factors[0]
    assert BobaFeedbackFactorV1.model_validate(factor.model_dump()) == factor


def test_05_decision_attribution_contract_serializes() -> None:
    attribution = _result().decision_attributions[0]
    assert BobaDecisionAttributionV1.model_validate(
        attribution.model_dump()
    ) == attribution


def test_06_correction_mapping_contract_serializes() -> None:
    mapping = _result().rejection_cases[0].correction_mapping[0]
    assert BobaCorrectionMappingV1.model_validate(mapping.model_dump()) == mapping


def test_07_pattern_score_contract_serializes() -> None:
    pattern = _result().pattern_scores[0]
    assert BobaApprovalRejectionPatternScoreV1.model_validate(
        pattern.model_dump()
    ) == pattern


def test_08_module_guidance_contract_serializes() -> None:
    guidance = _result().module_guidance
    assert BobaApprovalRejectionModuleGuidanceV1.model_validate(
        guidance.model_dump()
    ) == guidance


def test_09_audit_summary_contract_serializes() -> None:
    audit = _result().audit_summary
    assert BobaApprovalRejectionAuditSummaryV1.model_validate(
        audit.model_dump()
    ) == audit


def test_10_signal_usage_contract_serializes() -> None:
    usage = _result().signal_usage
    assert BobaApprovalRejectionSignalUsageV1.model_validate(
        usage.model_dump()
    ) == usage


def test_11_approved_clip_creates_positive_factors() -> None:
    assert _result().approval_cases
    assert all(
        factor.polarity == "positive"
        for factor in _result().approval_cases[0].approval_factors
    )


def test_12_rejected_clip_creates_negative_factors() -> None:
    case = next(
        item
        for item in _result().rejection_cases
        if "Too slow" in item.rejected_reason_summary
    )
    assert any(factor.polarity == "negative" for factor in case.likely_rejection_causes)


def test_13_too_slow_maps_to_hook_retention_and_pacing() -> None:
    result = _analyze([_event(note="Too slow.")])
    case = result.rejection_cases[0]
    attribution = result.decision_attributions[0]
    assert any(factor.category == "pacing" for factor in case.likely_rejection_causes)
    assert attribution.primary_module == "hook_retention"


def test_14_too_much_zoom_maps_to_caption_motion_or_creative_director() -> None:
    result = _analyze([_event(note="Too much zoom.")])
    attribution = result.decision_attributions[0]
    assert attribution.primary_module in {"caption_motion", "creative_director"}
    assert result.rejection_cases[0].correction_mapping[0].problem_category == "motion"


def test_15_wrong_music_maps_to_music_mood() -> None:
    result = _analyze([_event(note="Wrong music.")])
    assert result.decision_attributions[0].primary_module == "music_mood"
    assert result.rejection_cases[0].correction_mapping[0].problem_category == (
        "music_mood"
    )


def test_16_no_payoff_maps_to_editorial_or_hook_retention() -> None:
    result = _analyze([_event(note="No payoff.")])
    assert result.decision_attributions[0].primary_module in {
        "editorial_decision",
        "hook_retention",
    }
    assert any(
        mapping.problem_category == "payoff"
        for mapping in result.rejection_cases[0].correction_mapping
    )


def test_17_not_interesting_maps_to_ranking_or_discovery() -> None:
    result = _analyze([_event(note="Not interesting.")])
    assert result.decision_attributions[0].primary_module in {
        "clip_ranking",
        "candidate_discovery",
    }


def test_18_ambiguous_feedback_maps_to_unknown_with_warning() -> None:
    event = _event(
        note="I am unsure about this one.",
        event_type="preference_note",
        user_action="noted",
    )
    result = _analyze([event])
    assert result.approval_cases == []
    assert result.rejection_cases == []
    assert result.decision_attributions[0].primary_module == "unknown"
    assert result.decision_attributions[0].warnings


def test_19_repeated_approval_increases_pattern_strength() -> None:
    events = _events()
    single = _analyze(events[:1])
    repeated = _analyze(events[:2])
    assert _pattern(repeated, "hook", "curiosity gap").strength > _pattern(
        single, "hook", "curiosity gap"
    ).strength


def test_20_repeated_rejection_increases_pattern_strength() -> None:
    events = _events()
    single = _analyze(events[4:5])
    repeated = _analyze(events[4:6])
    assert _pattern(repeated, "pacing", "slow opening").strength > _pattern(
        single, "pacing", "slow opening"
    ).strength


def test_21_contradiction_reduces_confidence() -> None:
    events = _events()
    repeated = _analyze(events[:2])
    contradictory = _analyze([*events[:2], events[8]])
    assert _pattern(
        contradictory, "hook", "curiosity gap"
    ).confidence < _pattern(repeated, "hook", "curiosity gap").confidence


def test_22_single_event_remains_weak_signal() -> None:
    result = _analyze(_events()[:1])
    assert all(item.pattern_type == "weak_signal" for item in result.pattern_scores)


def test_23_guidance_apply_automatically_defaults_false() -> None:
    assert _result().module_guidance.apply_automatically is False
    assert all(
        mapping.apply_automatically is False
        for case in _result().rejection_cases
        for mapping in case.correction_mapping
    )


def test_24_dry_run_does_not_persist(tmp_path: Path) -> None:
    integration, store = _integration(tmp_path)
    for event in _events():
        store.record_creator_feedback_event(event)
    result = asyncio.run(
        integration.generate_approval_rejection_learning(
            PROJECT_ID,
            dry_run=True,
        )
    )
    assert result.audit_summary.dry_run is True
    assert store.load_approval_rejection_learning(PROJECT_ID) is None
    assert len(store.list_creator_feedback_events(PROJECT_ID)) == len(_events())


def test_25_export_excludes_raw_media_secrets_and_full_transcripts(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_approval_rejection_learning(_result())
    encoded = json.dumps(
        store.export_approval_rejection_learning(PROJECT_ID)
    ).casefold()
    for forbidden in (
        "raw_media",
        "full_transcript",
        "api_key",
        "access_token",
        "password",
        ".mp4",
        ".wav",
    ):
        assert forbidden not in encoded


def test_26_reset_removes_only_approval_rejection_artifact(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    events = _events()
    for event in events:
        store.record_creator_feedback_event(event)
    artifacts = _artifacts()
    creator_learning = BobaCreatorLearningLoopV1().analyze(
        PROJECT_ID,
        events,
        clip_ranking=artifacts["clip_ranking"],
    )
    store.save_creator_learning(creator_learning)
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    store.save_approval_rejection_learning(_result())
    assert store.reset_approval_rejection_learning(PROJECT_ID) is True
    assert store.load_approval_rejection_learning(PROJECT_ID) is None
    assert store.load_creator_learning(PROJECT_ID) is not None
    assert len(store.list_creator_feedback_events(PROJECT_ID)) == len(events)
    assert store.load_project_memory(PROJECT_ID) is not None


def test_27_missing_feedback_creates_clear_limitation() -> None:
    result = _analyze([])
    assert result.audit_summary.total_feedback_events_used == 0
    assert any("No explicit" in warning for warning in result.warnings)
    assert result.limitations


def test_28_missing_optional_artifacts_degrade_gracefully() -> None:
    result = _analyze([_event(note="Too slow.")], include_artifacts=False)
    assert result.rejection_cases
    assert result.signal_usage.fallback_used is True
    assert "clip_ranking" in result.signal_usage.unavailable_signals


def test_29_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_approval_rejection_learning(_result())
    path = store.approval_rejection_learning_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/approval_rejection_learning/index.json"
    )
    assert payload["schema_version"] == "boba_approval_rejection_learning_v1"
    assert store.load_approval_rejection_learning(PROJECT_ID) == saved


def test_30_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_approval_rejection_learning(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/approval-rejection-learning"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == (
        "boba_approval_rejection_learning_v1"
    )
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "Approval / Rejection Learning" in panel
    assert (
        "BOBA learns only from feedback you submit. Guidance is advisory unless"
        in panel
    )


def test_31_api_export_returns_safe_profile(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_approval_rejection_learning(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/approval-rejection-learning/export"
        )
    assert response.status_code == 200, response.text
    assert "raw_media" not in response.text.casefold()
    assert "full_transcript" not in response.text.casefold()
    assert "api_key" not in response.text.casefold()


def test_32_api_delete_resets_project_artifact_only(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    events = _events()
    for event in events:
        store.record_creator_feedback_event(event)
    store.save_approval_rejection_learning(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/approval-rejection-learning"
        )
    assert response.status_code == 200, response.text
    assert response.json()["creator_learning_removed"] is False
    assert store.load_approval_rejection_learning(PROJECT_ID) is None
    assert len(store.list_creator_feedback_events(PROJECT_ID)) == len(events)


def test_33_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.external_calls_made is False
    assert report.rendering_triggered is False


def test_34_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.approval_cases >= 4
    assert report.rejection_cases >= 6


def test_35_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Approval/rejection learning must not invoke a renderer.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    result = build_synthetic_approval_rejection_learning("proj_no_rendering")
    assert result.audit_summary.total_feedback_events_used > 0


def test_36_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Approval/rejection learning must not use network calls.")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    result = build_synthetic_approval_rejection_learning("proj_no_network")
    assert result.signal_usage.feedback_events_used > 0


def test_37_no_reports_or_media_are_staged() -> None:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    staged = result.stdout.replace("\\", "/").casefold().splitlines()
    forbidden_prefixes = (
        "work/",
        "storage_data/",
        "media/",
        ".venv/",
        "node_modules/",
        "frontend/.next/",
    )
    forbidden_suffixes = (".mp4", ".mov", ".wav", ".mp3")
    assert result.returncode == 0
    assert not any(
        path.startswith(forbidden_prefixes) or path.endswith(forbidden_suffixes)
        for path in staged
    )
