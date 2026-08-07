/**
 * Pure logic for the BOBA Repair Plan Panel.
 *
 * The panel is a read-only repair-plan projection, an evidence workspace, a
 * plan-comparison surface, an approval-requirement viewer, a recovery-history
 * viewer and a safe canonical action router. Nothing here generates a repair
 * plan, revises one, approves or rejects one, executes a plan or a step, runs a
 * command, shell, PowerShell, Git or FFmpeg, installs or downloads a tool,
 * restarts a process, restores a checkpoint, transitions a workflow, modifies
 * code, artifacts or media, uploads or publishes.
 *
 * Repair Planner proposed every plan shown here. A proposed strategy is never
 * presented as the correct repair, a reversible plan is never presented as
 * risk-free, an available rollback is never presented as a guaranteed rollback,
 * owner-reported success is never presented as independent verification, and
 * recovered is never presented as resolved.
 *
 * Command text and private absolute paths never reach this module: the backend
 * withholds them and reports only that the source record holds them.
 */

export const MAX_COMPARISON_PLANS = 4;
export const QUEUE_PAGE_SIZE = 50;
export const MAX_ANNOTATIONS = 32;
export const MAX_ANNOTATION_LENGTH = 4_000;
export const MAX_EXPANDED_SOURCE_CARDS = 20;
export const MAX_STEP_PROJECTIONS = 64;
export const MAX_TIMELINE_ENTRIES = 100;
export const SUPPORTED_REPAIR_PLAN_SCHEMA_ID = "boba_repair_planner_v1";

/** The exact notices the backend uses when it withholds source detail. */
export const COMMAND_WITHHELD_NOTICE = "Command details withheld from the review panel.";
export const PRIVATE_PATH_NOTICE = "Private path details redacted.";
export const NOT_EXECUTABLE_NOTICE = "This step cannot be executed from this panel.";
export const SOURCE_RETAINED_NOTICE = "Full source record retained by Repair Planner.";

export const PROPOSED_PLAN_NOTICE =
  "Repair Planner proposed this strategy. This panel does not state that it is the correct repair.";
export const REVERSIBLE_NOTICE = "Reversible does not mean risk-free.";
export const ROLLBACK_NOTICE =
  "A rollback plan being available does not mean a rollback is guaranteed to succeed.";
export const VERIFICATION_NOTICE =
  "Owner-reported success is not independent verification.";
export const RECOVERED_NOTICE = "Recovered is not resolved.";
export const ANNOTATION_NOTICE =
  "Review-session annotation — not part of the canonical repair plan.";
export const NO_EXECUTION_NOTICE =
  "Repair Plan Panel V1 exposes no plan approval, plan rejection, plan revision, execution, recovery, checkpoint or workflow action.";

export type RepairPlanReviewFilter =
  | "all_current"
  | "human_review_required"
  | "destructive"
  | "reversible"
  | "code_change"
  | "artifact_change"
  | "workflow_change"
  | "tool_execution"
  | "process_restart"
  | "checkpoint_restore"
  | "missing_approval"
  | "missing_verification"
  | "failed_recovery"
  | "conflicts"
  | "stale"
  | "completed"
  | "historical"
  | "superseded";

export type RepairPlanReviewSort =
  | "review_priority"
  | "source_severity"
  | "creation_order"
  | "affected_module"
  | "step_count"
  | "repair_plan_id";

export type RepairApprovalRequirementType =
  | "human_review"
  | "safety_gate"
  | "final_decision_bus"
  | "workflow"
  | "code_change"
  | "artifact_change"
  | "destructive_action"
  | "tool_execution"
  | "process_restart"
  | "checkpoint_restore"
  | "rights_gate"
  | "rollback_plan"
  | "validation_plan"
  | "output_quality_review"
  | "unknown";

export type RepairVerificationType =
  | "pre_repair_check"
  | "post_repair_check"
  | "validator_run"
  | "artifact_inspection"
  | "output_quality_review"
  | "rollback_validation"
  | "checkpoint_validation"
  | "unknown";

/** Source-owned risk ordering. Display only, never a score. */
export const SOURCE_RISK_ORDER: readonly string[] = [
  "blocking",
  "critical",
  "high",
  "moderate",
  "medium",
  "low",
  "minimal",
  "none",
  "unknown",
];

/** The twelve risk dimensions Repair Planner records on its own assessment. */
export const RISK_DIMENSIONS: readonly string[] = [
  "overall_risk",
  "source_data_risk",
  "artifact_loss_risk",
  "output_quality_risk",
  "workflow_corruption_risk",
  "configuration_risk",
  "environment_risk",
  "security_risk",
  "rights_safety_risk",
  "external_dependency_risk",
  "rollback_failure_risk",
  "human_error_risk",
];

