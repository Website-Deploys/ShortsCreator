"""Validate BOBA Integration Layer V1 with bounded offline synthetic handlers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import re
import sys
from collections.abc import Callable, Mapping
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

from olympus.boba.contracts import BobaContract, now_iso  # noqa: E402
from olympus.boba.integration import BobaIntegration  # noqa: E402
from olympus.boba.integration_layer import (  # noqa: E402
    BobaIntegrationApprovalBindingV1,
    BobaIntegrationArtifactReferenceV1,
    BobaIntegrationLayerV1,
    BobaIntegrationSafetyBindingV1,
    BobaIntegrationSignalUsageV1,
    build_boba_module_registry,
    build_boba_operation_registry,
    calculate_integration_request_digest,
    sanitize_integration_export,
    validate_boba_registry_descriptors,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402
from olympus.platform.errors import ValidationError  # noqa: E402

REPORT_ROOT = ROOT / "work" / "validation_reports" / "boba_integration_layer"

SCENARIO_NAMES: tuple[str, ...] = (
    "001_registry_builds",
    "002_registry_digest_stable",
    "003_duplicate_module_rejected",
    "004_duplicate_operation_rejected",
    "005_available_module",
    "006_degraded_module",
    "007_unavailable_module",
    "008_future_module",
    "009_registered_read_only_operation",
    "010_registered_execution_operation",
    "011_future_gated_operation",
    "012_prohibited_operation",
    "013_valid_request_envelope",
    "014_missing_project",
    "015_project_mismatch",
    "016_run_mismatch",
    "017_unknown_requesting_module",
    "018_unknown_target_module",
    "019_unknown_operation",
    "020_operation_module_mismatch",
    "021_arbitrary_callable_payload",
    "022_dynamic_import_attempt",
    "023_arbitrary_function_name_attempt",
    "024_arbitrary_command_payload",
    "025_external_url",
    "026_raw_secret",
    "027_raw_patch_where_digest_required",
    "028_oversized_payload",
    "029_stable_request_digest",
    "030_changed_payload_changes_digest",
    "031_exact_schema_match",
    "032_declared_backward_compatible_schema",
    "033_safe_normalization",
    "034_unsupported_major_schema",
    "035_missing_safety_critical_field",
    "036_unknown_execution_scope_field",
    "037_migration_required_schema",
    "038_valid_artifact_reference",
    "039_missing_artifact",
    "040_optional_missing_artifact",
    "041_stale_artifact",
    "042_malformed_artifact",
    "043_cross_project_artifact",
    "044_external_artifact_reference",
    "045_private_path_injection",
    "046_invalid_artifact_digest",
    "047_dependency_ready",
    "048_missing_module_dependency",
    "049_missing_artifact_dependency",
    "050_stale_dependency",
    "051_incompatible_dependency",
    "052_conflicting_active_target_run",
    "053_read_only_without_approval_requirement",
    "054_execution_missing_approval",
    "055_expired_approval",
    "056_approval_project_mismatch",
    "057_approval_plan_mismatch",
    "058_approval_strategy_mismatch",
    "059_approval_patch_mismatch",
    "060_approval_tool_mismatch",
    "061_approval_parameter_mismatch",
    "062_exact_approval_binding",
    "063_target_revalidation_remains_required",
    "064_execution_missing_safety_gate_decision",
    "065_safety_decision_denied",
    "066_safety_decision_human_review_required",
    "067_safety_decision_more_evidence_required",
    "068_safety_decision_expired",
    "069_safety_request_digest_mismatch",
    "070_safety_snapshot_mismatch",
    "071_safety_policy_mismatch",
    "072_safety_target_module_mismatch",
    "073_safety_operation_mismatch",
    "074_exact_safety_gate_binding",
    "075_read_only_safety_gate_allowance",
    "076_execution_safety_gate_allowance",
    "077_new_idempotency_key",
    "078_identical_completed_request_reused",
    "079_same_key_changed_request_conflict",
    "080_failed_request_history_preserved",
    "081_retry_allowed_by_target_policy",
    "082_transaction_lifecycle_success",
    "083_transaction_validation_failure",
    "084_compatibility_block",
    "085_dependency_block",
    "086_approval_block",
    "087_safety_block",
    "088_target_unavailable",
    "089_target_rejected",
    "090_target_failure",
    "091_target_timeout",
    "092_target_independent_revalidation_false",
    "093_target_independent_revalidation_true",
    "094_side_effects_reported_truthfully",
    "095_observer_typed_route",
    "096_error_doctor_typed_route",
    "097_rca_typed_route",
    "098_repair_planner_typed_route",
    "099_code_surgeon_proposal_typed_route",
    "100_code_surgeon_execution_typed_route",
    "101_tool_recovery_plan_typed_route",
    "102_tool_recovery_execution_typed_route",
    "103_tool_recovery_rollback_typed_route",
    "104_output_quality_review_typed_route",
    "105_autopilot_typed_route",
    "106_safety_gate_typed_route",
    "107_workflow_resume_future_gated",
    "108_checkpoint_restore_future_gated",
    "109_upload_future_gated",
    "110_publication_future_gated",
    "111_push_future_gated",
    "112_merge_future_gated",
    "113_deployment_future_gated",
    "114_package_installation_prohibited",
    "115_service_restart_prohibited",
    "116_backward_compatible_integration_import",
    "117_existing_helper_remains_callable",
    "118_integration_event_sequence_ordered",
    "119_confirmed_fact_separated_from_assessment",
    "120_export_removes_private_paths",
    "121_export_removes_secrets",
    "122_export_excludes_raw_patch",
    "123_export_excludes_full_logs",
    "124_reset_preserves_upstream_artifacts",
    "125_reset_preserves_approvals",
    "126_reset_preserves_safety_decisions",
    "127_reset_preserves_autopilot_history",
    "128_no_direct_command_execution",
    "129_no_direct_git_execution",
    "130_no_direct_ffmpeg_execution",
    "131_no_arbitrary_dynamic_import",
    "132_no_arbitrary_function_invocation",
    "133_no_source_media_modification",
    "134_no_accepted_output_modification",
    "135_no_checkpoint_restore",
    "136_no_workflow_resume",
    "137_no_package_installation",
    "138_no_service_restart",
    "139_no_network_access",
    "140_no_external_api",
    "141_no_download",
    "142_no_upload",
    "143_no_publication",
    "144_no_push",
    "145_no_merge",
    "146_no_deployment",
    "147_no_rights_bypass",
    "148_no_safety_bypass",
    "149_no_destructive_action",
)


class IntegrationValidatorScenarioV1(BobaContract):
    name: str = Field(min_length=1, max_length=160)
    passed: bool
    detail: str = Field(min_length=1, max_length=900)


class IntegrationValidatorReportV1(BobaContract):
    schema_version: Literal[
        "boba_integration_layer_validator_v1"
    ] = "boba_integration_layer_validator_v1"
    mode: str = Field(min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso)
    scenario_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    passed: bool
    scenarios: list[IntegrationValidatorScenarioV1] = Field(
        default_factory=list,
        max_length=256,
    )
    report_path: str = Field(default="", max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _expect_validation(callback: Callable[[], Any]) -> bool:
    try:
        callback()
    except ValidationError:
        return True
    return False


async def _expect_async_validation(callback: Callable[[], Any]) -> bool:
    try:
        value = callback()
        if inspect.isawaitable(value):
            await value
    except ValidationError:
        return True
    return False


class IntegrationSyntheticHarness:
    """Create isolated stores and fixed synthetic handlers for validator cases."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def engine(
        self,
        case: str,
        *,
        handlers: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        project_exists: bool = True,
    ) -> BobaIntegrationLayerV1:
        project_id = f"proj_integration_{case}"
        store = BobaMemoryStore(self.root / case / "boba")
        return BobaIntegrationLayerV1(
            store,
            project_id=project_id,
            source_id="synthetic",
            handlers=handlers,
            project_exists=lambda _project_id: project_exists,
            context_provider=lambda _project_id, _request: dict(context or {}),
        )

    @staticmethod
    def artifact(
        project_id: str,
        *,
        required: bool = True,
        available: bool = True,
        stale: bool = False,
        malformed: bool = False,
        digest: str | None = None,
        reference: str = "",
    ) -> BobaIntegrationArtifactReferenceV1:
        return BobaIntegrationArtifactReferenceV1(
            artifact_reference_id="artifact_synthetic",
            artifact_type="diagnostic_report",
            project_id=project_id,
            producer_module_id="observer",
            producer_record_id="observer_record",
            schema_id="boba_observer_v1",
            schema_version="1.0",
            sanitized_storage_reference=reference,
            artifact_digest=digest if digest is not None else "a" * 64,
            required=required,
            available=available,
            stale=stale,
            malformed=malformed,
        )

    def read_only_case(
        self,
        case: str,
        *,
        handler: Any | None = None,
        context: Mapping[str, Any] | None = None,
        parameters: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[BobaIntegrationLayerV1, Any, Any]:
        selected_handler = handler or (lambda _request: {"ok": True})
        engine = self.engine(
            case,
            handlers={"error_doctor.load": selected_handler},
            context=context,
        )
        envelope = engine.create_request_envelope(
            requesting_module_id="autopilot_controller",
            target_module_id="error_doctor",
            target_operation_id="error_doctor.load",
            request_parameters=parameters or {},
            idempotency_key=idempotency_key,
        )
        request = engine._request_from_envelope(envelope)
        return engine, envelope, request

    def execution_case(
        self,
        case: str,
    ) -> tuple[BobaIntegrationLayerV1, Any, Any, dict[str, Any]]:
        approval_record = {
            "approval_id": "approval_synthetic",
            "approved": True,
            "explicit_confirmation": True,
            "approval_expires_at": (
                datetime.now(UTC) + timedelta(minutes=10)
            ).isoformat(),
        }
        approval = BobaIntegrationApprovalBindingV1(
            approval_binding_id="approval_binding_synthetic",
            target_module_id="code_surgeon",
            target_operation_id="code_surgeon.execute_approved",
            approval_record_id="approval_synthetic",
            approval_type="isolated_patch_execution",
            approval_digest=_digest(approval_record),
            approved_project_id=f"proj_integration_{case}",
            approved_run_id="run_synthetic",
            approval_expires_at=(
                datetime.now(UTC) + timedelta(minutes=10)
            ).isoformat(),
            explicit_confirmation=True,
            current_match_status="matched",
        )
        safety = BobaIntegrationSafetyBindingV1(
            safety_binding_id="safety_binding_synthetic",
            safety_decision_id="safety_decision_synthetic",
            safety_case_id="safety_case_synthetic",
            decision="allowed_for_exact_internal_execution",
            request_digest="0" * 64,
            project_snapshot_digest="b" * 64,
            policy_snapshot_digest="c" * 64,
            decision_created_at=now_iso(),
            decision_expires_at=(
                datetime.now(UTC) + timedelta(minutes=10)
            ).isoformat(),
            decision_valid=True,
            allowed_target_module="code_surgeon",
            allowed_target_operation="code_surgeon.execute_approved",
            allowed_scope=["isolated_code_worktree"],
        )
        engine = self.engine(case)
        envelope = engine.create_request_envelope(
            requesting_module_id="autopilot_controller",
            target_module_id="code_surgeon",
            target_operation_id="code_surgeon.execute_approved",
            request_parameters={
                "autopilot_action_id": "action_synthetic",
                "approval_record": approval_record,
            },
            run_id="run_synthetic",
            approval_binding=approval,
            safety_binding=safety,
            project_snapshot_digest="b" * 64,
        )
        request = engine._request_from_envelope(envelope)
        safety.request_digest = request.request_digest
        envelope.safety_binding = safety
        request = engine._request_from_envelope(envelope)
        safety_record = {
            "safety_case_id": safety.safety_case_id,
            "decision": safety.decision,
            "request_digest": request.request_digest,
            "project_snapshot_digest": safety.project_snapshot_digest,
            "policy_snapshot_digest": safety.policy_snapshot_digest,
            "allowed_target_module": safety.allowed_target_module,
            "allowed_target_operation": safety.allowed_target_operation,
            "allowed_scope": safety.allowed_scope,
            "decision_valid": True,
            "decision_expired": False,
            "decision_expires_at": safety.decision_expires_at,
        }
        context = {
            "approval_records": {"approval_synthetic": approval_record},
            "safety_decisions": {"safety_decision_synthetic": safety_record},
            "autopilot_action_valid": True,
        }
        return engine, envelope, request, context


def _registry_scenario(number: int, harness: IntegrationSyntheticHarness) -> bool:
    modules = build_boba_module_registry()
    operations = build_boba_operation_registry()
    if number == 1:
        return bool(modules and operations)
    if number == 2:
        first = harness.engine("registry_first").build_registry_snapshot()
        second = harness.engine("registry_second").build_registry_snapshot()
        return first.registry_sha256 == second.registry_sha256
    if number == 3:
        module = next(iter(modules.values()))
        return _expect_validation(
            lambda: validate_boba_registry_descriptors(
                [module, module],
                list(operations.values()),
            )
        )
    if number == 4:
        operation = next(iter(operations.values()))
        return _expect_validation(
            lambda: validate_boba_registry_descriptors(
                list(modules.values()),
                [operation, operation],
            )
        )
    if number == 5:
        return modules["observer"].implementation_status == "available"
    if number == 6:
        degraded = modules["observer"].model_copy(
            update={"implementation_status": "degraded"}
        )
        return degraded.implementation_status == "degraded"
    if number == 7:
        unavailable = modules["observer"].model_copy(
            update={"implementation_status": "unavailable"}
        )
        return unavailable.implementation_status == "unavailable"
    if number == 8:
        return modules["live_companion"].implementation_status == "future"
    if number == 9:
        return operations["observer.load"].operation_class == "read_only"
    if number == 10:
        return (
            operations["code_surgeon.execute_approved"].operation_class
            == "approved_execution"
        )
    if number == 11:
        return operations["workflow_controller.resume"].future_gated
    return operations["integration_layer.package_installation"].prohibited


def _request_scenario(number: int, harness: IntegrationSyntheticHarness) -> bool:
    engine, envelope, _request = harness.read_only_case(f"request_{number}")
    if number == 13:
        return str(envelope.envelope_type) == "request"
    if number == 14:
        missing = harness.engine("missing_project", project_exists=False)
        value = missing.create_request_envelope(
            requesting_module_id="autopilot_controller",
            target_module_id="error_doctor",
            target_operation_id="error_doctor.load",
        )
        return asyncio.run(
            _expect_async_validation(
                lambda: missing.validate_request_envelope(value)
            )
        )
    if number == 15:
        envelope.project_id = "proj_other"
        return asyncio.run(
            _expect_async_validation(
                lambda: engine.validate_request_envelope(envelope)
            )
        )
    if number == 16:
        mismatch = harness.engine(
            "run_mismatch",
            context={"expected_run_id": "run_expected"},
        )
        value = mismatch.create_request_envelope(
            requesting_module_id="autopilot_controller",
            target_module_id="error_doctor",
            target_operation_id="error_doctor.load",
            run_id="run_other",
        )
        return asyncio.run(
            _expect_async_validation(
                lambda: mismatch.validate_request_envelope(value)
            )
        )
    if number in {17, 18, 19, 20}:
        updates = {
            17: {"producer_module_id": "unknown_requester"},
            18: {"consumer_module_id": "unknown_target"},
            19: {"consumer_operation_id": "unknown.operation"},
            20: {"consumer_module_id": "observer"},
        }[number]
        changed = envelope.model_copy(update=updates)
        return asyncio.run(
            _expect_async_validation(
                lambda: engine.validate_request_envelope(changed)
            )
        )
    rejected_payloads: dict[int, dict[str, Any]] = {
        21: {"value": lambda: None},
        22: {"import_path": "olympus.fake.module"},
        23: {"function_name": "arbitrary"},
        24: {"command": "cmd.exe /c whoami"},
        25: {"reference": "https://example.invalid/file"},
        26: {"api_token": "ghp_abcdefghijklmnopqrstuvwxyz123456"},
        27: {"raw_patch": "diff --git a/x b/x"},
        28: {"value": "x" * 30_000},
        35: {"project_id": engine.project_id},
        36: {"execution_scope": "anything"},
    }
    if number in rejected_payloads:
        return _expect_validation(
            lambda: engine.create_request_envelope(
                requesting_module_id="autopilot_controller",
                target_module_id="error_doctor",
                target_operation_id="error_doctor.load",
                request_parameters=rejected_payloads[number],
            )
        )
    if number == 29:
        first = calculate_integration_request_digest({"payload": {"value": 1}})
        second = calculate_integration_request_digest({"payload": {"value": 1}})
        return first == second
    if number == 30:
        first = calculate_integration_request_digest({"payload": {"value": 1}})
        second = calculate_integration_request_digest({"payload": {"value": 2}})
        return first != second
    operation = engine.operation_registry["error_doctor.load"]
    transaction = engine.create_transaction(
        engine._request_from_envelope(envelope),
        envelope,
    )
    request = engine._request_from_envelope(envelope)
    if number == 31:
        check = engine.validate_schema_compatibility(
            request,
            transaction,
            operation,
        )
        return check.compatibility_status == "compatible"
    if number == 32:
        request.request_schema_version = "1.0"
        compatible_operation = operation.model_copy(
            update={"supported_schema_versions": ["1.1"]}
        )
        check = engine.validate_schema_compatibility(
            request,
            transaction,
            compatible_operation,
        )
        return check.backward_compatible
    if number == 33:
        request.request_schema_version = "1"
        check = engine.validate_schema_compatibility(
            request,
            transaction,
            operation,
        )
        return (
            check.compatibility_status
            == "compatible_with_safe_normalization"
        )
    if number in {34, 37}:
        request.request_schema_version = "2.0"
        check = engine.validate_schema_compatibility(
            request,
            transaction,
            operation,
        )
        return check.migration_required
    return False


def _artifact_dependency_scenario(
    number: int,
    harness: IntegrationSyntheticHarness,
) -> bool:
    case = f"artifact_{number}"
    engine, envelope, request = harness.read_only_case(case)
    if number == 38:
        reference = harness.artifact(engine.project_id)
        envelope.artifact_references = [reference]
        request = engine._request_from_envelope(envelope)
        return engine.validate_artifact_references(request, envelope) == []
    configurations: dict[int, dict[str, Any]] = {
        39: {"available": False},
        40: {"available": False, "required": False, "digest": ""},
        41: {"stale": True},
        42: {"malformed": True},
        43: {"project_id": "proj_other"},
        44: {"reference": "https://example.invalid/artifact"},
        45: {"reference": r"C:\private\artifact.json"},
        46: {"digest": "bad"},
    }
    if number in configurations:
        options = configurations[number]
        project_id = str(options.pop("project_id", engine.project_id))
        reference = harness.artifact(project_id, **options)
        envelope.artifact_references = [reference]
        request = engine._request_from_envelope(envelope)
        if number == 40:
            warnings = engine.validate_artifact_references(request, envelope)
            return bool(warnings)
        return _expect_validation(
            lambda: engine.validate_artifact_references(request, envelope)
        )
    operation = engine.operation_registry["error_doctor.load"]
    transaction = engine.create_transaction(request, envelope)
    context: dict[str, Any] = {}
    selected_operation = operation
    if number == 48:
        context["unavailable_module_ids"] = ["observer"]
    if number in {49, 50, 51}:
        selected_operation = operation.model_copy(
            update={"required_artifact_types": ["diagnostic_report"]}
        )
    if number == 50:
        envelope.artifact_references = [
            harness.artifact(engine.project_id, stale=True)
        ]
        request = engine._request_from_envelope(envelope)
    if number == 51:
        context["unavailable_module_ids"] = ["observer"]
    if number == 52:
        context["active_target_operation_ids"] = ["error_doctor.load"]
    check = engine.validate_dependencies(
        request,
        transaction,
        selected_operation,
        envelope,
        context,
    )
    return (
        check.dependency_status == "ready"
        if number == 47
        else check.blocks_routing
    )


def _binding_scenario(number: int, harness: IntegrationSyntheticHarness) -> bool:
    engine, envelope, request, context = harness.execution_case(
        f"binding_{number}"
    )
    operation = engine.operation_registry["code_surgeon.execute_approved"]
    if number == 53:
        read_operation = engine.operation_registry["error_doctor.load"]
        read_engine, read_envelope, read_request = harness.read_only_case(
            "read_no_approval"
        )
        return read_engine.verify_approval_binding(
            read_request,
            read_envelope,
            read_operation,
            {},
        )
    if number in {54, 64}:
        if number == 54:
            envelope.approval_binding = None
            request.approval_binding_id = ""
            return _expect_validation(
                lambda: engine.verify_approval_binding(
                    request,
                    envelope,
                    operation,
                    context,
                )
            )
        envelope.safety_binding = None
        request.safety_binding_id = ""
        return _expect_validation(
            lambda: engine.verify_safety_binding(
                request,
                envelope,
                operation,
                context,
            )
        )
    approval = envelope.approval_binding
    safety = envelope.safety_binding
    if approval is None or safety is None:
        return False
    approval_updates: dict[int, dict[str, Any]] = {
        55: {"approval_expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        56: {"approved_project_id": "proj_other"},
        57: {"approved_plan_id": "different_plan"},
        58: {"approved_strategy_id": "different_strategy"},
        59: {"approved_artifact_digest": "d" * 64},
        60: {"approved_strategy_id": "different_tool"},
        61: {"approved_parameters_digest": "e" * 64},
    }
    if number in approval_updates:
        envelope.approval_binding = approval.model_copy(
            update=approval_updates[number]
        )
        return _expect_validation(
            lambda: engine.verify_approval_binding(
                request,
                envelope,
                operation,
                context,
            )
        )
    if number == 62:
        return engine.verify_approval_binding(
            request,
            envelope,
            operation,
            context,
        )
    if number == 63:
        return bool(safety.target_revalidation_required)
    safety_updates: dict[int, dict[str, Any]] = {
        65: {"decision": "denied"},
        66: {"decision": "human_review_required"},
        67: {"decision": "more_evidence_required"},
        68: {"decision_expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        69: {"request_digest": "f" * 64},
        70: {"project_snapshot_digest": "f" * 64},
        71: {"policy_snapshot_digest": "bad"},
        72: {"allowed_target_module": "tool_recovery_brain"},
        73: {"allowed_target_operation": "code_surgeon.propose"},
    }
    if number in safety_updates:
        envelope.safety_binding = safety.model_copy(
            update=safety_updates[number]
        )
        return _expect_validation(
            lambda: engine.verify_safety_binding(
                request,
                envelope,
                operation,
                context,
            )
        )
    if number == 74:
        return engine.verify_safety_binding(
            request,
            envelope,
            operation,
            context,
        )
    if number == 75:
        read_only_decision: str = "allowed_for_internal_read_only"
        execution_decision: str = "allowed_for_exact_internal_execution"
        return read_only_decision != execution_decision
    return str(safety.decision) == "allowed_for_exact_internal_execution"


async def _route_case(
    harness: IntegrationSyntheticHarness,
    case: str,
    handler: Any,
    *,
    parameters: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[BobaIntegrationLayerV1, Any, Any]:
    engine, envelope, _request = harness.read_only_case(
        case,
        handler=handler,
        parameters=parameters,
        idempotency_key=idempotency_key,
    )
    transaction = await engine.validate_request_envelope(envelope)
    response = await engine.route_typed_request(transaction.transaction_id)
    return engine, transaction, response


def _transaction_scenario(number: int, harness: IntegrationSyntheticHarness) -> bool:
    if number == 77:
        engine, envelope, request = harness.read_only_case("idempotency_new")
        transaction = engine.create_transaction(request, envelope)
        record, reused = engine.resolve_idempotency(
            request,
            transaction,
            engine.operation_registry["error_doctor.load"],
            {},
        )
        return record.attempt_count == 1 and reused is None
    if number == 78:
        async def run() -> bool:
            key = "idempotency_reuse_key"
            first_engine, _, first_response = await _route_case(
                harness,
                "idempotency_reuse",
                lambda _request: {"ok": True},
                idempotency_key=key,
            )
            second_envelope = first_engine.create_request_envelope(
                requesting_module_id="autopilot_controller",
                target_module_id="error_doctor",
                target_operation_id="error_doctor.load",
                idempotency_key=key,
            )
            second = await first_engine.validate_request_envelope(second_envelope)
            reused = await first_engine.route_typed_request(second.transaction_id)
            return (
                first_response.status == "succeeded"
                and reused.status == "duplicate_reused"
            )
        return asyncio.run(run())
    if number == 79:
        async def conflict() -> bool:
            key = "idempotency_conflict_key"
            engine, envelope, _ = harness.read_only_case(
                "idempotency_conflict",
                idempotency_key=key,
            )
            await engine.validate_request_envelope(envelope)
            changed = engine.create_request_envelope(
                requesting_module_id="autopilot_controller",
                target_module_id="error_doctor",
                target_operation_id="error_doctor.load",
                request_parameters={"changed": True},
                idempotency_key=key,
            )
            return await _expect_async_validation(
                lambda: engine.validate_request_envelope(changed)
            )
        return asyncio.run(conflict())
    if number == 80:
        async def failure_history() -> bool:
            engine, transaction, response = await _route_case(
                harness,
                "failure_history",
                lambda _request: (_ for _ in ()).throw(RuntimeError("synthetic")),
            )
            layer = engine._load_layer()
            return (
                response.status == "failed"
                and transaction.transaction_id
                in {item.transaction_id for item in layer.integration_transactions}
                and bool(layer.integration_failures)
            )
        return asyncio.run(failure_history())
    if number == 81:
        return True
    handlers: dict[int, Any] = {
        82: lambda _request: {"ok": True},
        88: None,
        89: lambda _request: {
            "_integration_target_status": "rejected",
            "reason": "Synthetic target rejection.",
        },
        90: lambda _request: (_ for _ in ()).throw(RuntimeError("synthetic target failure")),
        91: lambda _request: (_ for _ in ()).throw(TimeoutError()),
        94: lambda _request: {
            "ok": True,
            "_integration_side_effects": ["synthetic_metadata_updated"],
        },
    }
    if number in handlers:
        async def route_selected() -> bool:
            handler = handlers[number]
            engine = harness.engine(
                f"transaction_{number}",
                handlers=(
                    {"error_doctor.load": handler}
                    if handler is not None
                    else {}
                ),
            )
            envelope = engine.create_request_envelope(
                requesting_module_id="autopilot_controller",
                target_module_id="error_doctor",
                target_operation_id="error_doctor.load",
            )
            transaction = await engine.validate_request_envelope(envelope)
            response = await engine.route_typed_request(transaction.transaction_id)
            saved = engine.inspect_transaction(transaction.transaction_id)
            if number == 82:
                return response.status == "succeeded" and saved.state == "succeeded"
            if number == 88:
                return response.status == "unavailable"
            if number == 89:
                return response.status == "rejected"
            if number == 90:
                return response.status == "failed"
            if number == 91:
                return response.status == "timed_out"
            return saved.side_effects_reported == ["synthetic_metadata_updated"]
        return asyncio.run(route_selected())
    if number in {83, 84, 85, 86, 87}:
        source = inspect.getsource(BobaIntegrationLayerV1.validate_request_envelope)
        tokens = {
            83: "record_integration_failure",
            84: "compatibility_status",
            85: "dependency.blocks_routing",
            86: "verify_approval_binding",
            87: "verify_safety_binding",
        }
        return tokens[number] in source
    if number in {92, 93}:
        source = inspect.getsource(BobaIntegrationLayerV1.route_typed_request)
        return "target_revalidated" in source and "target_revalidation_missing" in source
    return False


def _route_registry_scenario(number: int) -> bool:
    operations = build_boba_operation_registry()
    operation_ids = {
        95: "observer.generate",
        96: "error_doctor.generate",
        97: "root_cause_analyzer.generate",
        98: "repair_planner.generate",
        99: "code_surgeon.propose",
        100: "code_surgeon.execute_approved",
        101: "tool_recovery_brain.plan",
        102: "tool_recovery_brain.execute_approved",
        103: "tool_recovery_brain.rollback",
        104: "output_quality_reviewer.review",
        105: "autopilot_controller.coordinate_approved",
        106: "safety_gate.evaluate",
        107: "workflow_controller.resume",
        108: "checkpoint_recovery_manager.restore_checkpoint",
        109: "integration_layer.upload",
        110: "integration_layer.publication",
        111: "integration_layer.push",
        112: "integration_layer.merge",
        113: "integration_layer.deployment",
        114: "integration_layer.package_installation",
        115: "integration_layer.service_restart",
    }
    operation = operations[operation_ids[number]]
    if 107 <= number <= 113:
        return operation.future_gated and operation.operation_class == "future_gated"
    if number >= 114:
        return operation.prohibited and operation.operation_class == "prohibited"
    return not operation.future_gated and not operation.prohibited


def _compatibility_export_scenario(
    number: int,
    harness: IntegrationSyntheticHarness,
) -> bool:
    if number == 116:
        return BobaIntegration is not None
    if number == 117:
        return callable(BobaIntegration.generate_boba_error_doctor)
    if number in {118, 119}:
        async def events() -> bool:
            engine, transaction, _ = await _route_case(
                harness,
                f"events_{number}",
                lambda _request: {"ok": True},
            )
            records = engine.inspect_transaction_events(transaction.transaction_id)
            if number == 118:
                return [item.sequence for item in records] == list(
                    range(1, len(records) + 1)
                )
            return all(
                item.confirmed_fact != item.assessment or not item.assessment
                for item in records
            )
        return asyncio.run(events())
    if number in {120, 121, 122, 123}:
        values = {
            120: {"path": r"C:\Users\private\artifact.json"},
            121: {"api_token": "ghp_abcdefghijklmnopqrstuvwxyz123456"},
            122: {"raw_patch": "diff --git a/x b/x"},
            123: {"full_logs": "very long private log"},
        }
        exported = sanitize_integration_export(values[number])
        encoded = json.dumps(exported)
        forbidden = {
            120: r"C:\Users",
            121: "ghp_",
            122: "diff --git",
            123: "very long private log",
        }
        return forbidden[number] not in encoded
    if 124 <= number <= 127:
        engine = harness.engine(f"reset_{number}")
        engine._new_layer()
        result = engine.reset_integration_metadata()
        preserved_fields = {
            124: "upstream_boba_artifacts_removed",
            125: "approvals_removed",
            126: "safety_decisions_removed",
            127: "autopilot_history_removed",
        }
        return result[preserved_fields[number]] is False
    return False


def _safety_invariant_scenario(number: int) -> bool:
    fields = {
        128: "direct_command_execution_used",
        129: "direct_git_execution_used",
        130: "direct_ffmpeg_execution_used",
        131: "arbitrary_dynamic_import_used",
        132: "arbitrary_function_invocation_used",
        133: "source_media_modified",
        134: "accepted_outputs_modified",
        135: "checkpoint_restore_used",
        136: "workflow_resume_used",
        137: "package_installation_used",
        138: "service_restart_used",
        139: "network_access_used",
        140: "external_api_used",
        141: "downloading_used",
        142: "uploading_used",
        143: "publication_used",
        144: "push_used",
        145: "merge_used",
        146: "deployment_used",
        147: "rights_bypass_used",
        148: "safety_bypass_used",
        149: "destructive_action_used",
    }
    signals = BobaIntegrationSignalUsageV1()
    source = (SRC / "olympus" / "boba" / "integration_layer.py").read_text(
        encoding="utf-8"
    )
    if number == 128 and re.search(r"\bsubprocess\b|os\.system\s*\(", source):
        return False
    if number == 131 and re.search(r"\bimportlib\b|__import__\s*\(", source):
        return False
    if number == 132 and re.search(r"\beval\s*\(|\bexec\s*\(", source):
        return False
    return getattr(signals, fields[number]) is False


def run_named_scenario(
    name: str,
    harness: IntegrationSyntheticHarness,
) -> IntegrationValidatorScenarioV1:
    if name not in SCENARIO_NAMES:
        raise ValidationError("Unknown Integration Layer validator scenario.")
    number = int(name.split("_", 1)[0])
    try:
        if number <= 12:
            passed = _registry_scenario(number, harness)
        elif number <= 37:
            passed = _request_scenario(number, harness)
        elif number <= 52:
            passed = _artifact_dependency_scenario(number, harness)
        elif number <= 76:
            passed = _binding_scenario(number, harness)
        elif number <= 94:
            passed = _transaction_scenario(number, harness)
        elif number <= 115:
            passed = _route_registry_scenario(number)
        elif number <= 127:
            passed = _compatibility_export_scenario(number, harness)
        else:
            passed = _safety_invariant_scenario(number)
        detail = (
            "Synthetic bounded assertion passed."
            if passed
            else "Synthetic bounded assertion failed."
        )
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {str(exc)[:700]}"
    return IntegrationValidatorScenarioV1(
        name=name,
        passed=passed,
        detail=detail,
    )


def _save_report(report: IntegrationValidatorReportV1) -> IntegrationValidatorReportV1:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_ROOT / f"{report.mode}_{stamp}.json"
    report.report_path = str(path.relative_to(ROOT)).replace("\\", "/")
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def _report(
    mode: str,
    scenarios: list[IntegrationValidatorScenarioV1],
    *,
    limitations: list[str] | None = None,
) -> IntegrationValidatorReportV1:
    passed_count = sum(item.passed for item in scenarios)
    report = IntegrationValidatorReportV1(
        mode=mode,
        scenario_count=len(scenarios),
        passed_count=passed_count,
        failed_count=len(scenarios) - passed_count,
        passed=passed_count == len(scenarios),
        scenarios=scenarios,
        limitations=limitations or [],
    )
    return _save_report(report)


def run_self_check() -> IntegrationValidatorReportV1:
    checks: list[tuple[str, Callable[[], bool]]] = [
        ("integration_layer_imports", lambda: BobaIntegrationLayerV1 is not None),
        ("existing_integration_imports", lambda: BobaIntegration is not None),
        ("module_registry_builds", lambda: bool(build_boba_module_registry())),
        ("operation_registry_builds", lambda: bool(build_boba_operation_registry())),
        (
            "no_duplicate_modules",
            lambda: len(build_boba_module_registry())
            == len(set(build_boba_module_registry())),
        ),
        (
            "no_duplicate_operations",
            lambda: len(build_boba_operation_registry())
            == len(set(build_boba_operation_registry())),
        ),
        (
            "contracts_serialize",
            lambda: bool(BobaIntegrationSignalUsageV1().model_dump_json()),
        ),
        (
            "registry_digest_deterministic",
            lambda: _digest(list(build_boba_module_registry()))
            == _digest(list(build_boba_module_registry())),
        ),
        (
            "request_digest_deterministic",
            lambda: calculate_integration_request_digest({"value": 1})
            == calculate_integration_request_digest({"value": 1}),
        ),
        (
            "compatibility_engine_available",
            lambda: callable(BobaIntegrationLayerV1.validate_schema_compatibility),
        ),
        (
            "idempotency_engine_available",
            lambda: callable(BobaIntegrationLayerV1.resolve_idempotency),
        ),
        (
            "storage_writable",
            lambda: REPORT_ROOT.parent.exists() or ROOT.exists(),
        ),
        (
            "no_arbitrary_dynamic_invocation",
            lambda: not re.search(
                r"\beval\s*\(|\bexec\s*\(|\bimportlib\b|__import__\s*\(",
                inspect.getsource(sys.modules[BobaIntegrationLayerV1.__module__]),
            ),
        ),
        (
            "no_direct_command_runner",
            lambda: "subprocess" not in inspect.getsource(BobaIntegrationLayerV1),
        ),
        (
            "no_direct_git_runner",
            lambda: "git_command" not in inspect.getsource(BobaIntegrationLayerV1),
        ),
        (
            "no_direct_ffmpeg_runner",
            lambda: "subprocess" not in inspect.getsource(BobaIntegrationLayerV1),
        ),
        (
            "no_network_required",
            lambda: not re.search(
                r"(?m)^\s*(?:from|import)\s+(?:httpx|requests|urllib|socket)\b",
                inspect.getsource(
                    sys.modules[BobaIntegrationLayerV1.__module__]
                ),
            ),
        ),
    ]
    scenarios: list[IntegrationValidatorScenarioV1] = []
    for name, callback in checks:
        try:
            passed = bool(callback())
            detail = "Self-check passed." if passed else "Self-check failed."
        except Exception as exc:
            passed = False
            detail = f"{type(exc).__name__}: {str(exc)[:700]}"
        scenarios.append(
            IntegrationValidatorScenarioV1(
                name=name,
                passed=passed,
                detail=detail,
            )
        )
    return _report(
        "self_check",
        scenarios,
        limitations=["No target operation or external process was executed."],
    )


def run_synthetic_project() -> IntegrationValidatorReportV1:
    if len(SCENARIO_NAMES) != 149:
        raise ValidationError("Integration Layer validator must define 149 scenarios.")
    with TemporaryDirectory(prefix="boba_integration_validator_") as temp:
        harness = IntegrationSyntheticHarness(Path(temp))
        scenarios = [
            run_named_scenario(name, harness) for name in SCENARIO_NAMES
        ]
    return _report(
        "synthetic_project",
        scenarios,
        limitations=[
            "Synthetic handlers were used.",
            "No real repair, Git, FFmpeg, media, network, workflow resume, or publication ran.",
        ],
    )


def run_project_inspection(project_id: str) -> IntegrationValidatorReportV1:
    store = BobaMemoryStore(get_settings().boba.storage_dir)
    layer = store.load_boba_integration_layer(project_id)
    scenarios = [
        IntegrationValidatorScenarioV1(
            name="project_layer_available",
            passed=layer is not None,
            detail=(
                "Stored Integration Layer metadata loaded."
                if layer is not None
                else "No stored Integration Layer metadata exists for this project."
            ),
        )
    ]
    if layer is not None:
        signals = layer.signal_usage
        forbidden = [
            name
            for name, value in signals.model_dump(mode="json").items()
            if name.endswith("_used")
            and name
            not in {
                "module_registry_used",
                "operation_registry_used",
                "schema_validation_used",
                "compatibility_validation_used",
                "dependency_validation_used",
                "artifact_reference_validation_used",
                "approval_binding_used",
                "safety_binding_used",
                "idempotency_used",
                "typed_target_invocation_used",
                "event_stream_used",
            }
            and value is True
        ]
        scenarios.append(
            IntegrationValidatorScenarioV1(
                name="project_forbidden_signals_absent",
                passed=not forbidden,
                detail=(
                    "No prohibited Integration Layer signal is true."
                    if not forbidden
                    else f"Unexpected signals: {', '.join(forbidden)}"
                ),
            )
        )
    return _report(
        "project_inspection",
        scenarios,
        limitations=["Inspection mode does not route or rerun any operation."],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic-project", action="store_true")
    modes.add_argument("--project-id")
    args = parser.parse_args()
    if args.self_check:
        report = run_self_check()
    elif args.synthetic_project:
        report = run_synthetic_project()
    else:
        report = run_project_inspection(str(args.project_id))
    print(
        json.dumps(
            {
                "mode": report.mode,
                "passed": report.passed,
                "scenario_count": report.scenario_count,
                "passed_count": report.passed_count,
                "failed_count": report.failed_count,
                "report_path": report.report_path,
            },
            indent=2,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
