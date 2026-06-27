"use client";

/**
 * The results section.
 *
 * HONESTY: no Shorts are generated until the editing pipeline is connected, so
 * this currently shows a clear, premium "coming soon" state - it never invents
 * clips, thumbnails, or viral scores. The premium card layout (commented intent
 * below) renders automatically once real clips exist.
 */
import { SparklesIcon } from "@/components/icons";
import { EmptyState } from "@/components/ui/EmptyState";
import type { Clip } from "@/lib/types";

export function ResultsSection({ clips }: { clips: Clip[] }) {
  if (clips.length === 0) {
    return (
      <EmptyState
        icon={<SparklesIcon className="h-6 w-6" />}
        title="Your Shorts will appear here"
        description="Once the AI editing pipeline runs, Olympus will present each generated Short as a card with a preview, length, and download. Nothing is generated yet — we never show results we haven't truly produced."
      />
    );
  }

  // Premium results grid (used when real clips exist).
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {clips.map((clip) => (
        <div key={clip.id} className="overflow-hidden rounded-xl border border-white/10 bg-surface">
          <div className="aspect-[9/16] bg-elevated" />
          <div className="p-4">
            <p className="truncate text-sm font-medium">{clip.title}</p>
            <p className="mt-1 text-xs text-muted">Viral score: Coming soon</p>
          </div>
        </div>
      ))}
    </div>
  );
}
