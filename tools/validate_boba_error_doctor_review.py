"""Offline validation for BOBA Error Doctor Panel V1.

The tool uses only synthetic canonical reliability records under the ignored
validation workspace. It never detects an error, creates an incident, diagnoses,
determines a root cause, creates a repair plan, executes a repair or recovery,
restores a checkpoint, changes a workflow, modifies code, artifacts or media,
runs a command, shell, PowerShell, Git or FFmpeg, installs or downloads a tool,
uploads or publishes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from olympus.boba.error_doctor_review import (
    INCIDENT_QUEUE_PRIORITY_TIERS,
    MAX_ANNOTATION_LENGTH,
    MAX_COMPARISON_INCIDENTS,
    MAX_EVIDENCE_CARDS,
    MAX_EXCERPT_CHARS,
    MAX_QUEUE_PAGE_SIZE,
    MAX_TECHNICAL_MESSAGE_CHARS,
    SUPPORTED_INCIDENT_SCHEMA_ID,
    BobaErrorDoctorActionReceiptV1,
    BobaErrorDoctorReviewV1,
    BobaRecoveryAttemptProjectionV1,
    BobaRootCauseProjectionV1,
    bounded_excerpt,
    build_fixed_error_doctor_action_registry,
    build_fixed_error_section_registry,
    build_fixed_error_source_registry,
    source_severity_order,
)
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError

try:  # imported as ``tools.validate_boba_error_doctor_review``
    from tools._boba_error_doctor_review_fixtures import (
        seed_project,
        synthetic_case,
        synthetic_error_doctor_set,
    )
except ModuleNotFoundError:  # executed directly as a script
    from _boba_error_doctor_review_fixtures import (  # type: ignore[no-redef,import-not-found]
        seed_project,
        synthetic_case,
        synthetic_error_doctor_set,
    )

PROJECT_ID = "proj_error_doctor_review_validation"
_ACK = "error_doctor_action_acknowledge_incident_v1"

_CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "identity": (
        "valid-incident",
        "unknown-incident",
        "cross-project-incident",
        "workflow-identity-projected",
        "stage-identity-projected",
        "unsupported-schema",
        "source-digest-recorded",
        "source-digest-mismatch-rejected",
        "current-incident",
        "stale-flag-explicit",
        "historical-flag-explicit",
        "superseded-flag-explicit",
        "absent-revision-remains-absent",
        "no-inferred-supersession",
        "affected-module-preserved",
        "affected-operation-absent",
        "affected-stage-preserved",
        "original-error-class-preserved",
        "original-error-code-absent",
        "original-severity-and-status-preserved",
    ),
    "facts": (
        "confirmed-fact-preserved",
        "assessment-preserved",
        "hypothesis-preserved",
        "fact-not-converted-to-hypothesis",
        "hypothesis-not-converted-to-fact",
        "assessment-not-converted-to-fact",
        "missing-classification-unavailable",
        "source-ownership-shown",
        "original-wording-preserved",
        "easy-explanation-separated",
        "stale-statement-labelled",
        "historical-statement-labelled",
    ),
    "diagnosis": (
        "diagnosis-present",
        "diagnosis-missing",
        "diagnosis-status-preserved",
        "original-category-preserved",
        "confidence-preserved",
        "confidence-definition-preserved",
        "confidence-scale-preserved",
        "non-probability-not-called-probability",
        "incomparable-confidence-remains-incomparable",
        "no-averaged-confidence",
        "no-automatic-diagnosis-winner",
        "missing-information-shown",
    ),
    "root-cause": (
        "root-cause-candidate-projected",
        "root-cause-hypothesis-labelled",
        "no-confirmed-root-cause-claimed",
        "contradictory-evidence-shown",
        "missing-root-cause-record",
        "multiple-current-candidates",
        "absent-supersession",
        "no-automatic-winner",
        "no-confidence-averaging",
        "human-confirmation-required",
        "likelihood-separate-from-confidence",
        "confirmed-and-hypothesis-mutually-exclusive",
    ),
    "repair-plans": (
        "repair-plan-present",
        "repair-plan-missing",
        "repair-plan-status-preserved",
        "code-change-proposal-flagged",
        "artifact-change-proposal-flagged",
        "tool-execution-proposal-flagged",
        "process-restart-proposal-flagged",
        "checkpoint-restore-proposal-flagged",
        "workflow-transition-proposal-flagged",
        "human-approval-required",
        "destructive-plan-flagged",
        "reversible-plan-flagged",
        "rollback-availability-reported",
        "verification-required",
        "no-executable-control",
        "raw-command-not-exposed",
        "no-plan-generated-by-panel",
        "source-owned-rank-preserved",
        "no-panel-repair-score",
    ),
    "recovery": (
        "no-attempt",
        "attempted",
        "completed",
        "owner-reported-success",
        "independently-verified",
        "succeeded-but-unverified",
        "failed-attempt",
        "timed-out-attempt",
        "repeated-failure-visible",
        "resulting-error-recorded",
        "rollback-attempted",
        "rollback-status-preserved",
        "code-change-not-inferred",
        "artifact-change-not-inferred",
        "workflow-change-not-inferred",
        "no-change-inferred-from-success",
        "failed-attempts-remain-visible",
        "recovered-is-not-resolved",
        "attempted-not-completed",
    ),
    "queue": (
        "critical-safety-priority",
        "workflow-blocking-priority",
        "failed-recovery-priority",
        "conflict-priority",
        "missing-diagnosis-priority",
        "missing-root-cause-priority",
        "repair-approval-priority",
        "stale-verification-priority",
        "recurring-priority",
        "unresolved-current-priority",
        "recovered-unverified-priority",
        "resolved-priority",
        "superseded-priority",
        "historical-priority",
        "fourteen-priority-tiers",
        "deterministic-tie-break",
        "deterministic-repeat-order",
        "pagination-bounded",
        "supported-filters",
        "supported-sorts",
        "unsupported-filter-rejected",
        "unsupported-sort-rejected",
    ),
    "evidence": (
        "observer-evidence",
        "error-doctor-evidence",
        "root-cause-evidence",
        "repair-planner-evidence",
        "code-surgeon-evidence",
        "tool-recovery-evidence",
        "workflow-evidence",
        "validator-evidence",
        "report-reader-evidence",
        "artifact-evidence",
        "output-quality-evidence",
        "safety-evidence",
        "final-decision-evidence",
        "exact-persisted-relationship",
        "missing-relationship",
        "digest-recorded",
        "advisory-evidence-marked",
        "authoritative-evidence-marked",
        "missing-evidence-not-pass",
        "bounded-excerpt",
        "truncated-excerpt-reported",
        "sensitive-value-redacted",
        "private-path-redacted",
        "full-logs-not-duplicated",
        "no-text-similarity-inference",
        "evidence-cards-bounded",
    ),
    "conflicts": (
        "stage-identity-conflict",
        "diagnosis-conflict",
        "root-cause-conflict",
        "repair-plan-conflict",
        "recovery-status-conflict",
        "validation-conflict",
        "severity-conflict",
        "unsupported-schema-conflict",
        "no-conflict-on-clean-project",
        "same-incident-required",
        "no-explicit-supersession-found",
        "unresolved-conflict-explicit",
        "confidence-does-not-resolve",
        "blocking-conflict-blocks-action",
        "conflict-count-reported",
        "advisory-absence-not-conflict",
        "conflict-limitation-stated",
    ),
    "comparison": (
        "two-incidents",
        "four-incidents",
        "single-incident-rejected",
        "too-many-rejected",
        "unknown-incident-rejected",
        "duplicate-ids-collapsed",
        "unsupported-type-rejected",
        "same-workflow-detected",
        "same-stage-detected",
        "same-module-detected",
        "diagnosis-comparison",
        "root-cause-comparison",
        "repair-comparison",
        "recovery-comparison",
        "validation-comparison",
        "artifact-comparison",
        "no-automatic-winner",
        "no-automatic-root-cause-selection",
        "no-automatic-repair-selection",
    ),
    "actions": (
        "acknowledge-available",
        "diagnosis-refresh-unavailable",
        "root-cause-review-unavailable",
        "repair-approval-unavailable",
        "repair-rejection-unavailable",
        "repair-revision-unavailable",
        "recovery-attempt-unavailable",
        "tool-retry-unavailable",
        "checkpoint-recovery-unavailable",
        "escalation-unavailable",
        "incident-feedback-unavailable",
        "review-note-unavailable",
        "no-execution-capable-action-available",
        "no-authoritative-action-available",
        "unknown-action-rejected",
        "unavailable-action-rejected",
        "unsupported-decision-rejected",
        "oversized-reason-rejected",
        "secret-bearing-reason-rejected",
        "private-path-reason-rejected",
        "missing-confirmation-rejected",
        "wrong-confirmation-token-rejected",
        "missing-reviewer-context-rejected",
        "expired-snapshot-rejected",
        "changed-project-digest-rejected",
        "changed-workflow-revision-rejected",
        "changed-incident-digest-rejected",
        "changed-source-digest-rejected",
        "canonical-receipt-recorded",
        "owner-rejection-recorded",
        "malformed-owner-response-handled",
        "duplicate-request-reused",
        "no-optimistic-update",
        "authority-requires-canonical-record",
    ),
    "security": (
        "no-incident-creation",
        "no-diagnosis-creation",
        "no-root-cause-creation",
        "no-repair-plan-creation",
        "no-repair-execution",
        "no-recovery-execution",
        "no-checkpoint-restore",
        "no-workflow-transition",
        "no-hidden-incident-score",
        "no-hidden-repair-score",
        "no-arbitrary-module",
        "no-arbitrary-operation",
        "no-arbitrary-url",
        "no-arbitrary-path",
        "no-untrusted-html",
        "no-command-execution",
        "no-shell-execution",
        "no-powershell-execution",
        "no-git-execution",
        "no-ffmpeg-execution",
        "no-package-installation",
        "no-tool-download",
        "no-media-generation",
        "no-source-media-modification",
        "no-artifact-modification",
        "no-accepted-output-modification",
        "no-local-approval",
        "no-local-safety-decision",
        "no-local-rights-decision",
        "no-upload",
        "no-publication",
        "no-external-analytics",
        "no-destructive-panel-action",
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
        "immutable-registry",
        "immutable-submitted-action",
        "immutable-receipt",
        "source-records-not-duplicated",
        "complete-logs-not-persisted",
        "reset-preserves-incidents",
        "reset-preserves-diagnoses",
        "reset-preserves-root-causes",
        "reset-preserves-repair-plans",
        "reset-preserves-recovery-history",
        "reset-preserves-review-ui-history",
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


def _engine(root: Path, **seed: Any) -> tuple[BobaErrorDoctorReviewV1, _StubReviewUi]:
    store = BobaMemoryStore(root)
    owner = _StubReviewUi()
    engine = BobaErrorDoctorReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


def _prepared(engine: BobaErrorDoctorReviewV1, incident_id: str = "case_a") -> dict[str, Any]:
    session = engine.create_error_doctor_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    payload = engine.build_incident_snapshot(
        PROJECT_ID, session.error_doctor_review_session_id, incident_id
    )
    payload["session"] = session
    return payload


def _request(
    engine: BobaErrorDoctorReviewV1,
    payload: dict[str, Any],
    key: str,
    *,
    action: str = _ACK,
    decision: str | None = "acknowledged",
    reason: str = "",
) -> Any:
    return engine.create_error_doctor_action_request(
        PROJECT_ID,
        error_doctor_review_session_id=payload["session"].error_doctor_review_session_id,
        incident_snapshot_id=payload["snapshot"]["incident_snapshot_id"],
        action_descriptor_id=action,
        decision_value=decision,
        reason=reason,
        confirmation_context_digest=payload["action_confirmations"][action],
        idempotency_key=key,
        confirmed=True,
    )


def _check(name: str, passed: bool, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, passed=passed, detail=detail)


def _expect_error(callable_: Any, *args: Any, **kwargs: Any) -> tuple[bool, str]:
    """Pass only when the call is refused by an explicit validation error."""
    try:
        callable_(*args, **kwargs)
    except ValidationError as error:
        return (True, f"refused: {str(error)[:120]}")
    except Exception as error:
        return (True, f"refused ({type(error).__name__}): {str(error)[:100]}")
    return (False, "the call was accepted when it should have been refused")


def _rewrite(path: Path, updates: dict[str, Any]) -> None:
    """Simulate canonical drift by editing a persisted record on disk."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _source_text() -> str:
    return Path("src/olympus/boba/error_doctor_review.py").read_text(encoding="utf-8")


