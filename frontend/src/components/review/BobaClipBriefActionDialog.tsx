"use client";

/**
 * Clip brief action bar and confirmation dialog.
 *
 * Only actions the server offered for this exact snapshot, with a server-issued
 * confirmation token, can be submitted. Every unavailable action is listed with
 * the reason it is unavailable and no substitute authority is offered. Nothing
 * here approves, rejects, revises or regenerates a brief.
 */

import { useState } from "react";

import {
  NO_AUTHORITATIVE_ACTION_NOTICE,
  availableActions,
  canSubmitAction,
  receiptChangedAuthority,
  receiptSummary,
  unavailableActionNotice,
  validateActionReason,
  withheldActions,
  type ClipBriefActionDescriptor,
  type ClipBriefActionReceipt,
  type ClipBriefSnapshot,
} from "@/lib/clipBriefReview";

export function BobaClipBriefActionBar({
  descriptors,
  snapshot,
  confirmations,
  receipt,
  message,
  onSelect,
}: {
  descriptors: ClipBriefActionDescriptor[];
  snapshot: ClipBriefSnapshot | null;
  confirmations: Record<string, string>;
  receipt: ClipBriefActionReceipt | null;
  message: string | null;
  onSelect: (descriptor: ClipBriefActionDescriptor) => void;
}) {
  const offered = availableActions(descriptors, snapshot, confirmations);
  const withheld = withheldActions(descriptors, snapshot, confirmations);

  return (
    <div className="space-y-2">
      <p className="text-[11px] text-white/45">{NO_AUTHORITATIVE_ACTION_NOTICE}</p>

      {offered.length === 0 ? (
        <p className="text-sm text-white/60">
          No review action is available for this exact clip brief right now.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {offered.map((descriptor) => (
            <button
              key={descriptor.action_descriptor_id}
              type="button"
              onClick={() => onSelect(descriptor)}
              className="rounded border border-sky-300/30 bg-sky-300/[0.08] px-3 py-1.5 text-xs text-sky-100"
            >
              {descriptor.display_name}
            </button>
          ))}
        </div>
      )}

      {withheld.length > 0 ? (
        <details className="rounded border border-white/10 bg-white/[0.02] p-3">
          <summary className="cursor-pointer text-xs text-white/60">
            {withheld.length} action(s) not available here
          </summary>
          <ul className="mt-2 space-y-2 text-[11px] text-white/50">
            {withheld.map((descriptor) => (
              <li key={descriptor.action_descriptor_id}>
                <span className="text-white/70">{descriptor.display_name}</span>
                <p className="mt-0.5">{unavailableActionNotice(descriptor)}</p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {message ? <p className="text-xs text-amber-200/90">{message}</p> : null}
      {receipt ? (
        <div
          className="rounded border border-white/10 bg-white/[0.02] p-3 text-xs text-white/70"
          data-authority-changed={receiptChangedAuthority(receipt)}
        >
          <p>{receiptSummary(receipt)}</p>
          {receipt.limitations.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-white/40">
              {receipt.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function BobaClipBriefActionDialog({
  descriptor,
  snapshot,
  confirmations,
  submitting,
  onCancel,
  onConfirm,
}: {
  descriptor: ClipBriefActionDescriptor | null;
  snapshot: ClipBriefSnapshot | null;
  confirmations: Record<string, string>;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: (decisionValue: string | null, reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  if (!descriptor) return null;

  const chosen =
    decision ?? (descriptor.allowed_decision_values[0] as string | undefined) ?? null;
  const reasonError = validateActionReason(reason, descriptor);
  const ready = canSubmitAction(
    descriptor,
    snapshot,
    confirmations,
    reason,
    chosen,
    confirmed,
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Confirm ${descriptor.display_name}`}
      className="rounded-lg border border-white/15 bg-[#0b1220] p-4 text-sm"
    >
      <p className="font-medium text-white">{descriptor.display_name}</p>
      <p className="mt-1 text-xs text-white/60">
        Owner: {descriptor.owning_module_id} · operation{" "}
        {descriptor.owning_operation_id}
      </p>

      {descriptor.consequences.length > 0 ? (
        <ul className="mt-2 space-y-0.5 text-xs text-white/70">
          {descriptor.consequences.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {descriptor.does_not_do.length > 0 ? (
        <ul className="mt-2 space-y-0.5 text-xs text-white/45">
          {descriptor.does_not_do.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}

      {descriptor.allowed_decision_values.length > 1 ? (
        <label className="mt-3 block text-xs text-white/60">
          Decision
          <select
            value={chosen ?? ""}
            onChange={(event) => setDecision(event.target.value)}
            className="mt-1 w-full rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-white"
          >
            {descriptor.allowed_decision_values.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <label className="mt-3 block text-xs text-white/60">
        Reason
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={descriptor.maximum_reason_length}
          rows={3}
          className="mt-1 w-full rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-white"
        />
      </label>
      {reasonError ? (
        <p className="mt-1 text-xs text-amber-200/90">{reasonError}</p>
      ) : null}

      <label className="mt-3 flex items-start gap-2 text-xs text-white/60">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I have reviewed this exact clip brief and its canonical sources.
      </label>

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-white/10 px-3 py-1.5 text-xs text-white/70"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={!ready || submitting}
          onClick={() => onConfirm(chosen, reason)}
          className="rounded border border-sky-300/30 bg-sky-300/[0.12] px-3 py-1.5 text-xs text-sky-100 disabled:opacity-40"
        >
          {submitting ? "Submitting…" : "Send to the owning module"}
        </button>
      </div>
    </div>
  );
}
