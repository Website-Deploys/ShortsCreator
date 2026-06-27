/**
 * Client-side video probing and thumbnail capture.
 *
 * Reads duration and resolution from the selected file and captures a real,
 * representative frame as a JPEG thumbnail - all in the browser, from the
 * original File (a same-origin blob URL, so the canvas is never tainted). This
 * gives genuine thumbnails and metadata with no server-side video tooling.
 *
 * Formats the browser cannot decode (some AVI/MKV) resolve with null metadata
 * and no thumbnail; callers then show a tasteful placeholder. Nothing is faked.
 */

export interface VideoProbe {
  durationSeconds: number | null;
  width: number | null;
  height: number | null;
  /** A representative JPEG frame, or null if the browser couldn't decode it. */
  thumbnail: Blob | null;
}

const EMPTY: VideoProbe = { durationSeconds: null, width: null, height: null, thumbnail: null };
const MAX_THUMB_WIDTH = 640;

export function probeVideo(file: File): Promise<VideoProbe> {
  return new Promise((resolve) => {
    if (typeof document === "undefined") {
      resolve(EMPTY);
      return;
    }

    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    video.playsInline = true;

    let duration: number | null = null;
    let width: number | null = null;
    let height: number | null = null;

    const finish = (thumbnail: Blob | null) => {
      resolve({ durationSeconds: duration, width, height, thumbnail });
      URL.revokeObjectURL(url);
    };

    video.onloadedmetadata = () => {
      duration = Number.isFinite(video.duration) ? video.duration : null;
      width = video.videoWidth || null;
      height = video.videoHeight || null;
      // Seek to a representative moment (a quarter in, capped at 1s) to capture.
      const target = Math.min(1, (video.duration || 2) / 4);
      try {
        video.currentTime = Number.isFinite(target) ? target : 0;
      } catch {
        finish(null);
      }
    };

    video.onseeked = () => {
      try {
        const w = video.videoWidth;
        const h = video.videoHeight;
        if (!w || !h) return finish(null);
        const scale = Math.min(1, MAX_THUMB_WIDTH / w);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        const ctx = canvas.getContext("2d");
        if (!ctx) return finish(null);
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => finish(blob), "image/jpeg", 0.82);
      } catch {
        finish(null);
      }
    };

    video.onerror = () => finish(null);
    video.src = url;
  });
}
