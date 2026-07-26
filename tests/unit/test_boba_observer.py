"""BOBA Observer V1 contracts, local observations, API, and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_observer import (
    build_synthetic_observer_report,
    build_synthetic_observer_state,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaArtifactObservationV1,
    BobaDependencyObservationV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaModuleHealthObservationV1,
    BobaNextActionRecommendationV1,
    BobaObserverFindingV1,
    BobaObserverSetV1,
    BobaObserverSignalUsageV1,
    BobaObserverSummaryV1,
    BobaObserverV1,
    BobaProjectMemoryV1,
    BobaSafetyObservationV1,
    BobaValidationObservationV1,
    BobaWorkflowObservationV1,
    build_boba_artifact_registry,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_observer_test"


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaObserverSetV1:
    return build_synthetic_observer_report(project_id)


def _artifact(
    report: BobaObserverSetV1,
    artifact_id: str,
) -> BobaArtifactObservationV1:
    return next(
        item
        for item in report.artifact_observations
        if item.artifact_id == artifact_id
    )


def _module(
    report: BobaObserverSetV1,
    module_name: str,
) -> BobaModuleHealthObservationV1:
    return next(
        item
        for item in report.module_health_observations
        if item.module_name == module_name
    )


def _safety(
    report: BobaObserverSetV1,
    safety_area: str,
) -> BobaSafetyObservationV1:
    return next(
        item
        for item in report.safety_observations
        if item.safety_area == safety_area
    )


def _observe(
    tmp_path: Path,
    *,
    project_id: str = PROJECT_ID,
    rights_status: str = "blocked",
) -> tuple[BobaObserverSetV1, Path, Path]:
    store_root, validation_root, observed_at = build_synthetic_observer_state(
        tmp_path,
        project_id=project_id,
        rights_status=rights_status,
    )
    report = BobaObserverV1(
        store_root,
        validation_report_root=validation_root,
    ).analyze(
        project_id,
        source_id="synthetic_test_state",
        observed_at=observed_at,
    )
    return report, store_root, validation_root


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Observer V1 Test",
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


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def test_01_observer_set_contract_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_observer_v1"
    assert BobaObserverSetV1.model_validate(payload) == _result()


def test_02_artifact_observation_contract_serializes() -> None:
    value = _artifact(_result(), "whole_video")
    assert BobaArtifactObservationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_03_module_health_observation_contract_serializes() -> None:
    value = _module(_result(), "whole_video")
    assert BobaModuleHealthObservationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_04_workflow_observation_contract_serializes() -> None:
    value = _result().workflow_observations[0]
    assert BobaWorkflowObservationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_05_dependency_observation_contract_serializes() -> None:
    value = _result().dependency_observations[0]
    assert BobaDependencyObservationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_06_validation_observation_contract_serializes() -> None:
    value = _result().validation_observations[0]
    assert BobaValidationObservationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_07_safety_observation_contract_serializes() -> None:
    value = _result().safety_observations[0]
    assert BobaSafetyObservationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_08_next_action_recommendation_contract_serializes() -> None:
    value = _result().next_action_recommendations[0]
    assert BobaNextActionRecommendationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_09_finding_contract_serializes() -> None:
    value = next(
        finding
        for artifact in _result().artifact_observations
        for finding in artifact.findings
    )
    assert BobaObserverFindingV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_10_summary_contract_serializes() -> None:
    value = _result().observer_summary
    assert BobaObserverSummaryV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_11_signal_usage_contract_serializes() -> None:
    value = _result().signal_usage
    assert BobaObserverSignalUsageV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_12_artifact_registry_includes_all_current_boba_modules() -> None:
    registry = build_boba_artifact_registry()
    assert len(registry) == 19
    assert {item.artifact_id for item in registry} == {
        "whole_video",
        "candidate_clip_discovery",
        "clip_ranking",
        "editorial_decision",
        "explanation",
        "creative_direction_v2",
        "clip_briefs",
        "hook_retention",
        "caption_motion",
        "music_mood",
        "creator_learning",
        "approval_rejection_learning",
        "experimentation",
        "performance_feedback",
        "content_scout_v2",
        "research_brain",
        "trend_topic_watcher",
        "candidate_video_scorer",
        "rights_permission_gate",
    }


def test_13_existing_artifact_is_marked_readable() -> None:
    artifact = _artifact(_result(), "whole_video")
    assert artifact.exists is True
    assert artifact.readable is True
    assert artifact.freshness_status == "fresh"


def test_14_missing_artifact_is_detected() -> None:
    artifact = _artifact(_result(), "candidate_clip_discovery")
    assert artifact.exists is False
    assert artifact.freshness_status == "missing"
    assert any(
        finding.category == "missing_artifact"
        for finding in artifact.findings
    )


def test_15_corrupt_json_becomes_finding_without_crash() -> None:
    artifact = _artifact(_result(), "explanation")
    assert artifact.exists is True
    assert artifact.readable is False
    assert artifact.issue_level == "blocker"
    assert any(
        finding.category == "unreadable_artifact"
        for finding in artifact.findings
    )


def test_16_downstream_older_than_upstream_becomes_stale_warning() -> None:
    artifact = _artifact(_result(), "caption_motion")
    dependency = next(
        item
        for item in _result().dependency_observations
        if item.downstream_artifact == "caption_motion"
        and item.upstream_artifact == "hook_retention"
    )
    assert dependency.status == "stale"
    assert artifact.freshness_status == "stale"
    assert artifact.issue_level == "warning"


def test_17_downstream_without_upstream_creates_broken_dependency() -> None:
    dependency = next(
        item
        for item in _result().dependency_observations
        if item.downstream_artifact == "clip_ranking"
        and item.upstream_artifact == "candidate_clip_discovery"
    )
    assert dependency.status == "broken"
    assert dependency.issue_level == "blocker"


def test_18_missing_downstream_with_upstream_is_incomplete() -> None:
    dependency = next(
        item
        for item in _result().dependency_observations
        if item.downstream_artifact == "candidate_clip_discovery"
        and item.upstream_artifact == "whole_video"
    )
    module = _module(_result(), "candidate_clip_discovery")
    assert dependency.status == "missing"
    assert module.health_status == "partial"
    assert module.missing_inputs == []
    assert module.missing_outputs == ["candidate_clip_discovery"]


def test_19_missing_validation_report_creates_gap() -> None:
    value = next(
        item
        for item in _result().validation_observations
        if item.validator_name == "BOBA Candidate Clip Discovery"
    )
    assert value.report_exists is False
    assert value.latest_status == "missing"
    assert value.missing_reason


def test_20_stale_validation_report_creates_warning() -> None:
    value = next(
        item
        for item in _result().validation_observations
        if item.validator_name == "BOBA Clip Ranking"
    )
    assert value.latest_status == "passed"
    assert value.freshness_status == "stale"
    assert value.issue_level == "warning"


def test_21_unknown_report_format_becomes_unknown_status() -> None:
    value = next(
        item
        for item in _result().validation_observations
        if item.validator_name == "BOBA Editorial Decision"
    )
    assert value.report_exists is True
    assert value.latest_status == "unknown"
    assert value.issue_level == "unknown"


def test_22_unknown_rights_status_creates_unsafe_ingestion_warning(
    tmp_path: Path,
) -> None:
    report, _, _ = _observe(tmp_path, rights_status="unknown")
    assert _safety(report, "rights_permission").status == "needs_human_review"
    assert _safety(report, "ingestion").status == "blocked"


def test_23_blocked_rights_status_creates_blocked_safety_observation() -> None:
    assert _safety(_result(), "rights_permission").status == "blocked"
    assert _safety(_result(), "ingestion").status == "blocked"


def test_24_ready_for_human_review_still_requires_human_review(
    tmp_path: Path,
) -> None:
    report, _, _ = _observe(
        tmp_path,
        rights_status="ready_for_human_review",
    )
    assert _safety(report, "rights_permission").status == "safe_to_review"
    ingestion = _safety(report, "ingestion")
    assert ingestion.status == "needs_human_review"
    assert ingestion.required_human_checks


def test_25_next_actions_never_recommend_automatic_code_edit() -> None:
    safe_actions = [
        item.action.casefold()
        for item in _result().next_action_recommendations
        if item.safe
    ]
    assert all("edit code" not in action for action in safe_actions)
    assert all("modify code" not in action for action in safe_actions)
    assert all("automatic repair" not in action for action in safe_actions)


def test_26_next_actions_never_recommend_bypassing_rights_gate() -> None:
    actions = " ".join(
        item.action for item in _result().next_action_recommendations
    ).casefold()
    assert "bypass" not in actions
    assert any(
        item.action_type == "do_not_process" and not item.safe
        for item in _result().next_action_recommendations
    )


def test_27_observer_does_not_mutate_existing_artifacts(
    tmp_path: Path,
) -> None:
    store_root, validation_root, observed_at = build_synthetic_observer_state(
        tmp_path,
        project_id=PROJECT_ID,
    )
    paths = sorted(
        path
        for path in store_root.rglob("*")
        if path.is_file()
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    }
    BobaObserverV1(
        store_root,
        validation_report_root=validation_root,
    ).analyze(PROJECT_ID, observed_at=observed_at)
    after = {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    }
    assert after == before


def test_28_observer_export_excludes_private_paths_and_raw_dumps(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_observer_report(_result())
    payload = store.export_observer_report(PROJECT_ID)
    observer = payload["observer"]
    assert not _contains_key(observer, "expected_path")
    assert not _contains_key(observer, "report_path")
    assert not _contains_key(observer, "evidence")
    assert payload["privacy"]["private_paths_excluded"] is True
    assert payload["privacy"]["raw_artifact_content_excluded"] is True
    assert payload["privacy"]["full_transcripts_excluded"] is True
    assert payload["privacy"]["credentials_excluded"] is True
    encoded = json.dumps(payload).casefold()
    for forbidden in (
        '"api_key":',
        '"access_token":',
        '"password":',
        '"raw_media":',
        '"full_transcript":',
        ".mp4",
        ".wav",
    ):
        assert forbidden not in encoded


def test_29_reset_removes_only_observer_artifact(tmp_path: Path) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated project memory survives Observer reset.",
        )
    )
    store.save_observer_report(_result())
    assert store.reset_observer_report(PROJECT_ID) is True
    assert store.load_observer_report(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_30_missing_optional_artifacts_degrade_gracefully() -> None:
    module = _module(_result(), "candidate_video_scorer")
    assert "research_brain" in module.optional_dependencies
    assert module.health_status == "partial"
    assert "research_brain" not in module.missing_inputs
    assert any("optional" in warning.casefold() for warning in module.warnings)


def test_31_artifact_persistence_writes_json_safe_output(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_observer_report(_result())
    path = store.observer_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/observer/index.json"
    )
    assert payload["schema_version"] == "boba_observer_v1"
    assert store.load_observer_report(PROJECT_ID) == saved


def test_32_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_observer_report(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/observer"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_observer_v1"


def test_33_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_observer_report(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/observer/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "boba_observer_export_v1"
    assert payload["privacy"]["external_api_used"] is False
    assert payload["privacy"]["validator_execution_used"] is False
    assert not _contains_key(payload["observer"], "expected_path")
    assert not _contains_key(payload["observer"], "report_path")


def test_34_api_delete_resets_project_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_observer_report(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated project memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/observer"
        )
    assert response.status_code == 200, response.text
    assert response.json()["observer_removed"] is True
    assert response.json()["other_boba_artifacts_removed"] is False
    assert response.json()["validators_executed"] is False
    assert response.json()["rendering_triggered"] is False
    assert store.load_observer_report(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_35_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.registry_builds is True
    assert report.validators_executed is False


def test_36_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.broken_dependency_detected is True
    assert report.unsafe_ingestion_detected is True


def test_37_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_38_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_39_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_40_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_41_command_execution_used_remains_false() -> None:
    assert _result().signal_usage.command_execution_used is False


def test_42_code_modification_used_remains_false() -> None:
    assert _result().signal_usage.code_modification_used is False


def test_43_destructive_action_used_remains_false() -> None:
    assert _result().signal_usage.destructive_action_used is False


def test_44_no_rendering_is_triggered(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Observer V1 must not render or execute commands.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    report, _, _ = _observe(tmp_path)
    assert _safety(report, "rendering").unsafe_next_actions


def test_45_no_downloading_is_triggered(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Observer V1 must not download media.")

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    report, _, _ = _observe(tmp_path)
    assert report.signal_usage.downloading_used is False


def test_46_no_url_fetching_is_triggered(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail_url_fetch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Observer V1 must not fetch URLs.")

    monkeypatch.setattr(urllib.request, "urlopen", fail_url_fetch)
    report, _, _ = _observe(tmp_path)
    assert report.signal_usage.url_fetching_used is False


def test_47_no_external_calls_are_made(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Observer V1 must not use the network.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    report, _, _ = _observe(tmp_path)
    assert report.signal_usage.external_api_used is False


def test_48_no_code_edits_are_made(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    store_root, validation_root, observed_at = build_synthetic_observer_state(
        tmp_path,
        project_id=PROJECT_ID,
    )

    def fail_write_text(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Observer V1 must not edit files.")

    monkeypatch.setattr(Path, "write_text", fail_write_text)
    report = BobaObserverV1(
        store_root,
        validation_report_root=validation_root,
    ).analyze(PROJECT_ID, observed_at=observed_at)
    assert report.signal_usage.code_modification_used is False


def test_49_no_destructive_actions_are_made(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    store_root, validation_root, observed_at = build_synthetic_observer_state(
        tmp_path,
        project_id=PROJECT_ID,
    )

    def fail_unlink(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Observer V1 must not delete files.")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    report = BobaObserverV1(
        store_root,
        validation_report_root=validation_root,
    ).analyze(PROJECT_ID, observed_at=observed_at)
    assert report.signal_usage.destructive_action_used is False


def test_50_no_reports_or_media_are_staged() -> None:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    staged = {
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip()
    }
    forbidden_prefixes = {
        ".venv/",
        "media/",
        "storage_data/",
        "work/",
        "frontend/.next/",
        "frontend/node_modules/",
        "node_modules/",
    }
    forbidden_suffixes = {
        ".mp4",
        ".mov",
        ".wav",
        ".webm",
        ".env",
    }
    assert not any(
        any(path.startswith(prefix) for prefix in forbidden_prefixes)
        or any(path.casefold().endswith(suffix) for suffix in forbidden_suffixes)
        for path in staged
    )
