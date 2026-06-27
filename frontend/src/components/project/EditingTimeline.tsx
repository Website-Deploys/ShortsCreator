"use client";

/**
 * The Editing timeline — a professional, read-only, horizontal NLE-style track
 * view (like Premiere/Resolve). Zoomable (pixels-per-second) and scrollable,
 * with Video / Audio / Subtitle / Markers lanes. Span events render as blocks;
 * point events render as pins. Clicking any event selects it so the inspector
 * can explain *why* it exists, with its confidence and evidence. Nothing is
 * editable - this only visualizes the edit decision list.
 */
import {
  eventMeta,
  formatTime,
  rulerTicks,
  timelineWidth,
  timeToX,
  TRACK_ORDER,
  trackMeta,
} from "@/lib/editing";
import type { Timeline, TimelineEvent } from "@/lib/types";

const LANE_HEIGHT = 44;
const LABEL_WIDTH = 92;

function EventBlock({
  event,
  pxPerSecond,
  selected,
  onSelect,
}: {
  event: TimelineEvent;
  pxPerSecond: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const meta = eventMeta(event.type);
  const left = timeToX(event.start, pxPerSecond);
  if (meta.point) {
    return (
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        title={`${meta.label} @ ${formatTime(event.start)}`}
        aria-label={`${meta.label} at ${formatTime(event.start)}`}
        className="absolute top-1 bottom-1 -translate-x-1/2"
        style={{ left }}
      >
        <span
          className={`block h-full w-[3px] rounded-full ${meta.color} ${
            selected ? "ring-2 ring-white" : ""
          }`}
        />
      </button>
    );
  }
  const width = Math.max(3, timeToX(event.duration, pxPerSecond));
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      title={`${meta.label}: ${formatTime(event.start)}–${formatTime(event.end)}`}
      aria-label={`${meta.label} from ${formatTime(event.start)} to ${formatTime(event.end)}`}
      className={`absolute top-1.5 bottom-1.5 overflow-hidden rounded ${meta.color} px-1 text-left text-[10px] text-white/90 ${
        selected ? "ring-2 ring-white" : "ring-1 ring-black/20"
      }`}
      style={{ left, width }}
    >
      <span className="block truncate leading-[1.9]">{meta.label}</span>
    </button>
  );
}

export function EditingTimeline({
  timeline,
  pxPerSecond,
  selectedEventId,
  onSelectEvent,
}: {
  timeline: Timeline;
  pxPerSecond: number;
  selectedEventId: string | null;
  onSelectEvent: (event: TimelineEvent) => void;
}) {
  const width = Math.max(240, timelineWidth(timeline.duration, pxPerSecond));
  const ticks = rulerTicks(timeline.duration, pxPerSecond);
  const tracks = TRACK_ORDER.map((kind) => ({
    kind,
    events: timeline.tracks.find((t) => t.kind === kind)?.events ?? [],
  }));

  return (
    <div className="flex rounded-xl border border-white/10 bg-[#0d0e12]">
      {/* Fixed track labels */}
      <div className="shrink-0 border-r border-white/10" style={{ width: LABEL_WIDTH }}>
        <div className="h-6 border-b border-white/10" />
        {tracks.map((t) => (
          <div
            key={t.kind}
            className="flex items-center border-b border-white/5 px-3 last:border-b-0"
            style={{ height: LANE_HEIGHT }}
          >
            <span className={`text-[11px] font-medium ${trackMeta(t.kind).accent}`}>
              {trackMeta(t.kind).label}
            </span>
          </div>
        ))}
      </div>

      {/* Scrollable track area */}
      <div className="min-w-0 flex-1 overflow-x-auto">
        <div style={{ width }}>
          {/* Ruler */}
          <div className="relative h-6 border-b border-white/10">
            {ticks.map((t) => (
              <div
                key={t}
                className="absolute top-0 flex h-full items-center"
                style={{ left: timeToX(t, pxPerSecond) }}
              >
                <span className="border-l border-white/10 pl-1 text-[10px] tabular-nums text-muted">
                  {formatTime(t)}
                </span>
              </div>
            ))}
          </div>
          {/* Lanes */}
          {tracks.map((t) => (
            <div
              key={t.kind}
              className="relative border-b border-white/5 last:border-b-0"
              style={{ height: LANE_HEIGHT }}
            >
              {ticks.map((tick) => (
                <span
                  key={tick}
                  aria-hidden
                  className="absolute top-0 h-full w-px bg-white/[0.04]"
                  style={{ left: timeToX(tick, pxPerSecond) }}
                />
              ))}
              {t.events.length === 0 && (
                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-[10px] text-muted/50">
                  none
                </span>
              )}
              {t.events.map((event) => (
                <EventBlock
                  key={event.id}
                  event={event}
                  pxPerSecond={pxPerSecond}
                  selected={event.id === selectedEventId}
                  onSelect={() => onSelectEvent(event)}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
