"use client";

/**
 * Protected, same-origin preview.
 *
 * Playback uses only the existing project-scoped backend media routes. Arbitrary
 * paths, absolute paths, UNC paths, file URIs, traversal and external URLs are
 * refused. Successful playback is not technical validation.
 */

import { protectedPreviewUrl } from "@/lib/reviewUi";

export function BobaReviewPreview({
  projectId,
  clipId,
  validationStatus,
}: {
  projectId: string;
  clipId?: string | null;
  validationStatus: string;
}) {
  const source = protectedPreviewUrl(projectId, clipId ?? null);
  return (
    <section aria-labelledby="review-preview-heading" className="space-y-2">
      <h3 id="review-preview-heading" className="text-sm font-semibold text-white/90">
        PROTECTED PREVIEW
      </h3>
      {source === null ? (
        <p role="status" className="rounded-md border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60">
          Preview unavailable. No protected same-origin reference exists for this item.
        </p>
      ) : (
        <video
          controls
          preload="metadata"
          playsInline
          src={source}
          className="w-full rounded-lg border border-white/10 bg-black"
        >
          <track kind="captions" />
          Your browser cannot play this preview.
        </video>
      )}
      <p className="text-[11px] text-white/55">
        Playing successfully in the browser is not technical validation. Technical validation is
        owned by the Validator Runner and currently reports:{" "}
        <span className="text-white/75">{validationStatus.replace(/_/g, " ")}</span>.
      </p>
      <p className="text-[11px] text-white/45">
        The preview is read-only. It cannot edit, replace or overwrite source media or accepted
        outputs, and it cannot upload or publish.
      </p>
    </section>
  );
}
