"""BOBA Report Reader V1 safety, persistence, API, and UI regressions."""

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
from tools.validate_boba_report_reader import (
    SCENARIO_NAMES,
    ReportReaderSyntheticHarness,
    run_named_scenario,
    run_self_check,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.contracts import BobaContract
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.report_reader import (
    BobaReportReaderSetV1,
    BobaReportReaderSignalUsageV1,
    BobaReportReaderV1,
    DuplicateJsonKeyError,
    MalformedReportError,
    _bounded_text_parse,
    _strict_json_parse,
    _strict_jsonl_parse,
    build_fixed_report_parser_registry,
    build_fixed_report_source_registry,
    calculate_report_bundle_digest,
    calculate_report_request_digest,
    sanitize_report_export,
)
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_report_reader_test"
SOURCE_ID = "source_boba_report_reader_test"
SNAPSHOT_DIGEST = "c" * 64

CONTRACT_NAMES = (
    "BobaReportReaderSetV1",
    "BobaReportRegistrySnapshotV1",
    "BobaReportSourceDescriptorV1",
    "BobaReportReferenceV1",
    "BobaReportReadRequestV1",
    "BobaReportReadRunV1",
    "BobaReportDocumentV1",
    "BobaReportSectionV1",
    "BobaReportFindingV1",
    "BobaReportEvidenceReferenceV1",
    "BobaReportStatusInterpretationV1",
    "BobaReportChronologyEntryV1",
    "BobaReportContradictionV1",
    "BobaReportCoverageV1",
    "BobaReportBundleV1",
    "BobaReportOpenQuestionV1",
    "BobaReportIncidentV1",
    "BobaReportEventV1",
    "BobaReportHandoffV1",
    "BobaReportReaderSummaryV1",
    "BobaReportReaderSignalUsageV1",
)
PROHIBITED_SIGNAL_FIELDS = (
    "arbitrary_path_scanning_used",
    "arbitrary_parser_loading_used",
    "arbitrary_dynamic_import_used",
    "arbitrary_function_invocation_used",
    "command_execution_used",
    "shell_execution_used",
    "git_execution_used",
    "ffmpeg_execution_used",
    "report_modification_used",
    "source_media_modified",
    "accepted_outputs_modified",
    "checkpoint_restore_used",
    "workflow_transition_used",
    "quality_authorization_used",
    "safety_authorization_used",
    "approval_creation_used",
    "external_api_used",
    "network_access_used",
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
    "https://example.invalid/report.json",
    "http://example.invalid/report.json",
    "ftp://example.invalid/report.json",
    "file:///private/report.json",
    "//server/share/report.json",
    r"\\server\share\report.json",
    r"\\?\C:\private\report.json",
    r"C:\private\report.json",
    "/private/report.json",
    "../private/report.json",
    "projects/../private/report.json",
    "projects/proj/../../private/report.json",
    "projects/proj/..",
    "projects/proj/validator_runner/../index.json",
    " ",
)
API_ROUTES = (
    ("get", "/api/v1/boba/projects/{project_id}/report-reader"),
    ("get", "/api/v1/boba/projects/{project_id}/report-reader/registry"),
    ("get", "/api/v1/boba/projects/{project_id}/report-reader/sources"),
    ("post", "/api/v1/boba/projects/{project_id}/report-reader/requests"),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/report-reader/requests/{request_id}/validate",
    ),
    (
        "post",
        "/api/v1/boba/projects/{project_id}/report-reader/requests/{request_id}/read",
    ),
    (
        "get",
        "/api/v1/boba/projects/{project_id}/report-reader/runs/{run_id}",
    ),
    ("post", "/api/v1/boba/projects/{project_id}/report-reader/compare"),
    ("post", "/api/v1/boba/projects/{project_id}/report-reader/bundles"),
    (
        "get",
        "/api/v1/boba/projects/{project_id}/report-reader/bundles/{bundle_id}",
    ),
    (
        "get",
        "/api/v1/boba/projects/{project_id}/report-reader/runs/{run_id}/events",
    ),
    ("get", "/api/v1/boba/projects/{project_id}/report-reader/export"),
    ("delete", "/api/v1/boba/projects/{project_id}/report-reader"),
)


@pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
def test_each_named_reader_scenario(
    tmp_path: Path,
    scenario_name: str,
) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / scenario_name)
    result = run_named_scenario(scenario_name, harness)
    assert result.passed, result.detail


@pytest.mark.parametrize("field_name", PROHIBITED_SIGNAL_FIELDS)
def test_prohibited_reader_signal_is_structurally_false(field_name: str) -> None:
    signals = BobaReportReaderSignalUsageV1()
    assert getattr(signals, field_name) is False
    with pytest.raises(PydanticValidationError):
        BobaReportReaderSignalUsageV1.model_validate({field_name: True})


@pytest.mark.parametrize(
    "descriptor",
    build_fixed_report_source_registry()[1],
    ids=lambda value: value.source_descriptor_id,
)
def test_each_fixed_descriptor_is_static_and_bounded(descriptor: Any) -> None:
    parser_registry = build_fixed_report_parser_registry()
    assert descriptor.source_descriptor_id
    assert descriptor.producer_module_id
    assert descriptor.schema_id
    assert descriptor.parser_id in parser_registry
    assert descriptor.maximum_bytes > 0
    assert descriptor.maximum_records > 0
    assert descriptor.maximum_depth > 0
    assert descriptor.maximum_string_length > 0
    assert descriptor.availability in {"available", "unavailable", "future"}


@pytest.fixture
def rich_reader(tmp_path: Path) -> BobaReportReaderSetV1:
    harness = ReportReaderSyntheticHarness(tmp_path / "rich")
    valid_path, valid_suffix = harness.write_json(
        "validator_runner.index",
        harness.payload(
            "validator_runner.index",
            warnings=["Source warning"],
            limitations=["Source limitation"],
        ),
    )
    valid = harness.read([harness.reference("validator_runner.index", valid_suffix, valid_path)])
    harness.reader.build_report_bundle(
        harness.project_id,
        read_run_id=valid["run"]["read_run_id"],
        purpose="Contract coverage",
    )

    malformed_path, malformed_suffix = harness.write_json(
        "validator_runner.run",
        record_id="malformed_contract",
        raw=b'{"status": "completed", "status": "failed"}',
    )
    harness.read(
        [
            harness.reference(
                "validator_runner.run",
                malformed_suffix,
                malformed_path,
                record_id="malformed_contract",
            )
        ],
        reading_mode="validation_review",
    )

    left_path, left_suffix = harness.write_json(
        "validator_runner.index",
        harness.payload(
            "validator_runner.index",
            status="failed",
            decision="failed",
            artifact_id="shared_contract_artifact",
        ),
        record_id="contradiction_left",
    )
    right_path, right_suffix = harness.write_json(
        "output_quality.index",
        harness.payload(
            "output_quality.index",
            status="accepted",
            decision="accepted",
            artifact_id="shared_contract_artifact",
        ),
        record_id="contradiction_right",
    )
    harness.read(
        [
            harness.reference(
                "validator_runner.index",
                left_suffix,
                left_path,
                record_id="contradiction_left",
            ),
            harness.reference(
                "output_quality.index",
                right_suffix,
                right_path,
                record_id="contradiction_right",
            ),
        ],
        reading_mode="comparison_review",
    )
    reader = harness.store.load_boba_report_reader(harness.project_id)
    assert reader is not None
    return reader


