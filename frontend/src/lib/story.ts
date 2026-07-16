/**
 * Pure presentation helpers for the Story Engine UI.
 *
 * The backend returns story stage `data` as loosely-typed JSON. These helpers
 * safely parse it into narrow view models and encode display logic (confidence
 * banding, role colours, timestamp formatting). They are deliberately pure and
 * side-effect-free so they can be unit-tested without a DOM, and so the React
 * components stay thin. Nothing here invents data — missing fields become empty
 * defaults that the UI renders as honest "unavailable/none" states.
 */

import type { Story, StoryStage } from "@/lib/types";

/* ------------------------------ confidence -------------------------------- */

export interface ConfidenceBand {
  label: "Low" | "Moderate" | "High";
  className: string;
}

/** Band a 0–1 confidence into a label + colour (heuristics stay modest). */
export function confidenceBand(value: number): ConfidenceBand {
  if (value >= 0.66) return { label: "High", className: "text-green-300 bg-green-500/10" };
  if (value >= 0.4) return { label: "Moderate", className: "text-amber-300 bg-amber-500/10" };
  return { label: "Low", className: "text-muted bg-white/5" };
}

/** Format a 0–1 confidence as a percentage string, e.g. `0.62 -> "62%"`. */
export function formatConfidence(value: number): string {
  const clamped = Math.max(0, Math.min(1, value));
  return `${Math.round(clamped * 100)}%`;
}

/** Format seconds as `m:ss` (or `h:mm:ss`), e.g. `75 -> "1:15"`. */
export function formatTimestamp(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}

/* ------------------------------ narrative roles --------------------------- */

export interface RoleMeta {
  label: string;
  /** Tailwind colour token used by the timeline track + chips. */
  color: string;
}

const ROLE_META: Record<string, RoleMeta> = {
  hook: { label: "Hook", color: "bg-fuchsia-500" },
  introduction: { label: "Introduction", color: "bg-sky-500" },
  background: { label: "Background", color: "bg-cyan-500" },
  problem: { label: "Problem", color: "bg-rose-500" },
  explanation: { label: "Explanation", color: "bg-indigo-500" },
  conflict: { label: "Conflict", color: "bg-orange-500" },
  example: { label: "Example", color: "bg-teal-500" },
  resolution: { label: "Resolution", color: "bg-emerald-500" },
  ending: { label: "Ending", color: "bg-violet-500" },
};

export function roleMeta(role: string): RoleMeta {
  return ROLE_META[role] ?? { label: role, color: "bg-slate-500" };
}

const HOOK_TYPE_LABELS: Record<string, string> = {
  question: "Question",
  shock: "Shock",
  curiosity: "Curiosity gap",
  bold_statement: "Bold statement",
  emotion: "Emotional",
  story: "Story",
};

export function hookTypeLabel(type: string | null | undefined): string {
  if (!type) return "Hook";
  return HOOK_TYPE_LABELS[type] ?? type;
}

/* ------------------------------ safe coercion ----------------------------- */

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}
function asNum(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}
function asStr(v: unknown): string {
  return typeof v === "string" ? v : "";
}
function asStrArray(v: unknown): string[] {
  return asArray(v).filter((x): x is string => typeof x === "string");
}

/* ------------------------------ view models ------------------------------- */

export function getStage(story: Story, name: string): StoryStage | undefined {
  return story.stages.find((s) => s.stage === name);
}

/** Stage data only when the stage genuinely completed (else null = honest gap). */
export function completedData(story: Story, name: string): Record<string, unknown> | null {
  const stage = getStage(story, name);
  if (stage && stage.status === "completed" && stage.data) return stage.data;
  return null;
}

export interface NarrativeSection {
  index: number;
  start: number;
  end: number;
  role: string;
  label: string;
  confidence: number;
  reason: string;
  keywords: string[];
  excerpt: string;
}

