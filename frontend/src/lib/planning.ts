/**
 * Pure presentation helpers for the Clip Planner UI.
 *
 * The backend returns plans and the summary as loosely-typed JSON. These helpers
 * format values, band scores, and implement search/filter/sort and overlap
 * detection - all pure and side-effect-free so they can be unit-tested without a
 * DOM. Nothing here invents data: a missing score stays `null`, zero plans is a
 * first-class honest outcome, and confidence is always available alongside scores.
 */

import type { ClipPlan, Planning } from "@/lib/types";

/* ------------------------------ formatting -------------------------------- */

export interface Band {
  label: "Low" | "Moderate" | "High";
  className: string;
}

export function confidenceBand(value: number): Band {
  if (value >= 0.66) return { label: "High", className: "text-green-300 bg-green-500/10" };
  if (value >= 0.4) return { label: "Moderate", className: "text-amber-300 bg-amber-500/10" };
  return { label: "Low", className: "text-muted bg-white/5" };
}

export function scoreBand(value: number): Band {
  if (value >= 0.66) return { label: "High", className: "text-emerald-300" };
  if (value >= 0.4) return { label: "Moderate", className: "text-amber-300" };
  return { label: "Low", className: "text-rose-300" };
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export function formatTimestamp(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}

/** Compact clip duration, e.g. `42 -> "42s"`, `95 -> "1m 35s"`. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}

export function humanize(value: string): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced[0].toUpperCase() + spaced.slice(1);
}

/* ------------------------------ dimensions -------------------------------- */

/** The clip-quality dimensions in display order, with labels. */
export const DIMENSION_DEFS: { key: string; label: string }[] = [
  { key: "hook", label: "Hook" },
  { key: "retention", label: "Retention" },
  { key: "emotion", label: "Emotion" },
  { key: "story", label: "Story" },
  { key: "virality", label: "Virality" },
  { key: "information", label: "Information" },
  { key: "novelty", label: "Novelty" },
  { key: "shareability", label: "Shareability" },
  { key: "conflict", label: "Conflict" },
  { key: "replay", label: "Replay" },
  { key: "editing_complexity", label: "Editing complexity" },
];

export interface DimensionScore {
  key: string;
  label: string;
  value: number | null;
}

/** Ordered dimension scores for a plan's scorecard (missing -> null). */
export function dimensionScores(plan: ClipPlan): DimensionScore[] {
  const scores = plan.scores ?? {};
  return DIMENSION_DEFS.map((d) => ({
    key: d.key,
    label: d.label,
    value: typeof scores[d.key] === "number" ? scores[d.key] : null,
  }));
}

/* ------------------------------ search / sort ----------------------------- */

export type PlanSortKey = "rank" | "quality" | "confidence" | "duration" | "start";

/** Sort plans by the chosen key (pure; returns a new array). */
export function sortPlans(plans: ClipPlan[], key: PlanSortKey): ClipPlan[] {
  const copy = [...plans];
  const by: Record<PlanSortKey, (p: ClipPlan) => number> = {
    rank: (p) => p.rank ?? Number.MAX_SAFE_INTEGER,
    quality: (p) => -p.quality_score,
    confidence: (p) => -p.confidence,
    duration: (p) => -p.duration,
    start: (p) => p.start,
  };
  return copy.sort((a, b) => by[key](a) - by[key](b));
}

function planTitle(plan: ClipPlan): string {
  const bp = plan.blueprint ?? {};
  const title = bp.title_suggestion;
  if (title && typeof title === "object" && typeof (title as Record<string, unknown>).text === "string") {
    return (title as Record<string, unknown>).text as string;
  }
  return "";
}

/** Filter plans by a free-text query (title/explanation) and a minimum quality. */
export function filterPlans(plans: ClipPlan[], query: string, minQuality: number): ClipPlan[] {
  const q = query.trim().toLowerCase();
  return plans.filter((p) => {
    if (p.quality_score < minQuality) return false;
    if (!q) return true;
    const haystack = `${planTitle(p)} ${p.explanation ?? ""} ${p.id}`.toLowerCase();
    return haystack.includes(q);
  });
}

/* ------------------------------ overlap viz ------------------------------- */

/** Whether two plans overlap in time at all (for the overlap visualization). */
export function plansOverlap(a: ClipPlan, b: ClipPlan): boolean {
  return Math.max(0, Math.min(a.end, b.end) - Math.max(a.start, b.start)) > 0;
}

/** Count how many other plans each plan overlaps (duplicate/overlap warnings). */
export function overlapCounts(plans: ClipPlan[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const a of plans) {
    out[a.id] = plans.filter((b) => b.id !== a.id && plansOverlap(a, b)).length;
  }
  return out;
}

/* ------------------------------ summary ----------------------------------- */

export interface PlanningSummaryView {
  planCount: number;
  zeroReason: string | null;
  distribution: { high: number; moderate: number; low: number };
  availableSignals: string[];
  pendingSignals: { signal: string; reason: string }[];
  confidence: number;
}

function asStrArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

export function parsePlanningSummary(
  summary: Record<string, unknown> | null | undefined,
): PlanningSummaryView | null {
  if (!summary) return null;
  const dist = (summary.score_distribution ?? {}) as Record<string, unknown>;
  const pending = Array.isArray(summary.pending_signals) ? summary.pending_signals : [];
  return {
    planCount: typeof summary.plan_count === "number" ? summary.plan_count : 0,
    zeroReason: typeof summary.zero_reason === "string" ? summary.zero_reason : null,
    distribution: {
      high: typeof dist.high === "number" ? dist.high : 0,
      moderate: typeof dist.moderate === "number" ? dist.moderate : 0,
      low: typeof dist.low === "number" ? dist.low : 0,
    },
    availableSignals: asStrArray(summary.available_signals),
    pendingSignals: pending.map((p) => {
      const r = (p ?? {}) as Record<string, unknown>;
      return {
        signal: typeof r.signal === "string" ? r.signal : "",
        reason: typeof r.reason === "string" ? r.reason : "",
      };
    }),
    confidence: typeof summary.confidence === "number" ? summary.confidence : 0,
  };
}

/** Whether the pipeline has reached a terminal state. */
export function isTerminal(planning: Planning | null | undefined): boolean {
  return !!planning && ["completed", "failed", "cancelled"].includes(planning.status);
}
