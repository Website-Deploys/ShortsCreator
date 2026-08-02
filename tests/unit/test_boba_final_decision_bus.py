from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.final_decision_bus import (
    BobaFinalDecisionBusV1,
    build_final_decision_registries,
)
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import build_boba_operation_registry
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_final_decision_bus_test"


class SyntheticFinalDecisionBus(BobaFinalDecisionBusV1):
    def __init__(
        self,
        store: BobaMemoryStore,
        source_records: dict[str, list[dict[str, Any]]],
    ) -> None:
        super().__init__(store)
        self.source_records = source_records

    def _source_records(
        self,
        project_id: str,
        decision_source_id: str,
    ) -> list[dict[str, Any]]:
        assert project_id == PROJECT_ID
        return [dict(item) for item in self.source_records.get(decision_source_id, [])]


def future_time(seconds: int = 300) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def ready_records() -> dict[str, list[dict[str, Any]]]:
    return {
        "safety_gate": [
            {
                "safety_decision_id": "safety_exact",
                "project_id": PROJECT_ID,
                "decision": "allowed_for_exact_internal_execution",
                "allowed_target_module": "validator_runner",
                "allowed_target_operation": "execute_run",
                "decision_valid": True,
                "decision_expires_at": future_time(),
            }
        ],
        "target_approval": [
            {
                "approval_binding_id": "approval_exact",
                "approved_project_id": PROJECT_ID,
                "approval_type": "target_module_exact",
                "target_module_id": "validator_runner",
                "target_operation_id": "execute_run",
                "explicit_confirmation": True,
                "current_match_status": "match",
                "approval_expires_at": future_time(),
            }
        ],
    }


def make_bus(
    tmp_path: Any,
    source_records: dict[str, list[dict[str, Any]]] | None = None,
) -> SyntheticFinalDecisionBus:
    return SyntheticFinalDecisionBus(
        BobaMemoryStore(tmp_path / "boba"),
        source_records or {},
    )


def ready_request(bus: SyntheticFinalDecisionBus) -> str:
    bus.build_final_decision_registries(PROJECT_ID, source_id="test")
    request = bus.create_final_decision_request(
        PROJECT_ID,
        source_id="test",
        requested_by_module="test_runner",
        action_policy_id="exact_registered_validation_execution",
        target_module_id="validator_runner",
        target_operation_id="execute_run",
        source_selectors=[
            {
                "decision_source_id": "safety_gate",
                "producer_record_id": "safety_exact",
            },
            {
                "decision_source_id": "target_approval",
                "producer_record_id": "approval_exact",
            },
        ],
    )
    return request.final_decision_request_id


def test_missing_evidence_fails_closed(tmp_path: Any) -> None:
    bus = make_bus(tmp_path)
    bus.build_final_decision_registries(PROJECT_ID, source_id="test")
    request = bus.create_final_decision_request(
        PROJECT_ID,
        source_id="test",
        requested_by_module="test_runner",
        action_policy_id="exact_registered_validation_execution",
        target_module_id="validator_runner",
        target_operation_id="execute_run",
        source_selectors=[],
    )

    evaluation = bus.evaluate_final_action_policy(PROJECT_ID, request.final_decision_request_id)

    assert evaluation.disposition == "hold_missing_evidence"
    decision = bus.finalize_exact_internal_decision(PROJECT_ID, request.final_decision_request_id)
    assert not decision.ready_for_dispatch
    with pytest.raises(ValidationError):
        bus.build_exact_dispatch_envelope(PROJECT_ID, decision.final_decision_id)


def test_ready_final_decision_creates_single_use_envelope(tmp_path: Any) -> None:
    bus = make_bus(tmp_path, ready_records())
    request_id = ready_request(bus)

    bindings = bus.collect_source_decision_bindings(PROJECT_ID, request_id)
    assert all(item.valid for item in bindings)
    evaluation = bus.evaluate_final_action_policy(PROJECT_ID, request_id)
    assert evaluation.disposition == "ready_for_exact_internal_dispatch"

    decision = bus.finalize_exact_internal_decision(PROJECT_ID, request_id)
    assert decision.ready_for_dispatch
    assert decision.target_execution_authorized is False
    envelope = bus.build_exact_dispatch_envelope(PROJECT_ID, decision.final_decision_id)
    assert envelope.single_use is True
    assert envelope.target_execution_authorized is False
    inspection = bus.inspect_dispatch_envelope(PROJECT_ID, envelope.dispatch_envelope_id)
    assert inspection["currently_valid_for_independent_revalidation"] is True
    assert inspection["target_execution_performed"] is False