export function parseSections(story: Story): NarrativeSection[] {
  const data = completedData(story, "narrative_segmentation");
  if (!data) return [];
  return asArray(data.sections).map((raw, i) => {
    const s = asRecord(raw);
    return {
      index: typeof s.index === "number" ? s.index : i,
      start: asNum(s.start),
      end: asNum(s.end),
      role: asStr(s.role) || "explanation",
      label: asStr(s.label) || "Section",
      confidence: asNum(s.confidence),
      reason: asStr(s.reason),
      keywords: asStrArray(s.keywords),
      excerpt: asStr(s.supporting_excerpt),
    };
  });
}

export interface HookInfo {
  hasHook: boolean;
  hookType?: string;
  why?: string;
  confidence: number;
  reason?: string;
  excerpt?: string;
}

export function parseHook(story: Story): HookInfo | null {
  const data = completedData(story, "hook_detection");
  if (!data) return null;
  return {
    hasHook: data.has_hook === true,
    hookType: asStr(data.hook_type) || undefined,
    why: asStr(data.why) || undefined,
    confidence: asNum(data.confidence),
    reason: asStr(data.reason) || undefined,
    excerpt: asStr(data.supporting_excerpt) || undefined,
  };
}

export interface TopicShift {
  timestamp: number;
  oldTopic: string[];
  newTopic: string[];
  confidence: number;
  reason: string;
}

export function parseTopics(story: Story): TopicShift[] {
  const data = completedData(story, "topic_segmentation");
  if (!data) return [];
  return asArray(data.shifts).map((raw) => {
    const s = asRecord(raw);
    return {
      timestamp: asNum(s.timestamp),
      oldTopic: asStrArray(s.old_topic),
      newTopic: asStrArray(s.new_topic),
      confidence: asNum(s.confidence),
      reason: asStr(s.reason),
    };
  });
}

export interface Payoff {
  type: string;
  setupTimestamp: number;
  payoffTimestamp: number;
  setupExcerpt: string;
  payoffExcerpt: string;
  confidence: number;
  sharedKeywords: string[];
}

export function parsePayoffs(story: Story): Payoff[] {
  const data = completedData(story, "payoff_detection");
  if (!data) return [];
  return asArray(data.relationships).map((raw) => {
    const r = asRecord(raw);
    const evidence = asRecord(r.evidence);
    return {
      type: asStr(r.type) || "payoff",
      setupTimestamp: asNum(r.setup_timestamp),
      payoffTimestamp: asNum(r.payoff_timestamp),
      setupExcerpt: asStr(r.setup_excerpt),
      payoffExcerpt: asStr(r.payoff_excerpt),
      confidence: asNum(r.confidence),
      sharedKeywords: asStrArray(evidence.shared_keywords),
    };
  });
}

export interface EmotionTurn {
  previous: string;
  next: string;
  timestamp: number;
  confidence: number;
  method: string;
}

export function parseEmotionTurns(story: Story): { method: string; turns: EmotionTurn[] } {
  const data = completedData(story, "emotional_turning_points");
  if (!data) return { method: "", turns: [] };
  const turns = asArray(data.turning_points).map((raw) => {
    const t = asRecord(raw);
    return {
      previous: asStr(t.previous_emotion),
      next: asStr(t.new_emotion),
      timestamp: asNum(t.timestamp),
      confidence: asNum(t.confidence),
      method: asStr(t.method) || asStr(data.method),
    };
  });
  return { method: asStr(data.method), turns };
}

export interface DensityWindow {
  start: number;
  end: number;
  density: number;
  classification: string;
  reason: string;
}

export function parseDensity(story: Story): DensityWindow[] {
  const data = completedData(story, "information_density");
  if (!data) return [];
  return asArray(data.windows).map((raw) => {
    const w = asRecord(raw);
    return {
      start: asNum(w.start),
      end: asNum(w.end),
      density: asNum(w.density),
      classification: asStr(w.classification) || "moderate",
      reason: asStr(w.reason),
    };
  });
}

export interface ContextRef {
  type: string;
  fromTimestamp: number;
  dependsOnTimestamp: number | null;
  term: string | null;
  confidence: number;
}

