/**
 * Pure logic for the BOBA Error Doctor Panel.
 *
 * The panel is a read-only incident projection, an evidence workspace, a
 * diagnosis and root-cause comparison surface, a recovery-history viewer and a
 * safe canonical action router. Nothing here detects an error, creates an
 * incident, diagnoses, determines a root cause, creates a repair plan, executes
 * a repair or recovery, restores a checkpoint, changes a workflow, modifies
 * code, artifacts or media, runs a command, shell, Git or FFmpeg, installs or
 * downloads a tool, uploads or publishes.
 *
 * A hypothesis is never presented as a fact, owner-reported recovery success is
 * never presented as independent verification, and recovered is never presented
 * as resolved.
 */

export const MAX_COMPARISON_INCIDENTS = 4;
export const QUEUE_PAGE_SIZE = 50;
export const MAX_ANNOTATIONS = 32;
export const MAX_ANNOTATION_LENGTH = 4_000;
export const MAX_EXPANDED_LOG_CARDS = 10;
export const MAX_EXPANDED_SOURCE_CARDS = 20;
export const MAX_TIMELINE_ENTRIES = 100;
export const SUPPORTED_INCIDENT_SCHEMA_ID = "boba_error_doctor_v1";

export type ErrorDoctorReviewFilter =
  | "all_current"
  | "critical"
  | "workflow_blocking"
  | "human_review_required"
  | "missing_diagnosis"
  | "missing_root_cause"
  | "repair_plan_available"
  | "failed_recovery"
  | "unverified_recovery"
  | "recurring"
  | "conflicts"
  | "missing_evidence"
  | "stale"
  | "recovered"
  | "resolved"
  | "historical"
  | "superseded";

export type ErrorDoctorReviewSort =
  | "review_priority"
  | "source_severity"
  | "first_seen"
  | "last_seen"
  | "affected_stage"
  | "affected_module"
  | "incident_id";

export type EvidenceClassification =
  | "confirmed_fact"
  | "source_owned_assessment"
  | "source_owned_hypothesis"
  | "unresolved_claim"
  | "unavailable";

/** Source-owned severity ordering. Used for display only, never as a score. */
export const SOURCE_SEVERITY_ORDER: readonly string[] = [
  "blocker",
  "critical",
  "high",
  "medium",
  "low",
  "informational",
  "unknown",
];

export interface IncidentQueueItem {
  incident_queue_item_id: string;
  incident_reference_id: string;
  project_id: string;
  workflow_run_id: string | null;
  stage_instance_id: string | null;
  incident_id: string;
  title: string;
  bounded_summary: string;
  affected_module_id: string;
  affected_operation_id: string;
  affected_stage_id: string;
  original_error_class: string;
  original_error_code: string | null;
  original_severity: string;
  original_status: string;
  diagnosis_status: string;
  root_cause_status: string;
  repair_plan_status: string;
  recovery_status: string;
  validation_status: string;
  artifact_status: string;
  workflow_status: string;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  recovered: boolean;
  resolved: boolean;
  recurring: boolean;
  human_action_required: boolean;
  blocker_count: number;
  warning_count: number;
  missing_evidence_count: number;
  conflict_count: number;
  failed_recovery_attempt_count: number;
  available_action_descriptor_ids: string[];
  source_module_ids: string[];
  priority_tier: number;
  priority_reason: string;
  deterministic_sort_key: string;
  warnings: string[];
  limitations: string[];
}

export interface IncidentReference {
  incident_reference_id: string;
  project_id: string;
  workflow_run_id: string | null;
  stage_instance_id: string | null;
  incident_id: string;
  incident_revision_id: string | null;
  source_schema_id: string;
  schema_supported: boolean;
  affected_module_id: string;
  affected_operation_id: string;
  affected_stage_id: string;
  error_class: string;
  error_code: string | null;
  original_severity: string;
  original_status: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  superseding_incident_id: string | null;
  recovered: boolean;
  resolved: boolean;
  warnings: string[];
  limitations: string[];
}

