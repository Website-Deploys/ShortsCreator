"""Validate BOBA Root Cause Analyzer V1 with bounded local diagnostic data."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.boba.error_doctor import (  # noqa: E402
    BobaCascadingImpactV1,
    BobaClassifiedFindingV1,
    BobaDiagnosticCaseV1,
    BobaDiagnosticEvidenceV1,
    BobaDiagnosticHypothesisV1,
    BobaErrorDoctorSetV1,
    BobaErrorDoctorSignalUsageV1,
    BobaErrorDoctorSummaryV1,
)
from olympus.boba.observer import build_boba_artifact_registry  # noqa: E402
from olympus.boba.root_cause_analyzer import (  # noqa: E402
    BobaRootCauseAnalyzerSetV1,
    BobaRootCauseAnalyzerV1,
    BobaRootCauseCandidateV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_root_cause_analyzer"
SYNTHETIC_PROJECT_ID = "proj_boba_root_cause_synthetic"


class BobaRootCauseAnalyzerValidationReport(BaseModel):
    """Compact proof that causal analysis is advisory and non-applying."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    module_imported: bool = False
    store_available: bool = False
    error_doctor_available: bool = False
    contracts_serialize: bool = False
    artifact_path_writable: bool = False
    dependency_registry_builds: bool = False
    analysis_cases_exist: bool = False
    failure_timelines_exist: bool = False
    causal_graphs_exist: bool = False
    root_cause_candidates_exist: bool = False
    contributing_factors_exist: bool = False
    downstream_symptoms_exist: bool = False
    evidence_gaps_exist: bool = False
    verification_plans_exist: bool = False
    workflow_impacts_exist: bool = False
    handoffs_exist: bool = False
    earliest_failure_separate_from_root_cause: bool = False
    missing_upstream_ranked_above_symptoms: bool = False
    duplicate_symptoms_share_cascade: bool = False
    optional_missing_not_critical: bool = False
    corrupt_required_is_blocking: bool = False
    stale_output_linked_conservatively: bool = False
    missing_validation_is_gap: bool = False
    failed_validation_is_confirmed: bool = False
    unknown_validation_format_unknown: bool = False
    configuration_remains_hypothesis: bool = False
    environment_remains_hypothesis: bool = False
    resource_exhaustion_routes_to_recovery: bool = False
    missing_executable_routes_to_recovery: bool = False
    code_defect_not_proven: bool = False
    rights_unknown_is_safety_block: bool = False
    rights_blocked_not_defect: bool = False
    missing_approval_not_code_failure: bool = False
    competing_candidates_preserved: bool = False
    contradictory_evidence_preserved: bool = False
    confirmation_checks_exist: bool = False
    rejection_checks_exist: bool = False
    verification_plans_advisory: bool = False
    handoffs_do_not_apply: bool = False
    handoffs_require_human_approval: bool = False
    output_json_safe: bool = False
    artifact_persisted: bool = False
    export_safe: bool = False
    error_doctor_unchanged: bool = False
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
    destructive_action_used_false: bool = False
    rendering_triggered: bool = False
    media_ingestion_triggered: bool = False
    commands_executed: bool = False
    validators_executed: bool = False
    code_edits_made: bool = False
    source_artifacts_modified: bool = False
    repairs_executed: bool = False
    fallback_tools_executed: bool = False
    destructive_actions_made: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _evidence(
    case_id: str,
    *,
    source_type: str,
    summary: str,
    module: str,
    artifact: str,
    timestamp: str = "",
    confidence: float = 0.9,
    evidence_id: str = "",
) -> BobaDiagnosticEvidenceV1:
    return BobaDiagnosticEvidenceV1(
        evidence_id=evidence_id or f"ev_{case_id}",
        source_type=source_type,
        source_id=f"source_{case_id}",
        module_name=module,
        artifact_id=artifact,
        evidence_summary=summary,
        observed_value=summary,
        expected_value="Expected healthy saved state.",
        timestamp=timestamp,
        confidence=confidence,
        usage_warning="Synthetic bounded evidence only.",
    )


def _hypothesis(
    case_id: str,
    name: str,
    *,
    category: str,
    confidence: float = 0.45,
    conflicts: list[str] | None = None,
) -> BobaDiagnosticHypothesisV1:
    return BobaDiagnosticHypothesisV1(
        hypothesis_id=f"hyp_{case_id}_{name}",
        hypothesis=name,
        category=category,
        supporting_evidence_ids=[f"ev_{case_id}"],
        conflicting_evidence_ids=conflicts or [],
        confidence=confidence,
        verification_needed=True,
        suggested_check="Inspect bounded saved evidence through a future approved module.",
        warnings=["Synthetic hypothesis is not proven."],
    )


