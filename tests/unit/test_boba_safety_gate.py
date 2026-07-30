"""BOBA Safety Gate V1 contracts, policy, persistence, and integration tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_safety_gate import (
    SCENARIO_NAMES,
    SafetySyntheticHarness,
    run_named_scenario,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.autopilot_controller import (
    BobaAutopilotActionV1,
    BobaAutopilotControllerSetV1,
    BobaAutopilotProjectSnapshotV1,
    BobaAutopilotRecoveryBudgetV1,
    BobaAutopilotRunV1,
)
from olympus.boba.contracts import BobaContract
from olympus.boba.integration import BobaIntegration
from olympus.boba.safety_gate import (
    BobaSafetyActionRequestV1,
    BobaSafetyApprovalReviewV1,
    BobaSafetyCheckpointReviewV1,
    BobaSafetyConstraintCheckV1,
    BobaSafetyDecisionInvalidationV1,
    BobaSafetyDecisionV1,
    BobaSafetyEvaluationCaseV1,
    BobaSafetyEvidenceV1,
    BobaSafetyGateSetV1,
    BobaSafetyGateSignalUsageV1,
    BobaSafetyGateSummaryV1,
    BobaSafetyGateV1,
    BobaSafetyHandoffV1,
    BobaSafetyPolicySnapshotV1,
    BobaSafetyQualityReviewV1,
    BobaSafetyRightsReviewV1,
    BobaSafetyRiskAssessmentV1,
    BobaSafetyRiskFactorV1,
    BobaSafetyValidationReadinessV1,
    build_safety_module_operation_registry,
    calculate_safety_decision_digest,
    calculate_safety_request_digest,
    decision_is_expired,
    sanitize_safety_export,
)
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_safety_gate_test"
SNAPSHOT_DIGEST = "a" * 64
CHECKPOINT_DIGEST = "b" * 64


def _policy() -> BobaSafetyPolicySnapshotV1:
    return BobaSafetyPolicySnapshotV1(
        policy_snapshot_id="safety_policy_test",
        policy_sha256="c" * 64,
    )


def _request() -> BobaSafetyActionRequestV1:
    return BobaSafetyActionRequestV1(
        action_request_id="safety_request_test",
        project_id=PROJECT_ID,
        requesting_module="autopilot_controller",
        target_module="observer",
        target_operation="generate",
        action_class="automatic_read_only",
        action_description="Generate bounded local read-only evidence.",
        action_parameters_digest="d" * 64,
        project_snapshot_id="snapshot_test",
        project_snapshot_digest=SNAPSHOT_DIGEST,
        request_digest="e" * 64,
    )


def _decision() -> BobaSafetyDecisionV1:
    return BobaSafetyDecisionV1(
        safety_decision_id="safety_decision_test",
        safety_case_id="safety_case_test",
        action_request_id="safety_request_test",
        project_id=PROJECT_ID,
        decision="denied",
        decision_summary="The bounded action is denied.",
        decision_expires_at=(
            datetime.now(UTC) + timedelta(minutes=5)
        ).isoformat(),
    )


def _contract_cases() -> list[tuple[str, BobaContract]]:
    policy = _policy()
    risk_factor = BobaSafetyRiskFactorV1(
        risk_factor_id="risk_factor_test",
        safety_case_id="safety_case_test",
        category="safety_policy",
        title="Synthetic policy risk",
        summary="A bounded synthetic risk used for serialization.",
        severity="low",
        likelihood="unlikely",
    )
    return [
        ("policy_snapshot", policy),
        (
            "evaluation_case",
            BobaSafetyEvaluationCaseV1(
                safety_case_id="safety_case_test",
                project_id=PROJECT_ID,
                action_request_id="safety_request_test",
                title="Synthetic evaluation",
                target_module="observer",
                target_operation="generate",
                action_class="automatic_read_only",
                policy_snapshot_id=policy.policy_snapshot_id,
            ),
        ),
        ("action_request", _request()),
        (
            "evidence",
            BobaSafetyEvidenceV1(
                evidence_id="safety_evidence_test",
                safety_case_id="safety_case_test",
                source_module="observer",
                category="project_snapshot",
                bounded_summary="The synthetic snapshot is current.",
            ),
        ),
        (
            "constraint_check",
            BobaSafetyConstraintCheckV1(
                constraint_check_id="safety_constraint_test",
                safety_case_id="safety_case_test",
                constraint_type="project_snapshot",
                name="Project snapshot",
            ),
        ),
        (
            "approval_review",
            BobaSafetyApprovalReviewV1(
                approval_review_id="approval_review_test",
                safety_case_id="safety_case_test",
                target_module="observer",
            ),
        ),
        (
            "rights_review",
            BobaSafetyRightsReviewV1(
                rights_review_id="rights_review_test",
                safety_case_id="safety_case_test",
            ),
        ),
        (
            "checkpoint_review",
            BobaSafetyCheckpointReviewV1(
                checkpoint_review_id="checkpoint_review_test",
                safety_case_id="safety_case_test",
            ),
        ),
        (
            "validation_review",
            BobaSafetyValidationReadinessV1(
                validation_review_id="validation_review_test",
                safety_case_id="safety_case_test",
            ),
        ),
        (
            "quality_review",
            BobaSafetyQualityReviewV1(
                quality_review_id="quality_review_test",
                safety_case_id="safety_case_test",
            ),
        ),
        ("risk_factor", risk_factor),
        (
            "risk_assessment",
            BobaSafetyRiskAssessmentV1(
                risk_assessment_id="risk_assessment_test",
                safety_case_id="safety_case_test",
                risk_factors=[risk_factor],
            ),
        ),
        ("decision", _decision()),
        (
            "decision_invalidation",
            BobaSafetyDecisionInvalidationV1(
                invalidation_id="invalidation_test",
                safety_decision_id="safety_decision_test",
                invalidation_reason="The exact synthetic request changed.",
            ),
        ),
        (
            "handoff",
            BobaSafetyHandoffV1(
                handoff_id="handoff_test",
                safety_case_id="safety_case_test",
                safety_decision_id="safety_decision_test",
                target_module="human_operator",
                reason="Human review is required.",
            ),
        ),
        ("summary", BobaSafetyGateSummaryV1()),
        ("signal_usage", BobaSafetyGateSignalUsageV1()),
        (
            "gate_set",
            BobaSafetyGateSetV1(
                project_id=PROJECT_ID,
                source_id=PROJECT_ID,
                policy_snapshot=policy,
            ),
        ),
    ]


PROHIBITED_SIGNAL_FIELDS = (
    "direct_action_execution_used",
    "direct_command_execution_used",
    "direct_git_execution_used",
    "direct_ffmpeg_execution_used",
    "code_modification_used",
    "artifact_modification_used",
    "source_media_modified",
    "accepted_outputs_modified",
    "checkpoint_restore_used",
    "workflow_resume_used",
    "package_installation_used",
    "service_restart_used",
    "process_kill_used",
    "external_api_used",
    "network_access_used",
    "url_fetching_used",
    "scraping_used",
    "downloading_used",
    "uploading_used",
    "publication_used",
    "push_used",
    "merge_used",
    "deployment_used",
    "rights_bypass_used",
    "safety_bypass_used",
    "destructive_action_used",
)

AUTHORITY_FIELDS = (
    "workflow_resume_authorized",
    "checkpoint_restore_authorized",
    "upload_authorized",
    "publication_authorized",
    "push_authorized",
    "merge_authorized",
    "deployment_authorized",
)


@pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
def test_each_named_safety_scenario(
    tmp_path: Path,
    scenario_name: str,
) -> None:
    harness = SafetySyntheticHarness(tmp_path / scenario_name)
    assert run_named_scenario(harness, scenario_name) is True


@pytest.mark.parametrize(
    ("case_name", "contract"),
    _contract_cases(),
    ids=[name for name, _ in _contract_cases()],
)
def test_every_safety_contract_serializes(
    case_name: str,
    contract: BobaContract,
) -> None:
    payload = contract.model_dump(mode="json")
    assert case_name
    assert json.loads(json.dumps(payload)) == payload


@pytest.mark.parametrize("field_name", PROHIBITED_SIGNAL_FIELDS)
def test_every_prohibited_signal_is_structurally_false(field_name: str) -> None:
    signals = BobaSafetyGateSignalUsageV1()
    assert getattr(signals, field_name) is False
    with pytest.raises(PydanticValidationError):
        BobaSafetyGateSignalUsageV1.model_validate({field_name: True})


@pytest.mark.parametrize("field_name", AUTHORITY_FIELDS)
def test_every_decision_authority_flag_remains_false(field_name: str) -> None:
    decision = _decision()
    assert getattr(decision, field_name) is False
    with pytest.raises(PydanticValidationError):
        BobaSafetyDecisionV1.model_validate(
            {
                **decision.model_dump(mode="python"),
                field_name: True,
            }
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: BobaSafetyDecisionV1(
            **{
                **_decision().model_dump(mode="python"),
                "decision": "execute_everything",
            }
        ),
        lambda: BobaSafetyEvaluationCaseV1(
            safety_case_id="case",
            project_id=PROJECT_ID,
            action_request_id="request",
            title="Invalid status",
            target_module="observer",
            target_operation="generate",
            action_class="automatic_read_only",
            policy_snapshot_id="policy",
            evaluation_status="executing",
        ),
        lambda: BobaSafetyEvidenceV1(
            evidence_id="evidence",
            safety_case_id="case",
            source_module="observer",
            category="raw_command",
            bounded_summary="Invalid category.",
        ),
        lambda: BobaSafetyHandoffV1(
            handoff_id="handoff",
            safety_case_id="case",
            safety_decision_id="decision",
            target_module="shell",
            reason="Invalid handoff.",
        ),
    ],
    ids=["decision", "status", "evidence", "handoff"],
)
def test_unsupported_contract_values_are_rejected(
    factory: Callable[[], BobaContract],
) -> None:
    with pytest.raises(PydanticValidationError):
        factory()


def test_policy_digest_is_deterministic(tmp_path: Path) -> None:
    first = BobaSafetyGateV1(
        BobaMemoryStore(tmp_path / "first")
    ).create_policy_snapshot(PROJECT_ID)
    second = BobaSafetyGateV1(
        BobaMemoryStore(tmp_path / "second")
    ).create_policy_snapshot(PROJECT_ID)
    assert first.policy_snapshot.policy_sha256 == second.policy_snapshot.policy_sha256


def test_stricter_policy_changes_digest_and_shortens_ttl(tmp_path: Path) -> None:
    engine = BobaSafetyGateV1(BobaMemoryStore(tmp_path / "boba"))
    original = engine.create_policy_snapshot(PROJECT_ID)
    stricter = engine.create_policy_snapshot(
        PROJECT_ID,
        project_policy={
            "decision_ttl_seconds": {
                "read_only_allowance": 60,
                "execution_allowance": 30,
            }
        },
    )
    assert original.policy_snapshot.policy_sha256 != (
        stricter.policy_snapshot.policy_sha256
    )
    assert stricter.policy_snapshot.decision_ttl_seconds[
        "read_only_allowance"
    ] == 60
    assert stricter.policy_snapshot.decision_ttl_seconds[
        "execution_allowance"
    ] == 30
    assert "rights_bypass" in stricter.policy_snapshot.prohibited_actions


def test_policy_history_remains_immutable_after_replacement(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    engine = BobaSafetyGateV1(store)
    first = engine.create_policy_snapshot(PROJECT_ID)
    first_path = store.boba_safety_policy_path(
        PROJECT_ID,
        first.policy_snapshot.policy_snapshot_id,
    )
    first_payload = first_path.read_text(encoding="utf-8")
    engine.create_policy_snapshot(
        PROJECT_ID,
        project_policy={"decision_ttl_seconds": {"read_only_allowance": 120}},
    )
    assert first_path.read_text(encoding="utf-8") == first_payload


def test_request_and_decision_digests_are_deterministic() -> None:
    request_payload = _request().model_dump(
        mode="json",
        exclude={"request_digest"},
    )
    decision_payload = _decision().model_dump(mode="json")
    assert calculate_safety_request_digest(request_payload) == (
        calculate_safety_request_digest(request_payload)
    )
    assert calculate_safety_decision_digest(decision_payload) == (
        calculate_safety_decision_digest(decision_payload)
    )


def test_sanitized_export_removes_paths_secrets_and_raw_patch() -> None:
    payload = sanitize_safety_export(
        {
            "private_path": r"D:\Users\private\source.mp4",
            "api_token": "sk_live_12345678901234567890",
            "raw_patch": "diff --git a/private.py b/private.py",
            "full_command_log": "secret output",
        }
    )
    serialized = json.dumps(payload)
    assert "D:\\\\" not in serialized
    assert "sk_live" not in serialized
    assert "diff --git" not in serialized
    assert "secret output" not in serialized


def test_expired_decision_is_detected() -> None:
    decision = _decision().model_copy(
        update={
            "decision_expires_at": (
                datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat()
        }
    )
    assert decision_is_expired(decision) is True


def test_registry_separates_prohibited_and_future_gated_actions() -> None:
    registry = build_safety_module_operation_registry()
    assert registry["workflow_controller"]["resume"] == "future_gated"
    assert registry["checkpoint_recovery_manager"]["restore_checkpoint"] == (
        "future_gated"
    )
    assert "observer" in registry
    assert "generate" in registry["observer"]


def test_persistence_keeps_active_and_immutable_records(tmp_path: Path) -> None:
    harness = SafetySyntheticHarness(tmp_path / "boba")
    decision, gate = harness.read_only(1)
    store = harness.store
    case = gate.evaluation_cases[-1]
    assert store.boba_safety_gate_path(gate.project_id).exists()
    assert store.boba_safety_evaluation_path(
        gate.project_id,
        case.safety_case_id,
    ).exists()
    assert store.boba_safety_decision_path(
        gate.project_id,
        decision.safety_decision_id,
    ).exists()
    assert store.boba_safety_policy_path(
        gate.project_id,
        gate.policy_snapshot.policy_snapshot_id,
    ).exists()


def test_reset_removes_only_active_gate_metadata(tmp_path: Path) -> None:
    harness = SafetySyntheticHarness(tmp_path / "boba")
    decision, gate = harness.read_only(1)
    store = harness.store
    case = gate.evaluation_cases[-1]
    policy_path = store.boba_safety_policy_path(
        gate.project_id,
        gate.policy_snapshot.policy_snapshot_id,
    )
    decision_path = store.boba_safety_decision_path(
        gate.project_id,
        decision.safety_decision_id,
    )
    evaluation_path = store.boba_safety_evaluation_path(
        gate.project_id,
        case.safety_case_id,
    )
    assert store.reset_boba_safety_gate(gate.project_id) is True
    assert store.load_boba_safety_gate(gate.project_id) is None
    assert policy_path.exists()
    assert decision_path.exists()
    assert evaluation_path.exists()


def _autopilot_action() -> BobaAutopilotActionV1:
    return BobaAutopilotActionV1(
        action_id="autopilot_action_safety_test",
        run_id="autopilot_run_safety_test",
        action_type="invoke_tool_recovery",
        action_class="approval_required_execution",
        target_module="tool_recovery_brain",
        target_operation="execute_approved",
        description="Execute one exact approved local recovery attempt.",
        rationale="The bounded synthetic recovery needs exact approval.",
        parameters={
            "recovery_plan_id": "plan_exact",
            "recovery_strategy_id": "strategy_exact",
            "tool_id": "tool_exact",
            "capability_id": "capability_exact",
            "checkpoint_reference": "checkpoints/synthetic.json",
            "rollback_plan_id": "rollback_plan_exact",
            "validation_plan_id": "validation_plan_exact",
            "quality_plan_id": "quality_plan_exact",
        },
        planned_snapshot_sha256=SNAPSHOT_DIGEST,
        idempotency_key="f" * 64,
    )


def _save_autopilot_fixture(
    store: BobaMemoryStore,
    action: BobaAutopilotActionV1,
) -> None:
    run = BobaAutopilotRunV1(
        run_id=action.run_id,
        project_id=PROJECT_ID,
        correlation_id="autopilot_correlation_safety_test",
        current_state="awaiting_execution_approval",
        run_status="paused",
        control_mode="approved_execution_coordination",
        project_snapshot_id="snapshot_autopilot_test",
        rights_status="owned",
        safety_status="clear_for_local_analysis",
        budget_id="budget_safety_test",
    )
    snapshot = BobaAutopilotProjectSnapshotV1(
        project_snapshot_id=run.project_snapshot_id,
        project_id=PROJECT_ID,
        rights_status="owned",
        safety_status="clear_for_local_analysis",
        snapshot_sha256=SNAPSHOT_DIGEST,
    )
    budget = BobaAutopilotRecoveryBudgetV1(
        budget_id=run.budget_id,
        run_id=run.run_id,
        execution_coordination_allowed=True,
    )
    store.save_boba_autopilot_controller(
        BobaAutopilotControllerSetV1(
            project_id=PROJECT_ID,
            source_id=PROJECT_ID,
            runs=[run],
            project_snapshots=[snapshot],
            recovery_budgets=[budget],
            planned_actions=[action],
        )
    )


def test_autopilot_validation_binds_exact_run_action_and_parameters(
    tmp_path: Path,
) -> None:
    harness = SafetySyntheticHarness(tmp_path / "boba")
    action = _autopilot_action()
    _save_autopilot_fixture(harness.store, action)
    harness.contexts[PROJECT_ID] = harness.context(execution=True)
    request = harness.engine.create_action_request(
        PROJECT_ID,
        autopilot_run_id=action.run_id,
        autopilot_action_id=action.action_id,
        approval_record_id="approval_exact",
        checkpoint_digest=CHECKPOINT_DIGEST,
        time_budget_seconds=300,
    )
    decision = harness.engine.evaluate_action(
        PROJECT_ID,
        request.action_request_id,
        approval_record={
            "approval_id": "approval_exact",
            "approved": True,
            "explicit_confirmation": "yes",
        },
    )
    validated = harness.engine.validate_for_autopilot(
        PROJECT_ID,
        action.run_id,
        action,
        decision.safety_decision_id,
        {
            "approval_id": "approval_exact",
            "approved": True,
            "explicit_confirmation": "yes",
        },
    )
    assert validated.safety_decision_id == decision.safety_decision_id
    changed = action.model_copy(
        update={"parameters": {**action.parameters, "tool_id": "changed_tool"}}
    )
    with pytest.raises(ValidationError, match="blocked"):
        harness.engine.validate_for_autopilot(
            PROJECT_ID,
            action.run_id,
            changed,
            decision.safety_decision_id,
            {
                "approval_id": "approval_exact",
                "approved": True,
                "explicit_confirmation": "yes",
            },
        )


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Safety Gate Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=20.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _integration(tmp_path: Path) -> BobaIntegration:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    return BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))


def test_api_evaluates_and_exposes_bounded_safety_records(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        policy = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate/policies",
            json={},
        )
        request_response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate/requests",
            json={
                "target_module": "observer",
                "target_operation": "generate",
                "action_class": "automatic_read_only",
                "action_description": "Generate bounded local read-only evidence.",
                "project_snapshot_id": "snapshot_api_test",
                "project_snapshot_digest": SNAPSHOT_DIGEST,
            },
        )
        assert request_response.status_code == 200, request_response.text
        action_request_id = request_response.json()["action_request_id"]
        evaluated = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate/evaluate",
            json={"action_request_id": action_request_id},
        )
        assert evaluated.status_code == 200, evaluated.text
        decision_id = evaluated.json()["safety_decision_id"]
        gate = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate"
        )
        decision = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate/decisions/"
            f"{decision_id}"
        )
        exported = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate/export"
        )
        reset = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate"
        )
    assert policy.status_code == 200, policy.text
    assert gate.status_code == 200, gate.text
    assert decision.status_code == 200, decision.text
    assert exported.status_code == 200, exported.text
    assert exported.json()["privacy"]["action_execution_used"] is False
    assert reset.status_code == 200, reset.text
    assert reset.json()["immutable_decision_history_deleted"] is False
    assert reset.json()["workflow_resumed"] is False


@pytest.mark.parametrize(
    "unsafe_field",
    [
        "direct_command",
        "git_command",
        "ffmpeg_command",
        "raw_patch",
        "api_token",
        "external_url",
        "workflow_resume",
        "publication",
    ],
)
def test_api_rejects_uncontracted_execution_fields(
    app: FastAPI,
    tmp_path: Path,
    unsafe_field: str,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/safety-gate/requests",
            json={
                "target_module": "observer",
                "target_operation": "generate",
                "action_description": "Inspect bounded local evidence.",
                "project_snapshot_id": "snapshot_api_test",
                "project_snapshot_digest": SNAPSHOT_DIGEST,
                unsafe_field: True,
            },
        )
    assert response.status_code == 422


def test_frontend_explains_safety_sections_and_authority_boundary() -> None:
    component = (
        Path("frontend/src/components/project/BobaSafetyGatePanel.tsx")
        .read_text(encoding="utf-8")
    )
    normalized = " ".join(component.split())
    for heading in (
        "ACTION REQUEST",
        "RIGHTS AND PERMISSIONS",
        "EXACT APPROVAL",
        "CHECKPOINT AND ROLLBACK",
        "VALIDATION",
        "QUALITY",
        "RISK",
        "SAFETY DECISION",
        "HUMAN REVIEW",
        "WHAT HAPPENS NEXT",
    ):
        assert heading in component
    assert "evaluates an action but does not execute it" in normalized
    assert "Target modules must independently verify approval" in normalized
    assert (
        "workflow resume, upload, publication, merge or deployment"
        in normalized
    )


def test_validator_self_check_passes_without_execution() -> None:
    report = run_self_check()
    assert report.passed is True
    assert report.direct_action_execution_used is False
    assert report.direct_command_execution_used is False
    assert report.direct_git_execution_used is False
    assert report.direct_ffmpeg_execution_used is False
    assert report.network_access_used is False


def test_validator_runs_exactly_179_named_synthetic_scenarios() -> None:
    report = run_synthetic_project()
    assert report.passed is True
    assert report.scenario_count == 179
    assert report.passed_scenario_count == 179
    assert tuple(report.scenario_results) == SCENARIO_NAMES
