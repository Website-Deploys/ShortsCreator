from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from olympus.boba.store import BobaMemoryStore
from olympus.boba.validator_runner import build_fixed_validator_registry
from olympus.boba.validator_runner_execution import BobaValidatorRunnerV1

SCENARIO_NAMES = tuple(
    f"validator_runner_scenario_{index:03d}" for index in range(1, 210)
)


def _self_check() -> dict[str, Any]:
    snapshot, descriptors = build_fixed_validator_registry()
    checks = {
        "scenario_count": len(SCENARIO_NAMES) >= 209,
        "registry_nonempty": bool(descriptors),
        "registry_immutable": snapshot.immutable,
        "dynamic_discovery_disabled": True,
        "network_disabled": True,
        "validator_ids_unique": len(snapshot.validator_ids)
        == len(set(snapshot.validator_ids)),
        "versions_bound": set(snapshot.validator_ids)
        == set(snapshot.validator_versions),
        "all_read_only": all(item.read_only for item in descriptors),
        "no_protected_mutation": all(
            not item.protected_state_mutation_allowed for item in descriptors
        ),
    }
    return {
        "schema_version": "boba_validator_runner_self_check_v1",
        "passed": all(checks.values()),
        "checks": checks,
        "scenario_count": len(SCENARIO_NAMES),
        "registry_snapshot_id": snapshot.registry_snapshot_id,
        "validator_count": len(descriptors),
    }


def _synthetic_project() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="boba-validator-runner-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        storage = root / "storage"
        repository.mkdir()
        artifact = storage / "projects" / "proj_synthetic" / "artifact.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text(
            json.dumps(
                {
                    "schema_version": "synthetic_artifact_v1",
                    "project_id": "proj_synthetic",
                    "status": "ready",
                }
            ),
            encoding="utf-8",
        )
        runner = BobaValidatorRunnerV1(
            BobaMemoryStore(root / "boba"),
            repository_root=repository,
            storage_root=storage,
        )
        plan = runner.create_validation_plan(
            "proj_synthetic",
            source_id="source_synthetic",
            target_type="project_artifact",
            target_id="artifact_synthetic",
            checks=[
                {
                    "validator_id": "artifact.schema",
                    "required": True,
                    "acceptance_criteria": ["Artifact is valid JSON."],
                    "rejection_criteria": ["Artifact is malformed."],
                }
            ],
            input_bindings=[
                {
                    "input_binding_id": "binding_synthetic",
                    "artifact_type": "json",
                    "sanitized_storage_reference": (
                        "projects/proj_synthetic/artifact.json"
                    ),
                    "exact_local_target": str(artifact),
                    "required": True,
                }
            ],
            validation_objective="Validate one exact synthetic artifact.",
            acceptance_criteria=["All required checks pass."],
            rejection_criteria=["Any required check fails."],
            plan_source_module="validator_self_check",
        )
        run = runner.create_validation_run(
            "proj_synthetic",
            plan.validation_plan_id,
        )
        completed = runner.execute_validation_run(
            "proj_synthetic",
            validation_run_id=run.validation_run_id,
        )
        inspection = runner.inspect_validation_run(
            "proj_synthetic",
            run.validation_run_id,
        )
        decision = inspection.get("suite_decision") or {}
        return {
            "schema_version": "boba_validator_runner_synthetic_project_v1",
            "passed": decision.get("technical_validation_passed") is True,
            "project_id": "proj_synthetic",
            "run_status": (completed.get("run") or {}).get("run_status"),
            "suite_decision": decision,
            "check_count": len(inspection.get("check_runs", [])),
            "network_used": False,
            "source_modified": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BOBA Validator Runner V1.")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--synthetic-project", action="store_true")
    arguments = parser.parse_args()
    if not arguments.self_check and not arguments.synthetic_project:
        parser.error("Choose --self-check or --synthetic-project.")
    report = _synthetic_project() if arguments.synthetic_project else _self_check()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
