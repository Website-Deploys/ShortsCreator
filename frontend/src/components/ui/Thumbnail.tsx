"use client";

/**
 * A project thumbnail that gracefully falls back to a tasteful placeholder.
 *
 * Loads the real captured frame from the backend when available; on any error
 * (or when none exists) it renders a clean placeholder so cards are never blank.
 */
import { useState } from "react";

import { FileVideoIcon } from "@/components/icons";
import { mediaUrls } from "@/lib/apiClient";

interface ThumbnailProps {
  projectId: string;
  hasThumbnail: boolean;
  className?: string;
  /** Tailwind size for the placeholder icon. */
  iconClassName?: string;
}

export function Thumbnail({
  projectId,
  hasThumbnail,
  className = "",
  iconClassName = "h-6 w-6",
}: ThumbnailProps) {
  const [failed, setFailed] = useState(false);
  const showImage = hasThumbnail && !failed;

  return (
    <div
      className={`relative flex items-center justify-center overflow-hidden bg-elevated text-muted ${className}`}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={mediaUrls.thumbnail(projectId)}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        <FileVideoIcon className={iconClassName} />
      )}
    </div>
  );
}
