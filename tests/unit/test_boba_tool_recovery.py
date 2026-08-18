"""BOBA Tool Recovery Brain V1 contracts, execution, API, and safety tests."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_repair_planner import (
    build_synthetic_planning_context,
    build_synthetic_root_cause_report,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.integration import BobaIntegration
from olympus.boba.repair_planner import BobaRepairPlannerSetV1, BobaRepairPlannerV1
from olympus.boba.store import BobaMemoryStore
from olympus.boba.tool_recovery import (
    EXPLICIT_RECOVERY_CONFIRMATION,
    BobaRecoveredOutputValidationV1,
    BobaRecoveryCommandV1,
    BobaRegisteredRecoveryToolV1,
    BobaToolCapabilityV1,
    BobaToolHealthCheckV1,
    BobaToolHealthResultV1,
    BobaToolRecoveryApprovalV1,
    BobaToolRecoveryAttemptV1,
    BobaToolRecoveryBrainSetV1,
    BobaToolRecoveryBrainV1,
    BobaToolRecoveryCaseV1,
    BobaToolRecoveryHandoffV1,
    BobaToolRecoveryPlanV1,
    BobaToolRecoveryRollbackV1,
    BobaToolRecoverySignalUsageV1,
    BobaToolRecoveryStrategyV1,
    BobaToolRecoverySummaryV1,
    build_minimal_capability_registry,
    build_trusted_recovery_command_registry,
    classify_tool_failure,
    fingerprint_recovery_strategy,
    validate_recovery_command_safety,
    validate_recovery_paths,
    verify_recovery_approval,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_tool_recovery_test"


@lru_cache(maxsize=4)
def _base_planner(project_id: str = PROJECT_ID) -> BobaRepairPlannerSetV1:
    root = build_synthetic_root_cause_report(project_id)
    return BobaRepairPlannerV1().plan(
        project_id,
        root,
        manual_context=build_synthetic_planning_context(root),
    )


def _eligible_planner(
    project_id: str = PROJECT_ID,
) -> tuple[BobaRepairPlannerSetV1, str]:
    planner = _base_planner(project_id).model_copy(deep=True)
    handoff = next(
        item
        for item in planner.execution_handoffs
        if item.target_module == "tool_recovery_brain"
        and "resource" in next(
            repair_case.title.lower()
            for repair_case in planner.repair_cases
            if repair_case.repair_case_id == item.repair_case_id
        )
    )
    strategy = next(
        item
        for item in planner.repair_strategies
        if item.repair_strategy_id == handoff.repair_strategy_id
    )
    strategy.requires_code_change = False
    strategy.requires_package_installation = False
    strategy.requires_service_restart = False
    strategy.requires_external_access = False
    strategy.requires_paid_service = False
    strategy.requires_checkpoint = False
    strategy.destructiveness = "low"
    strategy.maximum_attempts = 2
    strategy.maximum_recovery_duration_seconds = 120
    repair_case = next(
        item
        for item in planner.repair_cases
        if item.repair_case_id == handoff.repair_case_id
    )
    checkpoint = next(
        (
            item
            for item in planner.checkpoint_plans
            if item.checkpoint_plan_id == repair_case.checkpoint_plan_id
        ),
        None,
    )
    if checkpoint is not None:
        checkpoint.checkpoint_required = False
        checkpoint.checkpoint_type = "none"
    quality = next(
        (
            item
            for item in planner.quality_preservation_plans
            if item.quality_preservation_plan_id
            == repair_case.quality_preservation_plan_id
        ),
        None,
    )
    requirements = [
        "duration remains within 0.15 seconds",
        "resolution remains exact",
        "frame rate remains exact",
        "audio remains present",
        "A/V synchronization remains within 0.15 seconds",
        "source media remains untouched",
        "accepted outputs remain untouched",
    ]
    handoff.required_quality_properties = requirements
    if quality is not None:
        quality.original_requirements = requirements
        quality.non_negotiable_requirements = requirements
        quality.technical_quality_checks = requirements
        quality.rights_safety_checks = []
        quality.creative_quality_checks = []
    return planner, handoff.handoff_id


def _context(**overrides: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "required_capability": "media_encode_check",
        "failure_class": "resource_exhaustion",
        "rights_status": "clear",
        "safety_status": "clear",
        "checkpoint_ready": True,
        "configuration_overrides": {
            "output_filename": "recovered.mp4",
            "expected_duration_seconds": 1.0,
            "expected_width": 320,
            "expected_height": 180,
            "expected_fps": 24,
            "require_audio": True,
            "encoder_threads": 1,
            "filter_threads": 1,
            "parallel_tasks": 1,
        },
    }
    context.update(overrides)
    return context


def _engine(tmp_path: Path, *, mode: str = "plan_only") -> BobaToolRecoveryBrainV1:
    return BobaToolRecoveryBrainV1(
        tmp_path,
        workspace_root=tmp_path / "work" / "boba" / "tool_recovery" / "workspaces",
        approved_input_roots=[
            tmp_path / "work",
            tmp_path / "storage_data",
            tmp_path / "media",
        ],
        mode=mode,  # type: ignore[arg-type]
    )


def _report(
    tmp_path: Path,
    *,
    health: bool = False,
    context: dict[str, Any] | None = None,
) -> tuple[BobaToolRecoveryBrainV1, BobaToolRecoveryBrainSetV1]:
    planner, handoff_id = _eligible_planner()
    engine = _engine(tmp_path)
    report = engine.plan(
        PROJECT_ID,
        planner,
        selected_handoff_id=handoff_id,
        failure_context=context or _context(),
        run_health_checks=health,
    )
    return engine, report


def _strategy(report: BobaToolRecoveryBrainSetV1) -> BobaToolRecoveryStrategyV1:
    plan = report.recovery_plans[0]
    return next(
        item
        for item in plan.ordered_strategies
        if item.strategy_type == "reduce_thread_usage"
    )


def _approval(
    plan: BobaToolRecoveryPlanV1,
    strategy: BobaToolRecoveryStrategyV1,
    **changes: Any,
) -> BobaToolRecoveryApprovalV1:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "approval_id": f"approval_{strategy.recovery_strategy_id}",
        "recovery_case_id": plan.recovery_case_id,
        "recovery_plan_id": plan.recovery_plan_id,
        "approved": True,
        "approved_at": now.isoformat(),
        "approved_by": "local-human-reviewer",
        "approved_strategy_ids": [strategy.recovery_strategy_id],
        "approved_tool_ids": [strategy.tool_id],
        "approved_configuration_overrides": strategy.configuration_overrides,
        "approved_retry_budget": plan.retry_budget,
        "approved_time_budget_seconds": plan.time_budget_seconds,
        "approved_quality_requirements": plan.quality_requirements,
        "approved_checkpoint_reference": str(
            plan.checkpoint_requirements.get("reference") or ""
        ),
        "approval_expires_at": (now + timedelta(minutes=15)).isoformat(),
        "explicit_confirmation": EXPLICIT_RECOVERY_CONFIRMATION,
        "warnings": [],
    }
    values.update(changes)
    return BobaToolRecoveryApprovalV1.model_validate(values)


def _project(project_id: str = PROJECT_ID) -> Project:
    timestamp = utc_now()
    return Project(
        id=project_id,
        name="BOBA Tool Recovery V1 Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=120.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _integration(
    tmp_path: Path,
) -> tuple[BobaIntegration, BobaMemoryStore]:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    integration = BobaIntegration(storage, store)
    integration.tool_recovery = _engine(tmp_path)
    return integration, store


@pytest.mark.parametrize(
    ("failure_class", "expected"),
    [
        ("tool_unavailable", "tool_unavailable"),
        ("executable_missing", "executable_missing"),
        ("incompatible_version", "incompatible_version"),
        ("temporary_crash", "temporary_crash"),
        ("repeated_crash", "repeated_crash"),
        ("timeout", "timeout"),
        ("malformed_output", "malformed_output"),
        ("unsupported_input", "unsupported_input"),
        ("resource_exhaustion", "resource_exhaustion"),
        ("configuration_problem", "configuration_problem"),
        ("environment_problem", "environment_problem"),
        ("permission_problem", "permission_problem"),
        ("generated_state_problem", "generated_state_problem"),
        ("checkpoint_problem", "checkpoint_problem"),
        ("external_service_unavailable", "external_service_unavailable"),
        ("unknown", "unknown"),
    ],
)
def test_failure_class_context_is_deterministic(
    failure_class: str,
    expected: str,
) -> None:
    assert classify_tool_failure(None, None, {"failure_class": failure_class}) == expected


@pytest.mark.parametrize(
    "capability_id",
    [
        "video_probe",
        "video_render",
        "audio_probe",
        "media_decode_check",
        "media_encode_check",
        "frame_extraction",
        "audio_extraction",
        "transcript_provider_local",
        "JSON_artifact_validation",
        "checksum_validation",
    ],
)
def test_registry_contains_required_capability(capability_id: str) -> None:
    capabilities, _ = build_minimal_capability_registry()
    assert capability_id in {item.capability_id for item in capabilities}


@pytest.mark.parametrize(
    "tool_id",
    [
        "ffprobe",
        "ffmpeg",
        "pyav",
        "opencv",
        "faster_whisper_local",
        "internal_json_validator",
        "internal_checksum_validator",
        "external_transcription_service",
    ],
)
def test_registry_contains_truthful_tool(tool_id: str) -> None:
    _, tools = build_minimal_capability_registry()
    tool = next(item for item in tools if item.tool_id == tool_id)
    assert tool.available is False
    if tool.provider_type == "external_service":
        assert tool.health_status == "blocked"


@pytest.mark.parametrize(
    "signal_name",
    [
        "source_media_modified",
        "completed_outputs_modified",
        "workflow_resume_used",
        "code_modification_used",
        "package_installation_used",
        "service_restart_used",
        "process_kill_used",
        "external_api_used",
        "network_access_used",
        "url_fetching_used",
        "scraping_used",
        "downloading_used",
        "uploading_used",
        "paid_service_used",
        "rights_bypass_used",
        "safety_bypass_used",
        "destructive_action_used",
    ],
)
def test_prohibited_signal_defaults_false(signal_name: str) -> None:
    signals = BobaToolRecoverySignalUsageV1()
    assert getattr(signals, signal_name) is False


@pytest.mark.parametrize(
    "argument",
    [
        "|",
        ">",
        "<",
        "&&",
        "||",
        ";",
        "`whoami`",
        "$(whoami)",
        "\nwhoami",
        "https://example.invalid/media.mp4",
        "tcp://127.0.0.1:9000",
        "-command",
        "/c",
        "install",
        "uninstall",
        "upgrade",
        "download",
        "upload",
        "push",
        "kill",
    ],
)
def test_command_safety_rejects_injection_or_prohibited_action(argument: str) -> None:
    _, tools = build_minimal_capability_registry()
    tool = next(item for item in tools if item.tool_id == "ffmpeg")
    command = BobaRecoveryCommandV1(
        recovery_command_id="command_rejected",
        tool_id="ffmpeg",
        executable=tool.executable,
        arguments=[argument],
        working_directory_scope="work/boba/tool_recovery/workspaces/run_safe",
        category="render_retry",
        approved=True,
    )
    assert validate_recovery_command_safety(
        command,
        tools,
        build_trusted_recovery_command_registry(tools),
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "approved",
        "confirmation",
        "case",
        "plan",
        "strategy",
        "tool",
        "settings",
        "retry",
        "time",
        "quality",
        "checkpoint",
        "expiry",
    ],
)
def test_approval_binding_rejects_every_meaningful_change(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    changes: dict[str, Any] = {}
    if mutation == "approved":
        changes["approved"] = False
    elif mutation == "confirmation":
        changes["explicit_confirmation"] = "approve"
    elif mutation == "case":
        changes["recovery_case_id"] = "tool_case_changed"
    elif mutation == "plan":
        changes["recovery_plan_id"] = "tool_plan_changed"
    elif mutation == "strategy":
        changes["approved_strategy_ids"] = ["tool_strategy_changed"]
    elif mutation == "tool":
        changes["approved_tool_ids"] = ["ffprobe"]
    elif mutation == "settings":
        changes["approved_configuration_overrides"] = {"encoder_threads": 2}
    elif mutation == "retry":
        changes["approved_retry_budget"] = {"maximum_total_attempts": 99}
    elif mutation == "time":
        changes["approved_time_budget_seconds"] = plan.time_budget_seconds - 1
    elif mutation == "quality":
        changes["approved_quality_requirements"] = ["lower quality"]
    elif mutation == "checkpoint":
        changes["approved_checkpoint_reference"] = "changed"
    else:
        changes["approval_expires_at"] = "2000-01-01T00:00:00+00:00"
    assert verify_recovery_approval(plan, strategy, _approval(plan, strategy, **changes))


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "../source.mp4",
        "work/../source.mp4",
        "/absolute/source.mp4",
        "C:/private/source.mp4",
        "C:\\private\\source.mp4",
        "\\\\server\\share\\source.mp4",
        "./source.mp4",
        "work//source.mp4",
        "https://example.invalid/source.mp4",
    ],
)
def test_input_path_rejects_invalid_or_escaping_reference(
    tmp_path: Path,
    reference: str,
) -> None:
    with pytest.raises(ValidationError):
        validate_recovery_paths(
            repository_root=tmp_path,
            workspace_root=tmp_path / "work" / "boba" / "tool_recovery" / "run",
            input_reference=reference,
            output_filename="output.mp4",
            approved_input_roots=[tmp_path / "work"],
        )


@pytest.mark.parametrize(
    "failure_class",
    [
        "tool_unavailable",
        "executable_missing",
        "incompatible_version",
        "temporary_crash",
        "repeated_crash",
        "timeout",
        "malformed_output",
        "unsupported_input",
        "resource_exhaustion",
        "configuration_problem",
        "generated_state_problem",
        "unknown",
    ],
)
def test_every_supported_failure_builds_a_finite_ladder(
    tmp_path: Path,
    failure_class: str,
) -> None:
    _, report = _report(
        tmp_path,
        context=_context(failure_class=failure_class),
    )
    plan = report.recovery_plans[0]
    assert 1 <= len(plan.ordered_strategies) <= 10
    assert plan.retry_budget["maximum_attempts_per_strategy"] <= 2
    assert plan.retry_budget["maximum_total_attempts"] <= 4
    assert plan.time_budget_seconds <= 1_800


@pytest.mark.parametrize(
    "contract_name",
    [
        "capability",
        "tool",
        "health_check",
        "health_result",
        "case",
        "strategy",
        "plan",
        "approval",
        "command",
        "attempt",
        "validation",
        "rollback",
        "handoff",
        "summary",
        "signals",
        "report",
    ],
)
def test_contract_roundtrip_json_safe(tmp_path: Path, contract_name: str) -> None:
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    capability = report.capability_registry[0]
    tool = report.registered_tools[0]
    health_check = tool.health_check
    assert health_check is not None
    health_result = BobaToolHealthResultV1(
        health_result_id="health_result_roundtrip",
        health_check_id=health_check.health_check_id,
        tool_id=tool.tool_id,
        status="healthy",
    )
    command = BobaRecoveryCommandV1(
        recovery_command_id="command_roundtrip",
        tool_id="ffmpeg",
        executable="ffmpeg",
        arguments=["-version"],
        working_directory_scope="work/boba/tool_recovery/workspaces/run_roundtrip",
        category="health_check",
        approved=True,
    )
    attempt = BobaToolRecoveryAttemptV1(
        recovery_attempt_id="attempt_roundtrip",
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        attempt_number=1,
        tool_id=strategy.tool_id,
        capability_id=strategy.capability_id,
        working_directory_reference=(
            "work/boba/tool_recovery/workspaces/attempt_roundtrip"
        ),
        command_records=[command],
    )
    validation = BobaRecoveredOutputValidationV1(
        output_validation_id="validation_roundtrip",
        recovery_attempt_id=attempt.recovery_attempt_id,
    )
    rollback = BobaToolRecoveryRollbackV1(
        rollback_record_id="rollback_roundtrip",
        recovery_attempt_id=attempt.recovery_attempt_id,
        trigger="Not required.",
        status="not_required",
    )
    handoff = BobaToolRecoveryHandoffV1(
        handoff_id="handoff_roundtrip",
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        target_module="human_operator",
        reason="Review.",
    )
    values: dict[str, tuple[Any, Any]] = {
        "capability": (capability, BobaToolCapabilityV1),
        "tool": (tool, BobaRegisteredRecoveryToolV1),
        "health_check": (health_check, BobaToolHealthCheckV1),
        "health_result": (health_result, BobaToolHealthResultV1),
        "case": (report.recovery_cases[0], BobaToolRecoveryCaseV1),
        "strategy": (strategy, BobaToolRecoveryStrategyV1),
        "plan": (plan, BobaToolRecoveryPlanV1),
        "approval": (_approval(plan, strategy), BobaToolRecoveryApprovalV1),
        "command": (command, BobaRecoveryCommandV1),
        "attempt": (attempt, BobaToolRecoveryAttemptV1),
        "validation": (validation, BobaRecoveredOutputValidationV1),
        "rollback": (rollback, BobaToolRecoveryRollbackV1),
        "handoff": (handoff, BobaToolRecoveryHandoffV1),
        "summary": (report.recovery_summary, BobaToolRecoverySummaryV1),
        "signals": (report.signal_usage, BobaToolRecoverySignalUsageV1),
        "report": (report, BobaToolRecoveryBrainSetV1),
    }
    value, model = values[contract_name]
    assert model.model_validate(value.model_dump(mode="json")) == value
    json.dumps(value.model_dump(mode="json"))


def test_missing_planner_produces_blocked_report(tmp_path: Path) -> None:
    result = _engine(tmp_path).plan(PROJECT_ID, None)
    assert result.recovery_cases[0].recovery_eligible is False
    assert result.signal_usage.repair_planner_used is False
    assert result.signal_usage.recovery_commands_executed is False


def test_malformed_planner_produces_blocked_report(tmp_path: Path) -> None:
    result = _engine(tmp_path).plan(PROJECT_ID, {"broken": True})
    assert result.recovery_summary.blocked_case_count == 1
    assert result.recovery_handoffs[0].target_module == "human_operator"


def test_missing_tool_handoff_blocks(tmp_path: Path) -> None:
    planner = _base_planner().model_copy(deep=True)
    planner.execution_handoffs = [
        item for item in planner.execution_handoffs if item.target_module != "tool_recovery_brain"
    ]
    result = _engine(tmp_path).plan(PROJECT_ID, planner)
    assert "No valid Repair Planner" in result.recovery_cases[0].blocked_reason


def test_plan_only_never_executes_command(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    assert report.signal_usage.recovery_commands_executed is False
    assert report.signal_usage.output_validation_used is False
    assert report.recovery_attempts == []


def test_default_mode_runs_only_registered_health_checks(tmp_path: Path) -> None:
    planner, handoff_id = _eligible_planner()
    result = _engine(tmp_path, mode="plan_and_health_check").plan(
        PROJECT_ID,
        planner,
        selected_handoff_id=handoff_id,
        failure_context=_context(),
    )
    assert result.signal_usage.local_health_checks_executed is True
    assert result.signal_usage.recovery_commands_executed is False


def test_health_checks_are_shell_free_and_network_free(tmp_path: Path) -> None:
    _, report = _report(tmp_path, health=True)
    checks = [
        tool.health_check for tool in report.registered_tools if tool.health_check is not None
    ]
    assert checks
    assert all(check.shell_used is False for check in checks)
    assert all(check.network_required is False for check in checks)


def test_external_service_stays_blocked_after_health_check(tmp_path: Path) -> None:
    engine, report = _report(tmp_path)
    result = engine.run_health_checks(
        report,
        tool_ids=["external_transcription_service"],
    )
    tool = next(
        item
        for item in result.registered_tools
        if item.tool_id == "external_transcription_service"
    )
    assert tool.available is False
    assert tool.health_status == "blocked"


def test_internal_validator_health_is_local(tmp_path: Path) -> None:
    engine, report = _report(tmp_path)
    result = engine.run_health_checks(
        report,
        tool_ids=["internal_json_validator"],
    )
    health = result.tool_health_results[-1]
    assert health.status == "healthy"
    assert result.signal_usage.network_access_used is False


def test_unverified_tool_is_not_execution_eligible(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    assert _strategy(report).execution_allowed is False


def test_healthy_ffmpeg_enables_bounded_encode_strategy(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is unavailable in this environment.")
    _, report = _report(tmp_path, health=True)
    assert _strategy(report).execution_allowed is True


def test_exact_approval_passes(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    assert verify_recovery_approval(plan, strategy, _approval(plan, strategy)) == []


def test_approval_requires_bounded_expiration(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    errors = verify_recovery_approval(
        plan,
        strategy,
        _approval(plan, strategy, approval_expires_at=None),
    )
    assert any("expired" in item for item in errors)


def test_strategy_fingerprint_changes_with_settings(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    strategy = _strategy(report)
    changed = strategy.model_copy(deep=True)
    changed.configuration_overrides["encoder_threads"] = 2
    assert fingerprint_recovery_strategy(strategy) != fingerprint_recovery_strategy(
        changed
    )


def test_retry_budget_is_hard_capped(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    assert plan.retry_budget["maximum_attempts_per_strategy"] == 2
    assert plan.retry_budget["maximum_total_attempts"] == 4
    assert plan.time_budget_seconds <= 1_800


def test_reduced_threads_preserves_quality_contract(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    strategy = _strategy(report)
    assert strategy.configuration_overrides["encoder_threads"] == 1
    assert strategy.configuration_overrides["filter_threads"] == 1
    assert strategy.configuration_overrides["expected_width"] == 320
    assert strategy.configuration_overrides["expected_height"] == 180
    assert strategy.configuration_overrides["expected_fps"] == 24
    assert strategy.configuration_overrides["require_audio"] is True


def test_segmented_strategy_is_bounded_and_executable_when_healthy(
    tmp_path: Path,
) -> None:
    _, report = _report(tmp_path, health=True)
    segmented = next(
        item
        for item in report.recovery_plans[0].ordered_strategies
        if item.strategy_type == "segmented_processing"
    )
    assert segmented.execution_allowed is (shutil.which("ffmpeg") is not None)
    assert segmented.configuration_overrides["parallel_tasks"] == 1
    assert "maximum of 16" in " ".join(segmented.limitations)


def test_segmented_strategy_renders_validates_and_concatenates(
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg/FFprobe are unavailable in this environment.")
    context = _context()
    context["configuration_overrides"].update(
        {
            "expected_duration_seconds": 6.0,
            "segment_seconds": 5,
        }
    )
    engine, report = _report(
        tmp_path,
        health=True,
        context=context,
    )
    plan = report.recovery_plans[0]
    segmented = next(
        item
        for item in plan.ordered_strategies
        if item.strategy_type == "segmented_processing"
    )
    result = engine.execute_approved(
        report,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=segmented.recovery_strategy_id,
        approval=_approval(plan, segmented),
    )
    attempt = result.recovery_attempts[-1]
    validation = result.output_validations[-1]
    assert attempt.status == "completed"
    assert validation.required_checks_passed is True
    assert len(attempt.command_records) == 3
    assert all(
        command.category == "segmented_render"
        for command in attempt.command_records
    )
    assert all("-shortest" not in command.arguments for command in attempt.command_records)


def test_command_registry_contains_only_expected_categories() -> None:
    _, tools = build_minimal_capability_registry()
    registry = build_trusted_recovery_command_registry(tools)
    assert "render_retry" in registry["ffmpeg"]
    assert "media_probe" in registry["ffprobe"]
    assert registry["external_transcription_service"] == ("health_check",)


def test_unregistered_executable_is_rejected() -> None:
    _, tools = build_minimal_capability_registry()
    command = BobaRecoveryCommandV1(
        recovery_command_id="command_unknown",
        tool_id="unknown_tool",
        executable="unknown.exe",
        arguments=[],
        working_directory_scope="work/boba/tool_recovery/workspaces/run_unknown",
        category="unknown",
    )
    errors = validate_recovery_command_safety(
        command,
        tools,
        build_trusted_recovery_command_registry(tools),
    )
    assert any("unregistered" in item for item in errors)


def test_package_manager_executable_is_rejected() -> None:
    _, tools = build_minimal_capability_registry()
    command = BobaRecoveryCommandV1(
        recovery_command_id="command_pip",
        tool_id="ffmpeg",
        executable="pip",
        arguments=["install", "something"],
        working_directory_scope="work/boba/tool_recovery/workspaces/run_pip",
        category="render_retry",
    )
    errors = validate_recovery_command_safety(
        command,
        tools,
        build_trusted_recovery_command_registry(tools),
    )
    assert any("prohibited" in item for item in errors)


def test_shortest_is_rejected() -> None:
    _, tools = build_minimal_capability_registry()
    ffmpeg = next(item for item in tools if item.tool_id == "ffmpeg")
    command = BobaRecoveryCommandV1(
        recovery_command_id="command_shortest",
        tool_id="ffmpeg",
        executable=ffmpeg.executable,
        arguments=["-shortest"],
        working_directory_scope="work/boba/tool_recovery/workspaces/run_shortest",
        category="render_retry",
    )
    errors = validate_recovery_command_safety(
        command,
        tools,
        build_trusted_recovery_command_registry(tools),
    )
    assert any("-shortest" in item or "Unallowlisted" in item for item in errors)


def test_valid_workspace_paths_resolve(tmp_path: Path) -> None:
    source = tmp_path / "work" / "fixtures" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic")
    workspace = tmp_path / "work" / "boba" / "tool_recovery" / "run_safe"
    input_path, output_path = validate_recovery_paths(
        repository_root=tmp_path,
        workspace_root=workspace,
        input_reference="work/fixtures/source.mp4",
        output_filename="recovered.mp4",
        approved_input_roots=[tmp_path / "work"],
    )
    assert input_path == source.resolve()
    assert output_path.parent.name == "outputs"
    assert not output_path.exists()


def test_existing_output_cannot_be_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "work" / "fixtures" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic")
    workspace = tmp_path / "work" / "boba" / "tool_recovery" / "run_existing"
    output = workspace / "outputs" / "recovered.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"accepted")
    with pytest.raises(ValidationError):
        validate_recovery_paths(
            repository_root=tmp_path,
            workspace_root=workspace,
            input_reference="work/fixtures/source.mp4",
            output_filename="recovered.mp4",
            approved_input_roots=[tmp_path / "work"],
        )


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "source.mp4"
    source.write_bytes(b"synthetic")
    approved = tmp_path / "work"
    approved.mkdir()
    link = approved / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable.")
    with pytest.raises(ValidationError):
        validate_recovery_paths(
            repository_root=tmp_path,
            workspace_root=approved / "boba" / "tool_recovery" / "run_link",
            input_reference="work/escape/source.mp4",
            output_filename="recovered.mp4",
            approved_input_roots=[approved],
        )


def test_approved_synthetic_encode_passes_technical_validation(
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg/FFprobe are unavailable in this environment.")
    engine, report = _report(tmp_path, health=True)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    result = engine.execute_approved(
        report,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        approval=_approval(plan, strategy),
    )
    attempt = result.recovery_attempts[-1]
    validation = result.output_validations[-1]
    assert attempt.status == "completed"
    assert validation.required_checks_passed is True
    assert validation.accepted_for_quality_review is True
    assert result.signal_usage.recovery_commands_executed is True
    assert result.signal_usage.output_validation_used is True
    assert result.signal_usage.workflow_resume_used is False
    assert {
        "output_quality_reviewer",
        "safety_gate",
        "workflow_controller",
    }.issubset({item.target_module for item in result.recovery_handoffs})


def test_approved_execution_preserves_no_shortest(
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg/FFprobe are unavailable in this environment.")
    engine, report = _report(tmp_path, health=True)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    result = engine.execute_approved(
        report,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        approval=_approval(plan, strategy),
    )
    command = result.recovery_attempts[-1].command_records[0]
    assert "-shortest" not in command.arguments
    assert command.shell_used is False
    assert command.network_forbidden is True


def test_missing_output_fails_and_rolls_back(tmp_path: Path) -> None:
    engine, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    attempt = BobaToolRecoveryAttemptV1(
        recovery_attempt_id="tool_attempt_missing",
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        attempt_number=1,
        tool_id=strategy.tool_id,
        capability_id=strategy.capability_id,
        working_directory_reference=(
            "work/boba/tool_recovery/workspaces/tool_attempt_missing"
        ),
        status="succeeded_pending_validation",
        output_artifact_refs=[
            "work/boba/tool_recovery/workspaces/tool_attempt_missing/outputs/missing.mp4"
        ],
    )
    (engine.workspace_root / attempt.recovery_attempt_id / "outputs").mkdir(
        parents=True
    )
    report.recovery_attempts.append(attempt)
    engine.validate_output(report, recovery_attempt_id=attempt.recovery_attempt_id)
    assert report.output_validations[-1].artifact_exists is False
    assert report.rollback_records[-1].status == "completed"
    assert report.recovery_attempts[-1].status == "rolled_back"


def test_empty_output_fails_required_check(tmp_path: Path) -> None:
    engine, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    attempt_id = "tool_attempt_empty"
    output = engine.workspace_root / attempt_id / "outputs" / "empty.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"")
    attempt = BobaToolRecoveryAttemptV1(
        recovery_attempt_id=attempt_id,
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        attempt_number=1,
        tool_id=strategy.tool_id,
        capability_id=strategy.capability_id,
        working_directory_reference=(
            f"work/boba/tool_recovery/workspaces/{attempt_id}"
        ),
        status="succeeded_pending_validation",
        output_artifact_refs=[
            f"work/boba/tool_recovery/workspaces/{attempt_id}/outputs/empty.mp4"
        ],
    )
    report.recovery_attempts.append(attempt)
    engine.validate_output(report, recovery_attempt_id=attempt_id)
    validation = report.output_validations[-1]
    assert validation.artifact_non_empty is False
    assert "artifact_non_empty" in validation.failed_required_checks


def test_rollback_removes_only_recovery_owned_output(tmp_path: Path) -> None:
    engine, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    attempt_id = "tool_attempt_rollback"
    output = engine.workspace_root / attempt_id / "outputs" / "failed.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"failed")
    protected = tmp_path / "storage_data" / "accepted.mp4"
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"accepted")
    attempt = BobaToolRecoveryAttemptV1(
        recovery_attempt_id=attempt_id,
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        attempt_number=1,
        tool_id=strategy.tool_id,
        capability_id=strategy.capability_id,
        working_directory_reference=(
            f"work/boba/tool_recovery/workspaces/{attempt_id}"
        ),
        status="failed",
        output_artifact_refs=[
            f"work/boba/tool_recovery/workspaces/{attempt_id}/outputs/failed.mp4"
        ],
    )
    report.recovery_attempts.append(attempt)
    engine.rollback(
        report,
        recovery_attempt_id=attempt_id,
        trigger="Synthetic validation failure.",
    )
    assert not output.exists()
    assert protected.read_bytes() == b"accepted"
    assert report.rollback_records[-1].source_media_preserved is True
    assert report.rollback_records[-1].original_outputs_preserved is True
    assert report.rollback_records[-1].checkpoint_unchanged is True


def test_persistence_writes_summary_and_per_run(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    attempt = BobaToolRecoveryAttemptV1(
        recovery_attempt_id="tool_attempt_persist",
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        attempt_number=1,
        tool_id=strategy.tool_id,
        capability_id=strategy.capability_id,
        working_directory_reference=(
            "work/boba/tool_recovery/workspaces/tool_attempt_persist"
        ),
    )
    report.recovery_attempts.append(attempt)
    store.save_boba_tool_recovery(report)
    assert store.tool_recovery_path(PROJECT_ID).is_file()
    assert store.tool_recovery_run_path(
        PROJECT_ID,
        attempt.recovery_attempt_id,
    ).is_file()
    assert store.load_boba_tool_recovery(PROJECT_ID) is not None


def test_malformed_persisted_report_degrades_safely(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    path = store.tool_recovery_path(PROJECT_ID)
    path.parent.mkdir(parents=True)
    path.write_text("{malformed", encoding="utf-8")
    assert store.load_boba_tool_recovery(PROJECT_ID) is None


def test_export_is_sanitized_and_truthful(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    _, report = _report(tmp_path)
    store.save_boba_tool_recovery(report)
    exported = store.export_boba_tool_recovery(PROJECT_ID)
    privacy = exported["privacy"]
    assert privacy["private_absolute_paths_excluded"] is True
    assert privacy["unbounded_command_output_excluded"] is True
    assert privacy["network_access_used"] is False
    assert privacy["package_installation_used"] is False
    assert privacy["workflow_resume_used"] is False


def test_reset_removes_only_tool_recovery_metadata(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "work" / "boba")
    planner, _ = _eligible_planner()
    _, report = _report(tmp_path)
    store.save_boba_repair_planner(planner)
    store.save_boba_tool_recovery(report)
    workspace = tmp_path / "work" / "boba" / "tool_recovery" / "workspaces" / "keep"
    workspace.mkdir(parents=True)
    (workspace / "evidence.txt").write_text("keep", encoding="utf-8")
    assert store.reset_boba_tool_recovery(PROJECT_ID) is True
    assert store.load_boba_tool_recovery(PROJECT_ID) is None
    assert store.load_boba_repair_planner(PROJECT_ID) is not None
    assert (workspace / "evidence.txt").is_file()


def test_api_plan_get_export_and_reset(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    planner, handoff_id = _eligible_planner()
    store.save_boba_repair_planner(planner)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        planned = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/tool-recovery/plan",
            json={
                "selected_handoff_id": handoff_id,
                "failure_context": _context(),
                "run_health_checks": False,
            },
        )
        loaded = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/tool-recovery"
        )
        exported = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/tool-recovery/export"
        )
        reset = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/tool-recovery"
        )
    assert planned.status_code == 200, planned.text
    assert loaded.status_code == 200, loaded.text
    assert exported.status_code == 200, exported.text
    assert reset.status_code == 200, reset.text
    assert reset.json()["source_media_deleted"] is False
    assert reset.json()["accepted_outputs_deleted"] is False
    assert store.load_boba_repair_planner(PROJECT_ID) is not None


def test_api_health_check_never_executes_recovery(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    planner, handoff_id = _eligible_planner()
    store.save_boba_repair_planner(planner)
    asyncio.run(
        integration.generate_boba_tool_recovery_plan(
            PROJECT_ID,
            selected_handoff_id=handoff_id,
            failure_context=_context(),
            run_health_checks=False,
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/tool-recovery/health-check",
            json={"tool_ids": ["internal_json_validator"]},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["signal_usage"]["local_health_checks_executed"] is True
    assert payload["signal_usage"]["recovery_commands_executed"] is False


def test_api_execute_rejects_unapproved_request(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    planner, handoff_id = _eligible_planner()
    store.save_boba_repair_planner(planner)
    report = asyncio.run(
        integration.generate_boba_tool_recovery_plan(
            PROJECT_ID,
            selected_handoff_id=handoff_id,
            failure_context=_context(),
            run_health_checks=False,
        )
    )
    plan = report.recovery_plans[0]
    strategy = _strategy(report)
    approval = _approval(plan, strategy, approved=False)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/tool-recovery/execute-approved",
            json={
                "recovery_plan_id": plan.recovery_plan_id,
                "recovery_strategy_id": strategy.recovery_strategy_id,
                "approval": approval.model_dump(mode="json"),
            },
        )
    assert response.status_code >= 400


def test_handoff_defaults_never_apply_automatically() -> None:
    handoff = BobaToolRecoveryHandoffV1(
        handoff_id="handoff_defaults",
        recovery_case_id="tool_case_defaults",
        target_module="workflow_controller",
        reason="Review only.",
    )
    assert handoff.apply_automatically is False
    assert handoff.human_approval_required is True


def test_literal_safety_fields_reject_true() -> None:
    with pytest.raises(PydanticValidationError):
        BobaToolRecoverySignalUsageV1(source_media_modified=True)  # type: ignore[arg-type]


def test_command_contract_rejects_shell_true() -> None:
    with pytest.raises(PydanticValidationError):
        BobaRecoveryCommandV1(
            recovery_command_id="command_shell",
            tool_id="ffmpeg",
            executable="ffmpeg",
            arguments=["-version"],
            working_directory_scope="work/boba/tool_recovery/workspaces/run",
            category="health_check",
            shell_used=True,  # type: ignore[arg-type]
        )


def test_health_check_contract_rejects_network() -> None:
    with pytest.raises(PydanticValidationError):
        BobaToolHealthCheckV1(
            health_check_id="health_network",
            tool_id="ffmpeg",
            check_type="version",
            network_required=True,  # type: ignore[arg-type]
        )


def test_summary_requires_human_action_for_unapproved_plan(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    assert report.recovery_summary.required_human_actions


def test_repair_planner_is_not_mutated(tmp_path: Path) -> None:
    planner, handoff_id = _eligible_planner()
    before = planner.model_dump_json()
    _engine(tmp_path).plan(
        PROJECT_ID,
        planner,
        selected_handoff_id=handoff_id,
        failure_context=_context(),
        run_health_checks=False,
    )
    assert planner.model_dump_json() == before


def test_source_and_completed_output_signals_never_change(tmp_path: Path) -> None:
    _, report = _report(tmp_path, health=True)
    assert report.signal_usage.source_media_modified is False
    assert report.signal_usage.completed_outputs_modified is False
    assert report.signal_usage.workflow_resume_used is False
    assert report.signal_usage.code_modification_used is False


def test_no_optional_provider_is_installed_by_registry_build() -> None:
    _, tools = build_minimal_capability_registry()
    optional = {
        item.tool_id: item.installed
        for item in tools
        if item.tool_id in {"pyav", "opencv", "faster_whisper_local"}
    }
    assert set(optional) == {"pyav", "opencv", "faster_whisper_local"}
    assert all(
        "install" not in argument.lower()
        for tool in tools
        for argument in (tool.health_check.arguments if tool.health_check else [])
    )


# ---------------------------------------------------------------------------
# Recovery approval provenance.
#
# The parametrised mutation test above covers the binding fields, but an
# empirical sweep disabling each guard in verify_recovery_approval found these
# two provenance guards could be removed with the whole suite still green. An
# approval with no timestamp or no named approver is unattributable, so it
# cannot authorise a recovery.
# ---------------------------------------------------------------------------
def test_recovery_approval_requires_a_timestamp(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)

    errors = verify_recovery_approval(
        plan, strategy, _approval(plan, strategy, approved_at="")
    )
    assert "Recovery approval timestamp is missing." in errors


def test_recovery_approval_requires_a_named_approver(tmp_path: Path) -> None:
    _, report = _report(tmp_path)
    plan = report.recovery_plans[0]
    strategy = _strategy(report)

    assert "Recovery approver identity is missing." in verify_recovery_approval(
        plan, strategy, _approval(plan, strategy, approved_by="")
    )
    # Whitespace is not an identity either.
    assert "Recovery approver identity is missing." in verify_recovery_approval(
        plan, strategy, _approval(plan, strategy, approved_by="   ")
    )