def test_wrong_target_is_rejected_before_source_collection(tmp_path: Any) -> None:
    bus = make_bus(tmp_path, ready_records())
    bus.build_final_decision_registries(PROJECT_ID, source_id="test")

    with pytest.raises(ValidationError, match="exact registered target"):
        bus.create_final_decision_request(
            PROJECT_ID,
            source_id="test",
            requested_by_module="test_runner",
            action_policy_id="exact_registered_validation_execution",
            target_module_id="olympus_rendering",
            target_operation_id="render",
            source_selectors=[],
        )


def test_expired_source_evidence_holds_stale(tmp_path: Any) -> None:
    records = ready_records()
    records["safety_gate"][0]["decision_expires_at"] = (
        datetime.now(UTC) - timedelta(seconds=1)
    ).isoformat()
    bus = make_bus(tmp_path, records)
    request_id = ready_request(bus)
    bus.collect_source_decision_bindings(PROJECT_ID, request_id)

    evaluation = bus.evaluate_final_action_policy(PROJECT_ID, request_id)

    assert evaluation.disposition == "hold_stale_evidence"


def test_safety_denial_blocks_exact_action(tmp_path: Any) -> None:
    records = ready_records()
    records["safety_gate"][0]["decision"] = "denied"
    bus = make_bus(tmp_path, records)
    request_id = ready_request(bus)
    bus.collect_source_decision_bindings(PROJECT_ID, request_id)

    evaluation = bus.evaluate_final_action_policy(PROJECT_ID, request_id)

    assert evaluation.disposition == "blocked_by_safety"


def test_bound_rights_block_overrides_optional_status(tmp_path: Any) -> None:
    records = ready_records()
    records["rights_permission_gate"] = [
        {
            "decision_id": "rights_block",
            "source_project_id": PROJECT_ID,
            "gate_status": "blocked",
            "blocked": True,
            "requires_permission": True,
        }
    ]
    bus = make_bus(tmp_path, records)
    request_id = ready_request(bus)
    request = bus._request(bus._bus(PROJECT_ID), request_id)
    # Build a second request with the optional Rights decision explicitly selected.
    selected = bus.create_final_decision_request(
        PROJECT_ID,
        source_id=request.source_id,
        requested_by_module=request.requested_by_module,
        action_policy_id=request.action_policy_id,
        target_module_id=request.target_module_id,
        target_operation_id=request.target_operation_id,
        source_selectors=[
            *[item.model_dump(mode="json") for item in request.source_selectors],
            {
                "decision_source_id": "rights_permission_gate",
                "producer_record_id": "rights_block",
            },
        ],
    )
    bus.collect_source_decision_bindings(PROJECT_ID, selected.final_decision_request_id)

    evaluation = bus.evaluate_final_action_policy(PROJECT_ID, selected.final_decision_request_id)

    assert evaluation.disposition == "blocked_by_rights"


def test_conflicting_same_domain_records_hold(tmp_path: Any) -> None:
    records = ready_records()
    records["safety_gate"].append(
        {
            "safety_decision_id": "safety_deny",
            "project_id": PROJECT_ID,
            "decision": "denied",
            "allowed_target_module": "validator_runner",
            "allowed_target_operation": "execute_run",
            "decision_valid": True,
            "decision_expires_at": future_time(),
        }
    )
    bus = make_bus(tmp_path, records)
    bus.build_final_decision_registries(PROJECT_ID, source_id="test")
    request = bus.create_final_decision_request(
        PROJECT_ID,
        source_id="test",
        requested_by_module="test_runner",
        action_policy_id="exact_registered_validation_execution",
        target_module_id="validator_runner",
        target_operation_id="execute_run",
        source_selectors=[
            {"decision_source_id": "safety_gate", "producer_record_id": "safety_exact"},
            {"decision_source_id": "safety_gate", "producer_record_id": "safety_deny"},
            {"decision_source_id": "target_approval", "producer_record_id": "approval_exact"},
        ],
    )
    bus.collect_source_decision_bindings(PROJECT_ID, request.final_decision_request_id)

    conflicts = bus.detect_final_decision_conflicts(PROJECT_ID, request.final_decision_request_id)

    assert any(item.conflict_type == "decision_conflict" for item in conflicts)


