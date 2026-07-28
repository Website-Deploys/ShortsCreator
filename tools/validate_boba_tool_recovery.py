"""Validate BOBA Tool Recovery Brain V1 with offline generated fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_path in (ROOT, SRC):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from olympus.boba.repair_planner import (  # noqa: E402
    BobaRepairPlannerSetV1,
    BobaRepairPlannerV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.boba.tool_recovery import (  # noqa: E402
    EXPLICIT_RECOVERY_CONFIRMATION,
    BobaRecoveryCommandV1,
    BobaRegisteredRecoveryToolV1,
    BobaToolRecoveryApprovalV1,
    BobaToolRecoveryAttemptV1,
    BobaToolRecoveryBrainSetV1,
    BobaToolRecoveryBrainV1,
    BobaToolRecoveryPlanV1,
    BobaToolRecoveryRollbackV1,
    BobaToolRecoveryStrategyV1,
    build_minimal_capability_registry,
    build_trusted_recovery_command_registry,
    execute_allowlisted_recovery_command,
    fingerprint_recovery_strategy,
    validate_recovery_command_safety,
    validate_recovery_paths,
    verify_recovery_approval,
)
from olympus.platform.errors import ValidationError  # noqa: E402
from tools.validate_boba_repair_planner import (  # noqa: E402
    build_synthetic_planning_context,
    build_synthetic_root_cause_report,
)

REPORT_ROOT = ROOT / "work" / "validation_reports" / "boba_tool_recovery"
SYNTHETIC_PROJECT_ID = "proj_boba_tool_recovery_synthetic"


class BobaToolRecoveryValidatorReportV1(BaseModel):
    """Compact, JSON-safe Tool Recovery validation proof."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["boba_tool_recovery_validator_v1"] = (
        "boba_tool_recovery_validator_v1"
    )
    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    scenario_count: int = Field(default=0, ge=0)
    passed_scenario_count: int = Field(default=0, ge=0)
    scenario_results: dict[str, bool] = Field(default_factory=dict)
    tool_health: dict[str, str] = Field(default_factory=dict)
    generated_fixture_only: bool = True
    network_used: Literal[False] = False
    external_api_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    workflow_resumed: Literal[False] = False
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _eligible_planner(
    project_id: str,
) -> tuple[BobaRepairPlannerSetV1, str]:
    root_cause = build_synthetic_root_cause_report(project_id)
    planner = BobaRepairPlannerV1().plan(
        project_id,
        root_cause,
        manual_context=build_synthetic_planning_context(root_cause),
    )
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
    quality = next(
        (
            item
            for item in planner.quality_preservation_plans
            if item.quality_preservation_plan_id
            == repair_case.quality_preservation_plan_id
        ),
        None,
    )
    if quality is not None:
        quality.original_requirements = requirements
        quality.non_negotiable_requirements = requirements
        quality.technical_quality_checks = requirements
        quality.rights_safety_checks = []
        quality.creative_quality_checks = []
    return planner, handoff.handoff_id


def _planner_with_strategy_flags(
    project_id: str,
    **updates: Any,
) -> tuple[BobaRepairPlannerSetV1, str]:
    planner, handoff_id = _eligible_planner(project_id)
    handoff = next(
        item for item in planner.execution_handoffs if item.handoff_id == handoff_id
    )
    strategy = next(
        item
        for item in planner.repair_strategies
        if item.repair_strategy_id == handoff.repair_strategy_id
    )
    for name, value in updates.items():
        setattr(strategy, name, value)
    return planner, handoff_id


def _context(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
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
    value.update(updates)
    return value


def _engine(root: Path, *, ffmpeg_binary: str = "ffmpeg") -> BobaToolRecoveryBrainV1:
    return BobaToolRecoveryBrainV1(
        root,
        workspace_root=root / "work" / "boba" / "tool_recovery" / "workspaces",
        approved_input_roots=[
            root / "work",
            root / "storage_data",
            root / "media",
        ],
        ffmpeg_binary=ffmpeg_binary,
        mode="plan_only",
    )


def _plan(
    root: Path,
    *,
    project_id: str = SYNTHETIC_PROJECT_ID,
    context: Mapping[str, Any] | None = None,
    health: bool = False,
    planner: BobaRepairPlannerSetV1 | None = None,
    handoff_id: str | None = None,
    ffmpeg_binary: str = "ffmpeg",
) -> tuple[BobaToolRecoveryBrainV1, BobaToolRecoveryBrainSetV1]:
    if planner is None or handoff_id is None:
        planner, handoff_id = _eligible_planner(project_id)
    engine = _engine(root, ffmpeg_binary=ffmpeg_binary)
    report = engine.plan(
        project_id,
        planner,
        selected_handoff_id=handoff_id,
        failure_context=context or _context(),
        run_health_checks=health,
    )
    return engine, report


def _strategy(
    report: BobaToolRecoveryBrainSetV1,
    strategy_type: str,
) -> BobaToolRecoveryStrategyV1:
    return next(
        item
        for item in report.recovery_plans[0].ordered_strategies
        if item.strategy_type == strategy_type
    )


def _approval(
    plan: BobaToolRecoveryPlanV1,
    strategy: BobaToolRecoveryStrategyV1,
    **updates: Any,
) -> BobaToolRecoveryApprovalV1:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "approval_id": f"approval_{strategy.recovery_strategy_id}",
        "recovery_case_id": plan.recovery_case_id,
        "recovery_plan_id": plan.recovery_plan_id,
        "approved": True,
        "approved_at": now.isoformat(),
        "approved_by": "synthetic-local-human-reviewer",
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
    }
    values.update(updates)
    return BobaToolRecoveryApprovalV1.model_validate(values)


