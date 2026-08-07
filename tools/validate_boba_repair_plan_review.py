"""Offline validator for BOBA Repair Plan Panel V1.

Every scenario runs against synthetic canonical records built through the real
owner contracts. The validator never generates a repair plan, revises one,
approves or rejects one, executes a plan or a step, runs a command, restores a
checkpoint, restarts a process, transitions a workflow, modifies code or
artifacts, uploads or publishes.

Usage:
    python tools/validate_boba_repair_plan_review.py --self-check --report
    python tools/validate_boba_repair_plan_review.py --scenario steps:command-withheld
    python tools/validate_boba_repair_plan_review.py --synthetic-project
    python tools/validate_boba_repair_plan_review.py \
        --project-root work/boba --project-id my-project
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.repair_plan_review import (
    COMMAND_WITHHELD_NOTICE,
    MAX_COMPARISON_PLANS,
    NOT_EXECUTABLE_NOTICE,
    PRIVATE_PATH_NOTICE,
    SOURCE_RETAINED_NOTICE,
    SUPPORTED_REPAIR_PLAN_SCHEMA_ID,
    BobaRepairPlanReviewV1,
    bounded_step_description,
    build_fixed_repair_plan_action_registry,
    build_fixed_repair_section_registry,
    build_fixed_repair_source_registry,
    repair_plan_queue_priority_tiers,
    repair_risk_dimensions,
    source_holds_command,
    source_holds_private_path,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError
from tools._boba_repair_plan_review_fixtures import (
    COMMAND_TARGET,
    PLAN_CHECKPOINT,
    PLAN_CODE_CHANGE,
    PLAN_DESTRUCTIVE,
    PLAN_REVERSIBLE,
    PRIVATE_PATH_TARGET,
    REPAIR_CASE_ID,
    SHELL_TARGET,
    seed_project,
    synthetic_analysis_case,
    synthetic_approval_gate,
    synthetic_planning_case,
    synthetic_repair_planner_set,
    synthetic_risk_assessment,
    synthetic_rollback_plan,
    synthetic_root_cause_set,
    synthetic_step,
    synthetic_strategy,
    synthetic_validation_plan,
)

PROJECT_ID = "repair-plan-review-project"
_ACK = "repair_plan_action_acknowledge_linked_incident_v1"
_UNAVAILABLE_ACTIONS = (
    "repair_plan_action_acknowledge_plan_v1",
    "repair_plan_action_approve_plan_v1",
    "repair_plan_action_reject_plan_v1",
    "repair_plan_action_request_plan_revision_v1",
    "repair_plan_action_request_plan_regeneration_v1",
    "repair_plan_action_request_recovery_attempt_v1",
    "repair_plan_action_request_tool_retry_v1",
    "repair_plan_action_request_checkpoint_restore_v1",
    "repair_plan_action_escalate_plan_v1",
    "repair_plan_action_record_plan_review_note_v1",
)

_CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "identity": (
        "plan-identity-is-strategy-id",
        "plan-carries-repair-case-id",
        "plan-carries-analysis-case-id",
        "plan-carries-incident-id",
        "reference-id-is-deterministic",
        "source-record-id-is-plan-id",
        "source-record-digest-is-sha256",
        "project-snapshot-digest-is-sha256",
        "plan-digest-is-sha256",
        "plan-digest-covers-plan-documents",
        "plan-digest-changes-with-strategy",
        "plan-digest-changes-with-approval-gate",
        "schema-supported-flag-present",
        "unsupported-schema-flagged",
        "unsupported-schema-warns",
        "no-revision-identity-invented",
        "no-supersession-invented",
        "historical-never-inferred",
        "stale-never-inferred",
        "unknown-plan-refused",
        "cross-project-plan-refused",
        "malformed-plan-id-skipped",
    ),
    "plan-truth": (
        "strategy-presented-as-proposed",
        "no-correct-repair-claim",
        "owner-status-verbatim",
        "owner-strategy-type-verbatim",
        "owner-risk-level-verbatim",
        "owner-reversibility-verbatim",
        "owner-destructiveness-verbatim",
        "owner-recommended-flag-verbatim",
        "owner-rank-verbatim",
        "panel-adds-no-recommendation",
        "panel-adds-no-plan-score",
        "panel-adds-no-success-estimate",
        "missing-case-warns",
        "missing-analysis-warns",
        "blocked-status-surfaced",
        "no-action-strategy-surfaced",
        "limitations-always-present",
        "source-retained-notice-present",
        "rejected-strategy-attributed-to-owner",
        "handoff-apply-automatically-false",
    ),
    "steps": (
        "steps-projected",
        "step-order-preserved",
        "step-order-bounded",
        "step-ids-deterministic",
        "step-type-verbatim",
        "step-status-is-proposed",
        "step-no-rationale-invented",
        "step-target-never-projected",
        "step-command-withheld",
        "step-command-notice-exact",
        "step-command-flag-set",
        "step-private-path-flagged",
        "step-private-path-not-exposed",
        "step-read-only-verbatim",
        "step-reversible-verbatim",
        "step-code-change-verbatim",
        "step-tool-execution-derived",
        "step-process-restart-derived",
        "step-checkpoint-restore-derived",
        "step-workflow-transition-derived",
        "step-artifact-change-derived",
        "step-approval-always-required",
        "step-executable-by-panel-false",
        "step-not-executable-notice",
        "step-rollback-reference-not-guarantee",
        "step-count-matches-owner",
    ),
    "commands": (
        "shell-token-detected",
        "shell-operator-detected",
        "ffmpeg-detected",
        "git-detected",
        "package-manager-detected",
        "flagged-argument-detected",
        "prose-not-flagged",
        "empty-not-flagged",
        "command-not-in-step-payload",
        "command-not-in-evidence-payload",
        "command-not-in-comparison-payload",
        "command-not-in-queue-payload",
        "command-not-in-review-payload",
        "command-not-in-export-payload",
        "command-not-in-timeline-payload",
        "rollback-steps-never-projected",
        "rollback-shell-never-projected",
        "private-path-not-in-review-payload",
        "private-path-not-in-export-payload",
        "private-path-notice-available",
        "no-command-runner-in-source",
        "no-subprocess-import-in-source",
        "private-path-detected",
        "bounded-step-description-withholds",
    ),
    "risk": (
        "all-owner-dimensions-projected",
        "dimension-count-is-twelve",
        "dimension-levels-verbatim",
        "blocked-dimension-flagged",
        "blocked-dimension-warns",
        "strategy-risk-projected",
        "strategy-risk-scoped-to-plan",
        "strategy-risk-reasons-bounded",
        "strategy-risk-mitigations-bounded",
        "residual-risk-projected",
        "acceptable-only-if-projected",
        "owner-confidence-not-rescaled",
        "owner-confidence-labelled",
        "no-composite-risk-score",
        "no-repair-success-score",
        "reversible-not-risk-free-pinned",
        "risk-order-is-owner-order",
        "missing-assessment-yields-empty",
        "risk-projection-ids-deterministic",
        "risk-limitations-present",
    ),
    "approvals": (
        "human-review-required",
        "safety-gate-requirement-derived",
        "rights-gate-requirement-derived",
        "output-quality-requirement-derived",
        "rollback-plan-requirement-derived",
        "validation-plan-requirement-derived",
        "code-review-requirement-derived",
        "tool-execution-requirement-derived",
        "process-restart-requirement-derived",
        "destructive-action-requirement-derived",
        "checkpoint-restore-requirement-derived",
        "workflow-requirement-derived",
        "artifact-change-requirement-derived",
        "approved-status-impossible",
        "satisfaction-requires-canonical-record",
        "satisfaction-requires-digest",
        "rollback-satisfied-by-owner-record",
        "validation-satisfied-by-owner-record",
        "safety-never-satisfied-locally",
        "blocking-tracks-satisfaction",
        "no-approval-created-by-panel",
        "approval-limitations-present",
    ),
    "verification": (
        "pre-repair-checks-projected",
        "post-repair-checks-projected",
        "validator-run-requirement-projected",
        "checkpoint-validation-projected",
        "rollback-validation-projected",
        "artifact-inspection-projected",
        "output-quality-verification-projected",
        "validator-ids-preserved",
        "required-check-ids-preserved",
        "rollback-validation-list-joined",
        "no-python-repr-in-explanation",
        "satisfied-requires-owner-pass",
        "failed-validator-not-satisfied",
        "independent-verification-never-claimed",
        "independent-verification-requires-satisfied",
        "owner-success-is-not-verification",
        "blocks-acceptance-verbatim",
        "no-validator-executed-by-panel",
        "verification-ids-deterministic",
        "verification-limitations-present",
    ),
    "evidence": (
        "strategy-card-present",
        "planning-case-card-present",
        "risk-assessment-card-present",
        "approval-gate-card-present",
        "rollback-card-present",
        "checkpoint-card-present",
        "validation-card-present",
        "quality-card-present",
        "handoff-card-present",
        "rejected-strategy-card-present",
        "root-cause-case-card-present",
        "root-cause-candidate-card-present",
        "diagnostic-case-card-present",
        "recovery-card-present",
        "validator-result-card-present",
        "missing-root-cause-card-flagged",
        "missing-validator-card-flagged",
        "safety-card-marked-unbound",
        "final-decision-card-marked-unbound",
        "autopilot-card-advisory-only",
        "authority-domain-from-registry",
        "evidence-limitations-present",
    ),
    "recovery": (
        "attempts-projected",
        "attempt-linked-by-case",
        "attempt-linked-by-strategy-flagged",
        "case-only-link-warns",
        "attempted-reflects-owner",
        "completed-requires-attempt",
        "succeeded-reflects-owner-only",
        "sibling-success-not-inherited",
        "failed-attempt-flagged",
        "failed-attempt-warns",
        "rollback-attempt-surfaced",
        "rollback-status-verbatim",
        "failure-class-verbatim",
        "validation-source-ids-listed",
        "independent-verification-always-false",
        "recovered-is-not-resolved",
        "no-recovery-started-by-panel",
        "attempt-timestamps-from-owner",
        "recovery-link-ids-deterministic",
        "recovery-limitations-present",
    ),
    "conflicts": (
        "duplicate-plan-identity-detected",
        "duplicate-plan-blocks-action",
        "case-parent-disagreement-detected",
        "analysis-parent-disagreement-detected",
        "approval-status-conflict-detected",
        "non-destructive-but-actionable-detected",
        "reversible-but-destructive-detected",
        "rollback-required-but-absent-detected",
        "rollback-not-required-but-destructive-detected",
        "validator-runner-without-validators-detected",
        "plan-ready-with-failed-validator-detected",
        "recovery-status-conflict-detected",
        "recommended-flag-conflict-detected",
        "active-and-rejected-detected",
        "repair-not-needed-but-actionable-detected",
        "not-required-but-typed-detected",
        "workflow-stage-disagreement-detected",
        "conflict-requires-same-identity",
        "conflict-never-auto-resolved",
        "conflict-requires-human-review",
        "conflict-ids-deterministic",
        "no-supersession-claimed",
    ),
    "queue": (
        "queue-builds",
        "tier-count-is-fourteen",
        "destructive-awaiting-approval-tier",
        "code-artifact-workflow-tier",
        "checkpoint-restart-tier",
        "missing-verification-tier",
        "failed-recovery-tier",
        "completed-unverified-tier",
        "other-current-tier",
        "tier-is-not-a-score",
        "deterministic-sort-key",
        "sort-review-priority",
        "sort-source-severity",
        "sort-creation-order",
        "sort-step-count",
        "unsupported-sort-refused",
        "filter-destructive",
        "filter-missing-approval",
        "unsupported-filter-refused",
        "paging-bounded",
    ),
    "comparison": (
        "comparison-builds",
        "requires-two-plans",
        "limit-enforced",
        "duplicate-ids-collapsed",
        "same-repair-case-detected",
        "same-incident-detected",
        "strategy-axis-present",
        "step-axis-present",
        "approval-axis-present",
        "risk-axis-present",
        "rollback-axis-present",
        "recovery-axis-present",
        "no-automatic-winner",
        "no-automatic-plan-selection",
        "no-automatic-execution-selection",
        "missing-fields-listed",
    ),
    "actions": (
        "eleven-descriptors",
        "one-available-action",
        "ten-unavailable-actions",
        "every-unavailable-has-reason",
        "available-action-not-authoritative",
        "available-action-not-execution-capable",
        "approve-plan-unavailable",
        "reject-plan-unavailable",
        "revise-plan-unavailable",
        "regenerate-plan-unavailable",
        "recovery-attempt-unavailable",
        "tool-retry-unavailable",
        "checkpoint-restore-unavailable",
        "escalate-unavailable",
        "review-note-unavailable",
        "acknowledge-plan-unavailable",
        "unavailable-action-request-refused",
        "confirmation-digest-required",
        "wrong-confirmation-refused",
        "unconfirmed-refused",
        "secret-reason-refused",
        "private-path-reason-refused",
        "command-reason-refused",
        "action-requires-current-plan",
        "ambiguous-identity-withholds-action",
        "missing-incident-withholds-action",
    ),
    "security": (
        "no-execution-operation",
        "no-command-execution",
        "no-shell-execution",
        "no-git-execution",
        "no-ffmpeg-execution",
        "no-package-installation",
        "no-code-modification",
        "no-artifact-modification",
        "no-source-media-modification",
        "no-accepted-output-modification",
        "no-checkpoint-restore",
        "no-process-restart",
        "no-workflow-change",
        "no-plan-creation",
        "no-plan-revision",
        "no-local-approval",
        "no-local-safety-decision",
        "no-local-rights-decision",
        "no-upload",
        "no-publication",
        "no-arbitrary-module",
        "no-arbitrary-operation",
        "fixed-integration-calls-only",
        "safety-classifications-read-only",
        "no-arbitrary-url",
        "module-deps-declared",
        "module-not-execution-capable",
    ),
    "persistence": (
        "session-persisted",
        "session-project-scoped",
        "session-expiry-enforced",
        "session-field-allowlist",
        "comparison-limit-enforced",
        "annotation-bounded",
        "annotation-label-present",
        "secret-annotation-rejected",
        "command-annotation-rejected",
        "immutable-registry",
        "immutable-submitted-action",
        "immutable-receipt",
        "duplicate-submission-reused",
        "stale-state-rejected",
        "receipt-cannot-claim-change",
        "source-records-not-duplicated",
        "reset-preserves-repair-plans",
        "reset-preserves-recovery-history",
        "reset-preserves-receipts",
        "sanitized-export",
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


class _StubReviewUi:
    """Stands in for Review UI, the owner of incident acknowledgement metadata."""

    def __init__(self) -> None:
        self.sessions: list[dict[str, Any]] = []
        self.acknowledged: list[str] = []
        self.reject = False
        self.malformed = False

    def create_boba_review_session(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        if self.reject:
            raise ValidationError("Review UI rejected the review session.")
        self.sessions.append({"project_id": project_id, **kwargs})
        return {
            "review_session_id": f"review_session_{len(self.sessions)}",
            "session_digest": "a" * 64,
        }

    def acknowledge_boba_review_notification(
        self, project_id: str, session_id: str, notification_id: str
    ) -> dict[str, Any]:
        if self.reject:
            raise ValidationError("Review UI rejected the acknowledgement.")
        self.acknowledged.append(notification_id)
        if self.malformed:
            return {"review_session_id": session_id, "session_digest": "b" * 64}
        return {
            "review_session_id": session_id,
            "session_digest": "b" * 64,
            "acknowledged_notification_ids": list(self.acknowledged),
        }


def _engine(root: Path, **seed: Any) -> tuple[BobaRepairPlanReviewV1, _StubReviewUi]:
    store = BobaMemoryStore(root)
    owner = _StubReviewUi()
    engine = BobaRepairPlanReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


def _prepared(
    engine: BobaRepairPlanReviewV1, plan_id: str = PLAN_CHECKPOINT
) -> dict[str, Any]:
    session = engine.create_repair_plan_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    payload = engine.build_repair_plan_snapshot(
        PROJECT_ID, session.repair_plan_review_session_id, plan_id
    )
    payload["session"] = session
    return payload


def _request(
    engine: BobaRepairPlanReviewV1,
    payload: dict[str, Any],
    key: str,
    *,
    action: str = _ACK,
    decision: str | None = "acknowledged",
    reason: str = "",
    digest: str | None = None,
    confirmed: bool = True,
) -> Any:
    return engine.create_repair_plan_action_request(
        PROJECT_ID,
        repair_plan_review_session_id=payload["session"].repair_plan_review_session_id,
        repair_plan_snapshot_id=payload["snapshot"]["repair_plan_snapshot_id"],
        action_descriptor_id=action,
        decision_value=decision,
        reason=reason,
        confirmation_context_digest=(
            digest
            if digest is not None
            else payload["action_confirmations"].get(action, "0" * 64)
        ),
        idempotency_key=key,
        confirmed=confirmed,
    )


def _check(name: str, passed: bool, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, passed=passed, detail=detail)


def _expect_error(callable_: Any, *args: Any, **kwargs: Any) -> tuple[bool, str]:
    """Pass only when the call is refused by an explicit error."""
    try:
        callable_(*args, **kwargs)
    except ValidationError as error:
        return (True, f"refused: {str(error)[:120]}")
    except Exception as error:
        return (True, f"refused ({type(error).__name__}): {str(error)[:100]}")
    return (False, "the call was accepted when it should have been refused")


def _source_text() -> str:
    return Path("src/olympus/boba/repair_plan_review.py").read_text(encoding="utf-8")


def _frontend_text() -> str:
    path = Path("frontend/src/lib/repairPlanReview.ts")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _group(group: str, checks: dict[str, tuple[bool, str]]) -> list[ScenarioResult]:
    """Emit one result per catalogued condition, flagging any gap honestly."""
    results: list[ScenarioResult] = []
    for name in _CONDITION_GROUPS[group]:
        if name not in checks:
            results.append(_check(f"{group}:{name}", False, "condition not evaluated"))
            continue
        passed, detail = checks[name]
        results.append(_check(f"{group}:{name}", passed, detail))
    return results


class _RawSourceStore(BobaMemoryStore):
    """Serve arbitrary raw payloads for chosen repair-plan source loaders.

    The canonical loaders validate their owning contracts, so an unsupported
    schema id, a duplicated strategy identity or a disagreeing parent case
    cannot reach the panel through them. Injecting the raw payload here
    exercises the projection's real branches instead of assuming them.
    """

    def __init__(self, root: Path, raw: dict[str, Any]) -> None:
        super().__init__(root)
        self._raw = raw

    def _maybe(self, key: str, fallback: Any) -> Any:
        return self._raw.get(key, fallback)

    def load_boba_repair_planner(self, project_id: str) -> Any:
        return self._maybe("repair_planner", super().load_boba_repair_planner(project_id))

    def load_boba_root_cause_analyzer(self, project_id: str) -> Any:
        return self._maybe(
            "root_cause_analyzer", super().load_boba_root_cause_analyzer(project_id)
        )

    def load_boba_error_doctor(self, project_id: str) -> Any:
        return self._maybe("error_doctor", super().load_boba_error_doctor(project_id))

    def load_boba_tool_recovery(self, project_id: str) -> Any:
        return self._maybe("tool_recovery", super().load_boba_tool_recovery(project_id))

    def load_boba_code_surgeon(self, project_id: str) -> Any:
        return self._maybe("code_surgeon", super().load_boba_code_surgeon(project_id))

    def load_boba_validator_runner(self, project_id: str) -> Any:
        return self._maybe(
            "validator_runner", super().load_boba_validator_runner(project_id)
        )

    def load_boba_artifact_inspector(self, project_id: str) -> Any:
        return self._maybe(
            "artifact_inspector", super().load_boba_artifact_inspector(project_id)
        )

    def load_boba_output_quality_reviewer(self, project_id: str) -> Any:
        return self._maybe(
            "output_quality_reviewer",
            super().load_boba_output_quality_reviewer(project_id),
        )

    def load_boba_workflow_controller(self, project_id: str) -> Any:
        return self._maybe(
            "workflow_controller", super().load_boba_workflow_controller(project_id)
        )

    def load_boba_safety_gate(self, project_id: str) -> Any:
        return self._maybe("safety_gate", super().load_boba_safety_gate(project_id))

    def load_observer_report(self, project_id: str) -> Any:
        return self._maybe("observer", super().load_observer_report(project_id))


def _raw_engine(
    root: Path, raw: dict[str, Any], **seed: Any
) -> tuple[BobaRepairPlanReviewV1, _StubReviewUi]:
    store = _RawSourceStore(root, raw)
    owner = _StubReviewUi()
    engine = BobaRepairPlanReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


def _planner_dict(**overrides: Any) -> dict[str, Any]:
    """A raw Repair Planner payload the panel will read as-is."""
    payload = synthetic_repair_planner_set(PROJECT_ID).model_dump(mode="json")
    payload.update(overrides)
    return payload


def _validator_payload(*results: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "boba_validator_runner_v1",
        "project_id": PROJECT_ID,
        "validation_results": list(results),
    }


def _run_identity() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        refs = engine.build_repair_plan_references(PROJECT_ID)
        by_id = {item.repair_plan_id: item for item in refs}
        ref = by_id[PLAN_REVERSIBLE]

        checks["plan-identity-is-strategy-id"] = (
            set(by_id) == {PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_CHECKPOINT, PLAN_DESTRUCTIVE},
            f"plan ids are the owner's repair_strategy_ids: {sorted(by_id)}",
        )
        checks["plan-carries-repair-case-id"] = (
            ref.repair_case_id == REPAIR_CASE_ID,
            f"repair_case_id={ref.repair_case_id}",
        )
        checks["plan-carries-analysis-case-id"] = (
            ref.source_analysis_case_id == "analysis_a",
            f"source_analysis_case_id={ref.source_analysis_case_id}",
        )
        checks["plan-carries-incident-id"] = (
            ref.source_diagnostic_case_id == "case_a",
            f"source_diagnostic_case_id={ref.source_diagnostic_case_id}",
        )
        again = engine.build_repair_plan_references(PROJECT_ID)
        checks["reference-id-is-deterministic"] = (
            [i.repair_plan_reference_id for i in refs]
            == [i.repair_plan_reference_id for i in again],
            "reference ids are stable across rebuilds",
        )
        checks["source-record-id-is-plan-id"] = (
            all(i.source_record_id == i.repair_plan_id for i in refs),
            "each reference names its own plan as the source record",
        )
        checks["source-record-digest-is-sha256"] = (
            all(len(i.source_record_digest) == 64 for i in refs),
            "every source record digest is a sha256 hex digest",
        )
        checks["project-snapshot-digest-is-sha256"] = (
            len(ref.project_snapshot_digest) == 64,
            "project snapshot digest is a sha256 hex digest",
        )
        digest = engine._repair_plan_digest(PROJECT_ID, PLAN_REVERSIBLE)
        checks["plan-digest-is-sha256"] = (len(digest) == 64, "plan digest is sha256")

        # The digest must cover the plan documents, not just the strategy row.
        gate_engine, _ = _raw_engine(
            root / "gate",
            {
                "repair_planner": _planner_dict(
                    approval_gates=[
                        synthetic_approval_gate(approval_status="blocked").model_dump(
                            mode="json"
                        )
                    ]
                )
            },
        )
        gate_digest = gate_engine._repair_plan_digest(PROJECT_ID, PLAN_REVERSIBLE)
        checks["plan-digest-covers-plan-documents"] = (
            gate_digest != digest,
            "changing the approval gate changes the plan digest",
        )
        checks["plan-digest-changes-with-approval-gate"] = (
            gate_digest != digest,
            f"{digest[:12]} -> {gate_digest[:12]}",
        )
        strat_engine, _ = _raw_engine(
            root / "strat",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[
                        synthetic_strategy(
                            PLAN_REVERSIBLE, estimated_risk="critical"
                        ).model_dump(mode="json")
                    ]
                )
            },
        )
        checks["plan-digest-changes-with-strategy"] = (
            strat_engine._repair_plan_digest(PROJECT_ID, PLAN_REVERSIBLE) != digest,
            "changing the strategy changes the plan digest",
        )
        checks["schema-supported-flag-present"] = (
            all(i.schema_supported for i in refs)
            and ref.source_schema_id == SUPPORTED_REPAIR_PLAN_SCHEMA_ID,
            f"schema id {ref.source_schema_id} is recognised",
        )
        bad_engine, _ = _raw_engine(
            root / "bad", {"repair_planner": _planner_dict(schema_version="other_v9")}
        )
        bad_refs = bad_engine.build_repair_plan_references(PROJECT_ID)
        checks["unsupported-schema-flagged"] = (
            bool(bad_refs) and not any(i.schema_supported for i in bad_refs),
            "an unrecognised schema id is reported as unsupported",
        )
        checks["unsupported-schema-warns"] = (
            bool(bad_refs)
            and any("not supported" in w for i in bad_refs for w in i.warnings),
            "an unsupported schema produces an explicit warning",
        )
        checks["no-revision-identity-invented"] = (
            all(i.repair_plan_revision_id is None for i in refs),
            "Repair Planner records no revision identity, so none is shown",
        )
        checks["no-supersession-invented"] = (
            all(i.superseding_repair_plan_id is None and not i.superseded for i in refs),
            "no supersession is inferred from ordering or timestamps",
        )
        checks["historical-never-inferred"] = (
            all(not i.historical for i in refs),
            "historical stays explicitly false with no owner archive",
        )
        checks["stale-never-inferred"] = (
            all(not i.stale for i in refs),
            "stale stays explicitly false with no owner marker",
        )
        checks["unknown-plan-refused"] = _expect_error(
            engine.inspect_repair_plan, PROJECT_ID, "strategy_missing"
        )
        other, _ = _engine(root / "other", seed=False)
        checks["cross-project-plan-refused"] = _expect_error(
            other.inspect_repair_plan, "another-project", PLAN_REVERSIBLE
        )
        skipped, _ = _raw_engine(
            root / "skip",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[
                        {**synthetic_strategy().model_dump(mode="json"),
                         "repair_strategy_id": "bad id with spaces"},
                    ]
                )
            },
        )
        checks["malformed-plan-id-skipped"] = (
            skipped.build_repair_plan_references(PROJECT_ID) == [],
            "a plan id that is not a safe record id is skipped, never coerced",
        )
    return _group("identity", checks)


def _run_plan_truth() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        refs = {i.repair_plan_id: i for i in engine.build_repair_plan_references(PROJECT_ID)}
        cards = engine.build_repair_evidence_cards(PROJECT_ID, PLAN_REVERSIBLE)
        strategy_card = next(i for i in cards if i.evidence_type == "repair_strategy")
        review = engine.build_repair_plan_review(PROJECT_ID)
        blob = json.dumps(review)

        checks["strategy-presented-as-proposed"] = (
            any("proposed this strategy" in t for t in strategy_card.limitations),
            "the strategy card attributes the proposal to Repair Planner",
        )
        lowered = blob.lower()
        correct_claims = [
            fragment
            for fragment in lowered.split('"')
            if "correct repair" in fragment
            and not any(
                negation in fragment
                for negation in ("never states", "does not state", "not a statement")
            )
        ]
        checks["no-correct-repair-claim"] = (
            not correct_claims
            and "correct repair" not in strategy_card.bounded_summary.lower()
            and "correct" not in refs[PLAN_REVERSIBLE].original_status.lower(),
            "every mention of a correct repair sits inside an explicit denial",
        )
        checks["owner-status-verbatim"] = (
            refs[PLAN_REVERSIBLE].original_status == "plan_ready",
            f"planning status projected verbatim: {refs[PLAN_REVERSIBLE].original_status}",
        )
        checks["owner-strategy-type-verbatim"] = (
            refs[PLAN_CHECKPOINT].original_strategy_type == "restore_checkpoint",
            "strategy type projected verbatim",
        )
        checks["owner-risk-level-verbatim"] = (
            refs[PLAN_DESTRUCTIVE].original_risk_level == "critical",
            "estimated risk projected verbatim",
        )
        queue = engine.build_repair_plan_queue(PROJECT_ID)
        items = {i["repair_plan_id"]: i for i in queue["items"]}
        checks["owner-reversibility-verbatim"] = (
            items[PLAN_CHECKPOINT]["original_reversibility"] == "difficult_to_reverse",
            "reversibility projected verbatim",
        )
        checks["owner-destructiveness-verbatim"] = (
            items[PLAN_DESTRUCTIVE]["original_destructiveness"] == "blocked",
            "destructiveness projected verbatim",
        )
        checks["owner-recommended-flag-verbatim"] = (
            items[PLAN_REVERSIBLE]["source_marked_recommended"] is True
            and items[PLAN_DESTRUCTIVE]["source_marked_recommended"] is False,
            "the owner's own recommended flag is projected, not recomputed",
        )
        comparison = engine.compare_repair_plans(
            PROJECT_ID, [PLAN_REVERSIBLE, PLAN_DESTRUCTIVE]
        )["comparison"]
        ranks = {r["repair_plan_id"]: r["source_rank"] for r in comparison["strategy_comparison"]}
        checks["owner-rank-verbatim"] = (
            ranks[PLAN_REVERSIBLE] == 1 and ranks[PLAN_DESTRUCTIVE] == 4,
            f"owner ranks projected: {ranks}",
        )
        checks["panel-adds-no-recommendation"] = (
            comparison["no_automatic_winner"] is True
            and comparison["no_automatic_plan_selection"] is True,
            "the comparison selects nothing",
        )
        risk = engine.inspect_repair_risks(PROJECT_ID, PLAN_REVERSIBLE)
        checks["panel-adds-no-plan-score"] = (
            risk["panel_risk_score_created"] is False,
            "no panel risk score is produced",
        )
        checks["panel-adds-no-success-estimate"] = (
            risk["panel_repair_success_score_created"] is False,
            "no repair-success estimate is produced",
        )
        orphan, _ = _raw_engine(
            root / "orphan", {"repair_planner": _planner_dict(repair_cases=[])}
        )
        orphan_refs = orphan.build_repair_plan_references(PROJECT_ID)
        checks["missing-case-warns"] = (
            bool(orphan_refs)
            and any("planning case is unavailable" in w for w in orphan_refs[0].warnings),
            "a missing planning case is reported, not filled in",
        )
        # The owner contract forbids an empty source_analysis_case_id, so this
        # state can only be reached by injecting the raw payload.
        orphan_case = synthetic_planning_case().model_dump(mode="json")
        orphan_case["source_analysis_case_id"] = ""
        no_analysis, _ = _raw_engine(
            root / "noan", {"repair_planner": _planner_dict(repair_cases=[orphan_case])}
        )
        na_refs = no_analysis.build_repair_plan_references(PROJECT_ID)
        checks["missing-analysis-warns"] = (
            bool(na_refs) and any("no Root Cause Analyzer case" in w for w in na_refs[0].warnings),
            "a plan with no analysis case is reported explicitly",
        )
        blocked, _ = _raw_engine(
            root / "blocked",
            {
                "repair_planner": _planner_dict(
                    repair_cases=[
                        synthetic_planning_case(
                            planning_status="intentional_safety_block",
                            blocked_reason="Safety Gate blocked this repair.",
                        ).model_dump(mode="json")
                    ]
                )
            },
        )
        b_cards = blocked.build_repair_evidence_cards(PROJECT_ID, PLAN_REVERSIBLE)
        checks["blocked-status-surfaced"] = (
            any(i.blocking and i.evidence_type == "repair_planning_case" for i in b_cards),
            "an intentional safety block is surfaced as blocking evidence",
        )
        noaction, _ = _raw_engine(
            root / "noact",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[
                        synthetic_strategy(
                            PLAN_REVERSIBLE, strategy_type="no_action"
                        ).model_dump(mode="json")
                    ]
                )
            },
        )
        checks["no-action-strategy-surfaced"] = (
            noaction.build_repair_plan_references(PROJECT_ID)[0].original_strategy_type
            == "no_action",
            "a no_action strategy is still shown as a reviewable plan",
        )
        checks["limitations-always-present"] = (
            all(i.limitations for i in engine.build_repair_plan_references(PROJECT_ID)),
            "every reference carries explicit limitations",
        )
        checks["source-retained-notice-present"] = (
            any(SOURCE_RETAINED_NOTICE in i.limitations for i in refs.values()),
            "the source-retained notice is present",
        )
        rejected = next(i for i in cards if i.evidence_type == "repair_rejected_strategy")
        checks["rejected-strategy-attributed-to-owner"] = (
            any("Repair Planner rejected" in t for t in rejected.limitations),
            "the rejection is attributed to Repair Planner, not the panel",
        )
        handoff = next(i for i in cards if i.evidence_type == "repair_execution_handoff")
        checks["handoff-apply-automatically-false"] = (
            any("apply_automatically=False" in t for t in handoff.limitations),
            "the handoff card states apply_automatically is pinned false",
        )
    return _group("plan-truth", checks)


def _run_steps() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        steps = engine.build_step_projections(PROJECT_ID, PLAN_CODE_CHANGE)
        plain = engine.build_step_projections(PROJECT_ID, PLAN_REVERSIBLE)
        payload = engine.inspect_repair_steps(PROJECT_ID, PLAN_CODE_CHANGE)
        blob = json.dumps(payload)
        by_order = {i.original_order: i for i in steps}

        checks["steps-projected"] = (len(steps) == 3, f"{len(steps)} step projections")
        checks["step-order-preserved"] = (
            [i.original_order for i in steps] == [1, 2, 3],
            "owner step order is preserved",
        )
        checks["step-order-bounded"] = (
            all(1 <= i.original_order <= 64 for i in steps),
            "step order stays inside the owner's own bound",
        )
        again = engine.build_step_projections(PROJECT_ID, PLAN_CODE_CHANGE)
        checks["step-ids-deterministic"] = (
            [i.repair_step_projection_id for i in steps]
            == [i.repair_step_projection_id for i in again],
            "step projection ids are stable",
        )
        checks["step-type-verbatim"] = (
            [i.original_step_type for i in steps]
            == ["propose_patch", "retry", "restart_service"],
            "step types are projected verbatim",
        )
        checks["step-status-is-proposed"] = (
            all(i.original_status == "proposed" for i in steps),
            "no per-step lifecycle status is invented",
        )
        checks["step-no-rationale-invented"] = (
            all(i.bounded_reason == "" for i in steps),
            "no per-step rationale is invented",
        )
        checks["step-target-never-projected"] = (
            '"target"' not in blob
            and PRIVATE_PATH_TARGET not in blob
            and COMMAND_TARGET not in blob
            and "render_worker" not in blob,
            "no target key and no owner target value reaches the payload",
        )
        checks["step-command-withheld"] = (
            by_order[2].bounded_description == COMMAND_WITHHELD_NOTICE,
            "a command-bearing description is replaced by the fixed notice",
        )
        checks["step-command-notice-exact"] = (
            payload["notices"]["command"] == COMMAND_WITHHELD_NOTICE,
            f"exact notice: {COMMAND_WITHHELD_NOTICE}",
        )
        checks["step-command-flag-set"] = (
            by_order[2].raw_command_present_in_source is True
            and by_order[2].raw_command_exposed is False,
            "command presence is reported without exposing the command",
        )
        checks["step-private-path-flagged"] = (
            by_order[1].private_path_present_in_source is True,
            "a private path in the source is reported",
        )
        checks["step-private-path-not-exposed"] = (
            all(i.private_path_exposed is False for i in steps)
            and "/home/operator" not in blob,
            "no private path reaches the payload",
        )
        checks["step-read-only-verbatim"] = (
            plain[0].read_only_by_owner is True and by_order[1].read_only_by_owner is False,
            "the owner's read_only flag is projected verbatim",
        )
        checks["step-reversible-verbatim"] = (
            by_order[2].reversible is False and plain[0].reversible is True,
            "the owner's reversible flag is projected verbatim",
        )
        checks["step-code-change-verbatim"] = (
            by_order[1].requires_code_change is True,
            "the owner's code-change flag is projected verbatim",
        )
        checks["step-tool-execution-derived"] = (
            by_order[2].requires_tool_execution is True,
            "a retry/command step is reported as needing tool execution",
        )
        checks["step-process-restart-derived"] = (
            by_order[3].requires_process_restart is True,
            "a restart_service step is reported as needing a process restart",
        )
        cp = engine.build_step_projections(PROJECT_ID, PLAN_CHECKPOINT)
        checks["step-checkpoint-restore-derived"] = (
            cp[0].requires_checkpoint_restore is True,
            "a restore step is reported as needing a checkpoint restore",
        )
        checks["step-workflow-transition-derived"] = (
            cp[1].requires_workflow_transition is True,
            "a resume_workflow step is reported as a workflow transition",
        )
        checks["step-artifact-change-derived"] = (
            engine.build_step_projections(PROJECT_ID, PLAN_DESTRUCTIVE)[0]
            .requires_artifact_change
            is True,
            "a regenerate step is reported as an artifact change",
        )
        checks["step-approval-always-required"] = (
            all(i.requires_human_approval for i in steps),
            "every step keeps the owner's human-approval requirement",
        )
        checks["step-executable-by-panel-false"] = (
            all(i.executable_by_panel is False for i in steps)
            and payload["executable_by_panel"] is False,
            "no step is executable from the panel",
        )
        checks["step-not-executable-notice"] = (
            all(NOT_EXECUTABLE_NOTICE in i.limitations for i in steps),
            f"exact notice: {NOT_EXECUTABLE_NOTICE}",
        )
        checks["step-rollback-reference-not-guarantee"] = (
            any("not a rollback guarantee" in t for i in steps for t in i.limitations),
            "a rollback reference is explicitly not a guarantee",
        )
        checks["step-count-matches-owner"] = (
            payload["step_count"] == 3 and payload["command_bearing_step_count"] == 1,
            "step counts match the owner's own record",
        )
    return _group("steps", checks)


def _run_commands() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    source = _source_text()
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")

        checks["shell-token-detected"] = (
            source_holds_command("do this; then that"),
            "a shell separator is detected",
        )
        checks["shell-operator-detected"] = (
            source_holds_command(SHELL_TARGET),
            "a shell operator chain is detected",
        )
        checks["ffmpeg-detected"] = (
            source_holds_command(COMMAND_TARGET), "an ffmpeg invocation is detected"
        )
        checks["git-detected"] = (
            source_holds_command("git checkout -- ./generated"),
            "a git invocation is detected",
        )
        checks["package-manager-detected"] = (
            source_holds_command("pip install some-encoder"),
            "a package install invocation is detected",
        )
        checks["flagged-argument-detected"] = (
            source_holds_command("encoder --preset veryslow --crf 18"),
            "a flagged argument list is detected",
        )
        checks["prose-not-flagged"] = (
            not source_holds_command(
                "Confirm the caption timing matches the approved source window."
            ),
            "ordinary reviewer prose is not misclassified",
        )
        checks["empty-not-flagged"] = (
            not source_holds_command("") and not source_holds_command(None),
            "empty values are not flagged",
        )

        def leaks(text: str) -> bool:
            return (
                COMMAND_TARGET in text
                or "libx264" in text
                or "rm -rf" in text
                or "git checkout" in text
            )

        steps_blob = json.dumps(engine.inspect_repair_steps(PROJECT_ID, PLAN_CODE_CHANGE))
        checks["command-not-in-step-payload"] = (
            not leaks(steps_blob), "no command text in the step payload"
        )
        ev_blob = json.dumps(engine.inspect_repair_evidence(PROJECT_ID, PLAN_REVERSIBLE))
        checks["command-not-in-evidence-payload"] = (
            not leaks(ev_blob), "no command text in the evidence payload"
        )
        cmp_blob = json.dumps(
            engine.compare_repair_plans(PROJECT_ID, [PLAN_REVERSIBLE, PLAN_CODE_CHANGE])
        )
        checks["command-not-in-comparison-payload"] = (
            not leaks(cmp_blob), "no command text in the comparison payload"
        )
        q_blob = json.dumps(engine.build_repair_plan_queue(PROJECT_ID))
        checks["command-not-in-queue-payload"] = (
            not leaks(q_blob), "no command text in the queue payload"
        )
        review_blob = json.dumps(engine.build_repair_plan_review(PROJECT_ID))
        checks["command-not-in-review-payload"] = (
            not leaks(review_blob), "no command text in the review payload"
        )
        export_blob = json.dumps(engine.export_repair_plan_review(PROJECT_ID))
        checks["command-not-in-export-payload"] = (
            not leaks(export_blob), "no command text in the export payload"
        )
        tl_blob = json.dumps(engine.inspect_repair_plan_timeline(PROJECT_ID))
        checks["command-not-in-timeline-payload"] = (
            not leaks(tl_blob), "no command text in the timeline payload"
        )
        rollback_card = next(
            i
            for i in engine.build_repair_evidence_cards(PROJECT_ID, PLAN_REVERSIBLE)
            if i.evidence_type == "repair_rollback_plan"
        )
        checks["rollback-steps-never-projected"] = (
            rollback_card.bounded_excerpt == "" and "git checkout" not in ev_blob,
            "rollback step text is never projected",
        )
        checks["rollback-shell-never-projected"] = (
            SHELL_TARGET not in ev_blob and SHELL_TARGET not in review_blob,
            "shell text inside a rollback plan never reaches a payload",
        )
        checks["private-path-not-in-review-payload"] = (
            "/home/operator" not in review_blob,
            "no private path in the review payload",
        )
        checks["private-path-not-in-export-payload"] = (
            "/home/operator" not in export_blob,
            "no private path in the export payload",
        )
        checks["private-path-notice-available"] = (
            engine.inspect_repair_steps(PROJECT_ID, PLAN_CODE_CHANGE)["notices"][
                "private_path"
            ]
            == PRIVATE_PATH_NOTICE,
            f"exact notice: {PRIVATE_PATH_NOTICE}",
        )
        checks["no-command-runner-in-source"] = (
            "subprocess.run(" not in source and "os.system(" not in source,
            "the module contains no command runner",
        )
        checks["no-subprocess-import-in-source"] = (
            "import subprocess" not in source and "import shutil" not in source,
            "the module imports no process or filesystem mutation helper",
        )
        checks["private-path-detected"] = (
            source_holds_private_path(PRIVATE_PATH_TARGET),
            "a private absolute path is detected",
        )
        checks["bounded-step-description-withholds"] = (
            bounded_step_description(COMMAND_TARGET)["command_withheld"] is True,
            "the bounded step helper withholds command text",
        )
    return _group("commands", checks)


def _run_risk() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        rows = engine.build_risk_projections(PROJECT_ID, PLAN_DESTRUCTIVE)
        payload = engine.inspect_repair_risks(PROJECT_ID, PLAN_DESTRUCTIVE)
        dims = {i.risk_dimension: i for i in rows}
        owner_dims = repair_risk_dimensions()

        checks["all-owner-dimensions-projected"] = (
            all(d in dims for d in owner_dims),
            f"{len(owner_dims)} owner dimensions all projected",
        )
        checks["dimension-count-is-twelve"] = (
            len(owner_dims) == 12, f"{len(owner_dims)} named owner risk dimensions"
        )
        checks["dimension-levels-verbatim"] = (
            dims["output_quality_risk"].original_risk_level == "high"
            and dims["source_data_risk"].original_risk_level == "minimal",
            "dimension levels are the owner's own values",
        )
        strategy_rows = [i for i in rows if i.strategy_specific]
        checks["strategy-risk-projected"] = (
            len(strategy_rows) == 1, "the strategy-specific risk row is projected"
        )
        checks["blocked-dimension-flagged"] = (
            strategy_rows[0].blocked_by_owner is True,
            "the owner's blocked flag is projected",
        )
        checks["blocked-dimension-warns"] = (
            payload["blocked_dimension_count"] >= 1,
            f"{payload['blocked_dimension_count']} blocked dimensions reported",
        )
        other = engine.build_risk_projections(PROJECT_ID, PLAN_CHECKPOINT)
        checks["strategy-risk-scoped-to-plan"] = (
            not any(i.strategy_specific for i in other),
            "a strategy risk row is only shown for the strategy it names",
        )
        checks["strategy-risk-reasons-bounded"] = (
            bool(strategy_rows[0].bounded_reasons)
            and all(len(t) <= 700 for t in strategy_rows[0].bounded_reasons),
            "risk reasons are projected and bounded",
        )
        checks["strategy-risk-mitigations-bounded"] = (
            bool(strategy_rows[0].bounded_mitigations),
            "risk mitigations are projected",
        )
        checks["residual-risk-projected"] = (
            "not be recoverable" in strategy_rows[0].bounded_residual_risk,
            "the owner's residual risk text is projected",
        )
        checks["acceptable-only-if-projected"] = (
            bool(strategy_rows[0].acceptable_only_if),
            "the owner's acceptable-only-if conditions are projected",
        )
        checks["owner-confidence-not-rescaled"] = (
            strategy_rows[0].confidence_value == 0.44,
            f"owner confidence projected unchanged: {strategy_rows[0].confidence_value}",
        )
        checks["owner-confidence-labelled"] = (
            strategy_rows[0].confidence_name == "repair_planner_reported_confidence"
            and "does not compute" in strategy_rows[0].confidence_definition,
            "the confidence is labelled as the owner's own number",
        )
        checks["no-composite-risk-score"] = (
            payload["panel_risk_score_created"] is False
            and all("composite" not in str(i.original_risk_level) for i in rows),
            "no composite risk score is produced",
        )
        checks["no-repair-success-score"] = (
            payload["panel_repair_success_score_created"] is False,
            "no repair-success score is produced",
        )
        checks["reversible-not-risk-free-pinned"] = (
            all(i.reversible_does_not_mean_risk_free is True for i in rows),
            "every risk row pins that reversible is not risk-free",
        )
        checks["risk-order-is-owner-order"] = (
            payload["source_risk_order"][0] == "blocking"
            and "unknown" in payload["source_risk_order"],
            "the risk order is a fixed owner-derived ordering",
        )
        empty, _ = _raw_engine(
            root / "norisk", {"repair_planner": _planner_dict(risk_assessments=[])}
        )
        checks["missing-assessment-yields-empty"] = (
            empty.build_risk_projections(PROJECT_ID, PLAN_REVERSIBLE) == [],
            "a missing risk assessment yields no invented risk rows",
        )
        again = engine.build_risk_projections(PROJECT_ID, PLAN_DESTRUCTIVE)
        checks["risk-projection-ids-deterministic"] = (
            [i.repair_risk_projection_id for i in rows]
            == [i.repair_risk_projection_id for i in again],
            "risk projection ids are stable",
        )
        checks["risk-limitations-present"] = (
            all(i.limitations for i in rows), "every risk row carries limitations"
        )
    return _group("risk", checks)


def _run_approvals() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        rows = engine.build_approval_requirements(PROJECT_ID, PLAN_CODE_CHANGE)
        by_type = {i.requirement_type: i for i in rows}
        payload = engine.inspect_approval_requirements(PROJECT_ID, PLAN_CODE_CHANGE)

        checks["human-review-required"] = (
            by_type["human_review"].required is True
            and by_type["human_review"].satisfied_by_owner is False,
            "final human approval is required and never satisfied locally",
        )
        checks["safety-gate-requirement-derived"] = (
            "safety_gate" in by_type, "the Safety Gate requirement is derived"
        )
        gate = synthetic_approval_gate(rights_gate_required=True, code_review_required=True)
        rights_engine, _ = _raw_engine(
            root / "rights",
            {"repair_planner": _planner_dict(approval_gates=[gate.model_dump(mode="json")])},
        )
        rights_rows = {
            i.requirement_type
            for i in rights_engine.build_approval_requirements(PROJECT_ID, PLAN_CODE_CHANGE)
        }
        checks["rights-gate-requirement-derived"] = (
            "rights_gate" in rights_rows, "a rights gate requirement is derived when set"
        )
        checks["code-review-requirement-derived"] = (
            "code_change" in rights_rows, "a code review requirement is derived when set"
        )
        checks["output-quality-requirement-derived"] = (
            "output_quality_review" in by_type, "the output-quality requirement is derived"
        )
        checks["rollback-plan-requirement-derived"] = (
            "rollback_plan" in by_type, "the rollback-plan requirement is derived"
        )
        checks["validation-plan-requirement-derived"] = (
            "validation_plan" in by_type, "the validation-plan requirement is derived"
        )
        checks["tool-execution-requirement-derived"] = (
            "tool_execution" in by_type,
            "a command-executing strategy yields a tool-execution requirement",
        )
        restart = synthetic_strategy(PLAN_CODE_CHANGE, requires_service_restart=True)
        restart_engine, _ = _raw_engine(
            root / "restart",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[restart.model_dump(mode="json")]
                )
            },
        )
        restart_types = {
            i.requirement_type
            for i in restart_engine.build_approval_requirements(PROJECT_ID, PLAN_CODE_CHANGE)
        }
        checks["process-restart-requirement-derived"] = (
            "process_restart" in restart_types, "a service restart yields a requirement"
        )
        dest_types = {
            i.requirement_type
            for i in engine.build_approval_requirements(PROJECT_ID, PLAN_DESTRUCTIVE)
        }
        checks["destructive-action-requirement-derived"] = (
            "destructive_action" in dest_types,
            "a destructive rating yields a destructive-action requirement",
        )
        checks["artifact-change-requirement-derived"] = (
            "artifact_change" in dest_types,
            "a regenerate_artifact strategy yields an artifact-change requirement",
        )
        cp_types = {
            i.requirement_type
            for i in engine.build_approval_requirements(PROJECT_ID, PLAN_CHECKPOINT)
        }
        checks["checkpoint-restore-requirement-derived"] = (
            "checkpoint_restore" in cp_types,
            "a restore_checkpoint strategy yields a checkpoint requirement",
        )
        checks["workflow-requirement-derived"] = (
            "workflow" in {
                i.requirement_type
                for i in _raw_engine(
                    root / "wf",
                    {
                        "repair_planner": _planner_dict(
                            repair_strategies=[
                                synthetic_strategy(
                                    PLAN_REVERSIBLE,
                                    strategy_type="switch_safe_workflow_path",
                                ).model_dump(mode="json")
                            ]
                        )
                    },
                )[0].build_approval_requirements(PROJECT_ID, PLAN_REVERSIBLE)
            },
            "a workflow-switching strategy yields a workflow requirement",
        )
        statuses = set()
        for status in (
            "planning_only", "awaiting_human_review", "blocked",
            "not_required_for_no_action", "unknown",
        ):
            statuses.add(status)
        checks["approved-status-impossible"] = (
            "approved" not in statuses
            and any("no approved value" in t for t in payload["limitations"]),
            "the owner vocabulary has no approved value and the panel says so",
        )
        checks["satisfaction-requires-canonical-record"] = (
            all(
                (not i.satisfied_by_owner) or (i.canonical_record_id and i.canonical_record_digest)
                for i in rows
            ),
            "satisfaction always names a canonical owner record",
        )
        checks["satisfaction-requires-digest"] = _expect_error(
            type(rows[0]),
            approval_requirement_id="x",
            repair_plan_id=PLAN_REVERSIBLE,
            source_module_id="repair_planner",
            requirement_type="human_review",
            satisfied_by_owner=True,
        )
        checks["rollback-satisfied-by-owner-record"] = (
            by_type["rollback_plan"].satisfied_by_owner is True
            and by_type["rollback_plan"].canonical_record_id == "rollback_a",
            "the rollback requirement is satisfied by the owner's own plan record",
        )
        checks["validation-satisfied-by-owner-record"] = (
            by_type["validation_plan"].satisfied_by_owner is True
            and by_type["validation_plan"].canonical_record_id == "validation_a",
            "the validation requirement is satisfied by the owner's own plan record",
        )
        checks["safety-never-satisfied-locally"] = (
            by_type["safety_gate"].satisfied_by_owner is False
            and any(
                "no canonical record binds" in t.lower()
                for t in by_type["safety_gate"].limitations
            ),
            "no Safety decision is bound to a repair strategy identity",
        )
        checks["blocking-tracks-satisfaction"] = (
            all(i.blocking is (not i.satisfied_by_owner) for i in rows),
            "blocking exactly tracks unsatisfied requirements",
        )
        checks["no-approval-created-by-panel"] = (
            payload["approval_created_by_panel"] is False,
            "the panel records no approval",
        )
        checks["approval-limitations-present"] = (
            all(i.limitations for i in rows), "every requirement carries limitations"
        )
    return _group("approvals", checks)


def _run_verification() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        rows = engine.build_verification_requirements(PROJECT_ID, PLAN_REVERSIBLE)
        by_type = {i.verification_type: i for i in rows}
        payload = engine.inspect_verification_requirements(PROJECT_ID, PLAN_REVERSIBLE)

        checks["pre-repair-checks-projected"] = (
            "pre_repair_check" in by_type, "pre-repair checks are projected"
        )
        checks["post-repair-checks-projected"] = (
            "post_repair_check" in by_type, "post-repair checks are projected"
        )
        checks["validator-run-requirement-projected"] = (
            "validator_run" in by_type, "the required-validator requirement is projected"
        )
        checks["checkpoint-validation-projected"] = (
            "checkpoint_validation" in by_type, "checkpoint validation is projected"
        )
        checks["rollback-validation-projected"] = (
            "rollback_validation" in by_type, "rollback validation is projected"
        )
        checks["artifact-inspection-projected"] = (
            "artifact_inspection" in by_type, "artifact inspection is projected"
        )
        checks["output-quality-verification-projected"] = (
            "output_quality_review" in by_type, "output-quality verification is projected"
        )
        checks["validator-ids-preserved"] = (
            by_type["validator_run"].validator_ids
            == ["checkpoint_presence", "baseline_comparison"],
            "the owner's validator names are preserved in order",
        )
        checks["required-check-ids-preserved"] = (
            by_type["pre_repair_check"].required_check_ids == ["precheck_a"],
            "the owner's check ids are preserved",
        )
        explanation = by_type["rollback_validation"].bounded_explanation
        checks["rollback-validation-list-joined"] = (
            explanation.startswith("Confirm the prior generated state"),
            f"list-typed owner prose is joined: {explanation[:50]!r}",
        )
        blob = json.dumps(payload)
        checks["no-python-repr-in-explanation"] = (
            "['" not in blob and "']" not in blob,
            "no Python list repr reaches the payload",
        )
        checks["satisfied-requires-owner-pass"] = (
            by_type["validator_run"].satisfied is False,
            "with no Validator Runner results the requirement is not satisfied",
        )
        passing, _ = _raw_engine(
            root / "pass",
            {
                "validator_runner": _validator_payload(
                    {"result_id": "r1", "validator_id": "checkpoint_presence", "status": "passed"},
                    {"result_id": "r2", "validator_id": "baseline_comparison", "status": "passed"},
                )
            },
        )
        pass_rows = {
            i.verification_type: i
            for i in passing.build_verification_requirements(PROJECT_ID, PLAN_REVERSIBLE)
        }
        failing, _ = _raw_engine(
            root / "fail",
            {
                "validator_runner": _validator_payload(
                    {"result_id": "r1", "validator_id": "checkpoint_presence", "status": "passed"},
                    {"result_id": "r2", "validator_id": "baseline_comparison", "status": "failed"},
                )
            },
        )
        fail_rows = {
            i.verification_type: i
            for i in failing.build_verification_requirements(PROJECT_ID, PLAN_REVERSIBLE)
        }
        checks["failed-validator-not-satisfied"] = (
            pass_rows["validator_run"].satisfied is True
            and fail_rows["validator_run"].satisfied is False,
            "satisfaction follows the owner's own validator status",
        )
        checks["independent-verification-never-claimed"] = (
            all(i.independently_verified is False for i in rows)
            and all(i.independently_verified is False for i in pass_rows.values()),
            "independent verification is never claimed, even when the owner passed",
        )
        checks["independent-verification-requires-satisfied"] = _expect_error(
            type(rows[0]),
            verification_requirement_id="x",
            repair_plan_id=PLAN_REVERSIBLE,
            source_module_id="validator_runner",
            verification_type="validator_run",
            satisfied=False,
            independently_verified=True,
        )
        checks["owner-success-is-not-verification"] = (
            any("not independent" in t.lower() for t in payload["limitations"]),
            "the payload states owner success is not independent verification",
        )
        checks["blocks-acceptance-verbatim"] = (
            by_type["pre_repair_check"].blocks_acceptance_on_failure is True,
            "the owner's blocks-acceptance flag is projected",
        )
        checks["no-validator-executed-by-panel"] = (
            payload["validator_executed_by_panel"] is False,
            "the panel executes no validator",
        )
        again = engine.build_verification_requirements(PROJECT_ID, PLAN_REVERSIBLE)
        checks["verification-ids-deterministic"] = (
            [i.verification_requirement_id for i in rows]
            == [i.verification_requirement_id for i in again],
            "verification requirement ids are stable",
        )
        checks["verification-limitations-present"] = (
            all(i.limitations for i in rows), "every requirement carries limitations"
        )
    return _group("verification", checks)


def _run_evidence() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        cards = engine.build_repair_evidence_cards(PROJECT_ID, PLAN_REVERSIBLE)
        by_type: dict[str, Any] = {}
        for card in cards:
            by_type.setdefault(card.evidence_type, card)
        payload = engine.inspect_repair_evidence(PROJECT_ID, PLAN_REVERSIBLE)
        registry = build_fixed_repair_source_registry()

        for condition, evidence_type in (
            ("strategy-card-present", "repair_strategy"),
            ("planning-case-card-present", "repair_planning_case"),
            ("risk-assessment-card-present", "repair_risk_assessment"),
            ("approval-gate-card-present", "repair_approval_gate"),
            ("rollback-card-present", "repair_rollback_plan"),
            ("checkpoint-card-present", "repair_checkpoint_plan"),
            ("validation-card-present", "repair_validation_plan"),
            ("quality-card-present", "quality_preservation_plan"),
            ("handoff-card-present", "repair_execution_handoff"),
            ("rejected-strategy-card-present", "repair_rejected_strategy"),
            ("root-cause-case-card-present", "root_cause_analysis_case"),
            ("root-cause-candidate-card-present", "root_cause_candidate"),
            ("diagnostic-case-card-present", "diagnostic_case"),
            ("recovery-card-present", "tool_recovery_case"),
            ("validator-result-card-present", "validation_result"),
        ):
            checks[condition] = (
                evidence_type in by_type,
                f"{evidence_type} card present"
                if evidence_type in by_type
                else f"{evidence_type} card missing",
            )

        no_rca, _ = _raw_engine(
            root / "norca", {"root_cause_analyzer": {"schema_version": "x", "analysis_cases": []}}
        )
        rca_cards = no_rca.build_repair_evidence_cards(PROJECT_ID, PLAN_REVERSIBLE)
        checks["missing-root-cause-card-flagged"] = (
            any(
                i.evidence_type == "root_cause_analysis_case" and i.missing and i.blocking
                for i in rca_cards
            ),
            "an unavailable root-cause case is a missing, blocking card",
        )
        checks["missing-validator-card-flagged"] = (
            any(i.evidence_type == "validation_result" and i.missing for i in cards),
            "an absent validator result is reported as missing",
        )
        checks["safety-card-marked-unbound"] = (
            by_type["safety_decision"].missing is True
            and any(
                "no repair-strategy identity" in t
                for t in by_type["safety_decision"].limitations
            ),
            "the Safety card explains it cannot be bound to a repair plan",
        )
        checks["final-decision-card-marked-unbound"] = (
            by_type["final_decision"].missing is True,
            "the Final Decision card is reported unbound",
        )
        autopilot_present = "autopilot_context" in by_type
        checks["autopilot-card-advisory-only"] = (
            (not autopilot_present) or by_type["autopilot_context"].advisory_only is True,
            "autopilot context, when present, is advisory only",
        )
        checks["authority-domain-from-registry"] = (
            by_type["repair_strategy"].authority_domain == registry["repair_planner"][
                "authority_domain"
            ],
            "the authority domain comes from the fixed source registry",
        )
        checks["evidence-limitations-present"] = (
            all(i.limitations for i in cards) and bool(payload["limitations"]),
            "every evidence card carries limitations",
        )
    return _group("evidence", checks)


def _run_recovery() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        links = engine.build_recovery_links(PROJECT_ID, PLAN_REVERSIBLE)
        payload = engine.inspect_linked_recovery_history(PROJECT_ID, PLAN_REVERSIBLE)
        by_id = {i.recovery_attempt_id: i for i in links}
        sibling = engine.build_recovery_links(PROJECT_ID, PLAN_DESTRUCTIVE)

        checks["attempts-projected"] = (len(links) == 2, f"{len(links)} recovery links")
        checks["attempt-linked-by-case"] = (
            all(i.recovery_case_id == "recovery_case_a" for i in links),
            "attempts are reached through the plan's repair case",
        )
        checks["attempt-linked-by-strategy-flagged"] = (
            all(i.linked_by_strategy_id for i in links),
            "the owner named this exact strategy, so the link is strategy-scoped",
        )
        checks["case-only-link-warns"] = (
            bool(sibling)
            and all(not i.linked_by_strategy_id for i in sibling)
            and all(
                any("through the repair case" in w for w in i.warnings) for i in sibling
            ),
            "a case-only link is flagged and warned about",
        )
        checks["attempted-reflects-owner"] = (
            all(i.attempted for i in links), "attempted follows the owner's status"
        )
        checks["completed-requires-attempt"] = _expect_error(
            type(links[0]),
            repair_recovery_link_id="x",
            repair_plan_id=PLAN_REVERSIBLE,
            source_record_id="a",
            source_record_digest="a" * 64,
            recovery_attempt_id="a",
            attempted=False,
            completed=True,
        )
        checks["succeeded-reflects-owner-only"] = (
            by_id["recovery_attempt_a"].succeeded_by_owner is True
            and by_id["recovery_attempt_b"].succeeded_by_owner is False,
            "success follows only the owner's own attempt status",
        )
        queue = {
            i["repair_plan_id"]: i
            for i in engine.build_repair_plan_queue(PROJECT_ID)["items"]
        }
        checks["sibling-success-not-inherited"] = (
            queue[PLAN_REVERSIBLE]["completed"] is True
            and queue[PLAN_DESTRUCTIVE]["completed"] is False,
            "a sibling strategy never inherits another strategy's recovery success",
        )
        checks["failed-attempt-flagged"] = (
            by_id["recovery_attempt_b"].original_status == "failed"
            and payload["failed_attempt_count"] == 1,
            "the failed attempt is reported",
        )
        checks["failed-attempt-warns"] = (
            any("failed" in w for w in by_id["recovery_attempt_b"].warnings),
            "the failed attempt carries an explicit warning",
        )
        checks["rollback-attempt-surfaced"] = (
            by_id["recovery_attempt_b"].rollback_attempted is True,
            "the rollback record for the failed attempt is surfaced",
        )
        checks["rollback-status-verbatim"] = (
            by_id["recovery_attempt_b"].rollback_status == "completed",
            "the owner's rollback status is projected verbatim",
        )
        checks["failure-class-verbatim"] = (
            by_id["recovery_attempt_b"].resulting_failure_class == "repeated_crash",
            "the owner's failure class is projected verbatim",
        )
        checks["validation-source-ids-listed"] = (
            by_id["recovery_attempt_a"].verification_source_ids == ["recovery_validation_a"],
            "the owner's output-validation ids are listed",
        )
        checks["independent-verification-always-false"] = (
            all(i.independently_verified is False for i in links)
            and payload["independently_verified_count"] == 0,
            "the panel never claims independent verification of a recovery",
        )
        checks["recovered-is-not-resolved"] = (
            any("recovered is not resolved" in t.lower() for t in payload["limitations"]),
            "the payload states recovered is not resolved",
        )
        checks["no-recovery-started-by-panel"] = (
            payload["recovery_started_by_panel"] is False,
            "no recovery is started by the panel",
        )
        checks["attempt-timestamps-from-owner"] = (
            by_id["recovery_attempt_a"].started_at == "2026-02-01T11:00:00+00:00",
            "attempt timestamps come from the owner's own record",
        )
        again = engine.build_recovery_links(PROJECT_ID, PLAN_REVERSIBLE)
        checks["recovery-link-ids-deterministic"] = (
            [i.repair_recovery_link_id for i in links]
            == [i.repair_recovery_link_id for i in again],
            "recovery link ids are stable",
        )
        checks["recovery-limitations-present"] = (
            all(i.limitations for i in links), "every recovery link carries limitations"
        )
    return _group("recovery", checks)


def _run_conflicts() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)

        def types_for(engine: BobaRepairPlanReviewV1, plan: str) -> dict[str, Any]:
            return {
                i.conflict_type: i
                for i in engine.detect_repair_plan_conflicts(PROJECT_ID, plan)
            }

        base, _ = _engine(root / "a")
        base_types = types_for(base, PLAN_CODE_CHANGE)

        dup, _ = _raw_engine(
            root / "dup",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[
                        synthetic_strategy(PLAN_REVERSIBLE).model_dump(mode="json"),
                        synthetic_strategy(
                            PLAN_REVERSIBLE, estimated_risk="critical"
                        ).model_dump(mode="json"),
                    ]
                )
            },
        )
        dup_types = types_for(dup, PLAN_REVERSIBLE)
        checks["duplicate-plan-identity-detected"] = (
            "plan_identity_conflict" in dup_types, "a duplicated plan identity is detected"
        )
        checks["duplicate-plan-blocks-action"] = (
            "plan_identity_conflict" in dup_types
            and dup_types["plan_identity_conflict"].blocks_action is True,
            "a duplicated plan identity blocks the action",
        )
        two_cases, _ = _raw_engine(
            root / "cases",
            {
                "repair_planner": _planner_dict(
                    repair_cases=[
                        synthetic_planning_case().model_dump(mode="json"),
                        synthetic_planning_case(analysis_case_id="analysis_other").model_dump(
                            mode="json"
                        ),
                    ]
                )
            },
        )
        checks["case-parent-disagreement-detected"] = (
            "analysis_identity_conflict" in types_for(two_cases, PLAN_REVERSIBLE),
            "records disagreeing about the analysis parent are reported",
        )
        two_analysis, _ = _raw_engine(
            root / "an",
            {
                "root_cause_analyzer": synthetic_root_cause_set(
                    PROJECT_ID,
                    cases=[
                        synthetic_analysis_case(),
                        synthetic_analysis_case(incident_id="case_other"),
                    ],
                ).model_dump(mode="json")
            },
        )
        checks["analysis-parent-disagreement-detected"] = (
            "incident_identity_conflict" in types_for(two_analysis, PLAN_REVERSIBLE),
            "records disagreeing about the incident parent are reported",
        )
        noappr, _ = _raw_engine(
            root / "noappr",
            {
                "repair_planner": _planner_dict(
                    approval_gates=[
                        synthetic_approval_gate(
                            approval_status="not_required_for_no_action"
                        ).model_dump(mode="json")
                    ]
                )
            },
        )
        checks["approval-status-conflict-detected"] = (
            "approval_status_conflict" in types_for(noappr, PLAN_CODE_CHANGE),
            "an approval gate that contradicts the strategy is reported",
        )
        checks["non-destructive-but-actionable-detected"] = (
            "destructive_flag_conflict" in base_types,
            "a non-destructive rating on an acting strategy is reported",
        )
        checks["reversible-but-destructive-detected"] = (
            "destructive_flag_conflict" in types_for(base, PLAN_DESTRUCTIVE),
            "fully reversible and blocked at once is reported",
        )
        norollback, _ = _raw_engine(
            root / "norb", {"repair_planner": _planner_dict(rollback_plans=[])}
        )
        checks["rollback-required-but-absent-detected"] = (
            "rollback_conflict" in types_for(norollback, PLAN_REVERSIBLE),
            "a required but absent rollback plan is reported",
        )
        rb_off, _ = _raw_engine(
            root / "rboff",
            {
                "repair_planner": _planner_dict(
                    rollback_plans=[
                        synthetic_rollback_plan(rollback_required=False).model_dump(
                            mode="json"
                        )
                    ]
                )
            },
        )
        checks["rollback-not-required-but-destructive-detected"] = (
            "rollback_conflict" in types_for(rb_off, PLAN_DESTRUCTIVE),
            "no rollback required on a destructive strategy is reported",
        )
        novalidators, _ = _raw_engine(
            root / "nov",
            {
                "repair_planner": _planner_dict(
                    validation_plans=[
                        synthetic_validation_plan(required_validators=[]).model_dump(
                            mode="json"
                        )
                    ]
                )
            },
        )
        checks["validator-runner-without-validators-detected"] = (
            "verification_conflict" in types_for(novalidators, PLAN_REVERSIBLE),
            "requiring Validator Runner with no validators named is reported",
        )
        failed_validator, _ = _raw_engine(
            root / "fv",
            {
                "validator_runner": _validator_payload(
                    {"result_id": "r", "validator_id": "baseline_comparison", "status": "failed"}
                )
            },
        )
        fv_types = types_for(failed_validator, PLAN_REVERSIBLE)
        checks["plan-ready-with-failed-validator-detected"] = (
            "verification_conflict" in fv_types
            and fv_types["verification_conflict"].blocks_action is True,
            "a ready plan with a failing required validator is blocking",
        )
        checks["recovery-status-conflict-detected"] = (
            "recovery_status_conflict" in types_for(base, PLAN_REVERSIBLE),
            "owner success against unmet required checks is reported",
        )
        notrec, _ = _raw_engine(
            root / "notrec",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[
                        synthetic_strategy(PLAN_REVERSIBLE, recommended=False).model_dump(
                            mode="json"
                        )
                    ]
                )
            },
        )
        checks["recommended-flag-conflict-detected"] = (
            "strategy_conflict" in types_for(notrec, PLAN_REVERSIBLE),
            "a case/strategy recommendation disagreement is reported",
        )
        both, _ = _raw_engine(
            root / "both",
            {
                "repair_planner": _planner_dict(
                    repair_cases=[
                        synthetic_planning_case(
                            rejected_strategy_ids=[PLAN_REVERSIBLE]
                        ).model_dump(mode="json")
                    ]
                )
            },
        )
        both_types = types_for(both, PLAN_REVERSIBLE)
        checks["active-and-rejected-detected"] = (
            "lifecycle_conflict" in both_types
            and both_types["lifecycle_conflict"].blocks_action is True,
            "a strategy listed active and rejected is blocking",
        )
        noneed, _ = _raw_engine(
            root / "noneed",
            {
                "repair_planner": _planner_dict(
                    repair_cases=[
                        synthetic_planning_case(repair_needed=False).model_dump(mode="json")
                    ]
                )
            },
        )
        checks["repair-not-needed-but-actionable-detected"] = (
            "lifecycle_conflict" in types_for(noneed, PLAN_CODE_CHANGE),
            "repair_needed=false against an acting strategy is reported",
        )
        notreq, _ = _raw_engine(
            root / "notreq",
            {
                "repair_planner": _planner_dict(
                    repair_cases=[
                        synthetic_planning_case(
                            planning_status="repair_not_required"
                        ).model_dump(mode="json")
                    ]
                )
            },
        )
        checks["not-required-but-typed-detected"] = (
            "lifecycle_conflict" in types_for(notreq, PLAN_REVERSIBLE),
            "repair_not_required against a typed strategy is reported",
        )
        stage, _ = _raw_engine(
            root / "stage",
            {
                "tool_recovery": {
                    "schema_version": "boba_tool_recovery_brain_v1",
                    "recovery_cases": [
                        {
                            "recovery_case_id": "recovery_case_a",
                            "source_repair_case_id": REPAIR_CASE_ID,
                            "source_repair_strategy_ids": [PLAN_REVERSIBLE],
                            "workflow_stage": "assemble",
                        }
                    ],
                }
            },
        )
        checks["workflow-stage-disagreement-detected"] = (
            "workflow_identity_conflict" in types_for(stage, PLAN_REVERSIBLE),
            "a recovery case naming a different stage is reported",
        )
        all_conflicts = [
            i
            for plan in (PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_DESTRUCTIVE)
            for i in base.detect_repair_plan_conflicts(PROJECT_ID, plan)
        ]
        checks["conflict-requires-same-identity"] = (
            all(i.same_repair_plan for i in all_conflicts),
            "every conflict names the same exact plan identity",
        )
        checks["conflict-never-auto-resolved"] = (
            all(not i.resolved and i.resolution_source_id is None for i in all_conflicts)
            and base.inspect_repair_plan_conflicts(PROJECT_ID, PLAN_REVERSIBLE)[
                "auto_resolved_count"
            ]
            == 0,
            "no conflict is resolved automatically",
        )
        checks["conflict-requires-human-review"] = (
            all(i.human_review_required for i in all_conflicts),
            "every conflict requires human review",
        )
        first_pass = base.detect_repair_plan_conflicts(PROJECT_ID, PLAN_CODE_CHANGE)
        again = base.detect_repair_plan_conflicts(PROJECT_ID, PLAN_CODE_CHANGE)
        checks["conflict-ids-deterministic"] = (
            [i.conflict_record_id for i in first_pass]
            == [i.conflict_record_id for i in again],
            "conflict record ids are stable",
        )
        checks["no-supersession-claimed"] = (
            all(not i.explicit_supersession_found for i in all_conflicts),
            "no conflict claims an explicit supersession the owner never recorded",
        )
    return _group("conflicts", checks)


def _run_queue() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _ = _engine(root / "a")
        queue = engine.build_repair_plan_queue(PROJECT_ID)
        tiers = {i["repair_plan_id"]: i["priority_tier"] for i in queue["items"]}

        checks["queue-builds"] = (queue["total_count"] == 4, f"{queue['total_count']} plans")
        checks["tier-count-is-fourteen"] = (
            len(repair_plan_queue_priority_tiers()) == 14,
            f"{len(repair_plan_queue_priority_tiers())} display tiers",
        )
        checks["destructive-awaiting-approval-tier"] = (
            tiers[PLAN_DESTRUCTIVE] == 10 and tiers[PLAN_CHECKPOINT] == 10,
            f"destructive plans sit in tier 10: {tiers}",
        )
        checks["code-artifact-workflow-tier"] = (
            tiers[PLAN_CODE_CHANGE] == 20, "the code-change plan sits in tier 20"
        )
        restart_only = synthetic_strategy(
            PLAN_CHECKPOINT,
            strategy_type="repair_environment",
            destructiveness="none",
            reversibility="unknown",
            steps=[
                synthetic_step(
                    "restart_step_1",
                    strategy_id=PLAN_CHECKPOINT,
                    order=1,
                    step_type="restart_service",
                    description="Restart the render worker.",
                    target="render_worker_reference",
                    read_only=True,
                )
            ],
        )
        cp_only, _ = _raw_engine(
            root / "cponly",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[restart_only.model_dump(mode="json")]
                ),
                "tool_recovery": {"schema_version": "x", "recovery_cases": []},
            },
        )
        cp_items = cp_only.build_repair_plan_queue(PROJECT_ID)["items"]
        checks["checkpoint-restart-tier"] = (
            bool(cp_items) and cp_items[0]["priority_tier"] == 30,
            "a process-restarting non-destructive plan sits in tier 30"
            if cp_items
            else "no queue item was produced",
        )
        checks["missing-verification-tier"] = (
            any(i["missing_verification_count"] > 0 for i in queue["items"]),
            "plans missing verification are tracked",
        )
        checks["failed-recovery-tier"] = (
            any(i["failed_recovery_attempt_count"] > 0 for i in queue["items"]),
            "plans linked to a failed recovery attempt are tracked",
        )
        checks["completed-unverified-tier"] = (
            tiers[PLAN_REVERSIBLE] == 120,
            "the owner-completed but unverified plan sits in tier 120",
        )
        checks["other-current-tier"] = (
            all(1 <= v <= 140 for v in tiers.values()),
            "every plan lands in a catalogued display tier",
        )
        checks["tier-is-not-a-score"] = (
            all("never a score" in " ".join(i["limitations"]) for i in queue["items"]),
            "every queue item states the tier is not a score",
        )
        checks["deterministic-sort-key"] = (
            [i["deterministic_sort_key"] for i in queue["items"]]
            == [
                i["deterministic_sort_key"]
                for i in engine.build_repair_plan_queue(PROJECT_ID)["items"]
            ],
            "sort keys are stable across rebuilds",
        )
        checks["sort-review-priority"] = (
            [i["priority_tier"] for i in queue["items"]]
            == sorted(i["priority_tier"] for i in queue["items"]),
            "review priority orders by display tier",
        )
        sev = engine.build_repair_plan_queue(PROJECT_ID, active_sort="source_severity")
        checks["sort-source-severity"] = (
            sev["items"][0]["original_risk_level"] == "critical",
            "source severity orders by the owner's own risk level",
        )
        creation = engine.build_repair_plan_queue(PROJECT_ID, active_sort="creation_order")
        checks["sort-creation-order"] = (
            next(i["repair_plan_id"] for i in creation["items"]) == PLAN_REVERSIBLE,
            "creation order follows the owner's own list order",
        )
        by_steps = engine.build_repair_plan_queue(PROJECT_ID, active_sort="step_count")
        checks["sort-step-count"] = (
            by_steps["items"][0]["step_count"] == 3, "step count sorts descending"
        )
        checks["unsupported-sort-refused"] = _expect_error(
            engine.build_repair_plan_queue, PROJECT_ID, active_sort="best_first"
        )
        dest = engine.build_repair_plan_queue(PROJECT_ID, active_filter="destructive")
        checks["filter-destructive"] = (
            all(i["destructive"] for i in dest["items"]) and dest["filtered_count"] >= 2,
            f"{dest['filtered_count']} destructive plans",
        )
        missing = engine.build_repair_plan_queue(PROJECT_ID, active_filter="missing_approval")
        checks["filter-missing-approval"] = (
            all(i["missing_approval_count"] > 0 for i in missing["items"]),
            "the missing-approval filter only returns unsatisfied plans",
        )
        checks["unsupported-filter-refused"] = _expect_error(
            engine.build_repair_plan_queue, PROJECT_ID, active_filter="safe_ones"
        )
        page = engine.build_repair_plan_queue(PROJECT_ID, offset=0, limit=2)
        checks["paging-bounded"] = (
            page["returned_count"] == 2 and page["has_more"] is True,
            "paging is bounded and reports whether more remain",
        )
    return _group("queue", checks)


def _run_comparison() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        engine, _ = _engine(Path(raw) / "a")
        comparison = engine.compare_repair_plans(
            PROJECT_ID, [PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_DESTRUCTIVE]
        )["comparison"]

        checks["comparison-builds"] = (
            len(comparison["repair_plan_ids"]) == 3, "three plans compared"
        )
        checks["requires-two-plans"] = _expect_error(
            engine.compare_repair_plans, PROJECT_ID, [PLAN_REVERSIBLE]
        )
        checks["limit-enforced"] = _expect_error(
            engine.compare_repair_plans,
            PROJECT_ID,
            [PLAN_REVERSIBLE, PLAN_CODE_CHANGE, PLAN_CHECKPOINT, PLAN_DESTRUCTIVE, "extra"],
        )
        collapsed = engine.compare_repair_plans(
            PROJECT_ID, [PLAN_REVERSIBLE, PLAN_REVERSIBLE, PLAN_CODE_CHANGE]
        )["comparison"]
        checks["duplicate-ids-collapsed"] = (
            collapsed["repair_plan_ids"] == [PLAN_REVERSIBLE, PLAN_CODE_CHANGE],
            "duplicate ids are collapsed, never double-counted",
        )
        checks["same-repair-case-detected"] = (
            comparison["same_repair_case"] is True, "the shared repair case is detected"
        )
        checks["same-incident-detected"] = (
            comparison["same_incident"] is True, "the shared incident is detected"
        )
        for condition, axis in (
            ("strategy-axis-present", "strategy_comparison"),
            ("step-axis-present", "step_comparison"),
            ("approval-axis-present", "approval_comparison"),
            ("risk-axis-present", "risk_comparison"),
            ("rollback-axis-present", "rollback_comparison"),
            ("recovery-axis-present", "recovery_comparison"),
        ):
            rows = comparison[axis]
            checks[condition] = (
                len(rows) == 3 and all("repair_plan_id" in r for r in rows),
                f"{axis} has one row per plan",
            )
        checks["no-automatic-winner"] = (
            comparison["no_automatic_winner"] is True, "no winner is selected"
        )
        checks["no-automatic-plan-selection"] = (
            comparison["no_automatic_plan_selection"] is True, "no plan is selected"
        )
        checks["no-automatic-execution-selection"] = (
            comparison["no_automatic_execution_selection"] is True,
            "no plan is selected for execution",
        )
        checks["missing-fields-listed"] = (
            isinstance(comparison["missing_field_paths"], list)
            and all(
                r["rollback_guaranteed"] is False for r in comparison["rollback_comparison"]
            ),
            "missing fields are listed and rollback is never called guaranteed",
        )
    return _group("comparison", checks)


def _run_actions() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    registry = build_fixed_repair_plan_action_registry()
    available = [i for i in registry.values() if i.availability == "available"]
    unavailable = [i for i in registry.values() if i.availability == "unavailable"]
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _owner = _engine(root / "a")
        payload = _prepared(engine, PLAN_CHECKPOINT)

        checks["eleven-descriptors"] = (len(registry) == 11, f"{len(registry)} descriptors")
        checks["one-available-action"] = (
            len(available) == 1 and available[0].action_descriptor_id == _ACK,
            f"one available action: {available[0].action_descriptor_id}",
        )
        checks["ten-unavailable-actions"] = (
            len(unavailable) == 10, f"{len(unavailable)} unavailable actions"
        )
        checks["every-unavailable-has-reason"] = (
            all(i.unavailable_reason for i in unavailable),
            "every unavailable action states its exact reason",
        )
        checks["available-action-not-authoritative"] = (
            available[0].authoritative is False,
            "the available action is not authoritative over the plan",
        )
        checks["available-action-not-execution-capable"] = (
            not any(
                i.execution_capable or i.destructive or i.code_modifying
                or i.artifact_modifying or i.workflow_modifying or i.checkpoint_restoring
                or i.process_restarting or i.upload_or_publication
                for i in available
            ),
            "the available action cannot execute or modify anything",
        )
        for condition, action_id in (
            ("approve-plan-unavailable", "repair_plan_action_approve_plan_v1"),
            ("reject-plan-unavailable", "repair_plan_action_reject_plan_v1"),
            ("revise-plan-unavailable", "repair_plan_action_request_plan_revision_v1"),
            ("regenerate-plan-unavailable", "repair_plan_action_request_plan_regeneration_v1"),
            ("recovery-attempt-unavailable", "repair_plan_action_request_recovery_attempt_v1"),
            ("tool-retry-unavailable", "repair_plan_action_request_tool_retry_v1"),
            ("checkpoint-restore-unavailable", "repair_plan_action_request_checkpoint_restore_v1"),
            ("escalate-unavailable", "repair_plan_action_escalate_plan_v1"),
            ("review-note-unavailable", "repair_plan_action_record_plan_review_note_v1"),
            ("acknowledge-plan-unavailable", "repair_plan_action_acknowledge_plan_v1"),
        ):
            descriptor = registry[action_id]
            checks[condition] = (
                descriptor.availability == "unavailable"
                and bool(descriptor.unavailable_reason)
                and action_id not in payload["snapshot"]["available_action_descriptor_ids"],
                f"{action_id}: {descriptor.unavailable_reason[:70]}",
            )
        checks["unavailable-action-request-refused"] = _expect_error(
            _request, engine, payload, "idem_unavailable_key",
            action="repair_plan_action_approve_plan_v1", decision="approve", reason="please",
        )
        checks["confirmation-digest-required"] = (
            bool(payload["action_confirmations"].get(_ACK))
            and len(payload["action_confirmations"][_ACK]) == 64,
            "a sha256 confirmation digest is required",
        )
        checks["wrong-confirmation-refused"] = _expect_error(
            _request, engine, payload, "idem_wrong_digest_key", digest="0" * 64
        )
        checks["unconfirmed-refused"] = _expect_error(
            _request, engine, payload, "idem_unconfirmed_key", confirmed=False
        )
        checks["secret-reason-refused"] = _expect_error(
            _request, engine, payload, "idem_secret_key",
            reason="api_key=AKIAIOSFODNN7EXAMPLE",
        )
        checks["private-path-reason-refused"] = _expect_error(
            _request, engine, payload, "idem_path_key", reason=PRIVATE_PATH_TARGET
        )
        checks["command-reason-refused"] = _expect_error(
            _request, engine, payload, "idem_command_key", reason=COMMAND_TARGET
        )
        checks["action-requires-current-plan"] = (
            _ACK in payload["snapshot"]["available_action_descriptor_ids"]
            and payload["snapshot"]["current"] is True,
            "the action is only offered for a current plan",
        )
        dup_engine, _ = _raw_engine(
            root / "amb",
            {
                "repair_planner": _planner_dict(
                    repair_strategies=[
                        synthetic_strategy(PLAN_REVERSIBLE).model_dump(mode="json"),
                        synthetic_strategy(
                            PLAN_REVERSIBLE, estimated_risk="critical"
                        ).model_dump(mode="json"),
                    ]
                )
            },
        )
        amb = _prepared(dup_engine, PLAN_REVERSIBLE)
        checks["ambiguous-identity-withholds-action"] = (
            amb["snapshot"]["available_action_descriptor_ids"] == [],
            "an ambiguous identity chain withholds every action",
        )
        no_incident, _ = _raw_engine(
            root / "noinc",
            {"root_cause_analyzer": {"schema_version": "x", "analysis_cases": []}},
        )
        ni = _prepared(no_incident, PLAN_CHECKPOINT)
        checks["missing-incident-withholds-action"] = (
            ni["snapshot"]["available_action_descriptor_ids"] == [],
            "with no incident identity the acknowledgement is withheld",
        )
    return _group("actions", checks)


def _run_security() -> list[ScenarioResult]:
    import re

    checks: dict[str, tuple[bool, str]] = {}
    source = _source_text()
    with tempfile.TemporaryDirectory() as raw:
        engine, _ = _engine(Path(raw) / "a")
        review = engine.build_repair_plan_review(PROJECT_ID)
        usage = review["signal_usage"]
        layer_ops = {
            key.split(".", 1)[1]
            for key in build_boba_operation_registry()
            if key.startswith("repair_plan_review.")
        }
        safety_ops = build_safety_module_operation_registry().get("repair_plan_review", {})
        module = build_boba_module_registry()["repair_plan_review"]
        calls = set(re.findall(r"self\.integration\.([a-z_]+)", source))

        checks["no-execution-operation"] = (
            not any("execute" in op or "run" in op for op in layer_ops),
            f"no execution operation is registered: {sorted(layer_ops)[:4]}...",
        )
        for condition, flag in (
            ("no-command-execution", "command_execution_used"),
            ("no-shell-execution", "shell_execution_used"),
            ("no-git-execution", "git_execution_used"),
            ("no-ffmpeg-execution", "ffmpeg_execution_used"),
            ("no-package-installation", "package_installation_used"),
            ("no-code-modification", "code_modified_by_panel"),
            ("no-artifact-modification", "artifact_modified_by_panel"),
            ("no-source-media-modification", "source_media_modified"),
            ("no-accepted-output-modification", "accepted_output_modified"),
            ("no-checkpoint-restore", "checkpoint_restored_by_panel"),
            ("no-process-restart", "process_restarted_by_panel"),
            ("no-workflow-change", "workflow_changed_by_panel"),
            ("no-plan-creation", "plan_created_by_panel"),
            ("no-plan-revision", "plan_revised_by_panel"),
            ("no-local-approval", "approval_created_locally"),
            ("no-local-safety-decision", "safety_decision_created_locally"),
            ("no-local-rights-decision", "rights_decision_created_locally"),
            ("no-upload", "upload_used"),
            ("no-publication", "publication_used"),
            ("no-arbitrary-module", "arbitrary_module_used"),
            ("no-arbitrary-operation", "arbitrary_operation_used"),
        ):
            checks[condition] = (
                usage[flag] is False, f"signal_usage.{flag} is pinned false"
            )
        checks["fixed-integration-calls-only"] = (
            calls == {"create_boba_review_session", "acknowledge_boba_review_notification"},
            f"the module calls only its two fixed owner helpers: {sorted(calls)}",
        )
        checks["safety-classifications-read-only"] = (
            bool(safety_ops)
            and set(safety_ops.values()) <= {"automatic_read_only", "approval_required_read_only"}
            and safety_ops.get("submit_action") == "approval_required_read_only",
            f"{len(safety_ops)} classifications, all read-only",
        )
        checks["no-arbitrary-url"] = (
            "http://" not in source and "requests." not in source,
            "the module fetches no URL",
        )
        checks["module-deps-declared"] = (
            "repair_planner" in module.dependency_module_ids
            and "review_ui" in module.dependency_module_ids,
            f"{len(module.dependency_module_ids)} declared dependencies",
        )
        checks["module-not-execution-capable"] = (
            module.execution_capable is False and module.read_only is True,
            "the registered module is read-only and not execution capable",
        )
    return _group("security", checks)


def _run_persistence() -> list[ScenarioResult]:
    checks: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, _owner = _engine(root / "a")
        session = engine.create_repair_plan_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        sid = session.repair_plan_review_session_id

        checks["session-persisted"] = (
            engine.get_repair_plan_review_session(PROJECT_ID, sid).reviewer_context_id
            == "reviewer_a",
            "the session round-trips through the store",
        )
        checks["session-project-scoped"] = _expect_error(
            engine.get_repair_plan_review_session, "other-project", sid
        )
        expired, _ = _engine(root / "exp")
        short = expired.create_repair_plan_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a", expires_in_seconds=60
        )
        path = expired.store.boba_repair_plan_review_session_path(
            PROJECT_ID, short.repair_plan_review_session_id
        )
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
        raw_payload["expires_at"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(raw_payload), encoding="utf-8")
        checks["session-expiry-enforced"] = _expect_error(
            expired.get_repair_plan_review_session,
            PROJECT_ID,
            short.repair_plan_review_session_id,
        )
        checks["session-field-allowlist"] = _expect_error(
            engine.update_repair_plan_review_session,
            PROJECT_ID, sid, {"plan_status": "approved"},
        )
        checks["comparison-limit-enforced"] = _expect_error(
            engine.update_repair_plan_review_session,
            PROJECT_ID, sid,
            {"comparison_repair_plan_ids": ["a", "b", "c", "d", "e"]},
        )
        annotated = engine.update_repair_plan_review_session(
            PROJECT_ID, sid,
            {
                "local_annotations": [
                    {"text": "Needs a second reviewer.", "repair_plan_id": PLAN_REVERSIBLE}
                ]
            },
        )
        checks["annotation-bounded"] = (
            len(annotated.local_annotations) == 1
            and len(annotated.local_annotations[0]["text"]) <= 4_000,
            "annotations are bounded",
        )
        checks["annotation-label-present"] = (
            annotated.local_annotations[0]["notice"]
            == "Review-session annotation — not part of the canonical repair plan.",
            "the exact non-canonical annotation label is attached",
        )
        checks["secret-annotation-rejected"] = _expect_error(
            engine.update_repair_plan_review_session,
            PROJECT_ID, sid, {"local_annotations": [{"text": "password=hunter2hunter2"}]},
        )
        checks["command-annotation-rejected"] = _expect_error(
            engine.update_repair_plan_review_session,
            PROJECT_ID, sid, {"local_annotations": [{"text": COMMAND_TARGET}]},
        )
        first = engine.build_repair_plan_review_registry(PROJECT_ID)
        second = engine.build_repair_plan_review_registry(PROJECT_ID)
        checks["immutable-registry"] = (
            first["registry_snapshot"] == second["registry_snapshot"],
            "the registry snapshot is immutable and stable",
        )
        payload = _prepared(engine, PLAN_CHECKPOINT)
        request = _request(engine, payload, "idem_persist_key")
        checks["immutable-submitted-action"] = _expect_error(
            engine.store.save_boba_repair_plan_review_action,
            PROJECT_ID,
            request.repair_plan_action_request_id,
            {"repair_plan_action_request_id": "tampered"},
        )
        receipt = asyncio.run(
            engine.submit_repair_plan_action_to_owner(
                PROJECT_ID, request.repair_plan_action_request_id
            )
        )
        checks["immutable-receipt"] = _expect_error(
            engine.store.save_boba_repair_plan_review_receipt,
            PROJECT_ID,
            receipt.repair_plan_action_receipt_id,
            {"repair_plan_action_receipt_id": "tampered"},
        )
        repeat = asyncio.run(
            engine.submit_repair_plan_action_to_owner(
                PROJECT_ID, request.repair_plan_action_request_id
            )
        )
        checks["duplicate-submission-reused"] = (
            repeat.duplicate_request_reused is True
            and repeat.repair_plan_action_receipt_id == receipt.repair_plan_action_receipt_id,
            "a repeated submission reuses the existing receipt",
        )
        drift_engine, _ = _engine(root / "drift")
        drift_payload = _prepared(drift_engine, PLAN_CHECKPOINT)
        drift_request = _request(drift_engine, drift_payload, "idem_drift_key")
        drift_engine.store.save_boba_repair_planner(
            synthetic_repair_planner_set(
                PROJECT_ID,
                risk_assessments=[synthetic_risk_assessment(overall_risk="blocked")],
            )
        )
        drift_receipt = asyncio.run(
            drift_engine.submit_repair_plan_action_to_owner(
                PROJECT_ID, drift_request.repair_plan_action_request_id
            )
        )
        checks["stale-state-rejected"] = (
            drift_receipt.stale_state_rejected is True
            and drift_receipt.accepted_by_owner is False,
            f"drifted state refused: {drift_receipt.error_code}",
        )
        checks["receipt-cannot-claim-change"] = _expect_error(
            engine._persist_receipt,
            PROJECT_ID,
            receipt.model_copy(
                update={
                    "repair_plan_action_receipt_id": "repair_plan_receipt_forged",
                    "plan_approved": True,
                    "canonical_record_id": None,
                    "canonical_record_digest": None,
                }
            ),
        )
        engine.build_repair_plan_review(PROJECT_ID)
        review_path = engine.store.boba_repair_plan_review_path(PROJECT_ID)
        stored = json.loads(review_path.read_text(encoding="utf-8"))
        checks["source-records-not-duplicated"] = (
            "repair_strategies" not in stored and "proposed_steps" not in json.dumps(stored),
            "the panel stores projections, never a copy of the owner's records",
        )
        reset = engine.reset_repair_plan_review_metadata(PROJECT_ID, sid)
        checks["reset-preserves-repair-plans"] = (
            reset["repair_plan_records_preserved"] is True,
            "the reset preserves every repair plan record",
        )
        checks["reset-preserves-recovery-history"] = (
            reset["recovery_history_preserved"] is True,
            "the reset preserves recovery history",
        )
        full = engine.reset_repair_plan_review_metadata(PROJECT_ID)
        checks["reset-preserves-receipts"] = (
            full["action_receipt_history_preserved"] is True
            and engine.build_repair_plan_references(PROJECT_ID) != [],
            "the reset preserves receipts and leaves owner records readable",
        )
        export = engine.export_repair_plan_review(PROJECT_ID)
        checks["sanitized-export"] = (
            export["privacy"]["raw_commands_excluded"] is True
            and export["privacy"]["private_paths_excluded"] is True
            and export["privacy"]["plan_executed"] is False,
            "the export declares and honours its exclusions",
        )
    return _group("persistence", checks)


_GROUP_RUNNERS: dict[str, Callable[[], list[ScenarioResult]]] = {
    "identity": _run_identity,
    "plan-truth": _run_plan_truth,
    "steps": _run_steps,
    "commands": _run_commands,
    "risk": _run_risk,
    "approvals": _run_approvals,
    "verification": _run_verification,
    "evidence": _run_evidence,
    "recovery": _run_recovery,
    "conflicts": _run_conflicts,
    "queue": _run_queue,
    "comparison": _run_comparison,
    "actions": _run_actions,
    "security": _run_security,
    "persistence": _run_persistence,
}


def run_named_scenario(name: str) -> ScenarioResult:
    """Run one catalogued condition by its ``group:condition`` name."""
    if name not in SCENARIO_NAMES:
        raise ValidationError(f"Unknown repair plan review scenario: {name}")
    group = name.rsplit(":", 1)[0]
    for result in _GROUP_RUNNERS[group]():
        if result.name == name:
            return result
    raise ValidationError(f"Scenario {name} produced no result.")


def run_all_scenarios() -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for group in _CONDITION_GROUPS:
        results.extend(_GROUP_RUNNERS[group]())
    return results


def run_self_check() -> list[ScenarioResult]:
    """Prove the panel's declared boundaries against the real repository."""
    results: list[ScenarioResult] = []
    source = _source_text()
    frontend = _frontend_text()
    registry = build_fixed_repair_plan_action_registry()
    sources = build_fixed_repair_source_registry()
    sections = build_fixed_repair_section_registry()
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        engine, owner = _engine(root / "self")
        review = engine.build_repair_plan_review(PROJECT_ID)
        usage = review["signal_usage"]
        payload = _prepared(engine, PLAN_CHECKPOINT)
        request = _request(engine, payload, "idem_self_check_key")
        receipt = asyncio.run(
            engine.submit_repair_plan_action_to_owner(
                PROJECT_ID, request.repair_plan_action_request_id
            )
        )
        registry_one = engine.build_repair_plan_review_registry(PROJECT_ID)
        registry_two = engine.build_repair_plan_review_registry(PROJECT_ID)
        layer_ops = {
            key.split(".", 1)[1]
            for key in build_boba_operation_registry()
            if key.startswith("repair_plan_review.")
        }
        safety_ops = build_safety_module_operation_registry().get("repair_plan_review", {})
        confirmation = engine.describe_repair_plan_action_confirmation(
            PROJECT_ID, payload["snapshot"]["repair_plan_snapshot_id"], _ACK
        )

        def add(name: str, passed: bool, detail: str) -> None:
            results.append(_check(f"self-check:{name}", passed, detail))

        add(
            "module-imports",
            bool(sources) and bool(sections) and bool(registry),
            "the module, its registries and its contracts import cleanly",
        )
        add(
            "contracts-serialize",
            isinstance(json.dumps(review), str),
            "the whole review set serialises to JSON",
        )
        add(
            "registry-builds",
            len(registry_one["sources"]) == 14 and len(registry_one["actions"]) == 11,
            f"{len(registry_one['sources'])} sources, {len(registry_one['actions'])} actions",
        )
        add(
            "registry-immutable",
            registry_one["registry_snapshot"] == registry_two["registry_snapshot"],
            "rebuilding the registry returns the identical immutable snapshot",
        )
        add(
            "every-store-loader-exists",
            all(hasattr(engine.store, str(row["loader"])) for row in sources.values()),
            "every fixed source names a real store loader",
        )
        add(
            "operations-registered",
            len(layer_ops) == 27,
            f"{len(layer_ops)} fixed integration-layer operations",
        )
        add(
            "safety-classified",
            len(safety_ops) == 27,
            f"{len(safety_ops)} Safety Gate classifications",
        )
        add(
            "safety-submit-requires-approval",
            safety_ops.get("submit_action") == "approval_required_read_only",
            "submit_action is approval-required read-only",
        )
        add(
            "no-execution-classification",
            set(safety_ops.values())
            <= {"automatic_read_only", "approval_required_read_only"},
            "no operation is classified as execution capable",
        )
        add(
            "one-available-action",
            len(registry_one["registry_snapshot"]["available_action_descriptor_ids"]) == 1,
            "exactly one action is available in V1",
        )
        add(
            "ten-unavailable-actions",
            len(registry_one["registry_snapshot"]["unavailable_action_descriptor_ids"]) == 10,
            "ten actions are declared unavailable with reasons",
        )
        add(
            "acknowledgement-routed-to-owner",
            receipt.accepted_by_owner is True
            and receipt.owning_module_id == "review_ui"
            and receipt.owning_operation_id == "acknowledge_notification",
            "the acknowledgement reached Review UI, its canonical owner",
        )
        add(
            "acknowledgement-targets-incident",
            bool(owner.sessions)
            and owner.sessions[-1]["target_type"] == "incident"
            and owner.acknowledged[-1] == "case_a",
            "the acknowledgement targeted the linked incident identity",
        )
        add(
            "acknowledgement-changes-no-authority",
            receipt.authoritative_state_changed is False
            and receipt.plan_approved is False
            and receipt.plan_rejected is False
            and receipt.plan_revised is False
            and receipt.repair_executed is False
            and receipt.recovery_attempt_started is False
            and receipt.checkpoint_restored is False
            and receipt.process_restarted is False
            and receipt.workflow_changed is False
            and receipt.code_changed is False
            and receipt.artifact_changed is False,
            "the receipt claims no authoritative change of any kind",
        )
        add(
            "confirmation-statement-exact",
            confirmation["confirmation_statement"]
            == (
                "This request does not directly execute commands, modify code, "
                "change artifacts, restore a checkpoint, restart a process, "
                "transition the workflow, grant Rights or Safety approval, upload "
                "content or publish content."
            ),
            "the confirmation statement is the exact required sentence",
        )
        add(
            "confirmation-lists-non-consequences",
            len(confirmation["does_not_do"]) >= 10,
            f"{len(confirmation['does_not_do'])} explicit non-consequences",
        )
        for flag in (
            "plan_created_by_panel", "plan_revised_by_panel", "plan_approved_by_panel",
            "plan_rejected_by_panel", "plan_executed_by_panel", "step_executed_by_panel",
            "recovery_executed_by_panel", "checkpoint_restored_by_panel",
            "process_restarted_by_panel", "workflow_changed_by_panel",
            "code_modified_by_panel", "artifact_modified_by_panel",
            "raw_command_exposed", "private_path_exposed",
            "hidden_plan_ranking_created", "hidden_repair_success_score_created",
            "hidden_safety_score_created", "optimistic_authority_update_used",
            "command_execution_used", "shell_execution_used", "powershell_execution_used",
            "git_execution_used", "ffmpeg_execution_used", "package_installation_used",
            "tool_download_used", "media_generation_used", "source_media_modified",
            "accepted_output_modified", "approval_created_locally",
            "safety_decision_created_locally", "rights_decision_created_locally",
            "final_decision_created_locally", "upload_used", "publication_used",
            "rights_bypass_used", "safety_bypass_used", "destructive_action_used",
        ):
            add(f"signal-{flag.replace('_', '-')}", usage[flag] is False,
                f"signal_usage.{flag} is pinned false")
        add(
            "no-command-runner",
            "subprocess" not in source and "os.system(" not in source,
            "the module contains no command runner",
        )
        add(
            "notices-exact",
            COMMAND_WITHHELD_NOTICE == "Command details withheld from the review panel."
            and PRIVATE_PATH_NOTICE == "Private path details redacted."
            and NOT_EXECUTABLE_NOTICE == "This step cannot be executed from this panel."
            and SOURCE_RETAINED_NOTICE == "Full source record retained by Repair Planner.",
            "the four required notices are the exact required strings",
        )
        add(
            "no-command-in-review-payload",
            COMMAND_TARGET not in json.dumps(review)
            and "libx264" not in json.dumps(review),
            "no command text reaches the review payload",
        )
        add(
            "no-private-path-in-review-payload",
            "/home/operator" not in json.dumps(review),
            "no private path reaches the review payload",
        )
        add(
            "comparison-limit",
            MAX_COMPARISON_PLANS == 4,
            f"at most {MAX_COMPARISON_PLANS} plans may be compared",
        )
        add(
            "frontend-module-present",
            bool(frontend),
            "the frontend projection module exists"
            if frontend
            else "frontend/src/lib/repairPlanReview.ts is not present yet",
        )
        add(
            "frontend-declares-no-execution",
            bool(frontend)
            and "executable_by_panel" in frontend
            and "command_withheld" in frontend
            and "stepIsExecutable" in frontend,
            "the frontend module carries the withholding contract"
            if frontend
            else "frontend module not present yet",
        )
        add(
            "frontend-has-no-command-runner",
            "child_process" not in frontend and "eval(" not in frontend,
            "the frontend module runs no command",
        )
    return results


