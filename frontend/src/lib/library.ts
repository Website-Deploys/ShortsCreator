/**
 * Pure presentation helpers for the Project Management & Asset Library UI.
 *
 * Formatting and labelling only - no side effects. Honest by construction:
 * a missing/UNKNOWN value formats as "—" or "Unknown", never a fabricated
 * number, and scores/sizes are shown exactly as the backend reported them.
 */

import type { AssetKind } from "@/lib/types";

/** Human-readable byte size, or "—" when unknown. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

/** Format a 0-1 score as a percentage, honestly showing "Unknown" for null. */
export function formatScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

/** Format a millisecond duration as a friendly string, or "—". */
export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/** Format clip duration seconds as m:ss, or "—". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const ASSET_KIND_LABELS: Record<AssetKind, string> = {
  source_video: "Source video",
  clip: "Clip",
  render: "Render",
  export: "Export",
  thumbnail: "Thumbnail",
};

export function assetKindLabel(kind: string): string {
  return ASSET_KIND_LABELS[kind as AssetKind] ?? kind;
}

const NAMESPACE_LABELS: Record<string, string> = {
  uploads: "Uploads",
  analysis: "Analysis",
  story: "Story",
  virality: "Virality",
  planning: "Planning",
  editing: "Editing",
  renders: "Renders",
  exports: "Exports",
  optimization: "Optimization",
  logs: "Logs",
};

export function namespaceLabel(ns: string): string {
  return NAMESPACE_LABELS[ns] ?? ns;
}

export function humanize(value: string): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced[0].toUpperCase() + spaced.slice(1);
}

/** A tone class for an activity event type (for the feed dot). */
export function activityTone(type: string): string {
  if (type.includes("failed")) return "bg-rose-400";
  if (type.includes("completed")) return "bg-emerald-400";
  if (type.includes("cancelled")) return "bg-white/30";
  if (type.includes("archived")) return "bg-amber-400";
  if (type.includes("cleanup")) return "bg-amber-400";
  return "bg-accent";
}

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

/** A stable colour accent for a download/render status pill. */
export function statusTone(status: string): string {
  if (status === "available" || status === "rendered") return "text-emerald-300";
  if (status === "unavailable") return "text-amber-300";
  return "text-muted";
}
