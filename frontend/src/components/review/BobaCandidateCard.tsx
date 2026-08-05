"use client";

/**
 * Candidate card, queue and overlap badge.
 *
 * Every number shown here is copied from the module that owns it. Rank and score
 * always name their owner, and status is conveyed by text and glyph, never by
 * colour alone.
 */

import { useRef } from "react";

import {
  LOCAL_SHORTLIST_NOTICE,
  MAX_COMPARISON_CANDIDATES,
  candidateStateGlyph,
  candidateStateLabel,
  describeRank,
  editorialStatusLabel,
  evidenceSummary,
  filterCandidates,
  formatDuration,
  formatSourceWindow,
  overlapDescription,
  overlapLabel,
  sortCandidates,
  type CandidateOverlapRecord,
  type CandidateQueueItem,
  type CandidateReviewFilter,
  type CandidateReviewSort,
} from "@/lib/candidateReview";

const FILTERS: { id: CandidateReviewFilter; label: string }[] = [
  { id: "all_current", label: "All current" },
  { id: "human_review_required", label: "Human review required" },
  { id: "source_shortlisted", label: "Source-shortlisted" },
  { id: "selected", label: "Selected" },
  { id: "rejected", label: "Rejected" },
  { id: "blocked", label: "Blocked" },
  { id: "stale", label: "Stale" },
  { id: "overlapping", label: "Overlapping" },
  { id: "missing_evidence", label: "Missing evidence" },
  { id: "historical", label: "Historical" },
];

const SORTS: { id: CandidateReviewSort; label: string }[] = [
  { id: "review_priority", label: "Review priority" },
  { id: "original_rank", label: "Original rank (Clip Ranking)" },
  { id: "source_start_time", label: "Source start time" },
  { id: "duration", label: "Duration" },
  { id: "creation_order", label: "Creation order" },
  { id: "candidate_id", label: "Candidate ID" },
];

export function BobaCandidateOverlapBadge({ record }: { record: CandidateOverlapRecord }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded border border-amber-300/30 bg-amber-300/[0.06] px-1.5 py-0.5 text-[11px] text-amber-100"
      title={overlapDescription(record)}
    >
      <span aria-hidden="true" className="font-mono text-[10px]">
        {record.exact_duplicate_window ? "[dup]" : "[overlap]"}
      </span>
      <span>{overlapLabel(record)}</span>
    </span>
  );
}