export interface DiagnosisProjection {
  diagnosis_projection_id: string;
  source_module_id: string;
  diagnosis_id: string;
  diagnosis_revision_id: string | null;
  original_status: string;
  original_category: string;
  original_error_class: string;
  original_error_code: string | null;
  original_summary: string;
  bounded_technical_explanation: string;
  bounded_easy_explanation: string;
  confirmed_fact_ids: string[];
  assessment_ids: string[];
  hypothesis_ids: string[];
  confidence_value: number | null;
  confidence_name: string;
  confidence_definition: string;
  confidence_scale_min: number | null;
  confidence_scale_max: number | null;
  confidence_comparable_across_sources: boolean;
  current: boolean;
  stale: boolean;
  historical: boolean;
  sensitive_values_redacted: boolean;
  private_paths_redacted: boolean;
  warnings: string[];
  limitations: string[];
}

export interface RootCauseProjection {
  root_cause_projection_id: string;
  source_module_id: string;
  root_cause_id: string;
  original_status: string;
  original_classification: string;
  original_summary: string;
  confirmed: boolean;
  hypothesis: boolean;
  evidence_record_ids: string[];
  contradictory_evidence_record_ids: string[];
  confidence_value: number | null;
  confidence_name: string;
  confidence_definition: string;
  likelihood_value: number | null;
  likelihood_name: string;
  evidence_quality: string;
  repairability: string;
  recommended_owner_module_id: string;
  current: boolean;
  stale: boolean;
  human_confirmation_required: boolean;
  bounded_explanation: string;
  warnings: string[];
  limitations: string[];
}

export interface ErrorEvidenceCard {
  evidence_card_id: string;
  evidence_type: string;
  source_module_id: string;
  authority_domain: string;
  source_record_id: string;
  source_record_digest: string;
  title: string;
  original_status: string;
  original_decision: string | null;
  classification: EvidenceClassification;
  confirmed_fact: string;
  assessment: string;
  hypothesis: string;
  bounded_summary: string;
  bounded_excerpt: string;
  excerpt_truncated: boolean;
  sensitive_values_redacted: boolean;
  private_paths_redacted: boolean;
  current: boolean;
  stale: boolean;
  historical: boolean;
  missing: boolean;
  authoritative: boolean;
  advisory_only: boolean;
  blocking: boolean;
  warnings: string[];
  limitations: string[];
}

export interface RepairPlanProjection {
  repair_plan_projection_id: string;
  source_module_id: string;
  repair_plan_id: string;
  original_status: string;
  original_strategy: string;
  original_summary: string;
  affected_module_ids: string[];
  proposed_step_count: number;
  proposed_step_summaries: string[];
  requires_code_change: boolean;
  requires_artifact_change: boolean;
  requires_tool_execution: boolean;
  requires_process_restart: boolean;
  requires_checkpoint_restore: boolean;
  requires_workflow_transition: boolean;
  requires_human_approval: boolean;
  destructive: boolean;
  reversible: boolean;
  rollback_available: boolean;
  verification_required: boolean;
  source_owned_rank: number | null;
  source_owned_score: number | null;
  source_owned_score_name: string;
  source_marked_recommended: boolean;
  current: boolean;
  stale: boolean;
  executable_by_panel: false;
  raw_command_exposed: false;
  bounded_explanation: string;
  warnings: string[];
  limitations: string[];
}

export interface RecoveryAttemptProjection {
  recovery_attempt_projection_id: string;
  source_module_id: string;
  recovery_attempt_id: string;
  repair_plan_id: string;
  attempt_number: number | null;
  original_status: string;
  started_at: string | null;
  completed_at: string | null;
  attempted: boolean;
  completed: boolean;
  succeeded_by_owner: boolean;
  verified: boolean;
  verification_source_ids: string[];
  changed_code: boolean;
  changed_artifacts: boolean;
  changed_workflow: boolean;
  invoked_tool: string;
  invoked_operation_id: string;
  rollback_attempted: boolean;
  rollback_status: string;
  original_error_code: string | null;
  resulting_error_code: string | null;
  exit_code: number | null;
  timed_out: boolean;
  bounded_summary: string;
  warnings: string[];
  limitations: string[];
}

