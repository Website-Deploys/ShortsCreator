"""Unit tests for BOBA Validation + Reports V1.

Every catalogued validator scenario and declared-boundary self-check runs as an
individual test, alongside direct contract, engine, persistence and API tests.

Nothing here runs a real validator, reads a real report file, touches real media
or outputs, approves anything, grants Safety approval or advances a workflow.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from tools import _boba_validation_reports_fixtures as fx
from tools.validate_boba_validation_reports import (
    SCENARIO_NAMES,
    ScenarioResult,
    run_all_scenarios,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.boba.validation_reports import (
    MATRIX_STATES,
    VERDICT_STATES,
    BobaValidationBindingV1,
    BobaValidationConflictParticipantV1,
    BobaValidationConflictV1,
    BobaValidationEvidenceRefV1,
    BobaValidationMatrixCellV1,
    BobaValidationReportCardV1,
    BobaValidationReportsRegistrySnapshotV1,
    BobaValidationReportsV1,
    BobaValidationSummaryV1,
    bounded_projection_text,
    build_fixed_validation_conflict_kind_registry,
    build_fixed_validation_matrix_state_registry,
    build_fixed_validation_projection_source_registry,
    derive_matrix_state,
    owner_check_state_mapping,
    projection_content_digest,
    projection_content_for_digest,
    validate_projection_digest,
    validate_projection_reference,
    verdict_available,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import (
    NotFoundError,
    ValidationError,
    register_exception_handlers,
)
from olympus.utils import utc_now

PROJECT_ID = fx.PROJECT_ID
DIGEST = "a" * 64

CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaValidationReportsRegistrySnapshotV1,
    BobaValidationBindingV1,
    BobaValidationMatrixCellV1,
    BobaValidationSummaryV1,
    BobaValidationReportCardV1,
    BobaValidationEvidenceRefV1,
    BobaValidationConflictV1,
    BobaValidationConflictParticipantV1,
)

_AUTHORISATION_FLAGS: tuple[str, ...] = (
    "production_ready",
    "output_quality_authorized",
    "workflow_transition_authorized",
    "safety_authorized",
    "upload_authorized",
    "publication_authorized",
    "approval_granted",
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class _WorkflowStore(BobaMemoryStore):
    """A store reporting a synthetic canonical workflow run."""

    def load_boba_workflow_controller(self, project_id: str) -> Any:
        return {
            "workflow_runs": [
                {
                    "workflow_run_id": fx.WORKFLOW_RUN_ID,
                    "current_stage_instance_id": fx.STAGE_ID,
                    "revision": 3,
                    "status": "running",
                    "updated_at": "2026-08-01T00:05:00+00:00",
                }
            ]
        }


def _engine(
    tmp_path: Path, *, runner: Any = None, reader: Any = None
) -> BobaValidationReportsV1:
    store = _WorkflowStore(tmp_path / "boba")
    fx.seed(store, runner=runner, reader=reader)
    return BobaValidationReportsV1(store, None)  # type: ignore[arg-type]


def _project() -> Project:
    ts = utc_now()
    return Project(
        id=PROJECT_ID,
        name="Validation Reports Test",
        source_filename="s.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4",
        size_bytes=24,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=600.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=ts,
        updated_at=ts,
    )


def _client(tmp_path: Path) -> tuple[TestClient, BobaIntegration]:
    from olympus.api.v1.routes.boba import router

    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    asyncio.run(storage.put(project.storage_key, b"x", content_type="video/mp4"))
    asyncio.run(StorageProjectRepository(storage).save(project))
    store = _WorkflowStore(tmp_path / "boba")
    fx.seed(store, runner=fx.mixed_state_runner(), reader=fx.healthy_reader())
    integration = BobaIntegration(storage, store)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    return TestClient(app), integration


def _base() -> str:
    return f"/api/v1/boba/projects/{PROJECT_ID}/validation-reports"


# ---------------------------------------------------------------------------
# Validator coverage
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def scenario_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_all_scenarios()}


@pytest.fixture(scope="module")
def self_check_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_self_check()}


@pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
def test_validator_scenario_passes(
    scenario_name: str, scenario_results: dict[str, ScenarioResult]
) -> None:
    result = scenario_results[scenario_name]
    assert result.passed, f"{scenario_name}: {result.detail}"


def test_every_declared_scenario_produced_a_result(
    scenario_results: dict[str, ScenarioResult],
) -> None:
    assert set(scenario_results) == set(SCENARIO_NAMES)
    assert len(SCENARIO_NAMES) >= 100


def test_self_checks_pass(self_check_results: dict[str, ScenarioResult]) -> None:
    failed = [name for name, row in self_check_results.items() if not row.passed]
    assert not failed, failed
    assert len(self_check_results) >= 20


def test_synthetic_project_is_truthful() -> None:
    report = run_synthetic_project()
    assert report["validation_executed"] is False
    assert report["owner_records_modified"] is False
    assert report["production_ready"] is False
    assert report["export_excludes_bodies"] is True
    assert report["export_excludes_secrets"] is True
    assert sorted(report["state_counts"]) == sorted(MATRIX_STATES)


# ---------------------------------------------------------------------------
# Registries and vocabulary
# ---------------------------------------------------------------------------
def test_matrix_vocabulary_has_seven_distinct_states() -> None:
    assert len(MATRIX_STATES) == 7
    assert len(set(MATRIX_STATES)) == 7
    assert set(MATRIX_STATES) == {
        "PASS",
        "FAIL",
        "BLOCKED",
        "SKIPPED",
        "NOT_RUN",
        "STALE",
        "MISSING",
    }


def test_only_pass_and_fail_carry_a_verdict() -> None:
    assert set(VERDICT_STATES) == {"PASS", "FAIL"}
    for state in MATRIX_STATES:
        assert verdict_available(state) is (state in {"PASS", "FAIL"})


def test_every_owner_check_status_maps_without_collapsing_the_vocabulary() -> None:
    mapping = owner_check_state_mapping()
    # The Validator Runner's own vocabulary, transcribed.
    assert len(mapping) == 14
    assert set(mapping.values()) == set(MATRIX_STATES)
    assert mapping["passed"] == "PASS"
    assert mapping["failed"] == "FAIL"
    assert mapping["skipped_not_required"] == "SKIPPED"
    assert mapping["superseded"] == "STALE"
    assert mapping["unavailable"] == "MISSING"


def test_unrecognised_owner_status_never_becomes_a_pass() -> None:
    # None of these is a Validator Runner check status, so none may imply success.
    for status in ("", "brand_new", "success", "ok", "green", "complete", "done"):
        assert derive_matrix_state(status) == "MISSING"


def test_owner_status_matching_is_case_and_whitespace_normalised() -> None:
    # Casing is normalised because "PASSED" is the owner's own ``passed`` token,
    # not a new state. Normalising a token is not the same as inventing a result.
    assert derive_matrix_state("PASSED") == "PASS"
    assert derive_matrix_state("  passed  ") == "PASS"
    assert derive_matrix_state("Failed") == "FAIL"


def test_state_registry_marks_only_pass_as_success() -> None:
    registry = build_fixed_validation_matrix_state_registry()
    assert len(registry) == 7
    successes = [state for state, row in registry.items() if row["counts_as_success"]]
    assert successes == ["PASS"]
    assert sum(len(row["owner_statuses"]) for row in registry.values()) == 14


def test_source_registry_never_permits_override_or_execution() -> None:
    registry = build_fixed_validation_projection_source_registry()
    assert {"validator_runner", "report_reader", "artifact_inspector"} <= set(registry)
    for row in registry.values():
        assert row["access"] == "read_only"
        assert row["projection_may_override"] is False
        assert row["projection_may_execute"] is False


def test_conflict_registry_never_resolves_or_infers() -> None:
    registry = build_fixed_validation_conflict_kind_registry()
    assert len(registry) >= 8
    for row in registry.values():
        assert row["resolved_automatically"] is False
        assert row["winner_selected"] is False
        assert row["root_cause_inferred"] is False


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contract", CONTRACT_TYPES)
def test_contracts_forbid_unknown_fields(contract: type[BaseModel]) -> None:
    assert contract.model_config.get("extra") == "forbid"


def test_matrix_cell_cannot_claim_a_verdict_it_does_not_have() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationMatrixCellV1(
            cell_id="c1", derived_state="MISSING", verdict_available=True
        )


def test_matrix_cell_verdict_state_requires_an_available_verdict() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationMatrixCellV1(
            cell_id="c1",
            derived_state="FAIL",
            verdict_available=False,
            evidence_present=True,
        )


def test_matrix_cell_pass_requires_evidence() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationMatrixCellV1(
            cell_id="c1",
            derived_state="PASS",
            verdict_available=True,
            evidence_present=False,
        )


def test_matrix_cell_stale_must_present_as_stale() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationMatrixCellV1(
            cell_id="c1",
            derived_state="FAIL",
            verdict_available=True,
            evidence_present=True,
            stale=True,
        )


def test_summary_cannot_report_a_pass_without_evidence() -> None:
    binding = BobaValidationBindingV1(binding_id="b1", project_id=PROJECT_ID)
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationSummaryV1(
            summary_id="s1",
            project_id=PROJECT_ID,
            binding=binding,
            technical_validation_passed=True,
            validation_evidence_available=False,
        )
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationSummaryV1(
            summary_id="s2",
            project_id=PROJECT_ID,
            binding=binding,
            required_checks_passed=True,
            evidence_missing=True,
        )


@pytest.mark.parametrize("field", _AUTHORISATION_FLAGS)
def test_summary_authorisation_flags_cannot_be_set_true(field: str) -> None:
    binding = BobaValidationBindingV1(binding_id="b1", project_id=PROJECT_ID)
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationSummaryV1(
            summary_id="s1", project_id=PROJECT_ID, binding=binding, **{field: True}
        )


def test_report_card_cannot_claim_unverified_integrity() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationReportCardV1(
            report_card_id="rc1", integrity_verified=True, content_digest=""
        )


def test_report_card_cannot_claim_a_stored_body() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationReportCardV1(report_card_id="rc1", body_stored=True)


def test_evidence_cannot_support_both_pass_and_failure() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationEvidenceRefV1(
            evidence_ref_id="e1", supports_pass=True, supports_failure=True
        )


def test_unavailable_evidence_cannot_support_a_pass() -> None:
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationEvidenceRefV1(
            evidence_ref_id="e1", supports_pass=True, available=False
        )


def test_conflict_requires_at_least_two_differing_participants() -> None:
    participant = BobaValidationConflictParticipantV1(
        participant_id="p1", reported_value="passed"
    )
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationConflictV1(conflict_id="c1", participants=[participant])
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationConflictV1(
            conflict_id="c1",
            participants=[participant, participant],
            distinct_values=["passed"],
        )


@pytest.mark.parametrize(
    "field",
    (
        "resolved",
        "winner_selected",
        "values_merged",
        "values_averaged",
        "root_cause_inferred",
        "repair_inferred",
        "workflow_completion_inferred",
    ),
)
def test_conflict_cannot_claim_resolution_or_inference(field: str) -> None:
    participants = [
        BobaValidationConflictParticipantV1(participant_id="p1", reported_value="passed"),
        BobaValidationConflictParticipantV1(participant_id="p2", reported_value="failed"),
    ]
    with pytest.raises((ValidationError, PydanticValidationError)):
        BobaValidationConflictV1(
            conflict_id="c1",
            participants=participants,
            distinct_values=["passed", "failed"],
            **{field: True},
        )


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reference",
    (
        "/etc/passwd",
        "C:/Windows/system32",
        "\\\\server\\share\\report.json",
        "https://example.com/report.json",
        "file:///etc/passwd",
        "projects/../../etc/passwd",
        "projects/p/outputs/final.mp4",
        "projects/p/reports/authorization.json",
    ),
)
def test_unsafe_references_are_refused(reference: str) -> None:
    with pytest.raises(ValidationError):
        validate_projection_reference(reference, label="report reference")


def test_safe_project_scoped_reference_is_accepted() -> None:
    assert (
        validate_projection_reference(
            f"projects/{PROJECT_ID}/reports/r1.json", label="report reference"
        )
        == f"projects/{PROJECT_ID}/reports/r1.json"
    )
    assert validate_projection_reference("", label="report reference") == ""


@pytest.mark.parametrize("digest", ("not-a-digest", "A" * 64 + "x", "123", "z" * 64))
def test_malformed_digests_are_refused(digest: str) -> None:
    with pytest.raises(ValidationError):
        validate_projection_digest(digest, label="content digest")


def test_valid_digest_is_normalised_and_empty_is_allowed() -> None:
    assert validate_projection_digest(DIGEST.upper(), label="d") == DIGEST
    assert validate_projection_digest("", label="d") == ""


@pytest.mark.parametrize(
    "prose",
    (
        "run ffmpeg -i in.mp4 out.mp4",
        "rm -rf / && echo done",
        "authorization: Bearer abc",
        "see C:/Users/me/secret.txt",
        "fetch https://example.com/x",
        "../../etc/passwd",
    ),
)
def test_unsafe_owner_prose_is_redacted_not_echoed(prose: str) -> None:
    assert bounded_projection_text(prose) == "[redacted: unsafe content in owner record]"


def test_safe_owner_prose_is_preserved_and_bounded() -> None:
    assert bounded_projection_text("A schema assertion failed.") == (
        "A schema assertion failed."
    )
    assert len(bounded_projection_text("x" * 5_000, 100)) <= 100


# ---------------------------------------------------------------------------
# Engine: matrix
# ---------------------------------------------------------------------------
def test_empty_project_reports_no_validation_rather_than_a_pass(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.empty_runner())
    matrix = engine.build_validation_matrix(PROJECT_ID)
    summary = engine.build_validation_summary(PROJECT_ID)
    assert matrix["cells"] == []
    assert matrix["state_counts"] == dict.fromkeys(MATRIX_STATES, 0)
    assert matrix["required_verdict_complete"] is False
    assert matrix["evidence_complete"] is False
    assert summary["evidence_missing"] is True
    assert summary["technical_validation_passed"] is False
    assert "No validation run exists" in summary["derived_status_title"]


def test_every_distinguishable_state_is_projected_separately(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.mixed_state_runner())
    matrix = engine.build_validation_matrix(PROJECT_ID)
    states = {cell["owner_status"]: cell["derived_state"] for cell in matrix["cells"]}
    assert states["passed"] == "PASS"
    assert states["failed"] == "FAIL"
    assert states["blocked"] == "BLOCKED"
    assert states["dependency_blocked"] == "BLOCKED"
    assert states["skipped_not_required"] == "SKIPPED"
    assert states["pending"] == "NOT_RUN"
    assert states["unavailable"] == "MISSING"
    assert states["superseded"] == "STALE"
    # Distinct states remain distinct rather than being merged into failure.
    assert matrix["state_counts"]["FAIL"] == 1


def test_a_recorded_pass_without_evidence_is_never_a_pass(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.pass_without_evidence_runner())
    cell = engine.build_validation_matrix(PROJECT_ID)["cells"][0]
    assert cell["owner_status"] == "passed"
    assert cell["derived_state"] == "MISSING"
    assert cell["verdict_available"] is False
    assert cell["evidence_present"] is False
    assert "no evidence record exists" in cell["derived_state_reason"]


def test_matrix_ordering_is_deterministic(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.mixed_state_runner())
    first = engine.build_validation_matrix(PROJECT_ID)
    second = engine.build_validation_matrix(PROJECT_ID)
    assert [c["cell_id"] for c in first["cells"]] == [c["cell_id"] for c in second["cells"]]
    assert first["matrix_digest"] == second["matrix_digest"]
    keys = [(c["validator_id"], c["plan_check_id"], c["attempt_number"]) for c in first["cells"]]
    assert keys == sorted(keys)


def test_matrix_preserves_owner_facts_and_separates_presentation(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner())
    cell = engine.build_validation_matrix(PROJECT_ID)["cells"][0]
    assert cell["owner_fact"] is True
    assert cell["owner_module_id"] == "validator_runner"
    assert cell["owner_status"] == "passed"
    assert cell["validator_id"] == "v-schema"
    assert cell["validator_version"] == "1"
    assert len(cell["input_digest"]) == 64
    assert len(cell["result_digest"]) == 64
    assert cell["completed_at"]
    assert cell["workflow_revision"] == 3
    assert cell["derived_state"] == "PASS"
    assert cell["derived_state_reason"]
    assert cell["derived_title"]


def test_matrix_output_is_bounded(tmp_path: Path) -> None:
    from olympus.boba.validation_reports import MAX_MATRIX_CELLS

    checks = [fx._check(f"c{i}", "v-schema", "pending") for i in range(MAX_MATRIX_CELLS + 25)]
    engine = _engine(tmp_path, runner=fx.build_validator_runner(checks=checks))
    matrix = engine.build_validation_matrix(PROJECT_ID)
    assert len(matrix["cells"]) == MAX_MATRIX_CELLS
    assert matrix["total_cells"] == MAX_MATRIX_CELLS + 25
    assert matrix["truncated"] is True


# ---------------------------------------------------------------------------
# Engine: stale state
# ---------------------------------------------------------------------------
def test_changed_artifact_digest_makes_a_verdict_stale(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.stale_target_runner())
    cell = engine.build_validation_matrix(PROJECT_ID)["cells"][0]
    summary = engine.build_validation_summary(PROJECT_ID)
    assert cell["derived_state"] == "STALE"
    assert cell["owner_reported_state"] == "PASS"
    assert cell["owner_status"] == "passed"
    assert "artifact_digest" in cell["stale_reasons"]
    assert summary["binding"]["reuse_valid"] is False
    assert summary["technical_validation_passed"] is False


def test_validator_version_drift_makes_a_verdict_stale(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.version_drift_runner())
    cell = engine.build_validation_matrix(PROJECT_ID)["cells"][0]
    assert cell["derived_state"] == "STALE"
    assert "validator_version" in cell["stale_reasons"]


def test_binding_declares_all_eight_dimensions(tmp_path: Path) -> None:
    from olympus.boba.validation_reports import _STALE_DIMENSIONS

    assert len(_STALE_DIMENSIONS) == 8
    engine = _engine(tmp_path, runner=fx.passing_runner())
    binding = engine.build_validation_summary(PROJECT_ID)["binding"]
    for field in (
        "project_id",
        "workflow_run_id",
        "stage_instance_id",
        "target_id",
        "workflow_revision",
        "artifact_digest",
        "validator_version",
        "validation_request_id",
    ):
        assert field in binding


# ---------------------------------------------------------------------------
# Engine: summary
# ---------------------------------------------------------------------------
def test_a_passing_suite_never_implies_readiness_or_authority(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner())
    summary = engine.build_validation_summary(PROJECT_ID)
    assert summary["technical_validation_passed"] is True
    for field in _AUTHORISATION_FLAGS:
        assert summary[field] is False


# ---------------------------------------------------------------------------
# Engine: reports
# ---------------------------------------------------------------------------
def test_reports_are_projected_with_lineage_and_ownership(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    payload = engine.inspect_reports(PROJECT_ID)
    card = payload["report_cards"][0]
    assert card["owner_module_id"] == "report_reader"
    assert card["owner_fact"] is True
    assert card["body_stored"] is False
    assert card["lineage_read_run_id"] == "rrun-1"
    assert card["integrity_verified"] is True
    assert card["finding_count"] == 1


def test_malformed_and_mismatched_reports_are_never_reported_as_healthy(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.malformed_reader())
    payload = engine.inspect_reports(PROJECT_ID)
    card = payload["report_cards"][0]
    assert card["malformed"] is True
    assert card["expected_digest_match"] is False
    assert card["schema_supported"] is False
    assert card["integrity_verified"] is False
    assert card["incomplete"] is True
    assert payload["malformed_count"] == 1
    assert payload["digest_mismatch_count"] == 1


def test_report_filtering_and_bounded_output(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    matched = engine.inspect_reports(PROJECT_ID, "validator_runner")
    unmatched = engine.inspect_reports(PROJECT_ID, "rights_permission")
    assert matched["total_reports"] == 1
    assert unmatched["total_reports"] == 0
    assert unmatched["reports_available"] is False


def test_unknown_report_detail_is_refused(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    with pytest.raises(NotFoundError):
        engine.inspect_report_detail(PROJECT_ID, "rdoc-missing")


def test_report_detail_separates_failures_from_warnings(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    detail = engine.inspect_report_detail(PROJECT_ID, "rdoc-1")
    assert detail["report_card"]["report_document_id"] == "rdoc-1"
    assert len(detail["findings"]) == 1
    assert len(detail["failures"]) == 1
    assert detail["warnings"] == []
    assert len(detail["sections"]) == 1


# ---------------------------------------------------------------------------
# Engine: aggregation and conflicts
# ---------------------------------------------------------------------------
def test_contradictory_check_runs_are_both_preserved(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.contradictory_runner())
    matrix = engine.build_validation_matrix(PROJECT_ID)
    conflicts = engine.inspect_conflicts(PROJECT_ID)
    assert {c["owner_status"] for c in matrix["cells"]} == {"passed", "failed"}
    kinds = {row["conflict_kind"] for row in conflicts["conflicts"]}
    assert "check_status_conflict" in kinds
    status = next(
        row for row in conflicts["conflicts"] if row["conflict_kind"] == "check_status_conflict"
    )
    assert sorted(status["distinct_values"]) == ["failed", "passed"]
    assert status["winner_selected"] is False
    assert status["resolved"] is False
    assert status["values_merged"] is False
    assert status["values_averaged"] is False
    assert status["root_cause_inferred"] is False
    assert status["repair_inferred"] is False


def test_duplicate_suite_decisions_are_reported_not_chosen(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.duplicate_suite_decision_runner())
    conflicts = engine.inspect_conflicts(PROJECT_ID)
    kinds = {row["conflict_kind"] for row in conflicts["conflicts"]}
    assert "suite_decision_conflict" in kinds


def test_report_reader_contradictions_are_projected(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.contradictory_reader())
    kinds = {row["conflict_kind"] for row in engine.inspect_conflicts(PROJECT_ID)["conflicts"]}
    assert "reported_contradiction" in kinds
    assert "report_status_conflict" in kinds


def test_conflict_ordering_is_deterministic(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.contradictory_runner())
    first = [row["conflict_id"] for row in engine.inspect_conflicts(PROJECT_ID)["conflicts"]]
    second = [row["conflict_id"] for row in engine.inspect_conflicts(PROJECT_ID)["conflicts"]]
    assert first == second


# ---------------------------------------------------------------------------
# Engine: evidence
# ---------------------------------------------------------------------------
def test_evidence_is_referenced_and_bounded(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.mixed_state_runner())
    payload = engine.inspect_evidence(PROJECT_ID)
    assert payload["evidence_available"] is True
    for row in payload["evidence"]:
        assert row["redacted"] is True
        assert row["origin"] in {"validator_runner", "report_reader"}
        assert not (row["supports_pass"] and row["supports_failure"])


def test_missing_evidence_is_reported_as_absent(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.pass_without_evidence_runner())
    payload = engine.inspect_evidence(PROJECT_ID)
    assert payload["evidence"] == []
    assert payload["evidence_available"] is False


# ---------------------------------------------------------------------------
# Persistence, events and reset
# ---------------------------------------------------------------------------
def test_projection_persists_and_reloads_identically(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    first = engine.build_validation_reports(PROJECT_ID)
    loaded = engine.load_validation_reports(PROJECT_ID)
    assert loaded is not None
    assert loaded["matrix"]["matrix_id"] == first["matrix"]["matrix_id"]
    assert loaded["summary"]["summary_id"] == first["summary"]["summary_id"]


def test_registry_snapshot_is_immutable_across_rebuilds(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner())
    first = engine.build_validation_reports_registry(PROJECT_ID)
    second = engine.build_validation_reports_registry(PROJECT_ID)
    assert first["registry_snapshot"] == second["registry_snapshot"]


def test_projection_requests_are_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner())
    first = engine.create_projection_request(PROJECT_ID, idempotency_key="k")
    second = engine.create_projection_request(PROJECT_ID, idempotency_key="k")
    other = engine.create_projection_request(
        PROJECT_ID, requested_scope="matrix", idempotency_key="k"
    )
    assert first["request_id"] == second["request_id"]
    assert second["reused_existing_projection"] is True
    assert other["request_id"] != first["request_id"]


def test_unknown_projection_scope_is_refused(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner())
    with pytest.raises(ValidationError):
        engine.create_projection_request(PROJECT_ID, requested_scope="everything")


def test_events_are_append_only_and_paged(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    engine.build_validation_reports(PROJECT_ID)
    first = engine.inspect_validation_report_events(PROJECT_ID)
    assert first["returned"] >= 1
    assert first["append_only"] is True
    assert first["duplicates_owner_event_stream"] is False
    sequences = [row["sequence"] for row in first["events"]]
    assert sequences == sorted(sequences)

    engine.build_validation_reports(PROJECT_ID)
    second = engine.inspect_validation_report_events(PROJECT_ID)
    assert second["total_available"] > first["total_available"]
    # Earlier entries are never rewritten.
    assert second["events"][: len(first["events"])] == first["events"]

    page = engine.inspect_validation_report_events(
        PROJECT_ID, after_sequence=sequences[-1], limit=1
    )
    assert all(row["sequence"] > sequences[-1] for row in page["events"])


def test_negative_event_cursor_is_refused(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner())
    with pytest.raises(ValidationError):
        engine.inspect_validation_report_events(PROJECT_ID, after_sequence=-1)


def test_reset_removes_only_this_modules_metadata(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    engine.build_validation_reports(PROJECT_ID)
    before = engine.inspect_validation_report_events(PROJECT_ID)["total_available"]
    result = engine.reset_validation_report_metadata(PROJECT_ID)

    assert result["active_index_removed"] is True
    assert result["event_log_preserved"] is True
    assert result["registry_history_preserved"] is True
    assert result["validator_runner_history_preserved"] is True
    assert result["report_reader_history_preserved"] is True
    assert result["report_bodies_preserved"] is True
    assert result["media_removed"] is False
    assert result["outputs_removed"] is False
    assert result["code_modified"] is False

    assert engine.store.load_boba_validation_reports(PROJECT_ID) is None
    assert engine.store.load_boba_validator_runner(PROJECT_ID) is not None
    assert engine.store.load_boba_report_reader(PROJECT_ID) is not None
    assert engine.inspect_validation_report_events(PROJECT_ID)["total_available"] > before


def test_export_redacts_and_excludes_bodies(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    export = engine.export_validation_reports(PROJECT_ID)
    assert export["report_bodies_included"] is False
    assert export["raw_paths_included"] is False
    assert export["commands_included"] is False
    assert export["secrets_included"] is False
    assert export["media_included"] is False
    blob = str(export)
    for forbidden in ("/home/", "C:/Users", "Bearer ", "ffmpeg -i"):
        assert forbidden not in blob


# ---------------------------------------------------------------------------
# Ownership boundaries
# ---------------------------------------------------------------------------
def test_module_is_registered_with_its_owner_dependencies() -> None:
    module = build_boba_module_registry()["validation_reports"]
    assert module.module_id == "validation_reports"
    assert module.operation_ids
    operations = build_boba_operation_registry()
    assert all(op in operations for op in module.operation_ids)


def test_every_operation_is_read_only_or_own_metadata() -> None:
    operations = build_boba_operation_registry()
    own = {k: v for k, v in operations.items() if k.startswith("validation_reports.")}
    assert len(own) == 13
    assert {v.operation_class for v in own.values()} <= {
        "read_only",
        "export",
        "metadata_reset",
    }
    for descriptor in own.values():
        assert descriptor.target_approval_required is False
        assert descriptor.safety_gate_required is False
        assert descriptor.prohibited is False
        assert descriptor.future_gated is False


def test_safety_gate_classifies_every_operation_as_read_only() -> None:
    registry = build_safety_module_operation_registry()["validation_reports"]
    assert set(registry.values()) == {"automatic_read_only"}
    assert "inspect_matrix" in registry
    assert "reset" in registry


def test_owner_modules_are_still_registered_and_untouched() -> None:
    modules = build_boba_module_registry()
    for owner in (
        "validator_runner",
        "report_reader",
        "artifact_inspector",
        "workflow_controller",
        "safety_gate",
        "final_decision_bus",
        "integration_layer",
    ):
        assert owner in modules


def test_module_never_writes_owner_record_sets() -> None:
    source = Path("src/olympus/boba/validation_reports.py").read_text(encoding="utf-8")
    for forbidden in (
        "save_boba_validator_runner",
        "save_boba_report_reader",
        "save_boba_workflow_controller",
        "save_boba_safety_gate",
        "subprocess",
        "Popen",
        "os.system",
    ):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_every_read_route_returns_a_bounded_projection(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    for path in (
        "",
        "/registry",
        "/summary",
        "/matrix",
        "/reports",
        "/evidence",
        "/conflicts",
        "/events",
        "/export",
    ):
        response = client.get(_base() + path)
        assert response.status_code == 200, (path, response.text)
        assert isinstance(response.json(), dict)


def test_matrix_route_reports_all_seven_states(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = client.get(f"{_base()}/matrix").json()
    assert sorted(payload["state_counts"]) == sorted(MATRIX_STATES)
    assert payload["state_counts"]["PASS"] == 1
    assert payload["state_counts"]["FAIL"] == 1


def test_summary_route_never_authorises_anything(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = client.get(f"{_base()}/summary").json()
    for field in _AUTHORISATION_FLAGS:
        assert payload[field] is False


def test_report_detail_route_and_unknown_document(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get(f"{_base()}/reports/rdoc-1").status_code == 200
    assert client.get(f"{_base()}/reports/rdoc-missing").status_code == 404


def test_projection_request_route_is_idempotent(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = {"requested_scope": "matrix", "idempotency_key": "abc12345"}
    first = client.post(f"{_base()}/requests", json=body)
    second = client.post(f"{_base()}/requests", json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["request_id"] == second.json()["request_id"]
    assert second.json()["reused_existing_projection"] is True
    assert first.json()["executes_nothing"] is True


def test_projection_request_route_rejects_unknown_scope(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(f"{_base()}/requests", json={"requested_scope": "everything"})
    assert response.status_code == 422


def test_projection_request_route_forbids_unknown_fields(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        f"{_base()}/requests", json={"requested_scope": "full", "execute": True}
    )
    assert response.status_code == 422


def test_reset_route_preserves_owner_history(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.get(_base())
    response = client.delete(_base())
    assert response.status_code == 200
    payload = response.json()
    assert payload["validator_runner_history_preserved"] is True
    assert payload["report_bodies_preserved"] is True
    assert payload["media_removed"] is False


def test_routes_reject_an_unknown_project(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/api/v1/boba/projects/not-a-project/validation-reports")
    assert response.status_code == 404


def test_integration_facade_exposes_the_projection(tmp_path: Path) -> None:
    _, integration = _client(tmp_path)
    assert integration.build_boba_validation_matrix(PROJECT_ID)["cells"]
    assert integration.build_boba_validation_summary(PROJECT_ID)["production_ready"] is False
    assert integration.inspect_boba_validation_reports_list(PROJECT_ID)["reports_available"]
    assert integration.inspect_boba_validation_conflicts(PROJECT_ID)["schema_version"]
    assert integration.export_boba_validation_reports(PROJECT_ID)["secrets_included"] is False


# ---------------------------------------------------------------------------
# Projection digest determinism
#
# The projection digest has to identify projected content. It previously hashed
# the payload including its own generation timestamps, so an unchanged
# projection produced a different digest on every rebuild and the digest could
# not distinguish "nothing changed" from "something changed".
# ---------------------------------------------------------------------------
def test_projection_digest_is_stable_across_rebuilds(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    first = engine.build_validation_reports(PROJECT_ID)
    second = engine.build_validation_reports(PROJECT_ID)

    assert first["projection_digest"] == second["projection_digest"]
    assert len(first["projection_digest"]) == 64


def test_projection_digest_ignores_generation_timestamps_only(tmp_path: Path) -> None:
    """Timestamps stay in the payload; they simply do not feed the digest."""
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    first = engine.build_validation_reports(PROJECT_ID)
    second = engine.build_validation_reports(PROJECT_ID)

    # The generation timestamps are still reported, and did advance.
    assert first["created_at"] and second["created_at"]
    assert first["summary"]["created_at"] and first["matrix"]["created_at"]
    differing = {
        key
        for key in ("created_at",)
        if first[key] != second[key]
    }
    assert differing == {"created_at"}, "only wall-clock metadata may differ"
    assert first["projection_digest"] == second["projection_digest"]


def test_projection_digest_changes_when_owner_evidence_changes(tmp_path: Path) -> None:
    """A deterministic digest must still be sensitive to real content."""
    passing = _engine(
        tmp_path / "pass", runner=fx.passing_runner(), reader=fx.healthy_reader()
    ).build_validation_reports(PROJECT_ID)["projection_digest"]
    mixed = _engine(
        tmp_path / "mixed", runner=fx.mixed_state_runner(), reader=fx.healthy_reader()
    ).build_validation_reports(PROJECT_ID)["projection_digest"]
    malformed = _engine(
        tmp_path / "malformed", runner=fx.passing_runner(), reader=fx.malformed_reader()
    ).build_validation_reports(PROJECT_ID)["projection_digest"]
    stale = _engine(
        tmp_path / "stale", runner=fx.stale_target_runner(), reader=fx.healthy_reader()
    ).build_validation_reports(PROJECT_ID)["projection_digest"]
    empty = _engine(
        tmp_path / "empty", runner=fx.empty_runner(), reader=fx.empty_reader()
    ).build_validation_reports(PROJECT_ID)["projection_digest"]

    assert len({passing, mixed, malformed, stale, empty}) == 5


def test_reloaded_projection_keeps_its_digest(tmp_path: Path) -> None:
    engine = _engine(tmp_path, runner=fx.passing_runner(), reader=fx.healthy_reader())
    built = engine.build_validation_reports(PROJECT_ID)
    reloaded = engine.load_validation_reports(PROJECT_ID)

    assert reloaded is not None
    assert reloaded["projection_digest"] == built["projection_digest"]
    assert projection_content_digest(reloaded) == built["projection_digest"]


def test_projection_content_for_digest_strips_only_generation_timestamps() -> None:
    payload = {
        "created_at": "2026-08-01T00:00:00+00:00",
        "started_at": "2026-08-01T00:00:01+00:00",
        "completed_at": "2026-08-01T00:00:02+00:00",
        "generated_at": "2026-08-01T00:00:03+00:00",
        "matrix": {
            "created_at": "2026-08-01T00:00:04+00:00",
            "cells": [{"created_at": "x", "id": "c1"}],
        },
        "rows": [{"created_at": "y", "value": 1}],
    }
    content = projection_content_for_digest(payload)

    assert "created_at" not in content
    assert "created_at" not in content["matrix"]
    assert "created_at" not in content["matrix"]["cells"][0]
    assert "created_at" not in content["rows"][0]
    # Owner timestamps genuinely describe the evidence and must survive.
    assert content["started_at"] == "2026-08-01T00:00:01+00:00"
    assert content["completed_at"] == "2026-08-01T00:00:02+00:00"
    assert content["generated_at"] == "2026-08-01T00:00:03+00:00"
    assert content["matrix"]["cells"][0]["id"] == "c1"
    assert content["rows"][0]["value"] == 1


def test_projection_content_digest_excludes_the_digest_field() -> None:
    base = {"project_id": PROJECT_ID, "value": 1}
    without = projection_content_digest(base)
    with_digest = projection_content_digest({**base, "projection_digest": "z" * 64})

    assert without == with_digest


def test_projection_digest_survives_a_persisted_reload_round_trip(tmp_path: Path) -> None:
    """Rebuilding after a reload must not shift the digest."""
    engine = _engine(tmp_path, runner=fx.mixed_state_runner(), reader=fx.healthy_reader())
    first = engine.build_validation_reports(PROJECT_ID)["projection_digest"]
    assert engine.load_validation_reports(PROJECT_ID) is not None
    second = engine.build_validation_reports(PROJECT_ID)["projection_digest"]

    assert first == second


# ---------------------------------------------------------------------------
# Frontend contract
# ---------------------------------------------------------------------------
def test_frontend_exposes_the_projection_without_authority() -> None:
    panel = Path(
        "frontend/src/components/review/BobaValidationReportsPanel.tsx"
    ).read_text(encoding="utf-8")
    logic = Path("frontend/src/lib/validationReports.ts").read_text(encoding="utf-8")
    client = Path("frontend/src/lib/apiClient.ts").read_text(encoding="utf-8")
    results = Path("frontend/src/components/project/ResultsSection.tsx").read_text(
        encoding="utf-8"
    )

    assert "useMutation" not in panel
    assert "Presentation only" in panel
    assert "BobaValidationReportsPanel" in results
    assert "getBobaValidationMatrix:" in client
    for state in MATRIX_STATES:
        assert f'"{state}"' in logic
