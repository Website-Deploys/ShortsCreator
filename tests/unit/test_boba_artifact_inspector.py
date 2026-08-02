"""BOBA Artifact Inspector V1 contracts, safety, persistence, API, and UI tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_artifact_inspector import (
    _EXERCISE_POSITIONS,
    SCENARIO_NAMES,
    ArtifactInspectorSyntheticHarness,
    run_named_scenario,
    run_self_check,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.artifact_inspector import (
    BobaArtifactInspectorSetV1,
    BobaArtifactInspectorSignalUsageV1,
    BobaArtifactInspectorV1,
    BobaArtifactReferenceV1,
    build_fixed_artifact_resolver_registry,
    build_fixed_artifact_type_registry,
    sanitize_artifact_export,
)
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_artifact_inspector_test"
SOURCE_ID = "source_boba_artifact_inspector_test"
PROHIBITED_SIGNAL_FIELDS = (
    "arbitrary_path_scanning_used",
    "arbitrary_glob_used",
    "dynamic_resolver_loading_used",
    "arbitrary_function_invocation_used",
    "artifact_modification_used",
    "artifact_move_used",
    "artifact_copy_used",
    "artifact_deletion_used",
    "source_media_modified",
    "accepted_outputs_modified",
    "command_execution_used",
    "shell_execution_used",
    "git_execution_used",
    "ffmpeg_execution_used",
    "media_decoding_used",
    "ocr_used",
    "validator_execution_used",
    "workflow_transition_used",
    "quality_authorization_used",
    "safety_authorization_used",
    "checkpoint_restore_used",
    "approval_creation_used",
    "external_api_used",
    "network_used",
    "url_fetching_used",
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
UNSAFE_REFERENCES = (
    "https://example.invalid/manifest.json",
    "http://example.invalid/manifest.json",
    "file:///private/manifest.json",
    "//server/share/manifest.json",
    r"\\server\share\manifest.json",
    r"C:\private\manifest.json",
    "/private/manifest.json",
    "../private/manifest.json",
    "render/../private/manifest.json",
    "render/*/index.json",
)
API_ROUTES = (
    ("get", "/api/v1/boba/projects/{project_id}/artifact-inspector"),
    ("get", "/api/v1/boba/projects/{project_id}/artifact-inspector/registry"),
    ("get", "/api/v1/boba/projects/{project_id}/artifact-inspector/types"),
    ("post", "/api/v1/boba/projects/{project_id}/artifact-inspector/requests"),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/artifact-inspector/requests/{request_id}/validate",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/artifact-inspector/requests/{request_id}/inspect",
    ),
    ("get", "/api/v1/boba/projects/{project_id}/artifact-inspector/runs/{run_id}"),
    ("post", "/api/v1/boba/projects/{project_id}/artifact-inspector/inventory"),
    ("post", "/api/v1/boba/projects/{project_id}/artifact-inspector/lineage"),
    ("post", "/api/v1/boba/projects/{project_id}/artifact-inspector/compare"),
    (
        "get",
        "/api/v1/boba/projects/{project_id}/artifact-inspector/runs/{run_id}/events",
    ),
    ("get", "/api/v1/boba/projects/{project_id}/artifact-inspector/export"),
    ("delete", "/api/v1/boba/projects/{project_id}/artifact-inspector"),
)

_snapshot, _descriptors = build_fixed_artifact_type_registry()
DESCRIPTOR_ASSERTIONS = tuple(
    (descriptor, field_name)
    for descriptor in _descriptors
    for field_name in (
        "artifact_type_id",
        "display_name",
        "owner_module_id",
        "artifact_category",
        "storage_kind",
        "expected_storage_scopes",
        "identity_fields",
        "required_digest_type",
        "maximum_file_bytes",
        "maximum_directory_entries",
        "availability",
        "storage_domain",
    )
)


def _harness(tmp_path: Path) -> ArtifactInspectorSyntheticHarness:
    return ArtifactInspectorSyntheticHarness(tmp_path / "artifact_inspector")


def _manifest_reference(
    harness: ArtifactInspectorSyntheticHarness,
    payload: bytes,
) -> dict[str, Any]:
    key = f"render/{harness.project_id}/run/index.json"
    harness.write(key, payload)
    return harness.reference(
        "render_manifest",
        storage_reference=key,
        payload=payload,
        producer_record_id="render-run-test",
    )


@pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
def test_each_named_artifact_inspector_scenario(
    tmp_path: Path,
    scenario_name: str,
) -> None:
    position = int(scenario_name.split(":", 1)[0])
    requires_harness = position in _EXERCISE_POSITIONS or position in {
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        185,
        186,
    }
    result = run_named_scenario(
        scenario_name,
        _harness(tmp_path) if requires_harness else None,
    )
    assert result.passed, result.detail


@pytest.mark.parametrize("field_name", PROHIBITED_SIGNAL_FIELDS)
def test_prohibited_authority_signal_is_structurally_false(field_name: str) -> None:
    signals = BobaArtifactInspectorSignalUsageV1()
    assert getattr(signals, field_name) is False
    with pytest.raises(PydanticValidationError):
        BobaArtifactInspectorSignalUsageV1.model_validate({field_name: True})


@pytest.mark.parametrize(
    ("descriptor", "field_name"),
    DESCRIPTOR_ASSERTIONS,
    ids=lambda value: getattr(value, "artifact_type_id", str(value)),
)
def test_fixed_descriptor_contracts_are_bounded(
    descriptor: Any,
    field_name: str,
) -> None:
    value = getattr(descriptor, field_name)
    assert value not in (None, "", [])
    assert descriptor.maximum_file_bytes <= 32 * 1024 * 1024
    assert descriptor.maximum_directory_entries <= 4096
    assert descriptor.availability in {"available", "degraded", "unavailable", "future"}


@pytest.mark.parametrize("reference", UNSAFE_REFERENCES)
def test_unsafe_reference_never_reaches_storage(tmp_path: Path, reference: str) -> None:
    harness = _harness(tmp_path)
    assert harness.unsafe_reference_is_rejected(reference)


def test_registry_is_deterministic_immutable_and_fixed(tmp_path: Path) -> None:
    first_snapshot, first_descriptors = build_fixed_artifact_type_registry()
    second_snapshot, second_descriptors = build_fixed_artifact_type_registry()
    assert first_snapshot.registry_digest == second_snapshot.registry_digest
    assert first_snapshot.immutable is True
    assert [item.artifact_type_id for item in first_descriptors] == [
        item.artifact_type_id for item in second_descriptors
    ]
    harness = _harness(tmp_path)
    registry_path = harness.store.boba_artifact_registry_path(
        harness.project_id,
        first_snapshot.registry_snapshot_id,
    )
    assert registry_path.exists()


def test_resolver_registry_has_only_fixed_storage_domains() -> None:
    registry = build_fixed_artifact_resolver_registry()
    assert registry == {"boba_project_store": "boba", "project_storage": "project_storage"}


def test_reference_rejects_cross_scope_and_owner_mismatch(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = b"{}"
    reference = _manifest_reference(harness, payload)
    reference["owner_module_id"] = "validator_runner"
    with pytest.raises(ValidationError, match="owner"):
        harness.inspector.create_inspection_request(
            harness.project_id,
            source_id=harness.source_id,
            requested_by_module="test",
            inspection_mode="exact_artifact",
            artifact_references=[reference],
        )
    reference = _manifest_reference(harness, payload)
    reference["sanitized_storage_reference"] = "render/other-project/run/index.json"
    with pytest.raises(ValidationError, match="fixed project-scoped"):
        harness.inspector.create_inspection_request(
            harness.project_id,
            source_id=harness.source_id,
            requested_by_module="test",
            inspection_mode="exact_artifact",
            artifact_references=[reference],
        )


def test_reference_contract_rejects_traversal_and_bad_digest() -> None:
    with pytest.raises(ValidationError):
        BobaArtifactReferenceV1(
            artifact_reference_id="reference",
            project_id=PROJECT_ID,
            source_id=SOURCE_ID,
            owner_module_id="rendering",
            artifact_type_id="render_manifest",
            sanitized_storage_reference="../outside.json",
            storage_kind="manifest",
        )
    with pytest.raises(PydanticValidationError):
        BobaArtifactReferenceV1(
            artifact_reference_id="reference",
            project_id=PROJECT_ID,
            source_id=SOURCE_ID,
            owner_module_id="rendering",
            artifact_type_id="render_manifest",
            expected_digest="not-a-digest",
            sanitized_storage_reference=f"render/{PROJECT_ID}/run/index.json",
            storage_kind="manifest",
        )


def test_presence_digest_size_and_format_are_observed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = b'{"clips":[]}'
    result = harness.inspect([_manifest_reference(harness, payload)])
    snapshot = result["inspection"]["snapshots"][0]
    integrity = result["inspection"]["integrity"][0]
    assert snapshot["exists"] is True
    assert snapshot["observed_size_bytes"] == len(payload)
    assert snapshot["recomputed_digest_used"] is True
    assert integrity["recomputed_digest_status"] == "match"
    assert integrity["status"] == "deeper_validation_required"


def test_missing_and_optional_artifacts_are_honest(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    key = f"render/{harness.project_id}/run/index.json"
    required = harness.inspect(
        [harness.reference("render_manifest", storage_reference=key, required=True)]
    )
    optional = harness.inspect(
        [harness.reference("render_manifest", storage_reference=key, required=False)]
    )
    assert required["inspection"]["integrity"][0]["status"] == "missing"
    assert optional["inspection"]["integrity"][0]["status"] == "missing"
    inventory = required["inspection"]["coverage"]
    assert inventory["missing_required_count"] == 1


def test_partial_malformed_and_wrong_type_do_not_pass(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    partial = harness.inspect([_manifest_reference(harness, b"")])
    assert partial["inspection"]["integrity"][0]["status"] == "partial"
    malformed = harness.inspect([_manifest_reference(harness, b"not-json")])
    assert malformed["inspection"]["integrity"][0]["status"] == "malformed"
    key = f"render/{harness.project_id}/run/index.json"
    directory = harness.storage_root / key
    directory.unlink()
    directory.mkdir(parents=True)
    wrong_type = harness.inspect(
        [harness.reference("render_manifest", storage_reference=key)]
    )
    assert wrong_type["inspection"]["integrity"][0]["status"] == "wrong_type"


def test_rights_sensitive_source_media_is_metadata_only(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = b"\x00\x00\x00\x18ftypisom"
    key = f"projects/{harness.project_id}/source/source-test.mp4"
    harness.write(key, payload)
    result = harness.inspect(
        [
            harness.reference(
                "source_media",
                storage_reference=key,
                payload=payload,
                source_media=True,
                rights_status="unknown",
                producer_record_id="source-test",
            )
        ]
    )
    snapshot = result["inspection"]["snapshots"][0]
    integrity = result["inspection"]["integrity"][0]
    assert snapshot["recomputed_digest_used"] is False
    assert integrity["status"] == "rights_blocked"
    assert integrity["recomputed_digest_status"] == "blocked"


def test_accepted_output_is_immutable_and_never_writable(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = b"\x00\x00\x00\x18ftypisom"
    key = f"render/{harness.project_id}/clips/clip-accepted.mp4"
    harness.write(key, payload)
    reference = harness.reference(
        "accepted_output",
        storage_reference=key,
        payload=payload,
        clip_id="clip-accepted",
        accepted_output=True,
        immutable=False,
    )
    with pytest.raises(ValidationError, match="Accepted outputs"):
        harness.inspector.create_inspection_request(
            harness.project_id,
            source_id=harness.source_id,
            requested_by_module="test",
            inspection_mode="accepted_output",
            artifact_references=[reference],
        )


def test_digest_mismatch_and_changed_artifact_invalidate_reuse(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = b'{"clips":[]}'
    reference = _manifest_reference(harness, payload)
    first = harness.inspect([reference])
    second = harness.inspector.inspect_artifacts(
        harness.project_id,
        first["request"].inspection_request_id,
    )
    assert second.inspection_run_id == first["run"].inspection_run_id
    assert second.reused_existing_result is True
    changed_payload = b'{"claps":[]}'
    harness.write(reference["sanitized_storage_reference"], changed_payload)
    third = harness.inspector.inspect_artifacts(
        harness.project_id,
        first["request"].inspection_request_id,
    )
    assert third.inspection_run_id != first["run"].inspection_run_id
    run = harness.inspector.inspect_run(harness.project_id, third.inspection_run_id)
    assert run["integrity"][0]["status"] == "digest_mismatch"


def test_inventory_lineage_comparison_and_handoffs_are_advisory(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    baseline = harness.baseline()
    request = baseline["request"]
    run = baseline["run"]
    reference_ids = request.artifact_reference_ids
    comparison = harness.inspector.compare_artifacts(
        harness.project_id,
        inspection_run_id=run.inspection_run_id,
        left_reference_id=reference_ids[0],
        right_reference_id=reference_ids[1],
    )
    inventory = harness.inspector.build_project_inventory(
        harness.project_id,
        inspection_run_id=run.inspection_run_id,
    )
    lineage = harness.inspector.inspect_lineage(
        harness.project_id,
        inspection_run_id=run.inspection_run_id,
    )
    inspected = harness.inspector.inspect_run(harness.project_id, run.inspection_run_id)
    assert comparison.result in {"different", "inconclusive", "conflict", "match"}
    assert inventory.inventory_digest
    assert harness.store.boba_artifact_inventory_path(
        harness.project_id,
        inventory.inventory_id,
    ).is_file()
    assert harness.store.boba_artifact_comparison_path(
        harness.project_id,
        comparison.comparison_id,
    ).is_file()
    assert lineage["filename_or_timestamp_inference_used"] is False
    for handoff in inspected["handoffs"]:
        assert handoff["automatic_execution"] is False
        assert "artifact_snapshot_ids" in handoff
        assert "observed_digests" in handoff
        assert "blocking_conditions" in handoff
        assert "protected_state_requirements" in handoff


def test_persistence_export_and_reset_preserve_artifacts(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    baseline = harness.baseline()
    run = baseline["run"]
    loaded = harness.store.load_boba_artifact_inspector(harness.project_id)
    assert isinstance(loaded, BobaArtifactInspectorSetV1)
    assert loaded.inspection_runs
    snapshot_path = harness.store.boba_artifact_snapshot_path(
        harness.project_id,
        run.inspection_run_id,
        run.artifact_snapshot_ids[0],
    )
    inventory = next(
        item
        for item in loaded.inventories
        if item.inspection_run_id == run.inspection_run_id
    )
    inventory_path = harness.store.boba_artifact_inventory_path(
        harness.project_id,
        inventory.inventory_id,
    )
    assert snapshot_path.is_file()
    assert inventory_path.is_file()
    exported = harness.inspector.export_artifact_inspection(harness.project_id)
    reset = harness.inspector.reset_artifact_inspector_metadata(harness.project_id)
    assert exported["raw_media_included"] is False
    assert exported["source_code_included"] is False
    assert reset["active_metadata_removed"] is True
    assert reset["artifacts_preserved"] is True
    assert reset["accepted_outputs_preserved"] is True
    assert harness.store.load_boba_artifact_inspector(harness.project_id) is None
    assert snapshot_path.is_file()
    assert inventory_path.is_file()
    assert baseline["run"].inspection_run_id


def test_export_sanitizes_private_paths_and_secrets() -> None:
    exported = sanitize_artifact_export(
        {
            "path": r"C:\Users\private\secret.txt",
            "token": "very-secret-token",
            "nested": {"password": "hidden"},
        }
    )
    assert "private" not in json.dumps(exported).casefold()
    assert "very-secret-token" not in json.dumps(exported)
    assert "hidden" not in json.dumps(exported)


def test_self_check_passes_without_authority() -> None:
    result = run_self_check()
    assert result["passed"] is True
    assert result["scenario_count"] >= 218
    assert result["checks"]["no_authority_signals"] is True


def test_integration_layer_and_safety_gate_register_read_only_operations() -> None:
    modules = build_boba_module_registry()
    operations = build_boba_operation_registry()
    safety = build_safety_module_operation_registry()
    assert modules["artifact_inspector"].read_only is True
    for operation in (
        "inspect_registry",
        "create_inspection_request",
        "validate_references",
        "inspect_artifacts",
        "inspect_run",
        "build_inventory",
        "inspect_lineage",
        "compare_artifacts",
        "inspect_events",
    ):
        key = f"artifact_inspector.{operation}"
        assert operations[key].operation_class == "read_only"
        assert safety["artifact_inspector"][operation] == "automatic_read_only"


def test_completed_run_record_is_not_rewritten_by_newer_payload_shape(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run = harness.baseline()["run"]
    run_path = harness.store.boba_artifact_run_path(
        harness.project_id,
        run.inspection_run_id,
    )
    legacy_payload = json.loads(run_path.read_text(encoding="utf-8"))
    legacy_payload.pop("events", None)
    legacy_payload.pop("inventory", None)
    run_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    inspector = harness.store.load_boba_artifact_inspector(harness.project_id)
    assert isinstance(inspector, BobaArtifactInspectorSetV1)
    harness.store.save_boba_artifact_inspector(inspector)

    preserved_payload = json.loads(run_path.read_text(encoding="utf-8"))
    assert "events" not in preserved_payload
    assert "inventory" not in preserved_payload


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Artifact Inspector Test",
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


@pytest.mark.parametrize(("method", "route"), API_ROUTES)
def test_every_artifact_inspector_api_route_is_registered(
    app: FastAPI,
    method: str,
    route: str,
) -> None:
    registered = app.openapi()["paths"]
    assert route in registered
    assert method in registered[route]


def test_api_inspects_only_typed_registered_artifacts(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    manifest_payload = b'{"clips":[]}'
    clip_payload = b"\x00\x00\x00\x18ftypisom"
    manifest_key = f"render/{PROJECT_ID}/run/index.json"
    clip_key = f"render/{PROJECT_ID}/clips/clip-api.mp4"
    asyncio.run(integration.storage.put(manifest_key, manifest_payload))
    asyncio.run(integration.storage.put(clip_key, clip_payload))
    base = f"/api/v1/boba/projects/{PROJECT_ID}/artifact-inspector"
    try:
        with TestClient(app) as client:
            registry = client.get(f"{base}/registry")
            types = client.get(f"{base}/types")
            created = client.post(
                f"{base}/requests",
                json={
                    "source_id": SOURCE_ID,
                    "requested_by_module": "rendering",
                    "inspection_mode": "project_inventory",
                    "artifact_references": [
                        {
                            "owner_module_id": "rendering",
                            "producer_record_id": "render-api",
                            "artifact_type_id": "render_manifest",
                            "sanitized_storage_reference": manifest_key,
                            "storage_kind": "manifest",
                            "expected_digest": "sha256:"
                            + hashlib.sha256(manifest_payload).hexdigest(),
                            "expected_size_bytes": len(manifest_payload),
                        },
                        {
                            "owner_module_id": "rendering",
                            "producer_record_id": "render-api",
                            "artifact_type_id": "rendered_output",
                            "sanitized_storage_reference": clip_key,
                            "storage_kind": "file",
                            "clip_id": "clip-api",
                            "output_id": "output-api",
                            "expected_digest": "sha256:"
                            + hashlib.sha256(clip_payload).hexdigest(),
                            "expected_size_bytes": len(clip_payload),
                        },
                    ],
                },
            )
            request_id = created.json()["inspection_request_id"]
            validated = client.post(f"{base}/requests/{request_id}/validate")
            inspected = client.post(f"{base}/requests/{request_id}/inspect")
            run_id = inspected.json()["inspection_run_id"]
            run = client.get(f"{base}/runs/{run_id}")
            inventory = client.post(f"{base}/inventory", json={"inspection_run_id": run_id})
            lineage = client.post(f"{base}/lineage", json={"inspection_run_id": run_id})
            request_data = created.json()["artifact_reference_ids"]
            comparison = client.post(
                f"{base}/compare",
                json={
                    "inspection_run_id": run_id,
                    "left_reference_id": request_data[0],
                    "right_reference_id": request_data[1],
                },
            )
            events = client.get(f"{base}/runs/{run_id}/events")
            exported = client.get(f"{base}/export")
            reset = client.delete(base)
    finally:
        app.dependency_overrides.pop(boba_integration_provider, None)
    for response in (
        registry,
        types,
        created,
        validated,
        inspected,
        run,
        inventory,
        lineage,
        comparison,
        events,
        exported,
        reset,
    ):
        assert response.status_code == 200, response.text
    assert all(item["valid"] for item in validated.json()["references"])
    assert run.json()["run"]["status"] == "completed"
    assert events.json()["events"]
    assert exported.json()["raw_media_included"] is False
    assert reset.json()["active_metadata_removed"] is True
    assert reset.json()["artifacts_preserved"] is True


def test_api_rejects_uncontracted_artifact_inspector_fields(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/boba/projects/{PROJECT_ID}/artifact-inspector/requests",
                json={
                    "artifact_references": [],
                    "filesystem_root": "C:\\private",
                },
            )
    finally:
        app.dependency_overrides.pop(boba_integration_provider, None)
    assert response.status_code == 422


def test_frontend_panel_has_only_read_only_controls() -> None:
    panel = Path("frontend/src/components/project/BobaArtifactInspectorPanel.tsx")
    content = panel.read_text(encoding="utf-8")
    for heading in (
        "ARTIFACT REGISTRY",
        "ARTIFACT IDENTITY",
        "STORAGE AND FORMAT",
        "INTEGRITY",
        "FRESHNESS",
        "PROTECTION",
        "INVENTORY",
        "LINEAGE",
        "MISSING OR ORPHANED ARTIFACTS",
        "DUPLICATES AND CONFLICTS",
        "DEEPER VALIDATION REQUIRED",
        "WHAT HAPPENS NEXT",
    ):
        assert heading in content
    assert "Browse arbitrary path" not in content
    assert "Restore checkpoint" not in content
    assert "Artifact Inspector checks registered local artifacts without changing them." in content
    assert "Accepted outputs and source media remain protected and read-only." in content


def test_absent_inspector_is_not_silently_fabricated(tmp_path: Path) -> None:
    inspector = BobaArtifactInspectorV1(
        BobaMemoryStore(tmp_path / "boba"),
        LocalStorage(str(tmp_path / "storage")),
    )
    with pytest.raises(NotFoundError):
        inspector.export_artifact_inspection(PROJECT_ID)