export interface ErrorConflict {
  conflict_record_id: string;
  conflict_type: string;
  severity: string;
  value_a: string;
  value_b: string;
  same_incident: boolean;
  same_workflow_run: boolean;
  current_records: boolean;
  explicit_supersession_found: boolean;
  resolved: boolean;
  resolution_source_id: string | null;
  blocks_action: boolean;
  human_review_required: boolean;
  bounded_summary: string;
  warnings: string[];
  limitations: string[];
}

export interface IncidentSnapshot {
  incident_snapshot_id: string;
  error_doctor_review_session_id: string;
  project_id: string;
  incident_id: string;
  incident_digest: string;
  snapshot_digest: string;
  incident_status: string;
  diagnosis_status: string;
  root_cause_status: string;
  repair_plan_status: string;
  recovery_status: string;
  validation_status: string;
  artifact_status: string;
  workflow_status: string;
  rights_status: string;
  safety_status: string;
  final_decision_status: string;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  recovered: boolean;
  resolved: boolean;
  missing_evidence_count: number;
  conflict_count: number;
  available_action_descriptor_ids: string[];
  limitations: string[];
}

export interface ErrorDoctorActionDescriptor {
  action_descriptor_id: string;
  display_name: string;
  action_class: string;
  owning_module_id: string;
  owning_operation_id: string;
  supported_incident_states: string[];
  allowed_decision_values: string[];
  requires_reason: boolean;
  maximum_reason_length: number;
  requires_confirmation: boolean;
  requires_current_snapshot: boolean;
  requires_reviewer_context: boolean;
  requires_safety_gate: boolean;
  requires_final_decision_bus: boolean;
  authoritative: boolean;
  destructive: boolean;
  execution_capable: boolean;
  code_modifying: boolean;
  artifact_modifying: boolean;
  workflow_modifying: boolean;
  upload_or_publication: boolean;
  allowed_in_v1: boolean;
  availability: "available" | "unavailable";
  consequences: string[];
  does_not_do: string[];
  warnings: string[];
  limitations: string[];
}

export interface ErrorDoctorActionReceipt {
  error_doctor_action_receipt_id: string;
  owning_module_id: string;
  owning_operation_id: string;
  accepted_by_owner: boolean;
  canonical_status: string;
  canonical_record_id: string | null;
  canonical_record_digest: string | null;
  authoritative_state_changed: boolean;
  repair_executed: boolean;
  recovery_attempt_started: boolean;
  workflow_changed: boolean;
  code_changed: boolean;
  artifact_changed: boolean;
  stale_state_rejected: boolean;
  duplicate_request_reused: boolean;
  error_code: string | null;
  bounded_error_message: string;
  limitations: string[];
}

export interface ErrorDoctorAnnotation {
  annotation_id: string;
  incident_id: string;
  section_id: string;
  text: string;
  notice: string;
}

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */

export function formatTimestamp(value: string | null): string {
  if (!value) return "time not recorded by the owner";
  return value;
}

export function severityRank(severity: string): number {
  const index = SOURCE_SEVERITY_ORDER.indexOf(severity);
  return index === -1 ? SOURCE_SEVERITY_ORDER.length : index;
}

export function severityLabel(severity: string): string {
  return SOURCE_SEVERITY_ORDER.includes(severity)
    ? `Owner severity: ${severity}`
    : "Owner severity: not recorded";
}

/** Status words belong to the owning module. They are shown, never rephrased. */
export function ownerStatusLabel(moduleId: string, status: string): string {
  if (status === "unavailable") return `${moduleId} has supplied no record`;
  return `${moduleId} reports ${status.replace(/_/g, " ")}`;
}