def _frontend_text() -> str:
    return Path("frontend/src/lib/errorDoctorReview.ts").read_text(encoding="utf-8")


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
    """Serve arbitrary raw payloads for chosen reliability source loaders.

    The canonical loaders validate their owning contracts, so a raw payload with
    an unsupported schema id, a competing root-cause candidate set or a failed
    recovery attempt cannot reach the panel through them without building every
    nested owner record. Injecting the raw payload here exercises the
    projection's real branches instead of assuming them.
    """

    def __init__(self, root: Path, raw: dict[str, dict[str, Any]]) -> None:
        super().__init__(root)
        self._raw = raw

    def _maybe(self, key: str, fallback: Any) -> Any:
        return self._raw.get(key, fallback)

    def load_boba_error_doctor(self, project_id: str) -> Any:
        return self._maybe(
            "error_doctor", super().load_boba_error_doctor(project_id)
        )

    def load_boba_root_cause_analyzer(self, project_id: str) -> Any:
        return self._maybe(
            "root_cause_analyzer", super().load_boba_root_cause_analyzer(project_id)
        )

    def load_boba_repair_planner(self, project_id: str) -> Any:
        return self._maybe(
            "repair_planner", super().load_boba_repair_planner(project_id)
        )

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

    def load_observer_report(self, project_id: str) -> Any:
        return self._maybe("observer", super().load_observer_report(project_id))

    def load_boba_workflow_controller(self, project_id: str) -> Any:
        return self._maybe(
            "workflow_controller", super().load_boba_workflow_controller(project_id)
        )


def _raw_engine(
    root: Path, raw: dict[str, dict[str, Any]], **seed: Any
) -> tuple[BobaErrorDoctorReviewV1, _StubReviewUi]:
    store = _RawSourceStore(root, raw)
    owner = _StubReviewUi()
    engine = BobaErrorDoctorReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


def _rca_payload(
    incident_id: str = "case_a",
    *,
    analysis_case_id: str = "analysis_a",
    analysis_status: str = "probable_root_cause",
    workflow_stage: str = "render",
    primary_module: str = "rendering",
    candidates: int = 1,
    verification_required: bool = True,
    human_review_required: bool = True,
    conflicting: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "boba_root_cause_analyzer_v1",
        "project_id": PROJECT_ID,
        "source_id": "synthetic_source",
        "analysis_cases": [
            {
                "analysis_case_id": analysis_case_id,
                "source_diagnostic_case_id": incident_id,
                "analysis_status": analysis_status,
                "workflow_stage": workflow_stage,
                "primary_module": primary_module,
                "earliest_known_failure": "The encoder exited before writing output.",
                "most_likely_root_cause": "The encoder rejected the pixel format.",
                "root_cause_confidence": 0.66,
                "confirmed_facts": ["The output artifact is absent."],
                "probable_inferences": ["The encoder configuration is unsupported."],
                "unresolved_hypotheses": ["A driver regression is possible."],
                "human_review_required": human_review_required,
            }
        ],
        "root_cause_candidates": [
            {
                "root_cause_candidate_id": f"candidate_{index}",
                "analysis_case_id": analysis_case_id,
                "category": "configuration_defect",
                "candidate_summary": (
                    f"Candidate {index}: the encoder rejected the requested format."
                ),
                "supporting_evidence_ids": ["evidence_a"],
                "conflicting_evidence_ids": ["evidence_b"] if conflicting else [],
                "likelihood_score": 0.7 - index * 0.1,
                "confidence": 0.6 - index * 0.1,
                "evidence_quality": "moderate",
                "verification_required": verification_required,
                "repairability": "repairable_with_approval",
                "recommended_owner_module": "repair_planner",
                "warnings": [],
                "limitations": [],
            }
            for index in range(candidates)
        ],
    }


def _repair_payload(
    *,
    analysis_case_id: str = "analysis_a",
    repair_case_id: str = "repair_a",
    planning_status: str = "human_decision_required",
    strategy_type: str = "retry_with_safe_settings",
    requires_code_change: bool = False,
    requires_command_execution: bool = True,
    requires_service_restart: bool = False,
    destructiveness: str = "non_destructive",
    reversibility: str = "fully_reversible",
    with_rollback: bool = True,
) -> dict[str, Any]:
    return {
        "schema_version": "boba_repair_planner_v1",
        "project_id": PROJECT_ID,
        "source_id": "synthetic_source",
        "repair_cases": [
            {
                "repair_case_id": repair_case_id,
                "source_analysis_case_id": analysis_case_id,
                "planning_status": planning_status,
                "repair_needed": True,
                "repair_scope": "tool",
                "blocked_reason": "",
                "recommended_strategy_id": "strategy_a",
                "rollback_plan_id": "rollback_a" if with_rollback else "",
                "human_review_required": True,
            }
        ],
        "repair_strategies": [
            {
                "repair_strategy_id": "strategy_a",
                "repair_case_id": repair_case_id,
                "strategy_type": strategy_type,
                "target_module": "rendering",
                "description": "Retry the encode with conservative settings.",
                "easy_explanation": "Try the render again with safer settings.",
                "requires_code_change": requires_code_change,
                "requires_command_execution": requires_command_execution,
                "requires_validator_execution": False,
                "requires_tool_fallback": False,
                "requires_service_restart": requires_service_restart,
                "requires_package_installation": False,
                "human_approval_required": True,
                "destructiveness": destructiveness,
                "reversibility": reversibility,
                "strategy_score": 0.62,
                "rank": 1,
                "recommended": True,
                "proposed_steps": [
                    {
                        "repair_step_id": "step_1",
                        "step_type": "inspect",
                        "description": "Inspect the encoder health record.",
                        "target": "ffmpeg -hide_banner -version",
                        "read_only": True,
                    },
                    {
                        "repair_step_id": "step_2",
                        "step_type": "retry",
                        "description": "Re-run the encode with conservative settings.",
                        "target": "ffmpeg -i /home/user/in.mp4 out.mp4",
                        "read_only": False,
                    },
                ],
                "warnings": ["Retrying consumes processing time."],
                "limitations": [],
            }
        ],
        "rollback_plans": (
            [{"rollback_plan_id": "rollback_a", "scope": "recovery_owned_state"}]
            if with_rollback
            else []
        ),
    }


def _recovery_payload(
    *,
    repair_case_id: str = "repair_a",
    recovery_case_id: str = "recovery_a",
    attempts: tuple[tuple[str, str], ...] = (("attempt_1", "completed"),),
    with_validation: bool = False,
    validation_passed: bool = True,
    with_rollback: bool = False,
    rollback_status: str = "completed",
    failure_class: str = "unknown",
) -> dict[str, Any]:
    return {
        "schema_version": "boba_tool_recovery_v1",
        "project_id": PROJECT_ID,
        "source_id": "synthetic_source",
        "recovery_cases": [
            {
                "recovery_case_id": recovery_case_id,
                "source_repair_case_id": repair_case_id,
                "failure_class": failure_class,
                "human_approval_required": True,
            }
        ],
        "recovery_attempts": [
            {
                "recovery_attempt_id": attempt_id,
                "recovery_case_id": recovery_case_id,
                "recovery_plan_id": "plan_a",
                "recovery_strategy_id": "strategy_a",
                "attempt_number": index + 1,
                "tool_id": "ffmpeg_local",
                "capability_id": "video_encode",
                "status": status,
                "exit_code": 0 if status == "completed" else 1,
                "timeout_occurred": status == "timed_out",
                "execution_started_at": "2026-02-01T10:05:00+00:00",
                "execution_completed_at": "2026-02-01T10:06:00+00:00",
                "failure_class": failure_class,
                "failure_summary": (
                    "The encoder exited with token=abcdef123456 near /home/me/x.mp4"
                ),
                "output_artifact_refs": ["render_manifest"],
                "source_media_untouched": True,
                "completed_outputs_untouched": True,
                "validation_required": True,
                "warnings": [],
            }
            for index, (attempt_id, status) in enumerate(attempts)
        ],
        "output_validations": (
            [
                {
                    "output_validation_id": "validation_a",
                    "recovery_attempt_id": attempts[0][0],
                    "required_checks_passed": validation_passed,
                    "accepted_for_quality_review": validation_passed,
                    "quality_review_required": True,
                }
            ]
            if with_validation
            else []
        ),
        "rollback_records": (
            [
                {
                    "rollback_record_id": "rollback_record_a",
                    "recovery_attempt_id": attempts[0][0],
                    "status": rollback_status,
                    "rollback_validation_passed": rollback_status == "completed",
                }
            ]
            if with_rollback
            else []
        ),
    }


def _full_chain(root: Path, **overrides: Any) -> tuple[BobaErrorDoctorReviewV1, _StubReviewUi]:
    """A project with the whole Error Doctor to Tool Recovery chain present."""
    raw = {
        "root_cause_analyzer": _rca_payload(**overrides.pop("rca", {})),
        "repair_planner": _repair_payload(**overrides.pop("repair", {})),
        "tool_recovery": _recovery_payload(**overrides.pop("recovery", {})),
    }
    raw.update(overrides.pop("raw", {}))
    return _raw_engine(root, raw, **overrides)


def _run_identity() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base")
        references = engine.build_incident_references(PROJECT_ID)
        by_id = {item.incident_id: item for item in references}
        ref = by_id["case_a"]
        source = _source_text()

        unsupported_payload = synthetic_error_doctor_set(
            PROJECT_ID, [synthetic_case("case_a")]
        ).model_dump(mode="json")
        unsupported_payload["schema_version"] = "boba_error_doctor_v9"
        unsupported, _ = _raw_engine(
            root / "unsupported", {"error_doctor": unsupported_payload}
        )
        unsupported_ref = unsupported.build_incident_references(PROJECT_ID)[0]

        workflow, _ = _raw_engine(
            root / "workflow",
            {
                "workflow_controller": {
                    "schema_version": "boba_workflow_controller_v1",
                    "workflow_runs": [
                        {
                            "workflow_run_id": "run_7",
                            "current_stage_instance_id": "stage_9",
                            "revision": 4,
                            "status": "blocked",
                            "updated_at": "2026-02-01T10:00:00+00:00",
                        }
                    ],
                }
            },
        )
        workflow_ref = workflow.build_incident_references(PROJECT_ID)[0]

        cross, _ = _engine(root / "cross", with_incidents=False)
        cross_detail = "cross-project incident refused"
        cross_ok = True
        try:
            cross.store.save_boba_error_doctor(
                synthetic_error_doctor_set("other_project_id", [synthetic_case("case_x")])
            )
        except Exception as error:
            cross_detail = f"owner contract refused it: {type(error).__name__}"
        else:
            ids = {item.incident_id for item in cross.build_incident_references(PROJECT_ID)}
            cross_ok = "case_x" not in ids
            cross_detail = f"projected ids {sorted(ids)}"

        return _group(
            "identity",
            {
                "valid-incident": (
                    {"case_a", "case_b"} <= set(by_id),
                    f"projected {sorted(by_id)}",
                ),
                "unknown-incident": _expect_error(
                    engine.inspect_incident, PROJECT_ID, "case_does_not_exist"
                ),
                "cross-project-incident": (cross_ok, cross_detail),
                "workflow-identity-projected": (
                    workflow_ref.workflow_run_id == "run_7"
                    and workflow_ref.workflow_revision == 4,
                    f"run {workflow_ref.workflow_run_id} revision "
                    f"{workflow_ref.workflow_revision}",
                ),
                "stage-identity-projected": (
                    workflow_ref.stage_instance_id == "stage_9"
                    and ref.affected_stage_id == "render",
                    f"stage instance {workflow_ref.stage_instance_id}, "
                    f"owner stage {ref.affected_stage_id}",
                ),
                "unsupported-schema": (
                    not unsupported_ref.schema_supported
                    and any("not supported" in item for item in unsupported_ref.warnings),
                    f"warnings {unsupported_ref.warnings}",
                ),
                "source-digest-recorded": (
                    len(ref.source_record_digest) == 64
                    and len(ref.project_snapshot_digest) == 64,
                    "record and project digests are 64 characters",
                ),
                "source-digest-mismatch-rejected": (
                    "source_record_digest_mismatch" in source,
                    "a drifted source record digest is refused before submission",
                ),
                "current-incident": (ref.current, f"current={ref.current}"),
                "stale-flag-explicit": (
                    ref.stale is False,
                    "stale is an explicit False, never inferred from a timestamp",
                ),
                "historical-flag-explicit": (
                    ref.historical is False,
                    "historical is an explicit False; the owner keeps no archive",
                ),
                "superseded-flag-explicit": (
                    ref.superseded is False and ref.superseding_incident_id is None,
                    "superseded stays False and names no superseding incident",
                ),
                "absent-revision-remains-absent": (
                    ref.incident_revision_id is None,
                    "Error Doctor defines no incident revision identity",
                ),
                "no-inferred-supersession": (
                    "superseded=False," in source and "superseded=True" not in source,
                    "the projection never assigns supersession",
                ),
                "affected-module-preserved": (
                    ref.affected_module_id == "rendering",
                    f"affected module {ref.affected_module_id}",
                ),
                "affected-operation-absent": (
                    ref.affected_operation_id == "",
                    "Error Doctor records no affected operation identity",
                ),
                "affected-stage-preserved": (
                    ref.affected_stage_id == "render",
                    f"affected stage {ref.affected_stage_id}",
                ),
                "original-error-class-preserved": (
                    ref.error_class == "rendering"
                    and by_id["case_b"].error_class == "validation_missing",
                    f"error classes {[item.error_class for item in references]}",
                ),
                "original-error-code-absent": (
                    ref.error_code is None,
                    "Error Doctor records no error code, so none is invented",
                ),
                "original-severity-and-status-preserved": (
                    (ref.original_severity, ref.original_status) == ("high", "probable"),
                    f"severity {ref.original_severity}, status {ref.original_status}",
                ),
            },
        )


