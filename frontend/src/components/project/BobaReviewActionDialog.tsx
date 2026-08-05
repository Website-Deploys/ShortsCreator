"use client";

/**
 * Action bar and confirmation dialog.
 *
 * An action is offered only when the canonical snapshot lists it. Submitting
 * refreshes canonical state, validates digests and revision, requires explicit
 * confirmation, and then routes to the owning module. Authority is displayed as
 * changed only when the owner returns a canonical record and digest.
 */

import { useEffect, useRef, useState } from "react";

import {
  receiptChangedAuthority,
  receiptSummary,
  type ReviewActionReceipt,
  type ReviewSnapshot,
} from "@/lib/reviewUi";

export interface ReviewActionDescriptor {
  action_descriptor_id: string;
  display_name: string;
  action_class: string;
  owning_module_id: string;
  owning_operation_id: string;
  allowed_decision_values: string[];
  requires_reason: boolean;
  maximum_reason_length: number;
  availability: string;
  allowed_in_v1: boolean;
  limitations: string[];
}

export function BobaReviewActionBar({
  descriptors,
  snapshot,
  confirmableActionIds,
  onRequest,
  busy,
}: {
  descriptors: ReviewActionDescriptor[];
  snapshot: ReviewSnapshot | null;
  /** Actions for which the server issued a confirmation token. */
  confirmableActionIds: string[];
  onRequest: (descriptor: ReviewActionDescriptor) => void;
  busy: boolean;
}) {
  const snapshotOffered = snapshot?.available_action_descriptor_ids ?? [];
  const offered = snapshotOffered.filter((id) => confirmableActionIds.includes(id));
  const available = descriptors.filter((item) => offered.includes(item.action_descriptor_id));
  const withheld = descriptors.filter((item) => !offered.includes(item.action_descriptor_id));

  return (
    <section
      aria-labelledby="review-actions-heading"
      className="sticky bottom-0 space-y-2 border-t border-white/10 bg-[#0b0e14]/95 p-3 backdrop-blur"
    >
      <h3 id="review-actions-heading" className="text-sm font-semibold text-white/90">
        HUMAN ACTIONS
      </h3>
      {snapshot === null && (
        <p className="text-xs text-white/55">
          Select a review target to see the actions its owning modules accept.
        </p>
      )}
      {snapshot !== null && available.length === 0 && (
        <p className="text-xs text-white/55">
          No human action is available for this exact target right now.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {available.map((descriptor) => (
          <button
            key={descriptor.action_descriptor_id}
            type="button"
            disabled={busy}
            onClick={() => onRequest(descriptor)}
            className="min-h-[44px] rounded-md border border-sky-300/40 bg-sky-300/[0.08] px-3 text-sm text-sky-100 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            {descriptor.display_name}
          </button>
        ))}
      </div>
      {withheld.length > 0 && (
        <details className="text-xs text-white/55">
          <summary className="min-h-[44px] cursor-pointer py-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 sm:min-h-0">
            Why other actions are unavailable ({withheld.length})
          </summary>
          <ul className="mt-1 space-y-1">
            {withheld.map((descriptor) => (
              <li key={descriptor.action_descriptor_id}>
                <span className="text-white/75">{descriptor.display_name}</span> — owned by{" "}
                <span className="font-mono text-[11px]">{descriptor.owning_module_id}</span>.{" "}
                {descriptor.limitations[0] ?? "Unavailable for this exact target."}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-[11px] text-white/45">
        This workspace cannot upload, publish, run validators, execute repairs, restore checkpoints,
        or bypass Rights or Safety.
      </p>
    </section>
  );
}

export function BobaReviewActionDialog({
  descriptor,
  snapshot,
  receipt,
  validationMessage,
  busy,
  onCancel,
  onConfirm,
}: {
  descriptor: ReviewActionDescriptor | null;
  snapshot: ReviewSnapshot | null;
  receipt: ReviewActionReceipt | null;
  validationMessage: string | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (decisionValue: string | null, reason: string) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLSelectElement | HTMLTextAreaElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const [decisionValue, setDecisionValue] = useState<string>("");
  const [reason, setReason] = useState<string>("");
  const [acknowledged, setAcknowledged] = useState(false);

  const open = descriptor !== null;

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    setDecisionValue(descriptor?.allowed_decision_values[0] ?? "");
    setReason("");
    setAcknowledged(false);
    const timer = window.setTimeout(() => firstFieldRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [open, descriptor]);

  useEffect(() => {
    if (open) return;
    returnFocusRef.current?.focus();
  }, [open]);

  if (!open || descriptor === null) return null;

  const reasonMissing = descriptor.requires_reason && reason.trim().length === 0;
  const decisionMissing = descriptor.allowed_decision_values.length > 0 && !decisionValue;
  const blocked = reasonMissing || decisionMissing || !acknowledged || busy;

  const trapFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), select, textarea, input, [href], [tabindex]:not([tabindex="-1"])',
    );
    if (!focusable || focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-2 sm:items-center">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-action-dialog-title"
        aria-describedby="review-action-dialog-description"
        onKeyDown={trapFocus}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-white/10 bg-[#0b0e14] p-4"
      >
        <h2 id="review-action-dialog-title" className="text-base font-semibold text-white/95">
          Confirm: {descriptor.display_name}
        </h2>
        <p id="review-action-dialog-description" className="mt-1 text-xs text-white/65">
          This request is routed to{" "}
          <span className="font-mono text-white/80">{descriptor.owning_module_id}</span> using the
          fixed operation{" "}
          <span className="font-mono text-white/80">{descriptor.owning_operation_id}</span>. That
          module owns the outcome. This workspace records nothing on its own.
        </p>

        <dl className="mt-3 grid grid-cols-1 gap-1 text-[11px] sm:grid-cols-2">
          <div>
            <dt className="text-white/50">Workflow revision</dt>
            <dd className="font-mono text-white/75">{snapshot?.workflow_revision ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-white/50">Target digest</dt>
            <dd className="truncate font-mono text-white/75">
              {snapshot ? `${snapshot.target_digest.slice(0, 12)}…` : "—"}
            </dd>
          </div>
        </dl>

        {descriptor.allowed_decision_values.length > 0 && (
          <div className="mt-3">
            <label htmlFor="review-action-decision" className="block text-xs text-white/70">
              Decision (required)
            </label>
            <select
              id="review-action-decision"
              ref={(node) => {
                firstFieldRef.current = node;
              }}
              value={decisionValue}
              onChange={(event) => setDecisionValue(event.target.value)}
              className="mt-1 min-h-[44px] w-full rounded-md border border-white/10 bg-black/30 px-2 text-sm text-white/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
            >
              {descriptor.allowed_decision_values.map((value) => (
                <option key={value} value={value}>
                  {value.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="mt-3">
          <label htmlFor="review-action-reason" className="block text-xs text-white/70">
            Reason {descriptor.requires_reason ? "(required)" : "(optional)"}
          </label>
          <textarea
            id="review-action-reason"
            ref={(node) => {
              if (descriptor.allowed_decision_values.length === 0) firstFieldRef.current = node;
            }}
            value={reason}
            maxLength={descriptor.maximum_reason_length}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            aria-describedby="review-action-reason-help"
            className="mt-1 w-full rounded-md border border-white/10 bg-black/30 p-2 text-sm text-white/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          />
          <p id="review-action-reason-help" className="mt-1 text-[11px] text-white/45">
            Do not paste credentials, tokens or local file paths.
          </p>
        </div>

        <label className="mt-3 flex min-h-[44px] items-start gap-2 text-xs text-white/75">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
            className="mt-0.5 h-4 w-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          />
          I confirm this exact decision for this exact target.
        </label>

        {descriptor.limitations.length > 0 && (
          <ul className="mt-3 space-y-1 text-[11px] text-white/55">
            {descriptor.limitations.map((limitation) => (
              <li key={limitation}>Limitation: {limitation}</li>
            ))}
          </ul>
        )}

        {validationMessage && (
          <p role="alert" className="mt-3 rounded-md border border-amber-300/30 bg-amber-300/[0.06] p-2 text-xs text-amber-100">
            {validationMessage}
          </p>
        )}

        {receipt && (
          <div
            role="status"
            aria-live="polite"
            className="mt-3 rounded-md border border-white/10 bg-white/[0.02] p-2 text-xs text-white/75"
          >
            <p>{receiptSummary(receipt)}</p>
            <p className="mt-1 text-[11px] text-white/50">
              Authoritative state changed:{" "}
              {receiptChangedAuthority(receipt) ? "Yes, confirmed by the owner." : "No."}
            </p>
            {receipt.duplicate_request_reused && (
              <p className="mt-1 text-[11px] text-white/50">
                An existing receipt was reused; the request was not repeated.
              </p>
            )}
          </div>
        )}

        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="min-h-[44px] rounded-md border border-white/15 px-3 text-sm text-white/80 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={blocked}
            onClick={() => onConfirm(decisionValue || null, reason)}
            className="min-h-[44px] rounded-md border border-sky-300/40 bg-sky-300/[0.12] px-3 text-sm text-sky-100 disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            {busy ? "Submitting to owner…" : "Confirm and route to owner"}
          </button>
        </div>
      </div>
    </div>
  );
}
