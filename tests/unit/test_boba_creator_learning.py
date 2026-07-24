"""BOBA Creator Learning Loop V1 contracts, behavior, and safety tests."""

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
from tools.validate_boba_creator_learning import (
    build_synthetic_creator_learning,
    build_synthetic_creator_learning_artifacts,
    build_synthetic_creator_learning_events,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaCreatorFeedbackEventV1,
    BobaCreatorLearningLoopV1,
    BobaCreatorLearningProfileV1,
    BobaCreatorLearningSetV1,
    BobaCreatorLearningSignalUsageV1,
    BobaExtractedPreferenceV1,
    BobaIntegration,
    BobaLearningAuditSummaryV1,
    BobaLearningInsightV1,
    BobaMemoryRecordV1,
    BobaMemoryStore,
    BobaProjectMemoryV1,
    BobaRecommendationGuidanceV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_creator_learning_test"


@lru_cache(maxsize=8)
def _result(project_id: str = PROJECT_ID) -> BobaCreatorLearningSetV1:
    return build_synthetic_creator_learning(project_id)


def _artifacts() -> dict[str, dict[str, Any]]:
    return build_synthetic_creator_learning_artifacts()


def _events(
    project_id: str = PROJECT_ID,
) -> list[BobaCreatorFeedbackEventV1]:
    return build_synthetic_creator_learning_events(project_id, _artifacts())


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Creator Learning Test",
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


def _approval_event(
    project_id: str = PROJECT_ID,
    *,
    event_id: str = "creator_feedback_approval",
) -> BobaCreatorFeedbackEventV1:
    return BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=project_id,
        event_type="approval",
        target_type="ranked_clip",
        target_id="ranked_curiosity",
        user_action="approved",
        artifacts=_artifacts(),
        event_id=event_id,
        created_at="2026-01-01T00:00:00+00:00",
    )


def _analyze(
    events: list[BobaCreatorFeedbackEventV1],
    project_id: str = PROJECT_ID,
    *,
    include_artifacts: bool = True,
) -> BobaCreatorLearningSetV1:
    artifacts = _artifacts() if include_artifacts else {}
    return BobaCreatorLearningLoopV1().analyze(
        project_id,
        events,
        creator_id="creator_test",
        clip_ranking=artifacts.get("clip_ranking"),
        editorial_decision=artifacts.get("editorial_decision"),
        explanation=artifacts.get("explanation"),
        creative_direction=artifacts.get("creative_direction"),
        clip_briefs=artifacts.get("clip_briefs"),
        hook_retention=artifacts.get("hook_retention"),
        caption_motion=artifacts.get("caption_motion"),
        music_mood=artifacts.get("music_mood"),
    )


def test_01_learning_set_contract_serializes() -> None:
    result = _result()
    assert BobaCreatorLearningSetV1.model_validate_json(
        result.model_dump_json()
    ) == result
    assert result.schema_version == "boba_creator_learning_loop_v1"


def test_02_feedback_event_contract_serializes() -> None:
    event = _events()[0]
    assert BobaCreatorFeedbackEventV1.model_validate(event.model_dump()) == event


def test_03_extracted_preference_contract_serializes() -> None:
    preference = _events()[0].extracted_preferences[0]
    assert BobaExtractedPreferenceV1.model_validate(
        preference.model_dump()
    ) == preference


def test_04_creator_profile_contract_serializes() -> None:
    profile = _result().learning_profile
    assert BobaCreatorLearningProfileV1.model_validate(
        profile.model_dump()
    ) == profile


def test_05_learning_insight_contract_serializes() -> None:
    insight = _result().learning_insights[0]
    assert BobaLearningInsightV1.model_validate(insight.model_dump()) == insight


def test_06_recommendation_guidance_contract_serializes() -> None:
    guidance = _result().recommendation_guidance
    assert BobaRecommendationGuidanceV1.model_validate(
        guidance.model_dump()
    ) == guidance


def test_07_audit_summary_contract_serializes() -> None:
    audit = _result().audit_summary
    assert BobaLearningAuditSummaryV1.model_validate(audit.model_dump()) == audit


def test_08_signal_usage_contract_serializes() -> None:
    usage = _result().signal_usage
    assert BobaCreatorLearningSignalUsageV1.model_validate(
        usage.model_dump()
    ) == usage


def test_09_approval_event_extracts_positive_preference() -> None:
    event = _approval_event()
    assert event.extracted_preferences
    assert all(item.polarity == "prefer" for item in event.extracted_preferences)
    assert any(item.category == "hook_style" for item in event.extracted_preferences)


