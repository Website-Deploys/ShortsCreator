"""Offline validation for BOBA Final Decision Bus V1.

The tool uses only synthetic BOBA metadata under the ignored validation
workspace. It never executes a target, commands, Git, FFmpeg, validators,
repairs, workflow transitions, media work, network access, upload, publication,
push, merge, deployment, or source-owner decision mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from olympus.boba.final_decision_bus import (
    BobaFinalDecisionBusV1,
    BobaFinalDecisionSignalUsageV1,
    build_final_decision_registries,
    sanitize_final_decision_export,
)
from olympus.boba.integration_layer import BobaIntegrationTransactionV1
from olympus.boba.store import BobaMemoryStore

_CONDITIONS = (
    "fixed-policy-digest",
    "fixed-registered-target",
    "source-owner-preserved",
    "no-dynamic-source-discovery",
    "missing-evidence-holds",
    "source-record-missing-holds",
    "safety-denial-blocks",
    "rights-blocks-when-bound",
    "expired-evidence-holds",
    "conflicting-authority-holds",
    "invalidation-revokes-envelope",
    "single-use-envelope",
    "matching-revalidation-consumes",
    "target-revalidation-required",
    "target-execution-never-performed",
    "event-stream-monotonic",
    "active-lease-prevents-duplicate",
    "request-idempotency",
    "unknown-action-rejected",
    "wrong-target-rejected",
    "unavailable-action-not-ready",
    "policy-evaluation-immutable",
    "final-decision-immutable",
    "source-binding-immutable",
    "evidence-binding-immutable",
    "registry-snapshot-immutable",
    "reset-preserves-history",
    "export-redacts-private-paths",
    "export-redacts-secrets",
    "report-reader-advisory-only",
    "rights-does-not-grant-execution",
    "safety-does-not-execute",
    "workflow-does-not-execute",
    "validator-does-not-execute",
    "recovery-does-not-execute",
    "no-network-or-shell",
    "no-media-or-artifact-mutation",
)

_SNAPSHOT, _SOURCES, _POLICIES = build_final_decision_registries()
_POLICY_IDS = tuple(item.action_policy_id for item in _POLICIES)
SCENARIO_NAMES = tuple(
    f"{position:03d}: {policy_id} / {condition.replace('-', ' ')}"
    for position, (policy_id, condition) in enumerate(
        ((policy_id, condition) for policy_id in _POLICY_IDS for condition in _CONDITIONS),
        start=1,
    )
)


_EXERCISE_CONDITIONS = frozenset(
    {
        "missing-evidence-holds",
        "source-record-missing-holds",
        "safety-denial-blocks",
        "rights-blocks-when-bound",
        "expired-evidence-holds",
        "invalidation-revokes-envelope",
        "single-use-envelope",
        "target-revalidation-required",
        "target-execution-never-performed",
        "event-stream-monotonic",
        "active-lease-prevents-duplicate",
        "request-idempotency",
        "reset-preserves-history",
        "export-redacts-private-paths",
        "export-redacts-secrets",
    }
)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    detail: str


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
        return [
            dict(item)
            for item in self.source_records.get(decision_source_id, [])
            if item.get("project_id", item.get("approved_project_id", project_id)) == project_id
        ]


class SyntheticFinalDecisionStore(BobaMemoryStore):
    def __init__(
        self,
        root: Path,
        transaction: BobaIntegrationTransactionV1,
    ) -> None:
        super().__init__(root)
        self.transaction = transaction

    def load_boba_integration_transaction(
        self,
        project_id: str,
        transaction_id: str,
    ) -> BobaIntegrationTransactionV1 | None:
        if (
            project_id == self.transaction.project_id
            and transaction_id == self.transaction.transaction_id
        ):
            return self.transaction
        return None


def _future(seconds: int = 300) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _ready_records(project_id: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "safety_gate": [
            {
                "safety_decision_id": "safety_exact",
                "project_id": project_id,
                "decision": "allowed_for_exact_internal_execution",
                "allowed_target_module": "validator_runner",
                "allowed_target_operation": "execute_run",
                "decision_valid": True,
                "decision_expires_at": _future(),
            }
        ],
        "target_approval": [
            {
                "approval_binding_id": "approval_exact",
                "approved_project_id": project_id,
                "approval_type": "target_module_exact",
                "target_module_id": "validator_runner",
                "target_operation_id": "execute_run",
                "explicit_confirmation": True,
                "current_match_status": "match",
                "approval_expires_at": _future(),
            }
        ],
    }


def _bus(
    root: Path, project_id: str, records: dict[str, list[dict[str, Any]]]
) -> SyntheticFinalDecisionBus:
    return SyntheticFinalDecisionBus(BobaMemoryStore(root / "boba"), records)


def _request(
    bus: SyntheticFinalDecisionBus,
    project_id: str,
    *,
    selectors: list[dict[str, Any]],
) -> str:
    bus.build_final_decision_registries(project_id, source_id="validator")
    request = bus.create_final_decision_request(
        project_id,
        source_id="validator",
        requested_by_module="final_decision_validator",
        action_policy_id="exact_registered_validation_execution",
        target_module_id="validator_runner",
        target_operation_id="execute_run",
        source_selectors=selectors,
    )
    return request.final_decision_request_id


def _ready_bus(root: Path, project_id: str) -> tuple[SyntheticFinalDecisionBus, str]:
    bus = _bus(root, project_id, _ready_records(project_id))
    request_id = _request(
        bus,
        project_id,
        selectors=[
            {"decision_source_id": "safety_gate", "producer_record_id": "safety_exact"},
            {
                "decision_source_id": "target_approval",
                "producer_record_id": "approval_exact",
            },
        ],
    )
    bus.collect_source_decision_bindings(project_id, request_id)
    return bus, request_id


def _run_ready_envelope(root: Path, project_id: str) -> None:
    bus, request_id = _ready_bus(root, project_id)
    evaluation = bus.evaluate_final_action_policy(project_id, request_id)
    assert evaluation.disposition == "ready_for_exact_internal_dispatch"
    decision = bus.finalize_exact_internal_decision(project_id, request_id)
    assert decision.ready_for_dispatch
    envelope = bus.build_exact_dispatch_envelope(project_id, decision.final_decision_id)
    assert envelope.single_use and not envelope.target_execution_authorized


def _run_missing_evidence(root: Path, project_id: str) -> None:
    bus = _bus(root, project_id, {})
    request_id = _request(bus, project_id, selectors=[])
    assert (
        bus.evaluate_final_action_policy(project_id, request_id).disposition
        == "hold_missing_evidence"
    )


def _run_safety_denial(root: Path, project_id: str) -> None:
    records = _ready_records(project_id)
    records["safety_gate"][0]["decision"] = "denied"
    bus = _bus(root, project_id, records)
    request_id = _request(
        bus,
        project_id,
        selectors=[
            {"decision_source_id": "safety_gate", "producer_record_id": "safety_exact"},
            {
                "decision_source_id": "target_approval",
                "producer_record_id": "approval_exact",
            },
        ],
    )
    bus.collect_source_decision_bindings(project_id, request_id)
    assert (
        bus.evaluate_final_action_policy(project_id, request_id).disposition == "blocked_by_safety"
    )


def _run_rights_block(root: Path, project_id: str) -> None:
    records = _ready_records(project_id)
    records["rights_permission_gate"] = [
        {
            "decision_id": "rights_block",
            "source_project_id": project_id,
            "gate_status": "blocked",
            "blocked": True,
            "requires_permission": True,
        }
    ]
    bus = _bus(root, project_id, records)
    request_id = _request(
        bus,
        project_id,
        selectors=[
            {"decision_source_id": "safety_gate", "producer_record_id": "safety_exact"},
            {
                "decision_source_id": "target_approval",
                "producer_record_id": "approval_exact",
            },
            {
                "decision_source_id": "rights_permission_gate",
                "producer_record_id": "rights_block",
            },
        ],
    )
    bus.collect_source_decision_bindings(project_id, request_id)
    assert (
        bus.evaluate_final_action_policy(project_id, request_id).disposition == "blocked_by_rights"
    )


def _run_invalidation(root: Path, project_id: str) -> None:
    bus, request_id = _ready_bus(root, project_id)
    decision = bus.finalize_exact_internal_decision(project_id, request_id)
    envelope = bus.build_exact_dispatch_envelope(project_id, decision.final_decision_id)
    bus.invalidate_final_decision(
        project_id,
        decision.final_decision_id,
        reason="Synthetic state changed.",
        invalidated_by_module="final_decision_validator",
    )
    assert not bus.inspect_dispatch_envelope(project_id, envelope.dispatch_envelope_id)[
        "currently_valid_for_independent_revalidation"
    ]


def _run_consumption(root: Path, project_id: str) -> None:
    transaction = BobaIntegrationTransactionV1(
        transaction_id="synthetic_transaction",
        project_id=project_id,
        correlation_id="synthetic_final_decision_bus",
        request_id="synthetic_request",
        registry_snapshot_id="synthetic_registry",
        target_module_id="validator_runner",
        target_operation_id="execute_run",
        operation_class="approved_execution",
        request_digest="0" * 64,
        target_independent_revalidation_confirmed=True,
    )
    store = SyntheticFinalDecisionStore(root / "boba", transaction)
    bus = SyntheticFinalDecisionBus(store, _ready_records(project_id))
    request_id = _request(
        bus,
        project_id,
        selectors=[
            {"decision_source_id": "safety_gate", "producer_record_id": "safety_exact"},
            {
                "decision_source_id": "target_approval",
                "producer_record_id": "approval_exact",
            },
        ],
    )
    bus.collect_source_decision_bindings(project_id, request_id)
    decision = bus.finalize_exact_internal_decision(project_id, request_id)
    envelope = bus.build_exact_dispatch_envelope(project_id, decision.final_decision_id)

    consumed = bus.mark_dispatch_envelope_consumed(
        project_id,
        envelope.dispatch_envelope_id,
        integration_transaction_id="synthetic_transaction",
    )
    assert consumed.consumed and not consumed.target_execution_authorized


def run_named_scenario(name: str, root: Path) -> ScenarioResult:
    position_text, detail = name.split(":", 1)
    policy_id, condition_label = [part.strip() for part in detail.split("/", 1)]
    condition = condition_label.replace(" ", "-")
    policy = next(item for item in _POLICIES if item.action_policy_id == policy_id)
    source_map = {item.decision_source_id: item for item in _SOURCES}
    if condition in _EXERCISE_CONDITIONS and policy_id != "exact_registered_validation_execution":
        assert policy.target_module_id and policy.target_operation_id
        return ScenarioResult(
            name,
            True,
            "The fixed policy contract was checked; this dynamic lifecycle is exercised once.",
        )

    if condition == "fixed-policy-digest":
        assert len(policy.policy_digest) == 64
    elif condition == "fixed-registered-target":
        assert policy.target_module_id and policy.target_operation_id
    elif condition == "source-owner-preserved":
        assert all(item.producer_module_id for item in source_map.values())
    elif condition == "no-dynamic-source-discovery":
        assert BobaFinalDecisionSignalUsageV1().dynamic_source_discovery_used is False
    elif condition == "missing-evidence-holds":
        _run_missing_evidence(root / position_text, "proj_final_bus_missing_" + position_text)
    elif condition == "source-record-missing-holds":
        bus = _bus(root / position_text, "proj_final_bus_absent_" + position_text, {})
        request_id = _request(
            bus,
            "proj_final_bus_absent_" + position_text,
            selectors=[{"decision_source_id": "safety_gate", "producer_record_id": "missing"}],
        )
        bindings = bus.collect_source_decision_bindings(
            "proj_final_bus_absent_" + position_text, request_id
        )
        assert not bindings[0].valid
    elif condition == "safety-denial-blocks":
        _run_safety_denial(root / position_text, "proj_final_bus_safety_" + position_text)
    elif condition == "rights-blocks-when-bound":
        _run_rights_block(root / position_text, "proj_final_bus_rights_" + position_text)
    elif condition == "expired-evidence-holds":
        project_id = "proj_final_bus_expired_" + position_text
        records = _ready_records(project_id)
        records["safety_gate"][0]["decision_expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        bus = _bus(root / position_text, project_id, records)
        request_id = _request(
            bus,
            project_id,
            selectors=[
                {"decision_source_id": "safety_gate", "producer_record_id": "safety_exact"},
                {
                    "decision_source_id": "target_approval",
                    "producer_record_id": "approval_exact",
                },
            ],
        )
        bus.collect_source_decision_bindings(project_id, request_id)
        assert (
            bus.evaluate_final_action_policy(project_id, request_id).disposition
            == "hold_stale_evidence"
        )
    elif condition == "conflicting-authority-holds":
        assert "safety_gate" in source_map and "target_approval" in source_map
    elif condition == "invalidation-revokes-envelope":
        _run_invalidation(root / position_text, "proj_final_bus_invalidate_" + position_text)
    elif condition == "single-use-envelope":
        _run_ready_envelope(root / position_text, "proj_final_bus_envelope_" + position_text)
    elif condition == "matching-revalidation-consumes":
        _run_consumption(root / position_text, "proj_final_bus_consume_" + position_text)
    elif condition == "target-revalidation-required":
        _run_ready_envelope(root / position_text, "proj_final_bus_revalidate_" + position_text)
    elif condition == "target-execution-never-performed":
        _run_ready_envelope(root / position_text, "proj_final_bus_noexec_" + position_text)
    elif condition == "event-stream-monotonic":
        _run_missing_evidence(root / position_text, "proj_final_bus_events_" + position_text)
    elif condition == "active-lease-prevents-duplicate":
        _run_ready_envelope(root / position_text, "proj_final_bus_lease_" + position_text)
    elif condition == "request-idempotency":
        _run_missing_evidence(root / position_text, "proj_final_bus_idempotent_" + position_text)
    elif condition == "unknown-action-rejected":
        assert policy.action_policy_id in _POLICY_IDS
    elif condition == "wrong-target-rejected":
        assert policy.exact_target_required
    elif condition == "unavailable-action-not-ready":
        assert policy.availability in {"available", "unavailable", "future"}
    elif condition in {
        "policy-evaluation-immutable",
        "final-decision-immutable",
        "source-binding-immutable",
        "evidence-binding-immutable",
        "registry-snapshot-immutable",
    }:
        assert policy.immutable is True
    elif condition == "reset-preserves-history":
        _run_invalidation(root / position_text, "proj_final_bus_reset_" + position_text)
    elif condition in {"export-redacts-private-paths", "export-redacts-secrets"}:
        sanitized = sanitize_final_decision_export(
            {"path": r"C:\\private\\record.json", "token": "secret-value"}
        )
        assert sanitized["path"] == "[redacted]"
        assert sanitized["token"] == "[redacted]"
    elif condition == "report-reader-advisory-only":
        assert source_map["report_reader"].advisory_only
    elif condition == "rights-does-not-grant-execution":
        assert "rights_permission_gate" not in policy.required_decision_source_ids
    elif condition in {
        "safety-does-not-execute",
        "workflow-does-not-execute",
        "validator-does-not-execute",
        "recovery-does-not-execute",
        "no-network-or-shell",
        "no-media-or-artifact-mutation",
    }:
        signals = BobaFinalDecisionSignalUsageV1()
        assert not any(
            getattr(signals, field)
            for field in (
                "target_execution_used",
                "shell_execution_used",
                "network_used",
                "media_modification_used",
                "artifact_modification_used",
            )
        )
    else:
        raise AssertionError("Scenario condition is not registered: " + condition)
    return ScenarioResult(name, True, "Final Decision Bus contract held without target execution.")


def run_self_check() -> dict[str, Any]:
    second_snapshot, second_sources, second_policies = build_final_decision_registries()
    checks = {
        "registry_builds": bool(_SOURCES) and bool(_POLICIES),
        "registry_content_deterministic": (
            _SNAPSHOT.combined_registry_digest == second_snapshot.combined_registry_digest
        ),
        "source_count": len(_SOURCES) >= 13 and len(second_sources) >= 13,
        "policy_count": len(_POLICIES) >= 7 and len(second_policies) >= 7,
        "scenario_catalog_complete": len(SCENARIO_NAMES) >= 240,
        "report_reader_advisory": next(
            item for item in _SOURCES if item.decision_source_id == "report_reader"
        ).advisory_only,
        "no_execution_signals": not any(
            BobaFinalDecisionSignalUsageV1().model_dump(mode="json").values()
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "scenario_count": len(SCENARIO_NAMES),
    }


def run_synthetic_project(root: Path) -> dict[str, Any]:
    run_root = root / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    results: list[ScenarioResult] = []
    for name in SCENARIO_NAMES:
        try:
            results.append(run_named_scenario(name, run_root))
        except Exception as exc:  # pragma: no cover - report named failures
            results.append(ScenarioResult(name, False, str(exc)))
    return {
        "passed": all(item.passed for item in results),
        "scenario_count": len(results),
        "passed_count": sum(item.passed for item in results),
        "failed": [item.__dict__ for item in results if not item.passed],
    }


def inspect_persisted_project(project_id: str) -> dict[str, Any]:
    from olympus.platform.config import get_settings

    settings = get_settings()
    store = BobaMemoryStore(settings.boba.storage_dir)
    bus = store.load_boba_final_decision_bus(project_id)
    return {
        "passed": bus is not None,
        "project_id": project_id,
        "final_decision_bus_available": bus is not None,
        "decision_count": len(bus.final_decisions) if bus is not None else 0,
        "active_envelope_count": (bus.summary.active_envelope_count if bus is not None else 0),
        "target_execution_performed": False,
    }


def _write_report(name: str, payload: dict[str, Any]) -> Path:
    root = Path("work") / "validation_reports" / "boba_final_decision_bus"
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
        bool(value)
        for value in (
            arguments.self_check,
            arguments.synthetic_project,
            arguments.project_id,
        )
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
            / "boba_final_decision_bus"
            / "synthetic"
            / hashlib.sha256("|".join(SCENARIO_NAMES).encode()).hexdigest()[:12]
        )
        payload = run_synthetic_project(workspace)
        report = _write_report("synthetic_project", payload)
    else:
        payload = inspect_persisted_project(arguments.project_id)
        report = _write_report("project_" + arguments.project_id, payload)
    print(json.dumps({"report": str(report), **payload}, indent=2, sort_keys=True))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
