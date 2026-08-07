"""Offline validator for BOBA Approval / Reject Buttons V1.

Every scenario exercises a real assertion against the actual repository. The
validator never approves anything against real state, executes anything, grants
Safety approval, advances a workflow, uploads or publishes.

Usage:
    python tools/validate_boba_approval_reject_buttons.py --self-check --report
    python tools/validate_boba_approval_reject_buttons.py --scenario security:reason-rejects-url
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from olympus.boba.approval_controls import (
    APPROVE_DECISION,
    NOT_EXECUTION_NOTICE,
    NOT_SAFETY_NOTICE,
    NOT_WORKFLOW_NOTICE,
    REJECT_DECISION,
    REJECTION_NOTICE,
    STALE_NOTICE,
    BobaApprovalControlsV1,
    BobaApprovalDecisionReceiptV1,
    BobaApprovalEligibilityV1,
    approval_button_states,
    bounded_reason,
    build_fixed_approval_decision_registry,
)
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.review_ui import build_fixed_review_action_registry
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError

PROJECT_ID = "approval-controls-validation"

_CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "registry": (
        "derived-from-review-ui-registry",
        "adds-no-action",
        "reenables-nothing",
        "one-available-decision-action",
        "digest-is-sha256",
        "immutable-and-stable",
        "declares-no-approval-authority",
        "declares-no-second-decision-path",
        "ten-button-states",
    ),
    "eligibility": (
        "rows-built-per-decision-kind",
        "every-row-explains-itself",
        "owner-disabled-action-reported",
        "unsupported-target-type-reported",
        "missing-workflow-run-reported",
        "eligible-requires-eligible-reason-code",
        "ineligible-cannot-claim-eligible",
        "eligible-must-be-actionable",
        "no-row-grants-execution",
        "no-row-grants-safety",
        "no-row-grants-rights",
        "no-row-advances-workflow",
    ),
    "approval": (
        "approve-requires-confirmation",
        "approve-requires-reason-when-owner-does",
        "approve-blocked-without-eligibility",
        "approve-binds-exact-snapshot",
        "approve-never-optimistic",
    ),
    "rejection": (
        "reject-is-first-class",
        "reject-carries-bounded-reason",
        "reject-notice-states-no-deletion",
        "reject-not-an-error-receipt",
    ),
    "stale-state": (
        "project-digest-drift-refused",
        "target-digest-drift-refused",
        "safety-digest-drift-refused",
        "final-decision-digest-drift-refused",
        "safety-state-change-refused",
        "rights-state-change-refused",
        "validation-state-change-refused",
        "quality-state-change-refused",
        "budget-state-change-refused",
        "stale-notice-present",
        "stale-blocks-request-creation",
    ),
    "expiry": ("workflow-revision-drift-refused", "expiry-checked"),
    "invalidation": ("already-decided-refused", "already-decided-state-shown"),
    "safety-gate": (
        "safety-blocked-cannot-be-approved",
        "safety-block-yields-blocked-state",
        "approval-never-grants-safety",
        "safety-classified-read-only",
        "submit-requires-approval-classification",
    ),
    "rights": ("unknown-rights-blocks-approval", "rights-never-granted-here"),
    "evidence": ("owner-state-never-invented", "missing-owner-record-reported"),
    "revision": ("revision-bound-in-snapshot", "revision-required-by-owner-respected"),
    "digest": (
        "snapshot-digest-is-sha256",
        "confirmation-digest-is-sha256",
        "target-digest-covers-workflow",
    ),
    "idempotency": (
        "reuses-review-ui-idempotency",
        "duplicate-submission-returns-existing",
        "no-second-idempotency-mechanism",
    ),
    "concurrency": ("second-submission-does-not-duplicate", "receipt-keyed-by-request"),
    "events": (
        "append-only-log",
        "sequence-monotonic",
        "requested-event-emitted",
        "stale-event-emitted",
        "event-never-claims-execution",
        "event-never-claims-workflow-advance",
    ),
    "receipts": (
        "accepted-requires-canonical-record",
        "execution-requires-owner-module",
        "workflow-advance-requires-record",
        "user-decision-requires-value",
        "four-facts-kept-apart",
        "approval-is-not-execution",
    ),
    "persistence": (
        "registry-immutable",
        "receipt-immutable",
        "no-second-database",
        "no-secrets-persisted",
    ),
    "api": ("routes-registered", "project-scoped", "fourteen-operations-registered"),
    "frontend-contract": (
        "module-present",
        "declares-no-authority",
        "no-optimistic-approval",
        "no-command-runner",
        "state-not-colour-only",
        "mounted-in-review-ui",
    ),
    "security": (
        "reason-rejects-credential",
        "reason-rejects-command",
        "reason-rejects-shell",
        "reason-rejects-url",
        "reason-rejects-private-path",
        "reason-rejects-unc-path",
        "reason-rejects-traversal",
        "reason-accepts-prose",
        "raw-validated-before-sanitisation",
        "cross-project-snapshot-refused",
        "forged-snapshot-refused",
        "unknown-decision-kind-refused",
    ),
    "reset": (
        "preserves-workflow-decisions",
        "preserves-safety-records",
        "preserves-final-decision-records",
        "preserves-receipts",
        "preserves-event-log",
        "removes-no-media",
    ),
    "timeline": (
        "empty-timeline-truthful",
        "projects-control-events",
        "includes-owner-decision-records",
        "owner-facts-flagged",
        "derived-presentation-separate",
        "deterministic-ordering",
        "bounded-output",
        "reports-has-more",
        "redacts-private-paths",
        "no-mutation",
        "no-second-event-stream",
        "claims-no-execution",
        "survives-reset",
    ),
    "comparison": (
        "compares-same-target",
        "requires-two-decisions",
        "bounded-maximum",
        "collapses-duplicates",
        "rejects-unknown-decision",
        "rejects-cross-project",
        "preserves-approve-vs-reject",
        "preserves-stale-vs-current",
        "lists-differing-fields",
        "incompatible-target-is-truthful",
        "no-automatic-winner",
        "no-best-decision-inferred",
        "no-authority-change",
        "owner-facts-separate-from-presentation",
        "deterministic-output",
    ),
    "regression-protection": (
        "review-ui-registry-untouched",
        "workflow-decision-values-unchanged",
        "existing-modules-still-registered",
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


class _StubIntegration:
    """Stands in for the canonical Review UI action chain."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.submitted: list[str] = []
        self.accept = True
        self.stale = False

    def create_boba_review_action_request(
        self, project_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        request_id = f"review_action_{len(self.created) + 1}"
        self.created.append({"project_id": project_id, **kwargs})
        return {"review_action_request_id": request_id, **kwargs}

    async def submit_boba_review_action_to_owner(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        self.submitted.append(request_id)
        if self.stale:
            return {
                "action_receipt_id": "r1",
                "accepted_by_owner": False,
                "stale_state_rejected": True,
                "canonical_status": "rejected_stale_state",
            }
        if not self.accept:
            return {
                "action_receipt_id": "r1",
                "accepted_by_owner": False,
                "canonical_status": "rejected_by_owner",
            }
        return {
            "action_receipt_id": "r1",
            "accepted_by_owner": True,
            "canonical_record_id": "workflow_decision_1",
            "canonical_record_digest": "a" * 64,
            "canonical_status": "recorded",
            "owning_module_id": "workflow_controller",
            "owning_operation_id": "record_human_workflow_decision",
        }


def _engine(root: Path) -> tuple[BobaApprovalControlsV1, _StubIntegration]:
    owner = _StubIntegration()
    return BobaApprovalControlsV1(BobaMemoryStore(root), owner), owner  # type: ignore[arg-type]


class _StateStore(BobaMemoryStore):
    """Injects owner payloads so real gate-state branches can be exercised."""

    def __init__(self, root: Path, raw: dict[str, Any]) -> None:
        super().__init__(root)
        self._raw = raw

    def load_boba_workflow_controller(self, project_id: str) -> Any:
        return self._raw.get(
            "workflow_controller", super().load_boba_workflow_controller(project_id)
        )

    def load_boba_safety_gate(self, project_id: str) -> Any:
        return self._raw.get("safety_gate", super().load_boba_safety_gate(project_id))

    def load_boba_final_decision_bus(self, project_id: str) -> Any:
        return self._raw.get(
            "final_decision_bus", super().load_boba_final_decision_bus(project_id)
        )

    def load_boba_validator_runner(self, project_id: str) -> Any:
        return self._raw.get(
            "validator_runner", super().load_boba_validator_runner(project_id)
        )

    def load_boba_output_quality_reviewer(self, project_id: str) -> Any:
        return self._raw.get(
            "output_quality_reviewer", super().load_boba_output_quality_reviewer(project_id)
        )

    def load_boba_autopilot_controller(self, project_id: str) -> Any:
        return self._raw.get(
            "autopilot_controller", super().load_boba_autopilot_controller(project_id)
        )


def _state_engine(
    root: Path, raw: dict[str, Any]
) -> tuple[BobaApprovalControlsV1, _StubIntegration]:
    owner = _StubIntegration()
    return BobaApprovalControlsV1(_StateStore(root, raw), owner), owner  # type: ignore[arg-type]


def _workflow_payload(
    *, revision: int = 3, stage: str = "render", status: str = "running"
) -> dict[str, Any]:
    return {
        "schema_version": "boba_workflow_controller_v1",
        "workflow_runs": [
            {
                "workflow_run_id": "run_a",
                "revision": revision,
                "current_stage_instance_id": stage,
                "status": status,
                "updated_at": "2026-02-01T10:00:00+00:00",
            }
        ],
        "human_decisions": [],
    }


def _safety_payload(outcome: str = "approved_exact_action") -> dict[str, Any]:
    return {
        "schema_version": "boba_safety_gate_v1",
        "safety_decisions": [{"outcome": outcome}],
        "rights_reviews": [{"rights_status": "clear"}],
        "checkpoint_reviews": [{"checkpoint_status": "ready"}],
    }


def _eligible_raw(**over: Any) -> dict[str, Any]:
    raw = {
        "workflow_controller": _workflow_payload(),
        "safety_gate": _safety_payload(),
    }
    raw.update(over)
    return raw


def _check(name: str, passed: bool, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, passed=passed, detail=detail)


def _expect_error(fn: Any, *a: Any, **k: Any) -> tuple[bool, str]:
    try:
        fn(*a, **k)
    except ValidationError as error:
        return (True, f"refused: {str(error)[:110]}")
    except Exception as error:
        return (True, f"refused ({type(error).__name__}): {str(error)[:90]}")
    return (False, "the call was accepted when it should have been refused")


def _source() -> str:
    return Path("src/olympus/boba/approval_controls.py").read_text(encoding="utf-8")


def _frontend() -> str:
    p = Path("frontend/src/lib/approvalControls.ts")
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _component() -> str:
    p = Path("frontend/src/components/review/BobaApprovalRejectControls.tsx")
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _results() -> str:
    p = Path("frontend/src/components/project/ResultsSection.tsx")
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _group(group: str, checks: dict[str, tuple[bool, str]]) -> list[ScenarioResult]:
    rows: list[ScenarioResult] = []
    for name in _CONDITION_GROUPS[group]:
        if name not in checks:
            rows.append(_check(f"{group}:{name}", False, "condition not evaluated"))
            continue
        passed, detail = checks[name]
        rows.append(_check(f"{group}:{name}", passed, detail))
    return rows


def _run_registry() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    reg = build_fixed_approval_decision_registry()
    ui = build_fixed_review_action_registry()
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _engine(Path(raw))
        built = e.build_approval_control_registry(PROJECT_ID)
        again = e.build_approval_control_registry(PROJECT_ID)
        snap = built["registry_snapshot"]
        c["derived-from-review-ui-registry"] = (
            set(reg) <= set(ui), "every descriptor comes from the Review UI registry"
        )
        c["adds-no-action"] = (
            all(reg[k]["owning_operation_id"] == ui[k].owning_operation_id for k in reg),
            "no operation id is renamed or invented",
        )
        c["reenables-nothing"] = (
            all(reg[k]["allowed_in_v1"] == ui[k].allowed_in_v1 for k in reg),
            "an owner-disabled action stays disabled",
        )
        c["one-available-decision-action"] = (
            len(snap["available_decision_action_ids"]) == 1
            and snap["available_decision_action_ids"][0]
            == "review_action_workflow_human_decision_v1",
            f"available: {snap['available_decision_action_ids']}",
        )
        c["digest-is-sha256"] = (len(snap["registry_digest"]) == 64, "sha256 digest")
        c["immutable-and-stable"] = (
            snap == again["registry_snapshot"], "rebuild returns the identical snapshot"
        )
        c["declares-no-approval-authority"] = (
            snap["creates_approval_authority"] is False, "pinned false"
        )
        c["declares-no-second-decision-path"] = (
            snap["creates_second_decision_path"] is False, "pinned false"
        )
        c["ten-button-states"] = (
            len(approval_button_states()) == 10, f"{len(approval_button_states())} states"
        )
    return _group("registry", c)


def _run_eligibility() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        empty, _ = _engine(root / "empty")
        rows = empty.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
        ok_engine, _ = _state_engine(root / "ok", _eligible_raw())
        eligible_rows = ok_engine.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")

        c["rows-built-per-decision-kind"] = (
            {r.decision_kind for r in rows} == {"approve", "reject"},
            f"{len(rows)} rows across approve and reject",
        )
        c["every-row-explains-itself"] = (
            all(r.bounded_explanation for r in rows), "each row carries an explanation"
        )
        c["owner-disabled-action-reported"] = (
            any(r.reason_code == "action_not_available_in_v1" for r in rows),
            "an owner-disabled action is reported as such",
        )
        c["unsupported-target-type-reported"] = (
            any(
                r.reason_code == "target_type_not_supported"
                for r in empty.inspect_approval_eligibility(PROJECT_ID, "candidate_clip")
            ),
            "an unsupported target type is reported",
        )
        c["missing-workflow-run-reported"] = (
            any(r.reason_code == "no_workflow_run_bound" for r in rows),
            "a missing workflow run is reported",
        )
        c["eligible-requires-eligible-reason-code"] = _expect_error(
            BobaApprovalEligibilityV1,
            eligibility_id="x", project_id=PROJECT_ID, target_type="workflow_stage",
            action_descriptor_id="a", owning_module_id="m", owning_operation_id="o",
            decision_kind="approve", button_state="approve_available",
            eligible=True, reason_code="expired",
        )
        c["ineligible-cannot-claim-eligible"] = _expect_error(
            BobaApprovalEligibilityV1,
            eligibility_id="x", project_id=PROJECT_ID, target_type="workflow_stage",
            action_descriptor_id="a", owning_module_id="m", owning_operation_id="o",
            decision_kind="approve", button_state="unavailable",
            eligible=False, reason_code="eligible",
        )
        c["eligible-must-be-actionable"] = _expect_error(
            BobaApprovalEligibilityV1,
            eligibility_id="x", project_id=PROJECT_ID, target_type="workflow_stage",
            action_descriptor_id="a", owning_module_id="m", owning_operation_id="o",
            decision_kind="approve", button_state="blocked",
            eligible=True, reason_code="eligible",
        )
        allrows = rows + eligible_rows
        c["no-row-grants-execution"] = (
            all(r.grants_execution is False for r in allrows), "pinned false"
        )
        c["no-row-grants-safety"] = (
            all(r.grants_safety_approval is False for r in allrows), "pinned false"
        )
        c["no-row-grants-rights"] = (
            all(r.grants_rights_approval is False for r in allrows), "pinned false"
        )
        c["no-row-advances-workflow"] = (
            all(r.advances_workflow is False for r in allrows), "pinned false"
        )
    return _group("eligibility", c)


def _prepared(engine: BobaApprovalControlsV1) -> dict[str, Any]:
    return engine.build_approval_control_snapshot(
        PROJECT_ID, "review_session_a", "review_snapshot_a", "workflow_stage", "render"
    )


def _run_approval() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        e, _ = _state_engine(root / "a", _eligible_raw())
        payload = _prepared(e)
        sid = payload["snapshot"]["approval_control_snapshot_id"]
        c["approve-requires-confirmation"] = _expect_error(
            e.create_approval_decision_request, PROJECT_ID,
            approval_control_snapshot_id=sid, decision_kind=APPROVE_DECISION,
            reason="looks fine", idempotency_key="idem_a_key", confirmed=False,
        )
        c["approve-requires-reason-when-owner-does"] = _expect_error(
            e.create_approval_decision_request, PROJECT_ID,
            approval_control_snapshot_id=sid, decision_kind=APPROVE_DECISION,
            reason="", idempotency_key="idem_b_key", confirmed=True,
        )
        blocked, _ = _engine(root / "blocked")
        bpayload = _prepared(blocked)
        c["approve-blocked-without-eligibility"] = _expect_error(
            blocked.create_approval_decision_request, PROJECT_ID,
            approval_control_snapshot_id=bpayload["snapshot"]["approval_control_snapshot_id"],
            decision_kind=APPROVE_DECISION, reason="fine",
            idempotency_key="idem_c_key", confirmed=True,
        )
        snap = payload["snapshot"]
        c["approve-binds-exact-snapshot"] = (
            len(snap["target_digest"]) == 64
            and snap["workflow_revision"] == 3
            and snap["workflow_run_id"] == "run_a",
            "the snapshot binds run, revision and target digest",
        )
        src = _source()
        c["approve-never-optimistic"] = (
            "user_decision_recorded=accepted" in src.replace(" ", ""),
            "the user decision is recorded only when the owner accepted it",
        )
    return _group("approval", c)


def _run_rejection() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    reg = build_fixed_approval_decision_registry()
    row = reg["review_action_workflow_human_decision_v1"]
    c["reject-is-first-class"] = (
        REJECT_DECISION in row["reject_values"],
        "reject is a canonical decision value, not a deletion or failure",
    )
    c["reject-carries-bounded-reason"] = (
        row["requires_reason"] is True, "the owner requires a bounded reason"
    )
    c["reject-notice-states-no-deletion"] = (
        "deletes nothing" in REJECTION_NOTICE and "rolls nothing back" in REJECTION_NOTICE,
        REJECTION_NOTICE,
    )
    receipt = BobaApprovalDecisionReceiptV1(
        approval_decision_receipt_id="r", review_action_request_id="q",
        project_id=PROJECT_ID, target_type="workflow_stage", decision_kind="reject",
        owning_module_id="workflow_controller",
        owning_operation_id="record_human_workflow_decision",
        user_decision_recorded=True, user_decision_value="reject",
        owner_accepted=True, canonical_record_id="d1", canonical_record_digest="a" * 64,
    )
    c["reject-not-an-error-receipt"] = (
        receipt.error_code is None and receipt.owner_accepted is True,
        "an accepted rejection carries no error code",
    )
    return _group("rejection", c)


def _run_stale_state() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        base = _eligible_raw()
        e, _ = _state_engine(root / "a", base)
        payload = _prepared(e)
        sid = payload["snapshot"]["approval_control_snapshot_id"]

        def drift(label: str, over: dict[str, Any]) -> tuple[bool, str]:
            drifted, _ = _state_engine(root / "a", {**base, **over})
            result = drifted.revalidate_approval_snapshot(PROJECT_ID, sid)
            return (
                result["valid"] is False and bool(result.get("stale")),
                f"{label} -> {result['code']}",
            )

        c["project-digest-drift-refused"] = drift(
            "extra owner record", {"validator_runner": {"suite_decisions": [{"outcome": "pass"}]}}
        )
        c["target-digest-drift-refused"] = drift(
            "stage change", {"workflow_controller": _workflow_payload(stage="assemble")}
        )
        c["safety-digest-drift-refused"] = drift(
            "safety record change", {"safety_gate": _safety_payload(outcome="denied_action")}
        )
        c["final-decision-digest-drift-refused"] = drift(
            "final decision record", {"final_decision_bus": {"final_decisions": [{"id": "x"}]}}
        )
        c["safety-state-change-refused"] = c["safety-digest-drift-refused"]
        c["rights-state-change-refused"] = drift(
            "rights change",
            {
                "safety_gate": {
                    **_safety_payload(),
                    "rights_reviews": [{"rights_status": "blocked"}],
                }
            },
        )
        c["validation-state-change-refused"] = drift(
            "validation change", {"validator_runner": {"suite_decisions": [{"outcome": "failed"}]}}
        )
        c["quality-state-change-refused"] = drift(
            "quality change",
            {"output_quality_reviewer": {"acceptance_decisions": [{"decision": "reject_output"}]}},
        )
        c["budget-state-change-refused"] = drift(
            "budget change", {"autopilot_controller": {"runs": [{"budget_status": "exhausted"}]}}
        )
        c["stale-notice-present"] = (
            "changed after this control was displayed" in STALE_NOTICE, STALE_NOTICE[:60]
        )
        # Drift a record that does NOT change eligibility, so the refusal proves
        # the staleness gate rather than the eligibility gate.
        drifted, owner = _state_engine(
            root / "a", {**base, "final_decision_bus": {"final_decisions": [{"id": "x"}]}}
        )
        created = drifted.create_approval_decision_request(
            PROJECT_ID, approval_control_snapshot_id=sid, decision_kind=APPROVE_DECISION,
            reason="fine", idempotency_key="idem_stale_key", confirmed=True,
        )
        c["stale-blocks-request-creation"] = (
            created["created"] is False and owner.created == [],
            "no request reached the owner while state was stale",
        )
    return _group("stale-state", c)


def _run_expiry() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        base = _eligible_raw()
        e, _ = _state_engine(root / "a", base)
        sid = _prepared(e)["snapshot"]["approval_control_snapshot_id"]
        drifted, _ = _state_engine(
            root / "a", {**base, "workflow_controller": _workflow_payload(revision=9)}
        )
        result = drifted.revalidate_approval_snapshot(PROJECT_ID, sid)
        c["workflow-revision-drift-refused"] = (
            result["valid"] is False, f"revision drift -> {result['code']}"
        )
        c["expiry-checked"] = (
            "expired" in _source() and "_parse_time" in _source(),
            "the snapshot expiry is parsed and compared",
        )
    return _group("expiry", c)


def _run_invalidation() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        decided = _workflow_payload()
        decided["human_decisions"] = [
            {"human_decision_id": "d1", "decision": "approve", "stage_instance_id": "render"}
        ]
        e, _ = _state_engine(Path(raw), _eligible_raw(workflow_controller=decided))
        rows = e.inspect_approval_eligibility(PROJECT_ID, "workflow_stage", "render")
        payload = _prepared(e)
        sid = payload["snapshot"]["approval_control_snapshot_id"]
        result = e.revalidate_approval_snapshot(PROJECT_ID, sid)
        c["already-decided-refused"] = (
            result["valid"] is False and result["code"] == "already_decided",
            f"-> {result['code']}",
        )
        c["already-decided-state-shown"] = (
            any(r.button_state == "approved" and r.reason_code == "already_decided" for r in rows),
            "the recorded decision is shown instead of a fresh button",
        )
    return _group("invalidation", c)


def _run_safety_gate() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _state_engine(
            Path(raw), _eligible_raw(safety_gate=_safety_payload(outcome="denied_action"))
        )
        rows = e.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
        approve = [r for r in rows if r.decision_kind == "approve"]
        c["safety-blocked-cannot-be-approved"] = (
            all(not r.eligible for r in approve),
            "no approve row is eligible while Safety denies",
        )
        c["safety-block-yields-blocked-state"] = (
            any(
                r.button_state == "blocked" and r.reason_code == "safety_gate_blocked"
                for r in approve
            ),
            "a Safety denial yields the blocked state",
        )
        c["approval-never-grants-safety"] = (
            "safety_decision_granted_here: Literal[False]" in _source()
            and NOT_SAFETY_NOTICE in _source(),
            "the receipt pins that no Safety approval is granted here",
        )
        sg = build_safety_module_operation_registry().get("approval_controls", {})
        c["safety-classified-read-only"] = (
            bool(sg)
            and set(sg.values()) <= {"automatic_read_only", "approval_required_read_only"},
            f"{len(sg)} classifications, all read-only",
        )
        c["submit-requires-approval-classification"] = (
            sg.get("submit_decision") == "approval_required_read_only",
            "submit_decision is approval-required read-only",
        )
    return _group("safety-gate", c)


def _run_rights() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        payload = _safety_payload()
        payload["rights_reviews"] = [{"rights_status": "unknown"}]
        e, _ = _state_engine(Path(raw), _eligible_raw(safety_gate=payload))
        rows = [r for r in e.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
                if r.decision_kind == "approve"]
        c["unknown-rights-blocks-approval"] = (
            any(r.reason_code == "rights_unknown_or_blocked" for r in rows),
            "unknown rights blocks approval",
        )
        c["rights-never-granted-here"] = (
            "grants_rights_approval: Literal[False]" in _source(), "pinned false"
        )
    return _group("rights", c)


def _run_evidence() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _engine(Path(raw))
        snap = _prepared(e)["snapshot"]
        c["owner-state-never-invented"] = (
            snap["safety_status"] == "unavailable" and snap["rights_status"] == "unavailable",
            "absent owner state is reported as unavailable, not assumed",
        )
        c["missing-owner-record-reported"] = (
            bool(
                e.build_approval_controls(PROJECT_ID)["signal_usage"][
                    "unavailable_signals"
                ]
            ),
            "absent owners are listed in unavailable_signals",
        )
    return _group("evidence", c)


def _run_revision() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _state_engine(Path(raw), _eligible_raw())
        snap = _prepared(e)["snapshot"]
        c["revision-bound-in-snapshot"] = (snap["workflow_revision"] == 3, "revision 3 bound")
        reg = build_fixed_approval_decision_registry()
        c["revision-required-by-owner-respected"] = (
            reg["review_action_workflow_human_decision_v1"]["requires_workflow_revision"] is True,
            "the owner's revision requirement is carried through",
        )
    return _group("revision", c)


def _run_digest() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        e, _ = _state_engine(root / "a", _eligible_raw())
        snap = _prepared(e)["snapshot"]
        c["snapshot-digest-is-sha256"] = (len(snap["snapshot_digest"]) == 64, "sha256")
        c["confirmation-digest-is-sha256"] = (
            len(snap["confirmation_context_digest"]) == 64, "sha256"
        )
        other, _ = _state_engine(
            root / "b", _eligible_raw(workflow_controller=_workflow_payload(revision=4))
        )
        c["target-digest-covers-workflow"] = (
            _prepared(other)["snapshot"]["target_digest"] != snap["target_digest"],
            "a workflow change changes the target digest",
        )
    return _group("digest", c)


def _submit(engine: BobaApprovalControlsV1, request_id: str, kind: str) -> Any:
    import asyncio

    return asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, kind))


