"use client";

/**
 * The Cognitive Engine timeline — REAL, per-stage video-understanding progress.
 *
 * Unlike a static checklist, every row reflects the genuine state of an analysis
 * stage reported by the backend: completed stages are marked done, stages whose
 * model/tooling is not configured are shown honestly as "Unavailable" with the
 * backend's own explanation, and genuine failures are surfaced (never hidden).
 * Nothing here is fabricated — a stage is only "done" when it truly produced
 * output. Each stage can be re-run independently.
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
import { Button } from "@/components/ui/Button";
import { useRerunStage } from "@/lib/queries";
import type { Analysis, AnalysisStage, AnalysisStageStatus } from "@/lib/types";

const STATE_META: Record<
  AnalysisStageStatus,
  { label: string; tone: string; icon: "done" | "running" | "unavailable" | "failed" | "pending" }
> = {
  completed: { label: "Done", tone: "text-green-400", icon: "done" },
  running: { label: "Analyzing", tone: "text-accent", icon: "running" },
  unavailable: { label: "Unavailable", tone: "text-muted", icon: "unavailable" },
  failed: { label: "Failed", tone: "text-red-300", icon: "failed" },
  pending: { label: "Waiting", tone: "text-muted", icon: "pending" },
  cancelled: { label: "Cancelled", tone: "text-muted", icon: "pending" },
};

function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

function elapsedSeconds(startedAt: string | null) {
  if (!startedAt) return null;
  const started = Date.parse(startedAt);
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.floor((Date.now() - started) / 1000));
}

function runningDetail(stage: AnalysisStage) {
  if (stage.status !== "running") return null;
  const elapsed = elapsedSeconds(stage.started_at);
  const suffix = elapsed == null ? "" : ` Elapsed ${formatElapsed(elapsed)}.`;
  if (stage.stage === "speech_transcription") {
    return `Transcribing audio. This may take several minutes on CPU.${suffix}`;
  }
  if (elapsed != null && elapsed >= 90) {
    return `${stage.label} is still running.${suffix}`;
  }
  return null;
}

function StageIcon({ status }: { status: AnalysisStageStatus }) {
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
  stage: AnalysisStage;
  isLast: boolean;
  projectId: string;
}) {
  const [open, setOpen] = useState(false);
  const rerun = useRerunStage(projectId);
  const meta = STATE_META[stage.status];
  const detail = stage.reason ?? stage.error ?? null;
  const activeDetail = runningDetail(stage);

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
            <span
              className={`truncate text-sm font-medium ${
                stage.status === "completed" || stage.status === "running"
                  ? "text-white"
                  : "text-muted"
              }`}
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
        {activeDetail && <p className="mt-2 text-xs leading-relaxed text-muted">{activeDetail}</p>}
        {open && detail && (
          <p className="mt-2 rounded-lg bg-white/[0.03] px-3 py-2 text-xs leading-relaxed text-muted">
            {detail}
          </p>
        )}
      </div>
    </li>
  );
}

export function AnalysisTimeline({
  analysis,
  isLoading,
}: {
  analysis: Analysis | null | undefined;
  isLoading: boolean;
}) {
  if (isLoading && !analysis) {
    return (
      <div className="flex items-center gap-3 text-sm text-muted">
        <SpinnerIcon className="h-4 w-4 animate-spin" />
        Loading understanding…
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="flex items-center gap-3 text-sm text-muted">
        <ClockIcon className="h-4 w-4" />
        Preparing to understand your video…
      </div>
    );
  }

  const isRunning = analysis.status === "running" || analysis.status === "pending";

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          <span className="font-medium text-white">{analysis.completed_stages}</span> of{" "}
          {analysis.total_stages} analysis stages completed
          {isRunning && <span className="ml-2 text-accent">· analyzing…</span>}
        </p>
        <span className="text-[11px] uppercase tracking-wide text-muted">
          Pipeline v{analysis.pipeline_version}
        </span>
      </div>
      <ol className="relative">
        {analysis.stages.map((stage, index) => (
          <StageRow
            key={stage.stage}
            stage={stage}
            isLast={index === analysis.stages.length - 1}
            projectId={analysis.project_id}
          />
        ))}
      </ol>
    </div>
  );
}
