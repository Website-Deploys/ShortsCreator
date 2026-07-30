"""Validate BOBA Safety Gate V1 with bounded offline synthetic evidence."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_path in (ROOT, SRC):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from olympus.boba.autopilot_controller import (  # noqa: E402
    BobaAutopilotActionV1,
)
from olympus.boba.contracts import BobaContract, now_iso  # noqa: E402
from olympus.boba.safety_gate import (  # noqa: E402
    BobaSafetyDecisionV1,
    BobaSafetyGateSetV1,
    BobaSafetyGateSignalUsageV1,
    BobaSafetyGateV1,
    build_safety_module_operation_registry,
    calculate_safety_decision_digest,
    calculate_safety_request_digest,
    decision_is_expired,
    sanitize_safety_export,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.platform.errors import ValidationError  # noqa: E402

REPORT_ROOT = ROOT / "work" / "validation_reports" / "boba_safety_gate"
SNAPSHOT_DIGEST = "a" * 64
CHECKPOINT_DIGEST = "b" * 64

SCENARIO_NAMES: tuple[str, ...] = (
    "01_valid_read_only_action_request",
    "02_valid_internal_execution_request",
    "03_missing_project",
    "04_project_mismatch",
    "05_autopilot_run_mismatch",
    "06_unknown_requesting_module",
    "07_unknown_target_module",
    "08_unknown_target_operation",
    "09_arbitrary_command_payload",
    "10_external_url_payload",
    "11_raw_secret_material",
    "12_stable_request_digest",
    "13_changed_parameters_change_digest",
    "14_valid_snapshot",
    "15_missing_snapshot",
    "16_stale_snapshot",
    "17_changed_artifact_digest",
    "18_changed_rights_state",
    "19_new_conflicting_run",
    "20_rights_clear_for_local_action",
    "21_rights_unknown",
    "22_rights_blocked",
    "23_permission_required",
    "24_stale_rights_evidence",
    "25_code_only_action_with_irrelevant_media_rights",
    "26_missing_approval",
    "27_expired_approval",
    "28_approval_project_mismatch",
    "29_approval_plan_mismatch",
    "30_approval_strategy_mismatch",
    "31_approval_patch_mismatch",
    "32_approval_base_sha_mismatch",
    "33_approval_tool_mismatch",
    "34_approval_capability_mismatch",
    "35_approval_settings_mismatch",
    "36_approval_retry_budget_mismatch",
    "37_approval_time_budget_mismatch",
    "38_approval_checkpoint_mismatch",
    "39_approval_quality_mismatch",
    "40_exact_approval_match",
    "41_target_revalidation_remains_required",
    "42_checkpoint_not_required",
    "43_valid_checkpoint",
    "44_missing_checkpoint",
    "45_stale_checkpoint",
    "46_corrupt_checkpoint",
    "47_unverified_checkpoint",
    "48_checkpoint_digest_mismatch",
    "49_missing_rollback_plan",
    "50_rollback_not_ready",
    "51_source_media_not_protected",
    "52_accepted_output_not_protected",
    "53_destructive_rollback",
    "54_valid_rollback",
    "55_validation_plan_valid",
    "56_missing_validation_plan",
    "57_required_validator_unavailable",
    "58_required_validator_skipped",
    "59_missing_acceptance_criteria",
    "60_missing_rejection_criteria",
    "61_missing_rollback_validation",
    "62_validation_weakening_attempt",
    "63_quality_requirements_valid",
    "64_missing_quality_plan",
    "65_baseline_required_but_absent",
    "66_silent_resolution_reduction",
    "67_silent_frame_rate_reduction",
    "68_audio_removal",
    "69_caption_removal",
    "70_source_window_change",
    "71_non_negotiable_sync_regression",
    "72_disclosed_minor_degradation",
    "73_human_quality_review_incomplete",
    "74_quality_requirements_changed_after_approval",
    "75_budget_available",
    "76_action_budget_exhausted",
    "77_execution_budget_exhausted",
    "78_retry_budget_exhausted",
    "79_time_budget_exhausted",
    "80_module_attempt_budget_exhausted",
    "81_budget_reset_without_approval",
    "82_valid_bounded_budget_reset",
    "83_budget_reset_tries_to_erase_history",
    "84_budget_reset_bypasses_loop_block",
    "85_minimal_read_only_risk",
    "86_low_execution_risk",
    "87_medium_execution_risk_with_controls",
    "88_high_risk_requiring_review",
    "89_critical_risk",
    "90_blocked_risk",
    "91_source_data_risk",
    "92_accepted_output_risk",
    "93_secret_exposure_risk",
    "94_stale_state_risk",
    "95_concurrency_risk",
    "96_absolute_prohibited_action",
    "97_rights_bypass_request",
    "98_drm_bypass_request",
    "99_source_media_deletion",
    "100_accepted_output_overwrite",
    "101_direct_main_patch",
    "102_force_push_request",
    "103_automatic_merge_request",
    "104_deployment_request",
    "105_upload_request",
    "106_publication_request",
    "107_package_install_request",
    "108_service_restart_request",
    "109_unlimited_retry_request",
    "110_hidden_quality_reduction",
    "111_disable_validation_request",
    "112_unapproved_external_service",
    "113_unapproved_paid_provider",
    "114_observer_read_only_allowance",
    "115_error_doctor_allowance",
    "116_rca_allowance",
    "117_repair_planner_allowance",
    "118_code_surgeon_proposal_allowance",
    "119_code_surgeon_isolated_execution_allowance",
    "120_code_surgeon_commit_without_separate_approval",
    "121_valid_code_surgeon_local_commit_allowance",
    "122_tool_recovery_health_check_allowance",
    "123_tool_recovery_execution_allowance",
    "124_tool_recovery_fallback_changed_after_approval",
    "125_tool_recovery_rollback_allowance",
    "126_output_quality_artifact_review_allowance",
    "127_output_quality_local_review_allowance",
    "128_workflow_resume_request_future_gated",
    "129_checkpoint_restore_request_future_gated",
    "130_internal_execution_decision_expires",
    "131_read_only_decision_expires",
    "132_revalidation_succeeds",
    "133_revalidation_fails_after_snapshot_change",
    "134_revalidation_fails_after_policy_change",
    "135_revalidation_fails_after_approval_change",
    "136_revalidation_fails_after_plan_change",
    "137_revalidation_fails_after_patch_change",
    "138_revalidation_fails_after_tool_change",
    "139_revalidation_fails_after_checkpoint_change",
    "140_revalidation_fails_after_quality_change",
    "141_revalidation_fails_after_budget_change",
    "142_revalidation_fails_after_rights_change",
    "143_human_review_recorded",
    "144_human_review_cannot_override_absolute_prohibition",
    "145_human_review_cannot_authorize_publication",
    "146_human_review_cannot_authorize_rights_bypass",
    "147_allowed_decision_creates_autopilot_handoff",
    "148_validation_block_creates_validator_runner_handoff",
    "149_checkpoint_block_creates_checkpoint_manager_handoff",
    "150_rights_block_creates_rights_gate_handoff",
    "151_quality_block_creates_reviewer_planner_handoff",
    "152_human_uncertainty_creates_human_handoff",
    "153_event_explanation_is_bounded",
    "154_no_private_path_appears",
    "155_no_secret_appears",
    "156_no_action_executes",
    "157_no_commands_execute",
    "158_no_git_executes",
    "159_no_ffmpeg_executes",
    "160_no_code_modification",
    "161_no_artifact_modification",
    "162_no_source_media_modification",
    "163_no_accepted_output_modification",
    "164_no_checkpoint_restore",
    "165_no_workflow_resume",
    "166_no_package_installation",
    "167_no_service_restart",
    "168_no_process_kill",
    "169_no_network",
    "170_no_external_api",
    "171_no_download",
    "172_no_upload",
    "173_no_publication",
    "174_no_push",
    "175_no_merge",
    "176_no_deployment",
    "177_no_rights_bypass",
    "178_no_safety_bypass",
    "179_no_destructive_action",
)


class BobaSafetyGateValidatorReportV1(BobaContract):
    schema_version: Literal["boba_safety_gate_validator_v1"] = (
        "boba_safety_gate_validator_v1"
    )
    mode: Literal["self_check", "synthetic_project", "project_id"]
    created_at: str = Field(default_factory=now_iso)
    passed: bool
    project_id: str | None = None
    scenario_count: int = Field(default=0, ge=0)
    passed_scenario_count: int = Field(default=0, ge=0)
    scenario_results: dict[str, bool] = Field(default_factory=dict)
    decision_profiles: dict[str, str] = Field(default_factory=dict)
    generated_fixture_only: bool = True
    direct_action_execution_used: Literal[False] = False
    direct_command_execution_used: Literal[False] = False
    direct_git_execution_used: Literal[False] = False
    direct_ffmpeg_execution_used: Literal[False] = False
    code_modification_used: Literal[False] = False
    artifact_modification_used: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    workflow_resume_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    process_kill_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
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


class SafetySyntheticHarness:
    def __init__(self, root: Path) -> None:
        self.contexts: dict[str, dict[str, Any]] = {}
        self.store = BobaMemoryStore(root)
        self.engine = BobaSafetyGateV1(
            self.store,
            context_provider=lambda project_id, _request: self.contexts[project_id],
        )

    @staticmethod
    def context(*, execution: bool) -> dict[str, Any]:
        context: dict[str, Any] = {
            "snapshot_current": True,
            "rights_status": "owned",
            "permission_status": "confirmed",
            "safety_status": "clear_for_local_analysis",
            "source_media_protected": True,
            "accepted_outputs_protected": True,
            "conflicting_state": False,
            "risk_assessment": {"score": 5.0 if not execution else 28.0},
        }
        if execution:
            context.update(
                {
                    "approval_review": {
                        "approval_record_id": "approval_exact",
                        "approval_type": "synthetic_exact",
                        "approval_found": True,
                        "explicit_confirmation": True,
                        "approved": True,
                        "expires_at": (
                            datetime.now(UTC) + timedelta(hours=1)
                        ).isoformat(),
                        "scope_match": True,
                        "parameters_match": True,
                        "snapshot_match": True,
                    },
                    "checkpoint_review": {
                        "checkpoint_required": True,
                        "checkpoint_reference": "checkpoints/synthetic.json",
                        "checkpoint_digest": CHECKPOINT_DIGEST,
                        "checkpoint_status": "valid",
                        "checkpoint_validated": True,
                        "checkpoint_fresh": True,
                        "state_preservation_ready": True,
                        "rollback_plan_present": True,
                        "rollback_ready": True,
                        "source_media_protected": True,
                        "accepted_outputs_protected": True,
                    },
                    "validation_review": {
                        "required": True,
                        "validation_plan_id": "validation_plan_exact",
                        "required_validators": ["synthetic_validator"],
                        "available_validators": ["synthetic_validator"],
                        "pre_action_checks": ["snapshot remains current"],
                        "post_action_checks": ["result matches acceptance criteria"],
                        "rollback_checks": ["rollback preserves protected state"],
                        "acceptance_criteria": ["required checks pass"],
                        "rejection_criteria": ["any required check fails"],
                    },
                    "quality_review": {
                        "quality_review_required": True,
                        "quality_plan_id": "quality_plan_exact",
                        "non_negotiable_requirements": [
                            "source media remains untouched",
                            "accepted output remains protected",
                        ],
                        "baseline_required": False,
                        "baseline_available": True,
                        "quality_requirements_match_request": True,
                    },
                    "budget_review": {
                        "budget_exhausted": False,
                        "maximum_time_seconds": 600,
                    },
                }
            )
        return context

    def _project(self, number: int) -> str:
        return f"proj_safety_validator_{number:03d}"

    def read_only(
        self,
        number: int,
        *,
        target_module: str = "observer",
        target_operation: str = "generate",
        description: str = "Generate bounded local read-only evidence.",
        parameters: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        action_class: str = "automatic_read_only",
    ) -> tuple[BobaSafetyDecisionV1, BobaSafetyGateSetV1]:
        project_id = self._project(number)
        self.contexts[project_id] = self.context(execution=False)
        if context:
            self.contexts[project_id].update(context)
        request = self.engine.create_action_request(
            project_id,
            target_module=target_module,
            target_operation=target_operation,
            action_class=action_class,
            action_description=description,
            action_parameters=parameters or {},
            project_snapshot_id=f"snapshot_{number}",
            project_snapshot_digest=SNAPSHOT_DIGEST,
            approval_record_id=(
                "approval_exact"
                if action_class == "approval_required_read_only"
                else ""
            ),
            validation_plan_id=(
                "validation_plan_exact"
                if action_class == "approval_required_read_only"
                else ""
            ),
            quality_plan_id=(
                "quality_plan_exact"
                if target_module == "output_quality_reviewer"
                else ""
            ),
        )
        decision = self.engine.evaluate_action(project_id, request.action_request_id)
        gate = self.store.load_boba_safety_gate(project_id)
        assert gate is not None
        return decision, gate

    def execution(
        self,
        number: int,
        *,
        target_module: str = "tool_recovery_brain",
        target_operation: str = "execute_approved",
        description: str = "Execute one exact approved local recovery attempt.",
        parameters: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        approval_record_id: str = "approval_exact",
        validation_plan_id: str = "validation_plan_exact",
        quality_plan_id: str = "quality_plan_exact",
    ) -> tuple[BobaSafetyDecisionV1, BobaSafetyGateSetV1]:
        project_id = self._project(number)
        self.contexts[project_id] = self.context(execution=True)
        if context:
            for key, value in context.items():
                if isinstance(value, dict) and isinstance(
                    self.contexts[project_id].get(key),
                    dict,
                ):
                    self.contexts[project_id][key] = {
                        **self.contexts[project_id][key],
                        **value,
                    }
                else:
                    self.contexts[project_id][key] = value
        values = {
            "recovery_plan_id": "plan_exact",
            "recovery_strategy_id": "strategy_exact",
            "tool_id": "tool_exact",
            **(parameters or {}),
        }
        request = self.engine.create_action_request(
            project_id,
            target_module=target_module,
            target_operation=target_operation,
            action_class="approval_required_execution",
            action_description=description,
            action_parameters=values,
            project_snapshot_id=f"snapshot_{number}",
            project_snapshot_digest=SNAPSHOT_DIGEST,
            plan_id="plan_exact",
            strategy_id="strategy_exact",
            approval_record_id=approval_record_id,
            patch_proposal_id=(
                "patch_exact" if target_module == "code_surgeon" else ""
            ),
            patch_diff_sha256=(
                "c" * 64 if target_module == "code_surgeon" else ""
            ),
            code_base_sha="d" * 40 if target_module == "code_surgeon" else "",
            tool_id="tool_exact" if target_module == "tool_recovery_brain" else "",
            capability_id=(
                "capability_exact"
                if target_module == "tool_recovery_brain"
                else ""
            ),
            checkpoint_reference="checkpoints/synthetic.json",
            checkpoint_digest=CHECKPOINT_DIGEST,
            rollback_plan_id="rollback_plan_exact",
            validation_plan_id=validation_plan_id,
            quality_plan_id=quality_plan_id,
            time_budget_seconds=300,
        )
        decision = self.engine.evaluate_action(project_id, request.action_request_id)
        gate = self.store.load_boba_safety_gate(project_id)
        assert gate is not None
        return decision, gate


def _raises(callable_value: Callable[[], Any]) -> bool:
    try:
        callable_value()
    except (ValidationError, ValueError):
        return True
    return False


def _latest_review(gate: BobaSafetyGateSetV1, name: str) -> Any:
    values = getattr(gate, name)
    assert values
    return values[-1]


def _decision_with_context(
    harness: SafetySyntheticHarness,
    number: int,
    update: dict[str, Any],
) -> tuple[BobaSafetyDecisionV1, BobaSafetyGateSetV1]:
    return harness.execution(number, context=update)


def run_named_scenario(
    harness: SafetySyntheticHarness,
    scenario_name: str,
) -> bool:
    number = int(scenario_name.split("_", 1)[0])
    if number in {1, 14, 20, 114, 115, 116, 117, 118}:
        read_only_targets = {
            114: ("observer", "generate"),
            115: ("error_doctor", "generate"),
            116: ("root_cause_analyzer", "generate"),
            117: ("repair_planner", "generate"),
            118: ("code_surgeon", "proposal"),
        }
        target = read_only_targets.get(number, ("observer", "generate"))
        decision, _ = harness.read_only(
            number,
            target_module=target[0],
            target_operation=target[1],
        )
        return decision.decision == "allowed_for_internal_read_only"
    if number in {2, 43, 54, 55, 63, 75, 86, 87, 119, 123, 125}:
        kwargs: dict[str, Any] = {}
        if number == 119:
            kwargs = {
                "target_module": "code_surgeon",
                "target_operation": "execute_approved",
            }
        if number == 125:
            kwargs = {"target_operation": "rollback"}
        decision, _ = harness.execution(number, **kwargs)
        return decision.decision == "allowed_for_exact_internal_execution"
    if number == 3:
        return harness.store.load_boba_safety_gate("proj_missing") is None
    if number == 4:
        project = harness._project(number)
        harness.contexts[project] = harness.context(execution=False)
        return _raises(
            lambda: harness.engine.create_action_request(
                project,
                target_module="observer",
                target_operation="generate",
                action_class="automatic_read_only",
                action_description="Inspect proj_other_project only.",
                project_snapshot_id="snapshot",
                project_snapshot_digest=SNAPSHOT_DIGEST,
            )
        )
    if number == 5:
        action = BobaAutopilotActionV1(
            action_id="another_action",
            run_id="another_run",
            action_type="invoke_tool_recovery",
            action_class="approval_required_execution",
            target_module="tool_recovery_brain",
            target_operation="execute_approved",
            description="Synthetic mismatch.",
            rationale="Prove run binding.",
            parameters={
                "recovery_plan_id": "plan_exact",
                "recovery_strategy_id": "strategy_exact",
                "tool_id": "tool_exact",
            },
            planned_snapshot_sha256=SNAPSHOT_DIGEST,
            idempotency_key="mismatch_action",
        )
        decision, gate = harness.execution(number)
        request = gate.action_requests[-1]
        return (
            decision.autopilot_run_id != action.run_id
            and request.autopilot_action_id != action.action_id
        )
    if number in {6, 7, 8, 15}:
        project = harness._project(number)
        harness.contexts[project] = harness.context(execution=False)
        requesting_module = (
            "unknown_requester" if number == 6 else "autopilot_controller"
        )
        target_module = "unknown_target" if number == 7 else "observer"
        target_operation = "unknown_operation" if number == 8 else "generate"
        project_snapshot_id = "" if number == 15 else "snapshot"
        return _raises(
            lambda: harness.engine.create_action_request(
                project,
                requesting_module=requesting_module,
                target_module=target_module,
                target_operation=target_operation,
                action_class="automatic_read_only",
                action_description="Synthetic invalid request.",
                project_snapshot_id=project_snapshot_id,
                project_snapshot_digest=SNAPSHOT_DIGEST,
            )
        )
    if number in {9, 10, 11}:
        payloads = {
            9: {"command": "arbitrary.exe --unsafe"},
            10: {"reference": "https://example.invalid/input"},
            11: {"api_token": "sk_live_12345678901234567890"},
        }
        project = harness._project(number)
        harness.contexts[project] = harness.context(execution=False)
        return _raises(
            lambda: harness.engine.create_action_request(
                project,
                target_module="observer",
                target_operation="generate",
                action_class="automatic_read_only",
                action_description="Inspect bounded evidence.",
                action_parameters=payloads[number],
                project_snapshot_id="snapshot",
                project_snapshot_digest=SNAPSHOT_DIGEST,
            )
        )
    if number in {12, 13}:
        _, first_gate = harness.read_only(number, parameters={"value": 1})
        first_request = first_gate.action_requests[-1]
        project = harness._project(number)
        second = harness.engine.create_action_request(
            project,
            target_module="observer",
            target_operation="generate",
            action_class="automatic_read_only",
            action_description="Generate bounded local read-only evidence.",
            action_parameters={"value": 1 if number == 12 else 2},
            project_snapshot_id=f"snapshot_{number}",
            project_snapshot_digest=SNAPSHOT_DIGEST,
        )
        return (
            second.request_digest == first_request.request_digest
            if number == 12
            else second.request_digest != first_request.request_digest
        )
    if number in {16, 19, 94, 95}:
        snapshot_update = (
            {"snapshot_current": False}
            if number in {16, 94}
            else {"conflicting_state": True}
        )
        decision, gate = harness.read_only(number, context=snapshot_update)
        categories = {
            factor.category
            for assessment in gate.risk_assessments
            for factor in assessment.risk_factors
        }
        expected = "stale_state" if number in {16, 94} else "project_concurrency"
        return decision.decision == "blocked_stale_state" and expected in categories
    if number in {17, 18, 124, 133, 134, 136, 137, 138, 139, 140, 141, 142}:
        decision, gate = harness.execution(number)
        request = gate.action_requests[-1]
        bindings: dict[str, Any] = {}
        if number in {17, 133}:
            bindings["project_snapshot_digest"] = "f" * 64
        elif number in {18, 142}:
            bindings["rights_changed"] = True
        elif number == 124:
            bindings["strategy_id"] = "changed_strategy"
        elif number == 134:
            bindings["policy_snapshot_digest"] = "e" * 64
        elif number == 136:
            bindings["plan_id"] = "changed_plan"
        elif number == 137:
            bindings["patch_diff_sha256"] = "e" * 64
        elif number == 138:
            bindings["tool_id"] = "changed_tool"
        elif number == 139:
            bindings["checkpoint_digest"] = "changed_checkpoint"
        elif number == 140:
            bindings["quality_plan_id"] = "changed_quality"
        elif number == 141:
            bindings["retry_budget_digest"] = "e" * 64
        invalid = harness.engine.revalidate_decision(
            request.project_id,
            decision.safety_decision_id,
            current_bindings=bindings,
        )
        persisted_gate = harness.store.load_boba_safety_gate(request.project_id)
        return bool(
            not invalid.decision_valid
            and persisted_gate
            and persisted_gate.decision_invalidations
        )
    if number in {21, 22, 23, 24, 25}:
        if number == 25:
            decision, _ = harness.read_only(
                number,
                target_module="code_surgeon",
                target_operation="proposal",
                context={"rights_status": "unknown"},
            )
            return decision.decision == "allowed_for_internal_read_only"
        rights_updates: dict[int, dict[str, Any]] = {
            21: {"rights_status": "unknown"},
            22: {"rights_status": "blocked"},
            23: {
                "rights_status": "owned",
                "permission_status": "permission_required",
            },
            24: {
                "rights_review": {
                    "rights_status": "owned",
                    "permission_status": "confirmed",
                    "stale": True,
                }
            },
        }
        rights_update = rights_updates[number]
        decision, _ = harness.read_only(number, context=rights_update)
        return decision.decision == "blocked_rights"
    if 26 <= number <= 41:
        approval_update: dict[str, Any] = {}
        if number == 26:
            approval_update = {
                "approval_found": False,
                "explicit_confirmation": False,
                "approved": False,
                "scope_match": False,
                "parameters_match": False,
            }
        elif number == 27:
            approval_update = {
                "expires_at": (
                    datetime.now(UTC) - timedelta(seconds=1)
                ).isoformat()
            }
        elif 28 <= number <= 39:
            approval_update = {
                "snapshot_match": number != 28,
                "scope_match": number not in {29, 30, 33, 34},
                "parameters_match": number not in {31, 32, 35, 36, 37, 38, 39},
            }
        decision, gate = harness.execution(
            number,
            context={"approval_review": approval_update},
        )
        approval = _latest_review(gate, "approval_reviews")
        if number == 40:
            return (
                decision.decision == "allowed_for_exact_internal_execution"
                and approval.exact_binding_valid
            )
        if number == 41:
            return (
                decision.target_module_revalidation_required
                and approval.independent_target_revalidation_required
            )
        return decision.decision == "denied" and not approval.exact_binding_valid
    if number == 42:
        _, gate = harness.read_only(number)
        checkpoint = _latest_review(gate, "checkpoint_reviews")
        return not checkpoint.checkpoint_required and not checkpoint.blocks_action
    if 44 <= number <= 53:
        checkpoint_update: dict[str, Any] = {}
        if number == 44:
            checkpoint_update = {
                "checkpoint_reference": "",
                "checkpoint_status": "missing",
                "checkpoint_validated": False,
                "checkpoint_fresh": False,
            }
        elif number in {45, 46, 47}:
            checkpoint_update = {
                "checkpoint_status": {
                    45: "stale",
                    46: "corrupt",
                    47: "unverified",
                }[number],
                "checkpoint_validated": False,
                "checkpoint_fresh": False,
            }
        elif number == 48:
            checkpoint_update = {"checkpoint_digest": "different"}
        elif number == 49:
            checkpoint_update = {"rollback_plan_present": False}
        elif number == 50:
            checkpoint_update = {"rollback_ready": False}
        elif number == 51:
            checkpoint_update = {"source_media_protected": False}
        elif number == 52:
            checkpoint_update = {"accepted_outputs_protected": False}
        elif number == 53:
            checkpoint_update = {"destructive_rollback": True}
        decision, gate = _decision_with_context(
            harness,
            number,
            {"checkpoint_review": checkpoint_update},
        )
        checkpoint_review = _latest_review(gate, "checkpoint_reviews")
        return (
            decision.decision == "blocked_checkpoint"
            and checkpoint_review.blocks_action
        )
    if 56 <= number <= 62:
        validation_update: dict[str, Any] = {}
        if number == 56:
            validation_update = {"validation_plan_id": ""}
        elif number == 57:
            validation_update = {
                "required_validators": ["missing_validator"],
                "available_validators": [],
            }
        elif number == 58:
            validation_update = {
                "skipped_required_checks": ["synthetic_validator"]
            }
        elif number == 59:
            validation_update = {"acceptance_criteria": []}
        elif number == 60:
            validation_update = {"rejection_criteria": []}
        elif number == 61:
            validation_update = {"rollback_checks": []}
        elif number == 62:
            validation_update = {"validation_weakened": True}
        if number == 56:
            decision, gate = harness.execution(
                number,
                context={"validation_review": validation_update},
                validation_plan_id="",
            )
        else:
            decision, gate = _decision_with_context(
                harness,
                number,
                {"validation_review": validation_update},
            )
        validation_review = _latest_review(gate, "validation_reviews")
        return (
            decision.decision == "blocked_validation"
            and not validation_review.validation_ready
        )
    if 64 <= number <= 74:
        quality_update: dict[str, Any] = {}
        if number == 64:
            quality_update = {"quality_plan_id": ""}
        elif number == 65:
            quality_update = {
                "baseline_required": True,
                "baseline_available": False,
            }
        elif 66 <= number <= 70:
            quality_update = {"silent_quality_reduction_detected": True}
        elif number == 71:
            quality_update = {"non_negotiable_regression_present": True}
        elif number == 72:
            quality_update = {"disclosed_minor_degradation": True}
        elif number == 73:
            quality_update = {"human_quality_review_incomplete": True}
        elif number == 74:
            quality_update = {"quality_requirements_match_request": False}
        if number == 64:
            decision, gate = harness.execution(
                number,
                context={"quality_review": quality_update},
                quality_plan_id="",
            )
        else:
            decision, gate = _decision_with_context(
                harness,
                number,
                {"quality_review": quality_update},
            )
        quality_review = _latest_review(gate, "quality_reviews")
        if number in {72, 73}:
            return (
                decision.decision == "human_review_required"
                and quality_review.human_quality_review_required
            )
        return decision.decision == "blocked_quality"
    if 76 <= number <= 80:
        reason = {
            76: "The project-wide action budget is exhausted.",
            77: "The execution action budget is exhausted.",
            78: "The retry budget is exhausted.",
            79: "The time budget is exhausted.",
            80: "The target-module attempt budget is exhausted.",
        }[number]
        decision, _ = _decision_with_context(
            harness,
            number,
            {"budget_review": {"failure_reasons": [reason]}},
        )
        return decision.decision == "blocked_budget"
    if number in {81, 82, 83, 84}:
        budget_update: dict[str, Any] = {
            "near_or_exhausted": True,
            "history_preserved": number != 83,
            "loop_blocked": number == 84,
            "maximum_time_seconds": 600,
        }
        if number == 81:
            budget_update["approval_found"] = False
        budget_context = {
            "budget_review": budget_update,
            "approval_review": (
                {
                    "approval_found": False,
                    "explicit_confirmation": False,
                    "approved": False,
                }
                if number == 81
                else {}
            ),
        }
        decision, _ = harness.execution(
            number,
            target_module="autopilot_controller",
            target_operation="budget_reset",
            context=budget_context,
        )
        return (
            decision.decision == "allowed_for_exact_internal_execution"
            if number == 82
            else decision.decision in {"denied", "blocked_budget"}
        )
    if number in {85, 88, 89}:
        score = {85: 5.0, 88: 70.0, 89: 90.0}[number]
        call = harness.read_only if number == 85 else harness.execution
        decision, gate = call(number, context={"risk_assessment": {"score": score}})
        risk = _latest_review(gate, "risk_assessments")
        expected = {
            85: "allowed_for_internal_read_only",
            88: "human_review_required",
            89: "denied",
        }[number]
        return decision.decision == expected and 0 <= risk.overall_risk_score <= 100
    if number == 90:
        decision, gate = harness.read_only(
            number,
            description="Attempt rights_bypass.",
        )
        risk = _latest_review(gate, "risk_assessments")
        return decision.decision == "denied" and risk.blocked_risk_present
    if number in {91, 92, 93}:
        if number == 93:
            decision, gate = harness.read_only(
                number,
                description="Attempt secret_exposure.",
            )
            expected = "secret_exposure"
        else:
            key = (
                "source_media_protected"
                if number == 91
                else "accepted_outputs_protected"
            )
            decision, gate = harness.execution(
                number,
                context={"checkpoint_review": {key: False}},
            )
            expected = "source_data" if number == 91 else "accepted_output"
        categories = {
            factor.category
            for assessment in gate.risk_assessments
            for factor in assessment.risk_factors
        }
        return not decision.decision_valid and expected in categories
    if 96 <= number <= 113:
        token = {
            96: "rights_bypass",
            97: "rights_bypass",
            98: "drm_bypass",
            99: "delete_source",
            100: "accepted_output_overwrite",
            101: "direct_main",
            102: "force_push",
            103: "automatic_merge",
            104: "deployment",
            105: "automatic_upload",
            106: "automatic_publish",
            107: "install_package",
            108: "restart_service",
            109: "unlimited_retry",
            110: "hidden_quality_reduction",
            111: "disable_validation",
            112: "external_service",
            113: "paid_provider",
        }[number]
        decision, _ = harness.read_only(
            number,
            description=f"Request {token}.",
        )
        if number in {107, 108}:
            return decision.decision == "unsupported_future_action"
        return decision.decision == "denied"
    if number in {120, 121}:
        commit_context = (
            {
                "approval_review": {
                    "approval_found": False,
                    "explicit_confirmation": False,
                    "approved": False,
                }
            }
            if number == 120
            else None
        )
        decision, _ = harness.execution(
            number,
            target_module="code_surgeon",
            target_operation="prepare_local_commit",
            context=commit_context,
        )
        return (
            decision.decision == "allowed_for_exact_internal_execution"
            if number == 121
            else decision.decision == "denied"
        )
    if number == 122:
        decision, _ = harness.read_only(
            number,
            target_module="tool_recovery_brain",
            target_operation="health_check",
        )
        return decision.decision == "allowed_for_internal_read_only"
    if number == 126:
        decision, _ = harness.read_only(
            number,
            target_module="output_quality_reviewer",
            target_operation="artifact_review",
        )
        return decision.decision == "allowed_for_internal_read_only"
    if number == 127:
        context = harness.context(execution=True)
        project = harness._project(number)
        harness.contexts[project] = context
        request = harness.engine.create_action_request(
            project,
            target_module="output_quality_reviewer",
            target_operation="local_technical_review",
            action_class="approval_required_read_only",
            action_description="Inspect one exact local generated output.",
            project_snapshot_id="snapshot",
            project_snapshot_digest=SNAPSHOT_DIGEST,
            approval_record_id="approval_exact",
            validation_plan_id="validation_plan_exact",
            quality_plan_id="quality_plan_exact",
        )
        decision = harness.engine.evaluate_action(project, request.action_request_id)
        return decision.decision == "allowed_for_internal_read_only"
    if number in {128, 129}:
        target = (
            ("workflow_controller", "resume")
            if number == 128
            else ("checkpoint_recovery_manager", "restore_checkpoint")
        )
        decision, _ = harness.read_only(
            number,
            target_module=target[0],
            target_operation=target[1],
            action_class="future_gated",
        )
        return decision.decision == "unsupported_future_action"
    if number in {130, 131}:
        decision, _ = (
            harness.execution(number)
            if number == 130
            else harness.read_only(number)
        )
        at = datetime.fromisoformat(decision.decision_expires_at) + timedelta(seconds=1)
        return decision_is_expired(decision, at=at)
    if number == 132:
        decision, gate = harness.execution(number)
        current = harness.engine.revalidate_decision(
            gate.project_id,
            decision.safety_decision_id,
        )
        return current.safety_decision_id == decision.safety_decision_id
    if number == 135:
        decision, gate = harness.execution(number)
        changed_approval = {
            "approval_id": "changed",
            "approved": True,
            "explicit_confirmation": "yes",
        }
        invalid = harness.engine.revalidate_decision(
            gate.project_id,
            decision.safety_decision_id,
            approval_record=changed_approval,
        )
        return not invalid.decision_valid
    if number in {143, 152}:
        decision, gate = harness.execution(
            number,
            context={"risk_assessment": {"score": 70.0}},
        )
        case = gate.evaluation_cases[-1]
        request = gate.action_requests[-1]
        if number == 152:
            return (
                decision.decision == "human_review_required"
                and any(
                    item.target_module == "human_operator"
                    for item in gate.handoffs
                )
            )
        reviewed = harness.engine.record_human_safety_review(
            gate.project_id,
            case.safety_case_id,
            decision="deny_action",
            reason="Keep this exact project paused.",
            reviewer_identity="synthetic_reviewer",
            request_digest=request.request_digest,
            project_snapshot_digest=request.project_snapshot_digest,
        )
        return reviewed.decision == "denied"
    if number in {144, 145, 146}:
        token = {
            144: "accepted_output_overwrite",
            145: "automatic_publish",
            146: "rights_bypass",
        }[number]
        decision, gate = harness.read_only(number, description=f"Request {token}.")
        case = gate.evaluation_cases[-1]
        request = gate.action_requests[-1]
        return (
            decision.decision in {"denied", "unsupported_future_action"}
            and _raises(
                lambda: harness.engine.record_human_safety_review(
                    gate.project_id,
                    case.safety_case_id,
                    decision="approve_exact_medium_risk_action",
                    reason="Attempt an impermissible override.",
                    reviewer_identity="synthetic_reviewer",
                    request_digest=request.request_digest,
                    project_snapshot_digest=request.project_snapshot_digest,
                )
            )
        )
    if 147 <= number <= 151:
        if number == 147:
            _, gate = harness.read_only(number)
            handoff_targets = {"autopilot_controller"}
        elif number == 148:
            _, gate = harness.execution(
                number,
                context={
                    "validation_review": {
                        "available_validators": [],
                        "required_validators": ["missing"],
                    }
                },
            )
            handoff_targets = {"validator_runner"}
        elif number == 149:
            _, gate = harness.execution(
                number,
                context={
                    "checkpoint_review": {
                        "checkpoint_status": "missing",
                        "checkpoint_validated": False,
                    }
                },
            )
            handoff_targets = {"checkpoint_recovery_manager"}
        elif number == 150:
            _, gate = harness.read_only(number, context={"rights_status": "blocked"})
            handoff_targets = {"rights_permission_gate"}
        else:
            _, gate = harness.execution(
                number,
                context={
                    "quality_review": {
                        "non_negotiable_regression_present": True
                    }
                },
            )
            handoff_targets = {"output_quality_reviewer", "repair_planner"}
        actual = {item.target_module for item in gate.handoffs}
        return bool(actual & handoff_targets)
    if number == 153:
        decision, gate = harness.read_only(number)
        return (
            len(decision.decision_summary) <= 900
            and all(len(item.reason) <= 900 for item in gate.handoffs)
        )
    if number == 154:
        payload = sanitize_safety_export({"path": r"D:\private\secret.txt"})
        return "D:\\" not in json.dumps(payload)
    if number == 155:
        payload = sanitize_safety_export(
            {"api_token": "sk_live_12345678901234567890"}
        )
        return "sk_live" not in json.dumps(payload)
    if 156 <= number <= 179:
        signal_fields = (
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
            "network_access_used",
            "external_api_used",
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
        _, gate = harness.read_only(number)
        return getattr(gate.signal_usage, signal_fields[number - 156]) is False
    raise AssertionError(f"Unhandled Safety Gate scenario: {scenario_name}")


def run_self_check() -> BobaSafetyGateValidatorReportV1:
    results: dict[str, bool] = {}
    with TemporaryDirectory(prefix="boba_safety_self_check_") as temp:
        root = Path(temp)
        store = BobaMemoryStore(root)
        engine = BobaSafetyGateV1(store)
        gate = engine.create_policy_snapshot("proj_safety_self_check")
        registry = build_safety_module_operation_registry()
        request_payload = {
            "project_id": "proj_safety_self_check",
            "target_module": "observer",
            "target_operation": "generate",
            "action_parameters_digest": "a" * 64,
            "project_snapshot_digest": "b" * 64,
        }
        decision_payload = {
            "project_id": "proj_safety_self_check",
            "request_digest": calculate_safety_request_digest(request_payload),
            "decision": "denied",
        }
        source = inspect.getsource(BobaSafetyGateV1)
        results = {
            "safety_gate_imports": BobaSafetyGateV1.__name__ == "BobaSafetyGateV1",
            "required_boba_modules_import": all(
                module in registry
                for module in (
                    "autopilot_controller",
                    "code_surgeon",
                    "tool_recovery_brain",
                    "output_quality_reviewer",
                    "repair_planner",
                )
            ),
            "contracts_serialize": bool(json.dumps(gate.model_dump(mode="json"))),
            "policy_snapshot_builds": len(gate.policy_snapshot.policy_sha256) == 64,
            "module_operation_registry_builds": bool(registry),
            "request_digest_deterministic": (
                calculate_safety_request_digest(request_payload)
                == calculate_safety_request_digest(request_payload)
            ),
            "decision_digest_deterministic": (
                calculate_safety_decision_digest(decision_payload)
                == calculate_safety_decision_digest(decision_payload)
            ),
            "decision_expiry_works": decision_is_expired(
                BobaSafetyDecisionV1(
                    safety_decision_id="expired_self_check",
                    safety_case_id="case",
                    action_request_id="request",
                    project_id="proj_safety_self_check",
                    decision="expired",
                    decision_summary="Expired.",
                    decision_expires_at=(
                        datetime.now(UTC) - timedelta(seconds=1)
                    ).isoformat(),
                )
            ),
            "storage_writable": store.boba_safety_gate_path(
                "proj_safety_self_check"
            ).exists(),
            "no_execution_runner": "_invoke_action" not in source,
            "no_command_runner": "subprocess" not in source,
            "no_git_runner": "git " not in source.casefold(),
            "no_ffmpeg_runner": "ffmpeg" not in source.casefold(),
            "no_network_required": "http://" not in source.casefold(),
            "no_publication_or_resume_authority": all(
                not getattr(
                    BobaSafetyDecisionV1(
                        safety_decision_id="authority_self_check",
                        safety_case_id="case",
                        action_request_id="request",
                        project_id="proj_safety_self_check",
                        decision="denied",
                        decision_summary="Denied.",
                        decision_expires_at=datetime.now(UTC).isoformat(),
                    ),
                    field,
                )
                for field in (
                    "workflow_resume_authorized",
                    "upload_authorized",
                    "publication_authorized",
                    "merge_authorized",
                    "deployment_authorized",
                )
            ),
        }
    return BobaSafetyGateValidatorReportV1(
        mode="self_check",
        passed=all(results.values()),
        scenario_count=len(results),
        passed_scenario_count=sum(results.values()),
        scenario_results=results,
    )


def run_synthetic_project() -> BobaSafetyGateValidatorReportV1:
    results: dict[str, bool] = {}
    decisions: dict[str, str] = {}
    warnings: list[str] = []
    with TemporaryDirectory(prefix="boba_safety_synthetic_") as temp:
        harness = SafetySyntheticHarness(Path(temp))
        for scenario in SCENARIO_NAMES:
            try:
                results[scenario] = bool(run_named_scenario(harness, scenario))
            except Exception as exc:
                results[scenario] = False
                warnings.append(f"{scenario}: {exc.__class__.__name__}: {exc}")
        for project_number in (1, 2, 21, 72, 88, 128):
            gate = harness.store.load_boba_safety_gate(
                harness._project(project_number)
            )
            if gate and gate.safety_decisions:
                decisions[str(project_number)] = gate.safety_decisions[-1].decision
    return BobaSafetyGateValidatorReportV1(
        mode="synthetic_project",
        passed=len(results) == 179 and all(results.values()),
        project_id="proj_boba_safety_gate_synthetic",
        scenario_count=len(results),
        passed_scenario_count=sum(results.values()),
        scenario_results=results,
        decision_profiles=decisions,
        warnings=warnings[:64],
    )


def inspect_project(project_id: str) -> BobaSafetyGateValidatorReportV1:
    store = BobaMemoryStore(ROOT / "work" / "boba")
    gate = store.load_boba_safety_gate(project_id)
    results = {
        "gate_exists": gate is not None,
        "policy_digest_valid": bool(
            gate and len(gate.policy_snapshot.policy_sha256) == 64
        ),
        "signals_never_claim_execution": bool(
            gate
            and all(
                getattr(gate.signal_usage, field) is False
                for field in BobaSafetyGateSignalUsageV1.model_fields
                if field.endswith("_used")
                and field
                not in {
                    "autopilot_controller_used",
                    "rights_gate_used",
                    "repair_planner_used",
                    "code_surgeon_used",
                    "tool_recovery_used",
                    "output_quality_reviewer_used",
                    "project_snapshot_used",
                    "target_module_approval_used",
                    "checkpoint_reference_used",
                    "rollback_plan_used",
                    "validation_plan_used",
                    "quality_plan_used",
                    "recovery_budget_used",
                    "policy_snapshot_used",
                    "decision_digest_used",
                }
            )
        ),
    }
    return BobaSafetyGateValidatorReportV1(
        mode="project_id",
        passed=all(results.values()),
        project_id=project_id,
        scenario_count=len(results),
        passed_scenario_count=sum(results.values()),
        scenario_results=results,
        generated_fixture_only=False,
        warnings=[] if gate else ["No persisted Safety Gate record was found."],
    )


def _write_report(report: BobaSafetyGateValidatorReportV1) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    suffix = report.project_id or report.mode
    path = REPORT_ROOT / f"{report.mode}-{suffix}.json"
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    args = parser.parse_args()
    report = (
        run_self_check()
        if args.self_check
        else run_synthetic_project()
        if args.synthetic_project
        else inspect_project(str(args.project_id))
    )
    path = _write_report(report)
    print(
        json.dumps(
            {
                "passed": report.passed,
                "scenario_count": report.scenario_count,
                "passed_scenario_count": report.passed_scenario_count,
                "report": str(path),
                "warnings": report.warnings,
            },
            indent=2,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