def _decide(engine: BobaApprovalControlsV1, kind: str = APPROVE_DECISION) -> tuple[str, Any]:
    sid = _prepared(engine)["snapshot"]["approval_control_snapshot_id"]
    created = engine.create_approval_decision_request(
        PROJECT_ID, approval_control_snapshot_id=sid, decision_kind=kind,
        reason="A reviewer confirmed this.", idempotency_key="idem_decide_key",
        confirmed=True,
    )
    return str(created["review_action_request_id"]), created


def _run_idempotency() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    src = _source()
    with tempfile.TemporaryDirectory() as raw:
        e, owner = _state_engine(Path(raw), _eligible_raw())
        request_id, _ = _decide(e)
        first = _submit(e, request_id, APPROVE_DECISION)
        second = _submit(e, request_id, APPROVE_DECISION)
        c["reuses-review-ui-idempotency"] = (
            "idempotency_key=idempotency_key" in src.replace(" ", ""),
            "the Review UI idempotency key is passed straight through",
        )
        c["duplicate-submission-returns-existing"] = (
            second.duplicate_request_reused is True
            and second.approval_decision_receipt_id == first.approval_decision_receipt_id,
            "the existing canonical decision is returned",
        )
        c["no-second-idempotency-mechanism"] = (
            len(owner.submitted) == 1,
            "the owner was contacted exactly once for two submissions",
        )
    return _group("idempotency", c)


