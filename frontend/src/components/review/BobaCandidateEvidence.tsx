"use client";

/**
 * Score breakdown, transcript, evidence and comparison presentation.
 *
 * Scores keep their owner, scale, definition and direction. Transcript text is
 * reproduced verbatim and context is labelled as context. Comparison never
 * nominates a winner.
 */

import {
  describeScore,
  formatDuration,
  formatSourceWindow,
  overlapDescription,
  overlapLabel,
  type CandidateOverlapRecord,
  type CandidateQueueItem,
  type CandidateScoreCard,
} from "@/lib/candidateReview";

export function BobaCandidateScoreBreakdown({ cards }: { cards: CandidateScoreCard[] }) {
  const byModule = cards.reduce<Record<string, CandidateScoreCard[]>>((acc, card) => {
    acc[card.source_module_id] = [...(acc[card.source_module_id] ?? []), card];
    return acc;
  }, {});
  return (
    <section aria-labelledby="candidate-scores-heading" className="space-y-3">
      <h3 id="candidate-scores-heading" className="text-sm font-semibold text-white/90">
        SOURCE-OWNED SCORES
      </h3>
      <p className="text-xs text-white/60">
        Each score keeps the owner, scale and definition it was persisted with. The
        panel does not recompute, rescale or combine scores, and no score is a
        virality or performance prediction.
      </p>
      {cards.length === 0 && (
        <p className="text-xs text-white/55">No source-owned score is available.</p>
      )}
      {Object.entries(byModule).map(([moduleId, moduleCards]) => (
        <div key={moduleId} className="space-y-1">
          <h4 className="font-mono text-[11px] text-white/55">{moduleId}</h4>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-left text-xs">
              <caption className="sr-only">
                Scores owned by {moduleId}, with value, scale, direction and definition.
              </caption>
              <thead>
                <tr className="text-white/55">
                  <th scope="col" className="px-2 py-1 font-medium">Score</th>
                  <th scope="col" className="px-2 py-1 font-medium">Value</th>
                  <th scope="col" className="px-2 py-1 font-medium">Scale</th>
                  <th scope="col" className="px-2 py-1 font-medium">Direction</th>
                  <th scope="col" className="px-2 py-1 font-medium">Rank</th>
                  <th scope="col" className="px-2 py-1 font-medium">Definition</th>
                </tr>
              </thead>
              <tbody>
                {moduleCards.map((card) => (
                  <tr key={card.score_card_id} className="border-t border-white/5 align-top">
                    <th scope="row" className="px-2 py-1.5 font-medium text-white/85">
                      {card.score_name.replace(/_/g, " ")}
                      {card.source_owned_composite && (
                        <span className="ml-1 text-[10px] text-sky-200">
                          (owner composite)
                        </span>
                      )}
                    </th>
                    <td className="px-2 py-1.5 font-mono text-white/85">{card.score_value}</td>
                    <td className="px-2 py-1.5 text-white/70">
                      {card.score_scale_min}–{card.score_scale_max}
                    </td>
                    <td className="px-2 py-1.5 text-white/70">
                      {card.score_direction === "lower_is_better"
                        ? "Lower is better"
                        : card.score_direction === "higher_is_better"
                          ? "Higher is better"
                          : "Not stated"}
                    </td>
                    <td className="px-2 py-1.5 text-white/70">
                      {card.rank === null ? "—" : `#${card.rank}`}
                      {card.tied && <span className="ml-1 text-amber-100">tied</span>}
                    </td>
                    <td className="px-2 py-1.5 text-white/65">
                      {card.score_definition}
                      <span className="sr-only">{describeScore(card)}</span>
                      {card.weight === null && (
                        <span className="mt-0.5 block text-[10px] text-white/45">
                          No weight is persisted by the owner, so none is shown.
                        </span>
                      )}
                      {!card.comparable_across_candidates && (
                        <span className="mt-0.5 block text-[10px] text-amber-100/80">
                          Not directly comparable with other modules&rsquo; scores.
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </section>
  );
}

export function BobaCandidateTranscript({
  snippets,
  segmentIds,
  candidateStart,
  candidateEnd,
  contextStart,
  contextEnd,
  contextSeconds,
  onContextChange,
  sourceModuleId,
}: {
  snippets: string[];
  segmentIds: string[];
  candidateStart: number;
  candidateEnd: number;
  contextStart: number;
  contextEnd: number;
  contextSeconds: number;
  onContextChange: (value: number) => void;
  sourceModuleId: string;
}) {
  return (
    <section aria-labelledby="candidate-transcript-heading" className="space-y-2">
      <h3 id="candidate-transcript-heading" className="text-sm font-semibold text-white/90">
        TRANSCRIPT
      </h3>
      <div>
        <label htmlFor="transcript-context" className="block text-xs text-white/60">
          Context before and after (seconds)
        </label>
        <input
          id="transcript-context"
          type="range"
          min={0}
          max={60}
          step={5}
          value={contextSeconds}
          onChange={(event) => onContextChange(Number(event.target.value))}
          className="mt-1 w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        />
        <p className="text-[11px] text-white/45">
          Context {contextSeconds}s · {formatSourceWindow(contextStart, contextEnd)}. This does
          not change the candidate boundaries.
        </p>
      </div>

      <h4 className="text-xs font-medium text-white/80">
        Candidate transcript · {formatSourceWindow(candidateStart, candidateEnd)}
      </h4>
      {snippets.length === 0 ? (
        <p className="text-xs text-white/55">
          No transcript snippet is persisted on this candidate record.
        </p>
      ) : (
        <ul className="space-y-1">
          {snippets.map((snippet, index) => (
            <li
              key={`${index}-${snippet.slice(0, 12)}`}
              className="rounded border border-white/10 bg-white/[0.02] p-2 text-xs text-white/80"
            >
              {snippet}
            </li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-white/45">
        Reproduced verbatim from <span className="font-mono">{sourceModuleId}</span>.
        {segmentIds.length > 0 && ` Segment references: ${segmentIds.join(", ")}.`}
      </p>
      <p className="text-[11px] text-white/45">
        Speaker references stay opaque. The panel never identifies people from audio
        or video frames.
      </p>
    </section>
  );
}

export function BobaCandidateComparison({
  items,
  overlaps,
  onClear,
}: {
  items: CandidateQueueItem[];
  overlaps: CandidateOverlapRecord[];
  onClear: () => void;
}) {
  if (items.length < 2) {
    return (
      <section aria-labelledby="candidate-comparison-heading" className="space-y-2">
        <h3 id="candidate-comparison-heading" className="text-sm font-semibold text-white/90">
          COMPARISON
        </h3>
        <p className="text-xs text-white/55">
          Select two to four candidates to compare them side by side.
        </p>
      </section>
    );
  }
  return (
    <section aria-labelledby="candidate-comparison-heading" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 id="candidate-comparison-heading" className="text-sm font-semibold text-white/90">
          COMPARISON
        </h3>
        <button
          type="button"
          onClick={onClear}
          className="min-h-[44px] rounded px-2 text-xs text-sky-200 underline underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 sm:min-h-0"
        >
          Clear comparison
        </button>
      </div>
      <p className="text-xs text-white/60">
        No winner is chosen. Scores from different modules use different scales.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] border-collapse text-left text-xs">
          <caption className="sr-only">
            Side-by-side comparison of the selected candidates. No winner is chosen.
          </caption>
          <thead>
            <tr className="text-white/55">
              <th scope="col" className="px-2 py-1 font-medium">Field</th>
              {items.map((item) => (
                <th key={item.candidate_id} scope="col" className="px-2 py-1 font-medium">
                  {item.candidate_id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[
              ["Source window", (i: CandidateQueueItem) => formatSourceWindow(i.start_seconds, i.end_seconds)],
              ["Duration", (i: CandidateQueueItem) => formatDuration(i.duration_seconds)],
              ["Discovery reason", (i: CandidateQueueItem) => i.bounded_summary || "—"],
              [
                "Original rank",
                (i: CandidateQueueItem) =>
                  i.original_rank === null ? "Not ranked" : `#${i.original_rank}`,
              ],
              [
                "Primary source score",
                (i: CandidateQueueItem) =>
                  i.primary_score === null
                    ? "Not available"
                    : `${i.primary_score_name} ${i.primary_score} (${i.primary_score_owner_module_id})`,
              ],
              ["Editorial status", (i: CandidateQueueItem) => i.editorial_status],
              [
                "Evidence",
                (i: CandidateQueueItem) =>
                  i.missing_evidence_count === 0
                    ? "Complete"
                    : `${i.missing_evidence_count} missing`,
              ],
              ["Warnings", (i: CandidateQueueItem) => String(i.warning_count)],
            ].map(([label, accessor]) => (
              <tr key={String(label)} className="border-t border-white/5 align-top">
                <th scope="row" className="px-2 py-1.5 font-medium text-white/80">
                  {String(label)}
                </th>
                {items.map((item) => (
                  <td key={item.candidate_id} className="px-2 py-1.5 text-white/75">
                    {(accessor as (i: CandidateQueueItem) => string)(item)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {overlaps.length > 0 && (
        <ul className="space-y-1">
          {overlaps.map((record) => (
            <li key={record.overlap_record_id} className="text-[11px] text-amber-100/90">
              {record.candidate_a_id} / {record.candidate_b_id}: {overlapLabel(record)} —{" "}
              {overlapDescription(record)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function BobaCandidateEvidence({
  sourceCards,
}: {
  sourceCards: Record<string, unknown>[];
}) {
  return (
    <section aria-labelledby="candidate-evidence-heading" className="space-y-2">
      <h3 id="candidate-evidence-heading" className="text-sm font-semibold text-white/90">
        SOURCE EVIDENCE
      </h3>
      <p className="text-xs text-white/60">
        Each card is owned by the module named in it. Advisory modules are labelled.
      </p>
      {sourceCards.length === 0 && (
        <p className="text-xs text-white/55">No canonical evidence is available.</p>
      )}
      <ul className="space-y-2">
        {sourceCards.map((card) => {
          const moduleId = String(card.source_module_id ?? "unknown");
          const status = String(card.original_status ?? "unknown");
          const advisory = Boolean(card.advisory_only);
          return (
            <li
              key={String(card.source_card_id)}
              className="rounded border border-white/10 bg-white/[0.02] p-2 text-xs"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium text-white/85">{String(card.title ?? moduleId)}</span>
                <span className="font-mono text-[10px] text-white/45">{moduleId}</span>
              </div>
              <p className="mt-1 text-white/70">
                Original status: {status.replace(/_/g, " ")}
                {card.original_rank ? ` · rank #${String(card.original_rank)}` : ""}
              </p>
              <p className="mt-0.5 text-white/65">{String(card.bounded_summary ?? "")}</p>
              <p className="mt-0.5 text-[10px] text-white/45">
                {advisory ? "Advisory only — not a decision." : "Authoritative owner record."}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
