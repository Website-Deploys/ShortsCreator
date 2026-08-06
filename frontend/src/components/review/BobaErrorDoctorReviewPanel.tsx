"use client";

/**
 * BOBA Error Doctor Panel V1.
 *
 * A specialized read-only mode of the BOBA Review UI, rendered beside the
 * Candidate Review Panel and the Clip Brief Panel rather than replacing any of
 * them. It is a trusted incident projection, an evidence workspace, a diagnosis
 * and root-cause comparison surface, a recovery-history viewer and a safe
 * canonical action router.
 *
 * It never detects an error, creates an incident, diagnoses, determines a root
 * cause, creates a repair plan, executes a repair or recovery, restores a
 * checkpoint, changes a workflow, modifies code, artifacts or media, runs a
 * command, shell, Git or FFmpeg, installs or downloads a tool, uploads or
 * publishes. A hypothesis is never shown as a fact, owner-reported recovery
 * success is never shown as independent verification, and recovered is never
 * shown as resolved.
 */

import { Component, type ReactNode, useEffect, useMemo, useState } from "react";

import {
  CONFIDENCE_NOTICE,
  LOCAL_ANNOTATION_NOTICE,
  NO_EXECUTION_NOTICE,
  NO_WINNER_NOTICE,
  RECOVERED_NOTICE,
  REPAIR_EXECUTION_NOTICE,
  ROOT_CAUSE_NOTICE,
  availableActions,
  boundedLogCardIds,
  buildAnnotation,
  canCompare,
  canSubmitAction,
  classificationLabel,
  confidenceLabel,
  confirmationText,
  conflictResolutionLabel,
  conflictSummary,
  describeEvidenceCard,
  errorCodeLabel,
  evidenceSummary,
  excerptNotices,
  incidentStateLabel,
  ownerStatusLabel,
  priorityLabel,
  receiptChangeLabels,
  receiptChangedAuthority,
  receiptSummary,
  recoveryChangeLabels,
  recoveryOutcomeLabel,
  recoverySummary,
  removeAnnotation,
  repairOwnerRankLabel,
  repairRequirements,
  repairRiskLabel,
  revisionNotice,
  rootCauseHeading,
  severityLabel,
  toggleComparison,
  unavailableActionNotice,
  unsupportedSchemaNotice,
  upsertAnnotation,
  validateActionReason,
  type DiagnosisProjection,
  type ErrorConflict,
  type ErrorDoctorActionDescriptor,
  type ErrorDoctorActionReceipt,
  type ErrorDoctorAnnotation,
  type ErrorDoctorReviewFilter,
  type ErrorDoctorReviewSort,
  type ErrorEvidenceCard,
  type IncidentQueueItem,
  type IncidentReference,
  type IncidentSnapshot,
  type RecoveryAttemptProjection,
  type RepairPlanProjection,
  type RootCauseProjection,
} from "@/lib/errorDoctorReview";
import {
  useBobaErrorDoctorRegistry,
  useBobaIncidentQueue,
  useCompareBobaIncidents,
  useCreateBobaErrorDoctorAction,
  useCreateBobaErrorDoctorReviewSession,
  useCreateBobaIncidentSnapshot,
  useRefreshBobaIncidentSnapshot,
  useSubmitBobaErrorDoctorAction,
  useUpdateBobaErrorDoctorReviewSession,
  useValidateBobaErrorDoctorAction,
} from "@/lib/queries";
import { classifyReviewError } from "@/lib/reviewUi";

type PanelTab =
  | "incidents"
  | "diagnosis"
  | "root_cause"
  | "repair"
  | "recovery"
  | "evidence"
  | "events";

const TABS: { id: PanelTab; label: string }[] = [
  { id: "incidents", label: "Incidents" },
  { id: "diagnosis", label: "Diagnosis" },
  { id: "root_cause", label: "Root Cause" },
  { id: "repair", label: "Repair" },
  { id: "recovery", label: "Recovery" },
  { id: "evidence", label: "Evidence" },
  { id: "events", label: "Events" },
];

const FILTERS: { id: ErrorDoctorReviewFilter; label: string }[] = [
  { id: "all_current", label: "All current" },
  { id: "critical", label: "Critical" },
  { id: "workflow_blocking", label: "Workflow blocking" },
  { id: "human_review_required", label: "Needs human review" },
  { id: "missing_diagnosis", label: "Missing diagnosis" },
  { id: "missing_root_cause", label: "Missing root cause" },
  { id: "repair_plan_available", label: "Repair plan available" },
  { id: "failed_recovery", label: "Failed recovery" },
  { id: "unverified_recovery", label: "Unverified recovery" },
  { id: "recurring", label: "Recurring" },
  { id: "conflicts", label: "Conflicts" },
  { id: "missing_evidence", label: "Missing evidence" },
  { id: "stale", label: "Stale" },
  { id: "recovered", label: "Recovered" },
  { id: "resolved", label: "Resolved" },
  { id: "historical", label: "Historical" },
  { id: "superseded", label: "Superseded" },
];