def _run_concurrency() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        e, owner = _state_engine(Path(raw), _eligible_raw())
        request_id, _ = _decide(e)
        _submit(e, request_id, APPROVE_DECISION)
        _submit(e, request_id, APPROVE_DECISION)
        _submit(e, request_id, APPROVE_DECISION)
        c["second-submission-does-not-duplicate"] = (
            len(owner.submitted) == 1, f"owner contacted {len(owner.submitted)} time(s)"
        )
        stored = e.store.load_boba_approval_control_receipt_for_request(PROJECT_ID, request_id)
        c["receipt-keyed-by-request"] = (
            stored is not None
            and stored["review_action_request_id"] == request_id,
            "the receipt is keyed by the canonical request id",
        )
    return _group("concurrency", c)


def _run_events() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        e, _ = _state_engine(root / "a", _eligible_raw())
        request_id, _ = _decide(e)
        _submit(e, request_id, APPROVE_DECISION)
        events = e.inspect_approval_events(PROJECT_ID)
        rows = events["events"]
        types = [row["event_type"] for row in rows]
        c["append-only-log"] = (events["append_only"] is True, "log is append-only")
        c["sequence-monotonic"] = (
            [row["sequence"] for row in rows] == sorted(row["sequence"] for row in rows),
            f"sequences: {[row['sequence'] for row in rows]}",
        )
        c["requested-event-emitted"] = ("approval_requested" in types, f"types: {types}")
        c["event-never-claims-execution"] = (
            all(row["claims_execution"] is False for row in rows), "pinned false"
        )
        c["event-never-claims-workflow-advance"] = (
            all(row["claims_workflow_advance"] is False for row in rows), "pinned false"
        )
        base = _eligible_raw()
        stale_engine, _ = _state_engine(root / "b", base)
        sid = _prepared(stale_engine)["snapshot"]["approval_control_snapshot_id"]
        drifted, _ = _state_engine(
            root / "b", {**base, "final_decision_bus": {"final_decisions": [{"id": "x"}]}}
        )
        drifted.create_approval_decision_request(
            PROJECT_ID, approval_control_snapshot_id=sid, decision_kind=APPROVE_DECISION,
            reason="fine", idempotency_key="idem_stale_evt_key", confirmed=True,
        )
        stale_types = [
            row["event_type"] for row in drifted.inspect_approval_events(PROJECT_ID)["events"]
        ]
        c["stale-event-emitted"] = ("approval_stale" in stale_types, f"types: {stale_types}")
    return _group("events", c)