@pytest.mark.parametrize("contract_name", CONTRACT_NAMES)
def test_every_reader_contract_serializes_as_json(
    rich_reader: BobaReportReaderSetV1,
    contract_name: str,
) -> None:
    contracts: list[BobaContract] = [
        rich_reader,
        rich_reader.registry_snapshots[-1],
        rich_reader.source_descriptors[0],
        rich_reader.report_references[0],
        rich_reader.read_requests[0],
        rich_reader.read_runs[0],
        rich_reader.report_documents[0],
        rich_reader.report_sections[0],
        rich_reader.findings[0],
        rich_reader.evidence_references[0],
        rich_reader.status_interpretations[0],
        rich_reader.chronology_entries[0],
        rich_reader.contradictions[0],
        rich_reader.coverage_records[0],
        rich_reader.report_bundles[0],
        rich_reader.open_questions[0],
        rich_reader.incidents[0],
        rich_reader.events[0],
        rich_reader.handoffs[0],
        rich_reader.reader_summary,
        rich_reader.signal_usage,
    ]
    by_name = {item.__class__.__name__: item for item in contracts}
    assert contract_name in by_name
    payload = by_name[contract_name].model_dump(mode="json")
    assert json.loads(json.dumps(payload)) == payload


@pytest.mark.parametrize("reference", UNSAFE_REFERENCES)
def test_create_request_rejects_unsafe_reference_text(
    tmp_path: Path,
    reference: str,
) -> None:
    reader = BobaReportReaderV1(BobaMemoryStore(tmp_path / "boba"))
    with pytest.raises((PydanticValidationError, ValidationError, ValueError)):
        reader.create_report_read_request(
            PROJECT_ID,
            source_id=SOURCE_ID,
            requested_by_module="validator_runner",
            reading_mode="validation_review",
            report_references=[
                {
                    "source_descriptor_id": "validator_runner.index",
                    "sanitized_storage_reference": reference,
                }
            ],
        )


@pytest.mark.parametrize(
    ("raw", "expected_error"),
    (
        (b'{"ok": true, "ok": false}', DuplicateJsonKeyError),
        (b'{"value": NaN}', MalformedReportError),
        (b'{"token": "secret"}', MalformedReportError),
        (b"\xff\xfe", MalformedReportError),
        (b'{"value": "' + b"x" * 70_000 + b'"}', MalformedReportError),
        (
            b'{"nested": ' + b'{"node": ' * 34 + b"1" + b"}" * 35,
            MalformedReportError,
        ),
        (b'{"list": [' + b",".join(b"0" for _ in range(10_001)) + b"]}", MalformedReportError),
    ),
    ids=(
        "duplicate-key",
        "nonfinite",
        "secret",
        "invalid-utf8",
        "long-string",
        "deep-nesting",
        "large-list",
    ),
)
def test_strict_json_parser_rejects_unsafe_or_unbounded_content(
    raw: bytes,
    expected_error: type[Exception],
) -> None:
    descriptor = build_fixed_report_source_registry()[1][0]
    with pytest.raises(expected_error):
        _strict_json_parse(raw, descriptor)


def test_jsonl_and_text_parsers_are_bounded_and_inert() -> None:
    _snapshot, descriptors = build_fixed_report_source_registry()
    descriptor_by_id = {item.source_descriptor_id: item for item in descriptors}
    records = _strict_jsonl_parse(
        b'{"event_id": "event_one", "status": "completed"}\n',
        descriptor_by_id["validator_runner.events"],
    )
    assert records[0]["_line_number"] == 1
    with pytest.raises(MalformedReportError):
        _strict_jsonl_parse(
            b'{"event_id": "ok"}\nnot-json\n',
            descriptor_by_id["validator_runner.events"],
        )
    text_descriptor = descriptor_by_id["validator_runner.index"].model_copy(
        update={
            "expected_format": "markdown",
            "parser_id": "bounded_markdown_parser",
        }
    )
    text = _bounded_text_parse(
        b"# Report\n<script>never-executed()</script>\nhttps://example.invalid",
        text_descriptor,
    )
    assert "never-executed" in text
    assert "https://example.invalid" in text


