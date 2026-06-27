/**
 * Real file upload to the Olympus backend.
 *
 * Uses XMLHttpRequest (not fetch) because only XHR exposes upload *progress*
 * events, which we need for the percentage, speed, and ETA display. The upload
 * streams a multipart form to `POST /api/v1/uploads` - the real endpoint, no
 * mocks. Cancellation is supported via `xhr.abort()`.
 */

import { API_V1 } from "@/lib/config";
import type { ApiError } from "@/lib/types";

/** Progress reported during an upload. */
export interface UploadProgress {
  loaded: number;
  total: number;
  percent: number;
  /** Instantaneous transfer rate in bytes/second (null until measurable). */
  speedBps: number | null;
  /** Estimated seconds remaining (null until measurable). */
  etaSeconds: number | null;
}

/** The backend's successful upload response. */
export interface UploadResult {
  id: string;
  filename: string;
  size_bytes: number;
  content_type: string | null;
  video_format: string;
  storage_key: string;
}

/** A controllable, in-flight upload. */
export interface UploadHandle {
  promise: Promise<UploadResult>;
  cancel: () => void;
}

/** Thrown when the user cancels an upload (distinct from a real error). */
export class UploadCancelledError extends Error {
  constructor() {
    super("Upload cancelled.");
    this.name = "UploadCancelledError";
  }
}

/** Thrown when the upload fails (network or server error). */
export class UploadError extends Error {
  readonly code: string;
  constructor(message: string, code = "upload_error") {
    super(message);
    this.name = "UploadError";
    this.code = code;
  }
}

export function uploadVideo(
  file: File,
  onProgress: (progress: UploadProgress) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();
  const form = new FormData();
  form.append("file", file, file.name);

  const startedAt = performance.now();
  let lastLoaded = 0;
  let lastTime = startedAt;
  let speedBps: number | null = null;

  const promise = new Promise<UploadResult>((resolve, reject) => {
    xhr.upload.onprogress = (event: ProgressEvent) => {
      if (!event.lengthComputable) return;
      const now = performance.now();
      const dt = (now - lastTime) / 1000;
      if (dt >= 0.2) {
        const instant = (event.loaded - lastLoaded) / dt;
        // Smooth the rate so the display does not jitter.
        speedBps = speedBps == null ? instant : speedBps * 0.6 + instant * 0.4;
        lastLoaded = event.loaded;
        lastTime = now;
      }
      const remaining = event.total - event.loaded;
      const etaSeconds = speedBps && speedBps > 0 ? remaining / speedBps : null;
      onProgress({
        loaded: event.loaded,
        total: event.total,
        percent: event.total > 0 ? Math.round((event.loaded / event.total) * 100) : 0,
        speedBps,
        etaSeconds,
      });
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResult);
        } catch {
          reject(new UploadError("The server returned an unexpected response."));
        }
        return;
      }
      // Try to surface the backend's structured error message.
      let message = `Upload failed (${xhr.status}).`;
      let code = "upload_error";
      try {
        const body = JSON.parse(xhr.responseText) as ApiError;
        message = body.error?.message ?? message;
        code = body.error?.code ?? code;
      } catch {
        /* non-JSON error body */
      }
      reject(new UploadError(message, code));
    };

    xhr.onerror = () =>
      reject(new UploadError("Could not reach the server. Is the backend running?", "network_error"));
    xhr.onabort = () => reject(new UploadCancelledError());

    xhr.open("POST", `${API_V1}/uploads`);
    xhr.send(form);
  });

  return { promise, cancel: () => xhr.abort() };
}
