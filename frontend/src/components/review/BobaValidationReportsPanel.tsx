"use client";

/**
 * BOBA Validation + Reports V1 panel.
 *
 * Presentation only. This panel renders the backend projection and holds no
 * authority: it derives no verdict, resolves no conflict, selects no "best"
 * result, performs no optimistic mutation and never displays a success state
 * that the owner did not record. Missing evidence is shown as missing.
 */

import { Component, type ReactNode, useState } from "react";

import {
  buildStateRows,
  cellsWithoutVerdict,
  headlineFor,
  orderCells,
  orderConflicts,
  orderReportCards,
  parseConflict,
  parseEvidence,
  parseFinding,
  parseMatrix,
  parseReportCard,
  parseSummary,
  reportProblemLabels,
  shortDigest,
  staleDimensionLabels,
  stateGlyph,
  stateLabel,
  stateTone,
  type MatrixState,
  type ValidationConflict,
  type ValidationEvidenceRef,
  type ValidationMatrixCell,
  type ValidationReportCard,
  type ValidationReportFinding,
  type ValidationSummary,
} from "@/lib/validationReports";
import {
  useBobaValidationConflicts,
  useBobaValidationEvidence,
  useBobaValidationMatrix,
  useBobaValidationReportCards,
  useBobaValidationReportDetail,
  useBobaValidationSummary,
} from "@/lib/queries";

function words(value: string): string {
  return value ? value.replace(/_/g, " ") : "Not available";
}

