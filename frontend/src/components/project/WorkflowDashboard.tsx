"use client";

/**
 * The Workflow dashboard - the live operational view of Olympus's central
 * nervous system. It shows the execution graph across every engine, live overall
 * progress, the worker pool's activity, the scheduler/queue state, every job
 * (expandable to its logs, retries, durations, and errors), and the execution
 * timeline - all from real backend orchestration state, polled live. It exposes
 * the operator controls: start, pause, resume, cancel, retry job, retry workflow.
 *
 * Nothing here is fabricated: job statuses are genuine engine outcomes, progress
 * is derived from completed jobs, and the remaining time is shown as an estimate.
 */
import { useState } from "react";

import {
  AlertIcon,
  CheckCircleIcon,
  ChevronDownIcon,
  NetworkIcon,
  PauseIcon,
  PlayIcon,
  RefreshIcon,
  SpinnerIcon,
  XIcon,
} from "@/components/icons";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  useCancelWorkflow,
  usePauseWorkflow,
  useResumeWorkflow,
  useRetryWorkflow,
  useRetryWorkflowJob,
  useScheduler,
  useStartWorkflow,
  useWorkers,
  useWorkflow,
} from "@/lib/queries";
import {
  clockTime,
  formatDuration,
  formatEstimate,
  humanize,
  isRetryable,
  jobStatusMeta,
  jobTally,
  progressPercent,
  workflowStatusMeta,
} from "@/lib/workflow";
import type { Workflow, WorkflowJob } from "@/lib/types";

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-3 text-sm font-semibold text-white">{children}</h4>;
}

/* ------------------------------ execution graph --------------------------- */

