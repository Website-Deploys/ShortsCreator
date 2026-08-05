"use client";

/**
 * Protected candidate preview.
 *
 * Uses only the existing same-origin project-scoped media route. It seeks to the
 * exact candidate start, can stop at the candidate end, and offers a bounded
 * context replay that never changes the candidate boundaries. Successful
 * playback is not technical validation.
 */

import { useEffect, useRef, useState } from "react";

import {
  buildCandidatePreview,
  formatDuration,
  formatSourceWindow,
} from "@/lib/candidateReview";

export function BobaCandidatePreview({
  projectId,
  startSeconds,
  endSeconds,
  durationSeconds,
  contextSeconds,
  historical,
  validationStatus,
}: {
  projectId: string;
  startSeconds: number | null;
  endSeconds: number | null;
  durationSeconds: number | null;
  contextSeconds: number;
  historical: boolean;
  validationStatus: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [withContext, setWithContext] = useState(false);
  const reference =
    startSeconds === null || endSeconds === null
      ? null
      : { start_seconds: startSeconds, end_seconds: endSeconds };
  const preview = buildCandidatePreview(projectId, reference, contextSeconds);
  const playStart = withContext ? preview.contextStartSeconds : preview.startSeconds;
  const playEnd = withContext ? preview.contextEndSeconds : preview.endSeconds;

  // Keep playback inside the requested window without ever mutating the record.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || preview.url === null) return;
    const onTimeUpdate = () => {
      if (playEnd > 0 && video.currentTime >= playEnd) video.pause();
    };
    video.addEventListener("timeupdate", onTimeUpdate);
    return () => video.removeEventListener("timeupdate", onTimeUpdate);
  }, [playEnd, preview.url]);

  const replay = () => {
    const video = videoRef.current;
    if (!video) return;
    try {
      video.currentTime = playStart;
      void video.play();
    } catch {
      /* seeking may be unavailable for this source */
    }
  };

  return (
    <section aria-labelledby="candidate-preview-heading" className="space-y-2">
      <h3 id="candidate-preview-heading" className="text-sm font-semibold text-white/90">
        PROTECTED CANDIDATE PREVIEW
      </h3>

      <p className="text-[11px] text-white/60">
        <span aria-hidden="true" className="font-mono">
          {historical ? "[historical]" : "[current]"}
        </span>{" "}
        {historical ? "Historical candidate" : "Current candidate"} ·{" "}
        {startSeconds === null || endSeconds === null
          ? "No exact window bound"
          : `${formatSourceWindow(startSeconds, endSeconds)} (${formatDuration(
              durationSeconds ?? 0,
            )})`}
      </p>

      {preview.unavailableReason !== null ? (
        <p
          role="status"
          className="rounded-md border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60"
        >
          {preview.unavailableReason}
        </p>
      ) : (
        <>
          <video
            ref={videoRef}
            controls
            preload="metadata"
            playsInline
            src={`${preview.url}#t=${playStart}`}
            className="w-full rounded-lg border border-white/10 bg-black"
            aria-label="Candidate clip preview from the project source"
          >
            <track kind="captions" />
            Your browser cannot play this preview.
          </video>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={replay}
              className="min-h-[44px] rounded border border-white/15 px-2 text-xs text-white/85 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
            >
              Replay candidate window
            </button>
            <button
              type="button"
              onClick={() => setWithContext((value) => !value)}
              aria-pressed={withContext}
              className="min-h-[44px] rounded border border-white/15 px-2 text-xs text-white/85 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
            >
              {withContext ? "Candidate window only" : `Include ${contextSeconds}s context`}
            </button>
          </div>
          {withContext && (
            <p className="text-[11px] text-amber-100">{preview.contextNotice}</p>
          )}
        </>
      )}

      <p className="text-[11px] text-white/55">
        Playing successfully in the browser is not technical validation. Technical
        validation is owned by the Validator Runner and currently reports:{" "}
        <span className="text-white/75">{validationStatus.replace(/_/g, " ")}</span>.
      </p>
      <p className="text-[11px] text-white/45">
        The preview is read-only. It cannot edit, replace or overwrite source media or
        accepted outputs, and it cannot download, upload or publish.
      </p>
    </section>
  );
}
