"use client";

/**
 * Evidence, timeline and canonical event presentation.
 *
 * Events are canonical only. Control and heartbeat frames are never displayed as
 * work, and progress is shown only when the owning module supplied real counters.
 */

import {
  isWorkEvent,
  realProgress,
  type ReviewEvent,
  type ReviewSourceCard,
} from "@/lib/reviewUi";
import { BobaReviewSourceCard } from "@/components/project/BobaReviewStatusMatrix";

export function BobaReviewEvidenceDrawer({
  open,
  cards,
  focusModule,
  onClose,
}: {
  open: boolean;
  cards: ReviewSourceCard[];
  focusModule: string | null;
  onClose: () => void;
}) {
  if (!open) return null;
  const ordered = focusModule
    ? [...cards].sort((a, b) =>
        a.source_module_id === focusModule ? -1 : b.source_module_id === focusModule ? 1 : 0,
      )
    : cards;
  return (
    <aside
      aria-labelledby="review-evidence-heading"
      className="space-y-3 rounded-lg border border-white/10 bg-black/20 p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 id="review-evidence-heading" className="text-sm font-semibold text-white/90">
          EVIDENCE
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="min-h-[44px] rounded px-2 text-xs text-white/70 underline underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 sm:min-h-0"
        >
          Close evidence
        </button>
      </div>
      <p className="text-xs text-white/60">
        Evidence references canonical owner records. It does not copy reports, media or logs.
      </p>
      <div className="space-y-2">
        {ordered.length === 0 && (
          <p className="text-xs text-white/55">No canonical evidence is available.</p>
        )}
        {ordered.map((card) => (
          <BobaReviewSourceCard key={card.source_card_id} card={card} />
        ))}
      </div>
    </aside>
  );
}

export function BobaReviewTimeline({ events }: { events: ReviewEvent[] }) {
  const work = events.filter(isWorkEvent);
  return (
    <section aria-labelledby="review-timeline-heading" className="space-y-2">
      <h3 id="review-timeline-heading" className="text-sm font-semibold text-white/90">
        CANONICAL TIMELINE
      </h3>
      {work.length === 0 ? (
        <p className="text-xs text-white/55">
          No canonical events have been reported for this project.
        </p>
      ) : (
        <ol className="space-y-2">
          {work.map((event) => {
            const progress = realProgress(event);
            return (
              <li
                key={event.ui_event_id}
                className="rounded-md border border-white/10 bg-white/[0.02] p-2 text-xs"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium text-white/85">
                    {event.event_type.replace(/_/g, " ")}
                  </span>
                  <span className="font-mono text-[10px] text-white/45">
                    {event.source_module_id}
                    {typeof event.source_sequence === "number" ? ` #${event.source_sequence}` : ""}
                  </span>
                </div>
                <p className="mt-1 text-white/70">{event.easy_message || event.technical_message}</p>
                {event.confirmed_fact && (
                  <p className="mt-0.5 text-white/55">Confirmed: {event.confirmed_fact}</p>
                )}
                {event.assessment && (
                  <p className="mt-0.5 text-white/55">Source assessment: {event.assessment}</p>
                )}
                <p className="mt-0.5 text-[10px] text-white/40">
                  {event.created_at ?? "Timestamp not reported by the source"}
                </p>
                {progress !== null && (
                  <p className="mt-0.5 text-[11px] text-white/60">
                    Reported progress: {progress.toFixed(0)}% ({event.progress_current} of{" "}
                    {event.progress_total})
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export function BobaReviewEventStream({
  events,
  connected,
  onReconnect,
}: {
  events: ReviewEvent[];
  connected: boolean;
  onReconnect: () => void;
}) {
  const work = events.filter(isWorkEvent);
  return (
    <section aria-labelledby="review-events-heading" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 id="review-events-heading" className="text-sm font-semibold text-white/90">
          LIVE CANONICAL EVENTS
        </h3>
        <button
          type="button"
          onClick={onReconnect}
          className="min-h-[44px] rounded px-2 text-xs text-sky-200 underline underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 sm:min-h-0"
        >
          Reconnect
        </button>
      </div>
      <p aria-live="polite" role="status" className="text-xs">
        {connected ? (
          <span className="text-emerald-100">
            <span aria-hidden="true" className="font-mono">[live]</span> Connected to canonical
            events.
          </span>
        ) : (
          <span className="text-amber-100">
            <span aria-hidden="true" className="font-mono">[offline]</span> Live updates
            disconnected. Records shown may be behind.
          </span>
        )}
      </p>
      <p className="text-[11px] text-white/50">
        Idle and keep-alive frames are not work and are never shown as activity.
      </p>
      <p className="text-xs text-white/65">{work.length} canonical events retained.</p>
    </section>
  );
}