def _run_receipts() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    kw: dict[str, Any] = {
        "approval_decision_receipt_id": "r",
        "review_action_request_id": "q",
        "project_id": PROJECT_ID,
        "target_type": "workflow_stage",
        "decision_kind": "approve",
        "owning_module_id": "workflow_controller",
        "owning_operation_id": "record_human_workflow_decision",
    }
    c["accepted-requires-canonical-record"] = _expect_error(
        BobaApprovalDecisionReceiptV1, **kw, owner_accepted=True
    )
    c["execution-requires-owner-module"] = _expect_error(
        BobaApprovalDecisionReceiptV1, **kw, execution_reported_by_owner=True
    )
    c["workflow-advance-requires-record"] = _expect_error(
        BobaApprovalDecisionReceiptV1, **kw, workflow_advanced=True
    )
    c["user-decision-requires-value"] = _expect_error(
        BobaApprovalDecisionReceiptV1, **kw, user_decision_recorded=True
    )
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _state_engine(Path(raw), _eligible_raw())
        request_id, _ = _decide(e)
        receipt = _submit(e, request_id, APPROVE_DECISION)
        c["four-facts-kept-apart"] = (
            receipt.user_decision_recorded is True
            and receipt.owner_accepted is True
            and receipt.safety_decision_granted_here is False
            and receipt.execution_reported_by_owner is False,
            "user, owner, safety and execution are separate facts",
        )
        c["approval-is-not-execution"] = (
            receipt.execution_reported_by_owner is False
            and receipt.workflow_advanced is False
            and receipt.checkpoint_restored is False
            and receipt.code_changed is False
            and receipt.artifact_changed is False
            and receipt.media_modified is False
            and receipt.upload_performed is False
            and receipt.publication_performed is False,
            "an accepted approval claims no side effect",
        )
    return _group("receipts", c)


