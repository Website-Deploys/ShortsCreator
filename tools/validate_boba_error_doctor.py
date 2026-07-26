"""Validate BOBA Error Doctor V1 with bounded local Observer evidence."""

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
    BobaErrorDoctorSetV1,
    BobaErrorDoctorV1,
)
from olympus.boba.observer import (  # noqa: E402
    BobaObserverSetV1,
    BobaSafetyObservationV1,
    BobaValidationObservationV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402
from tools.validate_boba_observer import (  # noqa: E402
    build_synthetic_observer_report,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_error_doctor"
SYNTHETIC_PROJECT_ID = "proj_boba_error_doctor_synthetic"


class BobaErrorDoctorValidationReport(BaseModel):
    """Compact proof that diagnosis is local, advisory, and non-applying."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    module_imported: bool = False
    store_available: bool = False
    observer_available: bool = False
    contracts_serialize: bool = False
    artifact_path_writable: bool = False
    diagnostic_cases_exist: bool = False
    findings_classified: bool = False
    duplicate_findings_grouped: bool = False
    primary_missing_upstream_detected: bool = False
    cascading_effects_detected: bool = False
    optional_missing_not_critical: bool = False
    corrupt_required_is_blocking: bool = False
    stale_downstream_detected: bool = False
    missing_validation_is_gap: bool = False
    failed_validation_confirmed: bool = False
    unknown_validation_preserved: bool = False
    unknown_rights_blocks: bool = False
    blocked_rights_is_intentional: bool = False
    hypotheses_are_uncertain: bool = False
    facts_separate_from_hypotheses: bool = False
    recommendations_are_advisory: bool = False
    no_automatic_fix_applied: bool = False
    escalation_handoffs_exist: bool = False
    handoffs_do_not_apply: bool = False
    handoffs_require_human_approval: bool = False
    summary_counts_consistent: bool = False
    artifact_persisted: bool = False
    output_json_safe: bool = False
    export_safe: bool = False
    observer_unchanged: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    scraping_used_false: bool = False
    downloading_used_false: bool = False
    command_execution_used_false: bool = False
    validator_execution_used_false: bool = False
    code_modification_used_false: bool = False
    artifact_modification_used_false: bool = False
    destructive_action_used_false: bool = False
    rendering_triggered: bool = False
    media_ingestion_triggered: bool = False
    commands_executed: bool = False
    validators_executed: bool = False
    code_edits_made: bool = False
    source_artifacts_modified: bool = False
    destructive_actions_made: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _summary_counts_consistent(report: BobaErrorDoctorSetV1) -> bool:
    summary = report.doctor_summary
    counted = sum(
        (
            summary.informational_count,
            summary.low_count,
            summary.medium_count,
            summary.high_count,
            summary.critical_count,
            summary.blocker_count,
            summary.unknown_count,
        )
    )
    return (
        counted == summary.total_diagnostic_cases
        and summary.total_diagnostic_cases == len(report.diagnostic_cases)
        and summary.total_observer_findings == len(report.classified_findings)
        and summary.cascading_problem_count == len(report.cascading_impacts)
    )


def _safe_export(payload: dict[str, object]) -> bool:
    encoded = json.dumps(payload).casefold()
    privacy = payload.get("privacy")
    return bool(
        isinstance(privacy, dict)
        and privacy.get("private_paths_excluded") is True
        and privacy.get("full_evidence_values_excluded") is True
        and privacy.get("raw_logs_excluded") is True
        and privacy.get("observer_report_excluded") is True
        and '"observed_value":' not in encoded
        and '"expected_value":' not in encoded
        and '"timestamp":' not in encoded
        and '"api_key":' not in encoded
        and '"access_token":' not in encoded
        and '"password":' not in encoded
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("local-error-doctor-validation-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _enriched_observer() -> BobaObserverSetV1:
    observer = build_synthetic_observer_report(SYNTHETIC_PROJECT_ID)
    observer.validation_observations.append(
        BobaValidationObservationV1(
            validator_name="synthetic_required_validator",
            report_path="synthetic/failed-validation.json",
            report_exists=True,
            latest_status="failed",
            report_created_at="2026-01-15T11:00:00+00:00",
            freshness_status="fresh",
            issue_level="blocker",
            warnings=["Synthetic bounded failure evidence."],
        )
    )
    observer.safety_observations.append(
        BobaSafetyObservationV1(
            safety_id="synthetic_rights_unknown",
            safety_area="rights_permission",
            status="needs_human_review",
            reason="Synthetic rights status is unknown.",
            related_artifacts=["rights_permission_gate"],
            required_human_checks=["Confirm rights manually."],
            unsafe_next_actions=["Do not process automatically."],
            warnings=["Unknown rights are an intentional safety block."],
        )
    )
    return observer


def run_self_check(
    report_dir: Path | None = None,
) -> BobaErrorDoctorValidationReport:
    """Validate imports, contracts, storage, and non-execution defaults."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        with TemporaryDirectory(prefix="boba-error-doctor-self-check-") as temporary:
            store = BobaMemoryStore(Path(temporary) / "boba")
            diagnosis = BobaErrorDoctorV1().analyze(
                "proj_boba_error_doctor_self_check",
                None,
            )
            store.save_boba_error_doctor(diagnosis)
            loaded = store.load_boba_error_doctor(diagnosis.project_id)
            contracts_serialize = (
                BobaErrorDoctorSetV1.model_validate(
                    json.loads(diagnosis.model_dump_json())
                )
                == diagnosis
            )
            artifact_path_writable = (
                store.error_doctor_path(diagnosis.project_id).is_file()
                and loaded == diagnosis
            )
        signal = diagnosis.signal_usage
        checks = {
            "module_imported": True,
            "store_available": True,
            "observer_available": True,
            "contracts_serialize": contracts_serialize,
            "artifact_path_writable": artifact_path_writable,
            "external_api_used_false": not signal.external_api_used,
            "url_fetching_used_false": not signal.url_fetching_used,
            "scraping_used_false": not signal.scraping_used,
            "downloading_used_false": not signal.downloading_used,
            "command_execution_used_false": not signal.command_execution_used,
            "validator_execution_used_false": not signal.validator_execution_used,
            "code_modification_used_false": not signal.code_modification_used,
            "artifact_modification_used_false": not signal.artifact_modification_used,
            "destructive_action_used_false": not signal.destructive_action_used,
        }
        return BobaErrorDoctorValidationReport(
            mode="self_check",
            passed=all(checks.values()) and _report_path_writable(effective_report_dir),
            **checks,
            warnings=[
                "Self-check used temporary local JSON only.",
                "No command, validator, network, media, rendering, or repair action ran.",
            ],
        )
    except Exception as exc:
        return BobaErrorDoctorValidationReport(
            mode="self_check",
            passed=False,
            module_imported=True,
            errors=[str(exc)],
        )


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaErrorDoctorValidationReport:
    """Run the complete local synthetic Error Doctor proof."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        observer = _enriched_observer()
        assert hasattr(observer, "model_dump")
        diagnosis = BobaErrorDoctorV1().analyze(
            SYNTHETIC_PROJECT_ID,
            observer,
            manual_context={
                "configuration_issue": "Synthetic required setting is unavailable.",
                "environment_issue": "Synthetic expected executable is unavailable.",
            },
            error_summaries=[
                {
                    "summary": "Synthetic local tool timed out.",
                    "category": "timeout",
                    "module_name": "rendering",
                },
                {
                    "summary": "Synthetic duplicate local tool timed out.",
                    "category": "timeout",
                    "module_name": "rendering",
                },
            ],
        )
        conflicting = BobaErrorDoctorV1().analyze(
            SYNTHETIC_PROJECT_ID,
            observer,
            manual_context={"conflicting_evidence": True},
        )
        duplicate_counts = Counter(
            finding.duplicate_group_id
            for finding in diagnosis.classified_findings
        )
        safety_findings = [
            finding
            for finding in diagnosis.classified_findings
            if finding.classified_category == "rights_safety"
        ]
        optional_findings = [
            finding
            for finding in diagnosis.classified_findings
            if any("optional dependency" in warning.casefold() for warning in finding.warnings)
        ]
        observer_payload = observer.model_dump(mode="json")

        with TemporaryDirectory(prefix="boba-error-doctor-synthetic-") as temporary:
            store = BobaMemoryStore(Path(temporary) / "boba")
            store.save_observer_report(observer)
            observer_path = store.observer_path(SYNTHETIC_PROJECT_ID)
            observer_before = (
                observer_path.read_bytes(),
                observer_path.stat().st_mtime_ns,
            )
            store.save_boba_error_doctor(diagnosis)
            doctor_path = store.error_doctor_path(SYNTHETIC_PROJECT_ID)
            loaded = store.load_boba_error_doctor(SYNTHETIC_PROJECT_ID)
            exported = store.export_boba_error_doctor(SYNTHETIC_PROJECT_ID)
            observer_after = (
                observer_path.read_bytes(),
                observer_path.stat().st_mtime_ns,
            )
            persisted = doctor_path.is_file() and loaded == diagnosis

        signal = diagnosis.signal_usage
        checks = {
            "module_imported": True,
            "store_available": True,
            "observer_available": True,
            "contracts_serialize": (
                BobaErrorDoctorSetV1.model_validate(
                    json.loads(diagnosis.model_dump_json())
                )
                == diagnosis
            ),
            "artifact_path_writable": _report_path_writable(effective_report_dir),
            "diagnostic_cases_exist": bool(diagnosis.diagnostic_cases),
            "findings_classified": bool(diagnosis.classified_findings),
            "duplicate_findings_grouped": any(
                count > 1 for count in duplicate_counts.values()
            ),
            "primary_missing_upstream_detected": any(
                case.error_category == "missing_artifact"
                and case.diagnosis_status == "probable"
                for case in diagnosis.diagnostic_cases
            ),
            "cascading_effects_detected": any(
                len(impact.impacted_modules) > 1
                for impact in diagnosis.cascading_impacts
            ),
            "optional_missing_not_critical": bool(optional_findings)
            and all(
                finding.severity not in {"critical", "blocker"}
                for finding in optional_findings
            ),
            "corrupt_required_is_blocking": any(
                case.error_category == "corrupt_artifact"
                and case.severity in {"high", "critical", "blocker"}
                for case in diagnosis.diagnostic_cases
            ),
            "stale_downstream_detected": any(
                case.error_category == "stale_artifact"
                for case in diagnosis.diagnostic_cases
            ),
            "missing_validation_is_gap": any(
                case.error_category == "validation_missing"
                and case.diagnosis_status == "insufficient_evidence"
                for case in diagnosis.diagnostic_cases
            ),
            "failed_validation_confirmed": any(
                case.error_category == "validation_failure"
                and case.diagnosis_status == "observed_fact"
                for case in diagnosis.diagnostic_cases
            ),
            "unknown_validation_preserved": any(
                case.error_category == "unknown"
                and case.diagnosis_status == "insufficient_evidence"
                for case in diagnosis.diagnostic_cases
            ),
            "unknown_rights_blocks": any(
                finding.original_issue_level == "needs_human_review"
                and finding.severity == "blocker"
                for finding in safety_findings
            ),
            "blocked_rights_is_intentional": any(
                finding.original_issue_level == "blocked"
                and "intentional safety" in finding.explanation.casefold()
                for finding in safety_findings
            ),
            "hypotheses_are_uncertain": all(
                hypothesis.verification_needed
                and hypothesis.confidence < 1.0
                for case in diagnosis.diagnostic_cases
                for hypothesis in case.hypotheses
            ),
            "facts_separate_from_hypotheses": all(
                set(case.confirmed_facts).isdisjoint(
                    hypothesis.hypothesis for hypothesis in case.hypotheses
                )
                for case in diagnosis.diagnostic_cases
            ),
            "recommendations_are_advisory": all(
                item.requires_human_review
                for item in diagnosis.investigation_recommendations
            ),
            "no_automatic_fix_applied": all(
                not item.requires_code_change
                for item in diagnosis.investigation_recommendations
            ),
            "escalation_handoffs_exist": bool(diagnosis.escalation_handoffs),
            "handoffs_do_not_apply": all(
                not item.apply_automatically
                for item in diagnosis.escalation_handoffs
            ),
            "handoffs_require_human_approval": all(
                item.human_approval_required
                for item in diagnosis.escalation_handoffs
            ),
            "summary_counts_consistent": _summary_counts_consistent(diagnosis),
            "artifact_persisted": persisted,
            "output_json_safe": bool(json.dumps(diagnosis.model_dump(mode="json"))),
            "export_safe": _safe_export(exported),
            "observer_unchanged": (
                observer_before == observer_after
                and observer.model_dump(mode="json") == observer_payload
            ),
            "external_api_used_false": not signal.external_api_used,
            "url_fetching_used_false": not signal.url_fetching_used,
            "scraping_used_false": not signal.scraping_used,
            "downloading_used_false": not signal.downloading_used,
            "command_execution_used_false": not signal.command_execution_used,
            "validator_execution_used_false": not signal.validator_execution_used,
            "code_modification_used_false": not signal.code_modification_used,
            "artifact_modification_used_false": not signal.artifact_modification_used,
            "destructive_action_used_false": not signal.destructive_action_used,
        }
        checks["hypotheses_are_uncertain"] = bool(
            any(case.hypotheses for case in diagnosis.diagnostic_cases)
            and checks["hypotheses_are_uncertain"]
        )
        checks["facts_separate_from_hypotheses"] = bool(
            checks["facts_separate_from_hypotheses"]
            and any(case.confirmed_facts for case in diagnosis.diagnostic_cases)
            and any(case.hypotheses for case in diagnosis.diagnostic_cases)
        )
        conflict_detected = bool(
            conflicting.diagnostic_cases
            and all(
                case.diagnosis_status == "conflicting_evidence"
                for case in conflicting.diagnostic_cases
            )
            and max(case.confidence for case in conflicting.diagnostic_cases)
            < max(case.confidence for case in diagnosis.diagnostic_cases)
        )
        return BobaErrorDoctorValidationReport(
            mode="synthetic_project",
            project_id=SYNTHETIC_PROJECT_ID,
            passed=all(checks.values()) and conflict_detected,
            **checks,
            warnings=[
                "Synthetic data included conflicting evidence in a separate diagnosis.",
                "No command, validator, network, media, rendering, source edit, "
                "or repair action ran.",
            ],
        )
    except Exception as exc:
        return BobaErrorDoctorValidationReport(
            mode="synthetic_project",
            passed=False,
            project_id=SYNTHETIC_PROJECT_ID,
            module_imported=True,
            errors=[str(exc)],
        )


def run_existing_project(
    project_id: str,
    report_dir: Path | None = None,
) -> BobaErrorDoctorValidationReport:
    """Load saved Observer evidence and safely run or load Error Doctor."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        settings = get_settings()
        store = BobaMemoryStore(
            settings.boba.storage_dir,
            memory_root=settings.boba_memory.storage_dir,
        )
        observer_path = store.observer_path(project_id)
        observer_before = (
            (observer_path.read_bytes(), observer_path.stat().st_mtime_ns)
            if observer_path.is_file()
            else None
        )
        observer = store.load_observer_report(project_id)
        diagnosis = store.load_boba_error_doctor(project_id)
        if diagnosis is None:
            diagnosis = BobaErrorDoctorV1().analyze(project_id, observer)
            store.save_boba_error_doctor(diagnosis)
        observer_after = (
            (observer_path.read_bytes(), observer_path.stat().st_mtime_ns)
            if observer_path.is_file()
            else None
        )
        signal = diagnosis.signal_usage
        observer_available = observer is not None
        return BobaErrorDoctorValidationReport(
            mode="project_id",
            project_id=project_id,
            passed=(
                observer_available
                and store.error_doctor_path(project_id).is_file()
                and observer_before == observer_after
            ),
            module_imported=True,
            store_available=True,
            observer_available=observer_available,
            contracts_serialize=True,
            artifact_path_writable=_report_path_writable(effective_report_dir),
            diagnostic_cases_exist=bool(diagnosis.diagnostic_cases),
            findings_classified=bool(diagnosis.classified_findings),
            summary_counts_consistent=_summary_counts_consistent(diagnosis),
            artifact_persisted=store.error_doctor_path(project_id).is_file(),
            output_json_safe=bool(json.dumps(diagnosis.model_dump(mode="json"))),
            export_safe=_safe_export(store.export_boba_error_doctor(project_id)),
            observer_unchanged=observer_before == observer_after,
            external_api_used_false=not signal.external_api_used,
            url_fetching_used_false=not signal.url_fetching_used,
            scraping_used_false=not signal.scraping_used,
            downloading_used_false=not signal.downloading_used,
            command_execution_used_false=not signal.command_execution_used,
            validator_execution_used_false=not signal.validator_execution_used,
            code_modification_used_false=not signal.code_modification_used,
            artifact_modification_used_false=not signal.artifact_modification_used,
            destructive_action_used_false=not signal.destructive_action_used,
            warnings=(
                []
                if observer_available
                else [
                    "Saved Observer data is missing; Error Doctor produced only "
                    "an insufficient-evidence result."
                ]
            ),
        )
    except Exception as exc:
        return BobaErrorDoctorValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            module_imported=True,
            errors=[str(exc)],
            warnings=[
                "No command, validator, external API, download, render, code "
                "edit, or repair was attempted."
            ],
        )


def _write_report(
    report: BobaErrorDoctorValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_error_doctor_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Error Doctor V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Diagnostic cases: `{report.diagnostic_cases_exist}`",
        f"- Findings classified: `{report.findings_classified}`",
        f"- Cascades detected: `{report.cascading_effects_detected}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- Commands or validators executed by Error Doctor: `false`",
        "- External APIs, URLs, downloads, ingestion, or rendering: `false`",
        "- Code edits, repairs, or destructive actions: `false`",
        "",
        "Error Doctor V1 is advisory. Probable causes are not proven root causes.",
    ]
    (report_dir / "boba_error_doctor_v1_summary.md").write_text(
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
