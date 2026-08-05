/**
 * Pure logic for the BOBA Review UI workspace.
 *
 * The Review UI is a presentation and canonical action-routing layer. Nothing in
 * this module creates or mutates authority: it only projects canonical owner
 * records for display, and it refuses to render references it cannot prove are
 * same-origin project-scoped media.
 */

import { API_V1 } from "@/lib/config";

export type ReviewQueueCategory =
  | "critical_attention"
  | "blocked"
  | "human_review_required"
  | "ready_for_review"
  | "awaiting_evidence"
  | "in_progress"
  | "completed"
  | "historical"
  | "informational"
  | "unavailable"
  | "unknown";

export interface ReviewQueueItem {
  queue_item_id: string;
  project_id: string;
  workflow_run_id?: string | null;
  stage_instance_id?: string | null;
  target_type: string;
  target_id: string;
  review_mode: string;
  priority: number;
  display_category: ReviewQueueCategory;
  title: string;
  bounded_summary: string;
  source_module_ids: string[];
  source_record_ids: string[];
  primary_reason: string;
  blocker_count: number;
  warning_count: number;
  missing_evidence_count: number;
  conflict_count: number;
  human_action_required: boolean;
  available_action_descriptor_ids: string[];
  current: boolean;
  stale: boolean;
  historical: boolean;
  queue_sort_key: string;
  updated_at: string;
  warnings: string[];
  limitations: string[];
}

export interface ReviewSourceCard {
  source_card_id: string;
  source_module_id: string;
  authority_domain: string;
  source_record_id: string;
  source_record_digest: string;
  original_status: string;
  original_decision?: string | null;
  title: string;
  bounded_summary: string;
  easy_explanation: string;
  current: boolean;
  stale: boolean;
  expired: boolean;
  invalidated: boolean;
  superseded: boolean;
  human_review_required: boolean;
  blocking: boolean;
  details_route: string;
  warnings: string[];
  limitations: string[];
}

export interface ReviewSnapshot {
  review_snapshot_id: string;
  review_target_id: string;
  project_snapshot_digest: string;
  workflow_revision: number;
  target_digest: string;
  available_action_descriptor_ids: string[];
  missing_evidence_count: number;
  conflict_count: number;
  human_action_required: boolean;
  current: boolean;
  stale: boolean;
  snapshot_digest: string;
  warnings: string[];
  limitations: string[];
}

export interface ReviewEvent {
  ui_event_id: string;
  source_module_id: string;
  source_event_id?: string | null;
  source_sequence?: number | null;
  created_at?: string | null;
  event_type: string;
  severity: string;
  technical_message: string;
  easy_message: string;
  confirmed_fact: string;
  assessment: string;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_percent?: number | null;
  requires_attention: boolean;
  canonical: boolean;
  replayed: boolean;
}

export interface ReviewActionReceipt {
  action_receipt_id: string;
  owning_module_id: string;
  owning_operation_id: string;
  canonical_record_id?: string | null;
  canonical_record_digest?: string | null;
  canonical_status: string;
  accepted_by_owner: boolean;
  authoritative_state_changed: boolean;
  canonical_refresh_required: boolean;
  stale_state_rejected: boolean;
  duplicate_request_reused: boolean;
  error_code?: string | null;
  bounded_error_message: string;
  limitations: string[];
}

/** The ten source-owned rows of the status matrix, in fixed display order. */
export const STATUS_MATRIX_ROWS = [
  { key: "rights", label: "Rights", module: "rights_permission_gate" },
  { key: "safety", label: "Safety", module: "safety_gate" },
  { key: "approval", label: "Target approval", module: "workflow_controller" },
  { key: "human", label: "Human decision", module: "workflow_controller" },
  { key: "workflow", label: "Workflow", module: "workflow_controller" },
  { key: "artifacts", label: "Artifacts", module: "artifact_inspector" },
  { key: "validation", label: "Technical validation", module: "validator_runner" },
  { key: "quality", label: "Output quality", module: "output_quality_reviewer" },
  { key: "recovery", label: "Recovery", module: "tool_recovery" },
  { key: "final_decision", label: "Final Decision Bus", module: "final_decision_bus" },
] as const;

