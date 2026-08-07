"use client";

/**
 * BOBA Approval / Reject Buttons V1.
 *
 * A decision input, not an execution engine. The controls render only the
 * decisions the canonical owner registry says are genuinely offered, bind each
 * decision to an exact snapshot, revalidate before submitting, and report only
 * what the owner's receipt actually said.
 *
 * These buttons never approve anything themselves, grant Safety Gate approval,
 * grant Rights, bypass budgets, bypass validation, advance a workflow, execute a
 * repair or recovery, restore a checkpoint, modify code, artifacts or media, run
 * a command, run FFmpeg, upload or publish.
 *
 * No approval is ever shown optimistically.
 */

import { Component, type ReactNode, useMemo, useState } from "react";

import {
  NOT_EXECUTION_NOTICE,
  NOT_SAFETY_NOTICE,
  NOT_WORKFLOW_NOTICE,
  REJECTION_NOTICE,
  STALE_NOTICE,
  approveRow,
  buttonStateLabel,
  canSubmit,
  confirmationFacts,
  confirmationTitle,
  eligibilityNotices,
  humanise,
  ineligibilityNotice,
  isActionable,
  receiptButtonState,
  receiptClaimsNoSideEffects,
  receiptFacts,
  receiptSummary,
  rejectRow,
  revalidationNotice,
  validateReason,
  type ApprovalControlSnapshot,
  type ApprovalDecisionKind,
  type ApprovalDecisionReceipt,
  type ApprovalEligibility,
} from "@/lib/approvalControls";
import {
  useBobaApprovalEligibility,
  useCreateBobaApprovalControlSnapshot,
  useCreateBobaApprovalDecision,
  useRevalidateBobaApprovalControlSnapshot,
  useSubmitBobaApprovalDecision,
} from "@/lib/queries";
import { classifyReviewError } from "@/lib/reviewUi";

/** Contains unexpected render failures without leaking internals. */
export class BobaApprovalControlsErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div
          role="alert"
          className="rounded-lg border border-rose-300/30 bg-rose-300/[0.06] p-3 text-sm text-rose-100"
        >
          <p className="font-medium">The approval controls could not be displayed.</p>
          <p className="mt-1 text-xs text-rose-100/80">
            No decision was recorded. Reload the page to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

/** A state chip that never relies on colour alone. */
export function BobaApprovalStateChip({
  state,
}: {
  state: Parameters<typeof buttonStateLabel>[0];
}) {
  const { label, token } = buttonStateLabel(state);
  return (
    <span className="inline-flex items-center gap-1 rounded border border-white/20 px-1.5 py-0.5 text-[11px] text-white/75">
      <span aria-hidden="true">{token}</span>
      <span>{label}</span>
    </span>
  );
}