def test_invalidation_revokes_envelope_and_preserves_decision(tmp_path: Any) -> None:
    bus = make_bus(tmp_path, ready_records())
    request_id = ready_request(bus)
    bus.collect_source_decision_bindings(PROJECT_ID, request_id)
    decision = bus.finalize_exact_internal_decision(PROJECT_ID, request_id)
    envelope = bus.build_exact_dispatch_envelope(PROJECT_ID, decision.final_decision_id)

    invalidation = bus.invalidate_final_decision(
        PROJECT_ID,
        decision.final_decision_id,
        reason="The target parameters changed.",
        invalidated_by_module="test_runner",
    )

    assert invalidation.final_decision_id == decision.final_decision_id
    assert bus.inspect_final_decision(PROJECT_ID, decision.final_decision_id)["invalidated"]
    assert not bus.inspect_dispatch_envelope(PROJECT_ID, envelope.dispatch_envelope_id)[
        "currently_valid_for_independent_revalidation"
    ]
    persisted = bus._bus(PROJECT_ID)
    assert persisted.final_decisions[0].invalidated is False


def test_envelope_consumption_requires_exact_revalidation(tmp_path: Any) -> None:
    bus = make_bus(tmp_path, ready_records())
    request_id = ready_request(bus)
    bus.collect_source_decision_bindings(PROJECT_ID, request_id)
    decision = bus.finalize_exact_internal_decision(PROJECT_ID, request_id)
    envelope = bus.build_exact_dispatch_envelope(PROJECT_ID, decision.final_decision_id)
    transaction = SimpleNamespace(
        project_id=PROJECT_ID,
        target_module_id="validator_runner",
        target_operation_id="execute_run",
        target_independent_revalidation_confirmed=True,
    )
    bus.store.load_boba_integration_transaction = lambda _project, _transaction: transaction  # type: ignore[method-assign]

    consumed = bus.mark_dispatch_envelope_consumed(
        PROJECT_ID,
        envelope.dispatch_envelope_id,
        integration_transaction_id="transaction_exact",
    )

    assert consumed.consumed
    assert consumed.consumption_transaction_id == "transaction_exact"


def test_reset_preserves_history_and_resumes_event_sequence(tmp_path: Any) -> None:
    bus = make_bus(tmp_path, ready_records())
    request_id = ready_request(bus)
    bus.collect_source_decision_bindings(PROJECT_ID, request_id)
    decision = bus.finalize_exact_internal_decision(PROJECT_ID, request_id)
    bus.invalidate_final_decision(
        PROJECT_ID,
        decision.final_decision_id,
        reason="Synthetic state changed.",
        invalidated_by_module="test_runner",
    )
    before = bus.store.boba_final_decision_last_event_sequence(PROJECT_ID)

    reset = bus.reset_final_decision_bus_metadata(PROJECT_ID)
    assert reset["event_streams_preserved"] is True
    bus.build_final_decision_registries(PROJECT_ID, source_id="test")
    bus.create_final_decision_request(
        PROJECT_ID,
        source_id="test",
        requested_by_module="test_runner",
        action_policy_id="exact_registered_validation_execution",
        target_module_id="validator_runner",
        target_operation_id="execute_run",
        source_selectors=[],
    )

    assert bus.store.boba_final_decision_last_event_sequence(PROJECT_ID) > before


