"""Evaluation-only policy boundary for exact BOBA internal actions.

Safety Gate V1 validates bounded requests and persisted evidence. It never
executes a target action, command, Git, FFmpeg, network request, workflow
resume, checkpoint restore, upload, publication, merge, or deployment.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar, cast

from pydantic import Field

from olympus.boba.autopilot_controller import (
    BobaAutopilotActionClassV1,
    BobaAutopilotActionV1,
)
from olympus.boba.code_surgeon import (
    BobaCodeApprovalRecordV1,
    BobaCodeApprovalTypeV1,
)
from olympus.boba.code_surgeon import (
    verify_approval as verify_code_approval,
)
from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.tool_recovery import (
    BobaToolRecoveryApprovalV1,
    verify_recovery_approval,
)
from olympus.platform.errors import ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore

_StoredSafetyRecordT = TypeVar("_StoredSafetyRecordT")

BobaSafetyEvaluationStatusV1 = Literal[
    "received",
    "validating_request",
    "evaluating",
    "awaiting_evidence",
    "awaiting_human_review",
    "decision_ready",
    "completed",
    "blocked",
    "invalidated",
    "unknown",
]
BobaSafetyEvidenceCategoryV1 = Literal[
    "project_snapshot",
    "rights_permission",
    "target_approval",
    "repair_plan",
    "root_cause",
    "checkpoint",
    "rollback",
    "validation",
    "output_quality",
    "recovery_budget",
    "module_health",
    "artifact_integrity",
    "source_media_protection",
    "accepted_output_protection",
    "code_branch_protection",
    "command_policy",
    "external_access",
    "human_decision",
    "conflicting_state",
    "unknown",
]
BobaSafetyEvidenceReliabilityV1 = Literal[
    "high",
    "medium",
    "low",
    "conflicting",
    "unavailable",
    "unknown",
]
BobaSafetyConstraintTypeV1 = Literal[
    "project_scope",
    "registered_module",
    "registered_operation",
    "action_class",
    "policy_match",
    "project_snapshot",
    "request_digest",
    "rights",
    "permission",
    "human_approval",
    "approval_scope",
    "approval_expiry",
    "plan_match",
    "strategy_match",
    "patch_match",
    "base_sha_match",
    "tool_match",
    "capability_match",
    "configuration_match",
    "checkpoint",
    "rollback",
    "validation",
    "quality",
    "budget",
    "source_media_protection",
    "accepted_output_protection",
    "branch_protection",
    "path_protection",
    "external_access",
    "paid_service",
    "network",
    "package_installation",
    "service_restart",
    "retry_limit",
    "destructive_action",
    "publication",
    "upload",
    "deployment",
    "workflow_resume",
    "unknown",
]
BobaSafetyConstraintStatusV1 = Literal[
    "passed",
    "failed",
    "blocked",
    "unavailable",
    "stale",
    "conflicting",
    "not_required",
    "unknown",
]
BobaSafetyCheckpointStatusV1 = Literal[
    "not_required",
    "valid",
    "missing",
    "stale",
    "corrupt",
    "unverified",
    "mismatched",
    "unknown",
]
BobaSafetyRiskCategoryV1 = Literal[
    "source_data",
    "accepted_output",
    "artifact_integrity",
    "code_change",
    "configuration",
    "environment",
    "external_dependency",
    "network",
    "paid_service",
    "rights",
    "safety_policy",
    "validation",
    "quality",
    "checkpoint",
    "rollback",
    "retry_loop",
    "resource_exhaustion",
    "stale_state",
    "approval_mismatch",
    "project_concurrency",
    "secret_exposure",
    "destructive_action",
    "publication",
    "deployment",
    "unknown",
]
BobaSafetyRiskSeverityV1 = Literal[
    "negligible",
    "low",
    "medium",
    "high",
    "critical",
    "blocked",
    "unknown",
]
BobaSafetyLikelihoodV1 = Literal[
    "rare",
    "unlikely",
    "possible",
    "likely",
    "very_likely",
    "unknown",
]
BobaSafetyOverallRiskV1 = Literal[
    "minimal",
    "low",
    "medium",
    "high",
    "critical",
    "blocked",
    "unknown",
]
BobaSafetyDecisionValueV1 = Literal[
    "allowed_for_internal_read_only",
    "allowed_for_exact_internal_execution",
    "denied",
    "human_review_required",
    "more_evidence_required",
    "blocked_rights",
    "blocked_safety_policy",
    "blocked_stale_state",
    "blocked_budget",
    "blocked_checkpoint",
    "blocked_validation",
    "blocked_quality",
    "unsupported_future_action",
    "invalid_request",
    "expired",
    "unknown",
]
BobaSafetyHandoffTargetV1 = Literal[
    "autopilot_controller",
    "code_surgeon",
    "tool_recovery_brain",
    "output_quality_reviewer",
    "repair_planner",
    "root_cause_analyzer",
    "checkpoint_recovery_manager",
    "validator_runner",
    "report_reader",
    "workflow_controller",
    "final_decision_bus",
    "rights_permission_gate",
    "review_ui",
    "candidate_review",
    "clip_brief_review",
    "error_doctor_review",
    "repair_plan_review",
    "approval_controls",
    "live_companion",
    "human_operator",
    "unknown",
]

SafetyContextProvider: TypeAlias = Callable[
    [str, "BobaSafetyActionRequestV1"],
    Mapping[str, Any],
]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_WINDOWS_PATH = re.compile(r"(?i)(?:^|[\s\"'])?[A-Z]:[\\/][^\s\"']+")
_PRIVATE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users|root)/[^\s\"']+")
_EXTERNAL_URL = re.compile(r"(?i)\b(?:https?|ftp)://")
_PROJECT_REFERENCE = re.compile(r"\bproj_[A-Za-z0-9_-]{4,128}\b")
_SECRET_KEY = re.compile(
    r"(?i)(?:secret|token|password|credential|cookie|authorization|api[_-]?key)"
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|"
    r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"
    r")"
)
_RAW_PATCH_KEYS = frozenset(
    {
        "raw_patch",
        "patch_content",
        "unified_diff",
        "diff_content",
        "complete_patch",
        "source_media",
        "raw_media",
        "command_log",
        "full_command_log",
        "full_command_logs",
        "full_log",
        "full_logs",
        "stdout",
        "stderr",
    }
)
_COMMAND_KEYS = frozenset(
    {
        "command",
        "shell_command",
        "git_command",
        "ffmpeg_command",
        "arbitrary_command",
        "executable_arguments",
    }
)
_RIGHTS_CLEAR = frozenset(
    {
        "owned",
        "licensed",
        "permission_granted",
        "approved",
        "cleared",
        "confirmed",
        "ready_for_processing",
        "clear_for_local_analysis",
    }
)
_RIGHTS_BLOCKED = frozenset(
    {
        "blocked",
        "permission_denied",
        "not_allowed",
        "do_not_process",
        "needs_permission",
        "permission_needed",
        "needs_rights_review",
        "insufficient_information",
    }
)
_SAFETY_CLEAR = frozenset(
    {
        "safe",
        "approved",
        "cleared",
        "passed",
        "eligible",
        "ready_for_processing",
        "clear_for_local_analysis",
    }
)
_SAFETY_BLOCKED = frozenset(
    {"blocked", "unsafe", "rejected", "do_not_process", "denied"}
)

_ABSOLUTE_PROHIBITIONS = (
    "rights_bypass",
    "safety_bypass",
    "drm_bypass",
    "source_media_delete_or_overwrite",
    "accepted_output_overwrite",
    "direct_main_modification",
    "force_push",
    "automatic_merge",
    "automatic_deployment",
    "automatic_publication",
    "automatic_upload",
    "secret_exposure",
    "arbitrary_command_execution",
    "destructive_git",
    "unlimited_retries",
    "hidden_quality_reduction",
    "required_validation_removal",
    "unapproved_external_provider",
    "unapproved_paid_provider",
    "out_of_scope_modification",
)
_FUTURE_GATED_ACTIONS = (
    "workflow_resume",
    "checkpoint_restore",
    "remote_pr_creation",
    "push",
    "merge",
    "deployment",
    "publication",
    "upload",
    "package_installation",
    "service_restart",
    "production_configuration_change",
    "database_migration",
    "destructive_cleanup",
)
_PROHIBITED_TOKENS = {
    "rights_bypass": ("rights_bypass", "bypass_rights"),
    "safety_bypass": ("safety_bypass", "bypass_safety"),
    "drm_bypass": ("drm_bypass", "access_control_bypass"),
    "source_media_delete_or_overwrite": (
        "delete_source",
        "source_media_delete",
        "overwrite_source_media",
        "modify_source_media",
    ),
    "accepted_output_overwrite": (
        "accepted_output_overwrite",
        "overwrite_accepted_output",
        "modify_accepted_output",
    ),
    "direct_main_modification": ("direct_main", "modify_main", "patch_main"),
    "force_push": ("force_push", "push_force"),
    "automatic_merge": ("automatic_merge", "auto_merge"),
    "automatic_deployment": ("automatic_deploy", "deployment"),
    "automatic_publication": ("automatic_publish", "publication"),
    "automatic_upload": ("automatic_upload", "upload"),
    "secret_exposure": ("expose_secret", "secret_exposure"),
    "arbitrary_command_execution": ("arbitrary_command", "shell_command"),
    "destructive_git": ("git_reset_hard", "git_clean", "destructive_git"),
    "unlimited_retries": ("unlimited_retry", "unbounded_retry"),
    "hidden_quality_reduction": (
        "hidden_quality_reduction",
        "silent_resolution_reduction",
        "silent_fps_reduction",
        "remove_audio",
        "remove_captions",
    ),
    "required_validation_removal": ("disable_validation", "skip_required_validation"),
    "unapproved_external_provider": ("external_service", "external_provider"),
    "unapproved_paid_provider": ("paid_provider", "paid_service"),
    "out_of_scope_modification": ("outside_project_scope",),
}
_FUTURE_TOKENS = {
    "workflow_resume": ("workflow_resume", "resume_olympus"),
    "checkpoint_restore": ("checkpoint_restore", "restore_checkpoint"),
    "remote_pr_creation": ("create_pull_request", "remote_pr"),
    "push": ("git_push", "push_branch"),
    "merge": ("merge_branch", "merge_pr"),
    "deployment": ("deploy", "deployment"),
    "publication": ("publish", "publication"),
    "upload": ("upload",),
    "package_installation": ("install_package", "package_install"),
    "service_restart": ("restart_service", "service_restart"),
    "production_configuration_change": ("production_config",),
    "database_migration": ("database_migration",),
    "destructive_cleanup": ("destructive_cleanup",),
}


class BobaSafetyPolicySnapshotV1(BobaContract):
    policy_snapshot_id: str = Field(min_length=1, max_length=180)
    policy_version: str = Field(default="boba_safety_policy_v1", max_length=80)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    protected_actions: list[str] = Field(default_factory=list, max_length=128)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=128)
    future_gated_actions: list[str] = Field(default_factory=list, max_length=128)
    allowlisted_modules: list[str] = Field(default_factory=list, max_length=64)
    allowlisted_operations: dict[str, list[str]] = Field(
        default_factory=dict,
        max_length=64,
    )
    protected_paths: list[str] = Field(default_factory=list, max_length=128)
    protected_branches: list[str] = Field(default_factory=list, max_length=64)
    rights_requirements: list[str] = Field(default_factory=list, max_length=64)
    approval_requirements: list[str] = Field(default_factory=list, max_length=64)
    checkpoint_requirements: list[str] = Field(default_factory=list, max_length=64)
    rollback_requirements: list[str] = Field(default_factory=list, max_length=64)
    validation_requirements: list[str] = Field(default_factory=list, max_length=64)
    quality_requirements: list[str] = Field(default_factory=list, max_length=64)
    budget_requirements: list[str] = Field(default_factory=list, max_length=64)
    risk_thresholds: dict[str, float] = Field(default_factory=dict, max_length=16)
    decision_ttl_seconds: dict[str, int] = Field(default_factory=dict, max_length=16)
    policy_sha256: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaSafetyEvaluationCaseV1(BobaContract):
    safety_case_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    autopilot_run_id: str = Field(default="", max_length=180)
    action_request_id: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=240)
    target_module: str = Field(min_length=1, max_length=160)
    target_operation: str = Field(min_length=1, max_length=160)
    action_class: BobaAutopilotActionClassV1
    evaluation_status: BobaSafetyEvaluationStatusV1 = "received"
    project_snapshot_id: str = Field(default="", max_length=180)
    project_snapshot_digest: str = Field(default="", max_length=64)
    policy_snapshot_id: str = Field(min_length=1, max_length=180)
    rights_review_id: str = Field(default="", max_length=180)
    approval_review_id: str = Field(default="", max_length=180)
    checkpoint_review_id: str = Field(default="", max_length=180)
    validation_review_id: str = Field(default="", max_length=180)
    quality_review_id: str = Field(default="", max_length=180)
    risk_assessment_id: str = Field(default="", max_length=180)
    constraint_check_ids: list[str] = Field(default_factory=list, max_length=128)
    safety_decision_id: str = Field(default="", max_length=180)
    human_review_required: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaSafetyActionRequestV1(BobaContract):
    action_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    autopilot_run_id: str = Field(default="", max_length=180)
    autopilot_action_id: str = Field(default="", max_length=180)
    requesting_module: str = Field(min_length=1, max_length=160)
    target_module: str = Field(min_length=1, max_length=160)
    target_operation: str = Field(min_length=1, max_length=160)
    action_class: BobaAutopilotActionClassV1
    action_description: str = Field(min_length=1, max_length=700)
    action_parameters_digest: str = Field(min_length=64, max_length=64)
    project_snapshot_id: str = Field(min_length=1, max_length=180)
    project_snapshot_digest: str = Field(min_length=64, max_length=64)
    plan_id: str = Field(default="", max_length=180)
    strategy_id: str = Field(default="", max_length=180)
    approval_record_id: str = Field(default="", max_length=180)
    patch_proposal_id: str = Field(default="", max_length=180)
    patch_diff_sha256: str = Field(default="", max_length=64)
    code_base_sha: str = Field(default="", max_length=64)
    tool_id: str = Field(default="", max_length=180)
    capability_id: str = Field(default="", max_length=180)
    configuration_digest: str = Field(default="", max_length=64)
    checkpoint_reference: str = Field(default="", max_length=500)
    checkpoint_digest: str = Field(default="", max_length=128)
    rollback_plan_id: str = Field(default="", max_length=180)
    validation_plan_id: str = Field(default="", max_length=180)
    quality_plan_id: str = Field(default="", max_length=180)
    retry_budget_digest: str = Field(default="", max_length=64)
    time_budget_seconds: int = Field(default=0, ge=0, le=3_600)
    requested_at: str = Field(default_factory=now_iso, max_length=80)
    requested_by: str = Field(default="autopilot_controller", max_length=160)
    request_digest: str = Field(min_length=64, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaSafetyEvidenceV1(BobaContract):
    evidence_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    source_module: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(default="", max_length=180)
    category: BobaSafetyEvidenceCategoryV1
    bounded_summary: str = Field(min_length=1, max_length=900)
    observed_value: Any = None
    expected_value: Any = None
    reliability: BobaSafetyEvidenceReliabilityV1 = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    supports_allowance: bool = False
    supports_denial: bool = False
    requires_human_interpretation: bool = False
    stale: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyConstraintCheckV1(BobaContract):
    constraint_check_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    constraint_type: BobaSafetyConstraintTypeV1
    name: str = Field(min_length=1, max_length=240)
    required: bool = True
    status: BobaSafetyConstraintStatusV1 = "unknown"
    observed_value: Any = None
    expected_value: Any = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    blocks_allowance: bool = True
    failure_reason: str = Field(default="", max_length=900)
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyApprovalReviewV1(BobaContract):
    approval_review_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    approval_record_id: str = Field(default="", max_length=180)
    target_module: str = Field(min_length=1, max_length=160)
    approval_type: str = Field(default="", max_length=160)
    approval_found: bool = False
    explicit_confirmation: bool = False
    approved: bool = False
    approved_at: str | None = Field(default=None, max_length=80)
    expires_at: str | None = Field(default=None, max_length=80)
    expired: bool = False
    approved_by_reference: str = Field(default="", max_length=128)
    approved_scope: list[str] = Field(default_factory=list, max_length=64)
    expected_scope: list[str] = Field(default_factory=list, max_length=64)
    scope_match: bool = False
    approved_parameters_digest: str = Field(default="", max_length=64)
    current_parameters_digest: str = Field(default="", max_length=64)
    parameters_match: bool = False
    approved_project_snapshot_digest: str = Field(default="", max_length=64)
    current_project_snapshot_digest: str = Field(default="", max_length=64)
    snapshot_match: bool = False
    exact_binding_valid: bool = False
    independent_target_revalidation_required: Literal[True] = True
    failure_reasons: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyRightsReviewV1(BobaContract):
    rights_review_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    rights_gate_record_id: str = Field(default="", max_length=180)
    rights_status: str = Field(default="unknown", max_length=80)
    permission_status: str = Field(default="unknown", max_length=80)
    source_provenance_status: str = Field(default="unknown", max_length=80)
    processing_scope_allowed: list[str] = Field(default_factory=list, max_length=32)
    external_processing_allowed: bool = False
    upload_allowed: Literal[False] = False
    publication_allowed: Literal[False] = False
    unknown_rights_present: bool = True
    blocked_rights_present: bool = False
    human_rights_review_required: bool = True
    rights_clear_for_requested_internal_action: bool = False
    failure_reasons: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyCheckpointReviewV1(BobaContract):
    checkpoint_review_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    checkpoint_required: bool = False
    checkpoint_reference: str = Field(default="", max_length=500)
    checkpoint_digest: str = Field(default="", max_length=128)
    checkpoint_status: BobaSafetyCheckpointStatusV1 = "not_required"
    checkpoint_validated: bool = False
    checkpoint_fresh: bool = False
    state_preservation_ready: bool = False
    rollback_plan_present: bool = False
    rollback_ready: bool = False
    source_media_protected: bool = True
    accepted_outputs_protected: bool = True
    checkpoint_manager_required: bool = False
    blocks_action: bool = False
    failure_reasons: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyValidationReadinessV1(BobaContract):
    validation_review_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    validation_plan_id: str = Field(default="", max_length=180)
    required_validators: list[str] = Field(default_factory=list, max_length=64)
    available_validators: list[str] = Field(default_factory=list, max_length=64)
    unavailable_validators: list[str] = Field(default_factory=list, max_length=64)
    pre_action_checks: list[str] = Field(default_factory=list, max_length=64)
    post_action_checks: list[str] = Field(default_factory=list, max_length=64)
    rollback_checks: list[str] = Field(default_factory=list, max_length=64)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=64)
    rejection_criteria: list[str] = Field(default_factory=list, max_length=64)
    required_checks_defined: bool = False
    required_checks_available: bool = False
    skipped_required_checks: list[str] = Field(default_factory=list, max_length=64)
    validation_runner_required: bool = False
    validation_ready: bool = False
    failure_reasons: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyQualityReviewV1(BobaContract):
    quality_review_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    quality_plan_id: str = Field(default="", max_length=180)
    output_quality_decision_id: str = Field(default="", max_length=180)
    non_negotiable_requirements: list[str] = Field(default_factory=list, max_length=64)
    acceptable_disclosed_degradations: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    unacceptable_degradations: list[str] = Field(default_factory=list, max_length=64)
    baseline_required: bool = False
    baseline_available: bool = False
    quality_review_required: bool = False
    human_quality_review_required: bool = False
    non_negotiable_regression_present: bool = False
    silent_quality_reduction_detected: bool = False
    quality_requirements_match_request: bool = False
    quality_clear_for_requested_action: bool = False
    failure_reasons: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyRiskFactorV1(BobaContract):
    risk_factor_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    category: BobaSafetyRiskCategoryV1
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=900)
    severity: BobaSafetyRiskSeverityV1
    likelihood: BobaSafetyLikelihoodV1
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    mitigations: list[str] = Field(default_factory=list, max_length=64)
    residual_risk: str = Field(default="", max_length=700)
    blocking: bool = False
    human_review_required: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyRiskAssessmentV1(BobaContract):
    risk_assessment_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    risk_factors: list[BobaSafetyRiskFactorV1] = Field(
        default_factory=list,
        max_length=128,
    )
    overall_risk_level: BobaSafetyOverallRiskV1 = "unknown"
    overall_risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    risk_threshold: float = Field(default=0.0, ge=0.0, le=100.0)
    risk_within_threshold: bool = False
    critical_risk_present: bool = False
    blocked_risk_present: bool = False
    mitigations_complete: bool = False
    residual_risks: list[str] = Field(default_factory=list, max_length=64)
    human_review_required: bool = False
    failure_reasons: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyDecisionV1(BobaContract):
    safety_decision_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    action_request_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    autopilot_run_id: str = Field(default="", max_length=180)
    decision: BobaSafetyDecisionValueV1
    decision_summary: str = Field(min_length=1, max_length=900)
    allowed_action_class: str = Field(default="", max_length=80)
    allowed_target_module: str = Field(default="", max_length=160)
    allowed_target_operation: str = Field(default="", max_length=160)
    allowed_scope: list[str] = Field(default_factory=list, max_length=64)
    project_snapshot_digest: str = Field(default="", max_length=64)
    request_digest: str = Field(default="", max_length=64)
    policy_snapshot_digest: str = Field(default="", max_length=64)
    approval_record_id: str = Field(default="", max_length=180)
    decision_created_at: str = Field(default_factory=now_iso, max_length=80)
    decision_expires_at: str = Field(min_length=1, max_length=80)
    decision_expired: bool = False
    decision_valid: bool = False
    conditions: list[str] = Field(default_factory=list, max_length=64)
    unmet_conditions: list[str] = Field(default_factory=list, max_length=64)
    denial_reasons: list[str] = Field(default_factory=list, max_length=64)
    human_review_required: bool = False
    target_module_revalidation_required: bool = True
    workflow_resume_authorized: Literal[False] = False
    checkpoint_restore_authorized: Literal[False] = False
    upload_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False
    push_authorized: Literal[False] = False
    merge_authorized: Literal[False] = False
    deployment_authorized: Literal[False] = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaSafetyDecisionInvalidationV1(BobaContract):
    invalidation_id: str = Field(min_length=1, max_length=180)
    safety_decision_id: str = Field(min_length=1, max_length=180)
    invalidated_at: str = Field(default_factory=now_iso, max_length=80)
    invalidation_reason: str = Field(min_length=1, max_length=900)
    previous_request_digest: str = Field(default="", max_length=64)
    current_request_digest: str = Field(default="", max_length=64)
    previous_snapshot_digest: str = Field(default="", max_length=64)
    current_snapshot_digest: str = Field(default="", max_length=64)
    previous_policy_digest: str = Field(default="", max_length=64)
    current_policy_digest: str = Field(default="", max_length=64)
    approval_changed: bool = False
    plan_changed: bool = False
    strategy_changed: bool = False
    patch_changed: bool = False
    tool_changed: bool = False
    configuration_changed: bool = False
    checkpoint_changed: bool = False
    validation_changed: bool = False
    quality_requirements_changed: bool = False
    budget_changed: bool = False
    rights_changed: bool = False
    safety_state_changed: bool = False
    decision_expired: bool = False
    human_review_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=180)
    safety_case_id: str = Field(min_length=1, max_length=180)
    safety_decision_id: str = Field(min_length=1, max_length=180)
    target_module: BobaSafetyHandoffTargetV1
    reason: str = Field(min_length=1, max_length=900)
    required_inputs: list[str] = Field(default_factory=list, max_length=64)
    satisfied_conditions: list[str] = Field(default_factory=list, max_length=64)
    failed_conditions: list[str] = Field(default_factory=list, max_length=64)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=64)
    constraints: list[str] = Field(default_factory=list, max_length=64)
    prohibited_actions: list[str] = Field(default_factory=list, max_length=64)
    apply_automatically: bool = False
    human_approval_required: bool = True
    priority: str = Field(default="medium", max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyGateSummaryV1(BobaContract):
    total_evaluations: int = Field(default=0, ge=0)
    allowed_read_only_count: int = Field(default=0, ge=0)
    allowed_internal_execution_count: int = Field(default=0, ge=0)
    denied_count: int = Field(default=0, ge=0)
    human_review_count: int = Field(default=0, ge=0)
    more_evidence_count: int = Field(default=0, ge=0)
    rights_block_count: int = Field(default=0, ge=0)
    stale_state_block_count: int = Field(default=0, ge=0)
    budget_block_count: int = Field(default=0, ge=0)
    checkpoint_block_count: int = Field(default=0, ge=0)
    validation_block_count: int = Field(default=0, ge=0)
    quality_block_count: int = Field(default=0, ge=0)
    unsupported_future_action_count: int = Field(default=0, ge=0)
    expired_decision_count: int = Field(default=0, ge=0)
    invalidated_decision_count: int = Field(default=0, ge=0)
    highest_risk_case: str = Field(default="", max_length=700)
    most_common_denial_reason: str = Field(default="", max_length=700)
    current_pending_human_action: str = Field(default="", max_length=700)
    safest_next_action: str = Field(default="", max_length=700)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaSafetyGateSignalUsageV1(BobaContract):
    autopilot_controller_used: bool = False
    autopilot_artifact_read: bool = False
    rights_gate_used: bool = False
    rights_artifact_read: bool = False
    repair_planner_used: bool = False
    code_surgeon_used: bool = False
    tool_recovery_used: bool = False
    output_quality_reviewer_used: bool = False
    project_snapshot_used: bool = False
    target_module_approval_used: bool = False
    checkpoint_reference_used: bool = False
    rollback_plan_used: bool = False
    validation_plan_used: bool = False
    quality_plan_used: bool = False
    recovery_budget_used: bool = False
    policy_snapshot_used: bool = False
    decision_digest_used: bool = False
    direct_action_execution_used: Literal[False] = False
    direct_command_execution_used: Literal[False] = False
    direct_git_execution_used: Literal[False] = False
    direct_ffmpeg_execution_used: Literal[False] = False
    code_modification_used: Literal[False] = False
    artifact_modification_used: Literal[False] = False
    source_media_modified: Literal[False] = False
    accepted_outputs_modified: Literal[False] = False
    checkpoint_restore_used: Literal[False] = False
    workflow_resume_used: Literal[False] = False
    package_installation_used: Literal[False] = False
    service_restart_used: Literal[False] = False
    process_kill_used: Literal[False] = False
    external_api_used: Literal[False] = False
    network_access_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    uploading_used: Literal[False] = False
    publication_used: Literal[False] = False
    push_used: Literal[False] = False
    merge_used: Literal[False] = False
    deployment_used: Literal[False] = False
    rights_bypass_used: Literal[False] = False
    safety_bypass_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaSafetyGateSetV1(BobaContract):
    schema_version: Literal["boba_safety_gate_v1"] = "boba_safety_gate_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso, max_length=80)
    policy_snapshot: BobaSafetyPolicySnapshotV1
    evaluation_cases: list[BobaSafetyEvaluationCaseV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    action_requests: list[BobaSafetyActionRequestV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    evidence_records: list[BobaSafetyEvidenceV1] = Field(
        default_factory=list,
        max_length=4_096,
    )
    constraint_checks: list[BobaSafetyConstraintCheckV1] = Field(
        default_factory=list,
        max_length=8_192,
    )
    approval_reviews: list[BobaSafetyApprovalReviewV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    rights_reviews: list[BobaSafetyRightsReviewV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    checkpoint_reviews: list[BobaSafetyCheckpointReviewV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    validation_reviews: list[BobaSafetyValidationReadinessV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    quality_reviews: list[BobaSafetyQualityReviewV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    risk_assessments: list[BobaSafetyRiskAssessmentV1] = Field(
        default_factory=list,
        max_length=1_024,
    )
    safety_decisions: list[BobaSafetyDecisionV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    decision_invalidations: list[BobaSafetyDecisionInvalidationV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    handoffs: list[BobaSafetyHandoffV1] = Field(
        default_factory=list,
        max_length=2_048,
    )
    gate_summary: BobaSafetyGateSummaryV1 = Field(
        default_factory=BobaSafetyGateSummaryV1
    )
    signal_usage: BobaSafetyGateSignalUsageV1 = Field(
        default_factory=BobaSafetyGateSignalUsageV1
    )
    warnings: list[str] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=128)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *values: Any) -> str:
    return f"{prefix}_{_digest(values)[:24]}"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _text(value: Any, *, maximum: int = 900) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    text = _SECRET_VALUE.sub("[REDACTED]", text)
    text = _WINDOWS_PATH.sub("[private-path]", text)
    text = _PRIVATE_POSIX_PATH.sub("[private-path]", text)
    return text[:maximum]


def _unique(values: Sequence[Any], *, limit: int = 64, maximum: int = 900) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value, maximum=maximum)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
            if len(result) >= limit:
                break
    return result


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, BobaContract):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def sanitize_safety_export(value: Any) -> Any:
    """Return bounded JSON-safe evidence with paths and secrets removed."""

    if isinstance(value, BobaContract):
        return sanitize_safety_export(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:256]:
            key = _text(raw_key, maximum=160)
            if _SECRET_KEY.search(key):
                result[key] = "[REDACTED]"
            elif key.casefold() in _RAW_PATCH_KEYS | _COMMAND_KEYS:
                result[key] = "[OMITTED]"
            else:
                result[key] = sanitize_safety_export(item)
        return result
    if isinstance(value, list | tuple | set):
        return [sanitize_safety_export(item) for item in list(value)[:512]]
    if isinstance(value, str):
        return _text(value, maximum=2_000)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _text(value, maximum=900)


def build_safety_module_operation_registry() -> dict[str, dict[str, str]]:
    """Return the strict V1 module/operation registry."""

    return {
        "autopilot_controller": {
            "advance_safe_read_only": "automatic_read_only",
            "coordinate_approved_action": "approval_required_execution",
            "record_human_decision": "approval_required_read_only",
            "budget_reset": "approval_required_execution",
        },
        "code_surgeon": {
            "proposal": "automatic_read_only",
            "proposal_only": "automatic_read_only",
            "validate_patch": "automatic_read_only",
            "validate_proposal": "automatic_read_only",
            "execute_approved": "approval_required_execution",
            "prepare_local_commit": "approval_required_execution",
        },
        "tool_recovery_brain": {
            "plan": "automatic_read_only",
            "health_check": "automatic_read_only",
            "execute_approved": "approval_required_execution",
            "validate_output": "approval_required_read_only",
            "rollback": "approval_required_execution",
        },
        "output_quality_reviewer": {
            "artifact_review": "automatic_read_only",
            "local_technical_review": "approval_required_read_only",
            "technical_review": "approval_required_read_only",
            "compare": "approval_required_read_only",
            "baseline_compare": "approval_required_read_only",
            "record_human_review": "approval_required_read_only",
            "human_review": "approval_required_read_only",
        },
        "repair_planner": {"generate": "automatic_read_only"},
        "root_cause_analyzer": {"generate": "automatic_read_only"},
        "error_doctor": {"generate": "automatic_read_only"},
        "observer": {"generate": "automatic_read_only"},
        "checkpoint_recovery_manager": {
            "restore_checkpoint": "future_gated",
        },
        "workflow_controller": {
            "create_run": "automatic_read_only",
            "advance_safe_read_only_stage": "automatic_read_only",
            "advance_exact_internal_stage": "approval_required_execution",
            "pause": "approval_required_read_only",
            "cancel": "approval_required_read_only",
            "record_human_decision": "approval_required_read_only",
            "complete_internal_output": "approval_required_execution",
            "resume": "future_gated",
            "resume_workflow": "future_gated",
        },
        "validator_runner": {
            "build_registry": "automatic_read_only",
            "inspect_registry": "automatic_read_only",
            "inspect_availability": "automatic_read_only",
            "create_plan": "automatic_read_only",
            "validate_plan": "automatic_read_only",
            "create_run": "automatic_read_only",
            "execute_run": "approval_required_execution",
            "cancel_run": "approval_required_read_only",
            "retry_check": "approval_required_execution",
            "inspect_results": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "approval_required_read_only",
        },
        "report_reader": {
            "inspect_registry": "automatic_read_only",
            "create_read_request": "automatic_read_only",
            "validate_references": "automatic_read_only",
            "read_reports": "automatic_read_only",
            "inspect_read_run": "automatic_read_only",
            "compare_reports": "automatic_read_only",
            "build_bundle": "automatic_read_only",
            "inspect_bundle": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
        "artifact_inspector": {
            "inspect_registry": "automatic_read_only",
            "create_inspection_request": "automatic_read_only",
            "validate_references": "automatic_read_only",
            "inspect_artifacts": "automatic_read_only",
            "inspect_run": "automatic_read_only",
            "build_inventory": "automatic_read_only",
            "inspect_lineage": "automatic_read_only",
            "compare_artifacts": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
        "error_doctor_review": {
            "inspect_registry": "automatic_read_only",
            "create_session": "automatic_read_only",
            "update_session": "automatic_read_only",
            "build_queue": "automatic_read_only",
            "inspect_queue": "automatic_read_only",
            "build_snapshot": "automatic_read_only",
            "refresh_snapshot": "automatic_read_only",
            "inspect_incident": "automatic_read_only",
            "compare_incidents": "automatic_read_only",
            "inspect_diagnosis": "automatic_read_only",
            "inspect_root_cause": "automatic_read_only",
            "inspect_repair_plan": "automatic_read_only",
            "inspect_recovery_history": "automatic_read_only",
            "inspect_validation_evidence": "automatic_read_only",
            "inspect_artifact_evidence": "automatic_read_only",
            "detect_conflicts": "automatic_read_only",
            "create_action": "automatic_read_only",
            "validate_action": "automatic_read_only",
            "submit_action": "approval_required_read_only",
            "inspect_receipt": "automatic_read_only",
            "inspect_timeline": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
        "approval_controls": {
            "inspect_registry": "automatic_read_only",
            "inspect_eligibility": "automatic_read_only",
            "build_snapshot": "automatic_read_only",
            "revalidate_snapshot": "automatic_read_only",
            "create_decision": "automatic_read_only",
            "inspect_decision_status": "automatic_read_only",
            "inspect_decision_history": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
            "submit_decision": "approval_required_read_only",
        },
        "repair_plan_review": {
            "inspect_registry": "automatic_read_only",
            "create_session": "automatic_read_only",
            "update_session": "automatic_read_only",
            "build_queue": "automatic_read_only",
            "inspect_queue": "automatic_read_only",
            "build_snapshot": "automatic_read_only",
            "refresh_snapshot": "automatic_read_only",
            "inspect_plan": "automatic_read_only",
            "inspect_steps": "automatic_read_only",
            "inspect_risks": "automatic_read_only",
            "inspect_approvals": "automatic_read_only",
            "inspect_verification": "automatic_read_only",
            "inspect_evidence": "automatic_read_only",
            "inspect_recovery_history": "automatic_read_only",
            "detect_conflicts": "automatic_read_only",
            "inspect_conflicts": "automatic_read_only",
            "compare_plans": "automatic_read_only",
            "describe_confirmation": "automatic_read_only",
            "create_action": "automatic_read_only",
            "validate_action": "automatic_read_only",
            "submit_action": "approval_required_read_only",
            "inspect_receipt": "automatic_read_only",
            "inspect_timeline": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
        "clip_brief_review": {
            "inspect_registry": "automatic_read_only",
            "create_session": "automatic_read_only",
            "update_session": "automatic_read_only",
            "build_queue": "automatic_read_only",
            "inspect_queue": "automatic_read_only",
            "build_snapshot": "automatic_read_only",
            "refresh_snapshot": "automatic_read_only",
            "inspect_brief": "automatic_read_only",
            "compare_briefs": "automatic_read_only",
            "inspect_completeness": "automatic_read_only",
            "inspect_evidence": "automatic_read_only",
            "detect_conflicts": "automatic_read_only",
            "create_action": "automatic_read_only",
            "validate_action": "automatic_read_only",
            "submit_action": "approval_required_read_only",
            "inspect_receipt": "automatic_read_only",
            "inspect_timeline": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
        "candidate_review": {
            "inspect_registry": "automatic_read_only",
            "create_session": "automatic_read_only",
            "update_session": "automatic_read_only",
            "build_queue": "automatic_read_only",
            "inspect_queue": "automatic_read_only",
            "build_snapshot": "automatic_read_only",
            "refresh_snapshot": "automatic_read_only",
            "inspect_candidate": "automatic_read_only",
            "compare_candidates": "automatic_read_only",
            "calculate_overlaps": "automatic_read_only",
            "create_action": "automatic_read_only",
            "validate_action": "automatic_read_only",
            "submit_action": "approval_required_read_only",
            "inspect_receipt": "automatic_read_only",
            "inspect_timeline": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
        "review_ui": {
            "inspect_registry": "automatic_read_only",
            "create_session": "automatic_read_only",
            "update_session": "automatic_read_only",
            "build_queue": "automatic_read_only",
            "inspect_queue": "automatic_read_only",
            "build_snapshot": "automatic_read_only",
            "refresh_snapshot": "automatic_read_only",
            "inspect_target": "automatic_read_only",
            "create_action": "automatic_read_only",
            "validate_action": "automatic_read_only",
            "submit_action": "approval_required_read_only",
            "inspect_receipt": "automatic_read_only",
            "inspect_timeline": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "acknowledge_notification": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
        "final_decision_bus": {
            "build_registries": "automatic_read_only",
            "inspect_registries": "automatic_read_only",
            "create_request": "automatic_read_only",
            "validate_request": "automatic_read_only",
            "collect_source_bindings": "automatic_read_only",
            "validate_source_bindings": "automatic_read_only",
            "build_evidence_requirements": "automatic_read_only",
            "bind_evidence": "automatic_read_only",
            "detect_conflicts": "automatic_read_only",
            "evaluate_policy": "automatic_read_only",
            "finalize_decision": "automatic_read_only",
            "build_dispatch_envelope": "automatic_read_only",
            "inspect_decision": "automatic_read_only",
            "inspect_dispatch_envelope": "automatic_read_only",
            "consume_dispatch_envelope": "automatic_read_only",
            "invalidate_decision": "automatic_read_only",
            "inspect_events": "automatic_read_only",
            "load": "automatic_read_only",
            "export": "automatic_read_only",
            "reset": "automatic_read_only",
        },
    }


def calculate_safety_request_digest(value: Mapping[str, Any]) -> str:
    excluded = {"action_request_id", "request_digest", "requested_at", "warnings"}
    return _digest(
        {
            key: sanitize_safety_export(item)
            for key, item in value.items()
            if key not in excluded
        }
    )


def calculate_safety_decision_digest(value: Mapping[str, Any]) -> str:
    excluded = {
        "safety_decision_id",
        "decision_created_at",
        "decision_expired",
        "warnings",
        "limitations",
    }
    return _digest(
        {
            key: sanitize_safety_export(item)
            for key, item in value.items()
            if key not in excluded
        }
    )


def decision_is_expired(
    decision: BobaSafetyDecisionV1,
    *,
    at: datetime | None = None,
) -> bool:
    expires = _parse_time(decision.decision_expires_at)
    return expires is None or expires <= (at or datetime.now(UTC))


def _policy_payload(
    *,
    protected_paths: Sequence[str],
    protected_branches: Sequence[str],
    project_policy: Mapping[str, Any],
) -> dict[str, Any]:
    registry = build_safety_module_operation_registry()
    ttl = {
        "read_only_allowance": 900,
        "execution_allowance": 300,
        "human_review": 1_800,
    }
    raw_ttl = _mapping(project_policy.get("decision_ttl_seconds"))
    for key, ttl_default in list(ttl.items()):
        candidate = raw_ttl.get(key)
        if isinstance(candidate, int) and candidate > 0:
            ttl[key] = min(ttl_default, candidate)
    thresholds = {
        "automatic_read_only": 25.0,
        "approved_internal_execution": 60.0,
        "human_review": 80.0,
    }
    raw_thresholds = _mapping(project_policy.get("risk_thresholds"))
    for key, threshold_default in list(thresholds.items()):
        candidate = raw_thresholds.get(key)
        if isinstance(candidate, int | float):
            thresholds[key] = max(0.0, min(threshold_default, float(candidate)))
    extra_prohibited = _unique(
        _items(project_policy.get("additional_prohibited_actions")),
        limit=64,
        maximum=160,
    )
    extra_paths = _unique(
        _items(project_policy.get("additional_protected_paths")),
        limit=64,
        maximum=500,
    )
    extra_branches = _unique(
        _items(project_policy.get("additional_protected_branches")),
        limit=32,
        maximum=240,
    )
    return {
        "policy_version": "boba_safety_policy_v1",
        "protected_actions": [
            "source_media",
            "accepted_outputs",
            "protected_branches",
            "protected_paths",
            "required_validation",
            "quality_requirements",
            "rights_and_permission",
        ],
        "prohibited_actions": sorted(
            set(_ABSOLUTE_PROHIBITIONS) | set(extra_prohibited)
        ),
        "future_gated_actions": sorted(_FUTURE_GATED_ACTIONS),
        "allowlisted_modules": sorted(registry),
        "allowlisted_operations": {
            module: sorted(operations) for module, operations in sorted(registry.items())
        },
        "protected_paths": sorted(
            set(
                _unique(
                    [*protected_paths, *extra_paths],
                    limit=128,
                    maximum=500,
                )
            )
        ),
        "protected_branches": sorted(
            set(
                _unique(
                    [*protected_branches, *extra_branches],
                    limit=64,
                    maximum=240,
                )
            )
        ),
        "rights_requirements": [
            "Unknown or blocked rights cannot authorize media-processing execution.",
            "Local internal processing is distinct from upload and publication.",
            "Upload and publication remain unauthorized in V1.",
        ],
        "approval_requirements": [
            "Target-module approval must already exist.",
            "Approval must be explicit, current, exact, and independently revalidated.",
            "Approval alone never overrides higher-priority policy.",
        ],
        "checkpoint_requirements": [
            "Non-trivial execution requires a current validated checkpoint when planned.",
            "Safety Gate never restores or repairs checkpoints.",
        ],
        "rollback_requirements": [
            "Rollback ownership, scope, readiness, and validation must be explicit.",
            "Rollback cannot modify source media or accepted outputs.",
        ],
        "validation_requirements": [
            "Required validators and acceptance/rejection criteria must be available.",
            "Skipped or weakened required validation blocks execution.",
        ],
        "quality_requirements": [
            "Silent quality reduction and non-negotiable regressions block allowance.",
            "Technical completion is not final quality acceptance.",
        ],
        "budget_requirements": [
            "Project-wide action, execution, retry, time, and module budgets must remain.",
            "Budget reset requires separate exact human approval and preserved history.",
        ],
        "risk_thresholds": thresholds,
        "decision_ttl_seconds": ttl,
    }


def _semantic_signals(
    *,
    target_module: str,
    target_operation: str,
    action_description: str,
    parameters: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    flattened = _canonical(
        {
            "target_module": target_module,
            "target_operation": target_operation,
            "action_description": action_description,
            "parameter_keys": sorted(str(key) for key in parameters),
            "parameter_values": sanitize_safety_export(parameters),
        }
    ).casefold()
    prohibited = [
        name
        for name, tokens in _PROHIBITED_TOKENS.items()
        if any(token in flattened for token in tokens)
    ]
    future = [
        name
        for name, tokens in _FUTURE_TOKENS.items()
        if any(token in flattened for token in tokens)
    ]
    return sorted(set(prohibited)), sorted(set(future))


def _validate_request_payload(
    project_id: str,
    parameters: Mapping[str, Any],
) -> None:
    def inspect(value: Any, *, key: str = "") -> None:
        lowered = key.casefold()
        if lowered in _RAW_PATCH_KEYS:
            raise ValidationError(
                "Safety Gate accepts patch and media digests, not raw content."
            )
        if lowered in _COMMAND_KEYS:
            raise ValidationError("Safety Gate rejects arbitrary command payloads.")
        if _SECRET_KEY.search(lowered):
            raise ValidationError("Safety Gate rejects secret or credential material.")
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                inspect(child, key=str(child_key))
            return
        if isinstance(value, list | tuple | set):
            for child in value:
                inspect(child, key=key)
            return
        if isinstance(value, str):
            if _SECRET_VALUE.search(value):
                raise ValidationError("Safety Gate rejects secret material.")
            if _EXTERNAL_URL.search(value):
                raise ValidationError("Safety Gate rejects external URL payloads.")
            if _WINDOWS_PATH.search(value) or _PRIVATE_POSIX_PATH.search(value):
                raise ValidationError("Safety Gate rejects private absolute path injection.")
            references = set(_PROJECT_REFERENCE.findall(value))
            if references and references != {project_id}:
                raise ValidationError("Safety Gate rejects cross-project references.")

    inspect(parameters)


def _approval_fingerprint(value: Mapping[str, Any] | BobaContract | None) -> str:
    if value is None:
        return ""
    raw = value.model_dump(mode="json") if isinstance(value, BobaContract) else dict(value)
    for key in ("approved_by", "reviewer_identity", "reviewer"):
        if key in raw:
            raw[key] = _digest(_text(raw[key], maximum=160))
    return _digest(sanitize_safety_export(raw))


class BobaSafetyGateV1:
    """Evaluate exact bounded actions without invoking them."""

    def __init__(
        self,
        store: BobaMemoryStore,
        *,
        context_provider: SafetyContextProvider | None = None,
    ) -> None:
        self.store = store
        self.context_provider = context_provider

    def create_policy_snapshot(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        project_policy: Mapping[str, Any] | None = None,
        protected_paths: Sequence[str] = (
            ".git",
            ".env",
            "storage_data",
            "work",
            "media",
        ),
        protected_branches: Sequence[str] = ("main", "master"),
    ) -> BobaSafetyGateSetV1:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError("Invalid BOBA Safety Gate project id.")
        safe_project_policy = _mapping(project_policy)
        _validate_request_payload(project_id, safe_project_policy)
        payload = _policy_payload(
            protected_paths=protected_paths,
            protected_branches=protected_branches,
            project_policy=safe_project_policy,
        )
        policy_digest = _digest(payload)
        policy = BobaSafetyPolicySnapshotV1(
            policy_snapshot_id=f"safety_policy_{policy_digest[:24]}",
            **payload,
            policy_sha256=policy_digest,
            warnings=[
                "Lower-priority rules cannot override an absolute V1 prohibition."
            ],
            limitations=[
                "This policy evaluates internal actions only.",
                "It cannot authorize workflow resume, upload, publication, merge, or deployment.",
            ],
        )
        existing = self.store.load_boba_safety_gate(project_id)
        if existing is not None and existing.policy_snapshot.policy_sha256 == policy_digest:
            return existing
        if existing is None:
            gate = BobaSafetyGateSetV1(
                project_id=project_id,
                source_id=_text(source_id or project_id, maximum=512),
                policy_snapshot=policy,
                warnings=["Safety Gate V1 is evaluation-only."],
                limitations=[
                    "An allowance is temporary, exact, non-transferable, and revocable.",
                    "Target modules must independently revalidate approval and safety.",
                ],
            )
        else:
            prior_policy = existing.policy_snapshot
            existing.policy_snapshot = policy
            gate = existing
            for decision in list(gate.safety_decisions):
                if decision.decision_valid and not decision_is_expired(decision):
                    self._append_invalidation(
                        gate,
                        decision,
                        reason="The Safety Gate policy snapshot changed.",
                        current_policy_digest=policy.policy_sha256,
                    )
            gate.warnings = _unique(
                [
                    *gate.warnings,
                    f"Prior policy {prior_policy.policy_snapshot_id} remains immutable.",
                ],
                limit=128,
            )
        gate.signal_usage.policy_snapshot_used = True
        self._refresh_summary(gate)
        return self.store.save_boba_safety_gate(gate)

    def _gate(self, project_id: str) -> BobaSafetyGateSetV1:
        gate = self.store.load_boba_safety_gate(project_id)
        if gate is None:
            gate = self.create_policy_snapshot(project_id)
        return gate

    def create_action_request(
        self,
        project_id: str,
        *,
        autopilot_run_id: str = "",
        autopilot_action_id: str = "",
        requesting_module: str = "autopilot_controller",
        target_module: str = "",
        target_operation: str = "",
        action_class: BobaAutopilotActionClassV1 | str = "unknown",
        action_description: str = "",
        action_parameters: Mapping[str, Any] | None = None,
        project_snapshot_id: str = "",
        project_snapshot_digest: str = "",
        plan_id: str = "",
        strategy_id: str = "",
        approval_record_id: str = "",
        patch_proposal_id: str = "",
        patch_diff_sha256: str = "",
        code_base_sha: str = "",
        tool_id: str = "",
        capability_id: str = "",
        configuration_digest: str = "",
        checkpoint_reference: str = "",
        checkpoint_digest: str = "",
        rollback_plan_id: str = "",
        validation_plan_id: str = "",
        quality_plan_id: str = "",
        retry_budget_digest: str = "",
        time_budget_seconds: int = 0,
        requested_by: str = "autopilot_controller",
    ) -> BobaSafetyActionRequestV1:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError("Invalid BOBA Safety Gate project id.")
        gate = self._gate(project_id)
        controller = self.store.load_boba_autopilot_controller(project_id)
        action: BobaAutopilotActionV1 | None = None
        parameters = dict(action_parameters or {})
        if autopilot_action_id:
            if controller is None:
                raise ValidationError("The referenced Autopilot controller is unavailable.")
            action = next(
                (
                    item
                    for item in controller.planned_actions
                    if item.action_id == autopilot_action_id
                ),
                None,
            )
            if action is None:
                raise ValidationError("The referenced Autopilot action is unavailable.")
            run = next(
                (item for item in controller.runs if item.run_id == action.run_id),
                None,
            )
            if run is None:
                raise ValidationError("The referenced Autopilot run is unavailable.")
            if autopilot_run_id and autopilot_run_id != run.run_id:
                raise ValidationError("Autopilot run mismatch.")
            autopilot_run_id = run.run_id
            target_module = target_module or action.target_module
            target_operation = target_operation or action.target_operation
            action_class = (
                action.action_class if action_class == "unknown" else action_class
            )
            action_description = action_description or action.description
            parameters = parameters or dict(action.parameters)
            snapshot = next(
                (
                    item
                    for item in reversed(controller.project_snapshots)
                    if item.project_snapshot_id == run.project_snapshot_id
                ),
                None,
            )
            if snapshot is None:
                raise ValidationError("The Autopilot project snapshot is unavailable.")
            project_snapshot_id = project_snapshot_id or snapshot.project_snapshot_id
            project_snapshot_digest = (
                project_snapshot_digest or snapshot.snapshot_sha256
            )
            if project_snapshot_digest != snapshot.snapshot_sha256:
                raise ValidationError("The supplied project snapshot digest is stale.")
            plan_id = plan_id or _text(
                parameters.get("recovery_plan_id")
                or parameters.get("patch_proposal_id")
                or parameters.get("target_plan_id"),
                maximum=180,
            )
            strategy_id = strategy_id or _text(
                parameters.get("recovery_strategy_id")
                or parameters.get("repair_strategy_id")
                or parameters.get("target_strategy_id"),
                maximum=180,
            )
            patch_proposal_id = patch_proposal_id or _text(
                parameters.get("patch_proposal_id"),
                maximum=180,
            )
            tool_id = tool_id or _text(parameters.get("tool_id"), maximum=180)
            capability_id = capability_id or _text(
                parameters.get("capability_id"),
                maximum=180,
            )
            checkpoint_reference = checkpoint_reference or _text(
                parameters.get("checkpoint_reference"),
                maximum=500,
            )
            rollback_plan_id = rollback_plan_id or _text(
                parameters.get("rollback_plan_id"),
                maximum=180,
            )
            validation_plan_id = validation_plan_id or _text(
                parameters.get("validation_plan_id"),
                maximum=180,
            )
            quality_plan_id = quality_plan_id or _text(
                parameters.get("quality_plan_id"),
                maximum=180,
            )
        _validate_request_payload(project_id, parameters)
        _validate_request_payload(
            project_id,
            {
                "action_description": action_description,
                "plan_id": plan_id,
                "strategy_id": strategy_id,
                "approval_record_id": approval_record_id,
                "patch_proposal_id": patch_proposal_id,
                "tool_id": tool_id,
                "capability_id": capability_id,
                "checkpoint_reference": checkpoint_reference,
                "rollback_plan_id": rollback_plan_id,
                "validation_plan_id": validation_plan_id,
                "quality_plan_id": quality_plan_id,
                "requested_by": requested_by,
            },
        )
        registry = build_safety_module_operation_registry()
        if requesting_module not in {
            "autopilot_controller",
            "human_operator",
            *registry,
        }:
            raise ValidationError("Safety Gate rejected an unknown requesting module.")
        if target_module not in registry:
            raise ValidationError("Safety Gate rejected an unknown target module.")
        operation_class = registry[target_module].get(target_operation)
        if operation_class is None:
            raise ValidationError("Safety Gate rejected an unknown target operation.")
        if action_class == "unknown":
            action_class = operation_class
        if action_class not in {
            "automatic_read_only",
            "approval_required_read_only",
            "approval_required_execution",
            "future_gated",
            "prohibited",
        }:
            raise ValidationError("Safety Gate rejected an unsupported action class.")
        if operation_class != action_class and operation_class != "future_gated":
            raise ValidationError("The requested action class does not match the registry.")
        if not project_snapshot_id or len(project_snapshot_digest) != 64:
            raise ValidationError("An exact project snapshot and digest are required.")
        for digest_value in (
            patch_diff_sha256,
            configuration_digest,
            retry_budget_digest,
        ):
            if digest_value and len(digest_value) != 64:
                raise ValidationError("Safety Gate digest fields must be SHA-256 values.")
        if checkpoint_reference and (
            _WINDOWS_PATH.search(checkpoint_reference)
            or _PRIVATE_POSIX_PATH.search(checkpoint_reference)
            or _EXTERNAL_URL.search(checkpoint_reference)
        ):
            raise ValidationError("Safety Gate rejects unsafe checkpoint references.")
        prohibited_signals, future_signals = _semantic_signals(
            target_module=target_module,
            target_operation=target_operation,
            action_description=action_description,
            parameters=parameters,
        )
        parameter_digest = _digest(sanitize_safety_export(parameters))
        raw = {
            "project_id": project_id,
            "autopilot_run_id": autopilot_run_id,
            "autopilot_action_id": autopilot_action_id,
            "requesting_module": requesting_module,
            "target_module": target_module,
            "target_operation": target_operation,
            "action_class": action_class,
            "action_description": _text(action_description or target_operation, maximum=700),
            "action_parameters_digest": parameter_digest,
            "project_snapshot_id": project_snapshot_id,
            "project_snapshot_digest": project_snapshot_digest,
            "plan_id": _text(plan_id, maximum=180),
            "strategy_id": _text(strategy_id, maximum=180),
            "approval_record_id": _text(approval_record_id, maximum=180),
            "patch_proposal_id": _text(patch_proposal_id, maximum=180),
            "patch_diff_sha256": patch_diff_sha256,
            "code_base_sha": _text(code_base_sha, maximum=64),
            "tool_id": _text(tool_id, maximum=180),
            "capability_id": _text(capability_id, maximum=180),
            "configuration_digest": configuration_digest,
            "checkpoint_reference": _text(checkpoint_reference, maximum=500),
            "checkpoint_digest": _text(checkpoint_digest, maximum=128),
            "rollback_plan_id": _text(rollback_plan_id, maximum=180),
            "validation_plan_id": _text(validation_plan_id, maximum=180),
            "quality_plan_id": _text(quality_plan_id, maximum=180),
            "retry_budget_digest": retry_budget_digest,
            "time_budget_seconds": max(0, min(int(time_budget_seconds), 3_600)),
            "requested_by": _text(requested_by, maximum=160),
        }
        request_digest = calculate_safety_request_digest(raw)
        request = BobaSafetyActionRequestV1(
            action_request_id=f"safety_request_{request_digest[:24]}",
            **raw,
            request_digest=request_digest,
            warnings=[
                *[f"prohibited-signal:{item}" for item in prohibited_signals],
                *[f"future-signal:{item}" for item in future_signals],
                "The request stores references and digests, not raw commands, patches, or media.",
            ],
        )
        existing = next(
            (
                item
                for item in gate.action_requests
                if item.request_digest == request.request_digest
            ),
            None,
        )
        if existing is not None:
            return existing
        gate.action_requests.append(request)
        gate.action_requests = gate.action_requests[-1_024:]
        gate.signal_usage.autopilot_controller_used = controller is not None
        gate.signal_usage.autopilot_artifact_read = controller is not None
        gate.signal_usage.project_snapshot_used = True
        self._refresh_summary(gate)
        self.store.save_boba_safety_gate(gate)
        return request

    def _request(
        self,
        gate: BobaSafetyGateSetV1,
        action_request_id: str,
    ) -> BobaSafetyActionRequestV1:
        request = next(
            (
                item
                for item in gate.action_requests
                if item.action_request_id == action_request_id
            ),
            None,
        )
        if request is None:
            raise ValidationError("BOBA Safety Gate action request was not found.")
        return request

    def _default_context(
        self,
        project_id: str,
        request: BobaSafetyActionRequestV1,
    ) -> dict[str, Any]:
        controller = self.store.load_boba_autopilot_controller(project_id)
        run = None
        action = None
        snapshot = None
        budget = None
        usage = None
        checkpoint = None
        if controller is not None:
            run = next(
                (
                    item
                    for item in controller.runs
                    if item.run_id == request.autopilot_run_id
                ),
                None,
            )
            action = next(
                (
                    item
                    for item in controller.planned_actions
                    if item.action_id == request.autopilot_action_id
                ),
                None,
            )
            if run is not None:
                snapshot = next(
                    (
                        item
                        for item in reversed(controller.project_snapshots)
                        if item.project_snapshot_id == run.project_snapshot_id
                    ),
                    None,
                )
                budget = next(
                    (
                        item
                        for item in reversed(controller.recovery_budgets)
                        if item.budget_id == run.budget_id
                    ),
                    None,
                )
                usage = next(
                    (
                        item
                        for item in reversed(controller.budget_usages)
                        if item.budget_id == run.budget_id
                    ),
                    None,
                )
                checkpoint = next(
                    (
                        item
                        for item in reversed(controller.checkpoint_requirements)
                        if item.run_id == run.run_id
                    ),
                    None,
                )
        planner = self.store.load_boba_repair_planner(project_id)
        code = self.store.load_boba_code_surgeon(project_id)
        tool = self.store.load_boba_tool_recovery(project_id)
        quality = self.store.load_boba_output_quality_reviewer(project_id)
        rights = self.store.load_rights_permission_gate(project_id)
        validation_plan = next(
            (
                item
                for item in getattr(planner, "validation_plans", [])
                if item.validation_plan_id == request.validation_plan_id
            ),
            None,
        )
        quality_plan = next(
            (
                item
                for item in getattr(planner, "quality_preservation_plans", [])
                if item.quality_preservation_plan_id == request.quality_plan_id
            ),
            None,
        )
        rollback_plan = next(
            (
                item
                for item in getattr(planner, "rollback_plans", [])
                if item.rollback_plan_id == request.rollback_plan_id
            ),
            None,
        )
        code_proposal = next(
            (
                item
                for item in getattr(code, "patch_proposals", [])
                if item.patch_proposal_id
                in {request.patch_proposal_id, request.plan_id}
            ),
            None,
        )
        code_approval = next(
            (
                item
                for item in getattr(code, "approval_records", [])
                if item.approval_id == request.approval_record_id
            ),
            None,
        )
        recovery_plan = next(
            (
                item
                for item in getattr(tool, "recovery_plans", [])
                if item.recovery_plan_id == request.plan_id
            ),
            None,
        )
        recovery_strategy = next(
            (
                item
                for item in getattr(recovery_plan, "ordered_strategies", [])
                if item.recovery_strategy_id == request.strategy_id
            ),
            None,
        )
        quality_decision = (
            getattr(quality, "acceptance_decisions", [])[-1]
            if getattr(quality, "acceptance_decisions", [])
            else None
        )
        rights_status = getattr(run, "rights_status", "unknown")
        safety_status = getattr(run, "safety_status", "unknown")
        rights_gate_statuses = [
            getattr(item, "gate_status", "unknown")
            for item in getattr(rights, "gate_decisions", [])
        ]
        if "blocked" in rights_gate_statuses:
            rights_status = "blocked"
        elif any(
            item
            in {
                "needs_permission",
                "needs_rights_review",
                "insufficient_information",
            }
            for item in rights_gate_statuses
        ):
            rights_status = "needs_rights_review"
        return {
            "controller": controller,
            "run": run,
            "action": action,
            "snapshot": snapshot,
            "snapshot_current": bool(
                snapshot is not None
                and snapshot.snapshot_sha256 == request.project_snapshot_digest
                and snapshot.project_snapshot_id == request.project_snapshot_id
            ),
            "rights_status": rights_status,
            "permission_status": (
                "permission_required"
                if rights_status in {"needs_permission", "permission_needed"}
                else "confirmed"
                if rights_status in _RIGHTS_CLEAR
                else "unknown"
            ),
            "safety_status": safety_status,
            "rights_gate": rights,
            "budget": budget,
            "budget_usage": usage,
            "checkpoint": checkpoint,
            "validation_plan": validation_plan,
            "quality_plan": quality_plan,
            "rollback_plan": rollback_plan,
            "code_report": code,
            "code_proposal": code_proposal,
            "code_approval": code_approval,
            "tool_report": tool,
            "recovery_plan": recovery_plan,
            "recovery_strategy": recovery_strategy,
            "quality_report": quality,
            "quality_decision": quality_decision,
            "available_validators": [],
            "skipped_required_checks": [],
            "source_media_protected": bool(
                getattr(snapshot, "source_media_read_only", True)
            ),
            "accepted_outputs_protected": bool(
                getattr(checkpoint, "accepted_outputs_protected", True)
            ),
            "conflicting_state": bool(
                getattr(snapshot, "conflicting_artifact_ids", [])
                or getattr(snapshot, "active_external_operations", [])
            ),
            "approval": code_approval,
        }

    def _context(
        self,
        project_id: str,
        request: BobaSafetyActionRequestV1,
        *,
        approval_record: Mapping[str, Any] | BobaContract | None,
    ) -> dict[str, Any]:
        context = self._default_context(project_id, request)
        if self.context_provider is not None:
            context.update(dict(self.context_provider(project_id, request)))
        if approval_record is not None:
            context["approval"] = approval_record
        return context

    @staticmethod
    def _execution_required(request: BobaSafetyActionRequestV1) -> bool:
        return request.action_class == "approval_required_execution"

    @staticmethod
    def _media_relevant(request: BobaSafetyActionRequestV1) -> bool:
        return request.target_module in {
            "tool_recovery_brain",
            "output_quality_reviewer",
            "observer",
            "error_doctor",
            "root_cause_analyzer",
            "repair_planner",
        }

    def _approval_review(
        self,
        case_id: str,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
    ) -> BobaSafetyApprovalReviewV1:
        required = request.action_class in {
            "approval_required_read_only",
            "approval_required_execution",
        }
        raw_approval = context.get("approval")
        review_override = _mapping(context.get("approval_review"))
        failure_reasons: list[str] = []
        approval_found = raw_approval is not None
        approval_id = request.approval_record_id
        approval_type = ""
        approved = False
        explicit = False
        approved_at: str | None = None
        expires_at: str | None = None
        approved_by = ""
        approved_scope: list[str] = []
        scope_match = not required
        parameters_match = not required
        snapshot_match = True
        current_fingerprint = _approval_fingerprint(
            raw_approval if isinstance(raw_approval, Mapping | BobaContract) else None
        )
        approved_fingerprint = current_fingerprint
        if review_override:
            approval_found = bool(review_override.get("approval_found", required))
            approved = bool(review_override.get("approved", not required))
            explicit = bool(
                review_override.get("explicit_confirmation", not required)
            )
            scope_match = bool(review_override.get("scope_match", not required))
            parameters_match = bool(
                review_override.get("parameters_match", not required)
            )
            snapshot_match = bool(review_override.get("snapshot_match", True))
            approval_id = _text(
                review_override.get("approval_record_id") or approval_id,
                maximum=180,
            )
            approval_type = _text(
                review_override.get("approval_type"),
                maximum=160,
            )
            expires_at = _text(review_override.get("expires_at"), maximum=80) or None
            approved_fingerprint = _text(
                review_override.get("approved_parameters_digest")
                or current_fingerprint,
                maximum=64,
            )
            current_fingerprint = _text(
                review_override.get("current_parameters_digest")
                or current_fingerprint,
                maximum=64,
            )
            failure_reasons.extend(
                _unique(_items(review_override.get("failure_reasons")), limit=64)
            )
        elif isinstance(raw_approval, BobaCodeApprovalRecordV1 | Mapping) and (
            request.target_module == "code_surgeon"
        ):
            try:
                code_approval = (
                    raw_approval
                    if isinstance(raw_approval, BobaCodeApprovalRecordV1)
                    else BobaCodeApprovalRecordV1.model_validate(raw_approval)
                )
                proposal = context.get("code_proposal")
                approval_found = True
                approval_id = code_approval.approval_id
                approval_type = code_approval.approval_type
                approved = code_approval.approved
                explicit = code_approval.explicit_confirmation
                approved_at = code_approval.approved_at
                expires_at = code_approval.approval_expires_at
                approved_by = _digest(_text(code_approval.approved_by, maximum=160))
                approved_scope = code_approval.approved_scope
                if proposal is None:
                    failure_reasons.append("The exact Code Surgeon proposal is unavailable.")
                else:
                    required_type: BobaCodeApprovalTypeV1 = (
                        "local_commit_creation"
                        if request.target_operation == "prepare_local_commit"
                        else "isolated_patch_execution"
                    )
                    failure_reasons.extend(
                        verify_code_approval(
                            proposal,
                            code_approval,
                            required_type=required_type,
                        )
                    )
                    scope_match = not any(
                        "scope" in item.casefold() for item in failure_reasons
                    )
                    parameters_match = bool(
                        proposal.patch_proposal_id
                        in {request.patch_proposal_id, request.plan_id}
                        and proposal.diff_sha256 == request.patch_diff_sha256
                        and proposal.base_commit_sha == request.code_base_sha
                    )
            except Exception as exc:
                failure_reasons.append(
                    f"Code Surgeon approval is malformed: {_text(exc, maximum=400)}"
                )
        elif request.target_module == "tool_recovery_brain" and raw_approval is not None:
            try:
                recovery_approval = (
                    raw_approval
                    if isinstance(raw_approval, BobaToolRecoveryApprovalV1)
                    else BobaToolRecoveryApprovalV1.model_validate(raw_approval)
                )
                plan = context.get("recovery_plan")
                strategy = context.get("recovery_strategy")
                approval_found = True
                approval_id = recovery_approval.approval_id
                approval_type = "tool_recovery_exact"
                approved = recovery_approval.approved
                explicit = bool(recovery_approval.explicit_confirmation.strip())
                approved_at = recovery_approval.approved_at
                expires_at = recovery_approval.approval_expires_at
                approved_by = _digest(
                    _text(recovery_approval.approved_by, maximum=160)
                )
                approved_scope = [
                    *recovery_approval.approved_strategy_ids,
                    *recovery_approval.approved_tool_ids,
                ]
                if plan is None or strategy is None:
                    failure_reasons.append(
                        "The exact Tool Recovery plan or strategy is unavailable."
                    )
                else:
                    failure_reasons.extend(
                        verify_recovery_approval(
                            plan,
                            strategy,
                            recovery_approval,
                        )
                    )
                    scope_match = not any(
                        any(
                            token in item.casefold()
                            for token in ("strategy", "tool", "capability")
                        )
                        for item in failure_reasons
                    )
                    parameters_match = bool(
                        plan.recovery_plan_id == request.plan_id
                        and strategy.recovery_strategy_id == request.strategy_id
                        and (
                            not request.tool_id
                            or request.tool_id
                            in recovery_approval.approved_tool_ids
                        )
                    )
            except Exception as exc:
                failure_reasons.append(
                    f"Tool Recovery approval is malformed: {_text(exc, maximum=400)}"
                )
        elif raw_approval is not None:
            raw = _mapping(raw_approval)
            approval_found = True
            approval_id = _text(
                raw.get("approval_id")
                or raw.get("decision_id")
                or request.approval_record_id,
                maximum=180,
            )
            approval_type = _text(raw.get("approval_type") or "bounded_human", maximum=160)
            approved = bool(raw.get("approved"))
            explicit = bool(
                raw.get("explicit_confirmation")
                or raw.get("confirmation")
            )
            approved_at = _text(raw.get("approved_at"), maximum=80) or None
            expires_at = _text(
                raw.get("approval_expires_at") or raw.get("expires_at"),
                maximum=80,
            ) or None
            approved_by = _digest(
                _text(
                    raw.get("approved_by")
                    or raw.get("reviewer_identity")
                    or "bounded_reviewer",
                    maximum=160,
                )
            )
            approved_scope = _unique(
                _items(raw.get("approved_scope")),
                limit=64,
                maximum=180,
            )
            scope_match = bool(raw.get("scope_match", True))
            parameters_match = bool(raw.get("parameters_match", True))
            snapshot_match = (
                not raw.get("project_snapshot_digest")
                or raw.get("project_snapshot_digest")
                == request.project_snapshot_digest
            )
        expiry = _parse_time(expires_at) if expires_at else None
        expiry_value = expiry or datetime.min.replace(tzinfo=UTC)
        expired = bool(expires_at and expiry_value <= datetime.now(UTC))
        if required:
            if not approval_found:
                failure_reasons.append("Exact target-module approval is missing.")
            if not explicit:
                failure_reasons.append("Approval lacks explicit confirmation.")
            if not approved:
                failure_reasons.append("The target-module approval is not approved.")
            if expired:
                failure_reasons.append("The target-module approval expired.")
            if request.approval_record_id and approval_id != request.approval_record_id:
                failure_reasons.append("Approval record ID does not match the request.")
            if not scope_match:
                failure_reasons.append("Approval scope does not match.")
            if not parameters_match:
                failure_reasons.append("Approval-bound parameters changed.")
            if not snapshot_match:
                failure_reasons.append("Approval-bound project snapshot changed.")
        else:
            approved = True
            explicit = True
            scope_match = True
            parameters_match = True
            snapshot_match = True
        exact = not failure_reasons
        return BobaSafetyApprovalReviewV1(
            approval_review_id=_stable_id(
                "safety_approval_review",
                case_id,
                approval_id,
                current_fingerprint,
            ),
            safety_case_id=case_id,
            approval_record_id=approval_id,
            target_module=request.target_module,
            approval_type=approval_type or ("not_required" if not required else "unknown"),
            approval_found=approval_found,
            explicit_confirmation=explicit,
            approved=approved,
            approved_at=approved_at,
            expires_at=expires_at,
            expired=expired,
            approved_by_reference=approved_by,
            approved_scope=_unique(approved_scope, limit=64, maximum=180),
            expected_scope=_unique(
                [
                    request.plan_id,
                    request.strategy_id,
                    request.patch_proposal_id,
                    request.tool_id,
                    request.capability_id,
                ],
                limit=64,
                maximum=180,
            ),
            scope_match=scope_match,
            approved_parameters_digest=approved_fingerprint,
            current_parameters_digest=current_fingerprint,
            parameters_match=parameters_match,
            approved_project_snapshot_digest=request.project_snapshot_digest,
            current_project_snapshot_digest=request.project_snapshot_digest,
            snapshot_match=snapshot_match,
            exact_binding_valid=exact,
            failure_reasons=_unique(failure_reasons, limit=64),
            warnings=[
                "Safety Gate does not create approval.",
                "The target module must independently revalidate this approval.",
            ],
        )

    def _rights_review(
        self,
        case_id: str,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
    ) -> BobaSafetyRightsReviewV1:
        override = _mapping(context.get("rights_review"))
        status = _text(
            override.get("rights_status") or context.get("rights_status") or "unknown",
            maximum=80,
        ).casefold()
        permission = _text(
            override.get("permission_status")
            or context.get("permission_status")
            or "unknown",
            maximum=80,
        ).casefold()
        media_relevant = bool(
            override.get("media_relevant", self._media_relevant(request))
        )
        blocked = status in _RIGHTS_BLOCKED or permission in {
            "required",
            "permission_required",
            "denied",
        }
        unknown = status in {"", "unknown", "unverified", "ready_for_human_review"}
        explicitly_allowed = bool(
            override.get("rights_clear_for_requested_internal_action")
        )
        if media_relevant:
            clear = explicitly_allowed or (
                status in _RIGHTS_CLEAR
                and permission not in {"required", "permission_required", "denied"}
            )
        else:
            clear = not blocked
        failures: list[str] = []
        if blocked:
            failures.append("Rights or permission evidence blocks this internal action.")
        elif media_relevant and unknown and not explicitly_allowed:
            failures.append("Media-processing rights remain unknown.")
        if override.get("stale"):
            failures.append("Rights evidence is stale.")
        clear = clear and not failures
        return BobaSafetyRightsReviewV1(
            rights_review_id=_stable_id(
                "safety_rights_review",
                case_id,
                status,
                permission,
                clear,
            ),
            safety_case_id=case_id,
            rights_gate_record_id=_text(
                override.get("rights_gate_record_id")
                or getattr(context.get("rights_gate"), "created_at", ""),
                maximum=180,
            ),
            rights_status=status or "unknown",
            permission_status=permission or "unknown",
            source_provenance_status=_text(
                override.get("source_provenance_status") or "bounded_project_reference",
                maximum=80,
            ),
            processing_scope_allowed=(
                ["local_internal_analysis"]
                if clear
                else []
            ),
            external_processing_allowed=False,
            unknown_rights_present=unknown,
            blocked_rights_present=blocked,
            human_rights_review_required=not clear,
            rights_clear_for_requested_internal_action=clear,
            failure_reasons=failures,
            warnings=[
                "Local internal processing does not authorize upload or publication."
            ],
        )

    def _checkpoint_review(
        self,
        case_id: str,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
    ) -> BobaSafetyCheckpointReviewV1:
        override = _mapping(context.get("checkpoint_review"))
        checkpoint = context.get("checkpoint")
        rollback = context.get("rollback_plan")
        required = bool(
            override.get(
                "checkpoint_required",
                self._execution_required(request)
                and request.target_operation
                not in {"budget_reset", "record_human_review"},
            )
        )
        reference = _text(
            override.get("checkpoint_reference")
            or request.checkpoint_reference
            or getattr(checkpoint, "checkpoint_reference", ""),
            maximum=500,
        )
        digest = _text(
            override.get("checkpoint_digest")
            or request.checkpoint_digest
            or getattr(checkpoint, "checkpoint_artifact_digest", ""),
            maximum=128,
        )
        status_value = _text(
            override.get("checkpoint_status")
            or getattr(checkpoint, "checkpoint_status", "")
            or ("not_required" if not required else "missing"),
            maximum=80,
        )
        status: BobaSafetyCheckpointStatusV1 = (
            cast(BobaSafetyCheckpointStatusV1, status_value)
            if status_value
            in {
                "not_required",
                "valid",
                "missing",
                "stale",
                "corrupt",
                "unverified",
                "mismatched",
                "unknown",
            }
            else "valid"
            if status_value in {"available"}
            and getattr(checkpoint, "checkpoint_validated", False)
            else "unverified"
        )
        validated = bool(
            override.get(
                "checkpoint_validated",
                getattr(checkpoint, "checkpoint_validated", False),
            )
        )
        fresh = bool(
            override.get(
                "checkpoint_fresh",
                status == "valid" and validated,
            )
        )
        rollback_present = bool(
            override.get(
                "rollback_plan_present",
                request.rollback_plan_id or rollback is not None,
            )
        )
        rollback_ready = bool(
            override.get(
                "rollback_ready",
                getattr(checkpoint, "rollback_ready", False)
                or (
                    rollback is not None
                    and bool(getattr(rollback, "rollback_validation", []))
                    and bool(getattr(rollback, "rollback_owner_module", ""))
                ),
            )
        )
        state_ready = bool(
            override.get(
                "state_preservation_ready",
                getattr(checkpoint, "source_media_protected", True)
                and getattr(checkpoint, "accepted_outputs_protected", True),
            )
        )
        source_protected = bool(
            override.get(
                "source_media_protected",
                context.get("source_media_protected", True),
            )
        )
        outputs_protected = bool(
            override.get(
                "accepted_outputs_protected",
                context.get("accepted_outputs_protected", True),
            )
        )
        destructive = bool(
            override.get("destructive_rollback")
            or (
                rollback is not None
                and not getattr(rollback, "destructive_rollback_blocked", True)
            )
        )
        failures: list[str] = []
        if required:
            if not reference:
                failures.append("A required checkpoint reference is missing.")
            if status != "valid":
                failures.append(f"Checkpoint status is {status}.")
            if not validated:
                failures.append("The checkpoint is not validated.")
            if not fresh:
                failures.append("The checkpoint is stale or freshness is unverified.")
            if request.checkpoint_digest and digest != request.checkpoint_digest:
                failures.append("Checkpoint digest does not match the request.")
            if not rollback_present:
                failures.append("A required rollback plan is missing.")
            if not rollback_ready:
                failures.append("Rollback readiness is not confirmed.")
        if not source_protected:
            failures.append("Source media protection is not confirmed.")
        if not outputs_protected:
            failures.append("Accepted-output protection is not confirmed.")
        if destructive:
            failures.append("The rollback plan contains prohibited destructive behavior.")
        return BobaSafetyCheckpointReviewV1(
            checkpoint_review_id=_stable_id(
                "safety_checkpoint_review",
                case_id,
                reference,
                digest,
                status,
                failures,
            ),
            safety_case_id=case_id,
            checkpoint_required=required,
            checkpoint_reference=reference,
            checkpoint_digest=digest,
            checkpoint_status=status,
            checkpoint_validated=validated if required else True,
            checkpoint_fresh=fresh if required else True,
            state_preservation_ready=state_ready,
            rollback_plan_present=rollback_present if required else True,
            rollback_ready=rollback_ready if required else True,
            source_media_protected=source_protected,
            accepted_outputs_protected=outputs_protected,
            checkpoint_manager_required=bool(required and failures),
            blocks_action=bool(failures),
            failure_reasons=_unique(failures, limit=64),
            warnings=["Safety Gate does not restore or repair checkpoints."],
        )

    def _validation_review(
        self,
        case_id: str,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
    ) -> BobaSafetyValidationReadinessV1:
        override = _mapping(context.get("validation_review"))
        plan = context.get("validation_plan")
        required = bool(
            override.get(
                "required",
                self._execution_required(request)
                or request.target_operation
                in {"local_technical_review", "technical_review"},
            )
        )
        plan_id = _text(
            override.get("validation_plan_id")
            or request.validation_plan_id
            or getattr(plan, "validation_plan_id", ""),
            maximum=180,
        )
        required_validators = _unique(
            _items(override.get("required_validators"))
            or getattr(plan, "required_validators", []),
            limit=64,
            maximum=180,
        )
        available = _unique(
            _items(override.get("available_validators"))
            or _items(context.get("available_validators")),
            limit=64,
            maximum=180,
        )
        unavailable = _unique(
            _items(override.get("unavailable_validators"))
            or [item for item in required_validators if item not in available],
            limit=64,
            maximum=180,
        )
        pre_checks = _unique(
            _items(override.get("pre_action_checks"))
            or [
                getattr(item, "description", "")
                for item in getattr(plan, "pre_repair_checks", [])
            ],
            limit=64,
        )
        post_checks = _unique(
            _items(override.get("post_action_checks"))
            or [
                getattr(item, "description", "")
                for item in getattr(plan, "post_repair_checks", [])
            ],
            limit=64,
        )
        rollback_checks = _unique(
            _items(override.get("rollback_checks"))
            or getattr(context.get("rollback_plan"), "rollback_validation", []),
            limit=64,
        )
        acceptance = _unique(
            _items(override.get("acceptance_criteria"))
            or getattr(plan, "acceptance_criteria", []),
            limit=64,
        )
        rejection = _unique(
            _items(override.get("rejection_criteria"))
            or getattr(plan, "rejection_criteria", []),
            limit=64,
        )
        skipped = _unique(
            _items(override.get("skipped_required_checks"))
            or _items(context.get("skipped_required_checks")),
            limit=64,
        )
        failures: list[str] = []
        if required:
            if not plan_id:
                failures.append("A required validation plan is missing.")
            if not required_validators:
                failures.append("Required validators are not defined.")
            if unavailable:
                failures.append(
                    f"Required validators are unavailable: {', '.join(unavailable)}."
                )
            if skipped:
                failures.append(
                    f"Required checks were skipped: {', '.join(skipped)}."
                )
            if not post_checks:
                failures.append("Post-action validation checks are missing.")
            if not acceptance:
                failures.append("Validation acceptance criteria are missing.")
            if not rejection:
                failures.append("Validation rejection criteria are missing.")
            if self._execution_required(request) and not rollback_checks:
                failures.append("Rollback validation checks are missing.")
            if override.get("validation_weakened"):
                failures.append("The request weakens required validation.")
        defined = bool(plan_id and post_checks and acceptance and rejection)
        ready = not failures
        return BobaSafetyValidationReadinessV1(
            validation_review_id=_stable_id(
                "safety_validation_review",
                case_id,
                plan_id,
                required_validators,
                available,
                failures,
            ),
            safety_case_id=case_id,
            validation_plan_id=plan_id,
            required_validators=required_validators,
            available_validators=available,
            unavailable_validators=unavailable,
            pre_action_checks=pre_checks,
            post_action_checks=post_checks,
            rollback_checks=rollback_checks,
            acceptance_criteria=acceptance,
            rejection_criteria=rejection,
            required_checks_defined=defined if required else True,
            required_checks_available=not unavailable if required else True,
            skipped_required_checks=skipped,
            validation_runner_required=required,
            validation_ready=ready,
            failure_reasons=_unique(failures, limit=64),
            warnings=["Safety Gate evaluates validation readiness but never runs validators."],
        )

    def _quality_review(
        self,
        case_id: str,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
    ) -> BobaSafetyQualityReviewV1:
        override = _mapping(context.get("quality_review"))
        plan = context.get("quality_plan")
        output_decision = context.get("quality_decision")
        required = bool(
            override.get(
                "quality_review_required",
                self._execution_required(request)
                or request.target_module == "output_quality_reviewer",
            )
        )
        plan_id = _text(
            override.get("quality_plan_id")
            or request.quality_plan_id
            or getattr(plan, "quality_preservation_plan_id", ""),
            maximum=180,
        )
        non_negotiable = _unique(
            _items(override.get("non_negotiable_requirements"))
            or getattr(plan, "non_negotiable_requirements", []),
            limit=64,
        )
        acceptable = _unique(
            _items(override.get("acceptable_disclosed_degradations"))
            or getattr(plan, "acceptable_degradations", []),
            limit=64,
        )
        unacceptable = _unique(
            _items(override.get("unacceptable_degradations"))
            or getattr(plan, "unacceptable_degradations", []),
            limit=64,
        )
        baseline_required = bool(
            override.get(
                "baseline_required",
                bool(getattr(plan, "comparison_metrics", [])),
            )
        )
        baseline_available = bool(
            override.get(
                "baseline_available",
                getattr(output_decision, "baseline_equivalent", None) is not None,
            )
        )
        decision_id = _text(
            override.get("output_quality_decision_id")
            or getattr(output_decision, "acceptance_decision_id", ""),
            maximum=180,
        )
        non_negotiable_regression = bool(
            override.get("non_negotiable_regression_present")
            or any(
                getattr(item, "non_negotiable", False)
                and getattr(item, "acceptance_impact", "") == "blocks_acceptance"
                for item in getattr(context.get("quality_report"), "quality_regressions", [])
            )
        )
        silent_reduction = bool(
            override.get("silent_quality_reduction_detected")
            or any(
                item
                in {
                    "hidden_quality_reduction",
                }
                for item in (
                    warning.partition(":")[2]
                    for warning in request.warnings
                    if warning.startswith("prohibited-signal:")
                )
            )
        )
        disclosed = bool(override.get("disclosed_minor_degradation"))
        human_incomplete = bool(
            override.get("human_quality_review_incomplete")
            or (
                getattr(output_decision, "human_review_required", False)
                and getattr(output_decision, "decision", "")
                == "accepted_with_disclosed_limitations"
            )
        )
        requirements_match = bool(
            override.get(
                "quality_requirements_match_request",
                not required
                or bool(plan_id and plan_id == request.quality_plan_id),
            )
        )
        failures: list[str] = []
        if required and not plan_id:
            failures.append("A required quality-preservation plan is missing.")
        if baseline_required and not baseline_available:
            failures.append("The required quality baseline is unavailable.")
        if non_negotiable_regression:
            failures.append("A non-negotiable quality regression is present.")
        if silent_reduction:
            failures.append("A silent quality reduction was detected.")
        if required and not requirements_match:
            failures.append("Quality requirements changed after the request.")
        blocking_failures = list(failures)
        if human_incomplete:
            failures.append("Required human quality review is incomplete.")
        clear = not failures
        return BobaSafetyQualityReviewV1(
            quality_review_id=_stable_id(
                "safety_quality_review",
                case_id,
                plan_id,
                decision_id,
                failures,
            ),
            safety_case_id=case_id,
            quality_plan_id=plan_id,
            output_quality_decision_id=decision_id,
            non_negotiable_requirements=non_negotiable,
            acceptable_disclosed_degradations=acceptable,
            unacceptable_degradations=unacceptable,
            baseline_required=baseline_required,
            baseline_available=baseline_available,
            quality_review_required=required,
            human_quality_review_required=human_incomplete or disclosed,
            non_negotiable_regression_present=non_negotiable_regression,
            silent_quality_reduction_detected=silent_reduction,
            quality_requirements_match_request=requirements_match,
            quality_clear_for_requested_action=clear,
            failure_reasons=_unique(failures, limit=64),
            warnings=[
                "Technical completion and fallback success do not prove output quality.",
                *(
                    ["Disclosed degradation remains scoped to explicit human review."]
                    if disclosed
                    else []
                ),
                *(
                    ["Quality failures block allowance."]
                    if blocking_failures
                    else []
                ),
            ],
        )

    def _budget_state(
        self,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
    ) -> tuple[bool, str, list[str], str]:
        override = _mapping(context.get("budget_review"))
        budget = context.get("budget")
        usage = context.get("budget_usage")
        current_digest = _digest(
            {
                "budget": _mapping(budget),
                "usage": _mapping(usage),
                "override": override,
            }
        )
        failures = _unique(_items(override.get("failure_reasons")), limit=64)
        exhausted = bool(
            override.get("budget_exhausted")
            or getattr(usage, "budget_exhausted", False)
        )
        if exhausted:
            failures.append("The project-wide recovery budget is exhausted.")
        if self._execution_required(request) and budget is None and not override:
            failures.append("Execution budget evidence is unavailable.")
        if request.retry_budget_digest and request.retry_budget_digest != current_digest:
            failures.append("The approved retry-budget state changed.")
        maximum_time = int(
            override.get(
                "maximum_time_seconds",
                getattr(budget, "maximum_execution_duration_seconds", 0),
            )
            or 0
        )
        if (
            self._execution_required(request)
            and request.time_budget_seconds
            and maximum_time
            and request.time_budget_seconds > maximum_time
        ):
            failures.append("The requested time budget exceeds the hard policy.")
        if request.target_operation == "budget_reset":
            history_preserved = bool(override.get("history_preserved", True))
            loop_blocked = bool(override.get("loop_blocked", False))
            if not bool(override.get("near_or_exhausted", exhausted)):
                failures.append("Budget reset is not justified by bounded usage.")
            if not history_preserved:
                failures.append("Budget reset would erase prior usage history.")
            if loop_blocked:
                failures.append("Budget reset cannot bypass a detected recovery loop.")
        return not failures, current_digest, _unique(failures, limit=64), (
            "available" if not failures else "blocked"
        )

    def _risk_assessment(
        self,
        case_id: str,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
        *,
        approval: BobaSafetyApprovalReviewV1,
        rights: BobaSafetyRightsReviewV1,
        checkpoint: BobaSafetyCheckpointReviewV1,
        validation: BobaSafetyValidationReadinessV1,
        quality: BobaSafetyQualityReviewV1,
        budget_ok: bool,
        prohibited_signals: Sequence[str],
    ) -> BobaSafetyRiskAssessmentV1:
        override = _mapping(context.get("risk_assessment"))
        factors: list[BobaSafetyRiskFactorV1] = []
        score = (
            8.0
            if request.action_class == "automatic_read_only"
            else 15.0
            if request.action_class == "approval_required_read_only"
            else 35.0
        )

        def add(
            category: BobaSafetyRiskCategoryV1,
            title: str,
            points: float,
            *,
            blocking: bool = False,
            human: bool = False,
            severity: BobaSafetyRiskSeverityV1 = "medium",
            mitigation: str = "",
        ) -> None:
            nonlocal score
            score += points
            factors.append(
                BobaSafetyRiskFactorV1(
                    risk_factor_id=_stable_id(
                        "safety_risk_factor",
                        case_id,
                        category,
                        title,
                    ),
                    safety_case_id=case_id,
                    category=category,
                    title=title,
                    summary=f"{title} contributes bounded policy risk.",
                    severity=severity,
                    likelihood="possible",
                    confidence=0.78,
                    mitigations=[mitigation] if mitigation else [],
                    residual_risk="Safety Gate does not describe this score as certainty.",
                    blocking=blocking,
                    human_review_required=human,
                )
            )

        if request.target_module == "code_surgeon" and self._execution_required(request):
            add(
                "code_change",
                "Isolated code change",
                10.0,
                mitigation="Protected branches and exact patch binding remain enforced.",
            )
        if request.target_module == "tool_recovery_brain" and self._execution_required(request):
            add(
                "environment",
                "Local recovery execution",
                12.0,
                mitigation="The exact tool, strategy, retry, and time budget are bounded.",
            )
        if checkpoint.checkpoint_required:
            add(
                "checkpoint",
                "Checkpoint-dependent action",
                8.0 if checkpoint.blocks_action else 2.0,
                blocking=checkpoint.blocks_action,
                mitigation="Checkpoint and rollback evidence were evaluated.",
            )
        if not checkpoint.source_media_protected:
            add(
                "source_data",
                "Source media protection is not confirmed",
                45.0,
                blocking=True,
                severity="critical",
            )
        if not checkpoint.accepted_outputs_protected:
            add(
                "accepted_output",
                "Accepted-output protection is not confirmed",
                45.0,
                blocking=True,
                severity="critical",
            )
        if not rights.rights_clear_for_requested_internal_action:
            add(
                "rights",
                "Rights uncertainty or block",
                35.0,
                blocking=rights.blocked_rights_present,
                human=True,
                severity="high",
            )
        if not approval.exact_binding_valid:
            add(
                "approval_mismatch",
                "Exact approval mismatch",
                30.0,
                blocking=True,
                severity="high",
            )
        if not validation.validation_ready:
            add(
                "validation",
                "Validation readiness incomplete",
                25.0,
                blocking=True,
                severity="high",
            )
        if not quality.quality_clear_for_requested_action:
            add(
                "quality",
                "Quality-preservation requirements incomplete",
                25.0,
                blocking=bool(
                    quality.non_negotiable_regression_present
                    or quality.silent_quality_reduction_detected
                ),
                human=quality.human_quality_review_required,
                severity="high",
            )
        elif quality.human_quality_review_required:
            add(
                "quality",
                "Disclosed quality limitation needs human review",
                12.0,
                human=True,
                severity="medium",
            )
        if not budget_ok:
            add(
                "retry_loop",
                "Recovery budget block",
                20.0,
                blocking=True,
                severity="high",
            )
        if context.get("conflicting_state"):
            add(
                "project_concurrency",
                "Conflicting project state",
                35.0,
                blocking=True,
                severity="high",
            )
        if not context.get("snapshot_current", False):
            add(
                "stale_state",
                "Stale project snapshot",
                40.0,
                blocking=True,
                severity="high",
            )
        for signal in prohibited_signals:
            category: BobaSafetyRiskCategoryV1 = (
                "secret_exposure"
                if signal == "secret_exposure"
                else "publication"
                if "publication" in signal or "upload" in signal
                else "deployment"
                if "deployment" in signal or "merge" in signal
                else "destructive_action"
            )
            add(
                category,
                f"Absolute prohibition: {signal}",
                100.0,
                blocking=True,
                severity="blocked",
            )
        if approval.exact_binding_valid and self._execution_required(request):
            score -= 8.0
        if checkpoint.checkpoint_required and not checkpoint.blocks_action:
            score -= 6.0
        if validation.validation_ready:
            score -= 5.0
        if quality.quality_clear_for_requested_action:
            score -= 4.0
        if (
            checkpoint.source_media_protected
            and checkpoint.accepted_outputs_protected
        ):
            score -= 4.0
        if override.get("score") is not None:
            score = float(override["score"])
        score = max(0.0, min(100.0, round(score, 2)))
        blocked = any(item.blocking and item.severity == "blocked" for item in factors)
        critical = score >= 81.0 and not blocked
        level: BobaSafetyOverallRiskV1 = (
            "blocked"
            if blocked
            else "critical"
            if critical
            else "high"
            if score > 60
            else "medium"
            if score > 35
            else "low"
            if score > 15
            else "minimal"
        )
        threshold = float(
            context.get(
                "risk_threshold",
                25.0
                if request.action_class == "automatic_read_only"
                else 60.0,
            )
        )
        human = bool(
            override.get(
                "human_review_required",
                level == "high" or any(item.human_review_required for item in factors),
            )
        )
        return BobaSafetyRiskAssessmentV1(
            risk_assessment_id=_stable_id(
                "safety_risk_assessment",
                case_id,
                score,
                [item.risk_factor_id for item in factors],
            ),
            safety_case_id=case_id,
            risk_factors=factors,
            overall_risk_level=level,
            overall_risk_score=score,
            risk_threshold=max(0.0, min(100.0, threshold)),
            risk_within_threshold=score <= threshold and not blocked,
            critical_risk_present=critical,
            blocked_risk_present=blocked,
            mitigations_complete=all(not item.blocking for item in factors),
            residual_risks=_unique(
                [item.title for item in factors if not item.blocking],
                limit=64,
            ),
            human_review_required=human,
            failure_reasons=_unique(
                [
                    item.title
                    for item in factors
                    if item.blocking or item.human_review_required
                ],
                limit=64,
            ),
            warnings=["Risk scoring is deterministic policy guidance, not certainty."],
        )

    def _append_unique(
        self,
        collection: list[_StoredSafetyRecordT],
        item: _StoredSafetyRecordT,
        key: str,
    ) -> _StoredSafetyRecordT:
        identity = getattr(item, key)
        existing = next(
            (candidate for candidate in collection if getattr(candidate, key) == identity),
            None,
        )
        if existing is not None:
            return existing
        collection.append(item)
        return item

    def _evidence(
        self,
        gate: BobaSafetyGateSetV1,
        case_id: str,
        *,
        source_module: str,
        source_record_id: str,
        category: BobaSafetyEvidenceCategoryV1,
        summary: str,
        observed: Any,
        expected: Any,
        passed: bool,
        stale: bool = False,
        human: bool = False,
    ) -> BobaSafetyEvidenceV1:
        safe_observed = sanitize_safety_export(observed)
        safe_expected = sanitize_safety_export(expected)
        evidence = BobaSafetyEvidenceV1(
            evidence_id=_stable_id(
                "safety_evidence",
                case_id,
                category,
                source_record_id,
                safe_observed,
                safe_expected,
            ),
            safety_case_id=case_id,
            source_module=source_module,
            source_record_id=_text(source_record_id, maximum=180),
            category=category,
            bounded_summary=_text(summary, maximum=900),
            observed_value=safe_observed,
            expected_value=safe_expected,
            reliability="high" if not stale else "conflicting",
            confidence=0.9 if not stale else 0.45,
            supports_allowance=passed,
            supports_denial=not passed,
            requires_human_interpretation=human,
            stale=stale,
        )
        return self._append_unique(gate.evidence_records, evidence, "evidence_id")

    def _constraint(
        self,
        gate: BobaSafetyGateSetV1,
        case_id: str,
        *,
        constraint_type: BobaSafetyConstraintTypeV1,
        name: str,
        passed: bool,
        evidence: BobaSafetyEvidenceV1,
        required: bool = True,
        status: BobaSafetyConstraintStatusV1 | None = None,
        reason: str = "",
        human: bool = False,
    ) -> BobaSafetyConstraintCheckV1:
        effective_status: BobaSafetyConstraintStatusV1 = (
            status
            if status is not None
            else "passed"
            if passed
            else "failed"
        )
        check = BobaSafetyConstraintCheckV1(
            constraint_check_id=_stable_id(
                "safety_constraint",
                case_id,
                constraint_type,
                name,
                effective_status,
            ),
            safety_case_id=case_id,
            constraint_type=constraint_type,
            name=name,
            required=required,
            status=effective_status,
            observed_value=evidence.observed_value,
            expected_value=evidence.expected_value,
            evidence_ids=[evidence.evidence_id],
            blocks_allowance=required and not passed,
            failure_reason=_text(reason, maximum=900) if not passed else "",
            human_review_required=human,
        )
        return self._append_unique(gate.constraint_checks, check, "constraint_check_id")

    def _decision_value(
        self,
        request: BobaSafetyActionRequestV1,
        context: Mapping[str, Any],
        *,
        approval: BobaSafetyApprovalReviewV1,
        rights: BobaSafetyRightsReviewV1,
        checkpoint: BobaSafetyCheckpointReviewV1,
        validation: BobaSafetyValidationReadinessV1,
        quality: BobaSafetyQualityReviewV1,
        budget_ok: bool,
        risk: BobaSafetyRiskAssessmentV1,
        prohibited_signals: Sequence[str],
        future_signals: Sequence[str],
    ) -> BobaSafetyDecisionValueV1:
        if prohibited_signals or request.action_class == "prohibited":
            return "denied"
        if future_signals or request.action_class == "future_gated":
            return "unsupported_future_action"
        if not context.get("snapshot_current", False) or context.get("conflicting_state"):
            return "blocked_stale_state"
        safety_status = _text(context.get("safety_status"), maximum=80).casefold()
        if safety_status in _SAFETY_BLOCKED:
            return "blocked_safety_policy"
        if not rights.rights_clear_for_requested_internal_action:
            return "blocked_rights"
        if not approval.exact_binding_valid:
            return "denied"
        if checkpoint.blocks_action:
            return "blocked_checkpoint"
        if not validation.validation_ready:
            return "blocked_validation"
        if not quality.quality_clear_for_requested_action:
            return (
                "human_review_required"
                if quality.human_quality_review_required
                and not quality.non_negotiable_regression_present
                and not quality.silent_quality_reduction_detected
                else "blocked_quality"
            )
        if quality.human_quality_review_required:
            return "human_review_required"
        if not budget_ok:
            return "blocked_budget"
        if risk.blocked_risk_present or risk.critical_risk_present:
            return "denied"
        if risk.human_review_required or not risk.risk_within_threshold:
            return "human_review_required"
        if request.action_class == "automatic_read_only":
            return "allowed_for_internal_read_only"
        if request.action_class == "approval_required_read_only":
            return "allowed_for_internal_read_only"
        if request.action_class == "approval_required_execution":
            return "allowed_for_exact_internal_execution"
        return "invalid_request"

    @staticmethod
    def _decision_summary(
        decision: BobaSafetyDecisionValueV1,
        request: BobaSafetyActionRequestV1,
        reasons: Sequence[str],
    ) -> str:
        if decision == "allowed_for_internal_read_only":
            return (
                "BOBA checked this exact local read-only action and found its "
                "bounded project, policy, rights, and protection controls ready. "
                "Safety Gate did not execute it."
            )
        if decision == "allowed_for_exact_internal_execution":
            return (
                "BOBA checked the exact plan, approval, project snapshot, checkpoint, "
                "rollback, validation, quality, and budget evidence. This one internal "
                f"{request.target_module} action may be revalidated by the target module."
            )
        if decision == "unsupported_future_action":
            return (
                "Safety Gate V1 cannot authorize this future action. It prepared a "
                "bounded handoff and did not resume, upload, publish, merge, or deploy."
            )
        if decision == "expired":
            return (
                "This safety decision expired before execution. BOBA must evaluate "
                "the current project state again."
            )
        reason = _text("; ".join(reasons), maximum=650)
        fallback_reason = "required safety evidence is incomplete"
        return (
            f"BOBA blocked or paused this exact action because "
            f"{reason or fallback_reason}. Nothing was executed."
        )

    def _build_handoffs(
        self,
        gate: BobaSafetyGateSetV1,
        case: BobaSafetyEvaluationCaseV1,
        decision: BobaSafetyDecisionV1,
        checks: Sequence[BobaSafetyConstraintCheckV1],
    ) -> None:
        mapping: dict[BobaSafetyDecisionValueV1, list[BobaSafetyHandoffTargetV1]] = {
            "allowed_for_internal_read_only": ["autopilot_controller", "live_companion"],
            "allowed_for_exact_internal_execution": [
                "autopilot_controller",
                "live_companion",
            ],
            "blocked_rights": ["rights_permission_gate", "human_operator"],
            "blocked_checkpoint": ["checkpoint_recovery_manager", "human_operator"],
            "blocked_validation": ["validator_runner", "human_operator"],
            "blocked_quality": [
                "output_quality_reviewer",
                "repair_planner",
                "human_operator",
            ],
            "blocked_stale_state": ["root_cause_analyzer", "human_operator"],
            "blocked_budget": ["repair_planner", "human_operator"],
            "human_review_required": ["human_operator"],
            "more_evidence_required": ["root_cause_analyzer", "human_operator"],
            "unsupported_future_action": [
                "workflow_controller",
                "final_decision_bus",
                "human_operator",
            ],
            "denied": ["repair_planner", "human_operator"],
            "blocked_safety_policy": ["human_operator"],
            "invalid_request": ["human_operator"],
            "expired": ["autopilot_controller", "human_operator"],
            "unknown": ["human_operator"],
        }
        passed = [item.name for item in checks if item.status == "passed"]
        failed = [
            item.failure_reason or item.name
            for item in checks
            if item.status not in {"passed", "not_required"}
        ]
        for target in mapping.get(decision.decision, ["human_operator"]):
            handoff = BobaSafetyHandoffV1(
                handoff_id=_stable_id(
                    "safety_handoff",
                    case.safety_case_id,
                    decision.safety_decision_id,
                    target,
                ),
                safety_case_id=case.safety_case_id,
                safety_decision_id=decision.safety_decision_id,
                target_module=target,
                reason=decision.decision_summary,
                required_inputs=[
                    "Exact Safety Gate decision",
                    "Current request and project snapshot digests",
                    "Current target-module approval where required",
                ],
                satisfied_conditions=_unique(passed, limit=64),
                failed_conditions=_unique(failed, limit=64),
                unresolved_questions=(
                    decision.unmet_conditions
                    if decision.human_review_required
                    else []
                ),
                constraints=[
                    "Target module must independently revalidate.",
                    (
                        "Workflow resume, upload, publication, push, merge, "
                        "and deployment remain unauthorized."
                    ),
                ],
                prohibited_actions=list(_ABSOLUTE_PROHIBITIONS),
                apply_automatically=bool(
                    target == "autopilot_controller"
                    and decision.decision == "allowed_for_internal_read_only"
                ),
                human_approval_required=not bool(
                    target == "autopilot_controller"
                    and decision.decision == "allowed_for_internal_read_only"
                ),
                priority=(
                    "critical"
                    if decision.decision
                    in {
                        "denied",
                        "blocked_rights",
                        "blocked_safety_policy",
                    }
                    else "high"
                ),
                warnings=["Handoffs do not execute their target action."],
            )
            self._append_unique(gate.handoffs, handoff, "handoff_id")

    def evaluate_action(
        self,
        project_id: str,
        action_request_id: str,
        *,
        approval_record: Mapping[str, Any] | BobaContract | None = None,
    ) -> BobaSafetyDecisionV1:
        gate = self._gate(project_id)
        request = self._request(gate, action_request_id)
        if request.project_id != project_id:
            raise ValidationError("Safety Gate request belongs to another project.")
        calculated_request_digest = calculate_safety_request_digest(
            request.model_dump(mode="json")
        )
        if calculated_request_digest != request.request_digest:
            raise ValidationError("Safety Gate request digest is invalid.")
        context = self._context(
            project_id,
            request,
            approval_record=approval_record,
        )
        threshold_key = (
            "automatic_read_only"
            if request.action_class == "automatic_read_only"
            else "approved_internal_execution"
        )
        context.setdefault(
            "risk_threshold",
            gate.policy_snapshot.risk_thresholds.get(threshold_key, 0.0),
        )
        context_digest = _digest(
            {
                "request": request.request_digest,
                "policy": gate.policy_snapshot.policy_sha256,
                "snapshot_current": context.get("snapshot_current"),
                "rights": context.get("rights_status"),
                "safety": context.get("safety_status"),
                "approval": _approval_fingerprint(
                    context.get("approval")
                    if isinstance(context.get("approval"), Mapping | BobaContract)
                    else None
                ),
                "checkpoint": sanitize_safety_export(
                    context.get("checkpoint_review")
                    or _mapping(context.get("checkpoint"))
                ),
                "validation": sanitize_safety_export(
                    context.get("validation_review")
                    or _mapping(context.get("validation_plan"))
                ),
                "quality": sanitize_safety_export(
                    context.get("quality_review")
                    or _mapping(context.get("quality_plan"))
                ),
                "budget": sanitize_safety_export(
                    context.get("budget_review")
                    or {
                        "budget": _mapping(context.get("budget")),
                        "usage": _mapping(context.get("budget_usage")),
                    }
                ),
            }
        )
        case_id = _stable_id(
            "safety_case",
            project_id,
            request.request_digest,
            gate.policy_snapshot.policy_sha256,
            context_digest,
        )
        existing_case = next(
            (
                item
                for item in gate.evaluation_cases
                if item.safety_case_id == case_id
            ),
            None,
        )
        if existing_case is not None and existing_case.safety_decision_id:
            existing_decision = next(
                (
                    item
                    for item in gate.safety_decisions
                    if item.safety_decision_id == existing_case.safety_decision_id
                ),
                None,
            )
            if (
                existing_decision is not None
                and existing_decision.decision_valid
                and not decision_is_expired(existing_decision)
                and not any(
                    item.safety_decision_id == existing_decision.safety_decision_id
                    for item in gate.decision_invalidations
                )
            ):
                return existing_decision
        case = BobaSafetyEvaluationCaseV1(
            safety_case_id=case_id,
            project_id=project_id,
            autopilot_run_id=request.autopilot_run_id,
            action_request_id=request.action_request_id,
            title=f"Safety review for {request.target_module}.{request.target_operation}",
            target_module=request.target_module,
            target_operation=request.target_operation,
            action_class=request.action_class,
            evaluation_status="evaluating",
            project_snapshot_id=request.project_snapshot_id,
            project_snapshot_digest=request.project_snapshot_digest,
            policy_snapshot_id=gate.policy_snapshot.policy_snapshot_id,
            limitations=["Safety Gate evaluates this action and executes nothing."],
        )
        case = self._append_unique(gate.evaluation_cases, case, "safety_case_id")
        approval = self._approval_review(case_id, request, context)
        rights = self._rights_review(case_id, request, context)
        checkpoint = self._checkpoint_review(case_id, request, context)
        validation = self._validation_review(case_id, request, context)
        quality = self._quality_review(case_id, request, context)
        budget_ok, budget_digest, budget_failures, budget_status = self._budget_state(
            request,
            context,
        )
        prohibited_signals = [
            item.partition(":")[2]
            for item in request.warnings
            if item.startswith("prohibited-signal:")
        ]
        future_signals = [
            item.partition(":")[2]
            for item in request.warnings
            if item.startswith("future-signal:")
        ]
        risk = self._risk_assessment(
            case_id,
            request,
            context,
            approval=approval,
            rights=rights,
            checkpoint=checkpoint,
            validation=validation,
            quality=quality,
            budget_ok=budget_ok,
            prohibited_signals=prohibited_signals,
        )
        self._append_unique(
            gate.approval_reviews,
            approval,
            "approval_review_id",
        )
        self._append_unique(gate.rights_reviews, rights, "rights_review_id")
        self._append_unique(
            gate.checkpoint_reviews,
            checkpoint,
            "checkpoint_review_id",
        )
        self._append_unique(
            gate.validation_reviews,
            validation,
            "validation_review_id",
        )
        self._append_unique(gate.quality_reviews, quality, "quality_review_id")
        self._append_unique(gate.risk_assessments, risk, "risk_assessment_id")
        case.approval_review_id = approval.approval_review_id
        case.rights_review_id = rights.rights_review_id
        case.checkpoint_review_id = checkpoint.checkpoint_review_id
        case.validation_review_id = validation.validation_review_id
        case.quality_review_id = quality.quality_review_id
        case.risk_assessment_id = risk.risk_assessment_id
        checks: list[BobaSafetyConstraintCheckV1] = []

        def evidence_check(
            constraint_type: BobaSafetyConstraintTypeV1,
            category: BobaSafetyEvidenceCategoryV1,
            name: str,
            passed: bool,
            observed: Any,
            expected: Any,
            reason: str,
            *,
            required: bool = True,
            stale: bool = False,
            human: bool = False,
            source_module: str = "safety_gate",
            source_record_id: str = "",
        ) -> None:
            evidence = self._evidence(
                gate,
                case_id,
                source_module=source_module,
                source_record_id=source_record_id,
                category=category,
                summary=name,
                observed=observed,
                expected=expected,
                passed=passed,
                stale=stale,
                human=human,
            )
            checks.append(
                self._constraint(
                    gate,
                    case_id,
                    constraint_type=constraint_type,
                    name=name,
                    passed=passed,
                    evidence=evidence,
                    required=required,
                    status=(
                        "stale"
                        if stale
                        else "not_required"
                        if not required
                        else None
                    ),
                    reason=reason,
                    human=human,
                )
            )

        registry = build_safety_module_operation_registry()
        evidence_check(
            "project_scope",
            "artifact_integrity",
            "Request belongs to the exact project",
            request.project_id == project_id,
            request.project_id,
            project_id,
            "Project mismatch.",
        )
        evidence_check(
            "registered_module",
            "module_health",
            "Target module is registered",
            request.target_module in registry,
            request.target_module,
            sorted(registry),
            "Unknown target module.",
        )
        evidence_check(
            "registered_operation",
            "module_health",
            "Target operation is registered",
            request.target_operation in registry.get(request.target_module, {}),
            request.target_operation,
            sorted(registry.get(request.target_module, {})),
            "Unknown target operation.",
        )
        evidence_check(
            "request_digest",
            "artifact_integrity",
            "Request digest matches",
            calculate_safety_request_digest(request.model_dump(mode="json"))
            == request.request_digest,
            request.request_digest,
            "current deterministic digest",
            "Request digest mismatch.",
        )
        evidence_check(
            "project_snapshot",
            "project_snapshot",
            "Project snapshot is current",
            bool(context.get("snapshot_current")),
            request.project_snapshot_digest,
            request.project_snapshot_digest,
            "Project snapshot is missing, stale, or conflicting.",
            stale=not bool(context.get("snapshot_current")),
            source_module="autopilot_controller",
            source_record_id=request.project_snapshot_id,
        )
        evidence_check(
            "rights",
            "rights_permission",
            "Rights permit the requested internal action",
            rights.rights_clear_for_requested_internal_action,
            rights.rights_status,
            "clear for this exact internal scope",
            "; ".join(rights.failure_reasons),
            human=rights.human_rights_review_required,
            source_module="rights_permission_gate",
            source_record_id=rights.rights_gate_record_id,
        )
        evidence_check(
            "human_approval",
            "target_approval",
            "Exact target-module approval is valid",
            approval.exact_binding_valid,
            approval.approval_record_id,
            request.approval_record_id or "not required",
            "; ".join(approval.failure_reasons),
            required=request.action_class
            in {"approval_required_read_only", "approval_required_execution"},
            source_module=request.target_module,
            source_record_id=approval.approval_record_id,
        )
        evidence_check(
            "checkpoint",
            "checkpoint",
            "Checkpoint requirements are ready",
            not checkpoint.blocks_action,
            checkpoint.checkpoint_status,
            "valid or not required",
            "; ".join(checkpoint.failure_reasons),
            required=checkpoint.checkpoint_required,
            source_record_id=checkpoint.checkpoint_reference,
        )
        evidence_check(
            "rollback",
            "rollback",
            "Rollback requirements are ready",
            checkpoint.rollback_ready,
            checkpoint.rollback_ready,
            True,
            "; ".join(checkpoint.failure_reasons),
            required=checkpoint.checkpoint_required,
            source_module=request.target_module,
            source_record_id=request.rollback_plan_id,
        )
        evidence_check(
            "validation",
            "validation",
            "Validation readiness is complete",
            validation.validation_ready,
            validation.available_validators,
            validation.required_validators,
            "; ".join(validation.failure_reasons),
            required=validation.validation_runner_required,
            source_module="repair_planner",
            source_record_id=validation.validation_plan_id,
        )
        evidence_check(
            "quality",
            "output_quality",
            "Quality-preservation requirements are ready",
            quality.quality_clear_for_requested_action,
            quality.output_quality_decision_id or quality.quality_plan_id,
            request.quality_plan_id or "not required",
            "; ".join(quality.failure_reasons),
            required=quality.quality_review_required,
            human=quality.human_quality_review_required,
            source_module="output_quality_reviewer",
            source_record_id=quality.output_quality_decision_id,
        )
        evidence_check(
            "budget",
            "recovery_budget",
            "Recovery budget remains within policy",
            budget_ok,
            budget_status,
            "available",
            "; ".join(budget_failures),
            source_module="autopilot_controller",
            source_record_id=budget_digest,
        )
        evidence_check(
            "source_media_protection",
            "source_media_protection",
            "Source media remains protected",
            checkpoint.source_media_protected,
            checkpoint.source_media_protected,
            True,
            "Source media protection failed.",
        )
        evidence_check(
            "accepted_output_protection",
            "accepted_output_protection",
            "Accepted outputs remain protected",
            checkpoint.accepted_outputs_protected,
            checkpoint.accepted_outputs_protected,
            True,
            "Accepted-output protection failed.",
        )
        evidence_check(
            "destructive_action",
            "command_policy",
            "No absolute prohibition is requested",
            not prohibited_signals,
            prohibited_signals,
            [],
            f"Absolute prohibitions: {', '.join(prohibited_signals)}.",
        )
        evidence_check(
            "workflow_resume",
            "command_policy",
            "No unsupported future authority is requested",
            not future_signals,
            future_signals,
            [],
            f"Future-gated actions: {', '.join(future_signals)}.",
            required=not future_signals,
        )
        case.constraint_check_ids = [item.constraint_check_id for item in checks]
        decision_value = self._decision_value(
            request,
            context,
            approval=approval,
            rights=rights,
            checkpoint=checkpoint,
            validation=validation,
            quality=quality,
            budget_ok=budget_ok,
            risk=risk,
            prohibited_signals=prohibited_signals,
            future_signals=future_signals,
        )
        unmet = _unique(
            [
                item.failure_reason or item.name
                for item in checks
                if item.status not in {"passed", "not_required"}
            ],
            limit=64,
        )
        conditions = _unique(
            [item.name for item in checks if item.status == "passed"],
            limit=64,
        )
        ttl_key = (
            "read_only_allowance"
            if decision_value == "allowed_for_internal_read_only"
            else "execution_allowance"
            if decision_value == "allowed_for_exact_internal_execution"
            else "human_review"
        )
        ttl = gate.policy_snapshot.decision_ttl_seconds[ttl_key]
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(seconds=ttl)
        decision_payload = {
            "safety_case_id": case_id,
            "action_request_id": request.action_request_id,
            "project_id": project_id,
            "autopilot_run_id": request.autopilot_run_id,
            "decision": decision_value,
            "allowed_action_class": (
                request.action_class
                if decision_value
                in {
                    "allowed_for_internal_read_only",
                    "allowed_for_exact_internal_execution",
                }
                else ""
            ),
            "allowed_target_module": (
                request.target_module
                if decision_value
                in {
                    "allowed_for_internal_read_only",
                    "allowed_for_exact_internal_execution",
                }
                else ""
            ),
            "allowed_target_operation": (
                request.target_operation
                if decision_value
                in {
                    "allowed_for_internal_read_only",
                    "allowed_for_exact_internal_execution",
                }
                else ""
            ),
            "allowed_scope": _unique(
                [
                    request.plan_id,
                    request.strategy_id,
                    request.patch_proposal_id,
                    request.tool_id,
                    request.capability_id,
                ],
                limit=64,
                maximum=180,
            ),
            "project_snapshot_digest": request.project_snapshot_digest,
            "request_digest": request.request_digest,
            "policy_snapshot_digest": gate.policy_snapshot.policy_sha256,
            "approval_record_id": approval.approval_record_id,
            "decision_created_at": created_at.isoformat(),
            "decision_expires_at": expires_at.isoformat(),
            "decision_expired": False,
            "decision_valid": decision_value
            in {
                "allowed_for_internal_read_only",
                "allowed_for_exact_internal_execution",
            },
            "conditions": conditions,
            "unmet_conditions": unmet,
            "denial_reasons": unmet,
            "human_review_required": decision_value == "human_review_required",
            "target_module_revalidation_required": True,
            "confidence": max(
                0.0,
                min(
                    1.0,
                    round(
                        0.96
                        - 0.07 * len(unmet)
                        - 0.15 * int(risk.overall_risk_level == "unknown"),
                        3,
                    ),
                ),
            ),
        }
        decision_digest = calculate_safety_decision_digest(decision_payload)
        decision = BobaSafetyDecisionV1(
            safety_decision_id=f"safety_decision_{decision_digest[:24]}",
            **decision_payload,
            decision_summary=self._decision_summary(
                decision_value,
                request,
                unmet or risk.failure_reasons,
            ),
            warnings=[
                "Safety Gate evaluated this action and executed nothing.",
                "Changing any bound evidence invalidates an allowance.",
            ],
            limitations=[
                "An allowance does not guarantee repair success or output quality.",
                "No legal or copyright certainty is asserted.",
            ],
        )
        decision = self._append_unique(
            gate.safety_decisions,
            decision,
            "safety_decision_id",
        )
        case.safety_decision_id = decision.safety_decision_id
        case.human_review_required = decision.human_review_required
        case.confidence = decision.confidence
        case.evaluation_status = (
            "completed"
            if decision.decision
            in {
                "allowed_for_internal_read_only",
                "allowed_for_exact_internal_execution",
            }
            else "awaiting_human_review"
            if decision.decision == "human_review_required"
            else "awaiting_evidence"
            if decision.decision == "more_evidence_required"
            else "blocked"
        )
        self._build_handoffs(gate, case, decision, checks)
        gate.signal_usage.autopilot_controller_used = bool(context.get("controller"))
        gate.signal_usage.autopilot_artifact_read = bool(context.get("controller"))
        gate.signal_usage.rights_gate_used = bool(context.get("rights_gate"))
        gate.signal_usage.rights_artifact_read = bool(context.get("rights_gate"))
        gate.signal_usage.repair_planner_used = bool(
            context.get("validation_plan")
            or context.get("quality_plan")
            or context.get("rollback_plan")
        )
        gate.signal_usage.code_surgeon_used = request.target_module == "code_surgeon"
        gate.signal_usage.tool_recovery_used = (
            request.target_module == "tool_recovery_brain"
        )
        gate.signal_usage.output_quality_reviewer_used = bool(
            context.get("quality_report")
            or request.target_module == "output_quality_reviewer"
        )
        gate.signal_usage.project_snapshot_used = True
        gate.signal_usage.target_module_approval_used = approval.approval_found
        gate.signal_usage.checkpoint_reference_used = bool(
            checkpoint.checkpoint_reference
        )
        gate.signal_usage.rollback_plan_used = checkpoint.rollback_plan_present
        gate.signal_usage.validation_plan_used = bool(validation.validation_plan_id)
        gate.signal_usage.quality_plan_used = bool(quality.quality_plan_id)
        gate.signal_usage.recovery_budget_used = bool(
            context.get("budget") or context.get("budget_review")
        )
        gate.signal_usage.policy_snapshot_used = True
        gate.signal_usage.decision_digest_used = True
        self._refresh_summary(gate)
        self.store.save_boba_safety_gate(gate)
        return decision

    def inspect_decision(
        self,
        project_id: str,
        decision_id: str,
    ) -> BobaSafetyDecisionV1:
        gate = self.store.load_boba_safety_gate(project_id)
        decision = (
            next(
                (
                    item
                    for item in gate.safety_decisions
                    if item.safety_decision_id == decision_id
                ),
                None,
            )
            if gate is not None
            else None
        )
        if decision is None:
            decision = self.store.load_boba_safety_decision(project_id, decision_id)
        if decision is None:
            raise ValidationError("BOBA Safety Gate decision was not found.")
        return decision

    def _append_invalidation(
        self,
        gate: BobaSafetyGateSetV1,
        decision: BobaSafetyDecisionV1,
        *,
        reason: str,
        current_request_digest: str = "",
        current_snapshot_digest: str = "",
        current_policy_digest: str = "",
        changes: Mapping[str, bool] | None = None,
    ) -> BobaSafetyDecisionInvalidationV1:
        flags = dict(changes or {})
        invalidation = BobaSafetyDecisionInvalidationV1(
            invalidation_id=_stable_id(
                "safety_invalidation",
                decision.safety_decision_id,
                reason,
                current_request_digest,
                current_snapshot_digest,
                current_policy_digest,
            ),
            safety_decision_id=decision.safety_decision_id,
            invalidation_reason=_text(reason, maximum=900),
            previous_request_digest=decision.request_digest,
            current_request_digest=current_request_digest or decision.request_digest,
            previous_snapshot_digest=decision.project_snapshot_digest,
            current_snapshot_digest=current_snapshot_digest
            or decision.project_snapshot_digest,
            previous_policy_digest=decision.policy_snapshot_digest,
            current_policy_digest=current_policy_digest
            or decision.policy_snapshot_digest,
            approval_changed=bool(flags.get("approval_changed")),
            plan_changed=bool(flags.get("plan_changed")),
            strategy_changed=bool(flags.get("strategy_changed")),
            patch_changed=bool(flags.get("patch_changed")),
            tool_changed=bool(flags.get("tool_changed")),
            configuration_changed=bool(flags.get("configuration_changed")),
            checkpoint_changed=bool(flags.get("checkpoint_changed")),
            validation_changed=bool(flags.get("validation_changed")),
            quality_requirements_changed=bool(
                flags.get("quality_requirements_changed")
            ),
            budget_changed=bool(flags.get("budget_changed")),
            rights_changed=bool(flags.get("rights_changed")),
            safety_state_changed=bool(flags.get("safety_state_changed")),
            decision_expired=bool(flags.get("decision_expired")),
            warnings=["The original immutable decision remains in audit history."],
        )
        return self._append_unique(
            gate.decision_invalidations,
            invalidation,
            "invalidation_id",
        )

    def invalidate_decision(
        self,
        project_id: str,
        decision_id: str,
        *,
        reason: str,
        changes: Mapping[str, bool] | None = None,
    ) -> BobaSafetyDecisionInvalidationV1:
        gate = self._gate(project_id)
        decision = self.inspect_decision(project_id, decision_id)
        invalidation = self._append_invalidation(
            gate,
            decision,
            reason=reason,
            changes=changes,
        )
        case = next(
            (
                item
                for item in gate.evaluation_cases
                if item.safety_case_id == decision.safety_case_id
            ),
            None,
        )
        if case is not None:
            case.evaluation_status = "invalidated"
        self._refresh_summary(gate)
        self.store.save_boba_safety_gate(gate)
        return invalidation

    def _invalid_decision(
        self,
        gate: BobaSafetyGateSetV1,
        decision: BobaSafetyDecisionV1,
        *,
        expired: bool,
        reasons: Sequence[str],
    ) -> BobaSafetyDecisionV1:
        value: BobaSafetyDecisionValueV1 = "expired" if expired else "blocked_stale_state"
        created = datetime.now(UTC)
        payload = {
            **decision.model_dump(mode="json"),
            "safety_decision_id": _stable_id(
                "safety_decision",
                decision.safety_decision_id,
                value,
                list(reasons),
            ),
            "decision": value,
            "decision_summary": self._decision_summary(
                value,
                self._request(gate, decision.action_request_id),
                reasons,
            ),
            "allowed_action_class": "",
            "allowed_target_module": "",
            "allowed_target_operation": "",
            "allowed_scope": [],
            "decision_created_at": created.isoformat(),
            "decision_expires_at": created.isoformat(),
            "decision_expired": expired,
            "decision_valid": False,
            "conditions": [],
            "unmet_conditions": _unique(reasons, limit=64),
            "denial_reasons": _unique(reasons, limit=64),
            "human_review_required": True,
            "confidence": 1.0,
        }
        return self._append_unique(
            gate.safety_decisions,
            BobaSafetyDecisionV1.model_validate(payload),
            "safety_decision_id",
        )

    def revalidate_decision(
        self,
        project_id: str,
        decision_id: str,
        *,
        approval_record: Mapping[str, Any] | BobaContract | None = None,
        current_bindings: Mapping[str, Any] | None = None,
    ) -> BobaSafetyDecisionV1:
        gate = self._gate(project_id)
        decision = self.inspect_decision(project_id, decision_id)
        if any(
            item.safety_decision_id == decision.safety_decision_id
            for item in gate.decision_invalidations
        ):
            return self._invalid_decision(
                gate,
                decision,
                expired=False,
                reasons=["The Safety Gate decision was previously invalidated."],
            )
        request = self._request(gate, decision.action_request_id)
        context = self._context(
            project_id,
            request,
            approval_record=approval_record,
        )
        current_approval_review = self._approval_review(
            decision.safety_case_id,
            request,
            context,
        )
        bindings = dict(current_bindings or {})
        current_snapshot = _text(
            bindings.get("project_snapshot_digest")
            or getattr(context.get("snapshot"), "snapshot_sha256", "")
            or request.project_snapshot_digest,
            maximum=64,
        )
        current_policy = _text(
            bindings.get("policy_snapshot_digest")
            or gate.policy_snapshot.policy_sha256,
            maximum=64,
        )
        current_request = _text(
            bindings.get("request_digest") or request.request_digest,
            maximum=64,
        )
        expired = decision_is_expired(decision)
        changes = {
            "approval_changed": bool(
                approval_record is not None
                and _approval_fingerprint(approval_record)
                != next(
                    (
                        item.current_parameters_digest
                        for item in gate.approval_reviews
                        if item.approval_review_id
                        == next(
                            (
                                case.approval_review_id
                                for case in gate.evaluation_cases
                                if case.safety_case_id == decision.safety_case_id
                            ),
                            "",
                        )
                    ),
                    _approval_fingerprint(approval_record),
                )
            ),
            "plan_changed": bool(
                bindings.get("plan_id")
                and bindings.get("plan_id") != request.plan_id
            ),
            "strategy_changed": bool(
                bindings.get("strategy_id")
                and bindings.get("strategy_id") != request.strategy_id
            ),
            "patch_changed": bool(
                bindings.get("patch_diff_sha256")
                and bindings.get("patch_diff_sha256") != request.patch_diff_sha256
            ),
            "tool_changed": bool(
                bindings.get("tool_id")
                and bindings.get("tool_id") != request.tool_id
            ),
            "configuration_changed": bool(
                bindings.get("configuration_digest")
                and bindings.get("configuration_digest")
                != request.configuration_digest
            ),
            "checkpoint_changed": bool(
                bindings.get("checkpoint_digest")
                and bindings.get("checkpoint_digest") != request.checkpoint_digest
            ),
            "validation_changed": bool(
                bindings.get("validation_plan_id")
                and bindings.get("validation_plan_id") != request.validation_plan_id
            ),
            "quality_requirements_changed": bool(
                bindings.get("quality_plan_id")
                and bindings.get("quality_plan_id") != request.quality_plan_id
            ),
            "budget_changed": bool(
                bindings.get("retry_budget_digest")
                and bindings.get("retry_budget_digest") != request.retry_budget_digest
            ),
            "rights_changed": bool(bindings.get("rights_changed")),
            "safety_state_changed": bool(bindings.get("safety_state_changed")),
            "decision_expired": expired,
        }
        reasons: list[str] = []
        if expired:
            reasons.append("The Safety Gate decision expired.")
        if current_snapshot != decision.project_snapshot_digest:
            reasons.append("The project snapshot digest changed.")
        if current_policy != decision.policy_snapshot_digest:
            reasons.append("The Safety Gate policy digest changed.")
        if current_request != decision.request_digest:
            reasons.append("The exact action request digest changed.")
        if (
            request.action_class
            in {"approval_required_read_only", "approval_required_execution"}
            and not current_approval_review.exact_binding_valid
        ):
            reasons.extend(current_approval_review.failure_reasons)
        reasons.extend(
            name.replace("_", " ")
            for name, changed in changes.items()
            if changed and name != "decision_expired"
        )
        if reasons:
            self._append_invalidation(
                gate,
                decision,
                reason="; ".join(_unique(reasons, limit=32)),
                current_request_digest=current_request,
                current_snapshot_digest=current_snapshot,
                current_policy_digest=current_policy,
                changes=changes,
            )
            invalid = self._invalid_decision(
                gate,
                decision,
                expired=expired,
                reasons=reasons,
            )
            self._refresh_summary(gate)
            self.store.save_boba_safety_gate(gate)
            return invalid
        return decision

    def record_human_safety_review(
        self,
        project_id: str,
        case_id: str,
        *,
        decision: Literal[
            "approve_exact_medium_risk_action",
            "deny_action",
            "request_more_evidence",
            "acknowledge_disclosed_limitation",
            "approve_stricter_budget_reset",
            "select_safer_alternative",
            "keep_project_paused",
        ],
        reason: str,
        reviewer_identity: str,
        request_digest: str,
        project_snapshot_digest: str,
    ) -> BobaSafetyDecisionV1:
        gate = self._gate(project_id)
        case = next(
            (item for item in gate.evaluation_cases if item.safety_case_id == case_id),
            None,
        )
        if case is None:
            raise ValidationError("BOBA Safety Gate evaluation case was not found.")
        request = self._request(gate, case.action_request_id)
        if request.request_digest != request_digest:
            raise ValidationError("Human review request digest does not match.")
        if request.project_snapshot_digest != project_snapshot_digest:
            raise ValidationError("Human review snapshot digest does not match.")
        prior = self.inspect_decision(project_id, case.safety_decision_id)
        hard_blocks = {
            "denied",
            "blocked_rights",
            "blocked_safety_policy",
            "unsupported_future_action",
            "blocked_checkpoint",
            "blocked_validation",
            "blocked_quality",
            "blocked_budget",
            "blocked_stale_state",
        }
        approval_requested = decision in {
            "approve_exact_medium_risk_action",
            "acknowledge_disclosed_limitation",
            "approve_stricter_budget_reset",
        }
        if approval_requested and prior.decision in hard_blocks:
            raise ValidationError(
                "Human review cannot override an absolute or required-control block."
            )
        risk = next(
            (
                item
                for item in gate.risk_assessments
                if item.risk_assessment_id == case.risk_assessment_id
            ),
            None,
        )
        if (
            decision == "approve_exact_medium_risk_action"
            and (
                prior.decision != "human_review_required"
                or risk is None
                or risk.overall_risk_level not in {"minimal", "low", "medium"}
            )
        ):
            raise ValidationError(
                "Only an exact medium-or-lower risk review may receive bounded allowance."
            )
        evidence = self._evidence(
            gate,
            case_id,
            source_module="human_operator",
            source_record_id=_digest(_text(reviewer_identity, maximum=160)),
            category="human_decision",
            summary=reason,
            observed=decision,
            expected="bounded policy decision",
            passed=approval_requested,
            human=True,
        )
        created = datetime.now(UTC)
        value: BobaSafetyDecisionValueV1 = (
            "allowed_for_exact_internal_execution"
            if approval_requested
            and request.action_class == "approval_required_execution"
            else "allowed_for_internal_read_only"
            if approval_requested
            else "denied"
            if decision == "deny_action"
            else "more_evidence_required"
            if decision in {"request_more_evidence", "select_safer_alternative"}
            else "human_review_required"
        )
        ttl_key = (
            "execution_allowance"
            if value == "allowed_for_exact_internal_execution"
            else "read_only_allowance"
            if value == "allowed_for_internal_read_only"
            else "human_review"
        )
        expires = created + timedelta(
            seconds=gate.policy_snapshot.decision_ttl_seconds[ttl_key]
        )
        payload = {
            **prior.model_dump(mode="json"),
            "safety_decision_id": _stable_id(
                "safety_human_decision",
                prior.safety_decision_id,
                decision,
                evidence.evidence_id,
            ),
            "decision": value,
            "decision_summary": (
                f"Human review recorded for this exact request: {_text(reason, maximum=650)}. "
                "The review cannot override absolute prohibitions or authorize publication."
            ),
            "allowed_action_class": request.action_class if approval_requested else "",
            "allowed_target_module": request.target_module if approval_requested else "",
            "allowed_target_operation": request.target_operation
            if approval_requested
            else "",
            "decision_created_at": created.isoformat(),
            "decision_expires_at": expires.isoformat(),
            "decision_expired": False,
            "decision_valid": approval_requested,
            "conditions": [*prior.conditions, "Bounded human review recorded."],
            "unmet_conditions": [] if approval_requested else [reason],
            "denial_reasons": [] if approval_requested else [reason],
            "human_review_required": not approval_requested,
            "confidence": 1.0,
            "warnings": [
                *prior.warnings,
                (
                    "Human review cannot authorize rights bypass, source modification, "
                    "upload, publication, merge, or deployment."
                ),
            ],
        }
        reviewed = self._append_unique(
            gate.safety_decisions,
            BobaSafetyDecisionV1.model_validate(payload),
            "safety_decision_id",
        )
        case.safety_decision_id = reviewed.safety_decision_id
        case.evaluation_status = (
            "completed" if reviewed.decision_valid else "awaiting_human_review"
        )
        self._build_handoffs(
            gate,
            case,
            reviewed,
            [
                item
                for item in gate.constraint_checks
                if item.safety_case_id == case_id
            ],
        )
        self._refresh_summary(gate)
        self.store.save_boba_safety_gate(gate)
        return reviewed

    def validate_for_autopilot(
        self,
        project_id: str,
        run_id: str,
        action: BobaAutopilotActionV1,
        decision_id: str,
        approval_record: Mapping[str, Any] | BobaContract,
    ) -> BobaSafetyDecisionV1:
        decision = self.revalidate_decision(
            project_id,
            decision_id,
            approval_record=approval_record,
        )
        gate = self._gate(project_id)
        request = self._request(gate, decision.action_request_id)
        reasons: list[str] = []
        if decision.decision != "allowed_for_exact_internal_execution":
            reasons.append("Safety Gate did not allow exact internal execution.")
        if not decision.decision_valid or decision_is_expired(decision):
            reasons.append("Safety Gate decision is invalid or expired.")
        if decision.autopilot_run_id != run_id:
            reasons.append("Safety Gate decision belongs to another Autopilot run.")
        if request.autopilot_action_id != action.action_id:
            reasons.append("Safety Gate request belongs to another Autopilot action.")
        if request.target_module != action.target_module:
            reasons.append("Safety Gate target module changed.")
        if request.target_operation != action.target_operation:
            reasons.append("Safety Gate target operation changed.")
        if request.action_parameters_digest != _digest(
            sanitize_safety_export(action.parameters)
        ):
            reasons.append("Safety Gate action parameters changed.")
        if reasons:
            invalidated = any(
                item.safety_decision_id == decision.safety_decision_id
                for item in gate.decision_invalidations
            )
            raise ValidationError(
                "Safety Gate blocked Autopilot execution coordination.",
                details={
                    "decision": decision.decision,
                    "decision_id": decision.safety_decision_id,
                    "invalidated": invalidated,
                    "reasons": reasons,
                },
            )
        return decision

    def export_safety_gate(self, project_id: str) -> dict[str, Any]:
        return self.store.export_boba_safety_gate(project_id)

    def reset_safety_gate_metadata(self, project_id: str) -> bool:
        return self.store.reset_boba_safety_gate(project_id)

    @staticmethod
    def _refresh_summary(gate: BobaSafetyGateSetV1) -> None:
        decisions = gate.safety_decisions
        counts = Counter(item.decision for item in decisions)
        denial_reasons = Counter(
            reason
            for item in decisions
            for reason in item.denial_reasons
            if reason
        )
        risk = max(
            gate.risk_assessments,
            key=lambda item: item.overall_risk_score,
            default=None,
        )
        gate.gate_summary = BobaSafetyGateSummaryV1(
            total_evaluations=len(gate.evaluation_cases),
            allowed_read_only_count=counts["allowed_for_internal_read_only"],
            allowed_internal_execution_count=counts[
                "allowed_for_exact_internal_execution"
            ],
            denied_count=counts["denied"],
            human_review_count=counts["human_review_required"],
            more_evidence_count=counts["more_evidence_required"],
            rights_block_count=counts["blocked_rights"],
            stale_state_block_count=counts["blocked_stale_state"],
            budget_block_count=counts["blocked_budget"],
            checkpoint_block_count=counts["blocked_checkpoint"],
            validation_block_count=counts["blocked_validation"],
            quality_block_count=counts["blocked_quality"],
            unsupported_future_action_count=counts["unsupported_future_action"],
            expired_decision_count=counts["expired"],
            invalidated_decision_count=len(gate.decision_invalidations),
            highest_risk_case=(
                f"{risk.safety_case_id}: {risk.overall_risk_level} "
                f"({risk.overall_risk_score:.1f})"
                if risk is not None
                else ""
            ),
            most_common_denial_reason=(
                denial_reasons.most_common(1)[0][0] if denial_reasons else ""
            ),
            current_pending_human_action=(
                "Review the latest exact Safety Gate case."
                if any(item.human_review_required for item in decisions[-20:])
                else ""
            ),
            safest_next_action=(
                "Revalidate the exact current decision before target execution."
                if any(item.decision_valid for item in decisions[-20:])
                else "Resolve the displayed blocking evidence and create a new request."
            ),
            limitations=[
                "Safety Gate V1 is evaluation-only.",
                "Allowances are exact, temporary, non-transferable, and revocable.",
                (
                    "Workflow resume, checkpoint restore, upload, publication, push, "
                    "merge, and deployment remain unauthorized."
                ),
            ],
        )


__all__ = [
    "BobaSafetyActionRequestV1",
    "BobaSafetyApprovalReviewV1",
    "BobaSafetyCheckpointReviewV1",
    "BobaSafetyConstraintCheckV1",
    "BobaSafetyDecisionInvalidationV1",
    "BobaSafetyDecisionV1",
    "BobaSafetyEvaluationCaseV1",
    "BobaSafetyEvidenceV1",
    "BobaSafetyGateSetV1",
    "BobaSafetyGateSignalUsageV1",
    "BobaSafetyGateSummaryV1",
    "BobaSafetyGateV1",
    "BobaSafetyHandoffV1",
    "BobaSafetyPolicySnapshotV1",
    "BobaSafetyQualityReviewV1",
    "BobaSafetyRightsReviewV1",
    "BobaSafetyRiskAssessmentV1",
    "BobaSafetyRiskFactorV1",
    "BobaSafetyValidationReadinessV1",
    "build_safety_module_operation_registry",
    "calculate_safety_decision_digest",
    "calculate_safety_request_digest",
    "decision_is_expired",
    "sanitize_safety_export",
]
