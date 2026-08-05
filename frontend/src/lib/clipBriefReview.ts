/**
 * Pure logic for the BOBA Clip Brief Panel.
 *
 * The panel is a read-only clip brief projection, an evidence workspace, a
 * comparison surface and a safe canonical action router. Nothing here generates,
 * regenerates or rewrites a brief, invents a field the owner schema does not
 * define, computes a quality or virality score, chooses a winning brief, or
 * approves anything locally. Completeness means only that required owner-schema
 * fields are present.
 */

import { isSafePreviewReference, protectedPreviewUrl } from "@/lib/reviewUi";

export const MAX_COMPARISON_BRIEFS = 4;
export const QUEUE_PAGE_SIZE = 50;
export const MAX_ANNOTATION_LENGTH = 4_000;
export const MAX_ANNOTATIONS = 32;
export const MAX_PREVIEW_CONTEXT_SECONDS = 60;
export const SUPPORTED_BRIEF_SCHEMA_ID = "boba_clip_brief_generator_v1";

export type ClipBriefReviewFilter =
  | "all_current"
  | "human_review_required"
  | "current_selected_candidate"
  | "missing_required_fields"
  | "missing_evidence"
  | "conflicts"
  | "stale"
  | "complete_for_owner_schema"
  | "warnings"
  | "historical"
  | "superseded";

export type ClipBriefReviewSort =
  | "review_priority"
  | "candidate_rank"
  | "created_sequence"
  | "source_start_time"
  | "brief_id";

export type ClipBriefCompletenessStatus =
  | "complete"
  | "complete_with_optional_gaps"
  | "missing_required_fields"
  | "unsupported_schema"
  | "stale"
  | "unavailable";

export interface ClipBriefQueueItem {
  brief_queue_item_id: string;
  brief_reference_id: string;
  project_id: string;
  candidate_id: string;
  clip_id: string;
  brief_id: string;
  title: string;
  bounded_summary: string;
  owner_module_id: string;
  original_status: string;
  candidate_status: string;
  editorial_status: string;
  completeness_status: ClipBriefCompletenessStatus;
  evidence_status: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  candidate_rank: number | null;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  human_action_required: boolean;
  blocker_count: number;
  warning_count: number;
  missing_required_field_count: number;
  missing_optional_field_count: number;
  missing_evidence_count: number;
  conflict_count: number;
  available_action_descriptor_ids: string[];
  source_module_ids: string[];
  priority_tier: number;
  priority_reason: string;
  deterministic_sort_key: string;
  warnings: string[];
  limitations: string[];
}

export interface ClipBriefReference {
  brief_reference_id: string;
  project_id: string;
  candidate_id: string;
  clip_id: string;
  brief_id: string;
  brief_revision_id: string | null;
  brief_schema_id: string;
  schema_supported: boolean;
  lifecycle_bucket: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  superseding_brief_id: string | null;
  warnings: string[];
  limitations: string[];
}

export interface ClipBriefFieldProjection {
  field_projection_id: string;
  field_path: string;
  field_display_name: string;
  field_category: string;
  original_value: unknown;
  value_type: string;
  required_by_owner_schema: boolean;
  present: boolean;
  empty: boolean;
  unavailable: boolean;
  truncated_for_display: boolean;
  source_owned: boolean;
  advisory: boolean;
  human_editable: boolean;
  bounded_explanation: string;
  limitations: string[];
}

export interface ClipBriefSectionProjection {
  section_projection_id: string;
  section_id: string;
  title: string;
  field_projection_ids: string[];
  visible: boolean;
  empty: boolean;
  unavailable: boolean;
  required_field_count: number;
  present_required_field_count: number;
  optional_field_count: number;
  present_optional_field_count: number;
  warning_count: number;
  collapsed_by_default: boolean;
  bounded_empty_message: string;
  bounded_unavailable_message: string;
}

export interface ClipBriefSourceCard {
  source_card_id: string;
  source_module_id: string;
  authority_domain: string;
  title: string;
  original_status: string;
  original_decision: string | null;
  bounded_summary: string;
  easy_explanation: string;
  current: boolean;
  authoritative: boolean;
  advisory_only: boolean;
  blocking: boolean;
  human_review_required: boolean;
  warnings: string[];
  limitations: string[];
}

