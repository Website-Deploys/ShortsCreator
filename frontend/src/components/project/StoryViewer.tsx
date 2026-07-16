"use client";

/**
 * The Story Viewer — a read-only window into what Olympus understands about the
 * narrative: the summary, hook, arc, payoffs, emotional journey, topics, and
 * context dependencies.
 *
 * Every section renders the backend's genuine, evidence-backed output with its
 * confidence. When a stage lacks the inputs it needs, the section shows an
 * honest "not available yet" panel with the backend's reason and a re-run
 * action — it never invents a narrative. No editing happens here.
 */
import type { ReactNode } from "react";

import {
  ActivityIcon,
  AlertIcon,
  BookIcon,
  ClockIcon,
  FlagIcon,
  LayersIcon,
  LinkIcon,
  MinusCircleIcon,
  RefreshIcon,
  SparklesIcon,
} from "@/components/icons";
import { Card } from "@/components/ui/Card";
import { useRerunStoryStage } from "@/lib/queries";
import {
  confidenceBand,
  formatConfidence,
  formatTimestamp,
  getStage,
  humanizeArc,
  hookTypeLabel,
  parseContextRefs,
  parseEmotionTurns,
  parseHook,
  parsePayoffs,
  parseStoryV2,
  parseSummary,
  parseTopics,
  roleMeta,
} from "@/lib/story";
import type { Story } from "@/lib/types";