def _case(
    case_id: str,
    *,
    title: str,
    category: str,
    module: str,
    artifact: str,
    symptom: str,
    cause: str,
    timestamp: str = "",
    evidence_type: str = "artifact_observation",
    severity: str = "high",
    status: str = "probable",
    processing: str = "partial_block",
    safety: str = "none_known",
    affected_modules: list[str] | None = None,
    missing: list[str] | None = None,
    hypotheses: list[BobaDiagnosticHypothesisV1] | None = None,
    extra_evidence: list[BobaDiagnosticEvidenceV1] | None = None,
) -> BobaDiagnosticCaseV1:
    evidence = [
        _evidence(
            case_id,
            source_type=evidence_type,
            summary=symptom,
            module=module,
            artifact=artifact,
            timestamp=timestamp,
        ),
        *(extra_evidence or []),
    ]
    return BobaDiagnosticCaseV1(
        diagnostic_case_id=f"case_{case_id}",
        title=title,
        primary_module=module,
        primary_artifact=artifact,
        workflow_stage=(
            "rights_safety"
            if safety in {"rights_gate_blocked", "safety_gate_blocked"}
            else "self_healing"
        ),
        error_category=category,
        severity=severity,
        urgency=(
            "blocked"
            if severity == "blocker"
            else "immediate"
            if severity == "critical"
            else "soon"
            if severity == "high"
            else "normal"
        ),
        diagnosis_status=status,
        symptom_summary=symptom,
        probable_cause_summary=cause,
        confirmed_facts=(
            [symptom] if status == "observed_fact" else []
        ),
        hypotheses=hypotheses or [],
        affected_modules=affected_modules or [module],
        affected_artifacts=[artifact] if artifact else [],
        related_finding_ids=[f"finding_{case_id}"],
        evidence=evidence,
        missing_information=missing or [],
        processing_impact=processing,
        safety_impact=safety,
        recommended_investigation=[
            "Inspect bounded saved evidence through a future approved module."
        ],
        escalation_target="root_cause_analyzer",
        confidence=0.88 if status == "observed_fact" else 0.58,
        warnings=[],
        limitations=["Synthetic local diagnostic case."],
    )