const SORTS: { id: ErrorDoctorReviewSort; label: string }[] = [
  { id: "review_priority", label: "Review priority" },
  { id: "source_severity", label: "Source severity (owner owned)" },
  { id: "first_seen", label: "First seen" },
  { id: "last_seen", label: "Last seen" },
  { id: "affected_stage", label: "Affected stage" },
  { id: "affected_module", label: "Affected module" },
  { id: "incident_id", label: "Incident ID" },
];

/** Contains unexpected render failures without leaking internals. */
export class BobaErrorDoctorReviewErrorBoundary extends Component<
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
          <p className="font-medium">The error doctor panel could not be displayed.</p>
          <p className="mt-1 text-xs text-rose-100/80">
            No incident state changed. Reload the page to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

export function BobaIncidentCard({
  item,
  selected,
  comparing,
  onSelect,
  onToggleComparison,
}: {
  item: IncidentQueueItem;
  selected: boolean;
  comparing: boolean;
  onSelect: (incidentId: string) => void;
  onToggleComparison: (incidentId: string) => void;
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
          onClick={() => onSelect(item.incident_id)}
          className="text-left"
          aria-label={`Open incident ${item.incident_id}`}
        >
          <p className="font-medium text-white">{item.title}</p>
          <p className="mt-0.5 text-xs text-white/60">
            {item.affected_module_id || "module not recorded"} ·{" "}
            {item.affected_stage_id || "stage not recorded"} · {incidentStateLabel(item)}
          </p>
        </button>
        <label className="flex shrink-0 items-center gap-1.5 text-xs text-white/60">
          <input
            type="checkbox"
            checked={comparing}
            onChange={() => onToggleComparison(item.incident_id)}
            aria-label={`Compare incident ${item.incident_id}`}
          />
          Compare
        </label>
      </div>

      {item.bounded_summary ? (
        <p className="mt-2 line-clamp-2 text-xs text-white/70">{item.bounded_summary}</p>
      ) : null}

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-white/60">
        <div>
          <dt className="inline text-white/45">Error class: </dt>
          <dd className="inline">{item.original_error_class}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Severity: </dt>
          <dd className="inline">{severityLabel(item.original_severity)}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Diagnosis: </dt>
          <dd className="inline">{item.diagnosis_status}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Root cause: </dt>
          <dd className="inline">{item.root_cause_status}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Repair plan: </dt>
          <dd className="inline">{item.repair_plan_status}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Recovery: </dt>
          <dd className="inline">{item.recovery_status}</dd>
        </div>
      </dl>

      <p className="mt-2 text-xs text-white/50">{evidenceSummary(item)}</p>
      <p className="mt-1 text-[11px] text-white/40">{priorityLabel(item)}</p>

      {item.failed_recovery_attempt_count > 0 ? (
        <p className="mt-1 text-[11px] text-amber-200/90">
          {item.failed_recovery_attempt_count} failed recovery attempt(s) recorded by the
          owner.
        </p>
      ) : null}
      {item.human_action_required ? (
        <p className="mt-1 text-[11px] text-amber-200/90">
          A person must review this incident against its canonical sources.
        </p>
      ) : null}
      {item.warnings.length > 0 ? (
        <ul className="mt-1 space-y-0.5 text-[11px] text-amber-200/80">
          {item.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function BobaIncidentOverview({
  reference,
  snapshot,
}: {
  reference: IncidentReference | null;
  snapshot: IncidentSnapshot | null;
}) {
  if (!reference || !snapshot) {
    return <p className="text-sm text-white/60">Select an incident to review it.</p>;
  }
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60">
      <p className="text-sm font-medium text-white">Incident {reference.incident_id}</p>
      <p className="mt-1">
        Module {reference.affected_module_id || "not recorded"} · stage{" "}
        {reference.affected_stage_id || "not recorded"} · workflow run{" "}
        {reference.workflow_run_id ?? "not bound"}
      </p>
      <p className="mt-1">
        Error class {reference.error_class} · {errorCodeLabel(reference)} ·{" "}
        {severityLabel(reference.original_severity)}
      </p>
      <p className="mt-1">{revisionNotice(reference)}</p>
      <p className="mt-1">
        {reference.recovered
          ? "An owner reported a completed recovery attempt. This is not resolution."
          : "No completed recovery attempt is recorded."}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
        {(
          [
            ["validator_runner", snapshot.validation_status],
            ["artifact_inspector", snapshot.artifact_status],
            ["workflow_controller", snapshot.workflow_status],
            ["safety_gate", snapshot.safety_status],
            ["final_decision_bus", snapshot.final_decision_status],
          ] as const
        ).map(([moduleId, status]) => (
          <div key={moduleId}>
            <dt className="inline text-white/45">{moduleId}: </dt>
            <dd className="inline">{ownerStatusLabel(moduleId, status)}</dd>
          </div>
        ))}
      </dl>
      {unsupportedSchemaNotice(reference) ? (
        <p className="mt-1 text-amber-200/90">{unsupportedSchemaNotice(reference)}</p>
      ) : null}
      {reference.limitations.length > 0 ? (
        <ul className="mt-1 space-y-0.5 text-white/40">
          {reference.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function BobaDiagnosisReview({
  projections,
}: {
  projections: DiagnosisProjection[];
}) {
  if (projections.length === 0) {
    return (
      <p className="text-sm text-white/60">
        Error Doctor has supplied no diagnosis for this incident.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {projections.map((item) => (
        <article
          key={item.diagnosis_projection_id}
          className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs"
        >
          <p className="text-sm font-medium text-white">
            {ownerStatusLabel(item.source_module_id, item.original_status)}
          </p>
          <p className="mt-1 text-white/60">
            Category {item.original_category} · error class {item.original_error_class}
          </p>
          <p className="mt-2 text-white/45">Original wording, exactly as stored:</p>
          <pre className="mt-1 whitespace-pre-wrap break-words text-white/80">
            {item.bounded_technical_explanation}
          </pre>
          <p className="mt-2 text-white/45">Plain language, kept separate:</p>
          <p className="mt-1 text-white/70">{item.bounded_easy_explanation}</p>
          <p className="mt-2 text-white/60">
            {confidenceLabel(
              item.confidence_value,
              item.confidence_name,
              item.confidence_definition,
            )}
          </p>
          <p className="mt-1 text-[11px] text-white/40">{CONFIDENCE_NOTICE}</p>
          <p className="mt-2 text-white/60">
            {item.confirmed_fact_ids.length} confirmed fact(s),{" "}
            {item.assessment_ids.length} assessment(s), {item.hypothesis_ids.length}{" "}
            hypothesis(es)
          </p>
          {item.sensitive_values_redacted ? (
            <p className="mt-1 text-[11px] text-white/40">Sensitive values redacted</p>
          ) : null}
          {item.private_paths_redacted ? (
            <p className="mt-1 text-[11px] text-white/40">
              Private path details redacted
            </p>
          ) : null}
          {item.limitations.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-[11px] text-white/40">
              {item.limitations.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export function BobaRootCauseReview({
  projections,
}: {
  projections: RootCauseProjection[];
}) {
  if (projections.length === 0) {
    return (
      <p className="text-sm text-white/60">
        Root Cause Analyzer has supplied no analysis for this incident.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-white/45">{ROOT_CAUSE_NOTICE}</p>
      {projections.map((item) => (
        <article
          key={item.root_cause_projection_id}
          className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs"
          data-confirmed={item.confirmed}
        >
          <p className="text-sm font-medium text-white">{rootCauseHeading(item)}</p>
          <p className="mt-1 text-white/70">{item.original_summary}</p>
          <p className="mt-1 text-white/60">
            {ownerStatusLabel(item.source_module_id, item.original_status)} ·
            classification {item.original_classification} · evidence quality{" "}
            {item.evidence_quality}
          </p>
          <p className="mt-1 text-white/60">
            {confidenceLabel(
              item.confidence_value,
              item.confidence_name,
              item.confidence_definition,
            )}
          </p>
          {item.likelihood_value !== null ? (
            <p className="mt-1 text-white/60">
              {item.likelihood_name} = {item.likelihood_value} (separate owner value)
            </p>
          ) : null}
          <p className="mt-1 text-white/60">
            {item.evidence_record_ids.length} supporting and{" "}
            {item.contradictory_evidence_record_ids.length} contradictory evidence
            record(s)
          </p>
          {item.human_confirmation_required ? (
            <p className="mt-1 text-amber-200/90">
              The owning module requires human confirmation for this candidate.
            </p>
          ) : null}
          {item.limitations.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-[11px] text-white/40">
              {item.limitations.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export function BobaRepairPlanReview({
  projections,
}: {
  projections: RepairPlanProjection[];
}) {
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-amber-200/90">{REPAIR_EXECUTION_NOTICE}</p>
      {projections.length === 0 ? (
        <p className="text-sm text-white/60">
          Repair Planner has supplied no repair plan for this incident.
        </p>
      ) : (
        projections.map((item) => (
          <article
            key={item.repair_plan_projection_id}
            className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs"
          >
            <p className="text-sm font-medium text-white">
              {item.repair_plan_id} · {item.original_strategy}
            </p>
            <p className="mt-1 text-white/60">
              {ownerStatusLabel(item.source_module_id, item.original_status)}
            </p>
            <p className="mt-1 text-white/70">{item.original_summary}</p>
            <p className="mt-1 text-white/70">{item.bounded_explanation}</p>
            <p className="mt-2 text-white/60">{repairRiskLabel(item)}</p>
            <p className="mt-1 text-white/60">{repairOwnerRankLabel(item)}</p>
            <p className="mt-2 text-white/45">
              {item.proposed_step_count} proposed step(s), described only:
            </p>
            <ul className="mt-1 space-y-0.5 text-white/70">
              {item.proposed_step_summaries.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
            {repairRequirements(item).length > 0 ? (
              <ul className="mt-2 space-y-0.5 text-amber-200/80">
                {repairRequirements(item).map((row) => (
                  <li key={row}>{row}</li>
                ))}
              </ul>
            ) : null}
            <p className="mt-2 text-[11px] text-white/40">
              No step is executable from this panel and no command text is shown.
            </p>
            {item.limitations.length > 0 ? (
              <ul className="mt-1 space-y-0.5 text-[11px] text-white/40">
                {item.limitations.map((row) => (
                  <li key={row}>{row}</li>
                ))}
              </ul>
            ) : null}
          </article>
        ))
      )}
    </div>
  );
}

export function BobaRecoveryHistory({
  attempts,
}: {
  attempts: RecoveryAttemptProjection[];
}) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-white/60">{recoverySummary(attempts)}</p>
      {attempts.map((item) => (
        <article
          key={item.recovery_attempt_projection_id}
          className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs"
          data-verified={item.verified}
        >
          <p className="text-sm font-medium text-white">
            Attempt {item.attempt_number ?? "unnumbered"} · {item.recovery_attempt_id}
          </p>
          <p className="mt-1 text-white/70">{recoveryOutcomeLabel(item)}</p>
          <p className="mt-1 text-white/60">
            {ownerStatusLabel(item.source_module_id, item.original_status)} · tool{" "}
            {item.invoked_tool || "not recorded"} · exit code{" "}
            {item.exit_code ?? "not recorded"}
          </p>
          <p className="mt-1 text-white/60">
            Started {item.started_at ?? "not recorded"} · completed{" "}
            {item.completed_at ?? "not recorded"}
          </p>
          <ul className="mt-2 space-y-0.5 text-white/60">
            {recoveryChangeLabels(item).map((row) => (
              <li key={row}>{row}</li>
            ))}
          </ul>
          <p className="mt-1 text-white/60">
            Rollback {item.rollback_attempted ? "attempted" : "not attempted"} · status{" "}
            {item.rollback_status}
          </p>
          {item.bounded_summary ? (
            <p className="mt-2 text-white/70">{item.bounded_summary}</p>
          ) : null}
          {item.limitations.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-[11px] text-white/40">
              {item.limitations.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          ) : null}
        </article>
      ))}
      <p className="text-[11px] text-white/45">{RECOVERED_NOTICE}</p>
    </div>
  );
}

export function BobaErrorEvidence({
  cards,
  showBoundedLogs,
}: {
  cards: ErrorEvidenceCard[];
  showBoundedLogs: boolean;
}) {
  const expandable = boundedLogCardIds(
    cards.filter((item) => item.bounded_excerpt).map((item) => item.evidence_card_id),
  );
  return (
    <ul className="space-y-2">
      {cards.map((card) => (
        <li
          key={card.evidence_card_id}
          className="rounded border border-white/10 bg-white/[0.02] p-3 text-xs"
          data-missing={card.missing}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm text-white">{card.title}</p>
            <span className="text-[11px] text-white/45">
              {classificationLabel(card.classification)} ·{" "}
              {card.advisory_only ? "advisory" : "authoritative"} ·{" "}
              {card.authority_domain}
            </span>
          </div>
          <p className="mt-1 text-white/70">{describeEvidenceCard(card)}</p>
          {card.confirmed_fact ? (
            <p className="mt-1 text-white/70">Confirmed fact: {card.confirmed_fact}</p>
          ) : null}
          {card.assessment ? (
            <p className="mt-1 text-white/60">Assessment: {card.assessment}</p>
          ) : null}
          {card.hypothesis ? (
            <p className="mt-1 text-white/60">Hypothesis: {card.hypothesis}</p>
          ) : null}
          {showBoundedLogs &&
          card.bounded_excerpt &&
          expandable.includes(card.evidence_card_id) ? (
            <pre
              aria-label={`Bounded excerpt for ${card.title}`}
              className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-2 text-white/70"
            >
              {card.bounded_excerpt}
            </pre>
          ) : null}
          <ul className="mt-1 space-y-0.5 text-[11px] text-white/40">
            {excerptNotices(card).map((row) => (
              <li key={row}>{row}</li>
            ))}
          </ul>
          {card.limitations.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-[11px] text-white/40">
              {card.limitations.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function BobaIncidentConflicts({ conflicts }: { conflicts: ErrorConflict[] }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-white/60">{conflictSummary(conflicts)}</p>
      {conflicts.map((conflict) => (
        <article
          key={conflict.conflict_record_id}
          className="rounded border border-amber-300/30 bg-amber-300/[0.05] p-3 text-xs"
          data-blocking={conflict.blocks_action}
        >
          <p className="text-sm text-white">{conflict.conflict_type}</p>
          <p className="mt-1 text-white/70">{conflict.bounded_summary}</p>
          <p className="mt-1 text-white/50">
            Value A: {conflict.value_a || "not recorded"} · Value B:{" "}
            {conflict.value_b || "not recorded"}
          </p>
          <p className="mt-1 text-white/50">{conflictResolutionLabel(conflict)}</p>
          {conflict.limitations.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-white/40">
              {conflict.limitations.map((row) => (
                <li key={row}>{row}</li>
              ))}
            </ul>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export function BobaErrorDoctorActionBar({
  descriptors,
  snapshot,
  confirmations,
  receipt,
  message,
  onSelect,
}: {
  descriptors: ErrorDoctorActionDescriptor[];
  snapshot: IncidentSnapshot | null;
  confirmations: Record<string, string>;
  receipt: ErrorDoctorActionReceipt | null;
  message: string | null;
  onSelect: (descriptor: ErrorDoctorActionDescriptor) => void;
}) {
  const offered = availableActions(descriptors, snapshot, confirmations);
  const withheld = descriptors.filter(
    (item) =>
      !offered.some((row) => row.action_descriptor_id === item.action_descriptor_id),
  );
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-white/45">{NO_EXECUTION_NOTICE}</p>
      {offered.length === 0 ? (
        <p className="text-sm text-white/60">
          No review action is available for this exact incident right now.
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
          <ul className="mt-1 space-y-0.5 text-white/45">
            {receiptChangeLabels(receipt).map((row) => (
              <li key={row}>{row}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function BobaErrorDoctorActionDialog({
  descriptor,
  snapshot,
  confirmations,
  incidentId,
  submitting,
  onCancel,
  onConfirm,
}: {
  descriptor: ErrorDoctorActionDescriptor | null;
  snapshot: IncidentSnapshot | null;
  confirmations: Record<string, string>;
  incidentId: string;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: (decisionValue: string | null, reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  if (!descriptor) return null;
  const decision = descriptor.allowed_decision_values[0] ?? null;
  const reasonError = validateActionReason(reason, descriptor);
  const ready = canSubmitAction(
    descriptor,
    snapshot,
    confirmations,
    reason,
    decision,
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
      <p className="mt-2 text-xs text-white/70">
        {confirmationText(descriptor, incidentId)}
      </p>
      {descriptor.does_not_do.length > 0 ? (
        <ul className="mt-2 space-y-0.5 text-xs text-white/45">
          {descriptor.does_not_do.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      ) : null}
      {descriptor.requires_reason ? (
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
      ) : null}
      {reasonError ? (
        <p className="mt-1 text-xs text-amber-200/90">{reasonError}</p>
      ) : null}
      <label className="mt-3 flex items-start gap-2 text-xs text-white/60">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I have reviewed this exact incident and its canonical evidence.
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
          onClick={() => onConfirm(decision, reason)}
          className="rounded border border-sky-300/30 bg-sky-300/[0.12] px-3 py-1.5 text-xs text-sky-100 disabled:opacity-40"
        >
          {submitting ? "Submitting…" : "Send to the owning module"}
        </button>
      </div>
    </div>
  );
}

export function BobaErrorDoctorAnnotations({
  annotations,
  incidentId,
  onAdd,
  onRemove,
}: {
  annotations: ErrorDoctorAnnotation[];
  incidentId: string;
  onAdd: (annotation: ErrorDoctorAnnotation) => void;
  onRemove: (annotationId: string) => void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    const annotation = buildAnnotation(incidentId, "diagnosis", text);
    if (!annotation) {
      setError("Enter note text without credentials.");
      return;
    }
    setError(null);
    setText("");
    onAdd(annotation);
  };
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-white/45">{LOCAL_ANNOTATION_NOTICE}</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grow text-xs text-white/60">
          Note
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={4_000}
            className="mt-1 block w-full rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-white"
          />
        </label>
        <button
          type="button"
          onClick={submit}
          className="rounded border border-white/10 px-3 py-1.5 text-xs text-white/70"
        >
          Add note
        </button>
      </div>
      {error ? <p className="text-xs text-amber-200/90">{error}</p> : null}
      <ul className="space-y-2">
        {annotations.map((annotation) => (
          <li
            key={annotation.annotation_id}
            className="rounded border border-white/10 bg-white/[0.02] p-3 text-xs"
          >
            <p className="text-white/70">{annotation.text}</p>
            <p className="mt-1 text-[11px] text-white/40">{annotation.notice}</p>
            <button
              type="button"
              onClick={() => onRemove(annotation.annotation_id)}
              className="mt-1 text-[11px] text-white/50 underline"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BobaErrorDoctorReviewPanel({ projectId }: { projectId: string }) {
  const reviewerContextId = "local_reviewer";
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ErrorDoctorReviewFilter>("all_current");
  const [sort, setSort] = useState<ErrorDoctorReviewSort>("review_priority");
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Record<string, unknown> | null>(null);
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [reference, setReference] = useState<IncidentReference | null>(null);
  const [diagnoses, setDiagnoses] = useState<DiagnosisProjection[]>([]);
  const [rootCauses, setRootCauses] = useState<RootCauseProjection[]>([]);
  const [cards, setCards] = useState<ErrorEvidenceCard[]>([]);
  const [repairPlans, setRepairPlans] = useState<RepairPlanProjection[]>([]);
  const [attempts, setAttempts] = useState<RecoveryAttemptProjection[]>([]);
  const [conflicts, setConflicts] = useState<ErrorConflict[]>([]);
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});
  const [showBoundedLogs, setShowBoundedLogs] = useState(false);
  const [annotations, setAnnotations] = useState<ErrorDoctorAnnotation[]>([]);
  const [tab, setTab] = useState<PanelTab>("incidents");
  const [pending, setPending] = useState<ErrorDoctorActionDescriptor | null>(null);
  const [receipt, setReceipt] = useState<ErrorDoctorActionReceipt | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const registry = useBobaErrorDoctorRegistry(projectId);
  const queue = useBobaIncidentQueue(projectId, { filter, sort });
  const createSession = useCreateBobaErrorDoctorReviewSession(projectId);
  const updateSession = useUpdateBobaErrorDoctorReviewSession(projectId);
  const createSnapshot = useCreateBobaIncidentSnapshot(projectId);
  const refreshSnapshot = useRefreshBobaIncidentSnapshot(projectId);
  const compareIncidents = useCompareBobaIncidents(projectId);
  const createAction = useCreateBobaErrorDoctorAction(projectId);
  const validateAction = useValidateBobaErrorDoctorAction(projectId);
  const submitAction = useSubmitBobaErrorDoctorAction(projectId);

  const items: IncidentQueueItem[] = queue.data?.items ?? [];
  const descriptors = useMemo<ErrorDoctorActionDescriptor[]>(
    () => registry.data?.actions ?? [],
    [registry.data],
  );

  useEffect(() => {
    if (sessionId || createSession.isPending) return;
    createSession.mutate(
      { reviewer_context_id: reviewerContextId },
      { onSuccess: (session) => setSessionId(session.error_doctor_review_session_id) },
    );
  }, [sessionId, createSession]);

  const applySnapshot = (payload: {
    snapshot: IncidentSnapshot;
    incident_reference: IncidentReference;
    diagnosis_projections: DiagnosisProjection[];
    root_cause_projections: RootCauseProjection[];
    evidence_cards: ErrorEvidenceCard[];
    repair_plan_projections: RepairPlanProjection[];
    recovery_attempt_projections: RecoveryAttemptProjection[];
    conflict_records: ErrorConflict[];
    action_confirmations: Record<string, string>;
  }) => {
    setSnapshot(payload.snapshot);
    setReference(payload.incident_reference);
    setDiagnoses(payload.diagnosis_projections);
    setRootCauses(payload.root_cause_projections);
    setCards(payload.evidence_cards);
    setRepairPlans(payload.repair_plan_projections);
    setAttempts(payload.recovery_attempt_projections);
    setConflicts(payload.conflict_records);
    setConfirmations(payload.action_confirmations ?? {});
  };

  const selectIncident = (incidentId: string) => {
    setSelectedIncidentId(incidentId);
    setReceipt(null);
    setActionMessage(null);
    setTab("diagnosis");
    if (!sessionId) return;
    createSnapshot.mutate(
      { incidentId, sessionId },
      {
        onSuccess: (payload) => {
          applySnapshot(payload);
          setBanner(null);
        },
        onError: (error) => setBanner(classifyReviewError(error).guidance),
      },
    );
  };

  const toggleIncidentComparison = (incidentId: string) => {
    const next = toggleComparison(comparisonIds, incidentId);
    setComparisonIds(next);
    setComparison(null);
    if (sessionId) {
      updateSession.mutate({ sessionId, updates: { comparison_incident_ids: next } });
    }
  };

  const runComparison = () => {
    if (!canCompare(comparisonIds)) return;
    compareIncidents.mutate(comparisonIds, {
      onSuccess: (payload) => setComparison(payload.comparison),
      onError: (error) => setBanner(classifyReviewError(error).guidance),
    });
  };

  /**
   * Re-read canonical state, then create, validate and submit. No incident,
   * diagnosis, repair, recovery or workflow value is updated optimistically.
   */
  const confirmAction = (decisionValue: string | null, reason: string) => {
    if (!pending || !snapshot || !sessionId) return;
    refreshSnapshot.mutate(snapshot.incident_snapshot_id, {
      onError: (error) => setActionMessage(classifyReviewError(error).guidance),
      onSuccess: (refreshed) => {
        applySnapshot(refreshed);
        if (refreshed.snapshot.snapshot_digest !== snapshot.snapshot_digest) {
          setActionMessage(
            "Canonical incident state changed while this review was open. Review the refreshed record, then confirm again.",
          );
          return;
        }
        const token = (refreshed.action_confirmations ?? {})[
          pending.action_descriptor_id
        ];
        if (!token) {
          setActionMessage("This action is no longer available for this exact incident.");
          return;
        }
        createAction.mutate(
          {
            error_doctor_review_session_id: sessionId,
            incident_snapshot_id: refreshed.snapshot.incident_snapshot_id,
            action_descriptor_id: pending.action_descriptor_id,
            decision_value: decisionValue,
            reason,
            confirmation_context_digest: token,
            idempotency_key: `error_doctor_${refreshed.snapshot.incident_snapshot_id}_${pending.action_descriptor_id}`,
            confirmed: true,
          },
          {
            onError: (error) => setActionMessage(classifyReviewError(error).guidance),
            onSuccess: (created) => {
              const requestId = String(created.error_doctor_action_request_id ?? "");
              validateAction.mutate(requestId, {
                onError: (error) =>
                  setActionMessage(classifyReviewError(error).guidance),
                onSuccess: (validation) => {
                  if (!validation.valid) {
                    setActionMessage(validation.message);
                    return;
                  }
                  submitAction.mutate(requestId, {
                    onError: (error) =>
                      setActionMessage(classifyReviewError(error).guidance),
                    onSuccess: (owner) => {
                      setReceipt(owner);
                      setPending(null);
                      setActionMessage(null);
                    },
                  });
                },
              });
            },
          },
        );
      },
    });
  };

  return (
    <section
      aria-label="BOBA error doctor panel"
      className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-white">Error Doctor Panel</h2>
          <p className="mt-0.5 text-xs text-white/50">
            A read-only projection of the incidents, diagnoses, root-cause findings,
            repair plans and recovery attempts the reliability modules persisted.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {TABS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setTab(option.id)}
              aria-pressed={tab === option.id}
              className={`rounded px-2 py-1 text-xs ${
                tab === option.id
                  ? "bg-white/[0.10] text-white"
                  : "text-white/60 hover:text-white"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>

      {banner ? (
        <p role="status" className="mt-3 text-xs text-amber-200/90">
          {banner}
        </p>
      ) : null}
      {queue.isError ? (
        <p role="status" className="mt-3 text-xs text-amber-200/90">
          {classifyReviewError(queue.error).guidance}
        </p>
      ) : null}

      <div className="mt-4 space-y-4">
        {tab === "incidents" ? (
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs text-white/50" htmlFor="incident-filter">
                Filter
              </label>
              <select
                id="incident-filter"
                value={filter}
                onChange={(event) =>
                  setFilter(event.target.value as ErrorDoctorReviewFilter)
                }
                className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-white"
              >
                {FILTERS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
              <label className="text-xs text-white/50" htmlFor="incident-sort">
                Sort
              </label>
              <select
                id="incident-sort"
                value={sort}
                onChange={(event) =>
                  setSort(event.target.value as ErrorDoctorReviewSort)
                }
                className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-white"
              >
                {SORTS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span className="text-xs text-white/40">
                {queue.data?.total ?? 0} incident(s) projected
              </span>
              <button
                type="button"
                disabled={!canCompare(comparisonIds) || compareIncidents.isPending}
                onClick={runComparison}
                className="rounded border border-white/10 px-3 py-1 text-xs text-white/70 disabled:opacity-40"
              >
                Compare selected
              </button>
            </div>

            {items.length === 0 ? (
              <p className="mt-3 text-sm text-white/60">
                No incident matches this filter. Nothing is hidden by a score.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {items.map((item) => (
                  <BobaIncidentCard
                    key={item.incident_queue_item_id}
                    item={item}
                    selected={item.incident_id === selectedIncidentId}
                    comparing={comparisonIds.includes(item.incident_id)}
                    onSelect={selectIncident}
                    onToggleComparison={toggleIncidentComparison}
                  />
                ))}
              </ul>
            )}

            {comparison ? (
              <div className="mt-4 rounded border border-white/10 bg-white/[0.02] p-3 text-xs">
                <p className="text-white/70">
                  Comparing {String((comparison.incident_ids as string[]).join(", "))}
                </p>
                <p className="mt-1 text-[11px] text-white/45">{NO_WINNER_NOTICE}</p>
              </div>
            ) : null}
          </div>
        ) : null}

        {tab === "diagnosis" ? (
          <div className="space-y-3">
            <BobaIncidentOverview reference={reference} snapshot={snapshot} />
            <BobaDiagnosisReview projections={diagnoses} />
            <BobaErrorDoctorActionBar
              descriptors={descriptors}
              snapshot={snapshot}
              confirmations={confirmations}
              receipt={receipt}
              message={actionMessage}
              onSelect={setPending}
            />
            <BobaErrorDoctorActionDialog
              descriptor={pending}
              snapshot={snapshot}
              confirmations={confirmations}
              incidentId={selectedIncidentId ?? ""}
              submitting={submitAction.isPending || createAction.isPending}
              onCancel={() => setPending(null)}
              onConfirm={confirmAction}
            />
            <BobaErrorDoctorAnnotations
              annotations={annotations}
              incidentId={selectedIncidentId ?? "unknown"}
              onAdd={(annotation) => {
                const next = upsertAnnotation(annotations, annotation);
                setAnnotations(next);
                if (sessionId) {
                  updateSession.mutate({
                    sessionId,
                    updates: { local_annotations: next },
                  });
                }
              }}
              onRemove={(annotationId) => {
                const next = removeAnnotation(annotations, annotationId);
                setAnnotations(next);
                if (sessionId) {
                  updateSession.mutate({
                    sessionId,
                    updates: { local_annotations: next },
                  });
                }
              }}
            />
          </div>
        ) : null}

        {tab === "root_cause" ? <BobaRootCauseReview projections={rootCauses} /> : null}
        {tab === "repair" ? <BobaRepairPlanReview projections={repairPlans} /> : null}
        {tab === "recovery" ? <BobaRecoveryHistory attempts={attempts} /> : null}

        {tab === "evidence" ? (
          <div className="space-y-4">
            <label className="flex items-center gap-1.5 text-xs text-white/60">
              <input
                type="checkbox"
                checked={showBoundedLogs}
                onChange={(event) => setShowBoundedLogs(event.target.checked)}
              />
              Show bounded excerpts
            </label>
            <BobaErrorEvidence cards={cards} showBoundedLogs={showBoundedLogs} />
            <BobaIncidentConflicts conflicts={conflicts} />
          </div>
        ) : null}

        {tab === "events" ? (
          <p className="text-sm text-white/60">
            Canonical events are projected through the existing Review UI event stream.
            The panel opens no second stream and never invents progress.
          </p>
        ) : null}
      </div>

      <footer className="mt-4 space-y-0.5 border-t border-white/10 pt-3 text-[11px] text-white/40">
        <p>
          This panel does not diagnose, determine root causes, create repair plans or
          execute repairs, recovery, checkpoint restoration or workflow changes.
        </p>
        <p>
          A hypothesis is not a fact, owner-reported recovery success is not independent
          verification, and recovered is not resolved.
        </p>
      </footer>
    </section>
  );
}