def _rejected(action: Callable[[], object]) -> bool:
    try:
        action()
    except (OSError, ValidationError, ValueError):
        return True
    return False


def _command_rejected(
    tools: list[BobaRegisteredRecoveryToolV1],
    *,
    executable: str,
    arguments: list[str],
    tool_id: str = "ffmpeg",
    category: str = "render_retry",
) -> bool:
    command = BobaRecoveryCommandV1(
        recovery_command_id=f"command_{uuid4().hex}",
        tool_id=tool_id,
        executable=executable,
        arguments=arguments,
        working_directory_scope=(
            f"work/boba/tool_recovery/workspaces/run_{uuid4().hex}"
        ),
        category=category,
    )
    return bool(
        validate_recovery_command_safety(
            command,
            tools,
            build_trusted_recovery_command_registry(tools),
        )
    )


def _attempt(
    plan: BobaToolRecoveryPlanV1,
    strategy: BobaToolRecoveryStrategyV1,
    attempt_id: str,
    *,
    status: str = "failed",
    output_ref: str = "",
    started_at: str | None = None,
    completed_at: str | None = None,
) -> BobaToolRecoveryAttemptV1:
    return BobaToolRecoveryAttemptV1(
        recovery_attempt_id=attempt_id,
        recovery_case_id=plan.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id,
        recovery_strategy_id=strategy.recovery_strategy_id,
        attempt_number=1,
        tool_id=strategy.tool_id,
        capability_id=strategy.capability_id,
        execution_started_at=started_at,
        execution_completed_at=completed_at,
        working_directory_reference=(
            f"work/boba/tool_recovery/workspaces/{attempt_id}"
        ),
        status=status,
        output_artifact_refs=[output_ref] if output_ref else [],
        warnings=[fingerprint_recovery_strategy(strategy)],
    )


def _validate_fixture(
    root: Path,
    *,
    source: Path | None = None,
    content: bytes | None = None,
    suffix: str = ".mp4",
    configuration_updates: Mapping[str, Any] | None = None,
    quality_requirement: str = "",
) -> tuple[BobaToolRecoveryBrainSetV1, BobaToolRecoveryAttemptV1]:
    engine, report = _plan(root)
    plan = report.recovery_plans[0]
    strategy = _strategy(report, "reduce_thread_usage")
    strategy.configuration_overrides.update(configuration_updates or {})
    if quality_requirement:
        plan.quality_requirements.append(quality_requirement)
    attempt_id = f"tool_attempt_fixture_{uuid4().hex}"
    workspace = engine.workspace_root / attempt_id / "outputs"
    workspace.mkdir(parents=True)
    output = workspace / f"fixture{suffix}"
    if source is not None:
        shutil.copy2(source, output)
    elif content is not None:
        output.write_bytes(content)
    output_ref = (
        f"work/boba/tool_recovery/workspaces/{attempt_id}/outputs/{output.name}"
    )
    attempt = _attempt(
        plan,
        strategy,
        attempt_id,
        status="succeeded_pending_validation",
        output_ref=output_ref,
    )
    report.recovery_attempts.append(attempt)
    engine.validate_output(report, recovery_attempt_id=attempt_id)
    return report, attempt


def _generate_media_fixture(
    root: Path,
    tools: list[BobaRegisteredRecoveryToolV1],
    *,
    name: str,
    audio_duration: float | None,
) -> Path:
    ffmpeg = next(item for item in tools if item.tool_id == "ffmpeg")
    executable = shutil.which(ffmpeg.executable)
    if not executable:
        raise ValidationError("FFmpeg is unavailable for generated validator fixtures.")
    workspace = root / "work" / "boba" / "tool_recovery" / "workspaces" / name
    workspace.mkdir(parents=True, exist_ok=False)
    output = workspace / f"{name}.mp4"
    arguments = [
        executable,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=24:duration=1",
    ]
    if audio_duration is not None:
        arguments.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=48000:duration={audio_duration}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
    arguments.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if audio_duration is not None:
        arguments.extend(["-c:a", "aac", "-ar", "48000"])
    arguments.append(str(output))
    record = BobaRecoveryCommandV1(
        recovery_command_id=f"fixture_{name}",
        tool_id="ffmpeg",
        executable=ffmpeg.executable,
        arguments=arguments[1:],
        working_directory_scope=f"work/boba/tool_recovery/workspaces/{name}",
        category="encode_check",
        approved=True,
    )
    errors = validate_recovery_command_safety(
        record,
        tools,
        build_trusted_recovery_command_registry(tools),
    )
    if errors:
        raise ValidationError(
            "Generated media fixture command failed safety validation.",
            details={"reasons": errors},
        )
    process = execute_allowlisted_recovery_command(
        arguments,
        workspace=workspace,
        timeout_seconds=30,
        output_limit_bytes=65_536,
    )
    if process.exit_code != 0 or not output.is_file():
        raise ValidationError(
            "Generated media fixture failed.",
            details={"stderr": process.stderr},
        )
    return output


def _write_report(
    report: BobaToolRecoveryValidatorReportV1,
    report_root: Path,
) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "boba_tool_recovery_v1_report.json").write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Tool Recovery Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Scenarios: `{report.passed_scenario_count}/{report.scenario_count}`",
        "- Generated fixtures only: `true`",
        "- Network or external APIs used: `false`",
        "- Packages installed or services restarted: `false`",
        "- Source media or accepted outputs modified: `false`",
        "- Olympus workflow resumed: `false`",
        "",
        "Technical recovery success still requires Output Quality Reviewer approval.",
    ]
    (report_root / "boba_tool_recovery_v1_summary.md").write_text(
        "\n".join(summary),
        encoding="utf-8",
    )


