"use client";

/**
 * The Editing view — a read-only window into the non-destructive edit timelines
 * the Editing Engine assembled from approved clip plans.
 *
 * It lets the creator pick a clip, scrub a professional multi-track timeline
 * (zoomable px/sec), and click any edit decision to see *why* it exists: its
 * reason, confidence (honestly "Unknown" when undeterminable), evidence, and any
 * decision-specific detail. A validation banner reports whether the timelines
 * are internally consistent.
 *
 * Honesty-first: zero timelines is a valid outcome, shown with the engine's own
 * explanation (no approved clips / no transcript). Nothing here is editable and
 * nothing is rendered — this only visualizes the edit decision list.
 */
import { useMemo, useState } from "react";

import { AlertIcon, CheckCircleIcon, FilmIcon, MinusIcon, PlusIcon } from "@/components/icons";
import { EditingTimeline } from "@/components/project/EditingTimeline";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  clampZoom,
  countEvents,
  eventMeta,
  evidenceText,
  formatConfidence,
  formatTime,
  humanize,
  isTerminal,
  isUnknown,
  parseValidation,
  trackMeta,
} from "@/lib/editing";
import { useTimelines } from "@/lib/queries";
import type { Editing, Timeline, TimelineEvent } from "@/lib/types";

/* ----------------------------- validation banner -------------------------- */

