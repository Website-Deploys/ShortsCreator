/**
 * Pure presentation helpers for the Rendering Engine UI.
 *
 * The backend returns the render run, manifest, validation report, and logs as
 * structured JSON. These pure, side-effect-free helpers format and group that
 * data for display. Nothing here fabricates state: an `unavailable` stage keeps
 * its backend reason, a missing rendered file is never shown as downloadable,
 * and sizes/durations are formatted only when the backend measured them.
 */

import type { RenderRun, RenderStage, RenderStageStatus } from "@/lib/types";

export function humanize(value: string): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced[0].toUpperCase() + spaced.slice(1);
}

/** Whether the render pipeline has reached a terminal state. */
export function isTerminal(run: RenderRun | null | undefined): boolean {
  return !!run && ["completed", "failed", "cancelled"].includes(run.status);
}

export interface StatusMeta {
  label: string;
  tone: string;
}

const STATUS_META: Record<RenderStageStatus, StatusMeta> = {
  completed: { label: "Done", tone: "text-emerald-300" },
  running: { label: "Rendering", tone: "text-accent" },
  pending: { label: "Waiting", tone: "text-muted" },
  unavailable: { label: "Unavailable", tone: "text-amber-300" },
  failed: { label: "Failed", tone: "text-rose-300" },
  cancelled: { label: "Cancelled", tone: "text-muted" },
};

export function statusMeta(status: RenderStageStatus): StatusMeta {
  return STATUS_META[status] ?? { label: humanize(status), tone: "text-muted" };
}

/** Group the render stages into the engine's logical sections. */
export const STAGE_GROUPS: { title: string; stages: string[] }[] = [
  {
    title: "Inputs",
    stages: [
      "load_timeline",
      "validate_timeline",
      "validate_source_assets",
      "prepare_working_directory",
    ],
  },
  {
    title: "Build Plan",
    stages: ["build_video_timeline", "build_audio_timeline"],
  },
  {
    title: "Apply Edits",
    stages: [
      "apply_jump_cuts",
      "apply_zooms",
      "apply_crops",
      "apply_transitions",
      "apply_captions",
      "apply_broll",
      "apply_music",
      "audio_mixing",
    ],
  },
  {
    title: "Render & Publish",
    stages: [
      "render_preview",
      "full_resolution_render",
      "render_verification",
      "generate_render_manifest",
      "cleanup_temporary_files",
      "final_validation",
    ],
  },
];

export function stageTally(stages: RenderStage[]): {
  completed: number;
  unavailable: number;
  failed: number;
  total: number;
} {
  let completed = 0;
  let unavailable = 0;
  let failed = 0;
  for (const s of stages) {
    if (s.status === "completed") completed += 1;
    else if (s.status === "unavailable") unavailable += 1;
    else if (s.status === "failed") failed += 1;
  }
  return { completed, unavailable, failed, total: stages.length };
}

/** Human-readable byte size, or "Unknown" when not measured. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "Unknown";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

/** Human-readable duration (m:ss), or "Unknown" when not measured. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "Unknown";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Short checksum display (algorithm + first 12 hex chars). */
export function shortChecksum(checksum: string | null | undefined): string | null {
  if (!checksum) return null;
  const [algo, hex] = checksum.includes(":") ? checksum.split(":") : ["", checksum];
  return algo ? `${algo}:${hex.slice(0, 12)}…` : `${hex.slice(0, 12)}…`;
}

/** Whether a render genuinely produced a manifest with at least one clip. */
export function manifestProduced(run: RenderRun | null | undefined): boolean {
  if (!run) return false;
  const stage = run.stages.find((s) => s.stage === "generate_render_manifest");
  return stage?.status === "completed";
}
