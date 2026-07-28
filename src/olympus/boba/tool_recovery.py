"""Approval-bound recovery of registered local tool failures.

Tool Recovery Brain consumes persisted Repair Planner handoffs. It can inspect
registered local tools and execute only deterministic, bounded recovery profiles
inside an isolated generated workspace. It never installs software, changes
source code, mutates source media or accepted outputs, or resumes a workflow.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.repair_planner import (
    BobaQualityPreservationPlanV1,
    BobaRepairApprovalGateV1,
    BobaRepairCheckpointPlanV1,
    BobaRepairExecutionHandoffV1,
    BobaRepairPlannerSetV1,
    BobaRepairPlanningCaseV1,
    BobaRepairRollbackPlanV1,
    BobaRepairStrategyV1,
    BobaRepairValidationPlanV1,
)
from olympus.platform.errors import ValidationError

BobaToolFailureClassV1 = Literal[
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
    "environment_problem",
    "permission_problem",
    "generated_state_problem",
    "checkpoint_problem",
    "external_service_unavailable",
    "unknown",
]
BobaToolProviderTypeV1 = Literal[
    "executable",
    "python_package",
    "internal_module",
    "external_service",
    "unknown",
]
BobaToolHealthStatusV1 = Literal[
    "healthy",
    "degraded",
    "unavailable",
    "incompatible",
    "unverified",
    "blocked",
    "unknown",
]
BobaToolHealthCheckTypeV1 = Literal[
    "executable_exists",
    "version",
    "import_available",
    "bounded_smoke_test",
    "internal_health",
    "configuration_presence",
    "unknown",
]
BobaToolHealthResultStatusV1 = Literal[
    "healthy",
    "degraded",
    "unavailable",
    "timed_out",
    "blocked",
    "incompatible",
    "unknown",
]
BobaToolRecoveryApprovalStatusV1 = Literal[
    "planning_only",
    "awaiting_approval",
    "approved",
    "rejected",
    "expired",
    "invalidated",
    "unknown",
]
BobaToolRecoveryExecutionStatusV1 = Literal[
    "not_started",
    "health_check_only",
    "ready",
    "running",
    "recovered_pending_validation",
    "validation_failed",
    "recovery_failed",
    "rolled_back",
    "completed",
    "blocked",
    "unknown",
]
BobaToolRecoveryStrategyTypeV1 = Literal[
    "health_check",
    "bounded_retry",
    "retry_with_safe_settings",
    "reduce_thread_usage",
    "reduce_memory_pressure",
    "segmented_processing",
    "compatibility_mode",
    "regenerate_temporary_state",
    "switch_registered_local_tool",
    "collect_more_evidence",
    "stop_processing",
    "human_manual_action",
    "unknown",
]
BobaToolRecoveryAttemptStatusV1 = Literal[
    "not_started",
    "running",
    "succeeded_pending_validation",
    "failed",
    "timed_out",
    "blocked",
    "rolled_back",
    "rejected",
    "completed",
    "unknown",
]
BobaRecoveryCommandCategoryV1 = Literal[
    "health_check",
    "media_probe",
    "render_retry",
    "segmented_render",
    "audio_extract",
    "frame_extract",
    "decode_check",
    "encode_check",
    "artifact_validate",
    "checksum",
    "temporary_cleanup",
    "unknown",
]
BobaRecoveryCheckStatusV1 = Literal[
    "passed",
    "failed",
    "not_required",
    "unavailable",
    "unknown",
]
BobaToolRecoveryRollbackStatusV1 = Literal[
    "not_required",
    "completed",
    "partial",
    "failed",
    "blocked",
    "unknown",
]
BobaToolRecoveryHandoffTargetV1 = Literal[
    "output_quality_reviewer",
    "workflow_controller",
    "safety_gate",
    "checkpoint_recovery_manager",
    "repair_planner",
    "root_cause_analyzer",
    "code_surgeon",
    "validator_runner",
    "tool_registry_fallback_router",
    "human_operator",
    "unknown",
]
BobaToolRecoveryPriorityV1 = Literal["low", "medium", "high", "urgent"]
BobaToolRecoveryModeV1 = Literal[
    "plan_and_health_check",
    "plan_only",
    "health_check_only",
]
JsonObject: TypeAlias = dict[str, Any]

EXPLICIT_RECOVERY_CONFIRMATION = (
    "I approve this exact recovery strategy, registered tool, settings, "
    "retry budget, time budget, checkpoint reference, and quality requirements."
)
DEFAULT_MAX_ATTEMPTS_PER_STRATEGY = 2
DEFAULT_MAX_TOTAL_ATTEMPTS = 4
DEFAULT_MAX_RECOVERY_SECONDS = 1_800
DEFAULT_MAX_ATTEMPT_SECONDS = 900
DEFAULT_OUTPUT_LIMIT_BYTES = 65_536

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET = re.compile(
    r"(?:secret|token|password|credential|cookie|authorization|api[_-]?key)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?i)\b(?:bearer\s+[A-Za-z0-9._~-]+|"
    r"(?:secret|token|password|api[_-]?key)\s*[=:]\s*\S+)"
)
_PRIVATE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"']+|\\\\[^\\\s]+\\[^\s\"']+|"
    r"/(?:home|Users|root|private|tmp)/[^\s\"']+)"
)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_SHELL_TOKEN = re.compile(r"(?:\|\||&&|[|><;`]|\$\(|\r|\n)")
_FORBIDDEN_EXECUTABLES = {
    "bash",
    "bash.exe",
    "cmd",
    "cmd.exe",
    "curl",
    "curl.exe",
    "git",
    "git.exe",
    "npm",
    "npm.cmd",
    "pip",
    "pip.exe",
    "pip3",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "python",
    "python.exe",
    "python3",
    "sc",
    "sc.exe",
    "taskkill",
    "taskkill.exe",
    "wget",
    "wget.exe",
}
_FORBIDDEN_ARGUMENTS = {
    "-c",
    "/c",
    "-command",
    "--command",
    "install",
    "uninstall",
    "upgrade",
    "download",
    "upload",
    "push",
    "pull",
    "clone",
    "kill",
    "taskkill",
    "start-service",
    "stop-service",
    "restart-service",
}
_NETWORK_PREFIXES = (
    "http:",
    "https:",
    "ftp:",
    "ftps:",
    "rtmp:",
    "rtmps:",
    "s3:",
    "tcp:",
    "tls:",
    "udp:",
)
_SUPPORTED_FAILURE_CLASSES: set[str] = {
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
}
_EXECUTION_STRATEGIES: set[str] = {
    "bounded_retry",
    "retry_with_safe_settings",
    "reduce_thread_usage",
    "reduce_memory_pressure",
    "segmented_processing",
    "compatibility_mode",
    "switch_registered_local_tool",
}
_ALLOWED_CONFIGURATION_KEYS = {
    "audio_bitrate_kbps",
    "command_category",
    "encoder_preset",
    "encoder_threads",
    "expected_checksum",
    "expected_duration_seconds",
    "expected_fps",
    "expected_height",
    "expected_width",
    "filter_threads",
    "input_artifact_ref",
    "output_filename",
    "parallel_tasks",
    "protected_output_refs",
    "require_audio",
    "required_schema_keys",
    "segment_seconds",
    "source_window_end_seconds",
    "source_window_start_seconds",
    "timeout_seconds",
    "video_bitrate_kbps",
}
_FFMPEG_ALLOWED_OPTIONS = {
    "-ac",
    "-ar",
    "-b:a",
    "-b:v",
    "-c",
    "-c:a",
    "-c:v",
    "-f",
    "-filter_complex_threads",
    "-filter_threads",
    "-frames:v",
    "-hide_banner",
    "-i",
    "-loglevel",
    "-map",
    "-movflags",
    "-nostats",
    "-pix_fmt",
    "-preset",
    "-r",
    "-ss",
    "-t",
    "-threads",
    "-vf",
    "-vn",
    "-y",
}
_FFPROBE_ALLOWED_OPTIONS = {
    "-of",
    "-show_entries",
    "-v",
}


class BobaToolHealthCheckV1(BobaContract):
    health_check_id: str = Field(min_length=1, max_length=160)
    tool_id: str = Field(min_length=1, max_length=160)
    check_type: BobaToolHealthCheckTypeV1
    executable: str = Field(default="", max_length=260)
    arguments: list[str] = Field(default_factory=list, max_length=32)
    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    shell_used: Literal[False] = False
    network_required: Literal[False] = False
    read_only: bool = True
    expected_exit_codes: list[int] = Field(default_factory=lambda: [0], max_length=16)
    output_limit_bytes: int = Field(
        default=DEFAULT_OUTPUT_LIMIT_BYTES,
        ge=1_024,
        le=1_048_576,
    )
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaToolCapabilityV1(BobaContract):
    capability_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=700)
    required_input_properties: list[str] = Field(default_factory=list, max_length=32)
    required_output_properties: list[str] = Field(default_factory=list, max_length=32)
    non_negotiable_quality_properties: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    acceptable_degradations: list[str] = Field(default_factory=list, max_length=24)
    unacceptable_degradations: list[str] = Field(default_factory=list, max_length=32)
    safety_constraints: list[str] = Field(default_factory=list, max_length=32)
    rights_constraints: list[str] = Field(default_factory=list, max_length=32)
    registered_tool_ids: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRegisteredRecoveryToolV1(BobaContract):
    tool_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=160)
    provider_type: BobaToolProviderTypeV1
    capability_ids: list[str] = Field(default_factory=list, max_length=32)
    executable: str = Field(default="", max_length=260)
    package_name: str = Field(default="", max_length=160)
    local_only: bool = True
    installed: bool = False
    available: bool = False
    health_status: BobaToolHealthStatusV1 = "unverified"
    version: str = Field(default="", max_length=160)
    supported_inputs: list[str] = Field(default_factory=list, max_length=32)
    supported_outputs: list[str] = Field(default_factory=list, max_length=32)
    quality_tier: str = Field(default="unknown", max_length=80)
    resource_profile: str = Field(default="unknown", max_length=160)
    fallback_priority: int = Field(default=100, ge=0, le=1_000)
    known_limitations: list[str] = Field(default_factory=list, max_length=32)
    prohibited_uses: list[str] = Field(default_factory=list, max_length=32)
    health_check: BobaToolHealthCheckV1 | None = None
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaToolHealthResultV1(BobaContract):
    health_result_id: str = Field(min_length=1, max_length=160)
    health_check_id: str = Field(min_length=1, max_length=160)
    tool_id: str = Field(min_length=1, max_length=160)
    status: BobaToolHealthResultStatusV1
    exit_code: int | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)
    version_detected: str = Field(default="", max_length=160)
    bounded_stdout_summary: str = Field(default="", max_length=4_000)
    bounded_stderr_summary: str = Field(default="", max_length=4_000)
    output_truncated: bool = False
    secrets_redacted: bool = True
    checked_at: str = Field(default_factory=now_iso)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRecoveryCommandV1(BobaContract):
    recovery_command_id: str = Field(min_length=1, max_length=160)
    tool_id: str = Field(min_length=1, max_length=160)
    executable: str = Field(min_length=1, max_length=260)
    arguments: list[str] = Field(default_factory=list, max_length=128)
    working_directory_scope: str = Field(min_length=1, max_length=500)
    category: BobaRecoveryCommandCategoryV1
    approved: bool = False
    shell_used: Literal[False] = False
    network_forbidden: Literal[True] = True
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=1_800.0)
    expected_exit_codes: list[int] = Field(default_factory=lambda: [0], max_length=16)
    output_limit_bytes: int = Field(
        default=DEFAULT_OUTPUT_LIMIT_BYTES,
        ge=1_024,
        le=1_048_576,
    )
    environment_policy: str = Field(
        default="sanitized_local_only",
        min_length=1,
        max_length=160,
    )
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaToolRecoveryStrategyV1(BobaContract):
    recovery_strategy_id: str = Field(min_length=1, max_length=160)
    recovery_plan_id: str = Field(min_length=1, max_length=160)
    order: int = Field(ge=1, le=32)
    strategy_type: BobaToolRecoveryStrategyTypeV1
    tool_id: str = Field(default="", max_length=160)
    capability_id: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=700)
    rationale: str = Field(min_length=1, max_length=700)
    configuration_overrides: dict[str, Any] = Field(default_factory=dict, max_length=32)
    expected_result: str = Field(min_length=1, max_length=700)
    expected_quality_effect: str = Field(min_length=1, max_length=700)
    expected_resource_effect: str = Field(min_length=1, max_length=700)
    reversible: bool = True
    requires_checkpoint: bool = False
    requires_tool_switch: bool = False
    requires_quality_review: Literal[True] = True
    requires_human_approval: Literal[True] = True
    execution_allowed: bool = False
    maximum_attempts: int = Field(
        default=DEFAULT_MAX_ATTEMPTS_PER_STRATEGY,
        ge=1,
        le=2,
    )
    timeout_seconds: int = Field(default=DEFAULT_MAX_ATTEMPT_SECONDS, ge=1, le=1_800)
    failure_stop_condition: str = Field(min_length=1, max_length=700)
    success_condition: str = Field(min_length=1, max_length=700)
    rollback_reference: str = Field(default="", max_length=180)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaToolRecoveryPlanV1(BobaContract):
    recovery_plan_id: str = Field(min_length=1, max_length=160)
    recovery_case_id: str = Field(min_length=1, max_length=160)
    approved_repair_strategy_id: str = Field(default="", max_length=160)
    required_capability: str = Field(min_length=1, max_length=160)
    primary_tool_id: str = Field(default="", max_length=160)
    candidate_fallback_tool_ids: list[str] = Field(default_factory=list, max_length=32)
    ordered_strategies: list[BobaToolRecoveryStrategyV1] = Field(
        default_factory=list,
        max_length=32,
    )
    retry_budget: dict[str, int] = Field(default_factory=dict, max_length=12)
    time_budget_seconds: int = Field(
        default=DEFAULT_MAX_RECOVERY_SECONDS,
        ge=1,
        le=1_800,
    )
    checkpoint_requirements: dict[str, Any] = Field(default_factory=dict, max_length=32)
    rollback_requirements: dict[str, Any] = Field(default_factory=dict, max_length=32)
    quality_requirements: list[str] = Field(default_factory=list, max_length=64)
    validation_requirements: list[str] = Field(default_factory=list, max_length=64)
    approval_status: BobaToolRecoveryApprovalStatusV1 = "planning_only"
    execution_status: BobaToolRecoveryExecutionStatusV1 = "not_started"
    prohibited_actions: list[str] = Field(default_factory=list, max_length=64)
    stop_conditions: list[str] = Field(default_factory=list, max_length=32)
    escalation_conditions: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaToolRecoveryApprovalV1(BobaContract):
    approval_id: str = Field(min_length=1, max_length=160)
    recovery_case_id: str = Field(min_length=1, max_length=160)
    recovery_plan_id: str = Field(min_length=1, max_length=160)
    approved: bool = False
    approved_at: str | None = Field(default=None, max_length=80)
    approved_by: str = Field(default="", max_length=160)
    approved_strategy_ids: list[str] = Field(default_factory=list, max_length=32)
    approved_tool_ids: list[str] = Field(default_factory=list, max_length=32)
    approved_configuration_overrides: dict[str, Any] = Field(
        default_factory=dict,
        max_length=32,
    )
    approved_retry_budget: dict[str, int] = Field(default_factory=dict, max_length=12)
    approved_time_budget_seconds: int = Field(default=0, ge=0, le=1_800)
    approved_quality_requirements: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    approved_checkpoint_reference: str = Field(default="", max_length=500)
    approval_expires_at: str | None = Field(default=None, max_length=80)
    explicit_confirmation: str = Field(default="", max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaToolRecoveryCaseV1(BobaContract):
    recovery_case_id: str = Field(min_length=1, max_length=160)
    source_repair_case_id: str = Field(min_length=1, max_length=160)
    source_repair_strategy_ids: list[str] = Field(default_factory=list, max_length=32)
    title: str = Field(min_length=1, max_length=240)
    target_module: str = Field(default="", max_length=160)
    workflow_stage: str = Field(default="unknown", max_length=160)
    required_capability: str = Field(min_length=1, max_length=160)
    failing_tool_id: str = Field(default="", max_length=160)
    failure_class: BobaToolFailureClassV1
    failure_evidence: list[str] = Field(default_factory=list, max_length=64)
    rights_status: str = Field(default="unknown", max_length=80)
    safety_status: str = Field(default="unknown", max_length=80)
    checkpoint_required: bool = False
    checkpoint_ready: bool = False
    rollback_ready: bool = False
    quality_requirements: list[str] = Field(default_factory=list, max_length=64)
    approved_strategy_ids: list[str] = Field(default_factory=list, max_length=32)
    recovery_eligible: bool = False
    blocked_reason: str = Field(default="", max_length=900)
    human_approval_required: Literal[True] = True
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaToolRecoveryAttemptV1(BobaContract):
    recovery_attempt_id: str = Field(min_length=1, max_length=160)
    recovery_case_id: str = Field(min_length=1, max_length=160)
    recovery_plan_id: str = Field(min_length=1, max_length=160)
    recovery_strategy_id: str = Field(min_length=1, max_length=160)
    attempt_number: int = Field(ge=1, le=4)
    tool_id: str = Field(min_length=1, max_length=160)
    capability_id: str = Field(min_length=1, max_length=160)
    execution_started_at: str | None = Field(default=None, max_length=80)
    execution_completed_at: str | None = Field(default=None, max_length=80)
    working_directory_reference: str = Field(min_length=1, max_length=500)
    command_records: list[BobaRecoveryCommandV1] = Field(
        default_factory=list,
        max_length=64,
    )
    status: BobaToolRecoveryAttemptStatusV1 = "not_started"
    exit_code: int | None = None
    timeout_occurred: bool = False
    output_artifact_refs: list[str] = Field(default_factory=list, max_length=64)
    temporary_artifact_refs: list[str] = Field(default_factory=list, max_length=64)
    failure_class: BobaToolFailureClassV1 = "unknown"
    failure_summary: str = Field(default="", max_length=2_000)
    quality_change_disclosed: bool = False
    source_media_untouched: bool = True
    completed_outputs_untouched: bool = True
    validation_required: bool = True
    next_strategy_allowed: bool = False
    stop_reason: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRecoveredOutputValidationV1(BobaContract):
    output_validation_id: str = Field(min_length=1, max_length=160)
    recovery_attempt_id: str = Field(min_length=1, max_length=160)
    output_artifact_ref: str = Field(default="", max_length=500)
    artifact_exists: bool = False
    artifact_non_empty: bool = False
    checksum_valid: bool | None = None
    media_probe_valid: bool | None = None
    duration_valid: bool | None = None
    resolution_valid: bool | None = None
    frame_rate_valid: bool | None = None
    audio_presence_valid: bool | None = None
    audio_video_sync_valid: bool | None = None
    caption_timing_status: BobaRecoveryCheckStatusV1 = "not_required"
    framing_status: BobaRecoveryCheckStatusV1 = "not_required"
    source_window_status: BobaRecoveryCheckStatusV1 = "not_required"
    schema_valid: bool | None = None
    required_checks_passed: bool = False
    failed_required_checks: list[str] = Field(default_factory=list, max_length=64)
    unavailable_required_checks: list[str] = Field(default_factory=list, max_length=64)
    quality_review_required: Literal[True] = True
    accepted_for_quality_review: bool = False
    rejected_reason: str = Field(default="", max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaToolRecoveryRollbackV1(BobaContract):
    rollback_record_id: str = Field(min_length=1, max_length=160)
    recovery_attempt_id: str = Field(min_length=1, max_length=160)
    trigger: str = Field(min_length=1, max_length=900)
    scope: str = Field(default="recovery_owned_generated_state", max_length=180)
    temporary_outputs_removed: bool = False
    prior_generated_state_restored: bool = False
    original_outputs_preserved: bool = True
    source_media_preserved: bool = True
    checkpoint_unchanged: bool = True
    rollback_validation_passed: bool = False
    status: BobaToolRecoveryRollbackStatusV1 = "unknown"
    human_review_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaToolRecoveryHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=160)
    recovery_case_id: str = Field(min_length=1, max_length=160)
    recovery_plan_id: str = Field(default="", max_length=160)
    recovery_attempt_id: str = Field(default="", max_length=160)
    target_module: BobaToolRecoveryHandoffTargetV1
    reason: str = Field(min_length=1, max_length=700)
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    required_quality_checks: list[str] = Field(default_factory=list, max_length=32)
    blocked_actions: list[str] = Field(default_factory=list, max_length=32)
    allowed_advisory_actions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False
    human_approval_required: Literal[True] = True
    priority: BobaToolRecoveryPriorityV1 = "medium"
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaToolRecoverySummaryV1(BobaContract):
    total_recovery_cases: int = Field(default=0, ge=0)
    eligible_case_count: int = Field(default=0, ge=0)
    blocked_case_count: int = Field(default=0, ge=0)
    health_check_count: int = Field(default=0, ge=0)
    healthy_tool_count: int = Field(default=0, ge=0)
    unavailable_tool_count: int = Field(default=0, ge=0)
    recovery_plan_count: int = Field(default=0, ge=0)
    recovery_attempt_count: int = Field(default=0, ge=0)
    successful_pending_quality_count: int = Field(default=0, ge=0)
    failed_attempt_count: int = Field(default=0, ge=0)
    timeout_count: int = Field(default=0, ge=0)
    rollback_count: int = Field(default=0, ge=0)
    fallback_switch_count: int = Field(default=0, ge=0)
    checkpoint_block_count: int = Field(default=0, ge=0)
    quality_rejection_count: int = Field(default=0, ge=0)
    current_highest_priority_case: str = Field(default="", max_length=700)
    safest_available_strategy: str = Field(default="", max_length=700)
    required_human_actions: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaToolRecoverySignalUsageV1(BobaContract):
    repair_planner_used: bool = False
    repair_planner_artifact_read: bool = False
    root_cause_references_used: bool = False
    approval_record_used: bool = False
    capability_registry_used: bool = False
    local_health_checks_executed: bool = False
    recovery_commands_executed: bool = False
    local_fallback_used: bool = False
    checkpoint_reference_used: bool = False
    output_validation_used: bool = False
    rollback_used: bool = False
    source_media_modified: Literal[False] = False
    completed_outputs_modified: Literal[False] = False
    workflow_resume_used: Literal[False] = False
    code_modification_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    process_kill_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    uploading_used: Literal[False] = False
    paid_service_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaToolRecoveryBrainSetV1(BobaContract):
    schema_version: Literal["boba_tool_recovery_brain_v1"] = (
        "boba_tool_recovery_brain_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    repair_planner_source: str = Field(min_length=1, max_length=500)
    recovery_cases: list[BobaToolRecoveryCaseV1] = Field(
        default_factory=list,
        max_length=256,
    )
    capability_registry: list[BobaToolCapabilityV1] = Field(
        default_factory=list,
        max_length=64,
    )
    registered_tools: list[BobaRegisteredRecoveryToolV1] = Field(
        default_factory=list,
        max_length=64,
    )
    tool_health_results: list[BobaToolHealthResultV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    recovery_plans: list[BobaToolRecoveryPlanV1] = Field(
        default_factory=list,
        max_length=256,
    )
    recovery_attempts: list[BobaToolRecoveryAttemptV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    output_validations: list[BobaRecoveredOutputValidationV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    rollback_records: list[BobaToolRecoveryRollbackV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    recovery_handoffs: list[BobaToolRecoveryHandoffV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    recovery_summary: BobaToolRecoverySummaryV1
    signal_usage: BobaToolRecoverySignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


@dataclass(frozen=True)
class _ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    output_truncated: bool


@dataclass(frozen=True)
class _BuiltCommand:
    record: BobaRecoveryCommandV1
    arguments: tuple[str, ...]
    output_path: Path | None
    input_path: Path | None


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _safe_text(value: Any, *, maximum: int = 900) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    text = _SECRET_VALUE.sub("[REDACTED]", text)
    text = _PRIVATE_PATH.sub("[private-path]", text)
    return text[:maximum]


def _unique(values: Sequence[str], *, limit: int = 64) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _safe_text(value, maximum=900)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
            if len(result) >= limit:
                break
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _as_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _iso_expired(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    except ValueError:
        return True
    return parsed <= datetime.now(UTC)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _configured_executable(value: str) -> tuple[str, bool]:
    configured = value.strip() or value
    found = shutil.which(configured)
    if found:
        return Path(configured).name or configured, True
    path = Path(configured)
    return path.name or configured, path.is_file()


def _health_check(
    tool_id: str,
    check_type: BobaToolHealthCheckTypeV1,
    *,
    executable: str = "",
    arguments: Sequence[str] = (),
    timeout_seconds: float = 15.0,
) -> BobaToolHealthCheckV1:
    return BobaToolHealthCheckV1(
        health_check_id=_stable_id("health_check", tool_id, check_type),
        tool_id=tool_id,
        check_type=check_type,
        executable=executable,
        arguments=list(arguments),
        timeout_seconds=timeout_seconds,
    )


def build_minimal_capability_registry(
    *,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    transcription_provider: str = "noop",
) -> tuple[list[BobaToolCapabilityV1], list[BobaRegisteredRecoveryToolV1]]:
    """Build deterministic local capability and provider entries without execution."""

    ffmpeg_name, ffmpeg_installed = _configured_executable(ffmpeg_binary)
    ffprobe_name, ffprobe_installed = _configured_executable(ffprobe_binary)
    pyav_installed = _module_available("av")
    opencv_installed = _module_available("cv2")
    whisper_installed = _module_available("faster_whisper")
    whisper_configured = transcription_provider.strip().lower() in {
        "faster-whisper",
        "faster_whisper",
    }

    tools = [
        BobaRegisteredRecoveryToolV1(
            tool_id="ffprobe",
            display_name="FFprobe",
            provider_type="executable",
            capability_ids=["video_probe", "audio_probe"],
            executable=ffprobe_name,
            installed=ffprobe_installed,
            supported_inputs=["local_media_file"],
            supported_outputs=["bounded_media_metadata_json"],
            quality_tier="reference_probe",
            resource_profile="low",
            fallback_priority=10,
            prohibited_uses=["network_inputs", "private_unauthorized_media"],
            health_check=_health_check(
                "ffprobe",
                "version",
                executable=ffprobe_name,
                arguments=["-version"],
            ),
            warnings=[] if ffprobe_installed else ["Configured FFprobe is unavailable."],
        ),
        BobaRegisteredRecoveryToolV1(
            tool_id="ffmpeg",
            display_name="FFmpeg",
            provider_type="executable",
            capability_ids=[
                "video_render",
                "media_decode_check",
                "media_encode_check",
                "frame_extraction",
                "audio_extraction",
            ],
            executable=ffmpeg_name,
            installed=ffmpeg_installed,
            supported_inputs=["local_media_file", "generated_synthetic_fixture"],
            supported_outputs=[
                "generated_mp4",
                "generated_audio",
                "generated_frame",
            ],
            quality_tier="olympus_renderer",
            resource_profile="bounded_configurable",
            fallback_priority=10,
            prohibited_uses=[
                "network_inputs",
                "source_overwrite",
                "accepted_output_overwrite",
                "unbounded_execution",
            ],
            health_check=_health_check(
                "ffmpeg",
                "version",
                executable=ffmpeg_name,
                arguments=["-version"],
            ),
            warnings=[] if ffmpeg_installed else ["Configured FFmpeg is unavailable."],
        ),
        BobaRegisteredRecoveryToolV1(
            tool_id="pyav",
            display_name="PyAV",
            provider_type="python_package",
            capability_ids=["video_probe", "audio_probe", "media_decode_check"],
            package_name="av",
            installed=pyav_installed,
            supported_inputs=["local_media_file"],
            supported_outputs=["bounded_media_metadata"],
            quality_tier="compatible_probe",
            resource_profile="medium",
            fallback_priority=30,
            known_limitations=[
                "Output semantics are not identical to every FFprobe field."
            ],
            prohibited_uses=["network_inputs", "media_mutation"],
            health_check=_health_check("pyav", "import_available"),
            warnings=[] if pyav_installed else ["PyAV is not installed; no install was attempted."],
        ),
        BobaRegisteredRecoveryToolV1(
            tool_id="opencv",
            display_name="OpenCV",
            provider_type="python_package",
            capability_ids=["video_probe", "media_decode_check", "frame_extraction"],
            package_name="cv2",
            installed=opencv_installed,
            supported_inputs=["local_video_file"],
            supported_outputs=["basic_video_metadata", "generated_frame"],
            quality_tier="limited_fallback",
            resource_profile="medium",
            fallback_priority=40,
            known_limitations=[
                "Audio metadata and precise stream timing are not available.",
                "It cannot satisfy audio-probe or A/V-sync requirements.",
            ],
            prohibited_uses=["audio_probe", "network_inputs", "media_mutation"],
            health_check=_health_check("opencv", "import_available"),
            warnings=(
                []
                if opencv_installed
                else ["OpenCV is not installed; no install was attempted."]
            ),
        ),
        BobaRegisteredRecoveryToolV1(
            tool_id="faster_whisper_local",
            display_name="Configured Faster Whisper",
            provider_type="python_package",
            capability_ids=["transcript_provider_local"],
            package_name="faster_whisper",
            installed=whisper_installed,
            supported_inputs=["local_audio_or_video"],
            supported_outputs=["timestamped_transcript"],
            quality_tier="configured_local_transcription",
            resource_profile="high",
            fallback_priority=20,
            known_limitations=["Model weights must already be available locally."],
            prohibited_uses=[
                "model_download",
                "network_model_fetch",
                "unauthorized_media",
            ],
            health_check=_health_check("faster_whisper_local", "import_available"),
            warnings=_unique(
                [
                    *(
                        []
                        if whisper_installed
                        else ["Faster Whisper is not installed; no install was attempted."]
                    ),
                    *(
                        []
                        if whisper_configured
                        else ["Faster Whisper is not the configured transcription provider."]
                    ),
                ]
            ),
        ),
        BobaRegisteredRecoveryToolV1(
            tool_id="internal_json_validator",
            display_name="Olympus JSON Validator",
            provider_type="internal_module",
            capability_ids=["JSON_artifact_validation"],
            package_name="json",
            installed=True,
            supported_inputs=["local_json_artifact"],
            supported_outputs=["schema_validation_result"],
            quality_tier="deterministic_internal",
            resource_profile="low",
            fallback_priority=5,
            prohibited_uses=["artifact_mutation", "external_schema_fetch"],
            health_check=_health_check("internal_json_validator", "internal_health"),
        ),
        BobaRegisteredRecoveryToolV1(
            tool_id="internal_checksum_validator",
            display_name="Olympus Checksum Validator",
            provider_type="internal_module",
            capability_ids=["checksum_validation"],
            package_name="hashlib",
            installed=True,
            supported_inputs=["local_file"],
            supported_outputs=["sha256_digest"],
            quality_tier="deterministic_internal",
            resource_profile="low",
            fallback_priority=5,
            prohibited_uses=["file_mutation", "network_inputs"],
            health_check=_health_check("internal_checksum_validator", "internal_health"),
        ),
        BobaRegisteredRecoveryToolV1(
            tool_id="external_transcription_service",
            display_name="External transcription service",
            provider_type="external_service",
            capability_ids=["transcript_provider_local"],
            local_only=False,
            installed=False,
            available=False,
            health_status="blocked",
            supported_inputs=["external_upload"],
            supported_outputs=["transcript"],
            quality_tier="blocked_external",
            resource_profile="external",
            fallback_priority=1_000,
            prohibited_uses=[
                "all_v1_execution",
                "network_access",
                "paid_service",
                "media_upload",
            ],
            warnings=["External services are blocked for Tool Recovery Brain V1."],
        ),
    ]
    capability_specs: tuple[
        tuple[str, str, str, list[str], list[str], list[str], list[str]],
        ...,
    ] = (
        (
            "video_probe",
            "Video probe",
            "Inspect local video stream and container properties.",
            ["readable local media"],
            ["duration", "video stream", "resolution", "frame rate"],
            ["source untouched", "bounded local read"],
            ["ffprobe", "pyav", "opencv"],
        ),
        (
            "video_render",
            "Video render",
            "Encode an approved local generated video output.",
            ["trusted local source reference", "approved render specification"],
            ["validated generated MP4"],
            ["duration", "resolution", "frame rate", "audio", "A/V sync"],
            ["ffmpeg"],
        ),
        (
            "audio_probe",
            "Audio probe",
            "Inspect local audio stream properties.",
            ["readable local media"],
            ["audio stream", "sample rate", "duration"],
            ["source untouched", "A/V timing preserved"],
            ["ffprobe", "pyav"],
        ),
        (
            "media_decode_check",
            "Media decode check",
            "Perform a bounded local decode check without output mutation.",
            ["readable local media"],
            ["decode result"],
            ["source untouched"],
            ["ffmpeg", "pyav", "opencv"],
        ),
        (
            "media_encode_check",
            "Media encode check",
            "Encode a bounded generated synthetic fixture.",
            ["generated synthetic fixture"],
            ["probeable generated media"],
            ["bounded duration", "explicit resolution", "explicit frame rate"],
            ["ffmpeg"],
        ),
        (
            "frame_extraction",
            "Frame extraction",
            "Extract a generated review frame from local media.",
            ["readable local video"],
            ["generated image"],
            ["source untouched", "approved source timestamp"],
            ["ffmpeg", "opencv"],
        ),
        (
            "audio_extraction",
            "Audio extraction",
            "Extract generated audio from local media.",
            ["readable local media"],
            ["generated WAV"],
            ["source untouched", "source timing preserved"],
            ["ffmpeg"],
        ),
        (
            "transcript_provider_local",
            "Local transcript provider",
            "Use an already-configured local transcription provider.",
            ["authorized local media", "locally available model"],
            ["timestamped transcript"],
            ["no model download", "rights clearance"],
            ["faster_whisper_local", "external_transcription_service"],
        ),
        (
            "JSON_artifact_validation",
            "JSON artifact validation",
            "Validate generated JSON syntax and required keys locally.",
            ["local JSON artifact"],
            ["validation result"],
            ["artifact untouched", "no external schema fetch"],
            ["internal_json_validator"],
        ),
        (
            "checksum_validation",
            "Checksum validation",
            "Calculate or compare a local SHA-256 checksum.",
            ["local file"],
            ["SHA-256 digest result"],
            ["file untouched"],
            ["internal_checksum_validator"],
        ),
    )
    capabilities = [
        BobaToolCapabilityV1(
            capability_id=capability_id,
            name=name,
            description=description,
            required_input_properties=input_properties,
            required_output_properties=output_properties,
            non_negotiable_quality_properties=quality_properties,
            acceptable_degradations=["bounded resource reduction with identical output contract"],
            unacceptable_degradations=[
                "silent duration truncation",
                "silent audio removal",
                "source modification",
                "accepted output overwrite",
            ],
            safety_constraints=[
                "local only",
                "no shell",
                "no network",
                "bounded time and output",
            ],
            rights_constraints=["authorized local inputs only"],
            registered_tool_ids=tool_ids,
        )
        for (
            capability_id,
            name,
            description,
            input_properties,
            output_properties,
            quality_properties,
            tool_ids,
        ) in capability_specs
    ]
    return capabilities, tools


def build_trusted_recovery_command_registry(
    tools: Sequence[BobaRegisteredRecoveryToolV1],
) -> dict[str, tuple[BobaRecoveryCommandCategoryV1, ...]]:
    """Return the immutable command categories each registered provider may use."""

    registry: dict[str, tuple[BobaRecoveryCommandCategoryV1, ...]] = {}
    for tool in tools:
        if tool.tool_id == "ffmpeg":
            registry[tool.tool_id] = (
                "health_check",
                "render_retry",
                "segmented_render",
                "audio_extract",
                "frame_extract",
                "decode_check",
                "encode_check",
            )
        elif tool.tool_id == "ffprobe":
            registry[tool.tool_id] = ("health_check", "media_probe")
        elif tool.tool_id == "internal_json_validator":
            registry[tool.tool_id] = ("health_check", "artifact_validate")
        elif tool.tool_id == "internal_checksum_validator":
            registry[tool.tool_id] = ("health_check", "checksum")
        else:
            registry[tool.tool_id] = ("health_check",)
    return registry


def classify_tool_failure(
    repair_case: BobaRepairPlanningCaseV1 | None,
    strategy: BobaRepairStrategyV1 | None,
    context: Mapping[str, Any] | None = None,
) -> BobaToolFailureClassV1:
    supplied = str(_as_dict(context).get("failure_class") or "").strip().lower()
    allowed = {
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
        "environment_problem",
        "permission_problem",
        "generated_state_problem",
        "checkpoint_problem",
        "external_service_unavailable",
        "unknown",
    }
    if supplied in allowed:
        return supplied  # type: ignore[return-value]
    text = " ".join(
        [
            repair_case.title if repair_case else "",
            repair_case.selected_root_cause_summary if repair_case else "",
            strategy.title if strategy else "",
            strategy.description if strategy else "",
            strategy.rationale if strategy else "",
            strategy.strategy_type if strategy else "",
        ]
    ).lower()
    markers: tuple[tuple[BobaToolFailureClassV1, tuple[str, ...]], ...] = (
        ("resource_exhaustion", ("resource exhaustion", "out of memory", "winerror 1450")),
        ("repeated_crash", ("repeated crash", "crash loop", "same failure repeats")),
        ("temporary_crash", ("temporary crash", "transient crash", "retry_same_tool")),
        ("timeout", ("timeout", "timed out", "deadline")),
        ("malformed_output", ("malformed", "invalid output", "corrupt output")),
        ("unsupported_input", ("unsupported input", "unsupported codec", "decode")),
        ("incompatible_version", ("incompatible version", "version mismatch")),
        ("executable_missing", ("executable missing", "not found", "missing executable")),
        ("tool_unavailable", ("tool unavailable", "unavailable tool", "tool failure")),
        ("configuration_problem", ("configuration", "safe setting")),
        ("environment_problem", ("environment", "dependency", "install")),
        ("permission_problem", ("permission denied", "access denied")),
        ("generated_state_problem", ("generated state", "temporary state")),
        ("checkpoint_problem", ("checkpoint",)),
        ("external_service_unavailable", ("external service", "paid service")),
    )
    for failure_class, values in markers:
        if any(marker in text for marker in values):
            return failure_class
    return "unknown"


def _normalize_capability(value: str) -> str:
    normalized = value.strip().replace("-", "_").replace(" ", "_")
    aliases = {
        "media_probe": "video_probe",
        "video_rendering": "video_render",
        "rendering": "video_render",
        "audio_encoding": "media_encode_check",
        "artifact_validation": "JSON_artifact_validation",
        "json_artifact_validation": "JSON_artifact_validation",
        "checkpoint_validation": "checksum_validation",
    }
    return aliases.get(normalized.lower(), normalized)


def _infer_capability(
    handoff: BobaRepairExecutionHandoffV1,
    repair_case: BobaRepairPlanningCaseV1,
    strategy: BobaRepairStrategyV1 | None,
    context: Mapping[str, Any],
) -> str:
    supplied = str(context.get("required_capability") or "").strip()
    if supplied:
        return _normalize_capability(supplied)
    normalized = _normalize_capability(handoff.required_capability)
    known = {
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
    }
    if normalized in known:
        return normalized
    text = " ".join(
        [
            handoff.required_capability,
            repair_case.primary_module,
            repair_case.primary_artifact,
            strategy.target_module if strategy else "",
            strategy.target_artifact if strategy else "",
            strategy.title if strategy else "",
        ]
    ).lower()
    if "ffprobe" in text or "media probe" in text:
        return "video_probe"
    if "render" in text or "ffmpeg" in text:
        return "video_render"
    if "transcript" in text or "whisper" in text:
        return "transcript_provider_local"
    if "audio" in text and "extract" in text:
        return "audio_extraction"
    if "audio" in text:
        return "audio_probe"
    if "frame" in text:
        return "frame_extraction"
    if "json" in text or "artifact" in text or "tool_output" in text:
        return "JSON_artifact_validation"
    return normalized


def _infer_primary_tool(capability_id: str, context: Mapping[str, Any]) -> str:
    supplied = str(context.get("failing_tool_id") or "").strip()
    if supplied:
        return supplied
    if capability_id in {"video_probe", "audio_probe"}:
        return "ffprobe"
    if capability_id in {
        "video_render",
        "media_decode_check",
        "media_encode_check",
        "frame_extraction",
        "audio_extraction",
    }:
        return "ffmpeg"
    if capability_id == "transcript_provider_local":
        return "faster_whisper_local"
    if capability_id == "JSON_artifact_validation":
        return "internal_json_validator"
    if capability_id == "checksum_validation":
        return "internal_checksum_validator"
    return ""


def _quality_requirements(
    handoff: BobaRepairExecutionHandoffV1,
    quality: BobaQualityPreservationPlanV1 | None,
) -> list[str]:
    values = list(handoff.required_quality_properties)
    if quality:
        values.extend(quality.non_negotiable_requirements)
        values.extend(quality.technical_quality_checks)
        values.extend(quality.rights_safety_checks)
    return _unique(values, limit=64) or [
        "source media remains untouched",
        "accepted outputs remain untouched",
        "required technical validation passes",
    ]


def _validation_requirements(
    plan: BobaRepairValidationPlanV1 | None,
) -> list[str]:
    if not plan:
        return []
    return _unique(
        [
            *plan.required_validators,
            *plan.acceptance_criteria,
            *plan.output_quality_checks,
            *(
                check.validator_name or check.category
                for check in plan.post_repair_checks
                if check.required
            ),
        ],
        limit=64,
    )


def _safe_configuration(context: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    raw = _as_dict(context.get("configuration_overrides"))
    for key in _ALLOWED_CONFIGURATION_KEYS:
        if key in context and key not in raw:
            raw[key] = context[key]
    safe: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in raw.items():
        if key not in _ALLOWED_CONFIGURATION_KEYS:
            warnings.append(f"Unsupported recovery setting was ignored: {key}.")
            continue
        if key in {"input_artifact_ref", "output_filename"}:
            safe[key] = str(value or "")[:500]
        elif key in {"protected_output_refs", "required_schema_keys"}:
            safe[key] = [str(item)[:500] for item in _as_list(value)[:32]]
        elif key in {"require_audio"}:
            safe[key] = bool(value)
        elif key in {
            "expected_duration_seconds",
            "expected_fps",
            "source_window_end_seconds",
            "source_window_start_seconds",
        }:
            safe[key] = _as_float(value, 0.0)
        elif key in {
            "audio_bitrate_kbps",
            "encoder_threads",
            "expected_height",
            "expected_width",
            "filter_threads",
            "parallel_tasks",
            "segment_seconds",
            "timeout_seconds",
            "video_bitrate_kbps",
        }:
            safe[key] = _as_int(value, 0)
        else:
            safe[key] = _safe_text(value, maximum=160)
    return safe, warnings


def _strategy_specs(
    failure_class: BobaToolFailureClassV1,
) -> list[BobaToolRecoveryStrategyTypeV1]:
    ladders: dict[str, list[BobaToolRecoveryStrategyTypeV1]] = {
        "tool_unavailable": ["health_check", "switch_registered_local_tool", "stop_processing"],
        "executable_missing": ["health_check", "switch_registered_local_tool", "stop_processing"],
        "incompatible_version": ["health_check", "compatibility_mode", "stop_processing"],
        "temporary_crash": ["health_check", "bounded_retry", "stop_processing"],
        "repeated_crash": [
            "health_check",
            "retry_with_safe_settings",
            "switch_registered_local_tool",
            "stop_processing",
        ],
        "timeout": [
            "health_check",
            "retry_with_safe_settings",
            "segmented_processing",
            "stop_processing",
        ],
        "malformed_output": [
            "health_check",
            "bounded_retry",
            "switch_registered_local_tool",
            "stop_processing",
        ],
        "unsupported_input": ["health_check", "compatibility_mode", "stop_processing"],
        "resource_exhaustion": [
            "health_check",
            "reduce_thread_usage",
            "reduce_memory_pressure",
            "segmented_processing",
            "switch_registered_local_tool",
            "stop_processing",
        ],
        "configuration_problem": [
            "health_check",
            "retry_with_safe_settings",
            "human_manual_action",
        ],
        "generated_state_problem": [
            "health_check",
            "regenerate_temporary_state",
            "stop_processing",
        ],
        "checkpoint_problem": ["stop_processing", "human_manual_action"],
        "environment_problem": ["health_check", "human_manual_action"],
        "permission_problem": ["stop_processing", "human_manual_action"],
        "external_service_unavailable": ["stop_processing", "human_manual_action"],
        "unknown": ["collect_more_evidence", "stop_processing"],
    }
    return ladders[failure_class]


def _strategy_description(strategy_type: str) -> tuple[str, str, str]:
    descriptions = {
        "health_check": (
            "Run the registered local read-only health check.",
            "Confirm provider availability before considering recovery.",
            "No generated output changes.",
        ),
        "bounded_retry": (
            "Retry the exact failed local capability once within the approved budget.",
            "The evidence indicates a transient failure may be recoverable.",
            "Same required output contract; no silent quality reduction.",
        ),
        "retry_with_safe_settings": (
            "Retry with approved temporary bounded settings.",
            "A bounded timeout or configuration adjustment may reduce failure risk.",
            "Temporary invocation settings only; required output properties remain fixed.",
        ),
        "reduce_thread_usage": (
            "Retry with one encoder, filter, and parallel task thread.",
            "Lower concurrency reduces Windows process and memory pressure.",
            "Resolution, frame rate, duration, and audio requirements remain fixed.",
        ),
        "reduce_memory_pressure": (
            "Use a bounded-memory local recovery profile.",
            "The observed failure is consistent with resource exhaustion.",
            "No resolution, duration, frame-rate, or audio reduction is allowed.",
        ),
        "segmented_processing": (
            "Prepare bounded segment processing under one approved total budget.",
            "Smaller generated segments can reduce peak memory.",
            "Final continuity, duration, audio, and quality still require validation.",
        ),
        "compatibility_mode": (
            "Use an already-supported compatibility profile.",
            "The input or provider version may need a safer local decode or encode path.",
            "Any difference is disclosed and must pass the same quality requirements.",
        ),
        "regenerate_temporary_state": (
            "Regenerate recovery-owned temporary state only.",
            "The failure appears limited to generated temporary data.",
            "Source media, accepted outputs, and checkpoints remain untouched.",
        ),
        "switch_registered_local_tool": (
            "Use an approved already-installed compatible local provider.",
            "The primary provider is unavailable or repeatedly failed.",
            "Fallback semantics and limitations must satisfy all non-negotiable checks.",
        ),
        "collect_more_evidence": (
            "Collect bounded local evidence without recovery execution.",
            "The current failure classification is not strong enough to recover safely.",
            "No output is accepted and no workflow resumes.",
        ),
        "stop_processing": (
            "Stop recovery and preserve evidence.",
            "No remaining safe strategy is eligible.",
            "No generated output changes.",
        ),
        "human_manual_action": (
            "Require a human operator to resolve the blocked condition.",
            "V1 cannot install tools, change permanent configuration, or restore checkpoints.",
            "No automatic quality or workflow change.",
        ),
    }
    return descriptions.get(
        strategy_type,
        (
            "Unknown recovery strategy.",
            "The strategy is unsupported.",
            "No execution is allowed.",
        ),
    )


def _default_prohibited_actions() -> list[str]:
    return [
        "install or uninstall software",
        "update or download tools",
        "access the internet or external APIs",
        "use paid services",
        "download or upload media",
        "modify source media",
        "overwrite accepted outputs",
        "edit source code or Git state",
        "restart services or the operating system",
        "kill unrelated processes",
        "use a shell, pipe, redirect, or command chain",
        "silently lower resolution, frame rate, duration, audio, or sync quality",
        "bypass rights or safety gates",
        "resume the Olympus workflow",
    ]


def _strategy_ready(
    strategy: BobaToolRecoveryStrategyV1,
    case: BobaToolRecoveryCaseV1,
    tools: Sequence[BobaRegisteredRecoveryToolV1],
) -> bool:
    if not case.recovery_eligible or strategy.strategy_type not in _EXECUTION_STRATEGIES:
        return False
    tool = next((item for item in tools if item.tool_id == strategy.tool_id), None)
    if not tool or tool.health_status != "healthy" or not tool.available:
        return False
    if tool.provider_type in {"external_service", "unknown"}:
        return False
    if strategy.capability_id not in {
        "video_render",
        "media_encode_check",
        "frame_extraction",
        "audio_extraction",
    }:
        return False
    config = strategy.configuration_overrides
    if strategy.capability_id in {
        "video_render",
        "audio_extraction",
        "frame_extraction",
    } and not str(config.get("input_artifact_ref") or ""):
        return False
    return not (
        strategy.strategy_type == "segmented_processing"
        and strategy.capability_id not in {"video_render", "media_encode_check"}
    )


def _summary(report: BobaToolRecoveryBrainSetV1) -> BobaToolRecoverySummaryV1:
    healthy = {item.tool_id for item in report.registered_tools if item.health_status == "healthy"}
    unavailable = {
        item.tool_id
        for item in report.registered_tools
        if item.health_status in {"unavailable", "blocked", "incompatible"}
    }
    accepted_attempt_ids = {
        item.recovery_attempt_id
        for item in report.output_validations
        if item.accepted_for_quality_review
    }
    failed_attempts = [
        item
        for item in report.recovery_attempts
        if item.status in {"failed", "timed_out", "blocked", "rejected", "rolled_back"}
    ]
    ready_strategy = next(
        (
            strategy.description
            for plan in report.recovery_plans
            for strategy in plan.ordered_strategies
            if strategy.execution_allowed
        ),
        "",
    )
    highest = next(
        (item.title for item in report.recovery_cases if item.recovery_eligible),
        report.recovery_cases[0].title if report.recovery_cases else "",
    )
    required_actions = [
        "Review and explicitly approve one exact eligible recovery strategy."
        for plan in report.recovery_plans
        if plan.approval_status == "awaiting_approval"
    ]
    required_actions.extend(
        item.blocked_reason for item in report.recovery_cases if item.blocked_reason
    )
    return BobaToolRecoverySummaryV1(
        total_recovery_cases=len(report.recovery_cases),
        eligible_case_count=sum(item.recovery_eligible for item in report.recovery_cases),
        blocked_case_count=sum(not item.recovery_eligible for item in report.recovery_cases),
        health_check_count=len(report.tool_health_results),
        healthy_tool_count=len(healthy),
        unavailable_tool_count=len(unavailable),
        recovery_plan_count=len(report.recovery_plans),
        recovery_attempt_count=len(report.recovery_attempts),
        successful_pending_quality_count=len(accepted_attempt_ids),
        failed_attempt_count=len(failed_attempts),
        timeout_count=sum(item.timeout_occurred for item in report.recovery_attempts),
        rollback_count=len(report.rollback_records),
        fallback_switch_count=sum(
            item.strategy_type == "switch_registered_local_tool"
            for plan in report.recovery_plans
            for item in plan.ordered_strategies
            if any(
                attempt.recovery_strategy_id == item.recovery_strategy_id
                for attempt in report.recovery_attempts
            )
        ),
        checkpoint_block_count=sum(
            item.checkpoint_required and not item.checkpoint_ready
            for item in report.recovery_cases
        ),
        quality_rejection_count=sum(
            not item.required_checks_passed for item in report.output_validations
        ),
        current_highest_priority_case=highest,
        safest_available_strategy=ready_strategy,
        required_human_actions=_unique(required_actions, limit=32),
        limitations=[
            "Technical recovery success still requires Output Quality Reviewer.",
            "Tool Recovery Brain does not resume workflows.",
        ],
    )


def _blocked_report(
    project_id: str,
    source_id: str,
    reason: str,
    capabilities: list[BobaToolCapabilityV1],
    tools: list[BobaRegisteredRecoveryToolV1],
) -> BobaToolRecoveryBrainSetV1:
    case_id = _stable_id("tool_case", project_id, reason)
    case = BobaToolRecoveryCaseV1(
        recovery_case_id=case_id,
        source_repair_case_id="unavailable",
        title="Tool recovery is blocked",
        required_capability="unknown",
        failure_class="unknown",
        failure_evidence=[reason],
        rights_status="unknown",
        safety_status="unknown",
        rollback_ready=False,
        recovery_eligible=False,
        blocked_reason=reason,
        warnings=[reason],
        limitations=["A valid persisted Repair Planner tool-recovery handoff is required."],
    )
    handoff = BobaToolRecoveryHandoffV1(
        handoff_id=_stable_id("tool_handoff", case_id, "human_operator"),
        recovery_case_id=case_id,
        target_module="human_operator",
        reason=reason,
        required_inputs=["valid persisted Repair Planner artifact"],
        required_quality_checks=["rights and safety review"],
        blocked_actions=_default_prohibited_actions(),
        allowed_advisory_actions=["inspect saved Repair Planner metadata"],
        priority="high",
    )
    report = BobaToolRecoveryBrainSetV1(
        project_id=project_id,
        source_id=source_id,
        repair_planner_source="unavailable",
        recovery_cases=[case],
        capability_registry=capabilities,
        registered_tools=tools,
        recovery_handoffs=[handoff],
        recovery_summary=BobaToolRecoverySummaryV1(),
        signal_usage=BobaToolRecoverySignalUsageV1(
            capability_registry_used=True,
            fallback_used=True,
            unavailable_signals=["repair_planner"],
            warnings=[reason],
        ),
        warnings=[reason],
        limitations=[
            "No recovery command was executed.",
            "The Olympus workflow remains paused.",
        ],
    )
    report.recovery_summary = _summary(report)
    return report


def _coerce_planner(
    value: BobaRepairPlannerSetV1 | Mapping[str, Any] | None,
) -> BobaRepairPlannerSetV1 | None:
    if isinstance(value, BobaRepairPlannerSetV1):
        return value
    if isinstance(value, Mapping):
        try:
            return BobaRepairPlannerSetV1.model_validate(value)
        except PydanticValidationError:
            return None
    return None


def _find_by_id(values: Sequence[Any], attribute: str, identifier: str) -> Any | None:
    return next((item for item in values if getattr(item, attribute, "") == identifier), None)


def _priority(value: str) -> BobaToolRecoveryPriorityV1:
    return value if value in {"low", "medium", "high", "urgent"} else "medium"  # type: ignore[return-value]


def _build_handoff(
    case: BobaToolRecoveryCaseV1,
    plan: BobaToolRecoveryPlanV1 | None,
    *,
    target: BobaToolRecoveryHandoffTargetV1,
    reason: str,
    attempt_id: str = "",
    priority: BobaToolRecoveryPriorityV1 = "medium",
) -> BobaToolRecoveryHandoffV1:
    return BobaToolRecoveryHandoffV1(
        handoff_id=_stable_id(
            "tool_handoff",
            case.recovery_case_id,
            plan.recovery_plan_id if plan else "",
            attempt_id,
            target,
            reason,
        ),
        recovery_case_id=case.recovery_case_id,
        recovery_plan_id=plan.recovery_plan_id if plan else "",
        recovery_attempt_id=attempt_id,
        target_module=target,
        reason=reason,
        required_inputs=[
            "Tool Recovery report",
            *([f"recovery attempt {attempt_id}"] if attempt_id else []),
        ],
        required_quality_checks=(
            plan.quality_requirements if plan else case.quality_requirements
        )[:32],
        blocked_actions=_default_prohibited_actions()[:32],
        allowed_advisory_actions=[
            "review bounded recovery evidence",
            "approve or reject the next explicit action",
        ],
        priority=priority,
    )


def _strategy_configuration(
    strategy_type: BobaToolRecoveryStrategyTypeV1,
    base: Mapping[str, Any],
) -> dict[str, Any]:
    config = dict(base)
    if strategy_type == "reduce_thread_usage":
        config.update(
            {
                "encoder_threads": 1,
                "filter_threads": 1,
                "parallel_tasks": 1,
            }
        )
    elif strategy_type == "reduce_memory_pressure":
        config.update(
            {
                "encoder_threads": 1,
                "filter_threads": 1,
                "parallel_tasks": 1,
                "encoder_preset": str(config.get("encoder_preset") or "veryfast"),
            }
        )
    elif strategy_type == "segmented_processing":
        config.update(
            {
                "encoder_threads": min(1, _as_int(config.get("encoder_threads"), 1)),
                "filter_threads": min(1, _as_int(config.get("filter_threads"), 1)),
                "parallel_tasks": 1,
                "segment_seconds": min(
                    60,
                    max(5, _as_int(config.get("segment_seconds"), 30)),
                ),
            }
        )
    return config


def _tool_fallbacks(
    capability_id: str,
    primary_tool_id: str,
    tools: Sequence[BobaRegisteredRecoveryToolV1],
) -> list[BobaRegisteredRecoveryToolV1]:
    return sorted(
        [
            item
            for item in tools
            if item.tool_id != primary_tool_id
            and capability_id in item.capability_ids
            and item.local_only
            and item.installed
            and item.provider_type not in {"external_service", "unknown"}
            and capability_id not in item.prohibited_uses
        ],
        key=lambda item: (item.fallback_priority, item.tool_id),
    )


def _build_recovery_plan(
    *,
    case: BobaToolRecoveryCaseV1,
    source_strategy: BobaRepairStrategyV1 | None,
    checkpoint: BobaRepairCheckpointPlanV1 | None,
    rollback: BobaRepairRollbackPlanV1 | None,
    validation: BobaRepairValidationPlanV1 | None,
    tools: Sequence[BobaRegisteredRecoveryToolV1],
    context: Mapping[str, Any],
) -> BobaToolRecoveryPlanV1:
    plan_id = _stable_id(
        "tool_plan",
        case.recovery_case_id,
        source_strategy.repair_strategy_id if source_strategy else "unknown",
    )
    fallback_tools = _tool_fallbacks(
        case.required_capability,
        case.failing_tool_id,
        tools,
    )
    safe_config, config_warnings = _safe_configuration(context)
    source_attempts = (
        source_strategy.maximum_attempts
        if source_strategy and source_strategy.maximum_attempts
        else DEFAULT_MAX_ATTEMPTS_PER_STRATEGY
    )
    per_strategy = min(DEFAULT_MAX_ATTEMPTS_PER_STRATEGY, source_attempts)
    source_seconds = (
        source_strategy.maximum_recovery_duration_seconds
        if source_strategy and source_strategy.maximum_recovery_duration_seconds
        else DEFAULT_MAX_RECOVERY_SECONDS
    )
    total_seconds = min(DEFAULT_MAX_RECOVERY_SECONDS, source_seconds)
    strategies: list[BobaToolRecoveryStrategyV1] = []
    order = 1
    for strategy_type in _strategy_specs(case.failure_class):
        candidate_tools = (
            fallback_tools
            if strategy_type == "switch_registered_local_tool"
            else [
                item
                for item in tools
                if item.tool_id == case.failing_tool_id
            ]
        )
        if not candidate_tools:
            candidate_tools = [
                BobaRegisteredRecoveryToolV1(
                    tool_id=case.failing_tool_id or "unavailable",
                    display_name=case.failing_tool_id or "Unavailable provider",
                    provider_type="unknown",
                    capability_ids=[case.required_capability],
                    installed=False,
                    health_status="unavailable",
                )
            ]
        if strategy_type in {
            "stop_processing",
            "human_manual_action",
            "collect_more_evidence",
        }:
            candidate_tools = candidate_tools[:1]
        for tool in candidate_tools:
            description, rationale, quality_effect = _strategy_description(strategy_type)
            config = _strategy_configuration(strategy_type, safe_config)
            strategy_id = _stable_id(
                "tool_strategy",
                plan_id,
                strategy_type,
                tool.tool_id,
                _canonical(config),
            )
            warnings = list(config_warnings)
            limitations: list[str] = []
            if strategy_type == "segmented_processing":
                limitations.append(
                    "Segmented recovery is limited to the registered FFmpeg video-render "
                    "and media-encode adapters and a maximum of 16 bounded segments."
                )
            if strategy_type == "regenerate_temporary_state":
                limitations.append(
                    "Only recovery-owned temporary state may be regenerated."
                )
            if tool.provider_type == "external_service":
                limitations.append("External-service execution is blocked in V1.")
            strategy = BobaToolRecoveryStrategyV1(
                recovery_strategy_id=strategy_id,
                recovery_plan_id=plan_id,
                order=order,
                strategy_type=strategy_type,
                tool_id=tool.tool_id,
                capability_id=case.required_capability,
                description=description,
                rationale=rationale,
                configuration_overrides=config,
                expected_result=(
                    "A new recovery-owned artifact passes required technical checks."
                    if strategy_type in _EXECUTION_STRATEGIES
                    else "Recovery remains paused pending the stated next action."
                ),
                expected_quality_effect=quality_effect,
                expected_resource_effect=(
                    "Lower bounded resource pressure."
                    if strategy_type
                    in {
                        "reduce_thread_usage",
                        "reduce_memory_pressure",
                        "segmented_processing",
                    }
                    else "No unapproved resource or quality change."
                ),
                requires_checkpoint=case.checkpoint_required,
                requires_tool_switch=strategy_type == "switch_registered_local_tool",
                maximum_attempts=per_strategy,
                timeout_seconds=min(
                    DEFAULT_MAX_ATTEMPT_SECONDS,
                    max(1, _as_int(config.get("timeout_seconds"), DEFAULT_MAX_ATTEMPT_SECONDS)),
                    total_seconds,
                ),
                failure_stop_condition=(
                    "Stop after one repeated identical failure or any required validation "
                    "failure, approval mismatch, path violation, or safety/rights block."
                ),
                success_condition=(
                    "The generated output passes every required technical check and is "
                    "handed to Output Quality Reviewer."
                ),
                rollback_reference=rollback.rollback_plan_id if rollback else "",
                warnings=_unique(warnings, limit=24),
                limitations=_unique(limitations, limit=24),
            )
            strategy.execution_allowed = _strategy_ready(strategy, case, tools)
            strategies.append(strategy)
            order += 1
    return BobaToolRecoveryPlanV1(
        recovery_plan_id=plan_id,
        recovery_case_id=case.recovery_case_id,
        approved_repair_strategy_id=(
            source_strategy.repair_strategy_id if source_strategy else ""
        ),
        required_capability=case.required_capability,
        primary_tool_id=case.failing_tool_id,
        candidate_fallback_tool_ids=[item.tool_id for item in fallback_tools],
        ordered_strategies=strategies,
        retry_budget={
            "maximum_attempts_per_strategy": per_strategy,
            "maximum_total_attempts": DEFAULT_MAX_TOTAL_ATTEMPTS,
            "maximum_repeated_identical_failure": 1,
        },
        time_budget_seconds=total_seconds,
        checkpoint_requirements={
            "required": case.checkpoint_required,
            "ready": case.checkpoint_ready,
            "plan_id": checkpoint.checkpoint_plan_id if checkpoint else "",
            "reference": str(context.get("checkpoint_reference") or "")[:500],
        },
        rollback_requirements={
            "required": True,
            "ready": case.rollback_ready,
            "plan_id": rollback.rollback_plan_id if rollback else "",
            "recovery_owned_outputs_only": True,
        },
        quality_requirements=case.quality_requirements,
        validation_requirements=_validation_requirements(validation),
        approval_status="awaiting_approval" if case.recovery_eligible else "planning_only",
        execution_status="not_started" if case.recovery_eligible else "blocked",
        prohibited_actions=_default_prohibited_actions(),
        stop_conditions=_unique(
            [
                *(source_strategy.stop_conditions if source_strategy else []),
                "retry budget exhausted",
                "total recovery time exhausted",
                "identical failure repeated",
                "required validation fails",
                "rollback state becomes uncertain",
            ],
            limit=32,
        ),
        escalation_conditions=_unique(
            [
                source_strategy.escalation_condition if source_strategy else "",
                "No new safe approved strategy remains.",
                "The failure evidence changes or indicates code/checkpoint repair.",
            ],
            limit=32,
        ),
        warnings=_unique(config_warnings, limit=32),
        limitations=[
            "Approval is required before recovery execution.",
            "Technical validation is not final output acceptance.",
            "The workflow remains paused.",
        ],
    )


def _eligibility_blockers(
    *,
    case: BobaRepairPlanningCaseV1,
    strategy: BobaRepairStrategyV1 | None,
    failure_class: BobaToolFailureClassV1,
    rights_status: str,
    safety_status: str,
    checkpoint_required: bool,
    checkpoint_ready: bool,
    rollback: BobaRepairRollbackPlanV1 | None,
    validation: BobaRepairValidationPlanV1 | None,
    quality_requirements: Sequence[str],
) -> list[str]:
    blockers: list[str] = []
    if case.repair_scope != "tool":
        blockers.append(f"Repair scope is {case.repair_scope}, not tool recovery.")
    if failure_class not in _SUPPORTED_FAILURE_CLASSES:
        blockers.append(f"Failure class {failure_class} is not executable in V1.")
    if rights_status.lower() in {"unknown", "blocked", "denied", "unsafe"}:
        blockers.append(f"Rights status is {rights_status}.")
    if safety_status.lower() in {"blocked", "denied", "unsafe"}:
        blockers.append(f"Safety status is {safety_status}.")
    if checkpoint_required and not checkpoint_ready:
        blockers.append("Required checkpoint is missing or unvalidated.")
    if rollback is None or not rollback.rollback_required or not rollback.rollback_steps:
        blockers.append("A usable rollback plan is unavailable.")
    if validation is None or not (
        validation.required_validators or validation.post_repair_checks
    ):
        blockers.append("A usable post-recovery validation plan is unavailable.")
    if not quality_requirements:
        blockers.append("Non-negotiable quality requirements are unclear.")
    if strategy is None:
        blockers.append("The selected Repair Planner strategy is unavailable.")
    else:
        if strategy.requires_code_change:
            blockers.append("The strategy requires source-code repair.")
        if strategy.requires_package_installation:
            blockers.append("The strategy requires package installation.")
        if strategy.requires_service_restart:
            blockers.append("The strategy requires a service restart.")
        if strategy.requires_external_access:
            blockers.append("The strategy requires external access.")
        if strategy.requires_paid_service:
            blockers.append("The strategy requires a paid service.")
        if strategy.destructiveness in {"high", "blocked"}:
            blockers.append("The strategy is destructive or blocked.")
    return _unique(blockers, limit=32)


def verify_recovery_approval(
    plan: BobaToolRecoveryPlanV1,
    strategy: BobaToolRecoveryStrategyV1,
    approval: BobaToolRecoveryApprovalV1,
) -> list[str]:
    """Return every exact approval-binding mismatch."""

    errors: list[str] = []
    if not approval.approved:
        errors.append("Recovery approval is not granted.")
    if approval.explicit_confirmation != EXPLICIT_RECOVERY_CONFIRMATION:
        errors.append("Explicit recovery confirmation does not match the required text.")
    if approval.recovery_case_id != plan.recovery_case_id:
        errors.append("Approval recovery-case ID does not match.")
    if approval.recovery_plan_id != plan.recovery_plan_id:
        errors.append("Approval recovery-plan ID does not match.")
    if approval.approved_strategy_ids != [strategy.recovery_strategy_id]:
        errors.append("Approval must bind exactly one selected recovery strategy.")
    if approval.approved_tool_ids != [strategy.tool_id]:
        errors.append("Approval tool IDs do not exactly match the selected provider.")
    if _canonical(approval.approved_configuration_overrides) != _canonical(
        strategy.configuration_overrides
    ):
        errors.append("Approved temporary settings do not exactly match.")
    if _canonical(approval.approved_retry_budget) != _canonical(plan.retry_budget):
        errors.append("Approved retry budget does not exactly match.")
    if approval.approved_time_budget_seconds != plan.time_budget_seconds:
        errors.append("Approved total time budget does not exactly match.")
    if approval.approved_quality_requirements != plan.quality_requirements:
        errors.append("Approved quality requirements do not exactly match.")
    checkpoint_reference = str(plan.checkpoint_requirements.get("reference") or "")
    if approval.approved_checkpoint_reference != checkpoint_reference:
        errors.append("Approved checkpoint reference does not exactly match.")
    if approval.approval_expires_at is None or _iso_expired(
        approval.approval_expires_at
    ):
        errors.append("Recovery approval is expired or has no bounded expiration.")
    if not approval.approved_at:
        errors.append("Recovery approval timestamp is missing.")
    if not approval.approved_by.strip():
        errors.append("Recovery approver identity is missing.")
    return errors


def fingerprint_recovery_strategy(
    strategy: BobaToolRecoveryStrategyV1,
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "tool": strategy.tool_id,
                "capability": strategy.capability_id,
                "mode": strategy.strategy_type,
                "settings": strategy.configuration_overrides,
            }
        ).encode("utf-8")
    ).hexdigest()


def validate_recovery_command_safety(
    command: BobaRecoveryCommandV1,
    tools: Sequence[BobaRegisteredRecoveryToolV1],
    registry: Mapping[str, Sequence[BobaRecoveryCommandCategoryV1]],
) -> list[str]:
    errors: list[str] = []
    executable_name = Path(command.executable).name.lower()
    if executable_name in _FORBIDDEN_EXECUTABLES:
        errors.append("The executable is prohibited.")
    tool = next((item for item in tools if item.tool_id == command.tool_id), None)
    if tool is None:
        errors.append("The command references an unregistered tool.")
    else:
        configured_name = Path(tool.executable or tool.package_name).name.lower()
        if tool.provider_type == "executable" and executable_name != configured_name:
            errors.append("The executable does not match the registered tool.")
        if tool.provider_type == "external_service":
            errors.append("External-service commands are blocked.")
    if command.category not in registry.get(command.tool_id, ()):
        errors.append("The command category is not registered for this tool.")
    if command.shell_used:
        errors.append("Shell execution is prohibited.")
    if not command.network_forbidden:
        errors.append("Network access must be forbidden.")
    if command.environment_policy != "sanitized_local_only":
        errors.append("Only the sanitized local environment policy is allowed.")
    if not command.working_directory_scope.replace("\\", "/").startswith(
        "work/boba/tool_recovery/workspaces/"
    ):
        errors.append("Working directory is outside the recovery workspace.")
    option_allowlist = (
        _FFMPEG_ALLOWED_OPTIONS
        if executable_name in {"ffmpeg", "ffmpeg.exe"}
        else _FFPROBE_ALLOWED_OPTIONS
        if executable_name in {"ffprobe", "ffprobe.exe"}
        else set()
    )
    for argument in command.arguments:
        lowered = argument.strip().lower()
        if _CONTROL.search(argument) or _SHELL_TOKEN.search(argument):
            errors.append("Shell metacharacters, chaining, pipes, or redirects are prohibited.")
            break
        if lowered in _FORBIDDEN_ARGUMENTS:
            errors.append(f"Prohibited command argument: {lowered}.")
            break
        if lowered.startswith(_NETWORK_PREFIXES) or _URL_SCHEME.match(lowered):
            errors.append("Network or URL arguments are prohibited.")
            break
        if lowered.startswith("-") and option_allowlist and lowered not in option_allowlist:
            errors.append(f"Unallowlisted command option: {argument}.")
            break
    if "-shortest" in command.arguments:
        errors.append("FFmpeg -shortest is prohibited because it can hide sync truncation.")
    return _unique(errors, limit=32)


def _clean_relative_reference(value: str, *, field_name: str) -> PurePosixPath:
    text = value.strip().replace("\\", "/")
    if not text or _CONTROL.search(text):
        raise ValidationError(f"{field_name} is missing or invalid.")
    if _WINDOWS_ABSOLUTE.match(text) or text.startswith(("/", "//")):
        raise ValidationError(f"{field_name} must be a repository-relative reference.")
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError(f"{field_name} contains path traversal.")
    return path


def validate_recovery_paths(
    *,
    repository_root: Path,
    workspace_root: Path,
    input_reference: str,
    output_filename: str,
    approved_input_roots: Sequence[Path],
) -> tuple[Path, Path]:
    """Resolve one read-only input and one new recovery-owned output safely."""

    relative_input = _clean_relative_reference(
        input_reference,
        field_name="Recovery input reference",
    )
    input_path = (repository_root / Path(*relative_input.parts)).resolve(strict=False)
    approved = [path.resolve() for path in approved_input_roots]
    if not any(input_path == root or root in input_path.parents for root in approved):
        raise ValidationError("Recovery input is outside approved local input roots.")
    if not input_path.is_file():
        raise ValidationError("Recovery input artifact is unavailable.")
    for parent in [input_path, *input_path.parents]:
        if parent == repository_root.parent:
            break
        if parent.is_symlink() and not any(
            parent.resolve() == root or root in parent.resolve().parents for root in approved
        ):
            raise ValidationError("Recovery input uses a symlink outside approved roots.")
    relative_output = _clean_relative_reference(
        output_filename,
        field_name="Recovery output filename",
    )
    if len(relative_output.parts) != 1:
        raise ValidationError("Recovery output must be a new file in the attempt output folder.")
    output_directory = (workspace_root / "outputs").resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    if workspace_root.resolve() not in output_directory.parents:
        raise ValidationError("Recovery output folder escaped the attempt workspace.")
    output_path = (output_directory / relative_output.name).resolve()
    if output_directory not in output_path.parents:
        raise ValidationError("Recovery output escaped the attempt workspace.")
    if output_path.exists():
        raise ValidationError("Recovery output already exists and cannot be overwritten.")
    return input_path, output_path


def _sanitized_environment(workspace: Path) -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
        }
        and not _SECRET.search(key)
    }
    allowed["TEMP"] = str(workspace)
    allowed["TMP"] = str(workspace)
    allowed["NO_PROXY"] = "*"
    return allowed


def _bounded_file_text(handle: Any, limit: int) -> tuple[str, bool]:
    handle.flush()
    handle.seek(0, 2)
    size = int(handle.tell())
    offset = max(0, size - limit)
    handle.seek(offset)
    data = handle.read(limit)
    if offset and b"\n" in data:
        data = data.split(b"\n", 1)[1]
    text = data.decode("utf-8", "replace")
    return _safe_text(text, maximum=4_000), size > limit


def execute_allowlisted_recovery_command(
    arguments: Sequence[str],
    *,
    workspace: Path,
    timeout_seconds: float,
    output_limit_bytes: int,
) -> _ProcessResult:
    """Execute one already-validated argument vector without a shell."""

    started = time.monotonic()
    with (
        tempfile.TemporaryFile(prefix="boba-tool-stdout-", dir=workspace) as stdout,
        tempfile.TemporaryFile(prefix="boba-tool-stderr-", dir=workspace) as stderr,
    ):
        try:
            completed = subprocess.run(
                list(arguments),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                shell=False,
                cwd=workspace,
                env=_sanitized_environment(workspace),
                timeout=timeout_seconds,
            )
            exit_code: int | None = completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            exit_code = None
            timed_out = True
        except OSError as exc:
            exit_code = None
            timed_out = False
            stderr.write(str(exc).encode("utf-8", "replace"))
        stdout_text, stdout_truncated = _bounded_file_text(stdout, output_limit_bytes)
        stderr_text, stderr_truncated = _bounded_file_text(stderr, output_limit_bytes)
    return _ProcessResult(
        exit_code=exit_code,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_seconds=max(0.0, time.monotonic() - started),
        timed_out=timed_out,
        output_truncated=stdout_truncated or stderr_truncated,
    )


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_fps(value: Any) -> float | None:
    text = str(value or "")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        den = _as_float(denominator, 0.0)
        return round(_as_float(numerator, 0.0) / den, 3) if den else None
    parsed = _as_float(text, 0.0)
    return round(parsed, 3) if parsed > 0 else None


def _parse_probe(payload: Mapping[str, Any]) -> dict[str, Any]:
    streams = [item for item in _as_list(payload.get("streams")) if isinstance(item, Mapping)]
    format_data = _as_dict(payload.get("format"))
    video = next(
        (_as_dict(item) for item in streams if item.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (_as_dict(item) for item in streams if item.get("codec_type") == "audio"),
        {},
    )
    container_duration = _as_float(format_data.get("duration"), 0.0)
    video_duration = _as_float(video.get("duration"), container_duration)
    audio_duration = _as_float(audio.get("duration"), container_duration if audio else 0.0)
    return {
        "container_duration": container_duration,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
        "width": _as_int(video.get("width"), 0),
        "height": _as_int(video.get("height"), 0),
        "fps": _parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "has_audio": bool(audio),
    }


class BobaToolRecoveryBrainV1:
    """Capability-first, finite, approval-bound local tool recovery."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        workspace_root: str | Path | None = None,
        approved_input_roots: Sequence[str | Path] | None = None,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        transcription_provider: str = "noop",
        mode: BobaToolRecoveryModeV1 = "plan_and_health_check",
    ) -> None:
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.workspace_root = (
            Path(workspace_root).expanduser().resolve()
            if workspace_root is not None
            else (
                self.repository_root
                / "work"
                / "boba"
                / "tool_recovery"
                / "workspaces"
            ).resolve()
        )
        default_roots = [
            self.repository_root / "work",
            self.repository_root / "storage_data",
            self.repository_root / "media",
        ]
        self.approved_input_roots = tuple(
            Path(item).expanduser().resolve()
            for item in (approved_input_roots or default_roots)
        )
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.transcription_provider = transcription_provider
        self.mode = mode

    def plan(
        self,
        project_id: str,
        repair_planner: BobaRepairPlannerSetV1 | Mapping[str, Any] | None,
        *,
        source_id: str | None = None,
        selected_handoff_id: str | None = None,
        selected_repair_strategy_id: str | None = None,
        failure_context: Mapping[str, Any] | None = None,
        run_health_checks: bool | None = None,
    ) -> BobaToolRecoveryBrainSetV1:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError("Invalid BOBA project id.")
        context = _as_dict(failure_context)
        capabilities, tools = build_minimal_capability_registry(
            ffmpeg_binary=self.ffmpeg_binary,
            ffprobe_binary=self.ffprobe_binary,
            transcription_provider=self.transcription_provider,
        )
        planner = _coerce_planner(repair_planner)
        effective_source_id = source_id or (planner.source_id if planner else project_id)
        if planner is None:
            return _blocked_report(
                project_id,
                effective_source_id,
                "Persisted Repair Planner data is missing or malformed.",
                capabilities,
                tools,
            )
        if planner.project_id != project_id:
            return _blocked_report(
                project_id,
                effective_source_id,
                "Repair Planner project identity does not match.",
                capabilities,
                tools,
            )
        handoffs = [
            item
            for item in planner.execution_handoffs
            if item.target_module == "tool_recovery_brain"
            and (selected_handoff_id is None or item.handoff_id == selected_handoff_id)
            and (
                selected_repair_strategy_id is None
                or item.repair_strategy_id == selected_repair_strategy_id
            )
        ]
        if not handoffs:
            return _blocked_report(
                project_id,
                effective_source_id,
                "No valid Repair Planner Tool Recovery handoff is available.",
                capabilities,
                tools,
            )
        report = BobaToolRecoveryBrainSetV1(
            project_id=project_id,
            source_id=effective_source_id,
            repair_planner_source=(
                f"work/boba/projects/{project_id}/repair_planner/index.json"
            ),
            capability_registry=capabilities,
            registered_tools=tools,
            recovery_summary=BobaToolRecoverySummaryV1(),
            signal_usage=BobaToolRecoverySignalUsageV1(
                repair_planner_used=True,
                repair_planner_artifact_read=True,
                root_cause_references_used=True,
                capability_registry_used=True,
            ),
            limitations=[
                "Only registered already-installed local providers are considered.",
                "No recovery executes without exact unexpired approval.",
                "The workflow remains paused after technical recovery.",
            ],
        )
        for handoff in handoffs:
            repair_case = _find_by_id(
                planner.repair_cases,
                "repair_case_id",
                handoff.repair_case_id,
            )
            if not isinstance(repair_case, BobaRepairPlanningCaseV1):
                report.warnings.append(
                    f"Repair case {handoff.repair_case_id} is unavailable."
                )
                continue
            strategy_id = selected_repair_strategy_id or handoff.repair_strategy_id
            source_strategy = _find_by_id(
                planner.repair_strategies,
                "repair_strategy_id",
                strategy_id,
            )
            checkpoint = _find_by_id(
                planner.checkpoint_plans,
                "checkpoint_plan_id",
                handoff.checkpoint_plan_id or repair_case.checkpoint_plan_id,
            )
            rollback = _find_by_id(
                planner.rollback_plans,
                "rollback_plan_id",
                handoff.rollback_plan_id or repair_case.rollback_plan_id,
            )
            validation = _find_by_id(
                planner.validation_plans,
                "validation_plan_id",
                handoff.validation_plan_id or repair_case.validation_plan_id,
            )
            quality = _find_by_id(
                planner.quality_preservation_plans,
                "quality_preservation_plan_id",
                repair_case.quality_preservation_plan_id,
            )
            approval_gate = _find_by_id(
                planner.approval_gates,
                "approval_gate_id",
                handoff.approval_gate_id or repair_case.approval_gate_id,
            )
            source_strategy = (
                source_strategy if isinstance(source_strategy, BobaRepairStrategyV1) else None
            )
            checkpoint = (
                checkpoint
                if isinstance(checkpoint, BobaRepairCheckpointPlanV1)
                else None
            )
            rollback = (
                rollback if isinstance(rollback, BobaRepairRollbackPlanV1) else None
            )
            validation = (
                validation
                if isinstance(validation, BobaRepairValidationPlanV1)
                else None
            )
            quality = (
                quality if isinstance(quality, BobaQualityPreservationPlanV1) else None
            )
            approval_gate = (
                approval_gate
                if isinstance(approval_gate, BobaRepairApprovalGateV1)
                else None
            )
            capability_id = _infer_capability(
                handoff,
                repair_case,
                source_strategy,
                context,
            )
            failure_class = classify_tool_failure(repair_case, source_strategy, context)
            rights_status = str(
                context.get("rights_status")
                or (
                    "review_required"
                    if approval_gate and approval_gate.rights_gate_required
                    else "not_required"
                )
            )
            safety_status = str(context.get("safety_status") or "review_required")
            checkpoint_required = bool(
                checkpoint and checkpoint.checkpoint_required
            ) or bool(source_strategy and source_strategy.requires_checkpoint)
            checkpoint_ready = (
                bool(context.get("checkpoint_ready"))
                if checkpoint_required
                else True
            )
            requirements = _quality_requirements(handoff, quality)
            blockers = _eligibility_blockers(
                case=repair_case,
                strategy=source_strategy,
                failure_class=failure_class,
                rights_status=rights_status,
                safety_status=safety_status,
                checkpoint_required=checkpoint_required,
                checkpoint_ready=checkpoint_ready,
                rollback=rollback,
                validation=validation,
                quality_requirements=requirements,
            )
            recovery_case_id = _stable_id(
                "tool_case",
                project_id,
                repair_case.repair_case_id,
                strategy_id,
            )
            recovery_case = BobaToolRecoveryCaseV1(
                recovery_case_id=recovery_case_id,
                source_repair_case_id=repair_case.repair_case_id,
                source_repair_strategy_ids=[strategy_id] if strategy_id else [],
                title=repair_case.title,
                target_module=repair_case.primary_module,
                workflow_stage=repair_case.workflow_stage,
                required_capability=capability_id,
                failing_tool_id=_infer_primary_tool(capability_id, context),
                failure_class=failure_class,
                failure_evidence=_unique(
                    [
                        repair_case.selected_root_cause_summary,
                        handoff.reason,
                        *[str(item) for item in _as_list(context.get("failure_evidence"))],
                    ],
                    limit=64,
                ),
                rights_status=rights_status,
                safety_status=safety_status,
                checkpoint_required=checkpoint_required,
                checkpoint_ready=checkpoint_ready,
                rollback_ready=bool(
                    rollback and rollback.rollback_required and rollback.rollback_steps
                ),
                quality_requirements=requirements,
                approved_strategy_ids=[strategy_id] if strategy_id else [],
                recovery_eligible=not blockers,
                blocked_reason=" ".join(blockers),
                confidence=(
                    repair_case.confidence
                    if not blockers
                    else min(repair_case.confidence, 0.5)
                ),
                warnings=_unique(
                    [
                        *repair_case.warnings,
                        *(approval_gate.warnings if approval_gate else []),
                    ],
                    limit=32,
                ),
                limitations=_unique(
                    [
                        *repair_case.limitations,
                        *(
                            ["External-service recovery is blocked in V1."]
                            if failure_class == "external_service_unavailable"
                            else []
                        ),
                    ],
                    limit=32,
                ),
            )
            recovery_plan = _build_recovery_plan(
                case=recovery_case,
                source_strategy=source_strategy,
                checkpoint=checkpoint,
                rollback=rollback,
                validation=validation,
                tools=tools,
                context=context,
            )
            report.recovery_cases.append(recovery_case)
            report.recovery_plans.append(recovery_plan)
            if blockers:
                target: BobaToolRecoveryHandoffTargetV1 = "human_operator"
                if failure_class == "checkpoint_problem" or (
                    checkpoint_required and not checkpoint_ready
                ):
                    target = "checkpoint_recovery_manager"
                elif source_strategy and source_strategy.requires_code_change:
                    target = "code_surgeon"
                report.recovery_handoffs.append(
                    _build_handoff(
                        recovery_case,
                        recovery_plan,
                        target=target,
                        reason=recovery_case.blocked_reason,
                        priority=_priority(handoff.priority),
                    )
                )
        if not report.recovery_cases:
            return _blocked_report(
                project_id,
                effective_source_id,
                "Repair Planner Tool Recovery handoffs could not be resolved.",
                capabilities,
                tools,
            )
        should_health_check = (
            self.mode == "plan_and_health_check"
            if run_health_checks is None
            else run_health_checks
        )
        if should_health_check:
            report = self.run_health_checks(report)
        report.recovery_summary = _summary(report)
        return report

    def _health_workspace(self) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = (self.workspace_root / f"health_{uuid4().hex}").resolve()
        if self.workspace_root not in workspace.parents:
            raise ValidationError("Health-check workspace escaped the recovery root.")
        workspace.mkdir(parents=False, exist_ok=False)
        return workspace

    def run_health_checks(
        self,
        report: BobaToolRecoveryBrainSetV1,
        *,
        tool_ids: Sequence[str] | None = None,
    ) -> BobaToolRecoveryBrainSetV1:
        selected = set(tool_ids or [item.tool_id for item in report.registered_tools])
        unknown = selected - {item.tool_id for item in report.registered_tools}
        if unknown:
            raise ValidationError(
                "Health check requested an unregistered tool.",
                details={"tool_ids": sorted(unknown)},
            )
        workspace = self._health_workspace()
        try:
            results: list[BobaToolHealthResultV1] = []
            updated_tools: list[BobaRegisteredRecoveryToolV1] = []
            for tool in report.registered_tools:
                if tool.tool_id not in selected:
                    updated_tools.append(tool)
                    continue
                result = self._run_health_check(tool, workspace)
                results.append(result)
                status: BobaToolHealthStatusV1 = (
                    "healthy"
                    if result.status == "healthy"
                    else "degraded"
                    if result.status == "degraded"
                    else "incompatible"
                    if result.status == "incompatible"
                    else "blocked"
                    if result.status == "blocked"
                    else "unavailable"
                    if result.status in {"unavailable", "timed_out"}
                    else "unknown"
                )
                updated_tools.append(
                    tool.model_copy(
                        update={
                            "available": result.status == "healthy",
                            "health_status": status,
                            "version": result.version_detected or tool.version,
                        }
                    )
                )
            report.registered_tools = updated_tools
            report.tool_health_results.extend(results)
            report.signal_usage.local_health_checks_executed = bool(results)
            case_by_id = {item.recovery_case_id: item for item in report.recovery_cases}
            for plan in report.recovery_plans:
                case = case_by_id.get(plan.recovery_case_id)
                if case is None:
                    continue
                for strategy in plan.ordered_strategies:
                    strategy.execution_allowed = _strategy_ready(
                        strategy,
                        case,
                        report.registered_tools,
                    )
                if any(item.execution_allowed for item in plan.ordered_strategies):
                    plan.execution_status = "ready"
                elif plan.execution_status != "blocked":
                    plan.execution_status = "health_check_only"
            report.recovery_summary = _summary(report)
            return report
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def _run_health_check(
        self,
        tool: BobaRegisteredRecoveryToolV1,
        workspace: Path,
    ) -> BobaToolHealthResultV1:
        check = tool.health_check
        if tool.provider_type == "external_service":
            return BobaToolHealthResultV1(
                health_result_id=_stable_id(
                    "health_result",
                    tool.tool_id,
                    uuid4().hex,
                ),
                health_check_id=(
                    check.health_check_id
                    if check is not None
                    else _stable_id("health_check", tool.tool_id, "blocked")
                ),
                tool_id=tool.tool_id,
                status="blocked",
                confidence=1.0,
                warnings=["External-service health checks are blocked in V1."],
            )
        if check is None:
            return BobaToolHealthResultV1(
                health_result_id=_stable_id("health_result", tool.tool_id, uuid4().hex),
                health_check_id=_stable_id("health_check", tool.tool_id, "missing"),
                tool_id=tool.tool_id,
                status="unknown",
                confidence=0.0,
                warnings=["No registered health check exists."],
            )
        if check.check_type == "internal_health":
            return BobaToolHealthResultV1(
                health_result_id=_stable_id("health_result", check.health_check_id, uuid4().hex),
                health_check_id=check.health_check_id,
                tool_id=tool.tool_id,
                status="healthy",
                bounded_stdout_summary="Registered internal validator is available.",
                confidence=1.0,
            )
        if check.check_type == "import_available":
            available = bool(tool.package_name and _module_available(tool.package_name))
            return BobaToolHealthResultV1(
                health_result_id=_stable_id("health_result", check.health_check_id, uuid4().hex),
                health_check_id=check.health_check_id,
                tool_id=tool.tool_id,
                status="healthy" if available else "unavailable",
                bounded_stdout_summary=(
                    "Registered local Python provider is importable."
                    if available
                    else "Registered local Python provider is unavailable."
                ),
                confidence=1.0,
                warnings=(
                    []
                    if available
                    else ["No package installation was attempted."]
                ),
            )
        executable = shutil.which(tool.executable)
        if not executable and Path(tool.executable).is_file():
            executable = str(Path(tool.executable).resolve())
        if not executable:
            return BobaToolHealthResultV1(
                health_result_id=_stable_id("health_result", check.health_check_id, uuid4().hex),
                health_check_id=check.health_check_id,
                tool_id=tool.tool_id,
                status="unavailable",
                confidence=1.0,
                warnings=["Configured executable is unavailable; no install was attempted."],
            )
        result = execute_allowlisted_recovery_command(
            [executable, *check.arguments],
            workspace=workspace,
            timeout_seconds=check.timeout_seconds,
            output_limit_bytes=check.output_limit_bytes,
        )
        first_line = (result.stdout or result.stderr).split(" ", 8)[:8]
        version = " ".join(first_line)[:160]
        return BobaToolHealthResultV1(
            health_result_id=_stable_id("health_result", check.health_check_id, uuid4().hex),
            health_check_id=check.health_check_id,
            tool_id=tool.tool_id,
            status=(
                "timed_out"
                if result.timed_out
                else "healthy"
                if result.exit_code in check.expected_exit_codes
                else "unavailable"
            ),
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            version_detected=version,
            bounded_stdout_summary=result.stdout,
            bounded_stderr_summary=result.stderr,
            output_truncated=result.output_truncated,
            confidence=1.0,
        )

    def _attempt_workspace(self, attempt_id: str) -> Path:
        if not _IDENTIFIER.fullmatch(attempt_id):
            raise ValidationError("Invalid recovery attempt id.")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = (self.workspace_root / attempt_id).resolve()
        if self.workspace_root not in workspace.parents:
            raise ValidationError("Recovery attempt workspace escaped the configured root.")
        workspace.mkdir(parents=False, exist_ok=False)
        return workspace

    def _resolve_tool_executable(
        self,
        tool: BobaRegisteredRecoveryToolV1,
    ) -> str:
        executable = shutil.which(tool.executable)
        if not executable and Path(tool.executable).is_file():
            executable = str(Path(tool.executable).resolve())
        if not executable:
            raise ValidationError("Registered recovery executable is unavailable.")
        return executable

    def _build_command(
        self,
        strategy: BobaToolRecoveryStrategyV1,
        tool: BobaRegisteredRecoveryToolV1,
        workspace: Path,
        attempt_id: str,
    ) -> _BuiltCommand:
        config = strategy.configuration_overrides
        output_name = str(config.get("output_filename") or "recovered.mp4")
        input_path: Path | None = None
        output_path: Path | None = None
        if strategy.capability_id in {
            "video_render",
            "audio_extraction",
            "frame_extraction",
        }:
            input_path, output_path = validate_recovery_paths(
                repository_root=self.repository_root,
                workspace_root=workspace,
                input_reference=str(config.get("input_artifact_ref") or ""),
                output_filename=output_name,
                approved_input_roots=self.approved_input_roots,
            )
        elif strategy.capability_id == "media_encode_check":
            relative_output = _clean_relative_reference(
                output_name,
                field_name="Recovery output filename",
            )
            if len(relative_output.parts) != 1:
                raise ValidationError("Recovery output must be a file name.")
            output_directory = workspace / "outputs"
            output_directory.mkdir(parents=True, exist_ok=True)
            output_path = (output_directory / relative_output.name).resolve()
            if output_directory.resolve() not in output_path.parents or output_path.exists():
                raise ValidationError("Recovery output path is unsafe or already exists.")
        else:
            raise ValidationError(
                "The selected capability has no registered output-producing V1 adapter."
            )
        assert output_path is not None
        executable = self._resolve_tool_executable(tool)
        timeout = min(
            strategy.timeout_seconds,
            max(1, _as_int(config.get("timeout_seconds"), strategy.timeout_seconds)),
        )
        category: BobaRecoveryCommandCategoryV1
        if strategy.capability_id == "media_encode_check":
            category = "encode_check"
            width = max(64, min(3_840, _as_int(config.get("expected_width"), 320)))
            height = max(64, min(2_160, _as_int(config.get("expected_height"), 180)))
            fps = max(1, min(120, _as_int(config.get("expected_fps"), 24)))
            duration = max(
                0.25,
                min(10.0, _as_float(config.get("expected_duration_seconds"), 1.0)),
            )
            args = [
                executable,
                "-hide_banner",
                "-nostats",
                "-loglevel",
                "warning",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size={width}x{height}:rate={fps}:duration={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=48000:duration={duration}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                str(config.get("encoder_preset") or "veryfast"),
                "-b:v",
                f"{max(250, _as_int(config.get('video_bitrate_kbps'), 800))}k",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-b:a",
                f"{max(64, _as_int(config.get('audio_bitrate_kbps'), 128))}k",
                "-t",
                str(duration),
                str(output_path),
            ]
        elif strategy.capability_id == "audio_extraction":
            category = "audio_extract"
            assert input_path is not None
            args = [
                executable,
                "-hide_banner",
                "-nostats",
                "-loglevel",
                "warning",
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(output_path),
            ]
        elif strategy.capability_id == "frame_extraction":
            category = "frame_extract"
            assert input_path is not None
            timestamp = max(
                0.0,
                _as_float(config.get("source_window_start_seconds"), 0.0),
            )
            args = [
                executable,
                "-hide_banner",
                "-nostats",
                "-loglevel",
                "warning",
                "-y",
                "-ss",
                str(timestamp),
                "-i",
                str(input_path),
                "-frames:v",
                "1",
                str(output_path),
            ]
        else:
            category = "render_retry"
            assert input_path is not None
            width = max(64, min(3_840, _as_int(config.get("expected_width"), 1080)))
            height = max(64, min(3_840, _as_int(config.get("expected_height"), 1920)))
            fps = max(1, min(120, _as_int(config.get("expected_fps"), 30)))
            duration = max(
                0.1,
                min(
                    3_600.0,
                    _as_float(config.get("expected_duration_seconds"), 0.0),
                ),
            )
            encoder_threads = max(1, min(8, _as_int(config.get("encoder_threads"), 1)))
            filter_threads = max(1, min(8, _as_int(config.get("filter_threads"), 1)))
            video_filter = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}"
            )
            args = [
                executable,
                "-hide_banner",
                "-nostats",
                "-loglevel",
                "warning",
                "-y",
                "-filter_threads",
                str(filter_threads),
                "-filter_complex_threads",
                str(filter_threads),
                "-i",
                str(input_path),
                "-t",
                str(duration),
                "-vf",
                video_filter,
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-r",
                str(fps),
                "-c:v",
                "libx264",
                "-preset",
                str(config.get("encoder_preset") or "veryfast"),
                "-b:v",
                f"{max(500, _as_int(config.get('video_bitrate_kbps'), 8_000))}k",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                str(encoder_threads),
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-b:a",
                f"{max(64, _as_int(config.get('audio_bitrate_kbps'), 192))}k",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        reference_root = self.repository_root
        stored_arguments: list[str] = []
        for argument in args[1:]:
            if input_path is not None and argument == str(input_path):
                stored_arguments.append(
                    str(config.get("input_artifact_ref") or "").replace("\\", "/")
                )
            elif argument == str(output_path):
                stored_arguments.append(
                    str(output_path.relative_to(reference_root)).replace("\\", "/")
                    if reference_root in output_path.parents
                    else (
                        "work/boba/tool_recovery/workspaces/"
                        f"{attempt_id}/outputs/{output_path.name}"
                    )
                )
            else:
                stored_arguments.append(argument)
        record = BobaRecoveryCommandV1(
            recovery_command_id=_stable_id(
                "recovery_command",
                attempt_id,
                strategy.recovery_strategy_id,
                category,
            ),
            tool_id=tool.tool_id,
            executable=tool.executable,
            arguments=stored_arguments,
            working_directory_scope=(
                f"work/boba/tool_recovery/workspaces/{attempt_id}"
            ),
            category=category,
            approved=True,
            timeout_seconds=timeout,
        )
        registry = build_trusted_recovery_command_registry([tool])
        command_errors = validate_recovery_command_safety(record, [tool], registry)
        if command_errors:
            raise ValidationError(
                "Recovery command failed strict safety validation.",
                details={"reasons": command_errors},
            )
        return _BuiltCommand(
            record=record,
            arguments=tuple(args),
            output_path=output_path,
            input_path=input_path,
        )

    def _build_segmented_commands(
        self,
        strategy: BobaToolRecoveryStrategyV1,
        tool: BobaRegisteredRecoveryToolV1,
        workspace: Path,
        attempt_id: str,
    ) -> tuple[
        list[_BuiltCommand],
        Path | None,
        Path,
        list[Path],
        list[tuple[float, int, int, float, bool] | None],
    ]:
        if strategy.capability_id not in {"video_render", "media_encode_check"}:
            raise ValidationError(
                "Segmented recovery supports only registered FFmpeg video rendering "
                "and media encode checks."
            )
        config = strategy.configuration_overrides
        output_name = str(config.get("output_filename") or "recovered.mp4")
        relative_output = _clean_relative_reference(
            output_name,
            field_name="Recovery output filename",
        )
        if len(relative_output.parts) != 1:
            raise ValidationError("Recovery output must be a file name.")
        output_directory = (workspace / "outputs").resolve()
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = (output_directory / relative_output.name).resolve()
        if output_directory not in output_path.parents or output_path.exists():
            raise ValidationError("Recovery output path is unsafe or already exists.")

        input_path: Path | None = None
        if strategy.capability_id == "video_render":
            input_path, checked_output = validate_recovery_paths(
                repository_root=self.repository_root,
                workspace_root=workspace,
                input_reference=str(config.get("input_artifact_ref") or ""),
                output_filename=output_name,
                approved_input_roots=self.approved_input_roots,
            )
            output_path = checked_output

        duration = min(
            3_600.0,
            max(
                0.25,
                _as_float(config.get("expected_duration_seconds"), 0.0),
            ),
        )
        if duration <= 0.25 and _as_float(
            config.get("expected_duration_seconds"),
            0.0,
        ) <= 0:
            raise ValidationError(
                "Segmented recovery requires an expected output duration."
            )
        segment_seconds = min(
            60.0,
            max(0.25, _as_float(config.get("segment_seconds"), 30.0)),
        )
        segment_count = math.ceil(duration / segment_seconds)
        if segment_count > 16:
            raise ValidationError(
                "Segmented recovery exceeds the maximum of 16 bounded segments."
            )

        width = max(64, min(3_840, _as_int(config.get("expected_width"), 320)))
        height = max(64, min(3_840, _as_int(config.get("expected_height"), 180)))
        fps = max(1.0, min(120.0, _as_float(config.get("expected_fps"), 24.0)))
        require_audio = bool(config.get("require_audio", True))
        encoder_threads = max(1, min(8, _as_int(config.get("encoder_threads"), 1)))
        filter_threads = max(1, min(8, _as_int(config.get("filter_threads"), 1)))
        executable = self._resolve_tool_executable(tool)
        timeout = min(
            strategy.timeout_seconds,
            max(1, _as_int(config.get("timeout_seconds"), strategy.timeout_seconds)),
        )
        segment_directory = (workspace / "segments").resolve()
        segment_directory.mkdir(parents=False, exist_ok=False)
        concat_path = (workspace / "segments.txt").resolve()
        commands: list[_BuiltCommand] = []
        expectations: list[tuple[float, int, int, float, bool] | None] = []
        segment_paths: list[Path] = []
        input_reference = str(config.get("input_artifact_ref") or "").replace(
            "\\",
            "/",
        )

        for index in range(segment_count):
            start = index * segment_seconds
            part_duration = min(segment_seconds, duration - start)
            segment_path = (
                segment_directory / f"segment_{index:03d}.mp4"
            ).resolve()
            segment_paths.append(segment_path)
            common_output = [
                "-map",
                "0:v:0",
                "-map",
                "1:a:0" if strategy.capability_id == "media_encode_check" else "0:a:0",
                "-c:v",
                "libx264",
                "-preset",
                str(config.get("encoder_preset") or "veryfast"),
                "-b:v",
                f"{max(500, _as_int(config.get('video_bitrate_kbps'), 800))}k",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                str(encoder_threads),
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-b:a",
                f"{max(64, _as_int(config.get('audio_bitrate_kbps'), 128))}k",
                "-movflags",
                "+faststart",
                str(segment_path),
            ]
            if strategy.capability_id == "media_encode_check":
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
                    (
                        f"testsrc2=size={width}x{height}:rate={fps}:"
                        f"duration={part_duration}"
                    ),
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        "sine=frequency=440:sample_rate=48000:"
                        f"duration={part_duration}"
                    ),
                    *common_output,
                ]
            else:
                assert input_path is not None
                video_filter = (
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps}"
                )
                arguments = [
                    executable,
                    "-hide_banner",
                    "-nostats",
                    "-loglevel",
                    "warning",
                    "-y",
                    "-filter_threads",
                    str(filter_threads),
                    "-filter_complex_threads",
                    str(filter_threads),
                    "-ss",
                    str(start),
                    "-i",
                    str(input_path),
                    "-t",
                    str(part_duration),
                    "-vf",
                    video_filter,
                    *common_output,
                ]
            replacements = {
                str(segment_path): self._workspace_reference(segment_path),
            }
            if input_path is not None:
                replacements[str(input_path)] = input_reference
            stored_arguments = [
                replacements.get(argument, argument)
                for argument in arguments[1:]
            ]
            record = BobaRecoveryCommandV1(
                recovery_command_id=_stable_id(
                    "recovery_command",
                    attempt_id,
                    strategy.recovery_strategy_id,
                    "segmented_render",
                    str(index),
                ),
                tool_id=tool.tool_id,
                executable=tool.executable,
                arguments=stored_arguments,
                working_directory_scope=(
                    f"work/boba/tool_recovery/workspaces/{attempt_id}"
                ),
                category="segmented_render",
                approved=True,
                timeout_seconds=timeout,
            )
            errors = validate_recovery_command_safety(
                record,
                [tool],
                build_trusted_recovery_command_registry([tool]),
            )
            if errors:
                raise ValidationError(
                    "Segment recovery command failed strict safety validation.",
                    details={"reasons": errors},
                )
            commands.append(
                _BuiltCommand(
                    record=record,
                    arguments=tuple(arguments),
                    output_path=segment_path,
                    input_path=input_path,
                )
            )
            expectations.append((part_duration, width, height, fps, require_audio))

        concat_lines = [
            f"file 'segments/{segment_path.name}'"
            for segment_path in segment_paths
        ]
        concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        concat_arguments = [
            executable,
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-i",
            str(concat_path),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        concat_replacements = {
            str(concat_path): self._workspace_reference(concat_path),
            str(output_path): self._workspace_reference(output_path),
        }
        concat_record = BobaRecoveryCommandV1(
            recovery_command_id=_stable_id(
                "recovery_command",
                attempt_id,
                strategy.recovery_strategy_id,
                "segmented_render",
                "concat",
            ),
            tool_id=tool.tool_id,
            executable=tool.executable,
            arguments=[
                concat_replacements.get(argument, argument)
                for argument in concat_arguments[1:]
            ],
            working_directory_scope=(
                f"work/boba/tool_recovery/workspaces/{attempt_id}"
            ),
            category="segmented_render",
            approved=True,
            timeout_seconds=timeout,
        )
        concat_errors = validate_recovery_command_safety(
            concat_record,
            [tool],
            build_trusted_recovery_command_registry([tool]),
        )
        if concat_errors:
            raise ValidationError(
                "Segment concat command failed strict safety validation.",
                details={"reasons": concat_errors},
            )
        commands.append(
            _BuiltCommand(
                record=concat_record,
                arguments=tuple(concat_arguments),
                output_path=output_path,
                input_path=input_path,
            )
        )
        expectations.append(None)
        return (
            commands,
            input_path,
            output_path,
            [segment_directory, concat_path],
            expectations,
        )

    def _segment_validation_errors(
        self,
        path: Path,
        workspace: Path,
        expectation: tuple[float, int, int, float, bool],
    ) -> list[str]:
        expected_duration, width, height, fps, require_audio = expectation
        probe, probe_error = self._probe(path, workspace)
        if not probe:
            return [probe_error or "Segment media probe failed."]
        errors: list[str] = []
        if abs(_as_float(probe.get("container_duration"), 0.0) - expected_duration) > 0.15:
            errors.append("Segment duration does not match its approved window.")
        if probe.get("width") != width or probe.get("height") != height:
            errors.append("Segment resolution does not match the approved output.")
        if abs(_as_float(probe.get("fps"), 0.0) - fps) > 0.1:
            errors.append("Segment frame rate does not match the approved output.")
        if require_audio and not probe.get("has_audio"):
            errors.append("Segment audio is missing.")
        if probe.get("has_audio") and abs(
            _as_float(probe.get("audio_duration"), 0.0)
            - _as_float(probe.get("video_duration"), 0.0)
        ) > 0.15:
            errors.append("Segment audio/video duration delta exceeds 0.15 seconds.")
        return errors

    def _budget_errors(
        self,
        report: BobaToolRecoveryBrainSetV1,
        plan: BobaToolRecoveryPlanV1,
        strategy: BobaToolRecoveryStrategyV1,
    ) -> list[str]:
        attempts = [
            item
            for item in report.recovery_attempts
            if item.recovery_plan_id == plan.recovery_plan_id
        ]
        strategy_attempts = [
            item
            for item in attempts
            if item.recovery_strategy_id == strategy.recovery_strategy_id
        ]
        errors: list[str] = []
        if len(strategy_attempts) >= min(
            strategy.maximum_attempts,
            plan.retry_budget.get(
                "maximum_attempts_per_strategy",
                DEFAULT_MAX_ATTEMPTS_PER_STRATEGY,
            ),
        ):
            errors.append("Maximum attempts for this strategy are exhausted.")
        if len(attempts) >= plan.retry_budget.get(
            "maximum_total_attempts",
            DEFAULT_MAX_TOTAL_ATTEMPTS,
        ):
            errors.append("Maximum total recovery attempts are exhausted.")
        elapsed = sum(
            max(
                0.0,
                (
                    datetime.fromisoformat(item.execution_completed_at).timestamp()
                    - datetime.fromisoformat(item.execution_started_at).timestamp()
                ),
            )
            for item in attempts
            if item.execution_started_at and item.execution_completed_at
        )
        if elapsed >= plan.time_budget_seconds:
            errors.append("Maximum total recovery time is exhausted.")
        fingerprint = fingerprint_recovery_strategy(strategy)
        matching_failed = [
            item
            for item in strategy_attempts
            if item.status in {"failed", "timed_out", "rolled_back", "rejected"}
            and fingerprint in item.warnings
        ]
        if matching_failed:
            errors.append("An identical failed strategy fingerprint cannot be repeated.")
        return errors

    def execute_approved(
        self,
        report: BobaToolRecoveryBrainSetV1,
        *,
        recovery_plan_id: str,
        recovery_strategy_id: str,
        approval: BobaToolRecoveryApprovalV1,
    ) -> BobaToolRecoveryBrainSetV1:
        plan = _find_by_id(report.recovery_plans, "recovery_plan_id", recovery_plan_id)
        if not isinstance(plan, BobaToolRecoveryPlanV1):
            raise ValidationError("Tool Recovery plan was not found.")
        strategy = _find_by_id(
            plan.ordered_strategies,
            "recovery_strategy_id",
            recovery_strategy_id,
        )
        if not isinstance(strategy, BobaToolRecoveryStrategyV1):
            raise ValidationError("Tool Recovery strategy was not found.")
        case = _find_by_id(report.recovery_cases, "recovery_case_id", plan.recovery_case_id)
        if not isinstance(case, BobaToolRecoveryCaseV1):
            raise ValidationError("Tool Recovery case was not found.")
        errors = verify_recovery_approval(plan, strategy, approval)
        errors.extend(self._budget_errors(report, plan, strategy))
        if not case.recovery_eligible:
            errors.append(case.blocked_reason or "Recovery case is ineligible.")
        if not strategy.execution_allowed:
            errors.append(
                "Selected strategy is not executable with the current local health, "
                "input, checkpoint, and quality state."
            )
        tool = _find_by_id(report.registered_tools, "tool_id", strategy.tool_id)
        if not isinstance(tool, BobaRegisteredRecoveryToolV1):
            errors.append("Selected registered tool is unavailable.")
        elif tool.provider_type == "external_service":
            errors.append("External-service recovery is blocked.")
        elif tool.health_status != "healthy":
            errors.append("Selected tool has not passed its registered health check.")
        if errors:
            raise ValidationError(
                "Approved Tool Recovery execution was rejected.",
                details={"reasons": _unique(errors, limit=32)},
            )
        assert isinstance(tool, BobaRegisteredRecoveryToolV1)
        attempt_id = f"tool_attempt_{uuid4().hex}"
        attempt_number = 1 + sum(
            item.recovery_plan_id == plan.recovery_plan_id
            for item in report.recovery_attempts
        )
        workspace = self._attempt_workspace(attempt_id)
        workspace_reference = (
            f"work/boba/tool_recovery/workspaces/{attempt_id}"
        )
        attempt = BobaToolRecoveryAttemptV1(
            recovery_attempt_id=attempt_id,
            recovery_case_id=case.recovery_case_id,
            recovery_plan_id=plan.recovery_plan_id,
            recovery_strategy_id=strategy.recovery_strategy_id,
            attempt_number=attempt_number,
            tool_id=tool.tool_id,
            capability_id=strategy.capability_id,
            execution_started_at=now_iso(),
            working_directory_reference=workspace_reference,
            status="running",
            failure_class=case.failure_class,
            quality_change_disclosed=strategy.strategy_type
            in {"compatibility_mode", "switch_registered_local_tool"},
            warnings=[fingerprint_recovery_strategy(strategy)],
        )
        plan.approval_status = "approved"
        plan.execution_status = "running"
        report.signal_usage.approval_record_used = True
        report.signal_usage.checkpoint_reference_used = bool(
            plan.checkpoint_requirements.get("reference")
        )
        try:
            input_path: Path | None
            output_path: Path | None
            expectations: list[tuple[float, int, int, float, bool] | None]
            temporary_paths: list[Path]
            if strategy.strategy_type == "segmented_processing":
                (
                    built_commands,
                    input_path,
                    output_path,
                    temporary_paths,
                    expectations,
                ) = self._build_segmented_commands(
                    strategy,
                    tool,
                    workspace,
                    attempt_id,
                )
            else:
                built = self._build_command(strategy, tool, workspace, attempt_id)
                built_commands = [built]
                input_path = built.input_path
                output_path = built.output_path
                temporary_paths = []
                expectations = [None]
            attempt.temporary_artifact_refs = [
                self._workspace_reference(path)
                for path in temporary_paths
            ]
            source_checksum = _checksum(input_path) if input_path else ""
            protected_before = self._protected_checksums(
                strategy.configuration_overrides.get("protected_output_refs")
            )
            process = _ProcessResult(
                exit_code=None,
                stdout="",
                stderr="",
                duration_seconds=0.0,
                timed_out=False,
                output_truncated=False,
            )
            execution_failure = ""
            execution_started = time.monotonic()
            output_summaries: list[str] = []
            for built, expectation in zip(
                built_commands,
                expectations,
                strict=True,
            ):
                attempt.command_records.append(built.record)
                remaining_seconds = (
                    plan.time_budget_seconds
                    - (time.monotonic() - execution_started)
                )
                if remaining_seconds <= 0:
                    process = _ProcessResult(
                        exit_code=None,
                        stdout="",
                        stderr="Approved total recovery time budget was exhausted.",
                        duration_seconds=0.0,
                        timed_out=True,
                        output_truncated=False,
                    )
                    execution_failure = process.stderr
                    break
                process = execute_allowlisted_recovery_command(
                    built.arguments,
                    workspace=workspace,
                    timeout_seconds=min(
                        built.record.timeout_seconds,
                        remaining_seconds,
                    ),
                    output_limit_bytes=built.record.output_limit_bytes,
                )
                summary = _safe_text(
                    process.stderr or process.stdout,
                    maximum=500,
                )
                if summary:
                    output_summaries.append(summary)
                if process.timed_out:
                    execution_failure = (
                        "Approved recovery command exceeded its bounded timeout."
                    )
                    break
                if process.exit_code not in built.record.expected_exit_codes:
                    execution_failure = (
                        "Registered recovery command exited with "
                        f"{process.exit_code}."
                    )
                    break
                if not built.output_path or not built.output_path.is_file():
                    execution_failure = (
                        "Recovery command produced no output artifact."
                    )
                    break
                if expectation is not None:
                    segment_errors = self._segment_validation_errors(
                        built.output_path,
                        workspace,
                        expectation,
                    )
                    if segment_errors:
                        execution_failure = " ".join(segment_errors)
                        break
            report.signal_usage.recovery_commands_executed = True
            report.signal_usage.local_fallback_used = (
                strategy.strategy_type == "switch_registered_local_tool"
            )
            attempt.exit_code = process.exit_code
            attempt.timeout_occurred = process.timed_out
            attempt.failure_summary = _safe_text(
                execution_failure or " ".join(output_summaries),
                maximum=2_000,
            )
            attempt.source_media_untouched = bool(
                input_path is None
                or (input_path.exists() and _checksum(input_path) == source_checksum)
            )
            attempt.completed_outputs_untouched = (
                protected_before == self._protected_checksums(
                    strategy.configuration_overrides.get("protected_output_refs")
                )
            )
            if process.timed_out:
                attempt.status = "timed_out"
                attempt.stop_reason = "Approved recovery command exceeded its bounded timeout."
            elif execution_failure:
                attempt.status = "failed"
                attempt.stop_reason = execution_failure
            elif not output_path or not output_path.is_file():
                attempt.status = "failed"
                attempt.stop_reason = "Recovery command produced no output artifact."
            else:
                attempt.status = "succeeded_pending_validation"
                attempt.output_artifact_refs = [
                    self._workspace_reference(output_path)
                ]
                for temporary_path in temporary_paths:
                    try:
                        if temporary_path.is_dir():
                            shutil.rmtree(temporary_path)
                        elif temporary_path.exists():
                            temporary_path.unlink()
                    except OSError:
                        attempt.warnings.append(
                            "A recovery-owned segmented temporary artifact could "
                            "not be cleaned automatically."
                        )
            attempt.execution_completed_at = now_iso()
            attempt.next_strategy_allowed = attempt.status in {"failed", "timed_out"}
            report.recovery_attempts.append(attempt)
            if attempt.status != "succeeded_pending_validation":
                plan.execution_status = "recovery_failed"
                self.rollback(
                    report,
                    recovery_attempt_id=attempt_id,
                    trigger=attempt.stop_reason or "Recovery command failed.",
                )
                report.recovery_handoffs.append(
                    _build_handoff(
                        case,
                        plan,
                        target="repair_planner",
                        reason=attempt.stop_reason or "Recovery strategy failed.",
                        attempt_id=attempt_id,
                        priority="high",
                    )
                )
            else:
                plan.execution_status = "recovered_pending_validation"
                self.validate_output(report, recovery_attempt_id=attempt_id)
            report.recovery_summary = _summary(report)
            return report
        except Exception as exc:
            if not any(
                item.recovery_attempt_id == attempt_id
                for item in report.recovery_attempts
            ):
                attempt.status = "failed"
                attempt.failure_summary = _safe_text(exc, maximum=2_000)
                attempt.stop_reason = "Recovery execution failed before validation."
                attempt.execution_completed_at = now_iso()
                report.recovery_attempts.append(attempt)
            plan.execution_status = "recovery_failed"
            self.rollback(
                report,
                recovery_attempt_id=attempt_id,
                trigger=attempt.failure_summary or attempt.stop_reason,
            )
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(
                "Registered Tool Recovery execution failed.",
                details={"reason": _safe_text(exc)},
            ) from exc

    def _workspace_reference(self, path: Path) -> str:
        resolved = path.resolve()
        if self.repository_root in resolved.parents:
            return str(resolved.relative_to(self.repository_root)).replace("\\", "/")
        if self.workspace_root in resolved.parents:
            return (
                "work/boba/tool_recovery/workspaces/"
                + str(resolved.relative_to(self.workspace_root)).replace("\\", "/")
            )
        raise ValidationError("Recovery artifact is outside the configured workspace.")

    def _resolve_workspace_reference(self, value: str) -> Path:
        relative = _clean_relative_reference(value, field_name="Recovery artifact reference")
        text = str(relative).replace("\\", "/")
        prefix = "work/boba/tool_recovery/workspaces/"
        if not text.startswith(prefix):
            raise ValidationError("Artifact is not recovery-owned.")
        suffix = text[len(prefix) :]
        path = (self.workspace_root / Path(*PurePosixPath(suffix).parts)).resolve()
        if self.workspace_root not in path.parents:
            raise ValidationError("Recovery artifact escaped its workspace.")
        return path

    def _protected_checksums(self, values: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        for value in _as_list(values)[:32]:
            try:
                relative = _clean_relative_reference(
                    str(value),
                    field_name="Protected output reference",
                )
            except ValidationError:
                continue
            path = (self.repository_root / Path(*relative.parts)).resolve()
            if path.is_file() and any(
                path == root or root in path.parents for root in self.approved_input_roots
            ):
                result[str(relative)] = _checksum(path)
        return result

    def _probe(self, path: Path, workspace: Path) -> tuple[dict[str, Any], str]:
        tool_name, _ = _configured_executable(self.ffprobe_binary)
        executable = shutil.which(self.ffprobe_binary)
        if not executable and Path(self.ffprobe_binary).is_file():
            executable = str(Path(self.ffprobe_binary).resolve())
        if not executable:
            return {}, "FFprobe is unavailable."
        args = [
            executable,
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,size,format_name:"
                "stream=index,codec_type,codec_name,width,height,duration,"
                "channels,sample_rate,avg_frame_rate,r_frame_rate"
            ),
            "-of",
            "json",
            str(path),
        ]
        command = BobaRecoveryCommandV1(
            recovery_command_id=_stable_id("validation_command", str(path), uuid4().hex),
            tool_id="ffprobe",
            executable=tool_name,
            arguments=[
                *args[1:-1],
                self._workspace_reference(path),
            ],
            working_directory_scope=self._workspace_reference(workspace),
            category="media_probe",
            approved=True,
            timeout_seconds=60.0,
        )
        registry = build_trusted_recovery_command_registry(
            [
                BobaRegisteredRecoveryToolV1(
                    tool_id="ffprobe",
                    display_name="FFprobe",
                    provider_type="executable",
                    capability_ids=["video_probe", "audio_probe"],
                    executable=tool_name,
                    installed=True,
                )
            ]
        )
        if validate_recovery_command_safety(
            command,
            [
                BobaRegisteredRecoveryToolV1(
                    tool_id="ffprobe",
                    display_name="FFprobe",
                    provider_type="executable",
                    capability_ids=["video_probe", "audio_probe"],
                    executable=tool_name,
                    installed=True,
                )
            ],
            registry,
        ):
            return {}, "FFprobe validation command was rejected."
        result = execute_allowlisted_recovery_command(
            args,
            workspace=workspace,
            timeout_seconds=60.0,
            output_limit_bytes=262_144,
        )
        if result.timed_out:
            return {}, "FFprobe timed out."
        if result.exit_code != 0:
            return {}, result.stderr or "FFprobe failed."
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}, "FFprobe returned malformed JSON."
        return _parse_probe(_as_dict(payload)), ""

    def validate_output(
        self,
        report: BobaToolRecoveryBrainSetV1,
        *,
        recovery_attempt_id: str,
    ) -> BobaToolRecoveryBrainSetV1:
        attempt = _find_by_id(
            report.recovery_attempts,
            "recovery_attempt_id",
            recovery_attempt_id,
        )
        if not isinstance(attempt, BobaToolRecoveryAttemptV1):
            raise ValidationError("Recovery attempt was not found.")
        plan = _find_by_id(report.recovery_plans, "recovery_plan_id", attempt.recovery_plan_id)
        if not isinstance(plan, BobaToolRecoveryPlanV1):
            raise ValidationError("Recovery plan was not found.")
        strategy = _find_by_id(
            plan.ordered_strategies,
            "recovery_strategy_id",
            attempt.recovery_strategy_id,
        )
        if not isinstance(strategy, BobaToolRecoveryStrategyV1):
            raise ValidationError("Recovery strategy was not found.")
        case = _find_by_id(report.recovery_cases, "recovery_case_id", attempt.recovery_case_id)
        if not isinstance(case, BobaToolRecoveryCaseV1):
            raise ValidationError("Recovery case was not found.")
        output_ref = attempt.output_artifact_refs[0] if attempt.output_artifact_refs else ""
        path = self._resolve_workspace_reference(output_ref) if output_ref else None
        validation = BobaRecoveredOutputValidationV1(
            output_validation_id=_stable_id(
                "output_validation",
                attempt.recovery_attempt_id,
                output_ref,
                uuid4().hex,
            ),
            recovery_attempt_id=attempt.recovery_attempt_id,
            output_artifact_ref=output_ref,
        )
        failed: list[str] = []
        unavailable: list[str] = []
        warnings: list[str] = []
        validation.artifact_exists = bool(path and path.is_file())
        if not validation.artifact_exists:
            failed.append("artifact_exists")
        validation.artifact_non_empty = bool(
            path and path.is_file() and path.stat().st_size > 0
        )
        if not validation.artifact_non_empty:
            failed.append("artifact_non_empty")
        if path and validation.artifact_non_empty:
            expected_checksum = str(
                strategy.configuration_overrides.get("expected_checksum") or ""
            )
            actual_checksum = _checksum(path)
            validation.checksum_valid = (
                actual_checksum == expected_checksum if expected_checksum else True
            )
            if validation.checksum_valid is False:
                failed.append("checksum")
            suffix = path.suffix.lower()
            if suffix == ".json":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8-sig"))
                    required_keys = [
                        str(item)
                        for item in _as_list(
                            strategy.configuration_overrides.get("required_schema_keys")
                        )
                    ]
                    validation.schema_valid = isinstance(payload, dict) and all(
                        key in payload for key in required_keys
                    )
                except (OSError, json.JSONDecodeError):
                    validation.schema_valid = False
                if validation.schema_valid is False:
                    failed.append("schema")
            elif suffix in {".mp4", ".mov", ".mkv", ".webm", ".wav", ".m4a", ".mp3"}:
                workspace = path.parents[1]
                probe, probe_error = self._probe(path, workspace)
                validation.media_probe_valid = bool(probe)
                if not probe:
                    failed.append("media_probe")
                    warnings.append(probe_error)
                else:
                    expected_duration = _as_float(
                        strategy.configuration_overrides.get("expected_duration_seconds"),
                        0.0,
                    )
                    if expected_duration > 0:
                        actual_duration = _as_float(
                            probe.get("container_duration"),
                            0.0,
                        )
                        validation.duration_valid = (
                            abs(actual_duration - expected_duration) <= 0.15
                        )
                        validation.source_window_status = (
                            "passed" if validation.duration_valid else "failed"
                        )
                        if not validation.duration_valid:
                            failed.extend(["duration", "source_window"])
                    else:
                        validation.duration_valid = None
                        validation.source_window_status = "not_required"
                    expected_width = _as_int(
                        strategy.configuration_overrides.get("expected_width"),
                        0,
                    )
                    expected_height = _as_int(
                        strategy.configuration_overrides.get("expected_height"),
                        0,
                    )
                    if expected_width and expected_height:
                        validation.resolution_valid = (
                            probe.get("width") == expected_width
                            and probe.get("height") == expected_height
                        )
                        validation.framing_status = (
                            "passed" if validation.resolution_valid else "failed"
                        )
                        if not validation.resolution_valid:
                            failed.extend(["resolution", "framing"])
                    expected_fps = _as_float(
                        strategy.configuration_overrides.get("expected_fps"),
                        0.0,
                    )
                    if expected_fps:
                        actual_fps = _as_float(probe.get("fps"), 0.0)
                        validation.frame_rate_valid = abs(actual_fps - expected_fps) <= 0.1
                        if not validation.frame_rate_valid:
                            failed.append("frame_rate")
                    require_audio = bool(
                        strategy.configuration_overrides.get("require_audio", True)
                    )
                    validation.audio_presence_valid = (
                        bool(probe.get("has_audio")) if require_audio else True
                    )
                    if validation.audio_presence_valid is False:
                        failed.append("audio_presence")
                    if probe.get("has_audio"):
                        audio_duration = _as_float(probe.get("audio_duration"), 0.0)
                        video_duration = _as_float(probe.get("video_duration"), 0.0)
                        validation.audio_video_sync_valid = (
                            abs(audio_duration - video_duration) <= 0.15
                        )
                        if not validation.audio_video_sync_valid:
                            failed.append("audio_video_sync")
                    elif require_audio:
                        validation.audio_video_sync_valid = False
                        failed.append("audio_video_sync")
                    else:
                        validation.audio_video_sync_valid = None
            else:
                unavailable.append("artifact_type_specific_validation")
        quality_text = " ".join(plan.quality_requirements).lower()
        if "caption" in quality_text:
            validation.caption_timing_status = "unavailable"
            unavailable.append("caption_timing")
        if "framing" in quality_text and validation.framing_status == "not_required":
            validation.framing_status = "unavailable"
            unavailable.append("framing")
        validation.failed_required_checks = _unique(failed, limit=64)
        validation.unavailable_required_checks = _unique(unavailable, limit=64)
        validation.required_checks_passed = not failed and not unavailable
        validation.accepted_for_quality_review = validation.required_checks_passed
        validation.rejected_reason = (
            ""
            if validation.required_checks_passed
            else "Required technical checks failed or were unavailable."
        )
        validation.warnings = _unique(warnings, limit=32)
        report.output_validations.append(validation)
        report.signal_usage.output_validation_used = True
        if validation.required_checks_passed:
            attempt.status = "completed"
            attempt.stop_reason = (
                "Technical checks passed; final output quality review is still required."
            )
            attempt.next_strategy_allowed = False
            plan.execution_status = "completed"
            for target, reason in (
                (
                    "output_quality_reviewer",
                    "Recovered output passed required technical checks and needs final review.",
                ),
                (
                    "safety_gate",
                    "Confirm the recovered output and proposed next action remain safe.",
                ),
                (
                    "workflow_controller",
                    "Recovery is technically valid, but workflow resume remains "
                    "a separate decision.",
                ),
            ):
                report.recovery_handoffs.append(
                    _build_handoff(
                        case,
                        plan,
                        target=target,  # type: ignore[arg-type]
                        reason=reason,
                        attempt_id=attempt.recovery_attempt_id,
                        priority="high",
                    )
                )
        else:
            attempt.status = "rejected"
            attempt.stop_reason = validation.rejected_reason
            attempt.next_strategy_allowed = True
            plan.execution_status = "validation_failed"
            self.rollback(
                report,
                recovery_attempt_id=attempt.recovery_attempt_id,
                trigger=validation.rejected_reason,
            )
            report.recovery_handoffs.append(
                _build_handoff(
                    case,
                    plan,
                    target="repair_planner",
                    reason=validation.rejected_reason,
                    attempt_id=attempt.recovery_attempt_id,
                    priority="high",
                )
            )
        report.recovery_summary = _summary(report)
        return report

    def rollback(
        self,
        report: BobaToolRecoveryBrainSetV1,
        *,
        recovery_attempt_id: str,
        trigger: str,
    ) -> BobaToolRecoveryBrainSetV1:
        attempt = _find_by_id(
            report.recovery_attempts,
            "recovery_attempt_id",
            recovery_attempt_id,
        )
        if not isinstance(attempt, BobaToolRecoveryAttemptV1):
            raise ValidationError("Recovery attempt was not found.")
        record = BobaToolRecoveryRollbackV1(
            rollback_record_id=_stable_id(
                "tool_rollback",
                recovery_attempt_id,
                trigger,
                uuid4().hex,
            ),
            recovery_attempt_id=recovery_attempt_id,
            trigger=_safe_text(trigger, maximum=900) or "Recovery rollback requested.",
            status="completed",
        )
        removal_failed = False
        refs = [*attempt.output_artifact_refs, *attempt.temporary_artifact_refs]
        for reference in refs:
            try:
                path = self._resolve_workspace_reference(reference)
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            except (OSError, ValidationError):
                removal_failed = True
        record.temporary_outputs_removed = not any(
            self._resolve_workspace_reference(reference).exists()
            for reference in refs
            if reference.startswith("work/boba/tool_recovery/workspaces/")
        )
        record.prior_generated_state_restored = True
        record.rollback_validation_passed = (
            record.temporary_outputs_removed and not removal_failed
        )
        record.status = (
            "completed" if record.rollback_validation_passed else "partial"
        )
        if record.status != "completed":
            record.warnings = [
                "Rollback was incomplete; further recovery is blocked pending human review."
            ]
            attempt.next_strategy_allowed = False
        attempt.status = "rolled_back"
        attempt.stop_reason = record.trigger
        report.rollback_records.append(record)
        report.signal_usage.rollback_used = True
        plan = _find_by_id(
            report.recovery_plans,
            "recovery_plan_id",
            attempt.recovery_plan_id,
        )
        if isinstance(plan, BobaToolRecoveryPlanV1):
            plan.execution_status = "rolled_back"
        report.recovery_summary = _summary(report)
        return report


