"""BOBA Integration Layer V1 contracts, routing, storage, API, and UI tests."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_integration_layer import (
    SCENARIO_NAMES,
    IntegrationSyntheticHarness,
    run_named_scenario,
    run_self_check,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.contracts import BobaContract
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    BobaIntegrationLayerV1,
    BobaIntegrationSignalUsageV1,
    build_boba_module_registry,
    build_boba_operation_registry,
    calculate_integration_request_digest,
    sanitize_integration_export,
)
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_integration_layer_test"
MODULE_IDS = tuple(build_boba_module_registry())
OPERATION_IDS = tuple(build_boba_operation_registry())
PROHIBITED_SIGNAL_FIELDS = (
    "direct_command_execution_used",
    "direct_git_execution_used",
    "direct_ffmpeg_execution_used",
    "arbitrary_dynamic_import_used",
    "arbitrary_function_invocation_used",
    "code_modified_directly",
    "artifact_modified_directly",
    "source_media_modified",
    "accepted_outputs_modified",
    "checkpoint_restore_used",
    "workflow_resume_used",
    "package_installation_used",
    "service_restart_used",
    "process_kill_used",
    "external_api_used",
    "network_access_used",
    "downloading_used",
    "uploading_used",
    "publication_used",
    "push_used",
    "merge_used",
    "deployment_used",
    "rights_bypass_used",
    "safety_bypass_used",
    "destructive_action_used",
)
CONTRACT_NAMES = (
    "BobaIntegrationApprovalBindingV1",
    "BobaIntegrationArtifactReferenceV1",
    "BobaIntegrationCompatibilityCheckV1",
    "BobaIntegrationDependencyCheckV1",
    "BobaIntegrationEnvelopeV1",
    "BobaIntegrationEventV1",
    "BobaIntegrationFailureV1",
    "BobaIntegrationHandoffV1",
    "BobaIntegrationIdempotencyRecordV1",
    "BobaIntegrationLayerSetV1",
    "BobaIntegrationModuleDescriptorV1",
    "BobaIntegrationOperationDescriptorV1",
    "BobaIntegrationRegistrySnapshotV1",
    "BobaIntegrationRequestV1",
    "BobaIntegrationResponseV1",
    "BobaIntegrationSafetyBindingV1",
    "BobaIntegrationSignalUsageV1",
    "BobaIntegrationSummaryV1",
    "BobaIntegrationTransactionV1",
)


@pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
def test_each_named_integration_scenario(
    tmp_path: Path,
    scenario_name: str,
) -> None:
    harness = IntegrationSyntheticHarness(tmp_path / scenario_name)
    result = run_named_scenario(scenario_name, harness)
    assert result.passed, result.detail


@pytest.mark.parametrize("module_id", MODULE_IDS)
def test_every_registered_module_is_static_and_cross_linked(
    module_id: str,
) -> None:
    modules = build_boba_module_registry()
    operations = build_boba_operation_registry()
    descriptor = modules[module_id]
    assert descriptor.module_id == module_id
    assert descriptor.implementation_status in {
        "available",
        "degraded",
        "unavailable",
        "future",
        "blocked",
        "unknown",
    }
    if not descriptor.operation_ids:
        assert descriptor.implementation_status == "future"
    assert all(operation_id in operations for operation_id in descriptor.operation_ids)
    assert all(
        operations[operation_id].module_id == module_id
        for operation_id in descriptor.operation_ids
    )


@pytest.mark.parametrize("operation_id", OPERATION_IDS)
def test_every_registered_operation_has_valid_static_ownership(
    operation_id: str,
) -> None:
    modules = build_boba_module_registry()
    operation = build_boba_operation_registry()[operation_id]
    assert operation.operation_id == operation_id
    assert operation.module_id in modules
    assert operation_id in modules[operation.module_id].operation_ids
    assert operation.operation_class in {
        "read_only",
        "planning",
        "approved_execution",
        "approved_rollback",
        "metadata_reset",
        "export",
        "future_gated",
        "prohibited",
    }
    if operation.operation_class in {"approved_execution", "approved_rollback"}:
        assert operation.target_approval_required is True
        assert operation.safety_gate_required is True
        assert operation.idempotency_required is True
    if operation.future_gated:
        assert operation.operation_class == "future_gated"
    if operation.prohibited:
        assert operation.operation_class == "prohibited"


@pytest.mark.parametrize("field_name", PROHIBITED_SIGNAL_FIELDS)
def test_every_prohibited_integration_signal_is_structurally_false(
    field_name: str,
) -> None:
    signals = BobaIntegrationSignalUsageV1()
    assert getattr(signals, field_name) is False
    with pytest.raises(PydanticValidationError):
        BobaIntegrationSignalUsageV1.model_validate({field_name: True})


@pytest.fixture(scope="module")
def integration_contracts(
    tmp_path_factory: pytest.TempPathFactory,
) -> Mapping[str, BobaContract]:
    root = tmp_path_factory.mktemp("boba_integration_contracts")
    harness = IntegrationSyntheticHarness(root)
    engine, envelope, request = harness.read_only_case("contracts")
    transaction = asyncio.run(engine.validate_request_envelope(envelope))
    response = asyncio.run(engine.route_typed_request(transaction.transaction_id))
    layer = engine._load_layer()

    failure_engine, failure_envelope, _ = harness.read_only_case("failure_contracts")
    invalid = failure_envelope.model_copy(
        update={"consumer_module_id": "unknown_target"}
    )
    with pytest.raises(ValidationError):
        asyncio.run(failure_engine.validate_request_envelope(invalid))
    failed_layer = failure_engine._load_layer()

    _execution_engine, execution_envelope, _execution_request, _context = (
        harness.execution_case("binding_contracts")
    )
    contracts: list[BobaContract] = [
        execution_envelope.approval_binding,
        harness.artifact(engine.project_id),
        layer.compatibility_checks[-1],
        layer.dependency_checks[-1],
        envelope,
        layer.integration_events[-1],
        failed_layer.integration_failures[-1],
        failed_layer.integration_handoffs[-1],
        layer.idempotency_records[-1],
        layer,
        layer.module_descriptors[0],
        layer.operation_descriptors[0],
        layer.registry_snapshot,
        request,
        response,
        execution_envelope.safety_binding,
        layer.signal_usage,
        layer.integration_summary,
        engine.inspect_transaction(transaction.transaction_id),
    ]
    return {
        contract.__class__.__name__: contract
        for contract in contracts
        if contract is not None
    }


@pytest.mark.parametrize("contract_name", CONTRACT_NAMES)
def test_every_integration_contract_serializes_as_json(
    contract_name: str,
    integration_contracts: Mapping[str, BobaContract],
) -> None:
    assert set(CONTRACT_NAMES) <= set(integration_contracts)
    payload = integration_contracts[contract_name].model_dump(mode="json")
    assert json.loads(json.dumps(payload)) == payload


def test_registry_snapshot_is_deterministic_and_immutable(tmp_path: Path) -> None:
    first = IntegrationSyntheticHarness(tmp_path / "first").engine(
        "registry"
    ).build_registry_snapshot()
    second = IntegrationSyntheticHarness(tmp_path / "second").engine(
        "registry"
    ).build_registry_snapshot()
    assert first.registry_sha256 == second.registry_sha256
    assert first.registry_snapshot_id == second.registry_snapshot_id
    with pytest.raises(PydanticValidationError):
        first.registry_sha256 = "f" * 64


def test_registry_rejects_unregistered_handler_injection(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unregistered handlers"):
        BobaIntegrationLayerV1(
            BobaMemoryStore(tmp_path / "boba"),
            project_id=PROJECT_ID,
            source_id="synthetic",
            handlers={"attacker.dynamic": lambda _request: {"ok": True}},
        )


@pytest.mark.parametrize(
    "unsafe_payload",
    [
        {"callback": lambda: None},
        {"import_path": "untrusted.module"},
        {"function_name": "invoke_anything"},
        {"command": "powershell.exe -Command whoami"},
        {"external_url": "https://example.invalid/payload"},
        {"api_token": "ghp_abcdefghijklmnopqrstuvwxyz123456"},
        {"raw_patch": "diff --git a/a.py b/a.py"},
        {"private_path": r"C:\Users\private\secret.txt"},
        {"unc_path": r"\\server\private\artifact.json"},
        {"traversal": "../../private/artifact.json"},
    ],
    ids=(
        "callable",
        "dynamic-import",
        "function-name",
        "command",
        "external-url",
        "secret",
        "raw-patch",
        "absolute-path",
        "unc-path",
        "traversal",
    ),
)
def test_request_envelope_rejects_unbounded_authority_payloads(
    tmp_path: Path,
    unsafe_payload: dict[str, Any],
) -> None:
    engine = IntegrationSyntheticHarness(tmp_path).engine("unsafe_payload")
    with pytest.raises(ValidationError):
        engine.create_request_envelope(
            requesting_module_id="autopilot_controller",
            target_module_id="error_doctor",
            target_operation_id="error_doctor.load",
            request_parameters=unsafe_payload,
        )


def test_request_digest_is_canonical_and_payload_sensitive() -> None:
    first = calculate_integration_request_digest({"b": 2, "a": 1})
    reordered = calculate_integration_request_digest({"a": 1, "b": 2})
    changed = calculate_integration_request_digest({"a": 1, "b": 3})
    assert first == reordered
    assert first != changed


def test_sanitized_export_removes_secrets_paths_patches_and_logs() -> None:
    exported = sanitize_integration_export(
        {
            "api_token": "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "raw_patch": "diff --git a/a.py b/a.py",
            "full_log": "internal stack trace",
            "path": r"C:\Users\private\secret.txt",
            "safe_summary": "Bounded local result.",
        }
    )
    serialized = json.dumps(exported)
    assert "ghp_" not in serialized
    assert "diff --git" not in serialized
    assert "internal stack trace" not in serialized
    assert r"C:\\Users\\private" not in serialized
    assert exported["safe_summary"] == "Bounded local result."


def test_read_only_route_records_ordered_events_and_no_side_effects(
    tmp_path: Path,
) -> None:
    harness = IntegrationSyntheticHarness(tmp_path)
    engine, envelope, _request = harness.read_only_case("ordered_events")
    transaction = asyncio.run(engine.validate_request_envelope(envelope))
    response = asyncio.run(engine.route_typed_request(transaction.transaction_id))
    completed = engine.inspect_transaction(transaction.transaction_id)
    events = engine.inspect_transaction_events(transaction.transaction_id)
    assert response.status == "succeeded"
    assert completed.state == "succeeded"
    assert completed.side_effects_reported == []
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].event_type == "transaction_completed"


def test_identical_completed_request_reuses_saved_response(tmp_path: Path) -> None:
    harness = IntegrationSyntheticHarness(tmp_path)
    key = "integration_idempotency_exact"
    engine, envelope, _request = harness.read_only_case(
        "reuse",
        idempotency_key=key,
    )
    transaction = asyncio.run(engine.validate_request_envelope(envelope))
    original = asyncio.run(engine.route_typed_request(transaction.transaction_id))
    duplicate = envelope.model_copy(
        update={
            "envelope_id": "boba_integration_duplicate_envelope",
            "transaction_id": "boba_integration_duplicate_transaction",
        }
    )
    duplicate_transaction = asyncio.run(engine.validate_request_envelope(duplicate))
    reused = asyncio.run(
        engine.route_typed_request(duplicate_transaction.transaction_id)
    )
    assert original.response_id == reused.response_id
    assert reused.status == "duplicate_reused"
    assert reused.idempotency_reused is True


def test_reset_preserves_immutable_transaction_history(tmp_path: Path) -> None:
    harness = IntegrationSyntheticHarness(tmp_path)
    engine, envelope, _request = harness.read_only_case("reset_history")
    transaction = asyncio.run(engine.validate_request_envelope(envelope))
    asyncio.run(engine.route_typed_request(transaction.transaction_id))
    result = engine.reset_integration_metadata()
    preserved = engine.inspect_transaction(transaction.transaction_id)
    assert result["immutable_transactions_preserved"] is True
    assert result["upstream_boba_artifacts_removed"] is False
    assert result["approvals_removed"] is False
    assert result["safety_decisions_removed"] is False
    assert result["autopilot_history_removed"] is False
    assert preserved.state == "succeeded"


def test_backward_compatible_integration_facade_methods_remain_callable() -> None:
    for method_name in (
        "generate_observer_report",
        "generate_boba_error_doctor",
        "generate_boba_root_cause_analyzer",
        "generate_boba_repair_planner",
        "build_boba_integration_registry",
        "create_boba_integration_request",
        "route_boba_integration_request",
        "export_boba_integration_layer",
        "reset_boba_integration_layer",
    ):
        assert callable(getattr(BobaIntegration, method_name))


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Integration Layer Test",
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


def _integration(tmp_path: Path) -> BobaIntegration:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    return BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))


def test_api_exposes_registry_request_transaction_events_and_export(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    base = f"/api/v1/boba/projects/{PROJECT_ID}/integration-layer"
    with TestClient(app) as client:
        layer = client.get(base)
        modules = client.get(f"{base}/modules")
        operations = client.get(f"{base}/operations")
        exported = client.get(f"{base}/export")
        reset = client.delete(base)
        created = client.post(
            f"{base}/requests",
            json={
                "requesting_module_id": "autopilot_controller",
                "target_module_id": "error_doctor",
                "target_operation_id": "error_doctor.load",
                "request_parameters": {},
            },
        )
        transaction_id = created.json()["transaction"]["transaction_id"]
        transaction = client.get(f"{base}/transactions/{transaction_id}")
        events = client.get(f"{base}/transactions/{transaction_id}/events")
    for response in (
        layer,
        modules,
        operations,
        exported,
        reset,
        created,
        transaction,
        events,
    ):
        assert response.status_code == 200, response.text
    assert created.json()["routed"] is False
    assert created.json()["transaction"]["state"] == "ready"
    assert modules.json()["modules"]
    assert operations.json()["operations"]
    assert reset.json()["upstream_boba_artifacts_removed"] is False
    assert transaction.json()["transaction_id"] == transaction_id
    assert events.json()[-1]["event_type"] == "request_validated"


@pytest.mark.parametrize(
    "unsafe_field",
    (
        "callable",
        "handler",
        "command",
        "raw_patch",
        "external_url",
        "api_token",
        "workflow_resume",
        "approval_override",
    ),
)
def test_api_rejects_uncontracted_request_fields(
    app: FastAPI,
    tmp_path: Path,
    unsafe_field: str,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/integration-layer/requests",
            json={
                "requesting_module_id": "autopilot_controller",
                "target_module_id": "error_doctor",
                "target_operation_id": "error_doctor.load",
                unsafe_field: True,
            },
        )
    assert response.status_code == 422


def test_frontend_explains_registry_routing_and_authority_boundary() -> None:
    component = Path(
        "frontend/src/components/project/BobaIntegrationLayerPanel.tsx"
    ).read_text(encoding="utf-8")
    results = Path(
        "frontend/src/components/project/ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    normalized = " ".join(component.split())
    for heading in (
        "MODULE REGISTRY",
        "OPERATION REGISTRY",
        "COMPATIBILITY",
        "DEPENDENCIES",
        "REQUEST",
        "APPROVAL AND SAFETY",
        "TRANSACTION",
        "RESULT",
        "INTEGRATION FAILURES",
        "WHAT HAPPENS NEXT",
    ):
        assert heading in component
    assert "connects registered modules through typed, validated requests" in normalized
    assert "does not decide which repair to use" in normalized
    assert "exact module approval" in normalized
    assert "current Safety Gate allowance" in normalized
    assert "target-module revalidation" in normalized
    assert "Unknown modules and operations cannot be invoked" in normalized
    assert "BobaIntegrationLayerPanel" in results


def test_documentation_has_exact_requested_numbered_sections() -> None:
    documentation = Path("docs/BOBA_INTEGRATION_LAYER_V1.md").read_text(
        encoding="utf-8"
    )
    headings = re.findall(r"^## (\d+)\. (.+)$", documentation, re.MULTILINE)
    normalized = " ".join(documentation.split())
    assert [int(number) for number, _title in headings] == list(range(1, 30))
    assert headings[0][1] == "Purpose"
    assert headings[-1][1] == "Limitations"
    assert "does not choose actions" in normalized
    assert "does not create approvals" in normalized
    assert "does not change Safety Gate decisions" in normalized


def test_validator_self_check_passes_without_target_execution() -> None:
    report = run_self_check()
    assert report.passed, [
        scenario.detail for scenario in report.scenarios if not scenario.passed
    ]
    assert report.scenario_count == 17
    assert len(SCENARIO_NAMES) == 149