export function BobaApprovalConfirmationDialog({
  row,
  snapshot,
  reason,
  confirmed,
  submitting,
  errorMessage,
  onReasonChange,
  onConfirmChange,
  onSubmit,
  onCancel,
}: {
  row: ApprovalEligibility;
  snapshot: ApprovalControlSnapshot;
  reason: string;
  confirmed: boolean;
  submitting: boolean;
  errorMessage: string | null;
  onReasonChange: (value: string) => void;
  onConfirmChange: (value: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const reasonError = validateReason(row, reason);
  const ready = canSubmit(row, snapshot, reason, confirmed, submitting);
  const titleId = `approval-dialog-title-${row.eligibility_id}`;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="mt-3 rounded-lg border border-sky-300/30 bg-sky-300/[0.05] p-3 text-sm"
    >
      <h4 id={titleId} className="font-medium text-white">
        {confirmationTitle(row.decision_kind)}
      </h4>

      <dl className="mt-2 grid gap-x-3 gap-y-1 sm:grid-cols-2">
        {confirmationFacts(row, snapshot).map((fact) => (
          <div key={fact.label} className="text-xs">
            <dt className="inline text-white/45">{fact.label}: </dt>
            <dd className="inline text-white/80">{fact.value}</dd>
          </div>
        ))}
      </dl>

      {snapshot.warnings.length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs text-amber-100/85">
          {snapshot.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}

      <label className="mt-3 block text-xs text-white/70">
        {row.requires_reason ? "Reason (required)" : "Reason (optional)"}
        <textarea
          value={reason}
          onChange={(event) => onReasonChange(event.target.value)}
          rows={3}
          maxLength={500}
          aria-invalid={Boolean(reasonError)}
          className="mt-1 w-full rounded border border-white/15 bg-black/30 p-2 text-xs text-white"
        />
      </label>
      {reasonError ? (
        <p role="alert" className="mt-1 text-xs text-rose-200">
          {reasonError}
        </p>
      ) : null}

      <label className="mt-3 flex items-start gap-2 text-xs text-white/70">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => onConfirmChange(event.target.checked)}
        />
        I have read what this decision does and does not do.
      </label>

      <ul className="mt-2 space-y-1 text-xs text-white/50">
        <li>{NOT_EXECUTION_NOTICE}</li>
        <li>{NOT_SAFETY_NOTICE}</li>
        <li>{NOT_WORKFLOW_NOTICE}</li>
        {row.decision_kind === "reject" ? <li>{REJECTION_NOTICE}</li> : null}
      </ul>

      {errorMessage ? (
        <p role="alert" className="mt-2 text-xs text-rose-200">
          {errorMessage}
        </p>
      ) : null}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onSubmit}
          disabled={!ready}
          aria-disabled={!ready}
          className="rounded bg-sky-400/20 px-3 py-1.5 text-xs font-medium text-sky-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-300 disabled:opacity-40"
        >
          {submitting
            ? "Submitting to canonical owner…"
            : `Confirm ${humanise(row.decision_kind)}`}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-white/15 px-3 py-1.5 text-xs text-white/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/40"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export function BobaApprovalReceiptPanel({
  receipt,
}: {
  receipt: ApprovalDecisionReceipt;
}) {
  return (
    <div
      role="status"
      className="mt-3 rounded-lg border border-white/10 bg-black/20 p-3 text-xs"
    >
      <div className="flex items-center gap-2">
        <BobaApprovalStateChip state={receiptButtonState(receipt)} />
        <p className="text-white/80">{receiptSummary(receipt)}</p>
      </div>
      <dl className="mt-2 grid gap-x-3 gap-y-1 sm:grid-cols-2">
        {receiptFacts(receipt).map((fact) => (
          <div key={fact.label}>
            <dt className="inline text-white/45">{fact.label}: </dt>
            <dd className="inline text-white/75">{fact.value}</dd>
          </div>
        ))}
      </dl>
      {receiptClaimsNoSideEffects(receipt) ? (
        <p className="mt-2 text-white/45">
          Nothing was executed, advanced, restored, changed, uploaded or published.
        </p>
      ) : null}
    </div>
  );
}