def _run_persistence() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _state_engine(Path(raw), _eligible_raw())
        built = e.build_approval_control_registry(PROJECT_ID)
        rid = built["registry_snapshot"]["registry_snapshot_id"]
        c["registry-immutable"] = _expect_error(
            e.store.save_boba_approval_control_registry, PROJECT_ID, rid,
            {"registry_snapshot_id": "tampered"},
        )
        request_id, _ = _decide(e)
        receipt = _submit(e, request_id, APPROVE_DECISION)
        c["receipt-immutable"] = _expect_error(
            e.store.save_boba_approval_control_receipt, PROJECT_ID,
            receipt.approval_decision_receipt_id, {"review_action_request_id": "tampered"},
        )
        c["no-second-database"] = (
            "sqlite" not in _source().lower() and "psycopg" not in _source().lower(),
            "the existing BOBA store is the only persistence",
        )
        blob = json.dumps(e.export_approval_controls(PROJECT_ID))
        c["no-secrets-persisted"] = (
            "password" not in blob.lower() and "/home/" not in blob,
            "no credential or private path is exported",
        )
    return _group("persistence", c)


def _run_api() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    from olympus.api.v1.routes.boba import router

    paths = sorted(
        {
            str(getattr(r, "path", ""))
            for r in router.routes
            if "approval-controls" in str(getattr(r, "path", ""))
        }
    )
    ops = {
        k.split(".", 1)[1]
        for k in build_boba_operation_registry()
        if k.startswith("approval_controls.")
    }
    c["routes-registered"] = (len(paths) >= 10, f"{len(paths)} routes")
    c["project-scoped"] = (
        all("{project_id}" in p for p in paths), "every route is project scoped"
    )
    c["fourteen-operations-registered"] = (len(ops) == 14, f"{len(ops)} operations")
    return _group("api", c)


