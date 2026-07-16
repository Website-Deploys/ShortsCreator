/**
 * Pure presentation helpers for the Optimization Engine UI.
 *
 * The backend returns quality reports, music recommendations, variants, caption
 * improvements, and publish packages as loosely-typed JSON. These helpers parse
 * and format that data - all pure and side-effect-free so they can be unit-tested
 * without a DOM. Nothing here invents data: a `null` score/confidence is rendered
 * honestly as "Unknown", an `unavailable` stage keeps its backend reason, and an
 * unavailable asset is never presented as downloadable.
 */

import type { Optimization, OptimizationStage } from "@/lib/types";

/* ------------------------------ formatting -------------------------------- */

export function humanize(value: string): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced[0].toUpperCase() + spaced.slice(1);
}

/** Format a 0-1 score as a percentage, honestly showing "Unknown" for null. */
export function formatScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

/** Format a confidence (0-1), honestly showing UNKNOWN when the backend gave null. */
export function formatConfidence(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "Unknown";
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

/** Whether the optimization pipeline has reached a terminal state. */
export function isTerminal(optimization: Optimization | null | undefined): boolean {
  return (
    !!optimization && ["completed", "failed", "cancelled"].includes(optimization.status)
  );
}

/* ------------------------------ stage status meta ------------------------- */

export interface StatusMeta {
  label: string;
  /** Tailwind text colour for the status. */
  tone: string;
}

const STATUS_META: Record<string, StatusMeta> = {
  completed: { label: "Completed", tone: "text-emerald-300" },
  running: { label: "Running", tone: "text-sky-300" },
  pending: { label: "Pending", tone: "text-muted" },
  unavailable: { label: "Unavailable", tone: "text-amber-300" },
  failed: { label: "Failed", tone: "text-rose-300" },
  cancelled: { label: "Cancelled", tone: "text-muted" },
};

export function statusMeta(status: string): StatusMeta {
  return STATUS_META[status] ?? { label: humanize(status), tone: "text-muted" };
}

/** Group the pipeline's stages into the engine's logical sections. */
export const STAGE_GROUPS: { title: string; stages: string[] }[] = [
  { title: "Render", stages: ["load_render"] },
  {
    title: "Audio",
    stages: [
      "audio_analysis",
      "voice_enhancement",
      "noise_reduction",
      "loudness_normalization",
      "silence_refinement",
      "music_recommendation",
      "music_mixing",
    ],
  },
  { title: "Captions", stages: ["caption_optimization", "typography_improvement"] },
  {
    title: "Visual",
    stages: [
      "visual_enhancement",
      "sharpening",
      "color_refinement",
      "frame_cleanup",
      "thumbnail_optimization",
    ],
  },
  {
    title: "Metadata & Export",
    stages: [
      "title_suggestion",
      "description_suggestion",
      "hashtag_recommendation",
      "upload_metadata_v2",
      "platform_optimization",
      "compression_optimization",
    ],
  },
  {
    title: "Evaluation & Packaging",
    stages: [
      "quality_evaluation",
      "variant_generation",
      "final_validation",
      "publish_package_creation",
    ],
  },
];

/** Count stages by terminal kind (for the pipeline summary line). */
export function stageTally(stages: OptimizationStage[]): {
  completed: number;
  unavailable: number;
  failed: number;
  total: number;
} {
  let completed = 0;
  let unavailable = 0;
  let failed = 0;
  for (const s of stages) {
    if (s.status === "completed") completed += 1;
    else if (s.status === "unavailable") unavailable += 1;
    else if (s.status === "failed") failed += 1;
  }
  return { completed, unavailable, failed, total: stages.length };
}

/* ------------------------------ parsing: quality -------------------------- */

export interface QualityDimension {
  dimension: string;
  score: number | null;
  confidence: number | null;
  reasoning: string;
  limitations: string;
}

export interface QualityClip {
  clipId: string;
  overall: number | null;
  unknownDimensions: string[];
  dimensions: QualityDimension[];
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function parseQuality(report: Record<string, unknown> | null | undefined): QualityClip[] {
  if (!report) return [];
  const clips = Array.isArray(report.clips) ? report.clips : [];
  return clips.map((c) => {
    const rec = (c ?? {}) as Record<string, unknown>;
    const summary = (rec.summary ?? {}) as Record<string, unknown>;
    const dimsRaw = Array.isArray(rec.dimensions) ? rec.dimensions : [];
    return {
      clipId: str(rec.clip_id),
      overall: num(summary.overall_score),
      unknownDimensions: Array.isArray(summary.unknown_dimensions)
        ? (summary.unknown_dimensions as unknown[]).map(String)
        : [],
      dimensions: dimsRaw.map((d) => {
        const dr = (d ?? {}) as Record<string, unknown>;
        return {
          dimension: str(dr.dimension),
          score: num(dr.score),
          confidence: num(dr.confidence),
          reasoning: str(dr.reasoning),
          limitations: str(dr.limitations),
        };
      }),
    };
  });
}

/* ------------------------------ parsing: music ---------------------------- */

export interface MusicTrackView {
  title: string;
  artist: string | null;
  bpm: number | null;
  genre: string | null;
  energy: number | null;
  license: string;
  source: string;
  score: number | null;
  reason: string;
}

export interface MusicClip {
  clipId: string;
  pacing: string | null;
  recommendations: MusicTrackView[];
}

export interface ProviderStatus {
  provider: string;
  available: boolean;
  reason: string | null;
}

export function parseMusic(music: Record<string, unknown> | null | undefined): {
  clips: MusicClip[];
  providers: ProviderStatus[];
} {
  if (!music) return { clips: [], providers: [] };
  const clips = Array.isArray(music.clips) ? music.clips : [];
  const providers = Array.isArray(music.provider_statuses) ? music.provider_statuses : [];
  return {
    clips: clips.map((c) => {
      const rec = (c ?? {}) as Record<string, unknown>;
      const query = (rec.query ?? {}) as Record<string, unknown>;
      const recs = Array.isArray(rec.recommendations) ? rec.recommendations : [];
      return {
        clipId: str(rec.clip_id),
        pacing: str(query.pacing) || null,
        recommendations: recs.map((r) => {
          const rr = (r ?? {}) as Record<string, unknown>;
          const track = (rr.track ?? {}) as Record<string, unknown>;
          return {
            title: str(track.title),
            artist: str(track.artist) || null,
            bpm: num(track.bpm),
            genre: str(track.genre) || null,
            energy: num(track.energy),
            license: str(track.license),
            source: str(track.source),
            score: num(rr.score),
            reason: str(rr.reason),
          };
        }),
      };
    }),
    providers: providers.map((p) => {
      const pr = (p ?? {}) as Record<string, unknown>;
      return {
        provider: str(pr.provider),
        available: pr.available === true,
        reason: str(pr.reason) || null,
      };
    }),
  };
}

/* ------------------------------ parsing: captions ------------------------- */

export interface CaptionSummary {
  clipId: string;
  total: number;
  comfortable: number;
  brisk: number;
  tooFast: number;
  comfortableFraction: number | null;
}

export function parseCaptionSummaries(
  data: Record<string, unknown> | null | undefined,
): CaptionSummary[] {
  if (!data) return [];
  const clips = Array.isArray(data.clips) ? data.clips : [];
  return clips.map((c) => {
    const rec = (c ?? {}) as Record<string, unknown>;
    const s = (rec.summary ?? {}) as Record<string, unknown>;
    return {
      clipId: str(rec.clip_id),
      total: num(rec.caption_count) ?? 0,
      comfortable: num(s.comfortable) ?? 0,
      brisk: num(s.brisk) ?? 0,
      tooFast: num(s.too_fast) ?? 0,
      comfortableFraction: num(s.comfortable_fraction),
    };
  });
}

/* ------------------------------ asset meta -------------------------------- */

const ASSET_LABELS: Record<string, string> = {
  optimized_mp4: "Optimized MP4",
  thumbnail: "Thumbnail",
  metadata: "Metadata (JSON)",
  quality_report: "Quality report (JSON)",
  captions_srt: "Captions (SRT)",
  captions_vtt: "Captions (VTT)",
  captions: "Captions",
};

export function assetLabel(kind: string): string {
  return ASSET_LABELS[kind] ?? humanize(kind);
}

/* ------------------------------ platform labels --------------------------- */

const PLATFORM_LABELS: Record<string, string> = {
  youtube_shorts: "YouTube Shorts",
  tiktok: "TikTok",
  instagram_reels: "Instagram Reels",
  facebook_reels: "Facebook Reels",
  snapchat_spotlight: "Snapchat Spotlight",
};

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? humanize(platform);
}
