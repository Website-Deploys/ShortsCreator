"use client";

/**
 * The Story Timeline — a read-only visualization of the narrative.
 *
 * Narrative sections are drawn as proportional, colour-coded segments along a
 * single time track. Topic shifts, emotional turning points, payoffs, and
 * context dependencies are overlaid as markers at their real timestamps.
 * Hovering any segment or marker reveals its details and confidence. Everything
 * is derived from the backend's genuine output; when a signal is unavailable it
 * simply doesn't appear (the panel says so honestly) — nothing is invented.
 */
import {
  confidenceBand,
  formatConfidence,
  formatTimestamp,
  parseContextRefs,
  parseEmotionTurns,
  parsePayoffs,
  parseSections,
  parseTopics,
  roleMeta,
} from "@/lib/story";
import type { Story } from "@/lib/types";

const ROLE_LEGEND = [
  "hook",
  "introduction",
  "problem",
  "conflict",
  "explanation",
  "example",
  "resolution",
  "ending",
];

function pct(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, (value / total) * 100));
}

function Tooltip({ children }: { children: React.ReactNode }) {
  return (
    <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden -translate-x-1/2 group-hover:block">
      <div className="w-56 rounded-lg border border-white/10 bg-[#15161c] p-3 text-left shadow-xl">
        {children}
      </div>
    </div>
  );
}

export function StoryTimeline({
  story,
  durationSeconds,
}: {
  story: Story;
  durationSeconds?: number | null;
}) {
  const sections = parseSections(story);
  const topics = parseTopics(story);
  const payoffs = parsePayoffs(story);
  const { turns } = parseEmotionTurns(story);
  const refs = parseContextRefs(story).filter((r) => r.dependsOnTimestamp != null);

  if (sections.length === 0) {
    return (
      <p className="text-sm text-muted">
        The narrative timeline becomes available once the story has been segmented
        (which requires a transcript). See the stages above for the current status.
      </p>
    );
  }

  const total = Math.max(
    durationSeconds || 0,
    sections[sections.length - 1].end,
    ...topics.map((t) => t.timestamp),
    ...payoffs.map((p) => p.payoffTimestamp),
  );

  return (
    <div className="space-y-4">
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {ROLE_LEGEND.map((role) => (
          <span key={role} className="flex items-center gap-1.5 text-[11px] text-muted">
            <span className={`h-2 w-2 rounded-full ${roleMeta(role).color}`} />
            {roleMeta(role).label}
          </span>
        ))}
      </div>

      {/* Narrative track */}
      <div className="relative h-12 w-full overflow-visible rounded-lg bg-white/[0.03]">
        {sections.map((s) => {
          const left = pct(s.start, total);
          const width = Math.max(1.5, pct(s.end - s.start, total));
          const meta = roleMeta(s.role);
          return (
            <div
              key={s.index}
              className="group absolute top-0 h-full"
              style={{ left: `${left}%`, width: `${width}%` }}
            >
              <div
                className={`h-full w-full ${meta.color} cursor-default border-r border-black/30 opacity-80 transition-opacity hover:opacity-100`}
                role="img"
                aria-label={`${meta.label} from ${formatTimestamp(s.start)} to ${formatTimestamp(s.end)}`}
              />
              <Tooltip>
                <p className="flex items-center gap-1.5 text-xs font-semibold text-white">
                  <span className={`h-2 w-2 rounded-full ${meta.color}`} />
                  {meta.label}
                </p>
                <p className="mt-1 text-[11px] text-muted">
                  {formatTimestamp(s.start)} – {formatTimestamp(s.end)} ·{" "}
                  {formatConfidence(s.confidence)} confidence
                </p>
                {s.excerpt && (
                  <p className="mt-1.5 line-clamp-3 text-[11px] leading-relaxed text-white/70">
                    “{s.excerpt}”
                  </p>
                )}
              </Tooltip>
            </div>
          );
        })}
      </div>

      {/* Marker rows */}
      <MarkerRow label="Topic shifts" total={total} color="bg-sky-400"
        markers={topics.map((t) => ({
          at: t.timestamp,
          title: "Topic shift",
          detail: `${t.oldTopic.slice(0, 3).join(", ") || "—"} → ${t.newTopic.slice(0, 3).join(", ") || "—"}`,
          confidence: t.confidence,
        }))}
      />
      <MarkerRow label="Emotional shifts" total={total} color="bg-amber-400"
        markers={turns.map((t) => ({
          at: t.timestamp,
          title: "Emotional shift",
          detail: `${t.previous} → ${t.next}`,
          confidence: t.confidence,
        }))}
      />
      <MarkerRow label="Payoffs" total={total} color="bg-emerald-400"
        markers={payoffs.map((p) => ({
          at: p.payoffTimestamp,
          title: "Payoff",
          detail: p.payoffExcerpt || p.type,
          confidence: p.confidence,
        }))}
      />
      <MarkerRow label="Dependencies" total={total} color="bg-fuchsia-400"
        markers={refs.map((r) => ({
          at: r.fromTimestamp,
          title: "Context dependency",
          detail: `Relies on ${formatTimestamp(r.dependsOnTimestamp)}${r.term ? ` · “${r.term}”` : ""}`,
          confidence: r.confidence,
        }))}
      />

      {/* Time axis */}
      <div className="flex justify-between text-[11px] tabular-nums text-muted">
        <span>0:00</span>
        <span>{formatTimestamp(total / 2)}</span>
        <span>{formatTimestamp(total)}</span>
      </div>
    </div>
  );
}

interface Marker {
  at: number;
  title: string;
  detail: string;
  confidence: number;
}

function MarkerRow({
  label,
  markers,
  total,
  color,
}: {
  label: string;
  markers: Marker[];
  total: number;
  color: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 text-[11px] uppercase tracking-wide text-muted">{label}</span>
      <div className="relative h-5 flex-1">
        <span aria-hidden className="absolute top-1/2 h-px w-full -translate-y-1/2 bg-white/8" />
        {markers.length === 0 && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 text-[11px] text-muted/60">
            none detected
          </span>
        )}
        {markers.map((m, i) => (
          <div
            key={i}
            className="group absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${pct(m.at, total)}%` }}
          >
            <span
              className={`block h-2.5 w-2.5 rounded-full ${color} ring-2 ring-[#0d0e12]`}
              role="img"
              aria-label={`${m.title} at ${formatTimestamp(m.at)}`}
            />
            <Tooltip>
              <p className="text-xs font-semibold text-white">{m.title}</p>
              <p className="mt-0.5 text-[11px] text-muted">
                {formatTimestamp(m.at)} · {formatConfidence(m.confidence)} confidence
              </p>
              <p className="mt-1.5 line-clamp-3 text-[11px] leading-relaxed text-white/70">
                {m.detail}
              </p>
              <span
                className={`mt-1.5 inline-block rounded px-1.5 py-0.5 text-[10px] ${confidenceBand(m.confidence).className}`}
              >
                {confidenceBand(m.confidence).label} confidence
              </span>
            </Tooltip>
          </div>
        ))}
      </div>
    </div>
  );
}