def generate_boba_tool_recovery_plan(
    repository_root: str | Path,
    project_id: str,
    repair_planner: BobaRepairPlannerSetV1 | Mapping[str, Any] | None,
    **kwargs: Any,
) -> BobaToolRecoveryBrainSetV1:
    return BobaToolRecoveryBrainV1(repository_root).plan(
        project_id,
        repair_planner,
        **kwargs,
    )


def run_boba_tool_health_checks(
    repository_root: str | Path,
    report: BobaToolRecoveryBrainSetV1,
    **kwargs: Any,
) -> BobaToolRecoveryBrainSetV1:
    return BobaToolRecoveryBrainV1(repository_root).run_health_checks(report, **kwargs)


def execute_approved_boba_tool_recovery(
    repository_root: str | Path,
    report: BobaToolRecoveryBrainSetV1,
    **kwargs: Any,
) -> BobaToolRecoveryBrainSetV1:
    return BobaToolRecoveryBrainV1(repository_root).execute_approved(report, **kwargs)


def validate_boba_recovered_output(
    repository_root: str | Path,
    report: BobaToolRecoveryBrainSetV1,
    **kwargs: Any,
) -> BobaToolRecoveryBrainSetV1:
    return BobaToolRecoveryBrainV1(repository_root).validate_output(report, **kwargs)