def run_synthetic_project() -> dict[str, Any]:
    """Build every projection over a synthetic project and report real counts."""
    with tempfile.TemporaryDirectory() as raw:
        engine, _ = _engine(Path(raw))
        review = engine.build_repair_plan_review(PROJECT_ID)
        queue = engine.build_repair_plan_queue(PROJECT_ID)
        payload = _prepared(engine, PLAN_CODE_CHANGE)
        comparison = engine.compare_repair_plans(
            PROJECT_ID, [PLAN_REVERSIBLE, PLAN_CODE_CHANGE]
        )["comparison"]
        recovery = engine.inspect_linked_recovery_history(PROJECT_ID, PLAN_REVERSIBLE)
        steps = engine.inspect_repair_steps(PROJECT_ID, PLAN_CODE_CHANGE)
        return {
            "project_id": PROJECT_ID,
            "repair_plan_count": len(review["repair_plan_references"]),
            "queue_item_count": len(queue["items"]),
            "priority_tier_count": len(queue["priority_tiers"]),
            "step_projection_count": len(payload["step_projections"]),
            "command_bearing_step_count": steps["command_bearing_step_count"],
            "raw_command_exposed": steps["raw_command_exposed"],
            "private_path_exposed": steps["private_path_exposed"],
            "risk_projection_count": len(payload["risk_projections"]),
            "approval_requirement_count": len(payload["approval_requirements"]),
            "verification_requirement_count": len(payload["verification_requirements"]),
            "evidence_card_count": len(payload["evidence_cards"]),
            "recovery_link_count": len(payload["recovery_links"]),
            "conflict_count": payload["snapshot"]["conflict_count"],
            "missing_approval_count": payload["snapshot"]["missing_approval_count"],
            "missing_verification_count": payload["snapshot"]["missing_verification_count"],
            "owner_reported_success_count": recovery["owner_reported_success_count"],
            "independently_verified_count": recovery["independently_verified_count"],
            "available_action_descriptor_ids": payload["snapshot"][
                "available_action_descriptor_ids"
            ],
            "plan_execution_available": False,
            "comparison_no_automatic_winner": comparison["no_automatic_winner"],
            "review_limitations": review["limitations"],
        }