export interface RepairPlanQueueItem {
  repair_plan_queue_item_id: string;
  repair_plan_reference_id: string;
  project_id: string;
  repair_plan_id: string;
  repair_case_id: string;
  source_analysis_case_id: string;
  source_diagnostic_case_id: string;
  title: string;
  bounded_summary: string;
  owner_module_id: string;
  original_status: string;
  original_strategy_type: string;
  original_risk_level: string;
  original_reversibility: string;
  original_destructiveness: string;
  approval_status: string;
  verification_status: string;
  recovery_status: string;
  validation_status: string;
  artifact_status: string;
  workflow_status: string;
  affected_module_id: string;
  affected_stage_id: string;
  step_count: number;
  destructive: boolean;
  reversible: boolean;
  rollback_available: boolean;
  requires_code_change: boolean;
  requires_artifact_change: boolean;
  requires_workflow_transition: boolean;
  requires_tool_execution: boolean;
  requires_process_restart: boolean;
  requires_checkpoint_restore: boolean;
  requires_human_approval: boolean;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  completed: boolean;
  source_marked_recommended: boolean;
  human_action_required: boolean;
  blocker_count: number;
  warning_count: number;
  missing_approval_count: number;
  missing_verification_count: number;
  missing_evidence_count: number;
  conflict_count: number;
  failed_recovery_attempt_count: number;
  command_bearing_step_count: number;
  available_action_descriptor_ids: string[];
  source_module_ids: string[];
  priority_tier: number;
  priority_reason: string;
  deterministic_sort_key: string;
  warnings: string[];
  limitations: string[];
}

export interface RepairPlanReference {
  repair_plan_reference_id: string;
  project_id: string;
  repair_plan_id: string;
  repair_plan_revision_id: string | null;
  repair_case_id: string;
  source_analysis_case_id: string;
  source_diagnostic_case_id: string;
  source_record_id: string;
  source_record_digest: string;
  source_schema_id: string;
  schema_supported: boolean;
  owner_module_id: string;
  original_status: string;
  original_strategy_type: string;
  original_risk_level: string;
  affected_stage_id: string;
  affected_module_id: string;
  project_snapshot_digest: string;
  workflow_revision: number;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  superseding_repair_plan_id: string | null;
  warnings: string[];
  limitations: string[];
}

export interface RepairStepProjection {
  repair_step_projection_id: string;
  repair_plan_id: string;
  source_module_id: string;
  source_record_id: string;
  source_step_id: string;
  original_order: number;
  original_status: string;
  original_step_type: string;
  bounded_description: string;
  bounded_reason: string;
  affected_module_ids: string[];
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
  read_only_by_owner: boolean;
  raw_command_present_in_source: boolean;
  raw_command_exposed: false;
  private_path_present_in_source: boolean;
  private_path_exposed: false;
  executable_by_panel: false;
  bounded_safety_precondition: string;
  bounded_success_condition: string;
  warnings: string[];
  limitations: string[];
}

export interface RepairRiskProjection {
  repair_risk_projection_id: string;
  repair_plan_id: string;
  source_record_id: string;
  risk_dimension: string;
  original_risk_level: string;
  strategy_specific: boolean;
  blocked_by_owner: boolean;
  bounded_reasons: string[];
  bounded_mitigations: string[];
  bounded_residual_risk: string;
  acceptable_only_if: string[];
  confidence_value: number | null;
  confidence_name: string;
  confidence_definition: string;
  reversible_does_not_mean_risk_free: true;
  warnings: string[];
  limitations: string[];
}

export interface RepairApprovalRequirement {
  approval_requirement_id: string;
  repair_plan_id: string;
  source_module_id: string;
  source_record_id: string;
  requirement_type: RepairApprovalRequirementType;
  required: boolean;
  satisfied_by_owner: boolean;
  canonical_record_id: string | null;
  canonical_record_digest: string | null;
  blocking: boolean;
  bounded_explanation: string;
  warnings: string[];
  limitations: string[];
}

export interface RepairVerificationRequirement {
  verification_requirement_id: string;
  repair_plan_id: string;
  verification_type: RepairVerificationType;
  required: boolean;
  source_module_id: string;
  source_record_id: string;
  validator_ids: string[];
  artifact_reference_ids: string[];
  required_check_ids: string[];
  satisfied: boolean;
  independently_verified: boolean;
  blocks_acceptance_on_failure: boolean;
  blocking: boolean;
  bounded_explanation: string;
  warnings: string[];
  limitations: string[];
}

