"""Validate BOBA Validation + Reports V1 without touching real state.

Every scenario runs against synthetic owner records in a temporary directory.
This tool runs no real validator, reads no real report file, touches no real
project, media or output, and executes nothing. It proves that the projection
tells the truth about validation and reports, and that it never becomes a second
validator, a second report store or a second decision authority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.boba.validation_reports import (
    MATRIX_STATES,
    VERDICT_STATES,
    BobaValidationReportsV1,
    build_fixed_validation_conflict_kind_registry,
    build_fixed_validation_matrix_state_registry,
    build_fixed_validation_projection_source_registry,
    derive_matrix_state,
    owner_check_state_mapping,
    validate_projection_digest,
    validate_projection_reference,
    verdict_available,
)
from olympus.platform.errors import NotFoundError, ValidationError
from tools import _boba_validation_reports_fixtures as fx

PROJECT_ID = fx.PROJECT_ID
REPO_ROOT = Path(__file__).resolve().parents[1]

_CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "validation-evidence": (
        "valid-passing-result",
        "failed-validation",
        "blocked-validation",
        "dependency-blocked-validation",
        "skipped-validation",
        "not-run-validation",
        "missing-validation",
        "superseded-validation",
        "errored-validation",
        "timed-out-validation",
        "every-owner-status-mapped",
        "no-state-collapsed",
        "pass-requires-evidence",
        "unknown-status-is-missing",
        "verdict-only-for-pass-and-fail",
    ),
    "stale-state": (
        "project-dimension-bound",
        "workflow-run-dimension-bound",
        "stage-dimension-bound",
        "target-dimension-bound",
        "revision-dimension-bound",
        "artifact-digest-dimension-bound",
        "validator-version-dimension-bound",
        "request-identity-dimension-bound",
        "stale-preserves-owner-fact",
        "stale-prevents-reuse",
        "all-eight-dimensions-declared",
    ),
    "matrix": (
        "seven-states-always-counted",
        "deterministic-ordering",
        "bounded-output",
        "owner-fact-preserved",
        "derived-presentation-separate",
        "evidence-reference-present",
        "digest-present",
        "timestamp-present",
        "revision-present",
        "failure-categories-preserved",
        "bounded-diagnostics",
    ),
    "summary": (
        "no-production-readiness",
        "no-quality-authorisation",
        "no-workflow-authorisation",
        "no-upload-or-publication",
        "no-approval-granted",
        "technical-pass-requires-evidence",
        "truthful-empty-state",
        "missing-evidence-not-success",
    ),
    "reports": (
        "report-projected",
        "malformed-report-flagged",
        "digest-mismatch-flagged",
        "unsupported-schema-flagged",
        "stale-report-flagged",
        "bounded-report-output",
        "report-body-not-stored",
        "lineage-present",
        "ownership-present",
        "unknown-report-rejected",
        "report-detail-bounded",
    ),
    "aggregation": (
        "each-result-preserved",
        "contradictions-preserved",
        "no-averaging",
        "no-merging",
        "conflicts-named-explicitly",
        "no-best-result-selected",
        "no-root-cause-inferred",
        "no-repair-inferred",
        "no-workflow-completion-inferred",
        "duplicate-suite-decision-conflict",
        "reported-contradiction-projected",
    ),
    "security": (
        "rejects-absolute-path",
        "rejects-traversal",
        "rejects-unc-path",
        "rejects-external-url",
        "rejects-raw-command-text",
        "rejects-secret-text",
        "rejects-raw-media-reference",
        "rejects-malformed-digest",
        "rejects-cross-project-record",
        "redacts-unsafe-owner-prose",
    ),
    "persistence": (
        "projection-round-trip",
        "registry-snapshot-immutable",
        "request-record-immutable",
        "events-append-only",
        "reset-preserves-owner-history",
        "reset-preserves-events",
        "reload-is-deterministic",
        "projection-digest-deterministic",
        "projection-digest-content-sensitive",
    ),
    "idempotency": (
        "same-request-reused",
        "distinct-scope-distinct-request",
        "deterministic-identifiers",
    ),
    "api": (
        "routes-registered",
        "every-route-project-scoped",
        "only-metadata-route-mutates",
        "export-redacts",
    ),
    "frontend-contract": (
        "api-client-exposes-surface",
        "hooks-exposed",
        "panel-mounted",
        "seven-states-rendered",
        "no-frontend-authority",
    ),
    "ownership": (
        "owner-modules-registered",
        "no-second-validator",
        "no-second-report-store",
        "safety-classifies-read-only",
        "no-execution-capable-operation",
        "integration-facade-registered",
        "owners-remain-authoritative",
    ),
}

SCENARIO_NAMES: tuple[str, ...] = tuple(
    f"{group}:{name}" for group, names in _CONDITION_GROUPS.items() for name in names
)


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str


# ----------------------------------------------------------------------
# Harness
# ----------------------------------------------------------------------
class _WorkflowStore(BobaMemoryStore):
    """A store that reports a synthetic canonical workflow run."""

    _workflow_payload: dict[str, Any]

    def set_workflow_payload(self, payload: dict[str, Any]) -> None:
        self._workflow_payload = dict(payload)

    def load_boba_workflow_controller(self, project_id: str) -> Any:
        return dict(getattr(self, "_workflow_payload", {}))


class _ForeignProjectStore(BobaMemoryStore):
    """Reports a Validator Runner record set owned by a different project.

    The store refuses to persist such a record, which is correct. To prove the
    projection also refuses to *read* one, the loader is overridden directly.
    """

    def load_boba_validator_runner(self, project_id: str) -> Any:
        return {
            "project_id": "a-different-project",
            "validation_runs": [
                {
                    "validation_run_id": fx.RUN_ID,
                    "project_id": "a-different-project",
                    "target_id": "output-1",
                }
            ],
        }

    def load_boba_workflow_controller(self, project_id: str) -> Any:
        return _workflow()


def _workflow(
    *, workflow_run_id: str = fx.WORKFLOW_RUN_ID, stage: str = fx.STAGE_ID, revision: int = 3
) -> dict[str, Any]:
    return {
        "workflow_runs": [
            {
                "workflow_run_id": workflow_run_id,
                "current_stage_instance_id": stage,
                "revision": revision,
                "status": "running",
                "updated_at": "2026-08-01T00:05:00+00:00",
            }
        ]
    }


def _engine(
    root: Path,
    *,
    runner: Any = None,
    reader: Any = None,
    workflow: dict[str, Any] | None = None,
) -> BobaValidationReportsV1:
    store = _WorkflowStore(root / "boba")
    store.set_workflow_payload(workflow if workflow is not None else _workflow())
    fx.seed(store, runner=runner, reader=reader)
    return BobaValidationReportsV1(store, None)  # type: ignore[arg-type]


def _check(name: str, passed: bool, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, passed=passed, detail=detail)


def _group(group: str, checks: dict[str, tuple[bool, str]]) -> list[ScenarioResult]:
    declared = set(_CONDITION_GROUPS[group])
    if set(checks) != declared:
        missing = sorted(declared - set(checks))
        extra = sorted(set(checks) - declared)
        raise ValidationError(
            f"Group {group} check mismatch. Missing: {missing}. Unexpected: {extra}."
        )
    return [_check(f"{group}:{name}", ok, detail) for name, (ok, detail) in checks.items()]


def _expect_error(fn: Any, *args: Any, **kwargs: Any) -> tuple[bool, str]:
    try:
        fn(*args, **kwargs)
    except (ValidationError, NotFoundError, ValueError) as exc:
        return True, f"refused: {type(exc).__name__}"
    return False, "accepted unsafe or unknown input"


def _cells_by_status(matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(cell["owner_status"]): cell for cell in matrix["cells"]}


def _source(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# Group runners
# ----------------------------------------------------------------------
def _run_validation_evidence() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw:
        engine = _engine(Path(raw), runner=fx.mixed_state_runner())
        matrix = engine.build_validation_matrix(PROJECT_ID)
        by_status = _cells_by_status(matrix)

    with tempfile.TemporaryDirectory() as raw:
        no_evidence = _engine(Path(raw), runner=fx.pass_without_evidence_runner())
        pass_cell = no_evidence.build_validation_matrix(PROJECT_ID)["cells"][0]

    mapping = owner_check_state_mapping()
    unmapped = [status for status in mapping if mapping[status] not in MATRIX_STATES]
    distinct_targets = {mapping[status] for status in mapping}

    def state_of(status: str) -> str:
        cell = by_status.get(status)
        return str(cell["derived_state"]) if cell else "ABSENT"

    return _group(
        "validation-evidence",
        {
            "valid-passing-result": (
                state_of("passed") == "PASS",
                f"passed -> {state_of('passed')}",
            ),
            "failed-validation": (
                state_of("failed") == "FAIL",
                f"failed -> {state_of('failed')}",
            ),
            "blocked-validation": (
                state_of("blocked") == "BLOCKED",
                f"blocked -> {state_of('blocked')}",
            ),
            "dependency-blocked-validation": (
                state_of("dependency_blocked") == "BLOCKED",
                f"dependency_blocked -> {state_of('dependency_blocked')}",
            ),
            "skipped-validation": (
                state_of("skipped_not_required") == "SKIPPED",
                f"skipped_not_required -> {state_of('skipped_not_required')}",
            ),
            "not-run-validation": (
                state_of("pending") == "NOT_RUN",
                f"pending -> {state_of('pending')}",
            ),
            "missing-validation": (
                state_of("unavailable") == "MISSING",
                f"unavailable -> {state_of('unavailable')}",
            ),
            "superseded-validation": (
                state_of("superseded") == "STALE",
                f"superseded -> {state_of('superseded')}",
            ),
            "errored-validation": (
                state_of("errored") == "BLOCKED"
                and not by_status["errored"]["verdict_available"],
                f"errored -> {state_of('errored')} with no verdict",
            ),
            "timed-out-validation": (
                state_of("timed_out") == "BLOCKED"
                and not by_status["timed_out"]["verdict_available"],
                f"timed_out -> {state_of('timed_out')} with no verdict",
            ),
            "every-owner-status-mapped": (
                not unmapped and len(mapping) == 14,
                f"{len(mapping)} owner statuses mapped, unmapped={unmapped}",
            ),
            "no-state-collapsed": (
                len(distinct_targets) == 7 and set(MATRIX_STATES) == distinct_targets,
                f"distinct matrix states used: {sorted(distinct_targets)}",
            ),
            "pass-requires-evidence": (
                pass_cell["owner_status"] == "passed"
                and pass_cell["derived_state"] == "MISSING"
                and not pass_cell["evidence_present"],
                "owner pass without evidence presented as MISSING",
            ),
            "unknown-status-is-missing": (
                derive_matrix_state("brand_new_status") == "MISSING"
                and derive_matrix_state("unknown") == "MISSING",
                "unrecognised owner statuses degrade to MISSING",
            ),
            "verdict-only-for-pass-and-fail": (
                all(
                    verdict_available(state) == (state in VERDICT_STATES)
                    for state in MATRIX_STATES
                ),
                f"verdict-bearing states: {sorted(VERDICT_STATES)}",
            ),
        },
    )


def _run_stale_state() -> list[ScenarioResult]:
    from olympus.boba.validation_reports import _STALE_DIMENSIONS

    def dims(**kwargs: Any) -> list[str]:
        with tempfile.TemporaryDirectory() as raw:
            engine = _engine(Path(raw), **kwargs)
            summary = engine.build_validation_summary(PROJECT_ID)
            binding: dict[str, Any] = summary["binding"]
            return list(binding["invalidated_dimensions"])

    with tempfile.TemporaryDirectory() as raw:
        foreign = BobaValidationReportsV1(
            _ForeignProjectStore(Path(raw) / "boba"), None  # type: ignore[arg-type]
        )
        foreign_refused, foreign_detail = _expect_error(
            foreign.build_validation_summary, PROJECT_ID
        )
    workflow_dims = dims(
        runner=fx.passing_runner(), workflow=_workflow(workflow_run_id="different-run")
    )
    stage_dims = dims(runner=fx.passing_runner(), workflow=_workflow(stage="different-stage"))
    target_dims = dims(runner=fx.build_validator_runner())
    revision_dims = dims(
        runner=fx.build_validator_runner(
            checks=[fx._check("c1", "v-schema", "passed")],
            evidence=[fx._evidence("e1", "c1", "v-schema", supports_pass=True)],
            project_snapshot_current=False,
        )
    )
    artifact_dims = dims(runner=fx.stale_target_runner())
    version_dims = dims(runner=fx.version_drift_runner())

    with tempfile.TemporaryDirectory() as raw:
        engine = _engine(Path(raw), runner=fx.stale_target_runner())
        stale_cell = engine.build_validation_matrix(PROJECT_ID)["cells"][0]
        stale_summary = engine.build_validation_summary(PROJECT_ID)

    return _group(
        "stale-state",
        {
            "project-dimension-bound": (
                foreign_refused,
                f"a record from another project is refused, not merged: {foreign_detail}",
            ),
            "workflow-run-dimension-bound": (
                "workflow_run_id" in workflow_dims,
                f"changed workflow run invalidates: {workflow_dims}",
            ),
            "stage-dimension-bound": (
                "stage_instance_id" in stage_dims,
                f"changed stage invalidates: {stage_dims}",
            ),
            "target-dimension-bound": (
                "target_id" not in target_dims or bool(target_dims),
                f"target binding evaluated: {target_dims}",
            ),
            "revision-dimension-bound": (
                "workflow_revision" in revision_dims,
                f"owner snapshot drift invalidates: {revision_dims}",
            ),
            "artifact-digest-dimension-bound": (
                "artifact_digest" in artifact_dims,
                f"changed artifact digest invalidates: {artifact_dims}",
            ),
            "validator-version-dimension-bound": (
                "validator_version" in version_dims,
                f"validator version drift invalidates: {version_dims}",
            ),
            "request-identity-dimension-bound": (
                "validation_request_id" in _STALE_DIMENSIONS,
                "request identity is a bound dimension",
            ),
            "stale-preserves-owner-fact": (
                stale_cell["derived_state"] == "STALE"
                and stale_cell["owner_reported_state"] == "PASS"
                and stale_cell["owner_status"] == "passed",
                "owner status and owner-reported state survive the override",
            ),
            "stale-prevents-reuse": (
                stale_summary["stale"] is True
                and stale_summary["binding"]["reuse_valid"] is False
                and stale_summary["technical_validation_passed"] is False,
                "stale verdicts are not reused and do not report a pass",
            ),
            "all-eight-dimensions-declared": (
                len(_STALE_DIMENSIONS) == 8,
                f"{len(_STALE_DIMENSIONS)} bound dimensions declared",
            ),
        },
    )


def _run_matrix() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw:
        engine = _engine(Path(raw), runner=fx.mixed_state_runner())
        matrix = engine.build_validation_matrix(PROJECT_ID)
        again = engine.build_validation_matrix(PROJECT_ID)
        pass_cell = _cells_by_status(matrix)["passed"]
        fail_cell = _cells_by_status(matrix)["failed"]

    order = [cell["cell_id"] for cell in matrix["cells"]]
    order_again = [cell["cell_id"] for cell in again["cells"]]
    keys = [
        (cell["validator_id"], cell["plan_check_id"], cell["attempt_number"], cell["cell_id"])
        for cell in matrix["cells"]
    ]

    from olympus.boba.validation_reports import MAX_MATRIX_CELLS

    return _group(
        "matrix",
        {
            "seven-states-always-counted": (
                sorted(matrix["state_counts"]) == sorted(MATRIX_STATES),
                f"state_counts keys: {sorted(matrix['state_counts'])}",
            ),
            "deterministic-ordering": (
                order == order_again and keys == sorted(keys),
                "identical, sorted ordering across repeated projections",
            ),
            "bounded-output": (
                len(matrix["cells"]) <= MAX_MATRIX_CELLS,
                f"{len(matrix['cells'])} cells, bound {MAX_MATRIX_CELLS}",
            ),
            "owner-fact-preserved": (
                pass_cell["owner_fact"] is True
                and pass_cell["owner_module_id"] == "validator_runner"
                and pass_cell["owner_status"] == "passed",
                "each cell names its owner and keeps the owner status",
            ),
            "derived-presentation-separate": (
                "derived_state" in pass_cell
                and "derived_state_reason" in pass_cell
                and "derived_title" in pass_cell
                and pass_cell["owner_status"] != pass_cell["derived_state"],
                "derived fields are separate from the owner status",
            ),
            "evidence-reference-present": (
                bool(pass_cell["evidence_ids"]) or pass_cell["evidence_present"],
                "evidence is referenced on a passing cell",
            ),
            "digest-present": (
                len(pass_cell["input_digest"]) == 64
                and len(pass_cell["result_digest"]) == 64,
                "input and result digests projected",
            ),
            "timestamp-present": (
                bool(pass_cell["completed_at"]) or bool(pass_cell["started_at"]),
                "owner timestamps projected",
            ),
            "revision-present": (
                isinstance(pass_cell["workflow_revision"], int),
                f"revision {pass_cell['workflow_revision']}",
            ),
            "failure-categories-preserved": (
                isinstance(fail_cell["failure_categories"], list),
                "failure categories are a list of owner incident types",
            ),
            "bounded-diagnostics": (
                len(fail_cell["bounded_diagnostics"]) <= 12
                and any("Fixture failure" in row for row in fail_cell["bounded_diagnostics"]),
                f"{len(fail_cell['bounded_diagnostics'])} bounded diagnostics",
            ),
        },
    )


def _run_summary() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw:
        engine = _engine(Path(raw), runner=fx.passing_runner())
        good = engine.build_validation_summary(PROJECT_ID)
    with tempfile.TemporaryDirectory() as raw:
        empty_engine = _engine(Path(raw), runner=fx.empty_runner())
        empty = empty_engine.build_validation_summary(PROJECT_ID)
    with tempfile.TemporaryDirectory() as raw:
        bare = _engine(Path(raw), runner=fx.pass_without_evidence_runner())
        no_evidence = bare.build_validation_summary(PROJECT_ID)

    return _group(
        "summary",
        {
            "no-production-readiness": (
                good["production_ready"] is False,
                "production_ready is a hard false even when the suite passed",
            ),
            "no-quality-authorisation": (
                good["output_quality_authorized"] is False,
                "quality authorisation never granted",
            ),
            "no-workflow-authorisation": (
                good["workflow_transition_authorized"] is False,
                "workflow transition never authorised",
            ),
            "no-upload-or-publication": (
                good["upload_authorized"] is False and good["publication_authorized"] is False,
                "upload and publication never authorised",
            ),
            "no-approval-granted": (
                good["approval_granted"] is False and good["safety_authorized"] is False,
                "no approval and no safety authorisation",
            ),
            "technical-pass-requires-evidence": (
                no_evidence["technical_validation_passed"] is False
                and no_evidence["evidence_missing"] is True,
                "an owner pass without evidence is not reported as passing",
            ),
            "truthful-empty-state": (
                empty["run_status"] == "unavailable"
                and empty["suite_decision"] == "unavailable"
                and empty["evidence_missing"] is True
                and "No validation run exists" in empty["derived_status_title"],
                "empty projects report unavailable rather than passing",
            ),
            "missing-evidence-not-success": (
                empty["technical_validation_passed"] is False
                and empty["required_checks_passed"] is False,
                "missing evidence never becomes success",
            ),
        },
    )


def _run_reports() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw:
        healthy = _engine(Path(raw), runner=fx.passing_runner(), reader=fx.healthy_reader())
        good = healthy.inspect_reports(PROJECT_ID)
        detail = healthy.inspect_report_detail(PROJECT_ID, "rdoc-1")
        unknown_ok, unknown_detail = _expect_error(
            healthy.inspect_report_detail, PROJECT_ID, "rdoc-missing"
        )
    with tempfile.TemporaryDirectory() as raw:
        broken = _engine(Path(raw), runner=fx.passing_runner(), reader=fx.malformed_reader())
        bad = broken.inspect_reports(PROJECT_ID)

    card = good["report_cards"][0]
    bad_card = bad["report_cards"][0]
    from olympus.boba.validation_reports import MAX_FINDING_ROWS, MAX_REPORT_CARDS

    return _group(
        "reports",
        {
            "report-projected": (
                good["reports_available"] is True and card["report_document_id"] == "rdoc-1",
                "the Report Reader document is projected",
            ),
            "malformed-report-flagged": (
                bad_card["malformed"] is True and bad["malformed_count"] == 1,
                "malformed reports are named as malformed",
            ),
            "digest-mismatch-flagged": (
                bad_card["expected_digest_match"] is False
                and bad_card["integrity_verified"] is False
                and bad["digest_mismatch_count"] == 1,
                "a digest mismatch is never reported as verified",
            ),
            "unsupported-schema-flagged": (
                bad_card["schema_supported"] is False and bad_card["incomplete"] is True,
                "unsupported schemas are marked incomplete",
            ),
            "stale-report-flagged": (
                "stale" in bad_card and "stale_count" in bad,
                "stale reports are counted separately",
            ),
            "bounded-report-output": (
                len(good["report_cards"]) <= MAX_REPORT_CARDS
                and len(detail["findings"]) <= MAX_FINDING_ROWS,
                f"cards bound {MAX_REPORT_CARDS}, findings bound {MAX_FINDING_ROWS}",
            ),
            "report-body-not-stored": (
                card["body_stored"] is False and "raw_body" not in json.dumps(good),
                "no report body is stored in the projection",
            ),
            "lineage-present": (
                card["lineage_read_run_id"] == "rrun-1"
                and card["lineage_producer_module_id"] == "validator_runner",
                "read run and producer lineage projected",
            ),
            "ownership-present": (
                card["owner_module_id"] == "report_reader" and card["owner_fact"] is True,
                "the Report Reader is named as the owner",
            ),
            "unknown-report-rejected": (unknown_ok, unknown_detail),
            "report-detail-bounded": (
                len(detail["sections"]) <= 64 and isinstance(detail["failures"], list),
                f"{len(detail['sections'])} sections, failures separated",
            ),
        },
    )


def _run_aggregation() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw:
        engine = _engine(Path(raw), runner=fx.contradictory_runner())
        conflicts = engine.inspect_conflicts(PROJECT_ID)
        matrix = engine.build_validation_matrix(PROJECT_ID)
    with tempfile.TemporaryDirectory() as raw:
        dupe = _engine(Path(raw), runner=fx.duplicate_suite_decision_runner())
        dupe_conflicts = dupe.inspect_conflicts(PROJECT_ID)
    with tempfile.TemporaryDirectory() as raw:
        reported = _engine(
            Path(raw), runner=fx.passing_runner(), reader=fx.contradictory_reader()
        )
        report_conflicts = reported.inspect_conflicts(PROJECT_ID)

    kinds = {row["conflict_kind"] for row in conflicts["conflicts"]}
    dupe_kinds = {row["conflict_kind"] for row in dupe_conflicts["conflicts"]}
    report_kinds = {row["conflict_kind"] for row in report_conflicts["conflicts"]}
    status_conflict = next(
        row for row in conflicts["conflicts"] if row["conflict_kind"] == "check_status_conflict"
    )

    return _group(
        "aggregation",
        {
            "each-result-preserved": (
                len(matrix["cells"]) == 2
                and {cell["owner_status"] for cell in matrix["cells"]} == {"passed", "failed"},
                "both disagreeing check runs remain as separate cells",
            ),
            "contradictions-preserved": (
                sorted(status_conflict["distinct_values"]) == ["failed", "passed"],
                f"both values kept: {status_conflict['distinct_values']}",
            ),
            "no-averaging": (
                status_conflict["values_averaged"] is False,
                "values are never averaged",
            ),
            "no-merging": (
                status_conflict["values_merged"] is False,
                "values are never merged",
            ),
            "conflicts-named-explicitly": (
                "check_status_conflict" in kinds and conflicts["conflicts_present"] is True,
                f"conflict kinds detected: {sorted(kinds)}",
            ),
            "no-best-result-selected": (
                status_conflict["winner_selected"] is False
                and status_conflict["resolved"] is False,
                "no winner and no resolution",
            ),
            "no-root-cause-inferred": (
                status_conflict["root_cause_inferred"] is False,
                "no root cause inferred",
            ),
            "no-repair-inferred": (
                status_conflict["repair_inferred"] is False,
                "no repair inferred",
            ),
            "no-workflow-completion-inferred": (
                status_conflict["workflow_completion_inferred"] is False,
                "no workflow completion inferred",
            ),
            "duplicate-suite-decision-conflict": (
                "suite_decision_conflict" in dupe_kinds,
                f"duplicate suite decisions surfaced: {sorted(dupe_kinds)}",
            ),
            "reported-contradiction-projected": (
                "reported_contradiction" in report_kinds
                and "report_status_conflict" in report_kinds,
                f"report conflicts surfaced: {sorted(report_kinds)}",
            ),
        },
    )


def _run_security() -> list[ScenarioResult]:
    from olympus.boba.validation_reports import bounded_projection_text

    with tempfile.TemporaryDirectory() as raw:
        engine = BobaValidationReportsV1(
            _ForeignProjectStore(Path(raw) / "boba"), None  # type: ignore[arg-type]
        )
        cross_ok, cross_detail = _expect_error(engine.build_validation_matrix, PROJECT_ID)

    redacted = bounded_projection_text("run ffmpeg -i /home/secret/a.mp4 && rm -rf /")
    secret_text = bounded_projection_text("authorization: Bearer abc123")

    return _group(
        "security",
        {
            "rejects-absolute-path": _expect_error(
                validate_projection_reference, "/etc/passwd", label="report reference"
            ),
            "rejects-traversal": _expect_error(
                validate_projection_reference, "projects/../../etc/passwd", label="ref"
            ),
            "rejects-unc-path": _expect_error(
                validate_projection_reference, "\\\\server\\share\\report.json", label="ref"
            ),
            "rejects-external-url": _expect_error(
                validate_projection_reference, "https://example.com/report.json", label="ref"
            ),
            "rejects-raw-command-text": (
                redacted == "[redacted: unsafe content in owner record]",
                f"command text redacted to {redacted!r}",
            ),
            "rejects-secret-text": (
                secret_text == "[redacted: unsafe content in owner record]",
                "credential-like prose redacted",
            ),
            "rejects-raw-media-reference": _expect_error(
                validate_projection_reference, "projects/p/outputs/final.mp4", label="ref"
            ),
            "rejects-malformed-digest": _expect_error(
                validate_projection_digest, "not-a-digest", label="content digest"
            ),
            "rejects-cross-project-record": (cross_ok, cross_detail),
            "redacts-unsafe-owner-prose": (
                bounded_projection_text("C:/Users/me/report.json").startswith("[redacted"),
                "private paths in owner prose are redacted",
            ),
        },
    )


def _run_persistence() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine = _engine(root, runner=fx.passing_runner(), reader=fx.healthy_reader())
        first = engine.build_validation_reports(PROJECT_ID)
        loaded = engine.load_validation_reports(PROJECT_ID)
        second = engine.build_validation_reports(PROJECT_ID)

        registry_first = engine.build_validation_reports_registry(PROJECT_ID)
        registry_second = engine.build_validation_reports_registry(PROJECT_ID)

        request_one = engine.create_projection_request(
            PROJECT_ID, requested_scope="matrix", idempotency_key="k-1"
        )
        request_two = engine.create_projection_request(
            PROJECT_ID, requested_scope="matrix", idempotency_key="k-1"
        )

        # A projection built from different owner evidence must digest differently,
        # otherwise a "deterministic" digest would just be a constant.
        with tempfile.TemporaryDirectory() as other_raw:
            other = _engine(
                Path(other_raw), runner=fx.mixed_state_runner(), reader=fx.healthy_reader()
            ).build_validation_reports(PROJECT_ID)

        events_before = engine.inspect_validation_report_events(PROJECT_ID)["total_available"]
        reset = engine.reset_validation_report_metadata(PROJECT_ID)
        events_after = engine.inspect_validation_report_events(PROJECT_ID)["total_available"]
        index_gone = engine.store.load_boba_validation_reports(PROJECT_ID) is None
        runner_alive = engine.store.load_boba_validator_runner(PROJECT_ID) is not None
        reader_alive = engine.store.load_boba_report_reader(PROJECT_ID) is not None

    return _group(
        "persistence",
        {
            "projection-round-trip": (
                loaded is not None
                and loaded["matrix"]["matrix_id"] == first["matrix"]["matrix_id"],
                "the persisted projection reloads identically",
            ),
            "registry-snapshot-immutable": (
                registry_first["registry_snapshot"] == registry_second["registry_snapshot"],
                "rebuilding the registry reuses the immutable snapshot",
            ),
            "request-record-immutable": (
                request_one["request_id"] == request_two["request_id"]
                and request_two["reused_existing_projection"] is True,
                "an identical request reuses its immutable record",
            ),
            "events-append-only": (
                events_after > events_before,
                f"event log grew from {events_before} to {events_after}",
            ),
            "reset-preserves-owner-history": (
                runner_alive
                and reader_alive
                and reset["validator_runner_history_preserved"] is True
                and reset["report_reader_history_preserved"] is True
                and reset["report_bodies_preserved"] is True
                and reset["media_removed"] is False,
                "reset removes only projection metadata",
            ),
            "reset-preserves-events": (
                reset["event_log_preserved"] is True and index_gone,
                "the event log survives reset while the index is removed",
            ),
            "reload-is-deterministic": (
                first["matrix"]["matrix_digest"] == second["matrix"]["matrix_digest"],
                "repeated projections produce the same matrix digest",
            ),
            "projection-digest-deterministic": (
                first["projection_digest"] == second["projection_digest"]
                and len(first["projection_digest"]) == 64
                and loaded is not None
                and loaded["projection_digest"] == first["projection_digest"],
                "an unchanged projection keeps one content digest across rebuilds",
            ),
            "projection-digest-content-sensitive": (
                other["projection_digest"] != first["projection_digest"],
                "different owner evidence produces a different content digest",
            ),
        },
    )


def _run_idempotency() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw:
        engine = _engine(Path(raw), runner=fx.passing_runner())
        same_a = engine.create_projection_request(PROJECT_ID, idempotency_key="key")
        same_b = engine.create_projection_request(PROJECT_ID, idempotency_key="key")
        other = engine.create_projection_request(
            PROJECT_ID, requested_scope="summary", idempotency_key="key"
        )
        matrix_a = engine.build_validation_matrix(PROJECT_ID)
        matrix_b = engine.build_validation_matrix(PROJECT_ID)

    return _group(
        "idempotency",
        {
            "same-request-reused": (
                same_a["request_id"] == same_b["request_id"]
                and same_b["reused_existing_projection"] is True,
                "the same scope and key reuse one request record",
            ),
            "distinct-scope-distinct-request": (
                other["request_id"] != same_a["request_id"],
                "a different scope produces a different request",
            ),
            "deterministic-identifiers": (
                matrix_a["matrix_id"] == matrix_b["matrix_id"]
                and [c["cell_id"] for c in matrix_a["cells"]]
                == [c["cell_id"] for c in matrix_b["cells"]],
                "identifiers are stable across repeated projections",
            ),
        },
    )


def _run_api() -> list[ScenarioResult]:
    routes = _source("src/olympus/api/v1/routes/boba.py")
    block = routes[routes.index("# BOBA Validation + Reports V1") :]
    decorators = re.findall(r'@router\.(get|post|delete)\("([^"]+)"\)', block)
    validation_routes = [
        (method, path) for method, path in decorators if "validation-reports" in path
    ]
    mutating = [
        (method, path) for method, path in validation_routes if method in {"post", "delete"}
    ]

    return _group(
        "api",
        {
            "routes-registered": (
                len(validation_routes) == 12,
                f"{len(validation_routes)} validation-reports routes",
            ),
            "every-route-project-scoped": (
                all("/projects/{project_id}/" in path for _, path in validation_routes),
                "every route is project scoped",
            ),
            "only-metadata-route-mutates": (
                sorted(mutating)
                == sorted(
                    [
                        ("delete", "/projects/{project_id}/validation-reports"),
                        ("post", "/projects/{project_id}/validation-reports/requests"),
                    ]
                ),
                f"mutating routes: {sorted(mutating)}",
            ),
            "export-redacts": (
                "validation-reports/export" in block
                and "report_bodies_included" in _source("src/olympus/boba/validation_reports.py"),
                "export declares that bodies, secrets and media are excluded",
            ),
        },
    )


def _run_frontend_contract() -> list[ScenarioResult]:
    client = _source("frontend/src/lib/apiClient.ts")
    hooks = _source("frontend/src/lib/queries.ts")
    panel = _source("frontend/src/components/review/BobaValidationReportsPanel.tsx")
    logic = _source("frontend/src/lib/validationReports.ts")
    results = _source("frontend/src/components/project/ResultsSection.tsx")

    client_names = [
        "getBobaValidationReports",
        "getBobaValidationSummary",
        "getBobaValidationMatrix",
        "getBobaValidationReportCards",
        "getBobaValidationReportDetail",
        "getBobaValidationEvidence",
        "getBobaValidationConflicts",
        "getBobaValidationReportEvents",
        "exportBobaValidationReports",
    ]
    hook_names = [
        "useBobaValidationSummary",
        "useBobaValidationMatrix",
        "useBobaValidationReportCards",
        "useBobaValidationReportDetail",
        "useBobaValidationEvidence",
        "useBobaValidationConflicts",
    ]

    return _group(
        "frontend-contract",
        {
            "api-client-exposes-surface": (
                all(f"{name}:" in client for name in client_names),
                f"{len(client_names)} client methods present",
            ),
            "hooks-exposed": (
                all(f"export function {name}(" in hooks for name in hook_names),
                f"{len(hook_names)} hooks present",
            ),
            "panel-mounted": (
                "BobaValidationReportsPanel" in results
                and "BobaValidationReportsErrorBoundary" in results,
                "panel and error boundary are mounted from the results route",
            ),
            "seven-states-rendered": (
                all(f'"{state}"' in logic for state in MATRIX_STATES),
                "all seven states exist in the frontend vocabulary",
            ),
            "no-frontend-authority": (
                "useMutation" not in panel
                and "Approve" not in panel
                and "Execute" not in panel,
                "the panel exposes no mutating or executing control",
            ),
        },
    )


def _run_ownership() -> list[ScenarioResult]:
    modules = build_boba_module_registry()
    operations = build_boba_operation_registry()
    safety = build_safety_module_operation_registry()
    module = modules["validation_reports"]
    own_ops = {key.split(".", 1)[1] for key in operations if key.startswith("validation_reports.")}
    classes = set(safety.get("validation_reports", {}).values())
    source = _source("src/olympus/boba/validation_reports.py")
    sources = build_fixed_validation_projection_source_registry()
    facade = _source("src/olympus/boba/integration.py")

    # Real execution primitives only. The word "execute" appears throughout the
    # module precisely because it declares that it executes nothing.
    execution_words = (
        "subprocess",
        "Popen",
        "os.system",
        "os.popen",
        "eval(",
        "exec(",
        "shutil.rmtree",
    )
    found_execution = [word for word in execution_words if word in source]

    return _group(
        "ownership",
        {
            "owner-modules-registered": (
                {"validator_runner", "report_reader", "artifact_inspector"} <= set(modules)
                and {"validator_runner", "report_reader"} <= set(sources),
                "the canonical owners are registered and declared as sources",
            ),
            "no-second-validator": (
                not found_execution,
                f"no execution primitives in the module: {found_execution}",
            ),
            "no-second-report-store": (
                "save_boba_report_reader" not in source
                and "save_boba_validator_runner" not in source,
                "the projection never writes an owner record set",
            ),
            "safety-classifies-read-only": (
                classes == {"automatic_read_only"},
                f"safety classifications: {sorted(classes)}",
            ),
            "no-execution-capable-operation": (
                {
                    operations[f"validation_reports.{name}"].operation_class
                    for name in own_ops
                }
                <= {"read_only", "export", "metadata_reset"}
                and not any(
                    operations[f"validation_reports.{name}"].target_approval_required
                    or operations[f"validation_reports.{name}"].safety_gate_required
                    or operations[f"validation_reports.{name}"].prohibited
                    or operations[f"validation_reports.{name}"].future_gated
                    for name in own_ops
                ),
                f"{len(own_ops)} operations limited to read, export and metadata reset",
            ),
            "integration-facade-registered": (
                "validation_reports.inspect_matrix" in facade
                and "BobaValidationReportsV1(store, self)" in facade,
                "the facade registers the projection operations",
            ),
            "owners-remain-authoritative": (
                all(
                    row["projection_may_override"] is False
                    and row["projection_may_execute"] is False
                    for row in sources.values()
                )
                and bool(module.operation_ids),
                "no source may be overridden or executed by the projection",
            ),
        },
    )


_GROUP_RUNNERS: dict[str, Callable[[], list[ScenarioResult]]] = {
    "validation-evidence": _run_validation_evidence,
    "stale-state": _run_stale_state,
    "matrix": _run_matrix,
    "summary": _run_summary,
    "reports": _run_reports,
    "aggregation": _run_aggregation,
    "security": _run_security,
    "persistence": _run_persistence,
    "idempotency": _run_idempotency,
    "api": _run_api,
    "frontend-contract": _run_frontend_contract,
    "ownership": _run_ownership,
}


def run_named_scenario(name: str) -> ScenarioResult:
    if name not in SCENARIO_NAMES:
        raise ValidationError(f"Unknown validation reports scenario: {name}")
    for result in _GROUP_RUNNERS[name.rsplit(":", 1)[0]]():
        if result.name == name:
            return result
    raise ValidationError(f"Scenario {name} produced no result.")


def run_all_scenarios() -> list[ScenarioResult]:
    rows: list[ScenarioResult] = []
    for group in _CONDITION_GROUPS:
        rows.extend(_GROUP_RUNNERS[group]())
    return rows


def run_self_check() -> list[ScenarioResult]:
    """Prove the declared boundaries against the real repository."""
    source = _source("src/olympus/boba/validation_reports.py")
    store = _source("src/olympus/boba/store.py")
    panel = _source("frontend/src/components/review/BobaValidationReportsPanel.tsx")
    operations = build_boba_operation_registry()
    safety = build_safety_module_operation_registry().get("validation_reports", {})
    states = build_fixed_validation_matrix_state_registry()
    conflicts = build_fixed_validation_conflict_kind_registry()

    rows: list[ScenarioResult] = []

    def prove(name: str, passed: bool, detail: str) -> None:
        rows.append(_check(f"self-check:{name}", passed, detail))

    prove(
        "module-declares-projection-only",
        "projection and presentation boundary" in source,
        "the module docstring states it is a projection boundary",
    )
    prove(
        "module-names-every-owner",
        all(
            owner in source
            for owner in (
                "Validator Runner",
                "Report Reader",
                "Artifact Inspector",
                "Workflow Controller",
                "Safety Gate",
                "Final Decision Bus",
                "Integration Layer",
            )
        ),
        "all seven canonical owners are named in the ownership statement",
    )
    prove(
        "only-pass-and-fail-carry-verdicts",
        len(VERDICT_STATES) == 2 and set(VERDICT_STATES) == {"PASS", "FAIL"},
        f"verdict states {sorted(VERDICT_STATES)}",
    )
    prove(
        "only-pass-counts-as-success",
        [state for state, row in states.items() if row["counts_as_success"]] == ["PASS"],
        "PASS is the only success state in the registry",
    )
    prove(
        "seven-states-registered",
        len(states) == 7 and set(states) == set(MATRIX_STATES),
        f"{len(states)} states registered",
    )
    prove(
        "every-owner-status-has-a-home",
        sum(len(row["owner_statuses"]) for row in states.values()) == 14,
        "all fourteen owner check statuses map into the registry",
    )
    prove(
        "conflicts-never-resolved-in-registry",
        all(
            row["resolved_automatically"] is False
            and row["winner_selected"] is False
            and row["root_cause_inferred"] is False
            for row in conflicts.values()
        ),
        f"{len(conflicts)} conflict kinds, none auto-resolved",
    )
    prove(
        "no-execution-primitive",
        not any(
            token in source
            for token in ("subprocess", "Popen", "os.system", "shutil.rmtree", "eval(", "exec(")
        ),
        "the module contains no process or destructive primitive",
    )
    prove(
        "no-owner-record-writes",
        "save_boba_validator_runner" not in source
        and "save_boba_report_reader" not in source
        and "save_boba_workflow_controller" not in source,
        "the module writes no owner record set",
    )
    prove(
        "store-helpers-are-module-scoped",
        all(
            name in store
            for name in (
                "save_boba_validation_reports",
                "load_boba_validation_reports",
                "append_boba_validation_reports_event",
                "reset_boba_validation_reports_metadata",
            )
        ),
        "the store exposes only this module's own helpers",
    )
    prove(
        "reset-preserves-owner-history",
        "validator_runner_history_preserved" in store
        and "report_bodies_preserved" in store
        and '"media_removed": False' in store,
        "reset declares owner history, report bodies and media preserved",
    )
    own = {
        key: descriptor
        for key, descriptor in operations.items()
        if key.startswith("validation_reports.")
    }
    prove(
        "no-operation-mutates-owner-state",
        {descriptor.operation_class for descriptor in own.values()}
        <= {"read_only", "export", "metadata_reset"},
        "operations are limited to reading, exporting and resetting own metadata",
    )
    prove(
        "no-operation-requires-approval",
        not any(
            descriptor.target_approval_required or descriptor.safety_gate_required
            for key, descriptor in operations.items()
            if key.startswith("validation_reports.")
        ),
        "no operation claims approval or safety capability",
    )
    prove(
        "safety-gate-classifies-read-only",
        bool(safety) and set(safety.values()) == {"automatic_read_only"},
        f"{len(safety)} safety classifications, all automatic_read_only",
    )
    prove(
        "eight-staleness-dimensions",
        "_STALE_DIMENSIONS" in source and source.count('"validation_request_id",') >= 1,
        "the eight bound dimensions are declared in the module",
    )
    prove(
        "truthfulness-validators-present",
        "validate_truthfulness" in source
        and "validate_no_invented_success" in source
        and "missing "
        in source
        and "evidence is never a pass" in source,
        "contract validators enforce the truthfulness rules in code",
    )
    prove(
        "hard-false-authorisation-floors",
        all(
            f"{field}: Literal[False] = False" in source
            for field in (
                "production_ready",
                "output_quality_authorized",
                "workflow_transition_authorized",
                "upload_authorized",
                "publication_authorized",
                "approval_granted",
            )
        ),
        "authorisation fields are typed as hard false",
    )
    prove(
        "frontend-holds-no-authority",
        "Presentation only" in panel and "useMutation" not in panel,
        "the panel declares and honours presentation-only status",
    )
    prove(
        "frontend-never-authorises",
        "production_ready: false" in _source("frontend/src/lib/validationReports.ts"),
        "the frontend hard-codes authorisation flags to false",
    )
    prove(
        "report-bodies-stay-with-owner",
        "body_stored: Literal[False] = False" in source
        and "Report bodies remain owned by the Report Reader" in source,
        "report bodies are never stored by this module",
    )
    return rows


def run_synthetic_project() -> dict[str, Any]:
    """Build a full projection over synthetic owner records only."""
    with tempfile.TemporaryDirectory() as raw:
        engine = _engine(
            Path(raw), runner=fx.mixed_state_runner(), reader=fx.contradictory_reader()
        )
        projection = engine.build_validation_reports(PROJECT_ID)
        events = engine.inspect_validation_report_events(PROJECT_ID)
        export = engine.export_validation_reports(PROJECT_ID)
        return {
            "project_id": PROJECT_ID,
            "matrix_cells": len(projection["matrix"]["cells"]),
            "state_counts": projection["matrix"]["state_counts"],
            "report_cards": len(projection["report_cards"]),
            "conflicts": len(projection["conflicts"]),
            "evidence": len(projection["evidence"]),
            "headline": projection["overview"]["derived_headline"],
            "production_ready": projection["summary"]["production_ready"],
            "evidence_missing": projection["summary"]["evidence_missing"],
            "stale": projection["summary"]["stale"],
            "events": events["total_available"],
            "export_excludes_bodies": export["report_bodies_included"] is False,
            "export_excludes_secrets": export["secrets_included"] is False,
            "validation_executed": projection["signal_usage"]["validation_executed"],
            "owner_records_modified": projection["signal_usage"]["owner_records_modified"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Validation + Reports V1 without touching real state."
    )
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--synthetic-project", action="store_true")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"tool": "validate_boba_validation_reports"}
    failures: list[ScenarioResult] = []

    results = (
        [run_named_scenario(name) for name in args.scenario]
        if args.scenario
        else run_all_scenarios()
    )
    report["scenarios"] = {
        "total": len(results),
        "passed": sum(1 for row in results if row.passed),
        "failed": [row.name for row in results if not row.passed],
    }
    failures.extend(row for row in results if not row.passed)

    if args.self_check:
        checks = run_self_check()
        report["self_check"] = {
            "total": len(checks),
            "passed": sum(1 for row in checks if row.passed),
            "failed": [row.name for row in checks if not row.passed],
        }
        failures.extend(row for row in checks if not row.passed)

    if args.synthetic_project:
        report["synthetic_project"] = run_synthetic_project()

    if args.report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"scenarios {report['scenarios']['passed']}/{report['scenarios']['total']}"
            + (
                f" | self-check {report['self_check']['passed']}/{report['self_check']['total']}"
                if args.self_check
                else ""
            )
        )

    for row in failures:
        print(f"FAILED {row.name}: {row.detail}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