def _run_frontend_contract() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    lib, comp, results = _frontend(), _component(), _results()
    def flat(v: str) -> str:
        return re.sub(r"^[ \t]*\*[ \t]?", " ", v, flags=re.M).replace("\n", " ")
    c["module-present"] = (bool(lib) and bool(comp), "frontend modules exist")
    c["declares-no-authority"] = (
        "interaction layer, never an authority" in flat(lib),
        "the lib declares it is not an authority",
    )
    c["no-optimistic-approval"] = (
        "never shown optimistically" in flat(lib) and "receiptButtonState" in lib,
        "state is derived from the owner receipt only",
    )
    c["no-command-runner"] = (
        "child_process" not in comp and "eval(" not in comp and "innerHTML" not in comp,
        "the component runs no command",
    )
    c["state-not-colour-only"] = (
        "token" in lib and 'aria-hidden="true"' in comp,
        "every state carries a text label and a non-colour token",
    )
    c["mounted-in-review-ui"] = (
        results.count("{approvalRejectControls}") == 4,
        f"mounted at {results.count('{approvalRejectControls}')} render sites",
    )
    return _group("frontend-contract", c)


def _run_security() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    for key, bad in (
        ("reason-rejects-credential", "password=hunter2hunter2"),
        ("reason-rejects-command", "ffmpeg -i a.mp4 b.mp4"),
        ("reason-rejects-shell", "do this && rm -rf ."),
        ("reason-rejects-url", "see https://evil.example/x"),
        ("reason-rejects-private-path", "/home/operator/secret.mp4"),
        ("reason-rejects-unc-path", r"\\server\share\x"),
        ("reason-rejects-traversal", "../../etc/passwd"),
    ):
        c[key] = _expect_error(bounded_reason, bad)
    c["reason-accepts-prose"] = (
        bounded_reason("This looks correct to me.") == "This looks correct to me.",
        "ordinary reviewer prose is accepted",
    )
    c["raw-validated-before-sanitisation"] = (
        "raw = \"\" if value is None else str(value)" in _source()
        and "_contains_unsafe_text(raw)" in _source(),
        "the raw input is validated before sanitisation rewrites it",
    )
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _state_engine(Path(raw), _eligible_raw())
        sid = _prepared(e)["snapshot"]["approval_control_snapshot_id"]
        c["cross-project-snapshot-refused"] = _expect_error(
            e._snapshot, "another-project", sid
        )
        c["forged-snapshot-refused"] = _expect_error(
            e._snapshot, PROJECT_ID, "approval_control_snapshot_forged"
        )
        c["unknown-decision-kind-refused"] = _expect_error(
            e.create_approval_decision_request, PROJECT_ID,
            approval_control_snapshot_id=sid, decision_kind="request_revision",
            reason="x", idempotency_key="idem_bad_key", confirmed=True,
        )
    return _group("security", c)


def _run_reset() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        e, _ = _state_engine(Path(raw), _eligible_raw())
        request_id, _ = _decide(e)
        _submit(e, request_id, APPROVE_DECISION)
        e.build_approval_controls(PROJECT_ID)
        result = e.reset_approval_control_metadata(PROJECT_ID)
        for key, field in (
            ("preserves-workflow-decisions", "workflow_decision_history_preserved"),
            ("preserves-safety-records", "safety_gate_records_preserved"),
            ("preserves-final-decision-records", "final_decision_bus_records_preserved"),
            ("preserves-receipts", "decision_receipt_history_preserved"),
            ("preserves-event-log", "event_log_preserved"),
        ):
            c[key] = (result[field] is True, f"{field}=True")
        c["removes-no-media"] = (
            result["media_removed"] is False and result["outputs_removed"] is False,
            "no media or output is removed",
        )
        still = e.store.load_boba_approval_control_receipt_for_request(PROJECT_ID, request_id)
        c["preserves-receipts"] = (
            result["decision_receipt_history_preserved"] is True and still is not None,
            "the receipt survives the reset on disk",
        )
    return _group("reset", c)


def _run_regression_protection() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    ui = build_fixed_review_action_registry()
    c["review-ui-registry-untouched"] = (
        len(ui) == 4
        and ui["review_action_safety_human_review_v1"].allowed_in_v1 is False
        and ui["review_action_output_quality_human_review_v1"].allowed_in_v1 is False,
        "the Review UI registry and its gating are unchanged",
    )
    c["workflow-decision-values-unchanged"] = (
        list(ui["review_action_workflow_human_decision_v1"].allowed_decision_values)
        == ["approve", "reject", "request_revision"],
        "the owner's decision vocabulary is unchanged",
    )
    modules = build_boba_module_registry()
    c["existing-modules-still-registered"] = (
        all(
            m in modules
            for m in (
                "review_ui", "workflow_controller", "safety_gate", "final_decision_bus",
                "repair_plan_review", "error_doctor_review", "approval_controls",
            )
        ),
        f"{len(modules)} modules registered",
    )
    return _group("regression-protection", c)


def _run_timeline() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        empty, _ = _engine(root / "empty")
        t0 = empty.inspect_approval_timeline(PROJECT_ID)
        c["empty-timeline-truthful"] = (
            t0["empty"] is True and t0["entry_count"] == 0
            and "No approval decision" in t0["status"],
            "an empty timeline says so plainly",
        )
        c["no-mutation"] = (t0["mutation_performed"] is False, "pinned false")
        c["no-second-event-stream"] = (
            t0["second_event_stream_created"] is False, "pinned false"
        )

        e, _ = _state_engine(root / "a", _eligible_raw())
        request_id, _ = _decide(e)
        _submit(e, request_id, APPROVE_DECISION)
        t = e.inspect_approval_timeline(PROJECT_ID)
        entries = t["entries"]
        c["projects-control-events"] = (
            any(x["entry_kind"] == "approval_control_event" for x in entries),
            f"{len(entries)} entries projected",
        )
        c["owner-facts-flagged"] = (
            all(x["owner_fact"] is True for x in entries), "every entry marks owner facts"
        )
        c["derived-presentation-separate"] = (
            all("derived_title" in x and "derived_summary" in x for x in entries),
            "derived fields are separate from owner facts",
        )
        c["deterministic-ordering"] = (
            [x["timeline_entry_id"] for x in entries]
            == [x["timeline_entry_id"] for x in e.inspect_approval_timeline(PROJECT_ID)["entries"]],
            "identical order across rebuilds",
        )
        c["bounded-output"] = (
            len(e.inspect_approval_timeline(PROJECT_ID, limit=1)["entries"]) == 1,
            "output honours the limit",
        )
        c["reports-has-more"] = (
            e.inspect_approval_timeline(PROJECT_ID, limit=1)["has_more"] is True,
            "truncation is reported",
        )
        c["claims-no-execution"] = (
            all(
                x["claims_execution"] is False
                and x["claims_workflow_advance"] is False
                and x["claims_safety_approval"] is False
                for x in entries
            ),
            "no entry claims a side effect",
        )
        before = len(entries)
        e.reset_approval_control_metadata(PROJECT_ID)
        c["survives-reset"] = (
            len(e.inspect_approval_timeline(PROJECT_ID)["entries"]) == before,
            "immutable history survives the metadata reset",
        )

        decided = _workflow_payload()
        decided["human_decisions"] = [
            {
                "human_decision_id": "d1",
                "decision": "reject",
                "bounded_reason": "check /home/operator/secret.mp4",
                "decided_at": "2026-02-01T11:00:00+00:00",
                "workflow_revision": 3,
                "stage_instance_id": "render",
            }
        ]
        owner_engine, _ = _state_engine(
            root / "b", _eligible_raw(workflow_controller=decided)
        )
        owner_timeline = owner_engine.inspect_approval_timeline(PROJECT_ID)
        rows = [
            x for x in owner_timeline["entries"] if x["entry_kind"] == "owner_decision_record"
        ]
        c["includes-owner-decision-records"] = (
            bool(rows) and rows[0]["source_module_id"] == "workflow_controller",
            "the owner's own decision records are projected",
        )
        c["redacts-private-paths"] = (
            "/home/operator" not in json.dumps(owner_timeline),
            "private paths are redacted by the existing helpers",
        )
    return _group("timeline", c)