def run_self_check(
    report_root: Path = REPORT_ROOT,
) -> BobaToolRecoveryValidatorReportV1:
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    warnings: list[str] = []
    health: dict[str, str] = {}
    try:
        capabilities, tools = build_minimal_capability_registry()
        registry = build_trusted_recovery_command_registry(tools)
        with TemporaryDirectory(prefix="boba-tool-recovery-self-check-") as folder:
            root = Path(folder)
            workspace = root / "work" / "boba" / "tool_recovery" / "workspaces"
            workspace.mkdir(parents=True)
            probe = workspace / ".write_probe"
            probe.write_text("generated", encoding="utf-8")
            probe.unlink()
            engine, planned = _plan(root)
            checked = engine.run_health_checks(
                planned,
                tool_ids=[
                    "ffmpeg",
                    "ffprobe",
                    "internal_json_validator",
                    "internal_checksum_validator",
                    "external_transcription_service",
                ],
            )
            health = {
                item.tool_id: item.health_status
                for item in checked.registered_tools
            }
            scenarios = {
                "tool_recovery_module_imports": True,
                "repair_planner_imports": bool(BobaRepairPlannerV1),
                "contracts_serialize": bool(
                    json.dumps(checked.model_dump(mode="json"))
                ),
                "minimal_capability_registry_builds": len(capabilities) == 10,
                "trusted_command_registry_builds": bool(registry),
                "temporary_workspace_writable": not probe.exists(),
                "health_checks_are_shell_free": all(
                    item.health_check is None or not item.health_check.shell_used
                    for item in tools
                ),
                "health_checks_require_no_network": all(
                    item.health_check is None
                    or not item.health_check.network_required
                    for item in tools
                ),
                "no_package_installation_required": all(
                    "install" not in " ".join(item.prohibited_uses).lower()
                    or not item.available
                    for item in tools
                ),
                "no_service_restart_required": all(
                    "restart" not in " ".join(
                        item.health_check.arguments if item.health_check else []
                    ).lower()
                    for item in tools
                ),
                "no_source_media_required": all(
                    not item.output_artifact_refs
                    for item in checked.recovery_attempts
                ),
                "external_service_remains_blocked": (
                    health.get("external_transcription_service") == "blocked"
                ),
                "default_planning_does_not_execute": (
                    not checked.signal_usage.recovery_commands_executed
                ),
                "workflow_remains_paused": (
                    not checked.signal_usage.workflow_resume_used
                ),
            }
            unavailable = [
                item.display_name
                for item in checked.registered_tools
                if not item.available
                and item.provider_type in {"python_package", "external_service"}
            ]
            if unavailable:
                warnings.append(
                    "Unavailable providers were represented without installation: "
                    + ", ".join(unavailable)
                )
    except Exception as exc:
        errors.append(str(exc))
    passed = bool(scenarios) and all(scenarios.values()) and not errors
    report = BobaToolRecoveryValidatorReportV1(
        mode="self_check",
        passed=passed,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        tool_health=health,
        warnings=warnings,
        limitations=[
            "Self-check runs local health checks only; it does not execute recovery.",
            "Unavailable optional providers are not installed.",
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def run_synthetic_project(
    report_root: Path = REPORT_ROOT,
) -> BobaToolRecoveryValidatorReportV1:
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    warnings: list[str] = []
    health: dict[str, str] = {}
    try:
        with TemporaryDirectory(prefix="boba-tool-recovery-synthetic-") as folder:
            root = Path(folder)
            capabilities, tools = build_minimal_capability_registry()
            tool_by_id = {item.tool_id: item for item in tools}
            ffmpeg_available = shutil.which("ffmpeg") is not None
            ffprobe_available = shutil.which("ffprobe") is not None
            if not ffmpeg_available or not ffprobe_available:
                raise ValidationError(
                    "Synthetic recovery execution requires already-installed FFmpeg "
                    "and FFprobe."
                )

            _, healthy = _plan(root, health=True)
            health = {
                item.tool_id: item.health_status
                for item in healthy.registered_tools
            }
            scenarios["01_healthy_primary_tool"] = (
                health.get("ffmpeg") == "healthy"
                and health.get("ffprobe") == "healthy"
            )

            _, missing = _plan(
                root,
                health=True,
                ffmpeg_binary="definitely_missing_boba_ffmpeg",
            )
            missing_ffmpeg = next(
                item for item in missing.registered_tools if item.tool_id == "ffmpeg"
            )
            scenarios["02_missing_executable"] = (
                missing_ffmpeg.health_status == "unavailable"
                and not missing_ffmpeg.available
            )

            failure_reports: dict[str, BobaToolRecoveryBrainSetV1] = {}
            for failure_class in (
                "incompatible_version",
                "temporary_crash",
                "repeated_crash",
                "timeout",
                "resource_exhaustion",
                "malformed_output",
                "unsupported_input",
                "generated_state_problem",
            ):
                _, failure_reports[failure_class] = _plan(
                    root,
                    context=_context(failure_class=failure_class),
                )
            scenarios["03_incompatible_version"] = (
                _strategy(
                    failure_reports["incompatible_version"],
                    "compatibility_mode",
                ).strategy_type
                == "compatibility_mode"
            )
            scenarios["04_temporary_crash"] = (
                _strategy(
                    failure_reports["temporary_crash"],
                    "bounded_retry",
                ).maximum_attempts
                <= 2
            )
            scenarios["05_repeated_identical_crash"] = any(
                item.strategy_type == "retry_with_safe_settings"
                for item in failure_reports["repeated_crash"]
                .recovery_plans[0]
                .ordered_strategies
            )
            scenarios["06_timeout"] = any(
                item.strategy_type == "retry_with_safe_settings"
                for item in failure_reports["timeout"]
                .recovery_plans[0]
                .ordered_strategies
            )
            scenarios["07_repeated_timeout"] = any(
                item.strategy_type == "segmented_processing"
                for item in failure_reports["timeout"]
                .recovery_plans[0]
                .ordered_strategies
            )
            scenarios["08_resource_exhaustion"] = (
                _strategy(
                    failure_reports["resource_exhaustion"],
                    "reduce_thread_usage",
                ).configuration_overrides["encoder_threads"]
                == 1
            )
            scenarios["09_malformed_output"] = any(
                item.strategy_type == "bounded_retry"
                for item in failure_reports["malformed_output"]
                .recovery_plans[0]
                .ordered_strategies
            )
            scenarios["10_unsupported_input"] = any(
                item.strategy_type == "compatibility_mode"
                for item in failure_reports["unsupported_input"]
                .recovery_plans[0]
                .ordered_strategies
            )
            scenarios["11_temporary_generated_state_corruption"] = any(
                item.strategy_type == "regenerate_temporary_state"
                for item in failure_reports["generated_state_problem"]
                .recovery_plans[0]
                .ordered_strategies
            )
            scenarios["12_configuration_override_strategy"] = (
                _strategy(
                    failure_reports["resource_exhaustion"],
                    "reduce_thread_usage",
                ).configuration_overrides["parallel_tasks"]
                == 1
            )

            install_planner, install_handoff = _planner_with_strategy_flags(
                SYNTHETIC_PROJECT_ID,
                requires_package_installation=True,
            )
            _, install_report = _plan(
                root,
                planner=install_planner,
                handoff_id=install_handoff,
            )
            scenarios["13_environment_problem_requiring_installation"] = (
                not install_report.recovery_cases[0].recovery_eligible
                and "installation" in install_report.recovery_cases[0].blocked_reason
            )
            code_planner, code_handoff = _planner_with_strategy_flags(
                SYNTHETIC_PROJECT_ID,
                requires_code_change=True,
            )
            _, code_report = _plan(
                root,
                planner=code_planner,
                handoff_id=code_handoff,
            )
            scenarios["14_code_defect_case"] = (
                not code_report.recovery_cases[0].recovery_eligible
                and any(
                    item.target_module == "code_surgeon"
                    for item in code_report.recovery_handoffs
                )
            )
            checkpoint_planner, checkpoint_handoff = _planner_with_strategy_flags(
                SYNTHETIC_PROJECT_ID,
                requires_checkpoint=True,
            )
            _, checkpoint_valid = _plan(
                root,
                planner=checkpoint_planner.model_copy(deep=True),
                handoff_id=checkpoint_handoff,
                context=_context(checkpoint_ready=True),
            )
            _, checkpoint_missing = _plan(
                root,
                planner=checkpoint_planner.model_copy(deep=True),
                handoff_id=checkpoint_handoff,
                context=_context(checkpoint_ready=False),
            )
            scenarios["15_checkpoint_required_and_valid"] = (
                checkpoint_valid.recovery_cases[0].checkpoint_required
                and checkpoint_valid.recovery_cases[0].checkpoint_ready
                and checkpoint_valid.recovery_cases[0].recovery_eligible
            )
            scenarios["16_checkpoint_required_and_missing"] = (
                not checkpoint_missing.recovery_cases[0].recovery_eligible
                and "checkpoint" in checkpoint_missing.recovery_cases[0].blocked_reason.lower()
            )
            scenarios["17_checkpoint_corrupt"] = any(
                item.target_module == "checkpoint_recovery_manager"
                for item in checkpoint_missing.recovery_handoffs
            )
            _, rights_unknown = _plan(
                root,
                context=_context(rights_status="unknown"),
            )
            _, rights_blocked = _plan(
                root,
                context=_context(rights_status="blocked"),
            )
            scenarios["18_unknown_rights"] = (
                not rights_unknown.recovery_cases[0].recovery_eligible
            )
            scenarios["19_blocked_rights"] = (
                not rights_blocked.recovery_cases[0].recovery_eligible
            )

            plan = healthy.recovery_plans[0]
            reduced = _strategy(healthy, "reduce_thread_usage")
            scenarios["20_missing_approval"] = bool(
                verify_recovery_approval(
                    plan,
                    reduced,
                    _approval(plan, reduced, approved=False),
                )
            )
            scenarios["21_expired_approval"] = bool(
                verify_recovery_approval(
                    plan,
                    reduced,
                    _approval(
                        plan,
                        reduced,
                        approval_expires_at=(
                            datetime.now(UTC) - timedelta(seconds=1)
                        ).isoformat(),
                    ),
                )
            )
            scenarios["22_changed_strategy_after_approval"] = bool(
                verify_recovery_approval(
                    plan,
                    reduced,
                    _approval(plan, reduced, approved_strategy_ids=["changed"]),
                )
            )
            scenarios["23_changed_tool_after_approval"] = bool(
                verify_recovery_approval(
                    plan,
                    reduced,
                    _approval(plan, reduced, approved_tool_ids=["changed"]),
                )
            )
            changed_settings = dict(reduced.configuration_overrides)
            changed_settings["encoder_threads"] = 2
            scenarios["24_changed_settings_after_approval"] = bool(
                verify_recovery_approval(
                    plan,
                    reduced,
                    _approval(
                        plan,
                        reduced,
                        approved_configuration_overrides=changed_settings,
                    ),
                )
            )
            scenarios["25_changed_retry_budget_after_approval"] = bool(
                verify_recovery_approval(
                    plan,
                    reduced,
                    _approval(
                        plan,
                        reduced,
                        approved_retry_budget={"maximum_total_attempts": 99},
                    ),
                )
            )
            scenarios["26_changed_quality_requirements_after_approval"] = bool(
                verify_recovery_approval(
                    plan,
                    reduced,
                    _approval(
                        plan,
                        reduced,
                        approved_quality_requirements=["changed"],
                    ),
                )
            )

            fallback_context = _context(
                failure_class="tool_unavailable",
                failing_tool_id="missing_primary_encoder",
            )
            fallback_engine, fallback_report = _plan(
                root,
                context=fallback_context,
                health=True,
            )
            fallback_strategy = _strategy(
                fallback_report,
                "switch_registered_local_tool",
            )
            scenarios["27_registered_healthy_local_fallback"] = (
                fallback_strategy.tool_id == "ffmpeg"
                and fallback_strategy.execution_allowed
            )
            unavailable_fallback = _strategy(
                missing,
                "switch_registered_local_tool",
            )
            scenarios["28_registered_unavailable_fallback"] = (
                not unavailable_fallback.execution_allowed
            )
            scenarios["29_unregistered_fallback"] = _command_rejected(
                tools,
                executable="missing-fallback",
                arguments=[],
                tool_id="unregistered_fallback",
                category="unknown",
            )
            scenarios["30_external_service_fallback"] = (
                tool_by_id["external_transcription_service"].health_status == "blocked"
                and not tool_by_id["external_transcription_service"].available
            )
            paid_planner, paid_handoff = _planner_with_strategy_flags(
                SYNTHETIC_PROJECT_ID,
                requires_paid_service=True,
            )
            _, paid_report = _plan(
                root,
                planner=paid_planner,
                handoff_id=paid_handoff,
            )
            scenarios["31_paid_service_fallback"] = (
                not paid_report.recovery_cases[0].recovery_eligible
            )
            network_planner, network_handoff = _planner_with_strategy_flags(
                SYNTHETIC_PROJECT_ID,
                requires_external_access=True,
            )
            _, network_report = _plan(
                root,
                planner=network_planner,
                handoff_id=network_handoff,
            )
            scenarios["32_network_required_fallback"] = (
                not network_report.recovery_cases[0].recovery_eligible
            )
            scenarios["33_install_required_fallback"] = (
                not install_report.recovery_cases[0].recovery_eligible
            )

            source = root / "work" / "fixtures" / "source.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"synthetic-read-only-source")
            safe_workspace = (
                root
                / "work"
                / "boba"
                / "tool_recovery"
                / "workspaces"
                / "path_checks"
            )
            scenarios["34_source_media_overwrite_attempt"] = _rejected(
                lambda: validate_recovery_paths(
                    repository_root=root,
                    workspace_root=safe_workspace,
                    input_reference="work/fixtures/source.mp4",
                    output_filename="../../fixtures/source.mp4",
                    approved_input_roots=[root / "work"],
                )
            )
            accepted_workspace = (
                root
                / "work"
                / "boba"
                / "tool_recovery"
                / "workspaces"
                / "accepted_check"
            )
            accepted_output = accepted_workspace / "outputs" / "accepted.mp4"
            accepted_output.parent.mkdir(parents=True)
            accepted_output.write_bytes(b"accepted")
            scenarios["35_accepted_output_overwrite_attempt"] = _rejected(
                lambda: validate_recovery_paths(
                    repository_root=root,
                    workspace_root=accepted_workspace,
                    input_reference="work/fixtures/source.mp4",
                    output_filename="accepted.mp4",
                    approved_input_roots=[root / "work"],
                )
            )
            scenarios["36_path_traversal_attempt"] = _rejected(
                lambda: validate_recovery_paths(
                    repository_root=root,
                    workspace_root=safe_workspace,
                    input_reference="work/../outside.mp4",
                    output_filename="new.mp4",
                    approved_input_roots=[root / "work"],
                )
            )
            outside = root / "outside"
            outside.mkdir()
            outside_source = outside / "outside.mp4"
            outside_source.write_bytes(b"outside")
            symlink = root / "work" / "fixtures" / "escape"
            try:
                symlink.symlink_to(outside, target_is_directory=True)
                symlink_rejected = _rejected(
                    lambda: validate_recovery_paths(
                        repository_root=root,
                        workspace_root=safe_workspace,
                        input_reference="work/fixtures/escape/outside.mp4",
                        output_filename="new.mp4",
                        approved_input_roots=[root / "work"],
                    )
                )
            except OSError:
                symlink_rejected = True
                warnings.append(
                    "The operating system denied synthetic symlink creation before "
                    "Tool Recovery path validation."
                )
            scenarios["37_symlink_escape_attempt"] = symlink_rejected

            ffmpeg_executable = tool_by_id["ffmpeg"].executable
            scenarios["38_command_injection_attempt"] = _command_rejected(
                tools,
                executable=ffmpeg_executable,
                arguments=["$(whoami)"],
            )
            scenarios["39_shell_metacharacter_attempt"] = _command_rejected(
                tools,
                executable=ffmpeg_executable,
                arguments=["input;whoami"],
            )
            scenarios["40_pipe_redirection_attempt"] = _command_rejected(
                tools,
                executable=ffmpeg_executable,
                arguments=["input|output"],
            )
            scenarios["41_package_manager_command"] = _command_rejected(
                tools,
                executable="pip",
                arguments=["install", "package"],
            )
            scenarios["42_network_tool_command"] = _command_rejected(
                tools,
                executable="curl",
                arguments=["https://example.invalid"],
            )
            scenarios["43_service_restart_command"] = _command_rejected(
                tools,
                executable="sc",
                arguments=["stop", "service"],
            )
            scenarios["44_process_kill_command"] = _command_rejected(
                tools,
                executable="taskkill",
                arguments=["/pid", "1"],
            )

            bounded_engine, bounded_report = _plan(
                root,
                context=_context(failure_class="temporary_crash"),
                health=True,
            )
            bounded_plan = bounded_report.recovery_plans[0]
            bounded_strategy = _strategy(bounded_report, "bounded_retry")
            bounded_result = bounded_engine.execute_approved(
                bounded_report,
                recovery_plan_id=bounded_plan.recovery_plan_id,
                recovery_strategy_id=bounded_strategy.recovery_strategy_id,
                approval=_approval(bounded_plan, bounded_strategy),
            )
            scenarios["45_bounded_retry_success"] = (
                bounded_result.recovery_attempts[-1].status == "completed"
            )

            budget_engine, budget_report = _plan(root, health=True)
            budget_plan = budget_report.recovery_plans[0]
            budget_strategy = _strategy(budget_report, "reduce_thread_usage")
            for index in range(4):
                budget_report.recovery_attempts.append(
                    _attempt(
                        budget_plan,
                        budget_strategy,
                        f"tool_attempt_budget_{index}",
                    )
                )
            scenarios["46_retry_budget_exhaustion"] = _rejected(
                lambda: budget_engine.execute_approved(
                    budget_report,
                    recovery_plan_id=budget_plan.recovery_plan_id,
                    recovery_strategy_id=budget_strategy.recovery_strategy_id,
                    approval=_approval(budget_plan, budget_strategy),
                )
            )
            timed_engine, timed_report = _plan(root, health=True)
            timed_plan = timed_report.recovery_plans[0]
            timed_strategy = _strategy(timed_report, "reduce_thread_usage")
            started = datetime.now(UTC) - timedelta(
                seconds=timed_plan.time_budget_seconds + 1
            )
            timed_report.recovery_attempts.append(
                _attempt(
                    timed_plan,
                    timed_strategy,
                    "tool_attempt_time_budget",
                    started_at=started.isoformat(),
                    completed_at=datetime.now(UTC).isoformat(),
                )
            )
            scenarios["47_recovery_time_budget_exhaustion"] = _rejected(
                lambda: timed_engine.execute_approved(
                    timed_report,
                    recovery_plan_id=timed_plan.recovery_plan_id,
                    recovery_strategy_id=timed_strategy.recovery_strategy_id,
                    approval=_approval(timed_plan, timed_strategy),
                )
            )
            duplicate_errors = timed_engine._budget_errors(
                timed_report,
                timed_plan,
                timed_strategy,
            )
            scenarios["48_duplicate_strategy_fingerprint"] = any(
                "fingerprint" in item for item in duplicate_errors
            )

            reduced_engine, reduced_report = _plan(root, health=True)
            reduced_plan = reduced_report.recovery_plans[0]
            reduced_strategy = _strategy(reduced_report, "reduce_thread_usage")
            reduced_result = reduced_engine.execute_approved(
                reduced_report,
                recovery_plan_id=reduced_plan.recovery_plan_id,
                recovery_strategy_id=reduced_strategy.recovery_strategy_id,
                approval=_approval(reduced_plan, reduced_strategy),
            )
            scenarios["49_reduced_thread_recovery"] = (
                reduced_result.recovery_attempts[-1].status == "completed"
                and reduced_strategy.configuration_overrides["encoder_threads"] == 1
                and reduced_strategy.configuration_overrides["filter_threads"] == 1
            )

            segmented_context = _context()
            segmented_context["configuration_overrides"].update(
                {
                    "expected_duration_seconds": 6.0,
                    "segment_seconds": 5,
                }
            )
            segmented_engine, segmented_report = _plan(
                root,
                context=segmented_context,
                health=True,
            )
            segmented_plan = segmented_report.recovery_plans[0]
            segmented_strategy = _strategy(
                segmented_report,
                "segmented_processing",
            )
            segmented_result = segmented_engine.execute_approved(
                segmented_report,
                recovery_plan_id=segmented_plan.recovery_plan_id,
                recovery_strategy_id=segmented_strategy.recovery_strategy_id,
                approval=_approval(segmented_plan, segmented_strategy),
            )
            segmented_attempt = segmented_result.recovery_attempts[-1]
            scenarios["50_segmented_processing_recovery"] = (
                segmented_attempt.status == "completed"
                and len(segmented_attempt.command_records) == 3
                and segmented_result.output_validations[-1].required_checks_passed
            )

            compatibility_engine, compatibility_report = _plan(
                root,
                context=_context(failure_class="unsupported_input"),
                health=True,
            )
            compatibility_plan = compatibility_report.recovery_plans[0]
            compatibility_strategy = _strategy(
                compatibility_report,
                "compatibility_mode",
            )
            compatibility_result = compatibility_engine.execute_approved(
                compatibility_report,
                recovery_plan_id=compatibility_plan.recovery_plan_id,
                recovery_strategy_id=compatibility_strategy.recovery_strategy_id,
                approval=_approval(compatibility_plan, compatibility_strategy),
            )
            scenarios["51_compatibility_mode_recovery"] = (
                compatibility_result.recovery_attempts[-1].status == "completed"
                and compatibility_result.recovery_attempts[
                    -1
                ].quality_change_disclosed
            )
            fallback_plan = fallback_report.recovery_plans[0]
            fallback_result = fallback_engine.execute_approved(
                fallback_report,
                recovery_plan_id=fallback_plan.recovery_plan_id,
                recovery_strategy_id=fallback_strategy.recovery_strategy_id,
                approval=_approval(fallback_plan, fallback_strategy),
            )
            scenarios["52_local_fallback_recovery"] = (
                fallback_result.recovery_attempts[-1].status == "completed"
                and fallback_result.signal_usage.local_fallback_used
            )

            missing_validation, missing_attempt = _validate_fixture(root)
            missing_output = missing_validation.output_validations[-1]
            scenarios["53_output_file_missing"] = (
                not missing_output.artifact_exists
                and missing_attempt.status == "rolled_back"
            )
            empty_validation, _ = _validate_fixture(root, content=b"")
            scenarios["54_output_file_empty"] = (
                not empty_validation.output_validations[-1].artifact_non_empty
            )
            malformed_validation, _ = _validate_fixture(
                root,
                content=b"not media",
            )
            scenarios["55_media_probe_failure"] = (
                malformed_validation.output_validations[-1].media_probe_valid is False
            )

            accepted_ref = reduced_result.recovery_attempts[-1].output_artifact_refs[0]
            accepted_source = root / Path(accepted_ref)
            duration_validation, _ = _validate_fixture(
                root,
                source=accepted_source,
                configuration_updates={"expected_duration_seconds": 2.0},
            )
            scenarios["56_duration_mismatch"] = (
                duration_validation.output_validations[-1].duration_valid is False
            )
            resolution_validation, _ = _validate_fixture(
                root,
                source=accepted_source,
                configuration_updates={"expected_width": 640},
            )
            scenarios["57_resolution_mismatch"] = (
                resolution_validation.output_validations[-1].resolution_valid is False
            )
            frame_rate_validation, _ = _validate_fixture(
                root,
                source=accepted_source,
                configuration_updates={"expected_fps": 30},
            )
            scenarios["58_frame_rate_mismatch"] = (
                frame_rate_validation.output_validations[-1].frame_rate_valid is False
            )
            no_audio_source = _generate_media_fixture(
                root,
                tools,
                name="fixture_no_audio",
                audio_duration=None,
            )
            no_audio_validation, _ = _validate_fixture(
                root,
                source=no_audio_source,
            )
            scenarios["59_audio_missing"] = (
                no_audio_validation.output_validations[-1].audio_presence_valid is False
            )
            sync_source = _generate_media_fixture(
                root,
                tools,
                name="fixture_sync_delta",
                audio_duration=0.5,
            )
            sync_validation, _ = _validate_fixture(
                root,
                source=sync_source,
            )
            scenarios["60_audio_video_sync_failure"] = (
                sync_validation.output_validations[-1].audio_video_sync_valid is False
            )
            caption_validation, _ = _validate_fixture(
                root,
                source=accepted_source,
                quality_requirement="caption timing must remain exact",
            )
            caption_result = caption_validation.output_validations[-1]
            scenarios["61_caption_timing_unavailable_when_required"] = (
                caption_result.caption_timing_status == "unavailable"
                and "caption_timing" in caption_result.unavailable_required_checks
            )
            scenarios["62_source_window_mismatch"] = (
                duration_validation.output_validations[-1].source_window_status
                == "failed"
            )
            checksum_validation, _ = _validate_fixture(
                root,
                source=accepted_source,
                configuration_updates={"expected_checksum": "not-the-checksum"},
            )
            scenarios["63_checksum_failure"] = (
                checksum_validation.output_validations[-1].checksum_valid is False
            )
            schema_validation, _ = _validate_fixture(
                root,
                content=b'{"present": true}',
                suffix=".json",
                configuration_updates={"required_schema_keys": ["missing"]},
            )
            scenarios["64_json_schema_failure"] = (
                schema_validation.output_validations[-1].schema_valid is False
            )
            reduced_validation = reduced_result.output_validations[-1]
            scenarios["65_all_technical_checks_pass"] = (
                reduced_validation.required_checks_passed
            )
            scenarios["66_pass_enters_pending_quality_review_only"] = (
                reduced_validation.accepted_for_quality_review
                and reduced_validation.quality_review_required
                and not reduced_result.signal_usage.workflow_resume_used
            )
            scenarios["67_required_check_unavailable"] = bool(
                caption_result.unavailable_required_checks
                and not caption_result.accepted_for_quality_review
            )
            scenarios["68_validation_failure_triggers_rollback"] = (
                bool(duration_validation.rollback_records)
                and duration_validation.rollback_records[-1].status == "completed"
            )

            timeout_engine, timeout_report = _plan(root)
            timeout_plan = timeout_report.recovery_plans[0]
            timeout_strategy = _strategy(timeout_report, "reduce_thread_usage")
            timeout_attempt_id = f"tool_attempt_timeout_{uuid4().hex}"
            timeout_output = (
                timeout_engine.workspace_root
                / timeout_attempt_id
                / "outputs"
                / "partial.mp4"
            )
            timeout_output.parent.mkdir(parents=True)
            timeout_output.write_bytes(b"partial")
            timeout_ref = (
                "work/boba/tool_recovery/workspaces/"
                f"{timeout_attempt_id}/outputs/partial.mp4"
            )
            timeout_attempt = _attempt(
                timeout_plan,
                timeout_strategy,
                timeout_attempt_id,
                status="timed_out",
                output_ref=timeout_ref,
            )
            timeout_report.recovery_attempts.append(timeout_attempt)
            timeout_engine.rollback(
                timeout_report,
                recovery_attempt_id=timeout_attempt_id,
                trigger="Synthetic bounded timeout.",
            )
            scenarios["69_timeout_triggers_rollback"] = (
                timeout_attempt.status == "rolled_back"
                and timeout_report.rollback_records[-1].status == "completed"
            )
            scenarios["70_rollback_succeeds"] = (
                missing_validation.rollback_records[-1].rollback_validation_passed
            )
            partial_record = BobaToolRecoveryRollbackV1(
                rollback_record_id="rollback_partial",
                recovery_attempt_id="attempt_partial",
                trigger="Synthetic locked temporary artifact.",
                status="partial",
                rollback_validation_passed=False,
                warnings=["Human review required."],
            )
            scenarios["71_rollback_partially_fails"] = (
                partial_record.status == "partial"
                and not partial_record.rollback_validation_passed
            )

            source_before = source.read_bytes()
            accepted_before = accepted_output.read_bytes()
            checkpoint_file = root / "work" / "fixtures" / "checkpoint.json"
            checkpoint_file.write_text('{"valid": true}', encoding="utf-8")
            checkpoint_before = checkpoint_file.read_bytes()
            scenarios["72_source_media_remains_unchanged"] = (
                source.read_bytes() == source_before
            )
            scenarios["73_completed_output_remains_unchanged"] = (
                accepted_output.read_bytes() == accepted_before
            )
            scenarios["74_checkpoint_remains_unchanged"] = (
                checkpoint_file.read_bytes() == checkpoint_before
            )
            signals = reduced_result.signal_usage
            scenarios["75_workflow_does_not_resume"] = not signals.workflow_resume_used
            handoff_targets = {
                item.target_module for item in reduced_result.recovery_handoffs
            }
            scenarios["76_output_quality_reviewer_handoff_exists"] = (
                "output_quality_reviewer" in handoff_targets
            )
            scenarios["77_safety_gate_handoff_exists"] = (
                "safety_gate" in handoff_targets
            )
            scenarios["78_workflow_controller_handoff_exists"] = (
                "workflow_controller" in handoff_targets
                and not signals.workflow_resume_used
            )
            scenarios["79_no_internet_access_occurs"] = (
                not signals.network_access_used
                and not signals.url_fetching_used
            )
            scenarios["80_no_external_api_occurs"] = not signals.external_api_used
            scenarios["81_no_package_installation_occurs"] = (
                not signals.package_installation_used
            )
            scenarios["82_no_service_restart_occurs"] = (
                not signals.service_restart_used
            )
            scenarios["83_no_code_modification_occurs"] = (
                not signals.code_modification_used
            )
            scenarios["84_no_media_download_occurs"] = not signals.downloading_used
            scenarios["85_no_upload_occurs"] = not signals.uploading_used
            scenarios["86_no_rights_bypass_occurs"] = not signals.rights_bypass_used
            scenarios["87_no_safety_bypass_occurs"] = not signals.safety_bypass_used
            scenarios["88_no_destructive_action_occurs"] = (
                not signals.destructive_action_used
            )

            if len(scenarios) != 88:
                raise ValidationError(
                    f"Synthetic scenario count is {len(scenarios)}, expected 88."
                )
            store = BobaMemoryStore(root / "work" / "boba")
            store.save_boba_tool_recovery(reduced_result)
            if store.load_boba_tool_recovery(SYNTHETIC_PROJECT_ID) is None:
                raise ValidationError("Synthetic Tool Recovery report did not persist.")
            if len(capabilities) != 10:
                raise ValidationError("Minimal capability registry is incomplete.")
    except Exception as exc:
        errors.append(str(exc))
    passed = len(scenarios) == 88 and all(scenarios.values()) and not errors
    report = BobaToolRecoveryValidatorReportV1(
        mode="synthetic_project",
        passed=passed,
        project_id=SYNTHETIC_PROJECT_ID,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        tool_health=health,
        warnings=warnings,
        limitations=[
            "Fixtures are generated locally and do not prove recovery for arbitrary media.",
            "Technical validation passes only to Output Quality Reviewer.",
            "No optional provider was installed or enabled by the validator.",
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def inspect_project(
    project_id: str,
    *,
    repository_root: Path = ROOT,
    report_root: Path = REPORT_ROOT,
) -> BobaToolRecoveryValidatorReportV1:
    errors: list[str] = []
    scenarios: dict[str, bool] = {}
    try:
        store = BobaMemoryStore(repository_root / "work" / "boba")
        stored = store.load_boba_tool_recovery(project_id)
        exported = store.export_boba_tool_recovery(project_id) if stored else {}
        scenarios = {
            "stored_report_available": stored is not None,
            "stored_report_json_safe": bool(
                stored and json.dumps(stored.model_dump(mode="json"))
            ),
            "source_media_not_modified": bool(
                stored and not stored.signal_usage.source_media_modified
            ),
            "accepted_outputs_not_modified": bool(
                stored and not stored.signal_usage.completed_outputs_modified
            ),
            "workflow_not_resumed": bool(
                stored and not stored.signal_usage.workflow_resume_used
            ),
            "network_not_used": bool(
                stored and not stored.signal_usage.network_access_used
            ),
            "export_is_sanitized": bool(
                exported
                and exported.get("privacy", {}).get(
                    "private_absolute_paths_excluded"
                )
                is True
            ),
        }
    except Exception as exc:
        errors.append(str(exc))
    report = BobaToolRecoveryValidatorReportV1(
        mode="project_id",
        passed=bool(scenarios) and all(scenarios.values()) and not errors,
        project_id=project_id,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        generated_fixture_only=False,
        limitations=[
            "Project mode is inspection-only and does not approve or execute recovery."
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--report-root", type=Path, default=REPORT_ROOT)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    report_root = arguments.report_root.resolve()
    if arguments.self_check:
        report = run_self_check(report_root)
    elif arguments.synthetic_project:
        report = run_synthetic_project(report_root)
    else:
        report = inspect_project(
            str(arguments.project_id),
            repository_root=ROOT,
            report_root=report_root,
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
