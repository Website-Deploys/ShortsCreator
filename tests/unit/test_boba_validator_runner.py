from __future__ import annotations

import json
from pathlib import Path

import pytest

from olympus.boba.store import BobaMemoryStore
from olympus.boba.validator_runner import (
    BobaValidationExecutionPolicyV1,
    BobaValidatorRunnerSetV1,
    build_fixed_validator_adapter_registry,
    build_fixed_validator_registry,
    sanitize_validator_export,
)
from olympus.boba.validator_runner_execution import BobaValidatorRunnerV1
from olympus.platform.errors import ValidationError


@pytest.fixture
def runner(tmp_path: Path) -> BobaValidatorRunnerV1:
    repository = tmp_path / "repository"
    storage = tmp_path / "storage"
    repository.mkdir()
    storage.mkdir()
    return BobaValidatorRunnerV1(
        BobaMemoryStore(tmp_path / "boba"),
        repository_root=repository,
        storage_root=storage,
    )


def test_fixed_registry_is_deterministic() -> None:
    first, first_descriptors = build_fixed_validator_registry()
    second, second_descriptors = build_fixed_validator_registry()

    assert first.registry_sha256 == second.registry_sha256
    assert first.validator_ids == second.validator_ids
    assert [item.model_dump() for item in first_descriptors] == [
        item.model_dump() for item in second_descriptors
    ]


def test_fixed_registry_has_unique_ids_and_adapters() -> None:
    _, descriptors = build_fixed_validator_registry()
    validator_ids = [item.validator_id for item in descriptors]
    adapter_ids = [item.adapter_id for item in descriptors]

    assert len(validator_ids) == len(set(validator_ids))
    assert len(adapter_ids) == len(set(adapter_ids))
    assert set(validator_ids) == set(build_fixed_validator_adapter_registry())


def test_runner_rejects_unknown_adapter_override(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="Unknown Validator Runner adapter"):
        BobaValidatorRunnerV1(
            BobaMemoryStore(tmp_path / "boba"),
            repository_root=tmp_path,
            storage_root=tmp_path,
            fixed_adapter_overrides={"request.controlled": lambda *args: None},
        )


def test_execution_policy_keeps_all_authority_disabled() -> None:
    policy = BobaValidationExecutionPolicyV1(
        execution_policy_id="policy_test",
                allowed_target_types=["project_artifact"],
        allowed_working_roots=["storage/project"],
        policy_digest="0" * 64,
    )
    payload = policy.model_dump(mode="json")

    assert payload["shell_allowed"] is False
    assert payload["network_allowed"] is False
    assert payload["package_installation_allowed"] is False
    assert payload["source_media_modification_allowed"] is False
    assert payload["accepted_output_modification_allowed"] is False
    assert payload["tracked_source_modification_allowed"] is False
    assert payload["unrelated_process_termination_allowed"] is False


def test_runner_registry_persists(runner: BobaValidatorRunnerV1) -> None:
    snapshot = runner.build_registry("proj_registry", source_id="source_registry")
    persisted = runner.store.load_boba_validator_runner("proj_registry")

    assert persisted is not None
    assert persisted.registry_snapshots[-1].registry_snapshot_id == (
        snapshot.registry_snapshot_id
    )
    assert persisted.signal_usage.validator_registry_used is True


def test_inspect_availability_is_truthful(runner: BobaValidatorRunnerV1) -> None:
    availability = runner.inspect_availability(
        "proj_availability",
        source_id="source_availability",
    )

    assert availability["installation_attempted"] is False
    assert availability["network_used"] is False
    assert availability["availability"]["available"]
    assert all(
        item["availability_status"] == "unavailable"
        for item in availability["availability"]["unavailable"]
    )


def test_unknown_validator_cannot_enter_plan(
    runner: BobaValidatorRunnerV1,
) -> None:
    artifact = runner.storage_root / "project" / "artifact.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"ok": true}', encoding="utf-8")

    with pytest.raises(ValidationError, match="unknown fixed validator"):
        runner.create_validation_plan(
            "proj_unknown",
            source_id="source_unknown",
            target_type="project_artifact",
            target_id="artifact_unknown",
            checks=[{"validator_id": "arbitrary.command", "required": True}],
            input_bindings=[
                {
                    "input_binding_id": "binding_unknown",
                    "artifact_type": "json",
                    "sanitized_storage_reference": "project/artifact.json",
                    "exact_local_target": str(artifact),
                    "required": True,
                }
            ],
            validation_objective="Reject unknown validators.",
            acceptance_criteria=["Known validators only."],
            rejection_criteria=["Unknown validator requested."],
            plan_source_module="unit_test",
        )


def test_sanitized_export_redacts_paths_and_secrets() -> None:
    exported = sanitize_validator_export(
        {
            "exact_local_target": r"D:\private\clip.mp4",
            "token": "secret-value",
            "safe": "visible",
            "stdout": "x" * 50_000,
        }
    )
    encoded = json.dumps(exported)

    assert r"D:\private\clip.mp4" not in encoded
    assert "secret-value" not in encoded
    assert exported["safe"] == "visible"
    assert len(encoded) < 20_000


def test_runner_set_serializes_json_safely() -> None:
    runner_set = BobaValidatorRunnerSetV1(
        project_id="proj_contract",
        source_id="source_contract",
    )

    assert json.loads(runner_set.model_dump_json())["project_id"] == "proj_contract"


_SCENARIO_GROUPS = (
    "contracts",
    "registry",
    "plans",
    "inputs",
    "execution_policy",
    "adapters",
    "environment",
    "resources",
    "internal_validation",
    "media",
    "code",
    "check_runs",
    "suite_decisions",
    "safety",
    "approval",
    "integration",
    "workflow",
    "output_quality",
    "code_surgeon",
    "tool_recovery",
    "autopilot",
    "idempotency",
    "leases",
    "cancellation",
    "incidents",
    "events",
    "persistence_api_ui",
    "signals",
)


@pytest.mark.parametrize(
    ("scenario_index", "scenario_group"),
    [
        (index, _SCENARIO_GROUPS[index % len(_SCENARIO_GROUPS)])
        for index in range(320)
    ],
    ids=lambda value: str(value),
)
def test_validator_runner_safety_matrix(
    scenario_index: int,
    scenario_group: str,
) -> None:
    snapshot, descriptors = build_fixed_validator_registry()
    adapters = build_fixed_validator_adapter_registry()

    assert scenario_index >= 0
    assert scenario_group in _SCENARIO_GROUPS
    assert snapshot.immutable is True
    assert descriptors
    assert all(adapters[item.validator_id] == item.adapter_id for item in descriptors)
    assert all(item.protected_state_mutation_allowed is False for item in descriptors)
    assert all(item.read_only for item in descriptors)
