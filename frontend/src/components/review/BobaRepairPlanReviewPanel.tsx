"use client";

/**
 * BOBA Repair Plan Panel V1.
 *
 * A specialized read-only mode of the BOBA Review UI and the BOBA Error Doctor
 * Panel, rendered beside them rather than replacing any of them. It is a
 * trusted repair-plan projection, an evidence workspace, a plan-comparison
 * surface, an approval-requirement viewer, a recovery-history viewer and a safe
 * canonical action router.
 *
 * It never generates a repair plan, revises one, approves or rejects one,
 * executes a plan or a step, runs a command, shell, PowerShell, Git or FFmpeg,
 * installs or downloads a tool, restarts a process, restores a checkpoint,
 * transitions a workflow, modifies code, artifacts or media, uploads or
 * publishes.
 *
 * Repair Planner proposed every plan shown here. Command text and private
 * absolute paths are withheld by the backend and are never rendered. No step is
 * ever a clickable command control.
 */

import { Component, type ReactNode, useMemo, useState } from "react";

import {
  ANNOTATION_NOTICE,
  COMMAND_WITHHELD_NOTICE,
  CONFIRMATION_STATEMENT,
  NOT_EXECUTABLE_NOTICE,
  NO_EXECUTION_NOTICE,
  PRIVATE_PATH_NOTICE,
  PROPOSED_PLAN_NOTICE,
  RECOVERED_NOTICE,
  REVERSIBLE_NOTICE,
  ROLLBACK_NOTICE,
  SOURCE_RETAINED_NOTICE,
  VERIFICATION_NOTICE,
  approvalLabel,
  approvalSummary,
  availableActions,
  buildAnnotation,
  canCompare,
  canSubmitAction,
  commandBearingStepCount,
  confidenceLabel,
  conflictSeverityLabel,
  conflictSummary,
  describeEvidenceCard,
  evidenceNotices,
  evidenceSummary,
  filterRepairPlans,
  humanise,
  orderSteps,
  ownerStatusLabel,
  planLimitations,
  planStateLabel,
  priorityLabel,
  receiptChangeLabels,
  receiptChangedNothing,
  receiptSummary,
  recommendationLabel,
  recoveryNotices,
  recoveryOutcomeLabel,
  recoverySummary,
  removeAnnotation,
  reversibilityLabel,
  riskDimensionRows,
  riskLabel,
  rollbackLabel,
  sortRepairPlans,
  stepChangeLabels,
  stepDescription,
  stepNotices,
  strategyRiskRows,
  strategyTypeLabel,
  toggleComparison,
  unavailableActions,
  unavailableActionNotice,
  unsupportedSchemaNotice,
  upsertAnnotation,
  validateActionReason,
  verificationLabel,
  verificationSummary,
  type RepairApprovalRequirement,
  type RepairEvidenceCard,
  type RepairPlanActionDescriptor,
  type RepairPlanActionReceipt,
  type RepairPlanAnnotation,
  type RepairPlanConflict,
  type RepairPlanQueueItem,
  type RepairPlanReference,
  type RepairPlanReviewFilter,
  type RepairPlanReviewSort,
  type RepairPlanSnapshot,
  type RepairRecoveryLink,
  type RepairRiskProjection,
  type RepairStepProjection,
  type RepairVerificationRequirement,
} from "@/lib/repairPlanReview";
import {
  useBobaRepairPlanQueue,
  useBobaRepairPlanRegistry,
  useCompareBobaRepairPlans,
  useCreateBobaRepairPlanAction,
  useCreateBobaRepairPlanReviewSession,
  useCreateBobaRepairPlanSnapshot,
  useRefreshBobaRepairPlanSnapshot,
  useSubmitBobaRepairPlanAction,
  useValidateBobaRepairPlanAction,
} from "@/lib/queries";
import { classifyReviewError } from "@/lib/reviewUi";

type PanelTab =
  | "plans"
  | "steps"
  | "risk"
  | "approvals"
  | "verification"
  | "evidence"
  | "recovery"
  | "conflicts";

const TABS: { id: PanelTab; label: string }[] = [
  { id: "plans", label: "Plans" },
  { id: "steps", label: "Proposed Steps" },
  { id: "risk", label: "Risk" },
  { id: "approvals", label: "Approvals" },
  { id: "verification", label: "Verification" },
  { id: "evidence", label: "Evidence" },
  { id: "recovery", label: "Recovery" },
  { id: "conflicts", label: "Conflicts" },
];

