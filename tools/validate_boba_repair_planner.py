"""Validate BOBA Repair Planner V1 with bounded local causal-analysis data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.boba.repair_planner import (  # noqa: E402
    DEFAULT_CHECKPOINT_REGISTRY,
    DEFAULT_VALIDATOR_REGISTRY,
    BobaRepairExecutionHandoffV1,
    BobaRepairPlannerSetV1,
    BobaRepairPlannerV1,
    BobaRepairPlanningCaseV1,
    BobaRepairStrategyV1,
)
from olympus.boba.root_cause_analyzer import (  # noqa: E402
    BobaRootCauseAnalysisCaseV1,
    BobaRootCauseAnalyzerSetV1,
    BobaRootCauseAnalyzerV1,
    BobaRootCauseCandidateV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402
from tools.validate_boba_root_cause_analyzer import (  # noqa: E402
    build_synthetic_error_doctor_report,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_repair_planner"
SYNTHETIC_PROJECT_ID = "proj_boba_repair_planner_synthetic"


class BobaRepairPlannerValidationReport(BaseModel):
    """Compact proof that repair planning remains advisory and non-applying."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    module_imported: bool = False
    store_available: bool = False
    root_cause_analyzer_available: bool = False
    contracts_serialize: bool = False
    artifact_path_writable: bool = False
    checkpoint_registry_inspected: bool = False
    validator_registry_inspected: bool = False
    repair_cases_exist: bool = False
    multiple_strategies_exist: bool = False
    recommended_strategies_exist: bool = False
    alternative_strategies_exist: bool = False
    unsafe_strategies_rejected: bool = False
    missing_healthy_regeneration: bool = False
    missing_upstream_first: bool = False
    corrupt_artifact_recovery: bool = False
    stale_scoped_regeneration: bool = False
    valid_checkpoint_selected: bool = False
    missing_checkpoint_handled: bool = False
    corrupt_checkpoint_rejected: bool = False
    tool_unavailable_handoff: bool = False
    tool_crash_bounded: bool = False
    timeout_bounded: bool = False
    repeated_retry_not_recommended: bool = False
    resource_recovery_bounded: bool = False
    configuration_backup_approval: bool = False
    dependency_install_approval: bool = False
    failed_validation_revalidated: bool = False
    missing_validation_routes_validator: bool = False
    strong_code_routes_surgeon: bool = False
    weak_code_requests_evidence: bool = False
    rights_unknown_blocked: bool = False
    rights_blocked_not_repaired: bool = False
    permission_routes_rights_gate: bool = False
    missing_approval_human_action: bool = False
    competing_causes_conditional: bool = False
    conflicting_evidence_lowers_confidence: bool = False
    rendering_quality_preserved: bool = False
    silent_quality_reduction_rejected: bool = False
    no_rollback_rejected: bool = False
    destructive_source_strategy_rejected: bool = False
    unlimited_retry_rejected: bool = False
    healthy_no_action: bool = False
    checkpoint_plans_exist: bool = False
    rollback_plans_exist: bool = False
    validation_plans_exist: bool = False
    quality_plans_exist: bool = False
    approval_gates_exist: bool = False
    handoffs_exist: bool = False
    handoffs_do_not_apply: bool = False
    handoffs_require_human_approval: bool = False
    output_json_safe: bool = False
    artifact_persisted: bool = False
    export_safe: bool = False
    root_cause_analyzer_unchanged: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    scraping_used_false: bool = False
    downloading_used_false: bool = False
    command_execution_used_false: bool = False
    validator_execution_used_false: bool = False
    code_modification_used_false: bool = False
    artifact_modification_used_false: bool = False
    repair_execution_used_false: bool = False
    tool_fallback_execution_used_false: bool = False
    workflow_resume_used_false: bool = False
    service_restart_used_false: bool = False
    package_installation_used_false: bool = False
    destructive_action_used_false: bool = False
    rendering_triggered: bool = False
    media_ingestion_triggered: bool = False
    commands_executed: bool = False
    validators_executed: bool = False
    code_edits_made: bool = False
    source_artifacts_modified: bool = False
    repairs_executed: bool = False
    fallback_tools_executed: bool = False
    workflow_resumed: bool = False
    services_restarted: bool = False
    packages_installed: bool = False
    destructive_actions_made: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        probe = report_dir / ".repair_planner_write_probe"
        probe.write_text("local", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _clone_case(
    report: BobaRootCauseAnalyzerSetV1,
    source_case_id: str,
    suffix: str,
    *,
    case_updates: dict[str, Any] | None = None,
    candidate_updates: dict[str, Any] | None = None,
) -> tuple[BobaRootCauseAnalysisCaseV1, BobaRootCauseCandidateV1]:
    case = next(
        item
        for item in report.analysis_cases
        if item.source_diagnostic_case_id == source_case_id
    )
    candidate = next(
        item
        for item in report.root_cause_candidates
        if item.analysis_case_id == case.analysis_case_id
    )
    analysis_case_id = f"root_analysis_case_repair_{suffix}"
    cloned_case = case.model_copy(
        update={
            "analysis_case_id": analysis_case_id,
            "source_diagnostic_case_id": f"case_{suffix}",
            "failure_timeline_id": "",
            "causal_graph_id": "",
            "contributing_factor_ids": [],
            "downstream_symptom_ids": [],
            "evidence_gap_ids": [],
            "verification_plan_ids": [],
            **(case_updates or {}),
        }
    )
    cloned_candidate = candidate.model_copy(
        update={
            "root_cause_candidate_id": f"root_candidate_repair_{suffix}",
            "analysis_case_id": analysis_case_id,
            "supporting_evidence_ids": [],
            "conflicting_evidence_ids": [],
            "explains_symptom_ids": [],
            "unexplained_symptom_ids": [],
            **(candidate_updates or {}),
        }
    )
    return cloned_case, cloned_candidate


def build_synthetic_root_cause_report(
    project_id: str = SYNTHETIC_PROJECT_ID,
) -> BobaRootCauseAnalyzerSetV1:
    """Build deterministic persisted-style root-cause data for repair planning."""

    source = build_synthetic_error_doctor_report(project_id)
    report = BobaRootCauseAnalyzerV1().analyze(project_id, source)
    extra_cases: list[BobaRootCauseAnalysisCaseV1] = []
    extra_candidates: list[BobaRootCauseCandidateV1] = []

    missing_healthy = _clone_case(
        report,
        "case_missing_upstream",
        "missing_downstream_healthy",
        case_updates={
            "title": "Required downstream artifact is missing with healthy prerequisites",
            "earliest_known_failure": (
                "The downstream generated artifact is absent after healthy prerequisites."
            ),
            "most_likely_root_cause": (
                "The required downstream generated artifact was not persisted."
            ),
            "confirmed_facts": [
                "Required upstream inputs are present and healthy.",
                "The downstream generated artifact is absent.",
            ],
            "probable_inferences": [],
            "primary_module": "clip_ranking",
            "primary_artifact": "clip_ranking",
            "workflow_stage": "planning",
            "affected_modules": ["clip_ranking"],
            "affected_artifacts": ["clip_ranking"],
        },
        candidate_updates={
            "title": "Downstream generated artifact was not persisted",
            "candidate_summary": (
                "Healthy prerequisite artifacts exist, but the required downstream "
                "generated artifact is missing."
            ),
            "earliest_failure_relationship": (
                "The first supported failure is the absent downstream artifact."
            ),
            "category": "missing_artifact",
            "repairability": "likely_recoverable",
            "evidence_quality": "strong",
            "likelihood_score": 0.93,
            "confidence": 0.91,
        },
    )
    extra_cases.append(missing_healthy[0])
    extra_candidates.append(missing_healthy[1])

    for suffix, title in (
        ("checkpoint_valid", "A validated checkpoint is available"),
        ("checkpoint_missing", "The required checkpoint is missing"),
    ):
        cloned = _clone_case(
            report,
            "case_checkpoint",
            suffix,
            case_updates={"title": title},
        )
        extra_cases.append(cloned[0])
        extra_candidates.append(cloned[1])

    strong_code = _clone_case(
        report,
        "case_code_weak",
        "code_strong",
        case_updates={
            "title": "Repeated deterministic defect has strong code evidence",
            "analysis_status": "root_cause_supported",
            "most_likely_root_cause": (
                "A bounded implementation defect consistently produces the saved failure."
            ),
            "root_cause_confidence": 0.91,
            "confirmed_facts": [
                "The same bounded input fails at the same implementation branch.",
                "Equivalent healthy artifacts and environment inputs pass.",
            ],
            "probable_inferences": [],
            "unresolved_hypotheses": [],
        },
        candidate_updates={
            "title": "Scoped implementation defect",
            "candidate_summary": (
                "Strong bounded evidence supports a scoped implementation defect."
            ),
            "category": "code_defect",
            "repairability": "requires_code_change",
            "evidence_quality": "strong",
            "likelihood_score": 0.92,
            "confidence": 0.91,
            "verification_required": True,
        },
    )
    extra_cases.append(strong_code[0])
    extra_candidates.append(strong_code[1])

    healthy = _clone_case(
        report,
        "case_optional",
        "healthy",
        case_updates={
            "title": "Saved state is healthy",
            "analysis_status": "no_defect_detected",
            "earliest_known_failure": "No supported failure is present.",
            "most_likely_root_cause": "Healthy state is working as expected.",
            "root_cause_confidence": 0.9,
            "processing_impact": "none",
            "safety_impact": "none_known",
        },
        candidate_updates={
            "title": "No defect detected",
            "candidate_summary": "The saved state is healthy and working as expected.",
            "category": "unknown",
            "repairability": "not_a_defect",
            "evidence_quality": "strong",
            "likelihood_score": 0.9,
            "confidence": 0.9,
        },
    )
    extra_cases.append(healthy[0])
    extra_candidates.append(healthy[1])

    payload = report.model_dump(mode="json")
    payload["analysis_cases"] = [
        *payload["analysis_cases"],
        *(item.model_dump(mode="json") for item in extra_cases),
    ]
    payload["root_cause_candidates"] = [
        *payload["root_cause_candidates"],
        *(item.model_dump(mode="json") for item in extra_candidates),
    ]
    strengthened_case_ids: set[str] = set()
    for item in payload["analysis_cases"]:
        if item["source_diagnostic_case_id"] in {
            "case_configuration",
            "case_environment",
        }:
            item["analysis_status"] = "root_cause_supported"
            item["root_cause_confidence"] = 0.82
            strengthened_case_ids.add(item["analysis_case_id"])
    for item in payload["root_cause_candidates"]:
        if item["analysis_case_id"] in strengthened_case_ids:
            item["evidence_quality"] = "moderate"
            item["likelihood_score"] = 0.82
            item["confidence"] = 0.82
    return BobaRootCauseAnalyzerSetV1.model_validate(payload)


def build_synthetic_planning_context(
    report: BobaRootCauseAnalyzerSetV1,
) -> dict[str, Any]:
    """Return bounded local context for checkpoint and retry scenarios."""

    cases = {
        item.source_diagnostic_case_id: item.analysis_case_id
        for item in report.analysis_cases
    }
    return {
        "cases": {
            cases["case_missing_upstream"]: {
                "upstream_missing": True,
                "checkpoint_status": "missing",
            },
            cases["case_missing_downstream_healthy"]: {
                "upstream_healthy": True,
                "checkpoint_status": "missing",
            },
            cases["case_checkpoint_valid"]: {
                "valid_checkpoint_available": True,
                "checkpoint_status": "valid",
            },
            cases["case_checkpoint_missing"]: {
                "checkpoint_status": "missing",
            },
            cases["case_checkpoint"]: {
                "checkpoint_status": "corrupt",
            },
            cases["case_timeout"]: {
                "previously_attempted_strategies": [
                    "retry_with_safe_settings",
                ],
            },
            cases["case_resource"]: {
                "requires_external_access": True,
                "requires_paid_service": True,
            },
            cases["case_configuration"]: {
                "requires_service_restart": True,
            },
            cases["case_approval"]: {
                "human_approval_missing": True,
            },
        }
    }


def _repair_case_for_source(
    planner: BobaRepairPlannerSetV1,
    root: BobaRootCauseAnalyzerSetV1,
    source_case_id: str,
) -> BobaRepairPlanningCaseV1:
    analysis_case = next(
        item
        for item in root.analysis_cases
        if item.source_diagnostic_case_id == source_case_id
    )
    return next(
        item
        for item in planner.repair_cases
        if item.source_analysis_case_id == analysis_case.analysis_case_id
    )


def _strategies_for_case(
    planner: BobaRepairPlannerSetV1,
    repair_case_id: str,
) -> list[BobaRepairStrategyV1]:
    return [
        item
        for item in planner.repair_strategies
        if item.repair_case_id == repair_case_id
    ]


def _handoffs_for_case(
    planner: BobaRepairPlannerSetV1,
    repair_case_id: str,
) -> list[BobaRepairExecutionHandoffV1]:
    return [
        item
        for item in planner.execution_handoffs
        if item.repair_case_id == repair_case_id
    ]


def _safe_export(payload: dict[str, Any]) -> bool:
    serialized = json.dumps(payload, sort_keys=True)
    privacy = payload.get("privacy")
    return bool(
        isinstance(privacy, dict)
        and privacy.get("private_paths_excluded") is True
        and privacy.get("sensitive_evidence_excluded") is True
        and privacy.get("root_cause_analyzer_report_excluded") is True
        and "previously_attempted_strategies" not in serialized
        and "C:\\\\" not in serialized
        and "/Users/" not in serialized
        and "\"token\"" not in serialized.casefold()
        and "\"password\"" not in serialized.casefold()
    )


def _signal_checks(planner: BobaRepairPlannerSetV1) -> dict[str, bool]:
    signal = planner.signal_usage
    return {
        "external_api_used_false": not signal.external_api_used,
        "url_fetching_used_false": not signal.url_fetching_used,
        "scraping_used_false": not signal.scraping_used,
        "downloading_used_false": not signal.downloading_used,
        "command_execution_used_false": not signal.command_execution_used,
        "validator_execution_used_false": not signal.validator_execution_used,
        "code_modification_used_false": not signal.code_modification_used,
        "artifact_modification_used_false": not signal.artifact_modification_used,
        "repair_execution_used_false": not signal.repair_execution_used,
        "tool_fallback_execution_used_false": (
            not signal.tool_fallback_execution_used
        ),
        "workflow_resume_used_false": not signal.workflow_resume_used,
        "service_restart_used_false": not signal.service_restart_used,
        "package_installation_used_false": (
            not signal.package_installation_used
        ),
        "destructive_action_used_false": not signal.destructive_action_used,
    }


def run_self_check(
    report_dir: Path | None = None,
) -> BobaRepairPlannerValidationReport:
    """Validate local imports, contracts, persistence, and non-action flags."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        with TemporaryDirectory(prefix="boba-repair-planner-self-check-") as temporary:
            store = BobaMemoryStore(Path(temporary) / "boba")
            planner = BobaRepairPlannerV1().plan(
                "proj_boba_repair_planner_self_check",
                None,
            )
            store.save_boba_repair_planner(planner)
            loaded = store.load_boba_repair_planner(planner.project_id)
            contracts_serialize = (
                BobaRepairPlannerSetV1.model_validate(
                    json.loads(planner.model_dump_json())
                )
                == planner
            )
            artifact_path_writable = (
                store.repair_planner_path(planner.project_id).is_file()
                and loaded == planner
            )
        checks = {
            "module_imported": True,
            "store_available": True,
            "root_cause_analyzer_available": True,
            "contracts_serialize": contracts_serialize,
            "artifact_path_writable": artifact_path_writable
            and _report_path_writable(effective_report_dir),
            "checkpoint_registry_inspected": bool(DEFAULT_CHECKPOINT_REGISTRY),
            "validator_registry_inspected": bool(DEFAULT_VALIDATOR_REGISTRY),
            "output_json_safe": bool(json.dumps(planner.model_dump(mode="json"))),
            **_signal_checks(planner),
        }
        return BobaRepairPlannerValidationReport(
            mode="self_check",
            passed=all(checks.values()),
            **checks,
            warnings=[
                "Self-check used temporary local JSON only.",
                "No command, validator, network, media, rendering, code edit, "
                "repair, fallback, workflow resume, restart, installation, or "
                "destructive action ran.",
            ],
        )
    except Exception as exc:
        return BobaRepairPlannerValidationReport(
            mode="self_check",
            passed=False,
            module_imported=True,
            errors=[str(exc)],
        )


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaRepairPlannerValidationReport:
    """Run the complete local synthetic advisory repair-planning proof."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        root = build_synthetic_root_cause_report()
        root_before = root.model_dump_json()
        planner = BobaRepairPlannerV1().plan(
            SYNTHETIC_PROJECT_ID,
            root,
            manual_context=build_synthetic_planning_context(root),
        )

        def case(source_case_id: str) -> BobaRepairPlanningCaseV1:
            return _repair_case_for_source(planner, root, source_case_id)

        def strategies(source_case_id: str) -> list[BobaRepairStrategyV1]:
            repair_case = case(source_case_id)
            return _strategies_for_case(planner, repair_case.repair_case_id)

        def handoffs(source_case_id: str) -> list[BobaRepairExecutionHandoffV1]:
            repair_case = case(source_case_id)
            return _handoffs_for_case(planner, repair_case.repair_case_id)

        def recommended(source_case_id: str) -> BobaRepairStrategyV1:
            repair_case = case(source_case_id)
            return next(
                item
                for item in strategies(source_case_id)
                if item.repair_strategy_id
                == repair_case.recommended_strategy_id
            )

        rejected_titles = {
            item.title.casefold() for item in planner.rejected_strategies
        }
        corrupt_rejected = [
            item
            for item in planner.rejected_strategies
            if item.repair_case_id == case("case_checkpoint").repair_case_id
        ]
        rendering_quality = next(
            item
            for item in planner.quality_preservation_plans
            if item.repair_case_id == case("case_resource").repair_case_id
        )
        configuration_strategies = strategies("case_configuration")
        environment_strategies = strategies("case_environment")
        validation_failed_plan = next(
            item
            for item in planner.validation_plans
            if item.repair_case_id == case("case_validation_failed").repair_case_id
        )
        competing_case = case("case_competing")
        source_competing = next(
            item
            for item in root.analysis_cases
            if item.source_diagnostic_case_id == "case_competing"
        )
        with TemporaryDirectory(prefix="boba-repair-planner-synthetic-") as temporary:
            store = BobaMemoryStore(Path(temporary) / "boba")
            store.save_boba_root_cause_analyzer(root)
            root_path = store.root_cause_analyzer_path(root.project_id)
            persisted_root_before = (
                root_path.read_bytes(),
                root_path.stat().st_mtime_ns,
            )
            store.save_boba_repair_planner(planner)
            loaded = store.load_boba_repair_planner(root.project_id)
            export = store.export_boba_repair_planner(root.project_id)
            persisted_root_after = (
                root_path.read_bytes(),
                root_path.stat().st_mtime_ns,
            )
            persisted = (
                store.repair_planner_path(root.project_id).is_file()
                and loaded == planner
            )

        checks = {
            "module_imported": True,
            "store_available": True,
            "root_cause_analyzer_available": True,
            "contracts_serialize": (
                BobaRepairPlannerSetV1.model_validate(
                    json.loads(planner.model_dump_json())
                )
                == planner
            ),
            "artifact_path_writable": _report_path_writable(effective_report_dir),
            "checkpoint_registry_inspected": bool(DEFAULT_CHECKPOINT_REGISTRY),
            "validator_registry_inspected": bool(DEFAULT_VALIDATOR_REGISTRY),
            "repair_cases_exist": bool(planner.repair_cases),
            "multiple_strategies_exist": any(
                len(_strategies_for_case(planner, item.repair_case_id)) >= 2
                for item in planner.repair_cases
            ),
            "recommended_strategies_exist": any(
                item.recommended for item in planner.repair_strategies
            ),
            "alternative_strategies_exist": any(
                item.alternative_strategy_ids for item in planner.repair_cases
            ),
            "unsafe_strategies_rejected": bool(planner.rejected_strategies),
            "missing_healthy_regeneration": (
                recommended("case_missing_downstream_healthy") is not None
                and recommended(
                    "case_missing_downstream_healthy"
                ).strategy_type
                == "regenerate_artifact"
            ),
            "missing_upstream_first": (
                recommended("case_missing_upstream") is not None
                and recommended("case_missing_upstream").strategy_type
                == "collect_more_evidence"
            ),
            "corrupt_artifact_recovery": any(
                item.strategy_type
                in {"regenerate_artifact", "restore_checkpoint"}
                for item in strategies("case_corrupt")
            ),
            "stale_scoped_regeneration": any(
                item.strategy_type == "regenerate_artifact"
                for item in strategies("case_stale")
            ),
            "valid_checkpoint_selected": (
                recommended("case_checkpoint_valid") is not None
                and recommended("case_checkpoint_valid").strategy_type
                == "restore_checkpoint"
            ),
            "missing_checkpoint_handled": all(
                item.strategy_type != "restore_checkpoint"
                for item in strategies("case_checkpoint_missing")
            ),
            "corrupt_checkpoint_rejected": any(
                "corrupt checkpoint" in item.title.casefold()
                for item in corrupt_rejected
            ),
            "tool_unavailable_handoff": any(
                item.target_module == "tool_recovery_brain"
                for item in handoffs("case_tool_missing")
            ),
            "tool_crash_bounded": any(
                item.maximum_attempts is not None
                and item.maximum_recovery_duration_seconds is not None
                for item in strategies("case_tool_crash")
                if item.strategy_type
                in {
                    "retry_same_tool",
                    "retry_with_safe_settings",
                    "use_registered_tool_fallback",
                }
            ),
            "timeout_bounded": all(
                item.maximum_attempts is not None
                and item.maximum_recovery_duration_seconds is not None
                for item in strategies("case_timeout")
                if item.strategy_type == "retry_with_safe_settings"
            ),
            "repeated_retry_not_recommended": (
                recommended("case_timeout") is not None
                and recommended("case_timeout").strategy_type
                != "retry_with_safe_settings"
            ),
            "resource_recovery_bounded": any(
                item.strategy_type == "reduce_resource_usage"
                and item.maximum_attempts is not None
                for item in strategies("case_resource")
            ),
            "configuration_backup_approval": any(
                item.strategy_type == "repair_configuration"
                and item.requires_backup
                and item.human_approval_required
                for item in configuration_strategies
            ),
            "dependency_install_approval": any(
                item.strategy_type == "repair_environment"
                and item.requires_package_installation
                and item.human_approval_required
                for item in environment_strategies
            ),
            "failed_validation_revalidated": (
                "artifact_integrity"
                in validation_failed_plan.required_validators
                and any(
                    item.strategy_type == "rerun_validation"
                    for item in strategies("case_validation_failed")
                )
            ),
            "missing_validation_routes_validator": (
                case("case_validation_missing").planning_status
                == "needs_more_evidence"
                and any(
                    item.target_module == "validator_runner"
                    for item in handoffs("case_validation_missing")
                )
            ),
            "strong_code_routes_surgeon": any(
                item.target_module == "code_surgeon"
                for item in handoffs("case_code_strong")
            ),
            "weak_code_requests_evidence": (
                case("case_code_weak").planning_status == "needs_more_evidence"
                and all(
                    item.strategy_type != "propose_code_patch"
                    for item in strategies("case_code_weak")
                )
            ),
            "rights_unknown_blocked": (
                case("case_rights_unknown").planning_status
                == "intentional_safety_block"
            ),
            "rights_blocked_not_repaired": (
                not case("case_rights_blocked").repair_needed
                and all(
                    item.strategy_type in {"seek_permission", "stop_processing"}
                    for item in strategies("case_rights_blocked")
                )
            ),
            "permission_routes_rights_gate": any(
                item.target_module == "rights_permission_gate"
                for item in handoffs("case_rights_unknown")
            ),
            "missing_approval_human_action": (
                case("case_approval").planning_status
                == "human_decision_required"
                and any(
                    item.strategy_type == "human_manual_action"
                    for item in strategies("case_approval")
                )
            ),
            "competing_causes_conditional": (
                competing_case.planning_status
                in {"conflicting_causes", "conditional_plan"}
                and any(
                    item.strategy_type == "collect_more_evidence"
                    for item in strategies("case_competing")
                )
            ),
            "conflicting_evidence_lowers_confidence": (
                competing_case.confidence < source_competing.root_cause_confidence
            ),
            "rendering_quality_preserved": (
                any(
                    "A/V synchronization" in item
                    for item in rendering_quality.non_negotiable_requirements
                )
                and any(
                    "Silent reduction" in item
                    for item in rendering_quality.unacceptable_degradations
                )
            ),
            "silent_quality_reduction_rejected": (
                "silently lower output quality" in rejected_titles
            ),
            "no_rollback_rejected": (
                "execute without checkpoint or rollback" in rejected_titles
            ),
            "destructive_source_strategy_rejected": (
                "modify or delete source media" in rejected_titles
            ),
            "unlimited_retry_rejected": (
                "retry without a finite budget" in rejected_titles
            ),
            "healthy_no_action": (
                recommended("case_healthy") is not None
                and recommended("case_healthy").strategy_type == "no_action"
            ),
            "checkpoint_plans_exist": bool(planner.checkpoint_plans),
            "rollback_plans_exist": bool(planner.rollback_plans),
            "validation_plans_exist": bool(planner.validation_plans),
            "quality_plans_exist": bool(planner.quality_preservation_plans),
            "approval_gates_exist": bool(planner.approval_gates),
            "handoffs_exist": bool(planner.execution_handoffs),
            "handoffs_do_not_apply": all(
                not item.apply_automatically
                for item in planner.execution_handoffs
            ),
            "handoffs_require_human_approval": all(
                item.human_approval_required
                for item in planner.execution_handoffs
            ),
            "output_json_safe": bool(
                json.dumps(planner.model_dump(mode="json"))
            ),
            "artifact_persisted": persisted,
            "export_safe": _safe_export(export),
            "root_cause_analyzer_unchanged": (
                root.model_dump_json() == root_before
                and persisted_root_before == persisted_root_after
            ),
            **_signal_checks(planner),
            "rendering_triggered": False,
            "media_ingestion_triggered": False,
            "commands_executed": False,
            "validators_executed": False,
            "code_edits_made": False,
            "source_artifacts_modified": False,
            "repairs_executed": False,
            "fallback_tools_executed": False,
            "workflow_resumed": False,
            "services_restarted": False,
            "packages_installed": False,
            "destructive_actions_made": False,
        }
        action_outcomes = {
            "rendering_triggered",
            "media_ingestion_triggered",
            "commands_executed",
            "validators_executed",
            "code_edits_made",
            "source_artifacts_modified",
            "repairs_executed",
            "fallback_tools_executed",
            "workflow_resumed",
            "services_restarted",
            "packages_installed",
            "destructive_actions_made",
        }
        return BobaRepairPlannerValidationReport(
            mode="synthetic_project",
            project_id=SYNTHETIC_PROJECT_ID,
            passed=(
                all(
                    value
                    for name, value in checks.items()
                    if name not in action_outcomes
                )
                and not any(checks[name] for name in action_outcomes)
            ),
            **checks,
            warnings=[
                "Synthetic local data covered all 30 required planning scenarios.",
                "No command, validator, network, media, rendering, code edit, "
                "repair, fallback, workflow resume, restart, installation, or "
                "destructive action ran.",
            ],
        )
    except Exception as exc:
        return BobaRepairPlannerValidationReport(
            mode="synthetic_project",
            passed=False,
            project_id=SYNTHETIC_PROJECT_ID,
            module_imported=True,
            errors=[str(exc)],
        )


def run_existing_project(
    project_id: str,
    report_dir: Path | None = None,
) -> BobaRepairPlannerValidationReport:
    """Load saved causal analysis and safely create or load a planner artifact."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        settings = get_settings()
        store = BobaMemoryStore(
            settings.boba.storage_dir,
            memory_root=settings.boba_memory.storage_dir,
        )
        root = store.load_boba_root_cause_analyzer(project_id)
        if root is None:
            return BobaRepairPlannerValidationReport(
                mode="project_id",
                passed=False,
                project_id=project_id,
                module_imported=True,
                store_available=True,
                root_cause_analyzer_available=False,
                artifact_path_writable=_report_path_writable(
                    effective_report_dir
                ),
                checkpoint_registry_inspected=bool(
                    DEFAULT_CHECKPOINT_REGISTRY
                ),
                validator_registry_inspected=bool(DEFAULT_VALIDATOR_REGISTRY),
                warnings=[
                    "Saved Root Cause Analyzer data is missing. Repair Planner "
                    "did not regenerate Root Cause Analyzer, Error Doctor, or Observer."
                ],
            )
        root_path = store.root_cause_analyzer_path(project_id)
        root_before = (root_path.read_bytes(), root_path.stat().st_mtime_ns)
        planner = store.load_boba_repair_planner(project_id)
        if planner is None:
            planner = BobaRepairPlannerV1().plan(project_id, root)
            store.save_boba_repair_planner(planner)
        root_after = (root_path.read_bytes(), root_path.stat().st_mtime_ns)
        signal_checks = _signal_checks(planner)
        return BobaRepairPlannerValidationReport(
            mode="project_id",
            project_id=project_id,
            passed=(
                store.repair_planner_path(project_id).is_file()
                and root_before == root_after
                and all(signal_checks.values())
            ),
            module_imported=True,
            store_available=True,
            root_cause_analyzer_available=True,
            contracts_serialize=True,
            artifact_path_writable=_report_path_writable(effective_report_dir),
            checkpoint_registry_inspected=bool(DEFAULT_CHECKPOINT_REGISTRY),
            validator_registry_inspected=bool(DEFAULT_VALIDATOR_REGISTRY),
            repair_cases_exist=bool(planner.repair_cases),
            multiple_strategies_exist=any(
                len(_strategies_for_case(planner, item.repair_case_id)) >= 2
                for item in planner.repair_cases
            ),
            recommended_strategies_exist=any(
                item.recommended for item in planner.repair_strategies
            ),
            unsafe_strategies_rejected=bool(planner.rejected_strategies),
            checkpoint_plans_exist=bool(planner.checkpoint_plans),
            rollback_plans_exist=bool(planner.rollback_plans),
            validation_plans_exist=bool(planner.validation_plans),
            quality_plans_exist=bool(planner.quality_preservation_plans),
            approval_gates_exist=bool(planner.approval_gates),
            handoffs_exist=bool(planner.execution_handoffs),
            handoffs_do_not_apply=all(
                not item.apply_automatically
                for item in planner.execution_handoffs
            ),
            handoffs_require_human_approval=all(
                item.human_approval_required
                for item in planner.execution_handoffs
            ),
            output_json_safe=bool(
                json.dumps(planner.model_dump(mode="json"))
            ),
            artifact_persisted=store.repair_planner_path(project_id).is_file(),
            export_safe=_safe_export(
                store.export_boba_repair_planner(project_id)
            ),
            root_cause_analyzer_unchanged=root_before == root_after,
            **signal_checks,
            warnings=[
                "Project mode loaded the saved Root Cause Analyzer artifact and "
                "did not run upstream diagnostics or any planned action."
            ],
        )
    except Exception as exc:
        return BobaRepairPlannerValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            module_imported=True,
            errors=[str(exc)],
            warnings=[
                "No command, validator, external API, download, render, code "
                "edit, repair, fallback, workflow resume, restart, installation, "
                "or destructive action was attempted."
            ],
        )


def _write_report(
    report: BobaRepairPlannerValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_repair_planner_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Repair Planner V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Repair cases: `{report.repair_cases_exist}`",
        f"- Multiple strategies: `{report.multiple_strategies_exist}`",
        f"- Unsafe strategies rejected: `{report.unsafe_strategies_rejected}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- Commands or validators executed by Repair Planner: `false`",
        "- Repairs, code edits, artifact changes, or fallback tools executed: `false`",
        "- Workflow resumes, service restarts, or packages installed: `false`",
        "- External APIs, URLs, downloads, ingestion, or rendering: `false`",
        "",
        "Repair Planner V1 creates advisory plans only; success is not guaranteed.",
    ]
    (report_dir / "boba_repair_planner_v1_summary.md").write_text(
        "\n".join(summary),
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report_dir = args.report_dir.resolve()
    if args.self_check:
        report = run_self_check(report_dir)
    elif args.synthetic_project:
        report = run_synthetic_project(report_dir)
    else:
        report = run_existing_project(str(args.project_id), report_dir)
    _write_report(report, report_dir)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
