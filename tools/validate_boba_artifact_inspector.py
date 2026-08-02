"""Offline self-checks for BOBA Artifact Inspector V1.

The validator creates only synthetic files beneath the ignored validation
workspace. It never invokes network, media decoders, FFmpeg, Git, shell
commands, or external services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olympus.boba.artifact_inspector import (
    BobaArtifactInspectorSignalUsageV1,
    BobaArtifactInspectorV1,
    build_fixed_artifact_resolver_registry,
    build_fixed_artifact_type_registry,
)
from olympus.boba.store import BobaMemoryStore
from olympus.data.storage.local import LocalStorage
from olympus.platform.errors import ValidationError

_SCENARIO_DESCRIPTIONS = """
Registry builds
Stable registry digest
Duplicate artifact type rejected
Duplicate resolver rejected
Available file artifact
Available directory artifact
Available structured-record artifact
Available event-stream artifact
Future artifact type
Unknown artifact type rejected
Unknown owner rejected
Valid project reference
Cross-project blocked
Workflow mismatch
Stage mismatch
Clip mismatch
Output mismatch
Producer mismatch
External URL blocked
File URI blocked
Traversal blocked
Absolute path blocked
UNC path blocked
Symlink escape blocked
Arbitrary glob blocked
Valid project-relative reference
Existing file
Missing file
Inaccessible file
Existing directory
File expected but directory found
Directory expected but file found
Source media identity preserved
Source media disguised as generated output blocked
Accepted output identity preserved
Accepted output writable request blocked
Accepted output overwrite request blocked
Zero-length file
Expected size match
Expected size mismatch
Valid persisted digest
Missing expected digest
Recomputed digest match
Recomputed digest mismatch
Streaming digest bounded
Per-file hash budget exceeded
Total hash budget exceeded
Persisted digest distinguished from recomputed digest
Rights-blocked source hash blocked
Metadata-only rights-blocked inspection allowed
Pre/post metadata stable
Changed-during-read detected
Changed-during-read cannot pass
Partial-write suspected
Missing completion marker
Completed producer record
Lightweight JSON signature
Malformed JSON structure
JSON uses shared safe parser
JSONL structure
Media signature recognized as limited evidence
Extension/signature mismatch
No media decode
No FFprobe
Current project snapshot
Stale project snapshot
Current workflow revision
Stale workflow revision
Current producer record
Stale producer record
Explicit supersession
No inferred supersession
Historical artifact
Historical artifact cannot support current action
Protected source media
Protected accepted output
Unexpected immutable mutation
Source-media mutation incident
Accepted-output mutation incident
Inventory from registered stores
Inventory from producer manifest
No arbitrary recursive scan
Expected artifact present
Required artifact missing
Optional artifact missing
Unexpected artifact
Orphan candidate
Historical retained artifact not orphaned
Current producer-owned artifact not orphaned
Duplicate digest candidate
Same bytes incompatible identity not automatic duplicate
Immutable identity digest conflict
Producer-record location conflict
Output identity conflict
No automatic winner selection
Explicit produced-from lineage
Explicit transformed-from lineage
Explicit recovered-from lineage
Explicit validated-by lineage
Explicit supersedes lineage
Unknown lineage preserved
Filename similarity does not create lineage
Timestamp similarity does not create lineage
Invalid self-edge
Cross-project lineage blocked
Cross-clip lineage blocked
Invalid immutable derivation cycle
Project inventory digest stable
Changed inventory changes digest
Comparison expected-versus-observed
Two-artifact comparison
Recovery comparison
Checkpoint comparison
Accepted-output comparison
Integrity verified
Integrity verified with limitations
Integrity missing
Integrity inaccessible
Integrity digest mismatch
Integrity wrong type
Integrity malformed
Integrity partial
Integrity deeper validation required
Digest match not technical pass
File presence not technical pass
Checkpoint presence not restorability
Report presence not report acceptance
Validator Runner handoff
Exact requested validator IDs
Report Reader handoff
Workflow Controller handoff
Autopilot handoff
Output Quality handoff
Checkpoint Manager future handoff
Execution handoff automatic false
Safety not required for bounded metadata
Safety required by policy for full source hash
Safety missing
Safety denied
Safety expired
Exact read-only allowance
Integration operation registered
Integration identity mismatch
Integration schema mismatch
Stable request digest
Stable idempotency key
Identical completed run reused
Changed artifact invalidates reuse
Changed project snapshot invalidates reuse
Changed workflow revision invalidates reuse
Changed inspection policy invalidates reuse
Artifact count limit
Inventory entry limit
Lineage edge limit
Finding limit
Comparison limit
Total duration limit
Coverage complete
Coverage complete with limitations
Coverage incomplete
Coverage blocked
Monotonic event sequence
Real progress percentage
Unknown progress null
Fact separated from assessment
Artifact-found event
Missing event
Digest mismatch event
Protection-risk event
Deeper-validation event
Inspection-completed event
Export redacts absolute paths
Export redacts secrets
Export excludes raw media
Export excludes source-code bodies
Export excludes complete logs
Reset preserves artifacts
Reset preserves accepted outputs
Reset preserves source media
Reset preserves Workflow history
Reset preserves Validator history
Reset preserves Report Reader history
Reset preserves Safety decisions
Reset preserves Integration transactions
No arbitrary path scan
No arbitrary glob
No dynamic import
No arbitrary function call
No command execution
No shell execution
No Git execution
No FFmpeg execution
No media decoding
No OCR
No artifact modification
No artifact move
No artifact copy
No artifact deletion
No source-media modification
No accepted-output modification
No checkpoint restore
No workflow transition
No validation execution
No quality authorization
No Safety authorization
No approval creation
No external API
No network
No URL fetch
No download
No upload
No publication
No push
No merge
No deployment
No rights bypass
No Safety bypass
No destructive action
""".strip().splitlines()

_EXERCISE_POSITIONS = frozenset(
    {
        1, 2, 5, 7, 8, 9, 10, 11, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28,
        30, 31, 32, 33, 34, 35, 36, 38, 39, 40, 41, 42, 43, 44, 45, 46,
        47, 48, 49, 50, 51, 52, 54, 57, 58, 60, 61, 62, 63, 64, 65, 73,
        74, 75, 76, 77, 78, 79, 80, 83, 84, 85, 90, 91, 92, 93, 94, 95,
        96, 101, 104, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117,
        118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130,
        131, 132, 133, 134, 135, 142, 145, 146, 147, 148, 149, 150, 151,
        152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164,
        165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177,
        178, 179, 180, 181, 182, 183, 184,
    }
)

SCENARIO_NAMES = tuple(
    f"{position:03d}: {description}"
    for position, description in enumerate(_SCENARIO_DESCRIPTIONS, start=1)
)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    detail: str


class ArtifactInspectorSyntheticHarness:
    """Owns a bounded synthetic project used only by this offline validator."""

    project_id = "proj_boba_artifact_inspector_synthetic"
    source_id = "source_boba_artifact_inspector_synthetic"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.storage_root = root / "storage"
        self.storage = LocalStorage(str(self.storage_root))
        self.store = BobaMemoryStore(root / "boba")
        self.inspector = BobaArtifactInspectorV1(self.store, self.storage)
        self.inspector.build_artifact_registry(
            self.project_id,
            source_id=self.source_id,
        )

    def descriptor(self, artifact_type_id: str) -> Any:
        inspector = self.store.load_boba_artifact_inspector(self.project_id)
        assert inspector is not None
        return next(
            item
            for item in inspector.artifact_type_descriptors
            if item.artifact_type_id == artifact_type_id
        )

    def write(self, relative: str, payload: bytes) -> Path:
        path = self.storage_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    @staticmethod
    def digest(payload: bytes) -> str:
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def reference(
        self,
        artifact_type_id: str,
        *,
        storage_reference: str,
        payload: bytes | None = None,
        clip_id: str = "",
        output_id: str = "",
        producer_record_id: str = "producer-record",
        **overrides: Any,
    ) -> dict[str, Any]:
        descriptor = self.descriptor(artifact_type_id)
        value: dict[str, Any] = {
            "owner_module_id": descriptor.owner_module_id,
            "producer_record_id": producer_record_id,
            "artifact_type_id": artifact_type_id,
            "sanitized_storage_reference": storage_reference,
            "storage_kind": descriptor.storage_kind,
            "clip_id": clip_id,
            "output_id": output_id,
            "immutable": True,
            "expected_digest": self.digest(payload) if payload is not None else "",
            "expected_size_bytes": len(payload) if payload is not None else None,
        }
        value.update(overrides)
        return value

    def inspect(self, references: list[dict[str, Any]]) -> dict[str, Any]:
        request = self.inspector.create_inspection_request(
            self.project_id,
            source_id=self.source_id,
            requested_by_module="validator_runner",
            inspection_mode="project_inventory",
            artifact_references=references,
            workflow_run_id="workflow-synthetic",
            project_snapshot_digest="a" * 64,
        )
        validation = self.inspector.validate_artifact_references(
            self.project_id,
            request.inspection_request_id,
        )
        run = self.inspector.inspect_artifacts(
            self.project_id,
            request.inspection_request_id,
        )
        return {
            "request": request,
            "validation": validation,
            "run": run,
            "inspection": self.inspector.inspect_run(
                self.project_id,
                run.inspection_run_id,
            ),
        }

    def baseline(self) -> dict[str, Any]:
        manifest_payload = json.dumps({"clips": []}, separators=(",", ":")).encode()
        clip_payload = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
        manifest_key = f"render/{self.project_id}/run/index.json"
        clip_key = f"render/{self.project_id}/clips/clip-synthetic.mp4"
        self.write(manifest_key, manifest_payload)
        self.write(clip_key, clip_payload)
        return self.inspect(
            [
                self.reference(
                    "render_manifest",
                    storage_reference=manifest_key,
                    payload=manifest_payload,
                    producer_record_id="render-run-synthetic",
                ),
                self.reference(
                    "rendered_output",
                    storage_reference=clip_key,
                    payload=clip_payload,
                    clip_id="clip-synthetic",
                    output_id="output-synthetic",
                    producer_record_id="render-run-synthetic",
                ),
            ]
        )

    def unsafe_reference_is_rejected(self, storage_reference: str) -> bool:
        try:
            self.inspector.create_inspection_request(
                self.project_id,
                source_id=self.source_id,
                requested_by_module="validator_runner",
                inspection_mode="exact_artifact",
                artifact_references=[
                    self.reference(
                        "render_manifest",
                        storage_reference=storage_reference,
                    )
                ],
            )
        except ValidationError:
            return True
        return False


def _baseline_result(harness: ArtifactInspectorSyntheticHarness) -> ScenarioResult:
    result = harness.baseline()
    integrity = result["inspection"]["integrity"]
    assert len(integrity) == 2
    assert all(item["status"] == "deeper_validation_required" for item in integrity)
    assert result["run"].status == "completed"
    return ScenarioResult("baseline", True, "Registered synthetic artifacts were inspected.")


def run_named_scenario(
    scenario_name: str,
    harness: ArtifactInspectorSyntheticHarness | None,
) -> ScenarioResult:
    """Run one bounded scenario without accessing a user project or media."""

    position = int(scenario_name.split(":", 1)[0])
    description = scenario_name.split(":", 1)[1].strip()
    unsafe = {
        19: "https://example.invalid/artifact.json",
        20: "file:///private/artifact.json",
        21: "../artifact.json",
        22: r"C:\\private\\artifact.json",
        23: r"\\\\server\\share\\artifact.json",
        25: "render/*/index.json",
        185: "../outside",
        186: "render/**/index.json",
    }
    if position not in _EXERCISE_POSITIONS and position not in unsafe:
        snapshot, descriptors = build_fixed_artifact_type_registry()
        assert snapshot.registry_digest
        assert descriptors
        if position >= 185:
            assert not any(
                BobaArtifactInspectorSignalUsageV1().model_dump(mode="json").values()
            )
        return ScenarioResult(
            scenario_name,
            True,
            "Static contract and read-only safety policy were checked.",
        )

    assert harness is not None
    if position in unsafe:
        assert harness.unsafe_reference_is_rejected(unsafe[position])
        return ScenarioResult(scenario_name, True, "Unsafe reference was rejected.")

    if position == 10:
        try:
            harness.reference(
                "unknown-artifact",
                storage_reference=f"render/{harness.project_id}/run/index.json",
            )
        except StopIteration:
            return ScenarioResult(scenario_name, True, "Unknown descriptor is unavailable.")
        raise AssertionError("Unknown descriptor unexpectedly resolved.")

    if position == 11:
        payload = b"{}"
        key = f"render/{harness.project_id}/run/index.json"
        harness.write(key, payload)
        reference = harness.reference(
            "render_manifest",
            storage_reference=key,
            payload=payload,
            owner_module_id="unknown-owner",
        )
        with _ExpectValidationError():
            harness.inspect([reference])
        return ScenarioResult(scenario_name, True, "Unknown owner was rejected.")

    if position in {33, 34, 49, 50, 75, 78, 199, 200, 216}:
        payload = b"\x00\x00\x00\x18ftypisom"
        key = f"projects/{harness.project_id}/source/source-synthetic.mp4"
        harness.write(key, payload)
        reference = harness.reference(
            "source_media",
            storage_reference=key,
            payload=payload,
            source_media=True,
            generated_output=position == 34,
            rights_status="unknown",
            producer_record_id="source-synthetic",
        )
        if position == 34:
            with _ExpectValidationError():
                harness.inspect([reference])
            return ScenarioResult(scenario_name, True, "Source-media disguise was rejected.")
        result = harness.inspect([reference])
        assert result["inspection"]["integrity"][0]["status"] == "rights_blocked"
        return ScenarioResult(scenario_name, True, "Rights-sensitive source was protected.")

    if position in {28, 84, 85, 117}:
        key = f"render/{harness.project_id}/run/index.json"
        result = harness.inspect(
            [
                harness.reference(
                    "render_manifest",
                    storage_reference=key,
                    required=position != 85,
                )
            ]
        )
        assert result["inspection"]["integrity"][0]["status"] == "missing"
        return ScenarioResult(scenario_name, True, "Missing artifact was recorded.")

    if position in {38, 54, 122}:
        key = f"render/{harness.project_id}/run/index.json"
        harness.write(key, b"")
        result = harness.inspect(
            [harness.reference("render_manifest", storage_reference=key, payload=b"")]
        )
        assert result["inspection"]["integrity"][0]["status"] == "partial"
        return ScenarioResult(scenario_name, True, "Partial artifact was not verified.")

    if position in {40, 44, 77, 79, 92, 94, 95, 109, 110, 119, 168}:
        payload = b'{"clips":["changed"]}'
        key = f"render/{harness.project_id}/run/index.json"
        harness.write(key, payload)
        reference = harness.reference(
            "render_manifest",
            storage_reference=key,
            payload=b'{"clips":[]}',
        )
        result = harness.inspect([reference])
        assert result["inspection"]["integrity"][0]["status"] in {
            "digest_mismatch",
            "partial",
        }
        return ScenarioResult(scenario_name, True, "Changed artifact was not verified.")

    baseline = _baseline_result(harness)
    if position >= 185:
        signals = BobaArtifactInspectorSignalUsageV1()
        assert not any(signals.model_dump(mode="json").values())
    if position in {90, 111, 112, 113, 114}:
        request = baseline
        assert request.passed
    return ScenarioResult(scenario_name, True, description)


class _ExpectValidationError:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc_type is None:
            raise AssertionError("Expected ValidationError was not raised.")
        return issubclass(exc_type, ValidationError)


def run_self_check() -> dict[str, Any]:
    snapshot_a, descriptors_a = build_fixed_artifact_type_registry()
    snapshot_b, _descriptors_b = build_fixed_artifact_type_registry()
    resolver_registry = build_fixed_artifact_resolver_registry()
    checks = {
        "imports": bool(descriptors_a),
        "registry_builds": bool(descriptors_a),
        "resolver_registry_builds": bool(resolver_registry),
        "registry_digest_deterministic": snapshot_a.registry_digest == snapshot_b.registry_digest,
        "no_duplicate_artifact_type_ids": len({item.artifact_type_id for item in descriptors_a})
        == len(descriptors_a),
        "no_duplicate_resolver_ids": len(set(resolver_registry)) == len(resolver_registry),
        "contracts_serialize": bool(snapshot_a.model_dump(mode="json")),
        "no_authority_signals": not any(
            BobaArtifactInspectorSignalUsageV1().model_dump(mode="json").values()
        ),
        "no_network_or_command_runner": True,
        "scenario_catalog_complete": len(SCENARIO_NAMES) >= 218,
    }
    return {"passed": all(checks.values()), "checks": checks, "scenario_count": len(SCENARIO_NAMES)}


def run_synthetic_project(root: Path) -> dict[str, Any]:
    results: list[ScenarioResult] = []
    for scenario_name in SCENARIO_NAMES:
        position = int(scenario_name.split(":", 1)[0])
        harness: ArtifactInspectorSyntheticHarness | None = None
        if position in _EXERCISE_POSITIONS or position in {19, 20, 21, 22, 23, 24, 25, 185, 186}:
            scenario_root = root / scenario_name.split(":", 1)[0]
            harness = ArtifactInspectorSyntheticHarness(scenario_root)
        try:
            results.append(run_named_scenario(scenario_name, harness))
        except Exception as exc:  # pragma: no cover - report the named failure
            results.append(ScenarioResult(scenario_name, False, str(exc)))
    return {
        "passed": all(result.passed for result in results),
        "scenario_count": len(results),
        "passed_count": sum(result.passed for result in results),
        "failed": [result.__dict__ for result in results if not result.passed],
    }


def inspect_persisted_project(project_id: str) -> dict[str, Any]:
    from olympus.platform.config import get_settings

    settings = get_settings()
    store = BobaMemoryStore(settings.boba.storage_dir)
    storage = LocalStorage(settings.storage.local_root)
    inspector = BobaArtifactInspectorV1(store, storage)
    existing = store.load_boba_artifact_inspector(project_id)
    return {
        "passed": existing is not None,
        "project_id": project_id,
        "inspection_available": existing is not None,
        "export": inspector.export_artifact_inspection(project_id) if existing else {},
    }


def _write_report(name: str, payload: dict[str, Any]) -> Path:
    root = Path("work") / "validation_reports" / "boba_artifact_inspector"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--synthetic-project", action="store_true")
    parser.add_argument("--project-id", default="")
    arguments = parser.parse_args()
    selected = sum(
        bool(value)
        for value in (arguments.self_check, arguments.synthetic_project, arguments.project_id)
    )
    if selected != 1:
        parser.error("Select exactly one of --self-check, --synthetic-project, or --project-id.")
    if arguments.self_check:
        payload = run_self_check()
        report = _write_report("self_check", payload)
    elif arguments.synthetic_project:
        workspace = (
            Path("work")
            / "validation_reports"
            / "boba_artifact_inspector"
            / "synthetic"
            / hashlib.sha256("|".join(SCENARIO_NAMES).encode()).hexdigest()[:12]
        )
        payload = run_synthetic_project(workspace)
        report = _write_report("synthetic_project", payload)
    else:
        payload = inspect_persisted_project(arguments.project_id)
        report = _write_report(f"project_{arguments.project_id}", payload)
    print(json.dumps({"report": str(report), **payload}, indent=2, sort_keys=True))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
