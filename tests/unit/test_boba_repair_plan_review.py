"""Unit tests for BOBA Repair Plan Panel V1.

Every catalogued validator condition and declared-boundary self-check runs as an
individual test, alongside direct contract, engine, facade and API tests.

Nothing here generates a repair plan, revises one, approves or rejects one,
executes a plan or a step, runs a command, restores a checkpoint, restarts a
process, transitions a workflow, modifies code or artifacts, uploads or
publishes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from tools._boba_repair_plan_review_fixtures import (
    COMMAND_TARGET,
    PLAN_CHECKPOINT,
    PLAN_CODE_CHANGE,
    PLAN_DESTRUCTIVE,
    PLAN_REVERSIBLE,
    PRIVATE_PATH_TARGET,
    REPAIR_CASE_ID,
    SHELL_TARGET,
    seed_project,
    synthetic_approval_gate,
    synthetic_repair_planner_set,
    synthetic_strategy,
)
from tools.validate_boba_repair_plan_review import (
    SCENARIO_NAMES,
    ScenarioResult,
    inspect_persisted_project,
    run_all_scenarios,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.repair_plan_review import (
    COMMAND_WITHHELD_NOTICE,
    MAX_ANNOTATION_LENGTH,
    MAX_COMPARISON_PLANS,
    MAX_QUEUE_PAGE_SIZE,
    NOT_EXECUTABLE_NOTICE,
    PRIVATE_PATH_NOTICE,
    REPAIR_PLAN_QUEUE_PRIORITY_TIERS,
    SOURCE_RETAINED_NOTICE,
    SUPPORTED_REPAIR_PLAN_SCHEMA_ID,
    BobaRepairApprovalRequirementV1,
    BobaRepairEvidenceCardV1,
    BobaRepairPlanActionDescriptorV1,
    BobaRepairPlanActionReceiptV1,
    BobaRepairPlanActionRequestV1,
    BobaRepairPlanComparisonV1,
    BobaRepairPlanConflictV1,
    BobaRepairPlanQueueItemV1,
    BobaRepairPlanReferenceV1,
    BobaRepairPlanRegistrySnapshotV1,
    BobaRepairPlanReviewEventV1,
    BobaRepairPlanReviewNotificationV1,
    BobaRepairPlanReviewSessionV1,
    BobaRepairPlanReviewSetV1,
    BobaRepairPlanReviewSignalUsageV1,
    BobaRepairPlanReviewSummaryV1,
    BobaRepairPlanReviewTimelineEntryV1,
    BobaRepairPlanReviewV1,
    BobaRepairPlanSnapshotV1,
    BobaRepairRecoveryLinkV1,
    BobaRepairRiskProjectionV1,
    BobaRepairStepProjectionV1,
    BobaRepairVerificationRequirementV1,
    bounded_step_description,
    build_fixed_repair_plan_action_registry,
    build_fixed_repair_section_registry,
    build_fixed_repair_source_registry,
    joined_owner_text,
    repair_plan_queue_priority_tiers,
    repair_risk_dimensions,
    source_holds_command,
    source_holds_private_path,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError, register_exception_handlers
from olympus.utils import utc_now

PROJECT_ID = "repair-plan-review-project"
_ACK = "repair_plan_action_acknowledge_linked_incident_v1"

CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaRepairPlanRegistrySnapshotV1,
    BobaRepairPlanReferenceV1,
    BobaRepairPlanReviewSessionV1,
    BobaRepairPlanQueueItemV1,
    BobaRepairPlanSnapshotV1,
    BobaRepairStepProjectionV1,
    BobaRepairRiskProjectionV1,
    BobaRepairApprovalRequirementV1,
    BobaRepairVerificationRequirementV1,
    BobaRepairEvidenceCardV1,
    BobaRepairRecoveryLinkV1,
    BobaRepairPlanConflictV1,
    BobaRepairPlanComparisonV1,
    BobaRepairPlanActionDescriptorV1,
    BobaRepairPlanActionRequestV1,
    BobaRepairPlanActionReceiptV1,
    BobaRepairPlanReviewEventV1,
    BobaRepairPlanReviewTimelineEntryV1,
    BobaRepairPlanReviewNotificationV1,
    BobaRepairPlanReviewSummaryV1,
    BobaRepairPlanReviewSignalUsageV1,
    BobaRepairPlanReviewSetV1,
)

_WRITE_FLAGS: tuple[str, ...] = (
    "plan_created_by_panel",
    "plan_revised_by_panel",
    "plan_approved_by_panel",
    "plan_rejected_by_panel",
    "plan_executed_by_panel",
    "step_executed_by_panel",
    "recovery_executed_by_panel",
    "checkpoint_restored_by_panel",
    "process_restarted_by_panel",
    "workflow_changed_by_panel",
    "code_modified_by_panel",
    "artifact_modified_by_panel",
    "raw_command_exposed",
    "private_path_exposed",
    "hidden_plan_ranking_created",
    "hidden_repair_success_score_created",
    "hidden_safety_score_created",
    "optimistic_authority_update_used",
    "arbitrary_module_used",
    "arbitrary_operation_used",
    "arbitrary_url_used",
    "arbitrary_path_used",
    "untrusted_html_used",
    "command_execution_used",
    "shell_execution_used",
    "powershell_execution_used",
    "git_execution_used",
    "ffmpeg_execution_used",
    "package_installation_used",
    "tool_download_used",
    "media_generation_used",
    "source_media_modified",
    "accepted_output_modified",
    "approval_created_locally",
    "safety_decision_created_locally",
    "rights_decision_created_locally",
    "final_decision_created_locally",
    "upload_used",
    "publication_used",
    "external_analytics_used",
    "rights_bypass_used",
    "safety_bypass_used",
    "destructive_action_used",
)

_UNAVAILABLE_ACTIONS: tuple[str, ...] = (
    "repair_plan_action_acknowledge_plan_v1",
    "repair_plan_action_approve_plan_v1",
    "repair_plan_action_reject_plan_v1",
    "repair_plan_action_request_plan_revision_v1",
    "repair_plan_action_request_plan_regeneration_v1",
    "repair_plan_action_request_recovery_attempt_v1",
    "repair_plan_action_request_tool_retry_v1",
    "repair_plan_action_request_checkpoint_restore_v1",
    "repair_plan_action_escalate_plan_v1",
    "repair_plan_action_record_plan_review_note_v1",
)


class _StubReviewUi:
    """Stands in for Review UI, the owner of incident acknowledgement metadata."""

    def __init__(self) -> None:
        self.sessions: list[dict[str, Any]] = []
        self.acknowledged: list[str] = []
        self.reject = False
        self.malformed = False

    def create_boba_review_session(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        if self.reject:
            raise ValidationError("Review UI rejected the review session.")
        self.sessions.append({"project_id": project_id, **kwargs})
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


def _engine(tmp_path: Path, **seed: Any) -> tuple[BobaRepairPlanReviewV1, _StubReviewUi]:
    store = BobaMemoryStore(tmp_path / "boba")
    owner = _StubReviewUi()
    engine = BobaRepairPlanReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


def _prepared(
    engine: BobaRepairPlanReviewV1, plan_id: str = PLAN_CHECKPOINT
) -> dict[str, Any]:
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    payload = engine.build_repair_plan_snapshot(
        PROJECT_ID, session.repair_plan_review_session_id, plan_id
    )
    payload["session"] = session
    return payload


def _request(
    engine: BobaRepairPlanReviewV1, payload: dict[str, Any], key: str
) -> BobaRepairPlanActionRequestV1:
    return engine.create_repair_plan_action_request(
        PROJECT_ID,
        repair_plan_review_session_id=payload["session"].repair_plan_review_session_id,
        repair_plan_snapshot_id=payload["snapshot"]["repair_plan_snapshot_id"],
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
        name="BOBA Repair Plan Review Test",
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


def _base(project_id: str = PROJECT_ID) -> str:
    return f"/api/v1/boba/projects/{project_id}/repair-plan-review"


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
    assert len(SCENARIO_NAMES) >= 280
    assert all(":" in name for name in SCENARIO_NAMES)


def test_synthetic_project_reports_real_counts() -> None:
    report = run_synthetic_project()
    assert report["repair_plan_count"] == 4
    assert report["queue_item_count"] == 4
    assert report["priority_tier_count"] == 14
    assert report["command_bearing_step_count"] == 1
    assert report["raw_command_exposed"] is False
    assert report["private_path_exposed"] is False
    assert report["independently_verified_count"] == 0
    assert report["plan_execution_available"] is False
    assert report["available_action_descriptor_ids"] == [_ACK]


def test_persisted_project_inspection_is_read_only(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    seed_project(store, PROJECT_ID)
    report = inspect_persisted_project(tmp_path / "boba", PROJECT_ID)
    assert report["repair_plan_count"] == 4
    assert set(report["repair_plan_ids"]) == {
        PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_CHECKPOINT, PLAN_DESTRUCTIVE
    }
    assert report["unsupported_schema_plan_ids"] == []
    assert "Read-only inspection" in report["notice"]


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contract", CONTRACT_TYPES, ids=lambda c: c.__name__)
def test_contract_forbids_unknown_fields(contract: type[BaseModel]) -> None:
    assert contract.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("contract", CONTRACT_TYPES, ids=lambda c: c.__name__)
def test_contract_is_importable_and_named(contract: type[BaseModel]) -> None:
    assert contract.__name__.startswith("Boba")
    assert contract.__doc__ is None or isinstance(contract.__doc__, str)


def test_set_schema_version_is_pinned() -> None:
    assert (
        BobaRepairPlanReviewSetV1.model_fields["schema_version"].default
        == "boba_repair_plan_review_v1"
    )


@pytest.mark.parametrize("flag", _WRITE_FLAGS)
def test_signal_usage_write_flag_is_pinned_false(flag: str) -> None:
    usage = BobaRepairPlanReviewSignalUsageV1()
    assert getattr(usage, flag) is False
    with pytest.raises(PydanticValidationError):
        BobaRepairPlanReviewSignalUsageV1(**{flag: True})


def test_step_projection_pins_no_exposure() -> None:
    step = BobaRepairStepProjectionV1(
        repair_step_projection_id="s",
        repair_plan_id=PLAN_REVERSIBLE,
        source_record_id="step_1",
        source_record_digest="a" * 64,
        source_step_id="step_1",
        original_order=1,
    )
    assert step.raw_command_exposed is False
    assert step.private_path_exposed is False
    assert step.executable_by_panel is False


@pytest.mark.parametrize(
    "field", ["raw_command_exposed", "private_path_exposed", "executable_by_panel"]
)
def test_step_projection_refuses_exposure(field: str) -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairStepProjectionV1(
            repair_step_projection_id="s",
            repair_plan_id=PLAN_REVERSIBLE,
            source_record_id="step_1",
            source_record_digest="a" * 64,
            source_step_id="step_1",
            original_order=1,
            **{field: True},
        )


def test_risk_projection_pins_reversible_is_not_risk_free() -> None:
    row = BobaRepairRiskProjectionV1(
        repair_risk_projection_id="r",
        repair_plan_id=PLAN_REVERSIBLE,
        source_record_id="risk_a",
        source_record_digest="a" * 64,
        risk_dimension="overall_risk",
    )
    assert row.reversible_does_not_mean_risk_free is True
    with pytest.raises(PydanticValidationError):
        BobaRepairRiskProjectionV1(
            repair_risk_projection_id="r",
            repair_plan_id=PLAN_REVERSIBLE,
            source_record_id="risk_a",
            source_record_digest="a" * 64,
            risk_dimension="overall_risk",
            reversible_does_not_mean_risk_free=False,
        )


def test_approval_requirement_refuses_satisfaction_without_record() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairApprovalRequirementV1(
            approval_requirement_id="a",
            repair_plan_id=PLAN_REVERSIBLE,
            source_module_id="repair_planner",
            requirement_type="human_review",
            satisfied_by_owner=True,
        )


def test_approval_requirement_refuses_satisfaction_without_digest() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairApprovalRequirementV1(
            approval_requirement_id="a",
            repair_plan_id=PLAN_REVERSIBLE,
            source_module_id="repair_planner",
            requirement_type="rollback_plan",
            satisfied_by_owner=True,
            canonical_record_id="rollback_a",
        )


def test_approval_requirement_accepts_full_canonical_record() -> None:
    row = BobaRepairApprovalRequirementV1(
        approval_requirement_id="a",
        repair_plan_id=PLAN_REVERSIBLE,
        source_module_id="repair_planner",
        requirement_type="rollback_plan",
        satisfied_by_owner=True,
        canonical_record_id="rollback_a",
        canonical_record_digest="a" * 64,
    )
    assert row.satisfied_by_owner is True


def test_verification_requirement_refuses_unfounded_independent_verification() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairVerificationRequirementV1(
            verification_requirement_id="v",
            repair_plan_id=PLAN_REVERSIBLE,
            source_module_id="validator_runner",
            verification_type="validator_run",
            satisfied=False,
            independently_verified=True,
        )


def test_recovery_link_refuses_completion_without_attempt() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairRecoveryLinkV1(
            repair_recovery_link_id="l",
            repair_plan_id=PLAN_REVERSIBLE,
            source_record_id="a",
            source_record_digest="a" * 64,
            recovery_attempt_id="a",
            attempted=False,
            completed=True,
        )


def test_recovery_link_refuses_verification_without_owner_success() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairRecoveryLinkV1(
            repair_recovery_link_id="l",
            repair_plan_id=PLAN_REVERSIBLE,
            source_record_id="a",
            source_record_digest="a" * 64,
            recovery_attempt_id="a",
            attempted=True,
            succeeded_by_owner=False,
            independently_verified=True,
        )


def test_comparison_pins_no_automatic_selection() -> None:
    comparison = BobaRepairPlanComparisonV1(
        comparison_id="c",
        project_id=PROJECT_ID,
        repair_plan_ids=[PLAN_REVERSIBLE, PLAN_CODE_CHANGE],
    )
    assert comparison.no_automatic_winner is True
    assert comparison.no_automatic_plan_selection is True
    assert comparison.no_automatic_execution_selection is True


def test_comparison_requires_two_plans() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairPlanComparisonV1(
            comparison_id="c", project_id=PROJECT_ID, repair_plan_ids=[PLAN_REVERSIBLE]
        )


def test_comparison_enforces_plan_limit() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRepairPlanComparisonV1(
            comparison_id="c",
            project_id=PROJECT_ID,
            repair_plan_ids=[f"plan_{index}" for index in range(MAX_COMPARISON_PLANS + 1)],
        )


def test_conflict_defaults_to_human_review() -> None:
    conflict = BobaRepairPlanConflictV1(conflict_record_id="c")
    assert conflict.human_review_required is True
    assert conflict.resolved is False
    assert conflict.explicit_supersession_found is False
    assert conflict.limitations


def test_registry_snapshot_is_immutable_by_contract() -> None:
    snapshot = BobaRepairPlanRegistrySnapshotV1(
        registry_snapshot_id="r", registry_digest="a" * 64
    )
    assert snapshot.immutable is True
    with pytest.raises(PydanticValidationError):
        BobaRepairPlanRegistrySnapshotV1(
            registry_snapshot_id="r", registry_digest="a" * 64, immutable=False
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        COMMAND_TARGET,
        SHELL_TARGET,
        "git checkout -- ./generated",
        "pip install encoder",
        "npm run build",
        "bash ./script.sh",
        "powershell -Command Get-Item",
        "rm -rf ./tmp",
        "docker run image",
        "sudo systemctl restart worker",
        "ffprobe -show_streams input.mp4",
        "encoder --preset slow --crf 20",
        "a | b",
        "a && b",
        "a; b",
        "a > out.txt",
        "$(whoami)",
    ],
)
def test_source_holds_command_detects(text: str) -> None:
    assert source_holds_command(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "Confirm the caption timing matches the approved source window.",
        "The encoder rejected the requested pixel format.",
        "render_manifest",
        "Compare the new output against the approved baseline.",
        "A checkpoint must exist before this step runs.",
    ],
)
def test_source_holds_command_ignores_prose(text: str) -> None:
    assert source_holds_command(text) is False


@pytest.mark.parametrize(
    "text",
    [PRIVATE_PATH_TARGET, r"C:\Users\alice\file.mp4", "/root/work/output", "/Users/bob/x"],
)
def test_source_holds_private_path_detects(text: str) -> None:
    assert source_holds_private_path(text) is True


def test_bounded_step_description_withholds_command_entirely() -> None:
    projected = bounded_step_description(COMMAND_TARGET)
    assert projected["text"] == COMMAND_WITHHELD_NOTICE
    assert projected["command_withheld"] is True
    assert "ffmpeg" not in projected["text"]
    assert "libx264" not in projected["text"]


def test_bounded_step_description_keeps_prose() -> None:
    projected = bounded_step_description("Read the recorded encoder capability.")
    assert projected["text"].startswith("Read the recorded encoder capability")
    assert projected["command_withheld"] is False


def test_bounded_step_description_reports_private_path() -> None:
    projected = bounded_step_description(f"Inspect {PRIVATE_PATH_TARGET} carefully")
    assert projected["command_withheld"] is False
    assert projected["private_paths_redacted"] is True
    assert "/home/operator" not in projected["text"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["a", "b"], "a b"),
        ("plain", "plain"),
        ([], ""),
        (None, ""),
        (("x", "y"), "x y"),
    ],
)
def test_joined_owner_text_flattens_owner_lists(value: Any, expected: str) -> None:
    assert joined_owner_text(value) == expected


def test_joined_owner_text_never_emits_python_repr() -> None:
    assert "['" not in joined_owner_text(["one", "two"])


@pytest.mark.parametrize("notice", [
    COMMAND_WITHHELD_NOTICE, PRIVATE_PATH_NOTICE, NOT_EXECUTABLE_NOTICE, SOURCE_RETAINED_NOTICE
])
def test_required_notice_is_a_fixed_sentence(notice: str) -> None:
    assert notice.endswith(".")
    assert notice[0].isupper()


def test_required_notices_are_exact() -> None:
    assert COMMAND_WITHHELD_NOTICE == "Command details withheld from the review panel."
    assert PRIVATE_PATH_NOTICE == "Private path details redacted."
    assert NOT_EXECUTABLE_NOTICE == "This step cannot be executed from this panel."
    assert SOURCE_RETAINED_NOTICE == "Full source record retained by Repair Planner."


def test_supported_schema_matches_owner_set() -> None:
    assert SUPPORTED_REPAIR_PLAN_SCHEMA_ID == "boba_repair_planner_v1"
    assert (
        synthetic_repair_planner_set(PROJECT_ID).schema_version
        == SUPPORTED_REPAIR_PLAN_SCHEMA_ID
    )


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------
def test_source_registry_has_fourteen_sources() -> None:
    assert len(build_fixed_repair_source_registry()) == 14


@pytest.mark.parametrize("source_id", sorted(build_fixed_repair_source_registry()))
def test_source_registry_loader_exists_on_store(source_id: str) -> None:
    loader = build_fixed_repair_source_registry()[source_id]["loader"]
    assert hasattr(BobaMemoryStore, str(loader))


@pytest.mark.parametrize("source_id", sorted(build_fixed_repair_source_registry()))
def test_source_registry_declares_authority_domain(source_id: str) -> None:
    row = build_fixed_repair_source_registry()[source_id]
    assert row["authority_domain"]
    assert row["source_class"] in {"plan", "evidence", "approval", "verification"}


def test_only_repair_planner_is_required() -> None:
    registry = build_fixed_repair_source_registry()
    assert [key for key, row in registry.items() if row["required"]] == ["repair_planner"]


def test_section_registry_has_nine_sections() -> None:
    sections = build_fixed_repair_section_registry()
    assert len(sections) == 9
    assert "overview" in sections


def test_action_registry_has_one_available_and_ten_unavailable() -> None:
    registry = build_fixed_repair_plan_action_registry()
    assert len(registry) == 11
    available = [i for i in registry.values() if i.availability == "available"]
    assert [i.action_descriptor_id for i in available] == [_ACK]
    assert len([i for i in registry.values() if i.availability == "unavailable"]) == 10


@pytest.mark.parametrize("action_id", _UNAVAILABLE_ACTIONS)
def test_unavailable_action_states_its_reason(action_id: str) -> None:
    descriptor = build_fixed_repair_plan_action_registry()[action_id]
    assert descriptor.availability == "unavailable"
    assert len(descriptor.unavailable_reason) > 20


@pytest.mark.parametrize("action_id", _UNAVAILABLE_ACTIONS)
def test_unavailable_action_is_not_allowed_in_v1(action_id: str) -> None:
    assert build_fixed_repair_plan_action_registry()[action_id].allowed_in_v1 is False


def test_available_action_declares_its_non_consequences() -> None:
    descriptor = build_fixed_repair_plan_action_registry()[_ACK]
    joined = " ".join(descriptor.does_not_do).lower()
    for phrase in (
        "approve", "reject", "revise", "execute", "recovery", "checkpoint",
        "workflow", "code", "rights", "upload",
    ):
        assert phrase in joined


def test_available_action_is_not_authoritative_or_capable() -> None:
    descriptor = build_fixed_repair_plan_action_registry()[_ACK]
    assert descriptor.authoritative is False
    assert descriptor.execution_capable is False
    assert descriptor.destructive is False
    assert descriptor.code_modifying is False
    assert descriptor.artifact_modifying is False
    assert descriptor.workflow_modifying is False
    assert descriptor.checkpoint_restoring is False
    assert descriptor.process_restarting is False
    assert descriptor.upload_or_publication is False


def test_priority_tiers_are_fourteen_and_ordered() -> None:
    tiers = repair_plan_queue_priority_tiers()
    assert len(tiers) == 14
    assert tiers == REPAIR_PLAN_QUEUE_PRIORITY_TIERS
    assert [t[0] for t in tiers] == sorted(t[0] for t in tiers)


def test_risk_dimensions_match_owner_assessment() -> None:
    from olympus.boba.repair_planner import BobaRepairRiskAssessmentV1

    dims = repair_risk_dimensions()
    assert len(dims) == 12
    assert all(d in BobaRepairRiskAssessmentV1.model_fields for d in dims)


# ---------------------------------------------------------------------------
# Integration layer, safety gate and package exports
# ---------------------------------------------------------------------------
def test_module_is_registered_read_only() -> None:
    module = build_boba_module_registry()["repair_plan_review"]
    assert module.read_only is True
    assert module.execution_capable is False


def test_twenty_seven_operations_are_registered() -> None:
    ops = {
        key.split(".", 1)[1]
        for key in build_boba_operation_registry()
        if key.startswith("repair_plan_review.")
    }
    assert len(ops) == 27
    assert "submit_action" in ops
    assert not any("execute" in op for op in ops)


def test_submit_action_requires_approval_and_safety() -> None:
    descriptor = build_boba_operation_registry()["repair_plan_review.submit_action"]
    assert descriptor.target_approval_required is True
    assert descriptor.safety_gate_required is True
    assert descriptor.required_approval_type == "exact_repair_plan_review_action"


def test_safety_gate_classifies_every_operation_read_only() -> None:
    ops = build_safety_module_operation_registry()["repair_plan_review"]
    assert len(ops) == 27
    assert set(ops.values()) <= {"automatic_read_only", "approval_required_read_only"}
    assert ops["submit_action"] == "approval_required_read_only"


def test_package_exports_resolve() -> None:
    import olympus.boba as package

    for name in (
        "BobaRepairPlanReviewV1", "BobaRepairPlanReviewSetV1", "COMMAND_WITHHELD_NOTICE",
        "NOT_EXECUTABLE_NOTICE", "REPAIR_PLAN_QUEUE_PRIORITY_TIERS",
        "build_fixed_repair_plan_action_registry", "source_holds_command",
    ):
        assert name in package.__all__
        assert hasattr(package, name)


# ---------------------------------------------------------------------------
# Engine: references, sessions, projections
# ---------------------------------------------------------------------------
def test_references_project_every_owner_strategy(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    refs = engine.build_repair_plan_references(PROJECT_ID)
    assert {i.repair_plan_id for i in refs} == {
        PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_CHECKPOINT, PLAN_DESTRUCTIVE
    }
    assert all(i.repair_case_id == REPAIR_CASE_ID for i in refs)
    assert all(i.source_diagnostic_case_id == "case_a" for i in refs)


def test_references_are_empty_without_owner_records(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, seed=False)
    assert engine.build_repair_plan_references(PROJECT_ID) == []


def test_reference_never_invents_lifecycle(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    for ref in engine.build_repair_plan_references(PROJECT_ID):
        assert ref.repair_plan_revision_id is None
        assert ref.superseding_repair_plan_id is None
        assert ref.stale is False
        assert ref.historical is False
        assert ref.superseded is False
        assert ref.current is True


def test_unknown_plan_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.inspect_repair_plan(PROJECT_ID, "strategy_that_does_not_exist")


def test_session_round_trips_and_is_project_scoped(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    fetched = engine.get_repair_plan_review_session(
        PROJECT_ID, session.repair_plan_review_session_id
    )
    assert fetched.reviewer_context_id == "reviewer_a"
    with pytest.raises(ValidationError):
        engine.get_repair_plan_review_session(
            "another-project", session.repair_plan_review_session_id
        )


@pytest.mark.parametrize(
    "reviewer",
    [
        "secret_reviewer",
        "reviewer_token",
        "reviewer_password",
        "reviewer_credential",
        "reviewer_cookie",
        "authorization_reviewer",
    ],
)
def test_session_rejects_credential_in_reviewer_context(
    tmp_path: Path, reviewer: str
) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.create_repair_plan_review_session(
            PROJECT_ID, reviewer_context_id=reviewer
        )


def test_session_accepts_an_ordinary_reviewer_context(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    assert session.reviewer_context_id == "reviewer_a"


@pytest.mark.parametrize(
    "updates",
    [
        {"plan_status": "approved"},
        {"approval_status": "granted"},
        {"repair_plan_references": []},
        {"snapshot_digest": "a" * 64},
    ],
)
def test_session_update_rejects_unsupported_fields(
    tmp_path: Path, updates: dict[str, Any]
) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    with pytest.raises(ValidationError):
        engine.update_repair_plan_review_session(
            PROJECT_ID, session.repair_plan_review_session_id, updates
        )


def test_session_annotation_is_labelled_non_canonical(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    updated = engine.update_repair_plan_review_session(
        PROJECT_ID,
        session.repair_plan_review_session_id,
        {"local_annotations": [{"text": "Second reviewer needed."}]},
    )
    assert updated.local_annotations[0]["notice"] == (
        "Review-session annotation — not part of the canonical repair plan."
    )


def test_session_annotation_is_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    updated = engine.update_repair_plan_review_session(
        PROJECT_ID,
        session.repair_plan_review_session_id,
        {"local_annotations": [{"text": "x" * (MAX_ANNOTATION_LENGTH + 500)}]},
    )
    assert len(updated.local_annotations[0]["text"]) <= MAX_ANNOTATION_LENGTH


@pytest.mark.parametrize("text", ["password=hunter2hunter2", COMMAND_TARGET, SHELL_TARGET])
def test_session_annotation_rejects_unsafe_text(tmp_path: Path, text: str) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    with pytest.raises(ValidationError):
        engine.update_repair_plan_review_session(
            PROJECT_ID,
            session.repair_plan_review_session_id,
            {"local_annotations": [{"text": text}]},
        )


def test_steps_withhold_command_and_target(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_repair_steps(PROJECT_ID, PLAN_CODE_CHANGE)
    blob = json.dumps(payload)
    assert payload["command_bearing_step_count"] == 1
    assert COMMAND_TARGET not in blob
    assert PRIVATE_PATH_TARGET not in blob
    assert '"target"' not in blob
    assert payload["raw_command_exposed"] is False
    assert payload["executable_by_panel"] is False


def test_steps_preserve_owner_order(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    steps = engine.build_step_projections(PROJECT_ID, PLAN_CODE_CHANGE)
    assert [i.original_order for i in steps] == [1, 2, 3]
    assert [i.original_step_type for i in steps] == [
        "propose_patch", "retry", "restart_service"
    ]


def test_risk_projects_all_twelve_owner_dimensions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    rows = engine.build_risk_projections(PROJECT_ID, PLAN_DESTRUCTIVE)
    dims = {i.risk_dimension for i in rows}
    for dimension in repair_risk_dimensions():
        assert dimension in dims


def test_risk_creates_no_panel_score(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_repair_risks(PROJECT_ID, PLAN_REVERSIBLE)
    assert payload["panel_risk_score_created"] is False
    assert payload["panel_repair_success_score_created"] is False


def test_approvals_are_never_satisfied_for_human_or_safety(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    rows = {
        i.requirement_type: i
        for i in engine.build_approval_requirements(PROJECT_ID, PLAN_CODE_CHANGE)
    }
    assert rows["human_review"].satisfied_by_owner is False
    assert rows["safety_gate"].satisfied_by_owner is False
    assert rows["human_review"].blocking is True


def test_approvals_satisfied_only_by_owner_plan_documents(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    rows = {
        i.requirement_type: i
        for i in engine.build_approval_requirements(PROJECT_ID, PLAN_REVERSIBLE)
    }
    assert rows["rollback_plan"].satisfied_by_owner is True
    assert rows["rollback_plan"].canonical_record_id == "rollback_a"
    assert len(rows["rollback_plan"].canonical_record_digest or "") == 64


def test_approval_payload_states_no_approved_status_exists(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_approval_requirements(PROJECT_ID, PLAN_REVERSIBLE)
    assert payload["approval_created_by_panel"] is False
    assert any("no approved value" in t for t in payload["limitations"])


def test_verification_joins_owner_list_prose(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    rows = {
        i.verification_type: i
        for i in engine.build_verification_requirements(PROJECT_ID, PLAN_REVERSIBLE)
    }
    explanation = rows["rollback_validation"].bounded_explanation
    assert explanation.startswith("Confirm the prior generated state")
    assert "['" not in explanation


def test_verification_never_claims_independent_verification(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_verification_requirements(PROJECT_ID, PLAN_REVERSIBLE)
    assert payload["independently_verified_count"] == 0
    assert payload["validator_executed_by_panel"] is False


def test_evidence_never_projects_rollback_commands(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    blob = json.dumps(engine.inspect_repair_evidence(PROJECT_ID, PLAN_REVERSIBLE))
    assert "git checkout" not in blob
    assert "rm -rf" not in blob
    assert SHELL_TARGET not in blob


def test_evidence_marks_unbindable_owners_missing(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    cards = {
        i.evidence_type: i
        for i in engine.build_repair_evidence_cards(PROJECT_ID, PLAN_REVERSIBLE)
    }
    assert cards["safety_decision"].missing is True
    assert cards["final_decision"].missing is True
    assert cards["output_quality_review"].missing is True


def test_recovery_does_not_leak_success_across_siblings(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    items = {
        i["repair_plan_id"]: i
        for i in engine.build_repair_plan_queue(PROJECT_ID)["items"]
    }
    assert items[PLAN_REVERSIBLE]["completed"] is True
    assert items[PLAN_DESTRUCTIVE]["completed"] is False


def test_recovery_case_only_link_is_warned(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    links = engine.build_recovery_links(PROJECT_ID, PLAN_DESTRUCTIVE)
    assert links
    assert all(i.linked_by_strategy_id is False for i in links)
    assert all(any("repair case" in w for w in i.warnings) for i in links)


def test_recovery_payload_states_recovered_is_not_resolved(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_linked_recovery_history(PROJECT_ID, PLAN_REVERSIBLE)
    assert payload["recovery_started_by_panel"] is False
    assert any("not resolved" in t.lower() for t in payload["limitations"])


def test_conflicts_are_never_auto_resolved(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_repair_plan_conflicts(PROJECT_ID, PLAN_CODE_CHANGE)
    assert payload["auto_resolved_count"] == 0
    for record in payload["conflict_records"]:
        assert record["resolved"] is False
        assert record["human_review_required"] is True
        assert record["same_repair_plan"] is True


def test_duplicate_plan_identity_blocks_every_action(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    seed_project(store, PROJECT_ID)
    store.save_boba_repair_planner(
        synthetic_repair_planner_set(
            PROJECT_ID,
            strategies=[
                synthetic_strategy(PLAN_REVERSIBLE),
                synthetic_strategy(PLAN_REVERSIBLE, estimated_risk="critical"),
            ],
        )
    )
    engine = BobaRepairPlanReviewV1(store, _StubReviewUi())  # type: ignore[arg-type]
    payload = _prepared(engine, PLAN_REVERSIBLE)
    assert payload["snapshot"]["available_action_descriptor_ids"] == []


def test_queue_filters_and_sorts(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    destructive = engine.build_repair_plan_queue(PROJECT_ID, active_filter="destructive")
    assert all(i["destructive"] for i in destructive["items"])
    by_severity = engine.build_repair_plan_queue(
        PROJECT_ID, active_sort="source_severity"
    )
    assert by_severity["items"][0]["original_risk_level"] == "critical"


@pytest.mark.parametrize("bad", ["safest", "best", "unknown_filter"])
def test_queue_rejects_unknown_filter(tmp_path: Path, bad: str) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.build_repair_plan_queue(PROJECT_ID, active_filter=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["best_first", "score", "unknown_sort"])
def test_queue_rejects_unknown_sort(tmp_path: Path, bad: str) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.build_repair_plan_queue(PROJECT_ID, active_sort=bad)  # type: ignore[arg-type]


def test_queue_page_is_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    page = engine.build_repair_plan_queue(PROJECT_ID, limit=MAX_QUEUE_PAGE_SIZE + 100)
    assert page["limit"] == MAX_QUEUE_PAGE_SIZE


def test_queue_rejects_negative_offset(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.build_repair_plan_queue(PROJECT_ID, offset=-1)


def test_snapshot_is_digest_pinned(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    snapshot = payload["snapshot"]
    assert len(snapshot["snapshot_digest"]) == 64
    assert len(snapshot["repair_plan_digest"]) == 64
    assert len(snapshot["confirmation_context_digest"]) == 64


def test_snapshot_refresh_rebuilds_same_plan(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    refreshed = engine.refresh_repair_plan_snapshot(
        PROJECT_ID, payload["snapshot"]["repair_plan_snapshot_id"]
    )
    assert refreshed["snapshot"]["repair_plan_id"] == PLAN_CHECKPOINT
    assert (
        refreshed["snapshot"]["repair_plan_digest"]
        == payload["snapshot"]["repair_plan_digest"]
    )


def test_comparison_collapses_duplicates_and_picks_nothing(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    comparison = engine.compare_repair_plans(
        PROJECT_ID, [PLAN_REVERSIBLE, PLAN_REVERSIBLE, PLAN_CODE_CHANGE]
    )["comparison"]
    assert comparison["repair_plan_ids"] == [PLAN_REVERSIBLE, PLAN_CODE_CHANGE]
    assert comparison["no_automatic_winner"] is True


def test_comparison_requires_two_distinct_plans(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.compare_repair_plans(PROJECT_ID, [PLAN_REVERSIBLE, PLAN_REVERSIBLE])


def test_comparison_enforces_the_plan_limit(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.compare_repair_plans(
            PROJECT_ID,
            [PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_CHECKPOINT, PLAN_DESTRUCTIVE, "x"],
        )


# ---------------------------------------------------------------------------
# Engine: actions
# ---------------------------------------------------------------------------
def test_acknowledgement_routes_to_review_ui(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    request = _request(engine, payload, "idem_ack_key")
    receipt = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    assert receipt.accepted_by_owner is True
    assert receipt.owning_module_id == "review_ui"
    assert receipt.owning_operation_id == "acknowledge_notification"
    assert owner.sessions[-1]["target_type"] == "incident"
    assert owner.acknowledged == ["case_a"]


def test_acknowledgement_changes_no_authority(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    request = _request(engine, payload, "idem_noauth_key")
    receipt = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    for field in (
        "authoritative_state_changed", "plan_approved", "plan_rejected", "plan_revised",
        "repair_executed", "recovery_attempt_started", "checkpoint_restored",
        "process_restarted", "workflow_changed", "code_changed", "artifact_changed",
    ):
        assert getattr(receipt, field) is False


def test_owner_rejection_is_recorded_truthfully(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    request = _request(engine, payload, "idem_reject_key")
    owner.reject = True
    receipt = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    assert receipt.accepted_by_owner is False
    assert receipt.canonical_status == "rejected_by_owner"
    assert receipt.error_code == "owner_rejected"


def test_malformed_owner_response_is_refused(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    request = _request(engine, payload, "idem_malformed_key")
    owner.malformed = True
    receipt = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    assert receipt.canonical_status == "malformed_owner_response"
    assert receipt.accepted_by_owner is False


def test_duplicate_submission_reuses_receipt(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    request = _request(engine, payload, "idem_dup_key")
    first = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    second = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    assert second.duplicate_request_reused is True
    assert second.repair_plan_action_receipt_id == first.repair_plan_action_receipt_id


def test_drifted_plan_is_refused_before_reaching_owner(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    request = _request(engine, payload, "idem_drift_key")
    engine.store.save_boba_repair_planner(
        synthetic_repair_planner_set(
            PROJECT_ID,
            approval_gates=[synthetic_approval_gate(approval_status="blocked")],
        )
    )
    receipt = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    assert receipt.stale_state_rejected is True
    assert receipt.accepted_by_owner is False
    assert owner.acknowledged == []


@pytest.mark.parametrize("action_id", _UNAVAILABLE_ACTIONS)
def test_unavailable_action_request_is_refused(tmp_path: Path, action_id: str) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    with pytest.raises(ValidationError):
        engine.create_repair_plan_action_request(
            PROJECT_ID,
            repair_plan_review_session_id=payload[
                "session"
            ].repair_plan_review_session_id,
            repair_plan_snapshot_id=payload["snapshot"]["repair_plan_snapshot_id"],
            action_descriptor_id=action_id,
            decision_value=None,
            reason="a reason",
            confirmation_context_digest="0" * 64,
            idempotency_key="idem_unavailable_key",
            confirmed=True,
        )


@pytest.mark.parametrize(
    "reason",
    ["api_key=AKIAIOSFODNN7EXAMPLE", PRIVATE_PATH_TARGET, COMMAND_TARGET, SHELL_TARGET],
)
def test_action_reason_rejects_unsafe_text(tmp_path: Path, reason: str) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    with pytest.raises(ValidationError):
        engine.create_repair_plan_action_request(
            PROJECT_ID,
            repair_plan_review_session_id=payload[
                "session"
            ].repair_plan_review_session_id,
            repair_plan_snapshot_id=payload["snapshot"]["repair_plan_snapshot_id"],
            action_descriptor_id=_ACK,
            decision_value="acknowledged",
            reason=reason,
            confirmation_context_digest=payload["action_confirmations"][_ACK],
            idempotency_key="idem_unsafe_reason_key",
            confirmed=True,
        )


def test_action_requires_matching_confirmation(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    with pytest.raises(ValidationError):
        engine.create_repair_plan_action_request(
            PROJECT_ID,
            repair_plan_review_session_id=payload[
                "session"
            ].repair_plan_review_session_id,
            repair_plan_snapshot_id=payload["snapshot"]["repair_plan_snapshot_id"],
            action_descriptor_id=_ACK,
            decision_value="acknowledged",
            reason="",
            confirmation_context_digest="0" * 64,
            idempotency_key="idem_wrong_digest_key",
            confirmed=True,
        )


def test_action_requires_explicit_confirmation(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    with pytest.raises(ValidationError):
        engine.create_repair_plan_action_request(
            PROJECT_ID,
            repair_plan_review_session_id=payload[
                "session"
            ].repair_plan_review_session_id,
            repair_plan_snapshot_id=payload["snapshot"]["repair_plan_snapshot_id"],
            action_descriptor_id=_ACK,
            decision_value="acknowledged",
            reason="",
            confirmation_context_digest=payload["action_confirmations"][_ACK],
            idempotency_key="idem_unconfirmed_key",
            confirmed=False,
        )


def test_confirmation_statement_is_exact(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    described = engine.describe_repair_plan_action_confirmation(
        PROJECT_ID, payload["snapshot"]["repair_plan_snapshot_id"], _ACK
    )
    assert described["confirmation_statement"] == (
        "This request does not directly execute commands, modify code, "
        "change artifacts, restore a checkpoint, restart a process, "
        "transition the workflow, grant Rights or Safety approval, upload "
        "content or publish content."
    )


def test_receipt_cannot_claim_change_without_canonical_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine, PLAN_CHECKPOINT)
    request = _request(engine, payload, "idem_forge_key")
    receipt = asyncio.run(
        engine.submit_repair_plan_action_to_owner(
            PROJECT_ID, request.repair_plan_action_request_id
        )
    )
    for field in (
        "plan_approved", "plan_rejected", "plan_revised", "repair_executed",
        "recovery_attempt_started", "checkpoint_restored", "process_restarted",
        "workflow_changed", "code_changed", "artifact_changed",
    ):
        forged = receipt.model_copy(
            update={
                "repair_plan_action_receipt_id": f"repair_plan_receipt_forged_{field}",
                field: True,
                "canonical_record_id": None,
                "canonical_record_digest": None,
            }
        )
        with pytest.raises(ValidationError):
            engine._persist_receipt(PROJECT_ID, forged)


# ---------------------------------------------------------------------------
# Engine: aggregate, export, reset
# ---------------------------------------------------------------------------
def test_review_set_serialises_and_withholds(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    review = engine.build_repair_plan_review(PROJECT_ID)
    blob = json.dumps(review)
    assert review["schema_version"] == "boba_repair_plan_review_v1"
    assert COMMAND_TARGET not in blob
    assert "libx264" not in blob
    assert "/home/operator" not in blob


def test_review_summary_counts_are_truthful(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    summary = engine.build_repair_plan_review(PROJECT_ID)["review_summary"]
    assert summary["total_plan_count"] == 4
    assert summary["destructive_plan_count"] >= 1
    assert summary["code_change_plan_count"] == 1
    assert summary["command_bearing_step_count"] == 1
    assert summary["plans_missing_approval_count"] >= 1


def test_review_is_persisted_and_loadable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    engine.build_repair_plan_review(PROJECT_ID)
    assert engine.load_repair_plan_review(PROJECT_ID) is not None


def test_review_does_not_duplicate_owner_records(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    review = engine.build_repair_plan_review(PROJECT_ID)
    assert "repair_strategies" not in review
    assert "proposed_steps" not in json.dumps(review)


def test_export_declares_every_exclusion(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    privacy = engine.export_repair_plan_review(PROJECT_ID)["privacy"]
    for key in (
        "raw_commands_excluded", "command_arguments_excluded", "shell_text_excluded",
        "rollback_step_text_excluded", "step_target_excluded", "private_paths_excluded",
    ):
        assert privacy[key] is True
    for key in (
        "plan_created", "plan_revised", "plan_approved", "plan_rejected",
        "plan_executed", "step_executed", "recovery_executed", "checkpoint_restored",
        "process_restarted", "workflow_changed", "code_modified", "artifact_modified",
        "source_media_modified", "accepted_output_modified", "upload_used",
        "publication_used",
    ):
        assert privacy[key] is False


def test_reset_preserves_every_owner_history(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    engine.build_repair_plan_review(PROJECT_ID)
    result = engine.reset_repair_plan_review_metadata(PROJECT_ID)
    for key in (
        "repair_plan_records_preserved", "repair_case_records_preserved",
        "risk_assessment_records_preserved", "approval_gate_records_preserved",
        "rollback_plan_records_preserved", "checkpoint_plan_records_preserved",
        "validation_plan_records_preserved", "recovery_history_preserved",
        "root_cause_records_preserved", "incident_records_preserved",
        "action_receipt_history_preserved",
    ):
        assert result[key] is True
    assert result["code_modified"] is False
    assert engine.build_repair_plan_references(PROJECT_ID) != []


def test_session_reset_removes_only_the_session(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    result = engine.reset_repair_plan_review_metadata(
        PROJECT_ID, session.repair_plan_review_session_id
    )
    assert result["session_removed"] is True
    assert result["repair_plan_records_preserved"] is True
    assert engine.build_repair_plan_references(PROJECT_ID) != []


def test_events_and_timeline_are_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    events = engine.inspect_repair_plan_events(PROJECT_ID)
    timeline = engine.inspect_repair_plan_timeline(PROJECT_ID)
    assert events["schema_version"] == "boba_repair_plan_review_events_v1"
    assert timeline["schema_version"] == "boba_repair_plan_review_timeline_v1"
    assert len(timeline["entries"]) <= 100


def test_registry_snapshot_is_stable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first = engine.build_repair_plan_review_registry(PROJECT_ID)
    second = engine.build_repair_plan_review_registry(PROJECT_ID)
    assert first["registry_snapshot"] == second["registry_snapshot"]
    assert first["registry_snapshot"]["immutable"] is True


# ---------------------------------------------------------------------------
# Integration facade
# ---------------------------------------------------------------------------
def test_facade_exposes_repair_plan_review_engine(tmp_path: Path) -> None:
    _, integration = _client(tmp_path)
    assert isinstance(integration.repair_plan_review, BobaRepairPlanReviewV1)


def test_facade_queue_maps_external_names(tmp_path: Path) -> None:
    _, integration = _client(tmp_path)
    queue = integration.build_boba_repair_plan_queue(
        PROJECT_ID, review_filter="destructive", sort="source_severity"
    )
    assert queue["active_filter"] == "destructive"
    assert queue["active_sort"] == "source_severity"


def test_facade_load_builds_when_absent(tmp_path: Path) -> None:
    _, integration = _client(tmp_path)
    payload = integration.load_boba_repair_plan_review(PROJECT_ID)
    assert payload["schema_version"] == "boba_repair_plan_review_v1"


def test_facade_comparison_passes_through(tmp_path: Path) -> None:
    _, integration = _client(tmp_path)
    result = integration.compare_boba_repair_plans(
        PROJECT_ID, [PLAN_REVERSIBLE, PLAN_CODE_CHANGE]
    )
    assert result["comparison"]["no_automatic_winner"] is True


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
def test_api_registry_and_review(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    registry = client.get(f"{_base()}/registry")
    assert registry.status_code == 200
    assert len(registry.json()["priority_tiers"]) == 14
    review = client.get(_base())
    assert review.status_code == 200
    assert review.json()["review_summary"]["total_plan_count"] == 4


def test_api_session_lifecycle(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(f"{_base()}/sessions", json={"reviewer_context_id": "reviewer_a"})
    assert created.status_code == 200
    session_id = created.json()["repair_plan_review_session_id"]
    assert client.get(f"{_base()}/sessions/{session_id}").status_code == 200
    patched = client.patch(
        f"{_base()}/sessions/{session_id}", json={"active_filter": "destructive"}
    )
    assert patched.status_code == 200
    assert patched.json()["active_filter"] == "destructive"
    deleted = client.delete(f"{_base()}/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json()["repair_plan_records_preserved"] is True


def test_api_session_patch_forbids_unknown_fields(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(f"{_base()}/sessions", json={"reviewer_context_id": "reviewer_a"})
    session_id = created.json()["repair_plan_review_session_id"]
    response = client.patch(
        f"{_base()}/sessions/{session_id}", json={"plan_status": "approved"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "leaf",
    ["steps", "risk", "approvals", "verification", "evidence", "recovery-history", "conflicts"],
)
def test_api_plan_leaf_routes(tmp_path: Path, leaf: str) -> None:
    client, _ = _client(tmp_path)
    response = client.get(f"{_base()}/plans/{PLAN_CODE_CHANGE}/{leaf}")
    assert response.status_code == 200
    assert COMMAND_TARGET not in response.text
    assert "/home/operator" not in response.text


@pytest.mark.parametrize(
    "leaf",
    ["", "/steps", "/risk", "/approvals", "/verification", "/evidence",
     "/recovery-history", "/conflicts"],
)
def test_api_unknown_plan_is_client_error(tmp_path: Path, leaf: str) -> None:
    client, _ = _client(tmp_path)
    response = client.get(f"{_base()}/plans/strategy_missing{leaf}")
    assert 400 <= response.status_code < 500


def test_api_queue_and_paging(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(f"{_base()}/queue", params={"limit": 2})
    assert response.status_code == 200
    assert response.json()["returned_count"] == 2
    assert response.json()["has_more"] is True


def test_api_queue_rejects_unknown_filter(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(f"{_base()}/queue", params={"review_filter": "safest"})
    assert 400 <= response.status_code < 500


def test_api_snapshot_and_refresh(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    session_id = client.post(
        f"{_base()}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["repair_plan_review_session_id"]
    snapshot = client.post(
        f"{_base()}/plans/{PLAN_CHECKPOINT}/snapshot",
        json={"repair_plan_review_session_id": session_id},
    )
    assert snapshot.status_code == 200
    snapshot_id = snapshot.json()["snapshot"]["repair_plan_snapshot_id"]
    refreshed = client.post(f"{_base()}/snapshots/{snapshot_id}/refresh")
    assert refreshed.status_code == 200


def test_api_confirmation_route_lists_non_consequences(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    session_id = client.post(
        f"{_base()}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["repair_plan_review_session_id"]
    snapshot_id = client.post(
        f"{_base()}/plans/{PLAN_CHECKPOINT}/snapshot",
        json={"repair_plan_review_session_id": session_id},
    ).json()["snapshot"]["repair_plan_snapshot_id"]
    response = client.get(f"{_base()}/snapshots/{snapshot_id}/confirmations/{_ACK}")
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert len(response.json()["does_not_do"]) >= 10


def test_api_action_lifecycle(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    session_id = client.post(
        f"{_base()}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["repair_plan_review_session_id"]
    snapshot = client.post(
        f"{_base()}/plans/{PLAN_CHECKPOINT}/snapshot",
        json={"repair_plan_review_session_id": session_id},
    ).json()
    created = client.post(
        f"{_base()}/actions",
        json={
            "repair_plan_review_session_id": session_id,
            "repair_plan_snapshot_id": snapshot["snapshot"]["repair_plan_snapshot_id"],
            "action_descriptor_id": _ACK,
            "decision_value": "acknowledged",
            "reason": "",
            "confirmation_context_digest": snapshot["action_confirmations"][_ACK],
            "idempotency_key": "idem_api_action_key",
            "confirmed": True,
        },
    )
    assert created.status_code == 200
    request_id = created.json()["repair_plan_action_request_id"]
    assert client.post(f"{_base()}/actions/{request_id}/validate").json()["valid"] is True
    submitted = client.post(f"{_base()}/actions/{request_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["accepted_by_owner"] is True
    assert submitted.json()["authoritative_state_changed"] is False
    assert client.get(f"{_base()}/actions/{request_id}").status_code == 200


@pytest.mark.parametrize("action_id", _UNAVAILABLE_ACTIONS)
def test_api_refuses_unavailable_action(tmp_path: Path, action_id: str) -> None:
    client, _ = _client(tmp_path)
    session_id = client.post(
        f"{_base()}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["repair_plan_review_session_id"]
    snapshot = client.post(
        f"{_base()}/plans/{PLAN_CHECKPOINT}/snapshot",
        json={"repair_plan_review_session_id": session_id},
    ).json()
    response = client.post(
        f"{_base()}/actions",
        json={
            "repair_plan_review_session_id": session_id,
            "repair_plan_snapshot_id": snapshot["snapshot"]["repair_plan_snapshot_id"],
            "action_descriptor_id": action_id,
            "reason": "a reason",
            "confirmation_context_digest": "0" * 64,
            "idempotency_key": "idem_api_unavailable_key",
            "confirmed": True,
        },
    )
    assert 400 <= response.status_code < 500


def test_api_compare_bounds(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    ok = client.post(
        f"{_base()}/compare", json={"repair_plan_ids": [PLAN_REVERSIBLE, PLAN_CODE_CHANGE]}
    )
    assert ok.status_code == 200
    assert ok.json()["comparison"]["no_automatic_winner"] is True
    assert client.post(f"{_base()}/compare", json={"repair_plan_ids": ["a"]}).status_code == 422
    assert (
        client.post(
            f"{_base()}/compare", json={"repair_plan_ids": ["a", "b", "c", "d", "e"]}
        ).status_code
        == 422
    )


def test_api_timeline_events_and_export(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get(f"{_base()}/timeline").status_code == 200
    assert client.get(f"{_base()}/events").status_code == 200
    export = client.get(f"{_base()}/export")
    assert export.status_code == 200
    assert export.json()["privacy"]["raw_commands_excluded"] is True


def test_api_unknown_project_is_client_error(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(f"{_base('project-that-does-not-exist')}/registry")
    assert 400 <= response.status_code < 500
