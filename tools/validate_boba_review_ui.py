"""Offline validation for BOBA Frontend / Review UI V1.

The tool uses only synthetic BOBA metadata under the ignored validation
workspace. It never executes a target, commands, Git, FFmpeg, validators,
repairs, workflow transitions, media work, network access, upload, publication,
push, merge, deployment, or source-owner decision mutation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from olympus.boba.integration_layer import build_boba_operation_registry
from olympus.boba.review_ui import (
    QUEUE_PRIORITY_TIERS,
    BobaReviewUiV1,
    build_fixed_review_action_registry,
    build_fixed_review_view_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError

_CONDITIONS = (
    "registry-is-fixed-source-code",
    "registry-snapshot-immutable",
    "unknown-action-rejected",
    "unavailable-action-rejected",
    "session-is-metadata-only",
    "session-expiry-enforced",
    "session-project-scoped",
    "session-update-field-allowlist",
    "queue-priority-deterministic",
    "queue-missing-source-not-a-pass",
    "queue-retains-source-identity",
    "queue-hides-historical-by-default",
    "snapshot-binds-project-digest",
    "snapshot-binds-workflow-revision",
    "snapshot-binds-target-digest",
    "snapshot-publishes-confirmation-token",
    "snapshot-project-scoped",
    "action-requires-explicit-confirmation",
    "action-requires-matching-token",
    "action-rejects-secret-bearing-reason",
    "action-rejects-unsupported-decision",
    "stale-project-snapshot-rejected",
    "workflow-revision-mismatch-rejected",
    "target-digest-mismatch-rejected",
    "source-record-digest-mismatch-rejected",
    "expired-action-rejected",
    "receipt-immutable",
    "receipt-idempotent-resubmission",
    "acknowledgement-changes-no-authority",
    "authority-change-requires-owner-record",
    "owner-rejection-recorded-truthfully",
    "events-deduplicated",
    "events-never-invent-progress",
    "timeline-marks-unknown-timestamps",
    "export-redacts-secrets",
    "export-excludes-private-paths",
    "reset-preserves-source-history",
    "no-arbitrary-module-or-operation",
    "safety-gate-registers-read-only",
    "integration-layer-operations-registered",
    "no-upload-or-publication-action",
    "no-execution-capable-action",
)

SCENARIO_NAMES = tuple(_CONDITIONS)


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str


def _future(seconds: int = 300) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _synthetic_records(project_id: str) -> dict[str, dict[str, Any]]:
    """Return synthetic canonical-looking owner records for projection."""
    return {
        "rights_permission_gate": {
            "schema_version": "boba_rights_permission_gate_v1",
            "project_id": project_id,
            "status": "allowed",
            "decision": "allow",
            "summary": "Rights cleared for the registered source.",
        },
        "safety_gate": {
            "schema_version": "boba_safety_gate_v1",
            "project_id": project_id,
            "status": "human_review_required",
            "decision": "human_review_required",
            "summary": "Safety requires an exact human review.",
            "human_review_required": True,
            "approval_required": True,
        },
        "workflow_controller": {
            "schema_version": "boba_workflow_controller_v1",
            "project_id": project_id,
            "source_record_id": "wfc_synthetic_record_1",
            "status": "human_review_required",
            "summary": "A stage is waiting on a human decision.",
            "human_review_required": True,
            "approval_required": True,
            "workflow_runs": [
                {
                    "workflow_run_id": "wfr_synthetic_1",
                    "revision": 7,
                    "updated_at": "2026-08-05T10:00:00+00:00",
                    "current_stage_instance_id": "stage_synthetic_1",
                }
            ],
            "events": [
                {
                    "event_id": "wf_ev_1",
                    "sequence": 1,
                    "event_type": "human_review_required",
                    "severity": "warning",
                    "created_at": "2026-08-05T10:00:00+00:00",
                    "summary": "Waiting on a human decision.",
                    "confirmed_fact": "No stage was executed.",
                },
                {
                    "event_id": "wf_ev_1",
                    "sequence": 1,
                    "event_type": "human_review_required",
                    "severity": "warning",
                    "created_at": "2026-08-05T10:00:00+00:00",
                    "summary": "Duplicate replay of the same source event.",
                },
                {
                    "event_id": "wf_ev_2",
                    "sequence": 2,
                    "event_type": "stage_progress",
                    "severity": "info",
                    "summary": "Progress without a timestamp.",
                    "progress_current": 2,
                    "progress_total": 4,
                },
                {
                    "event_id": "wf_ev_3",
                    "sequence": 3,
                    "event_type": "stage_progress",
                    "severity": "info",
                    "created_at": "2026-08-05T10:05:00+00:00",
                    "summary": "Malformed counters must not become progress.",
                    "progress_current": 5,
                    "progress_total": 0,
                },
            ],
        },
        "validator_runner": {
            "schema_version": "boba_validator_runner_v1",
            "project_id": project_id,
            "status": "failed",
            "summary": "Technical validation failed for the rendered output.",
            "blocking": True,
        },
        "output_quality_reviewer": {
            "schema_version": "boba_output_quality_reviewer_v1",
            "project_id": project_id,
            "status": "awaiting_human_review",
            "summary": "Output quality needs a human decision.",
            "human_review_required": True,
        },
        "artifact_inspector": {
            "schema_version": "boba_artifact_inspector_v1",
            "project_id": project_id,
            "status": "stale",
            "summary": "Artifacts are stale.",
            "stale": True,
        },
        "report_reader": {
            "schema_version": "boba_report_reader_v1",
            "project_id": project_id,
            "status": "read",
            "summary": "Reports were read.",
            "api_token": "sk-should-be-redacted",
            "media_path": "C:\\Olympus\\work\\output.mp4",
        },
        "tool_recovery": {
            "schema_version": "boba_tool_recovery_v1",
            "project_id": project_id,
            "status": "recovery_hold",
            "summary": "A recovery hold is open.",
            "recovery_holds": [{"hold_id": "hold_1"}],
        },
        "autopilot_controller": {
            "schema_version": "boba_autopilot_controller_v1",
            "project_id": project_id,
            "status": "paused",
            "summary": "Autopilot is paused.",
        },
        "integration_layer": {
            "schema_version": "boba_integration_layer_v1",
            "project_id": project_id,
            "status": "available",
            "summary": "Integration layer is available.",
        },
        "final_decision_bus": {
            "schema_version": "boba_final_decision_bus_v1",
            "project_id": project_id,
            "status": "hold",
            "summary": "The Final Decision Bus is holding on a conflict.",
            "blocking": True,
            "conflicts": [{"conflict_id": "c1"}],
        },
    }


class _StubWorkflowController:
    """Records a canonical human decision exactly as the real owner would."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reject = False

    def record_human_workflow_decision(
        self,
        project_id: str,
        workflow_run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.reject:
            raise ValidationError("The requested human authority is unavailable.")
        self.calls.append({"project_id": project_id, "run": workflow_run_id, **kwargs})
        return {
            "human_decision_id": f"wf_decision_{len(self.calls)}",
            "workflow_run_id": workflow_run_id,
            "project_id": project_id,
            "decision": str(kwargs.get("decision") or ""),
            "workflow_revision": int(kwargs.get("expected_revision") or 0) + 1,
        }


class _StubIntegration:
    def __init__(self) -> None:
        self.workflow_controller = _StubWorkflowController()


class SyntheticReviewUi(BobaReviewUiV1):
    """Project synthetic owner records without touching real module storage."""

    def __init__(self, store: BobaMemoryStore, records: dict[str, dict[str, Any]]) -> None:
        stub = _StubIntegration()
        super().__init__(store, stub)  # type: ignore[arg-type]
        self.records = records
        self.controller = stub.workflow_controller

    def _source_payload(self, module_id: str, project_id: str) -> dict[str, Any]:
        return dict(self.records.get(module_id, {}))


def _harness(root: Path, project_id: str) -> SyntheticReviewUi:
    return SyntheticReviewUi(
        BobaMemoryStore(root / project_id), _synthetic_records(project_id)
    )


def _prepared(
    engine: SyntheticReviewUi,
    project_id: str,
    *,
    target_module: str = "workflow_controller",
) -> tuple[Any, dict[str, Any]]:
    session = engine.create_review_session(project_id, reviewer_context_id="reviewer_a")
    cards = engine._source_cards(project_id)
    card = next(item for item in cards if item.source_module_id == target_module)
    target = engine._target_from_card(project_id, card, cards)
    payload = engine.build_review_snapshot(
        project_id, session.review_session_id, target.review_target_id
    )
    return session, payload


def _check(name: str, passed: bool, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, passed=passed, detail=detail)


def run_named_scenario(name: str, root: Path) -> ScenarioResult:
    project_id = "proj_review_ui_validation"
    engine = _harness(root / name, project_id)

    if name == "registry-is-fixed-source-code":
        views = build_fixed_review_view_registry()
        actions = build_fixed_review_action_registry()
        ok = len(views) == 13 and len(actions) == 4
        return _check(name, ok, f"{len(views)} views and {len(actions)} fixed actions.")

    if name == "registry-snapshot-immutable":
        registry_a = engine.build_review_ui_registry(project_id)
        registry_b = engine.build_review_ui_registry(project_id)
        ok = registry_a["registry_snapshot"] == registry_b["registry_snapshot"]
        return _check(name, ok, "Content-addressed registry snapshot is reused.")

    if name == "unknown-action-rejected":
        session, payload = _prepared(engine, project_id)
        try:
            engine.create_review_action_request(
                project_id,
                review_session_id=session.review_session_id,
                review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
                action_descriptor_id="review_action_not_real_v1",
                decision_value=None,
                reason="x",
                confirmation_context_digest="0" * 64,
                idempotency_key="idem_unknown",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "Unknown" in str(error), str(error))
        return _check(name, False, "An unknown action descriptor was accepted.")

    if name == "unavailable-action-rejected":
        session, payload = _prepared(engine, project_id)
        try:
            engine.create_review_action_request(
                project_id,
                review_session_id=session.review_session_id,
                review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
                action_descriptor_id="review_action_safety_human_review_v1",
                decision_value="deny_action",
                reason="Reason",
                confirmation_context_digest="0" * 64,
                idempotency_key="idem_unavailable",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "unavailable" in str(error).lower(), str(error))
        return _check(name, False, "An unavailable V1 action was accepted.")

    if name == "session-is-metadata-only":
        session = engine.create_review_session(project_id, reviewer_context_id="reviewer_a")
        limitations = " ".join(session.limitations).lower()
        ok = "not approvals" in limitations
        return _check(name, ok, "Sessions disclose that they are not approvals.")

    if name == "session-expiry-enforced":
        session = engine.create_review_session(
            project_id, reviewer_context_id="reviewer_a", expires_in_seconds=60
        )
        raw = engine.store.load_boba_review_ui_session(project_id, session.review_session_id)
        assert raw is not None
        raw["expires_at"] = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        engine.store.save_boba_review_ui_session(project_id, session.review_session_id, raw)
        try:
            engine.get_review_session(project_id, session.review_session_id)
        except ValidationError as error:
            return _check(name, "expired" in str(error).lower(), str(error))
        return _check(name, False, "An expired session was accepted.")

    if name == "session-project-scoped":
        session = engine.create_review_session(project_id, reviewer_context_id="reviewer_a")
        try:
            engine.get_review_session("proj_other", session.review_session_id)
        except ValidationError as error:
            return _check(name, True, str(error))
        return _check(name, False, "A session was readable from another project.")

    if name == "session-update-field-allowlist":
        session = engine.create_review_session(project_id, reviewer_context_id="reviewer_a")
        try:
            engine.update_review_preferences(
                project_id, session.review_session_id, {"reviewer_context_id": "someone_else"}
            )
        except ValidationError as error:
            return _check(name, "unsupported" in str(error).lower(), str(error))
        return _check(name, False, "An unsupported session field was accepted.")

    if name == "queue-priority-deterministic":
        first = engine.build_review_queue(project_id)["items"]
        second = engine.build_review_queue(project_id)["items"]
        priorities = [item["priority"] for item in first]
        ok = (
            [item["queue_item_id"] for item in first]
            == [item["queue_item_id"] for item in second]
            and priorities == sorted(priorities)
            and len(QUEUE_PRIORITY_TIERS) == 12
        )
        return _check(name, ok, f"Twelve tiers; order {priorities}.")

    if name == "queue-missing-source-not-a-pass":
        empty = SyntheticReviewUi(BobaMemoryStore(root / name / "empty"), {})
        cards = empty._source_cards(project_id)
        ok = bool(cards) and all(
            card.original_status == "unavailable" and not card.current for card in cards
        )
        return _check(name, ok, f"{len(cards)} unavailable cards are never passes.")

    if name == "queue-retains-source-identity":
        items = engine.build_review_queue(project_id)["items"]
        ok = all(
            item["source_module_ids"]
            and item["source_record_ids"]
            and item["source_record_digests"]
            and item["primary_reason"]
            for item in items
        )
        return _check(name, ok, "Every queue item keeps module, record and digest.")

    if name == "queue-hides-historical-by-default":
        records = _synthetic_records(project_id)
        records["report_reader"]["superseded"] = True
        engine.records = records
        default = engine.build_review_queue(project_id)["items"]
        including = engine.build_review_queue(project_id, include_historical=True)["items"]
        ok = len(including) > len(default)
        return _check(name, ok, f"{len(default)} default, {len(including)} with history.")

    if name in {
        "snapshot-binds-project-digest",
        "snapshot-binds-workflow-revision",
        "snapshot-binds-target-digest",
    }:
        _, payload = _prepared(engine, project_id)
        snapshot = payload["snapshot"]
        ok = (
            len(snapshot["project_snapshot_digest"]) == 64
            and snapshot["workflow_revision"] == 7
            and len(snapshot["target_digest"]) == 64
        )
        return _check(name, ok, f"Revision {snapshot['workflow_revision']} bound with digests.")

    if name == "snapshot-publishes-confirmation-token":
        _, payload = _prepared(engine, project_id)
        tokens = payload["action_confirmations"]
        offered = payload["snapshot"]["available_action_descriptor_ids"]
        ok = bool(offered) and all(len(tokens.get(item, "")) == 64 for item in offered)
        return _check(name, ok, f"{len(tokens)} bound confirmation tokens.")

    if name == "snapshot-project-scoped":
        _, payload = _prepared(engine, project_id)
        try:
            engine._snapshot("proj_other", payload["snapshot"]["review_snapshot_id"])
        except ValidationError as error:
            return _check(name, True, str(error))
        return _check(name, False, "A snapshot was readable from another project.")

    if name == "action-requires-explicit-confirmation":
        session, payload = _prepared(engine, project_id)
        token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
        try:
            engine.create_review_action_request(
                project_id,
                review_session_id=session.review_session_id,
                review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
                action_descriptor_id="review_action_workflow_human_decision_v1",
                decision_value="approve",
                reason="Reviewed the exact stage.",
                confirmation_context_digest=token,
                idempotency_key="idem_unconfirmed",
                confirmed=False,
            )
        except ValidationError as error:
            return _check(name, "confirmation" in str(error).lower(), str(error))
        return _check(name, False, "An unconfirmed action was accepted.")

    if name == "action-requires-matching-token":
        session, payload = _prepared(engine, project_id)
        try:
            engine.create_review_action_request(
                project_id,
                review_session_id=session.review_session_id,
                review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
                action_descriptor_id="review_action_workflow_human_decision_v1",
                decision_value="approve",
                reason="Reviewed the exact stage.",
                confirmation_context_digest="f" * 64,
                idempotency_key="idem_badtoken",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "confirmation" in str(error).lower(), str(error))
        return _check(name, False, "A mismatched confirmation token was accepted.")

    if name == "action-rejects-secret-bearing-reason":
        session, payload = _prepared(engine, project_id)
        token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
        try:
            engine.create_review_action_request(
                project_id,
                review_session_id=session.review_session_id,
                review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
                action_descriptor_id="review_action_workflow_human_decision_v1",
                decision_value="approve",
                reason="token=sk-abc123 approved",
                confirmation_context_digest=token,
                idempotency_key="idem_secret_1",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "credential" in str(error).lower(), str(error))
        return _check(name, False, "A secret-bearing reason was accepted.")

    if name == "action-rejects-unsupported-decision":
        session, payload = _prepared(engine, project_id)
        token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
        try:
            engine.create_review_action_request(
                project_id,
                review_session_id=session.review_session_id,
                review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
                action_descriptor_id="review_action_workflow_human_decision_v1",
                decision_value="authorize_upload",
                reason="Reviewed.",
                confirmation_context_digest=token,
                idempotency_key="idem_baddecision",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "decision value" in str(error).lower(), str(error))
        return _check(name, False, "An unsupported decision value was accepted.")

    if name in {
        "stale-project-snapshot-rejected",
        "workflow-revision-mismatch-rejected",
        "target-digest-mismatch-rejected",
        "source-record-digest-mismatch-rejected",
    }:
        session, payload = _prepared(engine, project_id)
        token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
        request = engine.create_review_action_request(
            project_id,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="approve",
            reason="Reviewed the exact stage.",
            confirmation_context_digest=token,
            idempotency_key=f"idem_{name}",
            confirmed=True,
        )
        drifted = _synthetic_records(project_id)
        if name == "workflow-revision-mismatch-rejected":
            drifted["workflow_controller"]["workflow_runs"][0]["revision"] = 99
        else:
            drifted["workflow_controller"]["summary"] = "The canonical record moved on."
        engine.records = drifted
        result = engine.validate_review_action_request(
            project_id, request.review_action_request_id
        )
        receipt = asyncio.run(
            engine.submit_review_action_to_owner(project_id, request.review_action_request_id)
        )
        ok = (
            not result["valid"]
            and receipt.stale_state_rejected
            and not receipt.authoritative_state_changed
            and not engine.controller.calls
        )
        return _check(name, ok, f"Rejected as {result['code']}; owner never contacted.")

    if name == "expired-action-rejected":
        session, payload = _prepared(engine, project_id)
        token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
        request = engine.create_review_action_request(
            project_id,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="approve",
            reason="Reviewed.",
            confirmation_context_digest=token,
            idempotency_key="idem_expired",
            confirmed=True,
        )
        raw = engine.store.load_boba_review_ui_action(
            project_id, request.review_action_request_id
        )
        assert raw is not None
        raw["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        path = engine.store.boba_review_ui_action_path(
            project_id, request.review_action_request_id
        )
        path.write_text(json.dumps(raw), encoding="utf-8")
        result = engine.validate_review_action_request(
            project_id, request.review_action_request_id
        )
        ok = not result["valid"] and result["code"] == "expired_snapshot"
        return _check(name, ok, f"Expired action rejected as {result['code']}.")

    if name in {
        "receipt-immutable",
        "receipt-idempotent-resubmission",
        "authority-change-requires-owner-record",
    }:
        session, payload = _prepared(engine, project_id)
        token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
        request = engine.create_review_action_request(
            project_id,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="approve",
            reason="Reviewed the exact stage.",
            confirmation_context_digest=token,
            idempotency_key="idem_ok_submit_1",
            confirmed=True,
        )
        owner_receipt = asyncio.run(
            engine.submit_review_action_to_owner(project_id, request.review_action_request_id)
        )
        repeat_receipt = asyncio.run(
            engine.submit_review_action_to_owner(project_id, request.review_action_request_id)
        )
        if name == "receipt-idempotent-resubmission":
            ok = (
                repeat_receipt.duplicate_request_reused
                and repeat_receipt.action_receipt_id == owner_receipt.action_receipt_id
                and len(engine.controller.calls) == 1
            )
            return _check(name, ok, "The owner was contacted exactly once.")
        if name == "receipt-immutable":
            try:
                engine.store.save_boba_review_ui_receipt(
                    project_id,
                    owner_receipt.action_receipt_id,
                    {**owner_receipt.model_dump(mode="json"), "canonical_status": "tampered"},
                )
            except ValidationError as error:
                return _check(name, "immutable" in str(error).lower(), str(error))
            return _check(name, False, "A receipt was mutated.")
        ok = (
            owner_receipt.authoritative_state_changed
            and bool(owner_receipt.canonical_record_id)
            and bool(owner_receipt.canonical_record_digest)
            and owner_receipt.accepted_by_owner
        )
        return _check(name, ok, f"Owner returned {owner_receipt.canonical_record_id}.")

    if name == "owner-rejection-recorded-truthfully":
        session, payload = _prepared(engine, project_id)
        token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
        request = engine.create_review_action_request(
            project_id,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="approve",
            reason="Reviewed.",
            confirmation_context_digest=token,
            idempotency_key="idem_reject_1",
            confirmed=True,
        )
        engine.controller.reject = True
        receipt = asyncio.run(
            engine.submit_review_action_to_owner(project_id, request.review_action_request_id)
        )
        ok = (
            not receipt.accepted_by_owner
            and not receipt.authoritative_state_changed
            and receipt.error_code == "owner_rejected"
        )
        return _check(name, ok, "Owner rejection recorded without implying success.")

    if name == "acknowledgement-changes-no-authority":
        session = engine.create_review_session(project_id, reviewer_context_id="reviewer_a")
        cards = engine._source_cards(project_id)
        notifications = engine._notifications(project_id, cards)
        updated = engine.acknowledge_review_notification(
            project_id, session.review_session_id, notifications[0].notification_id
        )
        after = engine._source_cards(project_id)
        ok = (
            notifications[0].notification_id in updated.acknowledged_notification_ids
            and [card.original_status for card in after]
            == [card.original_status for card in cards]
        )
        return _check(name, ok, "Acknowledgement touched only session metadata.")

    if name == "events-deduplicated":
        events = engine.inspect_review_events(project_id)["events"]
        keys = [(item["source_module_id"], item["source_event_id"]) for item in events]
        ok = len(keys) == len(set(keys)) and len(events) == 3
        return _check(name, ok, f"{len(events)} unique canonical events from 4 rows.")

    if name == "events-never-invent-progress":
        events = engine.inspect_review_events(project_id)["events"]
        real = [item for item in events if item["progress_percent"] is not None]
        malformed = [
            item
            for item in events
            if item["progress_total"] == 0 and item["progress_percent"] is not None
        ]
        ok = len(real) == 1 and real[0]["progress_percent"] == 50.0 and not malformed
        return _check(name, ok, "Only real counters became progress.")

    if name == "timeline-marks-unknown-timestamps":
        entries = engine.inspect_review_timeline(project_id)["entries"]
        unknown = [item for item in entries if item["timestamp_precision"] == "unknown"]
        ok = any(item["confirmed_order"] is not None for item in entries) and bool(unknown)
        return _check(name, ok, f"{len(unknown)} entries disclose unknown timestamps.")

    if name in {"export-redacts-secrets", "export-excludes-private-paths"}:
        exported = json.dumps(engine.export_review_ui(project_id))
        ok = "sk-should-be-redacted" not in exported and "C:\\Olympus" not in exported
        return _check(name, ok, "Export carries no secrets and no private paths.")

    if name == "reset-preserves-source-history":
        engine.build_review_ui(project_id)
        result = engine.reset_review_ui_metadata(project_id)
        ok = all(
            result.get(key)
            for key in (
                "source_records_preserved",
                "workflow_history_preserved",
                "validation_history_preserved",
                "quality_history_preserved",
                "artifact_history_preserved",
                "final_decision_history_preserved",
            )
        ) and not result.get("source_media_removed", True)
        return _check(name, ok, "Reset removed only Review UI metadata.")

    if name == "no-arbitrary-module-or-operation":
        registry = build_fixed_review_action_registry()
        allowed_modules = {
            "review_ui",
            "workflow_controller",
            "output_quality_reviewer",
            "safety_gate",
        }
        ok = all(item.owning_module_id in allowed_modules for item in registry.values())
        source = Path("src/olympus/boba/review_ui.py").read_text(encoding="utf-8")
        forbidden = ("importlib", "subprocess", "eval(", "exec(", "getattr(request")
        ok = ok and not any(token in source for token in forbidden)
        return _check(name, ok, "Only fixed modules; no dynamic import or execution.")

    if name == "safety-gate-registers-read-only":
        operations = build_safety_module_operation_registry().get("review_ui", {})
        ok = (
            len(operations) == 18
            and operations["submit_action"] == "approval_required_read_only"
            and sum(1 for v in operations.values() if v == "automatic_read_only") == 17
        )
        return _check(name, ok, "Safety Gate classes are read-only or approval-gated.")

    if name == "integration-layer-operations-registered":
        registered = {
            item for item in build_boba_operation_registry() if item.startswith("review_ui.")
        }
        expected = {
            f"review_ui.{item}"
            for item in (
                "inspect_registry",
                "create_session",
                "update_session",
                "build_queue",
                "inspect_queue",
                "build_snapshot",
                "refresh_snapshot",
                "inspect_target",
                "create_action",
                "validate_action",
                "submit_action",
                "inspect_receipt",
                "inspect_timeline",
                "inspect_events",
                "acknowledge_notification",
                "load",
                "export",
                "reset",
            )
        }
        ok = expected == registered
        return _check(name, ok, f"{len(registered)} fixed operations registered.")

    if name == "no-upload-or-publication-action":
        registry = build_fixed_review_action_registry()
        ok = not any(item.upload_or_publication for item in registry.values())
        return _check(name, ok, "No action can upload or publish.")

    if name == "no-execution-capable-action":
        registry = build_fixed_review_action_registry()
        ok = not any(
            item.execution_capable or item.destructive for item in registry.values()
        )
        return _check(name, ok, "No action executes or destroys.")

    return _check(name, False, "Unknown scenario.")


def run_self_check() -> dict[str, Any]:
    views = build_fixed_review_view_registry()
    actions = build_fixed_review_action_registry()
    checks = {
        "scenario_catalog_complete": len(SCENARIO_NAMES) >= 40,
        "scenario_names_unique": len(set(SCENARIO_NAMES)) == len(SCENARIO_NAMES),
        "view_registry_fixed": len(views) == 13,
        "action_registry_fixed": len(actions) == 4,
        "priority_tiers_complete": len(QUEUE_PRIORITY_TIERS) == 12,
        "priority_tiers_ascending": [tier[0] for tier in QUEUE_PRIORITY_TIERS]
        == sorted(tier[0] for tier in QUEUE_PRIORITY_TIERS),
        "no_upload_or_publication": not any(
            item.upload_or_publication for item in actions.values()
        ),
        "no_execution_capable": not any(item.execution_capable for item in actions.values()),
        "every_action_names_owner": all(
            item.owning_module_id and item.owning_operation_id for item in actions.values()
        ),
        "safety_registration_present": "review_ui" in build_safety_module_operation_registry(),
        "integration_layer_registration_present": any(
            item.startswith("review_ui.") for item in build_boba_operation_registry()
        ),
    }
    return {
        "schema_version": "boba_review_ui_validation_self_check_v1",
        "passed": all(checks.values()),
        "checks": checks,
        "scenario_count": len(SCENARIO_NAMES),
        "conditions": list(_CONDITIONS),
    }


def run_synthetic_project(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    results = [run_named_scenario(name, root) for name in SCENARIO_NAMES]
    failed = [item.name for item in results if not item.passed]
    return {
        "schema_version": "boba_review_ui_validation_synthetic_v1",
        "passed": not failed,
        "scenario_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_scenarios": failed,
        "scenarios": [
            {"name": item.name, "passed": item.passed, "detail": item.detail}
            for item in results
        ],
        "guarantees": {
            "target_execution_performed": False,
            "commands_executed": False,
            "network_access_used": False,
            "media_modified": False,
            "upload_used": False,
            "publication_used": False,
            "source_owner_decisions_mutated": False,
        },
    }


def inspect_persisted_project(project_id: str) -> dict[str, Any]:
    store = BobaMemoryStore(Path("storage_data") / "boba")
    existing = store.load_boba_review_ui(project_id)
    return {
        "schema_version": "boba_review_ui_validation_project_v1",
        "passed": existing is not None,
        "project_id": project_id,
        "review_ui_present": existing is not None,
        "queue_item_count": len(existing.get("review_queue_items", [])) if existing else 0,
    }


def _write_report(name: str, payload: dict[str, Any]) -> Path:
    root = Path("work") / "validation_reports" / "boba_review_ui"
    root.mkdir(parents=True, exist_ok=True)
    report = root / (name + ".json")
    report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--synthetic-project", action="store_true")
    parser.add_argument("--project-id", default="")
    arguments = parser.parse_args()
    selected = sum(
        1
        for value in (
            arguments.self_check,
            arguments.synthetic_project,
            arguments.project_id,
        )
        if value
    )
    if selected != 1:
        parser.error("Select exactly one of --self-check, --synthetic-project, or --project-id.")
    if arguments.self_check:
        payload = run_self_check()
        report = _write_report("self_check", payload)
    elif arguments.synthetic_project:
        with tempfile.TemporaryDirectory(prefix="boba_review_ui_") as temporary:
            payload = run_synthetic_project(Path(temporary))
        report = _write_report("synthetic_project", payload)
    else:
        payload = inspect_persisted_project(arguments.project_id)
        report = _write_report("project_" + arguments.project_id, payload)
    print(json.dumps({"report": str(report), **payload}, indent=2, sort_keys=True))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