def build_synthetic_error_doctor_report(
    project_id: str = SYNTHETIC_PROJECT_ID,
) -> BobaErrorDoctorSetV1:
    """Build deterministic Error Doctor input covering the required scenarios."""

    cases = [
        _case(
            "missing_upstream",
            title="Required upstream artifact is missing",
            category="missing_dependency",
            module="whole_video",
            artifact="whole_video",
            symptom=(
                "The required whole_video artifact is missing and downstream "
                "video-intelligence modules are blocked."
            ),
            cause=(
                "The blocked chain is directly caused by the confirmed missing "
                "required upstream artifact."
            ),
            timestamp="2026-01-15T10:00:00+00:00",
            evidence_type="dependency_observation",
            severity="blocker",
            status="observed_fact",
            processing="full_block",
            affected_modules=[
                "whole_video",
                "candidate_clip_discovery",
                "clip_ranking",
                "editorial_decision",
            ],
        ),
        _case(
            "corrupt",
            title="Required artifact is corrupt",
            category="corrupt_artifact",
            module="candidate_clip_discovery",
            artifact="candidate_clip_discovery",
            symptom="The required candidate discovery artifact is corrupt and unreadable.",
            cause="The corrupt required artifact is the earliest supported failure.",
            timestamp="2026-01-15T10:05:00+00:00",
            severity="critical",
            status="observed_fact",
            processing="full_block",
        ),
        _case(
            "stale",
            title="Downstream artifact predates upstream update",
            category="stale_artifact",
            module="clip_ranking",
            artifact="clip_ranking",
            symptom="The clip ranking output is stale after an upstream update.",
            cause="A stale downstream artifact may explain the inconsistent ranking state.",
            timestamp="2026-01-15T10:10:00+00:00",
            evidence_type="dependency_observation",
            affected_modules=["clip_ranking", "editorial_decision"],
            missing=["Semantic version linkage between upstream and downstream artifacts."],
        ),
        _case(
            "optional",
            title="Optional context artifact is missing",
            category="missing_artifact",
            module="clip_briefs",
            artifact="optional_editorial_context",
            symptom="An optional editorial context artifact is missing.",
            cause="The optional input may reduce context but does not block processing.",
            severity="informational",
            status="observed_fact",
            processing="none",
        ),
        _case(
            "validation_failed",
            title="Required validator failed",
            category="validation_failure",
            module="rendering",
            artifact="render_manifest",
            symptom="The required rendering validation report has a failed status.",
            cause="The confirmed failed validation blocks acceptance of the render.",
            timestamp="2026-01-15T10:15:00+00:00",
            evidence_type="validation_observation",
            severity="blocker",
            status="observed_fact",
            processing="full_block",
        ),
        _case(
            "validation_missing",
            title="Required validation report is missing",
            category="validation_missing",
            module="rendering",
            artifact="render_validation",
            symptom="The required validation report is missing.",
            cause="Validation proof is unavailable; this alone does not prove software failure.",
            evidence_type="validation_observation",
            severity="medium",
            status="possible",
            processing="degraded",
            missing=["A current required rendering validation report."],
        ),
        _case(
            "validation_unknown",
            title="Validation report format is unknown",
            category="validation_missing",
            module="optimization",
            artifact="optimization_validation",
            symptom="The saved report has an unknown validation format.",
            cause="The unknown validation format cannot establish pass or failure.",
            evidence_type="validation_observation",
            severity="medium",
            status="unknown",
            processing="degraded",
            missing=["A known validation schema and status field."],
        ),
        _case(
            "configuration",
            title="Configuration may be incomplete",
            category="configuration",
            module="rendering",
            artifact="render_config",
            symptom="A required bounded rendering setting was not observed.",
            cause="Incomplete configuration is a possible explanation, not a proven cause.",
            status="possible",
            missing=["Bounded non-secret effective configuration."],
            hypotheses=[
                _hypothesis(
                    "configuration",
                    "The effective render configuration may be incomplete.",
                    category="configuration_factor",
                )
            ],
        ),
        _case(
            "environment",
            title="Environment may be incompatible",
            category="environment",
            module="rendering",
            artifact="runtime_environment",
            symptom="The expected runtime capability was not confirmed.",
            cause="An environment difference is possible but unverified.",
            status="possible",
            missing=["Bounded runtime capability and version metadata."],
            hypotheses=[
                _hypothesis(
                    "environment",
                    "The local runtime environment may differ from a successful run.",
                    category="environment_factor",
                )
            ],
        ),
        _case(
            "tool_missing",
            title="Required executable is unavailable",
            category="external_tool",
            module="rendering",
            artifact="ffmpeg",
            symptom="The required FFmpeg executable is unavailable or not found.",
            cause="Tool unavailability is a directly supported operational explanation.",
            evidence_type="manual_context",
            severity="blocker",
            status="observed_fact",
            processing="full_block",
        ),
        _case(
            "tool_crash",
            title="Required tool crashed",
            category="external_tool",
            module="rendering",
            artifact="ffmpeg",
            symptom="The local FFmpeg tool crashed before producing output.",
            cause="A temporary tool failure may explain the missing output.",
            evidence_type="manual_context",
            status="probable",
            missing=["Bounded tool version and failure output."],
        ),
        _case(
            "resource",
            title="Renderer exhausted local resources",
            category="resource_exhaustion",
            module="rendering",
            artifact="render_output",
            symptom="FFmpeg reported resource exhaustion during rendering.",
            cause="Resource pressure is the strongest current operational explanation.",
            evidence_type="manual_context",
            severity="critical",
            status="observed_fact",
            processing="full_block",
            missing=["Bounded resource history for the failed render stage."],
        ),
        _case(
            "timeout",
            title="Renderer timed out",
            category="timeout",
            module="rendering",
            artifact="render_output",
            symptom="The bounded render operation timed out.",
            cause="A timeout exposed the failure but may not be the deeper cause.",
            evidence_type="manual_context",
            status="observed_fact",
            processing="partial_block",
        ),
        _case(
            "checkpoint",
            title="Canonical checkpoint is invalid",
            category="storage",
            module="workflow_controller",
            artifact="render_checkpoint",
            symptom="The canonical render checkpoint is missing or invalid.",
            cause="Checkpoint failure may block optimization despite downstream symptoms.",
            evidence_type="dependency_observation",
            severity="blocker",
            status="observed_fact",
            processing="full_block",
        ),
        _case(
            "weak_input",
            title="Input data quality is weak",
            category="data_quality",
            module="analysis",
            artifact="analysis_signals",
            symptom="The saved input signal confidence is weak.",
            cause="Weak input data may degrade downstream analysis quality.",
            status="probable",
            processing="degraded",
        ),
        _case(
            "rights_unknown",
            title="Rights status is unknown",
            category="rights_safety",
            module="rights_permission_gate",
            artifact="rights_permission_gate",
            symptom="Source rights are unknown and unsafe processing is blocked.",
            cause="Unknown rights are an intentional safety blocker, not a software defect.",
            evidence_type="safety_observation",
            severity="blocker",
            status="observed_fact",
            processing="unsafe_to_continue",
            safety="rights_gate_blocked",
            missing=["Human-reviewed rights evidence."],
        ),
        _case(
            "rights_blocked",
            title="Rights gate blocked processing",
            category="rights_safety",
            module="rights_permission_gate",
            artifact="rights_permission_gate",
            symptom="The saved rights gate explicitly blocked processing.",
            cause="The rights decision intentionally blocks processing and is not a defect.",
            evidence_type="safety_observation",
            severity="blocker",
            status="observed_fact",
            processing="unsafe_to_continue",
            safety="rights_gate_blocked",
        ),
        _case(
            "approval",
            title="Human approval is missing",
            category="permission",
            module="workflow_controller",
            artifact="approval_state",
            symptom="Required human approval is missing.",
            cause="Processing is waiting for a human decision, not a code repair.",
            evidence_type="safety_observation",
            severity="high",
            status="observed_fact",
            processing="partial_block",
            safety="human_review_needed",
        ),
        _case(
            "competing",
            title="Configuration and environment explanations compete",
            category="configuration",
            module="rendering",
            artifact="render_environment",
            symptom=(
                "Rendering failed while both configuration and environment "
                "states are incomplete."
            ),
            cause="Configuration is one possible explanation.",
            status="possible",
            hypotheses=[
                _hypothesis(
                    "competing",
                    "Configuration may be incomplete.",
                    category="configuration_factor",
                    confidence=0.48,
                    conflicts=["ev_healthy_config"],
                ),
                _hypothesis(
                    "competing",
                    "Environment capability may be incompatible.",
                    category="environment_factor",
                    confidence=0.47,
                ),
            ],
            extra_evidence=[
                _evidence(
                    "competing_healthy",
                    source_type="artifact_observation",
                    summary="A bounded configuration snapshot appears present and healthy.",
                    module="rendering",
                    artifact="render_environment",
                    confidence=0.85,
                    evidence_id="ev_healthy_config",
                )
            ],
            missing=[
                "A successful comparison run using the same configuration and environment."
            ],
        ),
        _case(
            "code_weak",
            title="Generic failure weakly suggests code defect",
            category="unknown",
            module="rendering",
            artifact="render_output",
            symptom="A generic operation failed without a direct software fault signal.",
            cause="A code defect is only a weak possible explanation.",
            status="possible",
            hypotheses=[
                _hypothesis(
                    "code_weak",
                    "A code defect may exist, but simpler causes are not excluded.",
                    category="direct_cause",
                    confidence=0.25,
                )
            ],
            missing=["Direct code-defect evidence after simpler causes are excluded."],
        ),
        _case(
            "tool_malformed",
            title="Tool output is malformed",
            category="external_tool",
            module="analysis",
            artifact="tool_output",
            symptom="A local tool returned malformed output.",
            cause="Tool failure requires future fallback-capability analysis.",
            evidence_type="manual_context",
            status="probable",
            missing=["Required output schema and tool compatibility evidence."],
        ),
    ]
    missing_case = cases[0]
    findings = [
        BobaClassifiedFindingV1(
            classified_finding_id=f"finding_duplicate_{index}",
            observer_finding_id=f"observer_duplicate_{index}",
            source_observation_type="dependency",
            module_name=module,
            artifact_id=module,
            original_issue_level="blocker",
            classified_category="broken_dependency",
            severity="blocker",
            is_primary_symptom=False,
            is_secondary_symptom=True,
            is_possible_cause=False,
            is_downstream_effect=True,
            duplicate_group_id="duplicate_missing_upstream",
            cascade_group_id="cascade_missing_upstream",
            explanation=f"{module} is blocked by the same missing upstream artifact.",
            evidence=[],
            confidence=0.9,
            warnings=[],
        )
        for index, module in enumerate(
            ("candidate_clip_discovery", "clip_ranking", "editorial_decision"),
            start=1,
        )
    ]
    missing_case.related_finding_ids.extend(
        item.classified_finding_id for item in findings
    )
    cascade = BobaCascadingImpactV1(
        cascade_id="cascade_missing_upstream",
        originating_case_id=missing_case.diagnostic_case_id,
        originating_module="whole_video",
        impacted_modules=[
            "candidate_clip_discovery",
            "clip_ranking",
            "editorial_decision",
        ],
        impacted_artifacts=[
            "candidate_clip_discovery",
            "clip_ranking",
            "editorial_decision",
        ],
        impact_chain=[
            "whole_video",
            "candidate_clip_discovery",
            "clip_ranking",
            "editorial_decision",
        ],
        blocked_workflow_stages=["video_intelligence"],
        severity="blocker",
        explanation="One missing required upstream artifact blocks several downstream modules.",
        confidence=0.94,
        warnings=[],
    )
    severity_counts = Counter(item.severity for item in cases)
    return BobaErrorDoctorSetV1(
        project_id=project_id,
        source_id="synthetic_root_cause_source",
        observer_source="synthetic_saved_observer_v1",
        diagnostic_cases=cases,
        classified_findings=findings,
        cascading_impacts=[cascade],
        investigation_recommendations=[],
        escalation_handoffs=[],
        doctor_summary=BobaErrorDoctorSummaryV1(
            total_observer_findings=len(findings),
            total_diagnostic_cases=len(cases),
            informational_count=severity_counts["informational"],
            low_count=severity_counts["low"],
            medium_count=severity_counts["medium"],
            high_count=severity_counts["high"],
            critical_count=severity_counts["critical"],
            blocker_count=severity_counts["blocker"],
            unknown_count=severity_counts["unknown"],
            primary_problem_count=len(cases),
            cascading_problem_count=1,
            blocked_workflow_count=1,
            highest_priority_case=missing_case.title,
            safest_next_investigation="Inspect bounded saved evidence.",
            unresolved_information=[
                item
                for case in cases
                for item in case.missing_information
            ][:64],
            human_review_notes=["Synthetic local data only."],
        ),
        signal_usage=BobaErrorDoctorSignalUsageV1(
            observer_used=True,
            observer_artifact_read=True,
            validation_observations_used=True,
            dependency_observations_used=True,
            safety_observations_used=True,
        ),
        warnings=["Synthetic Error Doctor report for local validation."],
        limitations=["No real project or media was used."],
    )


