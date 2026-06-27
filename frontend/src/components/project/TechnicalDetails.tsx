"use client";

/**
 * "Technical Details" - a collapsed-by-default panel for power users.
 *
 * Shows only *real* information about the project (status, identifiers,
 * timestamps, stored file). It never fabricates logs or AI output. Normal users
 * never need to open it.
 */
import { ChevronDownIcon } from "@/components/icons";
import type { Project } from "@/lib/types";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-muted">{label}</span>
      <span className="break-all text-right font-mono text-xs text-white/80">{value}</span>
    </div>
  );
}

export function TechnicalDetails({ project }: { project: Project }) {
  return (
    <details className="group rounded-xl border border-white/10 bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-sm font-medium text-muted transition-colors hover:text-white">
        Technical details
        <ChevronDownIcon className="h-4 w-4 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-white/10 px-5 py-4 text-sm">
        <Row label="Project ID" value={project.id} />
        <Row label="Status" value={project.status} />
        <Row label="Stored file" value={project.source_filename} />
        <Row label="Format" value={project.video_format} />
        <Row label="Content type" value={project.content_type ?? "unknown"} />
        <Row label="Created" value={new Date(project.created_at).toLocaleString()} />
        <Row label="Updated" value={new Date(project.updated_at).toLocaleString()} />
        <p className="mt-3 text-xs text-muted">
          No errors or warnings. Backend messages and per-stage timings will appear here once the
          editing pipeline is connected.
        </p>
      </div>
    </details>
  );
}
