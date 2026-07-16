/**
 * Pure presentation helpers for the Workflow dashboard.
 *
 * The backend returns the workflow as a rich graph (jobs, history, DAG). These
 * pure, side-effect-free helpers format and classify that data for display.
 * Nothing here fabricates state: a job's status is shown exactly as reported,
 * durations only when measured, and the estimate is labelled an estimate.
 */

import type { JobStatus, Workflow, WorkflowJob, WorkflowStatus } from "@/lib/types";

export function humanize(value: string): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced[0].toUpperCase() + spaced.slice(1);
}

export function isTerminal(workflow: Workflow | null | undefined): boolean {
  return !!workflow && ["completed", "failed", "cancelled"].includes(workflow.status);
}

export function isActive(workflow: Workflow | null | undefined): boolean {
  return !!workflow && ["running", "pending", "paused"].includes(workflow.status);
}

export interface StatusMeta {
  label: string;
  tone: string;
  dot: string;
}

const JOB_STATUS_META: Record<JobStatus, StatusMeta> = {
  pending: { label: "Pending", tone: "text-muted", dot: "bg-white/25" },
  ready: { label: "Ready", tone: "text-sky-300", dot: "bg-sky-400" },
  running: { label: "Running", tone: "text-accent", dot: "bg-accent" },
  cancel_requested: { label: "Stopping", tone: "text-amber-300", dot: "bg-amber-400" },
  stale: { label: "Stale", tone: "text-amber-300", dot: "bg-amber-500" },
  completed: { label: "Completed", tone: "text-emerald-300", dot: "bg-emerald-400" },
  failed: { label: "Failed", tone: "text-rose-300", dot: "bg-rose-400" },
  cancelled: { label: "Cancelled", tone: "text-muted", dot: "bg-white/30" },
  dead: { label: "Dead", tone: "text-rose-300", dot: "bg-rose-500" },
  blocked: { label: "Blocked", tone: "text-amber-300", dot: "bg-amber-400" },
};

export function jobStatusMeta(status: JobStatus): StatusMeta {
  return JOB_STATUS_META[status] ?? { label: humanize(status), tone: "text-muted", dot: "bg-white/25" };
}

const WORKFLOW_STATUS_META: Record<WorkflowStatus, StatusMeta> = {
  pending: { label: "Pending", tone: "text-muted", dot: "bg-white/30" },
  running: { label: "Running", tone: "text-accent", dot: "bg-accent" },
  paused: { label: "Paused", tone: "text-amber-300", dot: "bg-amber-400" },
  completed: { label: "Completed", tone: "text-emerald-300", dot: "bg-emerald-400" },
  failed: { label: "Failed", tone: "text-rose-300", dot: "bg-rose-400" },
  cancelled: { label: "Cancelled", tone: "text-muted", dot: "bg-white/30" },
};

export function workflowStatusMeta(status: WorkflowStatus): StatusMeta {
  return (
    WORKFLOW_STATUS_META[status] ?? { label: humanize(status), tone: "text-muted", dot: "bg-white/30" }
  );
}

/** Whether a job can be retried by the operator. */
export function isRetryable(status: JobStatus): boolean {
  return status === "failed" || status === "dead" || status === "blocked";
}

/** Format a millisecond duration, or "—" when not measured. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

/** Format a nominal seconds estimate as a friendly duration (clearly an estimate). */
export function formatEstimate(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 60) return `~${Math.round(seconds)}s`;
  const m = Math.round(seconds / 60);
  return `~${m} min`;
}

export function progressPercent(workflow: Workflow): number {
  return Math.round((workflow.overall_progress || 0) * 100);
}

/** Count jobs by a coarse bucket for the summary line. */
export function jobTally(jobs: WorkflowJob[]): {
  completed: number;
  running: number;
  failed: number;
  pending: number;
  total: number;
} {
  let completed = 0;
  let running = 0;
  let failed = 0;
  let pending = 0;
  for (const j of jobs) {
    if (j.status === "completed") completed += 1;
    else if (j.status === "running" || j.status === "cancel_requested") running += 1;
    else if (j.status === "failed" || j.status === "dead" || j.status === "blocked") failed += 1;
    else pending += 1;
  }
  return { completed, running, failed, pending, total: jobs.length };
}

/** Short, human time-of-day for timeline rows (or "" when missing). */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