export function BobaApprovalRejectControls({
  projectId,
  targetType = "workflow_stage",
  targetId = "",
  reviewSessionId,
  reviewSnapshotId,
}: {
  projectId: string;
  targetType?: string;
  targetId?: string;
  reviewSessionId?: string;
  reviewSnapshotId?: string;
}) {
  const [activeKind, setActiveKind] = useState<ApprovalDecisionKind | null>(null);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [snapshot, setSnapshot] = useState<ApprovalControlSnapshot | null>(null);
  const [receipt, setReceipt] = useState<ApprovalDecisionReceipt | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [inFlight, setInFlight] = useState(false);

  const eligibility = useBobaApprovalEligibility(projectId, targetType, targetId);
  const createSnapshot = useCreateBobaApprovalControlSnapshot(projectId);
  const revalidate = useRevalidateBobaApprovalControlSnapshot(projectId);
  const createDecision = useCreateBobaApprovalDecision(projectId);
  const submitDecision = useSubmitBobaApprovalDecision(projectId);

  const rows = useMemo<ApprovalEligibility[]>(
    () => eligibility.data?.eligibility ?? [],
    [eligibility.data],
  );
  const approve = useMemo(() => approveRow(rows), [rows]);
  const reject = useMemo(() => rejectRow(rows), [rows]);
  const activeRow = activeKind === "approve" ? approve : activeKind === "reject" ? reject : null;

  async function openDialog(kind: ApprovalDecisionKind) {
    setErrorMessage(null);
    setReceipt(null);
    setReason("");
    setConfirmed(false);
    setActiveKind(kind);
    if (!reviewSessionId || !reviewSnapshotId) {
      setErrorMessage(
        "A Review UI session and snapshot are required before a decision can be bound.",
      );
      return;
    }
    try {
      const payload = await createSnapshot.mutateAsync({
        review_session_id: reviewSessionId,
        review_snapshot_id: reviewSnapshotId,
        target_type: targetType,
        target_id: targetId,
      });
      setSnapshot(payload.snapshot);
    } catch (error) {
      setErrorMessage(classifyReviewError(error).guidance);
    }
  }

  async function submit() {
    if (!activeRow || !snapshot || inFlight) return;
    setInFlight(true);
    setErrorMessage(null);
    try {
      const check = await revalidate.mutateAsync(snapshot.approval_control_snapshot_id);
      const notice = revalidationNotice(check);
      if (notice) {
        setErrorMessage(notice);
        await eligibility.refetch();
        return;
      }
      const created = await createDecision.mutateAsync({
        approval_control_snapshot_id: snapshot.approval_control_snapshot_id,
        decision_kind: activeRow.decision_kind as "approve" | "reject",
        reason,
        idempotency_key: `approval_${snapshot.approval_control_snapshot_id}_${activeRow.decision_kind}`,
        confirmed: true,
      });
      if (created.created !== true) {
        setErrorMessage(String(created.message ?? STALE_NOTICE));
        await eligibility.refetch();
        return;
      }
      const submitted = await submitDecision.mutateAsync({
        requestId: String(created.review_action_request_id ?? ""),
        decisionKind: activeRow.decision_kind as "approve" | "reject",
      });
      setReceipt(submitted);
      setActiveKind(null);
    } catch (error) {
      setErrorMessage(classifyReviewError(error).guidance);
    } finally {
      setInFlight(false);
    }
  }

  if (eligibility.isError) {
    return (
      <section
        aria-label="BOBA approval controls"
        className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm text-white/70"
      >
        <p>Approval controls are unavailable. No decision was recorded.</p>
        <p className="mt-1 text-xs text-white/55">
          {classifyReviewError(eligibility.error).guidance}
        </p>
      </section>
    );
  }

  return (
    <BobaApprovalControlsErrorBoundary>
      <section
        aria-label="BOBA approval controls"
        className="rounded-lg border border-white/10 bg-white/[0.02] p-3"
      >
        <header className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold text-white">Human decision</h3>
          <p className="text-xs text-white/50">{NOT_EXECUTION_NOTICE}</p>
        </header>

        {eligibility.isLoading ? (
          <p role="status" className="mt-2 text-xs text-white/60">
            Reading canonical eligibility…
          </p>
        ) : null}

        <div className="mt-3 flex flex-wrap gap-2">
          {(["approve", "reject"] as const).map((kind) => {
            const row = kind === "approve" ? approve : reject;
            if (!row) return null;
            const actionable = isActionable(row);
            const { label, token } = buttonStateLabel(row.button_state);
            return (
              <button
                key={kind}
                type="button"
                onClick={() => void openDialog(kind)}
                disabled={!actionable || inFlight}
                aria-disabled={!actionable || inFlight}
                aria-label={`${label} — ${row.owning_module_id}`}
                className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40 ${
                  kind === "approve"
                    ? "bg-emerald-400/15 text-emerald-100 focus-visible:outline-emerald-300"
                    : "bg-rose-400/15 text-rose-100 focus-visible:outline-rose-300"
                }`}
              >
                <span aria-hidden="true">{token}</span>
                <span>{label}</span>
              </button>
            );
          })}
        </div>

        <ul className="mt-2 space-y-1">
          {rows.map((row) => {
            const notice = ineligibilityNotice(row);
            return notice ? (
              <li key={row.eligibility_id} className="text-xs text-white/55">
                {notice}
              </li>
            ) : null;
          })}
        </ul>

        {activeRow && snapshot ? (
          <BobaApprovalConfirmationDialog
            row={activeRow}
            snapshot={snapshot}
            reason={reason}
            confirmed={confirmed}
            submitting={inFlight}
            errorMessage={errorMessage}
            onReasonChange={setReason}
            onConfirmChange={setConfirmed}
            onSubmit={() => void submit()}
            onCancel={() => setActiveKind(null)}
          />
        ) : null}

        {!activeRow && errorMessage ? (
          <p role="alert" className="mt-2 text-xs text-rose-200">
            {errorMessage}
          </p>
        ) : null}

        {receipt ? <BobaApprovalReceiptPanel receipt={receipt} /> : null}

        <footer className="mt-3 space-y-1 border-t border-white/10 pt-2 text-xs text-white/45">
          <p>{NOT_SAFETY_NOTICE}</p>
          <p>{NOT_WORKFLOW_NOTICE}</p>
          {rows.some((row) => row.decision_kind === "reject") ? (
            <p>{REJECTION_NOTICE}</p>
          ) : null}
          <p>
            Eligibility comes from the canonical owner registry. A decision the
            owner disabled is never offered here.
          </p>
        </footer>
      </section>
    </BobaApprovalControlsErrorBoundary>
  );
}