def test_request_and_bundle_digests_are_stable_and_sensitive() -> None:
    request = calculate_report_request_digest({"project_id": "proj", "value": 1})
    assert request == calculate_report_request_digest({"value": 1, "project_id": "proj"})
    assert request != calculate_report_request_digest({"project_id": "proj", "value": 2})
    bundle = calculate_report_bundle_digest({"project_id": "proj", "value": 1})
    assert bundle == calculate_report_bundle_digest({"value": 1, "project_id": "proj"})
    assert bundle != calculate_report_bundle_digest({"project_id": "proj", "value": 2})


def test_reader_persists_exact_references_without_raw_report_bodies(
    tmp_path: Path,
) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / "persistence")
    payload = harness.payload("validator_runner.index")
    payload["unmodeled_detail"] = "must not become a raw report copy"
    path, suffix = harness.write_json("validator_runner.index", payload)
    inspection = harness.read([harness.reference("validator_runner.index", suffix, path)])
    reader = harness.store.load_boba_report_reader(harness.project_id)
    assert reader is not None
    document_path = harness.store.boba_report_reader_document_path(
        harness.project_id,
        inspection["run"]["read_run_id"],
        inspection["documents"][0]["report_document_id"],
    )
    stored = document_path.read_text(encoding="utf-8")
    assert "unmodeled_detail" not in stored
    assert "raw_report" not in stored
    assert reader.report_references[0].expected_digest


def test_reader_reuses_identical_read_and_invalidates_changed_content(
    tmp_path: Path,
) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / "idempotency")
    path, suffix = harness.write_json("validator_runner.index")
    first_reference = harness.reference("validator_runner.index", suffix, path)
    first = harness.read([first_reference])
    repeated = harness.read([first_reference])
    assert repeated["run"]["read_run_id"] == first["run"]["read_run_id"]
    assert repeated["run"]["reused_existing_result"] is True

    changed_payload = harness.payload("validator_runner.index", decision="failed")
    path.write_text(json.dumps(changed_payload), encoding="utf-8")
    changed = harness.read([harness.reference("validator_runner.index", suffix, path)])
    assert changed["run"]["read_run_id"] != first["run"]["read_run_id"]


def test_reader_marks_historical_evidence_and_hands_it_to_workflow(
    tmp_path: Path,
) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / "historical")
    path, suffix = harness.write_json("workflow_controller.index")
    inspection = harness.read(
        [
            harness.reference(
                "workflow_controller.index",
                suffix,
                path,
                historical=True,
            )
        ]
    )
    assert inspection["documents"][0]["stale"] is True
    assert any(item["target_module_id"] == "workflow_controller" for item in inspection["handoffs"])
    assert all(item["apply_automatically"] is False for item in inspection["handoffs"])


def test_reader_only_compares_explicit_shared_targets(tmp_path: Path) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / "targets")
    left_path, left_suffix = harness.write_json(
        "validator_runner.index",
        harness.payload(
            "validator_runner.index",
            status="failed",
            decision="failed",
            artifact_id="artifact_left",
        ),
        record_id="left",
    )
    right_path, right_suffix = harness.write_json(
        "output_quality.index",
        harness.payload(
            "output_quality.index",
            status="accepted",
            decision="accepted",
            artifact_id="artifact_right",
        ),
        record_id="right",
    )
    inspection = harness.read(
        [
            harness.reference("validator_runner.index", left_suffix, left_path, record_id="left"),
            harness.reference("output_quality.index", right_suffix, right_path, record_id="right"),
        ],
        reading_mode="comparison_review",
    )
    assert inspection["contradictions"] == []


def test_sanitized_export_redacts_paths_secrets_and_raw_logs() -> None:
    exported = sanitize_report_export(
        {
            "private_path": r"D:\private\report.json",
            "token": "secret-value",
            "stdout": "x" * 50_000,
            "safe": "visible",
            "quality_authorization_used": False,
        }
    )
    encoded = json.dumps(exported)
    assert r"D:\private\report.json" not in encoded
    assert "secret-value" not in encoded
    assert len(exported["stdout"]) <= 4_000
    assert exported["safe"] == "visible"
    assert exported["quality_authorization_used"] is False


