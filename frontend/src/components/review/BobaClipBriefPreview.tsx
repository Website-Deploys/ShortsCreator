"use client";

/**
 * Preview of the exact persisted source window.
 *
 * The player is bound to the owner's start and end seconds. The browser cannot
 * substitute its own range, the context hint is read-only and non-authoritative,
 * and playing the preview validates and approves nothing.
 */

import { useEffect, useRef } from "react";

import {
  MAX_PREVIEW_CONTEXT_SECONDS,
  buildClipBriefPreview,
  formatSourceWindow,
  type ClipBriefReference,
} from "@/lib/clipBriefReview";

export function BobaClipBriefPreview({
  projectId,
  reference,
  contextSeconds,
  onContextSecondsChange,
}: {
  projectId: string;
  reference: ClipBriefReference | null;
  contextSeconds: number;
  onContextSecondsChange: (value: number) => void;
}) {
  const preview = buildClipBriefPreview(projectId, reference, contextSeconds);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const element = videoRef.current;
    if (!element || preview.url === null) return;
    element.currentTime = preview.contextStartSeconds;
  }, [preview.url, preview.contextStartSeconds]);

  if (preview.unavailableReason !== null) {
    return (
      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm text-white/60">
        <p>{preview.unavailableReason}</p>
        <p className="mt-1 text-[11px] text-white/40">
          Nothing is generated to stand in for a missing preview.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <video
        ref={videoRef}
        src={preview.url ?? undefined}
        controls
        preload="metadata"
        className="w-full rounded-lg border border-white/10 bg-black"
      />
      <p className="text-xs text-white/60">
        Persisted brief window{" "}
        {formatSourceWindow(preview.startSeconds, preview.endSeconds)}
      </p>
      <label className="flex items-center gap-2 text-xs text-white/50">
        Context seconds
        <input
          type="range"
          min={0}
          max={MAX_PREVIEW_CONTEXT_SECONDS}
          value={contextSeconds}
          onChange={(event) => onContextSecondsChange(Number(event.target.value))}
          aria-label="Preview context seconds"
        />
        <span>{contextSeconds}s</span>
      </label>
      <p className="text-[11px] text-white/40">{preview.contextNotice}</p>
      <p className="text-[11px] text-white/40">{preview.playbackNotice}</p>
    </div>
  );
}