function ExecutionGraph({ workflow }: { workflow: Workflow }) {
  const nodes = workflow.execution_graph.nodes;
  return (
    <div className="flex items-stretch gap-1 overflow-x-auto pb-2">
      {nodes.map((node, i) => {
        const meta = jobStatusMeta(node.status);
        const active = node.stage === workflow.current_stage;
        return (
          <div key={node.stage} className="flex items-center">
            <div
              className={`min-w-[110px] rounded-lg border px-3 py-2 ${
                active ? "border-accent bg-accent/5" : "border-white/10 bg-white/[0.02]"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
                <span className="truncate text-xs font-medium text-white">{node.label}</span>
              </div>
              <p className={`mt-1 text-[10px] ${meta.tone}`}>
                {meta.label}
                {node.attempts > 1 ? ` · ${node.attempts}×` : ""}
              </p>
            </div>
            {i < nodes.length - 1 && (
              <div
                className={`h-px w-3 shrink-0 ${
                  node.status === "completed" ? "bg-emerald-400/50" : "bg-white/15"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------ job row ----------------------------------- */

function JobRow({ projectId, job }: { projectId: string; job: WorkflowJob }) {
  const [open, setOpen] = useState(false);
  const retry = useRetryWorkflowJob(projectId);
  const meta = jobStatusMeta(job.status);
  const checkpoint = job.checkpoint ?? {};
  return (
    <li className="rounded-lg border border-white/10">
      <div className="flex items-center justify-between gap-3 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
        >
          <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
          <span className="truncate text-sm text-white">{humanize(job.stage)}</span>
          <span className={`shrink-0 text-[11px] ${meta.tone}`}>{meta.label}</span>
          {job.attempts > 1 && (
            <span className="shrink-0 text-[10px] text-muted">
              attempt {job.attempts}/{job.max_attempts}
            </span>
          )}
          <ChevronDownIcon
            className={`ml-auto h-3.5 w-3.5 shrink-0 text-muted transition-transform ${
              open ? "rotate-180" : ""
            }`}
          />
        </button>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-[11px] tabular-nums text-muted">{formatDuration(job.duration_ms)}</span>
          {isRetryable(job.status) && (
            <button
              type="button"
              onClick={() => retry.mutate(job.job_id)}
              disabled={retry.isPending}
              title="Retry this job"
              aria-label={`Retry ${job.stage}`}
              className="text-muted transition-colors hover:text-white disabled:opacity-50"
            >
              <RefreshIcon className={`h-3.5 w-3.5 ${retry.isPending ? "animate-spin" : ""}`} />
            </button>
          )}
        </div>
      </div>
      {open && (
        <div className="space-y-2 border-t border-white/10 px-3 py-2 text-xs">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted">
            <span>engine: <span className="text-white/80">{job.engine}</span></span>
            <span>worker: <span className="text-white/80">{job.worker_id ?? "—"}</span></span>
            <span>priority: <span className="text-white/80">{job.priority}</span></span>
            {job.depends_on.length > 0 && (
              <span>depends on: <span className="text-white/80">{job.depends_on.join(", ")}</span></span>
            )}
            <span>started: <span className="text-white/80">{clockTime(job.started_at) || "—"}</span></span>
            <span>finished: <span className="text-white/80">{clockTime(job.finished_at) || "—"}</span></span>
            <span>heartbeat: <span className="text-white/80">{clockTime(job.heartbeat_at) || "—"}</span></span>
          </div>
          {Object.keys(checkpoint).length > 0 && (
            <p className="rounded bg-white/[0.03] px-2 py-1 text-muted">
              Checkpoint: {checkpoint.valid === true ? "validated" : "warning"}
              {typeof checkpoint.artifact_path === "string" ? ` · ${checkpoint.artifact_path}` : ""}
            </p>
          )}
          {job.error && (
            <p className="rounded bg-rose-500/[0.08] px-2 py-1 text-rose-200">{job.error}</p>
          )}
          {job.logs.length > 0 && (
            <div className="max-h-40 space-y-0.5 overflow-y-auto rounded bg-black/30 p-2 font-mono text-[11px] text-muted">
              {job.logs.map((line, i) => (
                <p key={i}>
                  <span className="text-white/40">{clockTime(line.ts)}</span> {line.message}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/* ------------------------------ side panels ------------------------------- */

function WorkersPanel({ enabled }: { enabled: boolean }) {
  const { data } = useWorkers(enabled);
  const workers = data?.workers ?? [];
  return (
    <Card>
      <SectionTitle>Workers</SectionTitle>
      {workers.length === 0 ? (
        <p className="text-sm text-muted">No workers registered.</p>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {workers.map((w) => (
            <li key={w.worker_id} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5">
                <span
                  className={`h-2 w-2 rounded-full ${
                    w.status === "busy"
                      ? "bg-accent"
                      : w.status === "idle"
                        ? "bg-emerald-400"
                        : "bg-white/30"
                  }`}
                />
                <span className="font-mono text-white/80">{w.worker_id.slice(-8)}</span>
                <span className="text-muted">{w.status}</span>
              </span>
              <span className="text-muted">
                ✓{w.jobs_completed} ✕{w.jobs_failed}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SchedulerPanel({ enabled }: { enabled: boolean }) {
  const { data } = useScheduler(enabled);
  if (!data) return null;
  const q = data.queue;
  const cells: { label: string; value: number; tone?: string }[] = [
    { label: "Ready", value: q.ready, tone: "text-sky-300" },
    { label: "Running", value: q.running, tone: "text-accent" },
    { label: "Pending", value: q.pending },
    { label: "Delayed", value: q.delayed, tone: "text-amber-300" },
    { label: "Completed", value: q.completed, tone: "text-emerald-300" },
    { label: "Failed", value: q.failed + q.dead, tone: "text-rose-300" },
  ];
  return (
    <Card>
      <SectionTitle>Scheduler</SectionTitle>
      <div className="grid grid-cols-3 gap-2">
        {cells.map((c) => (
          <div key={c.label} className="rounded-lg bg-white/[0.03] px-2 py-2 text-center">
            <div className={`text-base font-semibold ${c.tone ?? "text-white"}`}>{c.value}</div>
            <div className="text-[10px] uppercase tracking-wide text-muted">{c.label}</div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-muted">
        Pool {data.pool_running ? "running" : "stopped"} · {data.worker_count} worker(s) ·{" "}
        {q.active_workflows} active workflow(s)
      </p>
    </Card>
  );
}

function HistoryTimeline({ workflow }: { workflow: Workflow }) {
  const events = [...workflow.history].slice(-40).reverse();
  return (
    <Card>
      <SectionTitle>Execution timeline</SectionTitle>
      {events.length === 0 ? (
        <p className="text-sm text-muted">No events yet.</p>
      ) : (
        <ul className="max-h-72 space-y-1.5 overflow-y-auto text-xs">
          {events.map((e, i) => (
            <li key={i} className="flex gap-2">
              <span className="shrink-0 font-mono text-white/40">{clockTime(e.ts)}</span>
              <span className="shrink-0 rounded bg-white/5 px-1.5 text-[10px] text-muted">
                {e.type}
              </span>
              <span className="text-muted">{e.message}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ------------------------------ controls ---------------------------------- */

function Controls({ workflow, projectId }: { workflow: Workflow; projectId: string }) {
  const pause = usePauseWorkflow(projectId);
  const resume = useResumeWorkflow(projectId);
  const cancel = useCancelWorkflow(projectId);
  const retry = useRetryWorkflow(projectId);
  const busy = pause.isPending || resume.isPending || cancel.isPending || retry.isPending;
  return (
    <div className="flex flex-wrap gap-2">
      {workflow.status === "running" && (
        <Button variant="secondary" onClick={() => pause.mutate()} disabled={busy}>
          <PauseIcon className="mr-1.5 h-4 w-4" /> Pause
        </Button>
      )}
      {workflow.status === "paused" && (
        <Button onClick={() => resume.mutate()} disabled={busy}>
          <PlayIcon className="mr-1.5 h-4 w-4" /> Resume
        </Button>
      )}
      {workflow.status === "cancelled" &&
        workflow.durable_job_v2?.status !== "cancel_requested" &&
        workflow.durable_job_v2?.resume.resumable !== false && (
        <Button onClick={() => resume.mutate()} disabled={busy}>
          <PlayIcon className="mr-1.5 h-4 w-4" /> Resume
        </Button>
      )}
      {workflow.failed_stages.length > 0 && workflow.status !== "running" && (
        <Button onClick={() => retry.mutate()} disabled={busy}>
          <RefreshIcon className="mr-1.5 h-4 w-4" /> Retry workflow
        </Button>
      )}
      {(workflow.status === "running" || workflow.status === "paused") && (
        <Button variant="secondary" onClick={() => cancel.mutate()} disabled={busy}>
          <XIcon className="mr-1.5 h-4 w-4" /> Cancel
        </Button>
      )}
    </div>
  );
}

/* --------------------------------- view ----------------------------------- */

export function WorkflowDashboard({ projectId }: { projectId: string }) {
  const { data: workflow, isLoading } = useWorkflow(projectId);
  const start = useStartWorkflow(projectId);
  const resume = useResumeWorkflow(projectId);

  if (isLoading && !workflow) {
    return (
      <Card>
        <div className="flex items-center gap-3 text-sm text-muted">
          <SpinnerIcon className="h-4 w-4 animate-spin" /> Loading workflow…
        </div>
      </Card>
    );
  }

  if (!workflow) {
    return (
      <EmptyState
        icon={<NetworkIcon className="h-6 w-6" />}
        title="No workflow has been started"
        description="The Workflow Engine coordinates the entire pipeline across every engine — upload, cognitive, story, virality, planning, editing, rendering, and optimization — with live progress, retries, recovery, and a worker pool. Start it to orchestrate the full lifecycle."
        action={
          <Button onClick={() => start.mutate()} disabled={start.isPending}>
            {start.isPending ? "Starting…" : "Start workflow"}
          </Button>
        }
      />
    );
  }

  const meta = workflowStatusMeta(workflow.status);
  const tally = jobTally(workflow.jobs);
  const active = ["running", "pending", "paused"].includes(workflow.status);
  const durable = workflow.durable_job_v2;
  const stale = durable?.resume.stale_running_detected || durable?.status === "stale";

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} />
              <span className={`text-sm font-semibold ${meta.tone}`}>{meta.label}</span>
              {workflow.current_stage && active && (
                <span className="text-xs text-muted">· {humanize(workflow.current_stage)}</span>
              )}
            </div>
            <p className="mt-1 text-xs text-muted">
              {tally.completed}/{tally.total} stages · {tally.running} running
              {tally.failed > 0 && <span className="text-rose-300"> · {tally.failed} failed</span>}
              {workflow.total_retries > 0 && <span> · {workflow.total_retries} retries</span>}
              {active && <span> · est. {formatEstimate(workflow.estimated_remaining_seconds)} left</span>}
            </p>
            <p className="mt-1 text-[11px] text-muted">
              Job {(durable?.job_id ?? workflow.workflow_id).slice(-12)}
              {durable?.heartbeat_at && <> · heartbeat {clockTime(durable.heartbeat_at)}</>}
            </p>
          </div>
          <Controls workflow={workflow} projectId={projectId} />
        </div>
        <div className="mt-4">
          <div className="h-2 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className={`h-full rounded-full transition-all ${
                workflow.status === "failed" ? "bg-rose-400" : "bg-emerald-400"
              }`}
              style={{ width: `${progressPercent(workflow)}%` }}
            />
          </div>
          <p className="mt-1 text-right text-[11px] tabular-nums text-muted">
            {progressPercent(workflow)}%
          </p>
        </div>
      </Card>

      {stale && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.08] px-4 py-3 text-sm text-amber-100">
          <span>
            <AlertIcon className="mr-2 inline h-5 w-5" />Backend restarted or a worker heartbeat expired. Resume validates checkpoints before continuing.
          </span>
          {durable?.resume.resumable !== false && (
            <Button onClick={() => resume.mutate()} disabled={resume.isPending}>Resume</Button>
          )}
        </div>
      )}

      {durable?.status === "cancel_requested" && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] px-4 py-3 text-sm text-amber-200">
          Cancellation requested. Olympus is waiting for the current stage to reach a safe stop point.
        </div>
      )}

      {/* Execution graph */}
      <Card>
        <SectionTitle>Execution graph</SectionTitle>
        <ExecutionGraph workflow={workflow} />
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Jobs */}
        <div className="lg:col-span-2">
          <Card>
            <SectionTitle>Jobs</SectionTitle>
            <ul className="space-y-2">
              {workflow.jobs.map((job) => (
                <JobRow key={job.job_id} projectId={projectId} job={job} />
              ))}
            </ul>
          </Card>
        </div>
        {/* Side panels */}
        <div className="space-y-6">
          <WorkersPanel enabled={!!workflow} />
          <SchedulerPanel enabled={!!workflow} />
        </div>
      </div>

      <HistoryTimeline workflow={workflow} />

      {workflow.status === "completed" && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3 text-sm text-emerald-300">
          <CheckCircleIcon className="h-5 w-5" /> Workflow completed — every engine ran to a terminal state.
        </div>
      )}
      {workflow.status === "failed" && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-4 py-3 text-sm text-rose-200">
          <AlertIcon className="h-5 w-5" /> Workflow failed — retry the failed stage(s) to continue.
        </div>
      )}
    </div>
  );
}
