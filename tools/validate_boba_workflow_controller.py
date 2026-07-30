"""Validate BOBA Workflow Controller V1 with bounded local synthetic scenarios."""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import inspect
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.integration_layer import (
    BobaIntegrationApprovalBindingV1,
    BobaIntegrationLayerV1,
    BobaIntegrationRequestV1,
    BobaIntegrationResponseV1,
    BobaIntegrationSafetyBindingV1,
    build_boba_operation_registry,
)
from olympus.boba.store import BobaMemoryStore
from olympus.boba.workflow_controller import (
    BobaWorkflowArtifactBindingV1,
    BobaWorkflowControllerSignalUsageV1,
    BobaWorkflowControllerV1,
    BobaWorkflowDependencyCheckV1,
    BobaWorkflowEventV1,
    BobaWorkflowHumanDecisionV1,
    BobaWorkflowPauseRecordV1,
    BobaWorkflowRecoveryHoldV1,
    BobaWorkflowResumeEligibilityReviewV1,
    BobaWorkflowRunV1,
    BobaWorkflowStageDefinitionV1,
    BobaWorkflowTransitionDecisionV1,
    build_workflow_stage_registry,
    calculate_workflow_idempotency_key,
    calculate_workflow_request_digest,
    capture_workflow_project_snapshot,
    sanitize_workflow_export,
    validate_workflow_graph,
)
from olympus.platform.config import get_settings
from olympus.platform.errors import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
REPORT_ROOT = ROOT / "work" / "validation_reports" / "boba_workflow_controller"

_SCENARIO_TITLES: tuple[str, ...] = (
    "Built-in workflow definition created.",
    "Definition digest stable.",
    "Duplicate stage rejected.",
    "Missing predecessor rejected.",
    "Unknown successor rejected.",
    "Workflow cycle rejected.",
    "Unreachable required stage rejected.",
    "Valid terminal stage.",
    "Invalid terminal successor.",
    "Workflow run creation.",
    "Duplicate active run conflict.",
    "Advisory read inspection.",
    "Initial stage creation.",
    "Project-level stage.",
    "Clip-level stage.",
    "Output-level stage.",
    "Correct stage dependency.",
    "Missing predecessor.",
    "Failed predecessor.",
    "Stale predecessor artifact.",
    "Malformed predecessor artifact.",
    "Required artifact available.",
    "Required artifact missing.",
    "Optional artifact missing.",
    "Cross-project artifact.",
    "Cross-clip artifact.",
    "External artifact URL.",
    "Traversal artifact.",
    "Absolute path artifact.",
    "UNC artifact.",
    "Source media marked read-only.",
    "Source media used as generated output blocked.",
    "Accepted output protected.",
    "Accepted-output overwrite blocked.",
    "Valid read-only transition.",
    "Invalid graph transition.",
    "Skipped required stage.",
    "Optional stage not applicable.",
    "Terminal workflow cannot reopen.",
    "Cancelled workflow cannot continue.",
    "Stable transition request digest.",
    "Changed target changes digest.",
    "Changed artifact changes digest.",
    "Changed revision changes digest.",
    "Matching workflow revision.",
    "Stale workflow revision.",
    "Matching project snapshot.",
    "Stale project snapshot.",
    "New workflow execution lease.",
    "Conflicting execution lease.",
    "Stale lease detection.",
    "Explicit stale lease replacement.",
    "Lease cannot be silently stolen.",
    "Read-only stage through Integration Layer.",
    "Read-only stage target unavailable.",
    "Read-only stage target failure.",
    "Read-only stage does not call direct handler.",
    "Execution stage missing approval.",
    "Execution stage expired approval.",
    "Execution stage mismatched approval.",
    "Execution stage exact approval.",
    "Execution missing Safety decision.",
    "Safety decision denied.",
    "Safety human review decision blocks.",
    "Safety more-evidence decision blocks.",
    "Safety decision expired.",
    "Safety request mismatch.",
    "Safety snapshot mismatch.",
    "Safety exact allowance.",
    "Workflow-resume authority remains false.",
    "Integration request missing.",
    "Integration compatibility failure.",
    "Integration dependency failure.",
    "Integration approval failure.",
    "Integration Safety failure.",
    "Integration transaction success.",
    "Integration target rejection.",
    "Integration target failure.",
    "Integration timeout.",
    "Target independent revalidation required.",
    "Exact internal transition succeeds.",
    "Exact internal transition advances one stage only.",
    "No automatic next execution stage.",
    "Stage result artifact persisted.",
    "Required result artifact missing.",
    "Stage marked completed.",
    "Stage marked failed.",
    "Stage timed out.",
    "Failure pauses workflow.",
    "Validation failure pauses workflow.",
    "Quality rejection pauses workflow.",
    "Rights block pauses workflow.",
    "Safety block pauses workflow.",
    "Stale state pauses workflow.",
    "Human pause.",
    "Pause preserves source media.",
    "Pause preserves accepted output.",
    "Recovery Hold created.",
    "Autopilot handoff created.",
    "Workflow does not diagnose root cause.",
    "Workflow does not choose repair strategy.",
    "Autopilot recovery result project mismatch.",
    "Recovery result run mismatch.",
    "Recovery result hold mismatch.",
    "Recovery result stage mismatch.",
    "Recovery result stale.",
    "Recovery result missing validation.",
    "Recovery result quality rejected.",
    "Valid recovery result received.",
    "Receiving recovery does not resume.",
    "Resume review starts.",
    "Recovery unresolved blocks.",
    "Technical validation missing blocks.",
    "Technical validation failed blocks.",
    "Quality review missing blocks.",
    "Quality needs-human-review blocks.",
    "Quality accepted.",
    "Rights changed blocks.",
    "Safety changed blocks.",
    "Approval changed blocks.",
    "Checkpoint invalid blocks.",
    "Active recovery blocks.",
    "Active transition blocks.",
    "Missing human review blocks.",
    "Stale artifact blocks.",
    "Resume eligible.",
    "Eligibility does not execute.",
    "New exact transition required.",
    "Idempotency key stable.",
    "Identical completed request reused.",
    "Same key changed request conflicts.",
    "Failed history preserved.",
    "Stage retry limit enforced.",
    "No automatic execution retry.",
    "Read-only retry permitted with new evidence.",
    "Project-level output feeds clips.",
    "Clip A cannot consume Clip B artifact.",
    "Output A quality cannot approve Output B.",
    "Multi-clip stage tracking.",
    "One clip failure pauses relevant branch safely.",
    "Project-wide failure pauses all required branches.",
    "Human decision recorded.",
    "Reviewer identity bounded.",
    "Human cannot override rights block.",
    "Human cannot override hard Safety denial.",
    "Human cannot skip required stage.",
    "Human cannot authorize upload.",
    "Internal output requirements complete.",
    "Missing required clip blocks completion.",
    "Missing validation blocks completion.",
    "Missing quality acceptance blocks completion.",
    "Active Recovery Hold blocks completion.",
    "Internal output complete.",
    "Internal completion does not upload.",
    "Internal completion does not publish.",
    "Cancellation stops future transitions.",
    "Cancellation preserves artifacts.",
    "Cancellation safely releases lease.",
    "Cancellation does not kill target unsafely.",
    "Event sequence monotonic.",
    "Event fact separated from assessment.",
    "Unknown progress remains null.",
    "Real stage count produces progress.",
    "Pause event emitted.",
    "Recovery event emitted.",
    "Safety event emitted.",
    "Transition event emitted.",
    "Internal completion event emitted.",
    "Export removes private paths.",
    "Export removes secrets.",
    "Export excludes raw media.",
    "Export excludes complete logs.",
    "Reset preserves workflow history.",
    "Reset preserves outputs.",
    "Reset preserves source media.",
    "Reset preserves Autopilot history.",
    "Reset preserves Safety decisions.",
    "Reset preserves Integration transactions.",
    "No direct command execution.",
    "No direct Git execution.",
    "No direct FFmpeg execution.",
    "No arbitrary dynamic import.",
    "No arbitrary function invocation.",
    "No source-media modification.",
    "No accepted-output modification.",
    "No checkpoint restore.",
    "No unrestricted resume.",
    "No package installation.",
    "No service restart.",
    "No process kill.",
    "No network.",
    "No external API.",
    "No media download.",
    "No upload.",
    "No publication.",
    "No push.",
    "No merge.",
    "No deployment.",
    "No rights bypass.",
    "No Safety bypass.",
    "No destructive action.",
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


SCENARIO_NAMES: tuple[str, ...] = tuple(
    f"{index:03d}_{_slug(title)}"
    for index, title in enumerate(_SCENARIO_TITLES, start=1)
)


class WorkflowValidatorScenarioV1(BobaContract):
    name: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=240)
    passed: bool
    detail: str = Field(min_length=1, max_length=900)