export function incidentStateLabel(item: IncidentQueueItem): string {
  if (item.superseded) return "Superseded";
  if (item.historical) return "Historical";
  if (item.stale) return "Stale";
  if (item.resolved) return "Resolved";
  if (item.recovered) return "Recovered, not resolved";
  if (item.current) return "Current";
  return "Unknown";
}

export function priorityLabel(item: IncidentQueueItem): string {
  return `Tier ${item.priority_tier}: ${item.priority_reason}`;
}

/* ------------------------------------------------------------------ */
/* Facts, assessments and hypotheses                                   */
/* ------------------------------------------------------------------ */

export function classificationLabel(value: EvidenceClassification): string {
  switch (value) {
    case "confirmed_fact":
      return "Confirmed fact";
    case "source_owned_assessment":
      return "Source assessment";
    case "source_owned_hypothesis":
      return "Source hypothesis";
    case "unresolved_claim":
      return "Unresolved claim";
    default:
      return "Unavailable";
  }
}

/** A hypothesis is never labelled a fact, and a fact is never softened. */
export function classificationIsFact(value: EvidenceClassification): boolean {
  return value === "confirmed_fact";
}

export function rootCauseHeading(projection: RootCauseProjection): string {
  return projection.confirmed ? "Confirmed root cause" : "Root-cause hypothesis";
}

export const ROOT_CAUSE_NOTICE =
  "Root Cause Analyzer requires human review on every analysis case, so this " +
  "panel never presents a candidate as a confirmed root cause.";

export function confidenceLabel(
  value: number | null,
  name: string,
  definition: string,
): string {
  if (value === null) return "The owner recorded no confidence value.";
  return `${name} = ${value} (owner scale). ${definition}`;
}

/** Confidence from different modules is never combined or compared. */
export const CONFIDENCE_NOTICE =
  "Confidence values belong to the module that produced them. They are not " +
  "probabilities unless that owner says so, and are never averaged or compared.";

/* ------------------------------------------------------------------ */
/* Queue                                                               */
/* ------------------------------------------------------------------ */

export interface IncidentFilterState {
  filter: ErrorDoctorReviewFilter;
  showRecovered: boolean;
  showResolved: boolean;
  showHistorical: boolean;
}

export function filterIncidents(
  items: IncidentQueueItem[],
  state: IncidentFilterState,
): IncidentQueueItem[] {
  let rows = state.showHistorical ? items : items.filter((item) => !item.historical);
  if (!state.showRecovered) rows = rows.filter((item) => !item.recovered);
  if (!state.showResolved) rows = rows.filter((item) => !item.resolved);
  switch (state.filter) {
    case "critical":
      return rows.filter(
        (item) =>
          item.original_severity === "critical" || item.original_severity === "blocker",
      );
    case "workflow_blocking":
      return rows.filter((item) => item.priority_tier === 20);
    case "human_review_required":
      return rows.filter((item) => item.human_action_required);
    case "missing_diagnosis":
      return rows.filter((item) => item.priority_tier === 50);
    case "missing_root_cause":
      return rows.filter((item) => item.root_cause_status === "unavailable");
    case "repair_plan_available":
      return rows.filter((item) => item.repair_plan_status !== "unavailable");
    case "failed_recovery":
      return rows.filter((item) => item.failed_recovery_attempt_count > 0);
    case "unverified_recovery":
      return rows.filter((item) => item.priority_tier === 110);
    case "recurring":
      return rows.filter((item) => item.recurring);
    case "conflicts":
      return rows.filter((item) => item.conflict_count > 0);
    case "missing_evidence":
      return rows.filter((item) => item.missing_evidence_count > 0);
    case "stale":
      return rows.filter((item) => item.stale);
    case "recovered":
      return items.filter((item) => item.recovered);
    case "resolved":
      return items.filter((item) => item.resolved);
    case "historical":
      return items.filter((item) => item.historical);
    case "superseded":
      return items.filter((item) => item.superseded);
    default:
      return rows;
  }
}