export interface ClipBriefEvidenceLink {
  evidence_link_id: string;
  brief_field_path: string;
  evidence_type: string;
  source_module_id: string;
  candidate_id: string | null;
  clip_id: string | null;
  transcript_segment_ids: string[];
  source_start_seconds: number | null;
  source_end_seconds: number | null;
  exact_identity_match: boolean;
  digest_match: boolean;
  missing: boolean;
  authoritative: boolean;
  advisory: boolean;
  bounded_summary: string;
  limitations: string[];
}

export interface ClipBriefCompleteness {
  completeness_record_id: string;
  owner_schema_id: string;
  required_field_paths: string[];
  present_required_field_paths: string[];
  missing_required_field_paths: string[];
  optional_field_paths: string[];
  present_optional_field_paths: string[];
  missing_optional_field_paths: string[];
  required_field_count: number;
  present_required_field_count: number;
  optional_field_count: number;
  present_optional_field_count: number;
  required_completion_ratio: number;
  optional_completion_ratio: number;
  completeness_status: ClipBriefCompletenessStatus;
  complete_for_owner_schema: boolean;
  blocking_reasons: string[];
}

export interface ClipBriefConflict {
  conflict_record_id: string;
  conflict_type: string;
  severity: string;
  brief_field_paths: string[];
  source_card_ids: string[];
  source_record_ids: string[];
  value_a: string;
  value_b: string;
  same_candidate: boolean;
  same_clip: boolean;
  current_records: boolean;
  explicit_supersession_found: boolean;
  resolved: boolean;
  resolution_source_id: string | null;
  blocks_review_action: boolean;
  human_review_required: boolean;
  bounded_summary: string;
  warnings: string[];
  limitations: string[];
}

export interface ClipBriefSnapshot {
  brief_snapshot_id: string;
  clip_brief_review_session_id: string;
  project_id: string;
  candidate_id: string;
  clip_id: string;
  brief_id: string;
  brief_digest: string;
  snapshot_digest: string;
  brief_status: string;
  candidate_status: string;
  editorial_status: string;
  rights_status: string;
  workflow_status: string;
  human_review_status: string;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  missing_required_field_count: number;
  missing_optional_field_count: number;
  missing_evidence_count: number;
  conflict_count: number;
  available_action_descriptor_ids: string[];
  limitations: string[];
}

export interface ClipBriefActionDescriptor {
  action_descriptor_id: string;
  display_name: string;
  action_class: string;
  owning_module_id: string;
  owning_operation_id: string;
  supported_brief_states: string[];
  allowed_decision_values: string[];
  requires_reason: boolean;
  maximum_reason_length: number;
  requires_confirmation: boolean;
  requires_current_snapshot: boolean;
  requires_reviewer_context: boolean;
  authoritative: boolean;
  destructive: boolean;
  execution_capable: boolean;
  upload_or_publication: boolean;
  allowed_in_v1: boolean;
  availability: "available" | "unavailable";
  consequences: string[];
  does_not_do: string[];
  warnings: string[];
  limitations: string[];
}

export interface ClipBriefActionReceipt {
  clip_brief_action_receipt_id: string;
  owning_module_id: string;
  owning_operation_id: string;
  accepted_by_owner: boolean;
  canonical_status: string;
  canonical_record_id: string | null;
  canonical_record_digest: string | null;
  authoritative_state_changed: boolean;
  stale_state_rejected: boolean;
  duplicate_request_reused: boolean;
  error_code: string | null;
  bounded_error_message: string;
  limitations: string[];
}

export interface ClipBriefComparison {
  comparison_id: string;
  brief_ids: string[];
  candidate_ids: string[];
  comparison_type: string;
  same_candidate: boolean;
  same_clip: boolean;
  field_comparisons: {
    field_path: string;
    field_display_name: string;
    required_by_owner_schema: boolean;
    values: { brief_id: string; present: boolean; original_value: unknown }[];
  }[];
  limitations: string[];
}

