"use client";

/**
 * Clip brief queue card and queue list.
 *
 * Every value shown here belongs to the owning module. The card never scores a
 * brief, never ranks the set itself, and never presents completeness as quality.
 */

import {
  briefStateLabel,
  completenessGlyph,
  completenessLabel,
  evidenceSummary,
  formatDuration,
  formatSourceWindow,
  priorityLabel,
  type ClipBriefQueueItem,
  type ClipBriefReviewFilter,
  type ClipBriefReviewSort,
} from "@/lib/clipBriefReview";

const FILTERS: { id: ClipBriefReviewFilter; label: string }[] = [
  { id: "all_current", label: "All current" },
  { id: "human_review_required", label: "Needs human review" },
  { id: "current_selected_candidate", label: "Selected candidate" },
  { id: "missing_required_fields", label: "Missing required fields" },
  { id: "missing_evidence", label: "Missing evidence" },
  { id: "conflicts", label: "Conflicts" },
  { id: "stale", label: "Stale" },
  { id: "complete_for_owner_schema", label: "Complete for owner schema" },
  { id: "warnings", label: "Warnings" },
  { id: "historical", label: "Historical" },
  { id: "superseded", label: "Superseded" },
];

const SORTS: { id: ClipBriefReviewSort; label: string }[] = [
  { id: "review_priority", label: "Review priority" },
  { id: "candidate_rank", label: "Candidate rank (source owned)" },
  { id: "created_sequence", label: "Created sequence" },
  { id: "source_start_time", label: "Source start time" },
  { id: "brief_id", label: "Brief ID" },
];

export function BobaClipBriefCard({
  item,
  selected,
  comparing,
  onSelect,
  onToggleComparison,
}: {
  item: ClipBriefQueueItem;
  selected: boolean;
  comparing: boolean;
  onSelect: (briefId: string) => void;
  onToggleComparison: (briefId: string) => void;
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
          onClick={() => onSelect(item.brief_id)}
          className="text-left"
          aria-label={`Open clip brief ${item.brief_id}`}
        >
          <p className="font-medium text-white">{item.title}</p>
          <p className="mt-0.5 text-xs text-white/60">
            {formatSourceWindow(item.start_seconds, item.end_seconds)} ·{" "}
            {formatDuration(item.duration_seconds)} · {briefStateLabel(item)}
          </p>
        </button>
        <label className="flex shrink-0 items-center gap-1.5 text-xs text-white/60">
          <input
            type="checkbox"
            checked={comparing}
            onChange={() => onToggleComparison(item.brief_id)}
            aria-label={`Compare clip brief ${item.brief_id}`}
          />
          Compare
        </label>
      </div>

      {item.bounded_summary ? (
        <p className="mt-2 line-clamp-2 text-xs text-white/70">{item.bounded_summary}</p>
      ) : null}

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-white/60">
        <div>
          <dt className="inline text-white/45">Owner status: </dt>
          <dd className="inline">{item.original_status}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Editorial: </dt>
          <dd className="inline">{item.editorial_status}</dd>
        </div>
        <div>
          <dt className="inline text-white/45">Candidate rank: </dt>
          <dd className="inline">
            {item.candidate_rank === null ? "not ranked by the owner" : item.candidate_rank}
          </dd>
        </div>
        <div>
          <dt className="inline text-white/45">Fields: </dt>
          <dd className="inline" data-state={completenessGlyph(item.completeness_status)}>
            {completenessLabel(item.completeness_status)}
          </dd>
        </div>
      </dl>

      <p className="mt-2 text-xs text-white/50">{evidenceSummary(item)}</p>
      <p className="mt-1 text-[11px] text-white/40">{priorityLabel(item)}</p>

      {item.human_action_required ? (
        <p className="mt-1 text-[11px] text-amber-200/90">
          A person must review this brief against its canonical sources.
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

export function BobaClipBriefQueue({
  items,
  total,
  filter,
  sort,
  selectedBriefId,
  comparisonIds,
  onFilterChange,
  onSortChange,
  onSelect,
  onToggleComparison,
}: {
  items: ClipBriefQueueItem[];
  total: number;
  filter: ClipBriefReviewFilter;
  sort: ClipBriefReviewSort;
  selectedBriefId: string | null;
  comparisonIds: string[];
  onFilterChange: (value: ClipBriefReviewFilter) => void;
  onSortChange: (value: ClipBriefReviewSort) => void;
  onSelect: (briefId: string) => void;
  onToggleComparison: (briefId: string) => void;
}) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-white/50" htmlFor="clip-brief-filter">
          Filter
        </label>
        <select
          id="clip-brief-filter"
          value={filter}
          onChange={(event) =>
            onFilterChange(event.target.value as ClipBriefReviewFilter)
          }
          className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-white"
        >
          {FILTERS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        <label className="text-xs text-white/50" htmlFor="clip-brief-sort">
          Sort
        </label>
        <select
          id="clip-brief-sort"
          value={sort}
          onChange={(event) => onSortChange(event.target.value as ClipBriefReviewSort)}
          className="rounded border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-white"
        >
          {SORTS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="text-xs text-white/40">{total} brief(s) projected</span>
      </div>

      {items.length === 0 ? (
        <p className="mt-3 text-sm text-white/60">
          No clip brief matches this filter. Nothing is hidden by a score.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <BobaClipBriefCard
              key={item.brief_queue_item_id}
              item={item}
              selected={item.brief_id === selectedBriefId}
              comparing={comparisonIds.includes(item.brief_id)}
              onSelect={onSelect}
              onToggleComparison={onToggleComparison}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