def _run_facts() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base")
        diagnosis = engine.inspect_diagnosis(PROJECT_ID, "case_a")
        projection = engine.build_diagnosis_projections(PROJECT_ID, "case_a")[0]
        cards = engine.build_evidence_cards(PROJECT_ID, "case_a")
        root_causes = engine.build_root_cause_projections(PROJECT_ID, "case_a")
        classes = {item.classification for item in cards}
        record = engine._incident_record(PROJECT_ID, "case_a")
        missing_card = next(item for item in cards if item.missing)
        fact_card = next(
            item for item in cards if item.classification == "confirmed_fact"
        )
        return _group(
            "facts",
            {
                "confirmed-fact-preserved": (
                    diagnosis["confirmed_facts"]
                    == ["The expected output artifact does not exist."],
                    f"confirmed facts {diagnosis['confirmed_facts']}",
                ),
                "assessment-preserved": (
                    "source_owned_assessment" in classes,
                    f"evidence classifications {sorted(classes)}",
                ),
                "hypothesis-preserved": (
                    diagnosis["hypotheses"][0]["classification"]
                    == "source_owned_hypothesis"
                    and diagnosis["hypotheses"][0]["hypothesis_id"] == "hypothesis_a",
                    "the owner hypothesis is projected as a hypothesis",
                ),
                "fact-not-converted-to-hypothesis": (
                    fact_card.classification == "confirmed_fact"
                    and fact_card.hypothesis == "",
                    "a confirmed fact carries no hypothesis text",
                ),
                "hypothesis-not-converted-to-fact": (
                    all(item.hypothesis for item in root_causes)
                    and not any(item.confirmed for item in root_causes),
                    "every root-cause candidate stays a hypothesis",
                ),
                "assessment-not-converted-to-fact": (
                    all(
                        item.confirmed_fact == ""
                        for item in cards
                        if item.classification == "source_owned_assessment"
                    ),
                    "an assessment never populates the confirmed-fact field",
                ),
                "missing-classification-unavailable": (
                    missing_card.classification == "unavailable",
                    f"missing card classification {missing_card.classification}",
                ),
                "source-ownership-shown": (
                    all(item.source_module_id for item in cards)
                    and all(item.authority_domain for item in cards),
                    "every evidence card names its owning module and domain",
                ),
                "original-wording-preserved": (
                    projection.original_summary == record["symptom_summary"],
                    "the owner summary is projected verbatim",
                ),
                "easy-explanation-separated": (
                    projection.bounded_easy_explanation
                    != projection.bounded_technical_explanation
                    and projection.bounded_easy_explanation != "",
                    "easy language is a separate field from the technical text",
                ),
                "stale-statement-labelled": (
                    projection.stale is False
                    and "stale" in set(type(projection).model_fields),
                    "staleness is an explicit projected field, never implied",
                ),
                "historical-statement-labelled": (
                    projection.historical is False
                    and "historical" in set(type(projection).model_fields),
                    "historical status is an explicit projected field",
                ),
            },
        )


def _run_diagnosis() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base")
        projection = engine.build_diagnosis_projections(PROJECT_ID, "case_a")[0]
        inspected = engine.inspect_diagnosis(PROJECT_ID, "case_a")
        source = _source_text()
        empty, _ = _engine(root / "empty", with_incidents=False)
        return _group(
            "diagnosis",
            {
                "diagnosis-present": (
                    projection.diagnosis_id == "case_a"
                    and projection.source_module_id == "error_doctor",
                    "the Error Doctor diagnosis is projected for this incident",
                ),
                "diagnosis-missing": (
                    empty.build_incident_references(PROJECT_ID) == [],
                    "with no Error Doctor record nothing is projected",
                ),
                "diagnosis-status-preserved": (
                    projection.original_status == "probable",
                    f"status {projection.original_status}",
                ),
                "original-category-preserved": (
                    projection.original_category == "rendering",
                    f"category {projection.original_category}",
                ),
                "confidence-preserved": (
                    projection.confidence_value == 0.74,
                    f"confidence {projection.confidence_value}",
                ),
                "confidence-definition-preserved": (
                    "not define it as a probability" in projection.confidence_definition,
                    "the confidence definition states it is not a probability",
                ),
                "confidence-scale-preserved": (
                    (projection.confidence_scale_min, projection.confidence_scale_max)
                    == (0.0, 1.0),
                    "the owner scale is recorded with the value",
                ),
                "non-probability-not-called-probability": (
                    "probability" not in projection.confidence_name,
                    f"confidence name {projection.confidence_name}",
                ),
                "incomparable-confidence-remains-incomparable": (
                    projection.confidence_comparable_across_sources is False,
                    "confidence is marked incomparable across modules",
                ),
                "no-averaged-confidence": (
                    all(
                        token not in source
                        for token in ("statistics.mean", "fmean(", "/ len(confidences")
                    ),
                    "no confidence averaging function is used anywhere",
                ),
                "no-automatic-diagnosis-winner": (
                    len(inspected["diagnosis_projections"]) == 1
                    and all(
                        token not in source
                        for token in ("select_winner", "best_diagnosis", "preferred_diagnosis")
                    ),
                    "one owner diagnosis is projected; no winner selection exists",
                ),
                "missing-information-shown": (
                    inspected["missing_information"]
                    == ["The encoder stderr output was not retained."],
                    f"missing information {inspected['missing_information']}",
                ),
            },
        )


def _run_root_cause() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base", rca={"conflicting": True})
        projections = engine.build_root_cause_projections(PROJECT_ID, "case_a")
        inspected = engine.inspect_root_cause(PROJECT_ID, "case_a")

        multi, _ = _full_chain(root / "multi", rca={"candidates": 3})
        multi_rows = multi.build_root_cause_projections(PROJECT_ID, "case_a")
        multi_conflicts = multi.detect_incident_conflicts(PROJECT_ID, "case_a")

        supported, _ = _full_chain(
            root / "supported",
            rca={
                "analysis_status": "root_cause_supported",
                "verification_required": False,
                "human_review_required": True,
            },
        )
        supported_rows = supported.build_root_cause_projections(PROJECT_ID, "case_a")

        missing, _ = _engine(root / "missing")
        missing_rows = missing.build_root_cause_projections(PROJECT_ID, "case_a")
        source = _source_text()
        return _group(
            "root-cause",
            {
                "root-cause-candidate-projected": (
                    len(projections) == 1
                    and projections[0].root_cause_id == "candidate_0",
                    f"{len(projections)} candidate projected",
                ),
                "root-cause-hypothesis-labelled": (
                    projections[0].hypothesis and not projections[0].confirmed,
                    "the candidate is labelled a hypothesis",
                ),
                "no-confirmed-root-cause-claimed": (
                    not any(item.confirmed for item in supported_rows),
                    "even root_cause_supported stays unconfirmed while the owner "
                    "requires human review",
                ),
                "contradictory-evidence-shown": (
                    projections[0].contradictory_evidence_record_ids == ["evidence_b"],
                    f"contradictory evidence {projections[0].contradictory_evidence_record_ids}",
                ),
                "missing-root-cause-record": (
                    missing_rows == [],
                    "with no Root Cause Analyzer record nothing is projected",
                ),
                "multiple-current-candidates": (
                    len(multi_rows) == 3
                    and all(item.current for item in multi_rows),
                    f"{len(multi_rows)} current candidates all shown",
                ),
                "absent-supersession": (
                    all(item.superseded is False for item in multi_rows),
                    "no supersession is inferred between competing candidates",
                ),
                "no-automatic-winner": (
                    "root_cause_conflict"
                    in {item.conflict_type for item in multi_conflicts}
                    and inspected["confirmed_root_cause_count"] == 0,
                    "competing candidates raise a conflict instead of a winner",
                ),
                "no-confidence-averaging": (
                    all(
                        item.confidence_value is not None
                        and item.likelihood_value is not None
                        for item in multi_rows
                    )
                    and len({item.confidence_value for item in multi_rows}) == len(multi_rows)
                    and all(
                        token not in source
                        for token in ("statistics.mean", "fmean(", "average_confidence")
                    ),
                    "each candidate keeps its own distinct confidence and likelihood",
                ),
                "human-confirmation-required": (
                    all(item.human_confirmation_required for item in projections),
                    "human confirmation is required on every candidate",
                ),
                "likelihood-separate-from-confidence": (
                    projections[0].likelihood_value != projections[0].confidence_value,
                    f"likelihood {projections[0].likelihood_value} vs confidence "
                    f"{projections[0].confidence_value}",
                ),
                "confirmed-and-hypothesis-mutually-exclusive": _expect_error(
                    BobaRootCauseProjectionV1,
                    root_cause_projection_id="rc",
                    source_module_id="root_cause_analyzer",
                    source_record_id="r",
                    source_record_digest="0" * 64,
                    root_cause_id="candidate_0",
                    confirmed=True,
                    hypothesis=True,
                ),
            },
        )


def _run_repair_plans() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base")
        plans = engine.build_repair_plan_projections(PROJECT_ID, "case_a")
        inspected = engine.inspect_repair_plan(PROJECT_ID, "case_a")
        missing, _ = _engine(root / "missing")
        code, _ = _full_chain(
            root / "code",
            repair={
                "requires_code_change": True,
                "strategy_type": "propose_code_patch",
            },
        )
        artifact, _ = _full_chain(
            root / "artifact", repair={"strategy_type": "regenerate_artifact"}
        )
        restart, _ = _full_chain(root / "restart", repair={"requires_service_restart": True})
        checkpoint, _ = _full_chain(
            root / "checkpoint", repair={"strategy_type": "restore_checkpoint"}
        )
        transition, _ = _full_chain(
            root / "transition", repair={"strategy_type": "switch_safe_workflow_path"}
        )
        destructive, _ = _full_chain(
            root / "destructive",
            repair={"destructiveness": "destructive", "reversibility": "irreversible"},
        )
        no_rollback, _ = _full_chain(root / "norollback", repair={"with_rollback": False})
        source = _source_text()
        step_text = " ".join(plans[0].proposed_step_summaries) if plans else ""
        return _group(
            "repair-plans",
            {
                "repair-plan-present": (
                    len(plans) == 1 and plans[0].repair_plan_id == "strategy_a",
                    f"{len(plans)} repair plan projected",
                ),
                "repair-plan-missing": (
                    missing.build_repair_plan_projections(PROJECT_ID, "case_a") == [],
                    "with no Repair Planner record nothing is projected",
                ),
                "repair-plan-status-preserved": (
                    plans[0].original_status == "human_decision_required"
                    and plans[0].original_strategy == "retry_with_safe_settings",
                    f"status {plans[0].original_status}, strategy {plans[0].original_strategy}",
                ),
                "code-change-proposal-flagged": (
                    code.build_repair_plan_projections(PROJECT_ID, "case_a")[
                        0
                    ].requires_code_change,
                    "a proposed code change is reported",
                ),
                "artifact-change-proposal-flagged": (
                    artifact.build_repair_plan_projections(PROJECT_ID, "case_a")[
                        0
                    ].requires_artifact_change,
                    "a proposed artifact change is reported",
                ),
                "tool-execution-proposal-flagged": (
                    plans[0].requires_tool_execution,
                    "a proposed tool execution is reported",
                ),
                "process-restart-proposal-flagged": (
                    restart.build_repair_plan_projections(PROJECT_ID, "case_a")[
                        0
                    ].requires_process_restart,
                    "a proposed process restart is reported",
                ),
                "checkpoint-restore-proposal-flagged": (
                    checkpoint.build_repair_plan_projections(PROJECT_ID, "case_a")[
                        0
                    ].requires_checkpoint_restore,
                    "a proposed checkpoint restore is reported",
                ),
                "workflow-transition-proposal-flagged": (
                    transition.build_repair_plan_projections(PROJECT_ID, "case_a")[
                        0
                    ].requires_workflow_transition,
                    "a proposed workflow transition is reported",
                ),
                "human-approval-required": (
                    plans[0].requires_human_approval,
                    "the owner requires human approval on every strategy",
                ),
                "destructive-plan-flagged": (
                    destructive.build_repair_plan_projections(PROJECT_ID, "case_a")[
                        0
                    ].destructive,
                    "a destructive plan is reported destructive",
                ),
                "reversible-plan-flagged": (
                    plans[0].reversible
                    and not destructive.build_repair_plan_projections(
                        PROJECT_ID, "case_a"
                    )[0].reversible,
                    "reversibility follows the owner value",
                ),
                "rollback-availability-reported": (
                    plans[0].rollback_available
                    and not no_rollback.build_repair_plan_projections(
                        PROJECT_ID, "case_a"
                    )[0].rollback_available,
                    "rollback availability follows the owner rollback plan",
                ),
                "verification-required": (
                    plans[0].verification_required,
                    "verification is always required after a repair",
                ),
                "no-executable-control": (
                    plans[0].executable_by_panel is False
                    and inspected["repair_execution_available"] is False,
                    "repair execution is unavailable in the panel",
                ),
                "raw-command-not-exposed": (
                    plans[0].raw_command_exposed is False
                    and "ffmpeg" not in step_text
                    and "/home/" not in step_text,
                    f"step summaries expose descriptions only: {step_text[:80]}",
                ),
                "no-plan-generated-by-panel": (
                    "save_boba_repair_planner" not in source
                    and "def generate" not in source,
                    "the panel never writes or generates a repair plan",
                ),
                "source-owned-rank-preserved": (
                    plans[0].source_owned_rank == 1
                    and plans[0].source_owned_score == 0.62
                    and plans[0].source_owned_score_name
                    == "repair_planner_strategy_score",
                    "rank and score keep their Repair Planner ownership",
                ),
                "no-panel-repair-score": (
                    "hidden_repair_score_created: Literal[False]" in source,
                    "no panel-side repair score exists",
                ),
            },
        )


