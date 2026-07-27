"""Bounded, approval-gated code repair inside isolated Git worktrees."""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.repair_planner import (
    BobaRepairExecutionHandoffV1,
    BobaRepairPlannerSetV1,
    BobaRepairPlanningCaseV1,
    BobaRepairStrategyV1,
    BobaRepairValidationPlanV1,
)
from olympus.platform.errors import ValidationError

BobaCodeEvidenceStrengthV1 = Literal[
    "strong",
    "moderate",
    "weak",
    "conflicting",
    "insufficient",
    "unknown",
]
BobaCodeProposalSourceV1 = Literal[
    "deterministic_template",
    "user_provided_diff",
    "codex_provided_diff",
    "imported_review_patch",
    "unknown",
]
BobaCodeApprovalStatusV1 = Literal[
    "not_requested",
    "awaiting_review",
    "approved_for_isolated_execution",
    "rejected",
    "expired",
    "invalidated_by_base_change",
    "unknown",
]
BobaCodeExecutionStatusV1 = Literal[
    "proposal_only",
    "validation_ready",
    "blocked",
    "applied_in_isolated_worktree",
    "validation_failed",
    "validation_passed",
    "rolled_back",
    "local_commit_prepared",
    "unknown",
]
BobaCodePatchOperationV1 = Literal[
    "add",
    "modify",
    "delete",
    "rename",
    "mode_change",
    "unknown",
]
BobaCodeApprovalTypeV1 = Literal[
    "proposal_review",
    "isolated_patch_execution",
    "special_path_change",
    "dependency_change",
    "workflow_change",
    "local_commit_creation",
    "unknown",
]
BobaCodeRunModeV1 = Literal[
    "proposal_only",
    "validate_provided_patch",
    "approved_isolated_patch",
    "prepare_local_review_commit",
]
BobaCodeRunStatusV1 = Literal[
    "not_started",
    "blocked",
    "worktree_ready",
    "patch_applied",
    "validation_running",
    "validation_failed",
    "validation_passed",
    "rolled_back",
    "local_commit_prepared",
    "completed",
    "failed",
    "unknown",
]
BobaCodeValidationCategoryV1 = Literal[
    "git_diff_check",
    "formatting",
    "lint",
    "unit_test",
    "integration_test",
    "typecheck",
    "build",
    "schema",
    "api",
    "frontend",
    "security",
    "secret_scan",
    "regression",
    "custom_allowlisted",
    "unknown",
]
BobaCodeValidationStatusV1 = Literal[
    "passed",
    "failed",
    "timed_out",
    "blocked",
    "skipped",
    "unavailable",
    "unknown",
]
BobaCodeRollbackStatusV1 = Literal[
    "not_required",
    "completed",
    "partial",
    "failed",
    "blocked",
    "unknown",
]
BobaCodeHandoffTargetV1 = Literal[
    "validator_runner",
    "output_quality_reviewer",
    "safety_gate",
    "workflow_controller",
    "repair_planner",
    "root_cause_analyzer",
    "tool_recovery_brain",
    "human_operator",
    "manual_git_review",
    "unknown",
]
BobaCodePriorityV1 = Literal["low", "medium", "high", "urgent"]
JsonObject: TypeAlias = dict[str, Any]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BRANCH_COMPONENT = re.compile(r"[^a-z0-9._-]+")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_DIFF_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)
_INDEX_HEADER = re.compile(r"^index ([0-9a-fA-F]+)\.\.([0-9a-fA-F]+)")
_PRIVATE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"']+|\\\\[^\\\s]+\\[^\s\"']+|"
    r"/(?:home|Users|root|private|tmp)/[^\s\"']+)"
)
_SECRET_ENV_KEY = re.compile(
    r"(?:secret|token|password|credential|cookie|authorization|api[_-]?key)",
    re.IGNORECASE,
)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "github_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "credential_url",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]+@", re.IGNORECASE),
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|"
            r"secret|authorization)\b\s*[:=]\s*[\"']?([^\s\"']{12,})"
        ),
    ),
)
_PLACEHOLDER_SECRET = re.compile(
    r"(?i)^(?:test|fake|dummy|example|placeholder|changeme|redacted|your[_-])"
)
_SUSPICIOUS_PATCH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "test_skip",
        re.compile(
            r"^\+\s*(?:@pytest\.mark\.skip|pytest\.skip\(|it\.skip\(|test\.skip\()"
        ),
    ),
    (
        "ignored_exception",
        re.compile(
            r"^\+\s*except\s+(?:Exception|BaseException)(?:\s+as\s+\w+)?:\s*(?:pass|return\s+None)?\s*$"
        ),
    ),
    ("always_success", re.compile(r"^\+\s*return\s+(?:True|[\"']success[\"'])\s*$")),
    (
        "validation_bypass",
        re.compile(
            r"(?i)^\+.*(?:skip_validation|validation_enabled\s*=\s*false|"
            r"bypass_validation|ignore_validation)"
        ),
    ),
    (
        "rights_bypass",
        re.compile(
            r"(?i)^\+.*(?:skip_rights|bypass_rights|rights_check\s*=\s*false|"
            r"permission_required\s*=\s*false)"
        ),
    ),
    (
        "quality_threshold_weakened",
        re.compile(
            r"(?i)^\+.*(?:quality|confidence|acceptance|pass)[_-]?threshold"
            r"\s*[:=]\s*(?:0(?:\.0+)?|false|none)"
        ),
    ),
    (
        "permanent_debug",
        re.compile(r"^\+\s*(?:print\(|console\.log\(|debugger\b)"),
    ),
)
_ALLOWED_EXTENSIONS = (
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".css",
    ".scss",
    ".html",
    ".sql",
    ".txt",
)
_BLOCKED_EXTENSIONS = (
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".wav",
    ".mp3",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".zip",
    ".exe",
    ".dll",
    ".so",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
)
_PROTECTED_BRANCHES = ("main", "master", "develop", "release")
_PROTECTED_PATHS = (
    ".git",
    ".env",
    ".env.*",
    "secrets",
    "credentials",
    "private_keys",
    "work",
    "storage_data",
    "media",
    "uploads",
    "downloads",
    "node_modules",
    "frontend/node_modules",
    "frontend/.next",
    ".venv",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "validation_reports",
)
_SPECIAL_APPROVAL_PATHS = (
    ".github/workflows",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "frontend/package.json",
    "frontend/package-lock.json",
    "requirements.txt",
    "requirements-dev.txt",
    "Dockerfile",
    "docker-compose.yml",
    "migrations",
)
_DEPENDENCY_PATHS = {
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "frontend/package.json",
    "frontend/package-lock.json",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",
}
_RUN_ACTIVE_STATUSES = {
    "worktree_ready",
    "patch_applied",
    "validation_running",
    "validation_passed",
    "local_commit_prepared",
}
_MAX_HARD_CHANGED_FILES = 64
_MAX_HARD_CHANGED_LINES = 5_000
_MAX_HARD_DIFF_BYTES = 2_000_000
_MAX_HARD_FILE_BYTES = 10_000_000


