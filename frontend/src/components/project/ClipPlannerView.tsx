"use client";

/**
 * The Clip Planner view — ranked editing plans with search/filter/sort, an
 * overlap timeline, quality scorecards, duplicate/overlap warnings, and a full
 * blueprint viewer for the selected plan.
 *
 * Honesty-first: zero plans is a valid outcome shown with the planner's own
 * explanation; every plan surfaces its quality score and confidence; overlaps
 * are flagged rather than hidden. This view inspects plans only — it edits
 * nothing.
 */
import { useMemo, useState } from "react";

import { AlertIcon, ScissorsIcon, SearchIcon } from "@/components/icons";
import { BlueprintViewer } from "@/components/project/BlueprintViewer";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { usePlans } from "@/lib/queries";
import {
  confidenceBand,
  filterPlans,
  formatDuration,
  formatPercent,
  formatTimestamp,
  isTerminal,
  overlapCounts,
  parsePlanningSummary,
  scoreBand,
  sortPlans,
  type PlanSortKey,
} from "@/lib/planning";
import type { ClipPlan, Planning } from "@/lib/types";

function qualityBg(score: number): string {
  if (score >= 0.66) return "bg-emerald-500/40 hover:bg-emerald-500/60";
  if (score >= 0.4) return "bg-amber-500/40 hover:bg-amber-500/60";
  return "bg-rose-500/40 hover:bg-rose-500/60";
}

/** Greedy lane assignment so overlapping clips render on separate rows. */
function assignLanes(plans: ClipPlan[]): { plan: ClipPlan; lane: number }[] {
  const laneEnds: number[] = [];
  const ordered = [...plans].sort((a, b) => a.start - b.start);
  return ordered.map((plan) => {
    let lane = laneEnds.findIndex((end) => plan.start >= end);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(plan.end);
    } else {
      laneEnds[lane] = plan.end;
    }
    return { plan, lane };
  });
}

