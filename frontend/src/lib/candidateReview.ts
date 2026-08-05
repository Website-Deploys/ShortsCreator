/**
 * Pure logic for the BOBA Candidate Review Panel.
 *
 * The panel is a read-only candidate projection, a comparison workspace and a
 * safe canonical action router. Nothing here discovers candidates, reranks them,
 * recomputes a source-owned score, builds a hidden composite, or chooses a
 * winner. Ranks and scores keep their original owner, scale and definition.
 */

import { protectedPreviewUrl } from "@/lib/reviewUi";

export const MAX_COMPARISON_CANDIDATES = 4;
export const SUBSTANTIAL_OVERLAP_IOU_THRESHOLD = 0.6;
export const QUEUE_PAGE_SIZE = 50;
export const MAX_TRANSCRIPT_CONTEXT_SECONDS = 60;

export type CandidateReviewFilter =
  | "all_current"
  | "human_review_required"
  | "source_shortlisted"
  | "selected"
  | "rejected"
  | "blocked"
  | "stale"
  | "overlapping"
  | "missing_evidence"
  | "historical";

export type CandidateReviewSort =
  | "review_priority"
  | "original_rank"
  | "source_start_time"
  | "duration"
  | "creation_order"
  | "candidate_id";

export interface CandidateQueueItem {
  candidate_queue_item_id: string;
  candidate_reference_id: string;
  project_id: string;
  candidate_id: string;
  title: string;
  bounded_summary: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  original_discovery_status: string;
  original_rank: number | null;
  original_rank_total: number | null;
  rank_owner_module_id: string;
  primary_score: number | null;
  primary_score_name: string;
  primary_score_owner_module_id: string;
  editorial_status: string;
  review_status: string;
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
  rejected: boolean;
  selected: boolean;
  human_action_required: boolean;
  blocker_count: number;
  warning_count: number;
  missing_evidence_count: number;
  conflict_count: number;
  duplicate_group_id: string | null;
  overlap_group_ids: string[];
  available_action_descriptor_ids: string[];
  source_module_ids: string[];
  priority_tier: number;
  priority_reason: string;
  deterministic_sort_key: string;
  warnings: string[];
  limitations: string[];
}

export interface CandidateReference {
  candidate_id: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  transcript_segment_ids: string[];
  current: boolean;
  stale: boolean;
  historical: boolean;
  superseded: boolean;
}

export interface CandidateScoreCard {
  score_card_id: string;
  candidate_id: string;
  source_module_id: string;
  score_name: string;
  score_value: number;
  score_scale_min: number;
  score_scale_max: number;
  score_definition: string;
  score_direction: "higher_is_better" | "lower_is_better" | "unknown";
  rank: number | null;
  rank_total: number | null;
  tied: boolean;
  weight: number | null;
  source_owned_composite: boolean;
  comparable_across_candidates: boolean;
  stale: boolean;
  limitations: string[];
}

export interface CandidateOverlapRecord {
  overlap_record_id: string;
  candidate_a_id: string;
  candidate_b_id: string;
  overlap_seconds: number;
  union_seconds: number;
  intersection_over_union: number;
  candidate_a_coverage: number;
  candidate_b_coverage: number;
  exact_duplicate_window: boolean;
  substantial_overlap: boolean;
  partial_overlap: boolean;
  contained: boolean;
  source_time_overlap_only: boolean;
  limitations: string[];
}

export interface CandidateSnapshot {
  candidate_snapshot_id: string;
  candidate_id: string;
  project_snapshot_digest: string;
  workflow_revision: number;
  candidate_digest: string;
  available_action_descriptor_ids: string[];
  confirmation_context_digest: string;
  snapshot_digest: string;
  discovery_status: string;
  rank_status: string;
  editorial_status: string;
  current: boolean;
  stale: boolean;
  selected: boolean;
  rejected: boolean;
  missing_evidence_count: number;
  conflict_count: number;
  limitations: string[];
}

export interface CandidateActionDescriptor {
  action_descriptor_id: string;
  display_name: string;
  action_class: string;
  owning_module_id: string;
  owning_operation_id: string;
  allowed_decision_values: string[];
  requires_reason: boolean;
  maximum_reason_length: number;
  authoritative: boolean;
  allowed_in_v1: boolean;
  availability: string;
  consequences: string[];
  does_not_do: string[];
  limitations: string[];
}

export interface CandidateActionReceipt {
  candidate_action_receipt_id: string;
  candidate_id: string;
  owning_module_id: string;
  owning_operation_id: string;
  accepted_by_owner: boolean;
  canonical_record_id: string | null;
  canonical_record_digest: string | null;
  canonical_status: string;
  authoritative_state_changed: boolean;
  stale_state_rejected: boolean;
  duplicate_request_reused: boolean;
  error_code: string | null;
  bounded_error_message: string;
  limitations: string[];
}

