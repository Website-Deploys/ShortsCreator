/**
 * Pure presentation helpers for the Production Monitoring & Analytics UI.
 *
 * Formatting and labelling only - no side effects. Honest by construction: a
 * missing/UNKNOWN value formats as "Unknown" (never a fabricated number), and
 * every percentage/rate is shown exactly as the backend measured it.
 *
 * Byte/score/duration formatters are reused from the library helpers so the two
 * dashboards stay visually consistent.
 */

export { formatBytes, formatMs, formatScore, humanize } from "@/lib/library";

/** Format a 0-1 rate as a percentage, honestly showing "Unknown" for null. */
export function formatRate(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

/** Format a possibly-unmeasured number, honestly showing "Unknown" for null. */
export function formatNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  return value.toLocaleString();
}

/** Format an estimated USD amount, or "Unknown" when not measured. */
export function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  return `$${value.toFixed(2)}`;
}

/** A Tailwind text-tone class for a coarse health status. */
export function healthTone(status: string | null | undefined): string {
  switch (status) {
    case "healthy":
      return "text-emerald-300";
    case "degraded":
      return "text-amber-300";
    case "unhealthy":
      return "text-rose-300";
    default:
      return "text-muted";
  }
}

/** A Tailwind background-dot tone for a coarse health status. */
export function healthDot(status: string | null | undefined): string {
  switch (status) {
    case "healthy":
      return "bg-emerald-400";
    case "degraded":
      return "bg-amber-400";
    case "unhealthy":
      return "bg-rose-400";
    default:
      return "bg-white/30";
  }
}

/** A Tailwind text-tone class for an alert severity. */
export function severityTone(severity: string | null | undefined): string {
  switch (severity) {
    case "critical":
      return "text-rose-300";
    case "warning":
      return "text-amber-300";
    case "info":
      return "text-sky-300";
    default:
      return "text-muted";
  }
}

/** A Tailwind border/background tone for an alert severity pill. */
export function severityBadge(severity: string | null | undefined): string {
  switch (severity) {
    case "critical":
      return "border-rose-400/40 bg-rose-400/10 text-rose-200";
    case "warning":
      return "border-amber-400/40 bg-amber-400/10 text-amber-200";
    case "info":
      return "border-sky-400/40 bg-sky-400/10 text-sky-200";
    default:
      return "border-white/15 bg-white/5 text-muted";
  }
}

const ENGINE_LABELS: Record<string, string> = {
  cognitive: "Cognitive",
  story: "Story",
  virality: "Virality",
  planning: "Clip Planner",
  editing: "Editing",
  rendering: "Rendering",
  optimization: "Optimization",
  upload: "Upload",
};

export function engineLabel(engine: string): string {
  return ENGINE_LABELS[engine] ?? engine;
}

/** A friendly timestamp, or "" when missing/invalid. */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