def test_10_rejection_event_extracts_avoid_preference() -> None:
    event = BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type="rejection",
        target_type="hook_alternative",
        target_id="hook_alt_slow",
        user_action="rejected",
        artifacts=_artifacts(),
    )
    assert any(
        item.preference == "slow_start" and item.polarity == "avoid"
        for item in event.extracted_preferences
    )


def test_11_rating_event_affects_preference_strength() -> None:
    engine = BobaCreatorLearningLoopV1()
    common: dict[str, Any] = {
        "project_id": PROJECT_ID,
        "event_type": "rating",
        "target_type": "caption_motion",
        "target_id": "caption_clean",
        "user_action": "liked",
        "artifacts": _artifacts(),
    }
    four = engine.create_feedback_event(rating=4, **common)
    five = engine.create_feedback_event(rating=5, **common)
    assert max(item.strength for item in five.extracted_preferences) > max(
        item.strength for item in four.extracted_preferences
    )


def test_12_chosen_hook_alternative_extracts_hook_preference() -> None:
    event = BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type="chosen_alternative",
        target_type="hook_alternative",
        target_id="hook_alt_bold",
        user_action="chose",
        artifacts=_artifacts(),
    )
    assert any(
        item.category == "hook_style"
        and item.preference == "bold_curiosity_gap"
        and item.polarity == "prefer"
        for item in event.extracted_preferences
    )


def test_13_chosen_caption_motion_extracts_caption_and_motion_preferences() -> None:
    event = BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type="chosen_alternative",
        target_type="caption_motion",
        target_id="caption_clean",
        user_action="chose",
        artifacts=_artifacts(),
    )
    categories = {item.category for item in event.extracted_preferences}
    assert {"caption_style", "motion_style"} <= categories


def test_14_chosen_music_mood_extracts_mood_preference() -> None:
    event = BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type="chosen_alternative",
        target_type="music_mood",
        target_id="mood_emotional",
        user_action="chose",
        artifacts=_artifacts(),
    )
    assert any(
        item.category == "music_mood"
        and item.preference == "emotional_cinematic"
        for item in event.extracted_preferences
    )


def test_15_manual_note_extracts_conservative_preference() -> None:
    event = BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type="preference_note",
        target_type="project",
        target_id=PROJECT_ID,
        user_action="noted",
        note="There is too much zoom and the captions were too busy.",
    )
    preferences = {
        (item.category, item.preference, item.polarity)
        for item in event.extracted_preferences
    }
    assert ("motion_style", "high_motion_intensity", "avoid") in preferences
    assert ("caption_style", "high_caption_density", "avoid") in preferences


def test_16_single_event_creates_low_confidence() -> None:
    assert _analyze([_approval_event()]).learning_profile.confidence < 0.5


def test_17_repeated_event_increases_confidence() -> None:
    single = _analyze([_approval_event()])
    repeated = _analyze(
        [
            _approval_event(),
            _approval_event(event_id="creator_feedback_approval_repeat"),
        ]
    )
    assert repeated.learning_profile.confidence > single.learning_profile.confidence
    assert repeated.learning_profile.repeated_feedback


def test_18_contradictory_events_reduce_confidence() -> None:
    positive = [
        _approval_event(),
        _approval_event(event_id="creator_feedback_approval_repeat"),
    ]
    repeated = _analyze(positive)
    rejection = BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type="rejection",
        target_type="ranked_clip",
        target_id="ranked_curiosity",
        user_action="rejected",
        artifacts=_artifacts(),
        event_id="creator_feedback_rejection_conflict",
    )
    contradictory = _analyze([*positive, rejection])
    assert contradictory.learning_profile.confidence < repeated.learning_profile.confidence
    assert contradictory.learning_profile.warnings


def test_19_guidance_apply_automatically_defaults_false() -> None:
    assert _result().recommendation_guidance.apply_automatically is False
    assert BobaRecommendationGuidanceV1().apply_automatically is False


def test_20_dry_run_does_not_persist_memory_writes(tmp_path: Path) -> None:
    integration, store = _integration(tmp_path)
    store.record_creator_feedback_event(_approval_event())
    result = asyncio.run(
        integration.generate_creator_learning_profile(
            PROJECT_ID,
            creator_id="creator_test",
            dry_run=True,
        )
    )
    assert "Dry run" in " ".join(result.warnings)
    assert store.load_creator_learning(PROJECT_ID) is None
    assert store.load_creator_memory("creator_test") is None