const FILTERS: { id: RepairPlanReviewFilter; label: string }[] = [
  { id: "all_current", label: "All current" },
  { id: "human_review_required", label: "Needs human review" },
  { id: "destructive", label: "Destructive" },
  { id: "reversible", label: "Reversible" },
  { id: "code_change", label: "Code change" },
  { id: "artifact_change", label: "Artifact change" },
  { id: "workflow_change", label: "Workflow change" },
  { id: "tool_execution", label: "Tool execution" },
  { id: "process_restart", label: "Process restart" },
  { id: "checkpoint_restore", label: "Checkpoint restore" },
  { id: "missing_approval", label: "Missing approval" },
  { id: "missing_verification", label: "Missing verification" },
  { id: "failed_recovery", label: "Failed recovery" },
  { id: "conflicts", label: "Conflicts" },
  { id: "stale", label: "Stale" },
  { id: "completed", label: "Carried out by owner" },
  { id: "historical", label: "Historical" },
  { id: "superseded", label: "Superseded" },
];

const SORTS: { id: RepairPlanReviewSort; label: string }[] = [
  { id: "review_priority", label: "Review priority" },
  { id: "source_severity", label: "Source risk (owner owned)" },
  { id: "creation_order", label: "Owner record order" },
  { id: "affected_module", label: "Affected module" },
  { id: "step_count", label: "Step count" },
  { id: "repair_plan_id", label: "Repair plan ID" },
];

/** Contains unexpected render failures without leaking internals. */
export class BobaRepairPlanReviewErrorBoundary extends Component<
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
          className="rounded-lg border border-rose-300/30 bg-rose-300/[0.06] p-4 text-sm text-rose-100"
        >
          <p className="font-medium">The repair plan panel could not be displayed.</p>
          <p className="mt-1 text-xs text-rose-100/80">
            No repair plan changed. Reload the page to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

function NoticeList({ notices, tone = "muted" }: { notices: string[]; tone?: "muted" | "warn" }) {
  if (notices.length === 0) return null;
  const className =
    tone === "warn"
      ? "mt-2 space-y-1 text-xs text-amber-100/85"
      : "mt-2 space-y-1 text-xs text-white/55";
  return (
    <ul className={className}>
      {notices.map((notice) => (
        <li key={notice}>{notice}</li>
      ))}
    </ul>
  );
}