export interface ClipBriefAnnotation {
  annotation_id: string;
  field_path: string;
  text: string;
  notice: string;
}

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */

export function formatTimecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function formatSourceWindow(startSeconds: number, endSeconds: number): string {
  return `${formatTimecode(startSeconds)} – ${formatTimecode(endSeconds)}`;
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown";
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
}

/* ------------------------------------------------------------------ */
/* Field and section presentation                                      */
/* ------------------------------------------------------------------ */

/** Field state describes owner presence only. It never grades the value. */
export function fieldStateLabel(field: ClipBriefFieldProjection): string {
  if (field.unavailable) return "Missing from the persisted brief";
  if (field.empty) return "Persisted as empty by the owner";
  if (!field.present) return "No usable value persisted";
  if (field.advisory) return "Supplied by the owner as advisory guidance";
  return "Supplied by the owner";
}

export function fieldStateGlyph(field: ClipBriefFieldProjection): string {
  if (field.unavailable) return "absent";
  if (field.empty) return "empty";
  if (!field.present) return "unusable";
  return "present";
}

export function requiredBadge(field: ClipBriefFieldProjection): string {
  return field.required_by_owner_schema ? "Required by owner schema" : "Optional";
}

/** Missing values are shown as missing. They are never filled in or guessed. */
export function fieldDisplayValue(field: ClipBriefFieldProjection): string {
  if (field.unavailable) return "— missing —";
  if (field.empty) return "— empty —";
  if (field.original_value === null || field.original_value === undefined) {
    return "— not persisted —";
  }
  if (typeof field.original_value === "string") return field.original_value;
  return JSON.stringify(field.original_value, null, 2);
}

export function sectionSummary(section: ClipBriefSectionProjection): string {
  if (section.unavailable) return section.bounded_unavailable_message;
  if (section.empty) return section.bounded_empty_message;
  return (
    `${section.present_required_field_count}/${section.required_field_count} required, ` +
    `${section.present_optional_field_count}/${section.optional_field_count} optional present`
  );
}

export function isSectionExpanded(
  section: ClipBriefSectionProjection,
  activeSectionId: string | null,
): boolean {
  if (activeSectionId === section.section_id) return true;
  return !section.collapsed_by_default;
}

/* ------------------------------------------------------------------ */
/* Completeness                                                        */
/* ------------------------------------------------------------------ */

export function completenessLabel(status: ClipBriefCompletenessStatus): string {
  switch (status) {
    case "complete":
      return "All owner-schema fields present";
    case "complete_with_optional_gaps":
      return "All required fields present, optional gaps remain";
    case "missing_required_fields":
      return "Required owner-schema fields missing";
    case "unsupported_schema":
      return "Brief schema is not supported by this panel";
    case "stale":
      return "Projection is stale";
    default:
      return "Completeness unavailable";
  }
}

export function completenessGlyph(status: ClipBriefCompletenessStatus): string {
  if (status === "complete") return "complete";
  if (status === "complete_with_optional_gaps") return "partial";
  return "incomplete";
}

/**
 * The single sentence that must accompany every completeness readout. Field
 * presence is not creative quality, technical validity, Rights clearance,
 * Safety approval, approval or render readiness.
 */
export const COMPLETENESS_NOTICE =
  "Completeness means only that required owner-schema fields are present. " +
  "It is not quality, approval, technical validation or render readiness.";

export function completenessNotice(record: ClipBriefCompleteness | null): string {
  if (!record) return COMPLETENESS_NOTICE;
  if (record.blocking_reasons.length > 0) {
    return `${record.blocking_reasons.length} required field(s) missing. ${COMPLETENESS_NOTICE}`;
  }
  return COMPLETENESS_NOTICE;
}

export function missingFieldSummary(record: ClipBriefCompleteness | null): string {
  if (!record) return "No completeness record is available.";
  if (record.missing_required_field_paths.length === 0) {
    return "No required owner-schema field is missing.";
  }
  return `Missing required fields: ${record.missing_required_field_paths.join(", ")}`;
}

