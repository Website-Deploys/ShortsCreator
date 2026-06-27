import { describe, expect, it } from "vitest";

import {
  assetLabel,
  formatConfidence,
  formatScore,
  humanize,
  isTerminal,
  parseCaptionSummaries,
  parseMusic,
  parseQuality,
  platformLabel,
  stageTally,
  statusMeta,
} from "@/lib/optimization";
import type { Optimization, OptimizationStage } from "@/lib/types";

function stage(over: Partial<OptimizationStage> & { stage: string; status: OptimizationStage["status"] }): OptimizationStage {
  return {
    label: over.stage,
    version: "1",
    progress: 1,
    attempts: 1,
    started_at: null,
    completed_at: null,
    error: null,
    reason: null,
    data: null,
    ...over,
  };
}

describe("formatting", () => {
  it("formats scores and shows Unknown for null", () => {
    expect(formatScore(0.72)).toBe("72%");
    expect(formatScore(null)).toBe("Unknown");
    expect(formatScore(undefined)).toBe("Unknown");
  });
  it("formats confidence honestly", () => {
    expect(formatConfidence(0.5)).toBe("50%");
    expect(formatConfidence(null)).toBe("Unknown");
  });
  it("humanizes ids", () => {
    expect(humanize("voice_enhancement")).toBe("Voice enhancement");
  });
});

describe("status meta + tally", () => {
  it("maps statuses to tones", () => {
    expect(statusMeta("completed").label).toBe("Completed");
    expect(statusMeta("unavailable").label).toBe("Unavailable");
    expect(statusMeta("mystery").label).toBe("Mystery");
  });
  it("tallies stages by terminal kind", () => {
    const tally = stageTally([
      stage({ stage: "a", status: "completed" }),
      stage({ stage: "b", status: "unavailable" }),
      stage({ stage: "c", status: "failed" }),
      stage({ stage: "d", status: "completed" }),
    ]);
    expect(tally).toEqual({ completed: 2, unavailable: 1, failed: 1, total: 4 });
  });
});

describe("isTerminal", () => {
  it("reflects terminal pipeline states", () => {
    expect(isTerminal({ status: "completed" } as Optimization)).toBe(true);
    expect(isTerminal({ status: "running" } as Optimization)).toBe(false);
    expect(isTerminal(null)).toBe(false);
  });
});

describe("parseQuality", () => {
  it("parses dimensions and honest UNKNOWN scores", () => {
    const clips = parseQuality({
      clips: [
        {
          clip_id: "clip_a",
          summary: { overall_score: 0.66, unknown_dimensions: ["audio_quality"] },
          dimensions: [
            { dimension: "caption_quality", score: 0.8, confidence: 0.7, reasoning: "r", limitations: "l" },
            { dimension: "audio_quality", score: null, confidence: null, reasoning: "r", limitations: "l" },
          ],
        },
      ],
    });
    expect(clips).toHaveLength(1);
    expect(clips[0].overall).toBe(0.66);
    expect(clips[0].unknownDimensions).toContain("audio_quality");
    expect(clips[0].dimensions[1].score).toBeNull();
  });
  it("returns empty for missing report", () => {
    expect(parseQuality(null)).toEqual([]);
  });
});

describe("parseMusic", () => {
  it("parses recommendations with license + provider statuses", () => {
    const { clips, providers } = parseMusic({
      clips: [
        {
          clip_id: "clip_a",
          query: { pacing: "fast" },
          recommendations: [
            {
              track: { title: "Uplift", license: "CC0", source: "local", bpm: 120, energy: 0.8 },
              score: 0.7,
              reason: "matches",
            },
          ],
        },
      ],
      provider_statuses: [
        { provider: "local_royalty_free", available: true, reason: null },
        { provider: "epidemic_sound", available: false, reason: "no credentials" },
      ],
    });
    expect(clips[0].recommendations[0].license).toBe("CC0");
    expect(clips[0].pacing).toBe("fast");
    expect(providers.find((p) => p.provider === "epidemic_sound")?.available).toBe(false);
  });
});

describe("parseCaptionSummaries", () => {
  it("parses per-clip caption stats", () => {
    const summaries = parseCaptionSummaries({
      clips: [
        {
          clip_id: "clip_a",
          caption_count: 10,
          summary: { comfortable: 8, brisk: 1, too_fast: 1, comfortable_fraction: 0.8 },
        },
      ],
    });
    expect(summaries[0].total).toBe(10);
    expect(summaries[0].comfortableFraction).toBe(0.8);
  });
});

describe("labels", () => {
  it("labels assets and platforms", () => {
    expect(assetLabel("captions_srt")).toBe("Captions (SRT)");
    expect(assetLabel("metadata")).toBe("Metadata (JSON)");
    expect(platformLabel("youtube_shorts")).toBe("YouTube Shorts");
    expect(platformLabel("unknown_platform")).toBe("Unknown platform");
  });
});