export interface StatusMatrixRow {
  key: string;
  label: string;
  sourceModule: string;
  originalStatus: string;
  originalDecision: string;
  state: "current" | "stale" | "expired" | "superseded" | "unavailable";
  blocking: boolean;
  humanActionRequired: boolean;
  details: string;
  detailsRoute: string;
  warnings: string[];
  limitations: string[];
}

/**
 * Project one status row per authority domain. A missing owner record is
 * reported as `unavailable` and never as a pass.
 */
export function buildStatusMatrix(cards: ReviewSourceCard[]): StatusMatrixRow[] {
  return STATUS_MATRIX_ROWS.map((row) => {
    const card = cards.find((item) => item.source_module_id === row.module);
    if (!card) {
      return {
        key: row.key,
        label: row.label,
        sourceModule: row.module,
        originalStatus: "unavailable",
        originalDecision: "Not available",
        state: "unavailable" as const,
        blocking: false,
        humanActionRequired: false,
        details: "No canonical record is available. This is not a pass.",
        detailsRoute: "",
        warnings: [],
        limitations: ["An unavailable source record is never treated as a pass."],
      };
    }
    let state: StatusMatrixRow["state"] = "current";
    if (card.superseded) state = "superseded";
    else if (card.expired) state = "expired";
    else if (card.stale || !card.current) state = "stale";
    return {
      key: row.key,
      label: row.label,
      sourceModule: card.source_module_id,
      originalStatus: card.original_status,
      originalDecision: card.original_decision ?? "Not available",
      state,
      blocking: card.blocking,
      humanActionRequired: card.human_review_required,
      details: card.bounded_summary,
      detailsRoute: card.details_route,
      warnings: card.warnings,
      limitations: card.limitations,
    };
  });
}

/** A short, non-colour status label so state is never conveyed by colour alone. */
export function stateLabel(state: StatusMatrixRow["state"]): string {
  switch (state) {
    case "current":
      return "Current";
    case "stale":
      return "Stale";
    case "expired":
      return "Expired";
    case "superseded":
      return "Superseded";
    default:
      return "Unavailable";
  }
}

/** A text glyph paired with every status so icons are never the only signal. */
export function stateGlyph(state: StatusMatrixRow["state"]): string {
  switch (state) {
    case "current":
      return "[ok]";
    case "stale":
      return "[stale]";
    case "expired":
      return "[expired]";
    case "superseded":
      return "[superseded]";
    default:
      return "[n/a]";
  }
}

export function categoryLabel(category: ReviewQueueCategory): string {
  const labels: Record<ReviewQueueCategory, string> = {
    critical_attention: "Critical attention",
    blocked: "Blocked",
    human_review_required: "Human review required",
    ready_for_review: "Ready for review",
    awaiting_evidence: "Awaiting evidence",
    in_progress: "In progress",
    completed: "Completed",
    historical: "Historical",
    informational: "Informational",
    unavailable: "Unavailable",
    unknown: "Unknown",
  };
  return labels[category] ?? "Unknown";
}

export interface QueueFilter {
  category?: ReviewQueueCategory | "all";
  includeHistorical?: boolean;
  search?: string;
}

export function filterQueue(items: ReviewQueueItem[], filter: QueueFilter): ReviewQueueItem[] {
  const needle = (filter.search ?? "").trim().toLowerCase();
  return items.filter((item) => {
    if (!filter.includeHistorical && item.historical) return false;
    if (filter.category && filter.category !== "all" && item.display_category !== filter.category) {
      return false;
    }
    if (!needle) return true;
    return (
      item.title.toLowerCase().includes(needle) ||
      item.bounded_summary.toLowerCase().includes(needle) ||
      item.source_module_ids.join(" ").toLowerCase().includes(needle)
    );
  });
}

