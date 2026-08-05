"use client";

/**
 * Source-owned status matrix.
 *
 * One row per authority domain. Every row names the owning module and shows that
 * module's original status and decision verbatim. The Review UI never merges,
 * overrides or re-derives a source-owned decision, and a missing record is shown
 * as unavailable rather than as a pass.
 */

import {
  buildStatusMatrix,
  stateGlyph,
  stateLabel,
  type ReviewSourceCard,
  type StatusMatrixRow,
} from "@/lib/reviewUi";

function words(value: string | undefined) {
  return value ? value.replace(/_/g, " ") : "Not available";
}

function rowTone(row: StatusMatrixRow) {
  if (row.blocking) return "border-rose-300/30 bg-rose-300/[0.06] text-rose-100";
  if (row.humanActionRequired) return "border-amber-300/30 bg-amber-300/[0.06] text-amber-100";
  if (row.state === "unavailable") return "border-white/10 bg-white/[0.02] text-white/60";
  if (row.state !== "current") return "border-sky-300/30 bg-sky-300/[0.06] text-sky-100";
  return "border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-100";
}

export function BobaReviewSourceCard({ card }: { card: ReviewSourceCard }) {
  return (
    <article
      className="rounded-lg border border-white/10 bg-white/[0.02] p-3"
      aria-labelledby={`source-card-${card.source_card_id}`}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 id={`source-card-${card.source_card_id}`} className="text-sm font-medium text-white/90">
          {card.title}
        </h4>
        <span className="font-mono text-[11px] text-white/50">{card.source_module_id}</span>
      </header>
      <dl className="mt-2 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-white/50">Original status</dt>
          <dd className="text-white/85">{words(card.original_status)}</dd>
        </div>
        <div>
          <dt className="text-white/50">Original decision</dt>
          <dd className="text-white/85">{words(card.original_decision ?? undefined)}</dd>
        </div>
        <div>
          <dt className="text-white/50">Record</dt>
          <dd className="truncate font-mono text-white/70">{card.source_record_id}</dd>
        </div>
        <div>
          <dt className="text-white/50">Owner authority</dt>
          <dd className="text-white/70">This module owns the decision.</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-white/70">{card.bounded_summary}</p>
      {card.warnings.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-amber-100/90">
          {card.warnings.map((warning) => (
            <li key={warning}>Warning: {warning}</li>
          ))}
        </ul>
      )}
      {card.limitations.length > 0 && (
        <ul className="mt-1 space-y-1 text-xs text-white/55">
          {card.limitations.map((limitation) => (
            <li key={limitation}>Limitation: {limitation}</li>
          ))}
        </ul>
      )}
    </article>
  );
}

export function BobaReviewStatusMatrix({
  cards,
  onOpenEvidence,
}: {
  cards: ReviewSourceCard[];
  onOpenEvidence?: (sourceModule: string) => void;
}) {
  const rows = buildStatusMatrix(cards);
  return (
    <section aria-labelledby="review-status-matrix-heading" className="space-y-3">
      <h3 id="review-status-matrix-heading" className="text-sm font-semibold text-white/90">
        SOURCE-OWNED STATUS
      </h3>
      <p className="text-xs text-white/60">
        Each row is owned by the module named in it. The review workspace displays these
        decisions; it does not create or change them.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[46rem] border-collapse text-left text-xs">
          <caption className="sr-only">
            Source-owned authority status by domain, including original status, current state,
            blocking state and required human action.
          </caption>
          <thead>
            <tr className="text-white/55">
              <th scope="col" className="px-2 py-1 font-medium">
                Domain
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                Source module
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                Original status
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                Original decision
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                State
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                Blocking
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                Human action
              </th>
              <th scope="col" className="px-2 py-1 font-medium">
                Details
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-t border-white/5 align-top">
                <th scope="row" className="px-2 py-2 font-medium text-white/85">
                  {row.label}
                </th>
                <td className="px-2 py-2 font-mono text-[11px] text-white/60">{row.sourceModule}</td>
                <td className="px-2 py-2 text-white/80">{words(row.originalStatus)}</td>
                <td className="px-2 py-2 text-white/80">{words(row.originalDecision)}</td>
                <td className="px-2 py-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 ${rowTone(row)}`}
                  >
                    <span aria-hidden="true" className="font-mono text-[10px]">
                      {stateGlyph(row.state)}
                    </span>
                    <span>{stateLabel(row.state)}</span>
                  </span>
                </td>
                <td className="px-2 py-2 text-white/80">{row.blocking ? "Blocking" : "Not blocking"}</td>
                <td className="px-2 py-2 text-white/80">
                  {row.humanActionRequired ? "Required" : "Not required"}
                </td>
                <td className="px-2 py-2 text-white/70">
                  <span>{row.details}</span>
                  {onOpenEvidence && (
                    <button
                      type="button"
                      onClick={() => onOpenEvidence(row.sourceModule)}
                      className="mt-1 block min-h-[44px] rounded text-left text-[11px] text-sky-200 underline underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 sm:min-h-0"
                    >
                      Open evidence for {row.label}
                    </button>
                  )}
                  {row.warnings.length > 0 && (
                    <ul className="mt-1 space-y-0.5 text-[11px] text-amber-100/90">
                      {row.warnings.slice(0, 3).map((warning) => (
                        <li key={warning}>Warning: {warning}</li>
                      ))}
                    </ul>
                  )}
                  {row.limitations.length > 0 && (
                    <ul className="mt-0.5 space-y-0.5 text-[11px] text-white/50">
                      {row.limitations.slice(0, 3).map((limitation) => (
                        <li key={limitation}>Limitation: {limitation}</li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
