"use client";

/**
 * The Rendering view - a read-only window into a project's render execution.
 *
 * It surfaces only REAL engine outputs: the published render manifest (rendered
 * clips with measured resolution/duration/codec/size and a checksum over the
 * actual bytes), an inline preview player + download for each rendered MP4, the
 * per-stage render logs, and the validation report. When rendering was
 * unavailable (e.g. FFmpeg absent) it says so honestly - it never shows a
 * fabricated file or a broken download.
 */
import { useMemo, useState } from "react";

import { AlertIcon, CheckCircleIcon, DownloadIcon, ServerIcon } from "@/components/icons";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { mediaUrls } from "@/lib/apiClient";
import { useRenderLogs, useRenderManifest, useRenderValidation } from "@/lib/queries";
import {
  formatBytes,
  formatDuration,
  isTerminal,
  shortChecksum,
} from "@/lib/rendering";
import type { RenderRun, RenderedVideo } from "@/lib/types";

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-3 text-sm font-semibold text-white">{children}</h4>;
}

/* ------------------------------ output files ------------------------------ */

function OutputFile({ projectId, render }: { projectId: string; render: RenderedVideo }) {
  const url = mediaUrls.renderClip(projectId, render.clip_id);
  return (
    <div className="rounded-xl border border-white/10 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{render.clip_id}</p>
          <p className="mt-0.5 text-[11px] text-muted">
            {render.width}×{render.height} · {formatDuration(render.duration)} ·{" "}
            {render.video_codec ?? "—"}/{render.audio_codec ?? "—"} · {formatBytes(render.size_bytes)}
          </p>
        </div>
        <a
          href={url}
          download
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1 text-xs text-white transition-colors hover:border-white/30"
        >
          <DownloadIcon className="h-3.5 w-3.5" />
          Download MP4
        </a>
      </div>
      {/* Real preview player pointing at the rendered file. */}
      <video
        controls
        preload="metadata"
        className="mt-3 w-full max-w-[240px] rounded-lg border border-white/10 bg-black"
        src={url}
      >
        <track kind="captions" />
      </video>
      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted">
        {render.subtitles_included && (
          <span className="rounded bg-white/5 px-2 py-0.5">captions burned</span>
        )}
        {render.music_included && <span className="rounded bg-white/5 px-2 py-0.5">music</span>}
        {shortChecksum(render.checksum) && (
          <span className="rounded bg-white/5 px-2 py-0.5" title={render.checksum ?? undefined}>
            {shortChecksum(render.checksum)}
          </span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------ logs panel -------------------------------- */

function LogsPanel({ projectId, enabled }: { projectId: string; enabled: boolean }) {
  const { data } = useRenderLogs(projectId, enabled);
  const stages = data?.stages ?? [];
  if (stages.length === 0) {
    return (
      <Card>
        <SectionTitle>Render logs</SectionTitle>
        <p className="text-sm text-muted">No logs yet.</p>
      </Card>
    );
  }
  return (
    <Card>
      <SectionTitle>Render logs</SectionTitle>
      <div className="max-h-72 space-y-2 overflow-y-auto font-mono text-[11px] leading-relaxed">
        {stages.map((s) => (
          <div key={s.stage}>
            <p className="text-muted">
              <span className="text-white/80">{s.stage}</span> [{s.status}]
            </p>
            {s.reason && <p className="pl-3 text-amber-300/80">{s.reason}</p>}
            {s.error && <p className="pl-3 text-rose-300/80">{s.error}</p>}
            {s.lines.map((line, i) => (
              <p key={i} className="pl-3 text-muted">
                {line}
              </p>
            ))}
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ------------------------------ validation -------------------------------- */

function ValidationPanel({ projectId, enabled }: { projectId: string; enabled: boolean }) {
  const { data } = useRenderValidation(projectId, enabled);
  const report = data?.report;
  if (!report) return null;
  const ok = report.valid === true && report.manifest_written === true;
  const unavailable = Array.isArray(report.unavailable_stages)
    ? (report.unavailable_stages as { stage: string; reason: string }[])
    : [];
  return (
    <div
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
        ok
          ? "border-emerald-500/20 bg-emerald-500/[0.06]"
          : "border-amber-500/20 bg-amber-500/[0.06]"
      }`}
    >
      <span className="mt-0.5 shrink-0">
        {ok ? (
          <CheckCircleIcon className="h-5 w-5 text-emerald-400" />
        ) : (
          <AlertIcon className="h-5 w-5 text-amber-300" />
        )}
      </span>
      <div className="min-w-0">
        <p className={`text-sm font-medium ${ok ? "text-emerald-300" : "text-amber-200"}`}>
          {ok
            ? "Render validated and manifest published"
            : "Render completed without producing a manifest"}
        </p>
        {!ok && unavailable.length > 0 && (
          <ul className="mt-1.5 space-y-1 text-xs text-muted">
            {unavailable.map((u) => (
              <li key={u.stage}>
                <span className="text-white/70">{u.stage}</span> — {u.reason}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* --------------------------------- view ----------------------------------- */

export function RenderingView({ render }: { render: RenderRun }) {
  const terminal = isTerminal(render);
  const manifestQuery = useRenderManifest(render.project_id, terminal);
  const [showManifest, setShowManifest] = useState(false);

  const renders = useMemo(
    () => manifestQuery.data?.manifest.renders ?? [],
    [manifestQuery.data],
  );
  const manifestReasonStage = render.stages.find((s) => s.stage === "generate_render_manifest");

  if (!terminal) {
    return (
      <Card>
        <p className="text-sm text-muted">Rendering… output appears as each clip completes.</p>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <ValidationPanel projectId={render.project_id} enabled={terminal} />

      <Card>
        <div className="flex items-center justify-between gap-3">
          <SectionTitle>Output files</SectionTitle>
          {renders.length > 0 && (
            <a
              href={mediaUrls.renderManifest(render.project_id)}
              download
              className="text-xs text-muted underline-offset-2 hover:text-white hover:underline"
            >
              Download manifest
            </a>
          )}
        </div>
        {renders.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {renders.map((r) => (
              <OutputFile key={r.clip_id} projectId={render.project_id} render={r} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<ServerIcon className="h-6 w-6" />}
            title="No rendered files were produced"
            description={
              manifestReasonStage?.reason ??
              "The render plan was built, but no MP4 was produced. This usually means the renderer (e.g. FFmpeg) is unavailable in this environment - reported honestly rather than fabricated."
            }
          />
        )}
      </Card>

      {renders.length > 0 && (
        <Card>
          <button
            type="button"
            onClick={() => setShowManifest((v) => !v)}
            className="text-xs text-muted hover:text-white"
          >
            {showManifest ? "Hide" : "Show"} render manifest JSON
          </button>
          {showManifest && (
            <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-black/40 p-3 text-[11px] leading-relaxed text-muted">
              {JSON.stringify(manifestQuery.data?.manifest, null, 2)}
            </pre>
          )}
        </Card>
      )}

      <LogsPanel projectId={render.project_id} enabled={terminal} />
    </div>
  );
}
