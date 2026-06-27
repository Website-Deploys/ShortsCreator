import { describe, expect, it } from "vitest";

import {
  formatDuration,
  formatEstimate,
  humanize,
  isActive,
  isRetryable,
  isTerminal,
  jobStatusMeta,
  jobTally,
  progressPercent,
  workflowStatusMeta,
} from "@/lib/workflow";
import type { Workflow, WorkflowJob } from "@/lib/types";

function job(over: Partial<WorkflowJob> & { status: WorkflowJob["status"] }): WorkflowJob {
  return {
    job_id: "j",
    workflow_id: "w",
    project_id: "p",
    engine: "x",
    stage: "x",
    priority: 50,
    depends_on: [],
    attempts: 1,
    max_attempts: 3,
    worker_id: null,
    created_at: null,
    started_at: null,
    finished_at: null,
    available_at: null,
    scheduled_for: null,
    duration_ms: null,
    error: null,
    result: {},
    logs: [],
    ...over,
  };
}

describe("status meta", () => {
  it("maps job + workflow statuses", () => {
    expect(jobStatusMeta("completed").label).toBe("Completed");
    expect(jobStatusMeta("dead").label).toBe("Dead");
    expect(workflowStatusMeta("paused").label).toBe("Paused");
  });
  it("flags retryable job statuses", () => {
    expect(isRetryable("failed")).toBe(true);
    expect(isRetryable("dead")).toBe(true);
    expect(isRetryable("blocked")).toBe(true);
    expect(isRetryable("completed")).toBe(false);
  });
});

describe("workflow state predicates", () => {
  it("detects terminal + active", () => {
    expect(isTerminal({ status: "completed" } as Workflow)).toBe(true);
    expect(isTerminal({ status: "running" } as Workflow)).toBe(false);
    expect(isActive({ status: "paused" } as Workflow)).toBe(true);
    expect(isActive(null)).toBe(false);
  });
  it("computes progress percent", () => {
    expect(progressPercent({ overall_progress: 0.5 } as Workflow)).toBe(50);
  });
});

describe("formatting", () => {
  it("humanizes ids", () => {
    expect(humanize("full_resolution_render")).toBe("Full resolution render");
  });
  it("formats durations honestly", () => {
    expect(formatDuration(500)).toBe("500ms");
    expect(formatDuration(1500)).toBe("1.5s");
    expect(formatDuration(90000)).toBe("1m 30s");
    expect(formatDuration(null)).toBe("—");
  });
  it("formats estimates", () => {
    expect(formatEstimate(30)).toBe("~30s");
    expect(formatEstimate(120)).toBe("~2 min");
    expect(formatEstimate(0)).toBe("—");
  });
});

describe("jobTally", () => {
  it("buckets jobs by coarse status", () => {
    const tally = jobTally([
      job({ status: "completed" }),
      job({ status: "running" }),
      job({ status: "dead" }),
      job({ status: "pending" }),
      job({ status: "blocked" }),
    ]);
    expect(tally).toEqual({ completed: 1, running: 1, failed: 2, pending: 1, total: 5 });
  });
});