def rollback_boba_tool_recovery(
    repository_root: str | Path,
    report: BobaToolRecoveryBrainSetV1,
    **kwargs: Any,
) -> BobaToolRecoveryBrainSetV1:
    return BobaToolRecoveryBrainV1(repository_root).rollback(report, **kwargs)


__all__ = [
    "DEFAULT_MAX_ATTEMPTS_PER_STRATEGY",
    "DEFAULT_MAX_RECOVERY_SECONDS",
    "DEFAULT_MAX_TOTAL_ATTEMPTS",
    "EXPLICIT_RECOVERY_CONFIRMATION",
    "BobaRecoveredOutputValidationV1",
    "BobaRecoveryCommandV1",
    "BobaRegisteredRecoveryToolV1",
    "BobaToolCapabilityV1",
    "BobaToolHealthCheckV1",
    "BobaToolHealthResultV1",
    "BobaToolRecoveryApprovalV1",
    "BobaToolRecoveryAttemptV1",
    "BobaToolRecoveryBrainSetV1",
    "BobaToolRecoveryBrainV1",
    "BobaToolRecoveryCaseV1",
    "BobaToolRecoveryHandoffV1",
    "BobaToolRecoveryPlanV1",
    "BobaToolRecoveryRollbackV1",
    "BobaToolRecoverySignalUsageV1",
    "BobaToolRecoveryStrategyV1",
    "BobaToolRecoverySummaryV1",
    "build_minimal_capability_registry",
    "build_trusted_recovery_command_registry",
    "classify_tool_failure",
    "execute_allowlisted_recovery_command",
    "execute_approved_boba_tool_recovery",
    "fingerprint_recovery_strategy",
    "generate_boba_tool_recovery_plan",
    "rollback_boba_tool_recovery",
    "run_boba_tool_health_checks",
    "validate_boba_recovered_output",
    "validate_recovery_command_safety",
    "validate_recovery_paths",
    "verify_recovery_approval",
]
