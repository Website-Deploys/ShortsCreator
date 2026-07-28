"""BOBA Output Quality Reviewer V1 contracts, safety, and integration tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import output_quality_reviewer as quality
from olympus.boba.integration import BobaIntegration
from olympus.boba.output_quality_reviewer import (
    BobaCreativeQualityAssessmentV1,
    BobaCreativeQualityDimensionV1,
    BobaOutputAcceptanceDecisionV1,
    BobaOutputBaselineComparisonV1,
    BobaOutputHumanReviewPackageV1,
    BobaOutputQualityEvidenceV1,
    BobaOutputQualityHandoffV1,
    BobaOutputQualityIssueV1,
    BobaOutputQualityRegressionV1,
    BobaOutputQualityReviewerSetV1,
    BobaOutputQualityReviewerSummaryV1,
    BobaOutputQualityReviewerV1,
    BobaOutputQualitySignalUsageV1,
    BobaOutputReviewCaseV1,
    BobaReadOnlyQualityValidatorV1,
    BobaReviewedOutputArtifactV1,
    BobaTechnicalQualityAssessmentV1,
    BobaTechnicalQualityCheckV1,
    build_creative_quality_dimensions,
    build_human_review_package,
    build_output_quality_handoffs,
    build_quality_issues,
    build_read_only_quality_validator_registry,
    compare_output_to_baseline,
    execute_read_only_quality_command,
    make_output_acceptance_decision,
    record_boba_output_human_review,
    resolve_review_output,
    sanitize_review_export,
    validate_caption_events,
    validate_quality_command_safety,
)
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_output_quality_test"
CASE_ID = "quality_case_test"


def _check(
    category: str = "artifact_exists",
    *,
    status: str = "passed",
    required: bool = True,
    observed: Any = True,
    expected: Any = True,
) -> BobaTechnicalQualityCheckV1:
    return BobaTechnicalQualityCheckV1(
        technical_check_id=f"check_{category}_{status}",
        review_case_id=CASE_ID,
        category=category,
        name=category.replace("_", " ").title(),
        required=required,
        status=status,
        observed_value=observed,
        expected_value=expected,
        evidence_ids=[f"evidence_{category}"],
        blocks_acceptance=required and status in {"failed", "unavailable"},
        failure_summary=(
            f"{category} did not satisfy the requirement."
            if status in {"failed", "unavailable", "degraded"}
            else ""
        ),
        human_review_needed=status in {"unavailable", "degraded"},
    )


def _technical(
    *,
    eligible: bool = True,
    checks: list[BobaTechnicalQualityCheckV1] | None = None,
    failed: list[str] | None = None,
    unavailable: list[str] | None = None,
    score: float = 1.0,
) -> BobaTechnicalQualityAssessmentV1:
    selected = checks or []
    failed_values = (
        failed
        if failed is not None
        else [
            item.name
            for item in selected
            if item.required and item.status == "failed"
        ]
    )
    unavailable_values = (
        unavailable
        if unavailable is not None
        else [
            item.name
            for item in selected
            if item.required and item.status == "unavailable"
        ]
    )
    return BobaTechnicalQualityAssessmentV1(
        technical_assessment_id="technical_test",
        review_case_id=CASE_ID,
        checks=selected,
        technical_score=score,
        required_checks_passed=eligible
        and not failed_values
        and not unavailable_values,
        failed_required_checks=failed_values,
        unavailable_required_checks=unavailable_values,
        technical_acceptance_eligible=eligible
        and not failed_values
        and not unavailable_values,
    )


def _dimension(
    name: str = "hook_strength",
    *,
    status: str = "acceptable",
    blocking: bool = False,
    human: bool = False,
    score: float = 0.8,
) -> BobaCreativeQualityDimensionV1:
    return BobaCreativeQualityDimensionV1(
        creative_dimension_id=f"dimension_{name}",
        review_case_id=CASE_ID,
        dimension=name,
        status=status,
        score=score,
        evidence_ids=[f"evidence_{name}"],
        requires_human_review=human,
        blocking=blocking,
    )


def _creative(
    *,
    eligible: bool = True,
    human: bool = False,
    dimensions: list[BobaCreativeQualityDimensionV1] | None = None,
    score: float = 0.8,
    coverage: float = 0.9,
) -> BobaCreativeQualityAssessmentV1:
    return BobaCreativeQualityAssessmentV1(
        creative_assessment_id="creative_test",
        review_case_id=CASE_ID,
        dimensions=dimensions or [],
        creative_score=score,
        evidence_coverage=coverage,
        creative_acceptance_eligible=eligible,
        human_review_required=human,
        subjective_uncertainty=["Human judgment remains required."] if human else [],
    )


def _artifact(
    reference: str = f"render/{PROJECT_ID}/run/clip.mp4",
    *,
    artifact_id: str = "artifact_test",
    resolution: tuple[int, int] = (1080, 1920),
    duration: float = 10.0,
    frame_rate: float = 30.0,
    expected_audio: bool | None = True,
    expected_captions: bool | None = True,
    checksum: str = "sha256:baseline",
    size_bytes: int = 100,
) -> BobaReviewedOutputArtifactV1:
    return BobaReviewedOutputArtifactV1(
        output_artifact_id=artifact_id,
        project_id=PROJECT_ID,
        clip_id="clip_test",
        sanitized_artifact_reference=reference,
        artifact_type="video",
        expected_source_window={"start_seconds": 5.0, "end_seconds": 15.0},
        expected_duration_seconds=duration,
        expected_resolution={"width": resolution[0], "height": resolution[1]},
        expected_frame_rate=frame_rate,
        expected_audio=expected_audio,
        expected_captions=expected_captions,
        checksum=checksum,
        file_size_bytes=size_bytes,
        rights_status="owned",
    )


def _comparison(
    *,
    equivalent: bool = True,
    unknown: list[str] | None = None,
    non_negotiable: list[str] | None = None,
) -> BobaOutputBaselineComparisonV1:
    return BobaOutputBaselineComparisonV1(
        baseline_comparison_id="comparison_test",
        review_case_id=CASE_ID,
        baseline_artifact_id="baseline",
        reviewed_artifact_id="reviewed",
        comparison_basis="manual_baseline",
        unknown_properties=unknown or [],
        non_negotiable_regressions=non_negotiable or [],
        comparison_confidence=0.9,
        equivalent_for_required_capability=equivalent,
    )


def _regression(
    category: str = "resolution",
    *,
    severity: str = "major",
    non_negotiable: bool = False,
    disclosed: bool = False,
    approved: bool = False,
    impact: str = "human_review",
) -> BobaOutputQualityRegressionV1:
    return BobaOutputQualityRegressionV1(
        quality_regression_id=f"regression_{category}",
        review_case_id=CASE_ID,
        category=category,
        baseline_value="baseline",
        reviewed_value="reviewed",
        severity=severity,
        non_negotiable=non_negotiable,
        disclosed=disclosed,
        approved=approved,
        evidence_ids=[f"evidence_regression_{category}"],
        acceptance_impact=impact,
        recommended_action="Review the difference.",
    )


def _issue(
    *,
    owner: str = "human_operator",
    severity: str = "moderate",
    category: str = "creative",
    blocks: bool = False,
) -> BobaOutputQualityIssueV1:
    return BobaOutputQualityIssueV1(
        quality_issue_id=f"issue_{owner}_{category}",
        review_case_id=CASE_ID,
        category=category,
        title="Quality issue",
        summary="The output requires a bounded quality decision.",
        severity=severity,
        confirmed=True,
        confidence=0.8,
        blocks_acceptance=blocks,
        recommended_owner_module=owner,
        recommended_action="Review the evidence.",
    )


def _decision(value: str = "needs_human_review") -> BobaOutputAcceptanceDecisionV1:
    return BobaOutputAcceptanceDecisionV1(
        acceptance_decision_id=f"decision_{value}",
        review_case_id=CASE_ID,
        decision=value,
        decision_summary="A bounded quality decision was produced.",
        technical_eligible=value not in {"rejected_technical", "blocked_rights"},
        creative_eligible=value.startswith("accepted_"),
        required_checks_complete=value.startswith("accepted_"),
        rights_clear_for_processing=value != "blocked_rights",
        safety_clear_for_processing=value != "blocked_safety",
        human_review_required=True,
        next_allowed_stage="human_operator",
    )


def _report() -> BobaOutputQualityReviewerSetV1:
    artifact = _artifact(reference=f"render/{PROJECT_ID}/run/output.json")
    technical = _technical()
    creative = _creative(human=True, eligible=False)
    decision = _decision()
    review_case = BobaOutputReviewCaseV1(
        review_case_id=CASE_ID,
        source_type="normal_render",
        output_artifact_id=artifact.output_artifact_id,
        title="Output quality review",
        review_mode="artifact_only",
        review_status="creative_review_incomplete",
        rights_status="owned",
        safety_status="passed",
        technical_assessment_id=technical.technical_assessment_id,
        creative_assessment_id=creative.creative_assessment_id,
        acceptance_decision_id=decision.acceptance_decision_id,
    )
    return BobaOutputQualityReviewerSetV1(
        project_id=PROJECT_ID,
        source_id=PROJECT_ID,
        review_cases=[review_case],
        output_artifacts=[artifact],
        technical_assessments=[technical],
        creative_assessments=[creative],
        acceptance_decisions=[decision],
        signal_usage=BobaOutputQualitySignalUsageV1(),
    )


CONTRACT_FACTORIES = [
    (
        "evidence",
        lambda: BobaOutputQualityEvidenceV1(
            evidence_id="evidence",
            source_type="render_manifest",
            source_id="source",
            category="duration",
            bounded_summary="Duration evidence.",
        ),
    ),
    (
        "technical_check",
        lambda: _check(),
    ),
    (
        "technical_assessment",
        lambda: _technical(),
    ),
    (
        "creative_dimension",
        lambda: _dimension(),
    ),
    (
        "creative_assessment",
        lambda: _creative(),
    ),
    (
        "baseline_comparison",
        lambda: _comparison(),
    ),
    (
        "regression",
        lambda: _regression(),
    ),
    (
        "issue",
        lambda: _issue(),
    ),
    (
        "decision",
        lambda: _decision(),
    ),
    (
        "human_package",
        lambda: BobaOutputHumanReviewPackageV1(
            human_review_package_id="human_package",
            review_case_id=CASE_ID,
            reason="Subjective evidence needs human review.",
            sanitized_output_reference="render/output.mp4",
        ),
    ),
    (
        "handoff",
        lambda: BobaOutputQualityHandoffV1(
            handoff_id="handoff",
            review_case_id=CASE_ID,
            acceptance_decision_id="decision",
            target_module="human_operator",
            reason="Human review is required.",
        ),
    ),
    (
        "summary",
        BobaOutputQualityReviewerSummaryV1,
    ),
    (
        "signals",
        BobaOutputQualitySignalUsageV1,
    ),
    (
        "artifact",
        _artifact,
    ),
    (
        "review_case",
        lambda: BobaOutputReviewCaseV1(
            review_case_id=CASE_ID,
            source_type="normal_render",
            output_artifact_id="artifact",
            title="Review",
            review_mode="artifact_only",
            review_status="not_started",
        ),
    ),
    (
        "reviewer_set",
        _report,
    ),
]


LITERAL_ALIASES = [
    ("source_type", quality.BobaOutputReviewSourceTypeV1),
    ("review_mode", quality.BobaOutputReviewModeV1),
    ("review_status", quality.BobaOutputReviewStatusV1),
    ("artifact_type", quality.BobaReviewedArtifactTypeV1),
    ("evidence_source", quality.BobaQualityEvidenceSourceTypeV1),
    ("evidence_reliability", quality.BobaQualityEvidenceReliabilityV1),
    ("technical_status", quality.BobaTechnicalQualityStatusV1),
    ("technical_category", quality.BobaTechnicalQualityCategoryV1),
    ("creative_dimension", quality.BobaCreativeQualityDimensionNameV1),
    ("creative_status", quality.BobaCreativeQualityStatusV1),
    ("comparison_basis", quality.BobaOutputComparisonBasisV1),
    ("regression_category", quality.BobaOutputQualityRegressionCategoryV1),
    ("severity", quality.BobaOutputQualitySeverityV1),
    ("regression_impact", quality.BobaOutputRegressionAcceptanceImpactV1),
    ("owner", quality.BobaOutputQualityOwnerV1),
    ("decision", quality.BobaOutputAcceptanceDecisionValueV1),
    ("handoff_target", quality.BobaOutputQualityHandoffTargetV1),
    ("priority", quality.BobaOutputQualityPriorityV1),
]
LITERAL_CASES = [
    (name, alias, value)
    for name, alias in LITERAL_ALIASES
    for value in get_args(alias)
]


@pytest.mark.parametrize(
    ("name", "factory"),
    CONTRACT_FACTORIES,
    ids=[item[0] for item in CONTRACT_FACTORIES],
)
def test_every_contract_serializes(
    name: str,
    factory: Any,
) -> None:
    payload = factory().model_dump(mode="json")
    assert json.loads(json.dumps(payload)) == payload, name


@pytest.mark.parametrize(
    ("name", "alias", "value"),
    LITERAL_CASES,
    ids=[f"{name}-{value}" for name, _, value in LITERAL_CASES],
)
def test_supported_contract_literal_is_accepted(
    name: str,
    alias: Any,
    value: str,
) -> None:
    assert TypeAdapter(alias).validate_python(value) == value, name


@pytest.mark.parametrize(
    ("name", "alias"),
    LITERAL_ALIASES,
    ids=[item[0] for item in LITERAL_ALIASES],
)
def test_unsupported_contract_literal_is_rejected(
    name: str,
    alias: Any,
) -> None:
    with pytest.raises(PydanticValidationError):
        TypeAdapter(alias).validate_python(f"unsupported-{name}")


def _storage_artifact(
    tmp_path: Path,
    *,
    reference: str = f"render/{PROJECT_ID}/run/output.json",
    content: bytes | None = b'{"ok": true}',
    **metadata: Any,
) -> tuple[Path, dict[str, Any]]:
    storage_root = tmp_path / "storage"
    path = storage_root / Path(*reference.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        path.write_bytes(content)
    artifact = {
        "artifact_id": metadata.pop("artifact_id", "known_artifact"),
        "project_id": metadata.pop("project_id", PROJECT_ID),
        "reference": reference,
        "path_scope": metadata.pop("path_scope", "storage"),
        "source_type": metadata.pop("source_type", "normal_render"),
        "accepted_output_protected": True,
        **metadata,
    }
    return path, artifact


def _resolve(
    tmp_path: Path,
    *,
    output_reference: str,
    artifacts: list[dict[str, Any]],
    source_media_reference: str = "",
) -> quality.ResolvedReviewedOutputV1:
    return resolve_review_output(
        project_id=PROJECT_ID,
        output_reference=output_reference,
        known_output_artifacts=artifacts,
        repository_root=tmp_path,
        storage_root=tmp_path / "storage",
        source_media_reference=source_media_reference,
        rights_status="owned",
    )


@pytest.mark.parametrize(
    ("suffix", "expected_type"),
    [
        ("mp4", "video"),
        ("mov", "video"),
        ("wav", "audio"),
        ("ass", "caption"),
        ("srt", "caption"),
        ("png", "image"),
        ("jpg", "image"),
        ("json", "JSON"),
    ],
)
def test_target_resolution_classifies_supported_artifacts(
    tmp_path: Path,
    suffix: str,
    expected_type: str,
) -> None:
    reference = f"render/{PROJECT_ID}/run/output.{suffix}"
    path, artifact = _storage_artifact(tmp_path, reference=reference)
    resolved = _resolve(
        tmp_path,
        output_reference=reference,
        artifacts=[artifact],
    )
    assert resolved.path == path.resolve()
    assert resolved.artifact.artifact_type == expected_type
    assert resolved.artifact.accepted_output_protected is True
    assert resolved.artifact.source_media_read_only is True


def test_target_resolution_accepts_exact_artifact_id(tmp_path: Path) -> None:
    _, artifact = _storage_artifact(tmp_path, artifact_id="artifact_by_id")
    resolved = _resolve(
        tmp_path,
        output_reference="artifact_by_id",
        artifacts=[artifact],
    )
    assert resolved.artifact.output_artifact_id == "artifact_by_id"


def test_target_resolution_rejects_missing_target(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="not a known generated artifact"):
        _resolve(tmp_path, output_reference="render/missing.json", artifacts=[])


def test_target_resolution_rejects_ambiguous_target(tmp_path: Path) -> None:
    _, first = _storage_artifact(
        tmp_path,
        reference=f"render/{PROJECT_ID}/run/first.json",
        artifact_id="shared",
    )
    _, second = _storage_artifact(
        tmp_path,
        reference=f"render/{PROJECT_ID}/run/second.json",
        artifact_id="shared",
    )
    with pytest.raises(ValidationError, match="ambiguous"):
        _resolve(
            tmp_path,
            output_reference="shared",
            artifacts=[first, second],
        )


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.com/output.mp4",
        "http://127.0.0.1/output.mp4",
        "../output.mp4",
        "render/../output.mp4",
        "D:/outside/output.mp4",
        "C:\\outside\\output.mp4",
        "\\\\server\\share\\output.mp4",
        "/absolute/output.mp4",
    ],
)
def test_target_resolution_rejects_unsafe_reference(
    tmp_path: Path,
    reference: str,
) -> None:
    with pytest.raises(ValidationError):
        _resolve(tmp_path, output_reference=reference, artifacts=[])


def test_target_resolution_rejects_unknown_project_output(tmp_path: Path) -> None:
    reference = f"render/{PROJECT_ID}/run/output.json"
    _, artifact = _storage_artifact(
        tmp_path,
        reference=reference,
        project_id="proj_other",
    )
    with pytest.raises(ValidationError, match="another project"):
        _resolve(tmp_path, output_reference=reference, artifacts=[artifact])


@pytest.mark.parametrize("source_marker", ["flag", "reference"])
def test_target_resolution_rejects_source_media(
    tmp_path: Path,
    source_marker: str,
) -> None:
    reference = f"uploads/{PROJECT_ID}/source.mp4"
    _, artifact = _storage_artifact(
        tmp_path,
        reference=reference,
        is_source_media=source_marker == "flag",
    )
    with pytest.raises(ValidationError, match="Source media"):
        _resolve(
            tmp_path,
            output_reference=reference,
            artifacts=[artifact],
            source_media_reference=reference if source_marker == "reference" else "",
        )


def test_target_resolution_rejects_unsupported_scope(tmp_path: Path) -> None:
    reference = f"render/{PROJECT_ID}/run/output.json"
    _, artifact = _storage_artifact(
        tmp_path,
        reference=reference,
        path_scope="external",
    )
    with pytest.raises(ValidationError, match="path scope"):
        _resolve(tmp_path, output_reference=reference, artifacts=[artifact])


def test_target_resolution_rejects_repository_path_outside_allowlist(
    tmp_path: Path,
) -> None:
    reference = "docs/output.json"
    _, artifact = _storage_artifact(
        tmp_path,
        reference=reference,
        path_scope="repository",
    )
    with pytest.raises(ValidationError, match="approved BOBA output roots"):
        _resolve(tmp_path, output_reference=reference, artifacts=[artifact])


def test_target_resolution_accepts_allowlisted_repository_output(
    tmp_path: Path,
) -> None:
    reference = "work/boba/tool_recovery/workspaces/case/output.json"
    path = tmp_path / Path(*reference.split("/"))
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    artifact = {
        "artifact_id": "recovered",
        "project_id": PROJECT_ID,
        "reference": reference,
        "path_scope": "repository",
        "source_type": "tool_recovery_output",
    }
    resolved = _resolve(
        tmp_path,
        output_reference=reference,
        artifacts=[artifact],
    )
    assert resolved.path == path.resolve()
    assert resolved.source_type == "tool_recovery_output"


def test_target_resolution_rejects_external_symlink(tmp_path: Path) -> None:
    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")
    reference = f"render/{PROJECT_ID}/run/symlink.json"
    link = tmp_path / "storage" / Path(*reference.split("/"))
    link.parent.mkdir(parents=True)
    try:
        os.symlink(external, link)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this Windows host.")
    artifact = {
        "artifact_id": "symlink",
        "project_id": PROJECT_ID,
        "reference": reference,
        "path_scope": "storage",
    }
    with pytest.raises(ValidationError, match="external symlink"):
        _resolve(tmp_path, output_reference=reference, artifacts=[artifact])


def _review_json(
    tmp_path: Path,
    *,
    content: bytes | None = b'{"ok": true}',
    rights_status: str = "owned",
    safety_status: str = "passed",
    review_mode: str = "artifact_only",
    reference: str | None = None,
    **metadata: Any,
) -> tuple[BobaOutputQualityReviewerSetV1, Path]:
    selected_reference = reference or f"render/{PROJECT_ID}/run/output.json"
    path, artifact = _storage_artifact(
        tmp_path,
        reference=selected_reference,
        content=content,
        **metadata,
    )
    reviewer = BobaOutputQualityReviewerV1(
        tmp_path,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
    )
    report = reviewer.review(
        project_id=PROJECT_ID,
        output_reference=selected_reference,
        known_output_artifacts=[artifact],
        source_id=PROJECT_ID,
        source_media_reference=f"uploads/{PROJECT_ID}/source.mp4",
        review_mode=review_mode,
        rights_status=rights_status,
        safety_status=safety_status,
    )
    return report, path


@pytest.mark.parametrize("rights_status", ["unknown", "pending", "blocked"])
def test_unknown_or_blocked_rights_block_review(
    tmp_path: Path,
    rights_status: str,
) -> None:
    report, _ = _review_json(tmp_path, rights_status=rights_status)
    assert report.acceptance_decisions[-1].decision == "blocked_rights"
    assert report.signal_usage.rights_bypass_used is False
    assert report.review_cases[-1].review_status == "blocked"


@pytest.mark.parametrize(
    "rights_status",
    ["owned", "licensed", "permission_granted", "approved", "cleared"],
)
def test_clear_rights_permit_local_artifact_review(
    tmp_path: Path,
    rights_status: str,
) -> None:
    report, _ = _review_json(tmp_path, rights_status=rights_status)
    assert report.acceptance_decisions[-1].decision != "blocked_rights"
    assert report.acceptance_decisions[-1].rights_clear_for_processing is True


@pytest.mark.parametrize("safety_status", ["blocked", "unsafe", "rejected"])
def test_blocked_safety_blocks_review(
    tmp_path: Path,
    safety_status: str,
) -> None:
    report, _ = _review_json(tmp_path, safety_status=safety_status)
    assert report.acceptance_decisions[-1].decision == "blocked_safety"
    assert report.signal_usage.safety_bypass_used is False


def test_unknown_safety_requires_more_evidence(tmp_path: Path) -> None:
    report, _ = _review_json(tmp_path, safety_status="unknown")
    assert report.acceptance_decisions[-1].decision == "needs_more_evidence"
    assert report.acceptance_decisions[-1].next_allowed_stage == "safety_gate"


def test_review_never_modifies_exact_output(tmp_path: Path) -> None:
    content = b'{"immutable": true}'
    before = hashlib.sha256(content).hexdigest()
    report, path = _review_json(tmp_path, content=content)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert report.signal_usage.output_modified is False
    assert report.signal_usage.rendering_used is False


@pytest.mark.parametrize(
    "category",
    list(get_args(quality.BobaTechnicalQualityCategoryV1)),
)
def test_failed_required_technical_category_creates_blocking_issue(
    category: str,
) -> None:
    technical = _technical(
        eligible=False,
        checks=[_check(category, status="failed")],
    )
    issues = build_quality_issues(
        review_case_id=CASE_ID,
        source_type="normal_render",
        technical=technical,
        creative=_creative(),
        regressions=[],
        required_quality_properties=[category],
    )
    assert issues
    assert issues[0].category == category
    assert issues[0].blocks_acceptance is True


def test_missing_artifact_fails_integrity_check(tmp_path: Path) -> None:
    report, _ = _review_json(tmp_path, content=None)
    assessment = report.technical_assessments[-1]
    check = next(item for item in assessment.checks if item.category == "artifact_exists")
    assert check.status == "failed"
    assert assessment.technical_acceptance_eligible is False


def test_empty_artifact_fails_non_empty_check(tmp_path: Path) -> None:
    report, _ = _review_json(tmp_path, content=b"")
    assessment = report.technical_assessments[-1]
    check = next(
        item for item in assessment.checks if item.category == "artifact_non_empty"
    )
    assert check.status == "failed"


def test_checksum_mismatch_fails_check(tmp_path: Path) -> None:
    report, _ = _review_json(
        tmp_path,
        expected_checksum="sha256:" + ("0" * 64),
    )
    assessment = report.technical_assessments[-1]
    check = next(item for item in assessment.checks if item.category == "checksum")
    assert check.status == "failed"


def test_optional_unavailable_check_remains_visible_without_blocking() -> None:
    technical = _technical(
        checks=[_check("subject_visibility", status="unavailable", required=False)]
    )
    issues = build_quality_issues(
        review_case_id=CASE_ID,
        source_type="normal_render",
        technical=technical,
        creative=_creative(),
        regressions=[],
        required_quality_properties=[],
    )
    assert issues
    assert issues[0].recommended_owner_module == "validator_runner"
    assert issues[0].blocks_acceptance is False


@pytest.mark.parametrize("status", ["unavailable", "unknown"])
def test_required_nonpass_never_becomes_technical_acceptance(
    status: str,
) -> None:
    assessment = _technical(
        eligible=False,
        checks=[_check("decode", status=status)],
        unavailable=["Decode"] if status == "unavailable" else [],
    )
    assert assessment.technical_acceptance_eligible is False
    assert assessment.required_checks_passed is False


@pytest.mark.parametrize("score", [-0.01, 1.01, 2.0])
def test_technical_score_rejects_out_of_bounds(score: float) -> None:
    with pytest.raises(PydanticValidationError):
        _technical(score=score)


@pytest.mark.parametrize(
    ("events", "duration", "passed", "error_fragment"),
    [
        ([{"start": 0.0, "end": 1.0, "text": "Hello"}], 2.0, True, ""),
        ([], 2.0, True, ""),
        ([{"start": -1.0, "end": 1.0, "text": "Bad"}], 2.0, False, "invalid"),
        ([{"start": 1.0, "end": 1.0, "text": "Bad"}], 2.0, False, "invalid"),
        ([{"start": "x", "end": 1.0, "text": "Bad"}], 2.0, False, "invalid"),
        (
            [
                {"start": 1.0, "end": 2.0, "text": "Later"},
                {"start": 0.0, "end": 0.5, "text": "Earlier"},
            ],
            3.0,
            False,
            "monotonic",
        ),
        (
            [
                {"start": 0.0, "end": 1.5, "text": "First"},
                {"start": 1.0, "end": 2.0, "text": "Overlap"},
            ],
            3.0,
            False,
            "overlaps",
        ),
        (
            [{"start": 0.0, "end": 3.0, "text": "Late"}],
            2.0,
            False,
            "after the output",
        ),
        ([{"start_seconds": 0.0, "end_seconds": 1.0, "text": "Alias"}], 1.0, True, ""),
        ([{"start": 0.0, "end": 1.0, "text": ""}], 2.0, True, ""),
    ],
)
def test_caption_event_validation(
    events: list[dict[str, Any]],
    duration: float,
    passed: bool,
    error_fragment: str,
) -> None:
    result = validate_caption_events(events, clip_duration_seconds=duration)
    assert result["passed"] is passed
    if error_fragment:
        assert any(error_fragment in item for item in result["errors"])
    if events and not events[0].get("text") and passed:
        assert result["warnings"]


def _creative_from(
    artifacts: dict[str, Any],
    *,
    expected_captions: bool | None = False,
    checks: list[BobaTechnicalQualityCheckV1] | None = None,
) -> tuple[BobaCreativeQualityAssessmentV1, BobaOutputQualitySignalUsageV1]:
    collector = quality._EvidenceCollector(
        review_case_id=CASE_ID,
        output_reference="render/output.mp4",
    )
    signals = BobaOutputQualitySignalUsageV1()
    assessment = build_creative_quality_dimensions(
        review_case_id=CASE_ID,
        artifact=_artifact(expected_captions=expected_captions),
        technical=_technical(checks=checks or []),
        creative_artifacts=artifacts,
        collector=collector,
        signal_usage=signals,
    )
    return assessment, signals


def _creative_status(
    assessment: BobaCreativeQualityAssessmentV1,
    name: str,
) -> str:
    return next(
        item.status for item in assessment.dimensions if item.dimension == name
    )


@pytest.mark.parametrize(
    ("artifacts", "dimension", "expected_status"),
    [
        (
            {
                "hook_retention": {
                    "hook_score": 0.9,
                    "hook_line": "You are making this mistake.",
                    "reasoning": "The opening creates a concrete curiosity gap.",
                }
            },
            "hook_strength",
            "strong",
        ),
        (
            {"hook_retention": {"hook_score": 0.9}},
            "hook_strength",
            "conflicting",
        ),
        (
            {"hook_retention": {"hook_score": 0.2, "weak_hook": True}},
            "hook_strength",
            "weak",
        ),
        ({}, "hook_strength", "unavailable"),
        (
            {
                "boundary_quality": {
                    "completeness_score": 0.9,
                    "payoff_present": True,
                    "payoff_time": 14.0,
                    "payoff_score": 0.8,
                }
            },
            "story_completeness",
            "strong",
        ),
        (
            {
                "boundary_quality": {
                    "completeness_score": 0.2,
                    "payoff_present": False,
                }
            },
            "story_completeness",
            "failed",
        ),
        (
            {"boundary_quality": {"payoff_present": False}},
            "payoff_preservation",
            "failed",
        ),
        (
            {"boundary_quality": {"pacing_score": 0.8, "abrupt_end_risk": 0.1}},
            "pacing",
            "acceptable",
        ),
        (
            {"boundary_quality": {"pacing_score": 0.8, "abrupt_end_risk": 0.9}},
            "pacing",
            "failed",
        ),
        (
            {"caption_motion": {"motion_overload": True}},
            "motion_balance",
            "failed",
        ),
        (
            {"music_mood": {"mood": "hopeful", "should_use_music": True}},
            "music_mood_fit",
            "unavailable",
        ),
        (
            {"boundary_quality": {"duplicate_risk": 0.9}},
            "repetition",
            "failed",
        ),
    ],
)
def test_creative_evidence_maps_to_truthful_status(
    artifacts: dict[str, Any],
    dimension: str,
    expected_status: str,
) -> None:
    assessment, _ = _creative_from(artifacts)
    assert _creative_status(assessment, dimension) == expected_status


def test_hook_score_alone_does_not_prove_rendered_hook() -> None:
    assessment, _ = _creative_from(
        {"hook_retention": {"hook_score": 0.99}}
    )
    hook = next(
        item for item in assessment.dimensions if item.dimension == "hook_strength"
    )
    assert hook.status == "conflicting"
    assert hook.requires_human_review is True
    assert "alone does not prove" in hook.uncertainty


def test_caption_readability_without_visual_evidence_requires_review() -> None:
    checks = [
        _check("caption_presence"),
        _check("caption_timing"),
        _check("caption_bounds"),
    ]
    assessment, _ = _creative_from(
        {
            "render_metadata": {
                "caption_readability_validation": {"passed": True}
            }
        },
        expected_captions=True,
        checks=checks,
    )
    caption = next(
        item
        for item in assessment.dimensions
        if item.dimension == "caption_readability"
    )
    assert caption.status == "acceptable"
    assert caption.requires_human_review is True


@pytest.mark.parametrize(
    ("category", "status", "dimension", "expected"),
    [
        ("framing", "passed", "vertical_framing", "acceptable"),
        ("framing", "failed", "vertical_framing", "failed"),
        ("subject_visibility", "unavailable", "subject_visibility", "unavailable"),
        ("face_tracking", "failed", "face_tracking", "failed"),
        ("multi_speaker_layout", "degraded", "multi_speaker_layout", "weak"),
    ],
)
def test_visual_quality_claims_follow_existing_validation(
    category: str,
    status: str,
    dimension: str,
    expected: str,
) -> None:
    assessment, _ = _creative_from(
        {},
        checks=[_check(category, status=status)],
    )
    assert _creative_status(assessment, dimension) == expected


def test_low_creative_evidence_coverage_requires_human_review() -> None:
    assessment, _ = _creative_from({})
    assert assessment.evidence_coverage < 0.65
    assert assessment.human_review_required is True
    assert assessment.creative_acceptance_eligible is False


@pytest.mark.parametrize("score", [-0.1, 1.1, 100.0])
def test_creative_score_rejects_out_of_bounds(score: float) -> None:
    with pytest.raises(PydanticValidationError):
        _creative(score=score)


def _resolved_snapshot(
    *,
    artifact_id: str,
    reference: str,
    resolution: tuple[int, int] = (1080, 1920),
    frame_rate: float = 30.0,
    duration: float = 10.0,
    audio: bool = True,
    captions: bool = True,
    hook: str = "acceptable",
    story: str = "acceptable",
    payoff: str = "acceptable",
    checksum: str = "sha256:same",
) -> quality.ResolvedReviewedOutputV1:
    artifact = _artifact(
        reference,
        artifact_id=artifact_id,
        resolution=resolution,
        duration=duration,
        frame_rate=frame_rate,
        expected_audio=audio,
        expected_captions=captions,
        checksum=checksum,
    )
    metadata = {
        "manifest_entry": {
            "width": resolution[0],
            "height": resolution[1],
            "fps": frame_rate,
            "duration": duration,
            "has_audio": audio,
            "subtitles_included": captions,
            "video_codec": "h264",
            "audio_codec": "aac" if audio else None,
            "container": "mp4",
        },
        "actual_source_window": {"start_seconds": 5.0, "end_seconds": 15.0},
        "sync_validation": {"passed": True},
        "caption_timing_status": "passed",
        "framing_status": "passed",
        "story_completeness_status": story,
        "hook_status": hook,
        "payoff_status": payoff,
        "pacing_status": "acceptable",
        "motion_status": "acceptable",
        "music_fit_status": "acceptable",
    }
    return quality.ResolvedReviewedOutputV1(
        artifact=artifact,
        path=Path(reference),
        metadata=metadata,
        source_type="normal_render",
        path_scope="storage",
    )


def _baseline_compare(
    *,
    baseline: quality.ResolvedReviewedOutputV1,
    reviewed: quality.ResolvedReviewedOutputV1,
    technical: BobaTechnicalQualityAssessmentV1 | None = None,
    creative: BobaCreativeQualityAssessmentV1 | None = None,
    non_negotiable: list[str] | None = None,
) -> tuple[BobaOutputBaselineComparisonV1, list[BobaOutputQualityRegressionV1]]:
    collector = quality._EvidenceCollector(
        review_case_id=CASE_ID,
        output_reference=reviewed.artifact.sanitized_artifact_reference,
    )
    return compare_output_to_baseline(
        review_case_id=CASE_ID,
        reviewed=reviewed,
        baseline=baseline,
        technical=technical or _technical(),
        creative=creative
        or _creative(
            dimensions=[
                _dimension("story_completeness"),
                _dimension("hook_strength"),
                _dimension("payoff_preservation"),
                _dimension("pacing"),
                _dimension("motion_balance"),
                _dimension("music_mood_fit"),
            ]
        ),
        collector=collector,
        comparison_basis="manual_baseline",
        non_negotiable_requirements=non_negotiable or [],
    )


def test_exact_required_baseline_equivalence_passes() -> None:
    baseline = _resolved_snapshot(
        artifact_id="baseline",
        reference="render/baseline.mp4",
    )
    reviewed = _resolved_snapshot(
        artifact_id="reviewed",
        reference="render/reviewed.mp4",
    )
    comparison, regressions = _baseline_compare(
        baseline=baseline,
        reviewed=reviewed,
    )
    assert regressions == []
    assert comparison.equivalent_for_required_capability is True


@pytest.mark.parametrize(
    ("category", "baseline_changes", "reviewed_changes"),
    [
        ("resolution", {"resolution": (1080, 1920)}, {"resolution": (720, 1280)}),
        ("frame_rate", {"frame_rate": 30.0}, {"frame_rate": 24.0}),
        ("duration", {"duration": 10.0}, {"duration": 8.0}),
        ("audio_presence", {"audio": True}, {"audio": False}),
        ("caption_presence", {"captions": True}, {"captions": False}),
        ("file_integrity", {"checksum": "sha256:a"}, {"checksum": "sha256:b"}),
        ("hook", {"hook": "strong"}, {"hook": "weak"}),
        ("story_completeness", {"story": "strong"}, {"story": "failed"}),
        ("payoff", {"payoff": "strong"}, {"payoff": "failed"}),
    ],
)
def test_baseline_regression_is_detected(
    category: str,
    baseline_changes: dict[str, Any],
    reviewed_changes: dict[str, Any],
) -> None:
    baseline = _resolved_snapshot(
        artifact_id="baseline",
        reference="render/baseline.mp4",
        **baseline_changes,
    )
    reviewed = _resolved_snapshot(
        artifact_id="reviewed",
        reference="render/reviewed.mp4",
        **reviewed_changes,
    )
    creative = _creative(
        dimensions=[
            _dimension(
                "story_completeness",
                status=reviewed_changes.get("story", "acceptable"),
            ),
            _dimension(
                "hook_strength",
                status=reviewed_changes.get("hook", "acceptable"),
            ),
            _dimension(
                "payoff_preservation",
                status=reviewed_changes.get("payoff", "acceptable"),
            ),
            _dimension("pacing"),
            _dimension("motion_balance"),
            _dimension("music_mood_fit"),
        ]
    )
    comparison, regressions = _baseline_compare(
        baseline=baseline,
        reviewed=reviewed,
        creative=creative,
    )
    assert category in {item.category for item in regressions}
    assert comparison.equivalent_for_required_capability is False


def test_disclosed_approved_minor_regression_remains_explicit() -> None:
    regression = _regression(
        category="music_fit",
        severity="minor",
        disclosed=True,
        approved=True,
        impact="disclose",
    )
    decision = make_output_acceptance_decision(
        review_case_id=CASE_ID,
        rights_status="owned",
        safety_status="passed",
        technical=_technical(),
        creative=_creative(),
        comparison=_comparison(),
        regressions=[regression],
        issues=[],
        baseline_required=True,
    )
    assert decision.decision == "accepted_with_disclosed_limitations"
    assert decision.human_review_required is True


@pytest.mark.parametrize(
    (
        "rights",
        "safety",
        "technical",
        "creative",
        "comparison",
        "regressions",
        "baseline_required",
        "expected",
    ),
    [
        (
            "blocked",
            "passed",
            _technical(),
            _creative(),
            None,
            [],
            False,
            "blocked_rights",
        ),
        (
            "owned",
            "blocked",
            _technical(),
            _creative(),
            None,
            [],
            False,
            "blocked_safety",
        ),
        (
            "owned",
            "passed",
            _technical(eligible=False, failed=["Decode"]),
            _creative(),
            None,
            [],
            False,
            "rejected_technical",
        ),
        (
            "owned",
            "passed",
            _technical(eligible=False, unavailable=["FFprobe"]),
            _creative(),
            None,
            [],
            False,
            "needs_more_evidence",
        ),
        (
            "owned",
            "passed",
            _technical(),
            _creative(
                eligible=False,
                dimensions=[
                    _dimension(
                        "payoff_preservation",
                        status="failed",
                        blocking=True,
                    )
                ],
            ),
            None,
            [],
            False,
            "rejected_quality",
        ),
        (
            "owned",
            "passed",
            _technical(),
            _creative(eligible=False, human=True),
            None,
            [],
            False,
            "needs_human_review",
        ),
        (
            "owned",
            "passed",
            _technical(),
            _creative(),
            _comparison(),
            [_regression(non_negotiable=True, impact="reject")],
            True,
            "rejected_regression",
        ),
        (
            "owned",
            "passed",
            _technical(),
            _creative(),
            _comparison(),
            [],
            True,
            "accepted_for_next_internal_stage",
        ),
        (
            "owned",
            "passed",
            _technical(),
            _creative(),
            None,
            [],
            True,
            "needs_more_evidence",
        ),
    ],
)
def test_acceptance_decision_matrix(
    rights: str,
    safety: str,
    technical: BobaTechnicalQualityAssessmentV1,
    creative: BobaCreativeQualityAssessmentV1,
    comparison: BobaOutputBaselineComparisonV1 | None,
    regressions: list[BobaOutputQualityRegressionV1],
    baseline_required: bool,
    expected: str,
) -> None:
    decision = make_output_acceptance_decision(
        review_case_id=CASE_ID,
        rights_status=rights,
        safety_status=safety,
        technical=technical,
        creative=creative,
        comparison=comparison,
        regressions=regressions,
        issues=[],
        baseline_required=baseline_required,
    )
    assert decision.decision == expected
    assert decision.workflow_resume_authorized is False
    assert decision.publication_authorized is False
    assert "virality" not in decision.decision_summary.casefold()


def test_human_review_package_is_bounded_and_non_destructive() -> None:
    package = build_human_review_package(
        review_case_id=CASE_ID,
        artifact=_artifact(),
        baseline=None,
        technical=_technical(),
        creative=_creative(human=True, eligible=False),
        comparison=None,
        decision=_decision(),
    )
    assert 1 <= len(package.reviewer_questions) <= 16
    assert any("opening" in item.casefold() for item in package.reviewer_questions)
    assert any("publish" in item.casefold() for item in package.prohibited_actions)


@pytest.mark.parametrize(
    ("decision_value", "owner", "expected_target"),
    [
        ("accepted_for_next_internal_stage", None, "workflow_controller"),
        ("accepted_with_disclosed_limitations", None, "workflow_controller"),
        ("needs_human_review", None, "human_operator"),
        ("needs_more_evidence", None, "validator_runner"),
        ("rejected_technical", None, "root_cause_analyzer"),
        ("rejected_quality", None, "repair_planner"),
        ("rejected_regression", None, "repair_planner"),
        ("blocked_rights", None, "rights_permission_gate"),
        ("blocked_safety", None, "safety_gate"),
        ("rejected_quality", "checkpoint_recovery_manager", "checkpoint_recovery_manager"),
    ],
)
def test_quality_handoff_routes_to_expected_module(
    decision_value: str,
    owner: str | None,
    expected_target: str,
) -> None:
    handoffs = build_output_quality_handoffs(
        review_case_id=CASE_ID,
        source_type="normal_render",
        decision=_decision(decision_value),
        technical=_technical(),
        issues=[_issue(owner=owner)] if owner else [],
    )
    assert expected_target in {item.target_module for item in handoffs}
    assert all(item.apply_automatically is False for item in handoffs)
    assert all(item.human_approval_required is True for item in handoffs)


def test_tool_recovery_technical_rejection_routes_back_to_tool_recovery() -> None:
    handoffs = build_output_quality_handoffs(
        review_case_id=CASE_ID,
        source_type="tool_recovery_output",
        decision=_decision("rejected_technical"),
        technical=_technical(eligible=False, failed=["Decode"]),
        issues=[],
    )
    assert {item.target_module for item in handoffs} == {"tool_recovery_brain"}


def _command_fixture(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    dict[str, BobaReadOnlyQualityValidatorV1],
    list[str],
]:
    reviewed = tmp_path / "reviewed.mp4"
    reviewed.write_bytes(b"media")
    work = tmp_path / "work"
    work.mkdir()
    executable = tmp_path / "ffprobe.exe"
    executable.write_bytes(b"binary")
    registry = build_read_only_quality_validator_registry(
        ffprobe_binary=str(executable),
        ffmpeg_binary="definitely-missing-ffmpeg",
    )
    command = quality._build_quality_ffprobe_command(
        binary=str(executable.resolve()),
        path=reviewed.resolve(),
    )
    return reviewed, work, registry, command


def test_exact_registered_read_only_command_is_safe(tmp_path: Path) -> None:
    reviewed, work, registry, command = _command_fixture(tmp_path)
    assert validate_quality_command_safety(
        validator_id="ffprobe_media",
        command=command,
        registry=registry,
        reviewed_path=reviewed,
        working_directory=work,
    ) == []


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda command, path: [*command, "|", "more"], "Shell"),
        (lambda command, path: [*command, ">", "out.txt"], "Shell"),
        (lambda command, path: [*command, "&&", "whoami"], "Shell"),
        (lambda command, path: [*command, ";", "whoami"], "Shell"),
        (lambda command, path: [*command, "$(whoami)"], "Shell"),
        (lambda command, path: [*command, "https://example.com/x"], "Network"),
        (lambda command, path: ["git", *command[1:]], "executable"),
        (lambda command, path: ["pip", *command[1:]], "executable"),
        (lambda command, path: ["npm", *command[1:]], "executable"),
        (lambda command, path: ["powershell", *command[1:]], "executable"),
        (lambda command, path: ["taskkill", *command[1:]], "executable"),
        (lambda command, path: [*command, "-y"], "unsafe"),
        (lambda command, path: [*command, str(path)], "once"),
        (
            lambda command, path: [item for item in command if item != str(path)],
            "once",
        ),
    ],
)
def test_command_safety_rejects_unsafe_shape(
    tmp_path: Path,
    mutation: Any,
    fragment: str,
) -> None:
    reviewed, work, registry, command = _command_fixture(tmp_path)
    errors = validate_quality_command_safety(
        validator_id="ffprobe_media",
        command=mutation(command, reviewed.resolve()),
        registry=registry,
        reviewed_path=reviewed,
        working_directory=work,
    )
    assert errors
    assert fragment.casefold() in " ".join(errors).casefold()


@pytest.mark.parametrize(
    "validator_id",
    ["arbitrary_validator", "curl", "package_installer", "service_manager"],
)
def test_command_safety_rejects_arbitrary_validator(
    tmp_path: Path,
    validator_id: str,
) -> None:
    reviewed, work, registry, command = _command_fixture(tmp_path)
    errors = validate_quality_command_safety(
        validator_id=validator_id,
        command=command,
        registry=registry,
        reviewed_path=reviewed,
        working_directory=work,
    )
    assert errors == ["The validator is not registered for local command execution."]


def test_read_only_command_uses_array_no_shell_and_bounded_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, work, registry, command = _command_fixture(tmp_path)
    captured: dict[str, Any] = {}

    def fake_run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["arguments"] = arguments
        captured.update(kwargs)
        kwargs["stdout"].write(b"x" * 140_000)
        kwargs["stderr"].write(b"bounded error")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = execute_read_only_quality_command(
        validator_id="ffprobe_media",
        command=command,
        registry=registry,
        reviewed_path=reviewed,
        working_directory=work,
    )
    assert captured["arguments"] == command
    assert isinstance(captured["arguments"], list)
    assert captured["shell"] is False
    assert captured["timeout"] <= 120
    assert captured["stdout"] is not subprocess.PIPE
    assert result.output_truncated is True
    assert len(result.stdout) <= 4_000
    assert "TOKEN" not in captured["env"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"api_key": "secret", "safe": "yes"}, {"safe": "yes"}),
        ({"token": "secret"}, {}),
        ({"stdout": "full log", "safe": 1}, {"safe": 1}),
        ("https://example.com/private", "[external reference excluded]"),
        ("D:\\private\\output.mp4", "[private path excluded]"),
        ("\\\\server\\share\\output.mp4", "[private path excluded]"),
        ("/private/output.mp4", "[private path excluded]"),
        ({"nested": {"password": "secret", "ok": True}}, {"nested": {"ok": True}}),
    ],
)
def test_safe_export_redacts_private_or_sensitive_values(
    value: Any,
    expected: Any,
) -> None:
    assert sanitize_review_export(value) == expected


@pytest.mark.parametrize(
    "field",
    [
        "output_modified",
        "source_media_modified",
        "workflow_resume_used",
        "rendering_used",
        "fallback_execution_used",
        "code_modification_used",
        "external_api_used",
        "network_access_used",
        "url_fetching_used",
        "scraping_used",
        "downloading_used",
        "uploading_used",
        "publication_used",
        "rights_bypass_used",
        "safety_bypass_used",
        "destructive_action_used",
    ],
)
def test_forbidden_signal_is_literal_false(field: str) -> None:
    signals = BobaOutputQualitySignalUsageV1()
    assert getattr(signals, field) is False
    with pytest.raises(PydanticValidationError):
        BobaOutputQualitySignalUsageV1.model_validate({field: True})


def test_human_review_records_hashed_identity_without_authentication_material() -> None:
    report = _report()
    updated = record_boba_output_human_review(
        report,
        review_case_id=CASE_ID,
        reviewer_identity="reviewer@example.test",
        review_decision="request_more_evidence",
        answers={"opening": "unclear", "token": "must not persist"},
        notes="Please inspect the opening.",
    )
    evidence = updated.quality_evidence[-1]
    payload = json.dumps(updated.model_dump(mode="json"))
    assert evidence.source_id.startswith("reviewer_")
    assert "reviewer@example.test" not in payload
    assert "must not persist" not in json.dumps(sanitize_review_export(updated))
    assert updated.signal_usage.bounded_manual_review_used is True
    assert updated.acceptance_decisions[-1].workflow_resume_authorized is False
    assert updated.acceptance_decisions[-1].publication_authorized is False


@pytest.mark.parametrize(
    ("review_decision", "target"),
    [
        ("request_more_evidence", "validator_runner"),
        ("reject_output", "repair_planner"),
        ("send_back_to_repair_planner", "repair_planner"),
        ("send_back_to_tool_recovery", "tool_recovery_brain"),
    ],
)
def test_human_review_rejection_or_request_routes_safely(
    review_decision: str,
    target: str,
) -> None:
    updated = record_boba_output_human_review(
        _report(),
        review_case_id=CASE_ID,
        reviewer_identity="bounded-reviewer",
        review_decision=review_decision,
    )
    assert updated.review_handoffs[-1].target_module == target
    assert updated.review_handoffs[-1].apply_automatically is False


def test_store_persists_main_and_per_review_records(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    report = _report()
    store.save_boba_output_quality_reviewer(report)
    assert store.output_quality_reviewer_path(PROJECT_ID).is_file()
    assert store.output_quality_reviewer_review_path(PROJECT_ID, CASE_ID).is_file()
    loaded = store.load_boba_output_quality_reviewer(PROJECT_ID)
    assert loaded is not None
    assert loaded.review_cases[0].review_case_id == CASE_ID


def test_store_export_is_json_safe_and_declares_privacy(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    store.save_boba_output_quality_reviewer(_report())
    exported = store.export_boba_output_quality_reviewer(PROJECT_ID)
    json.dumps(exported)
    assert exported["privacy"]["private_absolute_paths_excluded"] is True
    assert exported["privacy"]["sensitive_evidence_excluded"] is True
    assert exported["privacy"]["full_command_logs_excluded"] is True
    assert exported["privacy"]["output_modified"] is False
    assert exported["privacy"]["publication_used"] is False


def test_store_reset_removes_only_reviewer_metadata(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    store.save_boba_output_quality_reviewer(_report())
    protected = [
        tmp_path / "storage_data" / "render" / PROJECT_ID / "run" / "index.json",
        tmp_path / "storage_data" / "render" / PROJECT_ID / "run" / "clip.mp4",
        tmp_path / "media" / PROJECT_ID / "source.mp4",
        store._project_dir(PROJECT_ID) / "tool_recovery" / "index.json",
        store._project_dir(PROJECT_ID) / "code_surgeon" / "index.json",
    ]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"protected")
    assert store.reset_boba_output_quality_reviewer(PROJECT_ID) is True
    assert store.load_boba_output_quality_reviewer(PROJECT_ID) is None
    assert all(path.is_file() for path in protected)


def test_store_load_returns_none_for_malformed_report(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    path = store.output_quality_reviewer_path(PROJECT_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema_version": "wrong"}', encoding="utf-8")
    assert store.load_boba_output_quality_reviewer(PROJECT_ID) is None


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Output Quality Reviewer Test",
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


def _integration(
    tmp_path: Path,
) -> tuple[BobaIntegration, BobaMemoryStore, LocalStorage, str]:
    storage_root = tmp_path / "storage"
    storage = LocalStorage(root=str(storage_root))
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    output_reference = f"render/{PROJECT_ID}/run/output.json"
    asyncio.run(storage.put(output_reference, b'{"reviewed": true}'))
    manifest = {
        "render_id": "render_quality_test",
        "renders": [
            {
                "clip_id": "clip_test",
                "storage_key": output_reference,
                "duration": 10.0,
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "has_audio": False,
                "subtitles_included": False,
                "metadata": {},
            }
        ],
    }
    asyncio.run(
        storage.put(
            f"render/{PROJECT_ID}/run/index.json",
            json.dumps(manifest).encode("utf-8"),
        )
    )
    integration = BobaIntegration(storage, store)
    integration.output_quality_reviewer = BobaOutputQualityReviewerV1(
        tmp_path,
        storage_root=storage_root,
        evidence_root=tmp_path / "evidence",
    )
    return integration, store, storage, output_reference


def test_api_review_get_export_and_reset_do_not_modify_output(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store, storage, output_reference = _integration(tmp_path)
    output_path = Path(storage.local_path(output_reference) or "")
    before = output_path.read_bytes()
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        reviewed = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/output-quality-reviewer/review",
            json={
                "output_reference": output_reference,
                "review_mode": "artifact_only",
                "rights_status": "owned",
                "safety_status": "passed",
            },
        )
        loaded = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/output-quality-reviewer"
        )
        exported = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/output-quality-reviewer/export"
        )
        reset = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/output-quality-reviewer"
        )
    assert reviewed.status_code == 200, reviewed.text
    assert loaded.status_code == 200, loaded.text
    assert exported.status_code == 200, exported.text
    assert reset.status_code == 200, reset.text
    assert output_path.read_bytes() == before
    assert reset.json()["reviewed_output_deleted"] is False
    assert reset.json()["render_manifest_deleted"] is False
    assert store.load_boba_output_quality_reviewer(PROJECT_ID) is None


@pytest.mark.parametrize(
    "unsafe_field",
    [
        "output_modification_requested",
        "source_modification_requested",
        "network_review_requested",
    ],
)
def test_api_rejects_unsafe_review_request(
    app: FastAPI,
    tmp_path: Path,
    unsafe_field: str,
) -> None:
    integration, _, _, output_reference = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    payload = {
        "output_reference": output_reference,
        "review_mode": "artifact_only",
        "rights_status": "owned",
        "safety_status": "passed",
        unsafe_field: True,
    }
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/output-quality-reviewer/review",
            json=payload,
        )
    assert response.status_code == 422


def test_api_human_review_records_bounded_input(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store, _, output_reference = _integration(tmp_path)
    initial = asyncio.run(
        integration.generate_boba_output_quality_review(
            PROJECT_ID,
            output_reference=output_reference,
            review_mode="artifact_only",
            rights_status="owned",
            safety_status="passed",
        )
    )
    case_id = initial.review_cases[-1].review_case_id
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/output-quality-reviewer/human-review",
            json={
                "review_case_id": case_id,
                "reviewer_identity": "internal-reviewer",
                "review_decision": "request_more_evidence",
                "answers": {"opening": "uncertain"},
                "notes": "Inspect the opening.",
            },
        )
    assert response.status_code == 200, response.text
    loaded = store.load_boba_output_quality_reviewer(PROJECT_ID)
    assert loaded is not None
    assert loaded.signal_usage.bounded_manual_review_used is True
    assert loaded.acceptance_decisions[-1].workflow_resume_authorized is False


def test_frontend_exposes_unified_output_quality_reviewer() -> None:
    source = Path(
        "frontend/src/components/project/ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BobaOutputQualityReviewerPanel" in source
    for label in [
        "TECHNICAL CHECKS",
        "CREATIVE REVIEW",
        "BASELINE COMPARISON",
        "QUALITY REGRESSIONS",
        "DECISION",
        "HUMAN REVIEW",
        "WHAT HAPPENS NEXT",
    ]:
        assert label in source
