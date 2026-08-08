"""Synthetic owner records for BOBA Validation + Reports V1 validation.

Everything here is fabricated in a temporary directory. No real project, real
media, real validator process or real report file is touched, and nothing is
executed. The fixtures exist so the projection can be exercised against owner
records that are genuinely valid according to the owners' own contracts.
"""

from __future__ import annotations

import hashlib
from typing import Any

from olympus.boba.report_reader import (
    BobaReportContradictionV1,
    BobaReportDocumentV1,
    BobaReportEvidenceReferenceV1,
    BobaReportFindingV1,
    BobaReportReaderSetV1,
    BobaReportReadRunV1,
    BobaReportReferenceV1,
    BobaReportSectionV1,
)
from olympus.boba.validator_runner import (
    BobaValidationCheckRunV1,
    BobaValidationEvidenceV1,
    BobaValidationInputBindingV1,
    BobaValidationResultV1,
    BobaValidationRunV1,
    BobaValidationSuiteDecisionV1,
    BobaValidatorDescriptorV1,
    BobaValidatorRunnerSetV1,
)

PROJECT_ID = "validation-reports-fixture"
RUN_ID = "vrun-1"
PLAN_ID = "vplan-1"
WORKFLOW_RUN_ID = "wfrun-1"
STAGE_ID = "stage-1"


