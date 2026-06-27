"use client";

/**
 * The Blueprint Viewer — the complete, executable editing instructions for one
 * plan. Nothing is hidden: every timestamp, cut, zoom, caption, transition, and
 * recommendation the planner produced is shown, each with its evidence. This is
 * a read-only inspection surface; it edits nothing.
 */
import {
  dimensionScores,
  formatDuration,
  formatPercent,
  formatTimestamp,
  humanize,
  scoreBand,
} from "@/lib/planning";
import type { ClipPlan } from "@/lib/types";

type Rec = Record<string, unknown>;

function rec(v: unknown): Rec {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : {};
}
function arr(v: unknown): Rec[] {
  return Array.isArray(v) ? v.map(rec) : [];
}
function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}
function numOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-white/[0.02] px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
      <div className="mt-1 text-sm text-white/90">{children}</div>
    </div>
  );
}

function TimedList({
  items,
  textKey = "reason",
  empty,
}: {
  items: Rec[];
  textKey?: string;
  empty: string;
}) {
  if (items.length === 0) return <p className="text-xs text-muted">{empty}</p>;
  return (
    <ul className="space-y-1">
      {items.map((it, i) => {
        const ts = numOrNull(it.timestamp ?? it.start);
        return (
          <li key={i} className="flex gap-2 text-xs text-white/80">
            {ts != null && (
              <span className="shrink-0 tabular-nums text-muted">{formatTimestamp(ts)}</span>
            )}
            <span>{str(it[textKey]) || str(it.text) || humanize(str(it.type))}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function BlueprintViewer({ plan }: { plan: ClipPlan }) {
  const bp = plan.blueprint ?? {};
  const hook = rec(bp.opening_hook);
  const payoff = rec(bp.closing_payoff);
  const title = rec(bp.title_suggestion);
  const subtitle = rec(bp.subtitle_style);
  const aspect = rec(bp.aspect_ratio);
  const pacing = rec(bp.pacing);
  const sceneCuts = rec(bp.scene_cuts);
  const speakers = rec(bp.speaker_switches);
  const camera = rec(bp.camera_focus);
  const continuation = rec(bp.continuation_possibility);
  const complexity = rec(bp.estimated_complexity);
  const platforms = rec(bp.platform_suitability);
  const captions = arr(bp.caption_timing);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted">
            {plan.rank ? `Rank #${plan.rank} · ` : ""}Editing blueprint
          </p>
          <h3 className="text-base font-semibold text-white">{str(title.text) || plan.id}</h3>
          <p className="mt-0.5 text-xs text-muted">
            {formatTimestamp(plan.start)} – {formatTimestamp(plan.end)} ·{" "}
            {formatDuration(plan.duration)} · frames {plan.start_frame ?? "—"}–
            {plan.end_frame ?? "—"} @ {plan.fps ?? "—"}fps
          </p>
        </div>
        <div className="text-right">
          <p className={`text-2xl font-semibold tabular-nums ${scoreBand(plan.quality_score).className}`}>
            {formatPercent(plan.quality_score)}
          </p>
          <p className="text-[11px] text-muted">confidence {formatPercent(plan.confidence)}</p>
        </div>
      </div>

      {plan.explanation && (
        <p className="rounded-lg bg-white/[0.03] px-3 py-2 text-xs leading-relaxed text-white/75">
          {plan.explanation}
        </p>
      )}

      {/* Quality scores */}
      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
          Quality dimensions
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {dimensionScores(plan).map((d) => (
            <div key={d.key} className="rounded-lg bg-white/[0.02] px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted">{d.label}</span>
                <span
                  className={`text-sm font-medium tabular-nums ${
                    d.value == null ? "text-muted" : scoreBand(d.value).className
                  }`}
                >
                  {formatPercent(d.value)}
                </span>
              </div>
              {d.value != null && (
                <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-white/5">
                  <div className="h-full rounded-full bg-accent" style={{ width: formatPercent(d.value) }} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Narrative anchors */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Field label="Opening hook">
          <span className="italic">“{str(hook.text) || "—"}”</span>
          <p className="mt-0.5 text-[11px] text-muted">{str(hook.evidence)}</p>
        </Field>
        <Field label="Closing payoff">
          <span className="italic">“{str(payoff.text) || "—"}”</span>
          <p className="mt-0.5 text-[11px] text-muted">{str(payoff.evidence)}</p>
        </Field>
      </div>

      {/* Presentation */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Field label="Title">{str(title.text) || "—"}</Field>
        <Field label="Aspect ratio">
          {str(aspect.value) || "—"}
          <p className="mt-0.5 text-[11px] text-muted">{str(aspect.reason)}</p>
        </Field>
        <Field label="Pacing">{str(pacing.value) || "—"}</Field>
        <Field label="Subtitles">{str(subtitle.style) || "—"}</Field>
      </div>

      {/* Edit instructions */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Section title="Caption timing">
          {captions.length > 0 ? (
            <ul className="max-h-48 space-y-1 overflow-y-auto pr-1">
              {captions.map((c, i) => (
                <li key={i} className="flex gap-2 text-xs text-white/80">
                  <span className="shrink-0 tabular-nums text-muted">
                    {formatTimestamp(numOrNull(c.start))}
                  </span>
                  <span>{str(c.text)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">No transcript captions in this window.</p>
          )}
        </Section>
        <Section title="Silence removal">
          <TimedList items={arr(bp.silence_removal)} empty="No silences to trim." />
        </Section>
        <Section title="Jump cuts">
          <TimedList items={arr(bp.jump_cuts)} empty="No jump cuts suggested." />
        </Section>
        <Section title="Zoom suggestions">
          <TimedList items={arr(bp.zoom_suggestions)} empty="No zooms suggested." />
        </Section>
        <Section title="Emphasis moments">
          <TimedList items={arr(bp.emphasis_moments)} empty="None detected." />
        </Section>
        <Section title="Replay moments">
          <TimedList items={arr(bp.replay_moments)} empty="None detected." />
        </Section>
        <Section title="Retention risks">
          <TimedList items={arr(bp.retention_risks)} textKey="reason" empty="No notable risks." />
        </Section>
        <Section title="Scene cuts">
          <TimedList items={arr(sceneCuts.cuts)} empty={str(sceneCuts.note) || "None."} />
        </Section>
        <Section title="Speaker switches">
          <TimedList items={arr(speakers.switches)} textKey="speaker" empty={str(speakers.note) || "None."} />
        </Section>
        <Section title="Camera focus">
          <p className="text-xs text-white/80">{str(camera.value)}</p>
          <p className="mt-0.5 text-[11px] text-muted">{str(camera.reason)}</p>
        </Section>
      </div>

      {/* Platform suitability */}
      <Section title="Platform suitability">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {["youtube_shorts", "tiktok", "instagram_reels"].map((key) => {
            const p = rec(platforms[key]);
            const label = { youtube_shorts: "YouTube Shorts", tiktok: "TikTok", instagram_reels: "Instagram Reels" }[key];
            return (
              <div key={key} className="rounded-lg bg-white/[0.02] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-white">{label}</span>
                  <span className={`text-sm font-medium tabular-nums ${scoreBand(numOrNull(p.score) ?? 0).className}`}>
                    {formatPercent(numOrNull(p.score))}
                  </span>
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-muted">{str(p.reason)}</p>
              </div>
            );
          })}
        </div>
      </Section>

      {/* Logistics */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Field label="Continuation possibility">
          {continuation.possible ? "Possible (part 2)" : "Not indicated"}
          <p className="mt-0.5 text-[11px] text-muted">{str(continuation.reason)}</p>
        </Field>
        <Field label="Estimated editing complexity">
          {humanize(str(complexity.level) || "—")} ({formatPercent(numOrNull(complexity.score))})
        </Field>
      </div>

      {plan.alternatives.length > 0 && (
        <Section title="Merged alternatives (overlapping moments)">
          <ul className="space-y-1 text-xs text-muted">
            {plan.alternatives.map((a, i) => {
              const alt = rec(a);
              return (
                <li key={i}>
                  {str(alt.id)} · overlap {formatPercent(numOrNull(alt.iou))} · quality{" "}
                  {formatPercent(numOrNull(alt.quality_score))}
                </li>
              );
            })}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</p>
      {children}
    </div>
  );
}
