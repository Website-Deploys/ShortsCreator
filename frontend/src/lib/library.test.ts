import { describe, expect, it } from "vitest";

import {
  activityTone,
  assetKindLabel,
  formatBytes,
  formatDuration,
  formatMs,
  formatScore,
  humanize,
  namespaceLabel,
  statusTone,
} from "@/lib/library";

describe("formatting", () => {
  it("formats bytes honestly", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatBytes(null)).toBe("—");
  });
  it("formats scores, showing Unknown for null", () => {
    expect(formatScore(0.72)).toBe("72%");
    expect(formatScore(null)).toBe("Unknown");
  });
  it("formats ms and durations", () => {
    expect(formatMs(500)).toBe("500ms");
    expect(formatMs(1500)).toBe("1.5s");
    expect(formatMs(null)).toBe("—");
    expect(formatDuration(75)).toBe("1:15");
    expect(formatDuration(null)).toBe("—");
  });
});

describe("labels", () => {
  it("labels asset kinds + namespaces", () => {
    expect(assetKindLabel("source_video")).toBe("Source video");
    expect(assetKindLabel("export")).toBe("Export");
    expect(namespaceLabel("renders")).toBe("Renders");
    expect(humanize("project_archived")).toBe("Project archived");
  });
});

describe("tones", () => {
  it("maps activity + status tones", () => {
    expect(activityTone("workflow_completed")).toBe("bg-emerald-400");
    expect(activityTone("workflow_failed")).toBe("bg-rose-400");
    expect(activityTone("project_archived")).toBe("bg-amber-400");
    expect(activityTone("project_created")).toBe("bg-accent");
    expect(statusTone("available")).toBe("text-emerald-300");
    expect(statusTone("unavailable")).toBe("text-amber-300");
  });
});
