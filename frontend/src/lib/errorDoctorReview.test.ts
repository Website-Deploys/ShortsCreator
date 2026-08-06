import { describe, expect, it } from "vitest";

import {
  CONFIDENCE_NOTICE,
  LOCAL_ANNOTATION_NOTICE,
  MAX_ANNOTATIONS,
  MAX_ANNOTATION_LENGTH,
  MAX_COMPARISON_INCIDENTS,
  MAX_EXPANDED_LOG_CARDS,
  MAX_EXPANDED_SOURCE_CARDS,
  MAX_TIMELINE_ENTRIES,
  NO_EXECUTION_NOTICE,
  NO_WINNER_NOTICE,
  QUEUE_PAGE_SIZE,
  RECOVERED_NOTICE,
  REPAIR_EXECUTION_NOTICE,
  ROOT_CAUSE_NOTICE,
  SOURCE_SEVERITY_ORDER,
  SUPPORTED_INCIDENT_SCHEMA_ID,
  availableActions,
  boundedLogCardIds,
  boundedSourceCardIds,
  buildAnnotation,
  canCompare,
  canSubmitAction,
  classificationIsFact,
  classificationLabel,
  confidenceLabel,
  confirmationText,
  conflictResolutionLabel,
  conflictSummary,
  describeEvidenceCard,
  errorCodeLabel,
  evidenceSummary,
  excerptNotices,
  filterIncidents,
  formatTimestamp,
  incidentStateLabel,
  ownerStatusLabel,
  priorityLabel,
  receiptChangeLabels,
  receiptChangedAuthority,
  receiptSummary,
  recoveryChangeLabels,
  recoveryOutcomeLabel,
  recoverySummary,
  removeAnnotation,
  repairOwnerRankLabel,
  repairRequirements,
  repairRiskLabel,
  revisionNotice,
  rootCauseHeading,
  severityLabel,
  severityRank,
  sortIncidents,
  toggleComparison,
  unavailableActionNotice,
  unsupportedSchemaNotice,
  upsertAnnotation,
  validateActionReason,
  withheldActions,
  type DiagnosisProjection,
  type ErrorConflict,
  type ErrorDoctorActionDescriptor,
  type ErrorDoctorActionReceipt,
  type ErrorEvidenceCard,
  type IncidentQueueItem,
  type IncidentReference,
  type IncidentSnapshot,
  type RecoveryAttemptProjection,
  type RepairPlanProjection,
  type RootCauseProjection,
} from "@/lib/errorDoctorReview";

const ACK = "error_doctor_action_acknowledge_incident_v1";

