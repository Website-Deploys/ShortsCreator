/**
 * Pure logic for the BOBA Approval / Reject Buttons.
 *
 * This is an interaction layer, never an authority. It renders the approve and
 * reject controls that the canonical owner registry says are genuinely offered,
 * and refuses to render one that the owner disabled.
 *
 * Nothing here approves anything itself, grants Safety Gate approval, grants
 * Rights, advances a workflow, executes a repair or recovery, restores a
 * checkpoint, modifies code, artifacts or media, runs a command, uploads or
 * publishes. An approval is never shown optimistically: the button only shows
 * "Approved" after the canonical owner has confirmed it.
 */

export const MAX_REASON_LENGTH = 500;
export const MAX_EVENTS = 100;

export const NOT_EXECUTION_NOTICE =
  "This records a human decision only. It does not execute anything.";
export const NOT_SAFETY_NOTICE =
  "This does not grant Safety Gate approval; Safety Gate remains authoritative.";
export const NOT_WORKFLOW_NOTICE =
  "This does not advance the workflow; the Workflow Controller owns transitions.";
export const STALE_NOTICE =
  "The reviewed state changed after this control was displayed. Refresh and read the current state before deciding again.";
export const REJECTION_NOTICE =
  "A rejection is an explicit recorded human decision. It deletes nothing, rolls nothing back and changes no artifact.";

export type ApprovalButtonState =
  | "approve_available"
  | "reject_available"
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "invalidated"
  | "blocked"
  | "requires_review"
  | "unavailable";

export type ApprovalDecisionKind = "approve" | "reject" | "request_revision";

export type ApprovalIneligibilityReason =
  | "no_canonical_operation"
  | "action_not_available_in_v1"
  | "target_type_not_supported"
  | "no_workflow_run_bound"
  | "advisory_only_not_authoritative"
  | "already_decided"
  | "expired"
  | "safety_gate_blocked"
  | "rights_unknown_or_blocked"
  | "evidence_missing"
  | "owner_unavailable"
  | "eligible";

export interface ApprovalEligibility {
  eligibility_id: string;
  project_id: string;
  target_type: string;
  target_id: string;
  action_descriptor_id: string;
  owning_module_id: string;
  owning_operation_id: string;
  decision_kind: ApprovalDecisionKind;
  button_state: ApprovalButtonState;
  eligible: boolean;
  reason_code: ApprovalIneligibilityReason;
  bounded_explanation: string;
  requires_reason: boolean;
  requires_confirmation: boolean;
  requires_workflow_revision: boolean;
  requires_target_digest: boolean;
  authoritative_for_owner: boolean;
  grants_execution: false;
  grants_safety_approval: false;
  grants_rights_approval: false;
  advances_workflow: false;
  warnings: string[];
  limitations: string[];
}

export interface ApprovalControlSnapshot {
  approval_control_snapshot_id: string;
  review_session_id: string;
  review_snapshot_id: string;
  project_id: string;
  workflow_run_id: string | null;
  stage_instance_id: string | null;
  target_type: string;
  target_id: string;
  project_snapshot_digest: string;
  workflow_revision: number;
  target_digest: string;
  safety_record_digest: string;
  final_decision_record_digest: string;
  eligible_decision_kinds: string[];
  safety_status: string;
  rights_status: string;
  validation_status: string;
  quality_status: string;
  checkpoint_status: string;
  budget_status: string;
  workflow_status: string;
  expires_at: string | null;
  already_decided: boolean;
  snapshot_digest: string;
  confirmation_context_digest: string;
  warnings: string[];
  limitations: string[];
}

export interface ApprovalDecisionReceipt {
  approval_decision_receipt_id: string;
  review_action_request_id: string;
  project_id: string;
  target_type: string;
  target_id: string;
  decision_kind: ApprovalDecisionKind;
  owning_module_id: string;
  owning_operation_id: string;
  user_decision_recorded: boolean;
  user_decision_value: string;
  bounded_reason: string;
  owner_accepted: boolean;
  canonical_record_id: string | null;
  canonical_status: string;
  safety_decision_present: boolean;
  safety_decision_granted_here: false;
  execution_reported_by_owner: boolean;
  execution_owner_module_id: string | null;
  workflow_advanced: boolean;
  checkpoint_restored: false;
  code_changed: false;
  artifact_changed: false;
  media_modified: false;
  upload_performed: false;
  publication_performed: false;
  stale_state_rejected: boolean;
  duplicate_request_reused: boolean;
  already_decided: boolean;
  error_code: string | null;
  bounded_error_message: string;
  warnings: string[];
  limitations: string[];
}