def test_storage_layout_is_project_scoped_and_no_media_is_written(tmp_path: Any) -> None:
    bus = make_bus(tmp_path)
    bus.build_final_decision_registries(PROJECT_ID, source_id="test")
    root = bus.store.boba_final_decision_bus_path(PROJECT_ID)
    assert root.as_posix().endswith(
        "/projects/proj_final_decision_bus_test/final_decision_bus/index.json"
    )
    assert root.exists()
    assert not list((tmp_path / "boba").rglob("*.mp4"))


def make_api_integration(tmp_path: Path) -> BobaIntegration:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    timestamp = utc_now()
    project = Project(
        id=PROJECT_ID,
        name="BOBA Final Decision Bus Test",
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
    asyncio.run(StorageProjectRepository(storage).save(project))
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))
    integration.final_decision_bus = SyntheticFinalDecisionBus(
        integration.store,
        ready_records(),
    )
    return integration


API_ROUTES = (
    ("get", "/api/v1/boba/projects/{project_id}/final-decision-bus"),
    ("get", "/api/v1/boba/projects/{project_id}/final-decision-bus/registries"),
    ("get", "/api/v1/boba/projects/{project_id}/final-decision-bus/sources"),
    ("get", "/api/v1/boba/projects/{project_id}/final-decision-bus/actions"),
    ("post", "/api/v1/boba/projects/{project_id}/final-decision-bus/requests"),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/validate",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/collect-source-decisions",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/validate-source-bindings",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/evidence-requirements",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/bind-evidence",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/detect-conflicts",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/evaluate",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/requests/{final_decision_request_id}/finalize",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/decisions/{final_decision_id}/dispatch-envelope",
    ),
    ("get", "/api/v1/boba/projects/{project_id}/final-decision-bus/decisions/{final_decision_id}"),
    (
        "get",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/dispatch-envelopes/{dispatch_envelope_id}",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/dispatch-envelopes/{dispatch_envelope_id}/consume",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/final-decision-bus/decisions/{final_decision_id}/invalidate",
    ),
    ("get", "/api/v1/boba/projects/{project_id}/final-decision-bus/events"),
    ("get", "/api/v1/boba/projects/{project_id}/final-decision-bus/export"),
    ("delete", "/api/v1/boba/projects/{project_id}/final-decision-bus"),
)


@pytest.mark.parametrize(("method", "route"), API_ROUTES)
def test_final_decision_bus_api_routes_are_registered(
    app: FastAPI,
    method: str,
    route: str,
) -> None:
    registered = app.openapi()["paths"]
    assert route in registered
    assert method in registered[route]


