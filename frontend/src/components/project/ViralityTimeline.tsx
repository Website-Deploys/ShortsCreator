"use client";

/**
 * The Virality Timeline + Heatmap — a read-only visualization of where the video
 * is likely to perform.
 *
 * The heatmap intensity is the backend's real per-window heat (information
 * density + emotional activity + payoff presence + early hook) — not fake
 * colours. The timeline overlays where interest rises/falls, emotion spikes,
 * conflict appears, curiosity opens, payoffs land, and attention weakens. Click
 * any marker to inspect *why* it is there, with its confidence. When a transcript
 * is unavailable the heatmap is intentionally empty and says so honestly.
 */
import { useState } from "react";

import {
  confidenceBand,
  eventMeta,
  formatPercent,
  formatTimestamp,
  heatStyle,
  type TimelineEvent,
  type ViralitySummaryView,
} from "@/lib/virality";

function pct(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, (value / total) * 100));
}

export function ViralityTimeline({
  summary,
  durationSeconds,
}: {
  summary: ViralitySummaryView;
  durationSeconds?: number | null;
}) {
  const [selected, setSelected] = useState<number | null>(null);

  const total = Math.max(
    durationSeconds || 0,
    ...summary.heatmap.map((c) => c.end),
    ...summary.timeline.map((e) => e.timestamp),
    1,
  );

  return (
    <div className="space-y-5">
      {/* Heatmap */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Engagement heatmap
          </h4>
          <div className="flex items-center gap-1.5 text-[11px] text-muted">
            <span>cool</span>
            <span className="h-2 w-16 rounded-full" style={{
              backgroundImage: "linear-gradient(to right, hsl(220 35% 22%), hsl(110 60% 38%), hsl(12 90% 48%))",
            }} />
            <span>hot</span>
          </div>
        </div>
        {summary.heatmap.length > 0 ? (
          <div className="relative h-9 w-full overflow-hidden rounded-lg bg-white/[0.03]">
            {summary.heatmap.map((cell, i) => {
              const left = pct(cell.start, total);
              const width = Math.max(0.5, pct(cell.end - cell.start, total));
              return (
                <div
                  key={i}
                  className="group absolute top-0 h-full"
                  style={{ left: `${left}%`, width: `${width}%` }}
                >
                  <div
                    className="h-full w-full border-r border-black/20"
                    style={heatStyle(cell.heat)}
                    role="img"
                    aria-label={`Heat ${formatPercent(cell.heat)} at ${formatTimestamp(cell.start)}`}
                  />
                  <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden -translate-x-1/2 group-hover:block">
                    <div className="w-52 rounded-lg border border-white/10 bg-[#15161c] p-3 text-left shadow-xl">
                      <p className="text-xs font-semibold text-white">
                        Heat {formatPercent(cell.heat)}
                      </p>
                      <p className="mt-0.5 text-[11px] text-muted">
                        {formatTimestamp(cell.start)} – {formatTimestamp(cell.end)}
                      </p>
                      <ul className="mt-1.5 space-y-0.5 text-[11px] text-white/70">
                        <li>density {formatPercent(cell.components.density)}</li>
                        <li>emotion {cell.components.emotion ? "yes" : "no"}</li>
                        <li>payoff {cell.components.payoff ? "yes" : "no"}</li>
                        <li>hook {cell.components.hook ? "yes" : "no"}</li>
                      </ul>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] px-3 py-3 text-xs text-muted">
            {summary.heatmapNote || "No heatmap is available yet."}
          </p>
        )}
      </div>

      {/* Timeline markers */}
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
          Moments — click any marker to see why
        </h4>
        {summary.timeline.length > 0 ? (
          <>
            <div className="relative h-6">
              <span aria-hidden className="absolute top-1/2 h-px w-full -translate-y-1/2 bg-white/10" />
              {summary.timeline.map((event, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setSelected(selected === i ? null : i)}
                  aria-label={`${event.label} at ${formatTimestamp(event.timestamp)}`}
                  aria-pressed={selected === i}
                  className="group absolute top-1/2 -translate-x-1/2 -translate-y-1/2 p-1"
                  style={{ left: `${pct(event.timestamp, total)}%` }}
                >
                  <span
                    className={`block h-3 w-3 rounded-full ${eventMeta(event.type).color} ring-2 transition-transform group-hover:scale-125 ${
                      selected === i ? "ring-white" : "ring-[#0d0e12]"
                    }`}
                  />
                </button>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-[11px] tabular-nums text-muted">
              <span>0:00</span>
              <span>{formatTimestamp(total)}</span>
            </div>
            {selected !== null && summary.timeline[selected] && (
              <EventDetail event={summary.timeline[selected]} />
            )}
          </>
        ) : (
          <p className="text-xs text-muted">
            Timeline moments become available once the story signals (hook, emotion,
            payoffs, pacing) have been derived from a transcript.
          </p>
        )}
      </div>
    </div>
  );
}

function EventDetail({ event }: { event: TimelineEvent }) {
  const band = confidenceBand(event.confidence);
  return (
    <div className="mt-3 animate-fade-in rounded-lg border border-white/10 bg-white/[0.03] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${eventMeta(event.type).color}`} />
        <span className="text-sm font-medium text-white">{event.label}</span>
        <span className="text-xs text-muted">at {formatTimestamp(event.timestamp)}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${band.className}`}>
          {band.label} · {formatPercent(event.confidence)}
        </span>
      </div>
      {event.detail && <p className="mt-1.5 text-xs leading-relaxed text-white/75">{event.detail}</p>}
    </div>
  );
}