/** Deterministic ordering: priority tier, then the server's stable sort key. */
export function sortQueue(items: ReviewQueueItem[], sort: "priority" | "updated"): ReviewQueueItem[] {
  const copy = [...items];
  if (sort === "updated") {
    copy.sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
    return copy;
  }
  copy.sort(
    (a, b) =>
      a.priority - b.priority ||
      a.queue_sort_key.localeCompare(b.queue_sort_key) ||
      a.queue_item_id.localeCompare(b.queue_item_id),
  );
  return copy;
}

export const MAX_RETAINED_EVENTS = 200;

/**
 * Merge canonical events, suppressing duplicates by source identity so that a
 * reconnect or replay never double-counts work.
 */
export function mergeCanonicalEvents(
  existing: ReviewEvent[],
  incoming: ReviewEvent[],
  cap: number = MAX_RETAINED_EVENTS,
): ReviewEvent[] {
  const seen = new Set<string>();
  const keyOf = (event: ReviewEvent) =>
    `${event.source_module_id}::${event.source_event_id ?? event.ui_event_id}`;
  const merged: ReviewEvent[] = [];
  for (const event of [...existing, ...incoming]) {
    const key = keyOf(event);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(event);
  }
  merged.sort(
    (a, b) =>
      (a.created_at ?? "").localeCompare(b.created_at ?? "") ||
      (a.source_sequence ?? 0) - (b.source_sequence ?? 0) ||
      a.ui_event_id.localeCompare(b.ui_event_id),
  );
  return merged.slice(Math.max(0, merged.length - cap));
}

const CONTROL_EVENT_TYPES = new Set([
  "review_stream_open",
  "review_stream_idle",
  "review_stream_complete",
  "heartbeat",
  "keepalive",
  "ping",
]);

/**
 * Control and heartbeat frames are never work. Only canonical events with a
 * source identity may be presented as activity.
 */
export function isWorkEvent(event: Pick<ReviewEvent, "event_type" | "canonical">): boolean {
  if (!event.canonical) return false;
  return !CONTROL_EVENT_TYPES.has(event.event_type);
}

/** Real progress only. Absent or malformed counters yield null, never a guess. */
export function realProgress(event: ReviewEvent): number | null {
  const { progress_current: current, progress_total: total } = event;
  if (typeof current !== "number" || typeof total !== "number") return null;
  if (!Number.isFinite(current) || !Number.isFinite(total) || total <= 0) return null;
  return Math.max(0, Math.min(100, (current / total) * 100));
}

/** Bounded exponential backoff for event-stream reconnection. */
export function reconnectDelayMs(attempt: number, base = 1_000, ceiling = 30_000): number {
  const safeAttempt = Math.max(0, Math.min(attempt, 16));
  return Math.min(ceiling, base * 2 ** safeAttempt);
}

export type ReviewErrorKind =
  | "api_unavailable"
  | "target_removed"
  | "stale_snapshot"
  | "permission_denied"
  | "safety_block"
  | "action_unavailable"
  | "unsupported_schema"
  | "stream_disconnected"
  | "preview_unavailable"
  | "malformed_response"
  | "unexpected";

export interface ClassifiedReviewError {
  kind: ReviewErrorKind;
  title: string;
  guidance: string;
}

const ERROR_COPY: Record<ReviewErrorKind, { title: string; guidance: string }> = {
  api_unavailable: {
    title: "Olympus is unreachable",
    guidance: "The review workspace could not reach the backend. Nothing was submitted.",
  },
  target_removed: {
    title: "This review target is gone",
    guidance: "The canonical record no longer exists. Pick another item from the queue.",
  },
  stale_snapshot: {
    title: "The project moved on",
    guidance: "Canonical state changed while this review was open. Refresh before deciding.",
  },
  permission_denied: {
    title: "Not permitted",
    guidance: "This reviewer context cannot perform that action.",
  },
  safety_block: {
    title: "Blocked by the Safety Gate",
    guidance: "The Safety Gate owns this decision. The review workspace cannot bypass it.",
  },
  action_unavailable: {
    title: "Action unavailable",
    guidance: "This action is not offered for this exact target in V1.",
  },
  unsupported_schema: {
    title: "Unsupported record version",
    guidance: "This canonical record uses a schema this workspace does not understand.",
  },
  stream_disconnected: {
    title: "Live updates disconnected",
    guidance: "Shown records may be behind. Reconnecting; nothing was lost.",
  },
  preview_unavailable: {
    title: "Preview unavailable",
    guidance: "No protected same-origin preview exists for this item.",
  },
  malformed_response: {
    title: "Unreadable response",
    guidance: "The response did not match the expected shape. Nothing was applied.",
  },
  unexpected: {
    title: "Something went wrong",
    guidance: "The workspace hit an unexpected problem. No authority changed.",
  },
};