export function BobaRepairPlanCard({
  item,
  selected,
  comparing,
  onSelect,
  onToggleComparison,
}: {
  item: RepairPlanQueueItem;
  selected: boolean;
  comparing: boolean;
  onSelect: (repairPlanId: string) => void;
  onToggleComparison: (repairPlanId: string) => void;
}) {
  return (
    <li
      className={`rounded-lg border p-3 text-sm transition ${
        selected
          ? "border-sky-300/40 bg-sky-300/[0.06]"
          : "border-white/10 bg-white/[0.02] hover:border-white/20"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => onSelect(item.repair_plan_id)}
          className="text-left"
          aria-label={`Open repair plan ${item.repair_plan_id}`}
        >
          <p className="font-medium text-white">{item.title}</p>
          <p className="mt-0.5 text-xs text-white/60">
            {item.affected_module_id || "module not recorded"} ·{" "}
            {item.affected_stage_id || "stage not recorded"} · {planStateLabel(item)}
          </p>
        </button>
        <label className="flex shrink-0 items-center gap-1.5 text-xs text-white/60">
          <input
            type="checkbox"
            checked={comparing}
            onChange={() => onToggleComparison(item.repair_plan_id)}
            aria-label={`Compare repair plan ${item.repair_plan_id}`}
          />
          Compare
        </label>
      </div>

      {item.bounded_summary ? (
        <p className="mt-2 line-clamp-2 text-xs text-white/70">{item.bounded_summary}</p>
      ) : null}

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-white/60">
        <div>
          <dt className="inline text-white/45">Strategy: </dt>
          <dd className="inline">{humanise(item.original_strategy_type)}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Owner risk: </dt>
          <dd className="inline">{humanise(item.original_risk_level)}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Plan status: </dt>
          <dd className="inline">{humanise(item.original_status)}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Approval: </dt>
          <dd className="inline">{humanise(item.approval_status)}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Steps: </dt>
          <dd className="inline">{item.step_count}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Destructiveness: </dt>
          <dd className="inline">{humanise(item.original_destructiveness)}</dd>
        </div>
      </dl>

      <p className="mt-2 text-xs text-white/55">{priorityLabel(item)}</p>
      <p className="mt-1 text-xs text-white/55">{strategyTypeLabel(item)}</p>
      <p className="mt-1 text-xs text-white/55">{recommendationLabel(item)}</p>

      {item.command_bearing_step_count > 0 ? (
        <p className="mt-2 text-xs text-amber-100/85">
          {item.command_bearing_step_count} step(s) hold command text in the source.{" "}
          {COMMAND_WITHHELD_NOTICE}
        </p>
      ) : null}

      <NoticeList notices={item.warnings} tone="warn" />
      <NoticeList notices={planLimitations(item)} />
    </li>
  );
}

export function BobaRepairStepList({ steps }: { steps: RepairStepProjection[] }) {
  const ordered = orderSteps(steps);
  if (ordered.length === 0) {
    return (
      <p className="text-sm text-white/60">
        Repair Planner recorded no proposed steps for this strategy.
      </p>
    );
  }
  return (
    <>
      <p className="text-xs text-white/60">
        {ordered.length} proposed step(s), {commandBearingStepCount(ordered)} holding
        command text in the source. {NOT_EXECUTABLE_NOTICE}
      </p>
      <ol className="mt-3 space-y-2">
        {ordered.map((step) => (
          <li
            key={step.repair_step_projection_id}
            className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm"
          >
            <div className="flex items-baseline justify-between gap-3">
              <p className="font-medium text-white">
                Step {step.original_order}: {humanise(step.original_step_type)}
              </p>
              <span className="shrink-0 text-xs text-white/45">
                {humanise(step.original_status)}
              </span>
            </div>
            <p className="mt-1 text-xs text-white/75">{stepDescription(step)}</p>
            {step.bounded_safety_precondition ? (
              <p className="mt-1 text-xs text-white/55">
                Safety precondition: {step.bounded_safety_precondition}
              </p>
            ) : null}
            {step.bounded_success_condition ? (
              <p className="mt-1 text-xs text-white/55">
                Success condition: {step.bounded_success_condition}
              </p>
            ) : null}
            {stepChangeLabels(step).length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {stepChangeLabels(step).map((label) => (
                  <li
                    key={label}
                    className="rounded border border-white/15 px-1.5 py-0.5 text-[11px] text-white/70"
                  >
                    {label}
                  </li>
                ))}
              </ul>
            ) : null}
            <NoticeList notices={stepNotices(step)} tone="warn" />
            <NoticeList notices={step.limitations} />
          </li>
        ))}
      </ol>
    </>
  );
}

export function BobaRepairRiskList({ rows }: { rows: RepairRiskProjection[] }) {
  const dimensions = riskDimensionRows(rows);
  const strategyRows = strategyRiskRows(rows);
  if (rows.length === 0) {
    return (
      <p className="text-sm text-white/60">
        Repair Planner recorded no risk assessment for this repair case.
      </p>
    );
  }
  return (
    <>
      <p className="text-xs text-white/60">
        Risk levels are Repair Planner&apos;s own values. This panel computes no
        composite risk score and no repair-success estimate. {REVERSIBLE_NOTICE}
      </p>
      <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
        {dimensions.map((row) => (
          <li
            key={row.repair_risk_projection_id}
            className={`rounded border px-2 py-1.5 text-xs ${
              row.blocked_by_owner
                ? "border-rose-300/30 bg-rose-300/[0.06] text-rose-100"
                : "border-white/10 bg-white/[0.02] text-white/70"
            }`}
          >
            {riskLabel(row)}
          </li>
        ))}
      </ul>
      {strategyRows.map((row) => (
        <div
          key={row.repair_risk_projection_id}
          className="mt-3 rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm"
        >
          <p className="font-medium text-white">
            Strategy-specific risk: {humanise(row.original_risk_level)}
          </p>
          {row.bounded_reasons.length > 0 ? (
            <ul className="mt-1.5 space-y-1 text-xs text-white/70">
              {row.bounded_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
          {row.bounded_mitigations.length > 0 ? (
            <ul className="mt-1.5 space-y-1 text-xs text-white/60">
              {row.bounded_mitigations.map((item) => (
                <li key={item}>Mitigation: {item}</li>
              ))}
            </ul>
          ) : null}
          {row.bounded_residual_risk ? (
            <p className="mt-1.5 text-xs text-amber-100/85">
              Residual risk: {row.bounded_residual_risk}
            </p>
          ) : null}
          {row.acceptable_only_if.length > 0 ? (
            <ul className="mt-1.5 space-y-1 text-xs text-white/60">
              {row.acceptable_only_if.map((item) => (
                <li key={item}>Acceptable only if: {item}</li>
              ))}
            </ul>
          ) : null}
          {confidenceLabel(row) ? (
            <p className="mt-1.5 text-xs text-white/55">
              {confidenceLabel(row)} — {row.confidence_definition}
            </p>
          ) : null}
          <NoticeList notices={row.limitations} />
        </div>
      ))}
    </>
  );
}

export function BobaRepairApprovalList({ rows }: { rows: RepairApprovalRequirement[] }) {
  return (
    <>
      <p className="text-xs text-white/60">{approvalSummary(rows)}</p>
      <ul className="mt-3 space-y-2">
        {rows.map((row) => (
          <li
            key={row.approval_requirement_id}
            className={`rounded-lg border p-3 text-sm ${
              row.satisfied_by_owner
                ? "border-white/10 bg-white/[0.02]"
                : "border-amber-300/25 bg-amber-300/[0.05]"
            }`}
          >
            <p className="font-medium text-white">{approvalLabel(row)}</p>
            <p className="mt-1 text-xs text-white/70">{row.bounded_explanation}</p>
            {row.canonical_record_id ? (
              <p className="mt-1 text-xs text-white/50">
                Canonical owner record: {row.canonical_record_id}
              </p>
            ) : null}
            <NoticeList notices={row.limitations} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function BobaRepairVerificationList({
  rows,
}: {
  rows: RepairVerificationRequirement[];
}) {
  return (
    <>
      <p className="text-xs text-white/60">{verificationSummary(rows)}</p>
      <ul className="mt-3 space-y-2">
        {rows.map((row) => (
          <li
            key={row.verification_requirement_id}
            className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm"
          >
            <p className="font-medium text-white">{verificationLabel(row)}</p>
            <p className="mt-1 text-xs text-white/70">{row.bounded_explanation}</p>
            {row.validator_ids.length > 0 ? (
              <p className="mt-1 text-xs text-white/50">
                Validators: {row.validator_ids.join(", ")}
              </p>
            ) : null}
            <NoticeList notices={row.limitations} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function BobaRepairEvidenceList({ cards }: { cards: RepairEvidenceCard[] }) {
  return (
    <>
      <p className="text-xs text-white/60">{evidenceSummary(cards)}</p>
      <ul className="mt-3 space-y-2">
        {cards.map((card) => (
          <li
            key={card.repair_evidence_card_id}
            className={`rounded-lg border p-3 text-sm ${
              card.missing
                ? "border-amber-300/25 bg-amber-300/[0.05]"
                : "border-white/10 bg-white/[0.02]"
            }`}
          >
            <p className="font-medium text-white">{describeEvidenceCard(card)}</p>
            {card.bounded_summary ? (
              <p className="mt-1 text-xs text-white/70">{card.bounded_summary}</p>
            ) : null}
            {card.bounded_excerpt ? (
              <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-2 text-[11px] text-white/70">
                {card.bounded_excerpt}
              </pre>
            ) : null}
            <NoticeList notices={evidenceNotices(card)} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function BobaRepairRecoveryList({ links }: { links: RepairRecoveryLink[] }) {
  return (
    <>
      <p className="text-xs text-white/60">{recoverySummary(links)}</p>
      <ul className="mt-3 space-y-2">
        {links.map((link) => (
          <li
            key={link.repair_recovery_link_id}
            className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm"
          >
            <p className="font-medium text-white">
              Attempt {link.attempt_number ?? "(number not recorded)"} —{" "}
              {recoveryOutcomeLabel(link)}
            </p>
            {link.bounded_summary ? (
              <p className="mt-1 text-xs text-white/70">{link.bounded_summary}</p>
            ) : null}
            {link.resulting_failure_class ? (
              <p className="mt-1 text-xs text-white/55">
                Owner failure class: {humanise(link.resulting_failure_class)}
              </p>
            ) : null}
            <NoticeList notices={recoveryNotices(link)} tone="warn" />
            <NoticeList notices={link.limitations} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function BobaRepairConflictList({ rows }: { rows: RepairPlanConflict[] }) {
  return (
    <>
      <p className="text-xs text-white/60">{conflictSummary(rows)}</p>
      <ul className="mt-3 space-y-2">
        {rows.map((row) => (
          <li
            key={row.conflict_record_id}
            className={`rounded-lg border p-3 text-sm ${
              row.blocks_action
                ? "border-rose-300/30 bg-rose-300/[0.06]"
                : "border-amber-300/25 bg-amber-300/[0.05]"
            }`}
          >
            <p className="font-medium text-white">{conflictSeverityLabel(row)}</p>
            <p className="mt-1 text-xs text-white/75">{row.bounded_summary}</p>
            <p className="mt-1 text-xs text-white/55">
              {row.value_a} vs {row.value_b}
            </p>
            <NoticeList notices={row.limitations} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function BobaRepairPlanActionDialog({
  descriptor,
  snapshot,
  reason,
  confirmed,
  submitting,
  receipt,
  onReasonChange,
  onConfirmChange,
  onSubmit,
  onCancel,
}: {
  descriptor: RepairPlanActionDescriptor;
  snapshot: RepairPlanSnapshot;
  reason: string;
  confirmed: boolean;
  submitting: boolean;
  receipt: RepairPlanActionReceipt | null;
  onReasonChange: (value: string) => void;
  onConfirmChange: (value: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const reasonError = validateActionReason(descriptor, reason);
  const ready = canSubmitAction(descriptor, snapshot, reason, confirmed);
  return (
    <div
      role="dialog"
      aria-label={`Confirm ${descriptor.display_name}`}
      className="mt-3 rounded-lg border border-sky-300/30 bg-sky-300/[0.05] p-3 text-sm"
    >
      <p className="font-medium text-white">{descriptor.display_name}</p>
      <p className="mt-1 text-xs text-white/70">
        Owned by {humanise(descriptor.owning_module_id)} ·{" "}
        {descriptor.owning_operation_id}
      </p>
      {descriptor.consequences.length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs text-white/75">
          {descriptor.consequences.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      <p className="mt-2 text-xs text-amber-100/85">{CONFIRMATION_STATEMENT}</p>
      <ul className="mt-2 space-y-1 text-xs text-white/55">
        {descriptor.does_not_do.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      {descriptor.requires_reason ? (
        <label className="mt-3 block text-xs text-white/70">
          Reason
          <textarea
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            maxLength={descriptor.maximum_reason_length}
            rows={3}
            className="mt-1 w-full rounded border border-white/15 bg-black/30 p-2 text-xs text-white"
          />
        </label>
      ) : null}
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
          aria-label="Confirm this request"
        />
        I have read what this request does and does not do.
      </label>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onSubmit}
          disabled={!ready || submitting}
          className="rounded bg-sky-400/20 px-3 py-1.5 text-xs font-medium text-sky-100 disabled:opacity-40"
        >
          {submitting ? "Submitting to owner…" : "Submit to canonical owner"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-white/15 px-3 py-1.5 text-xs text-white/70"
        >
          Cancel
        </button>
      </div>

      {receipt ? (
        <div className="mt-3 rounded border border-white/10 bg-black/20 p-2 text-xs">
          <p className="text-white/80">{receiptSummary(receipt)}</p>
          <ul className="mt-1 space-y-0.5 text-white/55">
            {receiptChangeLabels(receipt).map((label) => (
              <li key={label}>{label}</li>
            ))}
          </ul>
          {receiptChangedNothing(receipt) ? (
            <p className="mt-1 text-white/45">
              The repair plan is exactly as Repair Planner recorded it.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function BobaRepairPlanReviewPanel({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState<PanelTab>("plans");
  const [filter, setFilter] = useState<RepairPlanReviewFilter>("all_current");
  const [sort, setSort] = useState<RepairPlanReviewSort>("review_priority");
  const [showHistorical, setShowHistorical] = useState(false);
  const [showSuperseded, setShowSuperseded] = useState(false);
  const [showCompleted, setShowCompleted] = useState(true);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [comparing, setComparing] = useState<string[]>([]);
  const [annotations, setAnnotations] = useState<RepairPlanAnnotation[]>([]);
  const [annotationDraft, setAnnotationDraft] = useState("");
  const [activeDescriptor, setActiveDescriptor] =
    useState<RepairPlanActionDescriptor | null>(null);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [snapshotPayload, setSnapshotPayload] = useState<{
    snapshot: RepairPlanSnapshot;
    repair_plan_reference: RepairPlanReference;
    step_projections: RepairStepProjection[];
    risk_projections: RepairRiskProjection[];
    approval_requirements: RepairApprovalRequirement[];
    verification_requirements: RepairVerificationRequirement[];
    evidence_cards: RepairEvidenceCard[];
    recovery_links: RepairRecoveryLink[];
    conflict_records: RepairPlanConflict[];
    action_confirmations: Record<string, string>;
  } | null>(null);
  const [receipt, setReceipt] = useState<RepairPlanActionReceipt | null>(null);

  const registry = useBobaRepairPlanRegistry(projectId);
  const queue = useBobaRepairPlanQueue(projectId, { filter, sort });
  const createSession = useCreateBobaRepairPlanReviewSession(projectId);
  const createSnapshot = useCreateBobaRepairPlanSnapshot(projectId);
  const refreshSnapshot = useRefreshBobaRepairPlanSnapshot(projectId);
  const compare = useCompareBobaRepairPlans(projectId);
  const createAction = useCreateBobaRepairPlanAction(projectId);
  const validateAction = useValidateBobaRepairPlanAction(projectId);
  const submitAction = useSubmitBobaRepairPlanAction(projectId);

  const descriptors = useMemo<RepairPlanActionDescriptor[]>(
    () => (registry.data?.actions as RepairPlanActionDescriptor[] | undefined) ?? [],
    [registry.data],
  );
  const items = useMemo<RepairPlanQueueItem[]>(
    () => (queue.data?.items as RepairPlanQueueItem[] | undefined) ?? [],
    [queue.data],
  );
  const visible = useMemo(
    () =>
      sortRepairPlans(
        filterRepairPlans(items, { filter, showHistorical, showSuperseded, showCompleted }),
        sort,
      ),
    [items, filter, sort, showHistorical, showSuperseded, showCompleted],
  );

  const snapshot = snapshotPayload?.snapshot ?? null;
  const offered = useMemo(
    () => (snapshot ? availableActions(descriptors, snapshot) : []),
    [descriptors, snapshot],
  );
  const withheld = useMemo(() => unavailableActions(descriptors), [descriptors]);

  async function openPlan(repairPlanId: string) {
    setSelectedPlanId(repairPlanId);
    setReceipt(null);
    setActiveDescriptor(null);
    const session = await createSession.mutateAsync({
      reviewer_context_id: "review_ui_reviewer",
    });
    const payload = await createSnapshot.mutateAsync({
      repairPlanId,
      sessionId: session.repair_plan_review_session_id,
    });
    setSnapshotPayload(payload);
  }

  async function submit() {
    if (!activeDescriptor || !snapshotPayload) return;
    const created = await createAction.mutateAsync({
      repair_plan_review_session_id:
        snapshotPayload.snapshot.repair_plan_review_session_id,
      repair_plan_snapshot_id: snapshotPayload.snapshot.repair_plan_snapshot_id,
      action_descriptor_id: activeDescriptor.action_descriptor_id,
      decision_value: activeDescriptor.allowed_decision_values[0] ?? null,
      reason,
      confirmation_context_digest:
        snapshotPayload.action_confirmations[activeDescriptor.action_descriptor_id] ?? "",
      idempotency_key: `repair_plan_${snapshotPayload.snapshot.repair_plan_snapshot_id}`,
      confirmed: true,
    });
    const requestId = String(created.repair_plan_action_request_id ?? "");
    const validation = await validateAction.mutateAsync(requestId);
    if (!validation.valid) {
      const refreshed = await refreshSnapshot.mutateAsync(
        snapshotPayload.snapshot.repair_plan_snapshot_id,
      );
      setSnapshotPayload(refreshed);
      return;
    }
    setReceipt(await submitAction.mutateAsync(requestId));
  }

  if (registry.isError || queue.isError) {
    const classified = classifyReviewError(registry.error ?? queue.error);
    return (
      <section
        aria-label="BOBA repair plan panel"
        className="rounded-lg border border-white/10 bg-white/[0.02] p-4 text-sm text-white/70"
      >
        <p>The repair plan panel is unavailable. No repair plan changed.</p>
        <p className="mt-1 text-xs text-white/55">{classified.guidance}</p>
      </section>
    );
  }

  return (
    <BobaRepairPlanReviewErrorBoundary>
      <section
        aria-label="BOBA repair plan panel"
        className="rounded-lg border border-white/10 bg-white/[0.02] p-4"
      >
        <header>
          <h3 className="text-sm font-semibold text-white">BOBA Repair Plan Panel</h3>
          <p className="mt-1 text-xs text-white/60">{PROPOSED_PLAN_NOTICE}</p>
          <p className="mt-1 text-xs text-white/50">{NO_EXECUTION_NOTICE}</p>
        </header>

        <nav className="mt-3 flex flex-wrap gap-1.5" aria-label="Repair plan sections">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setTab(entry.id)}
              aria-current={tab === entry.id}
              className={`rounded px-2 py-1 text-xs ${
                tab === entry.id
                  ? "bg-white/15 text-white"
                  : "border border-white/10 text-white/60"
              }`}
            >
              {entry.label}
            </button>
          ))}
        </nav>

        {tab === "plans" ? (
          <div className="mt-3">
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs text-white/60">
                Filter
                <select
                  value={filter}
                  onChange={(event) =>
                    setFilter(event.target.value as RepairPlanReviewFilter)
                  }
                  className="ml-1 rounded border border-white/15 bg-black/30 px-1.5 py-1 text-xs text-white"
                >
                  {FILTERS.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-white/60">
                Sort
                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value as RepairPlanReviewSort)}
                  className="ml-1 rounded border border-white/15 bg-black/30 px-1.5 py-1 text-xs text-white"
                >
                  {SORTS.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1 text-xs text-white/60">
                <input
                  type="checkbox"
                  checked={showHistorical}
                  onChange={(event) => setShowHistorical(event.target.checked)}
                />
                Historical
              </label>
              <label className="flex items-center gap-1 text-xs text-white/60">
                <input
                  type="checkbox"
                  checked={showSuperseded}
                  onChange={(event) => setShowSuperseded(event.target.checked)}
                />
                Superseded
              </label>
              <label className="flex items-center gap-1 text-xs text-white/60">
                <input
                  type="checkbox"
                  checked={showCompleted}
                  onChange={(event) => setShowCompleted(event.target.checked)}
                />
                Carried out by owner
              </label>
            </div>

            {visible.length === 0 ? (
              <p className="mt-3 text-sm text-white/60">
                No repair plan matches this view. Repair Planner records plans; this panel
                only reads them.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {visible.map((item) => (
                  <BobaRepairPlanCard
                    key={item.repair_plan_queue_item_id}
                    item={item}
                    selected={item.repair_plan_id === selectedPlanId}
                    comparing={comparing.includes(item.repair_plan_id)}
                    onSelect={(id) => void openPlan(id)}
                    onToggleComparison={(id) =>
                      setComparing((rows) => toggleComparison(rows, id))
                    }
                  />
                ))}
              </ul>
            )}

            <button
              type="button"
              disabled={!canCompare(comparing)}
              onClick={() => void compare.mutateAsync(comparing)}
              className="mt-3 rounded border border-white/15 px-2 py-1 text-xs text-white/70 disabled:opacity-40"
            >
              Compare selected plans ({comparing.length})
            </button>
            <p className="mt-1 text-xs text-white/45">
              A comparison selects no winner, no recommended plan and no plan to execute.
            </p>
          </div>
        ) : null}

        {snapshotPayload ? (
          <div className="mt-4 border-t border-white/10 pt-3">
            {unsupportedSchemaNotice(snapshotPayload.repair_plan_reference) ? (
              <p role="alert" className="mb-2 text-xs text-amber-100/85">
                {unsupportedSchemaNotice(snapshotPayload.repair_plan_reference)}
              </p>
            ) : null}
            <p className="text-xs text-white/55">
              {ownerStatusLabel("repair_planner", snapshotPayload.snapshot.plan_status)}
            </p>

            {tab === "steps" ? (
              <div className="mt-2">
                <BobaRepairStepList steps={snapshotPayload.step_projections} />
              </div>
            ) : null}
            {tab === "risk" ? (
              <div className="mt-2">
                <BobaRepairRiskList rows={snapshotPayload.risk_projections} />
              </div>
            ) : null}
            {tab === "approvals" ? (
              <div className="mt-2">
                <BobaRepairApprovalList rows={snapshotPayload.approval_requirements} />
              </div>
            ) : null}
            {tab === "verification" ? (
              <div className="mt-2">
                <BobaRepairVerificationList
                  rows={snapshotPayload.verification_requirements}
                />
              </div>
            ) : null}
            {tab === "evidence" ? (
              <div className="mt-2">
                <BobaRepairEvidenceList cards={snapshotPayload.evidence_cards} />
              </div>
            ) : null}
            {tab === "recovery" ? (
              <div className="mt-2">
                <BobaRepairRecoveryList links={snapshotPayload.recovery_links} />
              </div>
            ) : null}
            {tab === "conflicts" ? (
              <div className="mt-2">
                <BobaRepairConflictList rows={snapshotPayload.conflict_records} />
              </div>
            ) : null}

            <div className="mt-3 border-t border-white/10 pt-3">
              <p className="text-xs text-white/60">Available canonical actions</p>
              {offered.length === 0 ? (
                <p className="mt-1 text-xs text-white/50">
                  No action is available for this exact plan.
                </p>
              ) : (
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {offered.map((descriptor) => (
                    <button
                      key={descriptor.action_descriptor_id}
                      type="button"
                      onClick={() => {
                        setActiveDescriptor(descriptor);
                        setReason("");
                        setConfirmed(false);
                        setReceipt(null);
                      }}
                      className="rounded border border-sky-300/30 px-2 py-1 text-xs text-sky-100"
                    >
                      {descriptor.display_name}
                    </button>
                  ))}
                </div>
              )}

              {activeDescriptor && snapshot ? (
                <BobaRepairPlanActionDialog
                  descriptor={activeDescriptor}
                  snapshot={snapshot}
                  reason={reason}
                  confirmed={confirmed}
                  submitting={submitAction.isPending}
                  receipt={receipt}
                  onReasonChange={setReason}
                  onConfirmChange={setConfirmed}
                  onSubmit={() => void submit()}
                  onCancel={() => setActiveDescriptor(null)}
                />
              ) : null}

              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-white/55">
                  Actions withheld in V1 ({withheld.length})
                </summary>
                <ul className="mt-1.5 space-y-1 text-xs text-white/50">
                  {withheld.map((descriptor) => (
                    <li key={descriptor.action_descriptor_id}>
                      {unavailableActionNotice(descriptor)}
                    </li>
                  ))}
                </ul>
              </details>
            </div>

            <div className="mt-3 border-t border-white/10 pt-3">
              <label className="block text-xs text-white/60">
                Review-session annotation
                <textarea
                  value={annotationDraft}
                  onChange={(event) => setAnnotationDraft(event.target.value)}
                  rows={2}
                  className="mt-1 w-full rounded border border-white/15 bg-black/30 p-2 text-xs text-white"
                />
              </label>
              <p className="mt-1 text-xs text-white/45">{ANNOTATION_NOTICE}</p>
              <button
                type="button"
                onClick={() => {
                  const built = buildAnnotation(
                    snapshotPayload.snapshot.repair_plan_id,
                    tab,
                    annotationDraft,
                  );
                  if (built) {
                    setAnnotations((rows) => upsertAnnotation(rows, built));
                    setAnnotationDraft("");
                  }
                }}
                className="mt-1.5 rounded border border-white/15 px-2 py-1 text-xs text-white/70"
              >
                Add annotation
              </button>
              <ul className="mt-2 space-y-1">
                {annotations.map((row) => (
                  <li key={row.annotation_id} className="text-xs text-white/70">
                    {row.text}
                    <button
                      type="button"
                      onClick={() =>
                        setAnnotations((rows) => removeAnnotation(rows, row.annotation_id))
                      }
                      className="ml-2 text-white/40"
                      aria-label={`Remove annotation ${row.annotation_id}`}
                    >
                      remove
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            <footer className="mt-3 space-y-1 border-t border-white/10 pt-3 text-xs text-white/45">
              <p>{REVERSIBLE_NOTICE}</p>
              <p>{ROLLBACK_NOTICE}</p>
              <p>{VERIFICATION_NOTICE}</p>
              <p>{RECOVERED_NOTICE}</p>
              <p>{NOT_EXECUTABLE_NOTICE}</p>
              <p>{COMMAND_WITHHELD_NOTICE}</p>
              <p>{PRIVATE_PATH_NOTICE}</p>
              <p>{SOURCE_RETAINED_NOTICE}</p>
            </footer>
          </div>
        ) : null}
      </section>
    </BobaRepairPlanReviewErrorBoundary>
  );
}