function item(overrides: Partial<IncidentQueueItem> = {}): IncidentQueueItem {
  return {
    incident_queue_item_id: "queue_a",
    incident_reference_id: "ref_a",
    project_id: "proj",
    workflow_run_id: "run_1",
    stage_instance_id: "stage_1",
    incident_id: "case_a",
    title: "Rendering stage failed",
    bounded_summary: "The render stage stopped.",
    affected_module_id: "rendering",
    affected_operation_id: "",
    affected_stage_id: "render",
    original_error_class: "rendering",
    original_error_code: null,
    original_severity: "high",
    original_status: "probable",
    diagnosis_status: "probable",
    root_cause_status: "probable_root_cause",
    repair_plan_status: "human_decision_required",
    recovery_status: "failed",
    validation_status: "available",
    artifact_status: "available",
    workflow_status: "blocked",
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    recovered: false,
    resolved: false,
    recurring: false,
    human_action_required: true,
    blocker_count: 1,
    warning_count: 0,
    missing_evidence_count: 3,
    conflict_count: 1,
    failed_recovery_attempt_count: 2,
    available_action_descriptor_ids: [ACK],
    source_module_ids: ["error_doctor"],
    priority_tier: 30,
    priority_reason: "current_incident_with_failed_or_partial_recovery",
    deterministic_sort_key: "030:02:0000:case_a",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function reference(overrides: Partial<IncidentReference> = {}): IncidentReference {
  return {
    incident_reference_id: "ref_a",
    project_id: "proj",
    workflow_run_id: "run_1",
    stage_instance_id: "stage_1",
    incident_id: "case_a",
    incident_revision_id: null,
    source_schema_id: SUPPORTED_INCIDENT_SCHEMA_ID,
    schema_supported: true,
    affected_module_id: "rendering",
    affected_operation_id: "",
    affected_stage_id: "render",
    error_class: "rendering",
    error_code: null,
    original_severity: "high",
    original_status: "probable",
    first_seen_at: "2026-02-01T10:00:00+00:00",
    last_seen_at: "2026-02-01T10:05:00+00:00",
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    superseding_incident_id: null,
    recovered: false,
    resolved: false,
    warnings: [],
    limitations: ["Error Doctor records no error code, so none is shown."],
    ...overrides,
  };
}

function diagnosis(overrides: Partial<DiagnosisProjection> = {}): DiagnosisProjection {
  return {
    diagnosis_projection_id: "diag_a",
    source_module_id: "error_doctor",
    diagnosis_id: "case_a",
    diagnosis_revision_id: null,
    original_status: "probable",
    original_category: "rendering",
    original_error_class: "rendering",
    original_error_code: null,
    original_summary: "The render stage stopped.",
    bounded_technical_explanation: "Observer recorded a missing output artifact.",
    bounded_easy_explanation: "The render did not produce a file.",
    confirmed_fact_ids: ["fact_a"],
    assessment_ids: ["assessment_a"],
    hypothesis_ids: ["hypothesis_a"],
    confidence_value: 0.74,
    confidence_name: "error_doctor_case_confidence",
    confidence_definition: "The owner does not define it as a probability.",
    confidence_scale_min: 0,
    confidence_scale_max: 1,
    confidence_comparable_across_sources: false,
    current: true,
    stale: false,
    historical: false,
    sensitive_values_redacted: false,
    private_paths_redacted: false,
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function rootCause(overrides: Partial<RootCauseProjection> = {}): RootCauseProjection {
  return {
    root_cause_projection_id: "rc_a",
    source_module_id: "root_cause_analyzer",
    root_cause_id: "candidate_0",
    original_status: "probable_root_cause",
    original_classification: "configuration_defect",
    original_summary: "The encoder rejected the format.",
    confirmed: false,
    hypothesis: true,
    evidence_record_ids: ["evidence_a"],
    contradictory_evidence_record_ids: ["evidence_b"],
    confidence_value: 0.6,
    confidence_name: "root_cause_candidate_confidence",
    confidence_definition: "The owner does not define it as a probability.",
    likelihood_value: 0.7,
    likelihood_name: "root_cause_candidate_likelihood_score",
    evidence_quality: "moderate",
    repairability: "repairable_with_approval",
    recommended_owner_module_id: "repair_planner",
    current: true,
    stale: false,
    human_confirmation_required: true,
    bounded_explanation: "Candidate 0 explanation.",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function card(overrides: Partial<ErrorEvidenceCard> = {}): ErrorEvidenceCard {
  return {
    evidence_card_id: "card_a",
    evidence_type: "observer_finding",
    source_module_id: "observer",
    authority_domain: "observation",
    source_record_id: "finding_a",
    source_record_digest: "d".repeat(64),
    title: "Observer finding finding_a",
    original_status: "critical",
    original_decision: null,
    classification: "confirmed_fact",
    confirmed_fact: "The output artifact is missing.",
    assessment: "",
    hypothesis: "",
    bounded_summary: "The output artifact is missing.",
    bounded_excerpt: "Missing output near [private-path]",
    excerpt_truncated: false,
    sensitive_values_redacted: true,
    private_paths_redacted: true,
    current: true,
    stale: false,
    historical: false,
    missing: false,
    authoritative: true,
    advisory_only: false,
    blocking: false,
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function repairPlan(overrides: Partial<RepairPlanProjection> = {}): RepairPlanProjection {
  return {
    repair_plan_projection_id: "rp_a",
    source_module_id: "repair_planner",
    repair_plan_id: "strategy_a",
    original_status: "human_decision_required",
    original_strategy: "retry_with_safe_settings",
    original_summary: "Retry the encode with conservative settings.",
    affected_module_ids: ["rendering"],
    proposed_step_count: 2,
    proposed_step_summaries: ["inspect: Inspect the encoder health record."],
    requires_code_change: false,
    requires_artifact_change: false,
    requires_tool_execution: true,
    requires_process_restart: false,
    requires_checkpoint_restore: false,
    requires_workflow_transition: false,
    requires_human_approval: true,
    destructive: false,
    reversible: true,
    rollback_available: true,
    verification_required: true,
    source_owned_rank: 1,
    source_owned_score: 0.62,
    source_owned_score_name: "repair_planner_strategy_score",
    source_marked_recommended: true,
    current: true,
    stale: false,
    executable_by_panel: false,
    raw_command_exposed: false,
    bounded_explanation: "Try the render again with safer settings.",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function attempt(
  overrides: Partial<RecoveryAttemptProjection> = {},
): RecoveryAttemptProjection {
  return {
    recovery_attempt_projection_id: "ra_a",
    source_module_id: "tool_recovery",
    recovery_attempt_id: "attempt_1",
    repair_plan_id: "strategy_a",
    attempt_number: 1,
    original_status: "succeeded_pending_validation",
    started_at: "2026-02-01T10:05:00+00:00",
    completed_at: "2026-02-01T10:06:00+00:00",
    attempted: true,
    completed: true,
    succeeded_by_owner: true,
    verified: false,
    verification_source_ids: [],
    changed_code: false,
    changed_artifacts: false,
    changed_workflow: false,
    invoked_tool: "ffmpeg_local",
    invoked_operation_id: "video_encode",
    rollback_attempted: false,
    rollback_status: "unavailable",
    original_error_code: null,
    resulting_error_code: "unknown",
    exit_code: 0,
    timed_out: false,
    bounded_summary: "The encoder exited with [redacted]",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function conflict(overrides: Partial<ErrorConflict> = {}): ErrorConflict {
  return {
    conflict_record_id: "conflict_a",
    conflict_type: "stage_identity_conflict",
    severity: "critical",
    value_a: "render",
    value_b: "encode",
    same_incident: true,
    same_workflow_run: true,
    current_records: true,
    explicit_supersession_found: false,
    resolved: false,
    resolution_source_id: null,
    blocks_action: true,
    human_review_required: true,
    bounded_summary: "Two modules name different stages.",
    warnings: [],
    limitations: ["Conflicts are never resolved by comparing confidence."],
    ...overrides,
  };
}

function snapshot(overrides: Partial<IncidentSnapshot> = {}): IncidentSnapshot {
  return {
    incident_snapshot_id: "snap_a",
    error_doctor_review_session_id: "session_a",
    project_id: "proj",
    incident_id: "case_a",
    incident_digest: "a".repeat(64),
    snapshot_digest: "b".repeat(64),
    incident_status: "probable",
    diagnosis_status: "probable",
    root_cause_status: "probable_root_cause",
    repair_plan_status: "human_decision_required",
    recovery_status: "succeeded_pending_validation",
    validation_status: "unavailable",
    artifact_status: "unavailable",
    workflow_status: "unavailable",
    rights_status: "unavailable",
    safety_status: "unavailable",
    final_decision_status: "unavailable",
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    recovered: true,
    resolved: false,
    missing_evidence_count: 10,
    conflict_count: 1,
    available_action_descriptor_ids: [ACK],
    limitations: [],
    ...overrides,
  };
}

function descriptor(
  overrides: Partial<ErrorDoctorActionDescriptor> = {},
): ErrorDoctorActionDescriptor {
  return {
    action_descriptor_id: ACK,
    display_name: "Acknowledge incident",
    action_class: "ui_metadata_acknowledgement",
    owning_module_id: "review_ui",
    owning_operation_id: "acknowledge_notification",
    supported_incident_states: ["current"],
    allowed_decision_values: ["acknowledged"],
    requires_reason: false,
    maximum_reason_length: 500,
    requires_confirmation: true,
    requires_current_snapshot: false,
    requires_reviewer_context: true,
    requires_safety_gate: false,
    requires_final_decision_bus: false,
    authoritative: false,
    destructive: false,
    execution_capable: false,
    code_modifying: false,
    artifact_modifying: false,
    workflow_modifying: false,
    upload_or_publication: false,
    allowed_in_v1: true,
    availability: "available",
    consequences: ["Records the incident in the Review UI acknowledged list."],
    does_not_do: ["Does not resolve, dismiss or close the incident."],
    warnings: [],
    limitations: ["Acknowledgement is review-session metadata."],
    ...overrides,
  };
}

function receipt(
  overrides: Partial<ErrorDoctorActionReceipt> = {},
): ErrorDoctorActionReceipt {
  return {
    error_doctor_action_receipt_id: "receipt_a",
    owning_module_id: "review_ui",
    owning_operation_id: "acknowledge_notification",
    accepted_by_owner: true,
    canonical_status: "acknowledged",
    canonical_record_id: "review_session_1",
    canonical_record_digest: "c".repeat(64),
    authoritative_state_changed: false,
    repair_executed: false,
    recovery_attempt_started: false,
    workflow_changed: false,
    code_changed: false,
    artifact_changed: false,
    stale_state_rejected: false,
    duplicate_request_reused: false,
    error_code: null,
    bounded_error_message: "",
    limitations: [],
    ...overrides,
  };
}

describe("bounds and notices", () => {
  it("pins the comparison ceiling", () => {
    expect(MAX_COMPARISON_INCIDENTS).toBe(4);
  });

  it("pins the queue page size", () => {
    expect(QUEUE_PAGE_SIZE).toBe(50);
  });

  it("pins the annotation bounds", () => {
    expect(MAX_ANNOTATION_LENGTH).toBe(4_000);
    expect(MAX_ANNOTATIONS).toBe(32);
  });

  it("pins the expanded log and source card ceilings", () => {
    expect(MAX_EXPANDED_LOG_CARDS).toBe(10);
    expect(MAX_EXPANDED_SOURCE_CARDS).toBe(20);
  });

  it("pins the timeline page size", () => {
    expect(MAX_TIMELINE_ENTRIES).toBe(100);
  });

  it("names the supported owner schema exactly", () => {
    expect(SUPPORTED_INCIDENT_SCHEMA_ID).toBe("boba_error_doctor_v1");
  });

  it("states that no execution action exists", () => {
    expect(NO_EXECUTION_NOTICE).toContain("no repair, recovery, tool-retry, checkpoint");
    expect(NO_EXECUTION_NOTICE).toContain("never uploads or publishes");
  });

  it("states that repair execution is unavailable", () => {
    expect(REPAIR_EXECUTION_NOTICE).toBe(
      "Repair execution unavailable in Error Doctor Panel V1.",
    );
  });

  it("states that recovered is not resolved", () => {
    expect(RECOVERED_NOTICE).toContain("Recovered is not resolved");
    expect(RECOVERED_NOTICE).toContain("not independent");
  });

  it("states that confidence is never averaged", () => {
    expect(CONFIDENCE_NOTICE).toContain("never averaged or compared");
  });

  it("states that no root cause is confirmed", () => {
    expect(ROOT_CAUSE_NOTICE).toContain("never presents a candidate as a confirmed");
  });

  it("states that comparison chooses nothing", () => {
    expect(NO_WINNER_NOTICE).toContain("No incident, root cause or repair plan is");
  });

  it("uses the exact non-canonical annotation notice", () => {
    expect(LOCAL_ANNOTATION_NOTICE).toBe(
      "Review-session annotation — not part of the canonical incident, diagnosis or " +
        "repair record.",
    );
  });

  it("keeps the owner severity vocabulary", () => {
    expect(SOURCE_SEVERITY_ORDER[0]).toBe("blocker");
    expect(SOURCE_SEVERITY_ORDER).toHaveLength(7);
  });
});

describe("formatting and owner labels", () => {
  it("reports a missing timestamp honestly", () => {
    expect(formatTimestamp(null)).toBe("time not recorded by the owner");
  });

  it("shows a recorded timestamp verbatim", () => {
    expect(formatTimestamp("2026-02-01T10:00:00+00:00")).toBe("2026-02-01T10:00:00+00:00");
  });

  it("ranks known severities by owner order", () => {
    expect(severityRank("blocker")).toBeLessThan(severityRank("low"));
  });

  it("ranks an unknown severity last", () => {
    expect(severityRank("made_up")).toBe(SOURCE_SEVERITY_ORDER.length);
  });

  it("labels a known severity as owner owned", () => {
    expect(severityLabel("high")).toBe("Owner severity: high");
  });

  it("says an unrecognised severity was not recorded", () => {
    expect(severityLabel("made_up")).toBe("Owner severity: not recorded");
  });

  it("attributes a status to its owning module", () => {
    expect(ownerStatusLabel("validator_runner", "failed")).toBe(
      "validator_runner reports failed",
    );
  });

  it("says an unavailable module supplied no record", () => {
    expect(ownerStatusLabel("safety_gate", "unavailable")).toBe(
      "safety_gate has supplied no record",
    );
  });

  it("labels a current incident", () => {
    expect(incidentStateLabel(item())).toBe("Current");
  });

  it("labels a recovered incident as not resolved", () => {
    expect(incidentStateLabel(item({ recovered: true }))).toBe("Recovered, not resolved");
  });

  it("labels a resolved incident", () => {
    expect(incidentStateLabel(item({ resolved: true }))).toBe("Resolved");
  });

  it("labels a stale incident", () => {
    expect(incidentStateLabel(item({ stale: true }))).toBe("Stale");
  });

  it("labels a historical incident", () => {
    expect(incidentStateLabel(item({ historical: true }))).toBe("Historical");
  });

  it("labels a superseded incident first", () => {
    expect(incidentStateLabel(item({ superseded: true, stale: true }))).toBe("Superseded");
  });

  it("reports the owner priority tier and reason", () => {
    expect(priorityLabel(item())).toBe(
      "Tier 30: current_incident_with_failed_or_partial_recovery",
    );
  });
});

describe("facts, assessments and hypotheses", () => {
  it("labels a confirmed fact", () => {
    expect(classificationLabel("confirmed_fact")).toBe("Confirmed fact");
  });

  it("labels a source assessment", () => {
    expect(classificationLabel("source_owned_assessment")).toBe("Source assessment");
  });

  it("labels a source hypothesis", () => {
    expect(classificationLabel("source_owned_hypothesis")).toBe("Source hypothesis");
  });

  it("labels an unresolved claim", () => {
    expect(classificationLabel("unresolved_claim")).toBe("Unresolved claim");
  });

  it("labels an unavailable classification", () => {
    expect(classificationLabel("unavailable")).toBe("Unavailable");
  });

  it("treats only a confirmed fact as a fact", () => {
    expect(classificationIsFact("confirmed_fact")).toBe(true);
    expect(classificationIsFact("source_owned_hypothesis")).toBe(false);
    expect(classificationIsFact("source_owned_assessment")).toBe(false);
  });

  it("heads an unconfirmed candidate as a hypothesis", () => {
    expect(rootCauseHeading(rootCause())).toBe("Root-cause hypothesis");
  });

  it("heads a confirmed candidate as a confirmed root cause", () => {
    expect(rootCauseHeading(rootCause({ confirmed: true, hypothesis: false }))).toBe(
      "Confirmed root cause",
    );
  });

  it("reports a missing confidence value honestly", () => {
    expect(confidenceLabel(null, "n", "d")).toBe("The owner recorded no confidence value.");
  });

  it("shows a confidence value with its owner scale and definition", () => {
    const label = confidenceLabel(0.6, "candidate_confidence", "Not a probability.");
    expect(label).toContain("candidate_confidence = 0.6 (owner scale)");
    expect(label).toContain("Not a probability.");
  });
});

describe("queue filtering", () => {
  const rows = [
    item(),
    item({
      incident_id: "case_b",
      incident_queue_item_id: "queue_b",
      original_severity: "critical",
      priority_tier: 20,
      failed_recovery_attempt_count: 0,
      conflict_count: 0,
      missing_evidence_count: 0,
      human_action_required: false,
      root_cause_status: "unavailable",
      repair_plan_status: "unavailable",
      recurring: true,
    }),
    item({
      incident_id: "case_c",
      incident_queue_item_id: "queue_c",
      historical: true,
      superseded: true,
      recovered: true,
      resolved: true,
      priority_tier: 140,
    }),
  ];
  const state = {
    filter: "all_current" as const,
    showRecovered: true,
    showResolved: true,
    showHistorical: false,
  };

  it("hides historical incidents by default", () => {
    const result = filterIncidents(rows, state);
    expect(result.map((row) => row.incident_id)).toEqual(["case_a", "case_b"]);
  });

  it("includes historical incidents when asked", () => {
    const result = filterIncidents(rows, { ...state, showHistorical: true });
    expect(result).toHaveLength(3);
  });

  it("hides recovered incidents when the toggle is off", () => {
    const result = filterIncidents(rows, {
      ...state,
      showHistorical: true,
      showRecovered: false,
    });
    expect(result.map((row) => row.incident_id)).toEqual(["case_a", "case_b"]);
  });

  it("hides resolved incidents when the toggle is off", () => {
    const result = filterIncidents(rows, {
      ...state,
      showHistorical: true,
      showResolved: false,
    });
    expect(result.every((row) => !row.resolved)).toBe(true);
  });

  it("filters to critical incidents", () => {
    const result = filterIncidents(rows, { ...state, filter: "critical" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_b"]);
  });

  it("filters to workflow-blocking incidents", () => {
    const result = filterIncidents(rows, { ...state, filter: "workflow_blocking" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_b"]);
  });

  it("filters to incidents needing human review", () => {
    const result = filterIncidents(rows, { ...state, filter: "human_review_required" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_a"]);
  });

  it("filters to incidents missing a root cause", () => {
    const result = filterIncidents(rows, { ...state, filter: "missing_root_cause" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_b"]);
  });

  it("filters to incidents with a repair plan", () => {
    const result = filterIncidents(rows, { ...state, filter: "repair_plan_available" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_a"]);
  });

  it("filters to incidents with a failed recovery", () => {
    const result = filterIncidents(rows, { ...state, filter: "failed_recovery" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_a"]);
  });

  it("filters to recurring incidents", () => {
    const result = filterIncidents(rows, { ...state, filter: "recurring" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_b"]);
  });

  it("filters to incidents with conflicts", () => {
    const result = filterIncidents(rows, { ...state, filter: "conflicts" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_a"]);
  });

  it("filters to incidents with missing evidence", () => {
    const result = filterIncidents(rows, { ...state, filter: "missing_evidence" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_a"]);
  });

  it("filters to recovered incidents regardless of the toggle", () => {
    const result = filterIncidents(rows, {
      ...state,
      filter: "recovered",
      showRecovered: false,
    });
    expect(result.map((row) => row.incident_id)).toEqual(["case_c"]);
  });

  it("filters to resolved incidents", () => {
    const result = filterIncidents(rows, { ...state, filter: "resolved" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_c"]);
  });

  it("filters to historical incidents", () => {
    const result = filterIncidents(rows, { ...state, filter: "historical" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_c"]);
  });

  it("filters to superseded incidents", () => {
    const result = filterIncidents(rows, { ...state, filter: "superseded" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_c"]);
  });

  it("filters to incidents missing a diagnosis", () => {
    const rowsWithMissing = [...rows, item({ incident_id: "case_d", priority_tier: 50 })];
    const result = filterIncidents(rowsWithMissing, {
      ...state,
      filter: "missing_diagnosis",
    });
    expect(result.map((row) => row.incident_id)).toEqual(["case_d"]);
  });

  it("filters to unverified recovery", () => {
    const rowsWithUnverified = [
      ...rows,
      item({ incident_id: "case_e", priority_tier: 110 }),
    ];
    const result = filterIncidents(rowsWithUnverified, {
      ...state,
      filter: "unverified_recovery",
    });
    expect(result.map((row) => row.incident_id)).toEqual(["case_e"]);
  });

  it("filters to stale incidents", () => {
    const rowsWithStale = [...rows, item({ incident_id: "case_f", stale: true })];
    const result = filterIncidents(rowsWithStale, { ...state, filter: "stale" });
    expect(result.map((row) => row.incident_id)).toEqual(["case_f"]);
  });
});

describe("queue sorting", () => {
  const rows = [
    item({ incident_id: "case_b", priority_tier: 90, deterministic_sort_key: "090:b", original_severity: "low", affected_stage_id: "encode", affected_module_id: "captions" }),
    item({ incident_id: "case_a", priority_tier: 30, deterministic_sort_key: "030:a", original_severity: "critical", affected_stage_id: "render", affected_module_id: "rendering" }),
  ];

  it("sorts by review priority tier", () => {
    expect(sortIncidents(rows, "review_priority").map((row) => row.incident_id)).toEqual([
      "case_a",
      "case_b",
    ]);
  });

  it("sorts by owner severity", () => {
    expect(sortIncidents(rows, "source_severity").map((row) => row.incident_id)).toEqual([
      "case_a",
      "case_b",
    ]);
  });

  it("sorts by first seen", () => {
    expect(sortIncidents(rows, "first_seen").map((row) => row.incident_id)).toEqual([
      "case_a",
      "case_b",
    ]);
  });

  it("sorts by last seen in reverse", () => {
    expect(sortIncidents(rows, "last_seen").map((row) => row.incident_id)).toEqual([
      "case_b",
      "case_a",
    ]);
  });

  it("sorts by affected stage", () => {
    expect(sortIncidents(rows, "affected_stage").map((row) => row.incident_id)).toEqual([
      "case_b",
      "case_a",
    ]);
  });

  it("sorts by affected module", () => {
    expect(sortIncidents(rows, "affected_module").map((row) => row.incident_id)).toEqual([
      "case_b",
      "case_a",
    ]);
  });

  it("sorts by incident id", () => {
    expect(sortIncidents(rows, "incident_id").map((row) => row.incident_id)).toEqual([
      "case_a",
      "case_b",
    ]);
  });

  it("never mutates the input order", () => {
    const original = rows.map((row) => row.incident_id);
    sortIncidents(rows, "incident_id");
    expect(rows.map((row) => row.incident_id)).toEqual(original);
  });

  it("is stable across repeated calls", () => {
    expect(sortIncidents(rows, "review_priority")).toEqual(
      sortIncidents(rows, "review_priority"),
    );
  });
});

describe("evidence presentation", () => {
  it("says all evidence is present when nothing is missing", () => {
    expect(evidenceSummary(item({ missing_evidence_count: 0 }))).toBe(
      "All linked source evidence is present.",
    );
  });

  it("states that missing evidence is not a pass", () => {
    expect(evidenceSummary(item())).toContain("Missing evidence is not a pass");
  });

  it("uses the singular noun for one missing source", () => {
    expect(evidenceSummary(item({ missing_evidence_count: 1 }))).toContain("1 source missing");
  });

  it("describes an available authoritative card", () => {
    expect(describeEvidenceCard(card())).toBe("Observer finding finding_a: critical");
  });

  it("marks an advisory card as not a decision", () => {
    expect(describeEvidenceCard(card({ advisory_only: true }))).toContain(
      "advisory, not a decision",
    );
  });

  it("states that a missing card has no record", () => {
    expect(describeEvidenceCard(card({ missing: true }))).toContain(
      "no canonical record is available",
    );
  });

  it("announces redaction and truncation", () => {
    const notices = excerptNotices(card({ excerpt_truncated: true }));
    expect(notices).toContain("Sensitive values redacted");
    expect(notices).toContain("Private path details redacted");
    expect(notices).toContain("Excerpt truncated");
  });

  it("always states that the owner keeps the full record", () => {
    expect(excerptNotices(card())).toContain("Full record retained by the owning module");
  });

  it("bounds expanded log cards", () => {
    const ids = Array.from({ length: 40 }, (_value, index) => `card_${index}`);
    expect(boundedLogCardIds(ids)).toHaveLength(MAX_EXPANDED_LOG_CARDS);
  });

  it("bounds expanded source cards", () => {
    const ids = Array.from({ length: 40 }, (_value, index) => `card_${index}`);
    expect(boundedSourceCardIds(ids)).toHaveLength(MAX_EXPANDED_SOURCE_CARDS);
  });
});

describe("repair plan presentation", () => {
  it("lists the owner requirements", () => {
    const rows = repairRequirements(repairPlan());
    expect(rows).toContain("Requires tool execution");
    expect(rows).toContain("Requires human approval");
  });

  it("reports a proposed code change", () => {
    expect(repairRequirements(repairPlan({ requires_code_change: true }))).toContain(
      "Proposes a code change",
    );
  });

  it("reports a proposed artifact change", () => {
    expect(repairRequirements(repairPlan({ requires_artifact_change: true }))).toContain(
      "May change artifacts",
    );
  });

  it("reports a proposed process restart", () => {
    expect(repairRequirements(repairPlan({ requires_process_restart: true }))).toContain(
      "Proposes a process restart",
    );
  });

  it("reports a proposed checkpoint restore", () => {
    expect(
      repairRequirements(repairPlan({ requires_checkpoint_restore: true })),
    ).toContain("Proposes checkpoint restoration");
  });

  it("reports a proposed workflow transition", () => {
    expect(
      repairRequirements(repairPlan({ requires_workflow_transition: true })),
    ).toContain("Proposes a workflow transition");
  });

  it("summarises risk from owner values", () => {
    expect(repairRiskLabel(repairPlan())).toBe(
      "non-destructive, reversible, rollback available",
    );
  });

  it("summarises a destructive irreversible plan", () => {
    expect(
      repairRiskLabel(
        repairPlan({ destructive: true, reversible: false, rollback_available: false }),
      ),
    ).toBe("destructive, not reversible, no rollback plan");
  });

  it("attributes rank and score to Repair Planner", () => {
    const label = repairOwnerRankLabel(repairPlan());
    expect(label).toContain("Repair Planner recorded rank 1");
    expect(label).toContain("The panel adds no score.");
  });

  it("says when the owner recorded no rank or score", () => {
    expect(
      repairOwnerRankLabel(
        repairPlan({ source_owned_rank: null, source_owned_score: null }),
      ),
    ).toBe("Repair Planner recorded no rank or score.");
  });

  it("never exposes command text in step summaries", () => {
    const plan = repairPlan();
    expect(plan.proposed_step_summaries.join(" ")).not.toContain("ffmpeg");
    expect(plan.raw_command_exposed).toBe(false);
    expect(plan.executable_by_panel).toBe(false);
  });
});

describe("recovery presentation", () => {
  it("reports a not-attempted recovery", () => {
    expect(recoveryOutcomeLabel(attempt({ attempted: false }))).toBe("Not attempted");
  });

  it("separates owner success from verification", () => {
    expect(recoveryOutcomeLabel(attempt())).toBe(
      "Owner reports success, not independently verified",
    );
  });

  it("reports verified recovery only when verification passed", () => {
    expect(recoveryOutcomeLabel(attempt({ verified: true }))).toBe(
      "Owner reported success and verification passed",
    );
  });

  it("reports completion without owner-reported success", () => {
    expect(
      recoveryOutcomeLabel(attempt({ succeeded_by_owner: false, completed: true })),
    ).toBe("Completed without owner-reported success");
  });

  it("reports an attempted failure with its owner status", () => {
    expect(
      recoveryOutcomeLabel(
        attempt({ succeeded_by_owner: false, completed: false, original_status: "failed" }),
      ),
    ).toContain("Attempted, owner status failed");
  });

  it("never infers a code change", () => {
    expect(recoveryChangeLabels(attempt())).toContain(
      "No code change disclosed by the owner",
    );
  });

  it("reports a disclosed code change", () => {
    expect(recoveryChangeLabels(attempt({ changed_code: true }))).toContain(
      "Owner disclosed a code change",
    );
  });

  it("never infers an artifact change", () => {
    expect(recoveryChangeLabels(attempt())).toContain(
      "No artifact change disclosed by the owner",
    );
  });

  it("never infers a workflow change", () => {
    expect(recoveryChangeLabels(attempt())).toContain(
      "No workflow change disclosed by the owner",
    );
  });

  it("says when no attempt exists", () => {
    expect(recoverySummary([])).toBe(
      "No recovery attempt is recorded for this incident.",
    );
  });

  it("counts failures and verifications separately", () => {
    const summary = recoverySummary([
      attempt({ original_status: "failed", succeeded_by_owner: false }),
      attempt({ verified: true }),
    ]);
    expect(summary).toContain("2 attempt(s), 1 failed, 1 independently verified");
    expect(summary).toContain("Recovered is not resolved");
  });
});

describe("conflicts", () => {
  it("reports no conflict on a clean incident", () => {
    expect(conflictSummary([])).toBe(
      "No conflict was detected against canonical sources.",
    );
  });

  it("counts blocking conflicts", () => {
    expect(conflictSummary([conflict()])).toContain("1 conflict(s), 1 blocking");
  });

  it("states that confidence never resolves a conflict", () => {
    expect(conflictSummary([conflict()])).toContain("comparing confidence");
  });

  it("labels an unresolved conflict", () => {
    expect(conflictResolutionLabel(conflict())).toBe(
      "Unresolved. Only the owning module can resolve this.",
    );
  });

  it("names the owning module when it resolved the conflict", () => {
    expect(
      conflictResolutionLabel(
        conflict({ resolved: true, resolution_source_id: "root_cause_analyzer" }),
      ),
    ).toBe("Resolved by root_cause_analyzer.");
  });
});

describe("comparison", () => {
  it("adds an incident up to the ceiling", () => {
    expect(toggleComparison(["case_a"], "case_b")).toEqual(["case_a", "case_b"]);
  });

  it("removes a selected incident", () => {
    expect(toggleComparison(["case_a", "case_b"], "case_a")).toEqual(["case_b"]);
  });

  it("refuses to exceed the comparison ceiling", () => {
    const full = ["a", "b", "c", "d"];
    expect(toggleComparison(full, "e")).toEqual(full);
  });

  it("requires at least two incidents", () => {
    expect(canCompare(["case_a"])).toBe(false);
    expect(canCompare(["case_a", "case_b"])).toBe(true);
  });

  it("refuses more than four incidents", () => {
    expect(canCompare(["a", "b", "c", "d", "e"])).toBe(false);
  });
});

describe("actions", () => {
  it("offers an action only with a snapshot and a token", () => {
    expect(
      availableActions([descriptor()], snapshot(), { [ACK]: "token" }),
    ).toHaveLength(1);
  });

  it("withholds an action without a token", () => {
    expect(availableActions([descriptor()], snapshot(), {})).toHaveLength(0);
    expect(withheldActions([descriptor()], snapshot(), {})).toHaveLength(1);
  });

  it("withholds an action the snapshot did not offer", () => {
    expect(
      availableActions([descriptor()], snapshot({ available_action_descriptor_ids: [] }), {
        [ACK]: "token",
      }),
    ).toHaveLength(0);
  });

  it("withholds an unavailable descriptor", () => {
    expect(
      availableActions(
        [descriptor({ availability: "unavailable", allowed_in_v1: false })],
        snapshot(),
        { [ACK]: "token" },
      ),
    ).toHaveLength(0);
  });

  it("withholds every action without a snapshot", () => {
    expect(availableActions([descriptor()], null, { [ACK]: "t" })).toHaveLength(0);
  });

  it("explains why an unavailable action is unavailable", () => {
    const withheld = descriptor({
      availability: "unavailable",
      allowed_in_v1: false,
      limitations: ["No canonical repair approval operation exists."],
    });
    expect(unavailableActionNotice(withheld)).toBe(
      "No canonical repair approval operation exists.",
    );
  });

  it("offers no substitute authority when no reason was stated", () => {
    const withheld = descriptor({
      availability: "unavailable",
      allowed_in_v1: false,
      limitations: [],
    });
    expect(unavailableActionNotice(withheld)).toContain("No canonical owner operation");
  });

  it("returns no notice for an available action", () => {
    expect(unavailableActionNotice(descriptor())).toBe("");
  });

  it("accepts an empty reason when the owner does not require one", () => {
    expect(validateActionReason("", descriptor())).toBeNull();
  });

  it("requires a reason when the owner requires one", () => {
    expect(validateActionReason("  ", descriptor({ requires_reason: true }))).toContain(
      "reason is required",
    );
  });

  it("bounds the reason length", () => {
    expect(validateActionReason("x".repeat(501), descriptor())).toContain(
      "500 characters or fewer",
    );
  });

  it("refuses a reason carrying credentials", () => {
    expect(validateActionReason("the api_token is abc", descriptor())).toContain(
      "cannot contain credentials",
    );
  });

  it("refuses a reason carrying a private path", () => {
    expect(validateActionReason("see /home/me/notes.txt", descriptor())).toContain(
      "private path details",
    );
  });

  it("blocks submission until the reviewer confirms", () => {
    expect(
      canSubmitAction(descriptor(), snapshot(), { [ACK]: "t" }, "", "acknowledged", false),
    ).toBe(false);
  });

  it("allows submission once every requirement is met", () => {
    expect(
      canSubmitAction(descriptor(), snapshot(), { [ACK]: "t" }, "", "acknowledged", true),
    ).toBe(true);
  });

  it("refuses a decision the owner does not allow", () => {
    expect(
      canSubmitAction(descriptor(), snapshot(), { [ACK]: "t" }, "", "resolved", true),
    ).toBe(false);
  });

  it("refuses submission without a snapshot", () => {
    expect(
      canSubmitAction(descriptor(), null, { [ACK]: "t" }, "", "acknowledged", true),
    ).toBe(false);
  });

  it("names the owner and operation in the confirmation text", () => {
    const text = confirmationText(descriptor(), "case_a");
    expect(text).toContain("for incident case_a");
    expect(text).toContain("review_ui / acknowledge_notification");
  });

  it("lists every non-consequence in the confirmation text", () => {
    const text = confirmationText(descriptor(), "case_a");
    expect(text).toContain("does not directly execute shell");
    expect(text).toContain("restore a checkpoint");
    expect(text).toContain("upload content or publish");
  });

  it("says status changes only after a canonical record", () => {
    expect(confirmationText(descriptor(), "case_a")).toContain(
      "only after a canonical owner record and digest confirm the change",
    );
  });
});

describe("receipts", () => {
  it("reports no submission before one is made", () => {
    expect(receiptSummary(null)).toBe("No submission has been made.");
  });

  it("reports a stale-state rejection", () => {
    expect(receiptSummary(receipt({ stale_state_rejected: true }))).toContain(
      "No authority changed",
    );
  });

  it("reports an unavailable owner route", () => {
    expect(
      receiptSummary(
        receipt({ accepted_by_owner: false, error_code: "owner_route_unavailable" }),
      ),
    ).toContain("No canonical owner route exists");
  });

  it("reports an owner refusal", () => {
    expect(receiptSummary(receipt({ accepted_by_owner: false }))).toContain(
      "Not accepted by review_ui",
    );
  });

  it("states that an accepted acknowledgement changed nothing", () => {
    expect(receiptSummary(receipt())).toContain("no incident, repair, recovery");
  });

  it("reports an authoritative change only with a record and digest", () => {
    const authoritative = receipt({ authoritative_state_changed: true });
    expect(receiptChangedAuthority(authoritative)).toBe(true);
    expect(receiptSummary(authoritative)).toContain("review_session_1");
  });

  it("denies an authority change without an owner record", () => {
    expect(
      receiptChangedAuthority(
        receipt({
          authoritative_state_changed: true,
          canonical_record_id: null,
          canonical_record_digest: null,
        }),
      ),
    ).toBe(false);
  });

  it("denies an authority change without a receipt", () => {
    expect(receiptChangedAuthority(null)).toBe(false);
  });

  it("lists every unchanged domain", () => {
    const labels = receiptChangeLabels(receipt());
    expect(labels).toContain("No repair executed");
    expect(labels).toContain("No recovery attempt started");
    expect(labels).toContain("No workflow change");
    expect(labels).toContain("No code change");
    expect(labels).toContain("No artifact change");
  });

  it("reports a disclosed repair execution", () => {
    expect(receiptChangeLabels(receipt({ repair_executed: true }))).toContain(
      "Repair executed",
    );
  });

  it("returns nothing without a receipt", () => {
    expect(receiptChangeLabels(null)).toEqual([]);
  });
});

describe("review-session annotations", () => {
  it("builds an annotation carrying the notice", () => {
    expect(buildAnnotation("case_a", "diagnosis", "Check the encoder.")?.notice).toBe(
      LOCAL_ANNOTATION_NOTICE,
    );
  });

  it("bounds the annotation text", () => {
    expect(
      buildAnnotation("case_a", "diagnosis", "x".repeat(5_000))?.text,
    ).toHaveLength(MAX_ANNOTATION_LENGTH);
  });

  it("refuses empty annotation text", () => {
    expect(buildAnnotation("case_a", "diagnosis", "   ")).toBeNull();
  });

  it("refuses an annotation carrying credentials", () => {
    expect(buildAnnotation("case_a", "diagnosis", "the password is x")).toBeNull();
  });

  it("records the incident and section identity", () => {
    const annotation = buildAnnotation("case_a", "root_cause", "Note.");
    expect(annotation?.incident_id).toBe("case_a");
    expect(annotation?.section_id).toBe("root_cause");
  });

  it("adds a new annotation", () => {
    const annotation = buildAnnotation("case_a", "diagnosis", "Note.")!;
    expect(upsertAnnotation([], annotation)).toHaveLength(1);
  });

  it("replaces an annotation with the same identity", () => {
    const annotation = buildAnnotation("case_a", "diagnosis", "Note.")!;
    const rows = upsertAnnotation([annotation], { ...annotation, text: "Revised." });
    expect(rows).toHaveLength(1);
    expect(rows[0].text).toBe("Revised.");
  });

  it("refuses to exceed the annotation ceiling", () => {
    const rows = Array.from({ length: MAX_ANNOTATIONS }, (_value, index) => ({
      annotation_id: `annotation_${index}`,
      incident_id: "case_a",
      section_id: "diagnosis",
      text: `Note ${index}`,
      notice: LOCAL_ANNOTATION_NOTICE,
    }));
    const extra = buildAnnotation("case_a", "diagnosis", "One too many.")!;
    expect(upsertAnnotation(rows, extra)).toHaveLength(MAX_ANNOTATIONS);
  });

  it("removes an annotation by identity", () => {
    const annotation = buildAnnotation("case_a", "diagnosis", "Note.")!;
    expect(removeAnnotation([annotation], annotation.annotation_id)).toEqual([]);
  });
});

describe("schema support and absent identities", () => {
  it("returns no schema notice for a supported schema", () => {
    expect(unsupportedSchemaNotice(reference())).toBe("");
  });

  it("states that an unsupported schema is not interpreted", () => {
    expect(
      unsupportedSchemaNotice(
        reference({ schema_supported: false, source_schema_id: "boba_error_doctor_v9" }),
      ),
    ).toContain("nothing is interpreted");
  });

  it("states that the owner records no revision identity", () => {
    expect(revisionNotice(reference())).toContain("records no incident revision identity");
  });

  it("shows a revision identity only when the owner recorded one", () => {
    expect(revisionNotice(reference({ incident_revision_id: "rev_2" }))).toBe(
      "Revision rev_2.",
    );
  });

  it("states that the owner records no error code", () => {
    expect(errorCodeLabel(reference())).toBe("Error Doctor records no error code.");
  });

  it("shows an error code only when the owner recorded one", () => {
    expect(errorCodeLabel(reference({ error_code: "E42" }))).toBe("E42");
  });

  it("returns nothing without a reference", () => {
    expect(revisionNotice(null)).toBe("");
    expect(unsupportedSchemaNotice(null)).toBe("");
    expect(errorCodeLabel(null)).toBe("");
  });

  it("keeps the diagnosis confidence incomparable", () => {
    expect(diagnosis().confidence_comparable_across_sources).toBe(false);
  });
});