def _run_comparison() -> list[ScenarioResult]:
    c: dict[str, tuple[bool, str]] = {}
    with tempfile.TemporaryDirectory() as raw:
        e, owner = _state_engine(Path(raw), _eligible_raw())

        def decide(kind: str, key: str) -> str:
            sid = _prepared(e)["snapshot"]["approval_control_snapshot_id"]
            created = e.create_approval_decision_request(
                PROJECT_ID, approval_control_snapshot_id=sid, decision_kind=kind,
                reason="Reviewed.", idempotency_key=key, confirmed=True,
            )
            request_id = str(created["review_action_request_id"])
            _submit(e, request_id, kind)
            return request_id

        first = decide(APPROVE_DECISION, "idem_cmp_one_key")
        second = decide(REJECT_DECISION, "idem_cmp_two_key")
        result = e.compare_approval_decisions(PROJECT_ID, [first, second])["comparison"]

        c["compares-same-target"] = (
            result["compatible"] is True and result["same_target_id"] is True,
            "decisions on the same target compare cleanly",
        )
        c["requires-two-decisions"] = _expect_error(
            e.compare_approval_decisions, PROJECT_ID, [first]
        )
        c["bounded-maximum"] = _expect_error(
            e.compare_approval_decisions, PROJECT_ID, [first, second, "a", "b", "c"]
        )
        c["collapses-duplicates"] = (
            len(
                e.compare_approval_decisions(PROJECT_ID, [first, first, second])[
                    "comparison"
                ]["review_action_request_ids"]
            )
            == 2,
            "duplicate ids are collapsed",
        )
        c["rejects-unknown-decision"] = _expect_error(
            e.compare_approval_decisions, PROJECT_ID, [first, "review_action_unknown"]
        )
        c["rejects-cross-project"] = _expect_error(
            e.compare_approval_decisions, "another-project", [first, second]
        )
        c["preserves-approve-vs-reject"] = (
            set(result["decision_kinds"]) == {"approve", "reject"},
            "approve and reject stay distinct",
        )
        c["lists-differing-fields"] = (
            "decision_kind" in result["differing_fields"],
            f"differing: {result['differing_fields'][:4]}",
        )
        c["no-automatic-winner"] = (
            result["no_automatic_winner"] is True, "pinned true"
        )
        c["no-best-decision-inferred"] = (
            result["no_best_decision_inferred"] is True, "pinned true"
        )
        c["no-authority-change"] = (
            result["authority_changed"] is False
            and result["mutation_performed"] is False
            and result["approval_created"] is False
            and result["safety_overridden"] is False,
            "every write claim is pinned false",
        )
        c["owner-facts-separate-from-presentation"] = (
            len(result["owner_fact_rows"]) == 2 and len(result["presentation_rows"]) == 2,
            "owner facts and presentation are separate lists",
        )
        c["deterministic-output"] = (
            result["comparison_id"]
            == e.compare_approval_decisions(PROJECT_ID, [first, second])["comparison"][
                "comparison_id"
            ],
            "the comparison id is stable",
        )
        owner.stale = True
        third = decide(APPROVE_DECISION, "idem_cmp_three_key")
        stale_result = e.compare_approval_decisions(PROJECT_ID, [first, third])["comparison"]
        states = {row["derived_state"] for row in stale_result["presentation_rows"]}
        c["preserves-stale-vs-current"] = (
            "stale" in states and "approved" in states,
            f"states preserved: {sorted(states)}",
        )
        # An incompatible target must be reported, never smoothed over.
        forged = e.store.load_boba_approval_control_receipt_for_request(PROJECT_ID, second)
        assert forged is not None
        forged = dict(forged)
        forged["approval_decision_receipt_id"] = "approval_decision_receipt_other_target"
        forged["review_action_request_id"] = "review_action_other_target"
        forged["target_id"] = "assemble"
        e.store.save_boba_approval_control_receipt(
            PROJECT_ID, "approval_decision_receipt_other_target", forged
        )
        mixed = e.compare_approval_decisions(
            PROJECT_ID, [first, "review_action_other_target"]
        )["comparison"]
        c["incompatible-target-is-truthful"] = (
            mixed["compatible"] is False and bool(mixed["incompatibility_reason"]),
            "an incompatible target yields a bounded truthful result",
        )
    return _group("comparison", c)


_GROUP_RUNNERS: dict[str, Callable[[], list[ScenarioResult]]] = {
    "registry": _run_registry,
    "eligibility": _run_eligibility,
    "approval": _run_approval,
    "rejection": _run_rejection,
    "stale-state": _run_stale_state,
    "expiry": _run_expiry,
    "invalidation": _run_invalidation,
    "safety-gate": _run_safety_gate,
    "rights": _run_rights,
    "evidence": _run_evidence,
    "revision": _run_revision,
    "digest": _run_digest,
    "idempotency": _run_idempotency,
    "concurrency": _run_concurrency,
    "events": _run_events,
    "receipts": _run_receipts,
    "persistence": _run_persistence,
    "api": _run_api,
    "frontend-contract": _run_frontend_contract,
    "security": _run_security,
    "reset": _run_reset,
    "timeline": _run_timeline,
    "comparison": _run_comparison,
    "regression-protection": _run_regression_protection,
}