function ConfidenceChip({ value }: { value: number }) {
  const band = confidenceBand(value);
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${band.className}`}>
      {band.label} · {formatConfidence(value)}
    </span>
  );
}

function Section({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <div className="mb-4 flex items-center gap-2.5">
        <span className="text-muted">{icon}</span>
        <h3 className="text-sm font-semibold text-white">{title}</h3>
      </div>
      {children}
    </Card>
  );
}

/** Honest panel when a story stage produced no output. */
function Unavailable({ story, stageName }: { story: Story; stageName: string }) {
  const rerun = useRerunStoryStage(story.project_id);
  const stage = getStage(story, stageName);
  if (!stage) return <p className="text-sm text-muted">This signal has not been analyzed yet.</p>;
  const failed = stage.status === "failed";
  const pendingState = stage.status === "pending" || stage.status === "running";
  const Icon = failed ? AlertIcon : pendingState ? ClockIcon : MinusCircleIcon;
  const heading = failed
    ? "This stage encountered an error"
    : pendingState
      ? "Not analyzed yet"
      : "Not available yet";
  return (
    <div className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${failed ? "text-red-300" : "text-muted"}`} />
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-medium ${failed ? "text-red-200" : "text-white/80"}`}>
            {heading}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {stage.reason ?? stage.error ?? "No additional detail is available."}
          </p>
        </div>
        {(failed || stage.status === "unavailable") && (
          <button
            type="button"
            onClick={() => rerun.mutate(stage.stage)}
            disabled={rerun.isPending}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted transition-colors hover:bg-white/5 hover:text-white disabled:opacity-50"
          >
            <RefreshIcon className={`h-3.5 w-3.5 ${rerun.isPending ? "animate-spin" : ""}`} />
            Re-run
          </button>
        )}
      </div>
    </div>
  );
}

function isCompleted(story: Story, name: string): boolean {
  return getStage(story, name)?.status === "completed";
}

function Chips({ items, tone = "default" }: { items: string[]; tone?: "default" | "accent" }) {
  if (items.length === 0) return <span className="text-sm text-muted">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span
          key={`${item}-${i}`}
          className={`rounded-full px-2.5 py-1 text-xs ${
            tone === "accent" ? "bg-accent/10 text-accent" : "bg-white/5 text-white/80"
          }`}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

export function StoryViewer({ story }: { story: Story }) {
  const summary = parseSummary(story);
  const storyV2 = parseStoryV2(story);
  const hook = parseHook(story);
  const payoffs = parsePayoffs(story);
  const { method, turns } = parseEmotionTurns(story);
  const topics = parseTopics(story);
  const refs = parseContextRefs(story);
  const arc = getStage(story, "narrative_arc");
  const arcData = arc?.status === "completed" ? (arc.data ?? {}) : null;

  return (
    <div className="space-y-6">
      {/* Summary */}
      <Section icon={<SparklesIcon className="h-4 w-4" />} title="Story summary">
        {summary ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted">Overall confidence</span>
              <ConfidenceChip value={summary.confidence} />
              {summary.pendingSignals.length > 0 && (
                <span className="text-[11px] text-muted">
                  · {summary.pendingSignals.length} signal(s) still pending
                </span>
              )}
            </div>
            <Field label="Main subject">
              <Chips items={summary.mainSubject} tone="accent" />
            </Field>
            <Field label="Narrative arc">
              <span className="text-sm text-white">{humanizeArc(summary.arcType)}</span>
            </Field>
            {summary.keyLessons.length > 0 && (
              <Field label="Key lessons">
                <ul className="space-y-1.5">
                  {summary.keyLessons.map((lesson, i) => (
                    <li key={i} className="text-sm leading-relaxed text-white/85">
                      “{lesson}”
                    </li>
                  ))}
                </ul>
              </Field>
            )}
            {summary.importantMoments.length > 0 && (
              <Field label="Important moments">
                <div className="flex flex-wrap gap-2">
                  {summary.importantMoments.map((m, i) => (
                    <span
                      key={i}
                      className="flex items-center gap-1.5 rounded-md bg-white/5 px-2 py-1 text-xs text-white/80"
                    >
                      <FlagIcon className="h-3 w-3 text-muted" />
                      {m.type.replace(/_/g, " ")} · {formatTimestamp(m.timestamp)}
                    </span>
                  ))}
                </div>
              </Field>
            )}
          </div>
        ) : (
          <Unavailable story={story} stageName="story_summary" />
        )}
      </Section>

      {/* Story V2 */}
      <Section icon={<SparklesIcon className="h-4 w-4" />} title="Story intelligence V2">
        {storyV2 ? (
          <div className="space-y-4">
            <div className="grid gap-2 text-xs text-muted sm:grid-cols-4">
              <span>Topics: {storyV2.topicCount}</span>
              <span>Micro-stories: {storyV2.microStoryCount}</span>
              <span>Recommended: {storyV2.recommendedCount}</span>
              <span>Avg completeness: {formatConfidence(storyV2.averageCompleteness)}</span>
            </div>
            {storyV2.topStories.length > 0 ? (
              <ul className="space-y-3">
                {storyV2.topStories.map((item) => (
                  <li key={item.storyId} className="rounded-lg bg-white/[0.03] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium text-white">{item.title}</p>
                      <ConfidenceChip value={item.completeness} />
                    </div>
                    <p className="mt-1 text-xs text-muted">
                      {item.storyShape.replace(/_/g, " ")} Â· {formatTimestamp(item.start)}
                      â€“{formatTimestamp(item.end)} Â· context risk{" "}
                      {formatConfidence(item.contextRisk)}
                    </p>
                    {item.tension && (
                      <p className="mt-2 text-xs text-white/80">Tension: {item.tension}</p>
                    )}
                    {item.payoff && (
                      <p className="mt-1 text-xs text-white/80">Payoff: â€œ{item.payoff}â€</p>
                    )}
                    <p className="mt-1 text-xs text-muted">
                      Ending: {item.endingReason || "evaluated"} Â· Boundary:{" "}
                      {item.boundaryReason}
                    </p>
                    {item.warning && (
                      <p className="mt-2 rounded border border-amber-400/20 bg-amber-400/10 px-2 py-1 text-xs text-amber-100">
                        Warning: {item.warning}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">
                No complete recommended micro-stories passed V2 story checks.
              </p>
            )}
            {storyV2.warnings.length > 0 && (
              <div className="rounded-lg border border-amber-400/20 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
                {storyV2.warnings.join(" ")}
              </div>
            )}
          </div>
        ) : (
          <Unavailable story={story} stageName="story_analysis_v2" />
        )}
      </Section>

      {/* Hook */}
      <Section icon={<FlagIcon className="h-4 w-4" />} title="Opening hook">
        {hook ? (
          hook.hasHook ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-fuchsia-500/15 px-2.5 py-1 text-xs font-medium text-fuchsia-300">
                  {hookTypeLabel(hook.hookType)}
                </span>
                <ConfidenceChip value={hook.confidence} />
              </div>
              {hook.why && <p className="text-sm text-white/85">{hook.why}</p>}
              {hook.excerpt && (
                <p className="rounded-lg bg-white/[0.03] px-3 py-2 text-xs italic leading-relaxed text-white/70">
                  “{hook.excerpt}”
                </p>
              )}
            </div>
          ) : (
            <div className="flex items-start gap-3">
              <MinusCircleIcon className="mt-0.5 h-5 w-5 shrink-0 text-muted" />
              <div>
                <p className="text-sm font-medium text-white/80">No strong hook detected</p>
                <p className="mt-1 text-xs text-muted">{hook.reason}</p>
              </div>
            </div>
          )
        ) : (
          <Unavailable story={story} stageName="hook_detection" />
        )}
      </Section>

      {/* Narrative arc */}
      <Section icon={<BookIcon className="h-4 w-4" />} title="Narrative arc">
        {arcData ? (
          <div className="space-y-3">
            <p className="text-sm text-white">{humanizeArc(String(arcData.arc_type ?? ""))}</p>
            <div className="flex flex-wrap gap-2 text-xs">
              <Tag on={arcData.has_setup === true}>Setup</Tag>
              <Tag on={arcData.has_conflict === true}>Conflict</Tag>
              <Tag on={arcData.has_resolution === true}>Resolution</Tag>
            </div>
            <Field label="Role sequence">
              <div className="flex flex-wrap gap-1.5">
                {(Array.isArray(arcData.role_sequence) ? arcData.role_sequence : []).map(
                  (role, i) => (
                    <span
                      key={i}
                      className="flex items-center gap-1.5 rounded-full bg-white/5 px-2 py-1 text-xs text-white/80"
                    >
                      <span className={`h-2 w-2 rounded-full ${roleMeta(String(role)).color}`} />
                      {roleMeta(String(role)).label}
                    </span>
                  ),
                )}
              </div>
            </Field>
          </div>
        ) : (
          <Unavailable story={story} stageName="narrative_arc" />
        )}
      </Section>

      {/* Payoffs */}
      <Section icon={<SparklesIcon className="h-4 w-4" />} title="Payoffs">
        {isCompleted(story, "payoff_detection") ? (
          payoffs.length > 0 ? (
            <ul className="space-y-3">
              {payoffs.map((p, i) => (
                <li key={i} className="rounded-lg bg-white/[0.03] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-white">
                      {p.type.replace(/_/g, " ")}
                    </span>
                    <ConfidenceChip value={p.confidence} />
                  </div>
                  <p className="mt-1.5 text-xs text-muted">
                    Setup at {formatTimestamp(p.setupTimestamp)} → payoff at{" "}
                    {formatTimestamp(p.payoffTimestamp)}
                  </p>
                  {p.payoffExcerpt && (
                    <p className="mt-1.5 text-xs italic leading-relaxed text-white/70">
                      “{p.payoffExcerpt}”
                    </p>
                  )}
                  {p.sharedKeywords.length > 0 && (
                    <div className="mt-2">
                      <Chips items={p.sharedKeywords} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              No clear setup→payoff relationships were detected in this video.
            </p>
          )
        ) : (
          <Unavailable story={story} stageName="payoff_detection" />
        )}
      </Section>

      {/* Emotional journey */}
      <Section icon={<ActivityIcon className="h-4 w-4" />} title="Emotional journey">
        {isCompleted(story, "emotional_turning_points") ? (
          <div className="space-y-2">
            {method === "estimated_from_transcript" && (
              <p className="text-[11px] text-muted">
                Estimated from transcript sentiment (no emotion model configured); confidence is
                intentionally modest.
              </p>
            )}
            {turns.length > 0 ? (
              <ul className="space-y-2">
                {turns.map((t, i) => (
                  <li key={i} className="flex items-center gap-3 text-sm">
                    <span className="tabular-nums text-xs text-muted">
                      {formatTimestamp(t.timestamp)}
                    </span>
                    <span className="text-white/85">
                      {t.previous} <span className="text-muted">→</span> {t.next}
                    </span>
                    <ConfidenceChip value={t.confidence} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No clear emotional turning points were detected.</p>
            )}
          </div>
        ) : (
          <Unavailable story={story} stageName="emotional_turning_points" />
        )}
      </Section>

      {/* Topics */}
      <Section icon={<LayersIcon className="h-4 w-4" />} title="Topic shifts">
        {isCompleted(story, "topic_segmentation") ? (
          topics.length > 0 ? (
            <ul className="space-y-2">
              {topics.map((t, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="tabular-nums text-xs text-muted">
                    {formatTimestamp(t.timestamp)}
                  </span>
                  <Chips items={t.oldTopic.slice(0, 3)} />
                  <span className="text-muted">→</span>
                  <Chips items={t.newTopic.slice(0, 3)} tone="accent" />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">A single, cohesive topic — no major shifts detected.</p>
          )
        ) : (
          <Unavailable story={story} stageName="topic_segmentation" />
        )}
      </Section>

      {/* Context dependencies */}
      <Section icon={<LinkIcon className="h-4 w-4" />} title="Context dependencies">
        {isCompleted(story, "context_dependencies") ? (
          refs.length > 0 ? (
            <ul className="space-y-2">
              {refs.slice(0, 12).map((r, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="tabular-nums text-xs text-muted">
                    {formatTimestamp(r.fromTimestamp)}
                  </span>
                  <span className="text-white/85">relies on</span>
                  <span className="tabular-nums text-xs text-accent">
                    {formatTimestamp(r.dependsOnTimestamp)}
                  </span>
                  {r.term && <span className="text-xs text-muted">· “{r.term}”</span>}
                  <ConfidenceChip value={r.confidence} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">No cross-references between moments were detected.</p>
          )
        ) : (
          <Unavailable story={story} stageName="context_dependencies" />
        )}
      </Section>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted">{label}</p>
      {children}
    </div>
  );
}

function Tag({ on, children }: { on: boolean; children: ReactNode }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 ${
        on ? "bg-green-500/10 text-green-300" : "bg-white/5 text-muted line-through"
      }`}
    >
      {children}
    </span>
  );
}