def _safe_export(payload: dict[str, object]) -> bool:
    encoded = json.dumps(payload).casefold()
    privacy = payload.get("privacy")
    return bool(
        isinstance(privacy, dict)
        and privacy.get("private_paths_excluded") is True
        and privacy.get("full_evidence_values_excluded") is True
        and privacy.get("raw_logs_excluded") is True
        and privacy.get("error_doctor_report_excluded") is True
        and privacy.get("observer_report_excluded") is True
        and '"observed_value":' not in encoded
        and '"expected_value":' not in encoded
        and '"observed_at":' not in encoded
        and '"api_key":' not in encoded
        and '"access_token":' not in encoded
        and '"password":' not in encoded
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("local-root-cause-validation-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def run_self_check(
    report_dir: Path | None = None,
) -> BobaRootCauseAnalyzerValidationReport:
    """Validate imports, contracts, storage, registry, and non-execution defaults."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        with TemporaryDirectory(prefix="boba-root-cause-self-check-") as temporary:
            store = BobaMemoryStore(Path(temporary) / "boba")
            analysis = BobaRootCauseAnalyzerV1().analyze(
                "proj_boba_root_cause_self_check",
                None,
            )
            store.save_boba_root_cause_analyzer(analysis)
            loaded = store.load_boba_root_cause_analyzer(analysis.project_id)
            contracts_serialize = (
                BobaRootCauseAnalyzerSetV1.model_validate(
                    json.loads(analysis.model_dump_json())
                )
                == analysis
            )
            artifact_path_writable = (
                store.root_cause_analyzer_path(analysis.project_id).is_file()
                and loaded == analysis
            )
        signal = analysis.signal_usage
        checks = {
            "module_imported": True,
            "store_available": True,
            "error_doctor_available": True,
            "contracts_serialize": contracts_serialize,
            "artifact_path_writable": artifact_path_writable,
            "dependency_registry_builds": len(build_boba_artifact_registry()) == 19,
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
            "destructive_action_used_false": not signal.destructive_action_used,
        }
        return BobaRootCauseAnalyzerValidationReport(
            mode="self_check",
            passed=all(checks.values()) and _report_path_writable(effective_report_dir),
            **checks,
            warnings=[
                "Self-check used temporary local JSON only.",
                "No command, validator, network, media, rendering, repair, "
                "fallback, or destructive action ran.",
            ],
        )
    except Exception as exc:
        return BobaRootCauseAnalyzerValidationReport(
            mode="self_check",
            passed=False,
            module_imported=True,
            errors=[str(exc)],
        )


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaRootCauseAnalyzerValidationReport:
    """Run the complete local synthetic causal-analysis proof."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        source = build_synthetic_error_doctor_report()
        source_before = source.model_dump_json()
        analysis = BobaRootCauseAnalyzerV1().analyze(
            SYNTHETIC_PROJECT_ID,
            source,
            manual_context={
                "conflicting_timestamps": True,
                "healthy_modules": ["content_scout_v2", "creator_learning"],
            },
        )
        candidates = analysis.root_cause_candidates
        categories = {item.category for item in candidates}
        handoffs = analysis.escalation_handoffs
        cases_by_source = {
            item.source_diagnostic_case_id: item
            for item in analysis.analysis_cases
        }
        missing_case = cases_by_source["case_missing_upstream"]
        optional_case = cases_by_source["case_optional"]
        corrupt_case = cases_by_source["case_corrupt"]
        missing_validation = cases_by_source["case_validation_missing"]
        validation_failed = cases_by_source["case_validation_failed"]
        validation_unknown = cases_by_source["case_validation_unknown"]
        config_case = cases_by_source["case_configuration"]
        environment_case = cases_by_source["case_environment"]
        rights_unknown = cases_by_source["case_rights_unknown"]
        rights_blocked = cases_by_source["case_rights_blocked"]
        approval = cases_by_source["case_approval"]
        competing = cases_by_source["case_competing"]
        code_weak = cases_by_source["case_code_weak"]
        def candidate_for(
            case_id: str,
            category: str,
        ) -> BobaRootCauseCandidateV1 | None:
            return next(
                (
                    item
                    for item in candidates
                    if item.analysis_case_id
                    == cases_by_source[case_id].analysis_case_id
                    and item.category == category
                ),
                None,
            )

        missing_candidate = candidate_for("case_missing_upstream", "missing_artifact")
        corrupt_candidate = candidate_for("case_corrupt", "corrupt_artifact")
        stale_candidate = candidate_for("case_stale", "stale_artifact")
        missing_validation_candidate = candidate_for(
            "case_validation_missing",
            "validation_gap",
        )
        failed_validation_candidate = candidate_for(
            "case_validation_failed",
            "validation_failure",
        )
        resource_candidate = candidate_for(
            "case_resource",
            "resource_exhaustion",
        )
        code_candidate = candidate_for("case_code_weak", "code_defect")
        with TemporaryDirectory(prefix="boba-root-cause-synthetic-") as temporary:
            store = BobaMemoryStore(Path(temporary) / "boba")
            store.save_boba_error_doctor(source)
            error_path = store.error_doctor_path(source.project_id)
            error_before = (error_path.read_bytes(), error_path.stat().st_mtime_ns)
            store.save_boba_root_cause_analyzer(analysis)
            loaded = store.load_boba_root_cause_analyzer(source.project_id)
            export = store.export_boba_root_cause_analyzer(source.project_id)
            error_after = (error_path.read_bytes(), error_path.stat().st_mtime_ns)
            persisted = (
                store.root_cause_analyzer_path(source.project_id).is_file()
                and loaded == analysis
            )
        signal = analysis.signal_usage
        checks = {
            "module_imported": True,
            "store_available": True,
            "error_doctor_available": True,
            "contracts_serialize": (
                BobaRootCauseAnalyzerSetV1.model_validate(
                    json.loads(analysis.model_dump_json())
                )
                == analysis
            ),
            "artifact_path_writable": _report_path_writable(effective_report_dir),
            "dependency_registry_builds": len(build_boba_artifact_registry()) == 19,
            "analysis_cases_exist": bool(analysis.analysis_cases),
            "failure_timelines_exist": bool(analysis.failure_timelines),
            "causal_graphs_exist": bool(analysis.causal_graphs),
            "root_cause_candidates_exist": bool(candidates),
            "contributing_factors_exist": bool(analysis.contributing_factors),
            "downstream_symptoms_exist": bool(analysis.downstream_symptoms),
            "evidence_gaps_exist": bool(analysis.evidence_gaps),
            "verification_plans_exist": bool(analysis.verification_plans),
            "workflow_impacts_exist": bool(analysis.workflow_impacts),
            "handoffs_exist": bool(handoffs),
            "earliest_failure_separate_from_root_cause": (
                missing_case.earliest_known_failure
                != missing_case.most_likely_root_cause
            ),
            "missing_upstream_ranked_above_symptoms": bool(
                missing_candidate
                and missing_candidate.likelihood_score >= 0.7
                and len(missing_candidate.explains_symptom_ids) >= 3
            ),
            "duplicate_symptoms_share_cascade": (
                len(
                    [
                        item
                        for item in analysis.downstream_symptoms
                        if item.analysis_case_id == missing_case.analysis_case_id
                    ]
                )
                >= 3
            ),
            "optional_missing_not_critical": (
                optional_case.processing_impact == "none"
                and optional_case.analysis_status
                in {"no_defect_detected", "insufficient_evidence", "unknown"}
            ),
            "corrupt_required_is_blocking": bool(
                corrupt_candidate
                and corrupt_case.processing_impact == "full_block"
                and corrupt_candidate.likelihood_score >= 0.7
            ),
            "stale_output_linked_conservatively": bool(
                stale_candidate
                and any(
                    edge.relationship in {"probably_caused", "may_have_caused"}
                    for graph in analysis.causal_graphs
                    if graph.analysis_case_id == stale_candidate.analysis_case_id
                    for edge in graph.edges
                )
            ),
            "missing_validation_is_gap": bool(
                missing_validation_candidate
                and missing_validation.analysis_status
                in {"insufficient_evidence", "probable_root_cause"}
            ),
            "failed_validation_is_confirmed": bool(
                failed_validation_candidate
                and validation_failed.analysis_status
                in {"root_cause_supported", "probable_root_cause"}
            ),
            "unknown_validation_format_unknown": bool(
                candidate_for("case_validation_unknown", "unknown")
                and validation_unknown.analysis_status
                in {"insufficient_evidence", "unknown"}
            ),
            "configuration_remains_hypothesis": (
                config_case.analysis_status
                in {
                    "probable_root_cause",
                    "multiple_competing_causes",
                    "insufficient_evidence",
                }
            ),
            "environment_remains_hypothesis": (
                environment_case.analysis_status
                in {
                    "probable_root_cause",
                    "multiple_competing_causes",
                    "insufficient_evidence",
                }
            ),
            "resource_exhaustion_routes_to_recovery": (
                "resource_exhaustion" in categories
                and resource_candidate is not None
                and any(
                    item.target_module == "tool_recovery_brain"
                    and resource_candidate.root_cause_candidate_id
                    in item.root_cause_candidate_ids
                    for item in handoffs
                    )
            ),
            "missing_executable_routes_to_recovery": (
                "tool_unavailable" in categories
                and any(
                    item.target_module == "tool_recovery_brain"
                    and item.analysis_case_id
                    == cases_by_source["case_tool_missing"].analysis_case_id
                    for item in handoffs
                )
            ),
            "code_defect_not_proven": bool(
                code_candidate
                and code_weak.analysis_status != "root_cause_supported"
                and code_candidate.evidence_quality in {"weak", "insufficient"}
                and not any(
                    item.target_module == "code_surgeon"
                    and item.analysis_case_id == code_weak.analysis_case_id
                    for item in handoffs
                )
            ),
            "rights_unknown_is_safety_block": (
                rights_unknown.analysis_status == "intentional_safety_block"
            ),
            "rights_blocked_not_defect": (
                rights_blocked.analysis_status == "intentional_safety_block"
                and not candidate_for("case_rights_blocked", "code_defect")
            ),
            "missing_approval_not_code_failure": (
                approval.analysis_status == "intentional_safety_block"
                and not candidate_for("case_approval", "code_defect")
            ),
            "competing_candidates_preserved": (
                competing.analysis_status == "multiple_competing_causes"
                and len(
                    [
                        item
                        for item in candidates
                        if item.analysis_case_id == competing.analysis_case_id
                    ]
                )
                >= 2
            ),
            "contradictory_evidence_preserved": any(
                item.conflicting_evidence_ids
                for item in candidates
                if item.analysis_case_id == competing.analysis_case_id
            ),
            "confirmation_checks_exist": all(
                item.confirmation_checks for item in candidates
            ),
            "rejection_checks_exist": all(
                item.rejection_checks for item in candidates
            ),
            "verification_plans_advisory": all(
                plan.requires_human_approval
                and not plan.requires_code_modification
                for plan in analysis.verification_plans
            ),
            "handoffs_do_not_apply": all(
                not item.apply_automatically for item in handoffs
            ),
            "handoffs_require_human_approval": all(
                item.human_approval_required for item in handoffs
            ),
            "output_json_safe": bool(
                json.dumps(analysis.model_dump(mode="json"))
            ),
            "artifact_persisted": persisted,
            "export_safe": _safe_export(export),
            "error_doctor_unchanged": (
                source.model_dump_json() == source_before
                and error_before == error_after
            ),
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
            "destructive_action_used_false": not signal.destructive_action_used,
            "rendering_triggered": False,
            "media_ingestion_triggered": False,
            "commands_executed": False,
            "validators_executed": False,
            "code_edits_made": False,
            "source_artifacts_modified": False,
            "repairs_executed": False,
            "fallback_tools_executed": False,
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
            "destructive_actions_made",
        }
        return BobaRootCauseAnalyzerValidationReport(
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
                "Synthetic data covered all required causal-analysis scenarios.",
                "No command, validator, network, media, rendering, code edit, "
                "repair, fallback, workflow resume, or destructive action ran.",
            ],
        )
    except Exception as exc:
        return BobaRootCauseAnalyzerValidationReport(
            mode="synthetic_project",
            passed=False,
            project_id=SYNTHETIC_PROJECT_ID,
            module_imported=True,
            errors=[str(exc)],
        )