class BobaCodeRepairCaseV1(BobaContract):
    code_repair_case_id: str = Field(min_length=1, max_length=160)
    source_repair_case_id: str = Field(default="", max_length=160)
    source_repair_strategy_id: str = Field(default="", max_length=160)
    title: str = Field(min_length=1, max_length=240)
    target_module: str = Field(default="", max_length=160)
    suspected_code_defect: str = Field(default="", max_length=700)
    evidence_strength: BobaCodeEvidenceStrengthV1
    code_change_justified: bool
    justification: str = Field(min_length=1, max_length=900)
    affected_paths: list[str] = Field(default_factory=list, max_length=64)
    protected_paths_detected: list[str] = Field(default_factory=list, max_length=64)
    required_behavior: list[str] = Field(default_factory=list, max_length=32)
    behavior_to_preserve: list[str] = Field(default_factory=list, max_length=32)
    validation_requirements: list[str] = Field(default_factory=list, max_length=64)
    quality_requirements: list[str] = Field(default_factory=list, max_length=64)
    rollback_requirements: list[str] = Field(default_factory=list, max_length=64)
    approval_required: Literal[True] = True
    execution_eligible: bool
    blocked_reason: str | None = Field(default=None, max_length=900)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaCodePatchFileV1(BobaContract):
    path: str = Field(min_length=1, max_length=500)
    operation: BobaCodePatchOperationV1
    language: str = Field(default="text", max_length=80)
    previous_sha256: str = Field(default="", max_length=128)
    proposed_sha256: str = Field(default="", max_length=128)
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    binary: bool = False
    generated: bool = False
    protected: bool = False
    special_approval_required: bool = False
    reason_for_change: str = Field(default="", max_length=700)
    behavior_preserved: list[str] = Field(default_factory=list, max_length=32)
    validation_needed: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCodePatchHunkV1(BobaContract):
    file_path: str = Field(min_length=1, max_length=500)
    old_start: int = Field(ge=0)
    old_count: int = Field(ge=0)
    new_start: int = Field(ge=0)
    new_count: int = Field(ge=0)
    bounded_summary: str = Field(min_length=1, max_length=500)
    change_reason: str = Field(default="", max_length=500)
    related_evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    risk: str = Field(default="low", max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCodePatchProposalV1(BobaContract):
    patch_proposal_id: str = Field(min_length=1, max_length=160)
    code_repair_case_id: str = Field(min_length=1, max_length=160)
    proposal_source: BobaCodeProposalSourceV1
    base_branch: str = Field(min_length=1, max_length=240)
    base_commit_sha: str = Field(min_length=7, max_length=64)
    proposed_branch: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=900)
    rationale: str = Field(min_length=1, max_length=900)
    files: list[BobaCodePatchFileV1] = Field(default_factory=list, max_length=64)
    hunks: list[BobaCodePatchHunkV1] = Field(default_factory=list, max_length=256)
    unified_diff_reference: str = Field(default="", max_length=500)
    diff_sha256: str = Field(min_length=64, max_length=64)
    changed_file_count: int = Field(ge=0, le=_MAX_HARD_CHANGED_FILES)
    additions: int = Field(ge=0, le=_MAX_HARD_CHANGED_LINES)
    deletions: int = Field(ge=0, le=_MAX_HARD_CHANGED_LINES)
    total_changed_lines: int = Field(ge=0, le=_MAX_HARD_CHANGED_LINES)
    patch_size_bytes: int = Field(ge=0, le=_MAX_HARD_DIFF_BYTES)
    applies_cleanly: bool
    path_policy_passed: bool
    secret_scan_passed: bool
    scope_check_passed: bool
    binary_change_detected: bool
    dependency_change_detected: bool
    workflow_change_detected: bool
    risk_level: str = Field(default="unknown", max_length=80)
    approval_status: BobaCodeApprovalStatusV1
    execution_status: BobaCodeExecutionStatusV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaCodeApprovalRecordV1(BobaContract):
    approval_id: str = Field(min_length=1, max_length=160)
    code_repair_case_id: str = Field(min_length=1, max_length=160)
    patch_proposal_id: str = Field(min_length=1, max_length=160)
    approval_type: BobaCodeApprovalTypeV1
    approved: bool
    approved_at: str = Field(default_factory=now_iso, max_length=80)
    approved_by: str = Field(min_length=1, max_length=120)
    approved_base_commit_sha: str = Field(min_length=7, max_length=64)
    approved_diff_sha256: str = Field(min_length=64, max_length=64)
    approved_scope: list[str] = Field(default_factory=list, max_length=64)
    approved_validation_commands: list[str] = Field(default_factory=list, max_length=24)
    approved_special_paths: list[str] = Field(default_factory=list, max_length=32)
    approval_expires_at: str | None = Field(default=None, max_length=80)
    explicit_confirmation: bool
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCodeExecutionPolicyV1(BobaContract):
    policy_id: str = Field(min_length=1, max_length=160)
    protected_branches: list[str] = Field(default_factory=list, max_length=64)
    protected_paths: list[str] = Field(default_factory=list, max_length=128)
    special_approval_paths: list[str] = Field(default_factory=list, max_length=64)
    allowed_extensions: list[str] = Field(default_factory=list, max_length=64)
    blocked_extensions: list[str] = Field(default_factory=list, max_length=64)
    maximum_changed_files: int = Field(default=12, ge=1, le=_MAX_HARD_CHANGED_FILES)
    maximum_changed_lines: int = Field(default=800, ge=1, le=_MAX_HARD_CHANGED_LINES)
    maximum_diff_size_bytes: int = Field(default=200_000, ge=1, le=_MAX_HARD_DIFF_BYTES)
    maximum_individual_file_size_bytes: int = Field(
        default=2_000_000,
        ge=1,
        le=_MAX_HARD_FILE_BYTES,
    )
    maximum_validation_commands: int = Field(default=12, ge=1, le=24)
    maximum_patch_attempts: int = Field(default=2, ge=1, le=4)
    command_timeout_seconds: int = Field(default=300, ge=1, le=3_600)
    output_capture_limit_bytes: int = Field(default=64_000, ge=1_024, le=1_000_000)
    network_access_allowed: Literal[False] = False
    package_installation_allowed: Literal[False] = False
    service_restart_allowed: Literal[False] = False
    push_allowed: Literal[False] = False
    merge_allowed: Literal[False] = False
    tag_allowed: Literal[False] = False
    destructive_git_allowed: Literal[False] = False
    direct_main_modification_allowed: Literal[False] = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCodeIsolatedRunV1(BobaContract):
    isolated_run_id: str = Field(min_length=1, max_length=160)
    patch_proposal_id: str = Field(min_length=1, max_length=160)
    mode: BobaCodeRunModeV1
    base_branch: str = Field(min_length=1, max_length=240)
    base_commit_sha: str = Field(min_length=7, max_length=64)
    repair_branch: str = Field(min_length=1, max_length=240)
    sanitized_worktree_reference: str = Field(default="", max_length=500)
    worktree_created: bool = False
    current_worktree_clean_before_run: bool = False
    patch_apply_check_passed: bool = False
    patch_applied: bool = False
    changed_files_verified: bool = False
    approval_verified: bool = False
    execution_started_at: str | None = Field(default=None, max_length=80)
    execution_completed_at: str | None = Field(default=None, max_length=80)
    run_status: BobaCodeRunStatusV1
    stop_reason: str | None = Field(default=None, max_length=900)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaCodeValidationCommandV1(BobaContract):
    validation_command_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    executable: str = Field(min_length=1, max_length=500)
    arguments: list[str] = Field(default_factory=list, max_length=128)
    working_directory_scope: str = Field(default=".", max_length=240)
    category: BobaCodeValidationCategoryV1
    required: bool = True
    approved: bool = False
    timeout_seconds: int = Field(default=300, ge=1, le=3_600)
    network_forbidden: Literal[True] = True
    shell_used: Literal[False] = False
    expected_exit_codes: list[int] = Field(default_factory=lambda: [0], max_length=8)
    output_limit_bytes: int = Field(default=64_000, ge=1_024, le=1_000_000)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCodeValidationResultV1(BobaContract):
    validation_result_id: str = Field(min_length=1, max_length=160)
    validation_command_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    status: BobaCodeValidationStatusV1
    exit_code: int | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)
    bounded_stdout_summary: str = Field(default="", max_length=66_000)
    bounded_stderr_summary: str = Field(default="", max_length=66_000)
    output_truncated: bool = False
    secrets_redacted: bool = True
    required: bool = True
    blocks_acceptance: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCodeValidationRunV1(BobaContract):
    validation_run_id: str = Field(min_length=1, max_length=160)
    isolated_run_id: str = Field(min_length=1, max_length=160)
    commands: list[BobaCodeValidationCommandV1] = Field(default_factory=list, max_length=24)
    results: list[BobaCodeValidationResultV1] = Field(default_factory=list, max_length=24)
    required_checks_passed: bool
    optional_checks_passed: bool
    failed_required_checks: list[str] = Field(default_factory=list, max_length=24)
    failed_optional_checks: list[str] = Field(default_factory=list, max_length=24)
    skipped_checks: list[str] = Field(default_factory=list, max_length=24)
    acceptance_criteria_met: bool
    rejection_reason: str | None = Field(default=None, max_length=900)
    started_at: str = Field(default_factory=now_iso, max_length=80)
    completed_at: str | None = Field(default=None, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCodeRollbackRecordV1(BobaContract):
    rollback_record_id: str = Field(min_length=1, max_length=160)
    isolated_run_id: str = Field(min_length=1, max_length=160)
    rollback_trigger: str = Field(min_length=1, max_length=700)
    rollback_scope: str = Field(default="isolated_worktree", max_length=160)
    rollback_started_at: str | None = Field(default=None, max_length=80)
    rollback_completed_at: str | None = Field(default=None, max_length=80)
    patch_removed: bool = False
    temporary_worktree_removed: bool = False
    repair_branch_preserved_for_review: bool = True
    source_worktree_unchanged: bool = False
    rollback_validation_passed: bool = False
    rollback_status: BobaCodeRollbackStatusV1
    human_review_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCodeReviewPackageV1(BobaContract):
    review_package_id: str = Field(min_length=1, max_length=160)
    patch_proposal_id: str = Field(min_length=1, max_length=160)
    isolated_run_id: str = Field(default="", max_length=160)
    repair_branch: str = Field(min_length=1, max_length=240)
    base_commit_sha: str = Field(min_length=7, max_length=64)
    local_commit_sha: str = Field(default="", max_length=64)
    commit_created: bool = False
    diff_summary: str = Field(min_length=1, max_length=900)
    changed_files: list[str] = Field(default_factory=list, max_length=64)
    validation_summary: str = Field(min_length=1, max_length=900)
    failed_or_skipped_checks: list[str] = Field(default_factory=list, max_length=32)
    risk_summary: str = Field(min_length=1, max_length=900)
    rollback_summary: str = Field(min_length=1, max_length=900)
    PR_title: str = Field(min_length=1, max_length=240)
    PR_body: str = Field(min_length=1, max_length=4_000)
    reviewer_checklist: list[str] = Field(default_factory=list, max_length=32)
    prohibited_next_actions: list[str] = Field(default_factory=list, max_length=32)
    ready_for_manual_push: bool = False
    ready_for_manual_PR: bool = False  # noqa: N815
    ready_for_merge: Literal[False] = False
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaCodeSurgeonExecutionHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=160)
    code_repair_case_id: str = Field(min_length=1, max_length=160)
    patch_proposal_id: str = Field(default="", max_length=160)
    target_module: BobaCodeHandoffTargetV1
    reason: str = Field(min_length=1, max_length=700)
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    validation_requirements: list[str] = Field(default_factory=list, max_length=32)
    constraints: list[str] = Field(default_factory=list, max_length=32)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False
    human_approval_required: Literal[True] = True
    priority: BobaCodePriorityV1
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCodeSurgeonSummaryV1(BobaContract):
    total_repair_cases: int = Field(default=0, ge=0)
    eligible_case_count: int = Field(default=0, ge=0)
    blocked_case_count: int = Field(default=0, ge=0)
    proposal_count: int = Field(default=0, ge=0)
    approved_proposal_count: int = Field(default=0, ge=0)
    isolated_execution_count: int = Field(default=0, ge=0)
    validation_pass_count: int = Field(default=0, ge=0)
    validation_failure_count: int = Field(default=0, ge=0)
    rollback_count: int = Field(default=0, ge=0)
    local_commit_count: int = Field(default=0, ge=0)
    protected_path_block_count: int = Field(default=0, ge=0)
    secret_scan_block_count: int = Field(default=0, ge=0)
    scope_block_count: int = Field(default=0, ge=0)
    current_highest_priority_case: str = Field(default="", max_length=700)
    safest_reviewable_patch: str = Field(default="", max_length=700)
    required_human_actions: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaCodeSurgeonSignalUsageV1(BobaContract):
    repair_planner_used: bool = False
    repair_planner_artifact_read: bool = False
    root_cause_references_used: bool = False
    approval_record_used: bool = False
    git_repository_inspected: bool = False
    isolated_worktree_used: bool = False
    provided_patch_used: bool = False
    deterministic_template_used: bool = False
    secret_scan_used: bool = False
    validation_commands_executed: bool = False
    code_modified_in_isolated_worktree: bool = False
    local_branch_created: bool = False
    local_commit_created: bool = False
    main_branch_modified: Literal[False] = False
    push_used: Literal[False] = False
    PR_created: Literal[False] = False
    merge_used: Literal[False] = False
    tag_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    destructive_git_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCodeSurgeonSetV1(BobaContract):
    schema_version: Literal["boba_code_surgeon_v1"] = "boba_code_surgeon_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    repair_planner_source: str = Field(min_length=1, max_length=500)
    repair_cases: list[BobaCodeRepairCaseV1] = Field(default_factory=list, max_length=256)
    patch_proposals: list[BobaCodePatchProposalV1] = Field(
        default_factory=list,
        max_length=256,
    )
    approval_records: list[BobaCodeApprovalRecordV1] = Field(
        default_factory=list,
        max_length=512,
    )
    execution_policies: list[BobaCodeExecutionPolicyV1] = Field(
        default_factory=list,
        max_length=16,
    )
    isolated_runs: list[BobaCodeIsolatedRunV1] = Field(default_factory=list, max_length=256)
    validation_runs: list[BobaCodeValidationRunV1] = Field(
        default_factory=list,
        max_length=256,
    )
    rollback_records: list[BobaCodeRollbackRecordV1] = Field(
        default_factory=list,
        max_length=256,
    )
    review_packages: list[BobaCodeReviewPackageV1] = Field(
        default_factory=list,
        max_length=256,
    )
    execution_handoffs: list[BobaCodeSurgeonExecutionHandoffV1] = Field(
        default_factory=list,
        max_length=512,
    )
    surgeon_summary: BobaCodeSurgeonSummaryV1
    signal_usage: BobaCodeSurgeonSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


@dataclass(frozen=True)
class _ParsedFile:
    path: str
    old_path: str
    operation: BobaCodePatchOperationV1
    additions: int = 0
    deletions: int = 0
    previous_sha: str = ""
    proposed_sha: str = ""
    binary: bool = False
    hunks: tuple[BobaCodePatchHunkV1, ...] = ()


@dataclass(frozen=True)
class _ParsedPatch:
    files: tuple[_ParsedFile, ...]
    additions: int
    deletions: int
    size_bytes: int


@dataclass(frozen=True)
class _ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    output_truncated: bool


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _text(value: Any, *, maximum: int = 900) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _safe_text(value: Any, *, maximum: int = 900) -> str:
    return _PRIVATE_PATH.sub("[private path]", _text(value, maximum=maximum))


def _unique(
    values: Sequence[Any],
    *,
    limit: int,
    maximum: int = 900,
) -> list[str]:
    result: list[str] = []
    for value in values:
        item = _safe_text(value, maximum=maximum)
        if item and item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def default_code_execution_policy() -> BobaCodeExecutionPolicyV1:
    return BobaCodeExecutionPolicyV1(
        policy_id="boba_code_surgeon_default_v1",
        protected_branches=list(_PROTECTED_BRANCHES),
        protected_paths=list(_PROTECTED_PATHS),
        special_approval_paths=list(_SPECIAL_APPROVAL_PATHS),
        allowed_extensions=list(_ALLOWED_EXTENSIONS),
        blocked_extensions=list(_BLOCKED_EXTENSIONS),
        warnings=[
            "Larger bounded repairs require explicit policy override and human approval.",
            "Code Surgeon never pushes, merges, tags, deploys, installs packages, "
            "or restarts services.",
        ],
    )