def test_21_export_excludes_raw_media_secrets_and_full_transcripts(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    for event in _events():
        store.record_creator_feedback_event(event)
    store.save_creator_learning(_result())
    encoded = json.dumps(store.export_creator_learning_profile(PROJECT_ID)).casefold()
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


def test_22_reset_removes_project_learning_only(tmp_path: Path) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    store.save_creator_learning(_result())
    store.record_creator_feedback_event(_approval_event())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    assert store.reset_creator_learning_profile(PROJECT_ID) is True
    assert store.load_creator_learning(PROJECT_ID) is None
    assert store.list_creator_feedback_events(PROJECT_ID) == []
    assert store.load_project_memory(PROJECT_ID) is not None


def test_23_memory_integration_does_not_break_existing_memory_schema(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    record = store.save_record(
        BobaMemoryRecordV1(
            scope="project",
            record_type="creator_preference",
            source="explicit_test_feedback",
            project_id=PROJECT_ID,
            summary="Creator prefers a clean hook.",
            applies_to=["ranking"],
        )
    )
    store.save_creator_learning(_result())
    assert store.get_record(record.memory_id) == record
    exported = store.export_memory("project", PROJECT_ID)
    assert exported["schema_version"] == "boba_memory_export_v1"


def test_24_missing_feedback_creates_clear_limitation() -> None:
    result = _analyze([])
    assert result.learning_profile.data_points == 0
    assert result.learning_profile.confidence == 0.0
    assert any("No explicit" in item for item in result.warnings)
    assert result.limitations


def test_25_missing_optional_artifacts_degrade_gracefully() -> None:
    event = BobaCreatorLearningLoopV1().create_feedback_event(
        project_id=PROJECT_ID,
        event_type="preference_note",
        target_type="project",
        target_id=PROJECT_ID,
        user_action="noted",
        note="The pacing was too slow.",
    )
    result = _analyze([event], include_artifacts=False)
    assert result.learning_profile.pacing_preferences
    assert result.signal_usage.fallback_used is True
    assert "clip_ranking" in result.signal_usage.unavailable_signals


def test_26_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_creator_learning(_result())
    path = store.creator_learning_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/creator_learning/index.json"
    )
    assert payload["schema_version"] == "boba_creator_learning_loop_v1"
    assert store.load_creator_learning(PROJECT_ID) == saved


def test_27_events_log_is_append_safe(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    first = _approval_event(event_id="creator_feedback_append_one")
    second = _approval_event(event_id="creator_feedback_append_two")
    store.record_creator_feedback_event(first)
    store.record_creator_feedback_event(second)
    store.record_creator_feedback_event(second)
    lines = store.creator_learning_events_path(PROJECT_ID).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in lines)
    assert store.list_creator_feedback_events(PROJECT_ID) == [first, second]


def test_28_api_event_route_records_explicit_feedback(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/creator-learning/events",
            json={
                "event_type": "preference_note",
                "target_type": "project",
                "target_id": PROJECT_ID,
                "user_action": "noted",
                "note": "There is too much zoom.",
                "tags": [],
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["extracted_preferences"]
    assert len(store.list_creator_feedback_events(PROJECT_ID)) == 1


def test_29_api_get_returns_saved_learning_artifact_and_frontend_exposes_it(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_creator_learning(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/creator-learning"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_creator_learning_loop_v1"
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "Creator Learning Loop" in panel
    assert "BOBA learns only from feedback you submit." in panel
    assert "Update learning profile" in panel


def test_30_api_export_returns_safe_profile(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    for event in _events():
        store.record_creator_feedback_event(event)
    store.save_creator_learning(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/creator-learning/export"
        )
    assert response.status_code == 200, response.text
    encoded = response.text.casefold()
    assert "raw_media" not in encoded
    assert "full_transcript" not in encoded
    assert "api_key" not in encoded


def test_31_api_delete_resets_project_learning_only(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_creator_learning(_result())
    store.record_creator_feedback_event(_approval_event())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Preserved unrelated memory.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/creator-learning"
        )
    assert response.status_code == 200, response.text
    assert response.json()["unrelated_memory_removed"] is False
    assert store.load_creator_learning(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_32_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.external_calls_made is False
    assert report.rendering_triggered is False


def test_33_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.feedback_events_recorded >= 7
    assert report.preferences_extracted > 0


def test_34_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Creator learning must not invoke a renderer.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    result = build_synthetic_creator_learning("proj_no_rendering")
    assert result.audit_summary.total_events > 0


def test_35_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Creator learning must not make network calls.")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    result = build_synthetic_creator_learning("proj_no_network")
    assert result.signal_usage.feedback_events_used > 0


def test_36_no_reports_or_media_are_staged() -> None:
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