def test_reader_registry_rejects_unknown_or_future_sources(tmp_path: Path) -> None:
    reader = BobaReportReaderV1(BobaMemoryStore(tmp_path / "boba"))
    with pytest.raises(ValidationError, match="unknown fixed source"):
        reader.create_report_read_request(
            PROJECT_ID,
            source_id=SOURCE_ID,
            requested_by_module="validator_runner",
            reading_mode="validation_review",
            report_references=[
                {
                    "source_descriptor_id": "attacker.dynamic",
                    "sanitized_storage_reference": "projects/proj/report.json",
                }
            ],
        )

    source = reader.inspect_report_source_registry(PROJECT_ID, source_id=SOURCE_ID)
    future = next(
        item
        for item in source["sources"]
        if item["source_descriptor_id"] == "checkpoint_integrity.future"
    )
    future_path = reader.store.root / "projects" / PROJECT_ID / "checkpoint scope is future-gated"
    future_path.parent.mkdir(parents=True, exist_ok=True)
    future_path.write_text("{}", encoding="utf-8")
    request = reader.create_report_read_request(
        PROJECT_ID,
        source_id=SOURCE_ID,
        requested_by_module="validator_runner",
        reading_mode="validation_review",
        report_references=[
            {
                "source_descriptor_id": future["source_descriptor_id"],
                "sanitized_storage_reference": (
                    f"projects/{PROJECT_ID}/checkpoint scope is future-gated"
                ),
            }
        ],
    )
    validation = reader.validate_report_references(PROJECT_ID, request.read_request_id)
    assert validation["valid"] is False
    assert "future-gated" in validation["errors"][0]


def test_reader_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / "symlink")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link_path = (
        harness.store.root / "projects" / harness.project_id / "validator_runner" / "index.json"
    )
    link_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        link_path.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable in this Windows environment.")
    request = harness.reader.create_report_read_request(
        harness.project_id,
        source_id=harness.source_id,
        requested_by_module="validator_runner",
        reading_mode="validation_review",
        report_references=[
            {
                "source_descriptor_id": "validator_runner.index",
                "sanitized_storage_reference": (
                    f"projects/{harness.project_id}/validator_runner/index.json"
                ),
            }
        ],
    )
    validation = harness.reader.validate_report_references(
        harness.project_id,
        request.read_request_id,
    )
    assert validation["valid"] is False
    assert "escaped" in validation["errors"][0]


def test_reader_respects_disabled_chronology_and_open_questions(tmp_path: Path) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / "options")
    path, suffix = harness.write_json("validator_runner.index")
    inspection = harness.read(
        [harness.reference("validator_runner.index", suffix, path)],
        reading_mode="recovery_review",
        include_chronology=False,
        include_open_questions=False,
    )
    assert inspection["chronology"] == []
    assert inspection["open_questions"] == []


def test_reader_preserves_valid_source_confidence(tmp_path: Path) -> None:
    harness = ReportReaderSyntheticHarness(tmp_path / "confidence")
    path, suffix = harness.write_json(
        "validator_runner.index",
        harness.payload("validator_runner.index", confidence=0.82),
    )
    inspection = harness.read([harness.reference("validator_runner.index", suffix, path)])
    assert inspection["findings"][0]["confidence"] == 0.82


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Report Reader Test",
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
def test_every_report_reader_api_route_is_registered(
    app: FastAPI,
    method: str,
    route: str,
) -> None:
    registered = app.openapi()["paths"]
    assert route in registered
    assert method in registered[route]


