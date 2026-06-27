/** A coloured badge rendering a project's status in plain language. */
import type { ProjectStatus } from "@/lib/types";

const CONFIG: Record<ProjectStatus, { label: string; className: string; dot: string }> = {
  uploaded: { label: "Ready", className: "bg-white/5 text-muted", dot: "bg-muted" },
  analyzing: { label: "Analyzing", className: "bg-sky-500/10 text-sky-300", dot: "bg-sky-400" },
  analyzed: { label: "Understood", className: "bg-sky-500/10 text-sky-300", dot: "bg-sky-400" },
  queued: { label: "Queued", className: "bg-accent/10 text-accent", dot: "bg-accent" },
  processing: { label: "Processing", className: "bg-accent/10 text-accent", dot: "bg-accent" },
  complete: { label: "Complete", className: "bg-green-500/10 text-green-300", dot: "bg-green-400" },
  failed: { label: "Failed", className: "bg-red-500/10 text-red-300", dot: "bg-red-400" },
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  const config = CONFIG[status];
  const animate = status === "queued" || status === "processing" || status === "analyzing";
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${config.className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${config.dot} ${animate ? "animate-pulse-soft" : ""}`} />
      {config.label}
    </span>
  );
}