export class BobaValidationReportsErrorBoundary extends Component<
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
          <p className="font-medium">
            The validation and reports panel could not be displayed.
          </p>
          <p className="mt-1 text-xs text-rose-100/80">
            No validation ran and no report changed. Reload the page to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.02] p-3 sm:p-4">
      <header className="mb-3">
        <h3 className="text-sm font-medium text-white/90">{title}</h3>
        {description ? (
          <p className="mt-1 text-xs text-white/60">{description}</p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

function NoticeList({ notices }: { notices: string[] }) {
  if (notices.length === 0) return null;
  return (
    <ul className="mt-3 space-y-1 text-xs text-white/55">
      {notices.map((notice) => (
        <li key={notice}>{notice}</li>
      ))}
    </ul>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <p className="rounded-md border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60">
      {message}
    </p>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <p role="status" aria-live="polite" className="text-xs text-white/60">
      {label}
    </p>
  );
}

function ErrorState({ label }: { label: string }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-rose-300/30 bg-rose-300/[0.06] p-3 text-xs text-rose-100"
    >
      {label}
    </p>
  );
}

/** The seven-state count strip. All seven are always rendered. */
export function BobaValidationStateStrip({
  counts,
}: {
  counts: Record<string, number>;
}) {
  const rows = buildStateRows(counts);
  return (
    <ul
      className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7"
      aria-label="Validation state totals"
    >
      {rows.map((row) => (
        <li
          key={row.state}
          className={`rounded-md border p-2 text-center ${row.tone}`}
        >
          <span aria-hidden className="block text-base leading-none">
            {row.glyph}
          </span>
          <span className="mt-1 block text-lg font-semibold tabular-nums">
            {row.total}
          </span>
          <span className="block text-[11px] uppercase tracking-wide opacity-80">
            {row.label}
          </span>
          {!row.verdictBearing && row.total > 0 ? (
            <span className="mt-0.5 block text-[10px] opacity-70">no verdict</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function BobaValidationSummaryCard({
  summary,
  conflictCount,
}: {
  summary: ValidationSummary;
  conflictCount: number;
}) {
  const staleLabels = staleDimensionLabels(summary.binding);
  return (
    <article className="rounded-lg border border-white/10 bg-white/[0.02] p-3 sm:p-4">
      <h4 className="text-sm font-medium text-white/90">
        {headlineFor(summary, conflictCount)}
      </h4>
      <dl className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <dt className="text-white/50">Owner suite decision</dt>
          <dd className="text-white/85">{words(summary.suite_decision)}</dd>
        </div>
        <div>
          <dt className="text-white/50">Run status</dt>
          <dd className="text-white/85">{words(summary.run_status)}</dd>
        </div>
        <div>
          <dt className="text-white/50">Validation run</dt>
          <dd className="font-mono text-white/70">
            {summary.validation_run_id || "Not available"}
          </dd>
        </div>
        <div>
          <dt className="text-white/50">Technical validation (owner fact)</dt>
          <dd className="text-white/85">
            {summary.technical_validation_passed ? "Passed" : "Not passed"}
          </dd>
        </div>
        <div>
          <dt className="text-white/50">Evidence</dt>
          <dd className="text-white/85">
            {summary.evidence_missing ? "Incomplete" : "Complete"}
          </dd>
        </div>
        <div>
          <dt className="text-white/50">Workflow revision</dt>
          <dd className="text-white/85 tabular-nums">
            {summary.binding.workflow_revision}
          </dd>
        </div>
      </dl>

      {staleLabels.length > 0 ? (
        <p className="mt-3 rounded-md border border-amber-300/30 bg-amber-300/[0.06] p-2 text-xs text-amber-100">
          <span className="font-medium">Stale binding.</span> These bound
          dimensions changed, so earlier verdicts cannot be reused:{" "}
          {staleLabels.join(", ")}.
        </p>
      ) : null}

      <p className="mt-3 rounded-md border border-white/10 bg-white/[0.02] p-2 text-[11px] text-white/60">
        Passing technical validation does not mean production ready, quality
        accepted, rights cleared, or approved for upload or publication. Those
        remain with their own owners.
      </p>

      <NoticeList notices={summary.warnings} />
    </article>
  );
}

function CellRow({ cell }: { cell: ValidationMatrixCell }) {
  return (
    <li className={`rounded-md border p-2 ${stateTone(cell.derived_state)}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-xs font-medium">
          <span aria-hidden className="mr-1">
            {stateGlyph(cell.derived_state)}
          </span>
          {cell.validator_id || "Unknown validator"}
          {cell.required ? "" : " (optional)"}
        </span>
        <span className="text-[11px] uppercase tracking-wide opacity-80">
          {stateLabel(cell.derived_state)}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-1 text-[11px] sm:grid-cols-2">
        <div>
          <dt className="inline opacity-70">Owner status: </dt>
          <dd className="inline font-mono">{cell.owner_status}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Validator version: </dt>
          <dd className="inline font-mono">{cell.validator_version || "unknown"}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Verdict: </dt>
          <dd className="inline">
            {cell.verdict_available ? "Available" : "None recorded"}
          </dd>
        </div>
        <div>
          <dt className="inline opacity-70">Evidence: </dt>
          <dd className="inline">{cell.evidence_present ? "Present" : "Absent"}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Result digest: </dt>
          <dd className="inline font-mono">{shortDigest(cell.result_digest)}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Completed: </dt>
          <dd className="inline">{cell.completed_at || "Not available"}</dd>
        </div>
      </dl>
      <p className="mt-2 text-[11px] opacity-80">{cell.derived_state_reason}</p>
      {cell.owner_reported_state !== cell.derived_state ? (
        <p className="mt-1 text-[11px] opacity-80">
          Owner-reported presentation was{" "}
          <strong>{stateLabel(cell.owner_reported_state)}</strong>; it is shown as{" "}
          <strong>{stateLabel(cell.derived_state)}</strong> here.
        </p>
      ) : null}
      {cell.failure_categories.length > 0 ? (
        <p className="mt-1 text-[11px] opacity-80">
          Failure categories: {cell.failure_categories.map(words).join(", ")}
        </p>
      ) : null}
      {cell.bounded_diagnostics.length > 0 ? (
        <ul className="mt-1 space-y-0.5 text-[11px] opacity-80">
          {cell.bounded_diagnostics.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function BobaValidationMatrixTable({
  cells,
}: {
  cells: ValidationMatrixCell[];
}) {
  const ordered = orderCells(cells);
  if (ordered.length === 0) {
    return (
      <EmptyState message="No validation checks exist for this project yet. Nothing is reported as passing." />
    );
  }
  const withoutVerdict = cellsWithoutVerdict(ordered);
  return (
    <>
      <ul className="space-y-2" aria-label="Validation status matrix">
        {ordered.map((cell) => (
          <CellRow key={cell.cell_id} cell={cell} />
        ))}
      </ul>
      {withoutVerdict.length > 0 ? (
        <p className="mt-3 text-[11px] text-white/60">
          {withoutVerdict.length} of {ordered.length} check(s) carry no validation
          verdict. They are not counted as passing.
        </p>
      ) : null}
    </>
  );
}

export function BobaValidationReportCardView({
  card,
  onSelect,
  selected,
}: {
  card: ValidationReportCard;
  onSelect: (id: string) => void;
  selected: boolean;
}) {
  const problems = reportProblemLabels(card);
  return (
    <article
      className={`rounded-md border p-3 ${
        problems.length > 0
          ? "border-amber-300/30 bg-amber-300/[0.06] text-amber-100"
          : "border-white/10 bg-white/[0.02] text-white/80"
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-xs font-medium">{card.derived_title}</h4>
        <span className="text-[11px] uppercase tracking-wide opacity-80">
          {card.derived_status_label}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-1 text-[11px] sm:grid-cols-2">
        <div>
          <dt className="inline opacity-70">Source module: </dt>
          <dd className="inline">{words(card.source_module_id)}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Report type: </dt>
          <dd className="inline">{words(card.report_type)}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Content digest: </dt>
          <dd className="inline font-mono">{shortDigest(card.content_digest)}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Integrity: </dt>
          <dd className="inline">
            {card.integrity_verified ? "Digest verified" : "Not verified"}
          </dd>
        </div>
        <div>
          <dt className="inline opacity-70">Findings: </dt>
          <dd className="inline tabular-nums">{card.finding_count}</dd>
        </div>
        <div>
          <dt className="inline opacity-70">Generated: </dt>
          <dd className="inline">{card.generated_at || "Not available"}</dd>
        </div>
      </dl>
      {problems.length > 0 ? (
        <p className="mt-2 text-[11px]">Problems: {problems.join(", ")}</p>
      ) : null}
      {card.lineage_read_run_id ? (
        <p className="mt-1 text-[11px] opacity-75">
          Lineage: {words(card.lineage_producer_module_id)} → read run{" "}
          <span className="font-mono">{card.lineage_read_run_id}</span>
        </p>
      ) : null}
      <button
        type="button"
        onClick={() => onSelect(card.report_document_id)}
        aria-pressed={selected}
        className="mt-2 rounded-md border border-white/15 px-2 py-1 text-[11px] text-white/80 hover:bg-white/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/60"
      >
        {selected ? "Hide report details" : "View report details"}
      </button>
    </article>
  );
}

export function BobaValidationFindingList({
  findings,
}: {
  findings: ValidationReportFinding[];
}) {
  if (findings.length === 0) {
    return <EmptyState message="This report recorded no findings." />;
  }
  return (
    <ul className="space-y-2">
      {findings.map((finding) => (
        <li
          key={finding.finding_id}
          className="rounded-md border border-white/10 bg-white/[0.02] p-2 text-[11px] text-white/80"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-medium text-white/90">
              {finding.derived_title || finding.title}
            </span>
            <span className="uppercase tracking-wide opacity-80">
              {finding.derived_severity_label}
            </span>
          </div>
          <p className="mt-1 opacity-85">{finding.bounded_summary}</p>
          <p className="mt-1 opacity-70">
            Owner: {words(finding.producer_module_id)} · domain{" "}
            {words(finding.authority_domain)}
            {finding.source_status ? ` · status ${words(finding.source_status)}` : ""}
            {finding.stale ? " · stale" : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function BobaValidationEvidenceList({
  evidence,
}: {
  evidence: ValidationEvidenceRef[];
}) {
  if (evidence.length === 0) {
    return (
      <EmptyState message="No evidence references are available. Absent evidence is not treated as a pass." />
    );
  }
  return (
    <ul className="space-y-2">
      {evidence.map((row) => (
        <li
          key={row.evidence_ref_id}
          className="rounded-md border border-white/10 bg-white/[0.02] p-2 text-[11px] text-white/80"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-medium text-white/90">
              {row.validator_id || row.source_type || "Evidence reference"}
            </span>
            <span className="uppercase tracking-wide opacity-80">
              {row.derived_availability_label}
            </span>
          </div>
          {row.bounded_summary ? (
            <p className="mt-1 opacity-85">{row.bounded_summary}</p>
          ) : null}
          <p className="mt-1 opacity-70">
            Origin {words(row.origin)} · reliability {words(row.reliability)} ·
            digest <span className="font-mono">{shortDigest(row.evidence_digest)}</span>
            {row.supports_pass ? " · supports pass" : ""}
            {row.supports_failure ? " · supports failure" : ""}
            {row.stale ? " · stale" : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function BobaValidationConflictList({
  conflicts,
}: {
  conflicts: ValidationConflict[];
}) {
  const ordered = orderConflicts(conflicts);
  if (ordered.length === 0) {
    return <EmptyState message="No conflicts were detected between validators or reports." />;
  }
  return (
    <ul className="space-y-2" aria-label="Validation conflicts">
      {ordered.map((conflict) => (
        <li
          key={conflict.conflict_id}
          className="rounded-md border border-amber-300/30 bg-amber-300/[0.06] p-2 text-[11px] text-amber-100"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-medium">{words(conflict.conflict_kind)}</span>
            <span className="uppercase tracking-wide opacity-80">unresolved</span>
          </div>
          <p className="mt-1 opacity-90">{conflict.bounded_summary}</p>
          <ul className="mt-1 space-y-0.5">
            {conflict.participants.map((participant) => (
              <li key={participant.participant_id} className="opacity-85">
                {words(participant.source_module_id)} ·{" "}
                {words(participant.record_kind)}{" "}
                <span className="font-mono">{participant.record_id}</span> reported{" "}
                <strong>{participant.reported_value || "not available"}</strong>
              </li>
            ))}
          </ul>
          <p className="mt-1 opacity-75">
            Both values are preserved. No result was selected as best, merged or
            averaged, and no root cause or repair is inferred.
          </p>
        </li>
      ))}
    </ul>
  );
}

function ReportDetail({
  projectId,
  documentId,
}: {
  projectId: string;
  documentId: string;
}) {
  const detail = useBobaValidationReportDetail(projectId, documentId);
  if (detail.isPending) return <LoadingState label="Loading report details…" />;
  if (detail.isError) {
    return <ErrorState label="The report details could not be loaded." />;
  }
  const payload = detail.data ?? {};
  const findings = Array.isArray(payload.findings)
    ? payload.findings.map(parseFinding)
    : [];
  const evidence = Array.isArray(payload.evidence)
    ? payload.evidence.map(parseEvidence)
    : [];
  const failures = Array.isArray(payload.failures) ? payload.failures.length : 0;
  return (
    <div className="mt-2 space-y-3 rounded-md border border-white/10 bg-white/[0.01] p-3">
      <p className="text-[11px] text-white/60">
        {failures} high-severity finding(s). Report bodies remain owned by the
        Report Reader and are not stored here.
      </p>
      <div>
        <h5 className="mb-1 text-xs font-medium text-white/85">Findings</h5>
        <BobaValidationFindingList findings={findings} />
      </div>
      <div>
        <h5 className="mb-1 text-xs font-medium text-white/85">Evidence</h5>
        <BobaValidationEvidenceList evidence={evidence} />
      </div>
    </div>
  );
}

export function BobaValidationReportsPanel({ projectId }: { projectId: string }) {
  const [selectedReport, setSelectedReport] = useState("");
  const summaryQuery = useBobaValidationSummary(projectId);
  const matrixQuery = useBobaValidationMatrix(projectId);
  const reportsQuery = useBobaValidationReportCards(projectId);
  const evidenceQuery = useBobaValidationEvidence(projectId);
  const conflictsQuery = useBobaValidationConflicts(projectId);

  const conflicts = Array.isArray(conflictsQuery.data?.conflicts)
    ? conflictsQuery.data.conflicts.map(parseConflict)
    : [];
  const cards = Array.isArray(reportsQuery.data?.report_cards)
    ? orderReportCards(reportsQuery.data.report_cards.map(parseReportCard))
    : [];
  const evidence = Array.isArray(evidenceQuery.data?.evidence)
    ? evidenceQuery.data.evidence.map(parseEvidence)
    : [];

  const anyError =
    summaryQuery.isError ||
    matrixQuery.isError ||
    reportsQuery.isError ||
    conflictsQuery.isError;

  return (
    <BobaValidationReportsErrorBoundary>
      <div className="space-y-3 sm:space-y-4">
        <header>
          <h2 className="text-base font-semibold text-white/90">
            Validation and reports
          </h2>
          <p className="mt-1 text-xs text-white/60">
            A read-only projection of Validator Runner verdicts and Report Reader
            reports. Nothing here runs a validator, approves anything or changes a
            workflow.
          </p>
        </header>

        {anyError ? (
          <ErrorState label="Some validation or report data could not be loaded. Nothing is reported as passing while data is unavailable." />
        ) : null}

        <Section
          title="Validation summary"
          description="Owner facts first, presentation second."
        >
          {summaryQuery.isPending ? (
            <LoadingState label="Loading validation summary…" />
          ) : summaryQuery.isError ? (
            <ErrorState label="The validation summary could not be loaded." />
          ) : (
            <BobaValidationSummaryCard
              summary={parseSummary(summaryQuery.data)}
              conflictCount={conflicts.length}
            />
          )}
        </Section>

        <Section
          title="Validation status matrix"
          description="Seven distinct states. Pass, fail, blocked, skipped, not run, stale and missing are never collapsed together."
        >
          {matrixQuery.isPending ? (
            <LoadingState label="Loading validation matrix…" />
          ) : matrixQuery.isError ? (
            <ErrorState label="The validation matrix could not be loaded." />
          ) : (
            (() => {
              const matrix = parseMatrix(matrixQuery.data);
              return (
                <div className="space-y-3">
                  <BobaValidationStateStrip counts={matrix.state_counts} />
                  <BobaValidationMatrixTable cells={matrix.cells} />
                  {matrix.truncated ? (
                    <p className="text-[11px] text-white/60">
                      Output is bounded; only the first {matrix.cells.length} of{" "}
                      {matrix.total_cells} checks are shown.
                    </p>
                  ) : null}
                  <NoticeList notices={matrix.warnings} />
                </div>
              );
            })()
          )}
        </Section>

        <Section
          title="Reports"
          description="Report bodies stay owned by the Report Reader; only references, digests and bounded summaries appear here."
        >
          {reportsQuery.isPending ? (
            <LoadingState label="Loading reports…" />
          ) : reportsQuery.isError ? (
            <ErrorState label="The reports could not be loaded." />
          ) : cards.length === 0 ? (
            <EmptyState message="No reports have been read for this project yet." />
          ) : (
            <ul className="space-y-2">
              {cards.map((card) => (
                <li key={card.report_card_id}>
                  <BobaValidationReportCardView
                    card={card}
                    selected={selectedReport === card.report_document_id}
                    onSelect={(id) =>
                      setSelectedReport((current) => (current === id ? "" : id))
                    }
                  />
                  {selectedReport === card.report_document_id ? (
                    <ReportDetail
                      projectId={projectId}
                      documentId={card.report_document_id}
                    />
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          title="Evidence"
          description="Evidence is referenced, never copied. Absent evidence is never a pass."
        >
          {evidenceQuery.isPending ? (
            <LoadingState label="Loading evidence…" />
          ) : evidenceQuery.isError ? (
            <ErrorState label="The evidence references could not be loaded." />
          ) : (
            <BobaValidationEvidenceList evidence={evidence} />
          )}
        </Section>

        <Section
          title="Conflicts"
          description="Contradictions are named and preserved, never resolved automatically."
        >
          {conflictsQuery.isPending ? (
            <LoadingState label="Loading conflicts…" />
          ) : conflictsQuery.isError ? (
            <ErrorState label="The conflicts could not be loaded." />
          ) : (
            <BobaValidationConflictList conflicts={conflicts} />
          )}
        </Section>
      </div>
    </BobaValidationReportsErrorBoundary>
  );
}

export type { MatrixState };
