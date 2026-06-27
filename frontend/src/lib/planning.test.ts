import { describe, expect, it } from "vitest";

import {
  confidenceBand,
  dimensionScores,
  filterPlans,
  formatDuration,
  formatPercent,
  formatTimestamp,
  humanize,
  isTerminal,
  overlapCounts,
  parsePlanningSummary,
  plansOverlap,
  scoreBand,
  sortPlans,
} from "@/lib/planning";
import type { ClipPlan, Planning } from "@/lib/types";

function plan(over: Partial<ClipPlan> & { id: string }): ClipPlan {
  return {
    rank: 1,
    start: 0,
    end: 30,
    duration: 30,
    start_frame: 0,
    end_frame: 900,
    fps: 30,
    quality_score: 0.6,
    confidence: 0.5,
    scores: {},
    evidence: [],
    alternatives: [],
    blueprint: {},
    ...over,
  };
}

describe("formatting", () => {
  it("formats percent, timestamp, duration", () => {
    expect(formatPercent(0.62)).toBe("62%");
    expect(formatPercent(null)).toBe("—");
    expect(formatTimestamp(75)).toBe("1:15");
    expect(formatTimestamp(-1)).toBe("—");
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(95)).toBe("1m 35s");
  });
  it("bands and humanizes", () => {
    expect(scoreBand(0.8).label).toBe("High");
    expect(confidenceBand(0.1).label).toBe("Low");
    expect(humanize("editing_complexity")).toBe("Editing complexity");
  });
});

describe("dimensionScores", () => {
  it("returns ordered dimensions, null when missing (no fabrication)", () => {
    const p = plan({ id: "clip_a", scores: { hook: 0.7, retention: 0.5 } });
    const dims = dimensionScores(p);
    expect(dims.find((d) => d.key === "hook")!.value).toBe(0.7);
    expect(dims.find((d) => d.key === "emotion")!.value).toBeNull();
    expect(dims[0].key).toBe("hook");
  });
});

describe("sort / filter", () => {
  const plans = [
    plan({ id: "clip_a", rank: 2, quality_score: 0.5, confidence: 0.4, duration: 20, start: 50,
      blueprint: { title_suggestion: { text: "Productivity hack" } }, explanation: "from a hook" }),
    plan({ id: "clip_b", rank: 1, quality_score: 0.8, confidence: 0.7, duration: 40, start: 10,
      blueprint: { title_suggestion: { text: "Focus secret" } }, explanation: "from a payoff arc" }),
  ];

  it("sorts by quality, rank, duration, start", () => {
    expect(sortPlans(plans, "quality").map((p) => p.id)).toEqual(["clip_b", "clip_a"]);
    expect(sortPlans(plans, "rank").map((p) => p.id)).toEqual(["clip_b", "clip_a"]);
    expect(sortPlans(plans, "duration").map((p) => p.id)).toEqual(["clip_b", "clip_a"]);
    expect(sortPlans(plans, "start").map((p) => p.id)).toEqual(["clip_b", "clip_a"]);
  });

  it("filters by query and minimum quality", () => {
    expect(filterPlans(plans, "focus", 0).map((p) => p.id)).toEqual(["clip_b"]);
    expect(filterPlans(plans, "payoff", 0).map((p) => p.id)).toEqual(["clip_b"]);
    expect(filterPlans(plans, "", 0.7).map((p) => p.id)).toEqual(["clip_b"]);
    expect(filterPlans(plans, "nonexistent", 0)).toEqual([]);
  });
});

describe("overlap", () => {
  it("detects overlapping plans and counts them", () => {
    const a = plan({ id: "a", start: 0, end: 30 });
    const b = plan({ id: "b", start: 20, end: 40 });
    const c = plan({ id: "c", start: 60, end: 80 });
    expect(plansOverlap(a, b)).toBe(true);
    expect(plansOverlap(a, c)).toBe(false);
    const counts = overlapCounts([a, b, c]);
    expect(counts["a"]).toBe(1);
    expect(counts["c"]).toBe(0);
  });
});

describe("parsePlanningSummary", () => {
  it("parses counts, zero reason, distribution and pending signals", () => {
    const view = parsePlanningSummary({
      plan_count: 0,
      zero_reason: "no transcript available",
      score_distribution: { high: 0, moderate: 0, low: 0 },
      available_signals: [],
      pending_signals: [{ signal: "transcript", reason: "not produced upstream" }],
      confidence: 0,
    })!;
    expect(view.planCount).toBe(0);
    expect(view.zeroReason).toContain("transcript");
    expect(view.pendingSignals[0].signal).toBe("transcript");
  });
  it("returns null when summary is absent", () => {
    expect(parsePlanningSummary(null)).toBeNull();
  });
});

describe("isTerminal", () => {
  it("reflects terminal pipeline states", () => {
    expect(isTerminal({ status: "completed" } as Planning)).toBe(true);
    expect(isTerminal({ status: "running" } as Planning)).toBe(false);
    expect(isTerminal(null)).toBe(false);
  });
});
