"""Unit tests for BOBA Approval / Reject Buttons V1.

Every catalogued validator scenario and declared-boundary self-check runs as an
individual test, alongside direct contract, engine and API tests.

Nothing here approves anything against real state, executes anything, grants
Safety approval, advances a workflow, uploads or publishes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_approval_reject_buttons import (
    SCENARIO_NAMES,
    ScenarioResult,
    run_all_scenarios,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.approval_controls import (
    APPROVE_DECISION,
    NOT_EXECUTION_NOTICE,
    NOT_SAFETY_NOTICE,
    NOT_WORKFLOW_NOTICE,
    REJECT_DECISION,
    REJECTION_NOTICE,
    STALE_NOTICE,
    BobaApprovalControlEventV1,
    BobaApprovalControlRegistrySnapshotV1,
    BobaApprovalControlSetV1,
    BobaApprovalControlSignalUsageV1,
    BobaApprovalControlSnapshotV1,
    BobaApprovalControlSummaryV1,
    BobaApprovalControlsV1,
    BobaApprovalDecisionReceiptV1,
    BobaApprovalEligibilityV1,
    approval_button_states,
    bounded_reason,
    build_fixed_approval_decision_registry,
)
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.review_ui import build_fixed_review_action_registry
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError, register_exception_handlers
from olympus.utils import utc_now

PROJECT_ID = "approval-controls-test"

CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaApprovalControlRegistrySnapshotV1,
    BobaApprovalEligibilityV1,
    BobaApprovalControlSnapshotV1,
    BobaApprovalDecisionReceiptV1,
    BobaApprovalControlEventV1,
    BobaApprovalControlSignalUsageV1,
    BobaApprovalControlSummaryV1,
    BobaApprovalControlSetV1,
)

_WRITE_FLAGS: tuple[str, ...] = (
    "second_approval_authority_created",
    "second_decision_path_created",
    "second_database_created",
    "second_idempotency_mechanism_created",
    "optimistic_approval_shown",
    "safety_gate_bypassed",
    "rights_bypassed",
    "budget_bypassed",
    "validation_bypassed",
    "execution_performed",
    "repair_executed",
    "recovery_executed",
    "workflow_advanced_by_panel",
    "checkpoint_restored",
    "code_modified",
    "artifact_modified",
    "media_modified",
    "command_execution_used",
    "ffmpeg_execution_used",
    "upload_used",
    "publication_used",
)

_UNSAFE_REASONS: tuple[str, ...] = (
    "password=hunter2hunter2",
    "token=abc123def456",
    "ffmpeg -i in.mp4 out.mp4",
    "git checkout main",
    "do this && rm -rf .",
    "see https://evil.example/x",
    "ftp://host/file",
    "/home/operator/secret.mp4",
    "/Users/alice/x",
    r"C:\Users\bob\x",
    r"\\server\share\x",
    "../../etc/passwd",
)


class _StubIntegration:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.submitted: list[str] = []
        self.accept = True
        self.stale = False

    def create_boba_review_action_request(
        self, project_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.created.append({"project_id": project_id, **kwargs})
        return {"review_action_request_id": f"review_action_{len(self.created)}", **kwargs}

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
                "error_code": "owner_rejected",
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


class _StateStore(BobaMemoryStore):
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


def _workflow(revision: int = 3, stage: str = "render") -> dict[str, Any]:
    return {
        "schema_version": "boba_workflow_controller_v1",
        "workflow_runs": [
            {
                "workflow_run_id": "run_a",
                "revision": revision,
                "current_stage_instance_id": stage,
                "status": "running",
                "updated_at": "2026-02-01T10:00:00+00:00",
            }
        ],
        "human_decisions": [],
    }


def _safety(outcome: str = "approved_exact_action", rights: str = "clear") -> dict[str, Any]:
    return {
        "schema_version": "boba_safety_gate_v1",
        "safety_decisions": [{"outcome": outcome}],
        "rights_reviews": [{"rights_status": rights}],
        "checkpoint_reviews": [{"checkpoint_status": "ready"}],
    }


def _engine(
    tmp_path: Path, raw: dict[str, Any] | None = None
) -> tuple[BobaApprovalControlsV1, _StubIntegration]:
    owner = _StubIntegration()
    payload = (
        raw
        if raw is not None
        else {"workflow_controller": _workflow(), "safety_gate": _safety()}
    )
    store = _StateStore(tmp_path / "boba", payload)
    return BobaApprovalControlsV1(store, owner), owner  # type: ignore[arg-type]


def _snapshot_id(engine: BobaApprovalControlsV1) -> str:
    payload = engine.build_approval_control_snapshot(
        PROJECT_ID, "review_session_a", "review_snapshot_a", "workflow_stage", "render"
    )
    return str(payload["snapshot"]["approval_control_snapshot_id"])


def _decide(engine: BobaApprovalControlsV1, kind: str = APPROVE_DECISION) -> str:
    created = engine.create_approval_decision_request(
        PROJECT_ID,
        approval_control_snapshot_id=_snapshot_id(engine),
        decision_kind=kind,
        reason="A reviewer confirmed this.",
        idempotency_key="idem_test_key",
        confirmed=True,
    )
    return str(created["review_action_request_id"])


def _project() -> Project:
    ts = utc_now()
    return Project(
        id=PROJECT_ID, name="Approval Controls Test", source_filename="s.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4", size_bytes=24, video_format="mp4",
        content_type="video/mp4", duration_seconds=600.0, width=1920, height=1080,
        status=ProjectStatus.ANALYZED, created_at=ts, updated_at=ts,
    )


def _client(tmp_path: Path) -> tuple[TestClient, BobaIntegration]:
    from olympus.api.v1.routes.boba import router

    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    asyncio.run(storage.put(project.storage_key, b"x", content_type="video/mp4"))
    asyncio.run(StorageProjectRepository(storage).save(project))
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    return TestClient(app), integration


def _base() -> str:
    return f"/api/v1/boba/projects/{PROJECT_ID}/approval-controls"


# ---------------------------------------------------------------------------
# Validator coverage
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def scenario_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_all_scenarios()}


@pytest.fixture(scope="module")
def self_check_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_self_check()}


@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
def test_validator_scenario(
    scenario: str, scenario_results: dict[str, ScenarioResult]
) -> None:
    result = scenario_results[scenario]
    assert result.passed, f"{scenario}: {result.detail}"


SELF_CHECK_NAMES: tuple[str, ...] = tuple(item.name for item in run_self_check())


@pytest.mark.parametrize("check", SELF_CHECK_NAMES)
def test_declared_boundary_self_check(
    check: str, self_check_results: dict[str, ScenarioResult]
) -> None:
    result = self_check_results[check]
    assert result.passed, f"{check}: {result.detail}"


def test_scenario_catalogue_covers_every_required_group() -> None:
    groups = {name.rsplit(":", 1)[0] for name in SCENARIO_NAMES}
    for required in (
        "registry", "eligibility", "approval", "rejection", "stale-state", "expiry",
        "invalidation", "safety-gate", "rights", "evidence", "revision", "digest",
        "idempotency", "concurrency", "events", "receipts", "persistence", "api",
        "frontend-contract", "security", "reset", "regression-protection",
        # added with the timeline and comparison surfaces
        "timeline", "comparison",
    ):
        assert required in groups
    assert len(groups) == 24
    assert len(SCENARIO_NAMES) == len(set(SCENARIO_NAMES))


def test_synthetic_project_reports_truthfully() -> None:
    report = run_synthetic_project()
    assert report["decision_capable_actions"] == 3
    assert report["eligible_rows"] == 2
    assert report["owner_contacted_times"] == 1
    assert report["owner_accepted"] is True
    assert report["execution_reported"] is False
    assert report["workflow_advanced"] is False
    assert report["safety_granted_here"] is False


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contract", CONTRACT_TYPES, ids=lambda c: c.__name__)
def test_contract_forbids_unknown_fields(contract: type[BaseModel]) -> None:
    assert contract.model_config.get("extra") == "forbid"


@pytest.mark.parametrize("flag", _WRITE_FLAGS)
def test_signal_usage_flag_pinned_false(flag: str) -> None:
    assert getattr(BobaApprovalControlSignalUsageV1(), flag) is False
    with pytest.raises(PydanticValidationError):
        BobaApprovalControlSignalUsageV1(**{flag: True})


def test_signal_usage_pins_reuse_of_review_ui() -> None:
    usage = BobaApprovalControlSignalUsageV1()
    assert usage.reuses_review_ui_action_chain is True
    assert usage.reuses_review_ui_idempotency is True


def test_registry_snapshot_pins_no_authority() -> None:
    snap = BobaApprovalControlRegistrySnapshotV1(
        registry_snapshot_id="r", registry_digest="a" * 64
    )
    assert snap.creates_approval_authority is False
    assert snap.creates_second_decision_path is False
    assert snap.immutable is True


@pytest.mark.parametrize(
    "field",
    ["grants_execution", "grants_safety_approval", "grants_rights_approval",
     "advances_workflow"],
)
def test_eligibility_refuses_grant_claims(field: str) -> None:
    with pytest.raises(PydanticValidationError):
        BobaApprovalEligibilityV1(
            eligibility_id="e", project_id=PROJECT_ID, target_type="workflow_stage",
            action_descriptor_id="a", owning_module_id="m", owning_operation_id="o",
            decision_kind="approve", button_state="approve_available",
            eligible=True, reason_code="eligible", **{field: True},
        )


def test_eligibility_requires_consistent_reason_code() -> None:
    with pytest.raises(PydanticValidationError):
        BobaApprovalEligibilityV1(
            eligibility_id="e", project_id=PROJECT_ID, target_type="workflow_stage",
            action_descriptor_id="a", owning_module_id="m", owning_operation_id="o",
            decision_kind="approve", button_state="approve_available",
            eligible=True, reason_code="expired",
        )


_RECEIPT_KW: dict[str, Any] = {
    "approval_decision_receipt_id": "r",
    "review_action_request_id": "q",
    "project_id": PROJECT_ID,
    "target_type": "workflow_stage",
    "decision_kind": "approve",
    "owning_module_id": "workflow_controller",
    "owning_operation_id": "record_human_workflow_decision",
}


def test_receipt_refuses_acceptance_without_canonical_record() -> None:
    with pytest.raises(PydanticValidationError):
        BobaApprovalDecisionReceiptV1(**_RECEIPT_KW, owner_accepted=True)


def test_receipt_refuses_execution_without_owner_module() -> None:
    with pytest.raises(PydanticValidationError):
        BobaApprovalDecisionReceiptV1(**_RECEIPT_KW, execution_reported_by_owner=True)


def test_receipt_refuses_workflow_advance_without_record() -> None:
    with pytest.raises(PydanticValidationError):
        BobaApprovalDecisionReceiptV1(**_RECEIPT_KW, workflow_advanced=True)


def test_receipt_refuses_user_decision_without_value() -> None:
    with pytest.raises(PydanticValidationError):
        BobaApprovalDecisionReceiptV1(**_RECEIPT_KW, user_decision_recorded=True)


@pytest.mark.parametrize(
    "field",
    ["checkpoint_restored", "code_changed", "artifact_changed", "media_modified",
     "upload_performed", "publication_performed", "safety_decision_granted_here"],
)
def test_receipt_pins_no_side_effect(field: str) -> None:
    receipt = BobaApprovalDecisionReceiptV1(**_RECEIPT_KW)
    assert getattr(receipt, field) is False
    with pytest.raises(PydanticValidationError):
        BobaApprovalDecisionReceiptV1(**_RECEIPT_KW, **{field: True})


@pytest.mark.parametrize("field", ["claims_execution", "claims_workflow_advance"])
def test_event_pins_no_execution_claim(field: str) -> None:
    event = BobaApprovalControlEventV1(
        event_id="e", project_id=PROJECT_ID, sequence=1, event_type="approval_confirmed"
    )
    assert getattr(event, field) is False
    with pytest.raises(PydanticValidationError):
        BobaApprovalControlEventV1(
            event_id="e", project_id=PROJECT_ID, sequence=1,
            event_type="approval_confirmed", **{field: True},
        )


def test_event_sequence_is_one_based() -> None:
    with pytest.raises(PydanticValidationError):
        BobaApprovalControlEventV1(
            event_id="e", project_id=PROJECT_ID, sequence=0, event_type="approval_confirmed"
        )


# ---------------------------------------------------------------------------
# Registry and notices
# ---------------------------------------------------------------------------
def test_registry_is_the_decision_capable_subset_of_review_ui() -> None:
    reg = build_fixed_approval_decision_registry()
    ui = build_fixed_review_action_registry()
    assert len(reg) == 3
    assert set(reg) <= set(ui)
    for key, row in reg.items():
        assert row["owning_operation_id"] == ui[key].owning_operation_id
        assert row["allowed_in_v1"] == ui[key].allowed_in_v1


def test_only_the_workflow_decision_is_available_in_v1() -> None:
    reg = build_fixed_approval_decision_registry()
    available = [
        k
        for k, r in reg.items()
        if r["allowed_in_v1"] and r["availability"] == "available"
    ]
    assert available == ["review_action_workflow_human_decision_v1"]


def test_ten_truthful_button_states() -> None:
    assert len(approval_button_states()) == 10
    assert "approved" in approval_button_states()
    assert "blocked" in approval_button_states()


def test_required_notices_are_exact() -> None:
    assert NOT_EXECUTION_NOTICE == (
        "This records a human decision only. It does not execute anything."
    )
    assert "Safety Gate remains authoritative" in NOT_SAFETY_NOTICE
    assert "owns transitions" in NOT_WORKFLOW_NOTICE
    assert "deletes nothing" in REJECTION_NOTICE and "rolls nothing back" in REJECTION_NOTICE
    assert "changed after this control was displayed" in STALE_NOTICE


# ---------------------------------------------------------------------------
# bounded_reason security
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("reason", _UNSAFE_REASONS)
def test_bounded_reason_refuses_unsafe_material(reason: str) -> None:
    with pytest.raises(ValidationError):
        bounded_reason(reason)


@pytest.mark.parametrize(
    "reason",
    ["This looks correct to me.", "Approved after reading the evidence.",
     "Rejecting: the baseline comparison is missing.", ""],
)
def test_bounded_reason_accepts_prose(reason: str) -> None:
    assert bounded_reason(reason) == reason


def test_bounded_reason_validates_raw_before_sanitisation() -> None:
    # _safe_text rewrites https:// into http[private-path]/ and strips /home/,
    # so checking the sanitised text would silently accept both.
    with pytest.raises(ValidationError):
        bounded_reason("check https://evil.example")
    with pytest.raises(ValidationError):
        bounded_reason("look at /home/operator/x")


def test_bounded_reason_bounds_length() -> None:
    assert len(bounded_reason("x" * 900)) <= 500


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def test_registry_snapshot_is_immutable_and_stable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first = engine.build_approval_control_registry(PROJECT_ID)
    second = engine.build_approval_control_registry(PROJECT_ID)
    assert first["registry_snapshot"] == second["registry_snapshot"]


def test_eligibility_reports_owner_disabled_actions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    rows = engine.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
    assert any(r.reason_code == "action_not_available_in_v1" for r in rows)
    assert all(r.bounded_explanation for r in rows)


def test_eligibility_offers_approve_and_reject_when_owner_allows(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    rows = [
        r
        for r in engine.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
        if r.eligible
    ]
    assert {r.decision_kind for r in rows} == {"approve", "reject"}


def test_eligibility_requires_a_bound_workflow_run(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, {})
    rows = engine.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
    assert not any(r.eligible for r in rows)
    assert any(r.reason_code == "no_workflow_run_bound" for r in rows)


def test_safety_denial_blocks_approval_but_not_rejection(tmp_path: Path) -> None:
    engine, _ = _engine(
        tmp_path,
        {
            "workflow_controller": _workflow(),
            "safety_gate": _safety(outcome="denied_action"),
        },
    )
    rows = engine.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
    approve = [r for r in rows if r.decision_kind == "approve"]
    reject = [r for r in rows if r.decision_kind == "reject" and r.eligible]
    assert all(not r.eligible for r in approve)
    assert any(r.button_state == "blocked" for r in approve)
    assert reject, "a reviewer must still be able to reject a Safety-blocked action"


def test_unknown_rights_blocks_approval(tmp_path: Path) -> None:
    engine, _ = _engine(
        tmp_path, {"workflow_controller": _workflow(), "safety_gate": _safety(rights="unknown")}
    )
    rows = [r for r in engine.inspect_approval_eligibility(PROJECT_ID, "workflow_stage")
            if r.decision_kind == "approve"]
    assert any(r.reason_code == "rights_unknown_or_blocked" for r in rows)


def test_snapshot_binds_exact_identity(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    snap = engine.build_approval_control_snapshot(
        PROJECT_ID, "review_session_a", "review_snapshot_a", "workflow_stage", "render"
    )["snapshot"]
    assert snap["workflow_run_id"] == "run_a"
    assert snap["workflow_revision"] == 3
    assert len(snap["target_digest"]) == 64
    assert len(snap["snapshot_digest"]) == 64
    assert len(snap["confirmation_context_digest"]) == 64


def test_snapshot_is_project_scoped(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    sid = _snapshot_id(engine)
    with pytest.raises(ValidationError):
        engine._snapshot("another-project", sid)


def test_forged_snapshot_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine._snapshot(PROJECT_ID, "approval_control_snapshot_forged")


def test_revalidation_passes_when_nothing_changed(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    result = engine.revalidate_approval_snapshot(PROJECT_ID, _snapshot_id(engine))
    assert result["valid"] is True
    assert result["stale"] is False


@pytest.mark.parametrize(
    ("label", "override"),
    [
        ("workflow revision", {"workflow_controller": _workflow(revision=9)}),
        ("workflow stage", {"workflow_controller": _workflow(stage="assemble")}),
        ("safety record", {"safety_gate": _safety(outcome="denied_action")}),
        ("rights record", {"safety_gate": _safety(rights="blocked")}),
        ("final decision record", {"final_decision_bus": {"final_decisions": [{"id": "x"}]}}),
    ],
)
def test_revalidation_refuses_on_drift(
    tmp_path: Path, label: str, override: dict[str, Any]
) -> None:
    base = {"workflow_controller": _workflow(), "safety_gate": _safety()}
    engine, _ = _engine(tmp_path, base)
    sid = _snapshot_id(engine)
    drifted, _ = _engine(tmp_path, {**base, **override})
    result = drifted.revalidate_approval_snapshot(PROJECT_ID, sid)
    assert result["valid"] is False, f"{label} drift must be refused"


def test_already_decided_is_refused_and_shown(tmp_path: Path) -> None:
    decided = _workflow()
    decided["human_decisions"] = [
        {"human_decision_id": "d1", "decision": "approve", "stage_instance_id": "render"}
    ]
    engine, _ = _engine(tmp_path, {"workflow_controller": decided, "safety_gate": _safety()})
    rows = engine.inspect_approval_eligibility(PROJECT_ID, "workflow_stage", "render")
    assert any(r.reason_code == "already_decided" and r.button_state == "approved" for r in rows)
    result = engine.revalidate_approval_snapshot(PROJECT_ID, _snapshot_id(engine))
    assert result["code"] == "already_decided"


def test_decision_requires_confirmation(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.create_approval_decision_request(
            PROJECT_ID, approval_control_snapshot_id=_snapshot_id(engine),
            decision_kind=APPROVE_DECISION, reason="fine",
            idempotency_key="idem_x_key", confirmed=False,
        )


def test_decision_requires_reason_when_owner_does(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.create_approval_decision_request(
            PROJECT_ID, approval_control_snapshot_id=_snapshot_id(engine),
            decision_kind=APPROVE_DECISION, reason="",
            idempotency_key="idem_y_key", confirmed=True,
        )


@pytest.mark.parametrize("kind", ["request_revision", "delete", "execute", ""])
def test_unsupported_decision_kind_is_refused(tmp_path: Path, kind: str) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.create_approval_decision_request(
            PROJECT_ID, approval_control_snapshot_id=_snapshot_id(engine),
            decision_kind=kind, reason="fine",
            idempotency_key="idem_z_key", confirmed=True,
        )


def test_stale_state_blocks_the_request_before_the_owner(tmp_path: Path) -> None:
    base = {"workflow_controller": _workflow(), "safety_gate": _safety()}
    engine, _ = _engine(tmp_path, base)
    sid = _snapshot_id(engine)
    drifted, owner = _engine(
        tmp_path, {**base, "final_decision_bus": {"final_decisions": [{"id": "x"}]}}
    )
    created = drifted.create_approval_decision_request(
        PROJECT_ID, approval_control_snapshot_id=sid, decision_kind=APPROVE_DECISION,
        reason="fine", idempotency_key="idem_stale_key", confirmed=True,
    )
    assert created["created"] is False
    assert owner.created == []


@pytest.mark.parametrize("kind", [APPROVE_DECISION, REJECT_DECISION])
def test_decision_reaches_the_canonical_owner(tmp_path: Path, kind: str) -> None:
    engine, owner = _engine(tmp_path)
    request_id = _decide(engine, kind)
    receipt = asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, kind))
    assert owner.submitted == [request_id]
    assert receipt.owner_accepted is True
    assert receipt.owning_module_id == "workflow_controller"
    assert receipt.user_decision_value == kind


def test_accepted_decision_claims_no_side_effects(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    receipt = asyncio.run(
        engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION)
    )
    assert receipt.execution_reported_by_owner is False
    assert receipt.workflow_advanced is False
    assert receipt.safety_decision_granted_here is False
    assert receipt.checkpoint_restored is False
    assert receipt.code_changed is False
    assert receipt.artifact_changed is False


def test_owner_refusal_is_recorded_truthfully(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    request_id = _decide(engine)
    owner.accept = False
    receipt = asyncio.run(
        engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION)
    )
    assert receipt.owner_accepted is False
    assert receipt.user_decision_recorded is False
    assert receipt.canonical_record_id is None


def test_owner_stale_rejection_is_recorded(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    request_id = _decide(engine)
    owner.stale = True
    receipt = asyncio.run(
        engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION)
    )
    assert receipt.stale_state_rejected is True
    assert receipt.owner_accepted is False


def test_duplicate_submission_reuses_the_receipt(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    request_id = _decide(engine)
    first = asyncio.run(
        engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION)
    )
    second = asyncio.run(
        engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION)
    )
    third = asyncio.run(
        engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION)
    )
    assert len(owner.submitted) == 1
    assert second.duplicate_request_reused is True
    assert third.approval_decision_receipt_id == first.approval_decision_receipt_id


def test_events_are_append_only_and_one_based(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    events = engine.inspect_approval_events(PROJECT_ID)
    sequences = [e["sequence"] for e in events["events"]]
    assert events["append_only"] is True
    assert sequences == sorted(sequences)
    assert min(sequences) == 1, "a cursor of 0 must still return the first event"
    assert [e["event_type"] for e in events["events"]] == [
        "approval_requested", "approval_confirmed"
    ]


def test_events_never_claim_execution(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    for event in engine.inspect_approval_events(PROJECT_ID)["events"]:
        assert event["claims_execution"] is False
        assert event["claims_workflow_advance"] is False


def test_decision_history_is_owner_attributed(tmp_path: Path) -> None:
    decided = _workflow()
    decided["human_decisions"] = [
        {"human_decision_id": "d1", "decision": "reject", "bounded_reason": "not ready",
         "decided_at": "2026-02-01T11:00:00+00:00", "workflow_revision": 3}
    ]
    engine, _ = _engine(tmp_path, {"workflow_controller": decided, "safety_gate": _safety()})
    history = engine.inspect_decision_history(PROJECT_ID)
    assert history["owner_module_id"] == "workflow_controller"
    assert history["entry_count"] == 1
    assert history["entries"][0]["decision"] == "reject"
    assert history["entries"][0]["upload_authorized"] is False


def test_decision_status_reports_undecided(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    status = engine.inspect_decision_status(PROJECT_ID, "review_action_missing")
    assert status["decided"] is False
    assert status["receipt"] is None


def test_registry_and_receipt_are_immutable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    rid = engine.build_approval_control_registry(PROJECT_ID)["registry_snapshot"][
        "registry_snapshot_id"
    ]
    with pytest.raises(ValidationError):
        engine.store.save_boba_approval_control_registry(
            PROJECT_ID, rid, {"registry_snapshot_id": "tampered"}
        )
    request_id = _decide(engine)
    receipt = asyncio.run(
        engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION)
    )
    with pytest.raises(ValidationError):
        engine.store.save_boba_approval_control_receipt(
            PROJECT_ID, receipt.approval_decision_receipt_id, {"review_action_request_id": "x"}
        )


def test_reset_preserves_every_owner_history(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    engine.build_approval_controls(PROJECT_ID)
    result = engine.reset_approval_control_metadata(PROJECT_ID)
    for key in (
        "workflow_decision_history_preserved", "safety_gate_records_preserved",
        "final_decision_bus_records_preserved", "autopilot_history_preserved",
        "repair_history_preserved", "decision_receipt_history_preserved",
        "event_log_preserved", "review_ui_history_preserved",
    ):
        assert result[key] is True
    assert result["media_removed"] is False
    assert result["outputs_removed"] is False
    stored = engine.store.load_boba_approval_control_receipt_for_request(
        PROJECT_ID, request_id
    )
    assert stored is not None


def test_export_declares_its_exclusions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    privacy = engine.export_approval_controls(PROJECT_ID)["privacy"]
    for key in ("sensitive_values_excluded", "raw_commands_excluded", "private_paths_excluded",
                "raw_media_excluded", "reviewer_identity_bounded"):
        assert privacy[key] is True
    for key in ("execution_performed", "workflow_advanced", "safety_approval_granted",
                "upload_used", "publication_used"):
        assert privacy[key] is False


def test_aggregate_set_serialises(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    controls = engine.build_approval_controls(PROJECT_ID, "workflow_stage", "render")
    assert controls["schema_version"] == "boba_approval_controls_v1"
    assert isinstance(json.dumps(controls), str)
    assert controls["control_summary"]["approve_available"] is True


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def test_module_is_registered_read_only() -> None:
    module = build_boba_module_registry()["approval_controls"]
    assert module.read_only is True
    assert module.execution_capable is False


def test_fourteen_operations_registered() -> None:
    ops = {
        k.split(".", 1)[1]
        for k in build_boba_operation_registry()
        if k.startswith("approval_controls.")
    }
    assert len(ops) == 14
    assert "submit_decision" in ops
    assert not any("execute" in op for op in ops)


def test_submit_decision_requires_approval_and_safety() -> None:
    op = build_boba_operation_registry()["approval_controls.submit_decision"]
    assert op.target_approval_required is True
    assert op.safety_gate_required is True


def test_safety_gate_classifies_every_operation_read_only() -> None:
    ops = build_safety_module_operation_registry()["approval_controls"]
    assert len(ops) == 14
    assert set(ops.values()) <= {"automatic_read_only", "approval_required_read_only"}
    assert ops["submit_decision"] == "approval_required_read_only"


def test_review_ui_gating_is_unchanged() -> None:
    ui = build_fixed_review_action_registry()
    assert ui["review_action_safety_human_review_v1"].allowed_in_v1 is False
    assert ui["review_action_output_quality_human_review_v1"].allowed_in_v1 is False
    assert list(ui["review_action_workflow_human_decision_v1"].allowed_decision_values) == [
        "approve", "reject", "request_revision"
    ]


def test_package_exports_resolve() -> None:
    import olympus.boba as package

    for name in ("BobaApprovalControlsV1", "NOT_EXECUTION_NOTICE", "bounded_reason",
                 "build_fixed_approval_decision_registry"):
        assert name in package.__all__
        assert hasattr(package, name)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_api_registry_eligibility_and_controls(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get(f"{_base()}/registry").status_code == 200
    eligibility = client.get(f"{_base()}/eligibility", params={"target_type": "workflow_stage"})
    assert eligibility.status_code == 200
    assert eligibility.json()["approve_available"] is False
    assert client.get(_base()).status_code == 200


def test_api_history_events_and_export(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get(f"{_base()}/history").status_code == 200
    assert client.get(f"{_base()}/events").status_code == 200
    export = client.get(f"{_base()}/export")
    assert export.status_code == 200
    assert export.json()["privacy"]["execution_performed"] is False


def test_api_decision_rejects_unknown_kind(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        f"{_base()}/decisions",
        json={
            "approval_control_snapshot_id": "snap",
            "decision_kind": "execute",
            "idempotency_key": "idem_api_key",
            "confirmed": True,
        },
    )
    assert response.status_code == 422


def test_api_decision_rejects_forged_snapshot(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        f"{_base()}/decisions",
        json={
            "approval_control_snapshot_id": "approval_control_snapshot_forged",
            "decision_kind": "approve",
            "reason": "fine",
            "idempotency_key": "idem_api_key",
            "confirmed": True,
        },
    )
    assert 400 <= response.status_code < 500


def test_api_reset_preserves_owner_history(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.delete(_base())
    assert response.status_code == 200
    assert response.json()["workflow_decision_history_preserved"] is True


def test_api_unknown_project_is_client_error(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(
        "/api/v1/boba/projects/project-does-not-exist/approval-controls/registry"
    )
    assert 400 <= response.status_code < 500


# ---------------------------------------------------------------------------
# Timeline (read-only projection)
# ---------------------------------------------------------------------------
def test_timeline_is_truthful_when_empty(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, {})
    timeline = engine.inspect_approval_timeline(PROJECT_ID)
    assert timeline["empty"] is True
    assert timeline["entry_count"] == 0
    assert timeline["entries"] == []
    assert "No approval decision" in timeline["status"]


def test_timeline_never_mutates_or_duplicates_the_stream(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    timeline = engine.inspect_approval_timeline(PROJECT_ID)
    assert timeline["mutation_performed"] is False
    assert timeline["second_event_stream_created"] is False


def test_timeline_projects_control_events(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    entries = engine.inspect_approval_timeline(PROJECT_ID)["entries"]
    assert any(e["entry_kind"] == "approval_control_event" for e in entries)
    assert {e["event_type"] for e in entries} >= {"approval_requested", "approval_confirmed"}


def test_timeline_includes_owner_decision_records(tmp_path: Path) -> None:
    decided = _workflow()
    decided["human_decisions"] = [
        {"human_decision_id": "d1", "decision": "reject", "bounded_reason": "not ready",
         "decided_at": "2026-02-01T11:00:00+00:00", "workflow_revision": 3,
         "stage_instance_id": "render"}
    ]
    engine, _ = _engine(tmp_path, {"workflow_controller": decided, "safety_gate": _safety()})
    rows = [
        e for e in engine.inspect_approval_timeline(PROJECT_ID)["entries"]
        if e["entry_kind"] == "owner_decision_record"
    ]
    assert rows
    assert rows[0]["source_module_id"] == "workflow_controller"
    assert rows[0]["decision_value"] == "reject"
    assert rows[0]["timestamp_precision"] == "source"
    assert rows[0]["confirmed_order"] is True


def test_timeline_separates_owner_facts_from_presentation(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    for entry in engine.inspect_approval_timeline(PROJECT_ID)["entries"]:
        assert entry["owner_fact"] is True
        assert "derived_title" in entry
        assert "derived_summary" in entry


def test_timeline_ordering_is_deterministic(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    first = [
        e["timeline_entry_id"]
        for e in engine.inspect_approval_timeline(PROJECT_ID)["entries"]
    ]
    second = [
        e["timeline_entry_id"]
        for e in engine.inspect_approval_timeline(PROJECT_ID)["entries"]
    ]
    assert first == second


def test_timeline_output_is_bounded_and_reports_truncation(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    bounded = engine.inspect_approval_timeline(PROJECT_ID, limit=1)
    assert len(bounded["entries"]) == 1
    assert bounded["has_more"] is True
    assert bounded["total_available"] >= 2


def test_timeline_redacts_private_paths(tmp_path: Path) -> None:
    decided = _workflow()
    decided["human_decisions"] = [
        {"human_decision_id": "d1", "decision": "approve",
         "bounded_reason": "see /home/operator/secret.mp4",
         "decided_at": "2026-02-01T11:00:00+00:00"}
    ]
    engine, _ = _engine(tmp_path, {"workflow_controller": decided, "safety_gate": _safety()})
    assert "/home/operator" not in json.dumps(engine.inspect_approval_timeline(PROJECT_ID))


def test_timeline_entries_claim_no_side_effects(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    for entry in engine.inspect_approval_timeline(PROJECT_ID)["entries"]:
        assert entry["claims_execution"] is False
        assert entry["claims_workflow_advance"] is False
        assert entry["claims_safety_approval"] is False


def test_timeline_survives_reset_because_history_is_immutable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    request_id = _decide(engine)
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, APPROVE_DECISION))
    before = engine.inspect_approval_timeline(PROJECT_ID)["entry_count"]
    engine.reset_approval_control_metadata(PROJECT_ID)
    assert engine.inspect_approval_timeline(PROJECT_ID)["entry_count"] == before


@pytest.mark.parametrize(
    "field",
    ["claims_execution", "claims_workflow_advance", "claims_safety_approval"],
)
def test_timeline_contract_pins_no_claims(field: str) -> None:
    from olympus.boba.approval_controls import BobaApprovalTimelineEntryV1

    entry = BobaApprovalTimelineEntryV1(
        timeline_entry_id="t", project_id=PROJECT_ID,
        entry_kind="approval_control_event", source_module_id="approval_controls",
        source_record_id="e1",
    )
    assert getattr(entry, field) is False
    with pytest.raises(PydanticValidationError):
        BobaApprovalTimelineEntryV1(
            timeline_entry_id="t", project_id=PROJECT_ID,
            entry_kind="approval_control_event", source_module_id="approval_controls",
            source_record_id="e1", **{field: True},
        )


# ---------------------------------------------------------------------------
# Comparison (read-only projection)
# ---------------------------------------------------------------------------
def _two_decisions(engine: BobaApprovalControlsV1) -> tuple[str, str]:
    ids: list[str] = []
    for index, kind in enumerate((APPROVE_DECISION, REJECT_DECISION)):
        created = engine.create_approval_decision_request(
            PROJECT_ID, approval_control_snapshot_id=_snapshot_id(engine),
            decision_kind=kind, reason="Reviewed.",
            idempotency_key=f"idem_cmp_{index}_key", confirmed=True,
        )
        request_id = str(created["review_action_request_id"])
        asyncio.run(engine.submit_approval_decision(PROJECT_ID, request_id, kind))
        ids.append(request_id)
    return ids[0], ids[1]


def test_comparison_compares_same_target_decisions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    result = engine.compare_approval_decisions(PROJECT_ID, [first, second])["comparison"]
    assert result["compatible"] is True
    assert result["same_target_type"] is True
    assert result["same_target_id"] is True
    assert len(result["owner_fact_rows"]) == 2


def test_comparison_preserves_approve_versus_reject(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    result = engine.compare_approval_decisions(PROJECT_ID, [first, second])["comparison"]
    assert set(result["decision_kinds"]) == {"approve", "reject"}
    assert "decision_kind" in result["differing_fields"]


def test_comparison_preserves_stale_versus_current(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    first, _ = _two_decisions(engine)
    owner.stale = True
    created = engine.create_approval_decision_request(
        PROJECT_ID, approval_control_snapshot_id=_snapshot_id(engine),
        decision_kind=APPROVE_DECISION, reason="Reviewed.",
        idempotency_key="idem_cmp_stale_key", confirmed=True,
    )
    stale_id = str(created["review_action_request_id"])
    asyncio.run(engine.submit_approval_decision(PROJECT_ID, stale_id, APPROVE_DECISION))
    result = engine.compare_approval_decisions(PROJECT_ID, [first, stale_id])["comparison"]
    states = {row["derived_state"] for row in result["presentation_rows"]}
    assert "stale" in states
    assert "approved" in states


def test_comparison_reports_incompatible_targets_truthfully(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    stored = engine.store.load_boba_approval_control_receipt_for_request(PROJECT_ID, second)
    assert stored is not None
    forged = dict(stored)
    forged["approval_decision_receipt_id"] = "approval_decision_receipt_other"
    forged["review_action_request_id"] = "review_action_other"
    forged["target_id"] = "assemble"
    engine.store.save_boba_approval_control_receipt(
        PROJECT_ID, "approval_decision_receipt_other", forged
    )
    result = engine.compare_approval_decisions(
        PROJECT_ID, [first, "review_action_other"]
    )["comparison"]
    assert result["compatible"] is False
    assert result["same_target_id"] is False
    assert "do not refer to the same target" in result["incompatibility_reason"]


def test_comparison_requires_two_distinct_decisions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, _ = _two_decisions(engine)
    with pytest.raises(ValidationError):
        engine.compare_approval_decisions(PROJECT_ID, [first])
    with pytest.raises(ValidationError):
        engine.compare_approval_decisions(PROJECT_ID, [first, first])


def test_comparison_is_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    with pytest.raises(ValidationError):
        engine.compare_approval_decisions(PROJECT_ID, [first, second, "a", "b", "c"])


def test_comparison_collapses_duplicate_references(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    result = engine.compare_approval_decisions(
        PROJECT_ID, [first, first, second]
    )["comparison"]
    assert result["review_action_request_ids"] == [first, second]


def test_comparison_rejects_unknown_decision(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, _ = _two_decisions(engine)
    with pytest.raises(ValidationError):
        engine.compare_approval_decisions(PROJECT_ID, [first, "review_action_unknown"])


def test_comparison_rejects_cross_project_reference(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    with pytest.raises(ValidationError):
        engine.compare_approval_decisions("another-project", [first, second])


def test_comparison_rejects_malformed_reference(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, _ = _two_decisions(engine)
    with pytest.raises(ValidationError):
        engine.compare_approval_decisions(PROJECT_ID, [first, "bad id with spaces"])


def test_comparison_selects_no_winner_and_changes_nothing(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    result = engine.compare_approval_decisions(PROJECT_ID, [first, second])["comparison"]
    assert result["no_automatic_winner"] is True
    assert result["no_best_decision_inferred"] is True
    assert result["authority_changed"] is False
    assert result["mutation_performed"] is False
    assert result["approval_created"] is False
    assert result["safety_overridden"] is False


def test_comparison_output_is_deterministic(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first, second = _two_decisions(engine)
    a = engine.compare_approval_decisions(PROJECT_ID, [first, second])["comparison"]
    b = engine.compare_approval_decisions(PROJECT_ID, [first, second])["comparison"]
    assert a["comparison_id"] == b["comparison_id"]
    assert a["owner_fact_rows"] == b["owner_fact_rows"]
    assert a["differing_fields"] == b["differing_fields"]


def test_comparison_contract_pins_no_selection() -> None:
    from olympus.boba.approval_controls import BobaApprovalDecisionComparisonV1

    with pytest.raises(PydanticValidationError):
        BobaApprovalDecisionComparisonV1(
            comparison_id="c", project_id=PROJECT_ID,
            review_action_request_ids=["a", "b"], no_automatic_winner=False,
        )
    with pytest.raises(PydanticValidationError):
        BobaApprovalDecisionComparisonV1(
            comparison_id="c", project_id=PROJECT_ID,
            review_action_request_ids=["a", "b"], authority_changed=True,
        )


# ---------------------------------------------------------------------------
# API for both new surfaces
# ---------------------------------------------------------------------------
def test_api_timeline_route(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(f"{_base()}/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "boba_approval_controls_timeline_v1"
    assert body["mutation_performed"] is False
    assert body["empty"] is True


def test_api_timeline_respects_limit(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(f"{_base()}/timeline", params={"limit": 1})
    assert response.status_code == 200
    assert len(response.json()["entries"]) <= 1


def test_api_comparison_rejects_single_decision(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        f"{_base()}/comparison", json={"review_action_request_ids": ["a"]}
    )
    assert response.status_code == 422


def test_api_comparison_rejects_too_many_decisions(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        f"{_base()}/comparison",
        json={"review_action_request_ids": ["a", "b", "c", "d", "e"]},
    )
    assert response.status_code == 422


def test_api_comparison_rejects_unknown_decision(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        f"{_base()}/comparison",
        json={"review_action_request_ids": ["review_action_a", "review_action_b"]},
    )
    assert 400 <= response.status_code < 500


def test_api_timeline_and_comparison_unknown_project(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = "/api/v1/boba/projects/project-does-not-exist/approval-controls"
    assert 400 <= client.get(f"{base}/timeline").status_code < 500
    assert (
        400
        <= client.post(
            f"{base}/comparison",
            json={"review_action_request_ids": ["review_action_a", "review_action_b"]},
        ).status_code
        < 500
    )


def test_new_operations_are_registered_read_only() -> None:
    ops = build_boba_operation_registry()
    for name in (
        "approval_controls.inspect_timeline",
        "approval_controls.compare_decisions",
    ):
        assert ops[name].operation_class == "read_only"
        assert ops[name].target_approval_required is False
    safety = build_safety_module_operation_registry()["approval_controls"]
    assert safety["inspect_timeline"] == "automatic_read_only"
    assert safety["compare_decisions"] == "automatic_read_only"