export interface ApprovalRevalidation {
  valid: boolean;
  code: string;
  message: string;
  stale: boolean;
}

/* ------------------------------------------------------------------ */
/* Presentation                                                        */
/* ------------------------------------------------------------------ */

export function humanise(value: string): string {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** A label plus a non-colour token, so state is never colour-only. */
export function buttonStateLabel(state: ApprovalButtonState): {
  label: string;
  token: string;
} {
  switch (state) {
    case "approve_available":
      return { label: "Approve", token: "✓" };
    case "reject_available":
      return { label: "Reject", token: "✕" };
    case "pending":
      return { label: "Pending", token: "…" };
    case "approved":
      return { label: "Approved", token: "✓" };
    case "rejected":
      return { label: "Rejected", token: "✕" };
    case "expired":
      return { label: "Expired", token: "⏱" };
    case "invalidated":
      return { label: "Invalidated", token: "⟲" };
    case "blocked":
      return { label: "Blocked", token: "⛔" };
    case "requires_review":
      return { label: "Requires Review", token: "!" };
    default:
      return { label: "Unavailable", token: "–" };
  }
}

export function isActionable(row: ApprovalEligibility): boolean {
  return (
    row.eligible &&
    (row.button_state === "approve_available" || row.button_state === "reject_available")
  );
}

export function approveRow(rows: ApprovalEligibility[]): ApprovalEligibility | null {
  return rows.find((row) => row.decision_kind === "approve") ?? null;
}

export function rejectRow(rows: ApprovalEligibility[]): ApprovalEligibility | null {
  return rows.find((row) => row.decision_kind === "reject") ?? null;
}

/** The reason a control is not offered, always attributed to its owner. */
export function ineligibilityNotice(row: ApprovalEligibility): string | null {
  if (row.eligible) return null;
  return `${humanise(row.decision_kind)} unavailable — ${row.bounded_explanation}`;
}

export function eligibilityNotices(row: ApprovalEligibility): string[] {
  const rows = [...row.warnings, NOT_EXECUTION_NOTICE, NOT_SAFETY_NOTICE, NOT_WORKFLOW_NOTICE];
  if (row.decision_kind === "reject") rows.push(REJECTION_NOTICE);
  return rows;
}

/* ------------------------------------------------------------------ */
/* Confirmation content                                                */
/* ------------------------------------------------------------------ */

export interface ConfirmationFact {
  label: string;
  value: string;
}

/** Exactly what is being decided, drawn only from the bound snapshot. */
export function confirmationFacts(
  row: ApprovalEligibility,
  snapshot: ApprovalControlSnapshot,
): ConfirmationFact[] {
  return [
    { label: "Action", value: humanise(row.decision_kind) },
    { label: "Owning module", value: humanise(row.owning_module_id) },
    { label: "Owning operation", value: row.owning_operation_id },
    { label: "Target type", value: humanise(snapshot.target_type) },
    { label: "Target", value: snapshot.target_id || "not recorded by the owner" },
    { label: "Workflow run", value: snapshot.workflow_run_id ?? "not bound" },
    { label: "Workflow revision", value: String(snapshot.workflow_revision) },
    { label: "Workflow status", value: humanise(snapshot.workflow_status) },
    { label: "Safety state", value: humanise(snapshot.safety_status) },
    { label: "Rights state", value: humanise(snapshot.rights_status) },
    { label: "Validation state", value: humanise(snapshot.validation_status) },
    { label: "Quality state", value: humanise(snapshot.quality_status) },
    { label: "Checkpoint state", value: humanise(snapshot.checkpoint_status) },
    { label: "Budget state", value: humanise(snapshot.budget_status) },
    { label: "Expires", value: snapshot.expires_at ?? "no expiry recorded" },
    { label: "Target digest", value: `${snapshot.target_digest.slice(0, 16)}…` },
  ];
}

export function confirmationTitle(kind: ApprovalDecisionKind): string {
  return kind === "approve" ? "Approve this action?" : "Reject this action?";
}

/* ------------------------------------------------------------------ */
/* Reason validation (mirrors the backend refusals)                    */
/* ------------------------------------------------------------------ */

const SENSITIVE_KEY = /(secret|token|password|credential|cookie|authorization)/i;
const SHELL_TOKEN = /(?:\|\||&&|[|><;`]|\$\(|\r|\n)/;
const COMMAND_EXECUTABLE =
  /(?:^|[\s"'])(?:ffmpeg|ffprobe|git|python3?|pip3?|npm|npx|yarn|pnpm|node|bash|sh|zsh|powershell|pwsh|cmd|docker|apt|apt-get|brew|curl|wget|make|systemctl|kill|pkill|rm|mv|cp|chmod|chown|sudo|ssh|scp|rsync)\b/i;
const URL_PATTERN = /\b(?:https?|ftp|file):\/\//i;
const PRIVATE_PATH = /(?:[A-Za-z]:[\\/]|file:|\/home\/|\/Users\/|\\\\)/i;
const TRAVERSAL = /\.\.\/|\.\.\\/;

/** Returns an error message, or null when the reason is acceptable. */
export function validateReason(
  row: ApprovalEligibility,
  reason: string,
): string | null {
  const trimmed = reason.trim();
  if (row.requires_reason && !trimmed) return "This decision requires a reason.";
  if (trimmed.length > MAX_REASON_LENGTH) {
    return `A reason may be at most ${MAX_REASON_LENGTH} characters.`;
  }
  if (!trimmed) return null;
  if (SENSITIVE_KEY.test(trimmed)) return "A reason cannot contain a credential.";
  if (SHELL_TOKEN.test(trimmed) || COMMAND_EXECUTABLE.test(trimmed)) {
    return "A reason cannot contain command text.";
  }
  if (URL_PATTERN.test(trimmed)) return "A reason cannot contain a URL.";
  if (PRIVATE_PATH.test(trimmed)) return "A reason cannot contain a private path.";
  if (TRAVERSAL.test(trimmed)) return "A reason cannot contain a path traversal.";
  return null;
}

export function canSubmit(
  row: ApprovalEligibility | null,
  snapshot: ApprovalControlSnapshot | null,
  reason: string,
  confirmed: boolean,
  inFlight: boolean,
): boolean {
  if (!row || !snapshot) return false;
  if (inFlight) return false;
  if (!isActionable(row)) return false;
  if (snapshot.already_decided) return false;
  if (row.requires_confirmation && !confirmed) return false;
  return validateReason(row, reason) === null;
}

/* ------------------------------------------------------------------ */
/* Receipt truthfulness                                                */
/* ------------------------------------------------------------------ */

/** The state to show *after* the owner replied. Never optimistic. */
export function receiptButtonState(
  receipt: ApprovalDecisionReceipt,
): ApprovalButtonState {
  if (receipt.stale_state_rejected) return "invalidated";
  if (!receipt.owner_accepted) return "blocked";
  return receipt.decision_kind === "approve" ? "approved" : "rejected";
}

export function receiptSummary(receipt: ApprovalDecisionReceipt): string {
  if (receipt.stale_state_rejected) return STALE_NOTICE;
  if (receipt.duplicate_request_reused) {
    return "This decision was already submitted. The existing canonical decision is shown.";
  }
  if (!receipt.owner_accepted) {
    return `${humanise(receipt.owning_module_id)} did not accept the decision: ${humanise(receipt.canonical_status)}.`;
  }
  if (receipt.decision_kind === "approve") {
    return `${humanise(receipt.owning_module_id)} recorded a human approval. Nothing was executed and no workflow advanced.`;
  }
  return `${humanise(receipt.owning_module_id)} recorded a human rejection. Nothing was deleted or rolled back.`;
}

/** Keeps the four facts apart that are easy to conflate. */
export function receiptFacts(receipt: ApprovalDecisionReceipt): ConfirmationFact[] {
  return [
    {
      label: "User decision",
      value: receipt.user_decision_recorded
        ? humanise(receipt.user_decision_value)
        : "not recorded",
    },
    {
      label: "Owner decision",
      value: receipt.owner_accepted
        ? `accepted by ${humanise(receipt.owning_module_id)}`
        : humanise(receipt.canonical_status),
    },
    {
      label: "Safety decision",
      value: receipt.safety_decision_present
        ? "separately owned by Safety Gate"
        : "none recorded",
    },
    {
      label: "Execution",
      value: receipt.execution_reported_by_owner
        ? `reported by ${humanise(receipt.execution_owner_module_id ?? "")}`
        : "not executed",
    },
  ];
}

/** True when the receipt claims nothing beyond a recorded decision. */
export function receiptClaimsNoSideEffects(receipt: ApprovalDecisionReceipt): boolean {
  return (
    !receipt.execution_reported_by_owner &&
    !receipt.workflow_advanced &&
    !receipt.checkpoint_restored &&
    !receipt.code_changed &&
    !receipt.artifact_changed &&
    !receipt.media_modified &&
    !receipt.upload_performed &&
    !receipt.publication_performed &&
    !receipt.safety_decision_granted_here
  );
}

export function revalidationNotice(result: ApprovalRevalidation): string | null {
  if (result.valid) return null;
  return result.stale ? `${result.message} ${STALE_NOTICE}` : result.message;
}