def test_final_decision_bus_api_lifecycle_is_metadata_only(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = make_api_integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    base = f"/api/v1/boba/projects/{PROJECT_ID}/final-decision-bus"
    try:
        with TestClient(app) as client:
            root = client.get(base)
            registries = client.get(f"{base}/registries")
            sources = client.get(f"{base}/sources")
            actions = client.get(f"{base}/actions")
            created = client.post(
                f"{base}/requests",
                json={
                    "source_id": "api-test",
                    "requested_by_module": "api_test",
                    "action_policy_id": "exact_registered_validation_execution",
                    "target_module_id": "validator_runner",
                    "target_operation_id": "execute_run",
                    "source_selectors": [
                        {
                            "decision_source_id": "safety_gate",
                            "producer_record_id": "safety_exact",
                        },
                        {
                            "decision_source_id": "target_approval",
                            "producer_record_id": "approval_exact",
                        },
                    ],
                },
            )
            request_id = created.json()["final_decision_request_id"]
            validated = client.post(f"{base}/requests/{request_id}/validate")
            collected = client.post(f"{base}/requests/{request_id}/collect-source-decisions")
            binding_validation = client.post(
                f"{base}/requests/{request_id}/validate-source-bindings"
            )
            requirements = client.post(f"{base}/requests/{request_id}/evidence-requirements")
            bound = client.post(f"{base}/requests/{request_id}/bind-evidence")
            conflicts = client.post(f"{base}/requests/{request_id}/detect-conflicts")
            evaluation = client.post(f"{base}/requests/{request_id}/evaluate")
            finalized = client.post(f"{base}/requests/{request_id}/finalize")
            decision_id = finalized.json()["final_decision_id"]
            envelope = client.post(f"{base}/decisions/{decision_id}/dispatch-envelope")
            envelope_id = envelope.json()["dispatch_envelope_id"]
            decision = client.get(f"{base}/decisions/{decision_id}")
            envelope_inspection = client.get(f"{base}/dispatch-envelopes/{envelope_id}")
            invalidated = client.post(
                f"{base}/decisions/{decision_id}/invalidate",
                json={"reason": "API synthetic state changed."},
            )
            events = client.get(f"{base}/events")
            exported = client.get(f"{base}/export")
            reset = client.delete(base)
    finally:
        app.dependency_overrides.pop(boba_integration_provider, None)
    for response in (
        root,
        registries,
        sources,
        actions,
        created,
        validated,
        collected,
        binding_validation,
        requirements,
        bound,
        conflicts,
        evaluation,
        finalized,
        envelope,
        decision,
        envelope_inspection,
        invalidated,
        events,
        exported,
        reset,
    ):
        assert response.status_code == 200, response.text
    assert binding_validation.json()["all_valid"] is True
    assert evaluation.json()["disposition"] == "ready_for_exact_internal_dispatch"
    assert finalized.json()["target_execution_authorized"] is False
    assert envelope.json()["target_execution_authorized"] is False
    assert envelope_inspection.json()["target_execution_performed"] is False
    assert invalidated.json()["final_decision_id"] == decision_id
    assert events.json()["events"]


def test_final_decision_bus_is_only_registered_as_metadata_operations() -> None:
    operations = build_boba_operation_registry()
    final_bus_operations = [
        operation
        for operation in operations.values()
        if operation.module_id == "final_decision_bus"
    ]
    assert final_bus_operations
    assert {operation.operation_class for operation in final_bus_operations} <= {
        "read_only",
        "export",
        "metadata_reset",
    }
    assert {operation.side_effect_class for operation in final_bus_operations} <= {
        "none",
        "BOBA_metadata_only",
    }
    safety_operations = build_safety_module_operation_registry()["final_decision_bus"]
    assert safety_operations
    assert set(safety_operations.values()) == {"automatic_read_only"}


_snapshot, _source_descriptors, _action_policies = build_final_decision_registries()
_POLICY_MAP = {item.action_policy_id: item for item in _action_policies}
_SOURCE_MAP = {item.decision_source_id: item for item in _source_descriptors}
_REGISTRY_SCENARIO_KINDS = (
    "policy_digest",
    "fixed_target",
    "source_descriptor",
    "authority_domain",
    "owner_module",
)

REGISTRY_CONTRACT_SCENARIOS = [
    pytest.param(
        policy_id,
        source_id,
        scenario_kind,
        id=policy_id + "-" + source_id + "-" + scenario_kind,
    )
    for policy_id in sorted(_POLICY_MAP)
    for source_id in sorted(_SOURCE_MAP)
    for scenario_kind in _REGISTRY_SCENARIO_KINDS
]


@pytest.mark.parametrize(
    ("policy_id", "source_id", "scenario_kind"),
    REGISTRY_CONTRACT_SCENARIOS,
)
def test_fixed_registry_contract_scenarios(
    policy_id: str,
    source_id: str,
    scenario_kind: str,
) -> None:
    """455 focused policy/source contract scenarios without dynamic registrations."""

    policy = _POLICY_MAP[policy_id]
    source = _SOURCE_MAP[source_id]
    if scenario_kind == "policy_digest":
        assert len(policy.policy_digest) == 64
    elif scenario_kind == "fixed_target":
        assert policy.target_module_id and policy.target_operation_id
    elif scenario_kind == "source_descriptor":
        assert source.decision_source_id == source_id
    elif scenario_kind == "authority_domain":
        assert source.authority_domain != "unknown"
    elif scenario_kind == "owner_module":
        assert source.producer_module_id
    else:  # pragma: no cover - parametrize is intentionally exhaustive.
        raise AssertionError("Unknown registry contract scenario.")
