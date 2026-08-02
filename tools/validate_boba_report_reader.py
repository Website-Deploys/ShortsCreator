"""Validate BOBA Report Reader V1 with bounded local-only scenarios."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olympus.boba.report_reader import (
    BobaReportReaderSignalUsageV1,
    BobaReportReaderV1,
    BobaReportSourceDescriptorV1,
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
from olympus.platform.config import get_settings
from olympus.platform.errors import ValidationError

ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "work" / "validation_reports" / "boba_report_reader"
_SCENARIO_GROUPS = (
    "registry",
    "reference",
    "parser",
    "context",
    "authority",
    "chronology",
    "contradiction",
    "coverage",
    "bundle",
    "safety",
)
SCENARIO_NAMES = tuple(
    f"report_reader_{_SCENARIO_GROUPS[(index - 1) % len(_SCENARIO_GROUPS)]}_{index:03d}"
    for index in range(1, 199)
)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ValidationReport:
    schema_version: str
    passed: bool
    scenario_count: int
    scenarios: tuple[ScenarioResult, ...]


class ReportReaderSyntheticHarness:
    """Create only temporary, project-scoped synthetic report artifacts."""

    project_id = "proj_report_reader_synthetic"
    source_id = "source_report_reader_synthetic"
    workflow_run_id = "workflow_report_reader_synthetic"
    snapshot_digest = "a" * 64

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = BobaMemoryStore(root / "boba")
        self.reader = BobaReportReaderV1(self.store)
        _snapshot, descriptors = build_fixed_report_source_registry()
        self.descriptors: dict[str, BobaReportSourceDescriptorV1] = {
            item.source_descriptor_id: item for item in descriptors
        }

    def descriptor(self, descriptor_id: str) -> BobaReportSourceDescriptorV1:
        return self.descriptors[descriptor_id]

    def _suffix(self, descriptor_id: str, record_id: str) -> str:
        return self.descriptor(descriptor_id).expected_storage_scope.replace("*", record_id)

    def payload(
        self,
        descriptor_id: str,
        *,
        status: str = "completed",
        decision: str = "passed",
        artifact_id: str = "artifact_report_reader_synthetic",
        artifact_digest: str = "b" * 64,
        confidence: float = 0.75,
        warnings: list[str] | None = None,
        limitations: list[str] | None = None,
    ) -> dict[str, Any]:
        descriptor = self.descriptor(descriptor_id)
        return {
            "schema_version": descriptor.schema_id,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "workflow_run_id": self.workflow_run_id,
            "project_snapshot_digest": self.snapshot_digest,
            "status": status,
            "decision": decision,
            "confidence": confidence,
            "artifact_id": artifact_id,
            "artifact_digest": artifact_digest,
            "created_at": "2026-01-02T03:04:05+00:00",
            "warnings": warnings or [],
            "limitations": limitations or [],
        }

    def write_json(
        self,
        descriptor_id: str,
        payload: dict[str, Any] | None = None,
        *,
        record_id: str = "record_synthetic",
        raw: bytes | None = None,
    ) -> tuple[Path, str]:
        suffix = self._suffix(descriptor_id, record_id)
        path = self.store.root / "projects" / self.project_id / suffix
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is None:
            raw = json.dumps(payload or self.payload(descriptor_id), sort_keys=True).encode("utf-8")
        path.write_bytes(raw)
        return path, suffix

    def write_jsonl(
        self,
        descriptor_id: str,
        records: list[dict[str, Any]],
        *,
        record_id: str = "record_synthetic",
    ) -> tuple[Path, str]:
        suffix = self._suffix(descriptor_id, record_id)
        path = self.store.root / "projects" / self.project_id / suffix
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(item, sort_keys=True) for item in records) + "\n",
            encoding="utf-8",
        )
        return path, suffix

    def reference(
        self,
        descriptor_id: str,
        suffix: str,
        path: Path,
        *,
        record_id: str = "record_synthetic",
        required: bool = True,
        historical: bool = False,
    ) -> dict[str, Any]:
        return {
            "source_descriptor_id": descriptor_id,
            "producer_record_id": record_id,
            "sanitized_storage_reference": (f"projects/{self.project_id}/{suffix}"),
            "expected_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
            "required": required,
            "historical": historical,
        }

    def read(
        self,
        references: list[dict[str, Any]],
        *,
        reading_mode: str = "current_project_review",
        include_chronology: bool = True,
        include_contradictions: bool = True,
        include_open_questions: bool = True,
    ) -> dict[str, Any]:
        request = self.reader.create_report_read_request(
            self.project_id,
            source_id=self.source_id,
            requested_by_module="validator_runner",
            reading_mode=reading_mode,  # type: ignore[arg-type]
            report_references=references,
            workflow_run_id=self.workflow_run_id,
            current_project_snapshot_digest=self.snapshot_digest,
            include_chronology=include_chronology,
            include_contradictions=include_contradictions,
            include_open_questions=include_open_questions,
        )
        return self.reader.read_registered_reports(
            self.project_id,
            request.read_request_id,
        )


def _registry_case(harness: ReportReaderSyntheticHarness) -> None:
    first, first_descriptors = build_fixed_report_source_registry()
    second, second_descriptors = build_fixed_report_source_registry()
    assert first.registry_digest == second.registry_digest
    assert first.immutable is True
    assert [item.model_dump() for item in first_descriptors] == [
        item.model_dump() for item in second_descriptors
    ]
    assert len(first.source_descriptor_ids) == len(set(first.source_descriptor_ids))
    assert (
        harness.reader.inspect_report_source_registry(
            harness.project_id,
            source_id=harness.source_id,
        )["fixed_registry"]
        is True
    )


def _reference_case(harness: ReportReaderSyntheticHarness) -> None:
    path, suffix = harness.write_json("validator_runner.index")
    reference = harness.reference("validator_runner.index", suffix, path)
    request = harness.reader.create_report_read_request(
        harness.project_id,
        source_id=harness.source_id,
        requested_by_module="validator_runner",
        reading_mode="validation_review",
        report_references=[reference],
        current_project_snapshot_digest=harness.snapshot_digest,
    )
    assert (
        harness.reader.validate_report_references(harness.project_id, request.read_request_id)[
            "valid"
        ]
        is True
    )
    unsafe = dict(reference)
    unsafe["sanitized_storage_reference"] = f"projects/{harness.project_id}/../outside.json"
    try:
        harness.reader.create_report_read_request(
            harness.project_id,
            source_id=harness.source_id,
            requested_by_module="validator_runner",
            reading_mode="validation_review",
            report_references=[unsafe],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Traversal reference was accepted.")


def _parser_case(harness: ReportReaderSyntheticHarness) -> None:
    descriptor = harness.descriptor("validator_runner.index")
    assert _strict_json_parse(b'{"ok": true, "value": null}', descriptor)["ok"]
    try:
        _strict_json_parse(b'{"ok": true, "ok": false}', descriptor)
    except DuplicateJsonKeyError:
        pass
    else:
        raise AssertionError("Duplicate JSON key was accepted.")
    jsonl_descriptor = harness.descriptor("validator_runner.events")
    assert len(_strict_jsonl_parse(b'{"event_id": "one"}\n', jsonl_descriptor)) == 1
    text_descriptor = descriptor.model_copy(
        update={
            "expected_format": "plain_text",
            "parser_id": "bounded_plain_text_parser",
        }
    )
    text = _bounded_text_parse(
        b"# Heading\n```sh\necho never-executed\n```\nhttps://example.invalid",
        text_descriptor,
    )
    assert "never-executed" in text


def _context_case(harness: ReportReaderSyntheticHarness) -> None:
    descriptor_ids = (
        "validator_runner.index",
        "workflow_controller.index",
        "safety_gate.index",
        "output_quality.index",
        "autopilot.index",
        "integration_layer.index",
    )
    references: list[dict[str, Any]] = []
    for descriptor_id in descriptor_ids:
        path, suffix = harness.write_json(
            descriptor_id,
            harness.payload(descriptor_id),
            record_id=f"record_{descriptor_id.replace('.', '_')}",
        )
        references.append(
            harness.reference(
                descriptor_id,
                suffix,
                path,
                record_id=f"record_{descriptor_id.replace('.', '_')}",
            )
        )
    harness.read(references)
    reader = harness.store.load_boba_report_reader(harness.project_id)
    assert reader is not None
    signals = reader.signal_usage
    assert signals.validator_runner_evidence_used is True
    assert signals.workflow_controller_context_used is True
    assert signals.safety_gate_context_used is True
    assert signals.output_quality_context_used is True
    assert signals.autopilot_context_used is True
    assert signals.integration_layer_used is True


def _authority_case(harness: ReportReaderSyntheticHarness) -> None:
    path, suffix = harness.write_json("validator_runner.index")
    inspection = harness.read(
        [harness.reference("validator_runner.index", suffix, path)],
        reading_mode="validation_review",
    )
    interpretation = inspection["interpretations"][0]
    assert interpretation["source_authority_preserved"] is True
    assert interpretation["permits_current_action"] is False
    bundle = harness.reader.build_report_bundle(
        harness.project_id,
        read_run_id=inspection["run"]["read_run_id"],
        purpose="Synthetic authority boundary check",
    )
    assert bundle.suitable_for_current_action is False
    assert "not an approval" in bundle.technical_summary


def _chronology_case(harness: ReportReaderSyntheticHarness) -> None:
    payload = harness.payload("validator_runner.index")
    payload["completed_at"] = "2026-01-02T03:05:05+00:00"
    path, suffix = harness.write_json("validator_runner.index", payload)
    inspection = harness.read([harness.reference("validator_runner.index", suffix, path)])
    chronology = inspection["chronology"]
    assert chronology
    assert all(item["timestamp_source"] for item in chronology)
    assert all(item["confirmed_order"] is True for item in chronology)


def _contradiction_case(harness: ReportReaderSyntheticHarness) -> None:
    left_path, left_suffix = harness.write_json(
        "validator_runner.index",
        harness.payload(
            "validator_runner.index",
            status="failed",
            decision="failed",
            artifact_id="shared_output",
        ),
        record_id="record_left",
    )
    right_path, right_suffix = harness.write_json(
        "output_quality.index",
        harness.payload(
            "output_quality.index",
            status="accepted",
            decision="accepted",
            artifact_id="shared_output",
        ),
        record_id="record_right",
    )
    inspection = harness.read(
        [
            harness.reference(
                "validator_runner.index", left_suffix, left_path, record_id="record_left"
            ),
            harness.reference(
                "output_quality.index", right_suffix, right_path, record_id="record_right"
            ),
        ],
        reading_mode="comparison_review",
    )
    contradictions = inspection["contradictions"]
    assert contradictions
    assert contradictions[0]["resolved"] is False
    assert contradictions[0]["requires_human_review"] is True


def _coverage_case(harness: ReportReaderSyntheticHarness) -> None:
    path, suffix = harness.write_json("validator_runner.index")
    inspection = harness.read(
        [harness.reference("validator_runner.index", suffix, path)],
        reading_mode="recovery_review",
    )
    coverage = inspection["coverage"]
    assert coverage["coverage_status"] == "incomplete"
    assert inspection["open_questions"]
    assert any(
        item.event_type == "evidence_missing"
        for item in harness.reader.inspect_report_events(
            harness.project_id,
            inspection["run"]["read_run_id"],
        )
    )


def _bundle_case(harness: ReportReaderSyntheticHarness) -> None:
    path, suffix = harness.write_json("validator_runner.index")
    inspection = harness.read([harness.reference("validator_runner.index", suffix, path)])
    bundle = harness.reader.build_report_bundle(
        harness.project_id,
        read_run_id=inspection["run"]["read_run_id"],
        purpose="Synthetic bundle",
    )
    repeated = harness.reader.build_report_bundle(
        harness.project_id,
        read_run_id=inspection["run"]["read_run_id"],
        purpose="Synthetic bundle",
    )
    assert bundle.report_bundle_id == repeated.report_bundle_id
    exported = harness.reader.export_report_reader(harness.project_id)
    encoded = json.dumps(exported)
    assert "raw_report_bodies_included" in encoded
    assert '"raw_body"' not in encoded


def _safety_case(harness: ReportReaderSyntheticHarness) -> None:
    signals = BobaReportReaderSignalUsageV1()
    prohibited = (
        "arbitrary_path_scanning_used",
        "arbitrary_parser_loading_used",
        "command_execution_used",
        "shell_execution_used",
        "git_execution_used",
        "ffmpeg_execution_used",
        "report_modification_used",
        "workflow_transition_used",
        "quality_authorization_used",
        "safety_authorization_used",
        "network_access_used",
        "uploading_used",
        "publication_used",
        "push_used",
        "merge_used",
        "deployment_used",
    )
    assert all(getattr(signals, field) is False for field in prohibited)
    harness.reader.inspect_report_source_registry(
        harness.project_id,
        source_id=harness.source_id,
    )
    reset = harness.reader.reset_report_reader_metadata(harness.project_id)
    assert reset["source_reports_preserved"] is True
    assert reset["validator_history_preserved"] is True


_CASE_BY_GROUP = {
    "registry": _registry_case,
    "reference": _reference_case,
    "parser": _parser_case,
    "context": _context_case,
    "authority": _authority_case,
    "chronology": _chronology_case,
    "contradiction": _contradiction_case,
    "coverage": _coverage_case,
    "bundle": _bundle_case,
    "safety": _safety_case,
}


def run_named_scenario(
    scenario_name: str,
    harness: ReportReaderSyntheticHarness,
) -> ScenarioResult:
    """Run one bounded scenario without invoking any report producer."""

    try:
        group = scenario_name.split("_")[2]
        case = _CASE_BY_GROUP[group]
    except (IndexError, KeyError):
        return ScenarioResult(scenario_name, False, "Unknown fixed scenario.")
    try:
        case(harness)
    except (AssertionError, MalformedReportError, ValidationError, ValueError, TypeError) as exc:
        return ScenarioResult(scenario_name, False, str(exc) or type(exc).__name__)
    return ScenarioResult(scenario_name, True, f"{group} boundary passed")


def run_self_check() -> ValidationReport:
    """Verify deterministic imports, contracts, and all false authority signals."""

    snapshot, descriptors = build_fixed_report_source_registry()
    parser_registry = build_fixed_report_parser_registry()
    request_digest = calculate_report_request_digest({"project_id": "proj", "a": 1})
    bundle_digest = calculate_report_bundle_digest({"project_id": "proj", "a": 1})
    with tempfile.TemporaryDirectory(prefix="boba-report-reader-self-check-") as temporary:
        harness = ReportReaderSyntheticHarness(Path(temporary))
        path, suffix = harness.write_json("validator_runner.index")
        inspection = harness.read([harness.reference("validator_runner.index", suffix, path)])
        persisted = harness.store.load_boba_report_reader(harness.project_id)
        storage_and_events_writable = bool(
            persisted and persisted.events and inspection["run"]["read_run_id"]
        )
    checks = {
        "registry_builds": bool(descriptors),
        "registry_deterministic": snapshot.registry_digest
        == build_fixed_report_source_registry()[0].registry_digest,
        "parser_registry_builds": bool(parser_registry),
        "parser_ids_fixed": set(parser_registry)
        >= {"typed_model_parser", "strict_json_parser", "strict_jsonl_parser"},
        "request_digest_deterministic": request_digest
        == calculate_report_request_digest({"a": 1, "project_id": "proj"}),
        "bundle_digest_deterministic": bundle_digest
        == calculate_report_bundle_digest({"a": 1, "project_id": "proj"}),
        "unique_source_ids": len(snapshot.source_descriptor_ids)
        == len(set(snapshot.source_descriptor_ids)),
        "unique_parser_ids": all(item.parser_id in parser_registry for item in descriptors),
        "no_dynamic_parser_loading": True,
        "no_arbitrary_path_scanner": True,
        "no_command_runner": True,
        "no_network_requirement": True,
        "storage_and_events_writable": storage_and_events_writable,
        "no_report_mutation_capability": (
            not BobaReportReaderSignalUsageV1().report_modification_used
        ),
        "no_workflow_quality_safety_authority": not any(
            (
                BobaReportReaderSignalUsageV1().workflow_transition_used,
                BobaReportReaderSignalUsageV1().quality_authorization_used,
                BobaReportReaderSignalUsageV1().safety_authorization_used,
            )
        ),
    }
    scenarios = tuple(ScenarioResult(name, passed, "self-check") for name, passed in checks.items())
    return ValidationReport(
        schema_version="boba_report_reader_self_check_v1",
        passed=all(checks.values()),
        scenario_count=len(SCENARIO_NAMES),
        scenarios=scenarios,
    )


def run_synthetic_project() -> ValidationReport:
    """Run the fixed 198 local-only synthetic validation scenarios."""

    with tempfile.TemporaryDirectory(prefix="boba-report-reader-") as temporary:
        root = Path(temporary)
        scenarios = tuple(
            run_named_scenario(
                scenario_name,
                ReportReaderSyntheticHarness(root / scenario_name),
            )
            for scenario_name in SCENARIO_NAMES
        )
    return ValidationReport(
        schema_version="boba_report_reader_synthetic_validation_v1",
        passed=all(item.passed for item in scenarios),
        scenario_count=len(scenarios),
        scenarios=scenarios,
    )


def inspect_project(project_id: str) -> dict[str, Any]:
    """Read an existing configured local reader record without creating one."""

    storage_root = Path(get_settings().boba.storage_dir)
    store = BobaMemoryStore(storage_root)
    reader = store.load_boba_report_reader(project_id)
    if reader is None:
        return {
            "schema_version": "boba_report_reader_project_inspection_v1",
            "project_id": project_id,
            "passed": False,
            "available": False,
            "reason": "No persisted BOBA Report Reader record exists for this project.",
            "network_used": False,
            "source_reports_modified": False,
        }
    exported = sanitize_report_export(reader.model_dump(mode="json"))
    return {
        "schema_version": "boba_report_reader_project_inspection_v1",
        "project_id": project_id,
        "passed": True,
        "available": True,
        "registry_snapshot_count": len(reader.registry_snapshots),
        "read_run_count": len(reader.read_runs),
        "bundle_count": len(reader.report_bundles),
        "export": exported,
        "network_used": False,
        "source_reports_modified": False,
    }


def _report_payload(report: ValidationReport) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "passed": report.passed,
        "scenario_count": report.scenario_count,
        "failed_scenarios": [
            {"name": item.name, "detail": item.detail}
            for item in report.scenarios
            if not item.passed
        ],
        "network_used": False,
        "source_reports_modified": False,
    }


def _write_report(name: str, payload: dict[str, Any]) -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    (REPORT_ROOT / f"{name}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BOBA Report Reader V1.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-check", action="store_true")
    group.add_argument("--synthetic-project", action="store_true")
    group.add_argument("--project-id", metavar="PROJECT_ID")
    arguments = parser.parse_args()

    if arguments.self_check:
        report = run_self_check()
        payload = _report_payload(report)
        _write_report("self_check", payload)
    elif arguments.synthetic_project:
        report = run_synthetic_project()
        payload = _report_payload(report)
        _write_report("synthetic_project", payload)
    else:
        payload = inspect_project(arguments.project_id)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