/** Sorting is deterministic and never reorders by an invented score. */
export function sortIncidents(
  items: IncidentQueueItem[],
  sort: ErrorDoctorReviewSort,
): IncidentQueueItem[] {
  const rows = [...items];
  if (sort === "source_severity") {
    rows.sort((a, b) => {
      const left = severityRank(a.original_severity);
      const right = severityRank(b.original_severity);
      return left === right ? a.incident_id.localeCompare(b.incident_id) : left - right;
    });
    return rows;
  }
  if (sort === "affected_stage") {
    rows.sort(
      (a, b) =>
        a.affected_stage_id.localeCompare(b.affected_stage_id) ||
        a.incident_id.localeCompare(b.incident_id),
    );
    return rows;
  }
  if (sort === "affected_module") {
    rows.sort(
      (a, b) =>
        a.affected_module_id.localeCompare(b.affected_module_id) ||
        a.incident_id.localeCompare(b.incident_id),
    );
    return rows;
  }
  if (sort === "incident_id") {
    rows.sort((a, b) => a.incident_id.localeCompare(b.incident_id));
    return rows;
  }
  if (sort === "last_seen") {
    rows.sort((a, b) => b.deterministic_sort_key.localeCompare(a.deterministic_sort_key));
    return rows;
  }
  if (sort === "first_seen") {
    rows.sort((a, b) => a.deterministic_sort_key.localeCompare(b.deterministic_sort_key));
    return rows;
  }
  rows.sort((a, b) =>
    a.priority_tier === b.priority_tier
      ? a.deterministic_sort_key.localeCompare(b.deterministic_sort_key)
      : a.priority_tier - b.priority_tier,
  );
  return rows;
}

/* ------------------------------------------------------------------ */
/* Evidence, repair and recovery presentation                          */
/* ------------------------------------------------------------------ */

export function evidenceSummary(item: IncidentQueueItem): string {
  if (item.missing_evidence_count === 0) return "All linked source evidence is present.";
  const noun = item.missing_evidence_count === 1 ? "source" : "sources";
  return `${item.missing_evidence_count} ${noun} missing. Missing evidence is not a pass.`;
}

export function describeEvidenceCard(card: ErrorEvidenceCard): string {
  if (card.missing) return `${card.title}: no canonical record is available.`;
  const suffix = card.advisory_only ? " (advisory, not a decision)" : "";
  return `${card.title}: ${card.original_status.replace(/_/g, " ")}${suffix}`;
}

export function excerptNotices(card: ErrorEvidenceCard): string[] {
  const notices: string[] = [];
  if (card.sensitive_values_redacted) notices.push("Sensitive values redacted");
  if (card.private_paths_redacted) notices.push("Private path details redacted");
  if (card.excerpt_truncated) notices.push("Excerpt truncated");
  notices.push("Full record retained by the owning module");
  return notices;
}

export const REPAIR_EXECUTION_NOTICE =
  "Repair execution unavailable in Error Doctor Panel V1.";

export function repairRequirements(plan: RepairPlanProjection): string[] {
  const rows: string[] = [];
  if (plan.requires_code_change) rows.push("Proposes a code change");
  if (plan.requires_artifact_change) rows.push("May change artifacts");
  if (plan.requires_tool_execution) rows.push("Requires tool execution");
  if (plan.requires_process_restart) rows.push("Proposes a process restart");
  if (plan.requires_checkpoint_restore) rows.push("Proposes checkpoint restoration");
  if (plan.requires_workflow_transition) rows.push("Proposes a workflow transition");
  if (plan.requires_human_approval) rows.push("Requires human approval");
  return rows;
}

export function repairRiskLabel(plan: RepairPlanProjection): string {
  const destructive = plan.destructive ? "destructive" : "non-destructive";
  const reversible = plan.reversible ? "reversible" : "not reversible";
  const rollback = plan.rollback_available ? "rollback available" : "no rollback plan";
  return `${destructive}, ${reversible}, ${rollback}`;
}