export interface RepairEvidenceCard {
  repair_evidence_card_id: string;
  evidence_type: string;
  source_module_id: string;
  authority_domain: string;
  source_record_id: string;
  source_record_digest: string;
  title: string;
  original_status: string;
  original_decision: string | null;
  bounded_summary: string;
  bounded_excerpt: string;
  excerpt_truncated: boolean;
  command_withheld: boolean;
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

export interface RepairRecoveryLink {
  repair_recovery_link_id: string;
  repair_plan_id: string;
  source_module_id: string;
  source_record_id: string;
  recovery_case_id: string;
  recovery_attempt_id: string;
  attempt_number: number | null;
  original_status: string;
  linked_by_strategy_id: boolean;
  attempted: boolean;
  completed: boolean;
  succeeded_by_owner: boolean;
  independently_verified: boolean;
  verification_source_ids: string[];
  rollback_attempted: boolean;
  rollback_status: string;
  resulting_failure_class: string | null;
  started_at: string | null;
  completed_at: string | null;
  bounded_summary: string;
  warnings: string[];
  limitations: string[];
}

export interface RepairPlanConflict {
  conflict_record_id: string;
  conflict_type: string;
  severity: string;
  source_record_ids: string[];
  value_a: string;
  value_b: string;
  same_repair_plan: boolean;
  resolved: boolean;
  blocks_action: boolean;
  human_review_required: boolean;
  bounded_summary: string;
  warnings: string[];
  limitations: string[];
}

export interface RepairPlanSnapshot {
  repair_plan_snapshot_id: string;
  repair_plan_review_session_id: string;
  repair_plan_reference_id: string;
  project_id: string;
  repair_plan_id: string;
  repair_case_id: string;
  source_diagnostic_case_id: string;
  project_snapshot_digest: string;
  workflow_revision: number;
  repair_plan_digest: string;
  plan_status: string;
  approval_status: string;
  verification_status: string;
  recovery_status: string;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  completed: boolean;
  destructive: boolean;
  reversible: boolean;
  rollback_available: boolean;
  missing_approval_count: number;
  missing_verification_count: number;
  missing_evidence_count: number;
  conflict_count: number;
  available_action_descriptor_ids: string[];
  confirmation_context_digest: string;
  snapshot_digest: string;
  warnings: string[];
  limitations: string[];
}

export interface RepairPlanActionDescriptor {
  action_descriptor_id: string;
  display_name: string;
  action_class: string;
  owning_module_id: string;
  owning_operation_id: string;
  allowed_decision_values: string[];
  requires_reason: boolean;
  maximum_reason_length: number;
  requires_confirmation: boolean;
  authoritative: boolean;
  destructive: boolean;
  execution_capable: boolean;
  code_modifying: boolean;
  artifact_modifying: boolean;
  workflow_modifying: boolean;
  checkpoint_restoring: boolean;
  process_restarting: boolean;
  upload_or_publication: boolean;
  allowed_in_v1: boolean;
  availability: "available" | "unavailable";
  unavailable_reason: string;
  consequences: string[];
  does_not_do: string[];
  warnings: string[];
  limitations: string[];
}

export interface RepairPlanActionReceipt {
  repair_plan_action_receipt_id: string;
  repair_plan_action_request_id: string;
  repair_plan_id: string;
  owning_module_id: string;
  owning_operation_id: string;
  accepted_by_owner: boolean;
  canonical_record_id: string | null;
  canonical_status: string;
  authoritative_state_changed: boolean;
  plan_approved: boolean;
  plan_rejected: boolean;
  plan_revised: boolean;
  repair_executed: boolean;
  recovery_attempt_started: boolean;
  checkpoint_restored: boolean;
  process_restarted: boolean;
  workflow_changed: boolean;
  code_changed: boolean;
  artifact_changed: boolean;
  canonical_refresh_required: boolean;
  stale_state_rejected: boolean;
  duplicate_request_reused: boolean;
  error_code: string | null;
  bounded_error_message: string;
  limitations: string[];
}

export interface RepairPlanAnnotation {
  annotation_id: string;
  repair_plan_id: string;
  section_id: string;
  text: string;
  notice: string;
}

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */

export function formatTimestamp(value: string | null): string {
  if (!value) return "Time not recorded by the owner";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Time not recorded by the owner" : parsed.toLocaleString();
}

export function riskRank(level: string): number {
  const index = SOURCE_RISK_ORDER.indexOf(level);
  return index === -1 ? SOURCE_RISK_ORDER.length : index;
}

export function humanise(value: string): string {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Always attributes a status to the owner that recorded it. */
export function ownerStatusLabel(moduleId: string, status: string): string {
  return `${humanise(moduleId)} recorded: ${humanise(status)}`;
}

export function planStateLabel(item: RepairPlanQueueItem): string {
  if (item.superseded) return "Superseded";
  if (item.historical) return "Historical";
  if (item.completed) return "Carried out by its owner, not verified";
  if (item.stale) return "Stale";
  return "Current";
}

export function priorityLabel(item: RepairPlanQueueItem): string {
  return `Tier ${item.priority_tier} — ${humanise(item.priority_reason)}`;
}

export function strategyTypeLabel(item: RepairPlanQueueItem): string {
  return `Repair Planner proposed: ${humanise(item.original_strategy_type)}`;
}

export function recommendationLabel(item: RepairPlanQueueItem): string {
  return item.source_marked_recommended
    ? "Repair Planner marked this strategy recommended."
    : "Repair Planner did not mark this strategy recommended.";
}

export function reversibilityLabel(item: RepairPlanQueueItem): string {
  return `${humanise(item.original_reversibility)}. ${REVERSIBLE_NOTICE}`;
}

export function rollbackLabel(item: RepairPlanQueueItem): string {
  return item.rollback_available
    ? `A rollback plan is recorded. ${ROLLBACK_NOTICE}`
    : "No rollback plan is recorded for this repair case.";
}

/* ------------------------------------------------------------------ */
/* Queue filtering and sorting                                         */
/* ------------------------------------------------------------------ */

export interface RepairPlanFilterState {
  filter: RepairPlanReviewFilter;
  showHistorical: boolean;
  showSuperseded: boolean;
  showCompleted: boolean;
}

export function filterRepairPlans(
  items: RepairPlanQueueItem[],
  state: RepairPlanFilterState,
): RepairPlanQueueItem[] {
  let rows = state.showHistorical ? items : items.filter((item) => !item.historical);
  if (!state.showSuperseded) rows = rows.filter((item) => !item.superseded);
  if (!state.showCompleted) rows = rows.filter((item) => !item.completed);
  switch (state.filter) {
    case "human_review_required":
      return rows.filter((item) => item.human_action_required);
    case "destructive":
      return rows.filter((item) => item.destructive);
    case "reversible":
      return rows.filter((item) => item.reversible);
    case "code_change":
      return rows.filter((item) => item.requires_code_change);
    case "artifact_change":
      return rows.filter((item) => item.requires_artifact_change);
    case "workflow_change":
      return rows.filter((item) => item.requires_workflow_transition);
    case "tool_execution":
      return rows.filter((item) => item.requires_tool_execution);
    case "process_restart":
      return rows.filter((item) => item.requires_process_restart);
    case "checkpoint_restore":
      return rows.filter((item) => item.requires_checkpoint_restore);
    case "missing_approval":
      return rows.filter((item) => item.missing_approval_count > 0);
    case "missing_verification":
      return rows.filter((item) => item.missing_verification_count > 0);
    case "failed_recovery":
      return rows.filter((item) => item.failed_recovery_attempt_count > 0);
    case "conflicts":
      return rows.filter((item) => item.conflict_count > 0);
    case "stale":
      return rows.filter((item) => item.stale);
    case "completed":
      return items.filter((item) => item.completed);
    case "historical":
      return items.filter((item) => item.historical);
    case "superseded":
      return items.filter((item) => item.superseded);
    default:
      return rows;
  }
}

/** Deterministic ordering. Never reorders by an invented score. */
export function sortRepairPlans(
  items: RepairPlanQueueItem[],
  sort: RepairPlanReviewSort,
): RepairPlanQueueItem[] {
  const rows = [...items];
  if (sort === "source_severity") {
    rows.sort((a, b) => {
      const left = riskRank(a.original_risk_level);
      const right = riskRank(b.original_risk_level);
      return left === right
        ? a.deterministic_sort_key.localeCompare(b.deterministic_sort_key)
        : left - right;
    });
    return rows;
  }
  if (sort === "creation_order") {
    rows.sort((a, b) => a.deterministic_sort_key.localeCompare(b.deterministic_sort_key));
    return rows;
  }
  if (sort === "affected_module") {
    rows.sort(
      (a, b) =>
        a.affected_module_id.localeCompare(b.affected_module_id) ||
        a.deterministic_sort_key.localeCompare(b.deterministic_sort_key),
    );
    return rows;
  }
  if (sort === "step_count") {
    rows.sort(
      (a, b) =>
        b.step_count - a.step_count ||
        a.deterministic_sort_key.localeCompare(b.deterministic_sort_key),
    );
    return rows;
  }
  if (sort === "repair_plan_id") {
    rows.sort((a, b) => a.repair_plan_id.localeCompare(b.repair_plan_id));
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
/* Steps                                                               */
/* ------------------------------------------------------------------ */

/** Steps are always shown in the owner's own order. */
export function orderSteps(steps: RepairStepProjection[]): RepairStepProjection[] {
  return [...steps].sort(
    (a, b) => a.original_order - b.original_order || a.source_step_id.localeCompare(b.source_step_id),
  );
}

export function stepDescription(step: RepairStepProjection): string {
  return step.bounded_description || "No description recorded by Repair Planner.";
}

/** Every notice a step must carry, in a stable order. */
export function stepNotices(step: RepairStepProjection): string[] {
  const notices: string[] = [];
  if (step.raw_command_present_in_source) notices.push(COMMAND_WITHHELD_NOTICE);
  if (step.private_path_present_in_source) notices.push(PRIVATE_PATH_NOTICE);
  notices.push(NOT_EXECUTABLE_NOTICE);
  if (step.rollback_available) notices.push(ROLLBACK_NOTICE);
  return notices;
}

export function stepChangeLabels(step: RepairStepProjection): string[] {
  const labels: string[] = [];
  if (step.requires_code_change) labels.push("Proposes a code change");
  if (step.requires_artifact_change) labels.push("Proposes an artifact change");
  if (step.requires_tool_execution) labels.push("Needs tool execution");
  if (step.requires_process_restart) labels.push("Needs a process restart");
  if (step.requires_checkpoint_restore) labels.push("Needs a checkpoint restore");
  if (step.requires_workflow_transition) labels.push("Needs a workflow transition");
  if (step.read_only_by_owner) labels.push("Repair Planner marked this step read-only");
  return labels;
}

/** A step is never executable from this panel, whatever the source says. */
export function stepIsExecutable(_step: RepairStepProjection): false {
  return false;
}

export function commandBearingStepCount(steps: RepairStepProjection[]): number {
  return steps.filter((step) => step.raw_command_present_in_source).length;
}

/* ------------------------------------------------------------------ */
/* Risk                                                                */
/* ------------------------------------------------------------------ */

export function riskDimensionRows(rows: RepairRiskProjection[]): RepairRiskProjection[] {
  return RISK_DIMENSIONS.map((dimension) =>
    rows.find((row) => row.risk_dimension === dimension),
  ).filter((row): row is RepairRiskProjection => Boolean(row));
}

export function strategyRiskRows(rows: RepairRiskProjection[]): RepairRiskProjection[] {
  return rows.filter((row) => row.strategy_specific);
}

export function riskLabel(row: RepairRiskProjection): string {
  const base = `${humanise(row.risk_dimension)}: ${humanise(row.original_risk_level)}`;
  return row.blocked_by_owner ? `${base} (Repair Planner blocked this)` : base;
}

export function confidenceLabel(row: RepairRiskProjection): string | null {
  if (row.confidence_value === null) return null;
  return `${row.confidence_name || "owner confidence"}: ${row.confidence_value}`;
}

/** The panel never produces a composite risk or repair-success score. */
export function panelRiskScore(_rows: RepairRiskProjection[]): null {
  return null;
}

/* ------------------------------------------------------------------ */
/* Approvals and verification                                          */
/* ------------------------------------------------------------------ */

export function approvalLabel(row: RepairApprovalRequirement): string {
  const state = row.satisfied_by_owner
    ? "satisfied by a canonical owner record"
    : "not satisfied";
  return `${humanise(row.requirement_type)} — ${state}`;
}

export function missingApprovals(
  rows: RepairApprovalRequirement[],
): RepairApprovalRequirement[] {
  return rows.filter((row) => !row.satisfied_by_owner);
}

export function approvalSummary(rows: RepairApprovalRequirement[]): string {
  const missing = missingApprovals(rows).length;
  if (rows.length === 0) return "Repair Planner recorded no approval requirements.";
  if (missing === 0) return "Every recorded approval requirement names a canonical owner record.";
  const noun = missing === 1 ? "requirement" : "requirements";
  return `${missing} approval ${noun} not satisfied. A missing approval is not an approval.`;
}

export function verificationLabel(row: RepairVerificationRequirement): string {
  const state = row.satisfied ? "reported satisfied by its owner" : "not satisfied";
  return `${humanise(row.verification_type)} — ${state}`;
}

export function verificationSummary(rows: RepairVerificationRequirement[]): string {
  if (rows.length === 0) return "Repair Planner recorded no verification requirements.";
  const missing = rows.filter((row) => !row.satisfied).length;
  if (missing === 0) return `Every recorded check is reported satisfied. ${VERIFICATION_NOTICE}`;
  const noun = missing === 1 ? "check" : "checks";
  return `${missing} ${noun} not satisfied. ${VERIFICATION_NOTICE}`;
}

/** Independent verification is never claimed by this panel. */
export function independentlyVerifiedCount(
  rows: RepairVerificationRequirement[],
): number {
  return rows.filter((row) => row.independently_verified).length;
}

/* ------------------------------------------------------------------ */
/* Evidence                                                            */
/* ------------------------------------------------------------------ */

export function describeEvidenceCard(card: RepairEvidenceCard): string {
  if (card.missing) return `${card.title} — not available from ${humanise(card.source_module_id)}`;
  return `${card.title} — ${ownerStatusLabel(card.source_module_id, card.original_status)}`;
}

export function evidenceNotices(card: RepairEvidenceCard): string[] {
  const notices: string[] = [];
  if (card.command_withheld) notices.push(COMMAND_WITHHELD_NOTICE);
  if (card.private_paths_redacted) notices.push(PRIVATE_PATH_NOTICE);
  if (card.sensitive_values_redacted) notices.push("Sensitive values redacted.");
  if (card.excerpt_truncated) notices.push("Excerpt truncated.");
  if (card.advisory_only) notices.push("Advisory only. This does not authorise a repair.");
  notices.push(SOURCE_RETAINED_NOTICE);
  return notices;
}

export function missingEvidence(cards: RepairEvidenceCard[]): RepairEvidenceCard[] {
  return cards.filter((card) => card.missing);
}

export function evidenceSummary(cards: RepairEvidenceCard[]): string {
  const missing = missingEvidence(cards).length;
  if (missing === 0) return "Every linked canonical source is present.";
  const noun = missing === 1 ? "source" : "sources";
  return `${missing} ${noun} missing. Missing evidence is not a pass.`;
}

/* ------------------------------------------------------------------ */
/* Recovery                                                            */
/* ------------------------------------------------------------------ */

export function recoveryOutcomeLabel(link: RepairRecoveryLink): string {
  if (link.succeeded_by_owner) {
    return `Tool Recovery reported ${humanise(link.original_status)}. ${VERIFICATION_NOTICE}`;
  }
  return `Tool Recovery reported ${humanise(link.original_status)}.`;
}

export function recoveryNotices(link: RepairRecoveryLink): string[] {
  const notices: string[] = [];
  if (!link.linked_by_strategy_id) {
    notices.push(
      "This attempt is linked through the repair case, not through this exact strategy.",
    );
  }
  if (link.succeeded_by_owner) notices.push(VERIFICATION_NOTICE);
  notices.push(RECOVERED_NOTICE);
  if (link.rollback_attempted) {
    notices.push(`Rollback reported ${humanise(link.rollback_status)}. ${ROLLBACK_NOTICE}`);
  }
  return notices;
}

export function recoverySummary(links: RepairRecoveryLink[]): string {
  if (links.length === 0) return "No linked recovery attempt is recorded.";
  const failed = links.filter((link) =>
    ["failed", "timed_out", "blocked", "rejected", "rolled_back"].includes(
      link.original_status,
    ),
  ).length;
  const succeeded = links.filter((link) => link.succeeded_by_owner).length;
  return `${links.length} attempt(s): ${succeeded} reported successful by its owner, ${failed} failed. ${RECOVERED_NOTICE}`;
}

/* ------------------------------------------------------------------ */
/* Conflicts                                                           */
/* ------------------------------------------------------------------ */

export function blockingConflicts(rows: RepairPlanConflict[]): RepairPlanConflict[] {
  return rows.filter((row) => row.blocks_action);
}

export function conflictSummary(rows: RepairPlanConflict[]): string {
  if (rows.length === 0) return "No conflicting canonical records were found.";
  const blocking = blockingConflicts(rows).length;
  return `${rows.length} conflict(s), ${blocking} blocking. A conflict is never resolved automatically.`;
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */

export function availableActions(
  descriptors: RepairPlanActionDescriptor[],
  snapshot: RepairPlanSnapshot,
): RepairPlanActionDescriptor[] {
  return descriptors.filter(
    (descriptor) =>
      descriptor.allowed_in_v1 &&
      descriptor.availability === "available" &&
      snapshot.available_action_descriptor_ids.includes(descriptor.action_descriptor_id),
  );
}

export function unavailableActions(
  descriptors: RepairPlanActionDescriptor[],
): RepairPlanActionDescriptor[] {
  return descriptors.filter((descriptor) => descriptor.availability !== "available");
}

/** A descriptor that could change or execute anything is never offered. */
export function descriptorIsSafeForPanel(descriptor: RepairPlanActionDescriptor): boolean {
  return (
    !descriptor.authoritative &&
    !descriptor.destructive &&
    !descriptor.execution_capable &&
    !descriptor.code_modifying &&
    !descriptor.artifact_modifying &&
    !descriptor.workflow_modifying &&
    !descriptor.checkpoint_restoring &&
    !descriptor.process_restarting &&
    !descriptor.upload_or_publication
  );
}

export const CONFIRMATION_STATEMENT =
  "This request does not directly execute commands, modify code, change artifacts, restore a checkpoint, restart a process, transition the workflow, grant Rights or Safety approval, upload content or publish content.";

export function confirmationLines(descriptor: RepairPlanActionDescriptor): string[] {
  return [
    `${descriptor.display_name} is owned by ${humanise(descriptor.owning_module_id)}.`,
    ...descriptor.consequences,
    CONFIRMATION_STATEMENT,
    ...descriptor.does_not_do,
  ];
}

export function receiptSummary(receipt: RepairPlanActionReceipt): string {
  if (receipt.stale_state_rejected) {
    return "The repair plan changed while this review was open, so nothing was submitted.";
  }
  if (!receipt.accepted_by_owner) {
    return `The canonical owner did not accept this request: ${humanise(receipt.canonical_status)}.`;
  }
  return `${humanise(receipt.owning_module_id)} recorded this acknowledgement. The repair plan is unchanged.`;
}

/** Truthfully reports that a receipt changed no authority. */
export function receiptChangedNothing(receipt: RepairPlanActionReceipt): boolean {
  return (
    !receipt.authoritative_state_changed &&
    !receipt.plan_approved &&
    !receipt.plan_rejected &&
    !receipt.plan_revised &&
    !receipt.repair_executed &&
    !receipt.recovery_attempt_started &&
    !receipt.checkpoint_restored &&
    !receipt.process_restarted &&
    !receipt.workflow_changed &&
    !receipt.code_changed &&
    !receipt.artifact_changed
  );
}

/* ------------------------------------------------------------------ */
/* Annotations                                                         */
/* ------------------------------------------------------------------ */

const SENSITIVE_KEY = /(secret|token|password|credential|cookie|authorization)/i;
const SHELL_TOKEN = /(?:\|\||&&|[|><;`]|\$\(|\r|\n)/;
const COMMAND_EXECUTABLE =
  /(?:^|[\s"'])(?:ffmpeg|ffprobe|git|python3?|pip3?|npm|npx|yarn|pnpm|node|bash|sh|zsh|powershell|pwsh|cmd|docker|apt|apt-get|brew|curl|wget|make|systemctl|kill|pkill|rm|mv|cp|chmod|chown|sudo|ssh|scp|rsync)\b/i;
const PRIVATE_PATH = /(?:[A-Za-z]:[\\/]|file:|\/home\/|\/Users\/|\\\\)/i;

export function annotationIsAcceptable(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (trimmed.length > MAX_ANNOTATION_LENGTH) return false;
  if (SENSITIVE_KEY.test(trimmed)) return false;
  if (SHELL_TOKEN.test(trimmed)) return false;
  if (COMMAND_EXECUTABLE.test(trimmed)) return false;
  if (PRIVATE_PATH.test(trimmed)) return false;
  return true;
}

export function boundedAnnotations(rows: RepairPlanAnnotation[]): RepairPlanAnnotation[] {
  return rows
    .filter((row) => annotationIsAcceptable(row.text))
    .slice(0, MAX_ANNOTATIONS)
    .map((row) => ({ ...row, notice: ANNOTATION_NOTICE }));
}

/* ------------------------------------------------------------------ */
/* Panel-level summary                                                 */
/* ------------------------------------------------------------------ */

export function planLimitations(item: RepairPlanQueueItem): string[] {
  const rows = [PROPOSED_PLAN_NOTICE, NOT_EXECUTABLE_NOTICE, NO_EXECUTION_NOTICE];
  if (item.reversible) rows.push(REVERSIBLE_NOTICE);
  if (item.rollback_available) rows.push(ROLLBACK_NOTICE);
  if (item.completed) rows.push(RECOVERED_NOTICE);
  if (item.command_bearing_step_count > 0) rows.push(COMMAND_WITHHELD_NOTICE);
  return rows;
}

export function safestNextReviewAction(items: RepairPlanQueueItem[]): string {
  if (items.length === 0) return "No repair-plan review work is outstanding.";
  const sorted = sortRepairPlans(items, "review_priority");
  return `Read ${sorted[0].repair_plan_id} and its canonical evidence before any owner is asked to act.`;
}

/* ------------------------------------------------------------------ */
/* Interaction helpers                                                 */
/* ------------------------------------------------------------------ */

export function canCompare(selected: string[]): boolean {
  return selected.length >= 2 && selected.length <= MAX_COMPARISON_PLANS;
}

export function toggleComparison(selected: string[], repairPlanId: string): string[] {
  if (selected.includes(repairPlanId)) {
    return selected.filter((item) => item !== repairPlanId);
  }
  if (selected.length >= MAX_COMPARISON_PLANS) return selected;
  return [...selected, repairPlanId];
}

export function unsupportedSchemaNotice(reference: RepairPlanReference): string | null {
  if (reference.schema_supported) return null;
  return `This plan uses schema '${reference.source_schema_id}', which this panel does not support. Its fields are shown only as the owner recorded them.`;
}

export function revisionNotice(reference: RepairPlanReference): string {
  return "Repair Planner records no strategy revision identity and no supersession field, so neither is shown.";
}

export function unavailableActionNotice(
  descriptor: RepairPlanActionDescriptor,
): string {
  return `${descriptor.display_name} is unavailable in V1. ${descriptor.unavailable_reason}`;
}

export function validateActionReason(
  descriptor: RepairPlanActionDescriptor,
  reason: string,
): string | null {
  const trimmed = reason.trim();
  if (descriptor.requires_reason && !trimmed) {
    return "This action requires a reason.";
  }
  if (trimmed.length > descriptor.maximum_reason_length) {
    return `A reason may be at most ${descriptor.maximum_reason_length} characters.`;
  }
  if (trimmed && !annotationIsAcceptable(trimmed)) {
    return "A reason cannot contain credentials, command text or a private path.";
  }
  return null;
}

export function canSubmitAction(
  descriptor: RepairPlanActionDescriptor | null,
  snapshot: RepairPlanSnapshot | null,
  reason: string,
  confirmed: boolean,
): boolean {
  if (!descriptor || !snapshot) return false;
  if (!descriptor.allowed_in_v1 || descriptor.availability !== "available") return false;
  if (!descriptorIsSafeForPanel(descriptor)) return false;
  if (!snapshot.available_action_descriptor_ids.includes(descriptor.action_descriptor_id)) {
    return false;
  }
  if (descriptor.requires_confirmation && !confirmed) return false;
  return validateActionReason(descriptor, reason) === null;
}

export function buildAnnotation(
  repairPlanId: string,
  sectionId: string,
  text: string,
): RepairPlanAnnotation | null {
  if (!annotationIsAcceptable(text)) return null;
  return {
    annotation_id: `repair_plan_annotation_${repairPlanId}_${sectionId}_${text.length}`,
    repair_plan_id: repairPlanId,
    section_id: sectionId,
    text: text.trim(),
    notice: ANNOTATION_NOTICE,
  };
}

export function upsertAnnotation(
  rows: RepairPlanAnnotation[],
  row: RepairPlanAnnotation,
): RepairPlanAnnotation[] {
  const without = rows.filter((item) => item.annotation_id !== row.annotation_id);
  return boundedAnnotations([...without, row]);
}

export function removeAnnotation(
  rows: RepairPlanAnnotation[],
  annotationId: string,
): RepairPlanAnnotation[] {
  return rows.filter((item) => item.annotation_id !== annotationId);
}

export function conflictSeverityLabel(row: RepairPlanConflict): string {
  return `${humanise(row.conflict_type)} (${humanise(row.severity)})`;
}

export function receiptChangeLabels(receipt: RepairPlanActionReceipt): string[] {
  const labels: string[] = [];
  if (receipt.plan_approved) labels.push("Plan approved");
  if (receipt.plan_rejected) labels.push("Plan rejected");
  if (receipt.plan_revised) labels.push("Plan revised");
  if (receipt.repair_executed) labels.push("Repair executed");
  if (receipt.recovery_attempt_started) labels.push("Recovery started");
  if (receipt.checkpoint_restored) labels.push("Checkpoint restored");
  if (receipt.process_restarted) labels.push("Process restarted");
  if (receipt.workflow_changed) labels.push("Workflow changed");
  if (receipt.code_changed) labels.push("Code changed");
  if (receipt.artifact_changed) labels.push("Artifact changed");
  return labels.length > 0 ? labels : ["No authoritative state changed"];
}