function ValidationBanner({ report }: { report: Record<string, unknown> | null }) {
  const view = parseValidation(report);
  if (!view) return null;
  const ok = view.valid && view.issueCount === 0;
  return (
    <div
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
        ok
          ? "border-emerald-500/20 bg-emerald-500/[0.06]"
          : "border-amber-500/20 bg-amber-500/[0.06]"
      }`}
    >
      <span className="mt-0.5 shrink-0">
        {ok ? (
          <CheckCircleIcon className="h-5 w-5 text-emerald-400" />
        ) : (
          <AlertIcon className="h-5 w-5 text-amber-300" />
        )}
      </span>
      <div className="min-w-0">
        <p className={`text-sm font-medium ${ok ? "text-emerald-300" : "text-amber-200"}`}>
          {ok
            ? "All timelines passed validation"
            : `${view.issueCount} validation ${view.issueCount === 1 ? "issue" : "issues"} found`}
        </p>
        {!ok && (
          <ul className="mt-1.5 space-y-1 text-xs text-muted">
            {view.clips
              .filter((c) => !c.valid)
              .flatMap((c) =>
                c.issues.map((issue, i) => (
                  <li key={`${c.clipId}-${i}`}>
                    <span className="text-white/70">{c.clipId}</span> — {issue}
                  </li>
                )),
              )}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ----------------------------- event inspector ---------------------------- */

/** Keys that are structural, not decision-specific detail worth surfacing. */
const HIDDEN_KEYS = new Set([
  "id",
  "type",
  "start",
  "end",
  "duration",
  "reason",
  "confidence",
  "evidence",
  "track",
]);

function extraFields(event: TimelineEvent): { key: string; value: string }[] {
  return Object.entries(event)
    .filter(([k, v]) => !HIDDEN_KEYS.has(k) && v != null && typeof v !== "object")
    .map(([k, v]) => ({ key: humanize(k), value: String(v) }));
}

function EventInspector({ event }: { event: TimelineEvent | null }) {
  if (!event) {
    return (
      <Card>
        <p className="text-sm text-muted">
          Select any event on the timeline to see why it exists — its reason, confidence, and the
          evidence behind it.
        </p>
      </Card>
    );
  }
  const meta = eventMeta(event.type);
  const unknown = isUnknown(event);
  const evidence = evidenceText(event);
  const extras = extraFields(event);
  return (
    <Card>
      <div className="flex items-center gap-2">
        <span className={`h-3 w-3 shrink-0 rounded-sm ${meta.color}`} aria-hidden />
        <h4 className="text-sm font-semibold text-white">{meta.label}</h4>
      </div>

      <dl className="mt-4 space-y-3 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted">When</dt>
          <dd className="tabular-nums text-white">
            {meta.point
              ? formatTime(event.start)
              : `${formatTime(event.start)} – ${formatTime(event.end)}`}
          </dd>
        </div>
        {!meta.point && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Duration</dt>
            <dd className="tabular-nums text-white">{formatTime(event.duration)}</dd>
          </div>
        )}
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Confidence</dt>
          <dd className={unknown ? "text-amber-300" : "text-white"}>
            {formatConfidence(event.confidence)}
          </dd>
        </div>
        {extras.map((f) => (
          <div key={f.key} className="flex justify-between gap-4">
            <dt className="text-muted">{f.key}</dt>
            <dd className="min-w-0 truncate text-right text-white">{f.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 border-t border-white/10 pt-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Reason</p>
        <p className="mt-1 text-sm leading-relaxed text-white/90">
          {event.reason || "No reason was recorded."}
        </p>
      </div>

      {evidence && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Evidence</p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{evidence}</p>
        </div>
      )}

      {unknown && (
        <p className="mt-4 rounded-lg bg-amber-500/[0.06] px-3 py-2 text-xs leading-relaxed text-amber-200/90">
          The engine could not determine a confidence for this decision and is being honest about
          it rather than guessing.
        </p>
      )}
    </Card>
  );
}

/* ----------------------------- clip metadata ------------------------------ */

function clipTitle(timeline: Timeline): string {
  const title = timeline.metadata?.title;
  if (typeof title === "string" && title.trim()) return title;
  return timeline.clip_id;
}

function ClipMeta({ timeline }: { timeline: Timeline }) {
  const m = timeline.metadata ?? {};
  const chips: { label: string; value: string }[] = [];
  const push = (label: string, value: unknown) => {
    if (value != null && String(value).trim()) chips.push({ label, value: String(value) });
  };
  push("Aspect", m.aspect_ratio);
  push("Pacing", m.pacing);
  push("Captions", m.subtitle_style);
  push("Layout", m.caption_layout);
  push("Crop", m.crop);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted">
        {formatTime(timeline.duration)} long
      </span>
      <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted">
        {countEvents(timeline)} edits
      </span>
      {chips.map((c) => (
        <span key={c.label} className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted">
          {c.label}: <span className="text-white/80">{humanize(c.value)}</span>
        </span>
      ))}
    </div>
  );
}

/* --------------------------------- view ----------------------------------- */

export function EditingView({ editing }: { editing: Editing }) {
  const terminal = isTerminal(editing);
  const timelinesQuery = useTimelines(editing.project_id, terminal);
  const timelines = useMemo(
    () => timelinesQuery.data?.timelines ?? [],
    [timelinesQuery.data],
  );

  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [pxPerSecond, setPxPerSecond] = useState(24);
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);

  const validationReport =
    (editing.stages.find((s) => s.stage === "timeline_validation")?.data?.report as
      | Record<string, unknown>
      | undefined) ?? null;

  const initReason =
    (editing.stages.find((s) => s.stage === "timeline_initialization")?.reason as
      | string
      | undefined) ?? null;

  const selected =
    timelines.find((t) => t.clip_id === selectedClipId) ?? timelines[0] ?? null;

  // Still running / not yet assembled.
  if (!terminal || timelinesQuery.isLoading) {
    return (
      <Card>
        <p className="text-sm text-muted">Assembling edit timelines…</p>
      </Card>
    );
  }

  // Honest zero-timelines outcome.
  if (timelines.length === 0) {
    return (
      <EmptyState
        icon={<FilmIcon className="h-6 w-6" />}
        title="No edit timelines were assembled"
        description={
          initReason ??
          "The Editing Engine had no approved clip plans to turn into timelines. Once the Clip Planner proposes clips with a transcript present, their timelines will appear here."
        }
      />
    );
  }

  const zoomOut = () => setPxPerSecond((p) => clampZoom(p - 8));
  const zoomIn = () => setPxPerSecond((p) => clampZoom(p + 8));

  const selectClip = (clipId: string) => {
    setSelectedClipId(clipId);
    setSelectedEvent(null);
  };

  return (
    <div className="space-y-6">
      <ValidationBanner report={validationReport} />

      {/* Clip selector */}
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Clip timelines">
        {timelines.map((t) => {
          const active = selected?.clip_id === t.clip_id;
          return (
            <button
              key={t.clip_id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => selectClip(t.clip_id)}
              className={`rounded-lg border px-3 py-1.5 text-left text-sm transition-colors ${
                active
                  ? "border-accent bg-accent/5 text-white"
                  : "border-white/10 bg-white/[0.02] text-muted hover:border-white/20"
              }`}
            >
              <span className="text-[10px] uppercase tracking-wide text-muted">
                #{t.rank ?? "?"}
              </span>{" "}
              <span className="truncate">{clipTitle(t)}</span>
            </button>
          );
        })}
      </div>

      {selected && (
        <>
          {/* Header: clip meta + zoom control */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <ClipMeta timeline={selected} />
            <div className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-wide text-muted">Zoom</span>
              <button
                type="button"
                onClick={zoomOut}
                disabled={pxPerSecond <= 4}
                aria-label="Zoom out"
                className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-muted transition-colors hover:text-white disabled:opacity-40"
              >
                <MinusIcon className="h-4 w-4" />
              </button>
              <span className="w-14 text-center text-xs tabular-nums text-muted">
                {pxPerSecond} px/s
              </span>
              <button
                type="button"
                onClick={zoomIn}
                disabled={pxPerSecond >= 120}
                aria-label="Zoom in"
                className="flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-muted transition-colors hover:text-white disabled:opacity-40"
              >
                <PlusIcon className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Timeline + inspector */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <EditingTimeline
                timeline={selected}
                pxPerSecond={pxPerSecond}
                selectedEventId={selectedEvent?.id ?? null}
                onSelectEvent={setSelectedEvent}
              />
              <div className="mt-3 flex flex-wrap gap-3">
                {selected.tracks.map((track) => (
                  <span key={track.kind} className="flex items-center gap-1.5 text-[11px]">
                    <span className={`font-medium ${trackMeta(track.kind).accent}`}>
                      {trackMeta(track.kind).label}
                    </span>
                    <span className="text-muted">{track.events.length}</span>
                  </span>
                ))}
              </div>
            </div>
            <div className="lg:col-span-1">
              <EventInspector event={selectedEvent} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