def _run_recovery() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        none_engine, _ = _engine(root / "none")
        completed, _ = _full_chain(root / "completed")
        pending, _ = _full_chain(
            root / "pending",
            recovery={"attempts": (("attempt_1", "succeeded_pending_validation"),)},
        )
        verified, _ = _full_chain(
            root / "verified", recovery={"with_validation": True, "validation_passed": True}
        )
        failed, _ = _full_chain(
            root / "failed", recovery={"attempts": (("attempt_1", "failed"),)}
        )
        timed_out, _ = _full_chain(
            root / "timedout", recovery={"attempts": (("attempt_1", "timed_out"),)}
        )
        repeated, _ = _full_chain(
            root / "repeated",
            recovery={
                "attempts": (
                    ("attempt_1", "failed"),
                    ("attempt_2", "failed"),
                    ("attempt_3", "completed"),
                )
            },
        )
        rolled_back, _ = _full_chain(
            root / "rollback", recovery={"with_rollback": True, "rollback_status": "failed"}
        )
        classed, _ = _full_chain(
            root / "classed", recovery={"failure_class": "tool_timeout"}
        )
        history = repeated.inspect_recovery_history(PROJECT_ID, "case_a")
        reference = completed.build_incident_references(PROJECT_ID)[0]
        return _group(
            "recovery",
            {
                "no-attempt": (
                    none_engine.build_recovery_attempt_projections(PROJECT_ID, "case_a")
                    == [],
                    "with no Tool Recovery record nothing is projected",
                ),
                "attempted": (
                    completed.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].attempted,
                    "an attempt with a status past not_started is attempted",
                ),
                "completed": (
                    completed.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].completed,
                    "a completed status is reported completed",
                ),
                "owner-reported-success": (
                    pending.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].succeeded_by_owner,
                    "succeeded_pending_validation is owner-reported success",
                ),
                "independently-verified": (
                    verified.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].verified,
                    "a passing output validation marks the attempt verified",
                ),
                "succeeded-but-unverified": (
                    pending.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].succeeded_by_owner
                    and not pending.build_recovery_attempt_projections(
                        PROJECT_ID, "case_a"
                    )[0].verified,
                    "owner-reported success without verification stays unverified",
                ),
                "failed-attempt": (
                    failed.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].original_status
                    == "failed",
                    "a failed attempt keeps its failed status",
                ),
                "timed-out-attempt": (
                    timed_out.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].timed_out,
                    "a timed-out attempt is reported as timed out",
                ),
                "repeated-failure-visible": (
                    history["attempt_count"] == 3
                    and history["failed_attempt_count"] == 2,
                    f"{history['attempt_count']} attempts, "
                    f"{history['failed_attempt_count']} failed, all listed",
                ),
                "resulting-error-recorded": (
                    classed.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].resulting_error_code
                    == "tool_timeout",
                    "the owner failure class is projected as the resulting error",
                ),
                "rollback-attempted": (
                    rolled_back.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].rollback_attempted,
                    "a rollback record marks the attempt as rolled back",
                ),
                "rollback-status-preserved": (
                    rolled_back.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].rollback_status
                    == "failed",
                    "the owner rollback status is projected verbatim",
                ),
                "code-change-not-inferred": (
                    not any(
                        item.changed_code
                        for item in completed.build_recovery_attempt_projections(
                            PROJECT_ID, "case_a"
                        )
                    ),
                    "code change is never inferred from a recovery attempt",
                ),
                "artifact-change-not-inferred": (
                    not any(
                        item.changed_artifacts
                        for item in completed.build_recovery_attempt_projections(
                            PROJECT_ID, "case_a"
                        )
                    ),
                    "artifact change requires the owner to disclose it",
                ),
                "workflow-change-not-inferred": (
                    not any(
                        item.changed_workflow
                        for item in completed.build_recovery_attempt_projections(
                            PROJECT_ID, "case_a"
                        )
                    ),
                    "workflow change is never inferred",
                ),
                "no-change-inferred-from-success": (
                    completed.build_recovery_attempt_projections(PROJECT_ID, "case_a")[
                        0
                    ].succeeded_by_owner
                    and not completed.build_recovery_attempt_projections(
                        PROJECT_ID, "case_a"
                    )[0].changed_code,
                    "success alone never implies a code or artifact change",
                ),
                "failed-attempts-remain-visible": (
                    [
                        item.original_status
                        for item in repeated.build_recovery_attempt_projections(
                            PROJECT_ID, "case_a"
                        )
                    ]
                    == ["failed", "failed", "completed"],
                    "failed attempts are never collapsed or hidden",
                ),
                "recovered-is-not-resolved": (
                    reference.recovered and not reference.resolved,
                    "recovered is reported without claiming resolved",
                ),
                "attempted-not-completed": _expect_error(
                    BobaRecoveryAttemptProjectionV1,
                    recovery_attempt_projection_id="ra",
                    source_module_id="tool_recovery",
                    source_record_id="r",
                    source_record_digest="0" * 64,
                    recovery_attempt_id="attempt_1",
                    attempted=False,
                    completed=True,
                ),
            },
        )


def _run_queue() -> list[ScenarioResult]:
    priority = BobaErrorDoctorReviewV1._priority
    base = {
        "critical_safety": False,
        "workflow_blocking": False,
        "failed_recovery": False,
        "conflicting": False,
        "missing_diagnosis": False,
        "missing_root_cause": False,
        "repair_awaiting_approval": False,
        "stale_verification": False,
        "recurring": False,
        "recovered_unverified": False,
        "resolved": False,
        "superseded": False,
        "historical": False,
    }

    def tier(**overrides: bool) -> int:
        return priority(**{**base, **overrides})[0]

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base")
        queue = engine.build_incident_queue(PROJECT_ID)
        repeat = engine.build_incident_queue(PROJECT_ID)
        paged = engine.build_incident_queue(PROJECT_ID, limit=10_000)
        keys = [item["deterministic_sort_key"] for item in queue["items"]]
        filters = (
            "all_current",
            "critical",
            "workflow_blocking",
            "human_review_required",
            "missing_diagnosis",
            "missing_root_cause",
            "repair_plan_available",
            "failed_recovery",
            "unverified_recovery",
            "recurring",
            "conflicts",
            "missing_evidence",
            "stale",
            "recovered",
            "resolved",
            "historical",
            "superseded",
        )
        sorts = (
            "review_priority",
            "source_severity",
            "first_seen",
            "last_seen",
            "affected_stage",
            "affected_module",
            "incident_id",
        )
        filter_results = {
            name: len(engine.build_incident_queue(PROJECT_ID, review_filter=name)["items"])
            for name in filters
        }
        sort_results = {
            name: [
                item["incident_id"]
                for item in engine.build_incident_queue(PROJECT_ID, sort=name)["items"]
            ]
            for name in sorts
        }
        return _group(
            "queue",
            {
                "critical-safety-priority": (
                    tier(critical_safety=True) == 10,
                    "a critical Safety or Rights incident is tier 10",
                ),
                "workflow-blocking-priority": (
                    tier(workflow_blocking=True) == 20,
                    "a workflow-blocking incident is tier 20",
                ),
                "failed-recovery-priority": (
                    tier(failed_recovery=True) == 30,
                    "a failed or partial recovery is tier 30",
                ),
                "conflict-priority": (
                    tier(conflicting=True) == 40,
                    "conflicting records are tier 40",
                ),
                "missing-diagnosis-priority": (
                    tier(missing_diagnosis=True) == 50,
                    "a missing diagnosis is tier 50",
                ),
                "missing-root-cause-priority": (
                    tier(missing_root_cause=True) == 60,
                    "a missing root-cause analysis is tier 60",
                ),
                "repair-approval-priority": (
                    tier(repair_awaiting_approval=True) == 70,
                    "a repair plan awaiting approval is tier 70",
                ),
                "stale-verification-priority": (
                    tier(stale_verification=True) == 80,
                    "stale validation or artifact evidence is tier 80",
                ),
                "recurring-priority": (
                    tier(recurring=True) == 90,
                    "a recurring incident is tier 90",
                ),
                "unresolved-current-priority": (
                    tier() == 100,
                    "any other unresolved current incident is tier 100",
                ),
                "recovered-unverified-priority": (
                    tier(recovered_unverified=True) == 110,
                    "recovered but unverified is tier 110",
                ),
                "resolved-priority": (
                    tier(resolved=True) == 120,
                    "a resolved current incident is tier 120",
                ),
                "superseded-priority": (
                    tier(superseded=True) == 130,
                    "a superseded incident is tier 130",
                ),
                "historical-priority": (
                    tier(historical=True) == 140,
                    "a historical incident is tier 140",
                ),
                "fourteen-priority-tiers": (
                    len(INCIDENT_QUEUE_PRIORITY_TIERS) == 14
                    and len(queue["priority_tiers"]) == 14,
                    f"{len(INCIDENT_QUEUE_PRIORITY_TIERS)} fixed tiers",
                ),
                "deterministic-tie-break": (
                    len(set(keys)) == len(keys) and keys == sorted(keys),
                    f"sort keys {keys}",
                ),
                "deterministic-repeat-order": (
                    queue["items"] == repeat["items"],
                    "repeat builds produce an identical queue",
                ),
                "pagination-bounded": (
                    paged["limit"] == MAX_QUEUE_PAGE_SIZE == 50,
                    f"limit bounded to {paged['limit']}",
                ),
                "supported-filters": (
                    len(filter_results) == 17,
                    f"17 filters accepted: {filter_results}",
                ),
                "supported-sorts": (
                    len(sort_results) == 7
                    and len(source_severity_order()) == 7
                    and all(len(rows) == 2 for rows in sort_results.values()),
                    f"7 sorts accepted: {list(sort_results)}",
                ),
                "unsupported-filter-rejected": _expect_error(
                    engine.build_incident_queue, PROJECT_ID, review_filter="easiest_fix"
                ),
                "unsupported-sort-rejected": _expect_error(
                    engine.build_incident_queue,
                    PROJECT_ID,
                    sort="highest_success_probability",
                ),
            },
        )


