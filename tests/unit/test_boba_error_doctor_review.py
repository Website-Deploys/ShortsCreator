"""BOBA Error Doctor Panel V1 contracts, projections, evidence, routing and API tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from tools._boba_error_doctor_review_fixtures import (
    seed_project,
    synthetic_case,
    synthetic_error_doctor_set,
)
from tools.validate_boba_error_doctor_review import (
    SCENARIO_NAMES,
    ScenarioResult,
    _full_chain,
    run_all_scenarios,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.error_doctor_review import (
    INCIDENT_QUEUE_PRIORITY_TIERS,
    MAX_ANNOTATION_LENGTH,
    MAX_COMPARISON_INCIDENTS,
    MAX_EVIDENCE_CARDS,
    MAX_EXCERPT_CHARS,
    MAX_QUEUE_PAGE_SIZE,
    MAX_TECHNICAL_MESSAGE_CHARS,
    SUPPORTED_INCIDENT_SCHEMA_ID,
    BobaDiagnosisProjectionV1,
    BobaErrorConflictV1,
    BobaErrorDoctorActionDescriptorV1,
    BobaErrorDoctorActionReceiptV1,
    BobaErrorDoctorActionRequestV1,
    BobaErrorDoctorComparisonV1,
    BobaErrorDoctorRegistrySnapshotV1,
    BobaErrorDoctorReviewEventV1,
    BobaErrorDoctorReviewNotificationV1,
    BobaErrorDoctorReviewSessionV1,
    BobaErrorDoctorReviewSetV1,
    BobaErrorDoctorReviewSignalUsageV1,
    BobaErrorDoctorReviewSummaryV1,
    BobaErrorDoctorReviewTimelineEntryV1,
    BobaErrorDoctorReviewV1,
    BobaErrorEvidenceCardV1,
    BobaIncidentQueueItemV1,
    BobaIncidentReferenceV1,
    BobaIncidentSnapshotV1,
    BobaRecoveryAttemptProjectionV1,
    BobaRepairPlanProjectionV1,
    BobaRootCauseProjectionV1,
    bounded_excerpt,
    build_fixed_error_doctor_action_registry,
    build_fixed_error_section_registry,
    build_fixed_error_source_registry,
    source_severity_order,
)
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError, register_exception_handlers
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_error_doctor_review_test"
_ACK = "error_doctor_action_acknowledge_incident_v1"

CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaErrorDoctorRegistrySnapshotV1,
    BobaIncidentReferenceV1,
    BobaErrorDoctorReviewSessionV1,
    BobaIncidentQueueItemV1,
    BobaIncidentSnapshotV1,
    BobaDiagnosisProjectionV1,
    BobaRootCauseProjectionV1,
    BobaErrorEvidenceCardV1,
    BobaRepairPlanProjectionV1,
    BobaRecoveryAttemptProjectionV1,
    BobaErrorConflictV1,
    BobaErrorDoctorComparisonV1,
    BobaErrorDoctorActionDescriptorV1,
    BobaErrorDoctorActionRequestV1,
    BobaErrorDoctorActionReceiptV1,
    BobaErrorDoctorReviewEventV1,
    BobaErrorDoctorReviewTimelineEntryV1,
    BobaErrorDoctorReviewNotificationV1,
    BobaErrorDoctorReviewSummaryV1,
    BobaErrorDoctorReviewSignalUsageV1,
    BobaErrorDoctorReviewSetV1,
)


class _StubReviewUi:
    """Stands in for Review UI, the owner of incident acknowledgement metadata."""

    def __init__(self) -> None:
        self.acknowledged: list[str] = []
        self.reject = False
        self.malformed = False

    def create_boba_review_session(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        if self.reject:
            raise ValidationError("Review UI rejected the review session.")
        return {"review_session_id": "review_session_1", "session_digest": "a" * 64}

    def acknowledge_boba_review_notification(
        self, project_id: str, session_id: str, notification_id: str
    ) -> dict[str, Any]:
        if self.reject:
            raise ValidationError("Review UI rejected the acknowledgement.")
        self.acknowledged.append(notification_id)
        if self.malformed:
            return {"review_session_id": session_id, "session_digest": "b" * 64}
        return {
            "review_session_id": session_id,
            "session_digest": "b" * 64,
            "acknowledged_notification_ids": list(self.acknowledged),
        }


def _engine(tmp_path: Path, **seed: Any) -> tuple[BobaErrorDoctorReviewV1, _StubReviewUi]:
    store = BobaMemoryStore(tmp_path / "boba")
    owner = _StubReviewUi()
    engine = BobaErrorDoctorReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


def _prepared(engine: BobaErrorDoctorReviewV1, incident_id: str = "case_a") -> dict[str, Any]:
    session = engine.create_error_doctor_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    payload = engine.build_incident_snapshot(
        PROJECT_ID, session.error_doctor_review_session_id, incident_id
    )
    payload["session"] = session
    return payload


def _request(
    engine: BobaErrorDoctorReviewV1, payload: dict[str, Any], key: str
) -> BobaErrorDoctorActionRequestV1:
    return engine.create_error_doctor_action_request(
        PROJECT_ID,
        error_doctor_review_session_id=payload["session"].error_doctor_review_session_id,
        incident_snapshot_id=payload["snapshot"]["incident_snapshot_id"],
        action_descriptor_id=_ACK,
        decision_value="acknowledged",
        reason="",
        confirmation_context_digest=payload["action_confirmations"][_ACK],
        idempotency_key=key,
        confirmed=True,
    )


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Error Doctor Review Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4",
        size_bytes=24,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=600.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _client(tmp_path: Path) -> tuple[TestClient, BobaIntegration]:
    from olympus.api.v1.routes.boba import router

    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    asyncio.run(storage.put(project.storage_key, b"synthetic", content_type="video/mp4"))
    asyncio.run(StorageProjectRepository(storage).save(project))
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))
    seed_project(integration.store, PROJECT_ID)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    return TestClient(app), integration


# ---------------------------------------------------------------------------
# Offline validator coverage: one test per catalogued correctness condition
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def scenario_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_all_scenarios()}


@pytest.fixture(scope="module")
def self_check_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_self_check()}


@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
def test_validator_scenario(
    scenario: str, scenario_results: dict[str, ScenarioResult]
) -> None:
    result = scenario_results[scenario]
    assert result.passed, f"{scenario}: {result.detail}"


SELF_CHECK_NAMES: tuple[str, ...] = tuple(item.name for item in run_self_check())


@pytest.mark.parametrize("check", SELF_CHECK_NAMES)
def test_declared_boundary_self_check(
    check: str, self_check_results: dict[str, ScenarioResult]
) -> None:
    result = self_check_results[check]
    assert result.passed, f"{check}: {result.detail}"


def test_scenario_catalogue_is_unique_and_grouped() -> None:
    assert len(SCENARIO_NAMES) == len(set(SCENARIO_NAMES))
    assert len(SCENARIO_NAMES) >= 260
    assert all(":" in name for name in SCENARIO_NAMES)


def test_synthetic_project_reports_real_counts() -> None:
    report = run_synthetic_project()
    assert report["incident_count"] == 2
    assert report["priority_tier_count"] == 14
    assert report["evidence_card_count"] == 14
    assert report["confirmed_root_cause_count"] == 0
    assert report["owner_reported_success_count"] == 1
    assert report["independently_verified_count"] == 0
    assert report["repair_execution_available"] is False
    assert report["available_action_descriptor_ids"] == [_ACK]


# ---------------------------------------------------------------------------
# Contracts and fixed registries
# ---------------------------------------------------------------------------
def test_every_contract_forbids_unknown_fields() -> None:
    for contract in CONTRACT_TYPES:
        assert contract.model_config.get("extra") == "forbid", contract.__name__


def test_contract_count_covers_the_module_surface() -> None:
    assert len(CONTRACT_TYPES) == 21


def test_source_registry_is_fixed_and_unique() -> None:
    registry = build_fixed_error_source_registry()
    assert len(registry) == 14
    assert len(set(registry)) == 14
    assert [key for key, item in registry.items() if item["required"]] == ["error_doctor"]


def test_source_registry_names_only_real_store_loaders(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    for descriptor in build_fixed_error_source_registry().values():
        assert hasattr(store, str(descriptor["loader"])), descriptor


def test_source_registry_classes_cover_every_evidence_role() -> None:
    registry = build_fixed_error_source_registry()
    classes = {item["source_class"] for item in registry.values()}
    assert classes == {"incident", "diagnosis", "repair", "verification"}


def test_only_autopilot_evidence_is_advisory() -> None:
    registry = build_fixed_error_source_registry()
    advisory = {key for key, item in registry.items() if item["advisory_only"]}
    assert advisory == {"autopilot_controller"}


def test_section_registry_is_fixed() -> None:
    registry = build_fixed_error_section_registry()
    assert len(registry) == 10
    assert registry["overview"]["collapsed_by_default"] is False
    assert registry["repair_plan"]["collapsed_by_default"] is True


def test_action_registry_declares_twelve_actions_with_owners() -> None:
    registry = build_fixed_error_doctor_action_registry()
    assert len(registry) == 12
    for descriptor in registry.values():
        assert descriptor.owning_module_id
        assert descriptor.owning_operation_id


def test_only_acknowledgement_is_available_in_v1() -> None:
    registry = build_fixed_error_doctor_action_registry()
    available = [item for item in registry.values() if item.availability == "available"]
    assert [item.action_descriptor_id for item in available] == [_ACK]
    assert available[0].owning_module_id == "review_ui"
    assert available[0].authoritative is False


def test_every_unavailable_action_names_an_unavailable_operation() -> None:
    registry = build_fixed_error_doctor_action_registry()
    for descriptor in registry.values():
        if descriptor.availability == "unavailable":
            assert descriptor.owning_operation_id.startswith("unavailable_")
            assert descriptor.limitations, descriptor.action_descriptor_id


def test_execution_capable_actions_are_all_unavailable() -> None:
    registry = build_fixed_error_doctor_action_registry()
    for descriptor in registry.values():
        if descriptor.execution_capable:
            assert descriptor.availability == "unavailable"


def test_priority_tiers_are_fourteen_and_ordered() -> None:
    tiers = [priority for priority, _reason in INCIDENT_QUEUE_PRIORITY_TIERS]
    assert len(tiers) == 14
    assert tiers == sorted(tiers)
    assert len(set(tiers)) == 14


def test_source_severity_order_is_owner_owned() -> None:
    assert source_severity_order()[0] == "blocker"
    assert source_severity_order()[-1] == "unknown"
    assert len(source_severity_order()) == 7


def test_module_bounds_are_explicit() -> None:
    assert MAX_COMPARISON_INCIDENTS == 4
    assert MAX_QUEUE_PAGE_SIZE == 50
    assert MAX_ANNOTATION_LENGTH == 4_000
    assert MAX_EXCERPT_CHARS == 16_384
    assert MAX_TECHNICAL_MESSAGE_CHARS == 8_192
    assert MAX_EVIDENCE_CARDS == 100
    assert SUPPORTED_INCIDENT_SCHEMA_ID == "boba_error_doctor_v1"


def test_comparison_contract_pins_no_automatic_selection() -> None:
    for field_name in (
        "no_automatic_winner",
        "no_automatic_root_cause_selection",
        "no_automatic_repair_selection",
    ):
        assert BobaErrorDoctorComparisonV1.model_fields[field_name].default is True
    with pytest.raises(PydanticValidationError):
        BobaErrorDoctorComparisonV1(
            comparison_id="cmp",
            project_id=PROJECT_ID,
            incident_ids=["case_a", "case_b"],
            no_automatic_winner=False,  # type: ignore[arg-type]
        )


def test_repair_plan_contract_pins_non_executable() -> None:
    assert BobaRepairPlanProjectionV1.model_fields["executable_by_panel"].default is False
    assert BobaRepairPlanProjectionV1.model_fields["raw_command_exposed"].default is False
    with pytest.raises(PydanticValidationError):
        BobaRepairPlanProjectionV1(
            repair_plan_projection_id="rp",
            source_module_id="repair_planner",
            source_record_id="r",
            source_record_digest="0" * 64,
            repair_plan_id="strategy_a",
            executable_by_panel=True,  # type: ignore[arg-type]
        )


def test_signal_usage_pins_every_forbidden_flag_false() -> None:
    usage = BobaErrorDoctorReviewSignalUsageV1()
    for field_name in (
        "incident_created_by_panel",
        "diagnosis_created_by_panel",
        "root_cause_created_by_panel",
        "repair_plan_created_by_panel",
        "repair_executed_by_panel",
        "recovery_executed_by_panel",
        "checkpoint_restored_by_panel",
        "workflow_changed_by_panel",
        "code_modified_by_panel",
        "artifact_modified_by_panel",
        "hidden_incident_score_created",
        "hidden_repair_score_created",
        "optimistic_authority_update_used",
        "command_execution_used",
        "shell_execution_used",
        "powershell_execution_used",
        "git_execution_used",
        "ffmpeg_execution_used",
        "package_installation_used",
        "tool_download_used",
        "upload_used",
        "publication_used",
        "destructive_action_used",
    ):
        assert getattr(usage, field_name) is False, field_name


def test_root_cause_contract_refuses_confirmed_hypothesis() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRootCauseProjectionV1(
            root_cause_projection_id="rc",
            source_module_id="root_cause_analyzer",
            source_record_id="r",
            source_record_digest="0" * 64,
            root_cause_id="candidate_0",
            confirmed=True,
            hypothesis=True,
        )


def test_recovery_contract_refuses_completed_without_attempt() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRecoveryAttemptProjectionV1(
            recovery_attempt_projection_id="ra",
            source_module_id="tool_recovery",
            source_record_id="r",
            source_record_digest="0" * 64,
            recovery_attempt_id="attempt_1",
            attempted=False,
            completed=True,
        )


# ---------------------------------------------------------------------------
# Bounded, redacted text projection
# ---------------------------------------------------------------------------
def test_bounded_excerpt_keeps_line_structure() -> None:
    result = bounded_excerpt("line one\nline two\nline three")
    assert result["text"].count("\n") == 2
    assert result["truncated"] is False


def test_bounded_excerpt_redacts_bearer_tokens() -> None:
    result = bounded_excerpt("Authorization: Bearer abcdefghijklmnop")
    assert "abcdefghijklmnop" not in result["text"]
    assert result["sensitive_values_redacted"] is True


def test_bounded_excerpt_redacts_assigned_secrets() -> None:
    result = bounded_excerpt("client_secret=supersecretvalue123")
    assert "supersecretvalue123" not in result["text"]


def test_bounded_excerpt_redacts_private_keys() -> None:
    result = bounded_excerpt("-----BEGIN RSA PRIVATE KEY-----")
    assert "PRIVATE KEY" not in result["text"]


def test_bounded_excerpt_redacts_github_and_aws_tokens() -> None:
    text = bounded_excerpt("ghp_abcdefghijklmnopqrstuvwxyz01 AKIAIOSFODNN7EXAMPLE")["text"]
    assert "ghp_" not in text
    assert "AKIA" not in text


def test_bounded_excerpt_redacts_credential_urls() -> None:
    result = bounded_excerpt("https://user:password@example.com/repo.git")
    assert "password@" not in result["text"]


def test_bounded_excerpt_redacts_environment_assignments() -> None:
    result = bounded_excerpt("MY_API_TOKEN=abcdef123456")
    assert "abcdef123456" not in result["text"]


def test_bounded_excerpt_redacts_unix_and_windows_paths() -> None:
    text = bounded_excerpt("/home/me/x.py and C:\\Users\\bob\\y.py")["text"]
    assert "/home/me" not in text
    assert "Users" not in text


def test_bounded_excerpt_bounds_individual_lines() -> None:
    result = bounded_excerpt("y" * 5_000 + "\nshort")
    assert result["truncated"] is True
    assert all(len(line) <= 2_048 for line in result["text"].split("\n"))


def test_bounded_excerpt_bounds_total_length() -> None:
    result = bounded_excerpt("\n".join("z" * 100 for _ in range(400)))
    assert len(result["text"]) <= MAX_EXCERPT_CHARS


# ---------------------------------------------------------------------------
# Projection behaviour
# ---------------------------------------------------------------------------
def test_references_project_every_persisted_case(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    references = engine.build_incident_references(PROJECT_ID)
    assert [item.incident_id for item in references] == ["case_a", "case_b"]
    assert all(item.schema_supported for item in references)


def test_references_are_empty_without_an_error_doctor_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, with_incidents=False)
    assert engine.build_incident_references(PROJECT_ID) == []


def test_unknown_incident_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.inspect_incident(PROJECT_ID, "case_missing")


def test_incident_id_charset_is_enforced(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.inspect_incident(PROJECT_ID, "../../etc/passwd")


def test_diagnosis_preserves_owner_values(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    projection = engine.build_diagnosis_projections(PROJECT_ID, "case_a")[0]
    assert projection.original_status == "probable"
    assert projection.original_category == "rendering"
    assert projection.confidence_value == 0.74
    assert projection.confidence_comparable_across_sources is False


def test_diagnosis_easy_explanation_is_separate(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    projection = engine.build_diagnosis_projections(PROJECT_ID, "case_a")[0]
    assert projection.bounded_easy_explanation
    assert projection.bounded_easy_explanation != projection.bounded_technical_explanation


def test_diagnosis_hypotheses_are_labelled(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    inspected = engine.inspect_diagnosis(PROJECT_ID, "case_a")
    assert inspected["hypotheses"][0]["classification"] == "source_owned_hypothesis"
    assert inspected["hypotheses"][0]["verification_needed"] is True


def test_diagnosis_states_it_does_not_diagnose(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    joined = " ".join(engine.inspect_diagnosis(PROJECT_ID, "case_a")["limitations"])
    assert "The panel does not diagnose" in joined


def test_root_cause_is_absent_without_the_owner_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    assert engine.build_root_cause_projections(PROJECT_ID, "case_a") == []
    inspected = engine.inspect_root_cause(PROJECT_ID, "case_a")
    assert inspected["confirmed_root_cause_count"] == 0


def test_repair_plan_is_absent_without_the_owner_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    inspected = engine.inspect_repair_plan(PROJECT_ID, "case_a")
    assert inspected["repair_plan_projections"] == []
    assert inspected["repair_execution_available"] is False


def test_recovery_history_is_absent_without_the_owner_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    history = engine.inspect_recovery_history(PROJECT_ID, "case_a")
    assert history["attempt_count"] == 0
    assert history["independently_verified_count"] == 0


def test_recovery_history_states_owner_success_is_not_verification(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    joined = " ".join(engine.inspect_recovery_history(PROJECT_ID, "case_a")["limitations"])
    assert "never merged" in joined
    assert "never reported as resolved" in joined


def test_evidence_cards_cover_every_fixed_source(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    cards = engine.build_evidence_cards(PROJECT_ID, "case_a")
    modules = {item.source_module_id for item in cards}
    assert modules == set(build_fixed_error_source_registry())


def test_missing_evidence_is_never_a_pass(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    missing = [
        item for item in engine.build_evidence_cards(PROJECT_ID, "case_a") if item.missing
    ]
    assert missing
    for card in missing:
        assert any("never treated as a pass" in row for row in card.limitations)


def test_validation_evidence_reports_missing_honestly(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    validation = engine.inspect_validation_evidence(PROJECT_ID, "case_a")
    assert validation["missing_validation_evidence"] is True
    assert any("never becomes a pass" in row for row in validation["limitations"])


def test_artifact_evidence_never_infers_integrity(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    artifacts = engine.inspect_artifact_evidence(PROJECT_ID, "case_a")
    assert artifacts["missing_artifact_evidence_count"] == 1
    assert any("never inferred" in row for row in artifacts["limitations"])


def test_clean_project_reports_no_conflict(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    assert engine.detect_incident_conflicts(PROJECT_ID, "case_a") == []


def test_queue_is_deterministic_and_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first = engine.build_incident_queue(PROJECT_ID, limit=10_000)
    second = engine.build_incident_queue(PROJECT_ID, limit=10_000)
    assert first["items"] == second["items"]
    assert first["limit"] == MAX_QUEUE_PAGE_SIZE


def test_queue_rejects_unsupported_filter_and_sort(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.build_incident_queue(PROJECT_ID, review_filter="most_dangerous")
    with pytest.raises(ValidationError):
        engine.build_incident_queue(PROJECT_ID, sort="best_repair")


def test_queue_item_reports_no_repair_score(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    item = engine.build_incident_queue(PROJECT_ID)["items"][0]
    assert not any("score" in key for key in item)
    assert any("not a score" in row for row in item["limitations"])


def test_snapshot_records_digests_and_statuses(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    snapshot = _prepared(engine)["snapshot"]
    assert len(snapshot["snapshot_digest"]) == 64
    assert len(snapshot["incident_digest"]) == 64
    assert snapshot["rights_status"] == "unavailable"
    assert snapshot["recovered"] is False
    assert snapshot["resolved"] is False


def test_snapshot_refresh_rebuilds_from_canonical_state(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    refreshed = engine.refresh_incident_snapshot(
        PROJECT_ID, payload["snapshot"]["incident_snapshot_id"]
    )
    assert refreshed["snapshot"]["incident_digest"] == payload["snapshot"]["incident_digest"]
    assert (
        refreshed["snapshot"]["incident_snapshot_id"]
        != payload["snapshot"]["incident_snapshot_id"]
    )


def test_confirmation_tokens_match_available_actions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    assert set(payload["action_confirmations"]) == set(
        payload["snapshot"]["available_action_descriptor_ids"]
    )
    assert all(len(value) == 64 for value in payload["action_confirmations"].values())


def test_action_request_requires_the_server_issued_token(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    with pytest.raises(ValidationError):
        engine.create_error_doctor_action_request(
            PROJECT_ID,
            error_doctor_review_session_id=payload[
                "session"
            ].error_doctor_review_session_id,
            incident_snapshot_id=payload["snapshot"]["incident_snapshot_id"],
            action_descriptor_id=_ACK,
            decision_value="acknowledged",
            reason="",
            confirmation_context_digest="0" * 64,
            idempotency_key="idem_bad_token_key",
            confirmed=True,
        )


def test_snapshot_from_another_session_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    other = engine.create_error_doctor_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_b"
    )
    with pytest.raises(ValidationError):
        engine.create_error_doctor_action_request(
            PROJECT_ID,
            error_doctor_review_session_id=other.error_doctor_review_session_id,
            incident_snapshot_id=payload["snapshot"]["incident_snapshot_id"],
            action_descriptor_id=_ACK,
            decision_value="acknowledged",
            reason="",
            confirmation_context_digest=payload["action_confirmations"][_ACK],
            idempotency_key="idem_cross_session_key",
            confirmed=True,
        )


def test_acknowledgement_routes_to_review_ui(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_ack_key")
    receipt = asyncio.run(
        engine.submit_error_doctor_action_to_owner(
            PROJECT_ID, request.error_doctor_action_request_id
        )
    )
    assert receipt.accepted_by_owner is True
    assert receipt.owning_module_id == "review_ui"
    assert receipt.canonical_status == "acknowledged"
    assert owner.acknowledged == ["case_a"]


def test_acknowledgement_claims_no_change(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_nochange_key")
    receipt = asyncio.run(
        engine.submit_error_doctor_action_to_owner(
            PROJECT_ID, request.error_doctor_action_request_id
        )
    )
    assert receipt.authoritative_state_changed is False
    assert receipt.repair_executed is False
    assert receipt.recovery_attempt_started is False
    assert receipt.workflow_changed is False
    assert receipt.code_changed is False
    assert receipt.artifact_changed is False


def test_owner_rejection_is_recorded(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_owner_reject_key")
    owner.reject = True
    receipt = asyncio.run(
        engine.submit_error_doctor_action_to_owner(
            PROJECT_ID, request.error_doctor_action_request_id
        )
    )
    assert receipt.canonical_status == "rejected_by_owner"
    assert receipt.accepted_by_owner is False


def test_malformed_owner_response_is_handled(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_malformed_key")
    owner.malformed = True
    receipt = asyncio.run(
        engine.submit_error_doctor_action_to_owner(
            PROJECT_ID, request.error_doctor_action_request_id
        )
    )
    assert receipt.canonical_status == "malformed_owner_response"
    assert receipt.accepted_by_owner is False


def test_duplicate_submission_reuses_the_receipt(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_duplicate_key")
    first = asyncio.run(
        engine.submit_error_doctor_action_to_owner(
            PROJECT_ID, request.error_doctor_action_request_id
        )
    )
    second = asyncio.run(
        engine.submit_error_doctor_action_to_owner(
            PROJECT_ID, request.error_doctor_action_request_id
        )
    )
    assert len(owner.acknowledged) == 1
    assert second.duplicate_request_reused is True
    assert second.error_doctor_action_receipt_id == first.error_doctor_action_receipt_id


def test_stale_incident_state_is_refused_before_the_owner_is_called(
    tmp_path: Path,
) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_stale_key")
    path = engine.store.boba_error_doctor_review_action_path(
        PROJECT_ID, request.error_doctor_action_request_id
    )
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["expected_incident_digest"] = "9" * 64
    path.write_text(json.dumps(stored), encoding="utf-8")
    receipt = asyncio.run(
        engine.submit_error_doctor_action_to_owner(
            PROJECT_ID, request.error_doctor_action_request_id
        )
    )
    assert receipt.stale_state_rejected is True
    assert receipt.error_code == "incident_digest_mismatch"
    assert owner.acknowledged == []


def test_expired_action_request_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_expired_key")
    path = engine.store.boba_error_doctor_review_action_path(
        PROJECT_ID, request.error_doctor_action_request_id
    )
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(stored), encoding="utf-8")
    outcome = engine.validate_error_doctor_action_request(
        PROJECT_ID, request.error_doctor_action_request_id
    )
    assert outcome["valid"] is False
    assert outcome["code"] == "expired_snapshot"


def test_receipt_cannot_claim_repair_without_an_owner_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    forged = BobaErrorDoctorActionReceiptV1(
        error_doctor_action_receipt_id="error_doctor_receipt_forged",
        error_doctor_action_request_id="error_doctor_action_forged",
        project_id=PROJECT_ID,
        incident_id="case_a",
        owning_module_id="review_ui",
        owning_operation_id="acknowledge_notification",
        repair_executed=True,
    )
    with pytest.raises(ValidationError):
        engine._persist_receipt(PROJECT_ID, forged)


def test_session_updates_are_allowlisted(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_error_doctor_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    updated = engine.update_error_doctor_review_session(
        PROJECT_ID,
        session.error_doctor_review_session_id,
        {"active_filter": "failed_recovery", "show_bounded_logs": True},
    )
    assert updated.active_filter == "failed_recovery"
    assert updated.show_bounded_logs is True
    with pytest.raises(ValidationError):
        engine.update_error_doctor_review_session(
            PROJECT_ID,
            session.error_doctor_review_session_id,
            {"available_action_descriptor_ids": ["x"]},
        )


def test_annotations_are_bounded_and_labelled(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_error_doctor_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    updated = engine.update_error_doctor_review_session(
        PROJECT_ID,
        session.error_doctor_review_session_id,
        {"local_annotations": [{"text": "n" * (MAX_ANNOTATION_LENGTH + 20)}]},
    )
    assert len(updated.local_annotations[0]["text"]) == MAX_ANNOTATION_LENGTH
    assert updated.local_annotations[0]["notice"] == (
        "Review-session annotation — not part of the canonical incident, "
        "diagnosis or repair record."
    )


def test_annotations_reject_credentials(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_error_doctor_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    with pytest.raises(ValidationError):
        engine.update_error_doctor_review_session(
            PROJECT_ID,
            session.error_doctor_review_session_id,
            {"local_annotations": [{"text": "the api_token is abc"}]},
        )


def test_reset_preserves_canonical_records(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    engine.build_error_doctor_review(PROJECT_ID)
    result = engine.reset_error_doctor_review_metadata(PROJECT_ID)
    assert result["incident_records_preserved"] is True
    assert result["code_modified"] is False
    assert result["artifacts_modified"] is False
    assert engine.store.load_boba_error_doctor(PROJECT_ID) is not None


def test_export_is_sanitised(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    export = engine.export_error_doctor_review(PROJECT_ID)
    assert export["privacy"]["sensitive_values_excluded"] is True
    assert export["privacy"]["raw_stack_traces_excluded"] is True
    assert export["privacy"]["repair_executed"] is False
    assert str(tmp_path) not in json.dumps(export)


def test_review_set_round_trips_and_states_limits(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    built = engine.build_error_doctor_review(PROJECT_ID)
    loaded = engine.load_error_doctor_review(PROJECT_ID)
    assert loaded is not None
    assert BobaErrorDoctorReviewSetV1.model_validate(loaded)
    joined = " ".join(built["limitations"])
    assert "does not detect errors" in joined
    assert "never presented as a confirmed fact" in joined


def test_cross_project_case_is_not_projected(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, with_incidents=False)
    engine.store.save_boba_error_doctor(
        synthetic_error_doctor_set(PROJECT_ID, [synthetic_case("case_only")])
    )
    references = engine.build_incident_references(PROJECT_ID)
    assert [item.incident_id for item in references] == ["case_only"]


def test_events_are_empty_without_owner_events(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    events = engine.inspect_incident_events(PROJECT_ID)
    assert events["events"] == []
    assert events["has_more"] is False


def test_timeline_is_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    timeline = engine.inspect_incident_timeline(PROJECT_ID, limit=10_000)
    assert len(timeline["entries"]) <= 100


# ---------------------------------------------------------------------------
# Integration layer, safety gate and facade
# ---------------------------------------------------------------------------
def test_integration_layer_registers_the_module_as_read_only() -> None:
    descriptor = build_boba_module_registry()["error_doctor_review"]
    assert descriptor.implementation_status == "available"
    assert descriptor.implementation_import_path == "olympus.boba.error_doctor_review"
    assert descriptor.read_only is True
    assert descriptor.execution_capable is False


def test_integration_layer_registers_twenty_five_operations() -> None:
    operations = build_boba_operation_registry()
    ours = {
        key: value
        for key, value in operations.items()
        if key.startswith("error_doctor_review.")
    }
    assert len(ours) == 25
    assert all(item.module_id == "error_doctor_review" for item in ours.values())


def test_only_submit_action_requires_target_approval() -> None:
    operations = build_boba_operation_registry()
    approvals = {
        key
        for key, value in operations.items()
        if key.startswith("error_doctor_review.") and value.target_approval_required
    }
    assert approvals == {"error_doctor_review.submit_action"}


def test_no_operation_is_execution_capable() -> None:
    operations = build_boba_operation_registry()
    for key, value in operations.items():
        if key.startswith("error_doctor_review."):
            assert value.operation_class not in {
                "approved_execution",
                "approved_rollback",
                "repair",
            }, key


def test_safety_gate_classifies_every_operation() -> None:
    registry = build_safety_module_operation_registry()["error_doctor_review"]
    assert len(registry) == 25
    assert registry["submit_action"] == "approval_required_read_only"
    read_only = [key for key, value in registry.items() if value == "automatic_read_only"]
    assert len(read_only) == 24


def test_safety_gate_and_layer_agree_on_operation_names() -> None:
    layer = {
        key.split(".", 1)[1]
        for key in build_boba_operation_registry()
        if key.startswith("error_doctor_review.")
    }
    assert layer == set(build_safety_module_operation_registry()["error_doctor_review"])


def test_review_ui_module_is_not_modified() -> None:
    text = Path("src/olympus/boba/review_ui.py").read_text(encoding="utf-8")
    assert "error_doctor_review" not in text


def test_reliability_owner_modules_are_not_modified() -> None:
    for name in (
        "error_doctor",
        "root_cause_analyzer",
        "repair_planner",
        "tool_recovery",
        "code_surgeon",
        "observer",
    ):
        text = Path(f"src/olympus/boba/{name}.py").read_text(encoding="utf-8")
        assert "error_doctor_review" not in text, name


def test_module_exports_the_public_surface() -> None:
    import olympus.boba as boba_package

    for name in (
        "BobaErrorDoctorReviewV1",
        "BobaIncidentReferenceV1",
        "BobaIncidentSnapshotV1",
        "build_fixed_error_doctor_action_registry",
        "build_fixed_error_source_registry",
    ):
        assert hasattr(boba_package, name), name


def test_facade_exposes_every_error_doctor_review_operation(tmp_path: Path) -> None:
    integration = BobaIntegration(
        LocalStorage(root=str(tmp_path / "storage")), BobaMemoryStore(tmp_path / "boba")
    )
    for name in (
        "build_boba_error_doctor_review_registry",
        "inspect_boba_error_doctor_review_registry",
        "create_boba_error_doctor_review_session",
        "inspect_boba_error_doctor_review_session",
        "update_boba_error_doctor_review_session",
        "build_boba_incident_queue",
        "inspect_boba_incident_queue",
        "inspect_boba_incident",
        "build_boba_incident_snapshot",
        "refresh_boba_incident_snapshot",
        "inspect_boba_incident_diagnosis",
        "inspect_boba_incident_root_cause",
        "inspect_boba_incident_repair_plan",
        "inspect_boba_incident_recovery_history",
        "inspect_boba_incident_validation_evidence",
        "inspect_boba_incident_artifact_evidence",
        "detect_boba_incident_conflicts",
        "compare_boba_incidents",
        "create_boba_error_doctor_action_request",
        "validate_boba_error_doctor_action_request",
        "submit_boba_error_doctor_action_to_owner",
        "inspect_boba_error_doctor_action_receipt",
        "inspect_boba_incident_timeline",
        "inspect_boba_incident_events",
        "load_boba_error_doctor_review",
        "export_boba_error_doctor_review",
        "reset_boba_error_doctor_review_metadata",
    ):
        assert callable(getattr(integration, name)), name


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_api_root_and_registry(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review"
    root = client.get(base)
    assert root.status_code == 200
    assert root.json()["project_id"] == PROJECT_ID
    registry = client.get(f"{base}/registry")
    assert registry.status_code == 200
    assert len(registry.json()["sources"]) == 14
    assert len(registry.json()["actions"]) == 12
    assert len(registry.json()["priority_tiers"]) == 14


def test_api_queue_and_rejected_filters(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review/queue"
    response = client.get(base)
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert client.get(base, params={"review_filter": "easiest_fix"}).status_code >= 400
    assert client.get(base, params={"sort": "best_repair"}).status_code >= 400


def test_api_session_lifecycle(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review"
    created = client.post(f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"})
    assert created.status_code == 200
    session_id = created.json()["error_doctor_review_session_id"]
    assert client.get(f"{base}/sessions/{session_id}").status_code == 200
    patched = client.patch(
        f"{base}/sessions/{session_id}", json={"active_filter": "conflicts"}
    )
    assert patched.status_code == 200
    assert patched.json()["active_filter"] == "conflicts"
    deleted = client.delete(f"{base}/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json()["incident_records_preserved"] is True


def test_api_incident_projection_endpoints(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review/incidents/case_a"
    assert client.get(base).status_code == 200
    for path in (
        "diagnosis",
        "root-cause",
        "repair-plan",
        "recovery-history",
        "validation",
        "artifacts",
        "conflicts",
    ):
        assert client.get(f"{base}/{path}").status_code == 200, path


def test_api_unknown_incident_returns_an_error(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review/incidents/case_zz"
    )
    assert response.status_code >= 400


def test_api_snapshot_and_refresh(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["error_doctor_review_session_id"]
    snapshot = client.post(
        f"{base}/incidents/case_a/snapshot",
        json={"error_doctor_review_session_id": session_id},
    )
    assert snapshot.status_code == 200
    snapshot_id = snapshot.json()["snapshot"]["incident_snapshot_id"]
    refreshed = client.post(f"{base}/snapshots/{snapshot_id}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["snapshot"]["incident_id"] == "case_a"


def test_api_comparison_requires_two_incidents(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review/compare"
    good = client.post(base, json={"incident_ids": ["case_a", "case_b"]})
    assert good.status_code == 200
    comparison = good.json()["comparison"]
    assert comparison["no_automatic_winner"] is True
    assert comparison["no_automatic_root_cause_selection"] is True
    assert comparison["no_automatic_repair_selection"] is True
    assert client.post(base, json={"incident_ids": ["case_a"]}).status_code >= 400


def test_api_action_round_trip(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["error_doctor_review_session_id"]
    snapshot = client.post(
        f"{base}/incidents/case_a/snapshot",
        json={"error_doctor_review_session_id": session_id},
    ).json()
    created = client.post(
        f"{base}/actions",
        json={
            "error_doctor_review_session_id": session_id,
            "incident_snapshot_id": snapshot["snapshot"]["incident_snapshot_id"],
            "action_descriptor_id": _ACK,
            "decision_value": "acknowledged",
            "reason": "",
            "confirmation_context_digest": snapshot["action_confirmations"][_ACK],
            "idempotency_key": "idem_api_ack_key",
            "confirmed": True,
        },
    )
    assert created.status_code == 200
    request_id = created.json()["error_doctor_action_request_id"]
    assert client.post(f"{base}/actions/{request_id}/validate").json()["valid"] is True
    submitted = client.post(f"{base}/actions/{request_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["repair_executed"] is False
    assert submitted.json()["authoritative_state_changed"] is False
    assert client.get(f"{base}/actions/{request_id}").status_code == 200


def test_api_refuses_every_execution_action(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["error_doctor_review_session_id"]
    snapshot = client.post(
        f"{base}/incidents/case_a/snapshot",
        json={"error_doctor_review_session_id": session_id},
    ).json()
    for action_id in (
        "error_doctor_action_request_recovery_attempt_v1",
        "error_doctor_action_request_tool_retry_v1",
        "error_doctor_action_request_checkpoint_recovery_v1",
        "error_doctor_action_approve_repair_plan_v1",
    ):
        response = client.post(
            f"{base}/actions",
            json={
                "error_doctor_review_session_id": session_id,
                "incident_snapshot_id": snapshot["snapshot"]["incident_snapshot_id"],
                "action_descriptor_id": action_id,
                "decision_value": None,
                "reason": "Attempting an execution action.",
                "confirmation_context_digest": "0" * 64,
                "idempotency_key": f"idem_{action_id[-20:]}",
                "confirmed": True,
            },
        )
        assert response.status_code >= 400, action_id


def test_api_never_exposes_an_execution_route(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review"
    for path in ("/repair", "/execute", "/incidents/case_a/repair", "/incidents/case_a/retry"):
        assert client.post(f"{base}{path}", json={}).status_code in {404, 405, 422}


def test_api_timeline_events_and_export(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/error-doctor-review"
    assert client.get(f"{base}/timeline").status_code == 200
    assert client.get(f"{base}/events").status_code == 200
    export = client.get(f"{base}/export")
    assert export.status_code == 200
    assert export.json()["privacy"]["private_paths_excluded"] is True
    assert str(tmp_path) not in json.dumps(export.json())


def test_full_chain_project_projects_every_layer(tmp_path: Path) -> None:
    engine, _ = _full_chain(tmp_path / "chain")
    from tools.validate_boba_error_doctor_review import PROJECT_ID as VALIDATOR_PROJECT

    assert engine.build_root_cause_projections(VALIDATOR_PROJECT, "case_a")
    assert engine.build_repair_plan_projections(VALIDATOR_PROJECT, "case_a")
    assert engine.build_recovery_attempt_projections(VALIDATOR_PROJECT, "case_a")
