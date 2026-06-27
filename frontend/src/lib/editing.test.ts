import { describe, expect, it } from "vitest";

import {
  clampZoom,
  countEvents,
  eventMeta,
  evidenceText,
  formatConfidence,
  formatTime,
  humanize,
  isTerminal,
  isUnknown,
  parseValidation,
  rulerTicks,
  timeToX,
  timelineWidth,
  TRACK_ORDER,
  trackMeta,
} from "@/lib/editing";
import type { Editing, Timeline, TimelineEvent } from "@/lib/types";

function ev(over: Partial<TimelineEvent> & { type: string }): TimelineEvent {
  return {
    id: "e1",
    start: 0,
    end: 1,
    duration: 1,
    reason: "because",
    confidence: 0.5,
    evidence: [{ type: "transcript", detail: "hello" }],
    ...over,
  };
}

describe("formatting", () => {
  it("formats clip-relative time with one decimal", () => {
    expect(formatTime(75.4)).toBe("1:15.4");
    expect(formatTime(0)).toBe("0:00.0");
    expect(formatTime(null)).toBe("—");
    expect(formatTime(-1)).toBe("—");
  });
  it("formats confidence and shows UNKNOWN for null", () => {
    expect(formatConfidence(0.62)).toBe("62%");
    expect(formatConfidence(null)).toBe("Unknown");
    expect(formatConfidence(undefined)).toBe("Unknown");
  });
  it("humanizes ids", () => {
    expect(humanize("jump_cut_point")).toBe("Jump cut point");
  });
});

describe("track + event meta", () => {
  it("orders tracks and labels them", () => {
    expect(TRACK_ORDER).toEqual(["video", "audio", "caption", "markers"]);
    expect(trackMeta("caption").label).toBe("Subtitles");
    expect(trackMeta("unknown_kind").label).toBe("Unknown kind");
  });
  it("maps event types to label/colour/point", () => {
    expect(eventMeta("caption").point).toBe(false);
    expect(eventMeta("jump_cut_point").point).toBe(true);
    expect(eventMeta("mystery").label).toBe("Mystery");
  });
});

describe("geometry", () => {
  it("clamps zoom into a sane range", () => {
    expect(clampZoom(1)).toBe(4);
    expect(clampZoom(1000)).toBe(120);
    expect(clampZoom(30)).toBe(30);
  });
  it("maps time to pixels and computes width", () => {
    expect(timeToX(10, 20)).toBe(200);
    expect(timeToX(-5, 20)).toBe(0);
    expect(timelineWidth(30, 10)).toBe(300);
  });
  it("produces sensible ruler ticks", () => {
    const ticks = rulerTicks(60, 20);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(60);
    expect(ticks.length).toBeGreaterThan(1);
  });
});

describe("event helpers", () => {
  it("counts events across tracks", () => {
    const tl = {
      tracks: [
        { kind: "video", events: [ev({ type: "source_clip" })] },
        { kind: "caption", events: [ev({ type: "caption" }), ev({ type: "caption" })] },
      ],
    } as unknown as Timeline;
    expect(countEvents(tl)).toBe(3);
  });
  it("detects honest UNKNOWN events (null confidence)", () => {
    expect(isUnknown(ev({ type: "pan_to_speaker", confidence: null }))).toBe(true);
    expect(isUnknown(ev({ type: "caption", confidence: 0.7 }))).toBe(false);
  });
  it("extracts evidence text", () => {
    expect(evidenceText(ev({ type: "caption" }))).toBe("transcript: hello");
    expect(evidenceText(ev({ type: "caption", evidence: [] }))).toBe("");
  });
});

describe("parseValidation", () => {
  it("parses the report and clip issues", () => {
    const view = parseValidation({
      valid: false,
      issue_count: 1,
      clips: [
        { clip_id: "clip_a", valid: false, issues: [{ detail: "end precedes start" }] },
        { clip_id: "clip_b", valid: true, issues: [] },
      ],
    })!;
    expect(view.valid).toBe(false);
    expect(view.issueCount).toBe(1);
    expect(view.clips[0].issues[0]).toBe("end precedes start");
    expect(view.clips[1].valid).toBe(true);
  });
  it("returns null when no report", () => {
    expect(parseValidation(null)).toBeNull();
  });
});

describe("isTerminal", () => {
  it("reflects terminal pipeline states", () => {
    expect(isTerminal({ status: "completed" } as Editing)).toBe(true);
    expect(isTerminal({ status: "running" } as Editing)).toBe(false);
    expect(isTerminal(null)).toBe(false);
  });
});
