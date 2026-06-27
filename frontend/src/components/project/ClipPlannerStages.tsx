"use client";

/**
 * The Clip Planner pipeline progress — REAL, per-stage status reported by the
 * backend.
 *
 * Each row reflects a stage's genuine state: completed stages are marked done;
 * stages that lack the upstream signals they need are shown honestly as
 * "Unavailable" with the backend's own reason; genuine failures are surfaced.
 * Nothing is fabricated. Each stage can be re-run independently.
 */
import { useState } from "react";

import {
  AlertIcon,
  CheckCircleIcon,
  ChevronDownIcon,
  ClockIcon,
  MinusCircleIcon,
  RefreshIcon,
  SpinnerIcon,
} from "@/components/icons";
import { useRerunPlanningStage } from "@/lib/queries";
import type { Planning, PlanningStage, PlanningStageStatus } from "@/lib/types";

const STATE_META: Record<
  PlanningStageStatus,
  { label: string; tone: string; icon: "done" | "running" | "unavailable" | "failed" | "pending" }
> = {
  completed: { label: "Done", tone: "text-green-400", icon: "done" },
  running: { label: "Planning", tone: "text-accent", icon: "running" },
  unavailable: { label: "Unavailable", tone: "text-muted", icon: "unavailable" },
  failed: { label: "Failed", tone: "text-red-300", icon: "failed" },
  pending: { label: "Waiting", tone: "text-muted", icon: "pending" },
  cancelled: { label: "Cancelled", tone: "text-muted", icon: "pending" },
};

function StageIcon({ status }: { status: PlanningStageStatus }) {
  const kind = STATE_META[status].icon;
  if (kind === "done") {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-green-500/15">
        <CheckCircleIcon className="h-5 w-5 text-green-400" />
      </span>
    );
  }
  if (kind === "running") {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15">
        <SpinnerIcon className="h-4 w-4 animate-spin text-accent" />
      </span>
    );
  }
  if (kind === "failed") {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-red-500/15">
        <AlertIcon className="h-5 w-5 text-red-300" />
      </span>
    );
  }
  if (kind === "unavailable") {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/5">
        <MinusCircleIcon className="h-5 w-5 text-muted" />
      </span>
    );
  }
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/5">
      <span className="h-2 w-2 rounded-full bg-white/25" />
    </span>
  );
}

function StageRow({
  stage,
  isLast,
  projectId,
}: {
  stage: PlanningStage;
  isLast: boolean;
  projectId: string;
}) {
  const [open, setOpen] = useState(false);
  const rerun = useRerunPlanningStage(projectId);
  const meta = STATE_META[stage.status];
  const detail = stage.reason ?? stage.error ?? null;
  const active = stage.status === "completed" || stage.status === "running";

  return (
    <li className="relative flex gap-4 pb-5 last:pb-0">
      {!isLast && (
        <span
          aria-hidden
          className="absolute left-[15px] top-9 h-[calc(100%-1rem)] w-px bg-white/10"
        />
      )}
      <StageIcon status={stage.status} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3 pt-1">
          <button
            type="button"
            onClick={() => detail && setOpen((v) => !v)}
            className={`group flex min-w-0 items-center gap-2 text-left ${
              detail ? "cursor-pointer" : "cursor-default"
            }`}
            aria-expanded={detail ? open : undefined}
          >
            <span className={`truncate text-sm font-medium ${active ? "text-white" : "text-muted"}`}>
              {stage.label}
            </span>
            {detail && (
              <ChevronDownIcon
                className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${
                  open ? "rotate-180" : ""
                }`}
              />
            )}
          </button>
          <div className="flex shrink-0 items-center gap-3">
            <span className={`text-xs ${meta.tone}`}>{meta.label}</span>
            {(stage.status === "failed" || stage.status === "unavailable") && (
              <button
                type="button"
                onClick={() => rerun.mutate(stage.stage)}
                disabled={rerun.isPending}
                title="Re-run this stage"
                className="text-muted transition-colors hover:text-white disabled:opacity-50"
                aria-label={`Re-run ${stage.label}`}
              >
                <RefreshIcon className={`h-3.5 w-3.5 ${rerun.isPending ? "animate-spin" : ""}`} />
              </button>
            )}
          </div>
        </div>
        {stage.status === "running" && (
          <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${Math.round((stage.progress || 0) * 100)}%` }}
            />
          </div>
        )}
        {open && detail && (
          <p className="mt-2 rounded-lg bg-white/[0.03] px-3 py-2 text-xs leading-relaxed text-muted">
            {detail}
          </p>
        )}
      </div>
    </li>
  );
}

export function ClipPlannerStages({
  planning,
  isLoading,
}: {
  planning: Planning | null | undefined;
  isLoading: boolean;
}) {
  if (isLoading && !planning) {
    return (
      <div className="flex items-center gap-3 text-sm text-muted">
        <SpinnerIcon className="h-4 w-4 animate-spin" />
        Loading clip plans…
      </div>
    );
  }

  if (!planning) {
    return (
      <div className="flex items-center gap-3 text-sm text-muted">
        <ClockIcon className="h-4 w-4" />
        Clip planning begins automatically once the virality assessment completes…
      </div>
    );
  }

  const isRunning = planning.status === "running" || planning.status === "pending";

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          <span className="font-medium text-white">{planning.completed_stages}</span> of{" "}
          {planning.total_stages} planning stages complete
          {isRunning && <span className="ml-2 text-accent">· planning…</span>}
        </p>
        <span className="text-[11px] uppercase tracking-wide text-muted">
          Planner pipeline v{planning.pipeline_version}
        </span>
      </div>
      <ol className="relative">
        {planning.stages.map((stage, index) => (
          <StageRow
            key={stage.stage}
            stage={stage}
            isLast={index === planning.stages.length - 1}
            projectId={planning.project_id}
          />
        ))}
      </ol>
    </div>
  );
}