def sanitize_repair_branch_name(
    project_id: str,
    repair_case_id: str,
    slug: str,
) -> str:
    def component(value: str, fallback: str, maximum: int) -> str:
        normalized = _BRANCH_COMPONENT.sub("-", value.strip().lower())
        normalized = re.sub(r"[.-]{2,}", "-", normalized).strip("./-")
        if (
            not normalized
            or normalized.endswith(".lock")
            or "@{" in normalized
            or _CONTROL.search(normalized)
        ):
            normalized = fallback
        return normalized[:maximum].rstrip("./-") or fallback

    project = component(project_id, "project", 24)
    case = component(repair_case_id, "repair", 28)
    short_slug = component(slug, "bounded-fix", 24)
    identity = hashlib.sha256(
        f"{project_id}|{repair_case_id}|{slug}".encode()
    ).hexdigest()[:8]
    branch = f"boba-repair/{project}/{case}-{short_slug}-{identity}"
    if branch.endswith(".lock") or ".." in branch or "@{" in branch:
        raise ValidationError("Unable to create a safe repair branch name.")
    return branch


def is_protected_branch(branch: str, policy: BobaCodeExecutionPolicyV1) -> bool:
    normalized = branch.strip().lower()
    protected = {item.lower() for item in policy.protected_branches}
    return normalized in protected or normalized.startswith("release/")


def _normalize_patch_path(value: str) -> str:
    raw = value.strip().strip('"').replace("\\", "/")
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return str(PurePosixPath(raw))


def _path_matches(path: str, pattern: str) -> bool:
    normalized = _normalize_patch_path(path).lower()
    candidate = _normalize_patch_path(pattern).lower()
    if candidate.endswith(".*"):
        return normalized == candidate[:-2] or normalized.startswith(candidate[:-1])
    return normalized == candidate or normalized.startswith(f"{candidate.rstrip('/')}/")


def _is_generated_path(path: str) -> bool:
    normalized = _normalize_patch_path(path).lower()
    generated = {
        "work",
        "storage_data",
        "media",
        "uploads",
        "downloads",
        "node_modules",
        "frontend/node_modules",
        "frontend/.next",
        ".venv",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "validation_reports",
    }
    return any(_path_matches(normalized, item) for item in generated)


def _language_for_path(path: str) -> str:
    return {
        ".py": "python",
        ".pyi": "python",
        ".ts": "typescript",
        ".tsx": "typescript-react",
        ".js": "javascript",
        ".jsx": "javascript-react",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".css": "css",
        ".scss": "scss",
        ".html": "html",
        ".sql": "sql",
        ".txt": "text",
    }.get(Path(path).suffix.lower(), "text")


def _parse_unified_diff(unified_diff: str) -> _ParsedPatch:
    encoded = unified_diff.encode("utf-8")
    lines = unified_diff.splitlines()
    parsed: list[_ParsedFile] = []
    current: _ParsedFile | None = None
    current_hunks: list[BobaCodePatchHunkV1] = []
    current_hunk: BobaCodePatchHunkV1 | None = None

    def finish() -> None:
        nonlocal current, current_hunks, current_hunk
        if current is None:
            return
        if current_hunk is not None:
            current_hunks.append(current_hunk)
        parsed.append(replace(current, hunks=tuple(current_hunks)))
        current = None
        current_hunks = []
        current_hunk = None

    for line in lines:
        header = _DIFF_HEADER.match(line)
        if header:
            finish()
            old_path = _normalize_patch_path(header.group(1))
            new_path = _normalize_patch_path(header.group(2))
            current = _ParsedFile(path=new_path, old_path=old_path, operation="modify")
            continue
        if current is None:
            if line.startswith(("--- ", "+++ ", "@@ ", "+", "-")):
                raise ValidationError("Unified diff is missing a canonical diff --git header.")
            continue
        if line.startswith("new file mode "):
            current = replace(current, operation="add")
        elif line.startswith("deleted file mode "):
            current = replace(current, operation="delete")
        elif line.startswith(("rename from ", "rename to ")):
            current = replace(current, operation="rename")
        elif line.startswith(("old mode ", "new mode ")):
            if current.operation == "modify":
                current = replace(current, operation="mode_change")
        elif line.startswith(("GIT binary patch", "Binary files ")):
            current = replace(current, binary=True)
        else:
            index_match = _INDEX_HEADER.match(line)
            if index_match:
                current = replace(
                    current,
                    previous_sha=index_match.group(1),
                    proposed_sha=index_match.group(2),
                )
                continue
            hunk_match = _HUNK_HEADER.match(line)
            if hunk_match:
                if current_hunk is not None:
                    current_hunks.append(current_hunk)
                current_hunk = BobaCodePatchHunkV1(
                    file_path=current.path,
                    old_start=int(hunk_match.group("old_start")),
                    old_count=int(hunk_match.group("old_count") or "1"),
                    new_start=int(hunk_match.group("new_start")),
                    new_count=int(hunk_match.group("new_count") or "1"),
                    bounded_summary=_safe_text(line, maximum=500),
                    risk="low",
                )
            elif line.startswith("+") and not line.startswith("+++"):
                current = replace(current, additions=current.additions + 1)
            elif line.startswith("-") and not line.startswith("---"):
                current = replace(current, deletions=current.deletions + 1)
    finish()
    if not parsed:
        raise ValidationError("Unified diff contains no changed files.")
    paths = [item.path for item in parsed]
    if len(paths) != len(set(paths)):
        raise ValidationError("Unified diff repeats a target file.")
    return _ParsedPatch(
        files=tuple(parsed),
        additions=sum(item.additions for item in parsed),
        deletions=sum(item.deletions for item in parsed),
        size_bytes=len(encoded),
    )


def calculate_patch_digest(unified_diff: str) -> str:
    return hashlib.sha256(unified_diff.encode("utf-8")).hexdigest()


def scan_patch_for_secrets(unified_diff: str) -> tuple[bool, list[str]]:
    findings: list[str] = []
    for raw_line in unified_diff.splitlines():
        if not raw_line.startswith("+") or raw_line.startswith("+++"):
            continue
        line = raw_line[1:].strip()
        for category, pattern in _SECRET_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            candidate = match.group(1) if match.lastindex else match.group(0)
            if _PLACEHOLDER_SECRET.match(candidate):
                continue
            fingerprint = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:12]
            findings.append(f"{category}:[redacted:{fingerprint}]")
    return not findings, _unique(findings, limit=32, maximum=120)


def review_patch_quality(unified_diff: str) -> tuple[bool, list[str]]:
    findings: list[str] = []
    deleted_test = False
    for line in unified_diff.splitlines():
        if line.startswith("diff --git "):
            deleted_test = "tests/" in line.replace("\\", "/").lower()
        if deleted_test and line.startswith("deleted file mode"):
            findings.append("deleting_failing_or_regression_test")
        for category, pattern in _SUSPICIOUS_PATCH_PATTERNS:
            if pattern.search(line):
                findings.append(category)
    blocking = {
        "deleting_failing_or_regression_test",
        "test_skip",
        "ignored_exception",
        "always_success",
        "validation_bypass",
        "rights_bypass",
        "quality_threshold_weakened",
    }
    unique = _unique(findings, limit=32, maximum=120)
    return not any(item in blocking for item in unique), unique


def _validate_single_path(
    path: str,
    *,
    repository_root: Path,
    policy: BobaCodeExecutionPolicyV1,
) -> tuple[bool, bool, bool, list[str]]:
    warnings: list[str] = []
    raw = path.strip()
    normalized = _normalize_patch_path(raw)
    if (
        not raw
        or _CONTROL.search(raw)
        or raw.startswith(("/", "\\\\"))
        or _WINDOWS_DRIVE.match(raw)
        or ":" in normalized
    ):
        return False, False, False, ["absolute, UNC, drive, or control-character path rejected"]
    pure = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in pure.parts):
        return False, False, False, ["path traversal or ambiguous path rejected"]
    protected = any(_path_matches(normalized, item) for item in policy.protected_paths)
    special = any(
        _path_matches(normalized, item) for item in policy.special_approval_paths
    )
    generated = _is_generated_path(normalized)
    extension = Path(normalized).suffix.lower()
    if extension in policy.blocked_extensions:
        warnings.append("blocked binary or media extension")
    if (not extension or extension not in policy.allowed_extensions) and not special:
        warnings.append("file extension is not allowlisted")
    root = repository_root.resolve()
    target = (root / Path(*pure.parts)).resolve(strict=False)
    if target != root and root not in target.parents:
        warnings.append("resolved path escapes repository root")
    cursor = root
    for part in pure.parts:
        cursor /= part
        if cursor.exists() and cursor.is_symlink():
            resolved = cursor.resolve()
            if resolved != root and root not in resolved.parents:
                warnings.append("symlink escapes repository root")
                break
    if target.exists() and target.is_file():
        try:
            if target.stat().st_size > policy.maximum_individual_file_size_bytes:
                warnings.append("existing file exceeds individual file-size limit")
            if b"\x00" in target.read_bytes()[:8_192]:
                warnings.append("existing file appears binary")
        except OSError:
            warnings.append("existing file could not be inspected")
    passed = not protected and not generated and not warnings
    return passed, protected, special, warnings


def validate_patch_paths(
    parsed: _ParsedPatch,
    *,
    repository_root: Path,
    policy: BobaCodeExecutionPolicyV1,
    approved_special_paths: Sequence[str] = (),
) -> tuple[list[BobaCodePatchFileV1], bool, list[str]]:
    approved_special = {_normalize_patch_path(item) for item in approved_special_paths}
    files: list[BobaCodePatchFileV1] = []
    global_warnings: list[str] = []
    passed = True
    for item in parsed.files:
        path_passed, protected, special, warnings = _validate_single_path(
            item.path,
            repository_root=repository_root,
            policy=policy,
        )
        if special and item.path not in approved_special:
            warnings.append("special path requires exact separate approval")
            path_passed = False
        if (
            item.operation in {"delete", "rename", "mode_change"}
            and item.path not in approved_special
        ):
            warnings.append(f"{item.operation} requires exact separate approval")
            path_passed = False
        if item.binary:
            warnings.append("binary patch content is not supported")
            path_passed = False
        generated = _is_generated_path(item.path)
        passed = passed and path_passed
        global_warnings.extend(f"{item.path}: {warning}" for warning in warnings)
        files.append(
            BobaCodePatchFileV1(
                path=item.path,
                operation=item.operation,
                language=_language_for_path(item.path),
                previous_sha256=item.previous_sha,
                proposed_sha256=item.proposed_sha,
                additions=item.additions,
                deletions=item.deletions,
                binary=item.binary,
                generated=generated,
                protected=protected,
                special_approval_required=special
                or item.operation in {"delete", "rename", "mode_change"},
                reason_for_change="Bounded change proposed for the selected repair case.",
                behavior_preserved=["Unrelated repository behavior must remain unchanged."],
                validation_needed=["Run the approved scoped validation registry."],
                warnings=_unique(warnings, limit=32, maximum=500),
            )
        )
    return files, passed, _unique(global_warnings, limit=64, maximum=700)


def validate_patch_scope(
    changed_paths: Sequence[str],
    approved_paths: Sequence[str],
) -> tuple[bool, list[str]]:
    normalized_scope = [_normalize_patch_path(item) for item in approved_paths if item]
    if not normalized_scope:
        return False, ["No bounded target path scope is available."]
    outside = [
        path
        for path in changed_paths
        if not any(_path_matches(path, allowed) for allowed in normalized_scope)
    ]
    if outside:
        return False, [f"Out-of-scope path rejected: {path}" for path in outside]
    return True, []