const STALE_CODES = new Set([
  "stale_project_snapshot",
  "workflow_revision_mismatch",
  "target_digest_mismatch",
  "source_record_digest_mismatch",
  "expired_snapshot",
]);

/**
 * Map a thrown error or a validation code onto safe, human copy. Server stack
 * traces, secrets, tokens, absolute paths and raw logs are never surfaced.
 */
export function classifyReviewError(error: unknown): ClassifiedReviewError {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? String((error as { code?: unknown }).code ?? "")
      : typeof error === "string"
        ? error
        : "";
  const status =
    typeof error === "object" && error !== null && "status" in error
      ? Number((error as { status?: unknown }).status ?? 0)
      : 0;

  const byCode: Record<string, ReviewErrorKind> = {
    network_error: "api_unavailable",
    target_removed: "target_removed",
    action_unavailable: "action_unavailable",
    malformed_canonical_response: "malformed_response",
    stream_disconnected: "stream_disconnected",
    preview_unavailable: "preview_unavailable",
    unsupported_schema: "unsupported_schema",
    blocked_safety_policy: "safety_block",
    permission_denied: "permission_denied",
  };

  // Explicit canonical codes always win over HTTP status heuristics.
  let kind: ReviewErrorKind | undefined;
  if (STALE_CODES.has(code)) kind = "stale_snapshot";
  else if (byCode[code]) kind = byCode[code];
  else if (code.startsWith("safety")) kind = "safety_block";

  if (!kind) {
    if (status === 404) kind = "target_removed";
    else if (status === 401 || status === 403) kind = "permission_denied";
    else if (status === 409) kind = "stale_snapshot";
    else if (status >= 500) kind = "api_unavailable";
    else kind = "unexpected";
  }

  return { kind, ...ERROR_COPY[kind] };
}

const UNSAFE_REFERENCE = /^(?:[a-zA-Z]:[\\/]|\\\\|file:|https?:|\/\/)|\.\./;

/**
 * A preview reference must be a plain project-scoped identifier. Absolute
 * paths, UNC paths, file URIs, traversal and any external URL are refused.
 */
export function isSafePreviewReference(reference: string): boolean {
  if (!reference) return false;
  if (UNSAFE_REFERENCE.test(reference)) return false;
  return /^[A-Za-z0-9_.:-]{1,180}$/.test(reference);
}

/**
 * Build a same-origin, project-scoped preview URL using only the existing
 * backend media routes. Returns null when the reference is not provably safe.
 */
export function protectedPreviewUrl(projectId: string, clipId?: string | null): string | null {
  if (!isSafePreviewReference(projectId)) return null;
  if (!clipId) return `${API_V1}/projects/${projectId}/source`;
  if (!isSafePreviewReference(clipId)) return null;
  return `${API_V1}/projects/${projectId}/rendering/clips/${clipId}/download`;
}

/** A receipt only proves authority changed when the owner returned a record. */
export function receiptChangedAuthority(receipt: ReviewActionReceipt | null | undefined): boolean {
  if (!receipt) return false;
  return Boolean(
    receipt.authoritative_state_changed &&
      receipt.canonical_record_id &&
      receipt.canonical_record_digest,
  );
}

/** Human-readable outcome for a submission, without implying success. */
export function receiptSummary(receipt: ReviewActionReceipt | null | undefined): string {
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
  return `${receipt.owning_module_id} accepted the request. No authoritative state changed.`;
}