export function repairOwnerRankLabel(plan: RepairPlanProjection): string {
  if (plan.source_owned_rank === null && plan.source_owned_score === null) {
    return "Repair Planner recorded no rank or score.";
  }
  const parts: string[] = [];
  if (plan.source_owned_rank !== null) parts.push(`rank ${plan.source_owned_rank}`);
  if (plan.source_owned_score !== null) {
    parts.push(`${plan.source_owned_score_name} ${plan.source_owned_score}`);
  }
  return `Repair Planner recorded ${parts.join(", ")}. The panel adds no score.`;
}

/** Attempted, completed, owner-reported success and verification stay distinct. */
export function recoveryOutcomeLabel(attempt: RecoveryAttemptProjection): string {
  if (!attempt.attempted) return "Not attempted";
  if (attempt.verified) return "Owner reported success and verification passed";
  if (attempt.succeeded_by_owner) return "Owner reports success, not independently verified";
  if (attempt.completed) return "Completed without owner-reported success";
  return `Attempted, owner status ${attempt.original_status.replace(/_/g, " ")}`;
}

export function recoveryChangeLabels(attempt: RecoveryAttemptProjection): string[] {
  const rows: string[] = [];
  rows.push(
    attempt.changed_code
      ? "Owner disclosed a code change"
      : "No code change disclosed by the owner",
  );
  rows.push(
    attempt.changed_artifacts
      ? "Owner disclosed an artifact change"
      : "No artifact change disclosed by the owner",
  );
  rows.push(
    attempt.changed_workflow
      ? "Owner disclosed a workflow change"
      : "No workflow change disclosed by the owner",
  );
  return rows;
}

export const RECOVERED_NOTICE =
  "Recovered is not resolved, and owner-reported success is not independent " +
  "verification.";

export function recoverySummary(attempts: RecoveryAttemptProjection[]): string {
  if (attempts.length === 0) return "No recovery attempt is recorded for this incident.";
  const failed = attempts.filter((item) =>
    ["failed", "timed_out", "rejected", "blocked"].includes(item.original_status),
  ).length;
  const verified = attempts.filter((item) => item.verified).length;
  return (
    `${attempts.length} attempt(s), ${failed} failed, ${verified} independently ` +
    `verified. ${RECOVERED_NOTICE}`
  );
}

export function conflictResolutionLabel(conflict: ErrorConflict): string {
  if (conflict.resolved && conflict.resolution_source_id) {
    return `Resolved by ${conflict.resolution_source_id}.`;
  }
  return "Unresolved. Only the owning module can resolve this.";
}

export function conflictSummary(conflicts: ErrorConflict[]): string {
  if (conflicts.length === 0) return "No conflict was detected against canonical sources.";
  const blocking = conflicts.filter((item) => item.blocks_action).length;
  return (
    `${conflicts.length} conflict(s), ${blocking} blocking. Conflicts are reported ` +
    "unresolved and are never resolved by comparing confidence."
  );
}

/* ------------------------------------------------------------------ */
/* Comparison                                                          */
/* ------------------------------------------------------------------ */

export function toggleComparison(selected: string[], incidentId: string): string[] {
  if (selected.includes(incidentId)) {
    return selected.filter((item) => item !== incidentId);
  }
  if (selected.length >= MAX_COMPARISON_INCIDENTS) return selected;
  return [...selected, incidentId];
}

export function canCompare(selected: string[]): boolean {
  return selected.length >= 2 && selected.length <= MAX_COMPARISON_INCIDENTS;
}

export const NO_WINNER_NOTICE =
  "Comparison shows differences only. No incident, root cause or repair plan is " +
  "scored, preferred or chosen.";

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */

export function availableActions(
  descriptors: ErrorDoctorActionDescriptor[],
  snapshot: IncidentSnapshot | null,
  confirmations: Record<string, string>,
): ErrorDoctorActionDescriptor[] {
  const offered = snapshot?.available_action_descriptor_ids ?? [];
  return descriptors.filter(
    (item) =>
      item.allowed_in_v1 &&
      item.availability === "available" &&
      offered.includes(item.action_descriptor_id) &&
      Boolean(confirmations[item.action_descriptor_id]),
  );
}