/** Format an exact source window without altering its boundaries. */
export function formatSourceWindow(startSeconds: number, endSeconds: number): string {
  return `${formatTimecode(startSeconds)} – ${formatTimecode(endSeconds)}`;
}

export function formatTimecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown";
  const whole = Math.floor(seconds);
  const millis = Math.round((seconds - whole) * 1000);
  const minutes = Math.floor(whole / 60);
  const secs = whole % 60;
  const base = `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return millis > 0 ? `${base}.${String(millis).padStart(3, "0")}` : base;
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "unknown";
  return `${seconds.toFixed(3).replace(/\.?0+$/, "")}s`;
}

/**
 * Describe a score with its owner and original scale. Never a probability
 * unless the owning module's definition says so.
 */
export function describeScore(card: CandidateScoreCard): string {
  const scale = `${card.score_scale_min}–${card.score_scale_max}`;
  const direction =
    card.score_direction === "lower_is_better"
      ? "lower is better"
      : card.score_direction === "higher_is_better"
        ? "higher is better"
        : "direction not stated by the source";
  return `${card.source_module_id} · ${card.score_name} ${card.score_value} of ${scale} (${direction})`;
}

/** Accessible label naming the owner, so rank is never presented as the panel's. */
export function describeRank(item: CandidateQueueItem): string {
  if (item.original_rank === null) {
    return "No source-owned rank is available for this candidate.";
  }
  const total = item.original_rank_total ? ` of ${item.original_rank_total}` : "";
  const owner = item.rank_owner_module_id || "the owning module";
  return `${owner} ranked this candidate ${item.original_rank}${total}.`;
}

export function candidateStateLabel(item: CandidateQueueItem): string {
  if (item.historical) return "Historical";
  if (item.superseded) return "Superseded";
  if (item.stale) return "Stale";
  if (!item.current) return "Unavailable";
  return "Current";
}

/** Text glyph paired with every state so status is never colour-only. */
export function candidateStateGlyph(item: CandidateQueueItem): string {
  if (item.historical) return "[historical]";
  if (item.superseded) return "[superseded]";
  if (item.stale) return "[stale]";
  if (!item.current) return "[n/a]";
  return "[current]";
}

export function editorialStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    selected: "Selected by Editorial Decision",
    not_selected: "Not selected by Editorial Decision",
    rejected: "Rejected by Editorial Decision",
    no_editorial_decision: "No editorial decision yet",
    unavailable: "Editorial Decision unavailable",
  };
  return labels[status] ?? status.replace(/_/g, " ");
}

export interface CandidateFilterState {
  filter: CandidateReviewFilter;
  search?: string;
}

/** Client-side narrowing only. The server owns the canonical filter. */
export function filterCandidates(
  items: CandidateQueueItem[],
  state: CandidateFilterState,
): CandidateQueueItem[] {
  const needle = (state.search ?? "").trim().toLowerCase();
  return items.filter((item) => {
    if (!needle) return true;
    return (
      item.candidate_id.toLowerCase().includes(needle) ||
      item.title.toLowerCase().includes(needle) ||
      item.bounded_summary.toLowerCase().includes(needle)
    );
  });
}

/**
 * Deterministic ordering using the server's total sort key. Frontend arrival
 * order is never used and no priority score is generated.
 */
export function sortCandidates(
  items: CandidateQueueItem[],
  sort: CandidateReviewSort,
): CandidateQueueItem[] {
  const rows = [...items];
  if (sort === "original_rank") {
    rows.sort(
      (a, b) =>
        Number(a.original_rank === null) - Number(b.original_rank === null) ||
        (a.original_rank ?? 0) - (b.original_rank ?? 0) ||
        a.candidate_id.localeCompare(b.candidate_id),
    );
    return rows;
  }
  if (sort === "candidate_id") {
    rows.sort((a, b) => a.candidate_id.localeCompare(b.candidate_id));
    return rows;
  }
  rows.sort(
    (a, b) =>
      a.priority_tier - b.priority_tier ||
      a.deterministic_sort_key.localeCompare(b.deterministic_sort_key) ||
      a.candidate_id.localeCompare(b.candidate_id),
  );
  return rows;
}

/** Toggle a comparison selection, refusing to exceed the fixed limit. */
export function toggleComparison(selected: string[], candidateId: string): string[] {
  if (selected.includes(candidateId)) {
    return selected.filter((item) => item !== candidateId);
  }
  if (selected.length >= MAX_COMPARISON_CANDIDATES) return selected;
  return [...selected, candidateId];
}

export function canCompare(selected: string[]): boolean {
  return selected.length >= 2 && selected.length <= MAX_COMPARISON_CANDIDATES;
}

/** Classify an overlap for display. Never a semantic duplication claim. */
export function overlapLabel(record: CandidateOverlapRecord): string {
  if (record.exact_duplicate_window) return "Exact duplicate window";
  if (record.substantial_overlap) return "Substantial time overlap";
  if (record.contained) return "Contained window";
  return "Partial time overlap";
}

export function overlapDescription(record: CandidateOverlapRecord): string {
  const iou = (record.intersection_over_union * 100).toFixed(1);
  return (
    `${record.overlap_seconds}s of shared source time (IoU ${iou}%). ` +
    "This is time-range overlap only, not a semantic duplicate."
  );
}

/**
 * Preview window for the exact candidate range, plus a bounded context hint
 * that never changes the candidate boundaries.
 */
export interface CandidatePreview {
  url: string | null;
  startSeconds: number;
  endSeconds: number;
  contextStartSeconds: number;
  contextEndSeconds: number;
  contextNotice: string;
  unavailableReason: string | null;
}

export function buildCandidatePreview(
  projectId: string,
  reference: Pick<CandidateReference, "start_seconds" | "end_seconds"> | null,
  contextSeconds = 0,
): CandidatePreview {
  const bounded = Math.max(0, Math.min(contextSeconds, MAX_TRANSCRIPT_CONTEXT_SECONDS));
  const url = protectedPreviewUrl(projectId);
  const start = reference?.start_seconds ?? 0;
  const end = reference?.end_seconds ?? 0;
  return {
    url,
    startSeconds: start,
    endSeconds: end,
    contextStartSeconds: Math.max(0, start - bounded),
    contextEndSeconds: end + bounded,
    contextNotice: "Preview context only. This does not change the candidate boundaries.",
    unavailableReason:
      url === null
        ? "Preview unavailable. No protected same-origin source exists for this project."
        : reference === null
          ? "Preview unavailable. No exact candidate window is bound."
          : null,
  };
}

/** An action is offered only when the snapshot and the server token both allow it. */
export function availableActions(
  descriptors: CandidateActionDescriptor[],
  snapshot: CandidateSnapshot | null,
  confirmations: Record<string, string>,
): CandidateActionDescriptor[] {
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
  descriptors: CandidateActionDescriptor[],
  snapshot: CandidateSnapshot | null,
  confirmations: Record<string, string>,
): CandidateActionDescriptor[] {
  const available = new Set(
    availableActions(descriptors, snapshot, confirmations).map(
      (item) => item.action_descriptor_id,
    ),
  );
  return descriptors.filter((item) => !available.has(item.action_descriptor_id));
}

/** A receipt proves authority changed only with an owner record and digest. */
export function receiptChangedAuthority(
  receipt: CandidateActionReceipt | null | undefined,
): boolean {
  if (!receipt) return false;
  return Boolean(
    receipt.authoritative_state_changed &&
      receipt.canonical_record_id &&
      receipt.canonical_record_digest,
  );
}

export function receiptSummary(receipt: CandidateActionReceipt | null | undefined): string {
  if (!receipt) return "No submission has been made.";
  if (receipt.stale_state_rejected) {
    return "Rejected: canonical state changed before submission. No authority changed.";
  }
  if (!receipt.accepted_by_owner) {
    return `Not accepted by ${receipt.owning_module_id}. No authority changed.`;
  }
  if (receiptChangedAuthority(receipt)) {
    return `${receipt.owning_module_id} recorded ${receipt.canonical_record_id}.`;
  }
  return (
    `${receipt.owning_module_id} recorded ${receipt.canonical_record_id ?? "a record"}. ` +
    "This is advisory: no authoritative candidate state changed."
  );
}

/** The local shortlist is UI metadata. This label must always accompany it. */
export const LOCAL_SHORTLIST_NOTICE =
  "Review-session shortlist — not an editorial decision.";

export function toggleLocalShortlist(shortlist: string[], candidateId: string): string[] {
  return shortlist.includes(candidateId)
    ? shortlist.filter((item) => item !== candidateId)
    : [...shortlist, candidateId];
}

/** Evidence completeness, reported without inventing a pass. */
export function evidenceSummary(item: CandidateQueueItem): string {
  if (item.missing_evidence_count === 0) return "All required source evidence is present.";
  const noun = item.missing_evidence_count === 1 ? "source" : "sources";
  return `${item.missing_evidence_count} required ${noun} missing. This is not a pass.`;
}
