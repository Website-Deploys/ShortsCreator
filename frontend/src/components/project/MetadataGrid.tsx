"use client";

/**
 * Rich video information, presented as clean stat cards.
 *
 * Shows real values where they are genuinely known (filename, duration,
 * resolution, aspect ratio, container, size, upload date/time/duration) and an
 * honest "—" with a tooltip for details that require server-side media analysis
 * (fps, codec, bitrate, audio channels, sample rate). Nothing is fabricated.
 */
import { Tooltip } from "@/components/ui/Tooltip";
import {
  formatAspectRatio,
  formatBytes,
  formatDate,
  formatDuration,
  formatMillis,
  formatResolution,
  formatTime,
} from "@/lib/format";
import type { Project } from "@/lib/types";

interface Item {
  label: string;
  value: string;
  /** When true, the value isn't available yet (shown as "—" with a tooltip). */
  pending?: boolean;
}

const PENDING_HINT = "Detected when the editing pipeline analyses your video";

function Stat({ item }: { item: Item }) {
  return (
    <div className="rounded-lg border border-white/10 bg-surface px-4 py-3">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted">{item.label}</dt>
      <dd className="mt-1 truncate text-sm font-medium" title={item.pending ? undefined : item.value}>
        {item.pending ? (
          <Tooltip label={PENDING_HINT}>
            <span className="cursor-help text-muted">—</span>
          </Tooltip>
        ) : (
          item.value
        )}
      </dd>
    </div>
  );
}

export function MetadataGrid({ project }: { project: Project }) {
  const items: Item[] = [
    { label: "Filename", value: project.source_filename },
    { label: "Container", value: project.video_format.toUpperCase() },
    { label: "Duration", value: formatDuration(project.duration_seconds) },
    { label: "Resolution", value: formatResolution(project.width, project.height) },
    { label: "Aspect ratio", value: formatAspectRatio(project.width, project.height) },
    { label: "Frame rate", value: "", pending: true },
    { label: "Video codec", value: "", pending: true },
    { label: "Video bitrate", value: "", pending: true },
    { label: "Audio bitrate", value: "", pending: true },
    { label: "Audio channels", value: "", pending: true },
    { label: "Sample rate", value: "", pending: true },
    { label: "File size", value: formatBytes(project.size_bytes) },
    { label: "Upload date", value: formatDate(project.created_at) },
    { label: "Upload time", value: formatTime(project.created_at) },
    { label: "Upload duration", value: formatMillis(project.upload_duration_ms) },
    { label: "Storage used", value: formatBytes(project.size_bytes) },
  ];

  return (
    <dl className="grid grid-cols-2 gap-3">
      {items.map((item) => (
        <Stat key={item.label} item={item} />
      ))}
    </dl>
  );
}