/* ------------------------------------------------------------------ */
/* Queue                                                               */
/* ------------------------------------------------------------------ */

export interface ClipBriefFilterState {
  filter: ClipBriefReviewFilter;
  showHistorical: boolean;
}

export function filterBriefs(
  items: ClipBriefQueueItem[],
  state: ClipBriefFilterState,
): ClipBriefQueueItem[] {
  const rows = state.showHistorical ? items : items.filter((item) => !item.historical);
  switch (state.filter) {
    case "human_review_required":
      return rows.filter((item) => item.human_action_required);
    case "current_selected_candidate":
      return rows.filter((item) => item.editorial_status === "selected");
    case "missing_required_fields":
      return rows.filter((item) => item.missing_required_field_count > 0);
    case "missing_evidence":
      return rows.filter((item) => item.missing_evidence_count > 0);
    case "conflicts":
      return rows.filter((item) => item.conflict_count > 0);
    case "stale":
      return rows.filter((item) => item.stale);
    case "complete_for_owner_schema":
      return rows.filter(
        (item) =>
          item.completeness_status === "complete" ||
          item.completeness_status === "complete_with_optional_gaps",
      );
    case "warnings":
      return rows.filter((item) => item.warning_count > 0);
    case "historical":
      return items.filter((item) => item.historical);
    case "superseded":
      return items.filter((item) => item.superseded);
    default:
      return rows;
  }
}

/** Sorting is deterministic and never reorders by an invented quality score. */
export function sortBriefs(
  items: ClipBriefQueueItem[],
  sort: ClipBriefReviewSort,
): ClipBriefQueueItem[] {
  const rows = [...items];
  if (sort === "candidate_rank") {
    rows.sort((a, b) => {
      const left = a.candidate_rank ?? Number.MAX_SAFE_INTEGER;
      const right = b.candidate_rank ?? Number.MAX_SAFE_INTEGER;
      return left === right ? a.brief_id.localeCompare(b.brief_id) : left - right;
    });
    return rows;
  }
  if (sort === "brief_id") {
    rows.sort((a, b) => a.brief_id.localeCompare(b.brief_id));
    return rows;
  }
  if (sort === "created_sequence" || sort === "source_start_time") {
    rows.sort((a, b) =>
      a.deterministic_sort_key === b.deterministic_sort_key
        ? a.brief_id.localeCompare(b.brief_id)
        : a.deterministic_sort_key.localeCompare(b.deterministic_sort_key),
    );
    return rows;
  }
  rows.sort((a, b) =>
    a.priority_tier === b.priority_tier
      ? a.deterministic_sort_key.localeCompare(b.deterministic_sort_key)
      : a.priority_tier - b.priority_tier,
  );
  return rows;
}

export function priorityLabel(item: ClipBriefQueueItem): string {
  return `Tier ${item.priority_tier}: ${item.priority_reason}`;
}

export function briefStateLabel(item: ClipBriefQueueItem): string {
  if (item.superseded) return "Superseded";
  if (item.historical) return "Historical";
  if (item.stale) return "Stale";
  if (item.current) return "Current";
  return "Unknown";
}

export function evidenceSummary(item: ClipBriefQueueItem): string {
  if (item.missing_evidence_count === 0) return "All linked source evidence is present.";
  const noun = item.missing_evidence_count === 1 ? "source" : "sources";
  return `${item.missing_evidence_count} ${noun} missing. Missing evidence is not a pass.`;
}

export function conflictSummary(conflicts: ClipBriefConflict[]): string {
  if (conflicts.length === 0) return "No conflict was detected against canonical sources.";
  const blocking = conflicts.filter((item) => item.blocks_review_action).length;
  return (
    `${conflicts.length} conflict(s) against canonical sources, ${blocking} blocking. ` +
    "Conflicts are reported unresolved; the panel never picks a winner and never " +
    "resolves a conflict by comparing confidence."
  );
}

