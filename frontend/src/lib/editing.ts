/**
 * Pure presentation helpers for the Editing Engine timeline UI.
 *
 * The backend returns timelines and events as loosely-typed JSON. These helpers
 * format time, label/colour tracks and event types, expose timeline geometry
 * (px/sec zoom -> x positions), and parse the validation report - all pure and
 * side-effect-free so they can be unit-tested without a DOM. Nothing here invents
 * data: a `null` confidence is rendered honestly as "Unknown", and undeterminable
 * events keep their backend reason.
 */

import type { Editing, Timeline, TimelineEvent } from "@/lib/types";

/* ------------------------------ formatting -------------------------------- */

/** Format clip-relative seconds as `m:ss.S` (one decimal for editing precision). */
export function formatTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const tenths = Math.round((seconds - Math.floor(seconds)) * 10);
  return `${m}:${String(s).padStart(2, "0")}.${tenths}`;
}

/** Format a confidence (0-1), honestly showing UNKNOWN when the backend gave null. */
export function formatConfidence(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

export function humanize(value: string): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced[0].toUpperCase() + spaced.slice(1);
}

/* ------------------------------ track + event meta ------------------------ */

export interface TrackMeta {
  label: string;
  /** Tailwind background for the track lane header. */
  accent: string;
}

const TRACK_META: Record<string, TrackMeta> = {
  video: { label: "Video", accent: "text-sky-300" },
  audio: { label: "Audio", accent: "text-emerald-300" },
  caption: { label: "Subtitles", accent: "text-amber-300" },
  markers: { label: "Markers", accent: "text-fuchsia-300" },
};

/** Display order of tracks (video, audio, subtitles, markers). */
export const TRACK_ORDER = ["video", "audio", "caption", "markers"] as const;

export function trackMeta(kind: string): TrackMeta {
  return TRACK_META[kind] ?? { label: humanize(kind), accent: "text-muted" };
}

export interface EventMeta {
  label: string;
  /** Tailwind background colour for the event block/marker. */
  color: string;
  /** Whether this is a point-in-time marker (drawn as a pin) vs a span. */
  point: boolean;
}

const EVENT_META: Record<string, EventMeta> = {
  source_clip: { label: "Source clip", color: "bg-sky-500/50", point: false },
  source_audio: { label: "Source audio", color: "bg-emerald-500/40", point: false },
  zoom_in: { label: "Zoom in", color: "bg-indigo-500/60", point: false },
  pan_to_speaker: { label: "Pan", color: "bg-indigo-400", point: true },
  silence: { label: "Silence", color: "bg-white/15", point: false },
  long_pause: { label: "Long pause", color: "bg-white/15", point: false },
  dead_air: { label: "Dead air", color: "bg-rose-500/30", point: false },
  filler_word: { label: "Filler", color: "bg-amber-400", point: true },
  repeated_word: { label: "Repeat", color: "bg-amber-300", point: true },
  caption: { label: "Caption", color: "bg-amber-500/60", point: false },
  jump_cut_point: { label: "Jump cut", color: "bg-fuchsia-400", point: true },
  pattern_interrupt: { label: "Pattern interrupt", color: "bg-rose-400", point: true },
  music_intro: { label: "Music in", color: "bg-violet-400", point: true },
  music_drop: { label: "Music drop", color: "bg-violet-500", point: true },
  music_ending: { label: "Music out", color: "bg-violet-400", point: true },
  transition: { label: "Transition", color: "bg-cyan-400", point: true },
  broll_suggestion: { label: "B-roll", color: "bg-teal-500/50", point: false },
  hook_enhancement: { label: "Hook", color: "bg-pink-400", point: true },
};

export function eventMeta(type: string): EventMeta {
  return EVENT_META[type] ?? { label: humanize(type), color: "bg-slate-400", point: true };
}

/* ------------------------------ geometry ---------------------------------- */

/** Clamp a zoom level (pixels per second) to a sane editing range. */
export function clampZoom(pxPerSecond: number): number {
  return Math.max(4, Math.min(120, pxPerSecond));
}

/** Pixel x-position of a time (seconds) at a given zoom. */
export function timeToX(seconds: number, pxPerSecond: number): number {
  return Math.max(0, seconds) * pxPerSecond;
}

/** Total timeline width in pixels for a duration at a given zoom. */
export function timelineWidth(duration: number, pxPerSecond: number): number {
  return Math.max(0, duration) * pxPerSecond;
}

/** Evenly-spaced ruler ticks (seconds) for a duration, ~targetPx apart. */
export function rulerTicks(duration: number, pxPerSecond: number, targetPx = 80): number[] {
  if (duration <= 0 || pxPerSecond <= 0) return [0];
  const rawStep = targetPx / pxPerSecond;
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300];
  const step = steps.find((s) => s >= rawStep) ?? 600;
  const ticks: number[] = [];
  for (let t = 0; t <= duration + 1e-6; t += step) ticks.push(Math.round(t));
  return ticks;
}

/* ------------------------------ event helpers ----------------------------- */

/** Number of events across all tracks of a timeline. */
export function countEvents(timeline: Timeline): number {
  return (timeline.tracks ?? []).reduce((n, t) => n + (t.events?.length ?? 0), 0);
}

/** Whether an event is an honest UNKNOWN (no confidence was determinable). */
export function isUnknown(event: TimelineEvent): boolean {
  return event.confidence == null;
}

/** Pull a short evidence string from an event for inspector display. */
export function evidenceText(event: TimelineEvent): string {
  const first = Array.isArray(event.evidence) ? event.evidence[0] : undefined;
  if (first && typeof first === "object") {
    const rec = first as Record<string, unknown>;
    const detail = typeof rec.detail === "string" ? rec.detail : "";
    const type = typeof rec.type === "string" ? rec.type : "";
    return [type, detail].filter(Boolean).join(": ");
  }
  return "";
}

/* ------------------------------ validation -------------------------------- */

export interface ValidationView {
  valid: boolean;
  issueCount: number;
  clips: { clipId: string; valid: boolean; issues: string[] }[];
}

export function parseValidation(
  report: Record<string, unknown> | null | undefined,
): ValidationView | null {
  if (!report) return null;
  const clipsRaw = Array.isArray(report.clips) ? report.clips : [];
  return {
    valid: report.valid === true,
    issueCount: typeof report.issue_count === "number" ? report.issue_count : 0,
    clips: clipsRaw.map((c) => {
      const rec = (c ?? {}) as Record<string, unknown>;
      const issues = Array.isArray(rec.issues) ? rec.issues : [];
      return {
        clipId: typeof rec.clip_id === "string" ? rec.clip_id : "",
        valid: rec.valid === true,
        issues: issues.map((i) => {
          const ir = (i ?? {}) as Record<string, unknown>;
          return typeof ir.detail === "string" ? ir.detail : JSON.stringify(ir);
        }),
      };
    }),
  };
}

/** Whether the editing pipeline has reached a terminal state. */
export function isTerminal(editing: Editing | null | undefined): boolean {
  return !!editing && ["completed", "failed", "cancelled"].includes(editing.status);
}
