import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatDuration,
  humanize,
  isTerminal,
  manifestProduced,
  shortChecksum,
  stageTally,
  statusMeta,
} from "@/lib/rendering";
import type { RenderRun, RenderStage } from "@/lib/types";

function stage(
  over: Partial<RenderStage> & { stage: string; status: RenderStage["status"] },
): RenderStage {
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
  it("humanizes ids", () => {
    expect(humanize("full_resolution_render")).toBe("Full resolution render");
  });
  it("formats bytes honestly", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(null)).toBe("Unknown");
  });
  it("formats duration honestly", () => {
    expect(formatDuration(75)).toBe("1:15");
    expect(formatDuration(null)).toBe("Unknown");
  });
  it("shortens checksums", () => {
    expect(shortChecksum("sha256:abcdef0123456789")).toBe("sha256:abcdef012345…");
    expect(shortChecksum(null)).toBeNull();
  });
});

describe("status meta + tally", () => {
  it("maps statuses to tones", () => {
    expect(statusMeta("completed").label).toBe("Done");
    expect(statusMeta("unavailable").label).toBe("Unavailable");
  });
  it("tallies stages by terminal kind", () => {
    const tally = stageTally([
      stage({ stage: "a", status: "completed" }),
      stage({ stage: "b", status: "unavailable" }),
      stage({ stage: "c", status: "completed" }),
    ]);
    expect(tally).toEqual({ completed: 2, unavailable: 1, failed: 0, total: 3 });
  });
});

describe("isTerminal + manifestProduced", () => {
  it("reflects terminal pipeline state", () => {
    expect(isTerminal({ status: "completed" } as RenderRun)).toBe(true);
    expect(isTerminal({ status: "running" } as RenderRun)).toBe(false);
    expect(isTerminal(null)).toBe(false);
  });
  it("detects a produced manifest", () => {
    const withManifest = {
      stages: [stage({ stage: "generate_render_manifest", status: "completed" })],
    } as RenderRun;
    const withoutManifest = {
      stages: [stage({ stage: "generate_render_manifest", status: "unavailable" })],
    } as RenderRun;
    expect(manifestProduced(withManifest)).toBe(true);
    expect(manifestProduced(withoutManifest)).toBe(false);
    expect(manifestProduced(null)).toBe(false);
  });
});