export function BobaCandidateCard({
  item,
  selected,
  comparing,
  shortlisted,
  onSelect,
  onToggleCompare,
  onToggleShortlist,
}: {
  item: CandidateQueueItem;
  selected: boolean;
  comparing: boolean;
  shortlisted: boolean;
  onSelect: () => void;
  onToggleCompare: () => void;
  onToggleShortlist: () => void;
}) {
  return (
    <article
      className={`rounded-lg border p-3 ${
        selected
          ? "border-sky-300/50 bg-sky-300/[0.10]"
          : item.blocker_count > 0
            ? "border-rose-300/30 bg-rose-300/[0.05]"
            : item.human_action_required
              ? "border-amber-300/30 bg-amber-300/[0.05]"
              : "border-white/10 bg-white/[0.02]"
      }`}
      aria-labelledby={`candidate-title-${item.candidate_id}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h4
          id={`candidate-title-${item.candidate_id}`}
          className="text-sm font-medium text-white/90"
        >
          {item.title}
        </h4>
        <span className="inline-flex items-center gap-1 text-[11px] text-white/60">
          <span aria-hidden="true" className="font-mono text-[10px]">
            {candidateStateGlyph(item)}
          </span>
          {candidateStateLabel(item)}
        </span>
      </div>

      <p className="mt-0.5 font-mono text-[10px] text-white/45">{item.candidate_id}</p>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
        <div>
          <dt className="text-white/50">Source window</dt>
          <dd className="font-mono text-white/85">
            {formatSourceWindow(item.start_seconds, item.end_seconds)}
            <span className="ml-1 text-white/55">
              ({formatDuration(item.duration_seconds)})
            </span>
          </dd>
        </div>
        <div>
          <dt className="text-white/50">Original rank</dt>
          <dd className="text-white/85">
            {item.original_rank === null
              ? "Not ranked"
              : `#${item.original_rank}${
                  item.original_rank_total ? ` of ${item.original_rank_total}` : ""
                }`}
            {item.rank_owner_module_id && (
              <span className="ml-1 font-mono text-[10px] text-white/45">
                {item.rank_owner_module_id}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-white/50">Primary source score</dt>
          <dd className="text-white/85">
            {item.primary_score === null
              ? "Not available"
              : `${item.primary_score_name} ${item.primary_score}`}
            {item.primary_score_owner_module_id && (
              <span className="ml-1 font-mono text-[10px] text-white/45">
                {item.primary_score_owner_module_id}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-white/50">Editorial status</dt>
          <dd className="text-white/85">{editorialStatusLabel(item.editorial_status)}</dd>
        </div>
      </dl>

      <p className="sr-only">{describeRank(item)}</p>
      <p className="mt-2 text-xs text-white/65">{item.bounded_summary}</p>
      <p className="mt-1 text-[11px] text-white/55">{evidenceSummary(item)}</p>

      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-white/50">
        <li>tier {item.priority_tier}</li>
        <li>{item.blocker_count} blocking</li>
        <li>{item.conflict_count} conflicts</li>
        <li>{item.warning_count} warnings</li>
        {item.human_action_required && <li className="text-amber-100">Human action required</li>}
        {item.overlap_group_ids.length > 0 && (
          <li className="text-amber-100">
            {item.overlap_group_ids.length} overlapping window(s)
          </li>
        )}
      </ul>

      <p className="mt-1 font-mono text-[10px] text-white/40">
        {item.source_module_ids.join(", ")}
      </p>

      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onSelect}
          className="min-h-[44px] rounded border border-white/15 px-2 text-xs text-white/85 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          Review this candidate
        </button>
        <button
          type="button"
          onClick={onToggleCompare}
          aria-pressed={comparing}
          className="min-h-[44px] rounded border border-white/15 px-2 text-xs text-white/85 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {comparing ? "Remove from comparison" : "Add to comparison"}
        </button>
        <button
          type="button"
          onClick={onToggleShortlist}
          aria-pressed={shortlisted}
          title={LOCAL_SHORTLIST_NOTICE}
          className="min-h-[44px] rounded border border-white/15 px-2 text-xs text-white/85 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {shortlisted ? "Remove from session shortlist" : "Add to session shortlist"}
        </button>
      </div>
      {shortlisted && (
        <p className="mt-1 text-[11px] text-amber-100">{LOCAL_SHORTLIST_NOTICE}</p>
      )}
    </article>
  );
}

export function BobaCandidateQueue({
  items,
  filter,
  sort,
  search,
  selectedCandidateId,
  comparisonIds,
  shortlistIds,
  overlapsByCandidate,
  onFilterChange,
  onSortChange,
  onSearchChange,
  onSelect,
  onToggleCompare,
  onToggleShortlist,
  loading,
  error,
}: {
  items: CandidateQueueItem[];
  filter: CandidateReviewFilter;
  sort: CandidateReviewSort;
  search: string;
  selectedCandidateId: string | null;
  comparisonIds: string[];
  shortlistIds: string[];
  overlapsByCandidate: Record<string, CandidateOverlapRecord[]>;
  onFilterChange: (value: CandidateReviewFilter) => void;
  onSortChange: (value: CandidateReviewSort) => void;
  onSearchChange: (value: string) => void;
  onSelect: (candidateId: string) => void;
  onToggleCompare: (candidateId: string) => void;
  onToggleShortlist: (candidateId: string) => void;
  loading?: boolean;
  error?: string | null;
}) {
  const listRef = useRef<HTMLUListElement>(null);
  const visible = sortCandidates(filterCandidates(items, { filter, search }), sort);

  const move = (from: number, delta: number) => {
    const options = listRef.current?.querySelectorAll<HTMLElement>('[role="option"]');
    if (!options?.length) return;
    options[Math.max(0, Math.min(options.length - 1, from + delta))]?.focus();
  };

  return (
    <section aria-labelledby="candidate-queue-heading" className="space-y-3">
      <h3 id="candidate-queue-heading" className="text-sm font-semibold text-white/90">
        CANDIDATE QUEUE
      </h3>

      <div>
        <label htmlFor="candidate-search" className="block text-xs text-white/60">
          Search candidates
        </label>
        <input
          id="candidate-search"
          type="search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Candidate ID, title or reason"
          className="mt-1 min-h-[44px] w-full rounded-md border border-white/10 bg-black/30 px-3 text-sm text-white/90 placeholder:text-white/35 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        />
      </div>

      <div>
        <label htmlFor="candidate-filter" className="block text-xs text-white/60">
          Filter
        </label>
        <select
          id="candidate-filter"
          value={filter}
          onChange={(event) => onFilterChange(event.target.value as CandidateReviewFilter)}
          className="mt-1 min-h-[44px] w-full rounded-md border border-white/10 bg-black/30 px-2 text-sm text-white/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {FILTERS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="candidate-sort" className="block text-xs text-white/60">
          Sort
        </label>
        <select
          id="candidate-sort"
          value={sort}
          onChange={(event) => onSortChange(event.target.value as CandidateReviewSort)}
          className="mt-1 min-h-[44px] w-full rounded-md border border-white/10 bg-black/30 px-2 text-sm text-white/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          {SORTS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        <p className="mt-1 text-[11px] text-white/45">
          Ordering uses source-owned rank and a fixed review priority. There is no
          &ldquo;AI best&rdquo; or virality ordering.
        </p>
      </div>

      <p className="text-[11px] text-white/55">
        {comparisonIds.length} of {MAX_COMPARISON_CANDIDATES} selected for comparison.
      </p>

      {loading && (
        <p role="status" className="text-xs text-white/60">
          Loading the candidate queue…
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-rose-200">
          {error}
        </p>
      )}
      {!loading && !error && visible.length === 0 && (
        <p className="rounded-md border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60">
          No candidates match this filter.
        </p>
      )}

      <ul
        ref={listRef}
        role="listbox"
        aria-label="Candidate clips, ordered by review priority"
        className="space-y-2"
      >
        {visible.map((item, index) => (
          <li key={item.candidate_queue_item_id}>
            <div
              role="option"
              aria-selected={item.candidate_id === selectedCandidateId}
              tabIndex={index === 0 ? 0 : -1}
              onKeyDown={(event) => {
                if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)) {
                  event.preventDefault();
                  if (event.key === "ArrowDown") move(index, 1);
                  else if (event.key === "ArrowUp") move(index, -1);
                  else if (event.key === "Home") move(index, -index);
                  else if (event.key === "End") move(index, visible.length);
                  else onSelect(item.candidate_id);
                }
              }}
              className="rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
            >
              <BobaCandidateCard
                item={item}
                selected={item.candidate_id === selectedCandidateId}
                comparing={comparisonIds.includes(item.candidate_id)}
                shortlisted={shortlistIds.includes(item.candidate_id)}
                onSelect={() => onSelect(item.candidate_id)}
                onToggleCompare={() => onToggleCompare(item.candidate_id)}
                onToggleShortlist={() => onToggleShortlist(item.candidate_id)}
              />
              {(overlapsByCandidate[item.candidate_id] ?? []).length > 0 && (
                <ul className="mt-1 flex flex-wrap gap-1 px-3 pb-2">
                  {(overlapsByCandidate[item.candidate_id] ?? []).slice(0, 3).map((record) => (
                    <li key={record.overlap_record_id}>
                      <BobaCandidateOverlapBadge record={record} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-white/40">
        Source windows and durations are the exact persisted values from Candidate
        Clip Discovery.
      </p>
    </section>
  );
}
