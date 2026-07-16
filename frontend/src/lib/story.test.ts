import { describe, expect, it } from "vitest";

import {
  completedData,
  confidenceBand,
  formatConfidence,
  formatTimestamp,
  hookTypeLabel,
  humanizeArc,
  parseHook,
  parsePayoffs,
  parseSections,
  parseStoryV2,
  parseSummary,
  roleMeta,
} from "@/lib/story";
import type { Story, StoryStage, StoryStageStatus } from "@/lib/types";

function stage(
  name: string,
  status: StoryStageStatus,
  data: Record<string, unknown> | null = null,
  reason: string | null = null,
): StoryStage {
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

function story(stages: StoryStage[]): Story {
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

describe("formatConfidence", () => {
  it("formats and clamps", () => {
    expect(formatConfidence(0.62)).toBe("62%");
    expect(formatConfidence(0)).toBe("0%");
    expect(formatConfidence(1.5)).toBe("100%");
    expect(formatConfidence(-1)).toBe("0%");
  });
});

describe("formatTimestamp", () => {
  it("formats m:ss and h:mm:ss", () => {
    expect(formatTimestamp(0)).toBe("0:00");
    expect(formatTimestamp(75)).toBe("1:15");
    expect(formatTimestamp(3661)).toBe("1:01:01");
  });
  it("returns a dash for missing/invalid values", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp(undefined)).toBe("—");
    expect(formatTimestamp(-5)).toBe("—");
  });
});

describe("confidenceBand", () => {
  it("bands by threshold", () => {
    expect(confidenceBand(0.9).label).toBe("High");
    expect(confidenceBand(0.5).label).toBe("Moderate");
    expect(confidenceBand(0.1).label).toBe("Low");
  });
});

describe("labels", () => {
  it("maps roles, hook types, and arcs", () => {
    expect(roleMeta("hook").label).toBe("Hook");
    expect(roleMeta("mystery").label).toBe("mystery"); // unknown role falls back
    expect(hookTypeLabel("question")).toBe("Question");
    expect(hookTypeLabel(null)).toBe("Hook");
    expect(humanizeArc("classic_setup_conflict_resolution")).toBe(
      "Classic Setup Conflict Resolution",
    );
    expect(humanizeArc("")).toBe("—");
  });
});

describe("completedData", () => {
  it("returns data only for completed stages, null otherwise (honest gap)", () => {
    const s = story([
      stage("hook_detection", "completed", { has_hook: true }),
      stage("topic_segmentation", "unavailable", null, "no transcript"),
    ]);
    expect(completedData(s, "hook_detection")).not.toBeNull();
    expect(completedData(s, "topic_segmentation")).toBeNull();
    expect(completedData(s, "missing_stage")).toBeNull();
  });
});

describe("parsers", () => {
  it("parses narrative sections", () => {
    const s = story([
      stage("narrative_segmentation", "completed", {
        sections: [
          {
            index: 0,
            start: 0,
            end: 7,
            role: "hook",
            label: "Hook",
            confidence: 0.7,
            reason: "opens the video",
            keywords: ["productivity", "focus"],
            supporting_excerpt: "Why do most people fail?",
          },
        ],
      }),
    ]);
    const sections = parseSections(s);
    expect(sections).toHaveLength(1);
    expect(sections[0].role).toBe("hook");
    expect(sections[0].keywords).toContain("focus");
    expect(sections[0].excerpt).toContain("Why do most people");
  });

  it("parses a detected hook", () => {
    const s = story([
      stage("hook_detection", "completed", {
        has_hook: true,
        hook_type: "question",
        why: "opens with a question",
        confidence: 0.7,
        supporting_excerpt: "Why?",
      }),
    ]);
    const hook = parseHook(s);
    expect(hook?.hasHook).toBe(true);
    expect(hook?.hookType).toBe("question");
  });

  it("parses payoffs with shared-keyword evidence", () => {
    const s = story([
      stage("payoff_detection", "completed", {
        relationships: [
          {
            type: "question_answered",
            setup_timestamp: 5,
            payoff_timestamp: 80,
            setup_excerpt: "why?",
            payoff_excerpt: "because structure",
            confidence: 0.6,
            evidence: { shared_keywords: ["productivity", "people"] },
          },
        ],
      }),
    ]);
    const payoffs = parsePayoffs(s);
    expect(payoffs).toHaveLength(1);
    expect(payoffs[0].setupTimestamp).toBeLessThan(payoffs[0].payoffTimestamp);
    expect(payoffs[0].sharedKeywords).toContain("productivity");
  });

  it("parses the summary and lists pending signals honestly", () => {
    const s = story([
      stage("story_summary", "completed", {
        main_subject: ["productivity", "focus"],
        primary_narrative: { arc_type: "setup_and_resolution" },
        secondary_topics: [["calendar", "tasks"]],
        key_lessons: ["constraints create freedom"],
        story_flow: [{ role: "hook", start: 0, end: 7 }],
        important_moments: [{ type: "payoff", timestamp: 80, confidence: 0.6 }],
        confidence: 0.5,
        pending_signals: [{ stage: "emotional_turning_points", reason: "no model" }],
      }),
    ]);
    const summary = parseSummary(s);
    expect(summary?.mainSubject).toContain("focus");
    expect(summary?.arcType).toBe("setup_and_resolution");
    expect(summary?.secondaryTopics).toContain("calendar");
    expect(summary?.pendingSignals).toContain("emotional_turning_points");
  });

  it("parses Story V2 micro-story intelligence", () => {
    const s = story([
      stage("story_analysis_v2", "completed", {
        topic_sections: [{ section_id: "topic_0" }],
        micro_stories: [{ story_id: "story_1" }],
        recommended_clip_stories: [
          {
            story_id: "story_1",
            title: "Problem Solution",
            start: 10,
            end: 42,
            story_shape: "problem_solution",
            completeness_score: 0.72,
            context_dependency_score: 0.2,
            tension: { viewer_question: "How does this get solved?" },
            payoff: { payoff_text: "The solution was structure." },
            ending: { end_reason: "payoff preserved" },
            boundary_repair: { reason: "candidate boundaries already preserve story" },
          },
        ],
        story_quality_summary: { average_completeness: 0.62 },
        warnings: ["heuristic story analysis"],
      }),
    ]);

    const parsed = parseStoryV2(s);
    expect(parsed?.topicCount).toBe(1);
    expect(parsed?.microStoryCount).toBe(1);
    expect(parsed?.recommendedCount).toBe(1);
    expect(parsed?.topStories[0].storyShape).toBe("problem_solution");
    expect(parsed?.topStories[0].payoff).toContain("structure");
    expect(parsed?.warnings).toContain("heuristic story analysis");
  });

  it("returns empty/null for unavailable stages (no fabrication)", () => {
    const s = story([stage("narrative_segmentation", "unavailable", null, "no transcript")]);
    expect(parseSections(s)).toEqual([]);
    expect(parseHook(s)).toBeNull();
    expect(parseSummary(s)).toBeNull();
    expect(parseStoryV2(s)).toBeNull();
  });
});