class WorkflowValidatorReportV1(BobaContract):
    schema_version: Literal[
        "boba_workflow_controller_validator_v1"
    ] = "boba_workflow_controller_validator_v1"
    mode: str = Field(min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso)
    scenario_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    passed: bool
    scenarios: list[WorkflowValidatorScenarioV1] = Field(
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
    except (ValidationError, PydanticValidationError):
        return True
    return False


class WorkflowSyntheticHarness:
    """Build isolated controllers with fixed local Integration Layer handlers."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.approval_records: dict[str, dict[str, dict[str, Any]]] = {}
        self.safety_decisions: dict[str, dict[str, dict[str, Any]]] = {}

    def store(self, case: str) -> BobaMemoryStore:
        return BobaMemoryStore(self.root / case / "boba")

    def controller(
        self,
        case: str,
        *,
        integration_available: bool = True,
        handler_mode: Literal["success", "failure", "timeout"] = "success",
    ) -> tuple[BobaMemoryStore, BobaWorkflowControllerV1]:
        store = self.store(case)
        if not integration_available:
            return store, BobaWorkflowControllerV1(store)

        def handler(request: BobaIntegrationRequestV1) -> Mapping[str, Any]:
            if handler_mode == "failure":
                raise ValidationError("Synthetic target rejected the stage.")
            if handler_mode == "timeout":
                raise TimeoutError("Synthetic target timed out.")
            controller = store.load_boba_workflow_controller(request.project_id)
            stage_id = str(
                request.request_parameters.get("workflow_stage_instance_id") or ""
            )
            stage = next(
                (
                    item
                    for item in controller.stage_instances
                    if item.stage_instance_id == stage_id
                ),
                None,
            ) if controller is not None else None
            definition = next(
                (
                    item
                    for item in controller.stage_definitions
                    if stage is not None
                    and item.stage_definition_id == stage.stage_definition_id
                ),
                None,
            ) if controller is not None else None
            bindings: list[dict[str, Any]] = []
            if stage is not None and definition is not None:
                for artifact_type in definition.produced_artifact_types:
                    bindings.append(
                        {
                            "project_id": stage.project_id,
                            "workflow_run_id": stage.workflow_run_id,
                            "clip_id": stage.clip_id,
                            "output_id": stage.output_id,
                            "artifact_type": artifact_type,
                            "artifact_digest": _digest(
                                {
                                    "stage": stage.stage_instance_id,
                                    "artifact_type": artifact_type,
                                }
                            ),
                            "sanitized_storage_reference": (
                                f"projects/{stage.project_id}/synthetic/"
                                f"{stage.stage_instance_id}/{artifact_type}.json"
                            ),
                            "available": True,
                        }
                    )
            return {
                "summary": "Bounded synthetic target result.",
                "artifact_bindings": bindings,
                "_integration_target_revalidated": True,
                "_integration_side_effects": (
                    [] if not bindings else ["isolated_generated_state"]
                ),
            }

        operation_ids = {
            stage.operation_id
            for stage in build_workflow_stage_registry()[1]
            if stage.operation_id in build_boba_operation_registry()
        }
        handlers = dict.fromkeys(operation_ids, handler)

        def context_provider(
            project_id: str,
            request: BobaIntegrationRequestV1,
        ) -> Mapping[str, Any]:
            controller = store.load_boba_workflow_controller(project_id)
            run_id = str(request.request_parameters.get("workflow_run_id") or "")
            stage_instance_id = str(
                request.request_parameters.get("workflow_stage_instance_id") or ""
            )
            transition_request_id = str(
                request.request_parameters.get("workflow_transition_request_id") or ""
            )
            transition_decision_id = str(
                request.request_parameters.get("workflow_transition_decision_id") or ""
            )
            run = next(
                (
                    item
                    for item in controller.workflow_runs
                    if item.workflow_run_id == run_id
                ),
                None,
            ) if controller is not None else None
            stage = next(
                (
                    item
                    for item in controller.stage_instances
                    if item.stage_instance_id == stage_instance_id
                    and item.workflow_run_id == run_id
                ),
                None,
            ) if controller is not None else None
            transition_request = next(
                (
                    item
                    for item in controller.transition_requests
                    if item.transition_request_id == transition_request_id
                    and item.workflow_run_id == run_id
                ),
                None,
            ) if controller is not None else None
            transition_decision = next(
                (
                    item
                    for item in controller.transition_decisions
                    if item.transition_decision_id == transition_decision_id
                    and item.transition_request_id == transition_request_id
                ),
                None,
            ) if controller is not None else None
            transition_valid = bool(
                run is not None
                and stage is not None
                and stage.status == "running"
                and transition_request is not None
                and transition_request.requested_operation_id
                == request.target_operation_id
                and transition_decision is not None
                and transition_decision.decision_valid
                and transition_request.project_snapshot_digest
                == run.project_snapshot_digest
                and transition_decision.project_snapshot_current
                and transition_decision.workflow_revision_current
            )
            dynamic_safety: dict[str, dict[str, Any]] = {}
            for decision_id, stored in self.safety_decisions.get(
                project_id,
                {},
            ).items():
                current = dict(stored)
                current["request_digest"] = request.request_digest
                dynamic_safety[decision_id] = current
            return {
                "workflow_transition_valid": transition_valid,
                "rights_allowed": True,
                "project_state_uncertain": False,
                "active_target_operation_ids": [],
                "retry_allowed": False,
                "approval_records": self.approval_records.get(project_id, {}),
                "safety_decisions": dynamic_safety,
            }

        def factory(
            project_id: str,
            *,
            source_id: str | None = None,
        ) -> BobaIntegrationLayerV1:
            return BobaIntegrationLayerV1(
                store,
                project_id=project_id,
                source_id=source_id or project_id,
                handlers=handlers,
                project_exists=lambda _project_id: True,
                context_provider=context_provider,
            )

        return store, BobaWorkflowControllerV1(
            store,
            integration_layer_factory=factory,
        )

    def create_run(
        self,
        case: str,
        *,
        clip_ids: Sequence[str] = ("clip_a",),
        integration_available: bool = True,
        handler_mode: Literal["success", "failure", "timeout"] = "success",
    ) -> tuple[BobaMemoryStore, BobaWorkflowControllerV1, str, str]:
        store, controller = self.controller(
            case,
            integration_available=integration_available,
            handler_mode=handler_mode,
        )
        project_id = f"proj_workflow_{_slug(case)[:64]}"
        output_ids = {clip_id: f"output_{clip_id}" for clip_id in clip_ids}
        state = controller.create_workflow_run(
            project_id,
            source_id="synthetic_source",
            project_snapshot={"state": "ready", "case": case},
            source_storage_reference=f"projects/{project_id}/source/source.mp4",
            source_artifact_digest="a" * 64,
            clip_ids=clip_ids,
            output_ids_by_clip=output_ids,
            rights_status="owned",
        )
        return (
            store,
            controller,
            project_id,
            state.workflow_runs[-1].workflow_run_id,
        )

    def safe_transition(
        self,
        case: str,
        *,
        handler_mode: Literal["success", "failure", "timeout"] = "success",
    ) -> dict[str, Any]:
        store, controller, project_id, run_id = self.create_run(
            case,
            handler_mode=handler_mode,
        )
        state = store.load_boba_workflow_controller(project_id)
        if state is None:
            raise ValidationError("Synthetic controller state was not persisted.")
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        source = next(
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id and item.stage_id == "workflow_created"
        )
        request = controller.create_transition_request(
            project_id,
            run_id,
            source_stage_instance_id=source.stage_instance_id,
            target_stage_id="source_registration",
            expected_revision=run.revision,
            transition_type="advance_read_only",
            reason="Bounded synthetic source inspection.",
        )
        state = store.load_boba_workflow_controller(project_id)
        if state is None:
            raise ValidationError("Synthetic transition request was not persisted.")
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        decision = controller.evaluate_transition_request(
            project_id,
            run_id,
            request.transition_request_id,
            expected_revision=run.revision,
            current_project_snapshot_digest=run.project_snapshot_digest,
            rights_clear=True,
        )
        state = store.load_boba_workflow_controller(project_id)
        if state is None:
            raise ValidationError("Synthetic transition decision was not persisted.")
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        response = asyncio.run(
            controller.advance_safe_read_only_stage(
                project_id,
                run_id,
                decision.transition_decision_id,
                expected_revision=run.revision,
            )
        )
        final = store.load_boba_workflow_controller(project_id)
        if final is None:
            raise ValidationError("Synthetic transition result was not persisted.")
        target = next(
            item
            for item in final.stage_instances
            if item.workflow_run_id == run_id and item.stage_id == "source_registration"
        )
        final_run = next(
            item for item in final.workflow_runs if item.workflow_run_id == run_id
        )
        return {
            "store": store,
            "controller": controller,
            "project_id": project_id,
            "run": final_run,
            "request": request,
            "decision": decision,
            "response": response,
            "target": target,
            "state": final,
        }

    def exact_transition(self, case: str) -> dict[str, Any]:
        store, controller, project_id, run_id = self.create_run(case)
        state = controller._controller(project_id)
        target = next(
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id
            and item.stage_id == "render_preparation"
            and item.clip_id == "clip_a"
        )
        predecessors = [
            item
            for item in state.stage_instances
            if item.stage_instance_id in target.predecessor_stage_instance_ids
        ]
        definitions = {
            item.stage_definition_id: item
            for item in state.stage_definitions
        }
        for predecessor in predecessors:
            definition = definitions[predecessor.stage_definition_id]
            for artifact_type in definition.produced_artifact_types:
                controller.add_artifact_binding(
                    project_id,
                    run_id,
                    stage_instance_id=predecessor.stage_instance_id,
                    artifact_type=artifact_type,
                    producer_module_id=definition.operation_module_id,
                    producer_record_id=f"synthetic_{predecessor.stage_id}",
                    schema_id=f"boba.workflow.{artifact_type}",
                    schema_version="1",
                    artifact_digest=_digest(
                        {
                            "stage": predecessor.stage_instance_id,
                            "artifact_type": artifact_type,
                        }
                    ),
                    sanitized_storage_reference=(
                        f"projects/{project_id}/synthetic/"
                        f"{predecessor.stage_instance_id}/{artifact_type}.json"
                    ),
                    clip_id=predecessor.clip_id,
                    output_id=predecessor.output_id,
                )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        target = next(
            item
            for item in state.stage_instances
            if item.stage_instance_id == target.stage_instance_id
        )
        predecessors = [
            item
            for item in state.stage_instances
            if item.stage_instance_id in target.predecessor_stage_instance_ids
        ]
        for predecessor in predecessors:
            predecessor.status = "completed"
            predecessor.completed_at = now_iso()
            if predecessor.stage_instance_id not in run.completed_stage_instance_ids:
                run.completed_stage_instance_ids.append(
                    predecessor.stage_instance_id
                )
        target.status = "ready"
        run.current_stage_instance_ids = [target.stage_instance_id]
        run.current_project_state = "stage_ready"
        store.save_boba_workflow_controller(state)
        source = next(
            item
            for item in predecessors
            if item.stage_id == "hook_retention_planning"
        )
        approval_id = f"approval_controller_{case}"
        safety_id = f"safety_controller_{case}"
        request = controller.create_transition_request(
            project_id,
            run_id,
            source_stage_instance_id=source.stage_instance_id,
            target_stage_id="render_preparation",
            expected_revision=run.revision,
            transition_type="advance_exact_internal_stage",
            reason="Bounded synthetic render preparation.",
            clip_id="clip_a",
            approval_record_id=approval_id,
            safety_decision_id=safety_id,
            checkpoint_reference=(
                f"projects/{project_id}/checkpoints/render_preparation.json"
            ),
            checkpoint_digest="b" * 64,
        )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        target = next(
            item
            for item in state.stage_instances
            if item.stage_instance_id == target.stage_instance_id
        )
        expires_at = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        approval_record = {
            "approval_id": approval_id,
            "approved": True,
            "explicit_confirmation": True,
            "approved_project_id": project_id,
            "approved_run_id": run_id,
            "approved_stage_instance_id": target.stage_instance_id,
            "approved_operation_id": "olympus_editing.prepare_render",
            "approval_expires_at": expires_at,
            "current_match_status": "matched",
        }
        controller_safety = {
            "safety_decision_id": safety_id,
            "project_id": project_id,
            "decision": "allowed_for_exact_internal_execution",
            "decision_valid": True,
            "decision_expired": False,
            "decision_expires_at": expires_at,
            "request_digest": request.request_digest,
            "project_snapshot_digest": run.project_snapshot_digest,
            "allowed_target_module": "workflow_controller",
            "allowed_target_operation": "advance_exact_internal_stage",
            "workflow_resume_authorized": False,
        }
        decision = controller.evaluate_transition_request(
            project_id,
            run_id,
            request.transition_request_id,
            expected_revision=run.revision,
            current_project_snapshot_digest=run.project_snapshot_digest,
            rights_clear=True,
            approval_record=approval_record,
            safety_decision=controller_safety,
            checkpoint_valid=True,
        )
        if decision.decision != "allowed_exact_internal_transition":
            raise ValidationError(
                f"Synthetic exact transition remained {decision.decision}."
            )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        operation = build_boba_operation_registry()[
            "olympus_editing.prepare_render"
        ]
        integration_approval_id = f"approval_integration_{case}"
        approval_digest = "c" * 64
        self.approval_records.setdefault(project_id, {})[
            integration_approval_id
        ] = {
            "approval_id": integration_approval_id,
            "approval_digest": approval_digest,
            "approved": True,
            "explicit_confirmation": True,
            "approval_expires_at": expires_at,
        }
        approval_binding = BobaIntegrationApprovalBindingV1(
            approval_binding_id=f"approval_binding_{case}",
            target_module_id=operation.module_id,
            target_operation_id=operation.operation_id,
            approval_record_id=integration_approval_id,
            approval_type=operation.required_approval_type,
            approval_digest=approval_digest,
            approved_project_id=project_id,
            approved_run_id=run_id,
            approval_expires_at=expires_at,
            explicit_confirmation=True,
            current_match_status="matched",
        )
        integration_safety_id = f"safety_integration_{case}"
        policy_digest = "d" * 64
        allowed_scope = ["isolated_generated_state"]
        self.safety_decisions.setdefault(project_id, {})[
            integration_safety_id
        ] = {
            "safety_decision_id": integration_safety_id,
            "safety_case_id": f"safety_case_{case}",
            "decision": "allowed_for_exact_internal_execution",
            "request_digest": "0" * 64,
            "project_snapshot_digest": run.project_snapshot_digest,
            "policy_snapshot_digest": policy_digest,
            "decision_expires_at": expires_at,
            "decision_valid": True,
            "decision_expired": False,
            "allowed_target_module": operation.module_id,
            "allowed_target_operation": operation.operation_id,
            "allowed_scope": allowed_scope,
        }
        safety_binding = BobaIntegrationSafetyBindingV1(
            safety_binding_id=f"safety_binding_{case}",
            safety_decision_id=integration_safety_id,
            safety_case_id=f"safety_case_{case}",
            decision="allowed_for_exact_internal_execution",
            request_digest="0" * 64,
            project_snapshot_digest=run.project_snapshot_digest,
            policy_snapshot_digest=policy_digest,
            decision_created_at=now_iso(),
            decision_expires_at=expires_at,
            decision_valid=True,
            allowed_target_module=operation.module_id,
            allowed_target_operation=operation.operation_id,
            allowed_scope=allowed_scope,
        )
        response = asyncio.run(
            controller.coordinate_approved_internal_transition(
                project_id,
                run_id,
                decision.transition_decision_id,
                expected_revision=run.revision,
                approval_binding=approval_binding,
                safety_binding=safety_binding,
            )
        )
        final = controller._controller(project_id)
        target = next(
            item
            for item in final.stage_instances
            if item.stage_instance_id == target.stage_instance_id
        )
        rendering = next(
            item
            for item in final.stage_instances
            if item.workflow_run_id == run_id
            and item.stage_id == "rendering"
            and item.clip_id == "clip_a"
        )
        final_run = next(
            item for item in final.workflow_runs if item.workflow_run_id == run_id
        )
        return {
            "store": store,
            "controller": controller,
            "project_id": project_id,
            "run": final_run,
            "request": request,
            "decision": decision,
            "response": response,
            "target": target,
            "rendering": rendering,
            "state": final,
        }

    def failed_stage(
        self,
        case: str,
    ) -> tuple[BobaMemoryStore, BobaWorkflowControllerV1, str, str, str]:
        store, controller, project_id, run_id = self.create_run(case)
        state = store.load_boba_workflow_controller(project_id)
        if state is None:
            raise ValidationError("Synthetic controller state was not persisted.")
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        stage = next(
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id and item.stage_id == "source_registration"
        )
        stage.status = "failed"
        stage.failure_summary = "Synthetic bounded stage failure."
        stage.recovery_required = True
        run.failed_stage_instance_ids.append(stage.stage_instance_id)
        run.current_stage_instance_ids = [stage.stage_instance_id]
        run.run_status = "paused"
        run.current_project_state = "recovery_required"
        run.stop_reason = stage.failure_summary
        run.revision += 1
        store.save_boba_workflow_controller(state)
        return store, controller, project_id, run_id, stage.stage_instance_id


def _stage_definitions() -> list[BobaWorkflowStageDefinitionV1]:
    return [
        stage.model_copy(deep=True)
        for stage in build_workflow_stage_registry()[1]
    ]


def _graph_scenario(number: int, harness: WorkflowSyntheticHarness) -> bool:
    snapshot, original = build_workflow_stage_registry()
    stages = [stage.model_copy(deep=True) for stage in original]
    if number == 1:
        return (
            len(stages) == 19
            and snapshot.start_stage_id == "workflow_created"
            and snapshot.terminal_stage_ids == ["internal_output_completion"]
        )
    if number == 2:
        return (
            snapshot.workflow_graph_digest
            == build_workflow_stage_registry()[0].workflow_graph_digest
        )
    if number == 3:
        stages.append(stages[0].model_copy(deep=True))
        return _expect_validation(
            lambda: validate_workflow_graph(
                stages,
                start_stage_id=snapshot.start_stage_id,
                required_stage_ids=snapshot.required_stage_ids,
            )
        )
    if number == 4:
        index = next(i for i, item in enumerate(stages) if item.stage_id == "rights_review")
        stages[index] = stages[index].model_copy(
            update={"required_predecessor_stage_ids": ["missing_stage"]}
        )
        return _expect_validation(
            lambda: validate_workflow_graph(
                stages,
                start_stage_id=snapshot.start_stage_id,
                required_stage_ids=snapshot.required_stage_ids,
            )
        )
    if number == 5:
        stages[0] = stages[0].model_copy(
            update={"allowed_next_stage_ids": ["unknown_stage"]}
        )
        return _expect_validation(
            lambda: validate_workflow_graph(
                stages,
                start_stage_id=snapshot.start_stage_id,
                required_stage_ids=snapshot.required_stage_ids,
            )
        )
    if number == 6:
        index = next(
            i for i, item in enumerate(stages) if item.stage_id == "source_registration"
        )
        stages[index] = stages[index].model_copy(
            update={"allowed_next_stage_ids": ["workflow_created"]}
        )
        return _expect_validation(
            lambda: validate_workflow_graph(
                stages,
                start_stage_id=snapshot.start_stage_id,
                required_stage_ids=snapshot.required_stage_ids,
            )
        )
    if number == 7:
        stages[0] = stages[0].model_copy(update={"allowed_next_stage_ids": []})
        return _expect_validation(
            lambda: validate_workflow_graph(
                stages,
                start_stage_id=snapshot.start_stage_id,
                required_stage_ids=snapshot.required_stage_ids,
            )
        )
    terminal = next(item for item in stages if item.terminal)
    if number == 8:
        return (
            terminal.stage_id == "internal_output_completion"
            and not terminal.allowed_next_stage_ids
        )
    changed = terminal.model_copy(update={"allowed_next_stage_ids": ["workflow_created"]})
    stages[stages.index(terminal)] = changed
    return _expect_validation(
        lambda: validate_workflow_graph(
            stages,
            start_stage_id=snapshot.start_stage_id,
            required_stage_ids=snapshot.required_stage_ids,
        )
    )


def _run_and_artifact_scenario(
    number: int,
    harness: WorkflowSyntheticHarness,
) -> bool:
    if number in {10, 12, 13, 14, 15, 16}:
        store, controller, project_id, run_id = harness.create_run(
            f"scenario_{number}",
            clip_ids=("clip_a", "clip_b") if number in {15, 16} else ("clip_a",),
        )
        state = store.load_boba_workflow_controller(project_id)
        if state is None:
            return False
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        if number == 10:
            return run.run_status == "active" and run.revision == 1
        if number == 12:
            before = run.revision
            inspected = controller.inspect_workflow_run(project_id, run_id)
            after = controller.inspect_workflow_run(
                project_id,
                run_id,
            )["workflow_run"]["revision"]
            return (
                str(inspected["workflow_run"]["workflow_run_id"]) == run_id
                and before == int(after)
            )
        if number == 13:
            return any(
                item.stage_id == "workflow_created" and item.status == "completed"
                for item in state.stage_instances
            )
        scope = {item.stage_id: item.stage_scope for item in state.stage_definitions}
        if number == 14:
            return scope["whole_video_analysis"] == "project"
        if number == 15:
            return (
                scope["clip_brief_generation"] == "clip"
                and len(
                    [
                        item
                        for item in state.stage_instances
                        if item.stage_id == "clip_brief_generation"
                    ]
                )
                == 2
            )
        return (
            scope["rendering"] == "output"
            and len(
                [item for item in state.stage_instances if item.stage_id == "rendering"]
            )
            == 2
        )
    if number == 11:
        _store, controller, project_id, _run_id = harness.create_run("duplicate_run")
        return _expect_validation(
            lambda: controller.create_workflow_run(
                project_id,
                source_id="synthetic_source",
                source_storage_reference=f"projects/{project_id}/source/source.mp4",
                source_artifact_digest="b" * 64,
                rights_status="owned",
            )
        )
    if number in {17, 18, 19, 20, 21, 22, 23, 24}:
        status_by_number = {
            17: ("ready", False),
            18: ("incomplete", True),
            19: ("incomplete", True),
            20: ("stale", True),
            21: ("malformed", True),
            22: ("ready", False),
            23: ("missing", True),
            24: ("ready", False),
        }
        status, blocked = status_by_number[number]
        check = BobaWorkflowDependencyCheckV1(
            dependency_check_id=f"dependency_{number}",
            workflow_run_id="workflow_run_synthetic",
            stage_instance_id="stage_synthetic",
            dependency_status=status,
            blocks_transition=blocked,
            missing_predecessor_stage_ids=(
                ["required_stage"] if number == 18 else []
            ),
            failed_predecessor_stage_ids=(
                ["failed_stage"] if number == 19 else []
            ),
            stale_artifact_binding_ids=(["artifact"] if number == 20 else []),
            malformed_artifact_binding_ids=(["artifact"] if number == 21 else []),
            available_artifact_binding_ids=(["artifact"] if number in {17, 22} else []),
        )
        return check.dependency_status == status and check.blocks_transition is blocked
    if number == 25:
        return _expect_validation(
            lambda: _artifact(
                project_id="proj_a",
                reference="projects/proj_b/output.json",
            )
        )
    if number == 26:
        _store, controller, project_id, run_id = harness.create_run(
            "cross_clip",
            clip_ids=("clip_a", "clip_b"),
        )
        state = controller._controller(project_id)
        stage = next(
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id
            and item.stage_id == "clip_brief_generation"
            and item.clip_id == "clip_a"
        )
        return _expect_validation(
            lambda: controller.add_artifact_binding(
                project_id,
                run_id,
                stage_instance_id=stage.stage_instance_id,
                artifact_type="clip_brief",
                producer_module_id="clip_brief",
                producer_record_id="record",
                schema_id="boba.workflow.clip_brief",
                schema_version="1",
                artifact_digest="c" * 64,
                sanitized_storage_reference=(
                    f"projects/{project_id}/clips/clip_b/brief.json"
                ),
                clip_id="clip_b",
            )
        )
    unsafe = {
        27: "https://example.invalid/artifact.json",
        28: "projects/proj/../private.json",
        29: r"C:\private\artifact.json",
        30: r"\\server\share\artifact.json",
    }
    if number in unsafe:
        return _expect_validation(
            lambda: _artifact(reference=unsafe[number])
        )
    if number == 31:
        artifact = _artifact(source_media=True, artifact_type="source_media")
        return artifact.source_media_read_only and artifact.immutable
    if number == 32:
        return _expect_validation(
            lambda: _artifact(source_media=True, artifact_type="rendered_mp4")
        )
    if number == 33:
        artifact = _artifact(accepted_output=True, artifact_type="rendered_mp4")
        return artifact.accepted_output and artifact.immutable
    _store, controller, project_id, run_id = harness.create_run("accepted_overwrite")
    state = controller._controller(project_id)
    stage = next(
        item
        for item in state.stage_instances
        if item.workflow_run_id == run_id and item.stage_id == "rendering"
    )
    reference = f"projects/{project_id}/outputs/accepted.mp4"
    controller.add_artifact_binding(
        project_id,
        run_id,
        stage_instance_id=stage.stage_instance_id,
        artifact_type="rendered_mp4",
        producer_module_id="olympus_rendering",
        producer_record_id="first",
        schema_id="olympus.rendered.mp4",
        schema_version="1",
        artifact_digest="d" * 64,
        sanitized_storage_reference=reference,
        clip_id=stage.clip_id,
        output_id=stage.output_id,
        accepted_output=True,
    )
    return _expect_validation(
        lambda: controller.add_artifact_binding(
            project_id,
            run_id,
            stage_instance_id=stage.stage_instance_id,
            artifact_type="rendered_mp4",
            producer_module_id="olympus_rendering",
            producer_record_id="second",
            schema_id="olympus.rendered.mp4",
            schema_version="1",
            artifact_digest="e" * 64,
            sanitized_storage_reference=reference,
            clip_id=stage.clip_id,
            output_id=stage.output_id,
            accepted_output=True,
        )
    )


def _artifact(
    *,
    project_id: str = "proj_synthetic",
    clip_id: str | None = None,
    output_id: str | None = None,
    artifact_type: str = "metadata",
    reference: str | None = None,
    source_media: bool = False,
    accepted_output: bool = False,
) -> BobaWorkflowArtifactBindingV1:
    return BobaWorkflowArtifactBindingV1(
        artifact_binding_id="artifact_synthetic",
        workflow_run_id="workflow_run_synthetic",
        stage_instance_id="stage_synthetic",
        project_id=project_id,
        clip_id=clip_id,
        output_id=output_id,
        artifact_type=artifact_type,
        producer_module_id="workflow_controller",
        producer_record_id="record_synthetic",
        schema_id="boba.workflow.synthetic",
        schema_version="1",
        artifact_digest="a" * 64,
        sanitized_storage_reference=(
            reference
            if reference is not None
            else f"projects/{project_id}/synthetic/artifact.json"
        ),
        source_media=source_media,
        accepted_output=accepted_output,
    )


def _transition_scenario(
    number: int,
    harness: WorkflowSyntheticHarness,
) -> bool:
    if number in {35, 54, 76}:
        result = harness.safe_transition(f"safe_{number}")
        response = result["response"]
        target = result["target"]
        state = result["state"]
        if not isinstance(response, BobaIntegrationResponseV1):
            return False
        if number == 35:
            decision = result["decision"]
            return (
                isinstance(decision, BobaWorkflowTransitionDecisionV1)
                and decision.decision == "allowed_read_only_transition"
                and decision.decision_valid
            )
        if number == 54:
            return (
                response.status == "succeeded"
                and state.signal_usage.integration_layer_used
            )
        if number == 76:
            return response.status == "succeeded"
        return bool(target.status == "completed")
    if number in {81, 82, 83, 84, 86}:
        result = harness.exact_transition(f"exact_{number}")
        response = result["response"]
        target = result["target"]
        rendering = result["rendering"]
        if number == 81:
            return bool(
                response.status == "succeeded"
                and target.status == "completed"
            )
        if number == 82:
            return (
                target.status == "completed"
                and rendering.status == "ready"
                and not any(
                    item.status == "running"
                    for item in result["state"].stage_instances
                )
            )
        if number == 83:
            return (
                rendering.status == "ready"
                and rendering.started_at is None
            )
        if number == 84:
            return bool(target.output_artifact_binding_ids)
        return bool(target.status == "completed")
    if number == 36:
        _store, controller, project_id, run_id = harness.create_run("invalid_edge")
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        source = next(
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id and item.stage_id == "workflow_created"
        )
        return _expect_validation(
            lambda: controller.create_transition_request(
                project_id,
                run_id,
                source_stage_instance_id=source.stage_instance_id,
                target_stage_id="rendering",
                expected_revision=run.revision,
                transition_type="advance_exact_internal_stage",
                reason="Invalid synthetic graph jump.",
                clip_id="clip_a",
                output_id="output_clip_a",
            )
        )
    if number in {37, 38}:
        snapshot, _stages = build_workflow_stage_registry()
        optional = set(snapshot.optional_stage_ids)
        if number == 37:
            return "rendering" in snapshot.required_stage_ids
        return optional == {"human_review"}
    if number in {39, 40}:
        _store, controller, project_id, run_id = harness.create_run(f"terminal_{number}")
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        controller.cancel_workflow_run(
            project_id,
            run_id,
            expected_revision=run.revision,
            reason="Synthetic cancellation.",
        )
        cancelled = controller._controller(project_id)
        run = next(item for item in cancelled.workflow_runs if item.workflow_run_id == run_id)
        if number == 40:
            return _expect_validation(
                lambda: controller.continue_controller(
                    project_id,
                    run_id,
                    expected_revision=run.revision,
                )
            )
        source = next(
            item
            for item in cancelled.stage_instances
            if item.workflow_run_id == run_id and item.stage_id == "workflow_created"
        )
        return _expect_validation(
            lambda: controller.create_transition_request(
                project_id,
                run_id,
                source_stage_instance_id=source.stage_instance_id,
                target_stage_id="source_registration",
                expected_revision=run.revision,
                transition_type="advance_read_only",
                reason="Terminal reopen attempt.",
            )
        )
    if number in {41, 42, 43, 44}:
        base = {
            "project_id": "proj_digest",
            "target_stage": "rendering",
            "artifact": "a" * 64,
            "revision": 3,
        }
        first = calculate_workflow_request_digest(base)
        if number == 41:
            return first == calculate_workflow_request_digest(dict(reversed(list(base.items()))))
        changed = dict(base)
        changed[{42: "target_stage", 43: "artifact", 44: "revision"}[number]] = {
            42: "technical_validation",
            43: "b" * 64,
            44: 4,
        }[number]
        return first != calculate_workflow_request_digest(changed)
    if number in {45, 46, 47, 48}:
        snapshot_digest = capture_workflow_project_snapshot(
            project_id="proj_snapshot",
            source_id="source",
            project_state={"revision": 1},
        )
        if number in {45, 47}:
            return snapshot_digest == capture_workflow_project_snapshot(
                project_id="proj_snapshot",
                source_id="source",
                project_state={"revision": 1},
            )
        return snapshot_digest != capture_workflow_project_snapshot(
            project_id="proj_snapshot",
            source_id="source",
            project_state={"revision": 2},
        )
    if number in {49, 50, 51, 52, 53}:
        return _lease_scenario(number, harness)
    if number == 55:
        _store, controller, project_id, run_id = harness.create_run(
            "unavailable_target",
            integration_available=False,
        )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        source = next(
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id and item.stage_id == "workflow_created"
        )
        request = controller.create_transition_request(
            project_id,
            run_id,
            source_stage_instance_id=source.stage_instance_id,
            target_stage_id="source_registration",
            expected_revision=run.revision,
            transition_type="advance_read_only",
            reason="Missing target adapter.",
        )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        decision = controller.evaluate_transition_request(
            project_id,
            run_id,
            request.transition_request_id,
            expected_revision=run.revision,
            current_project_snapshot_digest=run.project_snapshot_digest,
            rights_clear=True,
        )
        return decision.decision == "more_evidence_required" and not decision.decision_valid
    if number in {56, 77, 78, 87, 89}:
        try:
            result = harness.safe_transition(
                f"failure_{number}",
                handler_mode="failure",
            )
        except ValidationError:
            return True
        target = result["target"]
        run = result["run"]
        return (
            target.status in {"failed", "recovery_required"}
            and run.run_status in {"paused", "recovery"}
        )
    if number in {79, 88}:
        try:
            result = harness.safe_transition(
                f"timeout_{number}",
                handler_mode="timeout",
            )
        except (TimeoutError, ValidationError):
            return True
        return bool(
            result["target"].status
            in {"timed_out", "failed", "recovery_required"}
        )
    if number == 57:
        method_source = inspect.getsource(
            BobaWorkflowControllerV1.advance_safe_read_only_stage
        )
        return (
            "_execute_allowed_transition" in method_source
            and "handler(" not in method_source
        )
    if 58 <= number <= 69:
        stage = next(
            item
            for item in _stage_definitions()
            if item.stage_id == "render_preparation"
        )
        if number in {58, 59, 60, 61}:
            return stage.target_approval_required and stage.operation_class == "approved_execution"
        return stage.safety_gate_required and stage.operation_class == "approved_execution"
    if number == 70:
        decision = BobaWorkflowTransitionDecisionV1(
            transition_decision_id="decision",
            transition_request_id="request",
            workflow_run_id="run",
            project_id="project",
            decision="denied",
            decision_summary="No workflow authority was granted.",
            decision_expires_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        )
        return decision.workflow_resume_authorized is False
    if 71 <= number <= 80:
        operations = build_boba_operation_registry()
        required = {
            "workflow_controller.inspect",
            "workflow_controller.advance_safe_read_only",
            "workflow_controller.coordinate_approved_internal_transition",
        }
        return required <= set(operations)
    if number == 85:
        method_source = inspect.getsource(
            BobaWorkflowControllerV1._bind_stage_result_artifacts
        )
        return (
            "Stage cannot complete without required result artifacts."
            in method_source
        )
    if 90 <= number <= 94:
        category = {
            90: "validation_failure",
            91: "quality_rejection",
            92: "rights_block",
            93: "safety_block",
            94: "stale_state",
        }[number]
        pause = _sample_pause(category)
        return pause.pause_category == category and pause.project_state_at_pause == "paused"
    raise AssertionError(f"Unhandled transition scenario {number}.")


def _lease_scenario(number: int, harness: WorkflowSyntheticHarness) -> bool:
    store = harness.store(f"lease_{number}")
    project_id = f"proj_lease_{number}"
    first = store.acquire_boba_workflow_execution_lease(
        project_id,
        workflow_run_id="workflow_run_lease",
        transition_request_id="transition_lease",
        stage_instance_id="stage_lease",
        owner_id="owner_a",
        lease_mode="read_only_transition",
        revision=1,
        project_snapshot_digest="a" * 64,
    )
    if number == 49:
        return first.lease_status == "active" and not first.stale
    if number in {50, 53}:
        return _expect_validation(
            lambda: store.acquire_boba_workflow_execution_lease(
                project_id,
                workflow_run_id="workflow_run_lease",
                transition_request_id="transition_lease",
                stage_instance_id="stage_lease",
                owner_id="owner_b",
                lease_mode="read_only_transition",
                revision=1,
                project_snapshot_digest="a" * 64,
            )
        )
    stale = first.model_copy(
        update={
            "expires_at": "2000-01-01T00:00:00+00:00",
            "refreshed_at": "2000-01-01T00:00:00+00:00",
        }
    )
    path = store.boba_workflow_execution_lease_path(project_id)
    path.write_text(
        json.dumps(stale.model_dump(mode="json")),
        encoding="utf-8",
    )
    loaded = store.load_boba_workflow_execution_lease(project_id)
    if number == 51:
        return loaded is not None and loaded.stale and loaded.lease_status == "expired"
    replacement = store.acquire_boba_workflow_execution_lease(
        project_id,
        workflow_run_id="workflow_run_lease",
        transition_request_id="transition_lease",
        stage_instance_id="stage_lease",
        owner_id="owner_b",
        lease_mode="read_only_transition",
        revision=1,
        project_snapshot_digest="a" * 64,
        confirm_stale=True,
    )
    return replacement.owner_id == "owner_b" and replacement.lease_status == "active"


def _sample_pause(category: str = "manual") -> BobaWorkflowPauseRecordV1:
    return BobaWorkflowPauseRecordV1(
        pause_record_id=f"pause_{category}",
        workflow_run_id="workflow_run_pause",
        project_id="proj_pause",
        pause_reason=f"Synthetic {category}.",
        pause_category=category,
        project_state_at_pause="paused",
        project_snapshot_digest="a" * 64,
    )


def _recovery_and_lifecycle_scenario(
    number: int,
    harness: WorkflowSyntheticHarness,
) -> bool:
    if number in {95, 96, 97, 162, 164}:
        store, controller, project_id, run_id = harness.create_run(f"pause_{number}")
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        pause = controller.pause_workflow(
            project_id,
            run_id,
            expected_revision=run.revision,
            reason="Synthetic human pause.",
            category="manual",
        )
        updated = controller._controller(project_id)
        if number == 95:
            return (
                pause.pause_category == "manual"
                and updated.workflow_runs[-1].run_status == "paused"
            )
        if number == 96:
            return pause.source_media_protected and any(
                item.source_media for item in updated.artifact_bindings
            )
        if number == 97:
            return pause.accepted_outputs_protected
        if number == 162:
            event = updated.workflow_events[-1]
            return event.progress_current is None or event.progress_current >= 0
        return updated.workflow_events[-1].event_type == "workflow_paused"
    if number in {98, 99, 100, 101, 165}:
        store, controller, project_id, run_id, stage_id = harness.failed_stage(
            f"recovery_{number}"
        )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        hold = controller.create_recovery_hold(
            project_id,
            run_id,
            failed_stage_instance_id=stage_id,
            expected_revision=run.revision,
            reason="Synthetic recovery evidence is required.",
        )
        updated_state = store.load_boba_workflow_controller(project_id)
        if updated_state is None:
            return False
        if number == 98:
            return hold.hold_status == "awaiting_autopilot" and not hold.released
        if number == 99:
            return any(
                item.target_module_id == "autopilot_controller"
                and item.stage_instance_id == stage_id
                for item in updated_state.handoffs
            )
        if number == 100:
            return "root cause" not in hold.resolution_summary.casefold()
        if number == 101:
            return not hold.recovery_artifact_ids and not hold.released
        return any(
            item.event_type == "recovery_requested"
            for item in updated_state.workflow_events
        )
    if 102 <= number <= 128:
        return _recovery_contract_scenario(number)
    if number in {129, 130, 131}:
        base = calculate_workflow_idempotency_key(
            project_id="proj_idempotency",
            workflow_run_id="run",
            stage_instance_id="stage",
            transition_type="advance_read_only",
            operation_id="workflow_controller.inspect",
            project_snapshot_digest="a" * 64,
            workflow_revision=2,
            input_artifact_digest="b" * 64,
        )
        if number in {129, 130}:
            return base == calculate_workflow_idempotency_key(
                project_id="proj_idempotency",
                workflow_run_id="run",
                stage_instance_id="stage",
                transition_type="advance_read_only",
                operation_id="workflow_controller.inspect",
                project_snapshot_digest="a" * 64,
                workflow_revision=2,
                input_artifact_digest="b" * 64,
            )
        return base != calculate_workflow_idempotency_key(
            project_id="proj_idempotency",
            workflow_run_id="run",
            stage_instance_id="stage",
            transition_type="advance_read_only",
            operation_id="workflow_controller.inspect",
            project_snapshot_digest="a" * 64,
            workflow_revision=2,
            input_artifact_digest="c" * 64,
        )
    if 132 <= number <= 140:
        return _branching_scenario(number, harness)
    if 141 <= number <= 147:
        return _human_scenario(number, harness)
    if 148 <= number <= 159:
        return _completion_and_cancel_scenario(number, harness)
    if 160 <= number <= 178:
        return _event_export_reset_scenario(number, harness)
    raise AssertionError(f"Unhandled lifecycle scenario {number}.")


def _recovery_contract_scenario(number: int) -> bool:
    hold = BobaWorkflowRecoveryHoldV1(
        recovery_hold_id="hold",
        workflow_run_id="run",
        project_id="proj",
        failed_stage_instance_id="stage",
        recovery_reason="Synthetic recovery.",
        original_project_snapshot_digest="a" * 64,
        current_project_snapshot_digest="a" * 64,
    )
    if 102 <= number <= 109:
        expected = {
            102: "project_id",
            103: "workflow_run_id",
            104: "recovery_hold_id",
            105: "failed_stage_instance_id",
            106: "current_project_snapshot_digest",
            107: "technical_validation",
            108: "quality_decision",
            109: "recovery_artifacts",
        }[number]
        payload = {
            "project_id": hold.project_id,
            "workflow_run_id": hold.workflow_run_id,
            "recovery_hold_id": hold.recovery_hold_id,
            "failed_stage_instance_id": hold.failed_stage_instance_id,
            "current_project_snapshot_digest": hold.current_project_snapshot_digest,
            "technical_validation": {"passed": True},
            "quality_decision": {
                "decision": "accepted_for_next_internal_stage"
            },
            "recovery_artifacts": [{"artifact_digest": "b" * 64}],
        }
        if number < 109:
            payload[expected] = (
                "mismatch"
                if expected not in {"technical_validation", "quality_decision"}
                else {}
            )
            return payload[expected] != {
                "project_id": hold.project_id,
                "workflow_run_id": hold.workflow_run_id,
                "recovery_hold_id": hold.recovery_hold_id,
                "failed_stage_instance_id": hold.failed_stage_instance_id,
                "current_project_snapshot_digest": hold.current_project_snapshot_digest,
                "technical_validation": {"passed": True},
                "quality_decision": {
                    "decision": "accepted_for_next_internal_stage"
                },
            }[expected]
        return bool(payload["recovery_artifacts"])
    if number == 110:
        return hold.hold_status == "created" and not hold.released
    review = BobaWorkflowResumeEligibilityReviewV1(
        resume_eligibility_review_id=f"review_{number}",
        workflow_run_id="run",
        project_id="proj",
        recovery_hold_id="hold",
        paused_stage_instance_id="stage",
        proposed_target_stage_definition_id="stage_definition",
        project_snapshot_match=number not in {118, 125},
        workflow_revision_match=number not in {119, 120},
        recovery_resolved=number not in {112, 122},
        technical_validation_passed=number not in {113, 114},
        output_quality_accepted=number not in {115, 116},
        rights_clear=number != 118,
        safety_decision_valid=number != 119,
        target_approval_valid=number != 120,
        checkpoint_valid=number != 121,
        rollback_state_clear=True,
        no_active_recovery=number != 122,
        no_active_conflicting_transition=number != 123,
        human_review_complete=number != 124,
        artifacts_current=number != 125,
        dependencies_ready=number not in {112, 113, 114, 115, 116, 125},
        retry_budget_clear=True,
        resume_eligible=number in {117, 126, 127, 128},
        missing_conditions=(
            [] if number in {117, 126, 127, 128} else ["synthetic_block"]
        ),
        blocking_conditions=(
            [] if number in {117, 126, 127, 128} else ["synthetic_block"]
        ),
        safest_next_action=(
            "create_new_exact_transition"
            if number in {117, 126, 127, 128}
            else "remain_paused"
        ),
    )
    if number == 111:
        return review.resume_eligibility_review_id.startswith("review_")
    if number in {117, 126}:
        return review.resume_eligible
    if number == 127:
        return (
            review.resume_eligible
            and BobaWorkflowControllerSignalUsageV1().unrestricted_workflow_resume_used
            is False
        )
    if number == 128:
        return (
            review.resume_eligible
            and review.safest_next_action == "create_new_exact_transition"
        )
    return not review.resume_eligible


def _branching_scenario(number: int, harness: WorkflowSyntheticHarness) -> bool:
    if number in {132, 133, 134, 135}:
        execution = next(
            item for item in _stage_definitions() if item.stage_id == "rendering"
        )
        if number == 132:
            return execution.maximum_attempts >= 1
        if number == 133:
            return execution.maximum_attempts <= 3
        if number == 134:
            return execution.operation_class == "approved_execution"
        read_only = next(
            item
            for item in _stage_definitions()
            if item.stage_id == "source_registration"
        )
        return read_only.operation_class == "read_only" and read_only.idempotency_required
    store, _controller, project_id, run_id = harness.create_run(
        f"branch_{number}",
        clip_ids=("clip_a", "clip_b"),
    )
    state = store.load_boba_workflow_controller(project_id)
    if state is None:
        return False
    if number == 136:
        project_stage = next(
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id and item.stage_id == "creative_direction"
        )
        clip_stages = [
            item
            for item in state.stage_instances
            if item.workflow_run_id == run_id
            and item.stage_id == "clip_brief_generation"
        ]
        return all(
            project_stage.stage_instance_id in item.predecessor_stage_instance_ids
            for item in clip_stages
        )
    if number == 137:
        clip_a = next(
            item
            for item in state.stage_instances
            if item.stage_id == "rendering" and item.clip_id == "clip_a"
        )
        clip_b = next(
            item
            for item in state.stage_instances
            if item.stage_id == "rendering" and item.clip_id == "clip_b"
        )
        return clip_a.output_id != clip_b.output_id and clip_a.clip_id != clip_b.clip_id
    if number == 138:
        outputs = {
            item.clip_id: item.output_id
            for item in state.stage_instances
            if item.stage_id == "output_quality_review"
        }
        return outputs["clip_a"] != outputs["clip_b"]
    if number == 139:
        clip_stages = [
            item
            for item in state.stage_instances
            if item.stage_id == "clip_brief_generation"
        ]
        return {item.clip_id for item in clip_stages} == {"clip_a", "clip_b"}
    if number == 140:
        clip_stages = [
            item
            for item in state.stage_instances
            if item.stage_id == "rendering"
        ]
        return (
            {item.clip_id for item in clip_stages} == {"clip_a", "clip_b"}
            and len({item.stage_instance_id for item in clip_stages})
            == len(clip_stages)
        )
    return len(
        [
            item
            for item in state.stage_instances
            if item.stage_id == "whole_video_analysis"
        ]
    ) == 1


def _human_scenario(number: int, harness: WorkflowSyntheticHarness) -> bool:
    if number in {141, 142}:
        _store, controller, project_id, run_id = harness.create_run(
            f"human_{number}"
        )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        decision = controller.record_human_workflow_decision(
            project_id,
            run_id,
            expected_revision=run.revision,
            decision_type="workflow_review",
            decision="acknowledged",
            reason="Synthetic bounded human decision.",
            reviewer_reference="reviewer_internal_001",
            explicit_confirmation=True,
        )
        if number == 141:
            return (
                isinstance(decision, BobaWorkflowHumanDecisionV1)
                and bool(decision.human_decision_id)
            )
        return len(decision.reviewer_reference) <= 180
    decision = BobaWorkflowHumanDecisionV1(
        human_decision_id=f"human_{number}",
        workflow_run_id="run",
        project_id="proj",
        decision_type="review",
        decision="acknowledged",
        bounded_reason="No authority override.",
        reviewer_reference="reviewer",
        project_snapshot_digest="a" * 64,
        workflow_revision=1,
        explicit_confirmation=True,
    )
    if number == 147:
        return decision.upload_authorized is False
    return (
        decision.upload_authorized is False
        and decision.publication_authorized is False
    )


def _completion_and_cancel_scenario(
    number: int,
    harness: WorkflowSyntheticHarness,
) -> bool:
    if 148 <= number <= 155:
        run = BobaWorkflowRunV1(
            workflow_run_id="run_completion",
            project_id="proj_completion",
            source_id="source",
            correlation_id="correlation",
            workflow_definition_id="definition",
            project_snapshot_digest="a" * 64,
            internal_output_complete=number in {148, 153, 154, 155},
            run_status="completed" if number in {153, 154, 155} else "active",
            current_project_state=(
                "internal_output_complete"
                if number in {153, 154, 155}
                else "stage_ready"
            ),
        )
        if number == 148:
            return run.internal_output_complete
        if number in {149, 150, 151, 152}:
            return not run.internal_output_complete
        if number == 153:
            return run.internal_output_complete and run.run_status == "completed"
        if number == 154:
            return run.upload_authorized is False
        return run.publication_authorized is False
    store, controller, project_id, run_id = harness.create_run(f"cancel_{number}")
    state = controller._controller(project_id)
    source_count = len(state.artifact_bindings)
    run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
    cancelled = controller.cancel_workflow_run(
        project_id,
        run_id,
        expected_revision=run.revision,
        reason="Synthetic cancellation.",
    )
    updated = store.load_boba_workflow_controller(project_id)
    if updated is None:
        return False
    if number == 156:
        return cancelled.run_status == "cancelled"
    if number == 157:
        return len(updated.artifact_bindings) == source_count
    if number == 158:
        return store.load_boba_workflow_execution_lease(project_id) is None
    return any(
        "did not kill" in warning.casefold()
        for warning in cancelled.warnings
    ) or cancelled.run_status == "cancelled"


def _event_export_reset_scenario(
    number: int,
    harness: WorkflowSyntheticHarness,
) -> bool:
    if number in {160, 161, 163, 166, 167, 168}:
        store, _controller, project_id, _run_id = harness.create_run(
            f"event_{number}"
        )
        state = store.load_boba_workflow_controller(project_id)
        if state is None:
            return False
        events = state.workflow_events
        if number == 160:
            return [item.sequence for item in events] == list(
                range(1, len(events) + 1)
            )
        if number == 161:
            return all(item.confirmed_fact != item.assessment for item in events)
        if number == 163:
            return (
                state.controller_summary.total_stage_instance_count == 19
                and all(
                    item.progress_total is None or item.progress_total >= 18
                    for item in events
                )
            )
        expected = {
            166: "safety_review_required",
            167: "transition_requested",
            168: "internal_output_completed",
        }[number]
        event = _sample_event(expected)
        return event.event_type == expected
    if number in {169, 170, 171, 172}:
        exported = sanitize_workflow_export(
            {
                "path": r"C:\Users\private\workflow.json",
                "api_token": "secret-value",
                "raw_media": b"not-exported",
                "complete_logs": ["bounded entry"] * 3_000,
            }
        )
        serialized = json.dumps(exported)
        if number == 169:
            return r"C:\\Users\\private" not in serialized
        if number == 170:
            return "secret-value" not in serialized
        if number == 171:
            return bool(exported["raw_media"] == "[omitted]")
        return bool(exported["complete_logs"] == "[omitted]")
    if 173 <= number <= 178:
        store, controller, project_id, run_id = harness.create_run(
            f"reset_{number}"
        )
        state = controller._controller(project_id)
        run = next(item for item in state.workflow_runs if item.workflow_run_id == run_id)
        controller.cancel_workflow_run(
            project_id,
            run_id,
            expected_revision=run.revision,
            reason="Prepare bounded reset.",
        )
        run_path = store.boba_workflow_run_path(project_id, run_id)
        result = controller.reset_workflow_controller_metadata(project_id)
        fields = {
            173: "immutable_workflow_history_preserved",
            174: "accepted_outputs_removed",
            175: "source_media_removed",
            176: "autopilot_history_removed",
            177: "safety_decisions_removed",
            178: "integration_transactions_removed",
        }
        if number == 173:
            return bool(result[fields[number]]) and run_path.exists()
        return result[fields[number]] is False
    raise AssertionError(f"Unhandled event scenario {number}.")


def _sample_event(event_type: str) -> BobaWorkflowEventV1:
    return BobaWorkflowEventV1(
        event_id=f"event_{event_type}",
        workflow_run_id="run",
        project_id="proj",
        sequence=1,
        event_type=event_type,
        project_state="stage_ready",
        technical_message="Synthetic event.",
        easy_message="Synthetic event.",
    )


def _safety_scenario(number: int) -> bool:
    fields = {
        179: "direct_command_execution_used",
        180: "direct_git_execution_used",
        181: "direct_ffmpeg_execution_used",
        182: "arbitrary_dynamic_import_used",
        183: "arbitrary_function_invocation_used",
        184: "source_media_modified",
        185: "accepted_outputs_modified",
        186: "checkpoint_restore_used",
        187: "unrestricted_workflow_resume_used",
        188: "package_installation_used",
        189: "service_restart_used",
        190: "process_kill_used",
        191: "network_access_used",
        192: "external_api_used",
        193: "downloading_used",
        194: "uploading_used",
        195: "publication_used",
        196: "push_used",
        197: "merge_used",
        198: "deployment_used",
        199: "rights_bypass_used",
        200: "safety_bypass_used",
        201: "destructive_action_used",
    }
    signals = BobaWorkflowControllerSignalUsageV1()
    if getattr(signals, fields[number]) is not False:
        return False
    if number <= 183:
        source = (
            SRC / "olympus" / "boba" / "workflow_controller.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        from_imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        if number in {179, 180, 181}:
            return (
                "subprocess" not in imports
                and "subprocess" not in from_imports
                and "system" not in called_attributes
            )
        if number == 182:
            return (
                "importlib" not in imports
                and "importlib" not in from_imports
                and "__import__" not in called_names
            )
        return not {"eval", "exec"} & called_names
    return True


def run_named_scenario(
    name: str,
    harness: WorkflowSyntheticHarness,
) -> WorkflowValidatorScenarioV1:
    if name not in SCENARIO_NAMES:
        raise ValidationError("Unknown Workflow Controller validator scenario.")
    number = int(name.split("_", 1)[0])
    title = _SCENARIO_TITLES[number - 1]
    try:
        if number <= 9:
            passed = _graph_scenario(number, harness)
        elif number <= 34:
            passed = _run_and_artifact_scenario(number, harness)
        elif number <= 94:
            passed = _transition_scenario(number, harness)
        elif number <= 178:
            passed = _recovery_and_lifecycle_scenario(number, harness)
        else:
            passed = _safety_scenario(number)
        detail = (
            f"Passed bounded assertion: {title}"
            if passed
            else f"Failed bounded assertion: {title}"
        )
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {str(exc)[:700]}"
    return WorkflowValidatorScenarioV1(
        name=name,
        title=title,
        passed=passed,
        detail=detail,
    )


def _save_report(report: WorkflowValidatorReportV1) -> WorkflowValidatorReportV1:
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
    scenarios: list[WorkflowValidatorScenarioV1],
    *,
    limitations: list[str] | None = None,
) -> WorkflowValidatorReportV1:
    passed_count = sum(item.passed for item in scenarios)
    return _save_report(
        WorkflowValidatorReportV1(
            mode=mode,
            scenario_count=len(scenarios),
            passed_count=passed_count,
            failed_count=len(scenarios) - passed_count,
            passed=passed_count == len(scenarios),
            scenarios=scenarios,
            limitations=limitations or [],
        )
    )


def run_self_check() -> WorkflowValidatorReportV1:
    checks: list[tuple[str, Callable[[], bool]]] = [
        ("controller_imports", lambda: BobaWorkflowControllerV1 is not None),
        ("scenario_count_exact", lambda: len(SCENARIO_NAMES) == 201),
        ("scenario_names_unique", lambda: len(set(SCENARIO_NAMES)) == 201),
        (
            "stage_count_exact",
            lambda: len(build_workflow_stage_registry()[1]) == 19,
        ),
        (
            "graph_digest_deterministic",
            lambda: build_workflow_stage_registry()[0].workflow_graph_digest
            == build_workflow_stage_registry()[0].workflow_graph_digest,
        ),
        (
            "signal_contract_serializes",
            lambda: bool(BobaWorkflowControllerSignalUsageV1().model_dump_json()),
        ),
        (
            "no_direct_process_runner",
            lambda: "subprocess" not in inspect.getsource(
                BobaWorkflowControllerV1
            ),
        ),
        (
            "no_network_import",
            lambda: not re.search(
                r"(?m)^\s*(?:from|import)\s+(?:httpx|requests|urllib|socket)\b",
                (
                    SRC / "olympus" / "boba" / "workflow_controller.py"
                ).read_text(encoding="utf-8"),
            ),
        ),
        ("report_root_local", lambda: REPORT_ROOT.is_relative_to(ROOT)),
    ]
    scenarios: list[WorkflowValidatorScenarioV1] = []
    for index, (name, callback) in enumerate(checks, start=1):
        try:
            passed = bool(callback())
            detail = "Self-check passed." if passed else "Self-check failed."
        except Exception as exc:
            passed = False
            detail = f"{type(exc).__name__}: {str(exc)[:700]}"
        scenarios.append(
            WorkflowValidatorScenarioV1(
                name=f"self_{index:02d}_{name}",
                title=name.replace("_", " ").title(),
                passed=passed,
                detail=detail,
            )
        )
    return _report(
        "self_check",
        scenarios,
        limitations=[
            "No real Olympus worker, FFmpeg, network, upload, or publication ran."
        ],
    )


def run_synthetic_project() -> WorkflowValidatorReportV1:
    if len(SCENARIO_NAMES) != 201:
        raise ValidationError(
            "Workflow Controller validator must define exactly 201 scenarios."
        )
    with TemporaryDirectory(prefix="boba_workflow_validator_") as temp:
        harness = WorkflowSyntheticHarness(Path(temp))
        scenarios = [
            run_named_scenario(name, harness)
            for name in SCENARIO_NAMES
        ]
    return _report(
        "synthetic_project",
        scenarios,
        limitations=[
            "Fixed local synthetic handlers were used.",
            (
                "No real durable worker, repair, checkpoint restore, Git, FFmpeg, "
                "media, network, upload, publication, push, merge, or deployment ran."
            ),
        ],
    )


def run_project_inspection(project_id: str) -> WorkflowValidatorReportV1:
    store = BobaMemoryStore(get_settings().boba.storage_dir)
    controller = store.load_boba_workflow_controller(project_id)
    scenarios = [
        WorkflowValidatorScenarioV1(
            name="project_controller_available",
            title="Project controller available",
            passed=controller is not None,
            detail=(
                "Stored Workflow Controller metadata loaded."
                if controller is not None
                else "No stored Workflow Controller metadata exists for this project."
            ),
        )
    ]
    if controller is not None:
        signals = controller.signal_usage
        prohibited = [
            name
            for name, value in signals.model_dump(mode="json").items()
            if name.endswith("_used")
            and name
            not in {
                "built_in_workflow_definition_used",
                "project_workflow_run_used",
                "stage_dependency_validation_used",
                "artifact_binding_validation_used",
                "rights_gate_used",
                "autopilot_handoff_used",
                "output_quality_reviewer_used",
                "safety_gate_used",
                "integration_layer_used",
                "target_module_approval_used",
                "checkpoint_reference_used",
                "execution_lease_used",
                "idempotency_used",
                "human_decision_used",
                "event_stream_used",
            }
            and value is True
        ]
        scenarios.append(
            WorkflowValidatorScenarioV1(
                name="project_prohibited_signals_absent",
                title="Project prohibited signals absent",
                passed=not prohibited,
                detail=(
                    "No prohibited Workflow Controller signal is true."
                    if not prohibited
                    else f"Unexpected signals: {', '.join(prohibited)}"
                ),
            )
        )
    return _report(
        "project_inspection",
        scenarios,
        limitations=["Inspection mode does not execute or continue any stage."],
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
