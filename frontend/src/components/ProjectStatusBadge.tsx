/** A coloured badge that renders a project's lifecycle state in plain language. */
import type { ProjectState } from "@/lib/types";

const LABELS: Record<ProjectState, string> = {
  intake: "Starting",
  ingested: "Downloaded",
  audio_ready: "Audio extracted",
  transcribed: "Transcribed",
  understood: "Understood",
  selected: "Moments selected",
  planned: "Editing planned",
  rendered: "Rendering",
  complete: "Ready",
  failed: "Failed",
  cancelled: "Cancelled",
};

const TONE: Record<ProjectState, string> = {
  intake: "bg-white/10 text-muted",
  ingested: "bg-white/10 text-muted",
  audio_ready: "bg-white/10 text-muted",
  transcribed: "bg-white/10 text-muted",
  understood: "bg-white/10 text-muted",
  selected: "bg-white/10 text-muted",
  planned: "bg-white/10 text-muted",
  rendered: "bg-accent/20 text-accent",
  complete: "bg-green-500/20 text-green-300",
  failed: "bg-red-500/20 text-red-300",
  cancelled: "bg-white/10 text-muted",
};

export function ProjectStatusBadge({ state }: { state: ProjectState }) {
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-medium ${TONE[state]}`}>
      {LABELS[state]}
    </span>
  );
}