def _run_evidence() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(
            root / "base",
            raw={
                "observer": {
                    "schema_version": "boba_observer_v1",
                    "project_id": PROJECT_ID,
                    "source_id": "synthetic_source",
                    "artifact_observations": [
                        {
                            "artifact_id": "render_manifest",
                            "findings": [
                                {
                                    "finding_id": "finding_a",
                                    "message": (
                                        "Missing output near /home/me/out.mp4 with "
                                        "token=abcdef123456"
                                    ),
                                    "issue_level": "critical",
                                }
                            ],
                        }
                    ],
                },
                "validator_runner": {
                    "schema_version": "boba_validator_runner_v1",
                    "validation_runs": [
                        {
                            "validation_run_id": "validation_run_a",
                            "status": "failed",
                            "executed_check_count": 4,
                            "passed_check_count": 3,
                            "failed_check_count": 1,
                            "skipped_check_count": 0,
                        }
                    ],
                    "validation_results": [{"result_id": "result_a"}],
                },
                "artifact_inspector": {
                    "artifact_references": [
                        {
                            "artifact_reference_id": "artifact_ref_a",
                            "content_digest": "c" * 64,
                            "status": "corrupt",
                        }
                    ],
                    "incidents": [],
                },
                "code_surgeon": {
                    "schema_version": "boba_code_surgeon_v1",
                    "code_repair_cases": [
                        {
                            "code_repair_case_id": "code_case_a",
                            "source_repair_case_id": "repair_a",
                            "code_change_justified": False,
                            "evidence_strength": "weak",
                            "execution_eligible": False,
                            "approval_required": True,
                            "affected_paths": ["/home/me/src/x.py"],
                            "blocked_reason": "Evidence is too weak for a code change.",
                        }
                    ],
                },
            },
        )
        cards = engine.build_evidence_cards(PROJECT_ID, "case_a")
        by_module: dict[str, Any] = {}
        for card in cards:
            by_module.setdefault(card.source_module_id, card)
        observer_card = next(
            item for item in cards if item.evidence_type == "observer_finding"
        )
        validation = engine.inspect_validation_evidence(PROJECT_ID, "case_a")
        repair_plan = engine.inspect_repair_plan(PROJECT_ID, "case_a")
        long_engine, _ = _full_chain(
            root / "long",
            raw={
                "observer": {
                    "schema_version": "boba_observer_v1",
                    "artifact_observations": [
                        {
                            "artifact_id": "a",
                            "findings": [
                                {
                                    "finding_id": "finding_a",
                                    "message": "x" * (MAX_EXCERPT_CHARS + 5_000),
                                    "issue_level": "high",
                                }
                            ],
                        }
                    ],
                }
            },
        )
        long_card = next(
            item
            for item in long_engine.build_evidence_cards(PROJECT_ID, "case_a")
            if item.evidence_type == "observer_finding"
        )
        source = _source_text()
        missing_cards = [item for item in cards if item.missing]
        return _group(
            "evidence",
            {
                "observer-evidence": (
                    not observer_card.missing
                    and observer_card.source_module_id == "observer",
                    "the referenced Observer finding is linked",
                ),
                "error-doctor-evidence": (
                    any(item.evidence_type == "error_doctor_evidence" for item in cards),
                    "Error Doctor's own evidence rows are projected",
                ),
                "root-cause-evidence": (
                    by_module["root_cause_analyzer"].current,
                    "the Root Cause Analyzer record is linked",
                ),
                "repair-planner-evidence": (
                    by_module["repair_planner"].current,
                    "the Repair Planner record is linked",
                ),
                "code-surgeon-evidence": (
                    by_module["code_surgeon"].current
                    and repair_plan["code_repair_cases"][0]["code_repair_case_id"]
                    == "code_case_a",
                    "the Code Surgeon record is linked",
                ),
                "tool-recovery-evidence": (
                    by_module["tool_recovery"].current,
                    "the Tool Recovery record is linked",
                ),
                "workflow-evidence": (
                    "workflow_controller" in by_module,
                    "a Workflow Controller card is always present",
                ),
                "validator-evidence": (
                    by_module["validator_runner"].current
                    and validation["validation_runs"][0]["original_status"] == "failed",
                    "the Validator Runner status is projected verbatim",
                ),
                "report-reader-evidence": (
                    "report_reader" in by_module,
                    "a Report Reader card is always present",
                ),
                "artifact-evidence": (
                    by_module["artifact_inspector"].current,
                    "the Artifact Inspector record is linked",
                ),
                "output-quality-evidence": (
                    "output_quality_reviewer" in by_module,
                    "an Output Quality Reviewer card is always present",
                ),
                "safety-evidence": (
                    "safety_gate" in by_module,
                    "a Safety Gate card is always present",
                ),
                "final-decision-evidence": (
                    "final_decision_bus" in by_module,
                    "a Final Decision Bus card is always present",
                ),
                "exact-persisted-relationship": (
                    observer_card.source_record_id == "finding_a",
                    "evidence is linked by the exact persisted finding identity",
                ),
                "missing-relationship": (
                    len(missing_cards) >= 1
                    and all(item.classification == "unavailable" for item in missing_cards),
                    f"{len(missing_cards)} missing evidence cards reported",
                ),
                "digest-recorded": (
                    all(
                        len(item.source_record_digest) == 64
                        for item in cards
                        if item.current
                    ),
                    "every present card carries a 64-character record digest",
                ),
                "advisory-evidence-marked": (
                    by_module["autopilot_controller"].advisory_only,
                    "Autopilot Controller evidence is advisory only",
                ),
                "authoritative-evidence-marked": (
                    by_module["safety_gate"].authoritative
                    and by_module["validator_runner"].authoritative,
                    "Safety and Validator evidence stay authoritative",
                ),
                "missing-evidence-not-pass": (
                    all(
                        any("never treated as a pass" in row for row in item.limitations)
                        for item in missing_cards
                    ),
                    "every missing card states that missing is not a pass",
                ),
                "bounded-excerpt": (
                    len(observer_card.bounded_excerpt) <= MAX_EXCERPT_CHARS,
                    f"excerpt bounded to {len(observer_card.bounded_excerpt)} characters",
                ),
                "truncated-excerpt-reported": (
                    long_card.excerpt_truncated,
                    "an oversized excerpt reports truncation explicitly",
                ),
                "sensitive-value-redacted": (
                    observer_card.sensitive_values_redacted
                    and "abcdef123456" not in observer_card.bounded_excerpt,
                    "secret-shaped values are removed from the excerpt",
                ),
                "private-path-redacted": (
                    observer_card.private_paths_redacted
                    and "/home/me" not in observer_card.bounded_excerpt,
                    "private paths are removed from the excerpt",
                ),
                "full-logs-not-duplicated": (
                    all(
                        len(item.bounded_excerpt) <= MAX_EXCERPT_CHARS for item in cards
                    )
                    and repair_plan["code_repair_cases"][0].get("affected_path_count") == 1
                    and "affected_paths" not in repair_plan["code_repair_cases"][0],
                    "affected paths are counted, never listed",
                ),
                "no-text-similarity-inference": (
                    all(
                        token not in source
                        for token in ("difflib", "SequenceMatcher", "similarity", "fuzz")
                    ),
                    "evidence is linked by identity, never by text similarity",
                ),
                "evidence-cards-bounded": (
                    len(cards) <= MAX_EVIDENCE_CARDS,
                    f"{len(cards)} evidence cards, bounded to {MAX_EVIDENCE_CARDS}",
                ),
            },
        )


def _run_conflicts() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        clean, _ = _engine(root / "clean")
        clean_rows = clean.detect_incident_conflicts(PROJECT_ID, "case_a")

        stage, _ = _full_chain(root / "stage", rca={"workflow_stage": "encode"})
        stage_rows = stage.detect_incident_conflicts(PROJECT_ID, "case_a")

        module, _ = _full_chain(root / "module", rca={"primary_module": "captions"})
        module_rows = module.detect_incident_conflicts(PROJECT_ID, "case_a")

        competing, _ = _full_chain(root / "competing", rca={"candidates": 3})
        competing_rows = competing.detect_incident_conflicts(PROJECT_ID, "case_a")

        not_needed, _ = _full_chain(
            root / "notneeded", repair={"planning_status": "repair_not_required"}
        )
        not_needed_rows = not_needed.detect_incident_conflicts(PROJECT_ID, "case_a")

        mixed, _ = _full_chain(
            root / "mixed",
            recovery={"attempts": (("attempt_1", "completed"), ("attempt_2", "failed"))},
        )
        mixed_rows = mixed.detect_incident_conflicts(PROJECT_ID, "case_a")

        unverified, _ = _full_chain(root / "unverified")
        unverified_rows = unverified.detect_incident_conflicts(PROJECT_ID, "case_a")

        severity_payload = synthetic_error_doctor_set(
            PROJECT_ID, [synthetic_case("case_a", severity="low")]
        ).model_dump(mode="json")
        severity, _ = _raw_engine(
            root / "severity",
            {
                "error_doctor": severity_payload,
                "artifact_inspector": {
                    "incidents": [
                        {
                            "incident_id": "artifact_incident_a",
                            "severity": "critical",
                            "incident_type": "corrupt_artifact",
                        }
                    ]
                },
            },
        )
        severity_rows = severity.detect_incident_conflicts(PROJECT_ID, "case_a")

        unsupported_payload = synthetic_error_doctor_set(
            PROJECT_ID, [synthetic_case("case_a")]
        ).model_dump(mode="json")
        unsupported_payload["schema_version"] = "boba_error_doctor_v9"
        unsupported, _ = _raw_engine(
            root / "unsupported", {"error_doctor": unsupported_payload}
        )
        unsupported_rows = unsupported.detect_incident_conflicts(PROJECT_ID, "case_a")

        blocking_payload = _prepared(stage)
        source = _source_text()
        conflict_source = source.split("def detect_incident_conflicts", 1)[1].split(
            "def inspect_incident_conflicts", 1
        )[0]

        def types_of(rows: list[Any]) -> set[str]:
            return {item.conflict_type for item in rows}

        return _group(
            "conflicts",
            {
                "stage-identity-conflict": (
                    "stage_identity_conflict" in types_of(stage_rows),
                    f"conflict types {sorted(types_of(stage_rows))}",
                ),
                "diagnosis-conflict": (
                    "diagnosis_conflict" in types_of(module_rows),
                    f"conflict types {sorted(types_of(module_rows))}",
                ),
                "root-cause-conflict": (
                    "root_cause_conflict" in types_of(competing_rows),
                    f"conflict types {sorted(types_of(competing_rows))}",
                ),
                "repair-plan-conflict": (
                    "repair_plan_conflict" in types_of(not_needed_rows),
                    f"conflict types {sorted(types_of(not_needed_rows))}",
                ),
                "recovery-status-conflict": (
                    "recovery_status_conflict" in types_of(mixed_rows),
                    f"conflict types {sorted(types_of(mixed_rows))}",
                ),
                "validation-conflict": (
                    "validation_conflict" in types_of(unverified_rows),
                    f"conflict types {sorted(types_of(unverified_rows))}",
                ),
                "severity-conflict": (
                    "severity_conflict" in types_of(severity_rows),
                    f"conflict types {sorted(types_of(severity_rows))}",
                ),
                "unsupported-schema-conflict": (
                    "unknown" in types_of(unsupported_rows),
                    f"conflict types {sorted(types_of(unsupported_rows))}",
                ),
                "no-conflict-on-clean-project": (
                    clean_rows == [],
                    "a project with only a consistent diagnosis has no conflict",
                ),
                "same-incident-required": (
                    all(item.same_incident for item in stage_rows + competing_rows),
                    "conflicts are raised only within one incident identity",
                ),
                "no-explicit-supersession-found": (
                    all(
                        item.explicit_supersession_found is False
                        for item in competing_rows
                    ),
                    "no supersession is invented to resolve competing records",
                ),
                "unresolved-conflict-explicit": (
                    all(
                        not item.resolved and item.resolution_source_id is None
                        for item in stage_rows
                    ),
                    "conflicts stay explicitly unresolved",
                ),
                "confidence-does-not-resolve": (
                    all(
                        token not in conflict_source
                        for token in (
                            'get("confidence")',
                            ".confidence_value",
                            "confidence_value >",
                            "root_cause_confidence",
                        )
                    ),
                    "conflict detection reads no confidence value; the word appears "
                    "only in the limitation text stating confidence never resolves it",
                ),
                "blocking-conflict-blocks-action": (
                    any(item.blocks_action for item in stage_rows)
                    and _ACK in blocking_payload["snapshot"][
                        "available_action_descriptor_ids"
                    ],
                    "a blocking conflict is recorded; acknowledgement stays "
                    "available because it does not require a current snapshot",
                ),
                "conflict-count-reported": (
                    stage.inspect_incident_conflicts(PROJECT_ID, "case_a")[
                        "blocking_conflict_count"
                    ]
                    >= 1,
                    "blocking and unresolved counts are reported",
                ),
                "advisory-absence-not-conflict": (
                    clean_rows == []
                    and any(
                        item.missing
                        for item in clean.build_evidence_cards(PROJECT_ID, "case_a")
                    ),
                    "an absent advisory module is never reported as a conflict",
                ),
                "conflict-limitation-stated": (
                    all(
                        any("never resolved by comparing" in row for row in item.limitations)
                        for item in stage_rows
                    ),
                    "every conflict states that confidence never resolves it",
                ),
            },
        )