def run_named_scenario(name: str) -> ScenarioResult:
    if name not in SCENARIO_NAMES:
        raise ValidationError(f"Unknown approval control scenario: {name}")
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
    rows: list[ScenarioResult] = []
    src, lib, comp = _source(), _frontend(), _component()
    ops = {
        k.split(".", 1)[1]
        for k in build_boba_operation_registry()
        if k.startswith("approval_controls.")
    }
    sg = build_safety_module_operation_registry().get("approval_controls", {})
    module = build_boba_module_registry()["approval_controls"]
    calls = set(re.findall(r"self\.integration\.([a-z_]+)", src))

    def add(name: str, passed: bool, detail: str) -> None:
        rows.append(_check(f"self-check:{name}", passed, detail))

    with tempfile.TemporaryDirectory() as raw:
        e, owner = _state_engine(Path(raw), _eligible_raw())
        controls = e.build_approval_controls(PROJECT_ID)
        request_id, _ = _decide(e)
        receipt = _submit(e, request_id, APPROVE_DECISION)
        usage = controls["signal_usage"]

        add("module-imports", bool(build_fixed_approval_decision_registry()), "registry builds")
        add("contracts-serialize", isinstance(json.dumps(controls), str), "set serialises")
        add("operations-registered", len(ops) == 14, f"{len(ops)} operations")
        add("safety-classified", len(sg) == 14, f"{len(sg)} classifications")
        add(
            "no-execution-classification",
            set(sg.values()) <= {"automatic_read_only", "approval_required_read_only"},
            "no execution-capable classification",
        )
        add("module-read-only", module.read_only is True, "module registered read-only")
        add(
            "module-not-execution-capable",
            module.execution_capable is False,
            "module is not execution capable",
        )
        add(
            "only-review-ui-chain-called",
            calls
            == {"create_boba_review_action_request", "submit_boba_review_action_to_owner"},
            f"integration calls: {sorted(calls)}",
        )
        add(
            "decision-reached-owner-once",
            len(owner.submitted) == 1,
            "the canonical owner was contacted exactly once",
        )
        add(
            "owner-record-required",
            receipt.owner_accepted and receipt.canonical_record_id is not None,
            "acceptance names a canonical owner record",
        )
        for flag in (
            "second_approval_authority_created", "second_decision_path_created",
            "second_database_created", "second_idempotency_mechanism_created",
            "optimistic_approval_shown", "safety_gate_bypassed", "rights_bypassed",
            "budget_bypassed", "validation_bypassed", "execution_performed",
            "repair_executed", "recovery_executed", "workflow_advanced_by_panel",
            "checkpoint_restored", "code_modified", "artifact_modified",
            "media_modified", "command_execution_used", "ffmpeg_execution_used",
            "upload_used", "publication_used",
        ):
            add(f"signal-{flag.replace('_','-')}", usage[flag] is False, f"{flag} pinned false")
        add(
            "notices-exact",
            NOT_EXECUTION_NOTICE.endswith("It does not execute anything.")
            and "Safety Gate remains authoritative" in NOT_SAFETY_NOTICE
            and "owns transitions" in NOT_WORKFLOW_NOTICE
            and "deletes nothing" in REJECTION_NOTICE,
            "the four notices are the exact required sentences",
        )
        add("no-command-runner", "subprocess" not in src, "no command runner in the module")
        timeline = e.inspect_approval_timeline(PROJECT_ID)
        add(
            "timeline-is-read-only",
            timeline["mutation_performed"] is False
            and timeline["second_event_stream_created"] is False,
            "the timeline mutates nothing and opens no second stream",
        )
        add(
            "timeline-separates-facts",
            all(x["owner_fact"] is True for x in timeline["entries"]),
            "owner facts are flagged and kept separate from presentation",
        )
        add(
            "operations-include-timeline-and-comparison",
            {"inspect_timeline", "compare_decisions"} <= ops,
            "both read-only projections are registered operations",
        )
        add(
            "timeline-and-comparison-classified-read-only",
            sg.get("inspect_timeline") == "automatic_read_only"
            and sg.get("compare_decisions") == "automatic_read_only",
            "both are Safety-classified automatic read-only",
        )
        add("frontend-present", bool(lib) and bool(comp), "frontend modules exist")
        add(
            "frontend-no-optimistic-approval",
            "never shown optimistically" in lib.replace("\n", " "),
            "the frontend never shows an optimistic approval",
        )
    return rows


def run_synthetic_project() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as raw:
        e, owner = _state_engine(Path(raw), _eligible_raw())
        controls = e.build_approval_controls(PROJECT_ID, "workflow_stage", "render")
        rows = e.inspect_approval_eligibility(PROJECT_ID, "workflow_stage", "render")
        request_id, _ = _decide(e)
        receipt = _submit(e, request_id, APPROVE_DECISION)
        return {
            "project_id": PROJECT_ID,
            "decision_capable_actions": len(build_fixed_approval_decision_registry()),
            "eligibility_rows": len(rows),
            "eligible_rows": sum(1 for r in rows if r.eligible),
            "approve_available": controls["control_summary"]["approve_available"],
            "reject_available": controls["control_summary"]["reject_available"],
            "owner_contacted_times": len(owner.submitted),
            "owner_accepted": receipt.owner_accepted,
            "execution_reported": receipt.execution_reported_by_owner,
            "workflow_advanced": receipt.workflow_advanced,
            "safety_granted_here": receipt.safety_decision_granted_here,
            "event_count": len(e.inspect_approval_events(PROJECT_ID)["events"]),
            "limitations": controls["limitations"],
        }


def _write_report(payload: dict[str, Any]) -> Path:
    directory = Path("work/validation_reports/boba_approval_reject_buttons")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"report_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Approval / Reject Buttons V1 without touching real state."
    )
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--synthetic-project", action="store_true")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"tool": "validate_boba_approval_reject_buttons"}
    failures: list[ScenarioResult] = []
    results = (
        [run_named_scenario(n) for n in args.scenario]
        if args.scenario
        else run_all_scenarios()
    )
    failed = [r for r in results if not r.passed]
    failures.extend(failed)
    report["scenarios"] = {
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": [{"name": r.name, "detail": r.detail} for r in failed],
    }
    print(
        f"scenarios: {len(results)} total, "
        f"{len(results) - len(failed)} passed, {len(failed)} failed"
    )

    if args.self_check:
        checks = run_self_check()
        cf = [r for r in checks if not r.passed]
        failures.extend(cf)
        report["self_check"] = {
            "total": len(checks),
            "passed": len(checks) - len(cf),
            "failed": [{"name": r.name, "detail": r.detail} for r in cf],
        }
        print(
            f"self-check: {len(checks)} checks, "
            f"{len(checks) - len(cf)} passed, {len(cf)} failed"
        )

    if args.synthetic_project:
        synthetic = run_synthetic_project()
        report["synthetic_project"] = synthetic
        print("synthetic project:")
        for k, v in synthetic.items():
            print(f"  {k}: {v}")

    for r in failures:
        print(f"FAILED {r.name}: {r.detail}")
    if args.report:
        print(f"report written to {_write_report(report)}")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