function ClipTimeline({
  plans,
  total,
  selectedId,
  onSelect,
}: {
  plans: ClipPlan[];
  total: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const lanes = assignLanes(plans);
  const laneCount = Math.max(1, ...lanes.map((l) => l.lane + 1));
  return (
    <div>
      <div
        className="relative w-full rounded-lg bg-white/[0.03]"
        style={{ height: `${laneCount * 30 + 8}px` }}
      >
        {lanes.map(({ plan, lane }) => {
          const left = total > 0 ? (plan.start / total) * 100 : 0;
          const width = total > 0 ? Math.max(2, ((plan.end - plan.start) / total) * 100) : 0;
          const selected = plan.id === selectedId;
          return (
            <button
              key={plan.id}
              type="button"
              onClick={() => onSelect(plan.id)}
              aria-pressed={selected}
              title={`${formatTimestamp(plan.start)}–${formatTimestamp(plan.end)} · ${formatPercent(plan.quality_score)}`}
              className={`absolute flex items-center overflow-hidden rounded px-1.5 text-[10px] font-medium text-white/90 transition-colors ${qualityBg(
                plan.quality_score,
              )} ${selected ? "ring-2 ring-white" : ""}`}
              style={{ left: `${left}%`, width: `${width}%`, top: `${lane * 30 + 4}px`, height: "26px" }}
            >
              <span className="truncate">#{plan.rank ?? "?"} · {formatPercent(plan.quality_score)}</span>
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[11px] tabular-nums text-muted">
        <span>0:00</span>
        <span>{formatTimestamp(total)}</span>
      </div>
    </div>
  );
}

function ClipCard({
  plan,
  overlaps,
  selected,
  onSelect,
}: {
  plan: ClipPlan;
  overlaps: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const band = scoreBand(plan.quality_score);
  const conf = confidenceBand(plan.confidence);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`w-full rounded-xl border p-4 text-left transition-colors ${
        selected ? "border-accent bg-accent/5" : "border-white/10 bg-white/[0.02] hover:border-white/20"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wide text-muted">Rank #{plan.rank ?? "?"}</p>
          <p className="truncate text-sm font-medium text-white">
            {String(
              (plan.blueprint?.title_suggestion as Record<string, unknown> | undefined)?.text ?? plan.id,
            )}
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {formatTimestamp(plan.start)}–{formatTimestamp(plan.end)} · {formatDuration(plan.duration)}
          </p>
        </div>
        <span className={`shrink-0 text-xl font-semibold tabular-nums ${band.className}`}>
          {formatPercent(plan.quality_score)}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${conf.className}`}>
          {conf.label} conf · {formatPercent(plan.confidence)}
        </span>
        {overlaps > 0 && (
          <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-amber-300 bg-amber-500/10">
            <AlertIcon className="h-3 w-3" />
            overlaps {overlaps}
          </span>
        )}
        {plan.alternatives.length > 0 && (
          <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-muted">
            {plan.alternatives.length} merged
          </span>
        )}
      </div>
    </button>
  );
}

export function ClipPlannerView({
  planning,
  durationSeconds,
}: {
  planning: Planning;
  durationSeconds?: number | null;
}) {
  const summary = parsePlanningSummary(
    (planning.stages.find((s) => s.stage === "planning_summary")?.data as
      | Record<string, unknown>
      | null) ?? null,
  );
  const plansQuery = usePlans(planning.project_id, isTerminal(planning));
  // Memoised so the empty-fallback array is stable across renders; otherwise a
  // fresh `[]` on every render would invalidate the useMemo hooks below.
  const plansData = plansQuery.data;
  const allPlans = useMemo(() => plansData?.plans ?? [], [plansData]);

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<PlanSortKey>("rank");
  const [minQuality, setMinQuality] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const visible = useMemo(
    () => sortPlans(filterPlans(allPlans, query, minQuality), sort),
    [allPlans, query, minQuality, sort],
  );
  const overlaps = useMemo(() => overlapCounts(allPlans), [allPlans]);
  const selected = visible.find((p) => p.id === selectedId) ?? visible[0] ?? null;
  const total = Math.max(durationSeconds || 0, ...allPlans.map((p) => p.end), 1);

  // Honest zero-clips outcome.
  if (summary && summary.planCount === 0) {
    return (
      <div className="space-y-4">
        <EmptyState
          icon={<ScissorsIcon className="h-6 w-6" />}
          title="No editing plans were produced"
          description={
            summary.zeroReason ??
            "The planner did not find any clip-worthy moments worth proposing."
          }
        />
        {summary.pendingSignals.length > 0 && (
          <Card>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">
              Signals still pending
            </p>
            <ul className="mt-2 space-y-1 text-xs text-muted">
              {summary.pendingSignals.map((p) => (
                <li key={p.signal}>
                  <span className="text-white/80">{p.signal}</span> — {p.reason}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    );
  }

  if (!isTerminal(planning) || plansQuery.isLoading) {
    return (
      <Card>
        <p className="text-sm text-muted">Generating editing plans…</p>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {summary && (
        <Card>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <div>
              <p className="text-2xl font-semibold text-white">{summary.planCount}</p>
              <p className="text-[11px] uppercase tracking-wide text-muted">editing plans</p>
            </div>
            <div className="flex gap-2 text-xs">
              <span className="rounded bg-emerald-500/10 px-2 py-1 text-emerald-300">
                {summary.distribution.high} high
              </span>
              <span className="rounded bg-amber-500/10 px-2 py-1 text-amber-300">
                {summary.distribution.moderate} moderate
              </span>
              <span className="rounded bg-rose-500/10 px-2 py-1 text-rose-300">
                {summary.distribution.low} low
              </span>
            </div>
            {summary.availableSignals.length > 0 && (
              <p className="text-[11px] text-muted">
                from: {summary.availableSignals.join(", ")}
              </p>
            )}
          </div>
        </Card>
      )}

      {/* Overlap timeline */}
      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
          Clip timeline &amp; overlaps
        </h4>
        <Card>
          <ClipTimeline
            plans={allPlans}
            total={total}
            selectedId={selected?.id ?? null}
            onSelect={setSelectedId}
          />
        </Card>
      </section>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[180px] flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search plans…"
            aria-label="Search plans"
            className="w-full rounded-lg border border-white/10 bg-white/[0.02] py-2 pl-9 pr-3 text-sm text-white placeholder:text-muted focus:border-accent focus:outline-none"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          Sort
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as PlanSortKey)}
            aria-label="Sort plans"
            className="rounded-lg border border-white/10 bg-surface py-1.5 px-2 text-sm text-white focus:border-accent focus:outline-none"
          >
            <option value="rank">Rank</option>
            <option value="quality">Quality</option>
            <option value="confidence">Confidence</option>
            <option value="duration">Duration</option>
            <option value="start">Start time</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-muted">
          Min quality {formatPercent(minQuality)}
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={minQuality}
            onChange={(e) => setMinQuality(Number(e.target.value))}
            aria-label="Minimum quality filter"
          />
        </label>
      </div>

      {/* Cards + blueprint */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-2">
          {visible.length > 0 ? (
            visible.map((plan) => (
              <ClipCard
                key={plan.id}
                plan={plan}
                overlaps={overlaps[plan.id] ?? 0}
                selected={selected?.id === plan.id}
                onSelect={() => setSelectedId(plan.id)}
              />
            ))
          ) : (
            <p className="text-sm text-muted">No plans match your search/filter.</p>
          )}
        </div>
        <div className="lg:col-span-3">
          {selected ? (
            <Card>
              <BlueprintViewer plan={selected} />
            </Card>
          ) : (
            <Card>
              <p className="text-sm text-muted">Select a plan to view its full editing blueprint.</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