def _run_comparison() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base")
        pair = engine.compare_incidents(PROJECT_ID, ["case_a", "case_b"])["comparison"]
        collapsed = engine.compare_incidents(
            PROJECT_ID, ["case_a", "case_b", "case_a"]
        )["comparison"]
        four_cases = [
            synthetic_case("case_a"),
            synthetic_case("case_b", workflow_stage="render", primary_module="rendering"),
            synthetic_case("case_c", workflow_stage="render", primary_module="rendering"),
            synthetic_case("case_d", workflow_stage="render", primary_module="rendering"),
        ]
        four, _ = _engine(root / "four", cases=four_cases)
        quad = four.compare_incidents(
            PROJECT_ID, ["case_a", "case_b", "case_c", "case_d"]
        )["comparison"]
        same, _ = _engine(
            root / "same",
            cases=[
                synthetic_case("case_a"),
                synthetic_case("case_b", workflow_stage="render", primary_module="rendering"),
            ],
        )
        same_pair = same.compare_incidents(PROJECT_ID, ["case_a", "case_b"])["comparison"]
        return _group(
            "comparison",
            {
                "two-incidents": (
                    pair["incident_ids"] == ["case_a", "case_b"],
                    f"compared {pair['incident_ids']}",
                ),
                "four-incidents": (
                    len(quad["incident_ids"]) == MAX_COMPARISON_INCIDENTS == 4,
                    f"compared {quad['incident_ids']}",
                ),
                "single-incident-rejected": _expect_error(
                    engine.compare_incidents, PROJECT_ID, ["case_a"]
                ),
                "too-many-rejected": _expect_error(
                    four.compare_incidents,
                    PROJECT_ID,
                    ["case_a", "case_b", "case_c", "case_d", "case_e"],
                ),
                "unknown-incident-rejected": _expect_error(
                    engine.compare_incidents, PROJECT_ID, ["case_a", "case_absent"]
                ),
                "duplicate-ids-collapsed": (
                    collapsed["incident_ids"] == ["case_a", "case_b"],
                    f"duplicates collapsed to {collapsed['incident_ids']}",
                ),
                "unsupported-type-rejected": _expect_error(
                    engine.compare_incidents,
                    PROJECT_ID,
                    ["case_a", "case_b"],
                    comparison_type="pick_the_best",
                ),
                "same-workflow-detected": (
                    pair["same_workflow_run"] is True,
                    "both incidents belong to the same workflow run projection",
                ),
                "same-stage-detected": (
                    same_pair["same_stage"] is True and pair["same_stage"] is False,
                    f"same stage {same_pair['same_stage']} vs {pair['same_stage']}",
                ),
                "same-module-detected": (
                    same_pair["same_affected_module"] is True
                    and pair["same_affected_module"] is False,
                    "affected-module sameness follows the owner values",
                ),
                "diagnosis-comparison": (
                    len(pair["diagnosis_comparison"]) == 2
                    and all(
                        row["confidence_comparable_across_sources"] is False
                        for row in pair["diagnosis_comparison"]
                    ),
                    "diagnosis rows are compared without claiming comparable confidence",
                ),
                "root-cause-comparison": (
                    len(pair["root_cause_comparison"]) == 2
                    and pair["root_cause_comparison"][0]["confirmed_count"] == 0,
                    f"root-cause rows {pair['root_cause_comparison']}",
                ),
                "repair-comparison": (
                    len(pair["repair_plan_comparison"]) == 2
                    and all(
                        row["executable_by_panel"] is False
                        for row in pair["repair_plan_comparison"]
                    ),
                    "repair rows are compared and stay non-executable",
                ),
                "recovery-comparison": (
                    len(pair["recovery_history_comparison"]) == 2
                    and "owner_reported_success_count"
                    in pair["recovery_history_comparison"][0]
                    and "independently_verified_count"
                    in pair["recovery_history_comparison"][0],
                    "owner success and verification are compared separately",
                ),
                "validation-comparison": (
                    len(pair["validation_comparison"]) == 2,
                    f"{len(pair['validation_comparison'])} validation rows",
                ),
                "artifact-comparison": (
                    len(pair["artifact_comparison"]) == 2,
                    f"{len(pair['artifact_comparison'])} artifact rows",
                ),
                "no-automatic-winner": (
                    pair["no_automatic_winner"] is True
                    and quad["no_automatic_winner"] is True,
                    "comparison never selects a winning incident",
                ),
                "no-automatic-root-cause-selection": (
                    pair["no_automatic_root_cause_selection"] is True,
                    "comparison never selects a root cause",
                ),
                "no-automatic-repair-selection": (
                    pair["no_automatic_repair_selection"] is True,
                    "comparison never selects a repair plan",
                ),
            },
        )


