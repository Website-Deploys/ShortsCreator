import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const dashboard = readFileSync(new URL("./WorkflowDashboard.tsx", import.meta.url), "utf8");

describe("Durable Job Queue / Resume V2 dashboard", () => {
  it("shows persisted job progress and restart diagnostics", () => {
    expect(dashboard).toContain("durable_job_v2");
    expect(dashboard).toContain("heartbeat");
    expect(dashboard).toContain("Checkpoint:");
    expect(dashboard).toContain("Backend restarted or a worker heartbeat expired");
    expect(dashboard).toContain("Cancellation requested");
  });

  it("exposes safe operator controls without requiring durable data on old projects", () => {
    expect(dashboard).toContain("Retry workflow");
    expect(dashboard).toContain("Resume");
    expect(dashboard).toContain("Cancel");
    expect(dashboard).toContain('durable_job_v2?.status !== "cancel_requested"');
    expect(dashboard).toContain("durable_job_v2?.resume.resumable !== false");
  });
});