def digest(seed: str) -> str:
    """Return a deterministic lowercase SHA-256 digest for a fixture seed."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _descriptor(validator_id: str, *, version: str = "1") -> BobaValidatorDescriptorV1:
    return BobaValidatorDescriptorV1(
        validator_id=validator_id,
        display_name=f"Fixture {validator_id}",
        validator_version=version,
        category="contract_schema",
        implementation_type="internal_python",
        adapter_id=f"adapter-{validator_id}",
        output_schema_id="schema-out-1",
        availability_status="available",
        health_status="healthy",
    )


def _check(
    check_run_id: str,
    validator_id: str,
    status: str,
    *,
    plan_check_id: str = "",
    version: str = "1",
    required: bool = True,
    attempt: int = 1,
    input_seed: str = "input",
    failure_summary: str = "",
) -> BobaValidationCheckRunV1:
    return BobaValidationCheckRunV1(
        check_run_id=check_run_id,
        validation_run_id=RUN_ID,
        plan_check_id=plan_check_id or f"pcheck-{validator_id}",
        validator_id=validator_id,
        validator_version=version,
        category="contract_schema",
        required=required,
        attempt_number=attempt,
        status=status,  # type: ignore[arg-type]
        adapter_id=f"adapter-{validator_id}",
        input_digest=digest(input_seed),
        environment_digest=digest("env"),
        started_at="2026-08-01T00:00:10+00:00",
        completed_at="2026-08-01T00:00:20+00:00",
        duration_seconds=10.0,
        timeout_seconds=60,
        failure_summary=failure_summary,
    )


def _result(
    result_id: str,
    check_run_id: str,
    validator_id: str,
    status: str,
    *,
    failed: list[str] | None = None,
) -> BobaValidationResultV1:
    return BobaValidationResultV1(
        result_id=result_id,
        validation_run_id=RUN_ID,
        check_run_id=check_run_id,
        validator_id=validator_id,
        status=status,  # type: ignore[arg-type]
        failed_assertions=failed or [],
        result_digest=digest(result_id),
    )


def _evidence(
    evidence_id: str,
    check_run_id: str,
    validator_id: str,
    *,
    supports_pass: bool = False,
    supports_failure: bool = False,
) -> BobaValidationEvidenceV1:
    return BobaValidationEvidenceV1(
        evidence_id=evidence_id,
        validation_run_id=RUN_ID,
        check_run_id=check_run_id,
        source_type="internal_validator",
        validator_id=validator_id,
        category="contract_schema",
        bounded_summary=f"Fixture evidence for {check_run_id}.",
        evidence_digest=digest(evidence_id),
        reliability="high",
        confidence=0.9,
        supports_pass=supports_pass,
        supports_failure=supports_failure,
    )


def build_validator_runner(
    *,
    checks: list[BobaValidationCheckRunV1] | None = None,
    results: list[BobaValidationResultV1] | None = None,
    evidence: list[BobaValidationEvidenceV1] | None = None,
    suite_decisions: list[BobaValidationSuiteDecisionV1] | None = None,
    descriptors: list[BobaValidatorDescriptorV1] | None = None,
    project_id: str = PROJECT_ID,
    workflow_run_id: str = WORKFLOW_RUN_ID,
    stage_instance_id: str = STAGE_ID,
    target_digest_unchanged: bool = True,
    project_snapshot_current: bool = True,
    include_run: bool = True,
) -> BobaValidatorRunnerSetV1:
    """Build a valid Validator Runner record set for the fixture project."""
    run = BobaValidationRunV1(
        validation_run_id=RUN_ID,
        validation_plan_id=PLAN_ID,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        stage_instance_id=stage_instance_id,
        target_type="generated_output",
        target_id="output-1",
        target_digest=digest("target"),
        registry_snapshot_id="vreg-1",
        environment_snapshot_id="venv-1",
        execution_policy_id="vpol-1",
        resource_budget_id="vbud-1",
        correlation_id="vcorr-1",
        run_status="completed",
        idempotency_key="videm-1",
        started_at="2026-08-01T00:00:00+00:00",
        completed_at="2026-08-01T00:01:00+00:00",
    )
    decision = BobaValidationSuiteDecisionV1(
        suite_decision_id="vdec-1",
        validation_run_id=RUN_ID,
        validation_plan_id=PLAN_ID,
        decision="passed",
        decision_summary="Fixture suite decision.",
        required_checks_complete=True,
        required_checks_passed=True,
        evidence_complete=True,
        target_digest_unchanged=target_digest_unchanged,
        environment_digest_unchanged=True,
        project_snapshot_current=project_snapshot_current,
        technical_validation_passed=True,
        acceptance_criteria_met=True,
    )
    binding = BobaValidationInputBindingV1(
        input_binding_id="vbind-1",
        validation_plan_id=PLAN_ID,
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        artifact_type="rendered_output",
        artifact_digest=digest("artifact"),
        sanitized_storage_reference=f"projects/{project_id}/outputs/output-1.json",
    )
    return BobaValidatorRunnerSetV1(
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        validator_descriptors=descriptors if descriptors is not None else [_descriptor("v-schema")],
        validation_runs=[run] if include_run else [],
        check_runs=checks or [],
        validation_results=results or [],
        evidence_records=evidence or [],
        input_bindings=[binding],
        suite_decisions=suite_decisions if suite_decisions is not None else [decision],
    )


def passing_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    """One required check that genuinely passed, with supporting evidence."""
    return build_validator_runner(
        project_id=project_id,
        checks=[_check("vcheck-1", "v-schema", "passed")],
        results=[_result("vres-1", "vcheck-1", "v-schema", "passed")],
        evidence=[_evidence("vev-1", "vcheck-1", "v-schema", supports_pass=True)],
    )


def mixed_state_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    """One check per distinguishable matrix state, so none may be collapsed."""
    checks = [
        _check("vcheck-pass", "v-schema", "passed"),
        _check("vcheck-fail", "v-fail", "failed", failure_summary="Fixture failure."),
        _check("vcheck-blocked", "v-blocked", "blocked"),
        _check("vcheck-depblocked", "v-dep", "dependency_blocked"),
        _check("vcheck-skipped", "v-skip", "skipped_not_required", required=False),
        _check("vcheck-notrun", "v-pending", "pending"),
        _check("vcheck-missing", "v-unavail", "unavailable"),
        _check("vcheck-errored", "v-error", "errored"),
        _check("vcheck-timeout", "v-timeout", "timed_out"),
        _check("vcheck-superseded", "v-super", "superseded"),
    ]
    descriptors = [
        _descriptor(item.validator_id) for item in checks
    ]
    return build_validator_runner(
        project_id=project_id,
        descriptors=descriptors,
        checks=checks,
        results=[
            _result("vres-pass", "vcheck-pass", "v-schema", "passed"),
            _result("vres-fail", "vcheck-fail", "v-fail", "failed", failed=["assert_schema"]),
        ],
        evidence=[
            _evidence("vev-pass", "vcheck-pass", "v-schema", supports_pass=True),
            _evidence("vev-fail", "vcheck-fail", "v-fail", supports_failure=True),
        ],
    )


def pass_without_evidence_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    """A recorded pass with no evidence record. Must never present as PASS."""
    return build_validator_runner(
        project_id=project_id,
        checks=[_check("vcheck-1", "v-schema", "passed")],
        results=[_result("vres-1", "vcheck-1", "v-schema", "passed")],
        evidence=[],
    )


def contradictory_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    """Two attempts at one plan check disagreeing, plus a result disagreement."""
    return build_validator_runner(
        project_id=project_id,
        descriptors=[_descriptor("v-schema")],
        checks=[
            _check("vcheck-a", "v-schema", "passed", plan_check_id="pcheck-shared", attempt=1),
            _check(
                "vcheck-b",
                "v-schema",
                "failed",
                plan_check_id="pcheck-shared",
                attempt=2,
                input_seed="input-b",
            ),
        ],
        results=[
            _result("vres-a", "vcheck-a", "v-schema", "passed"),
            _result("vres-b", "vcheck-b", "v-schema", "passed"),
        ],
        evidence=[
            _evidence("vev-a", "vcheck-a", "v-schema", supports_pass=True),
            _evidence("vev-b", "vcheck-b", "v-schema", supports_failure=True),
        ],
    )


def version_drift_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    """A verdict produced by an older validator version than the registered one."""
    return build_validator_runner(
        project_id=project_id,
        descriptors=[_descriptor("v-schema", version="2")],
        checks=[_check("vcheck-1", "v-schema", "passed", version="1")],
        results=[_result("vres-1", "vcheck-1", "v-schema", "passed")],
        evidence=[_evidence("vev-1", "vcheck-1", "v-schema", supports_pass=True)],
    )


def stale_target_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    """The owner itself reports the bound target digest changed."""
    return build_validator_runner(
        project_id=project_id,
        checks=[_check("vcheck-1", "v-schema", "passed")],
        results=[_result("vres-1", "vcheck-1", "v-schema", "passed")],
        evidence=[_evidence("vev-1", "vcheck-1", "v-schema", supports_pass=True)],
        target_digest_unchanged=False,
    )


def duplicate_suite_decision_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    """Two suite decisions for one run. Neither may be chosen automatically."""
    first = BobaValidationSuiteDecisionV1(
        suite_decision_id="vdec-1",
        validation_run_id=RUN_ID,
        validation_plan_id=PLAN_ID,
        decision="passed",
        decision_summary="First fixture decision.",
    )
    second = first.model_copy(
        update={
            "suite_decision_id": "vdec-2",
            "decision": "failed",
            "decision_summary": "Second fixture decision.",
        }
    )
    return build_validator_runner(
        project_id=project_id,
        checks=[_check("vcheck-1", "v-schema", "passed")],
        results=[_result("vres-1", "vcheck-1", "v-schema", "passed")],
        evidence=[_evidence("vev-1", "vcheck-1", "v-schema", supports_pass=True)],
        suite_decisions=[first, second],
    )


def empty_runner(project_id: str = PROJECT_ID) -> BobaValidatorRunnerSetV1:
    return build_validator_runner(project_id=project_id, include_run=False)


# ----------------------------------------------------------------------
# Report Reader fixtures
# ----------------------------------------------------------------------
def _reference(
    reference_id: str,
    *,
    producer: str,
    report_type: str,
    project_id: str,
    expected: str = "",
) -> BobaReportReferenceV1:
    return BobaReportReferenceV1(
        report_reference_id=reference_id,
        source_descriptor_id=f"src-{producer}",
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        workflow_run_id=WORKFLOW_RUN_ID,
        producer_module_id=producer,
        producer_record_id=f"rec-{reference_id}",
        report_type=report_type,  # type: ignore[arg-type]
        schema_id=f"schema-{report_type}",
        expected_digest=expected,
        sanitized_storage_reference=f"projects/{project_id}/reports/{reference_id}.json",
        format="json",
        created_at="2026-08-01T00:02:00+00:00",
    )


def _document(
    document_id: str,
    reference_id: str,
    *,
    producer: str,
    report_type: str,
    project_id: str,
    content_seed: str = "content",
    digest_match: bool = True,
    malformed: bool = False,
    stale: bool = False,
    schema_supported: bool = True,
    read_status: str = "completed",
    finding_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    section_ids: list[str] | None = None,
) -> BobaReportDocumentV1:
    return BobaReportDocumentV1(
        report_document_id=document_id,
        report_reference_id=reference_id,
        project_id=project_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        producer_module_id=producer,
        producer_record_id=f"rec-{reference_id}",
        report_type=report_type,  # type: ignore[arg-type]
        schema_id=f"schema-{report_type}",
        schema_version="1",
        parser_id="fixed_json_parser",
        format="json",
        content_digest=digest(content_seed),
        expected_digest_match=digest_match,
        schema_supported=schema_supported,
        malformed=malformed,
        stale=stale,
        read_status=read_status,  # type: ignore[arg-type]
        finding_ids=finding_ids or [],
        evidence_reference_ids=evidence_ids or [],
        section_ids=section_ids or [],
    )


def _finding(
    finding_id: str,
    document_id: str,
    *,
    producer: str,
    severity: str,
    domain: str = "technical_validation",
) -> BobaReportFindingV1:
    return BobaReportFindingV1(
        finding_id=finding_id,
        report_document_id=document_id,
        producer_module_id=producer,
        authority_domain=domain,  # type: ignore[arg-type]
        finding_type="fixture_finding",
        severity=severity,  # type: ignore[arg-type]
        title=f"Fixture {severity} finding",
        bounded_summary=f"A synthetic {severity} finding for {document_id}.",
        source_field_path="findings[0]",
        source_status="recorded",
        occurred_at="2026-08-01T00:03:00+00:00",
        timestamp_precision="exact",
    )


def _report_evidence(
    evidence_id: str,
    document_id: str,
    *,
    validation_run_id: str = RUN_ID,
    validator_id: str = "v-schema",
    available: bool = True,
) -> BobaReportEvidenceReferenceV1:
    return BobaReportEvidenceReferenceV1(
        evidence_reference_id=evidence_id,
        report_document_id=document_id,
        source_module_id="validator_runner",
        source_record_id=f"rec-{evidence_id}",
        source_field_path="evidence[0]",
        artifact_id="output-1",
        artifact_digest=digest("artifact"),
        validator_id=validator_id,
        validation_run_id=validation_run_id,
        bounded_summary=f"Fixture evidence reference {evidence_id}.",
        available=available,
        reliability="verified_digest",
        supports="source_fact",
    )


def _section(
    section_id: str, document_id: str, *, section_type: str = "status"
) -> BobaReportSectionV1:
    return BobaReportSectionV1(
        report_section_id=section_id,
        report_document_id=document_id,
        section_type=section_type,  # type: ignore[arg-type]
        source_field_path="status",
        title=f"Fixture {section_type} section",
        bounded_text=f"Synthetic {section_type} text.",
        item_count=1,
    )


def build_report_reader(
    *,
    references: list[BobaReportReferenceV1],
    documents: list[BobaReportDocumentV1],
    findings: list[BobaReportFindingV1] | None = None,
    evidence: list[BobaReportEvidenceReferenceV1] | None = None,
    sections: list[BobaReportSectionV1] | None = None,
    contradictions: list[BobaReportContradictionV1] | None = None,
    project_id: str = PROJECT_ID,
) -> BobaReportReaderSetV1:
    read_run = BobaReportReadRunV1(
        read_run_id="rrun-1",
        read_request_id="rreq-1",
        project_id=project_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        correlation_id="rcorr-1",
        status="completed",
        report_document_ids=[item.report_document_id for item in documents],
        idempotency_key="ridem-1",
    )
    return BobaReportReaderSetV1(
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        report_references=references,
        report_documents=documents,
        findings=findings or [],
        evidence_references=evidence or [],
        report_sections=sections or [],
        contradictions=contradictions or [],
        read_runs=[read_run],
    )


def healthy_reader(project_id: str = PROJECT_ID) -> BobaReportReaderSetV1:
    """One clean, digest-matched validator report with findings and evidence."""
    reference = _reference(
        "rref-1",
        producer="validator_runner",
        report_type="validator_runner",
        project_id=project_id,
        expected=digest("content"),
    )
    document = _document(
        "rdoc-1",
        "rref-1",
        producer="validator_runner",
        report_type="validator_runner",
        project_id=project_id,
        finding_ids=["rfind-1"],
        evidence_ids=["rev-1"],
        section_ids=["rsec-1"],
    )
    return build_report_reader(
        project_id=project_id,
        references=[reference],
        documents=[document],
        findings=[_finding("rfind-1", "rdoc-1", producer="validator_runner", severity="high")],
        evidence=[_report_evidence("rev-1", "rdoc-1")],
        sections=[_section("rsec-1", "rdoc-1")],
    )


def malformed_reader(project_id: str = PROJECT_ID) -> BobaReportReaderSetV1:
    """A malformed report and a digest mismatch. Neither may read as healthy."""
    return build_report_reader(
        project_id=project_id,
        references=[
            _reference(
                "rref-bad",
                producer="output_quality",
                report_type="output_quality",
                project_id=project_id,
                expected=digest("expected-different"),
            )
        ],
        documents=[
            _document(
                "rdoc-bad",
                "rref-bad",
                producer="output_quality",
                report_type="output_quality",
                project_id=project_id,
                digest_match=False,
                malformed=True,
                schema_supported=False,
                read_status="malformed",
            )
        ],
    )


def contradictory_reader(project_id: str = PROJECT_ID) -> BobaReportReaderSetV1:
    """Two reports of one type from one producer, plus a recorded contradiction."""
    references = [
        _reference(
            "rref-a",
            producer="output_quality",
            report_type="output_quality",
            project_id=project_id,
        ),
        _reference(
            "rref-b",
            producer="output_quality",
            report_type="output_quality",
            project_id=project_id,
        ),
    ]
    documents = [
        _document(
            "rdoc-a",
            "rref-a",
            producer="output_quality",
            report_type="output_quality",
            project_id=project_id,
            read_status="completed",
        ),
        _document(
            "rdoc-b",
            "rref-b",
            producer="output_quality",
            report_type="output_quality",
            project_id=project_id,
            content_seed="content-b",
            read_status="incomplete",
        ),
    ]
    contradiction = BobaReportContradictionV1(
        contradiction_id="rcon-1",
        project_id=project_id,
        report_document_ids=["rdoc-a", "rdoc-b"],
        contradiction_type="status_conflict",
        severity="high",
        bounded_summary="Two output quality reports disagree on status.",
        value_a="completed",
        value_b="incomplete",
        same_target=True,
    )
    return build_report_reader(
        project_id=project_id,
        references=references,
        documents=documents,
        contradictions=[contradiction],
    )


def empty_reader(project_id: str = PROJECT_ID) -> BobaReportReaderSetV1:
    return build_report_reader(project_id=project_id, references=[], documents=[])


def seed(store: Any, *, runner: Any = None, reader: Any = None) -> None:
    """Persist fixture owner records through the owners' own store helpers."""
    if runner is not None:
        store.save_boba_validator_runner(runner)
    if reader is not None:
        store.save_boba_report_reader(reader)
