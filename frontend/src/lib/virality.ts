/**
 * Pure presentation helpers for the Virality Engine UI.
 *
 * The backend returns virality stage `data` as loosely-typed JSON. These helpers
 * safely parse it into narrow view models and encode display logic (score/heat
 * colours, confidence banding, timestamp formatting). They are deliberately pure
 * and side-effect-free so they can be unit-tested without a DOM. Nothing here
 * invents data — a missing score stays `null` (rendered as an honest
 * "unavailable" state), and confidence is always surfaced alongside any score.
 */

import type { CSSProperties } from "react";

import type { Virality, ViralityStage, ViralityStageStatus } from "@/lib/types";

/* ------------------------------ formatting -------------------------------- */

export interface Band {
  label: "Low" | "Moderate" | "High";
  className: string;
}

/** Band a 0–1 value into a label + colour (used for confidence). */
export function confidenceBand(value: number): Band {
  if (value >= 0.66) return { label: "High", className: "text-green-300 bg-green-500/10" };
  if (value >= 0.4) return { label: "Moderate", className: "text-amber-300 bg-amber-500/10" };
  return { label: "Low", className: "text-muted bg-white/5" };
}

/** Band a 0–1 score into a colour for score cards/bars. */
export function scoreBand(value: number): Band {
  if (value >= 0.66) return { label: "High", className: "text-emerald-300" };
  if (value >= 0.4) return { label: "Moderate", className: "text-amber-300" };
  return { label: "Low", className: "text-rose-300" };
}

/** Format a 0–1 value as a percentage string, e.g. `0.62 -> "62%"`. */
export function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

/** Format seconds as `m:ss` (or `h:mm:ss`). */
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

/**
 * Map a real heat value (0–1) to a colour. The intensity is the analysis output;
 * this only chooses where on a cool→hot ramp to render it (never fabricated).
 */
export function heatStyle(heat: number): CSSProperties {
  const h = Math.max(0, Math.min(1, heat));
  const hue = Math.round(220 - 208 * h); // 220 (cool blue) -> 12 (hot red)
  const sat = Math.round(35 + 55 * h);
  const light = Math.round(22 + 26 * h);
  return { backgroundColor: `hsl(${hue} ${sat}% ${light}%)` };
}

/* ------------------------------ categories -------------------------------- */

export interface CategoryDef {
  category: string;
  stage: string;
  label: string;
}

/** The fourteen scored categories, in display order, with their backing stage. */
export const CATEGORY_DEFS: CategoryDef[] = [
  { category: "hook", stage: "hook_strength", label: "Hook" },
  { category: "curiosity", stage: "curiosity_gap", label: "Curiosity" },
  { category: "emotion", stage: "emotional_impact", label: "Emotion" },
  { category: "conflict", stage: "conflict", label: "Conflict" },
  { category: "novelty", stage: "novelty", label: "Novelty" },
  { category: "information", stage: "information_value", label: "Information" },
  { category: "relatability", stage: "audience_relatability", label: "Relatability" },
  { category: "momentum", stage: "momentum", label: "Momentum" },
  { category: "retention", stage: "retention", label: "Retention" },
  { category: "replay", stage: "replay_potential", label: "Replay" },
  { category: "sharing", stage: "shareability", label: "Sharing" },
  { category: "commenting", stage: "comment_potential", label: "Commenting" },
  { category: "platform_fit", stage: "platform_fit", label: "Platform Fit" },
  { category: "audience_match", stage: "audience_fit", label: "Audience Match" },
];

export interface EventMeta {
  label: string;
  color: string;
}

const EVENT_META: Record<string, EventMeta> = {
  interest_rise: { label: "Interest rises", color: "bg-emerald-400" },
  interest_fall: { label: "Interest falls", color: "bg-rose-400" },
  emotion_spike: { label: "Emotion spike", color: "bg-amber-400" },
  conflict: { label: "Conflict", color: "bg-orange-400" },
  curiosity: { label: "Curiosity opens", color: "bg-sky-400" },
  payoff: { label: "Payoff", color: "bg-emerald-400" },
  attention_drop: { label: "Attention weakens", color: "bg-rose-400" },
};

