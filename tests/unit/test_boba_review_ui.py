"""BOBA Frontend / Review UI V1 contracts, projection, routing, API and validator tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from tools.validate_boba_review_ui import (
    SCENARIO_NAMES,
    SyntheticReviewUi,
    _synthetic_records,
    run_named_scenario,
    run_self_check,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import build_boba_operation_registry
from olympus.boba.review_ui import (
    QUEUE_PRIORITY_TIERS,
    BobaReviewActionDescriptorV1,
    BobaReviewActionReceiptV1,
    BobaReviewActionRequestV1,
    BobaReviewNotificationV1,
    BobaReviewQueueItemV1,
    BobaReviewSectionV1,
    BobaReviewSessionV1,
    BobaReviewSnapshotV1,
    BobaReviewSourceCardV1,
    BobaReviewTargetV1,
    BobaReviewTimelineEntryV1,
    BobaReviewUiEventV1,
    BobaReviewUiRegistrySnapshotV1,
    BobaReviewUiSetV1,
    BobaReviewUiSignalUsageV1,
    BobaReviewUiSummaryV1,
    BobaReviewViewDescriptorV1,
    build_fixed_review_action_registry,
    build_fixed_review_view_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError, register_exception_handlers
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_review_ui_test"

CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaReviewUiRegistrySnapshotV1,
    BobaReviewViewDescriptorV1,
    BobaReviewActionDescriptorV1,
    BobaReviewSessionV1,
    BobaReviewQueueItemV1,
    BobaReviewTargetV1,
    BobaReviewSnapshotV1,
    BobaReviewSourceCardV1,
    BobaReviewSectionV1,
    BobaReviewActionRequestV1,
    BobaReviewActionReceiptV1,
    BobaReviewTimelineEntryV1,
    BobaReviewNotificationV1,
    BobaReviewUiEventV1,
    BobaReviewUiSummaryV1,
    BobaReviewUiSignalUsageV1,
    BobaReviewUiSetV1,
)


def _engine(tmp_path: Path) -> SyntheticReviewUi:
    return SyntheticReviewUi(
        BobaMemoryStore(tmp_path / "boba"), _synthetic_records(PROJECT_ID)
    )


def _prepared(engine: SyntheticReviewUi) -> tuple[BobaReviewSessionV1, dict[str, Any]]:
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    cards = engine._source_cards(PROJECT_ID)
    card = next(item for item in cards if item.source_module_id == "workflow_controller")
    target = engine._target_from_card(PROJECT_ID, card, cards)
    payload = engine.build_review_snapshot(
        PROJECT_ID, session.review_session_id, target.review_target_id
    )
    return session, payload


def _submit(engine: SyntheticReviewUi) -> BobaReviewActionReceiptV1:
    session, payload = _prepared(engine)
    token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
    request = engine.create_review_action_request(
        PROJECT_ID,
        review_session_id=session.review_session_id,
        review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
        action_descriptor_id="review_action_workflow_human_decision_v1",
        decision_value="approve",
        reason="Reviewed the exact stage.",
        confirmation_context_digest=token,
        idempotency_key="idem_test_submit",
        confirmed=True,
    )
    return asyncio.run(
        engine.submit_review_action_to_owner(PROJECT_ID, request.review_action_request_id)
    )


# ---------------------------------------------------------------------------
# Contracts and registries
# ---------------------------------------------------------------------------
def test_contracts_forbid_unknown_fields() -> None:
    for contract in CONTRACT_TYPES:
        assert contract.model_config.get("extra") == "forbid", contract.__name__


def test_view_registry_is_fixed_and_unique() -> None:
    views = build_fixed_review_view_registry()
    assert len(views) == 13
    assert len({item.review_mode for item in views.values()}) == 13
    for descriptor in views.values():
        assert descriptor.required_identity_fields
        assert "workflow_controller" in descriptor.required_source_modules


def test_action_registry_names_an_exact_owner_for_every_action() -> None:
    actions = build_fixed_review_action_registry()
    assert len(actions) == 4
    for descriptor in actions.values():
        assert descriptor.owning_module_id
        assert descriptor.owning_operation_id
        assert not descriptor.upload_or_publication
        assert not descriptor.execution_capable
        assert not descriptor.destructive


def test_authoritative_actions_require_confirmation_and_identity() -> None:
    actions = build_fixed_review_action_registry()
    workflow = actions["review_action_workflow_human_decision_v1"]
    assert workflow.owning_module_id == "workflow_controller"
    assert workflow.owning_operation_id == "record_human_workflow_decision"
    assert workflow.requires_confirmation
    assert workflow.requires_current_snapshot
    assert workflow.requires_workflow_revision
    assert workflow.requires_target_digest
    assert workflow.requires_human_identity
    assert "authorize_upload" not in workflow.allowed_decision_values


def test_registry_snapshot_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = engine.build_review_ui_registry(PROJECT_ID)
    second = engine.build_review_ui_registry(PROJECT_ID)
    assert first["registry_snapshot"] == second["registry_snapshot"]
    snapshot_id = first["registry_snapshot"]["registry_snapshot_id"]
    with pytest.raises(ValidationError, match="immutable"):
        engine.store.save_boba_review_ui_registry(
            PROJECT_ID, snapshot_id, {"registry_snapshot_id": snapshot_id, "tampered": True}
        )


# ---------------------------------------------------------------------------
# Sessions and preferences
# ---------------------------------------------------------------------------
def test_session_holds_ui_state_only(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    assert session.project_id == PROJECT_ID
    assert any("not approvals" in item for item in session.limitations)


def test_session_rejects_credential_bearing_reviewer_context(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with pytest.raises(ValidationError, match="credentials"):
        engine.create_review_session(PROJECT_ID, reviewer_context_id="token_abc")


def test_expired_session_is_refused(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    raw = engine.store.load_boba_review_ui_session(PROJECT_ID, session.review_session_id)
    assert raw is not None
    raw["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    engine.store.save_boba_review_ui_session(PROJECT_ID, session.review_session_id, raw)
    with pytest.raises(ValidationError, match="expired"):
        engine.get_review_session(PROJECT_ID, session.review_session_id)


def test_session_is_project_scoped(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    with pytest.raises(ValidationError):
        engine.get_review_session("proj_other", session.review_session_id)


def test_preferences_update_uses_a_field_allowlist(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    updated = engine.update_review_preferences(
        PROJECT_ID, session.review_session_id, {"active_tab": "evidence", "compact_mode": True}
    )
    assert updated.active_tab == "evidence"
    assert updated.compact_mode is True
    with pytest.raises(ValidationError, match="unsupported"):
        engine.update_review_preferences(
            PROJECT_ID, session.review_session_id, {"session_digest": "0" * 64}
        )


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------
def test_queue_exposes_twelve_priority_tiers_in_order() -> None:
    assert len(QUEUE_PRIORITY_TIERS) == 12
    priorities = [tier[0] for tier in QUEUE_PRIORITY_TIERS]
    assert priorities == sorted(priorities)
    assert len({tier[1] for tier in QUEUE_PRIORITY_TIERS}) == 12


def test_queue_is_deterministic_and_priority_ordered(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = engine.build_review_queue(PROJECT_ID)["items"]
    second = engine.build_review_queue(PROJECT_ID)["items"]
    assert [item["queue_item_id"] for item in first] == [
        item["queue_item_id"] for item in second
    ]
    priorities = [item["priority"] for item in first]
    assert priorities == sorted(priorities)


def test_rights_and_safety_blocks_outrank_everything(tmp_path: Path) -> None:
    records = _synthetic_records(PROJECT_ID)
    records["safety_gate"] = {
        "schema_version": "boba_safety_gate_v1",
        "project_id": PROJECT_ID,
        "status": "blocked_safety_policy",
        "decision": "deny",
        "summary": "Safety blocked the action.",
        "blocking": True,
    }
    engine = SyntheticReviewUi(BobaMemoryStore(tmp_path / "boba"), records)
    top = engine.build_review_queue(PROJECT_ID)["items"][0]
    assert top["priority"] == 10
    assert top["primary_reason"] == "rights_or_safety_critical_block"
    assert top["display_category"] == "critical_attention"


def test_protected_asset_incident_is_second_tier(tmp_path: Path) -> None:
    records = _synthetic_records(PROJECT_ID)
    records["report_reader"]["incidents"] = [{"incident_type": "accepted_output_protection"}]
    engine = SyntheticReviewUi(BobaMemoryStore(tmp_path / "boba"), records)
    item = next(
        entry
        for entry in engine.build_review_queue(PROJECT_ID)["items"]
        if entry["source_module_ids"] == ["report_reader"]
    )
    assert item["priority"] == 20
    assert item["primary_reason"] == "protected_asset_incident"


def test_recovery_hold_and_validation_and_artifact_tiers(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    items = {
        entry["source_module_ids"][0]: entry
        for entry in engine.build_review_queue(PROJECT_ID)["items"]
    }
    assert items["tool_recovery"]["priority"] == 30
    assert items["validator_runner"]["priority"] == 70
    assert items["artifact_inspector"]["priority"] == 80
    assert items["final_decision_bus"]["priority"] == 60


def test_missing_source_record_is_never_a_pass(tmp_path: Path) -> None:
    engine = SyntheticReviewUi(BobaMemoryStore(tmp_path / "boba"), {})
    cards = engine._source_cards(PROJECT_ID)
    assert cards
    for card in cards:
        assert card.original_status == "unavailable"
        assert card.current is False
        assert card.display_category == "unavailable"
        assert any("never treated as a pass" in item for item in card.limitations)


def test_queue_items_retain_full_source_identity(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    for item in engine.build_review_queue(PROJECT_ID)["items"]:
        assert item["source_module_ids"]
        assert item["source_record_ids"]
        assert item["source_record_digests"]
        assert len(next(iter(item["source_record_digests"].values()))) == 64
        assert item["primary_reason"]


def test_historical_records_are_hidden_by_default(tmp_path: Path) -> None:
    records = _synthetic_records(PROJECT_ID)
    records["report_reader"]["superseded"] = True
    engine = SyntheticReviewUi(BobaMemoryStore(tmp_path / "boba"), records)
    default = engine.build_review_queue(PROJECT_ID)["total"]
    with_history = engine.build_review_queue(PROJECT_ID, include_historical=True)["total"]
    assert with_history == default + 1


def test_queue_filters_by_presentation_category(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    filtered = engine.build_review_queue(PROJECT_ID, category="awaiting_evidence")["items"]
    assert filtered
    assert all(item["display_category"] == "awaiting_evidence" for item in filtered)


# ---------------------------------------------------------------------------
# Snapshots and source authority
# ---------------------------------------------------------------------------
def test_snapshot_binds_project_revision_and_target_digests(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _, payload = _prepared(engine)
    snapshot = payload["snapshot"]
    assert len(snapshot["project_snapshot_digest"]) == 64
    assert len(snapshot["target_digest"]) == 64
    assert snapshot["workflow_revision"] == 7
    assert snapshot["source_record_digests"]


def test_snapshot_reports_each_authority_domain_separately(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _, payload = _prepared(engine)
    snapshot = payload["snapshot"]
    assert snapshot["rights_status"] == "allowed"
    assert snapshot["safety_status"] == "human_review_required"
    assert snapshot["validation_status"] == "failed"
    assert snapshot["artifact_status"] == "stale"
    assert snapshot["final_decision_status"] == "hold"
    assert snapshot["approval_status"] == "human_approval_required"


def test_snapshot_publishes_bound_confirmation_tokens(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _, payload = _prepared(engine)
    offered = payload["snapshot"]["available_action_descriptor_ids"]
    tokens = payload["action_confirmations"]
    assert offered
    assert all(len(tokens[item]) == 64 for item in offered)


def test_snapshot_sections_cover_every_authority_domain(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _, payload = _prepared(engine)
    kinds = {section["section_type"] for section in payload["sections"]}
    assert {"rights", "safety", "workflow", "validation", "quality", "final_decision"} <= kinds


def test_snapshot_is_project_scoped(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _, payload = _prepared(engine)
    with pytest.raises(ValidationError):
        engine._snapshot("proj_other", payload["snapshot"]["review_snapshot_id"])


def test_unknown_target_is_refused(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with pytest.raises(ValidationError, match="unavailable or belongs"):
        engine.inspect_review_target(PROJECT_ID, "review_target_does_not_exist")


# ---------------------------------------------------------------------------
# Action descriptors and validation
# ---------------------------------------------------------------------------
def test_unknown_action_descriptor_is_refused(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with pytest.raises(ValidationError, match="Unknown"):
        engine._action_descriptor("review_action_made_up_v1")


def test_unavailable_action_cannot_be_requested(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session, payload = _prepared(engine)
    with pytest.raises(ValidationError, match="unavailable"):
        engine.create_review_action_request(
            PROJECT_ID,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_output_quality_human_review_v1",
            decision_value="reject_output",
            reason="Reason",
            confirmation_context_digest="0" * 64,
            idempotency_key="idem_unavailable_1",
            confirmed=True,
        )


def test_action_requires_explicit_confirmation(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session, payload = _prepared(engine)
    token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
    with pytest.raises(ValidationError, match="confirmation is required"):
        engine.create_review_action_request(
            PROJECT_ID,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="approve",
            reason="Reviewed.",
            confirmation_context_digest=token,
            idempotency_key="idem_unconfirmed_1",
            confirmed=False,
        )


def test_action_requires_the_bound_confirmation_token(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session, payload = _prepared(engine)
    with pytest.raises(ValidationError, match="does not match"):
        engine.create_review_action_request(
            PROJECT_ID,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="approve",
            reason="Reviewed.",
            confirmation_context_digest="a" * 64,
            idempotency_key="idem_badtoken_1",
            confirmed=True,
        )


def test_action_rejects_secret_bearing_reason(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session, payload = _prepared(engine)
    token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
    with pytest.raises(ValidationError, match="credentials"):
        engine.create_review_action_request(
            PROJECT_ID,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="approve",
            reason="password=hunter2",
            confirmation_context_digest=token,
            idempotency_key="idem_secret_2",
            confirmed=True,
        )


def test_action_rejects_unsupported_decision_value(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session, payload = _prepared(engine)
    token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
    with pytest.raises(ValidationError, match="Unsupported decision value"):
        engine.create_review_action_request(
            PROJECT_ID,
            review_session_id=session.review_session_id,
            review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
            action_descriptor_id="review_action_workflow_human_decision_v1",
            decision_value="override_safety",
            reason="Reviewed.",
            confirmation_context_digest=token,
            idempotency_key="idem_baddecision_1",
            confirmed=True,
        )


# ---------------------------------------------------------------------------
# Stale-state protection and canonical routing
# ---------------------------------------------------------------------------
STALE_CODES = {
    "stale_project_snapshot",
    "workflow_revision_mismatch",
    "target_digest_mismatch",
    "source_record_digest_mismatch",
    "target_removed",
}


def _pending_action(engine: SyntheticReviewUi, key: str) -> BobaReviewActionRequestV1:
    session, payload = _prepared(engine)
    token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
    return engine.create_review_action_request(
        PROJECT_ID,
        review_session_id=session.review_session_id,
        review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
        action_descriptor_id="review_action_workflow_human_decision_v1",
        decision_value="approve",
        reason="Reviewed.",
        confirmation_context_digest=token,
        idempotency_key=key,
        confirmed=True,
    )


@pytest.mark.parametrize("mutate", ["revision", "summary", "removed"])
def test_canonical_drift_is_rejected_before_the_owner_is_contacted(
    tmp_path: Path, mutate: str
) -> None:
    """Any canonical drift must reject, and must never reach the owning module."""
    engine = _engine(tmp_path)
    request = _pending_action(engine, f"idem_drift_{mutate}")

    drifted = _synthetic_records(PROJECT_ID)
    if mutate == "revision":
        drifted["workflow_controller"]["workflow_runs"][0]["revision"] = 99
    elif mutate == "summary":
        drifted["workflow_controller"]["summary"] = "Canonical record moved on."
    else:
        drifted.pop("workflow_controller")
    engine.records = drifted

    result = engine.validate_review_action_request(
        PROJECT_ID, request.review_action_request_id
    )
    assert result["valid"] is False
    assert result["code"] in STALE_CODES

    receipt = asyncio.run(
        engine.submit_review_action_to_owner(PROJECT_ID, request.review_action_request_id)
    )
    assert receipt.stale_state_rejected is True
    assert receipt.accepted_by_owner is False
    assert receipt.authoritative_state_changed is False
    assert receipt.canonical_record_id is None
    assert engine.controller.calls == []


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("expected_project_snapshot_digest", "0" * 64, "stale_project_snapshot"),
        ("expected_workflow_revision", 4242, "workflow_revision_mismatch"),
        ("expected_target_digest", "1" * 64, "target_digest_mismatch"),
        (
            "expected_source_record_digests",
            {"wfc_synthetic_record_1": "2" * 64},
            "source_record_digest_mismatch",
        ),
    ],
)
def test_each_staleness_guard_fires_independently(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    """Every digest and revision guard is checked, not just the outermost one."""
    engine = _engine(tmp_path)
    request = _pending_action(engine, f"idem_guard_{expected}")
    path = engine.store.boba_review_ui_action_path(
        PROJECT_ID, request.review_action_request_id
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[field] = value
    path.write_text(json.dumps(raw), encoding="utf-8")

    result = engine.validate_review_action_request(
        PROJECT_ID, request.review_action_request_id
    )
    assert result["valid"] is False
    assert result["code"] == expected
    assert engine.controller.calls == []


def test_expired_action_request_is_rejected(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session, payload = _prepared(engine)
    token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
    request = engine.create_review_action_request(
        PROJECT_ID,
        review_session_id=session.review_session_id,
        review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
        action_descriptor_id="review_action_workflow_human_decision_v1",
        decision_value="approve",
        reason="Reviewed.",
        confirmation_context_digest=token,
        idempotency_key="idem_expiry_1",
        confirmed=True,
    )
    raw = engine.store.load_boba_review_ui_action(PROJECT_ID, request.review_action_request_id)
    assert raw is not None
    raw["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    engine.store.boba_review_ui_action_path(
        PROJECT_ID, request.review_action_request_id
    ).write_text(json.dumps(raw), encoding="utf-8")
    result = engine.validate_review_action_request(
        PROJECT_ID, request.review_action_request_id
    )
    assert result["code"] == "expired_snapshot"


def test_confirmed_action_routes_to_the_owning_module(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    receipt = _submit(engine)
    assert receipt.owning_module_id == "workflow_controller"
    assert receipt.owning_operation_id == "record_human_workflow_decision"
    assert receipt.accepted_by_owner is True
    assert receipt.canonical_record_id
    assert receipt.canonical_record_digest
    assert receipt.authoritative_state_changed is True
    assert receipt.canonical_refresh_required is True
    assert len(engine.controller.calls) == 1
    assert engine.controller.calls[0]["explicit_confirmation"] is True
    assert engine.controller.calls[0]["expected_revision"] == 7


def test_authority_cannot_change_without_a_canonical_owner_record(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with pytest.raises(ValidationError, match="without a canonical owner record"):
        engine._persist_receipt(
            PROJECT_ID,
            BobaReviewActionReceiptV1(
                action_receipt_id="review_receipt_fake",
                review_action_request_id="review_action_fake",
                project_id=PROJECT_ID,
                owning_module_id="workflow_controller",
                owning_operation_id="record_human_workflow_decision",
                authoritative_state_changed=True,
            ),
        )


def test_owner_rejection_is_recorded_without_implying_success(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.controller.reject = True
    receipt = _submit(engine)
    assert receipt.accepted_by_owner is False
    assert receipt.authoritative_state_changed is False
    assert receipt.error_code == "owner_rejected"
    assert receipt.canonical_record_id is None


def test_resubmission_reuses_the_receipt_and_contacts_the_owner_once(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session, payload = _prepared(engine)
    token = payload["action_confirmations"]["review_action_workflow_human_decision_v1"]
    request = engine.create_review_action_request(
        PROJECT_ID,
        review_session_id=session.review_session_id,
        review_snapshot_id=payload["snapshot"]["review_snapshot_id"],
        action_descriptor_id="review_action_workflow_human_decision_v1",
        decision_value="approve",
        reason="Reviewed.",
        confirmation_context_digest=token,
        idempotency_key="idem_idempotent_1",
        confirmed=True,
    )
    first = asyncio.run(
        engine.submit_review_action_to_owner(PROJECT_ID, request.review_action_request_id)
    )
    second = asyncio.run(
        engine.submit_review_action_to_owner(PROJECT_ID, request.review_action_request_id)
    )
    assert second.duplicate_request_reused is True
    assert second.action_receipt_id == first.action_receipt_id
    assert len(engine.controller.calls) == 1


def test_action_requests_and_receipts_are_immutable(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    receipt = _submit(engine)
    with pytest.raises(ValidationError, match="immutable"):
        engine.store.save_boba_review_ui_receipt(
            PROJECT_ID,
            receipt.action_receipt_id,
            {**receipt.model_dump(mode="json"), "canonical_status": "tampered"},
        )


def test_acknowledgement_changes_no_authoritative_state(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    before = engine._source_cards(PROJECT_ID)
    notification = engine._notifications(PROJECT_ID, before)[0]
    updated = engine.acknowledge_review_notification(
        PROJECT_ID, session.review_session_id, notification.notification_id
    )
    after = engine._source_cards(PROJECT_ID)
    assert notification.notification_id in updated.acknowledged_notification_ids
    assert [card.original_status for card in after] == [
        card.original_status for card in before
    ]
    assert [card.source_record_digest for card in after] == [
        card.source_record_digest for card in before
    ]


# ---------------------------------------------------------------------------
# Events and timeline
# ---------------------------------------------------------------------------
def test_events_are_deduplicated_by_source_identity(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    events = engine.inspect_review_events(PROJECT_ID)["events"]
    keys = [(item["source_module_id"], item["source_event_id"]) for item in events]
    assert len(keys) == len(set(keys))
    assert len(events) == 3


def test_events_never_invent_progress(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    events = engine.inspect_review_events(PROJECT_ID)["events"]
    real = [item for item in events if item["progress_percent"] is not None]
    assert len(real) == 1
    assert real[0]["progress_percent"] == 50.0
    assert all(
        item["progress_percent"] is None
        for item in events
        if not item["progress_total"]
    )


def test_events_are_bounded_and_expose_a_cursor(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    payload = engine.inspect_review_events(PROJECT_ID, limit=1)
    assert len(payload["events"]) == 1
    assert payload["has_more"] is True
    assert payload["latest_sequence"] >= 0


def test_event_cursor_is_persisted_and_bounded(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    cursor = engine.record_review_event_cursor(
        PROJECT_ID, session.review_session_id, last_sequence=10**12, last_event_id="ev"
    )
    assert cursor["last_sequence"] == 1_000_000_000
    assert cursor["review_session_id"] == session.review_session_id


def test_timeline_discloses_unknown_timestamps(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    entries = engine.inspect_review_timeline(PROJECT_ID)["entries"]
    assert entries
    assert any(item["timestamp_precision"] == "unknown" for item in entries)
    assert all(item["source_module_id"] for item in entries)


# ---------------------------------------------------------------------------
# Persistence, export and reset
# ---------------------------------------------------------------------------
def test_build_persists_and_reloads_the_active_summary(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    built = engine.build_review_ui(PROJECT_ID)
    reloaded = engine.load_review_ui(PROJECT_ID)
    assert reloaded is not None
    assert reloaded["project_id"] == PROJECT_ID
    assert built["ui_summary"]["total_queue_item_count"] == len(built["review_queue_items"])


def test_signal_usage_declares_no_false_authority(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    usage = engine.build_review_ui(PROJECT_ID)["signal_usage"]
    for flag in (
        "optimistic_authority_change_used",
        "local_approval_created",
        "local_safety_decision_created",
        "local_rights_decision_created",
        "local_validation_decision_created",
        "local_quality_decision_created",
        "local_workflow_transition_created",
        "fake_progress_used",
        "command_execution_used",
        "shell_execution_used",
        "git_execution_used",
        "ffmpeg_execution_used",
        "repair_execution_used",
        "checkpoint_restore_used",
        "source_media_modified",
        "accepted_outputs_modified",
        "uploading_used",
        "publication_used",
        "external_analytics_used",
        "rights_bypass_used",
        "safety_bypass_used",
        "destructive_action_used",
        "untrusted_html_rendering_used",
        "arbitrary_api_url_used",
        "arbitrary_operation_used",
        "arbitrary_module_used",
        "arbitrary_path_used",
        "external_media_used",
    ):
        assert usage[flag] is False, flag


def test_export_redacts_secrets_and_private_paths(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    exported = json.dumps(engine.export_review_ui(PROJECT_ID))
    assert "sk-should-be-redacted" not in exported
    assert "C:\\Olympus" not in exported
    assert "[private-path]" in exported or "media_path" not in exported


def test_reset_preserves_every_source_owned_history(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.build_review_ui(PROJECT_ID)
    result = engine.reset_review_ui_metadata(PROJECT_ID)
    for key in (
        "source_records_preserved",
        "workflow_history_preserved",
        "validation_history_preserved",
        "quality_history_preserved",
        "artifact_history_preserved",
        "final_decision_history_preserved",
        "action_receipt_history_preserved",
    ):
        assert result[key] is True, key
    assert result["source_media_removed"] is False
    assert result["accepted_outputs_removed"] is False


def test_session_reset_removes_only_that_session(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    session = engine.create_review_session(PROJECT_ID, reviewer_context_id="reviewer_a")
    result = engine.reset_review_ui_metadata(PROJECT_ID, session.review_session_id)
    assert result["session_removed"] is True
    assert result["source_records_preserved"] is True
    with pytest.raises(ValidationError):
        engine.get_review_session(PROJECT_ID, session.review_session_id)


# ---------------------------------------------------------------------------
# Registration in the Integration Layer and Safety Gate
# ---------------------------------------------------------------------------
def test_integration_layer_registers_every_fixed_operation() -> None:
    registered = {
        item for item in build_boba_operation_registry() if item.startswith("review_ui.")
    }
    expected = {
        f"review_ui.{name}"
        for name in (
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
    assert registered == expected


def test_safety_gate_classes_review_ui_as_read_only_or_approval_gated() -> None:
    operations = build_safety_module_operation_registry()["review_ui"]
    assert len(operations) == 18
    assert operations["submit_action"] == "approval_required_read_only"
    read_only = [key for key, value in operations.items() if value == "automatic_read_only"]
    assert len(read_only) == 17


def test_review_ui_module_contains_no_dynamic_dispatch() -> None:
    source = Path("src/olympus/boba/review_ui.py").read_text(encoding="utf-8")
    for forbidden in (
        "importlib",
        "subprocess",
        "eval(",
        "exec(",
        "os.system",
        "requests.",
        "httpx.",
    ):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Review UI Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4",
        size_bytes=24,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=20.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _client(tmp_path: Path) -> TestClient:
    from olympus.api.v1.routes.boba import router

    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    asyncio.run(storage.put(project.storage_key, b"synthetic", content_type="video/mp4"))
    asyncio.run(StorageProjectRepository(storage).save(project))
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    return TestClient(app)


def test_api_exposes_registry_views_and_actions(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui"
    registry = client.get(f"{base}/registry")
    assert registry.status_code == 200
    assert len(registry.json()["views"]) == 13
    assert client.get(f"{base}/views").json()["views"]
    assert client.get(f"{base}/actions").json()["actions"]


def test_api_queue_and_summary_are_project_scoped(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui"
    summary = client.get(base)
    assert summary.status_code == 200
    assert summary.json()["project_id"] == PROJECT_ID
    queue = client.get(f"{base}/queue")
    assert queue.status_code == 200
    assert len(queue.json()["priority_tiers"]) == 12


def test_api_rejects_unknown_queue_sort(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/review-ui/queue", params={"sort": "arbitrary"}
    )
    assert response.status_code >= 400


def test_api_session_lifecycle(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui"
    created = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    )
    assert created.status_code == 200
    session_id = created.json()["review_session_id"]
    assert client.get(f"{base}/sessions/{session_id}").status_code == 200
    patched = client.patch(f"{base}/sessions/{session_id}", json={"active_tab": "events"})
    assert patched.status_code == 200
    assert patched.json()["active_tab"] == "events"
    assert client.delete(f"{base}/sessions/{session_id}").status_code == 200


def test_api_rejects_unsupported_session_fields(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["review_session_id"]
    response = client.patch(
        f"{base}/sessions/{session_id}", json={"reviewer_context_id": "someone_else"}
    )
    assert response.status_code == 422


def test_api_snapshot_and_target_round_trip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["review_session_id"]
    target_id = f"review_target_project_{PROJECT_ID}"
    assert client.get(f"{base}/targets/{target_id}").status_code == 200
    snapshot = client.post(
        f"{base}/targets/{target_id}/snapshot", json={"review_session_id": session_id}
    )
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert "action_confirmations" in body
    snapshot_id = body["snapshot"]["review_snapshot_id"]
    assert client.post(f"{base}/snapshots/{snapshot_id}/refresh").status_code == 200


def test_api_rejects_unknown_target(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/review-ui/targets/review_target_missing"
    )
    assert response.status_code >= 400


def test_api_rejects_unknown_action_descriptor(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["review_session_id"]
    target_id = f"review_target_project_{PROJECT_ID}"
    snapshot_id = client.post(
        f"{base}/targets/{target_id}/snapshot", json={"review_session_id": session_id}
    ).json()["snapshot"]["review_snapshot_id"]
    response = client.post(
        f"{base}/actions",
        json={
            "review_session_id": session_id,
            "review_snapshot_id": snapshot_id,
            "action_descriptor_id": "review_action_arbitrary_v1",
            "confirmation_context_digest": "0" * 64,
            "idempotency_key": "idem_api_unknown",
            "confirmed": True,
        },
    )
    assert response.status_code >= 400


def test_api_timeline_events_and_export(tmp_path: Path) -> None:
    client = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui"
    assert client.get(f"{base}/timeline").status_code == 200
    events = client.get(f"{base}/events")
    assert events.status_code == 200
    assert "latest_sequence" in events.json()
    exported = client.get(f"{base}/export")
    assert exported.status_code == 200
    assert exported.json()["privacy"]["upload_used"] is False


def test_api_event_stream_emits_only_canonical_or_control_frames(tmp_path: Path) -> None:
    client = _client(tmp_path)
    url = f"/api/v1/boba/projects/{PROJECT_ID}/review-ui/events/stream"
    with client.stream(
        "GET", url, params={"max_frames": 1, "poll_seconds": 0.1}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert "event: review_stream_open" in body
    assert "event: review_stream_complete" in body
    for frame in body.split("\n\n"):
        if not frame.strip() or "data:" not in frame:
            continue
        payload = json.loads(frame.split("data: ", 1)[1])
        if frame.startswith("event: review_canonical_events"):
            continue
        assert payload["represents_work"] is False


def test_api_unknown_project_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/v1/boba/projects/proj_missing/review-ui/queue")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------
def test_validator_self_check_passes() -> None:
    payload = run_self_check()
    assert payload["passed"] is True
    assert payload["scenario_count"] == len(SCENARIO_NAMES)
    assert all(payload["checks"].values())


def test_validator_scenario_names_are_unique() -> None:
    assert len(set(SCENARIO_NAMES)) == len(SCENARIO_NAMES)
    assert len(SCENARIO_NAMES) >= 40


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_validator_scenario_passes(name: str, tmp_path: Path) -> None:
    result = run_named_scenario(name, tmp_path)
    assert result.passed, f"{name}: {result.detail}"
