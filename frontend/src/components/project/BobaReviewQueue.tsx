"use client";

/**
 * Deterministic review queue.
 *
 * Order comes from the backend priority tier. The list is a keyboard-navigable
 * listbox: arrow keys move, Home/End jump, Enter or Space selects.
 */

import { useRef } from "react";

import {
  categoryLabel,
  filterQueue,
  sortQueue,
  type QueueFilter,
  type ReviewQueueCategory,
  type ReviewQueueItem,
} from "@/lib/reviewUi";

const CATEGORY_FILTERS: (ReviewQueueCategory | "all")[] = [
  "all",
  "critical_attention",
  "blocked",
  "human_review_required",
  "ready_for_review",
  "awaiting_evidence",
  "informational",
  "unavailable",
];

function itemTone(item: ReviewQueueItem, selected: boolean) {
  if (selected) return "border-sky-300/50 bg-sky-300/[0.10]";
  if (item.display_category === "critical_attention") return "border-rose-300/30 bg-rose-300/[0.05]";
  if (item.display_category === "blocked") return "border-orange-300/30 bg-orange-300/[0.05]";
  if (item.display_category === "human_review_required")
    return "border-amber-300/30 bg-amber-300/[0.05]";
  return "border-white/10 bg-white/[0.02]";
}

export function BobaReviewQueue({
  items,
  filter,
  sort,
  selectedTargetId,
  onSelect,
  onFilterChange,
  loading,
  error,
}: {
  items: ReviewQueueItem[];
  filter: QueueFilter;
  sort: "priority" | "updated";
  selectedTargetId: string | null;
  onSelect: (item: ReviewQueueItem) => void;
  onFilterChange: (next: QueueFilter) => void;
  loading?: boolean;
  error?: string | null;
}) {
  const listRef = useRef<HTMLUListElement>(null);
  const visible = sortQueue(filterQueue(items, filter), sort);

  const moveFocus = (delta: number, from: number) => {
    const options = listRef.current?.querySelectorAll<HTMLElement>('[role="option"]');
    if (!options || options.length === 0) return;
    const next = Math.max(0, Math.min(options.length - 1, from + delta));
    options[next]?.focus();
  };

  const onKeyDown = (eventKey: string, index: number, item: ReviewQueueItem) => {
    if (eventKey === "ArrowDown") return moveFocus(1, index);
    if (eventKey === "ArrowUp") return moveFocus(-1, index);
    if (eventKey === "Home") return moveFocus(-index, index);
    if (eventKey === "End") return moveFocus(visible.length, index);
    if (eventKey === "Enter" || eventKey === " ") return onSelect(item);
  };

  return (
    <section aria-labelledby="review-queue-heading" className="space-y-3">
      <h3 id="review-queue-heading" className="text-sm font-semibold text-white/90">
        REVIEW QUEUE
      </h3>

      <div className="space-y-2">
        <label htmlFor="review-queue-search" className="block text-xs text-white/60">
          Search the queue
        </label>
        <input
          id="review-queue-search"
          type="search"
          value={filter.search ?? ""}
          onChange={(event) => onFilterChange({ ...filter, search: event.target.value })}
          placeholder="Title, summary or module"
          className="min-h-[44px] w-full rounded-md border border-white/10 bg-black/30 px-3 text-sm text-white/90 placeholder:text-white/35 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        />
        <div>
          <label htmlFor="review-queue-category" className="block text-xs text-white/60">
            Filter by category
          </label>
          <select
            id="review-queue-category"
            value={filter.category ?? "all"}
            onChange={(event) =>
              onFilterChange({
                ...filter,
                category: event.target.value as ReviewQueueCategory | "all",
              })
            }
            className="mt-1 min-h-[44px] w-full rounded-md border border-white/10 bg-black/30 px-2 text-sm text-white/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            {CATEGORY_FILTERS.map((value) => (
              <option key={value} value={value}>
                {value === "all" ? "All categories" : categoryLabel(value)}
              </option>
            ))}
          </select>
        </div>
        <label className="flex min-h-[44px] items-center gap-2 text-xs text-white/70">
          <input
            type="checkbox"
            checked={Boolean(filter.includeHistorical)}
            onChange={(event) =>
              onFilterChange({ ...filter, includeHistorical: event.target.checked })
            }
            className="h-4 w-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          />
          Include historical records
        </label>
      </div>

      {loading && (
        <p role="status" className="text-xs text-white/60">
          Loading the review queue…
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-rose-200">
          {error}
        </p>
      )}

      {!loading && !error && visible.length === 0 && (
        <p className="rounded-md border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60">
          No canonical review work matches this filter.
        </p>
      )}

      <ul
        ref={listRef}
        role="listbox"
        aria-label="Review queue, ordered by canonical priority"
        className="space-y-2"
      >
        {visible.map((item, index) => {
          const selected = item.target_id === selectedTargetId;
          return (
            <li key={item.queue_item_id}>
              <div
                role="option"
                aria-selected={selected}
                tabIndex={index === 0 ? 0 : -1}
                onClick={() => onSelect(item)}
                onKeyDown={(event) => {
                  if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)) {
                    event.preventDefault();
                    onKeyDown(event.key, index, item);
                  }
                }}
                className={`w-full cursor-pointer rounded-lg border p-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 ${itemTone(item, selected)}`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium text-white/90">{item.title}</span>
                  <span className="font-mono text-[10px] text-white/45">
                    tier {item.priority}
                  </span>
                </div>
                <p className="mt-1 text-xs text-white/65">{item.bounded_summary}</p>
                <p className="mt-1 text-[11px] text-white/55">
                  {categoryLabel(item.display_category)} · {item.primary_reason.replace(/_/g, " ")}
                </p>
                <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-white/50">
                  <li>{item.blocker_count} blocking</li>
                  <li>{item.missing_evidence_count} missing evidence</li>
                  <li>{item.conflict_count} conflicts</li>
                  <li>{item.warning_count} warnings</li>
                  {item.human_action_required && <li className="text-amber-100">Human action</li>}
                  {item.stale && <li className="text-sky-100">Stale</li>}
                  {item.historical && <li className="text-white/40">Historical</li>}
                </ul>
                <p className="mt-1 font-mono text-[10px] text-white/40">
                  {item.source_module_ids.join(", ")}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
