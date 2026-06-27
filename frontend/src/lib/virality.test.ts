import { describe, expect, it } from "vitest";

import {
  CATEGORY_DEFS,
  confidenceBand,
  eventMeta,
  formatPercent,
  formatTimestamp,
  heatStyle,
  humanize,
  parseAudience,
  parsePlatforms,
  parseScoreCards,
  parseSummary,
  scoreBand,
} from "@/lib/virality";
import type { Virality, ViralityStage, ViralityStageStatus } from "@/lib/types";

function stage(
  name: string,
  status: ViralityStageStatus,
  data: Record<string, unknown> | null = null,
  reason: string | null = null,
): ViralityStage {
  return {
    stage: name,
    label: name,
    status,
    version: "1",
    progress: status === "completed" ? 1 : 0,
    attempts: 1,
    started_at: null,
    completed_at: null,
    error: null,
    reason,
    data,
  };
}

function virality(stages: ViralityStage[]): Virality {
  return {
    project_id: "proj_1",
    pipeline_version: "1",
    status: "completed",
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    completed_stages: stages.filter((s) => s.status === "completed").length,
    total_stages: stages.length,
    stages,
  };
}

describe("formatting", () => {
  it("formats percent and clamps/guards", () => {
    expect(formatPercent(0.62)).toBe("62%");
    expect(formatPercent(1.5)).toBe("100%");
    expect(formatPercent(null)).toBe("—");
  });
  it("formats timestamps", () => {
    expect(formatTimestamp(75)).toBe("1:15");
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(-1)).toBe("—");
  });
  it("bands confidence and score by threshold", () => {
    expect(confidenceBand(0.9).label).toBe("High");
    expect(confidenceBand(0.5).label).toBe("Moderate");
    expect(confidenceBand(0.1).label).toBe("Low");
    expect(scoreBand(0.8).label).toBe("High");
    expect(scoreBand(0.1).label).toBe("Low");
  });
  it("maps real heat to a hotter colour as it rises", () => {
    const cold = heatStyle(0).backgroundColor as string;
    const hot = heatStyle(1).backgroundColor as string;
    expect(cold).toContain("hsl(220");
    expect(hot).toContain("hsl(12");
  });
  it("humanizes ids and labels events", () => {
    expect(humanize("attention_drop")).toBe("Attention drop");
    expect(eventMeta("payoff").label).toBe("Payoff");
    expect(eventMeta("unknown_type").label).toBe("unknown type");
  });
});

describe("parseScoreCards", () => {
  it("returns one card per category with honest status", () => {
    const v = virality([
      stage("hook_strength", "completed", {
        score: 0.7,
        confidence: 0.6,
        evidence: [{ type: "hook", excerpt: "Why?" }],
        limitations: "transcript only",
      }),
      stage("emotional_impact", "unavailable", null, "no transcript"),
    ]);
    const cards = parseScoreCards(v);
    expect(cards).toHaveLength(CATEGORY_DEFS.length);
    const hook = cards.find((c) => c.stage === "hook_strength")!;
    expect(hook.score).toBe(0.7);
    expect(hook.evidence).toHaveLength(1);
    const emotion = cards.find((c) => c.stage === "emotional_impact")!;
    expect(emotion.status).toBe("unavailable");
    expect(emotion.score).toBeNull(); // never fabricated
    expect(emotion.reason).toBe("no transcript");
  });
});

describe("parseSummary", () => {
  it("parses overall score, confidence, pending categories, heatmap and timeline", () => {
    const v = virality([
      stage("virality_summary", "completed", {
        overall_score: 0.55,
        overall_confidence: 0.21,
        available_categories: ["hook", "platform_fit"],
        pending_categories: [{ category: "emotion", stage: "emotional_impact", reason: "no transcript" }],
        strengths: [{ category: "hook", evidence: "high Hook score" }],
        weaknesses: [],
        risks: [{ category: "retention", evidence: "early drop-off" }],
        missed_opportunities: [{ evidence: "strong emotion, weak hook" }],
        recommendations: [
          { title: "Strengthen the hook", reason: "weak opening", evidence_stage: "hook_strength" },
        ],
        timeline: [
          { timestamp: 0, type: "interest_rise", label: "Opening hook", detail: "question", confidence: 0.7 },
        ],
        heatmap: [
          { start: 0, end: 15, heat: 0.8, components: { density: 0.6, emotion: 1, payoff: 0, hook: 1 } },
        ],
        heatmap_note: "derived from analysis",
        limitations: "heuristics",
      }),
    ]);
    const summary = parseSummary(v)!;
    expect(summary.overallScore).toBe(0.55);
    expect(summary.overallConfidence).toBe(0.21);
    expect(summary.availableCategories).toContain("platform_fit");
    expect(summary.pendingCategories[0].category).toBe("emotion");
    expect(summary.recommendations[0].evidenceStage).toBe("hook_strength");
    expect(summary.timeline[0].type).toBe("interest_rise");
    expect(summary.heatmap[0].heat).toBe(0.8);
    expect(summary.risks[0].evidence).toBe("early drop-off");
  });

  it("returns null when the summary stage is not completed", () => {
    const v = virality([stage("virality_summary", "unavailable", null, "n/a")]);
    expect(parseSummary(v)).toBeNull();
  });

  it("preserves a null overall score (no fabrication) when no categories were available", () => {
    const v = virality([
      stage("virality_summary", "completed", {
        overall_score: null,
        overall_confidence: 0,
        available_categories: [],
        pending_categories: [],
        timeline: [],
        heatmap: [],
      }),
    ]);
    const summary = parseSummary(v)!;
    expect(summary.overallScore).toBeNull();
  });
});

describe("parsePlatforms / parseAudience", () => {
  it("parses platform scores when available", () => {
    const v = virality([
      stage("platform_fit", "completed", {
        score: 0.8,
        platforms: {
          youtube_shorts: { score: 0.9, reason: "fits" },
          tiktok: { score: 0.8, reason: "fits" },
          instagram_reels: { score: 0.7, reason: "fits" },
        },
      }),
    ]);
    const platforms = parsePlatforms(v);
    expect(platforms).toHaveLength(3);
    expect(platforms.find((p) => p.key === "youtube_shorts")!.label).toBe("YouTube Shorts");
  });

  it("returns empty audience/platform lists honestly when unavailable", () => {
    const v = virality([
      stage("platform_fit", "unavailable", null, "no duration"),
      stage("audience_fit", "unavailable", null, "no keywords"),
    ]);
    expect(parsePlatforms(v)).toEqual([]);
    expect(parseAudience(v)).toEqual([]);
  });

  it("parses audience segments with matched keywords", () => {
    const v = virality([
      stage("audience_fit", "completed", {
        score: 0.5,
        segments: [{ segment: "Productivity & self-improvement", matched_keywords: ["productivity", "focus"] }],
      }),
    ]);
    const audience = parseAudience(v);
    expect(audience[0].segment).toContain("Productivity");
    expect(audience[0].matchedKeywords).toContain("focus");
  });
});