export function parseContextRefs(story: Story): ContextRef[] {
  const data = completedData(story, "context_dependencies");
  if (!data) return [];
  return asArray(data.references).map((raw) => {
    const r = asRecord(raw);
    return {
      type: asStr(r.type) || "reference",
      fromTimestamp: asNum(r.from_timestamp),
      dependsOnTimestamp: typeof r.depends_on_timestamp === "number" ? r.depends_on_timestamp : null,
      term: typeof r.term === "string" ? r.term : null,
      confidence: asNum(r.confidence),
    };
  });
}

export interface SummaryView {
  mainSubject: string[];
  arcType: string;
  secondaryTopics: string[];
  keyLessons: string[];
  storyFlow: { role: string; start: number; end: number }[];
  importantMoments: { type: string; timestamp: number; confidence: number }[];
  confidence: number;
  pendingSignals: string[];
}

export function parseSummary(story: Story): SummaryView | null {
  const data = completedData(story, "story_summary");
  if (!data) return null;
  const narrative = asRecord(data.primary_narrative);
  const secondary = asArray(data.secondary_topics).flatMap((t) => asStrArray(t));
  return {
    mainSubject: asStrArray(data.main_subject),
    arcType: asStr(narrative.arc_type),
    secondaryTopics: secondary,
    keyLessons: asStrArray(data.key_lessons),
    storyFlow: asArray(data.story_flow).map((raw) => {
      const f = asRecord(raw);
      return { role: asStr(f.role), start: asNum(f.start), end: asNum(f.end) };
    }),
    importantMoments: asArray(data.important_moments).map((raw) => {
      const m = asRecord(raw);
      return { type: asStr(m.type), timestamp: asNum(m.timestamp), confidence: asNum(m.confidence) };
    }),
    confidence: asNum(data.confidence),
    pendingSignals: asArray(data.pending_signals)
      .map((p) => asStr(asRecord(p).stage))
      .filter(Boolean),
  };
}

export interface StoryV2MicroStory {
  storyId: string;
  title: string;
  start: number;
  end: number;
  storyShape: string;
  completeness: number;
  contextRisk: number;
  payoff: string;
  tension: string;
  endingReason: string;
  boundaryReason: string;
  warning: string | null;
}

export interface StoryV2View {
  topicCount: number;
  microStoryCount: number;
  recommendedCount: number;
  averageCompleteness: number;
  topStories: StoryV2MicroStory[];
  warnings: string[];
}

export function parseStoryV2(story: Story): StoryV2View | null {
  const data = completedData(story, "story_analysis_v2");
  if (!data) return null;
  const quality = asRecord(data.story_quality_summary);
  const topStories = asArray(data.recommended_clip_stories)
    .slice(0, 3)
    .map((raw) => {
      const item = asRecord(raw);
      const tension = asRecord(item.tension);
      const payoff = asRecord(item.payoff);
      const ending = asRecord(item.ending);
      const context = asRecord(item.context);
      const repair = asRecord(item.boundary_repair);
      return {
        storyId: asStr(item.story_id),
        title: asStr(item.title) || "Micro-story",
        start: asNum(item.start),
        end: asNum(item.end),
        storyShape: asStr(item.story_shape) || "micro story",
        completeness: asNum(item.completeness_score),
        contextRisk: asNum(item.context_dependency_score),
        payoff: asStr(payoff.payoff_text),
        tension: asStr(tension.viewer_question) || asStr(tension.unresolved_question),
        endingReason: asStr(ending.end_reason),
        boundaryReason: asStr(repair.reason) || asStr(item.boundary_reasoning),
        warning: asStr(item.rejection_reason) || null,
      };
    });
  return {
    topicCount: asArray(data.topic_sections).length,
    microStoryCount: asArray(data.micro_stories).length,
    recommendedCount: asArray(data.recommended_clip_stories).length,
    averageCompleteness: asNum(quality.average_completeness),
    topStories,
    warnings: asStrArray(data.warnings),
  };
}

/** Humanize an arc-type id, e.g. `"classic_setup_conflict_resolution"`. */
export function humanizeArc(arcType: string): string {
  if (!arcType) return "—";
  return arcType
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
