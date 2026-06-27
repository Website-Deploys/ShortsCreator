import { describe, expect, it } from "vitest";

import {
  engineLabel,
  formatNumber,
  formatRate,
  formatUsd,
  healthDot,
  healthTone,
  severityBadge,
  severityTone,
} from "@/lib/monitoring";

describe("rate / number / usd formatting", () => {
  it("formats rates as percentages, Unknown for null", () => {
    expect(formatRate(0.5)).toBe("50%");
    expect(formatRate(1)).toBe("100%");
    expect(formatRate(null)).toBe("Unknown");
    expect(formatRate(undefined)).toBe("Unknown");
  });
  it("formats numbers, Unknown for null", () => {
    expect(formatNumber(1000)).toBe((1000).toLocaleString());
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(null)).toBe("Unknown");
  });
  it("formats USD estimates, Unknown for null", () => {
    expect(formatUsd(1.5)).toBe("$1.50");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(null)).toBe("Unknown");
  });
});

describe("health tones", () => {
  it("maps statuses to tones and dots", () => {
    expect(healthTone("healthy")).toBe("text-emerald-300");
    expect(healthTone("degraded")).toBe("text-amber-300");
    expect(healthTone("unhealthy")).toBe("text-rose-300");
    expect(healthTone("unknown")).toBe("text-muted");
    expect(healthDot("healthy")).toBe("bg-emerald-400");
    expect(healthDot(null)).toBe("bg-white/30");
  });
});

describe("severity tones", () => {
  it("maps severities to tones and badges", () => {
    expect(severityTone("critical")).toBe("text-rose-300");
    expect(severityTone("warning")).toBe("text-amber-300");
    expect(severityTone("info")).toBe("text-sky-300");
    expect(severityBadge("critical")).toContain("rose");
    expect(severityBadge("warning")).toContain("amber");
    expect(severityBadge("info")).toContain("sky");
  });
});

describe("engine labels", () => {
  it("maps engine ids to friendly labels", () => {
    expect(engineLabel("cognitive")).toBe("Cognitive");
    expect(engineLabel("planning")).toBe("Clip Planner");
    expect(engineLabel("rendering")).toBe("Rendering");
    expect(engineLabel("mystery")).toBe("mystery");
  });
});