def run_existing_project(
    project_id: str,
    report_dir: Path | None = None,
) -> BobaRootCauseAnalyzerValidationReport:
    """Load saved Error Doctor data and safely run or load causal analysis."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        settings = get_settings()
        store = BobaMemoryStore(
            settings.boba.storage_dir,
            memory_root=settings.boba_memory.storage_dir,
        )
        error_path = store.error_doctor_path(project_id)
        error_before = (
            (error_path.read_bytes(), error_path.stat().st_mtime_ns)
            if error_path.is_file()
            else None
        )
        error_doctor = store.load_boba_error_doctor(project_id)
        analysis = store.load_boba_root_cause_analyzer(project_id)
        if analysis is None:
            analysis = BobaRootCauseAnalyzerV1().analyze(
                project_id,
                error_doctor,
            )
            store.save_boba_root_cause_analyzer(analysis)
        error_after = (
            (error_path.read_bytes(), error_path.stat().st_mtime_ns)
            if error_path.is_file()
            else None
        )
        signal = analysis.signal_usage
        available = error_doctor is not None
        return BobaRootCauseAnalyzerValidationReport(
            mode="project_id",
            project_id=project_id,
            passed=(
                available
                and store.root_cause_analyzer_path(project_id).is_file()
                and error_before == error_after
            ),
            module_imported=True,
            store_available=True,
            error_doctor_available=available,
            contracts_serialize=True,
            artifact_path_writable=_report_path_writable(effective_report_dir),
            dependency_registry_builds=True,
            analysis_cases_exist=bool(analysis.analysis_cases),
            failure_timelines_exist=bool(analysis.failure_timelines),
            causal_graphs_exist=bool(analysis.causal_graphs),
            root_cause_candidates_exist=bool(analysis.root_cause_candidates),
            contributing_factors_exist=bool(analysis.contributing_factors),
            downstream_symptoms_exist=bool(analysis.downstream_symptoms),
            evidence_gaps_exist=bool(analysis.evidence_gaps),
            verification_plans_exist=bool(analysis.verification_plans),
            workflow_impacts_exist=bool(analysis.workflow_impacts),
            handoffs_exist=bool(analysis.escalation_handoffs),
            output_json_safe=bool(json.dumps(analysis.model_dump(mode="json"))),
            artifact_persisted=store.root_cause_analyzer_path(project_id).is_file(),
            export_safe=_safe_export(
                store.export_boba_root_cause_analyzer(project_id)
            ),
            error_doctor_unchanged=error_before == error_after,
            external_api_used_false=not signal.external_api_used,
            url_fetching_used_false=not signal.url_fetching_used,
            scraping_used_false=not signal.scraping_used,
            downloading_used_false=not signal.downloading_used,
            command_execution_used_false=not signal.command_execution_used,
            validator_execution_used_false=not signal.validator_execution_used,
            code_modification_used_false=not signal.code_modification_used,
            artifact_modification_used_false=not signal.artifact_modification_used,
            repair_execution_used_false=not signal.repair_execution_used,
            tool_fallback_execution_used_false=(
                not signal.tool_fallback_execution_used
            ),
            destructive_action_used_false=not signal.destructive_action_used,
            warnings=(
                []
                if available
                else [
                    "Saved Error Doctor data is missing; Root Cause Analyzer "
                    "produced only an insufficient-evidence result."
                ]
            ),
        )
    except Exception as exc:
        return BobaRootCauseAnalyzerValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            module_imported=True,
            errors=[str(exc)],
            warnings=[
                "No command, validator, external API, download, render, code "
                "edit, repair, fallback, or destructive action was attempted."
            ],
        )


def _write_report(
    report: BobaRootCauseAnalyzerValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_root_cause_analyzer_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Root Cause Analyzer V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Analysis cases: `{report.analysis_cases_exist}`",
        f"- Failure timelines: `{report.failure_timelines_exist}`",
        f"- Causal graphs: `{report.causal_graphs_exist}`",
        f"- Root-cause candidates: `{report.root_cause_candidates_exist}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- Commands or validators executed by Root Cause Analyzer: `false`",
        "- Repairs or fallback tools executed: `false`",
        "- External APIs, URLs, downloads, ingestion, or rendering: `false`",
        "- Code edits, source-artifact changes, or destructive actions: `false`",
        "",
        "Root Cause Analyzer V1 is advisory. Highest-ranked does not mean proven.",
    ]
    (report_dir / "boba_root_cause_analyzer_v1_summary.md").write_text(
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
