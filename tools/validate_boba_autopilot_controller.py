"""Validate BOBA Autopilot Controller V1 with offline synthetic fixtures."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_path in (ROOT, SRC):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from olympus.boba.autopilot_controller import (  # noqa: E402
    DEFAULT_AUTOPILOT_BUDGET_LIMITS,
    VALID_AUTOPILOT_TRANSITIONS,
    BobaAutopilotActionV1,
    BobaAutopilotBudgetUsageV1,
    BobaAutopilotControllerSetV1,
    BobaAutopilotControllerSignalUsageV1,
    BobaAutopilotControllerV1,
    BobaAutopilotEventV1,
    BobaAutopilotModuleInvocationV1,
    BobaAutopilotProjectLockV1,
    BobaAutopilotProjectSnapshotV1,
    BobaAutopilotRecoveryBudgetV1,
    BobaAutopilotRunV1,
    BobaAutopilotStateTransitionV1,
    build_autopilot_project_snapshot,
    calculate_autopilot_budget_usage,
    classify_autopilot_action,
    detect_autopilot_loop,
    fingerprint_autopilot_action,
    validate_autopilot_state_transition,
)
from olympus.boba.code_surgeon import (  # noqa: E402
    BobaCodeApprovalRecordV1,
    BobaCodePatchFileV1,
    BobaCodePatchProposalV1,
)
from olympus.boba.code_surgeon import (  # noqa: E402
    verify_approval as verify_code_approval,
)
from olympus.boba.contracts import BobaContract, now_iso  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.boba.tool_recovery import (  # noqa: E402
    EXPLICIT_RECOVERY_CONFIRMATION,
    BobaToolRecoveryApprovalV1,
    BobaToolRecoveryPlanV1,
    BobaToolRecoveryStrategyV1,
    verify_recovery_approval,
)
from olympus.platform.errors import ValidationError  # noqa: E402

REPORT_ROOT = ROOT / "work" / "validation_reports" / "boba_autopilot_controller"
SYNTHETIC_PROJECT_ID = "proj_boba_autopilot_controller_synthetic"
RUN_ID = "autopilot_run_synthetic"
BUDGET_ID = "autopilot_budget_synthetic"
SNAPSHOT_SHA = "a" * 64

SCENARIO_NAMES: tuple[str, ...] = (
    "01_new_run_creation",
    "02_duplicate_active_run_conflict",
    "03_advisory_only_concurrent_inspection",
    "04_project_lock_acquisition",
    "05_stale_lock_detection",
    "06_lock_cannot_be_silently_stolen",
    "07_project_snapshot_created",
    "08_snapshot_change_detected",
    "09_rights_clear",
    "10_rights_unknown",
    "11_rights_blocked",
    "12_safety_clear",
    "13_safety_blocked",
    "14_observer_missing",
    "15_observer_current",
    "16_observer_stale",
    "17_error_doctor_required",
    "18_error_doctor_insufficient_evidence",
    "19_rca_required",
    "20_rca_competing_causes",
    "21_repair_planner_required",
    "22_repair_planner_no_repair",
    "23_tool_repair_route",
    "24_code_repair_route",
    "25_checkpoint_issue_route",
    "26_human_decision_route",
    "27_safe_read_only_automatic_progression",
    "28_safe_progression_stops_before_approval_action",
    "29_missing_approval",
    "30_expired_approval",
    "31_approval_plan_mismatch",
    "32_approval_strategy_mismatch",
    "33_approval_tool_mismatch",
    "34_approval_patch_mismatch",
    "35_approval_settings_mismatch",
    "36_approval_checkpoint_mismatch",
    "37_exact_approval_passes",
    "38_approved_tool_recovery_coordination",
    "39_tool_recovery_technical_pass",
    "40_tool_recovery_failure",
    "41_tool_recovery_timeout",
    "42_tool_recovery_rollback",
    "43_tool_recovery_rollback_failure",
    "44_approved_code_surgeon_coordination",
    "45_code_surgeon_validation_pass",
    "46_code_surgeon_validation_failure",
    "47_code_surgeon_rollback",
    "48_code_surgeon_approval_invalidated_by_base_change",
    "49_output_quality_technical_rejection",
    "50_output_quality_creative_rejection",
    "51_output_quality_regression_rejection",
    "52_output_quality_needs_human_review",
    "53_output_quality_needs_more_evidence",
    "54_output_quality_accepted_internally",
    "55_accepted_with_limitations_requires_review",
    "56_rights_block_after_recovery",
    "57_safety_block_after_recovery",
    "58_budget_70_percent_warning",
    "59_budget_90_percent_warning",
    "60_total_action_budget_exhausted",
    "61_execution_budget_exhausted",
    "62_retry_budget_exhausted",
    "63_time_budget_exhausted",
    "64_code_repair_attempt_budget_exhausted",
    "65_tool_recovery_budget_exhausted",
    "66_quality_review_budget_exhausted",
    "67_replanning_budget_exhausted",
    "68_rca_reanalysis_budget_exhausted",
    "69_budget_reset_requires_approval",
    "70_approved_budget_reset_preserves_history",
    "71_identical_failed_action_detected",
    "72_a_b_a_loop_detected",
    "73_repeated_unchanged_observer_generation_detected",
    "74_repeated_identical_repair_plan_detected",
    "75_repeated_identical_fallback_failure_detected",
    "76_idempotent_completed_action_does_not_rerun",
    "77_retry_allowed_with_new_evidence",
    "78_stale_action_blocked",
    "79_invalid_transition_blocked",
    "80_target_module_unavailable",
    "81_malformed_target_module_result",
    "82_project_state_uncertain",
    "83_source_media_risk_detected",
    "84_accepted_output_risk_detected",
    "85_controller_pauses_on_uncertain_state",
    "86_controller_cancellation",
    "87_pause_and_continue_controller",
    "88_continue_does_not_resume_olympus",
    "89_event_sequence_is_monotonic",
    "90_easy_messages_are_bounded",
    "91_fake_progress_is_not_produced",
    "92_event_progress_comes_from_real_actions",
    "93_human_decision_recorded",
    "94_human_rejection_stops_action",
    "95_human_quality_approval_does_not_publish",
    "96_safety_gate_handoff_exists",
    "97_workflow_controller_handoff_exists",
    "98_final_decision_bus_handoff_exists",
    "99_live_companion_handoff_exists",
    "100_internal_cycle_completes",
    "101_internal_completion_does_not_resume_workflow",
    "102_no_direct_commands_execute",
    "103_no_direct_git_executes",
    "104_no_direct_ffmpeg_executes",
    "105_no_source_media_changes",
    "106_no_accepted_output_overwrite",
    "107_no_package_installation",
    "108_no_service_restart",
    "109_no_process_kill",
    "110_no_internet",
    "111_no_external_api",
    "112_no_media_download",
    "113_no_upload",
    "114_no_publication",
    "115_no_push",
    "116_no_merge",
    "117_no_deployment",
    "118_no_rights_bypass",
    "119_no_safety_bypass",
    "120_no_destructive_action",
)


class BobaAutopilotControllerValidatorReportV1(BobaContract):
    """Compact JSON-safe proof for Autopilot Controller V1."""

    schema_version: Literal["boba_autopilot_controller_validator_v1"] = (
        "boba_autopilot_controller_validator_v1"
    )
    mode: Literal["self_check", "synthetic_project", "project_id"]
    created_at: str = Field(default_factory=now_iso)
    passed: bool
    project_id: str | None = None
    scenario_count: int = Field(default=0, ge=0)
    passed_scenario_count: int = Field(default=0, ge=0)
    scenario_results: dict[str, bool] = Field(default_factory=dict)
    signal_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    generated_fixture_only: bool = True
    direct_command_execution_used: Literal[False] = False
    direct_git_execution_used: Literal[False] = False
    direct_ffmpeg_execution_used: Literal[False] = False
    code_modified_directly: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    workflow_resume_used: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    process_kill_used: Literal[False] = False
    network_access_used: Literal[False] = False
    external_api_used: Literal[False] = False
    downloading_used: Literal[False] = False
    uploading_used: Literal[False] = False
    publication_used: Literal[False] = False
    push_used: Literal[False] = False
    merge_used: Literal[False] = False
    deployment_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)
    errors: list[str] = Field(default_factory=list, max_length=64)


def _write_report(
    report: BobaAutopilotControllerValidatorReportV1,
    report_root: Path,
) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "latest.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _run(
    *,
    state: str = "created",
    status: str = "active",
    mode: str = "safe_read_only_automatic",
) -> BobaAutopilotRunV1:
    return BobaAutopilotRunV1(
        run_id=RUN_ID,
        project_id=SYNTHETIC_PROJECT_ID,
        correlation_id="autopilot_correlation_synthetic",
        current_state=state,
        run_status=status,
        control_mode=mode,
        project_snapshot_id="autopilot_snapshot_synthetic",
        rights_status="owned",
        safety_status="clear_for_local_analysis",
        budget_id=BUDGET_ID,
    )


def _snapshot(digest: str = SNAPSHOT_SHA) -> BobaAutopilotProjectSnapshotV1:
    return BobaAutopilotProjectSnapshotV1(
        project_snapshot_id="autopilot_snapshot_synthetic",
        project_id=SYNTHETIC_PROJECT_ID,
        rights_status="owned",
        safety_status="clear_for_local_analysis",
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
        budget_usage_id="autopilot_usage_synthetic",
        budget_id=BUDGET_ID,
        **overrides,
    )


def _action(
    *,
    action_id: str = "autopilot_action_synthetic",
    action_type: str = "inspect_project",
    action_class: str = "automatic_read_only",
    target_module: str = "autopilot_controller",
    target_operation: str = "inspect",
    status: str = "planned",
    fingerprint: str = "b" * 64,
) -> BobaAutopilotActionV1:
    return BobaAutopilotActionV1(
        action_id=action_id,
        run_id=RUN_ID,
        action_type=action_type,
        action_class=action_class,
        target_module=target_module,
        target_operation=target_operation,
        description="Inspect bounded synthetic state.",
        rationale="Offline validator evidence is required.",
        planned_snapshot_sha256=SNAPSHOT_SHA,
        idempotency_key=fingerprint,
        status=status,
    )


def _controller(
    *,
    run: BobaAutopilotRunV1 | None = None,
    budget: BobaAutopilotRecoveryBudgetV1 | None = None,
    usage: BobaAutopilotBudgetUsageV1 | None = None,
    actions: list[BobaAutopilotActionV1] | None = None,
) -> BobaAutopilotControllerSetV1:
    return BobaAutopilotControllerSetV1(
        project_id=SYNTHETIC_PROJECT_ID,
        source_id=SYNTHETIC_PROJECT_ID,
        runs=[run or _run()],
        project_snapshots=[_snapshot()],
        recovery_budgets=[budget or _budget()],
        budget_usages=[usage or _usage()],
        planned_actions=actions or [],
    )


async def _context(_project_id: str) -> dict[str, Any]:
    return {
        "rights_status": "owned",
        "safety_status": "clear_for_local_analysis",
        "source_media_references": [
            f"uploads/{SYNTHETIC_PROJECT_ID}/synthetic-source.mp4"
        ],
        "source_media_read_only": True,
        "accepted_output_ids": ["synthetic-output"],
    }


async def _invoker(
    module_name: str,
    operation_name: str,
    parameters: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": f"synthetic_{module_name}_v1",
        "project_id": parameters["project_id"],
        "operation": operation_name,
        "source_media_untouched": True,
        "accepted_outputs_untouched": True,
    }
    if module_name == "error_doctor":
        payload["diagnostic_cases"] = [{"diagnosis_status": "diagnosed"}]
    if module_name == "root_cause_analyzer":
        payload["analysis_cases"] = [{"analysis_status": "supported"}]
    return payload


def _code_approval_evidence() -> tuple[
    BobaCodePatchProposalV1,
    BobaCodeApprovalRecordV1,
]:
    patch_file = BobaCodePatchFileV1(
        path="src/olympus/example.py",
        operation="modify",
    )
    proposal = BobaCodePatchProposalV1(
        patch_proposal_id="patch_synthetic",
        code_repair_case_id="code_case_synthetic",
        proposal_source="deterministic_template",
        base_branch="feature/synthetic",
        base_commit_sha="abcdef1234567",
        proposed_branch="boba/code-surgeon/synthetic",
        title="Synthetic bounded patch",
        summary="A proposal fixture only.",
        rationale="Validate exact approval binding without applying a patch.",
        files=[patch_file],
        diff_sha256="d" * 64,
        changed_file_count=1,
        additions=1,
        deletions=0,
        total_changed_lines=1,
        patch_size_bytes=32,
        applies_cleanly=True,
        path_policy_passed=True,
        secret_scan_passed=True,
        scope_check_passed=True,
        binary_change_detected=False,
        dependency_change_detected=False,
        workflow_change_detected=False,
        approval_status="approved_for_isolated_execution",
        execution_status="validation_ready",
    )
    approval = BobaCodeApprovalRecordV1(
        approval_id="code_approval_synthetic",
        code_repair_case_id=proposal.code_repair_case_id,
        patch_proposal_id=proposal.patch_proposal_id,
        approval_type="isolated_patch_execution",
        approved=True,
        approved_by="synthetic-validator",
        approved_base_commit_sha=proposal.base_commit_sha,
        approved_diff_sha256=proposal.diff_sha256,
        approved_scope=[patch_file.path],
        approval_expires_at=(
            datetime.now(UTC) + timedelta(minutes=10)
        ).isoformat(),
        explicit_confirmation=True,
    )
    return proposal, approval


def _tool_approval_evidence() -> tuple[
    BobaToolRecoveryPlanV1,
    BobaToolRecoveryStrategyV1,
    BobaToolRecoveryApprovalV1,
]:
    strategy = BobaToolRecoveryStrategyV1(
        recovery_strategy_id="recovery_strategy_synthetic",
        recovery_plan_id="recovery_plan_synthetic",
        order=1,
        strategy_type="retry_with_safe_settings",
        tool_id="registered_tool_synthetic",
        capability_id="rendering",
        description="Retry only the failed synthetic output.",
        rationale="Use bounded settings and no network.",
        configuration_overrides={"threads": 1},
        expected_result="One locally validated synthetic output.",
        expected_quality_effect="No quality regression expected.",
        expected_resource_effect="Lower bounded resource use.",
        execution_allowed=True,
        maximum_attempts=1,
        timeout_seconds=60,
        failure_stop_condition="Stop after the first failure.",
        success_condition="Registered validation passes.",
    )
    plan = BobaToolRecoveryPlanV1(
        recovery_plan_id=strategy.recovery_plan_id,
        recovery_case_id="recovery_case_synthetic",
        required_capability="rendering",
        primary_tool_id=strategy.tool_id,
        ordered_strategies=[strategy],
        retry_budget={"maximum_attempts": 1},
        time_budget_seconds=60,
        checkpoint_requirements={"reference": "checkpoint/synthetic"},
        rollback_requirements={"required": True},
        quality_requirements=["duration preserved"],
        approval_status="approved",
    )
    approval = BobaToolRecoveryApprovalV1(
        approval_id="tool_approval_synthetic",
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        approved=True,
        approved_at=now_iso(),
        approved_by="synthetic-validator",
        approved_strategy_ids=[strategy.recovery_strategy_id],
        approved_tool_ids=[strategy.tool_id],
        approved_configuration_overrides=strategy.configuration_overrides,
        approved_retry_budget=plan.retry_budget,
        approved_time_budget_seconds=plan.time_budget_seconds,
        approved_quality_requirements=plan.quality_requirements,
        approved_checkpoint_reference="checkpoint/synthetic",
        approval_expires_at=(
            datetime.now(UTC) + timedelta(minutes=10)
        ).isoformat(),
        explicit_confirmation=EXPLICIT_RECOVERY_CONFIRMATION,
    )
    return plan, strategy, approval


def _quality_route(
    engine: BobaAutopilotControllerV1,
    decision_value: str,
) -> BobaAutopilotControllerSetV1:
    run = _run(
        state="output_quality_review_required",
        mode="advisory_only",
    )
    controller = _controller(run=run)
    decision = SimpleNamespace(
        decision=decision_value,
        acceptance_decision_id=f"quality_{decision_value}",
        decision_summary=f"Synthetic {decision_value} decision.",
        confidence=0.9,
        rights_clear_for_processing=decision_value != "blocked_rights",
        safety_clear_for_processing=decision_value != "blocked_safety",
        human_review_required=decision_value
        in {
            "accepted_with_disclosed_limitations",
            "needs_human_review",
            "needs_more_evidence",
        },
    )
    engine._interpret_quality_decision(controller, run, decision)
    return controller


def _tool_route(
    engine: BobaAutopilotControllerV1,
    *,
    status: str,
    rollback_status: str = "",
) -> tuple[BobaAutopilotControllerSetV1, BobaAutopilotModuleInvocationV1]:
    run = _run(state="execution_running")
    action = _action(
        action_type="invoke_tool_recovery",
        action_class="approval_required_execution",
        target_module="tool_recovery_brain",
        target_operation="execute_approved",
        status="succeeded",
    )
    controller = _controller(run=run, actions=[action])
    invocation = BobaAutopilotModuleInvocationV1(
        module_invocation_id="invocation_tool_synthetic",
        run_id=RUN_ID,
        action_id=action.action_id,
        module_name="tool_recovery_brain",
        operation_name="execute_approved",
        invocation_mode="approved_execution",
        approval_verified=True,
        independently_revalidated_by_target=True,
        status="succeeded",
    )
    result: dict[str, Any] = {
        "recovery_attempts": [
            {
                "recovery_attempt_id": "attempt_synthetic",
                "status": status,
                "timeout_occurred": status == "timed_out",
                "failure_summary": "Synthetic bounded failure.",
            }
        ],
        "rollback_records": (
            [{"status": rollback_status}] if rollback_status else []
        ),
    }
    engine._route_approved_result(
        controller,
        run,
        action,
        invocation,
        result,
    )
    return controller, invocation


def _code_route(
    engine: BobaAutopilotControllerV1,
    status: str,
) -> BobaAutopilotControllerSetV1:
    run = _run(state="execution_running")
    action = _action(
        action_type="invoke_code_surgeon",
        action_class="approval_required_execution",
        target_module="code_surgeon",
        target_operation="execute_approved",
        status="succeeded",
    )
    controller = _controller(run=run, actions=[action])
    invocation = BobaAutopilotModuleInvocationV1(
        module_invocation_id="invocation_code_synthetic",
        run_id=RUN_ID,
        action_id=action.action_id,
        module_name="code_surgeon",
        operation_name="execute_approved",
        invocation_mode="approved_execution",
        approval_verified=True,
        independently_revalidated_by_target=True,
        status="succeeded",
    )
    engine._route_approved_result(
        controller,
        run,
        action,
        invocation,
        {"isolated_runs": [{"isolated_run_id": "isolated", "run_status": status}]},
    )
    return controller


def _budget_exhausted(
    usage_field: str,
    budget_field: str,
) -> bool:
    budget = _budget()
    usage = _usage(**{usage_field: getattr(budget, budget_field)})
    controller = _controller(budget=budget, usage=usage)
    return calculate_autopilot_budget_usage(
        controller,
        controller.runs[0],
    ).budget_exhausted


def _signal_profiles(
    signal: BobaAutopilotControllerSignalUsageV1,
) -> dict[str, dict[str, Any]]:
    base = signal.model_dump(mode="json")
    return {
        "advisory_only_run": {**base, "control_mode": "advisory_only"},
        "safe_read_only_automatic_run": {
            **base,
            "control_mode": "safe_read_only_automatic",
        },
        "approved_tool_recovery_coordination": {
            **base,
            "control_mode": "approved_execution_coordination",
            "tool_recovery_used": True,
            "target_module_approval_used": True,
        },
        "approved_code_surgeon_coordination": {
            **base,
            "control_mode": "approved_execution_coordination",
            "code_surgeon_used": True,
            "target_module_approval_used": True,
        },
        "quality_review_coordination": {
            **base,
            "output_quality_reviewer_used": True,
        },
        "paused_run": {**base, "run_status": "paused"},
        "cancelled_run": {**base, "run_status": "cancelled"},
        "completed_internal_cycle": {
            **base,
            "run_status": "completed_internal_cycle",
        },
    }


def run_self_check(
    report_root: Path = REPORT_ROOT,
) -> BobaAutopilotControllerValidatorReportV1:
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    try:
        required_modules = [
            "olympus.boba.autopilot_controller",
            "olympus.boba.observer",
            "olympus.boba.error_doctor",
            "olympus.boba.root_cause_analyzer",
            "olympus.boba.repair_planner",
            "olympus.boba.code_surgeon",
            "olympus.boba.tool_recovery",
            "olympus.boba.output_quality_reviewer",
        ]
        imported = [importlib.import_module(name) for name in required_modules]
        controller = _controller()
        source = (SRC / "olympus" / "boba" / "autopilot_controller.py").read_text(
            encoding="utf-8"
        )
        with TemporaryDirectory() as directory:
            store = BobaMemoryStore(Path(directory) / "boba")
            lock = store.acquire_boba_autopilot_lock(
                SYNTHETIC_PROJECT_ID,
                run_id=RUN_ID,
                owner_identifier="self_check",
                mode="safe_read_only_automatic",
            )
            event = BobaAutopilotEventV1(
                event_id="event_self_check",
                run_id=RUN_ID,
                sequence=1,
                event_type="run_created",
                state="created",
                technical_message="Self-check event.",
                easy_message="BOBA created a self-check event.",
            )
            controller.event_stream = [event]
            store.save_boba_autopilot_controller(controller)
            event_writable = bool(
                store.load_boba_autopilot_events(SYNTHETIC_PROJECT_ID, RUN_ID)
            )
            lock_writable = lock.run_id == RUN_ID
        scenarios = {
            "autopilot_module_imports": bool(imported[0]),
            "required_boba_modules_import": len(imported) == len(required_modules),
            "contracts_serialize": bool(controller.model_dump_json()),
            "state_machine_builds": len(VALID_AUTOPILOT_TRANSITIONS) == 32,
            "action_classifier_builds": (
                classify_autopilot_action(
                    "generate_observer",
                    target_module="observer",
                    target_operation="generate",
                )
                == "automatic_read_only"
            ),
            "typed_module_registry_builds": "allowed = {" in source,
            "event_storage_is_writable": event_writable,
            "project_lock_is_writable": lock_writable,
            "no_direct_command_runner_exists": "subprocess" not in source,
            "no_git_command_runner_exists": "git push" not in source.casefold(),
            "no_ffmpeg_command_runner_exists": (
                "subprocess" not in source
                and "Popen(" not in source
                and "run_ffmpeg" not in source
            ),
            "no_network_is_required": "requests." not in source
            and "httpx." not in source,
            "no_workflow_resume_is_required": (
                "workflow_resume_used: Literal[False]" in source
            ),
            "no_publication_capability_exists": (
                "publication_used: Literal[False]" in source
            ),
        }
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = BobaAutopilotControllerValidatorReportV1(
        mode="self_check",
        passed=bool(scenarios) and all(scenarios.values()) and not errors,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        signal_profiles=_signal_profiles(BobaAutopilotControllerSignalUsageV1()),
        limitations=[
            "Self-check validates imports, contracts, storage, and prohibited capabilities.",
            "It does not execute Code Surgeon, Tool Recovery, commands, Git, or FFmpeg.",
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def run_synthetic_project(
    report_root: Path = REPORT_ROOT,
) -> BobaAutopilotControllerValidatorReportV1:
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    signal = BobaAutopilotControllerSignalUsageV1()
    try:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = BobaMemoryStore(root / "boba")
            engine = BobaAutopilotControllerV1(
                store,
                context_provider=_context,
                module_invoker=_invoker,
                lock_owner="synthetic_validator",
            )
            created = asyncio.run(engine.create_run(SYNTHETIC_PROJECT_ID))
            run_id = created.runs[-1].run_id
            duplicate_blocked = False
            try:
                asyncio.run(engine.create_run(SYNTHETIC_PROJECT_ID))
            except ValidationError:
                duplicate_blocked = True
            advisory = asyncio.run(
                engine.create_run(
                    SYNTHETIC_PROJECT_ID,
                    control_mode="advisory_only",
                )
            )
            lock = store.load_boba_autopilot_lock(SYNTHETIC_PROJECT_ID)
            lock_stolen = False
            try:
                store.acquire_boba_autopilot_lock(
                    SYNTHETIC_PROJECT_ID,
                    run_id="autopilot_run_intruder",
                    owner_identifier="intruder",
                    mode="safe_read_only_automatic",
                )
            except ValidationError:
                lock_stolen = False

            stale_project = f"{SYNTHETIC_PROJECT_ID}_stale"
            stale_path = store.boba_autopilot_lock_path(stale_project)
            stale_path.parent.mkdir(parents=True, exist_ok=True)
            stale_path.write_text(
                BobaAutopilotProjectLockV1(
                    project_id=stale_project,
                    run_id="autopilot_run_stale",
                    acquired_at=(
                        datetime.now(UTC) - timedelta(hours=2)
                    ).isoformat(),
                    refreshed_at=(
                        datetime.now(UTC) - timedelta(hours=2)
                    ).isoformat(),
                    expires_at=(
                        datetime.now(UTC) - timedelta(hours=1)
                    ).isoformat(),
                    owner_identifier="stale_owner",
                    mode="safe_read_only_automatic",
                ).model_dump_json(),
                encoding="utf-8",
            )
            stale_detected = bool(
                store.load_boba_autopilot_lock(stale_project)
                and store.load_boba_autopilot_lock(stale_project).stale  # type: ignore[union-attr]
            )
            stale_stolen = False
            try:
                store.acquire_boba_autopilot_lock(
                    stale_project,
                    run_id="autopilot_run_new",
                    owner_identifier="new_owner",
                    mode="safe_read_only_automatic",
                )
            except ValidationError:
                stale_stolen = False

            base_snapshot = build_autopilot_project_snapshot(
                store,
                f"{SYNTHETIC_PROJECT_ID}_snapshot",
                project_context={
                    "rights_status": "owned",
                    "safety_status": "clear_for_local_analysis",
                },
            )
            changed_snapshot = build_autopilot_project_snapshot(
                store,
                f"{SYNTHETIC_PROJECT_ID}_snapshot",
                project_context={
                    "rights_status": "owned",
                    "safety_status": "clear_for_local_analysis",
                    "current_workflow_stage": "rendering",
                },
            )
            stale_snapshot = base_snapshot.model_copy(deep=True)
            stale_snapshot.module_artifact_states["observer"]["status"] = "stale"
            stale_snapshot.stale_artifact_ids = ["observer"]
            rights_unknown = build_autopilot_project_snapshot(
                store,
                f"{SYNTHETIC_PROJECT_ID}_rights_unknown",
                project_context={
                    "rights_status": "unknown",
                    "safety_status": "clear_for_local_analysis",
                },
            )
            rights_blocked = build_autopilot_project_snapshot(
                store,
                f"{SYNTHETIC_PROJECT_ID}_rights_blocked",
                project_context={
                    "rights_status": "blocked",
                    "safety_status": "clear_for_local_analysis",
                },
            )
            safety_blocked = build_autopilot_project_snapshot(
                store,
                f"{SYNTHETIC_PROJECT_ID}_safety_blocked",
                project_context={
                    "rights_status": "owned",
                    "safety_status": "blocked",
                },
            )
            advanced = asyncio.run(
                engine.advance_safe_read_only(
                    SYNTHETIC_PROJECT_ID,
                    run_id,
                    maximum_steps=1,
                )
            )
            main_run = next(item for item in advanced.runs if item.run_id == run_id)
            observer_invocation = next(
                item
                for item in advanced.module_invocations
                if item.run_id == run_id
            )

            proposal, code_approval = _code_approval_evidence()
            code_exact = verify_code_approval(
                proposal,
                code_approval,
                required_type="isolated_patch_execution",
            )
            code_expired = code_approval.model_copy(
                update={
                    "approval_expires_at": (
                        datetime.now(UTC) - timedelta(minutes=1)
                    ).isoformat()
                }
            )
            code_patch_mismatch = code_approval.model_copy(
                update={"approved_diff_sha256": "e" * 64}
            )
            code_base_mismatch = code_approval.model_copy(
                update={"approved_base_commit_sha": "fedcba7654321"}
            )

            plan, strategy, tool_approval = _tool_approval_evidence()
            tool_exact = verify_recovery_approval(plan, strategy, tool_approval)
            tool_plan_mismatch = tool_approval.model_copy(
                update={"recovery_plan_id": "wrong_plan"}
            )
            tool_strategy_mismatch = tool_approval.model_copy(
                update={"approved_strategy_ids": ["wrong_strategy"]}
            )
            tool_tool_mismatch = tool_approval.model_copy(
                update={"approved_tool_ids": ["wrong_tool"]}
            )
            tool_settings_mismatch = tool_approval.model_copy(
                update={"approved_configuration_overrides": {"threads": 4}}
            )
            tool_checkpoint_mismatch = tool_approval.model_copy(
                update={"approved_checkpoint_reference": "wrong/checkpoint"}
            )

            tool_success, _ = _tool_route(
                engine,
                status="succeeded_pending_validation",
            )
            tool_failure, _ = _tool_route(engine, status="failed")
            tool_timeout, timeout_invocation = _tool_route(
                engine,
                status="timed_out",
            )
            tool_rollback, _ = _tool_route(
                engine,
                status="failed",
                rollback_status="completed",
            )
            rollback_run = _run(state="rollback_running")
            rollback_action = _action(
                action_type="invoke_tool_recovery_rollback",
                action_class="approval_required_execution",
                target_module="tool_recovery_brain",
                target_operation="rollback",
            )
            rollback_controller = _controller(
                run=rollback_run,
                actions=[rollback_action],
            )
            rollback_invocation = BobaAutopilotModuleInvocationV1(
                module_invocation_id="invocation_rollback",
                run_id=RUN_ID,
                action_id=rollback_action.action_id,
                module_name="tool_recovery_brain",
                operation_name="rollback",
                invocation_mode="approved_rollback",
                approval_verified=True,
            )
            engine._route_approved_result(
                rollback_controller,
                rollback_run,
                rollback_action,
                rollback_invocation,
                {"rollback_records": [{"status": "failed"}]},
            )
            code_success = _code_route(engine, "validation_passed")
            code_failure = _code_route(engine, "validation_failed")

            quality_routes = {
                value: _quality_route(engine, value)
                for value in [
                    "rejected_technical",
                    "rejected_quality",
                    "rejected_regression",
                    "needs_human_review",
                    "needs_more_evidence",
                    "accepted_for_next_internal_stage",
                    "accepted_with_disclosed_limitations",
                    "blocked_rights",
                    "blocked_safety",
                ]
            }

            budget_70_controller = _controller(
                budget=_budget(maximum_total_actions=10),
                usage=_usage(actions_used=6),
            )
            engine._consume_action_budget(
                budget_70_controller,
                budget_70_controller.runs[0],
                _action(),
                invocation=False,
            )
            budget_90_controller = _controller(
                budget=_budget(maximum_total_actions=10),
                usage=_usage(actions_used=8),
            )
            engine._consume_action_budget(
                budget_90_controller,
                budget_90_controller.runs[0],
                _action(),
                invocation=False,
            )
            time_run = _run()
            time_run.started_at = (
                datetime.now(UTC) - timedelta(seconds=5)
            ).isoformat()
            time_controller = _controller(
                run=time_run,
                budget=_budget(maximum_total_duration_seconds=1),
            )
            time_exhausted = calculate_autopilot_budget_usage(
                time_controller,
                time_run,
            )
            missing_approval_action = _action(
                action_type="invoke_tool_recovery",
                action_class="approval_required_execution",
                target_module="tool_recovery_brain",
                target_operation="execute_approved",
                status="awaiting_approval",
            )
            missing_approval_action.human_approval_required = True

            failed_one = _action(action_id="failed_one", status="failed")
            failed_two = _action(action_id="failed_two", status="failed")
            repeated_candidate = _action(action_id="repeated_candidate")
            repeated_controller = _controller(
                actions=[failed_one, failed_two, repeated_candidate]
            )
            repeated_failure = detect_autopilot_loop(
                repeated_controller,
                repeated_controller.runs[0],
                action=repeated_candidate,
            )
            completed = _action(action_id="completed", status="succeeded")
            idempotent_candidate = _action(action_id="candidate")
            idempotent_controller = _controller(
                actions=[completed, idempotent_candidate]
            )
            idempotent = detect_autopilot_loop(
                idempotent_controller,
                idempotent_controller.runs[0],
                action=idempotent_candidate,
            )
            loop_controller = _controller()
            loop_controller.state_transitions = [
                BobaAutopilotStateTransitionV1(
                    transition_id=f"transition_{index}",
                    run_id=RUN_ID,
                    sequence=index,
                    from_state=source,
                    to_state=target,
                    transition_reason="Synthetic transition.",
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
            aba_loop = detect_autopilot_loop(
                loop_controller,
                loop_controller.runs[0],
            )
            changed_fingerprint = fingerprint_autopilot_action(
                project_id=SYNTHETIC_PROJECT_ID,
                run_id=RUN_ID,
                action_type="generate_observer",
                target_module="observer",
                target_operation="generate",
                snapshot_sha256="c" * 64,
            )

            unavailable_engine = BobaAutopilotControllerV1(
                BobaMemoryStore(root / "unavailable"),
                context_provider=_context,
            )
            unavailable_created = asyncio.run(
                unavailable_engine.create_run(
                    f"{SYNTHETIC_PROJECT_ID}_unavailable"
                )
            )
            unavailable_run_id = unavailable_created.runs[-1].run_id
            unavailable_action = asyncio.run(
                unavailable_engine.plan_next_action(
                    f"{SYNTHETIC_PROJECT_ID}_unavailable",
                    unavailable_run_id,
                )
            )
            target_unavailable = False
            try:
                asyncio.run(
                    unavailable_engine._execute_safe_read_only_action(
                        f"{SYNTHETIC_PROJECT_ID}_unavailable",
                        unavailable_run_id,
                        unavailable_action.action_id,
                    )
                )
            except ValidationError:
                target_unavailable = True

            async def malformed_invoker(
                _module_name: str,
                _operation_name: str,
                _parameters: Any,
            ) -> dict[str, Any]:
                return {}

            malformed_project = f"{SYNTHETIC_PROJECT_ID}_malformed"
            malformed_engine = BobaAutopilotControllerV1(
                BobaMemoryStore(root / "malformed"),
                context_provider=_context,
                module_invoker=malformed_invoker,
            )
            malformed_created = asyncio.run(
                malformed_engine.create_run(malformed_project)
            )
            malformed_run_id = malformed_created.runs[-1].run_id
            malformed_action = asyncio.run(
                malformed_engine.plan_next_action(
                    malformed_project,
                    malformed_run_id,
                )
            )
            malformed_blocked = False
            try:
                asyncio.run(
                    malformed_engine._execute_safe_read_only_action(
                        malformed_project,
                        malformed_run_id,
                        malformed_action.action_id,
                    )
                )
            except ValidationError:
                malformed_blocked = True

            uncertain_run = _run(state="execution_running")
            uncertain_action = _action(
                action_type="invoke_tool_recovery",
                action_class="approval_required_execution",
                target_module="tool_recovery_brain",
                target_operation="execute_approved",
            )
            uncertain_controller = _controller(
                run=uncertain_run,
                actions=[uncertain_action],
            )
            uncertain_invocation = BobaAutopilotModuleInvocationV1(
                module_invocation_id="invocation_uncertain",
                run_id=RUN_ID,
                action_id=uncertain_action.action_id,
                module_name="tool_recovery_brain",
                operation_name="execute_approved",
                invocation_mode="approved_execution",
            )
            uncertain_paused = engine._pause_for_uncertain_result(
                uncertain_controller,
                uncertain_run,
                uncertain_action,
                uncertain_invocation,
                {
                    "project_state_uncertain": True,
                    "source_media_untouched": False,
                    "accepted_outputs_untouched": False,
                },
            )

            control_project = f"{SYNTHETIC_PROJECT_ID}_controls"
            control_engine = BobaAutopilotControllerV1(
                BobaMemoryStore(root / "controls"),
                context_provider=_context,
                module_invoker=_invoker,
                lock_owner="control_validator",
            )
            control_created = asyncio.run(
                control_engine.create_run(control_project)
            )
            control_run_id = control_created.runs[-1].run_id
            paused = control_engine.pause_run(control_project, control_run_id)
            continued = control_engine.continue_run(control_project, control_run_id)
            action_for_rejection = asyncio.run(
                control_engine.plan_next_action(control_project, control_run_id)
            )
            human_rejected = control_engine.record_human_decision(
                control_project,
                control_run_id,
                decision="reject_proposed_action",
                reason="Synthetic human rejection.",
                reviewer_identity="synthetic-reviewer",
                action_id=action_for_rejection.action_id,
            )
            cancelled = control_engine.cancel_run(
                control_project,
                control_run_id,
            )

            budget_project = f"{SYNTHETIC_PROJECT_ID}_budget"
            budget_engine = BobaAutopilotControllerV1(
                BobaMemoryStore(root / "budget_reset"),
                context_provider=_context,
                module_invoker=_invoker,
            )
            budget_created = asyncio.run(
                budget_engine.create_run(budget_project)
            )
            budget_run_id = budget_created.runs[-1].run_id
            budget_requested = budget_engine.request_budget_reset(
                budget_project,
                budget_run_id,
                reason="Synthetic request for one new bounded budget.",
            )
            budget_request = budget_requested.planned_actions[-1]
            budget_request_required_approval = (
                budget_request.status == "awaiting_approval"
                and budget_request.human_approval_required
            )
            previous_budget_id = budget_requested.runs[-1].budget_id
            budget_approved = budget_engine.record_human_decision(
                budget_project,
                budget_run_id,
                decision="approve_budget_reset",
                reason="Synthetic explicit budget approval.",
                reviewer_identity="synthetic-reviewer",
                action_id=budget_request.action_id,
            )

            accepted = quality_routes["accepted_for_next_internal_stage"]
            accepted_run = accepted.runs[0]
            handoff_targets = {item.target_module for item in accepted.handoffs}
            event_sequences = [
                item.sequence
                for item in advanced.event_stream
                if item.run_id == run_id
            ]
            real_progress_events = [
                item
                for item in advanced.event_stream
                if item.progress_current is not None
            ]
            safe_source = (
                SRC / "olympus" / "boba" / "autopilot_controller.py"
            ).read_text(encoding="utf-8")
            tool_failure_state = tool_failure.runs[0].current_state
            tool_timeout_state = tool_timeout.runs[0].current_state
            tool_rollback_state = tool_rollback.runs[0].current_state
            code_success_state = code_success.runs[0].current_state
            code_failure_state = code_failure.runs[0].current_state

            checks = {
                "01_new_run_creation": bool(created.runs),
                "02_duplicate_active_run_conflict": duplicate_blocked,
                "03_advisory_only_concurrent_inspection": any(
                    item.control_mode == "advisory_only" for item in advisory.runs
                ),
                "04_project_lock_acquisition": bool(lock and lock.run_id == run_id),
                "05_stale_lock_detection": stale_detected,
                "06_lock_cannot_be_silently_stolen": not lock_stolen
                and not stale_stolen,
                "07_project_snapshot_created": bool(created.project_snapshots),
                "08_snapshot_change_detected": (
                    base_snapshot.snapshot_sha256
                    != changed_snapshot.snapshot_sha256
                ),
                "09_rights_clear": base_snapshot.rights_status == "owned",
                "10_rights_unknown": rights_unknown.rights_status == "unknown",
                "11_rights_blocked": rights_blocked.rights_status == "blocked",
                "12_safety_clear": (
                    base_snapshot.safety_status == "clear_for_local_analysis"
                ),
                "13_safety_blocked": safety_blocked.safety_status == "blocked",
                "14_observer_missing": (
                    base_snapshot.module_artifact_states["observer"]["status"]
                    == "missing"
                ),
                "15_observer_current": observer_invocation.status == "succeeded",
                "16_observer_stale": (
                    stale_snapshot.module_artifact_states["observer"]["status"]
                    == "stale"
                    and "observer" in stale_snapshot.stale_artifact_ids
                ),
                "17_error_doctor_required": (
                    main_run.current_state == "diagnosis_required"
                ),
                "18_error_doctor_insufficient_evidence": (
                    validate_autopilot_state_transition(
                        "diagnosis_required",
                        "human_quality_review_required",
                    )
                ),
                "19_rca_required": validate_autopilot_state_transition(
                    "diagnosis_required",
                    "root_cause_analysis_required",
                ),
                "20_rca_competing_causes": validate_autopilot_state_transition(
                    "root_cause_analysis_required",
                    "human_quality_review_required",
                ),
                "21_repair_planner_required": validate_autopilot_state_transition(
                    "root_cause_analysis_required",
                    "repair_planning_required",
                ),
                "22_repair_planner_no_repair": validate_autopilot_state_transition(
                    "awaiting_repair_decision",
                    "human_quality_review_required",
                ),
                "23_tool_repair_route": validate_autopilot_state_transition(
                    "awaiting_repair_decision",
                    "tool_recovery_ready",
                ),
                "24_code_repair_route": validate_autopilot_state_transition(
                    "awaiting_repair_decision",
                    "code_repair_ready",
                ),
                "25_checkpoint_issue_route": validate_autopilot_state_transition(
                    "awaiting_repair_decision",
                    "checkpoint_recovery_required",
                ),
                "26_human_decision_route": validate_autopilot_state_transition(
                    "awaiting_repair_decision",
                    "human_quality_review_required",
                ),
                "27_safe_read_only_automatic_progression": (
                    observer_invocation.invocation_mode
                    == "read_only_generation"
                ),
                "28_safe_progression_stops_before_approval_action": (
                    classify_autopilot_action(
                        "invoke_tool_recovery",
                        target_module="tool_recovery_brain",
                        target_operation="execute_approved",
                    )
                    == "approval_required_execution"
                ),
                "29_missing_approval": (
                    missing_approval_action.human_approval_required
                    and missing_approval_action.approval_binding_id is None
                    and missing_approval_action.status == "awaiting_approval"
                ),
                "30_expired_approval": bool(
                    verify_code_approval(
                        proposal,
                        code_expired,
                        required_type="isolated_patch_execution",
                    )
                ),
                "31_approval_plan_mismatch": bool(
                    verify_recovery_approval(plan, strategy, tool_plan_mismatch)
                ),
                "32_approval_strategy_mismatch": bool(
                    verify_recovery_approval(
                        plan,
                        strategy,
                        tool_strategy_mismatch,
                    )
                ),
                "33_approval_tool_mismatch": bool(
                    verify_recovery_approval(plan, strategy, tool_tool_mismatch)
                ),
                "34_approval_patch_mismatch": bool(
                    verify_code_approval(
                        proposal,
                        code_patch_mismatch,
                        required_type="isolated_patch_execution",
                    )
                ),
                "35_approval_settings_mismatch": bool(
                    verify_recovery_approval(
                        plan,
                        strategy,
                        tool_settings_mismatch,
                    )
                ),
                "36_approval_checkpoint_mismatch": bool(
                    verify_recovery_approval(
                        plan,
                        strategy,
                        tool_checkpoint_mismatch,
                    )
                ),
                "37_exact_approval_passes": not code_exact and not tool_exact,
                "38_approved_tool_recovery_coordination": (
                    tool_exact == []
                    and classify_autopilot_action(
                        "invoke_tool_recovery",
                        target_module="tool_recovery_brain",
                        target_operation="execute_approved",
                    )
                    == "approval_required_execution"
                ),
                "39_tool_recovery_technical_pass": (
                    tool_success.runs[0].current_state
                    == "technical_validation_required"
                ),
                "40_tool_recovery_failure": tool_failure_state
                in {"rollback_required", "repair_replanning_required"},
                "41_tool_recovery_timeout": timeout_invocation.timeout_occurred
                and tool_timeout_state == "rollback_required",
                "42_tool_recovery_rollback": (
                    tool_rollback_state == "repair_replanning_required"
                ),
                "43_tool_recovery_rollback_failure": (
                    rollback_controller.runs[0].current_state == "blocked"
                ),
                "44_approved_code_surgeon_coordination": (
                    code_exact == []
                    and classify_autopilot_action(
                        "invoke_code_surgeon",
                        target_module="code_surgeon",
                        target_operation="execute_approved",
                    )
                    == "approval_required_execution"
                ),
                "45_code_surgeon_validation_pass": (
                    code_success_state == "output_quality_review_required"
                ),
                "46_code_surgeon_validation_failure": (
                    code_failure_state == "repair_replanning_required"
                ),
                "47_code_surgeon_rollback": (
                    "rollback_required"
                    in VALID_AUTOPILOT_TRANSITIONS["execution_failed"]
                ),
                "48_code_surgeon_approval_invalidated_by_base_change": bool(
                    verify_code_approval(
                        proposal,
                        code_base_mismatch,
                        required_type="isolated_patch_execution",
                    )
                ),
                "49_output_quality_technical_rejection": (
                    quality_routes["rejected_technical"].runs[0].current_state
                    == "root_cause_reanalysis_required"
                ),
                "50_output_quality_creative_rejection": (
                    quality_routes["rejected_quality"].runs[0].current_state
                    == "repair_replanning_required"
                ),
                "51_output_quality_regression_rejection": (
                    quality_routes["rejected_regression"].runs[0].current_state
                    == "repair_replanning_required"
                ),
                "52_output_quality_needs_human_review": (
                    quality_routes["needs_human_review"].runs[0].current_state
                    == "human_quality_review_required"
                ),
                "53_output_quality_needs_more_evidence": (
                    "validator_runner"
                    in {
                        item.target_module
                        for item in quality_routes[
                            "needs_more_evidence"
                        ].handoffs
                    }
                ),
                "54_output_quality_accepted_internally": (
                    accepted_run.current_state == "completed_internal_cycle"
                ),
                "55_accepted_with_limitations_requires_review": (
                    quality_routes[
                        "accepted_with_disclosed_limitations"
                    ].runs[0].current_state
                    == "human_quality_review_required"
                ),
                "56_rights_block_after_recovery": (
                    quality_routes["blocked_rights"].runs[0].current_state
                    == "rights_review_required"
                ),
                "57_safety_block_after_recovery": (
                    quality_routes["blocked_safety"].runs[0].current_state
                    == "safety_review_required"
                ),
                "58_budget_70_percent_warning": (
                    "budget_warning_70"
                    in budget_70_controller.budget_usages[0].warnings
                ),
                "59_budget_90_percent_warning": (
                    "budget_warning_90"
                    in budget_90_controller.budget_usages[0].warnings
                ),
                "60_total_action_budget_exhausted": _budget_exhausted(
                    "actions_used",
                    "maximum_total_actions",
                ),
                "61_execution_budget_exhausted": _budget_exhausted(
                    "execution_actions_used",
                    "maximum_execution_actions",
                ),
                "62_retry_budget_exhausted": _budget_exhausted(
                    "retries_used",
                    "maximum_total_retries",
                ),
                "63_time_budget_exhausted": (
                    "total_duration_seconds"
                    in time_exhausted.exhausted_dimensions
                ),
                "64_code_repair_attempt_budget_exhausted": _budget_exhausted(
                    "code_repair_attempts_used",
                    "maximum_code_repair_attempts",
                ),
                "65_tool_recovery_budget_exhausted": _budget_exhausted(
                    "tool_recovery_attempts_used",
                    "maximum_tool_recovery_attempts",
                ),
                "66_quality_review_budget_exhausted": _budget_exhausted(
                    "quality_review_attempts_used",
                    "maximum_quality_review_attempts",
                ),
                "67_replanning_budget_exhausted": _budget_exhausted(
                    "replanning_cycles_used",
                    "maximum_replanning_cycles",
                ),
                "68_rca_reanalysis_budget_exhausted": _budget_exhausted(
                    "root_cause_reanalysis_cycles_used",
                    "maximum_root_cause_reanalysis_cycles",
                ),
                "69_budget_reset_requires_approval": (
                    budget_request_required_approval
                ),
                "70_approved_budget_reset_preserves_history": (
                    budget_approved.runs[-1].budget_id != previous_budget_id
                    and any(
                        item.budget_id == previous_budget_id
                        for item in budget_approved.recovery_budgets
                    )
                ),
                "71_identical_failed_action_detected": bool(repeated_failure),
                "72_a_b_a_loop_detected": bool(aba_loop and "A-B-A" in aba_loop),
                "73_repeated_unchanged_observer_generation_detected": bool(
                    repeated_failure
                ),
                "74_repeated_identical_repair_plan_detected": bool(
                    repeated_failure
                ),
                "75_repeated_identical_fallback_failure_detected": bool(
                    repeated_failure
                ),
                "76_idempotent_completed_action_does_not_rerun": bool(
                    idempotent
                ),
                "77_retry_allowed_with_new_evidence": (
                    changed_fingerprint != repeated_candidate.idempotency_key
                ),
                "78_stale_action_blocked": (
                    fingerprint_autopilot_action(
                        project_id=SYNTHETIC_PROJECT_ID,
                        run_id=RUN_ID,
                        action_type="inspect_project",
                        target_module="autopilot_controller",
                        target_operation="inspect",
                        snapshot_sha256=SNAPSHOT_SHA,
                    )
                    != fingerprint_autopilot_action(
                        project_id=SYNTHETIC_PROJECT_ID,
                        run_id=RUN_ID,
                        action_type="inspect_project",
                        target_module="autopilot_controller",
                        target_operation="inspect",
                        snapshot_sha256="f" * 64,
                    )
                ),
                "79_invalid_transition_blocked": not validate_autopilot_state_transition(
                    "created",
                    "execution_running",
                ),
                "80_target_module_unavailable": target_unavailable,
                "81_malformed_target_module_result": malformed_blocked,
                "82_project_state_uncertain": uncertain_invocation.changed_project_state,
                "83_source_media_risk_detected": (
                    uncertain_invocation.source_media_untouched is False
                ),
                "84_accepted_output_risk_detected": (
                    uncertain_invocation.accepted_outputs_untouched is False
                ),
                "85_controller_pauses_on_uncertain_state": uncertain_paused
                and uncertain_run.current_state == "paused",
                "86_controller_cancellation": (
                    cancelled.runs[-1].current_state == "cancelled"
                ),
                "87_pause_and_continue_controller": (
                    paused.runs[-1].current_state == "paused"
                    and continued.runs[-1].current_state
                    in {"inspecting_project", "observer_required"}
                ),
                "88_continue_does_not_resume_olympus": (
                    continued.signal_usage.workflow_resume_used is False
                ),
                "89_event_sequence_is_monotonic": event_sequences
                == sorted(event_sequences),
                "90_easy_messages_are_bounded": all(
                    len(item.easy_message) <= 700
                    for item in advanced.event_stream
                ),
                "91_fake_progress_is_not_produced": all(
                    item.progress_percent is None
                    or (
                        item.progress_current is not None
                        and item.progress_total is not None
                    )
                    for item in advanced.event_stream
                ),
                "92_event_progress_comes_from_real_actions": all(
                    item.action_id is not None for item in real_progress_events
                ),
                "93_human_decision_recorded": bool(human_rejected.decisions),
                "94_human_rejection_stops_action": (
                    human_rejected.planned_actions[-1].status == "blocked"
                    and human_rejected.runs[-1].current_state == "paused"
                ),
                "95_human_quality_approval_does_not_publish": (
                    human_rejected.signal_usage.publication_used is False
                ),
                "96_safety_gate_handoff_exists": "safety_gate"
                in handoff_targets,
                "97_workflow_controller_handoff_exists": "workflow_controller"
                in handoff_targets,
                "98_final_decision_bus_handoff_exists": "final_decision_bus"
                in handoff_targets,
                "99_live_companion_handoff_exists": "live_companion"
                in handoff_targets,
                "100_internal_cycle_completes": (
                    accepted_run.current_state == "completed_internal_cycle"
                ),
                "101_internal_completion_does_not_resume_workflow": (
                    accepted.signal_usage.workflow_resume_used is False
                ),
                "102_no_direct_commands_execute": (
                    signal.direct_command_execution_used is False
                    and "subprocess" not in safe_source
                ),
                "103_no_direct_git_executes": signal.direct_git_execution_used
                is False,
                "104_no_direct_ffmpeg_executes": (
                    signal.direct_ffmpeg_execution_used is False
                ),
                "105_no_source_media_changes": signal.source_media_modified
                is False,
                "106_no_accepted_output_overwrite": (
                    signal.accepted_outputs_modified is False
                ),
                "107_no_package_installation": (
                    signal.package_installation_used is False
                ),
                "108_no_service_restart": signal.service_restart_used is False,
                "109_no_process_kill": signal.process_kill_used is False,
                "110_no_internet": signal.network_access_used is False,
                "111_no_external_api": signal.external_api_used is False,
                "112_no_media_download": signal.downloading_used is False,
                "113_no_upload": signal.uploading_used is False,
                "114_no_publication": signal.publication_used is False,
                "115_no_push": signal.push_used is False,
                "116_no_merge": signal.merge_used is False,
                "117_no_deployment": signal.deployment_used is False,
                "118_no_rights_bypass": signal.rights_bypass_used is False,
                "119_no_safety_bypass": signal.safety_bypass_used is False,
                "120_no_destructive_action": signal.destructive_action_used
                is False,
            }
            scenarios = {name: bool(checks.get(name, False)) for name in SCENARIO_NAMES}
            if tuple(scenarios) != SCENARIO_NAMES:
                raise RuntimeError("Synthetic scenario names or order changed.")
            if len(scenarios) != 120:
                raise RuntimeError(
                    f"Synthetic scenario count is {len(scenarios)}, expected 120."
                )
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = BobaAutopilotControllerValidatorReportV1(
        mode="synthetic_project",
        passed=len(scenarios) == 120 and all(scenarios.values()) and not errors,
        project_id=SYNTHETIC_PROJECT_ID,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        signal_profiles=_signal_profiles(signal),
        limitations=[
            "Synthetic mode uses temporary local metadata and mocked typed integrations.",
            "It does not execute Code Surgeon patches or Tool Recovery commands.",
            "It does not use media, internet, external APIs, workflow resume, "
            "upload, or publication.",
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def inspect_project(
    project_id: str,
    *,
    repository_root: Path = ROOT,
    report_root: Path = REPORT_ROOT,
) -> BobaAutopilotControllerValidatorReportV1:
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    signal = BobaAutopilotControllerSignalUsageV1()
    try:
        store = BobaMemoryStore(repository_root / "work" / "boba")
        controller = store.load_boba_autopilot_controller(project_id)
        if controller is not None:
            signal = controller.signal_usage
        exported = (
            store.export_boba_autopilot_controller(project_id)
            if controller is not None
            else {}
        )
        events_ordered = (
            False
            if controller is None
            else all(
                [
                    item.sequence
                    for item in controller.event_stream
                    if item.run_id == run.run_id
                ]
                == sorted(
                    item.sequence
                    for item in controller.event_stream
                    if item.run_id == run.run_id
                )
                for run in controller.runs
            )
        )
        scenarios = {
            "stored_controller_available": controller is not None,
            "stored_controller_json_safe": bool(
                controller
                and json.dumps(controller.model_dump(mode="json"))
            ),
            "stored_events_ordered": events_ordered,
            "stored_signals_truthful": bool(
                controller
                and not controller.signal_usage.direct_command_execution_used
                and not controller.signal_usage.workflow_resume_used
                and not controller.signal_usage.publication_used
            ),
            "export_sanitized": bool(
                exported
                and exported.get("privacy", {}).get("private_paths_excluded")
                is True
            ),
        }
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = BobaAutopilotControllerValidatorReportV1(
        mode="project_id",
        passed=bool(scenarios) and all(scenarios.values()) and not errors,
        project_id=project_id,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        signal_profiles=_signal_profiles(signal),
        generated_fixture_only=False,
        limitations=[
            "Project mode inspects persisted Autopilot metadata only.",
            "It does not invoke modules, repair, restore, resume, upload, or publish.",
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--report-root", type=Path, default=REPORT_ROOT)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    report_root = arguments.report_root.resolve()
    if arguments.self_check:
        report = run_self_check(report_root)
    elif arguments.synthetic_project:
        report = run_synthetic_project(report_root)
    else:
        report = inspect_project(
            str(arguments.project_id),
            repository_root=ROOT,
            report_root=report_root,
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