/** An unresolved conflict stays unresolved and is named as such. */
export function conflictResolutionLabel(conflict: ClipBriefConflict): string {
  if (conflict.resolved && conflict.resolution_source_id) {
    return `Resolved by ${conflict.resolution_source_id}.`;
  }
  return "Unresolved. Only the owning module can resolve this.";
}

/* ------------------------------------------------------------------ */
/* Comparison                                                          */
/* ------------------------------------------------------------------ */

export function toggleComparison(selected: string[], briefId: string): string[] {
  if (selected.includes(briefId)) return selected.filter((item) => item !== briefId);
  if (selected.length >= MAX_COMPARISON_BRIEFS) return selected;
  return [...selected, briefId];
}

export function canCompare(selected: string[]): boolean {
  return selected.length >= 2 && selected.length <= MAX_COMPARISON_BRIEFS;
}

/**
 * Comparison shows differences side by side. It never scores a brief, ranks the
 * set, or marks a winner, and missing fields stay visible as missing.
 */
export const NO_WINNER_NOTICE =
  "Comparison shows differences only. No brief is scored, preferred or chosen.";

export function comparisonDifferences(
  comparison: ClipBriefComparison | null,
): ClipBriefComparison["field_comparisons"] {
  if (!comparison) return [];
  return comparison.field_comparisons.filter((row) => {
    const rendered = row.values.map((value) =>
      value.present ? JSON.stringify(value.original_value) : "__missing__",
    );
    return new Set(rendered).size > 1;
  });
}

export function comparisonMissingFields(
  comparison: ClipBriefComparison | null,
): string[] {
  if (!comparison) return [];
  return comparison.field_comparisons
    .filter((row) => row.values.some((value) => !value.present))
    .map((row) => row.field_path);
}

/* ------------------------------------------------------------------ */
/* Preview                                                             */
/* ------------------------------------------------------------------ */

export interface ClipBriefPreview {
  url: string | null;
  startSeconds: number;
  endSeconds: number;
  contextStartSeconds: number;
  contextEndSeconds: number;
  contextNotice: string;
  playbackNotice: string;
  unavailableReason: string | null;
}

/**
 * Preview publishes the exact persisted source window. The browser cannot
 * substitute its own range: only a bounded read-only context hint is offered,
 * and the brief boundaries are always the owner values.
 */
export function buildClipBriefPreview(
  projectId: string,
  reference: Pick<ClipBriefReference, "start_seconds" | "end_seconds"> | null,
  contextSeconds = 0,
): ClipBriefPreview {
  const safe = isSafePreviewReference(projectId);
  const url = safe ? protectedPreviewUrl(projectId) : null;
  const bounded = Math.max(0, Math.min(contextSeconds, MAX_PREVIEW_CONTEXT_SECONDS));
  const start = reference?.start_seconds ?? 0;
  const end = reference?.end_seconds ?? 0;
  return {
    url,
    startSeconds: start,
    endSeconds: end,
    contextStartSeconds: Math.max(0, start - bounded),
    contextEndSeconds: end + bounded,
    contextNotice:
      "Preview context only. It is not authoritative and never changes the persisted brief window.",
    playbackNotice: "Playing the preview is not validation and approves nothing.",
    unavailableReason:
      url === null
        ? "Preview unavailable. No protected same-origin source exists for this project."
        : reference === null
          ? "Preview unavailable. No exact persisted source window is bound."
          : null,
  };
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */

export function availableActions(
  descriptors: ClipBriefActionDescriptor[],
  snapshot: ClipBriefSnapshot | null,
  confirmations: Record<string, string>,
): ClipBriefActionDescriptor[] {
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
  descriptors: ClipBriefActionDescriptor[],
  snapshot: ClipBriefSnapshot | null,
  confirmations: Record<string, string>,
): ClipBriefActionDescriptor[] {
  const available = new Set(
    availableActions(descriptors, snapshot, confirmations).map(
      (item) => item.action_descriptor_id,
    ),
  );
  return descriptors.filter((item) => !available.has(item.action_descriptor_id));
}

/** Unavailable actions are explained honestly. No substitute authority is offered. */
export function unavailableActionNotice(descriptor: ClipBriefActionDescriptor): string {
  if (descriptor.availability === "available" && descriptor.allowed_in_v1) return "";
  if (descriptor.limitations.length > 0) return descriptor.limitations.join(" ");
  return "No canonical owner operation exists for this action, so the panel does not offer it.";
}

export const NO_AUTHORITATIVE_ACTION_NOTICE =
  "Clip Brief Panel V1 exposes no authoritative brief approval, rejection, " +
  "revision or regeneration action. Available actions are advisory only.";

export function receiptChangedAuthority(
  receipt: ClipBriefActionReceipt | null | undefined,
): boolean {
  if (!receipt) return false;
  return Boolean(
    receipt.authoritative_state_changed &&
      receipt.canonical_record_id &&
      receipt.canonical_record_digest,
  );
}

export function receiptSummary(receipt: ClipBriefActionReceipt | null | undefined): string {
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
    `${receipt.owning_module_id} recorded ${receipt.canonical_record_id ?? "a record"}. ` +
    "This is advisory: no authoritative clip brief state changed."
  );
}