def test_api_reads_registered_report_and_preserves_safe_metadata(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    path = integration.store.root / "projects" / PROJECT_ID / "validator_runner" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "boba_validator_runner_v1",
                "project_id": PROJECT_ID,
                "source_id": SOURCE_ID,
                "project_snapshot_digest": SNAPSHOT_DIGEST,
                "status": "completed",
                "decision": "passed",
                "artifact_id": "api_artifact",
            }
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    base = f"/api/v1/boba/projects/{PROJECT_ID}/report-reader"
    with TestClient(app) as client:
        registry = client.get(f"{base}/registry")
        sources = client.get(f"{base}/sources")
        created = client.post(
            f"{base}/requests",
            json={
                "source_id": SOURCE_ID,
                "requested_by_module": "validator_runner",
                "reading_mode": "validation_review",
                "current_project_snapshot_digest": SNAPSHOT_DIGEST,
                "report_references": [
                    {
                        "source_descriptor_id": "validator_runner.index",
                        "sanitized_storage_reference": (
                            f"projects/{PROJECT_ID}/validator_runner/index.json"
                        ),
                        "expected_digest": digest,
                    }
                ],
            },
        )
        request_id = created.json()["read_request_id"]
        validated = client.post(f"{base}/requests/{request_id}/validate")
        read = client.post(f"{base}/requests/{request_id}/read")
        run_id = read.json()["run"]["read_run_id"]
        compared = client.post(f"{base}/compare", json={"read_run_id": run_id})
        bundled = client.post(
            f"{base}/bundles",
            json={"read_run_id": run_id, "purpose": "API route coverage"},
        )
        bundle_id = bundled.json()["report_bundle_id"]
        bundle = client.get(f"{base}/bundles/{bundle_id}")
        events = client.get(f"{base}/runs/{run_id}/events")
        exported = client.get(f"{base}/export")
        reset = client.delete(base)
    for response in (
        registry,
        sources,
        created,
        validated,
        read,
        compared,
        bundled,
        bundle,
        events,
        exported,
        reset,
    ):
        assert response.status_code == 200, response.text
    assert validated.json()["valid"] is True
    assert read.json()["run"]["status"] == "completed"
    assert bundled.json()["suitable_for_current_action"] is False
    assert events.json()["events"]
    assert exported.json()["raw_report_bodies_included"] is False
    assert reset.json()["source_reports_preserved"] is True


@pytest.mark.parametrize(
    "unsafe_field",
    (
        "parser_path",
        "callable",
        "command",
        "executable",
        "filesystem_root",
        "url",
        "external_url",
        "raw_report",
    ),
)
def test_api_rejects_uncontracted_report_reader_fields(
    app: FastAPI,
    tmp_path: Path,
    unsafe_field: str,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/report-reader/requests",
            json={
                "report_references": [
                    {
                        "source_descriptor_id": "validator_runner.index",
                        "sanitized_storage_reference": (
                            f"projects/{PROJECT_ID}/validator_runner/index.json"
                        ),
                    }
                ],
                unsafe_field: True,
            },
        )
    assert response.status_code == 422


def test_integration_layer_and_safety_gate_register_read_only_operations() -> None:
    modules = build_boba_module_registry()
    operations = build_boba_operation_registry()
    assert "report_reader" in modules
    report_operations = [
        operation for operation in operations.values() if operation.module_id == "report_reader"
    ]
    assert report_operations
    assert all(
        operation.operation_class in {"read_only", "metadata_reset", "export"}
        for operation in report_operations
    )
    assert all(operation.safety_gate_required is False for operation in report_operations)


def test_frontend_mounts_reader_panel_and_keeps_authority_boundary_visible() -> None:
    component = Path("frontend/src/components/project/BobaReportReaderPanel.tsx").read_text(
        encoding="utf-8"
    )
    results = Path("frontend/src/components/project/ResultsSection.tsx").read_text(encoding="utf-8")
    normalized = " ".join(component.split())
    assert "BobaReportReaderPanel" in results
    assert "without changing their decisions" in normalized
    assert "not the same as quality approval" in normalized
    assert "Historical reports remain visible" in normalized
    assert "Reset active metadata" in component


def test_validator_self_check_passes_without_network_or_source_mutation() -> None:
    report = run_self_check()
    assert report.passed, [item.detail for item in report.scenarios if not item.passed]
    assert report.scenario_count == 198
    assert len(SCENARIO_NAMES) == 198
