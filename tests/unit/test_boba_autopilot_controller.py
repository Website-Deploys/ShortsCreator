"""BOBA Autopilot Controller V1 contracts, safety, and integration tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_autopilot_controller import (
    SCENARIO_NAMES,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.autopilot_controller import (
    DEFAULT_AUTOPILOT_BUDGET_LIMITS,
    VALID_AUTOPILOT_TRANSITIONS,
    BobaAutopilotActionV1,
    BobaAutopilotApprovalBindingV1,
    BobaAutopilotBudgetUsageV1,
    BobaAutopilotCheckpointRequirementV1,
    BobaAutopilotControllerSetV1,
    BobaAutopilotControllerSignalUsageV1,
    BobaAutopilotControllerSummaryV1,
    BobaAutopilotControllerV1,
    BobaAutopilotDecisionV1,
    BobaAutopilotEventV1,
    BobaAutopilotHandoffV1,
    BobaAutopilotIncidentV1,
    BobaAutopilotModuleInvocationV1,
    BobaAutopilotProjectLockV1,
    BobaAutopilotProjectSnapshotV1,
    BobaAutopilotRecoveryBudgetV1,
    BobaAutopilotRunV1,
    BobaAutopilotStateTransitionV1,
    BobaAutopilotStateV1,
    build_autopilot_project_snapshot,
    calculate_autopilot_budget_usage,
    classify_autopilot_action,
    detect_autopilot_loop,
    fingerprint_autopilot_action,
    sanitize_autopilot_export,
    validate_autopilot_state_transition,
)
from olympus.boba.integration import BobaIntegration
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_autopilot_test"
RUN_ID = "autopilot_run_test"
BUDGET_ID = "autopilot_budget_test"
SNAPSHOT_SHA = "a" * 64


def _run(
    *,
    state: BobaAutopilotStateV1 = "created",
    status: str = "active",
    mode: str = "safe_read_only_automatic",
) -> BobaAutopilotRunV1:
    return BobaAutopilotRunV1(
        run_id=RUN_ID,
        project_id=PROJECT_ID,
        correlation_id="autopilot_correlation_test",
        current_state=state,
        run_status=status,
        control_mode=mode,
        project_snapshot_id="autopilot_snapshot_test",
        rights_status="owned",
        safety_status="clear_for_local_analysis",
        budget_id=BUDGET_ID,
    )


def _snapshot(
    *,
    digest: str = SNAPSHOT_SHA,
    rights_status: str = "owned",
    safety_status: str = "clear_for_local_analysis",
) -> BobaAutopilotProjectSnapshotV1:
    return BobaAutopilotProjectSnapshotV1(
        project_snapshot_id="autopilot_snapshot_test",
        project_id=PROJECT_ID,
        rights_status=rights_status,
        safety_status=safety_status,
        snapshot_sha256=digest,
    )


def _budget(**overrides: Any) -> BobaAutopilotRecoveryBudgetV1:
    values = dict(DEFAULT_AUTOPILOT_BUDGET_LIMITS)
    values.update(overrides)
    return BobaAutopilotRecoveryBudgetV1(
        budget_id=BUDGET_ID,
        run_id=RUN_ID,
        **values,
    )


def _usage(**overrides: Any) -> BobaAutopilotBudgetUsageV1:
    return BobaAutopilotBudgetUsageV1(
        budget_usage_id="autopilot_usage_test",
        budget_id=BUDGET_ID,
        **overrides,
    )


def _action(
    *,
    action_id: str = "autopilot_action_test",
    action_type: str = "inspect_project",
    action_class: str = "automatic_read_only",
    target_module: str = "autopilot_controller",
    target_operation: str = "inspect",
    status: str = "planned",
    idempotency_key: str = "b" * 64,
) -> BobaAutopilotActionV1:
    return BobaAutopilotActionV1(
        action_id=action_id,
        run_id=RUN_ID,
        action_type=action_type,
        action_class=action_class,
        target_module=target_module,
        target_operation=target_operation,
        description="Inspect bounded persisted state.",
        rationale="A deterministic test action is required.",
        planned_snapshot_sha256=SNAPSHOT_SHA,
        idempotency_key=idempotency_key,
        status=status,
    )


def _controller(
    *,
    run: BobaAutopilotRunV1 | None = None,
    budget: BobaAutopilotRecoveryBudgetV1 | None = None,
    usage: BobaAutopilotBudgetUsageV1 | None = None,
    actions: list[BobaAutopilotActionV1] | None = None,
) -> BobaAutopilotControllerSetV1:
    selected_run = run or _run()
    return BobaAutopilotControllerSetV1(
        project_id=PROJECT_ID,
        source_id=PROJECT_ID,
        runs=[selected_run],
        project_snapshots=[_snapshot()],
        recovery_budgets=[budget or _budget()],
        budget_usages=[usage or _usage()],
        planned_actions=actions or [],
    )


def _contract_cases() -> list[tuple[str, object]]:
    return [
        (
            "project_lock",
            BobaAutopilotProjectLockV1(
                project_id=PROJECT_ID,
                run_id=RUN_ID,
                expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                owner_identifier="test_owner",
                mode="safe_read_only_automatic",
            ),
        ),
        ("run", _run()),
        ("project_snapshot", _snapshot()),
        (
            "state_transition",
            BobaAutopilotStateTransitionV1(
                transition_id="transition_test",
                run_id=RUN_ID,
                sequence=1,
                from_state="created",
                to_state="inspecting_project",
                transition_reason="Run started.",
            ),
        ),
        ("action", _action()),
        (
            "module_invocation",
            BobaAutopilotModuleInvocationV1(
                module_invocation_id="invocation_test",
                run_id=RUN_ID,
                action_id="action_test",
                module_name="observer",
                operation_name="generate",
                invocation_mode="read_only_generation",
            ),
        ),
        (
            "approval_binding",
            BobaAutopilotApprovalBindingV1(
                approval_binding_id="approval_binding_test",
                run_id=RUN_ID,
                action_id="action_test",
                target_module="tool_recovery_brain",
                approval_record_id="approval_test",
                approval_type="tool_recovery_exact_execution",
            ),
        ),
        ("recovery_budget", _budget()),
        ("budget_usage", _usage()),
        (
            "checkpoint",
            BobaAutopilotCheckpointRequirementV1(
                checkpoint_requirement_id="checkpoint_requirement_test",
                run_id=RUN_ID,
            ),
        ),
        (
            "decision",
            BobaAutopilotDecisionV1(
                decision_id="decision_test",
                run_id=RUN_ID,
                decision_type="next_stage",
                decision="inspect_project",
                reason="The project snapshot is ready.",
            ),
        ),
        (
            "incident",
            BobaAutopilotIncidentV1(
                incident_id="incident_test",
                run_id=RUN_ID,
                incident_type="module_failure",
                title="Synthetic module failure",
                summary="Bounded synthetic evidence.",
            ),
        ),
        (
            "event",
            BobaAutopilotEventV1(
                event_id="event_test",
                run_id=RUN_ID,
                sequence=1,
                event_type="run_created",
                state="created",
                technical_message="A persisted run was created.",
                easy_message="BOBA created a controlled run.",
            ),
        ),
        (
            "handoff",
            BobaAutopilotHandoffV1(
                handoff_id="handoff_test",
                run_id=RUN_ID,
                target_module="safety_gate",
                reason="Quality review passed internally.",
                current_state="awaiting_safety_gate",
            ),
        ),
        ("summary", BobaAutopilotControllerSummaryV1()),
        ("signal_usage", BobaAutopilotControllerSignalUsageV1()),
        ("controller", _controller()),
    ]


@pytest.mark.parametrize(
    ("case_name", "contract"),
    _contract_cases(),
    ids=[item[0] for item in _contract_cases()],
)
def test_every_autopilot_contract_serializes(
    case_name: str,
    contract: object,
) -> None:
    assert case_name
    payload = contract.model_dump(mode="json")  # type: ignore[union-attr]
    json.dumps(payload)
    assert contract.model_validate(payload) == contract  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (source, target)
        for source, targets in VALID_AUTOPILOT_TRANSITIONS.items()
        for target in sorted(targets)
    ],
    ids=lambda value: str(value),
)
def test_every_declared_state_transition_is_valid(
    from_state: BobaAutopilotStateV1,
    to_state: BobaAutopilotStateV1,
) -> None:
    assert validate_autopilot_state_transition(from_state, to_state) is True


INVALID_TRANSITIONS = [
    (source, target)
    for source in get_args(BobaAutopilotStateV1)
    for target in get_args(BobaAutopilotStateV1)
    if target not in VALID_AUTOPILOT_TRANSITIONS[source]
]


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    INVALID_TRANSITIONS[:96],
    ids=lambda value: str(value),
)
def test_representative_undeclared_state_transitions_are_invalid(
    from_state: BobaAutopilotStateV1,
    to_state: BobaAutopilotStateV1,
) -> None:
    assert validate_autopilot_state_transition(from_state, to_state) is False


@pytest.mark.parametrize(
    "terminal_state",
    ["completed_internal_cycle", "cancelled", "blocked", "failed"],
)
def test_terminal_states_have_no_outbound_transitions(
    terminal_state: BobaAutopilotStateV1,
) -> None:
    assert VALID_AUTOPILOT_TRANSITIONS[terminal_state] == frozenset()


@pytest.mark.parametrize(
    ("from_state", "forbidden_target"),
    [
        ("created", "diagnosis_required"),
        ("observer_required", "repair_planning_required"),
        ("diagnosis_required", "awaiting_repair_decision"),
        ("root_cause_analysis_required", "tool_recovery_ready"),
        ("repair_planning_required", "execution_running"),
        ("awaiting_execution_approval", "execution_running"),
        ("execution_running", "awaiting_safety_gate"),
        ("technical_validation_required", "awaiting_safety_gate"),
        ("output_quality_review_required", "ready_for_workflow_controller"),
        ("awaiting_safety_gate", "completed_internal_cycle"),
    ],
)
def test_required_diagnostic_approval_quality_and_handoff_stages_cannot_be_skipped(
    from_state: BobaAutopilotStateV1,
    forbidden_target: BobaAutopilotStateV1,
) -> None:
    assert validate_autopilot_state_transition(from_state, forbidden_target) is False


@pytest.mark.parametrize(
    ("action_type", "target_module", "operation", "expected_class"),
    [
        ("inspect_project", "autopilot_controller", "inspect", "automatic_read_only"),
        ("load_artifacts", "autopilot_controller", "load", "automatic_read_only"),
        ("generate_observer", "observer", "generate", "automatic_read_only"),
        ("generate_error_doctor", "error_doctor", "generate", "automatic_read_only"),
        (
            "generate_root_cause_analyzer",
            "root_cause_analyzer",
            "generate",
            "automatic_read_only",
        ),
        (
            "generate_repair_planner",
            "repair_planner",
            "generate",
            "automatic_read_only",
        ),
        (
            "invoke_code_surgeon",
            "code_surgeon",
            "proposal_only",
            "automatic_read_only",
        ),
        (
            "invoke_code_surgeon",
            "code_surgeon",
            "validate_proposal",
            "automatic_read_only",
        ),
        (
            "invoke_code_surgeon",
            "code_surgeon",
            "execute_approved",
            "approval_required_execution",
        ),
        (
            "invoke_code_surgeon",
            "code_surgeon",
            "prepare_local_commit",
            "approval_required_execution",
        ),
        (
            "invoke_tool_recovery",
            "tool_recovery_brain",
            "plan",
            "automatic_read_only",
        ),
        (
            "invoke_tool_recovery",
            "tool_recovery_brain",
            "health_check",
            "automatic_read_only",
        ),
        (
            "invoke_tool_recovery",
            "tool_recovery_brain",
            "validate_output",
            "approval_required_read_only",
        ),
        (
            "invoke_tool_recovery",
            "tool_recovery_brain",
            "execute_approved",
            "approval_required_execution",
        ),
        (
            "invoke_tool_recovery_rollback",
            "tool_recovery_brain",
            "rollback",
            "approval_required_execution",
        ),
        (
            "invoke_output_quality_review",
            "output_quality_reviewer",
            "artifact_review",
            "automatic_read_only",
        ),
        (
            "invoke_output_quality_review",
            "output_quality_reviewer",
            "technical_review",
            "approval_required_read_only",
        ),
        (
            "prepare_checkpoint_handoff",
            "checkpoint_recovery_manager",
            "prepare",
            "future_gated",
        ),
        (
            "prepare_safety_handoff",
            "safety_gate",
            "prepare",
            "future_gated",
        ),
        (
            "prepare_workflow_handoff",
            "workflow_controller",
            "prepare",
            "automatic_read_only",
        ),
        ("human_review", "human_operator", "review", "future_gated"),
        ("unknown", "unknown", "unknown", "unknown"),
    ],
)
def test_action_classifier_enforces_the_typed_registry(
    action_type: Any,
    target_module: str,
    operation: str,
    expected_class: str,
) -> None:
    assert (
        classify_autopilot_action(
            action_type,
            target_module=target_module,
            target_operation=operation,
        )
        == expected_class
    )


@pytest.mark.parametrize(
    ("action_type", "target_module", "operation"),
    [
        ("invoke_code_surgeon", "unknown", "execute_approved"),
        ("invoke_code_surgeon", "code_surgeon", "arbitrary_callable"),
        ("invoke_tool_recovery", "unknown", "execute_approved"),
        ("invoke_tool_recovery", "tool_recovery_brain", "shell"),
        ("invoke_output_quality_review", "unknown", "artifact_review"),
        ("invoke_output_quality_review", "output_quality_reviewer", "publish"),
    ],
)
def test_action_classifier_rejects_arbitrary_module_or_operation(
    action_type: Any,
    target_module: str,
    operation: str,
) -> None:
    assert (
        classify_autopilot_action(
            action_type,
            target_module=target_module,
            target_operation=operation,
        )
        == "prohibited"
    )


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("project_id", "proj_changed"),
        ("run_id", "run_changed"),
        ("action_type", "generate_observer"),
        ("target_module", "observer"),
        ("target_operation", "generate"),
        ("target_plan_id", "plan_changed"),
        ("target_strategy_id", "strategy_changed"),
        ("snapshot_sha256", "c" * 64),
    ],
)
def test_action_fingerprint_changes_with_every_bound_identity(
    changed_field: str,
    changed_value: str,
) -> None:
    values = {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "action_type": "invoke_tool_recovery",
        "target_module": "tool_recovery_brain",
        "target_operation": "execute_approved",
        "target_plan_id": "plan_test",
        "target_strategy_id": "strategy_test",
        "snapshot_sha256": SNAPSHOT_SHA,
    }
    baseline = fingerprint_autopilot_action(**values)
    values[changed_field] = changed_value
    assert fingerprint_autopilot_action(**values) != baseline


def test_action_fingerprint_is_deterministic() -> None:
    values = {
        "project_id": PROJECT_ID,
        "run_id": RUN_ID,
        "action_type": "inspect_project",
        "target_module": "autopilot_controller",
        "target_operation": "inspect",
        "snapshot_sha256": SNAPSHOT_SHA,
    }
    assert fingerprint_autopilot_action(**values) == fingerprint_autopilot_action(
        **values
    )


@pytest.mark.parametrize(
    ("unsafe_payload", "forbidden_text"),
    [
        ({"path": r"C:\Users\private\secret.txt"}, r"C:\Users"),
        ({"path": "/home/private/secret.txt"}, "/home/private"),
        ({"api_key": "secret-value"}, "secret-value"),
        ({"authorization": "Bearer private"}, "Bearer private"),
        ({"password": "private"}, "private"),
        ({"cookie": "session-private"}, "session-private"),
    ],
)
def test_export_sanitizer_removes_private_paths_and_secret_values(
    unsafe_payload: dict[str, str],
    forbidden_text: str,
) -> None:
    exported = sanitize_autopilot_export(unsafe_payload)
    payload = json.dumps(exported)
    assert forbidden_text not in payload


def test_export_sanitizer_bounds_deep_payloads() -> None:
    value: dict[str, Any] = {}
    cursor = value
    for index in range(12):
        nested: dict[str, Any] = {"level": index}
        cursor["child"] = nested
        cursor = nested
    assert "[bounded]" in json.dumps(sanitize_autopilot_export(value))


def test_invalid_state_enum_is_rejected() -> None:
    payload = _run().model_dump(mode="json")
    payload["current_state"] = "full_unrestricted_autonomy"
    with pytest.raises(PydanticValidationError):
        BobaAutopilotRunV1.model_validate(payload)


def test_signal_usage_forbids_claiming_prohibited_capabilities() -> None:
    payload = BobaAutopilotControllerSignalUsageV1().model_dump(mode="json")
    payload["direct_command_execution_used"] = True
    with pytest.raises(PydanticValidationError):
        BobaAutopilotControllerSignalUsageV1.model_validate(payload)


PROHIBITED_SIGNAL_FIELDS = [
    "direct_command_execution_used",
    "direct_git_execution_used",
    "direct_ffmpeg_execution_used",
    "code_modified_directly",
    "source_media_modified",
    "accepted_outputs_modified",
    "workflow_resume_used",
    "checkpoint_restore_used",
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
]


@pytest.mark.parametrize("field_name", PROHIBITED_SIGNAL_FIELDS)
def test_every_prohibited_signal_is_structurally_false(field_name: str) -> None:
    signal = BobaAutopilotControllerSignalUsageV1()
    assert getattr(signal, field_name) is False
    payload = signal.model_dump(mode="json")
    payload[field_name] = True
    with pytest.raises(PydanticValidationError):
        BobaAutopilotControllerSignalUsageV1.model_validate(payload)


def test_snapshot_contains_all_required_module_states(tmp_path: Path) -> None:
    snapshot = build_autopilot_project_snapshot(
        BobaMemoryStore(tmp_path / "boba"),
        PROJECT_ID,
        project_context={
            "rights_status": "owned",
            "safety_status": "clear_for_local_analysis",
        },
    )
    assert set(snapshot.module_artifact_states) >= {
        "rights_permission_gate",
        "observer",
        "error_doctor",
        "root_cause_analyzer",
        "repair_planner",
        "code_surgeon",
        "tool_recovery_brain",
        "output_quality_reviewer",
    }
    assert snapshot.source_media_read_only is True


def test_snapshot_digest_is_deterministic(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    context = {
        "rights_status": "owned",
        "safety_status": "clear_for_local_analysis",
        "current_workflow_stage": "rendering",
    }
    first = build_autopilot_project_snapshot(
        store,
        PROJECT_ID,
        project_context=context,
    )
    second = build_autopilot_project_snapshot(
        store,
        PROJECT_ID,
        project_context=context,
    )
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert first.project_snapshot_id == second.project_snapshot_id


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("current_workflow_stage", "optimization"),
        ("accepted_output_ids", ["clip_changed"]),
        ("source_media_references", ["uploads/changed/source.mp4"]),
        ("rights_status", "blocked"),
        ("safety_status", "blocked"),
        ("active_external_operations", ["external_operation"]),
    ],
)
def test_snapshot_digest_changes_when_bounded_project_state_changes(
    tmp_path: Path,
    field_name: str,
    value: Any,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    baseline_context = {
        "rights_status": "owned",
        "safety_status": "clear_for_local_analysis",
    }
    baseline = build_autopilot_project_snapshot(
        store,
        PROJECT_ID,
        project_context=baseline_context,
    )
    changed_context = {**baseline_context, field_name: value}
    changed = build_autopilot_project_snapshot(
        store,
        PROJECT_ID,
        project_context=changed_context,
    )
    assert changed.snapshot_sha256 != baseline.snapshot_sha256


def test_snapshot_bounds_source_references(tmp_path: Path) -> None:
    snapshot = build_autopilot_project_snapshot(
        BobaMemoryStore(tmp_path / "boba"),
        PROJECT_ID,
        project_context={
            "rights_status": "owned",
            "safety_status": "clear_for_local_analysis",
            "source_media_references": [
                f"uploads/{PROJECT_ID}/source-{index}.mp4" for index in range(80)
            ],
        },
    )
    assert len(snapshot.source_media_references) == 32


def test_snapshot_sanitizes_private_source_reference(tmp_path: Path) -> None:
    snapshot = build_autopilot_project_snapshot(
        BobaMemoryStore(tmp_path / "boba"),
        PROJECT_ID,
        project_context={
            "rights_status": "owned",
            "safety_status": "clear_for_local_analysis",
            "source_media_references": [r"C:\Users\private\source.mp4"],
        },
    )
    assert "C:\\Users" not in json.dumps(snapshot.model_dump(mode="json"))


def test_lock_acquisition_refresh_and_release_are_persisted(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    acquired = store.acquire_boba_autopilot_lock(
        PROJECT_ID,
        run_id=RUN_ID,
        owner_identifier="owner",
        mode="safe_read_only_automatic",
        lease_seconds=60,
    )
    refreshed = store.refresh_boba_autopilot_lock(
        PROJECT_ID,
        run_id=RUN_ID,
        owner_identifier="owner",
        lease_seconds=120,
    )
    assert acquired.run_id == refreshed.run_id
    assert refreshed.stale is False
    assert store.release_boba_autopilot_lock(
        PROJECT_ID,
        run_id=RUN_ID,
        owner_identifier="owner",
    )
    assert store.load_boba_autopilot_lock(PROJECT_ID) is None


def test_active_lock_cannot_be_stolen(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.acquire_boba_autopilot_lock(
        PROJECT_ID,
        run_id=RUN_ID,
        owner_identifier="owner",
        mode="safe_read_only_automatic",
    )
    with pytest.raises(ValidationError, match="already active"):
        store.acquire_boba_autopilot_lock(
            PROJECT_ID,
            run_id="autopilot_run_other",
            owner_identifier="other",
            mode="safe_read_only_automatic",
        )


def test_stale_lock_requires_explicit_confirmation(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    path = store.boba_autopilot_lock_path(PROJECT_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    stale = BobaAutopilotProjectLockV1(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        acquired_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        refreshed_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        owner_identifier="stale_owner",
        mode="safe_read_only_automatic",
    )
    path.write_text(stale.model_dump_json(), encoding="utf-8")
    assert store.load_boba_autopilot_lock(PROJECT_ID).stale is True  # type: ignore[union-attr]
    with pytest.raises(ValidationError, match="explicit confirmation"):
        store.acquire_boba_autopilot_lock(
            PROJECT_ID,
            run_id="autopilot_run_new",
            owner_identifier="new_owner",
            mode="safe_read_only_automatic",
        )
    replacement = store.acquire_boba_autopilot_lock(
        PROJECT_ID,
        run_id="autopilot_run_new",
        owner_identifier="new_owner",
        mode="safe_read_only_automatic",
        confirm_stale=True,
    )
    assert replacement.run_id == "autopilot_run_new"
    assert list(path.parent.glob("active.lock.stale.*.json"))


@pytest.mark.parametrize(
    ("usage_field", "budget_field"),
    [
        ("actions_used", "maximum_total_actions"),
        ("execution_actions_used", "maximum_execution_actions"),
        ("module_invocations_used", "maximum_module_invocations"),
        ("retries_used", "maximum_total_retries"),
        (
            "identical_failure_retries_used",
            "maximum_identical_failure_retries",
        ),
        ("execution_duration_seconds", "maximum_execution_duration_seconds"),
        ("current_risk_score", "maximum_risk_score"),
        ("code_repair_attempts_used", "maximum_code_repair_attempts"),
        ("tool_recovery_attempts_used", "maximum_tool_recovery_attempts"),
        ("quality_review_attempts_used", "maximum_quality_review_attempts"),
        ("replanning_cycles_used", "maximum_replanning_cycles"),
        (
            "root_cause_reanalysis_cycles_used",
            "maximum_root_cause_reanalysis_cycles",
        ),
    ],
)
def test_each_hard_budget_dimension_blocks_next_action(
    usage_field: str,
    budget_field: str,
) -> None:
    budget = _budget()
    usage = _usage(**{usage_field: getattr(budget, budget_field)})
    controller = _controller(budget=budget, usage=usage)
    updated = calculate_autopilot_budget_usage(controller, controller.runs[0])
    assert updated.budget_exhausted is True
    assert updated.next_action_allowed is False


def test_total_duration_budget_blocks_next_action() -> None:
    run = _run()
    run.started_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    controller = _controller(
        run=run,
        budget=_budget(maximum_total_duration_seconds=60),
    )
    updated = calculate_autopilot_budget_usage(controller, run)
    assert "total_duration_seconds" in updated.exhausted_dimensions


def test_completed_identical_action_is_idempotent() -> None:
    completed = _action(action_id="action_completed", status="succeeded")
    candidate = _action(action_id="action_candidate")
    controller = _controller(actions=[completed, candidate])
    assert (
        detect_autopilot_loop(
            controller,
            controller.runs[0],
            action=candidate,
        )
        == "A completed identical action already exists."
    )


def test_repeated_identical_failure_is_detected() -> None:
    first = _action(action_id="failed_one", status="failed")
    second = _action(action_id="failed_two", status="failed")
    candidate = _action(action_id="candidate")
    controller = _controller(actions=[first, second, candidate])
    assert "failed without new evidence" in (
        detect_autopilot_loop(
            controller,
            controller.runs[0],
            action=candidate,
        )
        or ""
    )


def test_a_b_a_state_loop_is_detected() -> None:
    controller = _controller()
    controller.state_transitions = [
        BobaAutopilotStateTransitionV1(
            transition_id=f"transition_{index}",
            run_id=RUN_ID,
            sequence=index,
            from_state=source,
            to_state=target,
            transition_reason="Synthetic applied transition.",
            transition_status="applied",
        )
        for index, (source, target) in enumerate(
            [
                ("inspecting_project", "observer_required"),
                ("observer_required", "diagnosis_required"),
                ("diagnosis_required", "observer_required"),
            ],
            start=1,
        )
    ]
    assert "A-B-A" in (
        detect_autopilot_loop(controller, controller.runs[0]) or ""
    )


async def _clear_context(_project_id: str) -> dict[str, Any]:
    return {
        "rights_status": "owned",
        "safety_status": "clear_for_local_analysis",
        "source_media_references": [f"uploads/{PROJECT_ID}/source.mp4"],
        "source_media_read_only": True,
    }


async def _safe_module_invoker(
    module_name: str,
    operation_name: str,
    parameters: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": f"synthetic_{module_name}_v1",
        "project_id": parameters["project_id"],
        "operation": operation_name,
    }
    if module_name == "error_doctor":
        payload["diagnostic_cases"] = [{"diagnosis_status": "diagnosed"}]
    if module_name == "root_cause_analyzer":
        payload["analysis_cases"] = [{"analysis_status": "supported"}]
    return payload


def _engine(tmp_path: Path) -> BobaAutopilotControllerV1:
    return BobaAutopilotControllerV1(
        BobaMemoryStore(tmp_path / "boba"),
        context_provider=_clear_context,
        module_invoker=_safe_module_invoker,
        lock_owner="pytest",
    )


def test_create_run_captures_snapshot_without_executing_repair(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    controller = asyncio.run(engine.create_run(PROJECT_ID))
    run = controller.runs[-1]
    assert run.current_state == "inspecting_project"
    assert controller.module_invocations == []
    assert controller.planned_actions == []
    assert controller.signal_usage.direct_command_execution_used is False


def test_duplicate_active_execution_run_is_rejected(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    asyncio.run(engine.create_run(PROJECT_ID))
    with pytest.raises(ValidationError, match="conflicting"):
        asyncio.run(engine.create_run(PROJECT_ID))


def test_advisory_inspection_can_coexist_with_active_run(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    asyncio.run(engine.create_run(PROJECT_ID))
    controller = asyncio.run(
        engine.create_run(PROJECT_ID, control_mode="advisory_only")
    )
    assert len(controller.runs) == 2
    assert controller.runs[-1].control_mode == "advisory_only"


def test_unknown_budget_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Unknown Autopilot budget field"):
        asyncio.run(
            _engine(tmp_path).create_run(
                PROJECT_ID,
                recovery_budget={"unbounded_actions": 999},
            )
        )


@pytest.mark.parametrize(
    ("rights_status", "expected_state"),
    [
        ("unknown", "rights_review_required"),
        ("needs_permission", "rights_review_required"),
        ("blocked", "blocked"),
        ("permission_denied", "blocked"),
    ],
)
def test_rights_preflight_stops_automatic_progression(
    tmp_path: Path,
    rights_status: str,
    expected_state: str,
) -> None:
    async def context(_project_id: str) -> dict[str, Any]:
        return {
            "rights_status": rights_status,
            "safety_status": "clear_for_local_analysis",
        }

    engine = BobaAutopilotControllerV1(
        BobaMemoryStore(tmp_path / "boba"),
        context_provider=context,
        module_invoker=_safe_module_invoker,
    )
    controller = asyncio.run(engine.create_run(PROJECT_ID))
    action = asyncio.run(
        engine.plan_next_action(PROJECT_ID, controller.runs[-1].run_id)
    )
    updated = engine.inspect_run(PROJECT_ID, controller.runs[-1].run_id)
    assert updated.runs[-1].current_state == expected_state
    assert action.status == "blocked"
    assert updated.signal_usage.rights_bypass_used is False


@pytest.mark.parametrize(
    ("safety_status", "expected_state"),
    [("unknown", "safety_review_required"), ("blocked", "blocked")],
)
def test_safety_preflight_stops_automatic_progression(
    tmp_path: Path,
    safety_status: str,
    expected_state: str,
) -> None:
    async def context(_project_id: str) -> dict[str, Any]:
        return {"rights_status": "owned", "safety_status": safety_status}

    engine = BobaAutopilotControllerV1(
        BobaMemoryStore(tmp_path / "boba"),
        context_provider=context,
        module_invoker=_safe_module_invoker,
    )
    controller = asyncio.run(engine.create_run(PROJECT_ID))
    action = asyncio.run(
        engine.plan_next_action(PROJECT_ID, controller.runs[-1].run_id)
    )
    updated = engine.inspect_run(PROJECT_ID, controller.runs[-1].run_id)
    assert updated.runs[-1].current_state == expected_state
    assert action.status == "blocked"
    assert updated.signal_usage.safety_bypass_used is False


def test_safe_progression_runs_only_registered_read_only_action(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    advanced = asyncio.run(
        engine.advance_safe_read_only(PROJECT_ID, run_id, maximum_steps=1)
    )
    run = advanced.runs[-1]
    assert run.current_state == "diagnosis_required"
    assert len(advanced.module_invocations) == 1
    assert advanced.module_invocations[0].module_name == "observer"
    assert advanced.module_invocations[0].approval_verified is False


def test_safe_progression_pauses_on_malformed_target_result(
    tmp_path: Path,
) -> None:
    async def malformed_invoker(
        _module_name: str,
        _operation_name: str,
        _parameters: Any,
    ) -> dict[str, Any]:
        return {}

    engine = BobaAutopilotControllerV1(
        BobaMemoryStore(tmp_path / "boba"),
        context_provider=_clear_context,
        module_invoker=malformed_invoker,
    )
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    with pytest.raises(ValidationError, match="malformed"):
        action = asyncio.run(engine.plan_next_action(PROJECT_ID, run_id))
        asyncio.run(engine._execute_safe_read_only_action(PROJECT_ID, run_id, action.action_id))
    updated = engine.inspect_run(PROJECT_ID, run_id)
    assert updated.runs[-1].current_state == "paused"
    assert updated.incidents[-1].incident_type == "malformed_artifact"


def test_pause_continue_and_cancel_never_resume_workflow(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    paused = engine.pause_run(PROJECT_ID, run_id)
    assert paused.runs[-1].current_state == "paused"
    continued = engine.continue_run(PROJECT_ID, run_id)
    assert continued.runs[-1].current_state == "inspecting_project"
    cancelled = engine.cancel_run(PROJECT_ID, run_id)
    assert cancelled.runs[-1].current_state == "cancelled"
    assert cancelled.signal_usage.workflow_resume_used is False
    assert engine.store.load_boba_autopilot_lock(PROJECT_ID) is None


def test_event_sequences_are_monotonic_and_messages_bounded(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    engine.pause_run(PROJECT_ID, run_id)
    events = engine.store.load_boba_autopilot_events(PROJECT_ID, run_id)
    assert [item.sequence for item in events] == sorted(
        item.sequence for item in events
    )
    assert len({item.event_id for item in events}) == len(events)
    assert all(len(item.easy_message) <= 700 for item in events)
    assert all(len(item.technical_message) <= 1_200 for item in events)


def test_store_persists_controller_run_and_append_only_events(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    assert engine.store.boba_autopilot_controller_path(PROJECT_ID).is_file()
    assert engine.store.boba_autopilot_run_path(PROJECT_ID, run_id).is_file()
    assert engine.store.boba_autopilot_events_path(PROJECT_ID, run_id).is_file()
    persisted = engine.store.load_boba_autopilot_run(PROJECT_ID, run_id)
    assert persisted is not None
    assert persisted["run"]["run_id"] == run_id


def test_export_is_json_safe_and_truthful(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    exported = engine.export_run(PROJECT_ID, run_id)
    json.dumps(exported)
    assert exported["privacy"]["private_paths_excluded"] is True
    assert exported["privacy"]["direct_command_execution_used"] is False
    assert exported["privacy"]["workflow_resume_used"] is False
    assert exported["privacy"]["publication_used"] is False


def test_reset_rejects_active_run_and_preserves_upstream_artifacts(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    protected = engine.store.observer_path(PROJECT_ID)
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text('{"protected": true}', encoding="utf-8")
    with pytest.raises(ValidationError, match="Active Autopilot runs"):
        engine.reset_run_metadata(PROJECT_ID)
    engine.cancel_run(PROJECT_ID, created.runs[-1].run_id)
    assert engine.reset_run_metadata(PROJECT_ID) is True
    assert protected.is_file()


def test_budget_reset_requires_and_records_separate_human_approval(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    requested = engine.request_budget_reset(
        PROJECT_ID,
        run_id,
        reason="A separate bounded attempt is justified by new evidence.",
    )
    request = requested.planned_actions[-1]
    assert request.status == "awaiting_approval"
    old_budget_id = requested.runs[-1].budget_id
    approved = engine.record_human_decision(
        PROJECT_ID,
        run_id,
        decision="approve_budget_reset",
        reason="Human approved one new bounded budget.",
        reviewer_identity="reviewer@example.test",
        action_id=request.action_id,
    )
    assert approved.runs[-1].budget_id != old_budget_id
    assert any(item.budget_id == old_budget_id for item in approved.recovery_budgets)
    payload = json.dumps(approved.model_dump(mode="json"))
    assert "reviewer@example.test" not in payload


def test_budget_reset_requests_are_idempotent_and_do_not_reopen_history(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    reason = "New bounded evidence justifies another reviewed attempt."
    requested = engine.request_budget_reset(PROJECT_ID, run_id, reason=reason)
    first_request = requested.planned_actions[-1]
    duplicate = engine.request_budget_reset(PROJECT_ID, run_id, reason=reason)
    assert duplicate.planned_actions[-1].action_id == first_request.action_id
    assert len(duplicate.planned_actions) == len(requested.planned_actions)

    approved = engine.record_human_decision(
        PROJECT_ID,
        run_id,
        decision="approve_budget_reset",
        reason="Human approved one bounded reset.",
        reviewer_identity="budget_reviewer",
        action_id=first_request.action_id,
    )
    assert approved.planned_actions[-1].status == "succeeded"
    second = engine.request_budget_reset(PROJECT_ID, run_id, reason=reason)
    assert second.planned_actions[-1].action_id != first_request.action_id
    assert first_request.action_id in {
        item.action_id for item in second.planned_actions if item.status == "succeeded"
    }


def test_human_rejection_blocks_action_and_pauses_controller(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    created = asyncio.run(engine.create_run(PROJECT_ID))
    run_id = created.runs[-1].run_id
    action = asyncio.run(engine.plan_next_action(PROJECT_ID, run_id))
    rejected = engine.record_human_decision(
        PROJECT_ID,
        run_id,
        decision="reject_proposed_action",
        reason="The bounded action is not approved.",
        reviewer_identity="human_reviewer",
        action_id=action.action_id,
    )
    assert rejected.runs[-1].current_state == "paused"
    assert rejected.planned_actions[-1].status == "blocked"
    assert rejected.signal_usage.publication_used is False


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Autopilot Test",
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


def test_api_create_inspect_plan_events_export_cancel_and_reset(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot/runs",
            json={
                "control_mode": "safe_read_only_automatic",
                "trigger": "manual",
            },
        )
        assert created.status_code == 200, created.text
        run_id = created.json()["runs"][-1]["run_id"]
        loaded = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot"
        )
        planned = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot/runs/{run_id}/plan-next"
        )
        events = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot/runs/{run_id}/events"
        )
        exported = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot/export"
        )
        cancelled = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot/runs/{run_id}/cancel",
            json={"reason": "API test cancellation."},
        )
        reset = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot"
        )
    assert loaded.status_code == 200, loaded.text
    assert planned.status_code == 200, planned.text
    assert planned.json()["action_class"] == "future_gated"
    assert planned.json()["target_module"] == "rights_permission_gate"
    assert events.status_code == 200, events.text
    event_items = events.json()["events"]
    assert [item["sequence"] for item in event_items] == sorted(
        item["sequence"] for item in event_items
    )
    assert exported.status_code == 200, exported.text
    assert cancelled.status_code == 200, cancelled.text
    assert reset.status_code == 200, reset.text
    assert reset.json()["upstream_boba_artifacts_deleted"] is False
    assert reset.json()["source_media_deleted"] is False
    assert reset.json()["accepted_outputs_deleted"] is False


def test_api_create_route_does_not_execute_repair(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot/runs",
            json={"control_mode": "safe_read_only_automatic"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["module_invocations"] == []
    assert response.json()["signal_usage"]["direct_command_execution_used"] is False


@pytest.mark.parametrize(
    "unsafe_field",
    [
        "direct_command",
        "git_command",
        "ffmpeg_command",
        "workflow_resume",
        "publication",
        "upload",
        "deployment",
    ],
)
def test_api_rejects_arbitrary_execution_fields(
    app: FastAPI,
    tmp_path: Path,
    unsafe_field: str,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/autopilot/runs",
            json={
                "control_mode": "safe_read_only_automatic",
                unsafe_field: True,
            },
        )
    assert response.status_code == 422


def test_validator_self_check_passes_without_execution(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.direct_command_execution_used is False
    assert report.direct_git_execution_used is False
    assert report.direct_ffmpeg_execution_used is False
    assert report.network_access_used is False
    assert report.workflow_resume_used is False


def test_validator_runs_exactly_120_named_synthetic_scenarios(
    tmp_path: Path,
) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.scenario_count == 120
    assert report.passed_scenario_count == 120
    assert tuple(report.scenario_results) == SCENARIO_NAMES
    assert all(report.scenario_results.values())