export function withheldActions(
  descriptors: ErrorDoctorActionDescriptor[],
  snapshot: IncidentSnapshot | null,
  confirmations: Record<string, string>,
): ErrorDoctorActionDescriptor[] {
  const available = new Set(
    availableActions(descriptors, snapshot, confirmations).map(
      (item) => item.action_descriptor_id,
    ),
  );
  return descriptors.filter((item) => !available.has(item.action_descriptor_id));
}

/** Unavailable actions are explained honestly. No substitute authority is offered. */
export function unavailableActionNotice(
  descriptor: ErrorDoctorActionDescriptor,
): string {
  if (descriptor.availability === "available" && descriptor.allowed_in_v1) return "";
  if (descriptor.limitations.length > 0) return descriptor.limitations.join(" ");
  return "No canonical owner operation exists for this action, so the panel does not offer it.";
}

export const NO_EXECUTION_NOTICE =
  "Error Doctor Panel V1 exposes no repair, recovery, tool-retry, checkpoint or " +
  "workflow action. It runs no command, shell, Git or FFmpeg, and it never " +
  "uploads or publishes.";

const SENSITIVE_TEXT = /secret|token|password|credential|cookie|authorization/i;
const PRIVATE_PATH = /(?:[A-Za-z]:[\\/]|file:|\/home\/|\/Users\/|\\\\)/i;

export function validateActionReason(
  reason: string,
  descriptor: ErrorDoctorActionDescriptor,
): string | null {
  if (descriptor.requires_reason && reason.trim().length === 0) {
    return "A reason is required for this action.";
  }
  if (reason.length > descriptor.maximum_reason_length) {
    return `The reason must be ${descriptor.maximum_reason_length} characters or fewer.`;
  }
  if (SENSITIVE_TEXT.test(reason)) return "The reason cannot contain credentials.";
  if (PRIVATE_PATH.test(reason)) {
    return "The reason cannot contain private path details.";
  }
  return null;
}

export function canSubmitAction(
  descriptor: ErrorDoctorActionDescriptor,
  snapshot: IncidentSnapshot | null,
  confirmations: Record<string, string>,
  reason: string,
  decisionValue: string | null,
  confirmed: boolean,
): boolean {
  if (!snapshot) return false;
  if (availableActions([descriptor], snapshot, confirmations).length === 0) return false;
  if (validateActionReason(reason, descriptor) !== null) return false;
  if (
    descriptor.allowed_decision_values.length > 0 &&
    (decisionValue === null || !descriptor.allowed_decision_values.includes(decisionValue))
  ) {
    return false;
  }
  return descriptor.requires_confirmation ? confirmed : true;
}

/** Build the exact confirmation wording shown before any canonical submission. */
export function confirmationText(
  descriptor: ErrorDoctorActionDescriptor,
  incidentId: string,
): string {
  return (
    `You are submitting ${descriptor.display_name} for incident ${incidentId}. ` +
    `This sends a canonical request to ${descriptor.owning_module_id} / ` +
    `${descriptor.owning_operation_id}. It does not directly execute shell ` +
    "commands, modify code, restore a checkpoint, change the workflow, modify " +
    "artifacts, grant Rights or Safety approval, upload content or publish " +
    "content. The displayed incident status will change only after a canonical " +
    "owner record and digest confirm the change."
  );
}

export function receiptChangedAuthority(
  receipt: ErrorDoctorActionReceipt | null | undefined,
): boolean {
  if (!receipt) return false;
  return Boolean(
    receipt.authoritative_state_changed &&
      receipt.canonical_record_id &&
      receipt.canonical_record_digest,
  );
}