/** A reason is required, bounded, and never allowed to carry credentials. */
const SENSITIVE_TEXT = /secret|token|password|credential/i;

export function validateActionReason(
  reason: string,
  descriptor: ClipBriefActionDescriptor,
): string | null {
  if (descriptor.requires_reason && reason.trim().length === 0) {
    return "A reason is required for this action.";
  }
  if (reason.length > descriptor.maximum_reason_length) {
    return `The reason must be ${descriptor.maximum_reason_length} characters or fewer.`;
  }
  if (SENSITIVE_TEXT.test(reason)) return "The reason cannot contain credentials.";
  return null;
}

export function canSubmitAction(
  descriptor: ClipBriefActionDescriptor,
  snapshot: ClipBriefSnapshot | null,
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

/* ------------------------------------------------------------------ */
/* Review-session annotations                                          */
/* ------------------------------------------------------------------ */

/** The exact notice that must accompany every local annotation. */
export const LOCAL_ANNOTATION_NOTICE =
  "Review-session annotation — not part of the canonical clip brief.";

export function buildAnnotation(
  fieldPath: string,
  text: string,
  annotationId?: string,
): ClipBriefAnnotation | null {
  const bounded = text.trim().slice(0, MAX_ANNOTATION_LENGTH);
  if (!bounded) return null;
  if (SENSITIVE_TEXT.test(bounded)) return null;
  return {
    annotation_id: annotationId ?? `annotation_${fieldPath}_${bounded.length}`,
    field_path: fieldPath,
    text: bounded,
    notice: LOCAL_ANNOTATION_NOTICE,
  };
}

export function upsertAnnotation(
  annotations: ClipBriefAnnotation[],
  annotation: ClipBriefAnnotation,
): ClipBriefAnnotation[] {
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
  annotations: ClipBriefAnnotation[],
  annotationId: string,
): ClipBriefAnnotation[] {
  return annotations.filter((item) => item.annotation_id !== annotationId);
}

/* ------------------------------------------------------------------ */
/* Source cards and schema support                                     */
/* ------------------------------------------------------------------ */

export function describeSourceCard(card: ClipBriefSourceCard): string {
  if (!card.current) return `${card.title}: no canonical record is available.`;
  const suffix = card.advisory_only ? " (advisory, not a decision)" : "";
  return `${card.title}: ${card.original_status.replace(/_/g, " ")}${suffix}`;
}

export function unsupportedSchemaNotice(reference: ClipBriefReference | null): string {
  if (!reference || reference.schema_supported) return "";
  return (
    `Brief schema "${reference.brief_schema_id}" is not supported by this panel. ` +
    "Fields are shown as stored and no field is interpreted."
  );
}

/**
 * The owner schema defines no revision identity and no supersession field, so
 * the panel reports both as absent rather than inferring them.
 */
export function revisionNotice(reference: ClipBriefReference | null): string {
  if (!reference) return "";
  if (reference.brief_revision_id) return `Revision ${reference.brief_revision_id}.`;
  return "The owner records no revision identity for clip briefs, so none is shown.";
}
