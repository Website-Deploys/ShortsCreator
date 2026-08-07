import { describe, expect, it } from "vitest";

import {
  ANNOTATION_NOTICE,
  COMMAND_WITHHELD_NOTICE,
  CONFIRMATION_STATEMENT,
  MAX_ANNOTATIONS,
  MAX_ANNOTATION_LENGTH,
  MAX_COMPARISON_PLANS,
  MAX_EXPANDED_SOURCE_CARDS,
  MAX_STEP_PROJECTIONS,
  MAX_TIMELINE_ENTRIES,
  NOT_EXECUTABLE_NOTICE,
  NO_EXECUTION_NOTICE,
  PRIVATE_PATH_NOTICE,
  PROPOSED_PLAN_NOTICE,
  QUEUE_PAGE_SIZE,
  RECOVERED_NOTICE,
  REVERSIBLE_NOTICE,
  RISK_DIMENSIONS,
  ROLLBACK_NOTICE,
  SOURCE_RETAINED_NOTICE,
  SOURCE_RISK_ORDER,
  SUPPORTED_REPAIR_PLAN_SCHEMA_ID,
  VERIFICATION_NOTICE,
  annotationIsAcceptable,
  approvalLabel,
  approvalSummary,
  availableActions,
  blockingConflicts,
  boundedAnnotations,
  buildAnnotation,
  canCompare,
  canSubmitAction,
  commandBearingStepCount,
  confidenceLabel,
  conflictSeverityLabel,
  conflictSummary,
  descriptorIsSafeForPanel,
  describeEvidenceCard,
  evidenceNotices,
  evidenceSummary,
  filterRepairPlans,
  formatTimestamp,
  humanise,
  independentlyVerifiedCount,
  missingApprovals,
  missingEvidence,
  orderSteps,
  ownerStatusLabel,
  panelRiskScore,
  planLimitations,
  planStateLabel,
  priorityLabel,
  receiptChangeLabels,
  receiptChangedNothing,
  receiptSummary,
  recommendationLabel,
  recoveryNotices,
  recoveryOutcomeLabel,
  recoverySummary,
  removeAnnotation,
  reversibilityLabel,
  revisionNotice,
  riskDimensionRows,
  riskLabel,
  riskRank,
  rollbackLabel,
  safestNextReviewAction,
  sortRepairPlans,
  stepChangeLabels,
  stepDescription,
  stepIsExecutable,
  stepNotices,
  strategyRiskRows,
  strategyTypeLabel,
  toggleComparison,
  unavailableActionNotice,
  unavailableActions,
  unsupportedSchemaNotice,
  upsertAnnotation,
  validateActionReason,
  verificationLabel,
  verificationSummary,
  type RepairApprovalRequirement,
  type RepairEvidenceCard,
  type RepairPlanActionDescriptor,
  type RepairPlanActionReceipt,
  type RepairPlanConflict,
  type RepairPlanQueueItem,
  type RepairPlanReference,
  type RepairPlanSnapshot,
  type RepairRecoveryLink,
  type RepairRiskProjection,
  type RepairStepProjection,
  type RepairVerificationRequirement,
} from "@/lib/repairPlanReview";

/* ------------------------------------------------------------------ */
/* Builders                                                            */
/* ------------------------------------------------------------------ */

