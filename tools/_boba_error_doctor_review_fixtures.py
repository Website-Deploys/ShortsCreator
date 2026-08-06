"""Synthetic canonical BOBA reliability records built through the real contracts.

Shared by the Error Doctor Review validator and its unit tests so both exercise
genuine module contracts rather than hand-written dictionaries.
"""

from __future__ import annotations

from typing import Any

from olympus.boba.error_doctor import (
    BobaDiagnosticCaseV1,
    BobaDiagnosticEvidenceV1,
    BobaDiagnosticHypothesisV1,
    BobaErrorDoctorSetV1,
    BobaErrorDoctorSignalUsageV1,
    BobaErrorDoctorSummaryV1,
)
from olympus.boba.store import BobaMemoryStore


def synthetic_evidence(
    evidence_id: str,
    *,
    summary: str = "The renderer exited before writing the output file.",
    observed: str = "exit_code=1",
    timestamp: str = "2026-02-01T10:00:00+00:00",
) -> BobaDiagnosticEvidenceV1:
    return BobaDiagnosticEvidenceV1(
        evidence_id=evidence_id,
        source_type="artifact_observation",
        source_id="observer_report",
        module_name="rendering",
        artifact_id="render_manifest",
        evidence_summary=summary,
        observed_value=observed,
        expected_value="exit_code=0",
        timestamp=timestamp,
        confidence=0.82,
        usage_warning="Evidence is bounded to what Observer recorded.",
    )


def synthetic_hypothesis(hypothesis_id: str) -> BobaDiagnosticHypothesisV1:
    return BobaDiagnosticHypothesisV1(
        hypothesis_id=hypothesis_id,
        hypothesis="The external encoder rejected the requested pixel format.",
        category="direct_cause",
        supporting_evidence_ids=["evidence_a"],
        conflicting_evidence_ids=[],
        confidence=0.61,
        verification_needed=True,
        suggested_check="Re-run the encoder health check for this capability.",
        warnings=["This is a hypothesis, not a confirmed cause."],
    )


def synthetic_case(
    incident_id: str,
    *,
    title: str = "Rendering stage failed before writing output",
    primary_module: str = "rendering",
    workflow_stage: str = "render",
    error_category: str = "rendering",
    severity: str = "high",
    diagnosis_status: str = "probable",
    processing_impact: str = "full_block",
    safety_impact: str = "none_known",
    with_hypotheses: bool = True,
    with_evidence: bool = True,
    confirmed_facts: list[str] | None = None,
    finding_ids: list[str] | None = None,
    affected_artifacts: list[str] | None = None,
    warnings: list[str] | None = None,
) -> BobaDiagnosticCaseV1:
    return BobaDiagnosticCaseV1(
        diagnostic_case_id=incident_id,
        title=title,
        primary_module=primary_module,
        primary_artifact="render_manifest",
        workflow_stage=workflow_stage,
        error_category=error_category,
        severity=severity,
        urgency="soon",
        diagnosis_status=diagnosis_status,
        symptom_summary="The render stage stopped and no output artifact appeared.",
        probable_cause_summary=(
            "Observer recorded a missing output artifact after the encoder exited."
        ),
        confirmed_facts=confirmed_facts
        if confirmed_facts is not None
        else ["The expected output artifact does not exist."],
        hypotheses=[synthetic_hypothesis("hypothesis_a")] if with_hypotheses else [],
        affected_modules=[primary_module],
        affected_artifacts=affected_artifacts
        if affected_artifacts is not None
        else ["render_manifest"],
        related_finding_ids=finding_ids if finding_ids is not None else ["finding_a"],
        evidence=[synthetic_evidence("evidence_a")] if with_evidence else [],
        missing_information=["The encoder stderr output was not retained."],
        processing_impact=processing_impact,
        safety_impact=safety_impact,
        recommended_investigation=["Check the encoder health for this capability."],
        escalation_target="root_cause_analyzer",
        confidence=0.74,
        warnings=warnings or [],
        limitations=["Diagnosis is bounded by the evidence Observer retained."],
    )


def synthetic_error_doctor_set(
    project_id: str, cases: list[BobaDiagnosticCaseV1]
) -> BobaErrorDoctorSetV1:
    return BobaErrorDoctorSetV1(
        project_id=project_id,
        source_id="synthetic_source",
        observer_source="observer_report",
        diagnostic_cases=cases,
        doctor_summary=BobaErrorDoctorSummaryV1(
            total_diagnostic_cases=len(cases),
            blocked_workflow_count=sum(
                1 for item in cases if item.processing_impact == "full_block"
            ),
        ),
        signal_usage=BobaErrorDoctorSignalUsageV1(observer_used=True),
    )


def seed_project(
    store: BobaMemoryStore,
    project_id: str,
    *,
    with_incidents: bool = True,
    cases: list[BobaDiagnosticCaseV1] | None = None,
) -> dict[str, Any]:
    """Persist canonical Error Doctor records for a synthetic review project."""
    rows = (
        cases
        if cases is not None
        else [
            synthetic_case("case_a"),
            synthetic_case(
                "case_b",
                title="Validation evidence is missing for the accepted output",
                primary_module="validation",
                workflow_stage="validate",
                error_category="validation_missing",
                severity="medium",
                diagnosis_status="insufficient_evidence",
                processing_impact="degraded",
                finding_ids=["finding_b"],
                affected_artifacts=["validation_report"],
            ),
        ]
    )
    if with_incidents:
        store.save_boba_error_doctor(synthetic_error_doctor_set(project_id, rows))
    return {"incident_ids": [item.diagnostic_case_id for item in rows]}
