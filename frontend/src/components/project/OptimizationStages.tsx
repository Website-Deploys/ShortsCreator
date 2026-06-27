"use client";

/**
 * The Optimization Engine pipeline progress — REAL, per-stage status reported by
 * the backend, grouped into the engine's logical sections (Render, Audio,
 * Captions, Visual, Metadata & Export, Evaluation & Packaging).
 *
 * Each row reflects a stage's genuine state: completed stages are marked done;
 * stages that lack the rendered media or an enhancement model are shown honestly
 * as "Unavailable" with the backend's own reason; genuine failures are surfaced.
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
import { STAGE_GROUPS, stageTally } from "@/lib/optimization";
import { useRerunOptimizationStage } from "@/lib/queries";
import type { Optimization, OptimizationStage, OptimizationStageStatus } from "@/lib/types";

const STATE_META: Record<
  OptimizationStageStatus,
  { label: string; tone: string; icon: "done" | "running" | "unavailable" | "failed" | "pending" }
> = {
  completed: { label: "Done", tone: "text-green-400", icon: "done" },
  running: { label: "Optimizing", tone: "text-accent", icon: "running" },
  unavailable: { label: "Unavailable", tone: "text-amber-300", icon: "unavailable" },
  failed: { label: "Failed", tone: "text-red-300", icon: "failed" },
  pending: { label: "Waiting", tone: "text-muted", icon: "pending" },
  cancelled: { label: "Cancelled", tone: "text-muted", icon: "pending" },
};

function StageIcon({ status }: { status: OptimizationStageStatus }) {
  const kind = STATE_META[status].icon;
  if (kind === "done") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-green-500/15">
        <CheckCircleIcon className="h-4 w-4 text-green-400" />
      </span>
    );
  }
  if (kind === "running") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/15">
        <SpinnerIcon className="h-4 w-4 animate-spin text-accent" />
      </span>
    );
  }
  if (kind === "failed") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-red-500/15">
        <AlertIcon className="h-4 w-4 text-red-300" />
      </span>
    );
  }
  if (kind === "unavailable") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-500/10">
        <MinusCircleIcon className="h-4 w-4 text-amber-300/80" />
      </span>
    );
  }
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/5">
      <span className="h-2 w-2 rounded-full bg-white/25" />
    </span>
  );
}

function StageRow({ stage, projectId }: { stage: OptimizationStage; projectId: string }) {
  const [open, setOpen] = useState(false);
  const rerun = useRerunOptimizationStage(projectId);
  const meta = STATE_META[stage.status];
  const detail = stage.reason ?? stage.error ?? null;
  const active = stage.status === "completed" || stage.status === "running";

  return (
    <li className="flex gap-3 py-2">
      <StageIcon status={stage.status} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <button
            type="button"
            onClick={() => detail && setOpen((v) => !v)}
            className={`group flex min-w-0 items-center gap-2 text-left ${
              detail ? "cursor-pointer" : "cursor-default"
            }`}
            aria-expanded={detail ? open : undefined}
          >
            <span
              className={`truncate text-sm ${active ? "font-medium text-white" : "text-muted"}`}
            >
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

export function OptimizationStages({
  optimization,
  isLoading,
}: {
  optimization: Optimization | null | undefined;
  isLoading: boolean;
}) {
  if (isLoading && !optimization) {
    return (
      <div className="flex items-center gap-3 text-sm text-muted">
        <SpinnerIcon className="h-4 w-4 animate-spin" />
        Loading optimization…
      </div>
    );
  }

  if (!optimization) {
    return (
      <div className="flex items-center gap-3 text-sm text-muted">
        <ClockIcon className="h-4 w-4" />
        Optimization runs on a finished render. Start it once a Short has been rendered.
      </div>
    );
  }

  const byName = new Map(optimization.stages.map((s) => [s.stage, s]));
  const isRunning = optimization.status === "running" || optimization.status === "pending";
  const tally = stageTally(optimization.stages);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          <span className="font-medium text-white">{tally.completed}</span> done ·{" "}
          <span className="text-amber-300">{tally.unavailable}</span> unavailable
          {tally.failed > 0 && <span className="text-red-300"> · {tally.failed} failed</span>} of{" "}
          {tally.total} stages
          {isRunning && <span className="ml-2 text-accent">· optimizing…</span>}
        </p>
        <span className="text-[11px] uppercase tracking-wide text-muted">
          Optimization pipeline v{optimization.pipeline_version}
        </span>
      </div>

      <div className="space-y-5">
        {STAGE_GROUPS.map((group) => {
          const stages = group.stages
            .map((name) => byName.get(name))
            .filter((s): s is OptimizationStage => s != null);
          if (stages.length === 0) return null;
          return (
            <div key={group.title}>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
                {group.title}
              </p>
              <ul className="divide-y divide-white/5">
                {stages.map((stage) => (
                  <StageRow key={stage.stage} stage={stage} projectId={optimization.project_id} />
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