function queueItem(overrides: Partial<RepairPlanQueueItem> = {}): RepairPlanQueueItem {
  return {
    repair_plan_queue_item_id: "q1",
    repair_plan_reference_id: "ref1",
    project_id: "p1",
    repair_plan_id: "strategy_a",
    repair_case_id: "case_a",
    source_analysis_case_id: "analysis_a",
    source_diagnostic_case_id: "incident_a",
    title: "Retry the render",
    bounded_summary: "Try again with a supported setting.",
    owner_module_id: "repair_planner",
    original_status: "plan_ready",
    original_strategy_type: "retry_with_safe_settings",
    original_risk_level: "low",
    original_reversibility: "fully_reversible",
    original_destructiveness: "none",
    approval_status: "awaiting_human_review",
    verification_status: "incomplete",
    recovery_status: "unavailable",
    validation_status: "planned",
    artifact_status: "unavailable",
    workflow_status: "running",
    affected_module_id: "rendering",
    affected_stage_id: "render",
    step_count: 2,
    destructive: false,
    reversible: true,
    rollback_available: true,
    requires_code_change: false,
    requires_artifact_change: false,
    requires_workflow_transition: false,
    requires_tool_execution: false,
    requires_process_restart: false,
    requires_checkpoint_restore: false,
    requires_human_approval: true,
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    completed: false,
    source_marked_recommended: true,
    human_action_required: true,
    blocker_count: 0,
    warning_count: 0,
    missing_approval_count: 2,
    missing_verification_count: 1,
    missing_evidence_count: 0,
    conflict_count: 0,
    failed_recovery_attempt_count: 0,
    command_bearing_step_count: 0,
    available_action_descriptor_ids: [],
    source_module_ids: ["repair_planner"],
    priority_tier: 90,
    priority_reason: "current_reversible_plan_awaiting_review",
    deterministic_sort_key: "000000:strategy_a",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function step(overrides: Partial<RepairStepProjection> = {}): RepairStepProjection {
  return {
    repair_step_projection_id: "s1",
    repair_plan_id: "strategy_a",
    source_module_id: "repair_planner",
    source_record_id: "step_1",
    source_step_id: "step_1",
    original_order: 1,
    original_status: "proposed",
    original_step_type: "inspect",
    bounded_description: "Read the recorded capability.",
    bounded_reason: "",
    affected_module_ids: ["artifact_inspector"],
    requires_code_change: false,
    requires_artifact_change: false,
    requires_tool_execution: false,
    requires_process_restart: false,
    requires_checkpoint_restore: false,
    requires_workflow_transition: false,
    requires_human_approval: true,
    destructive: false,
    reversible: true,
    rollback_available: false,
    verification_required: true,
    read_only_by_owner: true,
    raw_command_present_in_source: false,
    raw_command_exposed: false,
    private_path_present_in_source: false,
    private_path_exposed: false,
    executable_by_panel: false,
    bounded_safety_precondition: "A checkpoint must exist.",
    bounded_success_condition: "The capability matches.",
    warnings: [],
    limitations: [NOT_EXECUTABLE_NOTICE],
    ...overrides,
  };
}

function riskRow(overrides: Partial<RepairRiskProjection> = {}): RepairRiskProjection {
  return {
    repair_risk_projection_id: "r1",
    repair_plan_id: "strategy_a",
    source_record_id: "risk_a",
    risk_dimension: "overall_risk",
    original_risk_level: "medium",
    strategy_specific: false,
    blocked_by_owner: false,
    bounded_reasons: [],
    bounded_mitigations: [],
    bounded_residual_risk: "",
    acceptable_only_if: [],
    confidence_value: null,
    confidence_name: "",
    confidence_definition: "",
    reversible_does_not_mean_risk_free: true,
    warnings: [],
    limitations: ["Risk levels are the owner's own values."],
    ...overrides,
  };
}

function approval(
  overrides: Partial<RepairApprovalRequirement> = {},
): RepairApprovalRequirement {
  return {
    approval_requirement_id: "a1",
    repair_plan_id: "strategy_a",
    source_module_id: "repair_planner",
    source_record_id: "gate_a",
    requirement_type: "human_review",
    required: true,
    satisfied_by_owner: false,
    canonical_record_id: null,
    canonical_record_digest: null,
    blocking: true,
    bounded_explanation: "Final human approval is required.",
    warnings: [],
    limitations: ["The panel records no approval."],
    ...overrides,
  };
}

function verification(
  overrides: Partial<RepairVerificationRequirement> = {},
): RepairVerificationRequirement {
  return {
    verification_requirement_id: "v1",
    repair_plan_id: "strategy_a",
    verification_type: "validator_run",
    required: true,
    source_module_id: "validator_runner",
    source_record_id: "validation_a",
    validator_ids: ["baseline_comparison"],
    artifact_reference_ids: [],
    required_check_ids: [],
    satisfied: false,
    independently_verified: false,
    blocks_acceptance_on_failure: true,
    blocking: true,
    bounded_explanation: "Validator Runner must run these validators.",
    warnings: [],
    limitations: [VERIFICATION_NOTICE],
    ...overrides,
  };
}

function evidence(overrides: Partial<RepairEvidenceCard> = {}): RepairEvidenceCard {
  return {
    repair_evidence_card_id: "e1",
    evidence_type: "repair_strategy",
    source_module_id: "repair_planner",
    authority_domain: "repair_plan",
    source_record_id: "strategy_a",
    source_record_digest: "a".repeat(64),
    title: "Proposed Repair Strategy",
    original_status: "retry_with_safe_settings",
    original_decision: null,
    bounded_summary: "Try again with a supported setting.",
    bounded_excerpt: "",
    excerpt_truncated: false,
    command_withheld: false,
    sensitive_values_redacted: false,
    private_paths_redacted: false,
    current: true,
    stale: false,
    historical: false,
    missing: false,
    authoritative: true,
    advisory_only: false,
    blocking: false,
    warnings: [],
    limitations: [SOURCE_RETAINED_NOTICE],
    ...overrides,
  };
}

function recovery(overrides: Partial<RepairRecoveryLink> = {}): RepairRecoveryLink {
  return {
    repair_recovery_link_id: "l1",
    repair_plan_id: "strategy_a",
    source_module_id: "tool_recovery",
    source_record_id: "attempt_a",
    recovery_case_id: "recovery_case_a",
    recovery_attempt_id: "attempt_a",
    attempt_number: 1,
    original_status: "succeeded_pending_validation",
    linked_by_strategy_id: true,
    attempted: true,
    completed: true,
    succeeded_by_owner: true,
    independently_verified: false,
    verification_source_ids: ["validation_a"],
    rollback_attempted: false,
    rollback_status: "unavailable",
    resulting_failure_class: null,
    started_at: "2026-02-01T11:00:00+00:00",
    completed_at: "2026-02-01T11:04:00+00:00",
    bounded_summary: "The fallback encoder produced an output.",
    warnings: [],
    limitations: [RECOVERED_NOTICE],
    ...overrides,
  };
}

function conflict(overrides: Partial<RepairPlanConflict> = {}): RepairPlanConflict {
  return {
    conflict_record_id: "c1",
    conflict_type: "destructive_flag_conflict",
    severity: "warning",
    source_record_ids: ["strategy_a"],
    value_a: "destructiveness=none",
    value_b: "declares a code change",
    same_repair_plan: true,
    resolved: false,
    blocks_action: false,
    human_review_required: true,
    bounded_summary: "The strategy is rated non-destructive yet changes code.",
    warnings: [],
    limitations: ["Conflicts are never resolved automatically."],
    ...overrides,
  };
}

function descriptor(
  overrides: Partial<RepairPlanActionDescriptor> = {},
): RepairPlanActionDescriptor {
  return {
    action_descriptor_id: "repair_plan_action_acknowledge_linked_incident_v1",
    display_name: "Acknowledge the linked incident",
    action_class: "ui_metadata_acknowledgement",
    owning_module_id: "review_ui",
    owning_operation_id: "acknowledge_notification",
    allowed_decision_values: ["acknowledged"],
    requires_reason: false,
    maximum_reason_length: 500,
    requires_confirmation: true,
    authoritative: false,
    destructive: false,
    execution_capable: false,
    code_modifying: false,
    artifact_modifying: false,
    workflow_modifying: false,
    checkpoint_restoring: false,
    process_restarting: false,
    upload_or_publication: false,
    allowed_in_v1: true,
    availability: "available",
    unavailable_reason: "",
    consequences: ["Records the incident in the Review UI session."],
    does_not_do: ["Does not approve the repair plan."],
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function snapshot(overrides: Partial<RepairPlanSnapshot> = {}): RepairPlanSnapshot {
  return {
    repair_plan_snapshot_id: "snap1",
    repair_plan_review_session_id: "sess1",
    repair_plan_reference_id: "ref1",
    project_id: "p1",
    repair_plan_id: "strategy_a",
    repair_case_id: "case_a",
    source_diagnostic_case_id: "incident_a",
    project_snapshot_digest: "a".repeat(64),
    workflow_revision: 3,
    repair_plan_digest: "b".repeat(64),
    plan_status: "plan_ready",
    approval_status: "awaiting_human_review",
    verification_status: "incomplete",
    recovery_status: "unavailable",
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    completed: false,
    destructive: false,
    reversible: true,
    rollback_available: true,
    missing_approval_count: 2,
    missing_verification_count: 1,
    missing_evidence_count: 0,
    conflict_count: 0,
    available_action_descriptor_ids: [
      "repair_plan_action_acknowledge_linked_incident_v1",
    ],
    confirmation_context_digest: "c".repeat(64),
    snapshot_digest: "d".repeat(64),
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function reference(overrides: Partial<RepairPlanReference> = {}): RepairPlanReference {
  return {
    repair_plan_reference_id: "ref1",
    project_id: "p1",
    repair_plan_id: "strategy_a",
    repair_plan_revision_id: null,
    repair_case_id: "case_a",
    source_analysis_case_id: "analysis_a",
    source_diagnostic_case_id: "incident_a",
    source_record_id: "strategy_a",
    source_record_digest: "a".repeat(64),
    source_schema_id: SUPPORTED_REPAIR_PLAN_SCHEMA_ID,
    schema_supported: true,
    owner_module_id: "repair_planner",
    original_status: "plan_ready",
    original_strategy_type: "retry_with_safe_settings",
    original_risk_level: "low",
    affected_stage_id: "render",
    affected_module_id: "rendering",
    project_snapshot_digest: "a".repeat(64),
    workflow_revision: 3,
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    superseding_repair_plan_id: null,
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function receipt(
  overrides: Partial<RepairPlanActionReceipt> = {},
): RepairPlanActionReceipt {
  return {
    repair_plan_action_receipt_id: "rc1",
    repair_plan_action_request_id: "rq1",
    repair_plan_id: "strategy_a",
    owning_module_id: "review_ui",
    owning_operation_id: "acknowledge_notification",
    accepted_by_owner: true,
    canonical_record_id: "review_session_1",
    canonical_status: "acknowledged",
    authoritative_state_changed: false,
    plan_approved: false,
    plan_rejected: false,
    plan_revised: false,
    repair_executed: false,
    recovery_attempt_started: false,
    checkpoint_restored: false,
    process_restarted: false,
    workflow_changed: false,
    code_changed: false,
    artifact_changed: false,
    canonical_refresh_required: true,
    stale_state_rejected: false,
    duplicate_request_reused: false,
    error_code: null,
    bounded_error_message: "",
    limitations: [],
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/* Constants and notices                                               */
/* ------------------------------------------------------------------ */

describe("constants match the backend contract", () => {
  it("bounds comparison to four plans", () => {
    expect(MAX_COMPARISON_PLANS).toBe(4);
  });

  it("bounds the queue page", () => {
    expect(QUEUE_PAGE_SIZE).toBe(50);
  });

  it("bounds annotations", () => {
    expect(MAX_ANNOTATIONS).toBe(32);
    expect(MAX_ANNOTATION_LENGTH).toBe(4_000);
  });

  it("bounds step projections", () => {
    expect(MAX_STEP_PROJECTIONS).toBe(64);
  });

  it("bounds expanded source cards", () => {
    expect(MAX_EXPANDED_SOURCE_CARDS).toBe(20);
  });

  it("bounds the timeline", () => {
    expect(MAX_TIMELINE_ENTRIES).toBe(100);
  });

  it("names the supported owner schema", () => {
    expect(SUPPORTED_REPAIR_PLAN_SCHEMA_ID).toBe("boba_repair_planner_v1");
  });

  it("lists the twelve owner risk dimensions", () => {
    expect(RISK_DIMENSIONS).toHaveLength(12);
    expect(RISK_DIMENSIONS).toContain("overall_risk");
    expect(RISK_DIMENSIONS).toContain("rollback_failure_risk");
  });

  it("orders risk from the owner's own vocabulary", () => {
    expect(SOURCE_RISK_ORDER[0]).toBe("blocking");
    expect(SOURCE_RISK_ORDER).toContain("unknown");
  });
});

describe("required notices are the exact fixed strings", () => {
  it("withholds commands with the exact sentence", () => {
    expect(COMMAND_WITHHELD_NOTICE).toBe(
      "Command details withheld from the review panel.",
    );
  });

  it("redacts private paths with the exact sentence", () => {
    expect(PRIVATE_PATH_NOTICE).toBe("Private path details redacted.");
  });

  it("states a step is not executable with the exact sentence", () => {
    expect(NOT_EXECUTABLE_NOTICE).toBe("This step cannot be executed from this panel.");
  });

  it("states the source is retained with the exact sentence", () => {
    expect(SOURCE_RETAINED_NOTICE).toBe(
      "Full source record retained by Repair Planner.",
    );
  });

  it("labels an annotation as non-canonical with the exact sentence", () => {
    expect(ANNOTATION_NOTICE).toBe(
      "Review-session annotation — not part of the canonical repair plan.",
    );
  });

  it("uses the exact confirmation statement", () => {
    expect(CONFIRMATION_STATEMENT).toContain("does not directly execute commands");
    expect(CONFIRMATION_STATEMENT).toContain("grant Rights or Safety approval");
    expect(CONFIRMATION_STATEMENT).toContain("publish content");
  });

  it("attributes the plan to Repair Planner", () => {
    expect(PROPOSED_PLAN_NOTICE).toContain("Repair Planner proposed this strategy");
    expect(PROPOSED_PLAN_NOTICE).toContain("does not state that it is the correct repair");
  });

  it("states reversible is not risk-free", () => {
    expect(REVERSIBLE_NOTICE).toBe("Reversible does not mean risk-free.");
  });

  it("states an available rollback is not guaranteed", () => {
    expect(ROLLBACK_NOTICE).toContain("does not mean a rollback is guaranteed");
  });

  it("states owner success is not verification", () => {
    expect(VERIFICATION_NOTICE).toBe(
      "Owner-reported success is not independent verification.",
    );
  });

  it("states recovered is not resolved", () => {
    expect(RECOVERED_NOTICE).toBe("Recovered is not resolved.");
  });

  it("states no execution action exists", () => {
    expect(NO_EXECUTION_NOTICE).toContain("no plan approval");
    expect(NO_EXECUTION_NOTICE).toContain("execution");
  });
});

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */

describe("formatting never invents owner data", () => {
  it("reports a missing timestamp honestly", () => {
    expect(formatTimestamp(null)).toBe("Time not recorded by the owner");
  });

  it("reports an unparseable timestamp honestly", () => {
    expect(formatTimestamp("not-a-date")).toBe("Time not recorded by the owner");
  });

  it("formats a real timestamp", () => {
    expect(formatTimestamp("2026-02-01T10:00:00+00:00")).not.toBe(
      "Time not recorded by the owner",
    );
  });

  it("humanises snake case", () => {
    expect(humanise("retry_with_safe_settings")).toBe("Retry With Safe Settings");
  });

  it("humanises an empty value as Unknown", () => {
    expect(humanise("")).toBe("Unknown");
  });

  it("ranks known risk levels by owner order", () => {
    expect(riskRank("critical")).toBeLessThan(riskRank("low"));
  });

  it("ranks an unknown risk level last", () => {
    expect(riskRank("not-a-level")).toBe(SOURCE_RISK_ORDER.length);
  });

  it("always attributes a status to its owner", () => {
    expect(ownerStatusLabel("repair_planner", "plan_ready")).toBe(
      "Repair Planner recorded: Plan Ready",
    );
  });

  it("attributes a proposal to Repair Planner", () => {
    expect(strategyTypeLabel(queueItem())).toContain("Repair Planner proposed");
  });

  it("reports the owner's own recommended flag", () => {
    expect(recommendationLabel(queueItem({ source_marked_recommended: true }))).toContain(
      "marked this strategy recommended",
    );
    expect(
      recommendationLabel(queueItem({ source_marked_recommended: false })),
    ).toContain("did not mark this strategy recommended");
  });

  it("pairs reversibility with the risk-free warning", () => {
    expect(reversibilityLabel(queueItem())).toContain(REVERSIBLE_NOTICE);
  });

  it("pairs an available rollback with the guarantee warning", () => {
    expect(rollbackLabel(queueItem({ rollback_available: true }))).toContain(
      ROLLBACK_NOTICE,
    );
  });

  it("reports an absent rollback plan plainly", () => {
    expect(rollbackLabel(queueItem({ rollback_available: false }))).toContain(
      "No rollback plan is recorded",
    );
  });

  it("labels the display tier without calling it a score", () => {
    const label = priorityLabel(queueItem({ priority_tier: 10 }));
    expect(label).toContain("Tier 10");
    expect(label.toLowerCase()).not.toContain("score");
  });
});

describe("plan state labels never strengthen a source status", () => {
  it("labels a current plan", () => {
    expect(planStateLabel(queueItem())).toBe("Current");
  });

  it("labels a stale plan", () => {
    expect(planStateLabel(queueItem({ stale: true }))).toBe("Stale");
  });

  it("labels a superseded plan", () => {
    expect(planStateLabel(queueItem({ superseded: true }))).toBe("Superseded");
  });

  it("labels a historical plan", () => {
    expect(planStateLabel(queueItem({ historical: true }))).toBe("Historical");
  });

  it("never calls a completed plan verified", () => {
    const label = planStateLabel(queueItem({ completed: true }));
    expect(label).toBe("Carried out by its owner, not verified");
    expect(label).not.toContain("Verified,");
  });
});

/* ------------------------------------------------------------------ */
/* Filtering and sorting                                              */
/* ------------------------------------------------------------------ */

const baseFilter = {
  filter: "all_current" as const,
  showHistorical: false,
  showSuperseded: false,
  showCompleted: true,
};

describe("filtering is explicit and hides nothing silently", () => {
  it("hides historical plans unless asked", () => {
    const rows = filterRepairPlans(
      [queueItem(), queueItem({ repair_plan_id: "b", historical: true })],
      baseFilter,
    );
    expect(rows).toHaveLength(1);
  });

  it("shows historical plans when asked", () => {
    const rows = filterRepairPlans(
      [queueItem(), queueItem({ repair_plan_id: "b", historical: true })],
      { ...baseFilter, showHistorical: true },
    );
    expect(rows).toHaveLength(2);
  });

  it("hides superseded plans unless asked", () => {
    const rows = filterRepairPlans(
      [queueItem(), queueItem({ repair_plan_id: "b", superseded: true })],
      baseFilter,
    );
    expect(rows).toHaveLength(1);
  });

  it("hides completed plans when asked", () => {
    const rows = filterRepairPlans(
      [queueItem(), queueItem({ repair_plan_id: "b", completed: true })],
      { ...baseFilter, showCompleted: false },
    );
    expect(rows).toHaveLength(1);
  });

  it("filters plans needing human review", () => {
    const rows = filterRepairPlans(
      [
        queueItem({ human_action_required: true }),
        queueItem({ repair_plan_id: "b", human_action_required: false }),
      ],
      { ...baseFilter, filter: "human_review_required" },
    );
    expect(rows).toHaveLength(1);
  });

  it("filters destructive plans", () => {
    const rows = filterRepairPlans(
      [queueItem({ destructive: true }), queueItem({ repair_plan_id: "b" })],
      { ...baseFilter, filter: "destructive" },
    );
    expect(rows.every((row) => row.destructive)).toBe(true);
  });

  it("filters reversible plans", () => {
    const rows = filterRepairPlans([queueItem({ reversible: true })], {
      ...baseFilter,
      filter: "reversible",
    });
    expect(rows).toHaveLength(1);
  });

  it("filters code-change plans", () => {
    const rows = filterRepairPlans([queueItem({ requires_code_change: true })], {
      ...baseFilter,
      filter: "code_change",
    });
    expect(rows).toHaveLength(1);
  });

  it("filters artifact-change plans", () => {
    const rows = filterRepairPlans([queueItem({ requires_artifact_change: true })], {
      ...baseFilter,
      filter: "artifact_change",
    });
    expect(rows).toHaveLength(1);
  });

  it("filters workflow-change plans", () => {
    const rows = filterRepairPlans([queueItem({ requires_workflow_transition: true })], {
      ...baseFilter,
      filter: "workflow_change",
    });
    expect(rows).toHaveLength(1);
  });

  it("filters tool-execution plans", () => {
    const rows = filterRepairPlans([queueItem({ requires_tool_execution: true })], {
      ...baseFilter,
      filter: "tool_execution",
    });
    expect(rows).toHaveLength(1);
  });

  it("filters process-restart plans", () => {
    const rows = filterRepairPlans([queueItem({ requires_process_restart: true })], {
      ...baseFilter,
      filter: "process_restart",
    });
    expect(rows).toHaveLength(1);
  });

  it("filters checkpoint-restore plans", () => {
    const rows = filterRepairPlans([queueItem({ requires_checkpoint_restore: true })], {
      ...baseFilter,
      filter: "checkpoint_restore",
    });
    expect(rows).toHaveLength(1);
  });

  it("filters plans missing approval", () => {
    const rows = filterRepairPlans(
      [queueItem({ missing_approval_count: 0 }), queueItem({ repair_plan_id: "b" })],
      { ...baseFilter, filter: "missing_approval" },
    );
    expect(rows).toHaveLength(1);
  });

  it("filters plans missing verification", () => {
    const rows = filterRepairPlans(
      [queueItem({ missing_verification_count: 0 }), queueItem({ repair_plan_id: "b" })],
      { ...baseFilter, filter: "missing_verification" },
    );
    expect(rows).toHaveLength(1);
  });

  it("filters plans with a failed recovery attempt", () => {
    const rows = filterRepairPlans(
      [queueItem({ failed_recovery_attempt_count: 2 }), queueItem({ repair_plan_id: "b" })],
      { ...baseFilter, filter: "failed_recovery" },
    );
    expect(rows).toHaveLength(1);
  });

  it("filters plans with conflicts", () => {
    const rows = filterRepairPlans(
      [queueItem({ conflict_count: 1 }), queueItem({ repair_plan_id: "b" })],
      { ...baseFilter, filter: "conflicts" },
    );
    expect(rows).toHaveLength(1);
  });

  it("filters stale plans", () => {
    const rows = filterRepairPlans([queueItem({ stale: true })], {
      ...baseFilter,
      filter: "stale",
    });
    expect(rows).toHaveLength(1);
  });

  it("shows completed plans on the completed filter even when hidden", () => {
    const rows = filterRepairPlans([queueItem({ completed: true })], {
      ...baseFilter,
      filter: "completed",
      showCompleted: false,
    });
    expect(rows).toHaveLength(1);
  });

  it("shows historical plans on the historical filter even when hidden", () => {
    const rows = filterRepairPlans([queueItem({ historical: true })], {
      ...baseFilter,
      filter: "historical",
    });
    expect(rows).toHaveLength(1);
  });

  it("shows superseded plans on the superseded filter even when hidden", () => {
    const rows = filterRepairPlans([queueItem({ superseded: true })], {
      ...baseFilter,
      filter: "superseded",
    });
    expect(rows).toHaveLength(1);
  });
});

describe("sorting is deterministic and never uses a panel score", () => {
  const rows = [
    queueItem({
      repair_plan_id: "a",
      priority_tier: 90,
      original_risk_level: "low",
      step_count: 2,
      affected_module_id: "rendering",
      deterministic_sort_key: "000001:a",
    }),
    queueItem({
      repair_plan_id: "b",
      priority_tier: 10,
      original_risk_level: "critical",
      step_count: 5,
      affected_module_id: "assembly",
      deterministic_sort_key: "000000:b",
    }),
  ];

  it("orders by display tier for review priority", () => {
    expect(sortRepairPlans(rows, "review_priority")[0].repair_plan_id).toBe("b");
  });

  it("orders by the owner's own risk for source severity", () => {
    expect(sortRepairPlans(rows, "source_severity")[0].original_risk_level).toBe(
      "critical",
    );
  });

  it("orders by the owner's record order for creation order", () => {
    expect(sortRepairPlans(rows, "creation_order")[0].deterministic_sort_key).toBe(
      "000000:b",
    );
  });

  it("orders by affected module", () => {
    expect(sortRepairPlans(rows, "affected_module")[0].affected_module_id).toBe(
      "assembly",
    );
  });

  it("orders by step count descending", () => {
    expect(sortRepairPlans(rows, "step_count")[0].step_count).toBe(5);
  });

  it("orders by plan id", () => {
    expect(sortRepairPlans(rows, "repair_plan_id")[0].repair_plan_id).toBe("a");
  });

  it("does not mutate the input", () => {
    const original = [...rows];
    sortRepairPlans(rows, "source_severity");
    expect(rows).toEqual(original);
  });

  it("breaks ties deterministically", () => {
    const tied = [
      queueItem({ repair_plan_id: "y", deterministic_sort_key: "000002:y" }),
      queueItem({ repair_plan_id: "x", deterministic_sort_key: "000001:x" }),
    ];
    expect(sortRepairPlans(tied, "review_priority")[0].repair_plan_id).toBe("x");
  });
});

/* ------------------------------------------------------------------ */
/* Steps                                                               */
/* ------------------------------------------------------------------ */

describe("steps preserve owner order and withhold commands", () => {
  it("orders by the owner's own order field", () => {
    const ordered = orderSteps([
      step({ repair_step_projection_id: "s2", source_step_id: "step_2", original_order: 2 }),
      step(),
    ]);
    expect(ordered.map((row) => row.original_order)).toEqual([1, 2]);
  });

  it("breaks order ties by source step id", () => {
    const ordered = orderSteps([
      step({ repair_step_projection_id: "sb", source_step_id: "step_b" }),
      step({ repair_step_projection_id: "sa", source_step_id: "step_a" }),
    ]);
    expect(ordered[0].source_step_id).toBe("step_a");
  });

  it("shows the owner description when present", () => {
    expect(stepDescription(step())).toBe("Read the recorded capability.");
  });

  it("reports a missing description honestly", () => {
    expect(stepDescription(step({ bounded_description: "" }))).toContain(
      "No description recorded",
    );
  });

  it("shows the withheld notice for a command-bearing step", () => {
    const notices = stepNotices(step({ raw_command_present_in_source: true }));
    expect(notices).toContain(COMMAND_WITHHELD_NOTICE);
  });

  it("shows the private path notice when the source holds one", () => {
    const notices = stepNotices(step({ private_path_present_in_source: true }));
    expect(notices).toContain(PRIVATE_PATH_NOTICE);
  });

  it("always states a step is not executable", () => {
    expect(stepNotices(step())).toContain(NOT_EXECUTABLE_NOTICE);
  });

  it("warns that an available rollback is not guaranteed", () => {
    expect(stepNotices(step({ rollback_available: true }))).toContain(ROLLBACK_NOTICE);
  });

  it("never reports a step as executable", () => {
    expect(stepIsExecutable(step())).toBe(false);
    expect(stepIsExecutable(step({ raw_command_present_in_source: true }))).toBe(false);
  });

  it("labels a code change", () => {
    expect(stepChangeLabels(step({ requires_code_change: true }))).toContain(
      "Proposes a code change",
    );
  });

  it("labels an artifact change", () => {
    expect(stepChangeLabels(step({ requires_artifact_change: true }))).toContain(
      "Proposes an artifact change",
    );
  });

  it("labels tool execution", () => {
    expect(stepChangeLabels(step({ requires_tool_execution: true }))).toContain(
      "Needs tool execution",
    );
  });

  it("labels a process restart", () => {
    expect(stepChangeLabels(step({ requires_process_restart: true }))).toContain(
      "Needs a process restart",
    );
  });

  it("labels a checkpoint restore", () => {
    expect(stepChangeLabels(step({ requires_checkpoint_restore: true }))).toContain(
      "Needs a checkpoint restore",
    );
  });

  it("labels a workflow transition", () => {
    expect(stepChangeLabels(step({ requires_workflow_transition: true }))).toContain(
      "Needs a workflow transition",
    );
  });

  it("reports the owner's read-only marking", () => {
    expect(stepChangeLabels(step({ read_only_by_owner: true }))).toContain(
      "Repair Planner marked this step read-only",
    );
  });

  it("counts command-bearing steps", () => {
    expect(
      commandBearingStepCount([
        step({ raw_command_present_in_source: true }),
        step({ repair_step_projection_id: "s2" }),
      ]),
    ).toBe(1);
  });
});

/* ------------------------------------------------------------------ */
/* Risk                                                                */
/* ------------------------------------------------------------------ */

describe("risk is projected verbatim with no panel score", () => {
  it("returns dimension rows in the owner's dimension order", () => {
    const rows = RISK_DIMENSIONS.map((dimension) =>
      riskRow({ repair_risk_projection_id: dimension, risk_dimension: dimension }),
    );
    expect(riskDimensionRows(rows).map((row) => row.risk_dimension)).toEqual([
      ...RISK_DIMENSIONS,
    ]);
  });

  it("omits dimensions the owner did not record", () => {
    expect(riskDimensionRows([riskRow()])).toHaveLength(1);
  });

  it("separates strategy-specific rows", () => {
    const rows = [riskRow(), riskRow({ repair_risk_projection_id: "r2", strategy_specific: true })];
    expect(strategyRiskRows(rows)).toHaveLength(1);
  });

  it("labels a dimension with the owner's own level", () => {
    expect(riskLabel(riskRow({ original_risk_level: "high" }))).toBe(
      "Overall Risk: High",
    );
  });

  it("marks an owner-blocked dimension", () => {
    expect(riskLabel(riskRow({ blocked_by_owner: true }))).toContain(
      "Repair Planner blocked this",
    );
  });

  it("returns no confidence when the owner recorded none", () => {
    expect(confidenceLabel(riskRow())).toBeNull();
  });

  it("shows the owner's confidence unchanged", () => {
    expect(
      confidenceLabel(
        riskRow({ confidence_value: 0.44, confidence_name: "repair_planner_reported_confidence" }),
      ),
    ).toContain("0.44");
  });

  it("never produces a panel risk score", () => {
    expect(panelRiskScore([riskRow()])).toBeNull();
  });

  it("pins that reversible is not risk-free on every row", () => {
    expect(riskRow().reversible_does_not_mean_risk_free).toBe(true);
  });
});

/* ------------------------------------------------------------------ */
/* Approvals and verification                                          */
/* ------------------------------------------------------------------ */

describe("approvals are never satisfied without a canonical record", () => {
  it("labels an unsatisfied requirement", () => {
    expect(approvalLabel(approval())).toContain("not satisfied");
  });

  it("labels a satisfied requirement as owner-backed", () => {
    expect(
      approvalLabel(
        approval({
          satisfied_by_owner: true,
          canonical_record_id: "rollback_a",
          canonical_record_digest: "a".repeat(64),
        }),
      ),
    ).toContain("satisfied by a canonical owner record");
  });

  it("collects missing approvals", () => {
    expect(
      missingApprovals([approval(), approval({ approval_requirement_id: "a2", satisfied_by_owner: true, canonical_record_id: "x", canonical_record_digest: "y" })]),
    ).toHaveLength(1);
  });

  it("summarises no requirements honestly", () => {
    expect(approvalSummary([])).toContain("no approval requirements");
  });

  it("states a missing approval is not an approval", () => {
    expect(approvalSummary([approval()])).toContain("A missing approval is not an approval");
  });

  it("summarises fully satisfied requirements", () => {
    expect(
      approvalSummary([
        approval({
          satisfied_by_owner: true,
          canonical_record_id: "x",
          canonical_record_digest: "y",
        }),
      ]),
    ).toContain("names a canonical owner record");
  });
});

describe("verification never claims independent verification", () => {
  it("labels an unsatisfied check", () => {
    expect(verificationLabel(verification())).toContain("not satisfied");
  });

  it("labels an owner-satisfied check without calling it verified", () => {
    const label = verificationLabel(verification({ satisfied: true }));
    expect(label).toContain("reported satisfied by its owner");
    expect(label).not.toContain("independently");
  });

  it("summarises no requirements honestly", () => {
    expect(verificationSummary([])).toContain("no verification requirements");
  });

  it("appends the verification notice when all are satisfied", () => {
    expect(verificationSummary([verification({ satisfied: true })])).toContain(
      VERIFICATION_NOTICE,
    );
  });

  it("appends the verification notice when some are missing", () => {
    expect(verificationSummary([verification()])).toContain(VERIFICATION_NOTICE);
  });

  it("counts independent verification as zero for owner-satisfied checks", () => {
    expect(independentlyVerifiedCount([verification({ satisfied: true })])).toBe(0);
  });
});

/* ------------------------------------------------------------------ */
/* Evidence                                                            */
/* ------------------------------------------------------------------ */

describe("evidence is attributed and never rewritten", () => {
  it("attributes a present card to its owner", () => {
    expect(describeEvidenceCard(evidence())).toContain("Repair Planner recorded");
  });

  it("reports a missing card honestly", () => {
    expect(describeEvidenceCard(evidence({ missing: true }))).toContain("not available");
  });

  it("shows the command notice when the excerpt was withheld", () => {
    expect(evidenceNotices(evidence({ command_withheld: true }))).toContain(
      COMMAND_WITHHELD_NOTICE,
    );
  });

  it("shows the private path notice when redacted", () => {
    expect(evidenceNotices(evidence({ private_paths_redacted: true }))).toContain(
      PRIVATE_PATH_NOTICE,
    );
  });

  it("reports redacted sensitive values", () => {
    expect(evidenceNotices(evidence({ sensitive_values_redacted: true }))).toContain(
      "Sensitive values redacted.",
    );
  });

  it("reports a truncated excerpt", () => {
    expect(evidenceNotices(evidence({ excerpt_truncated: true }))).toContain(
      "Excerpt truncated.",
    );
  });

  it("marks advisory evidence as non-authorising", () => {
    expect(evidenceNotices(evidence({ advisory_only: true }))).toContain(
      "Advisory only. This does not authorise a repair.",
    );
  });

  it("always states the source is retained", () => {
    expect(evidenceNotices(evidence())).toContain(SOURCE_RETAINED_NOTICE);
  });

  it("collects missing evidence", () => {
    expect(
      missingEvidence([evidence(), evidence({ repair_evidence_card_id: "e2", missing: true })]),
    ).toHaveLength(1);
  });

  it("states missing evidence is not a pass", () => {
    expect(evidenceSummary([evidence({ missing: true })])).toContain(
      "Missing evidence is not a pass",
    );
  });

  it("reports full coverage plainly", () => {
    expect(evidenceSummary([evidence()])).toContain("Every linked canonical source is present");
  });
});

/* ------------------------------------------------------------------ */
/* Recovery                                                            */
/* ------------------------------------------------------------------ */

describe("recovery never overstates an owner outcome", () => {
  it("appends the verification notice to owner success", () => {
    expect(recoveryOutcomeLabel(recovery())).toContain(VERIFICATION_NOTICE);
  });

  it("reports a failure plainly", () => {
    const label = recoveryOutcomeLabel(
      recovery({ succeeded_by_owner: false, original_status: "failed" }),
    );
    expect(label).toContain("Failed");
    expect(label).not.toContain(VERIFICATION_NOTICE);
  });

  it("warns when the link is only through the repair case", () => {
    expect(recoveryNotices(recovery({ linked_by_strategy_id: false }))).toContain(
      "This attempt is linked through the repair case, not through this exact strategy.",
    );
  });

  it("always states recovered is not resolved", () => {
    expect(recoveryNotices(recovery())).toContain(RECOVERED_NOTICE);
  });

  it("warns that a rollback is not guaranteed", () => {
    expect(
      recoveryNotices(recovery({ rollback_attempted: true, rollback_status: "completed" })).join(" "),
    ).toContain(ROLLBACK_NOTICE);
  });

  it("summarises no attempts honestly", () => {
    expect(recoverySummary([])).toContain("No linked recovery attempt");
  });

  it("summarises owner-reported success without claiming verification", () => {
    const summary = recoverySummary([recovery()]);
    expect(summary).toContain("reported successful by its owner");
    expect(summary).toContain(RECOVERED_NOTICE);
  });

  it("counts failed attempts", () => {
    expect(
      recoverySummary([
        recovery({ succeeded_by_owner: false, original_status: "failed" }),
      ]),
    ).toContain("1 failed");
  });
});

/* ------------------------------------------------------------------ */
/* Conflicts                                                           */
/* ------------------------------------------------------------------ */

describe("conflicts are surfaced and never auto-resolved", () => {
  it("collects blocking conflicts", () => {
    expect(
      blockingConflicts([conflict(), conflict({ conflict_record_id: "c2", blocks_action: true })]),
    ).toHaveLength(1);
  });

  it("reports no conflicts plainly", () => {
    expect(conflictSummary([])).toContain("No conflicting canonical records");
  });

  it("states a conflict is never resolved automatically", () => {
    expect(conflictSummary([conflict()])).toContain("never resolved automatically");
  });

  it("labels a conflict with its type and severity", () => {
    expect(conflictSeverityLabel(conflict())).toBe(
      "Destructive Flag Conflict (Warning)",
    );
  });
});

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */

describe("actions offer only the one safe available descriptor", () => {
  it("offers a descriptor the snapshot allows", () => {
    expect(availableActions([descriptor()], snapshot())).toHaveLength(1);
  });

  it("withholds a descriptor the snapshot does not allow", () => {
    expect(
      availableActions([descriptor()], snapshot({ available_action_descriptor_ids: [] })),
    ).toHaveLength(0);
  });

  it("withholds a descriptor not allowed in V1", () => {
    expect(
      availableActions([descriptor({ allowed_in_v1: false })], snapshot()),
    ).toHaveLength(0);
  });

  it("collects unavailable descriptors", () => {
    expect(
      unavailableActions([
        descriptor(),
        descriptor({
          action_descriptor_id: "repair_plan_action_approve_plan_v1",
          availability: "unavailable",
        }),
      ]),
    ).toHaveLength(1);
  });

  it("explains why an action is unavailable", () => {
    expect(
      unavailableActionNotice(
        descriptor({
          display_name: "Approve repair plan",
          availability: "unavailable",
          unavailable_reason: "No owning operation records a plan approval.",
        }),
      ),
    ).toContain("No owning operation records a plan approval.");
  });

  it("accepts a safe descriptor", () => {
    expect(descriptorIsSafeForPanel(descriptor())).toBe(true);
  });

  it.each([
    "authoritative",
    "destructive",
    "execution_capable",
    "code_modifying",
    "artifact_modifying",
    "workflow_modifying",
    "checkpoint_restoring",
    "process_restarting",
    "upload_or_publication",
  ])("rejects a descriptor that is %s", (field) => {
    expect(descriptorIsSafeForPanel(descriptor({ [field]: true }))).toBe(false);
  });

  it("blocks submission for an unsafe descriptor", () => {
    expect(
      canSubmitAction(descriptor({ execution_capable: true }), snapshot(), "", true),
    ).toBe(false);
  });

  it("blocks submission without confirmation", () => {
    expect(canSubmitAction(descriptor(), snapshot(), "", false)).toBe(false);
  });

  it("allows submission when confirmed and safe", () => {
    expect(canSubmitAction(descriptor(), snapshot(), "", true)).toBe(true);
  });

  it("blocks submission with no descriptor", () => {
    expect(canSubmitAction(null, snapshot(), "", true)).toBe(false);
  });

  it("blocks submission with no snapshot", () => {
    expect(canSubmitAction(descriptor(), null, "", true)).toBe(false);
  });

  it("requires a reason when the descriptor demands one", () => {
    expect(validateActionReason(descriptor({ requires_reason: true }), "  ")).toContain(
      "requires a reason",
    );
  });

  it("bounds the reason length", () => {
    expect(
      validateActionReason(descriptor({ maximum_reason_length: 10 }), "x".repeat(20)),
    ).toContain("at most 10 characters");
  });

  it.each([
    "password=hunter2hunter2",
    "ffmpeg -i in.mp4 out.mp4",
    "rm -rf ./generated",
    "/home/operator/media/file.mp4",
    "a && b",
  ])("rejects an unsafe reason: %s", (reason) => {
    expect(validateActionReason(descriptor(), reason)).toContain("cannot contain");
  });

  it("accepts an ordinary reason", () => {
    expect(validateActionReason(descriptor(), "A second reviewer should look.")).toBeNull();
  });

  it("lists the confirmation statement and the non-consequences", () => {
    const receiptless = descriptor();
    expect(receiptless.does_not_do.length).toBeGreaterThan(0);
    expect(CONFIRMATION_STATEMENT).toContain("restore a checkpoint");
  });
});

describe("receipts report truthfully", () => {
  it("reports a stale rejection without contacting an owner", () => {
    expect(receiptSummary(receipt({ stale_state_rejected: true }))).toContain(
      "nothing was submitted",
    );
  });

  it("reports an owner refusal", () => {
    expect(
      receiptSummary(receipt({ accepted_by_owner: false, canonical_status: "rejected_by_owner" })),
    ).toContain("did not accept");
  });

  it("reports acceptance without claiming a plan change", () => {
    const summary = receiptSummary(receipt());
    expect(summary).toContain("recorded this acknowledgement");
    expect(summary).toContain("repair plan is unchanged");
  });

  it("reports that nothing authoritative changed", () => {
    expect(receiptChangedNothing(receipt())).toBe(true);
  });

  it.each([
    "plan_approved",
    "plan_rejected",
    "plan_revised",
    "repair_executed",
    "recovery_attempt_started",
    "checkpoint_restored",
    "process_restarted",
    "workflow_changed",
    "code_changed",
    "artifact_changed",
  ])("detects a claimed %s change", (field) => {
    expect(receiptChangedNothing(receipt({ [field]: true }))).toBe(false);
  });

  it("labels no change when nothing changed", () => {
    expect(receiptChangeLabels(receipt())).toEqual(["No authoritative state changed"]);
  });

  it("labels a claimed plan approval", () => {
    expect(receiptChangeLabels(receipt({ plan_approved: true }))).toContain(
      "Plan approved",
    );
  });
});

/* ------------------------------------------------------------------ */
/* Comparison selection                                               */
/* ------------------------------------------------------------------ */

describe("comparison selection is bounded", () => {
  it("requires at least two plans", () => {
    expect(canCompare(["a"])).toBe(false);
  });

  it("allows two plans", () => {
    expect(canCompare(["a", "b"])).toBe(true);
  });

  it("allows the maximum", () => {
    expect(canCompare(["a", "b", "c", "d"])).toBe(true);
  });

  it("rejects more than the maximum", () => {
    expect(canCompare(["a", "b", "c", "d", "e"])).toBe(false);
  });

  it("adds a plan to the selection", () => {
    expect(toggleComparison(["a"], "b")).toEqual(["a", "b"]);
  });

  it("removes a plan already selected", () => {
    expect(toggleComparison(["a", "b"], "a")).toEqual(["b"]);
  });

  it("refuses to exceed the maximum", () => {
    const full = ["a", "b", "c", "d"];
    expect(toggleComparison(full, "e")).toEqual(full);
  });
});

/* ------------------------------------------------------------------ */
/* Annotations                                                        */
/* ------------------------------------------------------------------ */

describe("annotations stay review-session metadata", () => {
  it("accepts ordinary reviewer prose", () => {
    expect(annotationIsAcceptable("A second reviewer should confirm.")).toBe(true);
  });

  it("rejects empty text", () => {
    expect(annotationIsAcceptable("   ")).toBe(false);
  });

  it("rejects over-long text", () => {
    expect(annotationIsAcceptable("x".repeat(MAX_ANNOTATION_LENGTH + 1))).toBe(false);
  });

  it.each([
    "password=hunter2",
    "token=abc",
    "ffmpeg -i a.mp4 b.mp4",
    "git checkout main",
    "a; b",
    "/home/operator/x",
    "C:\\Users\\alice\\x",
  ])("rejects unsafe annotation text: %s", (text) => {
    expect(annotationIsAcceptable(text)).toBe(false);
  });

  it("builds an annotation with the non-canonical notice", () => {
    const built = buildAnnotation("strategy_a", "steps", "Looks risky.");
    expect(built?.notice).toBe(ANNOTATION_NOTICE);
  });

  it("refuses to build an unsafe annotation", () => {
    expect(buildAnnotation("strategy_a", "steps", "rm -rf /")).toBeNull();
  });

  it("bounds the annotation list", () => {
    const rows = Array.from({ length: MAX_ANNOTATIONS + 10 }, (_, index) => ({
      annotation_id: `a${index}`,
      repair_plan_id: "strategy_a",
      section_id: "steps",
      text: `note ${index}`,
      notice: "",
    }));
    expect(boundedAnnotations(rows)).toHaveLength(MAX_ANNOTATIONS);
  });

  it("re-labels every bounded annotation", () => {
    const rows = boundedAnnotations([
      {
        annotation_id: "a1",
        repair_plan_id: "strategy_a",
        section_id: "steps",
        text: "note",
        notice: "wrong",
      },
    ]);
    expect(rows[0].notice).toBe(ANNOTATION_NOTICE);
  });

  it("replaces an annotation with the same id", () => {
    const first = buildAnnotation("strategy_a", "steps", "one")!;
    const rows = upsertAnnotation([first], { ...first, text: "two" });
    expect(rows).toHaveLength(1);
    expect(rows[0].text).toBe("two");
  });

  it("removes an annotation by id", () => {
    const first = buildAnnotation("strategy_a", "steps", "one")!;
    expect(removeAnnotation([first], first.annotation_id)).toHaveLength(0);
  });
});

/* ------------------------------------------------------------------ */
/* Panel-level summary                                                */
/* ------------------------------------------------------------------ */

describe("panel summaries stay truthful", () => {
  it("always attributes the plan and states it is not executable", () => {
    const rows = planLimitations(queueItem());
    expect(rows).toContain(PROPOSED_PLAN_NOTICE);
    expect(rows).toContain(NOT_EXECUTABLE_NOTICE);
    expect(rows).toContain(NO_EXECUTION_NOTICE);
  });

  it("adds the risk-free warning for a reversible plan", () => {
    expect(planLimitations(queueItem({ reversible: true }))).toContain(REVERSIBLE_NOTICE);
  });

  it("adds the rollback warning when a rollback exists", () => {
    expect(planLimitations(queueItem({ rollback_available: true }))).toContain(
      ROLLBACK_NOTICE,
    );
  });

  it("adds the recovered warning for a completed plan", () => {
    expect(planLimitations(queueItem({ completed: true }))).toContain(RECOVERED_NOTICE);
  });

  it("adds the command warning when a step holds command text", () => {
    expect(planLimitations(queueItem({ command_bearing_step_count: 1 }))).toContain(
      COMMAND_WITHHELD_NOTICE,
    );
  });

  it("reports no outstanding work honestly", () => {
    expect(safestNextReviewAction([])).toContain("No repair-plan review work");
  });

  it("names the highest-priority plan to read first", () => {
    expect(
      safestNextReviewAction([
        queueItem({ repair_plan_id: "low", priority_tier: 110 }),
        queueItem({ repair_plan_id: "high", priority_tier: 10 }),
      ]),
    ).toContain("high");
  });

  it("never tells a reviewer to execute anything", () => {
    const text = safestNextReviewAction([queueItem()]);
    expect(text.toLowerCase()).not.toContain("execute");
    expect(text.toLowerCase()).not.toContain("run ");
  });
});

describe("reference notices are honest about missing owner fields", () => {
  it("returns no schema notice for a supported schema", () => {
    expect(unsupportedSchemaNotice(reference())).toBeNull();
  });

  it("explains an unsupported schema", () => {
    expect(
      unsupportedSchemaNotice(
        reference({ schema_supported: false, source_schema_id: "other_v9" }),
      ),
    ).toContain("other_v9");
  });

  it("states that no revision identity exists", () => {
    expect(revisionNotice(reference())).toContain("no strategy revision identity");
  });
});