export function receiptSummary(
  receipt: ErrorDoctorActionReceipt | null | undefined,
): string {
  if (!receipt) return "No submission has been made.";
  if (receipt.stale_state_rejected) {
    return "Rejected: canonical state changed before submission. No authority changed.";
  }
  if (receipt.error_code === "owner_route_unavailable") {
    return "No canonical owner route exists for this action. Nothing changed.";
  }
  if (!receipt.accepted_by_owner) {
    return `Not accepted by ${receipt.owning_module_id}. No authority changed.`;
  }
  if (receiptChangedAuthority(receipt)) {
    return `${receipt.owning_module_id} recorded ${receipt.canonical_record_id}.`;
  }
  return (
    `${receipt.owning_module_id} recorded the request. This is review metadata: no ` +
    "incident, repair, recovery, workflow, code or artifact state changed."
  );
}

/** A receipt only proves a change when the owner returned a record and digest. */
export function receiptChangeLabels(
  receipt: ErrorDoctorActionReceipt | null | undefined,
): string[] {
  if (!receipt) return [];
  return [
    receipt.repair_executed ? "Repair executed" : "No repair executed",
    receipt.recovery_attempt_started
      ? "Recovery attempt started"
      : "No recovery attempt started",
    receipt.workflow_changed ? "Workflow changed" : "No workflow change",
    receipt.code_changed ? "Code changed" : "No code change",
    receipt.artifact_changed ? "Artifact changed" : "No artifact change",
  ];
}

/* ------------------------------------------------------------------ */
/* Review-session annotations                                          */
/* ------------------------------------------------------------------ */

export const LOCAL_ANNOTATION_NOTICE =
  "Review-session annotation — not part of the canonical incident, diagnosis or " +
  "repair record.";

export function buildAnnotation(
  incidentId: string,
  sectionId: string,
  text: string,
  annotationId?: string,
): ErrorDoctorAnnotation | null {
  const bounded = text.trim().slice(0, MAX_ANNOTATION_LENGTH);
  if (!bounded) return null;
  if (SENSITIVE_TEXT.test(bounded)) return null;
  return {
    annotation_id: annotationId ?? `annotation_${incidentId}_${bounded.length}`,
    incident_id: incidentId,
    section_id: sectionId,
    text: bounded,
    notice: LOCAL_ANNOTATION_NOTICE,
  };
}

export function upsertAnnotation(
  annotations: ErrorDoctorAnnotation[],
  annotation: ErrorDoctorAnnotation,
): ErrorDoctorAnnotation[] {
  const existing = annotations.findIndex(
    (item) => item.annotation_id === annotation.annotation_id,
  );
  if (existing >= 0) {
    const rows = [...annotations];
    rows[existing] = annotation;
    return rows;
  }
  if (annotations.length >= MAX_ANNOTATIONS) return annotations;
  return [...annotations, annotation];
}

export function removeAnnotation(
  annotations: ErrorDoctorAnnotation[],
  annotationId: string,
): ErrorDoctorAnnotation[] {
  return annotations.filter((item) => item.annotation_id !== annotationId);
}

/* ------------------------------------------------------------------ */
/* Schema support and revision honesty                                 */
/* ------------------------------------------------------------------ */

export function unsupportedSchemaNotice(reference: IncidentReference | null): string {
  if (!reference || reference.schema_supported) return "";
  return (
    `Incident schema "${reference.source_schema_id}" is not supported by this panel. ` +
    "Records are shown as stored and nothing is interpreted."
  );
}

export function revisionNotice(reference: IncidentReference | null): string {
  if (!reference) return "";
  if (reference.incident_revision_id) return `Revision ${reference.incident_revision_id}.`;
  return "Error Doctor records no incident revision identity, so none is shown.";
}

export function errorCodeLabel(reference: IncidentReference | null): string {
  if (!reference) return "";
  if (reference.error_code) return reference.error_code;
  return "Error Doctor records no error code.";
}

/** Bounded log cards are limited so a huge incident cannot flood the browser. */
export function boundedLogCardIds(cardIds: string[]): string[] {
  return cardIds.slice(0, MAX_EXPANDED_LOG_CARDS);
}

export function boundedSourceCardIds(cardIds: string[]): string[] {
  return cardIds.slice(0, MAX_EXPANDED_SOURCE_CARDS);
}