def _git_result(
    repository_root: Path,
    arguments: Sequence[str],
    *,
    timeout: int = 30,
    output_limit: int = 64_000,
) -> _ProcessResult:
    return _run_process(
        ["git", *arguments],
        cwd=repository_root,
        timeout_seconds=timeout,
        output_limit_bytes=output_limit,
    )


def _bounded_read(handle: Any, limit: int) -> tuple[str, bool]:
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    truncated = size > limit
    handle.seek(max(0, size - limit))
    payload = handle.read(limit)
    text = (
        payload.decode("utf-8", errors="replace")
        if isinstance(payload, bytes)
        else str(payload)
    )
    return _redact_output(text), truncated


def _redact_output(value: str) -> str:
    redacted = _PRIVATE_PATH.sub("[private path]", value)
    for _, pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[redacted secret]", redacted)
    return redacted[-66_000:]


def _sanitized_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "LANG",
        "LC_ALL",
        "PYTHONIOENCODING",
        "VIRTUAL_ENV",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed and not _SECRET_ENV_KEY.search(key)
    }
    environment.update(
        {
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "NPM_CONFIG_OFFLINE": "true",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _run_process(
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    output_limit_bytes: int,
) -> _ProcessResult:
    started = time.monotonic()
    with tempfile.TemporaryFile() as stdout_handle, tempfile.TemporaryFile() as stderr_handle:
        try:
            process = subprocess.Popen(
                list(arguments),
                cwd=cwd,
                env=_sanitized_environment(),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                shell=False,
            )
        except OSError as exc:
            return _ProcessResult(
                exit_code=None,
                stdout="",
                stderr=_redact_output(str(exc)),
                duration_seconds=round(time.monotonic() - started, 4),
                timed_out=False,
                output_truncated=False,
            )
        timed_out = False
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            exit_code = process.wait()
        stdout, stdout_truncated = _bounded_read(stdout_handle, output_limit_bytes)
        stderr, stderr_truncated = _bounded_read(stderr_handle, output_limit_bytes)
    return _ProcessResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=round(time.monotonic() - started, 4),
        timed_out=timed_out,
        output_truncated=stdout_truncated or stderr_truncated,
    )


def _repository_sha(repository_root: Path, ref: str) -> str:
    result = _git_result(repository_root, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    sha = result.stdout.strip().splitlines()[-1] if result.exit_code == 0 else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValidationError(
            "The requested Git base commit could not be verified.",
            details={"ref": _safe_text(ref, maximum=120)},
        )
    return sha


def _repository_clean(repository_root: Path) -> tuple[bool, str]:
    result = _git_result(repository_root, ["status", "--porcelain=v1", "--untracked-files=all"])
    if result.exit_code != 0:
        return False, result.stderr or "Git status failed."
    return not result.stdout.strip(), result.stdout


def _patch_applies(
    repository_root: Path,
    unified_diff: str,
    *,
    policy: BobaCodeExecutionPolicyV1,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="boba-code-surgeon-check-") as directory:
        patch_path = Path(directory) / "patch.diff"
        patch_path.write_text(unified_diff, encoding="utf-8", newline="\n")
        result = _git_result(
            repository_root,
            ["apply", "--check", "--", str(patch_path)],
            timeout=min(policy.command_timeout_seconds, 60),
            output_limit=policy.output_capture_limit_bytes,
        )
    return result.exit_code == 0, _safe_text(result.stderr or result.stdout, maximum=700)


def _render_exact_text_template(
    repository_root: Path,
    parameters: Mapping[str, Any],
) -> str:
    path = _normalize_patch_path(str(parameters.get("path") or ""))
    old_text = str(parameters.get("old_text") or "")
    new_text = str(parameters.get("new_text") or "")
    if not path or not old_text or old_text == new_text:
        raise ValidationError(
            "The exact-text template requires path, old_text, and a different new_text."
        )
    source = repository_root / Path(*PurePosixPath(path).parts)
    if not source.is_file():
        raise ValidationError("The exact-text template target is not a text file.")
    content = source.read_text(encoding="utf-8")
    if content.count(old_text) != 1:
        raise ValidationError(
            "The exact-text template requires exactly one matching old_text occurrence."
        )
    updated = content.replace(old_text, new_text, 1)
    return "".join(
        difflib.unified_diff(
            content.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    ).replace(f"--- a/{path}\n", f"diff --git a/{path} b/{path}\n--- a/{path}\n", 1)


def _planner_model(value: BobaRepairPlannerSetV1 | Mapping[str, Any] | None) -> (
    BobaRepairPlannerSetV1 | None
):
    if isinstance(value, BobaRepairPlannerSetV1):
        return value
    if isinstance(value, Mapping):
        try:
            return BobaRepairPlannerSetV1.model_validate(dict(value))
        except PydanticValidationError:
            return None
    return None


def _selected_planner_parts(
    planner: BobaRepairPlannerSetV1,
    *,
    repair_case_id: str | None,
    repair_strategy_id: str | None,
) -> tuple[
    BobaRepairPlanningCaseV1 | None,
    BobaRepairStrategyV1 | None,
    BobaRepairExecutionHandoffV1 | None,
    BobaRepairValidationPlanV1 | None,
]:
    handoffs = [
        item for item in planner.execution_handoffs if item.target_module == "code_surgeon"
    ]
    handoff = next(
        (
            item
            for item in handoffs
            if not repair_case_id or item.repair_case_id == repair_case_id
        ),
        None,
    )
    selected_case_id = repair_case_id or (handoff.repair_case_id if handoff else "")
    case = next(
        (item for item in planner.repair_cases if item.repair_case_id == selected_case_id),
        None,
    )
    selected_strategy_id = (
        repair_strategy_id
        or (handoff.repair_strategy_id if handoff else "")
        or (case.recommended_strategy_id if case else "")
    )
    strategy = next(
        (
            item
            for item in planner.repair_strategies
            if item.repair_strategy_id == selected_strategy_id
        ),
        None,
    )
    validation_plan = next(
        (
            item
            for item in planner.validation_plans
            if case and item.validation_plan_id == case.validation_plan_id
        ),
        None,
    )
    return case, strategy, handoff, validation_plan


def _evidence_strength(case: BobaRepairPlanningCaseV1 | None) -> BobaCodeEvidenceStrengthV1:
    if case is None:
        return "insufficient"
    if case.planning_status == "conflicting_causes":
        return "conflicting"
    if case.planning_status == "needs_more_evidence":
        return "weak"
    if case.confidence >= 0.86 and case.planning_status == "plan_ready":
        return "strong"
    if case.confidence >= 0.72 and case.planning_status in {
        "plan_ready",
        "conditional_plan",
    }:
        return "moderate"
    if case.confidence > 0:
        return "weak"
    return "unknown"


def verify_code_repair_eligibility(
    planner: BobaRepairPlannerSetV1 | Mapping[str, Any] | None,
    *,
    repair_case_id: str | None = None,
    repair_strategy_id: str | None = None,
    affected_paths: Sequence[str] = (),
) -> BobaCodeRepairCaseV1:
    model = _planner_model(planner)
    fallback_id = repair_case_id or "unavailable"
    if model is None:
        return BobaCodeRepairCaseV1(
            code_repair_case_id=_stable_id("code_repair_case", fallback_id),
            source_repair_case_id=fallback_id,
            title="Code repair handoff unavailable",
            suspected_code_defect="No valid persisted Repair Planner artifact was available.",
            evidence_strength="insufficient",
            code_change_justified=False,
            justification="Code Surgeon cannot justify a code change without a valid saved plan.",
            affected_paths=[],
            required_behavior=["Return to Repair Planner or Root Cause Analyzer."],
            behavior_to_preserve=["Do not modify repository code."],
            validation_requirements=[],
            quality_requirements=[],
            rollback_requirements=[],
            execution_eligible=False,
            blocked_reason="Missing or malformed Repair Planner artifact.",
            confidence=0.0,
            warnings=["No patch was generated."],
            limitations=["Code Surgeon does not regenerate upstream diagnosis."],
        )
    case, strategy, handoff, validation = _selected_planner_parts(
        model,
        repair_case_id=repair_case_id,
        repair_strategy_id=repair_strategy_id,
    )
    if case is None:
        return BobaCodeRepairCaseV1(
            code_repair_case_id=_stable_id("code_repair_case", fallback_id),
            source_repair_case_id=fallback_id,
            title="Selected repair case unavailable",
            suspected_code_defect="The requested saved repair case could not be found.",
            evidence_strength="insufficient",
            code_change_justified=False,
            justification="A bounded persisted repair case is required.",
            affected_paths=[],
            required_behavior=["Select a saved Code Surgeon handoff."],
            behavior_to_preserve=["Do not modify repository code."],
            validation_requirements=[],
            quality_requirements=[],
            rollback_requirements=[],
            execution_eligible=False,
            blocked_reason="No matching repair case exists.",
            confidence=0.0,
            warnings=["No patch was generated."],
            limitations=["Only persisted Repair Planner cases are accepted."],
        )
    strength = _evidence_strength(case)
    rollback = next(
        (
            item
            for item in model.rollback_plans
            if item.rollback_plan_id == case.rollback_plan_id
        ),
        None,
    )
    quality = next(
        (
            item
            for item in model.quality_preservation_plans
            if item.quality_preservation_plan_id == case.quality_preservation_plan_id
        ),
        None,
    )
    blockers: list[str] = []
    if handoff is None:
        blockers.append("Repair Planner did not create a Code Surgeon handoff.")
    if case.repair_scope != "code":
        blockers.append(f"Repair scope is {case.repair_scope}, not code.")
    if strategy is None or not strategy.requires_code_change:
        blockers.append("No selected code-change strategy is available.")
    if strength not in {"strong", "moderate"}:
        blockers.append(f"Evidence strength is {strength}.")
    if validation is None or not validation.acceptance_criteria:
        blockers.append("A bounded validation plan is missing.")
    if rollback is None or not rollback.rollback_steps:
        blockers.append("A bounded rollback plan is missing.")
    if case.planning_status in {
        "intentional_safety_block",
        "human_decision_required",
        "blocked",
    }:
        blockers.append(f"Planning status {case.planning_status} blocks execution.")
    if strategy and (
        strategy.destructiveness in {"high", "blocked"}
        or strategy.requires_external_access
        or strategy.requires_package_installation
        or strategy.requires_service_restart
    ):
        blockers.append("The selected strategy requires prohibited or destructive capability.")
    paths = _unique(affected_paths, limit=64, maximum=500)
    if not paths and case.primary_artifact and (
        "/" in case.primary_artifact or Path(case.primary_artifact).suffix
    ):
        paths = [_normalize_patch_path(case.primary_artifact)]
    code_change_justified = (
        case.repair_needed
        and case.repair_scope == "code"
        and strength in {"strong", "moderate"}
        and handoff is not None
    )
    return BobaCodeRepairCaseV1(
        code_repair_case_id=_stable_id("code_repair_case", case.repair_case_id),
        source_repair_case_id=case.repair_case_id,
        source_repair_strategy_id=strategy.repair_strategy_id if strategy else "",
        title=case.title,
        target_module=case.primary_module,
        suspected_code_defect=case.selected_root_cause_summary,
        evidence_strength=strength,
        code_change_justified=code_change_justified,
        justification=(
            "Saved Repair Planner evidence supports a bounded code review."
            if code_change_justified
            else "Saved evidence does not yet justify isolated code modification."
        ),
        affected_paths=paths,
        protected_paths_detected=[],
        required_behavior=_unique(
            [
                strategy.expected_result if strategy else "",
                case.expected_workflow_impact,
            ],
            limit=32,
        ),
        behavior_to_preserve=_unique(
            quality.non_negotiable_requirements if quality else [],
            limit=32,
        ),
        validation_requirements=_unique(
            [
                *(validation.required_validators if validation else []),
                *(validation.acceptance_criteria if validation else []),
            ],
            limit=64,
        ),
        quality_requirements=_unique(
            [
                *(quality.technical_quality_checks if quality else []),
                *(quality.creative_quality_checks if quality else []),
                *(quality.rights_safety_checks if quality else []),
            ],
            limit=64,
        ),
        rollback_requirements=_unique(
            [
                *(rollback.rollback_steps if rollback else []),
                *(rollback.rollback_validation if rollback else []),
            ],
            limit=64,
        ),
        execution_eligible=code_change_justified and not blockers,
        blocked_reason=" ".join(blockers) or None,
        confidence=case.confidence,
        warnings=_unique(
            [
                *case.warnings,
                *([] if paths else ["Exact affected paths must be supplied with the patch."]),
            ],
            limit=64,
        ),
        limitations=_unique(
            [
                *case.limitations,
                "Code Surgeon V1 does not invent arbitrary repairs.",
            ],
            limit=64,
        ),
    )


def _proposal_handoffs(
    repair_case: BobaCodeRepairCaseV1,
    proposal: BobaCodePatchProposalV1 | None,
) -> list[BobaCodeSurgeonExecutionHandoffV1]:
    proposal_id = proposal.patch_proposal_id if proposal else ""
    target: BobaCodeHandoffTargetV1 = (
        "manual_git_review"
        if proposal and proposal.execution_status != "blocked"
        else "repair_planner"
    )
    return [
        BobaCodeSurgeonExecutionHandoffV1(
            handoff_id=_stable_id(
                "code_surgeon_handoff",
                repair_case.code_repair_case_id,
                proposal_id,
                target,
            ),
            code_repair_case_id=repair_case.code_repair_case_id,
            patch_proposal_id=proposal_id,
            target_module=target,
            reason=(
                "Review the exact bounded patch and approval scope."
                if target == "manual_git_review"
                else "Repair evidence or scope must be strengthened before a patch can run."
            ),
            required_inputs=[
                "Exact base commit SHA",
                "Exact diff SHA-256",
                "Exact changed-path scope",
                "Approved validation command names",
            ],
            validation_requirements=repair_case.validation_requirements[:32],
            constraints=[
                "Apply only inside an isolated Git worktree.",
                "Never modify main directly.",
                "Stop after any failed required validation.",
            ],
            prohibited_actions=[
                "Push, merge, tag, deploy, install packages, restart services, "
                "or access the network",
                "Run destructive Git commands",
            ],
            apply_automatically=False,
            human_approval_required=True,
            priority="high" if repair_case.execution_eligible else "medium",
            warnings=["Human review is mandatory."],
        )
    ]


def _summary(report: BobaCodeSurgeonSetV1) -> BobaCodeSurgeonSummaryV1:
    proposals = report.patch_proposals
    return BobaCodeSurgeonSummaryV1(
        total_repair_cases=len(report.repair_cases),
        eligible_case_count=sum(item.execution_eligible for item in report.repair_cases),
        blocked_case_count=sum(not item.execution_eligible for item in report.repair_cases),
        proposal_count=len(proposals),
        approved_proposal_count=sum(
            item.approval_status == "approved_for_isolated_execution" for item in proposals
        ),
        isolated_execution_count=sum(item.worktree_created for item in report.isolated_runs),
        validation_pass_count=sum(
            item.required_checks_passed and item.acceptance_criteria_met
            for item in report.validation_runs
        ),
        validation_failure_count=sum(
            not item.required_checks_passed for item in report.validation_runs
        ),
        rollback_count=len(report.rollback_records),
        local_commit_count=sum(item.commit_created for item in report.review_packages),
        protected_path_block_count=sum(
            not item.path_policy_passed
            and any(file.protected for file in item.files)
            for item in proposals
        ),
        secret_scan_block_count=sum(not item.secret_scan_passed for item in proposals),
        scope_block_count=sum(not item.scope_check_passed for item in proposals),
        current_highest_priority_case=(
            report.repair_cases[0].title if report.repair_cases else ""
        ),
        safest_reviewable_patch=next(
            (
                item.title
                for item in proposals
                if item.execution_status in {"validation_ready", "validation_passed"}
            ),
            "",
        ),
        required_human_actions=[
            "Review the exact diff, base SHA, changed paths, risk, and validation plan.",
            "Provide separate explicit approval for isolated execution.",
            "Provide separate explicit approval before a local commit.",
            "Push, PR, merge, deployment, and release remain manual.",
        ],
        limitations=[
            "Passing validation does not guarantee production correctness.",
            "V1 supports reviewed diffs and deterministic exact-text templates only.",
        ],
    )


def _base_report(
    project_id: str,
    source_id: str,
    repair_case: BobaCodeRepairCaseV1,
    policy: BobaCodeExecutionPolicyV1,
    *,
    planner_available: bool,
    proposal: BobaCodePatchProposalV1 | None = None,
    proposal_source: BobaCodeProposalSourceV1 = "unknown",
) -> BobaCodeSurgeonSetV1:
    report = BobaCodeSurgeonSetV1(
        project_id=project_id,
        source_id=source_id,
        repair_planner_source="repair_planner/index.json",
        repair_cases=[repair_case],
        patch_proposals=[proposal] if proposal else [],
        approval_records=[],
        execution_policies=[policy],
        isolated_runs=[],
        validation_runs=[],
        rollback_records=[],
        review_packages=[],
        execution_handoffs=_proposal_handoffs(repair_case, proposal),
        surgeon_summary=BobaCodeSurgeonSummaryV1(),
        signal_usage=BobaCodeSurgeonSignalUsageV1(
            repair_planner_used=planner_available,
            repair_planner_artifact_read=planner_available,
            root_cause_references_used=bool(repair_case.source_repair_case_id),
            git_repository_inspected=proposal is not None,
            provided_patch_used=proposal_source
            in {"user_provided_diff", "codex_provided_diff", "imported_review_patch"},
            deterministic_template_used=proposal_source == "deterministic_template",
            secret_scan_used=proposal is not None,
            fallback_used=not planner_available,
            unavailable_signals=(
                [] if planner_available else ["persisted_repair_planner"]
            ),
        ),
        warnings=(
            []
            if planner_available
            else ["Code Surgeon remained blocked because Repair Planner was unavailable."]
        ),
        limitations=[
            "No arbitrary coding model is used in V1.",
            "Code Surgeon does not push, open remote PRs, merge, tag, deploy, or release.",
        ],
    )
    report.surgeon_summary = _summary(report)
    return report


def _replace_proposal(
    report: BobaCodeSurgeonSetV1,
    proposal: BobaCodePatchProposalV1,
) -> None:
    report.patch_proposals = [
        proposal if item.patch_proposal_id == proposal.patch_proposal_id else item
        for item in report.patch_proposals
    ]


def verify_approval(
    proposal: BobaCodePatchProposalV1,
    approval: BobaCodeApprovalRecordV1,
    *,
    required_type: BobaCodeApprovalTypeV1,
) -> list[str]:
    errors: list[str] = []
    if not approval.approved or not approval.explicit_confirmation:
        errors.append("Approval is not explicit.")
    if approval.approval_type != required_type:
        errors.append(f"Approval type must be {required_type}.")
    if approval.patch_proposal_id != proposal.patch_proposal_id:
        errors.append("Approval is bound to a different patch proposal.")
    if approval.code_repair_case_id != proposal.code_repair_case_id:
        errors.append("Approval is bound to a different repair case.")
    if approval.approved_base_commit_sha != proposal.base_commit_sha:
        errors.append("Approval base SHA does not match.")
    if approval.approved_diff_sha256 != proposal.diff_sha256:
        errors.append("Approval diff SHA does not match.")
    approved_scope = {_normalize_patch_path(item) for item in approval.approved_scope}
    proposal_scope = {item.path for item in proposal.files}
    if approved_scope != proposal_scope:
        errors.append("Approval path scope does not exactly match the patch.")
    required_special = {
        item.path for item in proposal.files if item.special_approval_required
    }
    approved_special = {
        _normalize_patch_path(item) for item in approval.approved_special_paths
    }
    if not required_special.issubset(approved_special):
        errors.append("Required special-path approval is missing.")
    if approval.approval_expires_at:
        try:
            expires = datetime.fromisoformat(approval.approval_expires_at.replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= datetime.now(UTC):
                errors.append("Approval has expired.")
        except ValueError:
            errors.append("Approval expiry timestamp is invalid.")
    return errors


def _command_is_safe(command: BobaCodeValidationCommandV1) -> tuple[bool, str]:
    executable_name = Path(command.executable).name.lower()
    allowed_executables = {
        "git",
        "git.exe",
        "python",
        "python.exe",
        Path(sys.executable).name.lower(),
        "npm",
        "npm.cmd",
    }
    if executable_name not in allowed_executables:
        return False, "Executable is not allowlisted."
    forbidden_fragments = {"|", ">", "<", ";", "&&", "||", "$(", "`"}
    for argument in command.arguments:
        if any(fragment in argument for fragment in forbidden_fragments):
            return False, "Shell metacharacter or command chaining was rejected."
        if _CONTROL.search(argument):
            return False, "Control characters were rejected."
    lowered = [item.lower() for item in command.arguments]
    if executable_name.startswith("python"):
        if "-c" in lowered:
            return False, "Arbitrary Python -c execution is forbidden."
        allowed_modules = {"ruff", "pytest", "mypy", "compileall"}
        if (
            len(lowered) < 2
            or lowered[0] != "-m"
            or lowered[1] not in allowed_modules
        ):
            return False, "Direct or unapproved Python script execution is forbidden."
    if executable_name.startswith("npm") and "install" in lowered:
        return False, "Package installation is forbidden."
    if executable_name.startswith("python") and "pip" in lowered:
        return False, "Package installation is forbidden."
    if executable_name.startswith("git"):
        forbidden_git = {
            "push",
            "pull",
            "merge",
            "rebase",
            "cherry-pick",
            "reset",
            "clean",
            "tag",
            "gc",
            "remote",
            "config",
        }
        if any(item in forbidden_git for item in lowered):
            return False, "Prohibited Git operation was rejected."
        if any(item in {"--force", "-f"} for item in lowered):
            return False, "Force option was rejected."
    if any(
        item in {"shutdown", "restart", "reboot", "stop-service", "start-service"}
        for item in lowered
    ):
        return False, "Service or system control is forbidden."
    return True, ""


def validate_command_safety(
    command: BobaCodeValidationCommandV1,
) -> tuple[bool, str]:
    return _command_is_safe(command)


def build_validation_commands(
    repository_root: Path,
    changed_paths: Sequence[str],
    approved_names: Sequence[str],
    *,
    policy: BobaCodeExecutionPolicyV1,
) -> list[BobaCodeValidationCommandV1]:
    names = list(dict.fromkeys(approved_names))
    if "git_diff_check" not in names:
        names.insert(0, "git_diff_check")
    python_paths = [
        path for path in changed_paths if Path(path).suffix.lower() in {".py", ".pyi"}
    ]
    changed_test_paths = [
        path for path in python_paths if path.replace("\\", "/").startswith("tests/")
    ]
    inferred_test_paths: list[str] = []
    for path in python_paths:
        normalized = path.replace("\\", "/")
        if not normalized.startswith("src/"):
            continue
        candidate = f"tests/unit/test_{Path(normalized).stem}.py"
        if (repository_root / candidate).is_file():
            inferred_test_paths.append(candidate)
    test_paths = list(dict.fromkeys([*changed_test_paths, *inferred_test_paths]))
    frontend_changed = any(path.startswith("frontend/") for path in changed_paths)
    registry: dict[str, BobaCodeValidationCommandV1] = {
        "git_diff_check": BobaCodeValidationCommandV1(
            validation_command_id="git_diff_check",
            name="git_diff_check",
            executable="git",
            arguments=["diff", "--check"],
            category="git_diff_check",
            required=True,
            approved="git_diff_check" in names,
            timeout_seconds=min(policy.command_timeout_seconds, 60),
            output_limit_bytes=policy.output_capture_limit_bytes,
        ),
        "ruff": BobaCodeValidationCommandV1(
            validation_command_id="ruff",
            name="ruff",
            executable=sys.executable,
            arguments=["-m", "ruff", "check", *python_paths],
            category="lint",
            required=True,
            approved="ruff" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if python_paths else ["No Python paths were selected."],
        ),
        "mypy": BobaCodeValidationCommandV1(
            validation_command_id="mypy",
            name="mypy",
            executable=sys.executable,
            arguments=["-m", "mypy", *python_paths],
            category="typecheck",
            required=True,
            approved="mypy" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if python_paths else ["No Python paths were selected."],
        ),
        "pytest": BobaCodeValidationCommandV1(
            validation_command_id="pytest",
            name="pytest",
            executable=sys.executable if test_paths else "unavailable",
            arguments=["-m", "pytest", *test_paths] if test_paths else [],
            category="unit_test",
            required=True,
            approved="pytest" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if test_paths else ["No bounded focused test path was found."],
        ),
        "python_compile": BobaCodeValidationCommandV1(
            validation_command_id="python_compile",
            name="python_compile",
            executable=sys.executable,
            arguments=["-m", "compileall", "-q", *python_paths],
            category="schema",
            required=True,
            approved="python_compile" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if python_paths else ["No Python paths were selected."],
        ),
        "frontend_typecheck": BobaCodeValidationCommandV1(
            validation_command_id="frontend_typecheck",
            name="frontend_typecheck",
            executable=shutil.which("npm") or "npm",
            arguments=["run", "typecheck"],
            working_directory_scope="frontend",
            category="typecheck",
            required=True,
            approved="frontend_typecheck" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if frontend_changed else ["No frontend paths were selected."],
        ),
        "frontend_lint": BobaCodeValidationCommandV1(
            validation_command_id="frontend_lint",
            name="frontend_lint",
            executable=shutil.which("npm") or "npm",
            arguments=["run", "lint"],
            working_directory_scope="frontend",
            category="lint",
            required=True,
            approved="frontend_lint" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if frontend_changed else ["No frontend paths were selected."],
        ),
        "frontend_test": BobaCodeValidationCommandV1(
            validation_command_id="frontend_test",
            name="frontend_test",
            executable=shutil.which("npm") or "npm",
            arguments=["test"],
            working_directory_scope="frontend",
            category="unit_test",
            required=True,
            approved="frontend_test" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if frontend_changed else ["No frontend paths were selected."],
        ),
        "frontend_build": BobaCodeValidationCommandV1(
            validation_command_id="frontend_build",
            name="frontend_build",
            executable=shutil.which("npm") or "npm",
            arguments=["run", "build"],
            working_directory_scope="frontend",
            category="build",
            required=True,
            approved="frontend_build" in names,
            timeout_seconds=policy.command_timeout_seconds,
            output_limit_bytes=policy.output_capture_limit_bytes,
            warnings=[] if frontend_changed else ["No frontend paths were selected."],
        ),
    }
    commands: list[BobaCodeValidationCommandV1] = []
    for name in names:
        command = registry.get(name)
        if command is None:
            commands.append(
                BobaCodeValidationCommandV1(
                    validation_command_id=_stable_id("unavailable_command", name),
                    name=name,
                    executable="unavailable",
                    arguments=[],
                    category="unknown",
                    required=True,
                    approved=True,
                    timeout_seconds=policy.command_timeout_seconds,
                    output_limit_bytes=policy.output_capture_limit_bytes,
                    warnings=["Requested validator is not in the trusted registry."],
                )
            )
        else:
            commands.append(command)
        if len(commands) >= policy.maximum_validation_commands:
            break
    return commands


def execute_allowlisted_validation(
    worktree_root: Path,
    isolated_run_id: str,
    commands: Sequence[BobaCodeValidationCommandV1],
) -> BobaCodeValidationRunV1:
    started_at = now_iso()
    results: list[BobaCodeValidationResultV1] = []
    for command in commands:
        safe, reason = _command_is_safe(command)
        working_directory = (worktree_root / command.working_directory_scope).resolve(
            strict=False
        )
        root = worktree_root.resolve()
        in_scope = working_directory == root or root in working_directory.parents
        if not command.approved or not safe or not in_scope or not working_directory.is_dir():
            status: BobaCodeValidationStatusV1 = (
                "skipped" if not command.approved else "blocked"
            )
            if command.executable == "unavailable":
                status = "unavailable"
            results.append(
                BobaCodeValidationResultV1(
                    validation_result_id=_stable_id(
                        "validation_result",
                        isolated_run_id,
                        command.validation_command_id,
                    ),
                    validation_command_id=command.validation_command_id,
                    name=command.name,
                    status=status,
                    bounded_stderr_summary=_safe_text(
                        reason
                        or (
                            "Command was not explicitly approved."
                            if not command.approved
                            else "Working directory is unavailable or outside the worktree."
                        ),
                        maximum=700,
                    ),
                    required=command.required,
                    blocks_acceptance=command.required,
                    warnings=command.warnings,
                )
            )
            if command.required:
                break
            continue
        result = _run_process(
            [command.executable, *command.arguments],
            cwd=working_directory,
            timeout_seconds=command.timeout_seconds,
            output_limit_bytes=command.output_limit_bytes,
        )
        if result.timed_out:
            status = "timed_out"
        elif result.exit_code in command.expected_exit_codes:
            status = "passed"
        else:
            status = "failed"
        results.append(
            BobaCodeValidationResultV1(
                validation_result_id=_stable_id(
                    "validation_result",
                    isolated_run_id,
                    command.validation_command_id,
                ),
                validation_command_id=command.validation_command_id,
                name=command.name,
                status=status,
                exit_code=result.exit_code,
                duration_seconds=result.duration_seconds,
                bounded_stdout_summary=result.stdout,
                bounded_stderr_summary=result.stderr,
                output_truncated=result.output_truncated,
                secrets_redacted=True,
                required=command.required,
                blocks_acceptance=command.required and status != "passed",
                warnings=command.warnings,
            )
        )
        if command.required and status != "passed":
            break
    failed_required = [
        item.name for item in results if item.required and item.status != "passed"
    ]
    failed_optional = [
        item.name for item in results if not item.required and item.status != "passed"
    ]
    skipped = [
        item.name
        for item in results
        if item.status in {"skipped", "unavailable", "blocked"}
    ]
    required_commands = [item for item in commands if item.required]
    completed_required = {
        item.validation_command_id
        for item in results
        if item.required and item.status == "passed"
    }
    required_passed = (
        not failed_required
        and all(item.validation_command_id in completed_required for item in required_commands)
    )
    optional_passed = not failed_optional
    return BobaCodeValidationRunV1(
        validation_run_id=_stable_id("validation_run", isolated_run_id),
        isolated_run_id=isolated_run_id,
        commands=list(commands),
        results=results,
        required_checks_passed=required_passed,
        optional_checks_passed=optional_passed,
        failed_required_checks=failed_required,
        failed_optional_checks=failed_optional,
        skipped_checks=skipped,
        acceptance_criteria_met=required_passed,
        rejection_reason=(
            None
            if required_passed
            else (
                "At least one required check failed, timed out, was blocked, "
                "unavailable, or skipped."
            )
        ),
        started_at=started_at,
        completed_at=now_iso(),
        warnings=[] if required_passed else ["The patch was not accepted."],
    )


def _build_review_package(
    proposal: BobaCodePatchProposalV1,
    run: BobaCodeIsolatedRunV1 | None,
    validation: BobaCodeValidationRunV1 | None,
    rollback: BobaCodeRollbackRecordV1 | None,
    *,
    commit_sha: str = "",
) -> BobaCodeReviewPackageV1:
    validation_passed = bool(
        validation
        and validation.required_checks_passed
        and validation.acceptance_criteria_met
    )
    return BobaCodeReviewPackageV1(
        review_package_id=_stable_id(
            "review_package",
            proposal.patch_proposal_id,
            run.isolated_run_id if run else "proposal",
        ),
        patch_proposal_id=proposal.patch_proposal_id,
        isolated_run_id=run.isolated_run_id if run else "",
        repair_branch=proposal.proposed_branch,
        base_commit_sha=proposal.base_commit_sha,
        local_commit_sha=commit_sha,
        commit_created=bool(commit_sha),
        diff_summary=(
            f"{proposal.changed_file_count} file(s), +{proposal.additions}/"
            f"-{proposal.deletions}; diff {proposal.diff_sha256[:12]}."
        ),
        changed_files=[item.path for item in proposal.files],
        validation_summary=(
            "All required approved checks passed."
            if validation_passed
            else "Required validation has not passed."
        ),
        failed_or_skipped_checks=(
            [
                *validation.failed_required_checks,
                *validation.failed_optional_checks,
                *validation.skipped_checks,
            ]
            if validation
            else ["validation_not_run"]
        ),
        risk_summary=(
            f"Risk is {proposal.risk_level}; protected paths, secret findings, "
            "binary changes, and out-of-scope files block execution."
        ),
        rollback_summary=(
            f"Rollback status: {rollback.rollback_status}."
            if rollback
            else "No rollback was required during proposal review."
        ),
        PR_title=proposal.title,
        PR_body=(
            f"Repairs `{proposal.code_repair_case_id}` from base "
            f"`{proposal.base_commit_sha[:12]}` using reviewed diff "
            f"`{proposal.diff_sha256[:12]}`.\n\n"
            f"Changed files: {', '.join(item.path for item in proposal.files)}.\n\n"
            "All required checks must remain visible. Code Surgeon did not push, "
            "open this PR, merge, deploy, or claim production correctness."
        ),
        reviewer_checklist=[
            "Confirm the patch addresses the selected repair case.",
            "Confirm every changed path and hunk is necessary.",
            "Confirm no safety, rights, checkpoint, or validation gate was weakened.",
            "Confirm all required checks passed and no required check was skipped.",
            "Review runtime behavior before any manual merge.",
        ],
        prohibited_next_actions=[
            "Do not push or merge without human review.",
            "Do not bypass failed or unavailable checks.",
            "Do not deploy or release from this package automatically.",
        ],
        ready_for_manual_push=bool(commit_sha) and validation_passed,
        ready_for_manual_PR=bool(commit_sha) and validation_passed,
        ready_for_merge=False,
        warnings=[
            "Code Surgeon did not push or create a remote PR.",
            "Validation success does not guarantee production correctness.",
        ],
        limitations=[
            "Human review and normal repository protections remain mandatory."
        ],
    )


class BobaCodeSurgeonV1:
    def __init__(
        self,
        repository_root: str | Path,
        *,
        policy: BobaCodeExecutionPolicyV1 | None = None,
    ) -> None:
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.policy = policy or default_code_execution_policy()
        self.last_proposed_diff: str | None = None

    def propose(
        self,
        project_id: str,
        repair_planner: BobaRepairPlannerSetV1 | Mapping[str, Any] | None,
        *,
        source_id: str | None = None,
        repair_case_id: str | None = None,
        repair_strategy_id: str | None = None,
        unified_diff: str | None = None,
        proposal_source: BobaCodeProposalSourceV1 = "user_provided_diff",
        deterministic_template_identifier: str | None = None,
        template_parameters: Mapping[str, Any] | None = None,
        base_branch: str = "main",
        affected_paths: Sequence[str] = (),
        approved_special_paths: Sequence[str] = (),
    ) -> BobaCodeSurgeonSetV1:
        self.last_proposed_diff = None
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError("Invalid BOBA project id.")
        planner = _planner_model(repair_planner)
        repair_case = verify_code_repair_eligibility(
            planner,
            repair_case_id=repair_case_id,
            repair_strategy_id=repair_strategy_id,
            affected_paths=affected_paths,
        )
        if deterministic_template_identifier:
            if deterministic_template_identifier != "exact_text_replacement_v1":
                raise ValidationError("Unsupported deterministic repair template.")
            unified_diff = _render_exact_text_template(
                self.repository_root,
                template_parameters or {},
            )
            proposal_source = "deterministic_template"
        if not unified_diff:
            return _base_report(
                project_id,
                source_id or (planner.source_id if planner else project_id),
                repair_case,
                self.policy,
                planner_available=planner is not None,
                proposal_source="unknown",
            )
        self.last_proposed_diff = unified_diff
        if len(unified_diff.encode("utf-8")) > self.policy.maximum_diff_size_bytes:
            parsed_size = len(unified_diff.encode("utf-8"))
            raise ValidationError(
                "Patch exceeds the configured diff-size limit.",
                details={
                    "patch_size_bytes": parsed_size,
                    "maximum_diff_size_bytes": self.policy.maximum_diff_size_bytes,
                },
            )
        parsed = _parse_unified_diff(unified_diff)
        changed_lines = parsed.additions + parsed.deletions
        if len(parsed.files) > self.policy.maximum_changed_files:
            raise ValidationError("Patch exceeds the changed-file limit.")
        if changed_lines > self.policy.maximum_changed_lines:
            raise ValidationError("Patch exceeds the changed-line limit.")
        if is_protected_branch(
            sanitize_repair_branch_name(
                project_id,
                repair_case.source_repair_case_id or repair_case.code_repair_case_id,
                repair_case.title,
            ),
            self.policy,
        ):
            raise ValidationError("Generated repair branch is protected.")
        files, path_passed, path_warnings = validate_patch_paths(
            parsed,
            repository_root=self.repository_root,
            policy=self.policy,
            approved_special_paths=approved_special_paths,
        )
        patch_paths = [item.path for item in files]
        if not repair_case.affected_paths:
            repair_case.affected_paths = patch_paths
            repair_case.warnings = _unique(
                [
                    *repair_case.warnings,
                    "Target path scope was inferred from the proposal and still "
                    "requires exact approval.",
                ],
                limit=64,
            )
        scope_passed, scope_warnings = validate_patch_scope(
            patch_paths,
            repair_case.affected_paths,
        )
        secret_passed, secret_findings = scan_patch_for_secrets(unified_diff)
        quality_passed, quality_findings = review_patch_quality(unified_diff)
        base_sha = _repository_sha(self.repository_root, base_branch)
        applies_cleanly, apply_warning = _patch_applies(
            self.repository_root,
            unified_diff,
            policy=self.policy,
        )
        diff_sha = calculate_patch_digest(unified_diff)
        proposed_branch = sanitize_repair_branch_name(
            project_id,
            repair_case.source_repair_case_id or repair_case.code_repair_case_id,
            repair_case.title,
        )
        all_passed = (
            repair_case.execution_eligible
            and path_passed
            and scope_passed
            and secret_passed
            and quality_passed
            and applies_cleanly
        )
        warnings = _unique(
            [
                *path_warnings,
                *scope_warnings,
                *[f"Secret scan blocked {item}." for item in secret_findings],
                *[f"Patch quality finding: {item}." for item in quality_findings],
                *([] if applies_cleanly or not apply_warning else [apply_warning]),
            ],
            limit=64,
        )
        proposal_id = _stable_id(
            "code_patch",
            project_id,
            repair_case.code_repair_case_id,
            base_sha,
            diff_sha,
        )
        proposal = BobaCodePatchProposalV1(
            patch_proposal_id=proposal_id,
            code_repair_case_id=repair_case.code_repair_case_id,
            proposal_source=proposal_source,
            base_branch=base_branch,
            base_commit_sha=base_sha,
            proposed_branch=proposed_branch,
            title=f"Repair {repair_case.title}"[:240],
            summary=(
                f"Bounded proposal changes {len(files)} approved text file(s) "
                f"with {changed_lines} changed line(s)."
            ),
            rationale=repair_case.justification,
            files=files,
            hunks=[hunk for item in parsed.files for hunk in item.hunks],
            unified_diff_reference=(
                f"code_surgeon/runs/{proposal_id}/patch.diff"
            ),
            diff_sha256=diff_sha,
            changed_file_count=len(files),
            additions=parsed.additions,
            deletions=parsed.deletions,
            total_changed_lines=changed_lines,
            patch_size_bytes=parsed.size_bytes,
            applies_cleanly=applies_cleanly,
            path_policy_passed=path_passed,
            secret_scan_passed=secret_passed,
            scope_check_passed=scope_passed and quality_passed,
            binary_change_detected=any(item.binary for item in files),
            dependency_change_detected=any(
                item.path in _DEPENDENCY_PATHS for item in files
            ),
            workflow_change_detected=any(
                _path_matches(item.path, ".github/workflows") for item in files
            ),
            risk_level=(
                "low"
                if all_passed and len(files) <= 3 and changed_lines <= 120
                else "medium"
                if all_passed
                else "blocked"
            ),
            approval_status="awaiting_review" if all_passed else "not_requested",
            execution_status="validation_ready" if all_passed else "blocked",
            warnings=warnings,
            limitations=[
                "The full unified diff is stored separately under ignored work storage.",
                "A clean apply check and passing tests do not prove production correctness.",
            ],
        )
        repair_case.protected_paths_detected = [
            item.path for item in files if item.protected
        ]
        report = _base_report(
            project_id,
            source_id or (planner.source_id if planner else project_id),
            repair_case,
            self.policy,
            planner_available=planner is not None,
            proposal=proposal,
            proposal_source=proposal_source,
        )
        report.review_packages = [_build_review_package(proposal, None, None, None)]
        report.surgeon_summary = _summary(report)
        return report

    def execute_approved(
        self,
        report: BobaCodeSurgeonSetV1,
        *,
        patch_proposal_id: str,
        unified_diff: str,
        approval: BobaCodeApprovalRecordV1,
        approved_validation_commands: Sequence[str],
    ) -> BobaCodeSurgeonSetV1:
        proposal = next(
            (
                item
                for item in report.patch_proposals
                if item.patch_proposal_id == patch_proposal_id
            ),
            None,
        )
        if proposal is None:
            raise ValidationError("Code Surgeon patch proposal was not found.")
        run_id = f"code_run_{uuid4().hex}"
        worktree_reference = f"work/boba/code_surgeon/worktrees/{run_id}"
        worktree = (
            self.repository_root
            / "work"
            / "boba"
            / "code_surgeon"
            / "worktrees"
            / run_id
        ).resolve()
        run = BobaCodeIsolatedRunV1(
            isolated_run_id=run_id,
            patch_proposal_id=proposal.patch_proposal_id,
            mode="approved_isolated_patch",
            base_branch=proposal.base_branch,
            base_commit_sha=proposal.base_commit_sha,
            repair_branch=proposal.proposed_branch,
            sanitized_worktree_reference=worktree_reference,
            run_status="not_started",
            execution_started_at=now_iso(),
        )
        report.approval_records.append(approval)
        approval_errors = verify_approval(
            proposal,
            approval,
            required_type="isolated_patch_execution",
        )
        if proposal.execution_status not in {"validation_ready", "validation_passed"}:
            approval_errors.append(
                "Patch proposal is not eligible for isolated execution."
            )
        if calculate_patch_digest(unified_diff) != proposal.diff_sha256:
            approval_errors.append("Stored patch content does not match the approved diff SHA.")
        current_base = _repository_sha(self.repository_root, proposal.base_commit_sha)
        if current_base != proposal.base_commit_sha:
            approval_errors.append("Approved base commit is no longer available.")
        clean, original_status = _repository_clean(self.repository_root)
        if not clean:
            approval_errors.append("Original repository worktree is not clean.")
        if is_protected_branch(proposal.proposed_branch, self.policy):
            approval_errors.append("Repair branch is protected.")
        if set(approved_validation_commands) != set(
            approval.approved_validation_commands
        ):
            approval_errors.append("Validation command approval does not exactly match.")
        if approval_errors:
            run.run_status = "blocked"
            run.stop_reason = " ".join(approval_errors)
            run.approval_verified = False
            run.current_worktree_clean_before_run = clean
            run.execution_completed_at = now_iso()
            report.isolated_runs.append(run)
            report.signal_usage.approval_record_used = True
            report.warnings = _unique(
                [*report.warnings, *approval_errors],
                limit=64,
            )
            report.surgeon_summary = _summary(report)
            return report
        worktree.parent.mkdir(parents=True, exist_ok=True)
        create = _git_result(
            self.repository_root,
            [
                "worktree",
                "add",
                "-b",
                proposal.proposed_branch,
                str(worktree),
                proposal.base_commit_sha,
            ],
            timeout=min(self.policy.command_timeout_seconds, 120),
            output_limit=self.policy.output_capture_limit_bytes,
        )
        if create.exit_code != 0:
            run.run_status = "failed"
            run.stop_reason = _safe_text(create.stderr or create.stdout, maximum=900)
            run.execution_completed_at = now_iso()
            report.isolated_runs.append(run)
            report.signal_usage.approval_record_used = True
            report.surgeon_summary = _summary(report)
            return report
        run.worktree_created = True
        run.current_worktree_clean_before_run = clean
        run.approval_verified = True
        run.run_status = "worktree_ready"
        report.signal_usage.approval_record_used = True
        report.signal_usage.isolated_worktree_used = True
        report.signal_usage.local_branch_created = True
        patch_path = worktree.parent / f"{run_id}.diff"
        patch_path.write_text(unified_diff, encoding="utf-8", newline="\n")
        apply_check = _git_result(
            worktree,
            ["apply", "--check", "--", str(patch_path)],
            timeout=min(self.policy.command_timeout_seconds, 60),
            output_limit=self.policy.output_capture_limit_bytes,
        )
        run.patch_apply_check_passed = apply_check.exit_code == 0
        apply_result = (
            _git_result(
                worktree,
                ["apply", "--", str(patch_path)],
                timeout=min(self.policy.command_timeout_seconds, 60),
                output_limit=self.policy.output_capture_limit_bytes,
            )
            if run.patch_apply_check_passed
            else apply_check
        )
        run.patch_applied = run.patch_apply_check_passed and apply_result.exit_code == 0
        if not run.patch_applied:
            run.run_status = "failed"
            run.stop_reason = _safe_text(
                apply_result.stderr or apply_result.stdout or "Patch application failed.",
                maximum=900,
            )
            rollback = self._rollback(
                run,
                patch_path,
                trigger=run.stop_reason,
                original_status=original_status,
            )
            run.run_status = (
                "rolled_back" if rollback.rollback_status == "completed" else "failed"
            )
            run.execution_completed_at = now_iso()
            report.isolated_runs.append(run)
            report.rollback_records.append(rollback)
            proposal.execution_status = "rolled_back"
            _replace_proposal(report, proposal)
            patch_path.unlink(missing_ok=True)
            report.surgeon_summary = _summary(report)
            return report
        run.run_status = "patch_applied"
        report.signal_usage.code_modified_in_isolated_worktree = True
        changed = _git_result(
            worktree,
            ["diff", "--name-only"],
            output_limit=self.policy.output_capture_limit_bytes,
        )
        changed_paths = [
            _normalize_patch_path(item)
            for item in changed.stdout.splitlines()
            if item.strip()
        ]
        expected_paths = [item.path for item in proposal.files]
        run.changed_files_verified = set(changed_paths) == set(expected_paths)
        diff_check = _git_result(
            worktree,
            ["diff", "--check"],
            output_limit=self.policy.output_capture_limit_bytes,
        )
        security_passed, _ = scan_patch_for_secrets(unified_diff)
        if (
            changed.exit_code != 0
            or not run.changed_files_verified
            or diff_check.exit_code != 0
            or not security_passed
        ):
            run.stop_reason = (
                "Post-apply changed-file, diff, or secret validation failed."
            )
            rollback = self._rollback(
                run,
                patch_path,
                trigger=run.stop_reason,
                original_status=original_status,
            )
            run.run_status = (
                "rolled_back" if rollback.rollback_status == "completed" else "failed"
            )
            run.execution_completed_at = now_iso()
            report.isolated_runs.append(run)
            report.rollback_records.append(rollback)
            proposal.execution_status = "rolled_back"
            _replace_proposal(report, proposal)
            patch_path.unlink(missing_ok=True)
            report.surgeon_summary = _summary(report)
            return report
        commands = build_validation_commands(
            self.repository_root,
            changed_paths,
            approved_validation_commands,
            policy=self.policy,
        )
        run.run_status = "validation_running"
        validation = execute_allowlisted_validation(worktree, run_id, commands)
        report.signal_usage.validation_commands_executed = bool(validation.results)
        report.validation_runs.append(validation)
        if not validation.required_checks_passed:
            run.run_status = "validation_failed"
            run.stop_reason = validation.rejection_reason
            rollback = self._rollback(
                run,
                patch_path,
                trigger=validation.rejection_reason or "Required validation failed.",
                original_status=original_status,
            )
            run.run_status = (
                "rolled_back" if rollback.rollback_status == "completed" else "failed"
            )
            report.rollback_records.append(rollback)
            proposal.execution_status = (
                "rolled_back"
                if rollback.rollback_status == "completed"
                else "validation_failed"
            )
        else:
            run.run_status = "validation_passed"
            proposal.execution_status = "validation_passed"
            proposal.approval_status = "approved_for_isolated_execution"
        run.execution_completed_at = now_iso()
        report.isolated_runs.append(run)
        _replace_proposal(report, proposal)
        rollback_record = (
            report.rollback_records[-1]
            if report.rollback_records
            and report.rollback_records[-1].isolated_run_id == run_id
            else None
        )
        report.review_packages = [
            item
            for item in report.review_packages
            if item.patch_proposal_id != proposal.patch_proposal_id
        ]
        report.review_packages.append(
            _build_review_package(proposal, run, validation, rollback_record)
        )
        patch_path.unlink(missing_ok=True)
        report.surgeon_summary = _summary(report)
        return report

    def _rollback(
        self,
        run: BobaCodeIsolatedRunV1,
        patch_path: Path,
        *,
        trigger: str,
        original_status: str,
    ) -> BobaCodeRollbackRecordV1:
        worktree = (
            self.repository_root
            / "work"
            / "boba"
            / "code_surgeon"
            / "worktrees"
            / run.isolated_run_id
        ).resolve()
        rollback = BobaCodeRollbackRecordV1(
            rollback_record_id=_stable_id("rollback", run.isolated_run_id),
            isolated_run_id=run.isolated_run_id,
            rollback_trigger=_safe_text(trigger, maximum=700),
            rollback_started_at=now_iso(),
            rollback_status="partial",
        )
        if worktree.is_dir() and run.patch_applied:
            reverse = _git_result(
                worktree,
                ["apply", "-R", "--check", "--", str(patch_path)],
                timeout=min(self.policy.command_timeout_seconds, 60),
                output_limit=self.policy.output_capture_limit_bytes,
            )
            if reverse.exit_code == 0:
                reversed_patch = _git_result(
                    worktree,
                    ["apply", "-R", "--", str(patch_path)],
                    timeout=min(self.policy.command_timeout_seconds, 60),
                    output_limit=self.policy.output_capture_limit_bytes,
                )
                rollback.patch_removed = reversed_patch.exit_code == 0
        elif not run.patch_applied:
            rollback.patch_removed = True
        worktree_clean, _ = (
            _repository_clean(worktree) if worktree.is_dir() else (True, "")
        )
        if worktree.is_dir() and worktree_clean:
            removed = _git_result(
                self.repository_root,
                ["worktree", "remove", "--", str(worktree)],
                timeout=min(self.policy.command_timeout_seconds, 60),
                output_limit=self.policy.output_capture_limit_bytes,
            )
            rollback.temporary_worktree_removed = removed.exit_code == 0
        source_clean, source_status = _repository_clean(self.repository_root)
        rollback.source_worktree_unchanged = source_clean and source_status == original_status
        rollback.rollback_validation_passed = (
            rollback.patch_removed
            and rollback.temporary_worktree_removed
            and rollback.source_worktree_unchanged
        )
        rollback.rollback_status = (
            "completed" if rollback.rollback_validation_passed else "partial"
        )
        rollback.rollback_completed_at = now_iso()
        if not rollback.rollback_validation_passed:
            rollback.warnings = [
                "Rollback was incomplete; preserve the isolated branch and require human review."
            ]
        return rollback

    def prepare_local_commit(
        self,
        report: BobaCodeSurgeonSetV1,
        *,
        isolated_run_id: str,
        approval: BobaCodeApprovalRecordV1,
    ) -> BobaCodeSurgeonSetV1:
        run = next(
            (item for item in report.isolated_runs if item.isolated_run_id == isolated_run_id),
            None,
        )
        if run is None:
            raise ValidationError("Isolated Code Surgeon run was not found.")
        proposal = next(
            (
                item
                for item in report.patch_proposals
                if item.patch_proposal_id == run.patch_proposal_id
            ),
            None,
        )
        if proposal is None:
            raise ValidationError("Code Surgeon patch proposal was not found.")
        errors = verify_approval(
            proposal,
            approval,
            required_type="local_commit_creation",
        )
        validation = next(
            (
                item
                for item in report.validation_runs
                if item.isolated_run_id == isolated_run_id
            ),
            None,
        )
        if run.run_status != "validation_passed":
            errors.append("The isolated run has not passed required validation.")
        if validation is None or not validation.acceptance_criteria_met:
            errors.append("Required validation acceptance is missing.")
        worktree = (
            self.repository_root
            / "work"
            / "boba"
            / "code_surgeon"
            / "worktrees"
            / isolated_run_id
        ).resolve()
        if not worktree.is_dir():
            errors.append("The isolated worktree is unavailable.")
        if errors:
            raise ValidationError(
                "Local review commit approval failed.",
                details={"reasons": errors},
            )
        branch = _git_result(worktree, ["branch", "--show-current"])
        if branch.exit_code != 0 or branch.stdout.strip() != proposal.proposed_branch:
            raise ValidationError("Local commit target is not the approved repair branch.")
        changed = _git_result(worktree, ["diff", "--name-only"])
        changed_paths = [
            _normalize_patch_path(item)
            for item in changed.stdout.splitlines()
            if item.strip()
        ]
        if set(changed_paths) != {item.path for item in proposal.files}:
            raise ValidationError("Changed paths no longer match the approved patch.")
        add = _git_result(worktree, ["add", "--", *changed_paths])
        if add.exit_code != 0:
            raise ValidationError("Approved files could not be staged.")
        staged_check = _git_result(worktree, ["diff", "--cached", "--check"])
        if staged_check.exit_code != 0:
            raise ValidationError("Staged diff validation failed.")
        message = f"fix(boba): repair {_text(report.repair_cases[0].title, maximum=70)}"
        with tempfile.TemporaryDirectory(prefix="boba-empty-hooks-") as hooks:
            commit = _git_result(
                worktree,
                [
                    "-c",
                    f"core.hooksPath={hooks}",
                    "-c",
                    "commit.gpgSign=false",
                    "commit",
                    "-m",
                    message,
                ],
                timeout=min(self.policy.command_timeout_seconds, 120),
                output_limit=self.policy.output_capture_limit_bytes,
            )
        if commit.exit_code != 0:
            raise ValidationError(
                "Local review commit failed.",
                details={"reason": _safe_text(commit.stderr or commit.stdout, maximum=700)},
            )
        commit_sha = _repository_sha(worktree, "HEAD")
        run.run_status = "local_commit_prepared"
        run.execution_completed_at = now_iso()
        proposal.execution_status = "local_commit_prepared"
        report.approval_records.append(approval)
        _replace_proposal(report, proposal)
        report.review_packages = [
            item
            for item in report.review_packages
            if item.patch_proposal_id != proposal.patch_proposal_id
        ]
        report.review_packages.append(
            _build_review_package(proposal, run, validation, None, commit_sha=commit_sha)
        )
        report.signal_usage.approval_record_used = True
        report.signal_usage.local_commit_created = True
        report.surgeon_summary = _summary(report)
        return report


def generate_boba_code_surgeon_proposal(
    repository_root: str | Path,
    project_id: str,
    repair_planner: BobaRepairPlannerSetV1 | Mapping[str, Any] | None,
    **kwargs: Any,
) -> BobaCodeSurgeonSetV1:
    return BobaCodeSurgeonV1(repository_root).propose(
        project_id,
        repair_planner,
        **kwargs,
    )


def validate_boba_code_surgeon_patch(
    repository_root: str | Path,
    project_id: str,
    repair_planner: BobaRepairPlannerSetV1 | Mapping[str, Any] | None,
    **kwargs: Any,
) -> BobaCodeSurgeonSetV1:
    kwargs.setdefault("proposal_source", "imported_review_patch")
    return BobaCodeSurgeonV1(repository_root).propose(
        project_id,
        repair_planner,
        **kwargs,
    )


def execute_approved_boba_code_surgeon_patch(
    repository_root: str | Path,
    report: BobaCodeSurgeonSetV1,
    **kwargs: Any,
) -> BobaCodeSurgeonSetV1:
    return BobaCodeSurgeonV1(repository_root).execute_approved(report, **kwargs)


def prepare_boba_code_surgeon_local_commit(
    repository_root: str | Path,
    report: BobaCodeSurgeonSetV1,
    **kwargs: Any,
) -> BobaCodeSurgeonSetV1:
    return BobaCodeSurgeonV1(repository_root).prepare_local_commit(report, **kwargs)


__all__ = [
    "BobaCodeApprovalRecordV1",
    "BobaCodeExecutionPolicyV1",
    "BobaCodeIsolatedRunV1",
    "BobaCodePatchFileV1",
    "BobaCodePatchHunkV1",
    "BobaCodePatchProposalV1",
    "BobaCodeRepairCaseV1",
    "BobaCodeReviewPackageV1",
    "BobaCodeRollbackRecordV1",
    "BobaCodeSurgeonExecutionHandoffV1",
    "BobaCodeSurgeonSetV1",
    "BobaCodeSurgeonSignalUsageV1",
    "BobaCodeSurgeonSummaryV1",
    "BobaCodeSurgeonV1",
    "BobaCodeValidationCommandV1",
    "BobaCodeValidationResultV1",
    "BobaCodeValidationRunV1",
    "build_validation_commands",
    "calculate_patch_digest",
    "default_code_execution_policy",
    "execute_allowlisted_validation",
    "execute_approved_boba_code_surgeon_patch",
    "generate_boba_code_surgeon_proposal",
    "is_protected_branch",
    "prepare_boba_code_surgeon_local_commit",
    "review_patch_quality",
    "sanitize_repair_branch_name",
    "scan_patch_for_secrets",
    "validate_boba_code_surgeon_patch",
    "validate_command_safety",
    "validate_patch_paths",
    "validate_patch_scope",
    "verify_approval",
    "verify_code_repair_eligibility",
]