export function eventMeta(type: string): EventMeta {
  return EVENT_META[type] ?? { label: type.replace(/_/g, " "), color: "bg-slate-400" };
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
function asNumOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function asStr(v: unknown): string {
  return typeof v === "string" ? v : "";
}
function asStrArray(v: unknown): string[] {
  return asArray(v).filter((x): x is string => typeof x === "string");
}

/* ------------------------------ view models ------------------------------- */

export function getStage(virality: Virality, name: string): ViralityStage | undefined {
  return virality.stages.find((s) => s.stage === name);
}

export function completedData(virality: Virality, name: string): Record<string, unknown> | null {
  const stage = getStage(virality, name);
  if (stage && stage.status === "completed" && stage.data) return stage.data;
  return null;
}

export interface ScoreCard {
  category: string;
  stage: string;
  label: string;
  status: ViralityStageStatus;
  score: number | null;
  confidence: number | null;
  evidence: Record<string, unknown>[];
  limitations: string;
  reason: string;
}

/** One card per scored category, with its honest status (available or not). */
export function parseScoreCards(virality: Virality): ScoreCard[] {
  return CATEGORY_DEFS.map((def) => {
    const stage = getStage(virality, def.stage);
    const data = stage?.status === "completed" ? (stage.data ?? {}) : null;
    return {
      category: def.category,
      stage: def.stage,
      label: def.label,
      status: stage?.status ?? "pending",
      score: data ? asNumOrNull(data.score) : null,
      confidence: data ? asNumOrNull(data.confidence) : null,
      evidence: data ? asArray(data.evidence).map(asRecord) : [],
      limitations: data ? asStr(data.limitations) : "",
      reason: stage?.reason ?? "",
    };
  });
}

export interface TimelineEvent {
  timestamp: number;
  type: string;
  label: string;
  detail: string;
  confidence: number;
}

export interface HeatCell {
  start: number;
  end: number;
  heat: number;
  components: { density: number; emotion: number; payoff: number; hook: number };
}

export interface Recommendation {
  title: string;
  reason: string;
  evidenceStage: string;
}

export interface PlatformScore {
  key: string;
  label: string;
  score: number;
  reason: string;
}

export interface AudienceSegment {
  segment: string;
  matchedKeywords: string[];
}

export interface ViralitySummaryView {
  overallScore: number | null;
  overallConfidence: number;
  availableCategories: string[];
  pendingCategories: { category: string; reason: string }[];
  strengths: { category?: string; evidence: string }[];
  weaknesses: { category?: string; evidence: string }[];
  risks: { category?: string; evidence: string }[];
  missedOpportunities: { evidence: string }[];
  recommendations: Recommendation[];
  timeline: TimelineEvent[];
  heatmap: HeatCell[];
  heatmapNote: string;
  limitations: string;
}

const PLATFORM_LABELS: Record<string, string> = {
  youtube_shorts: "YouTube Shorts",
  tiktok: "TikTok",
  instagram_reels: "Instagram Reels",
};

function parseAssessmentList(v: unknown): { category?: string; evidence: string }[] {
  return asArray(v).map((raw) => {
    const r = asRecord(raw);
    return { category: asStr(r.category) || undefined, evidence: asStr(r.evidence) };
  });
}

export function parseSummary(virality: Virality): ViralitySummaryView | null {
  const data = completedData(virality, "virality_summary");
  if (!data) return null;
  return {
    overallScore: asNumOrNull(data.overall_score),
    overallConfidence: asNum(data.overall_confidence),
    availableCategories: asStrArray(data.available_categories),
    pendingCategories: asArray(data.pending_categories).map((raw) => {
      const r = asRecord(raw);
      return { category: asStr(r.category), reason: asStr(r.reason) };
    }),
    strengths: parseAssessmentList(data.strengths),
    weaknesses: parseAssessmentList(data.weaknesses),
    risks: parseAssessmentList(data.risks),
    missedOpportunities: asArray(data.missed_opportunities).map((raw) => ({
      evidence: asStr(asRecord(raw).evidence),
    })),
    recommendations: asArray(data.recommendations).map((raw) => {
      const r = asRecord(raw);
      return {
        title: asStr(r.title),
        reason: asStr(r.reason),
        evidenceStage: asStr(r.evidence_stage),
      };
    }),
    timeline: asArray(data.timeline).map((raw) => {
      const e = asRecord(raw);
      return {
        timestamp: asNum(e.timestamp),
        type: asStr(e.type),
        label: asStr(e.label),
        detail: asStr(e.detail),
        confidence: asNum(e.confidence),
      };
    }),
    heatmap: asArray(data.heatmap).map((raw) => {
      const c = asRecord(raw);
      const comp = asRecord(c.components);
      return {
        start: asNum(c.start),
        end: asNum(c.end),
        heat: asNum(c.heat),
        components: {
          density: asNum(comp.density),
          emotion: asNum(comp.emotion),
          payoff: asNum(comp.payoff),
          hook: asNum(comp.hook),
        },
      };
    }),
    heatmapNote: asStr(data.heatmap_note),
    limitations: asStr(data.limitations),
  };
}

/** Per-platform scores from the platform-fit stage (empty when unavailable). */
export function parsePlatforms(virality: Virality): PlatformScore[] {
  const data = completedData(virality, "platform_fit");
  if (!data) return [];
  const platforms = asRecord(data.platforms);
  return Object.entries(platforms).map(([key, raw]) => {
    const r = asRecord(raw);
    return {
      key,
      label: PLATFORM_LABELS[key] ?? key,
      score: asNum(r.score),
      reason: asStr(r.reason),
    };
  });
}

/** Audience segments from the audience-fit stage (empty when unavailable). */
export function parseAudience(virality: Virality): AudienceSegment[] {
  const data = completedData(virality, "audience_fit");
  if (!data) return [];
  return asArray(data.segments).map((raw) => {
    const r = asRecord(raw);
    return { segment: asStr(r.segment), matchedKeywords: asStrArray(r.matched_keywords) };
  });
}

/** Humanize a snake_case id, e.g. `"attention_drop" -> "Attention drop"`. */
export function humanize(value: string): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced[0].toUpperCase() + spaced.slice(1);
}