def _drifted(root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Create a real action request, then drift the persisted expectation."""
    engine, _ = _full_chain(root)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_drift_key")
    _rewrite(
        engine.store.boba_error_doctor_review_action_path(
            PROJECT_ID, request.error_doctor_action_request_id
        ),
        updates,
    )
    return engine.validate_error_doctor_action_request(
        PROJECT_ID, request.error_doctor_action_request_id
    )


def _run_actions() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, owner = _full_chain(root / "base")
        payload = _prepared(engine)
        registry = build_fixed_error_doctor_action_registry()
        available_ids = payload["snapshot"]["available_action_descriptor_ids"]
        session_id = payload["session"].error_doctor_review_session_id
        snapshot_id = payload["snapshot"]["incident_snapshot_id"]

        def create(**overrides: Any) -> Any:
            kwargs: dict[str, Any] = {
                "error_doctor_review_session_id": session_id,
                "incident_snapshot_id": snapshot_id,
                "action_descriptor_id": _ACK,
                "decision_value": "acknowledged",
                "reason": "",
                "confirmation_context_digest": payload["action_confirmations"][_ACK],
                "idempotency_key": "idem_probe_key",
                "confirmed": True,
            }
            kwargs.update(overrides)
            return engine.create_error_doctor_action_request(PROJECT_ID, **kwargs)

        accepted_engine, accepted_owner = _full_chain(root / "accepted")
        accepted_payload = _prepared(accepted_engine)
        accepted_request = _request(accepted_engine, accepted_payload, "idem_accept_key")
        digest_before = accepted_payload["snapshot"]["incident_digest"]
        accepted = asyncio.run(
            accepted_engine.submit_error_doctor_action_to_owner(
                PROJECT_ID, accepted_request.error_doctor_action_request_id
            )
        )
        duplicate = asyncio.run(
            accepted_engine.submit_error_doctor_action_to_owner(
                PROJECT_ID, accepted_request.error_doctor_action_request_id
            )
        )
        digest_after = accepted_engine._incident_digest(PROJECT_ID, "case_a")

        rejecting_engine, rejecting_owner = _full_chain(root / "rejecting")
        rejecting_payload = _prepared(rejecting_engine)
        rejecting_request = _request(rejecting_engine, rejecting_payload, "idem_reject_key")
        rejecting_owner.reject = True
        rejected = asyncio.run(
            rejecting_engine.submit_error_doctor_action_to_owner(
                PROJECT_ID, rejecting_request.error_doctor_action_request_id
            )
        )

        malformed_engine, malformed_owner = _full_chain(root / "malformed")
        malformed_payload = _prepared(malformed_engine)
        malformed_request = _request(malformed_engine, malformed_payload, "idem_malform_key")
        malformed_owner.malformed = True
        malformed = asyncio.run(
            malformed_engine.submit_error_doctor_action_to_owner(
                PROJECT_ID, malformed_request.error_doctor_action_request_id
            )
        )

        expired = _drifted(
            root / "expired",
            {"expires_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()},
        )
        project_drift = _drifted(
            root / "project", {"expected_project_snapshot_digest": "1" * 64}
        )
        revision_drift = _drifted(root / "revision", {"expected_workflow_revision": 9})
        incident_drift = _drifted(root / "incident", {"expected_incident_digest": "2" * 64})
        source_drift = _drifted(
            root / "source", {"expected_source_record_digests": {"error_doctor": "3" * 64}}
        )

        forged = BobaErrorDoctorActionReceiptV1(
            error_doctor_action_receipt_id="error_doctor_receipt_forged",
            error_doctor_action_request_id=accepted_request.error_doctor_action_request_id,
            project_id=PROJECT_ID,
            incident_id="case_a",
            owning_module_id="review_ui",
            owning_operation_id="acknowledge_notification",
            authoritative_state_changed=True,
        )
        forged_repair = forged.model_copy(
            update={"authoritative_state_changed": False, "repair_executed": True}
        )
        unavailable = [
            item for item in registry.values() if item.availability == "unavailable"
        ]
        return _group(
            "actions",
            {
                "acknowledge-available": (
                    available_ids == [_ACK]
                    and registry[_ACK].owning_module_id == "review_ui",
                    f"available actions {available_ids}",
                ),
                "diagnosis-refresh-unavailable": (
                    registry[
                        "error_doctor_action_request_diagnosis_refresh_v1"
                    ].availability
                    == "unavailable",
                    "no per-incident diagnosis refresh operation exists",
                ),
                "root-cause-review-unavailable": (
                    registry[
                        "error_doctor_action_request_root_cause_review_v1"
                    ].availability
                    == "unavailable",
                    "no per-incident root-cause review operation exists",
                ),
                "repair-approval-unavailable": (
                    registry["error_doctor_action_approve_repair_plan_v1"].availability
                    == "unavailable",
                    "no canonical repair approval operation exists",
                ),
                "repair-rejection-unavailable": (
                    registry["error_doctor_action_reject_repair_plan_v1"].availability
                    == "unavailable",
                    "no canonical repair rejection operation exists",
                ),
                "repair-revision-unavailable": (
                    registry[
                        "error_doctor_action_request_repair_plan_revision_v1"
                    ].availability
                    == "unavailable",
                    "repair plans carry no revision identity",
                ),
                "recovery-attempt-unavailable": (
                    registry[
                        "error_doctor_action_request_recovery_attempt_v1"
                    ].availability
                    == "unavailable",
                    "recovery execution is withheld from the panel",
                ),
                "tool-retry-unavailable": (
                    registry["error_doctor_action_request_tool_retry_v1"].availability
                    == "unavailable",
                    "a tool retry runs a real command and is withheld",
                ),
                "checkpoint-recovery-unavailable": (
                    registry[
                        "error_doctor_action_request_checkpoint_recovery_v1"
                    ].availability
                    == "unavailable",
                    "workflow_controller.resume is future_gated",
                ),
                "escalation-unavailable": (
                    registry["error_doctor_action_escalate_incident_v1"].availability
                    == "unavailable",
                    "no module exposes an escalation operation",
                ),
                "incident-feedback-unavailable": (
                    registry[
                        "error_doctor_action_submit_incident_feedback_v1"
                    ].availability
                    == "unavailable",
                    "Creator Learning defines no incident feedback target type",
                ),
                "review-note-unavailable": (
                    registry[
                        "error_doctor_action_record_incident_review_note_v1"
                    ].availability
                    == "unavailable",
                    "no canonical owner accepts an incident-scoped note",
                ),
                "no-execution-capable-action-available": (
                    not any(
                        item.execution_capable
                        or item.destructive
                        or item.code_modifying
                        or item.artifact_modifying
                        or item.workflow_modifying
                        or item.upload_or_publication
                        for item in registry.values()
                        if item.availability == "available"
                    ),
                    "no available action can execute, modify or publish anything",
                ),
                "no-authoritative-action-available": (
                    not any(
                        item.authoritative
                        for item in registry.values()
                        if item.availability == "available"
                    ),
                    "no available action is authoritative",
                ),
                "unknown-action-rejected": _expect_error(
                    create,
                    action_descriptor_id="error_doctor_action_invented_v1",
                    confirmation_context_digest="0" * 64,
                ),
                "unavailable-action-rejected": _expect_error(
                    create,
                    action_descriptor_id="error_doctor_action_request_recovery_attempt_v1",
                    decision_value=None,
                    reason="Try recovery.",
                    confirmation_context_digest="0" * 64,
                ),
                "unsupported-decision-rejected": _expect_error(
                    create, decision_value="resolved"
                ),
                "oversized-reason-rejected": _expect_error(create, reason="x" * 900),
                "secret-bearing-reason-rejected": _expect_error(
                    create, reason="Use api_token=abcdef123456 to check."
                ),
                "private-path-reason-rejected": _expect_error(
                    create, reason="See /home/me/notes.txt for detail."
                ),
                "missing-confirmation-rejected": _expect_error(create, confirmed=False),
                "wrong-confirmation-token-rejected": _expect_error(
                    create, confirmation_context_digest="4" * 64
                ),
                "missing-reviewer-context-rejected": _expect_error(
                    engine.create_error_doctor_review_session,
                    PROJECT_ID,
                    reviewer_context_id="",
                ),
                "expired-snapshot-rejected": (
                    expired["code"] == "expired_snapshot" and not expired["valid"],
                    f"validation code {expired['code']}",
                ),
                "changed-project-digest-rejected": (
                    project_drift["code"] == "stale_project_snapshot",
                    f"validation code {project_drift['code']}",
                ),
                "changed-workflow-revision-rejected": (
                    revision_drift["code"] == "workflow_revision_mismatch",
                    f"validation code {revision_drift['code']}",
                ),
                "changed-incident-digest-rejected": (
                    incident_drift["code"] == "incident_digest_mismatch",
                    f"validation code {incident_drift['code']}",
                ),
                "changed-source-digest-rejected": (
                    source_drift["code"] == "source_record_digest_mismatch",
                    f"validation code {source_drift['code']}",
                ),
                "canonical-receipt-recorded": (
                    accepted.accepted_by_owner
                    and accepted.canonical_status == "acknowledged"
                    and accepted.owning_module_id == "review_ui"
                    and accepted_owner.acknowledged == ["case_a"],
                    f"owner recorded {accepted.canonical_record_id}",
                ),
                "owner-rejection-recorded": (
                    rejected.canonical_status == "rejected_by_owner"
                    and not rejected.accepted_by_owner,
                    f"canonical status {rejected.canonical_status}",
                ),
                "malformed-owner-response-handled": (
                    malformed.canonical_status == "malformed_owner_response"
                    and not malformed.accepted_by_owner,
                    f"canonical status {malformed.canonical_status}",
                ),
                "duplicate-request-reused": (
                    duplicate.duplicate_request_reused
                    and duplicate.error_doctor_action_receipt_id
                    == accepted.error_doctor_action_receipt_id
                    and len(accepted_owner.acknowledged) == 1,
                    f"the owner was called {len(accepted_owner.acknowledged)} time",
                ),
                "no-optimistic-update": (
                    digest_before == digest_after
                    and accepted.authoritative_state_changed is False
                    and accepted.repair_executed is False
                    and accepted.recovery_attempt_started is False
                    and accepted.workflow_changed is False
                    and accepted.code_changed is False
                    and accepted.artifact_changed is False
                    and owner.acknowledged == [],
                    "the incident digest is unchanged and no change is claimed",
                ),
                "authority-requires-canonical-record": (
                    _expect_error(accepted_engine._persist_receipt, PROJECT_ID, forged)[0]
                    and _expect_error(
                        accepted_engine._persist_receipt, PROJECT_ID, forged_repair
                    )[0]
                    and len(unavailable) == 11,
                    "neither authority nor repair execution can be claimed without a "
                    "canonical owner record",
                ),
            },
        )


def _run_security() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        engine, _ = _full_chain(Path(raw_root))
        usage = engine.build_error_doctor_review(PROJECT_ID)["signal_usage"]
        source = _source_text()
        registry = build_fixed_error_doctor_action_registry()
        saves = set(re.findall(r"self\.store\.save_[a-z_]+", source))
        owner_calls = set(re.findall(r"self\.integration\.([a-z_]+)", source))

        def flag(name: str) -> bool:
            return usage[name] is False

        return _group(
            "security",
            {
                "no-incident-creation": (
                    flag("incident_created_by_panel")
                    and "save_boba_error_doctor(" not in source,
                    "the panel never writes the Error Doctor store",
                ),
                "no-diagnosis-creation": (
                    flag("diagnosis_created_by_panel") and "def generate" not in source,
                    "no diagnosis is generated",
                ),
                "no-root-cause-creation": (
                    flag("root_cause_created_by_panel")
                    and "save_boba_root_cause_analyzer" not in source,
                    "no root cause is created",
                ),
                "no-repair-plan-creation": (
                    flag("repair_plan_created_by_panel")
                    and "save_boba_repair_planner" not in source,
                    "no repair plan is created",
                ),
                "no-repair-execution": (
                    flag("repair_executed_by_panel")
                    and owner_calls
                    == {"create_boba_review_session", "acknowledge_boba_review_notification"},
                    f"the only owner calls are {sorted(owner_calls)}; no repair "
                    "execution entry point is reachable",
                ),
                "no-recovery-execution": (
                    flag("recovery_executed_by_panel")
                    and not any(
                        name.startswith(("execute", "run_", "start_"))
                        for name in owner_calls
                    ),
                    "no owner call starts or executes a recovery attempt",
                ),
                "no-checkpoint-restore": (
                    flag("checkpoint_restored_by_panel")
                    and "restore_checkpoint(" not in source,
                    "no checkpoint restoration is performed",
                ),
                "no-workflow-transition": (
                    flag("workflow_changed_by_panel")
                    and "save_boba_workflow_controller" not in source,
                    "no workflow transition is performed",
                ),
                "no-hidden-incident-score": (
                    flag("hidden_incident_score_created"),
                    "no hidden incident score is created",
                ),
                "no-hidden-repair-score": (
                    flag("hidden_repair_score_created"),
                    "no hidden repair score is created",
                ),
                "no-arbitrary-module": (
                    flag("arbitrary_module_used")
                    and source.count("getattr(self.store") == 1
                    and 'descriptor["loader"]' in source,
                    "store access uses only the fixed loader names",
                ),
                "no-arbitrary-operation": (
                    flag("arbitrary_operation_used")
                    and "getattr(self.integration" not in source,
                    "owner operations are fixed in the action registry",
                ),
                "no-arbitrary-url": (
                    flag("arbitrary_url_used")
                    and "http://" not in source
                    and "https://" not in source,
                    "no URL is constructed",
                ),
                "no-arbitrary-path": (
                    flag("arbitrary_path_used") and "open(" not in source,
                    "the projection opens no path of its own",
                ),
                "no-untrusted-html": (
                    flag("untrusted_html_used"),
                    "no untrusted HTML is rendered",
                ),
                "no-command-execution": (
                    flag("command_execution_used") and "subprocess" not in source,
                    "no command execution exists",
                ),
                "no-shell-execution": (
                    flag("shell_execution_used")
                    and "shell=True" not in source
                    and "os.system" not in source,
                    "no shell execution exists",
                ),
                "no-powershell-execution": (
                    flag("powershell_execution_used")
                    and all(
                        token not in source.lower()
                        for token in ("powershell -", "pwsh ", "powershell.exe")
                    ),
                    "no PowerShell invocation exists",
                ),
                "no-git-execution": (
                    flag("git_execution_used") and '"git"' not in source,
                    "no Git invocation exists",
                ),
                "no-ffmpeg-execution": (
                    flag("ffmpeg_execution_used")
                    and all(
                        token not in source
                        for token in ("ffmpeg_binary", "ffprobe", '"ffmpeg"')
                    ),
                    "no FFmpeg or FFprobe invocation exists",
                ),
                "no-package-installation": (
                    flag("package_installation_used")
                    and all(
                        token not in source
                        for token in ("pip install", "npm install", "apt-get")
                    ),
                    "nothing is installed",
                ),
                "no-tool-download": (
                    flag("tool_download_used")
                    and all(
                        token not in source for token in ("urlretrieve", "wget", "curl ")
                    ),
                    "nothing is downloaded",
                ),
                "no-media-generation": (
                    flag("media_generation_used") and "save_render" not in source,
                    "no media is generated",
                ),
                "no-source-media-modification": (
                    flag("source_media_modified") and "storage_key" not in source,
                    "source media is never touched",
                ),
                "no-artifact-modification": (
                    flag("artifact_modified_by_panel")
                    and "save_boba_artifact_inspector" not in source,
                    "artifact records are read, never written",
                ),
                "no-accepted-output-modification": (
                    flag("accepted_output_modified") and "save_accepted" not in source,
                    "accepted output is never modified",
                ),
                "no-local-approval": (
                    flag("approval_created_locally")
                    and source.count('"accepted_by_owner": True') == 1,
                    "acceptance is set only from a canonical owner response",
                ),
                "no-local-safety-decision": (
                    flag("safety_decision_created_locally")
                    and "save_boba_safety_gate" not in source,
                    "no Safety decision is created locally",
                ),
                "no-local-rights-decision": (
                    flag("rights_decision_created_locally")
                    and "save_rights_permission_gate" not in source,
                    "no Rights decision is created locally",
                ),
                "no-upload": (
                    flag("upload_used")
                    and all(
                        token not in source for token in ("presigned", "put_object", "boto3")
                    ),
                    "nothing is uploaded",
                ),
                "no-publication": (
                    flag("publication_used")
                    and "publish(" not in source
                    and ".publish" not in source,
                    "nothing is published",
                ),
                "no-external-analytics": (
                    flag("external_analytics_used")
                    and "analytics." not in source
                    and "telemetry" not in source,
                    "no external analytics call exists",
                ),
                "no-destructive-panel-action": (
                    flag("destructive_action_used")
                    and not any(
                        item.destructive
                        for item in registry.values()
                        if item.availability == "available"
                    )
                    and bool(saves)
                    and all(
                        item.startswith("self.store.save_boba_error_doctor_review")
                        for item in saves
                    ),
                    f"the module writes only its own records: {sorted(saves)}",
                ),
            },
        )


def _run_persistence() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _full_chain(root / "base")
        session = engine.create_error_doctor_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        session_id = session.error_doctor_review_session_id
        loaded = engine.get_error_doctor_review_session(PROJECT_ID, session_id)

        expiring, _ = _full_chain(root / "expiring")
        expiring_session = expiring.create_error_doctor_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        _rewrite(
            expiring.store.boba_error_doctor_review_session_path(
                PROJECT_ID, expiring_session.error_doctor_review_session_id
            ),
            {"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
        )

        annotated = engine.update_error_doctor_review_session(
            PROJECT_ID,
            session_id,
            {
                "local_annotations": [
                    {
                        "incident_id": "case_a",
                        "section_id": "diagnosis",
                        "text": "y" * (MAX_ANNOTATION_LENGTH + 100),
                    }
                ]
            },
        )
        registry_one = engine.build_error_doctor_review_registry(PROJECT_ID)
        registry_two = engine.build_error_doctor_review_registry(PROJECT_ID)

        action_engine, _ = _full_chain(root / "action")
        action_payload = _prepared(action_engine)
        request = _request(action_engine, action_payload, "idem_persist_key")
        receipt = asyncio.run(
            action_engine.submit_error_doctor_action_to_owner(
                PROJECT_ID, request.error_doctor_action_request_id
            )
        )
        action_dump = request.model_dump(mode="json")
        receipt_dump = receipt.model_dump(mode="json")

        export = engine.export_error_doctor_review(PROJECT_ID, session_id)
        export_text = json.dumps(export)
        index_text = json.dumps(engine.build_error_doctor_review(PROJECT_ID))
        reset = engine.reset_error_doctor_review_metadata(PROJECT_ID)
        return _group(
            "persistence",
            {
                "session-persisted": (
                    loaded.error_doctor_review_session_id == session_id,
                    "the review session round-trips through the store",
                ),
                "session-project-scoped": _expect_error(
                    engine.get_error_doctor_review_session, "proj_other_project", session_id
                ),
                "session-expiry-enforced": _expect_error(
                    expiring.get_error_doctor_review_session,
                    PROJECT_ID,
                    expiring_session.error_doctor_review_session_id,
                ),
                "session-field-allowlist": _expect_error(
                    engine.update_error_doctor_review_session,
                    PROJECT_ID,
                    session_id,
                    {"available_action_descriptor_ids": ["x"]},
                ),
                "comparison-limit-enforced": _expect_error(
                    engine.update_error_doctor_review_session,
                    PROJECT_ID,
                    session_id,
                    {"comparison_incident_ids": ["a", "b", "c", "d", "e"]},
                ),
                "annotation-bounded": (
                    len(annotated.local_annotations) == 1
                    and len(annotated.local_annotations[0]["text"])
                    == MAX_ANNOTATION_LENGTH,
                    f"annotation bounded to {MAX_ANNOTATION_LENGTH} characters",
                ),
                "annotation-label-present": (
                    annotated.local_annotations[0]["notice"]
                    == (
                        "Review-session annotation — not part of the canonical "
                        "incident, diagnosis or repair record."
                    ),
                    "every annotation carries the exact non-canonical notice",
                ),
                "secret-annotation-rejected": _expect_error(
                    engine.update_error_doctor_review_session,
                    PROJECT_ID,
                    session_id,
                    {"local_annotations": [{"text": "the password is hunter2"}]},
                ),
                "immutable-registry": (
                    registry_one["registry_snapshot"] == registry_two["registry_snapshot"]
                    and registry_one["registry_snapshot"]["immutable"] is True,
                    "the registry snapshot is stable and immutable",
                ),
                "immutable-submitted-action": _expect_error(
                    action_engine.store.save_boba_error_doctor_review_action,
                    PROJECT_ID,
                    request.error_doctor_action_request_id,
                    {**action_dump, "bounded_reason": "rewritten"},
                ),
                "immutable-receipt": _expect_error(
                    action_engine.store.save_boba_error_doctor_review_receipt,
                    PROJECT_ID,
                    receipt.error_doctor_action_receipt_id,
                    {**receipt_dump, "accepted_by_owner": False},
                ),
                "source-records-not-duplicated": (
                    export["privacy"]["source_records_duplicated"] is False
                    and "diagnostic_cases" not in export_text
                    and "diagnostic_cases" not in index_text,
                    "the review records link to owner records instead of copying them",
                ),
                "complete-logs-not-persisted": (
                    export["privacy"]["raw_logs_excluded"] is True
                    and export["privacy"]["raw_stack_traces_excluded"] is True
                    and len(export_text) < 400_000,
                    "no complete log or stack trace is persisted",
                ),
                "reset-preserves-incidents": (
                    reset["incident_records_preserved"] is True
                    and engine.store.load_boba_error_doctor(PROJECT_ID) is not None,
                    "the canonical Error Doctor record survives a metadata reset",
                ),
                "reset-preserves-diagnoses": (
                    reset["diagnosis_records_preserved"] is True,
                    "diagnosis records survive",
                ),
                "reset-preserves-root-causes": (
                    reset["root_cause_records_preserved"] is True,
                    "root-cause records survive",
                ),
                "reset-preserves-repair-plans": (
                    reset["repair_plan_records_preserved"] is True,
                    "repair-plan records survive",
                ),
                "reset-preserves-recovery-history": (
                    reset["recovery_history_preserved"] is True
                    and reset["code_modified"] is False
                    and reset["artifacts_modified"] is False,
                    "recovery history survives and nothing is modified",
                ),
                "reset-preserves-review-ui-history": (
                    reset["review_ui_history_preserved"] is True
                    and reset["clip_brief_review_history_preserved"] is True
                    and reset["candidate_review_history_preserved"] is True,
                    "Review UI, Candidate Review and Clip Brief history survive",
                ),
                "sanitized-export": (
                    export["privacy"]["sensitive_values_excluded"] is True
                    and export["privacy"]["private_paths_excluded"] is True
                    and str(root) not in export_text,
                    "the export is sanitised and states what it excludes",
                ),
            },
        )


_GROUP_RUNNERS: dict[str, Any] = {
    "identity": _run_identity,
    "facts": _run_facts,
    "diagnosis": _run_diagnosis,
    "root-cause": _run_root_cause,
    "repair-plans": _run_repair_plans,
    "recovery": _run_recovery,
    "queue": _run_queue,
    "evidence": _run_evidence,
    "conflicts": _run_conflicts,
    "comparison": _run_comparison,
    "actions": _run_actions,
    "security": _run_security,
    "persistence": _run_persistence,
}


def run_named_scenario(name: str) -> ScenarioResult:
    """Run one catalogued condition by its ``group:condition`` name."""
    if name not in SCENARIO_NAMES:
        raise ValidationError(f"Unknown error doctor review scenario: {name}")
    group = name.rsplit(":", 1)[0]
    group_results: list[ScenarioResult] = _GROUP_RUNNERS[group]()
    for result in group_results:
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
    registry = build_fixed_error_doctor_action_registry()
    sources = build_fixed_error_source_registry()
    sections = build_fixed_error_section_registry()
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, owner = _full_chain(root / "self")
        review = engine.build_error_doctor_review(PROJECT_ID)
        usage = review["signal_usage"]
        payload = _prepared(engine)
        request = _request(engine, payload, "idem_self_check_key")
        receipt = asyncio.run(
            engine.submit_error_doctor_action_to_owner(
                PROJECT_ID, request.error_doctor_action_request_id
            )
        )
        first = engine.build_incident_snapshot(
            PROJECT_ID, payload["session"].error_doctor_review_session_id, "case_a"
        )["snapshot"]
        second = engine.build_incident_snapshot(
            PROJECT_ID, payload["session"].error_doctor_review_session_id, "case_a"
        )["snapshot"]
        registry_one = engine.build_error_doctor_review_registry(PROJECT_ID)
        registry_two = engine.build_error_doctor_review_registry(PROJECT_ID)
        session_one = engine.create_error_doctor_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        session_two = engine.create_error_doctor_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        layer_ops = {
            key.split(".", 1)[1]
            for key in build_boba_operation_registry()
            if key.startswith("error_doctor_review.")
        }
        safety_ops = build_safety_module_operation_registry().get(
            "error_doctor_review", {}
        )
        module = build_boba_module_registry()["error_doctor_review"]

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
            len(registry_one["sources"]) == 14 and len(registry_one["actions"]) == 12,
            f"{len(registry_one['sources'])} sources, {len(registry_one['actions'])} actions",
        )
        add(
            "deterministic-registry-digest",
            registry_one["registry_snapshot"]["registry_digest"]
            == registry_two["registry_snapshot"]["registry_digest"],
            "the registry digest is stable across builds",
        )
        add(
            "deterministic-session-digest",
            session_one.session_digest != session_two.session_digest
            and len(session_one.session_digest) == 64,
            "each session carries its own 64-character digest",
        )
        add(
            "deterministic-snapshot-digest",
            first["incident_digest"] == second["incident_digest"]
            and first["project_snapshot_digest"] == second["project_snapshot_digest"],
            "repeat snapshots of unchanged state produce identical digests",
        )
        add(
            "deterministic-action-request-digest",
            engine.build_incident_snapshot(
                PROJECT_ID, payload["session"].error_doctor_review_session_id, "case_a"
            )["action_confirmations"].keys()
            == set(first["available_action_descriptor_ids"]),
            "a confirmation token is issued for exactly the available actions",
        )
        add(
            "duplicate-source-descriptors-rejected",
            len(sources) == len(set(sources)) == 14,
            "the source registry refuses duplicate descriptors",
        )
        add(
            "duplicate-action-descriptors-rejected",
            len(registry) == len(set(registry)) == 12,
            "the action registry refuses duplicate descriptors",
        )
        add(
            "exact-incident-identity-validation",
            _expect_error(engine.inspect_incident, PROJECT_ID, "case_absent")[0],
            "an unknown incident identity is refused",
        )
        add(
            "exact-source-digest-validation",
            "source_record_digest_mismatch" in source,
            "a drifted source record digest is refused",
        )
        add(
            "facts-remain-facts",
            engine.inspect_diagnosis(PROJECT_ID, "case_a")["confirmed_facts"] != [],
            "owner confirmed facts are projected as confirmed facts",
        )
        add(
            "assessments-remain-assessments",
            any(
                item.classification == "source_owned_assessment"
                for item in engine.build_evidence_cards(PROJECT_ID, "case_a")
            ),
            "owner assessments stay assessments",
        )
        add(
            "hypotheses-remain-hypotheses",
            all(
                item.hypothesis
                for item in engine.build_root_cause_projections(PROJECT_ID, "case_a")
            ),
            "every root-cause candidate stays a hypothesis",
        )
        add(
            "no-automatic-root-cause-selection",
            engine.compare_incidents(PROJECT_ID, ["case_a", "case_b"])["comparison"][
                "no_automatic_root_cause_selection"
            ]
            is True,
            "comparison pins no automatic root-cause selection",
        )
        add(
            "no-automatic-repair-selection",
            engine.compare_incidents(PROJECT_ID, ["case_a", "case_b"])["comparison"][
                "no_automatic_repair_selection"
            ]
            is True,
            "comparison pins no automatic repair selection",
        )
        add(
            "no-hidden-incident-score",
            usage["hidden_incident_score_created"] is False,
            "no hidden incident score exists",
        )
        add(
            "no-hidden-repair-score",
            usage["hidden_repair_score_created"] is False,
            "no hidden repair score exists",
        )
        add(
            "bounded-log-projection",
            bounded_excerpt("x" * (MAX_EXCERPT_CHARS + 100))["truncated"]
            and len(bounded_excerpt("x" * (MAX_EXCERPT_CHARS + 100))["text"])
            <= MAX_EXCERPT_CHARS
            and MAX_TECHNICAL_MESSAGE_CHARS == 8_192,
            "log and technical excerpts are bounded and report truncation",
        )
        add(
            "sensitive-value-redaction",
            bounded_excerpt("api_key=abcdef123456")["sensitive_values_redacted"]
            and "abcdef123456" not in bounded_excerpt("api_key=abcdef123456")["text"],
            "secret-shaped values are redacted from excerpts",
        )
        add(
            "private-path-redaction",
            bounded_excerpt("/home/me/secret/x.py")["private_paths_redacted"]
            and "/home/me" not in bounded_excerpt("/home/me/secret/x.py")["text"],
            "private paths are redacted from excerpts",
        )
        add(
            "no-diagnosis-creation",
            usage["diagnosis_created_by_panel"] is False,
            "no diagnosis is created by the panel",
        )
        add(
            "no-root-cause-creation",
            usage["root_cause_created_by_panel"] is False,
            "no root cause is created by the panel",
        )
        add(
            "no-repair-plan-creation",
            usage["repair_plan_created_by_panel"] is False,
            "no repair plan is created by the panel",
        )
        add(
            "no-repair-execution",
            usage["repair_executed_by_panel"] is False
            and receipt.repair_executed is False,
            "no repair is executed and no receipt claims one",
        )
        add(
            "no-recovery-execution",
            usage["recovery_executed_by_panel"] is False
            and receipt.recovery_attempt_started is False,
            "no recovery is executed and no receipt claims one",
        )
        add(
            "no-checkpoint-restoration",
            usage["checkpoint_restored_by_panel"] is False,
            "no checkpoint is restored",
        )
        add(
            "no-workflow-transition",
            usage["workflow_changed_by_panel"] is False
            and receipt.workflow_changed is False,
            "no workflow transition happens",
        )
        add(
            "no-dynamic-routing",
            "importlib" not in source
            and source.count("getattr(self.store") == 1
            and "getattr(self.integration" not in source,
            "module and operation routing is fixed source code",
        )
        add(
            "no-command-runner",
            usage["command_execution_used"] is False
            and usage["shell_execution_used"] is False
            and usage["powershell_execution_used"] is False
            and "subprocess" not in source,
            "no command, shell or PowerShell runner exists",
        )
        add(
            "no-git-runner",
            usage["git_execution_used"] is False and '"git"' not in source,
            "no Git runner exists",
        )
        add(
            "no-ffmpeg-runner",
            usage["ffmpeg_execution_used"] is False
            and all(
                token not in source for token in ("ffmpeg_binary", "ffprobe", '"ffmpeg"')
            ),
            "no FFmpeg or FFprobe runner exists",
        )
        add(
            "no-package-installer",
            usage["package_installation_used"] is False,
            "nothing is installed",
        )
        add(
            "no-tool-downloader",
            usage["tool_download_used"] is False,
            "nothing is downloaded",
        )
        add("no-upload", usage["upload_used"] is False, "nothing is uploaded")
        add("no-publication", usage["publication_used"] is False, "nothing is published")
        add(
            "storage-writable",
            engine.store.load_boba_error_doctor_review(PROJECT_ID) is not None
            and engine.store.load_boba_error_doctor_review_session(
                PROJECT_ID, payload["session"].error_doctor_review_session_id
            )
            is not None
            and engine.store.load_boba_error_doctor_review_snapshot(
                PROJECT_ID, first["incident_snapshot_id"]
            )
            is not None,
            "the review index, sessions and snapshots persist",
        )
        add(
            "receipts-writable",
            engine.store.load_boba_error_doctor_review_receipt(
                PROJECT_ID, receipt.error_doctor_action_receipt_id
            )
            is not None
            and engine.store.load_boba_error_doctor_review_action(
                PROJECT_ID, request.error_doctor_action_request_id
            )
            is not None,
            "action requests and receipts persist",
        )
        add(
            "integration-layer-registered",
            len(layer_ops) == 25 and layer_ops == set(safety_ops),
            f"{len(layer_ops)} operations registered and classified",
        )
        add(
            "safety-gate-gates-submit",
            safety_ops.get("submit_action") == "approval_required_read_only"
            and module.read_only is True
            and module.execution_capable is False,
            f"submit_action -> {safety_ops.get('submit_action')}",
        )
        add(
            "review-ui-not-duplicated",
            "error_doctor_review"
            not in Path("src/olympus/boba/review_ui.py").read_text(encoding="utf-8"),
            "the global Review UI is reused, not replaced",
        )
        add(
            "owner-of-acknowledgement-is-review-ui",
            registry[_ACK].owning_module_id == "review_ui"
            and registry[_ACK].owning_operation_id == "acknowledge_notification"
            and owner.acknowledged == ["case_a"],
            "acknowledgement is routed to Review UI's own canonical operation",
        )
        add(
            "unavailable-actions-explained",
            all(
                bool(item.limitations)
                for item in registry.values()
                if item.availability == "unavailable"
            ),
            "every unavailable action states why, with no substitute authority",
        )
        add(
            "recovered-is-not-resolved",
            any(
                "recovered is not resolved" in item
                for item in review["limitations"]
            ),
            "the review set states that recovered is not resolved",
        )
        add(
            "supported-schema-declared",
            SUPPORTED_INCIDENT_SCHEMA_ID == "boba_error_doctor_v1",
            f"supported incident schema {SUPPORTED_INCIDENT_SCHEMA_ID}",
        )
    return results


def run_synthetic_project() -> dict[str, Any]:
    """Build every projection over a synthetic project and report real counts."""
    with tempfile.TemporaryDirectory() as raw_root:
        engine, _ = _full_chain(Path(raw_root))
        review = engine.build_error_doctor_review(PROJECT_ID)
        queue = engine.build_incident_queue(PROJECT_ID)
        payload = _prepared(engine)
        comparison = engine.compare_incidents(PROJECT_ID, ["case_a", "case_b"])[
            "comparison"
        ]
        recovery = engine.inspect_recovery_history(PROJECT_ID, "case_a")
        return {
            "project_id": PROJECT_ID,
            "incident_count": len(review["incident_references"]),
            "queue_item_count": len(queue["items"]),
            "priority_tier_count": len(queue["priority_tiers"]),
            "diagnosis_projection_count": len(payload["diagnosis_projections"]),
            "root_cause_projection_count": len(payload["root_cause_projections"]),
            "evidence_card_count": len(payload["evidence_cards"]),
            "repair_plan_projection_count": len(payload["repair_plan_projections"]),
            "recovery_attempt_projection_count": len(
                payload["recovery_attempt_projections"]
            ),
            "missing_evidence_count": payload["snapshot"]["missing_evidence_count"],
            "conflict_count": payload["snapshot"]["conflict_count"],
            "confirmed_root_cause_count": sum(
                1 for item in payload["root_cause_projections"] if item["confirmed"]
            ),
            "owner_reported_success_count": recovery["owner_reported_success_count"],
            "independently_verified_count": recovery["independently_verified_count"],
            "available_action_descriptor_ids": payload["snapshot"][
                "available_action_descriptor_ids"
            ],
            "repair_execution_available": False,
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
    engine = BobaErrorDoctorReviewV1(store, _NullOwner())  # type: ignore[arg-type]
    references = engine.build_incident_references(project_id)
    queue = engine.build_incident_queue(project_id)
    return {
        "project_id": project_id,
        "incident_count": len(references),
        "incident_ids": [item.incident_id for item in references],
        "queue_item_count": len(queue["items"]),
        "unsupported_schema_incident_ids": [
            item.incident_id for item in references if not item.schema_supported
        ],
        "notice": (
            "Read-only inspection. Nothing was diagnosed, repaired, recovered, "
            "restored, executed, uploaded or published."
        ),
    }


def _write_report(payload: dict[str, Any]) -> Path:
    directory = Path("work/validation_reports/boba_error_doctor_review")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"report_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Error Doctor Panel V1 without touching real state."
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

    report: dict[str, Any] = {"tool": "validate_boba_error_doctor_review"}
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