def inspect_persisted_project(project_root: Path, project_id: str) -> dict[str, Any]:
    """Read-only inspection of an existing persisted BOBA project."""

    class _NullOwner:
        def create_boba_review_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise ValidationError("Read-only inspection does not contact any owner.")

        def acknowledge_boba_review_notification(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any]:
            raise ValidationError("Read-only inspection does not contact any owner.")

    store = BobaMemoryStore(project_root)
    engine = BobaRepairPlanReviewV1(store, _NullOwner())  # type: ignore[arg-type]
    references = engine.build_repair_plan_references(project_id)
    queue = engine.build_repair_plan_queue(project_id)
    return {
        "project_id": project_id,
        "repair_plan_count": len(references),
        "repair_plan_ids": [item.repair_plan_id for item in references],
        "queue_item_count": len(queue["items"]),
        "unsupported_schema_plan_ids": [
            item.repair_plan_id for item in references if not item.schema_supported
        ],
        "notice": (
            "Read-only inspection. No plan was created, revised, approved, "
            "rejected or executed; nothing was recovered, restored, restarted, "
            "uploaded or published."
        ),
    }


def _write_report(payload: dict[str, Any]) -> Path:
    directory = Path("work/validation_reports/boba_repair_plan_review")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"report_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Repair Plan Panel V1 without touching real state."
    )
    parser.add_argument(
        "--self-check", action="store_true", help="run the declared-boundary checks"
    )
    parser.add_argument(
        "--synthetic-project",
        action="store_true",
        help="build every projection over a synthetic project",
    )
    parser.add_argument(
        "--scenario", action="append", default=[], help="run one named scenario"
    )
    parser.add_argument(
        "--project-root", default=None, help="BOBA memory root for a read-only inspection"
    )
    parser.add_argument(
        "--project-id", default=None, help="existing project id to inspect read-only"
    )
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"tool": "validate_boba_repair_plan_review"}
    failures: list[ScenarioResult] = []

    results = (
        [run_named_scenario(name) for name in args.scenario]
        if args.scenario
        else run_all_scenarios()
    )
    failed = [item for item in results if not item.passed]
    failures.extend(failed)
    report["scenarios"] = {
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": [{"name": item.name, "detail": item.detail} for item in failed],
    }
    print(
        f"scenarios: {len(results)} total, {len(results) - len(failed)} passed, "
        f"{len(failed)} failed"
    )

    if args.self_check:
        checks = run_self_check()
        check_failures = [item for item in checks if not item.passed]
        failures.extend(check_failures)
        report["self_check"] = {
            "total": len(checks),
            "passed": len(checks) - len(check_failures),
            "failed": [
                {"name": item.name, "detail": item.detail} for item in check_failures
            ],
        }
        print(
            f"self-check: {len(checks)} checks, {len(checks) - len(check_failures)} "
            f"passed, {len(check_failures)} failed"
        )

    if args.synthetic_project:
        synthetic = run_synthetic_project()
        report["synthetic_project"] = synthetic
        print("synthetic project:")
        for key, value in synthetic.items():
            print(f"  {key}: {value}")

    if args.project_root and args.project_id:
        inspection = inspect_persisted_project(Path(args.project_root), args.project_id)
        report["persisted_project"] = inspection
        print("persisted project inspection:")
        for key, value in inspection.items():
            print(f"  {key}: {value}")

    for item in failures:
        print(f"FAILED {item.name}: {item.detail}")

    if args.report:
        print(f"report written to {_write_report(report)}")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
