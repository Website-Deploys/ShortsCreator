"use client";

/**
 * The upload card - the centrepiece of the landing page.
 *
 * State machine: idle -> uploading -> finalizing -> (navigate) | error,
 * with a drag-over highlight on idle.
 *
 * It performs a real upload to the backend, shows live filename / size /
 * progress / speed / ETA with cancel and retry, reads duration & resolution
 * client-side, and on success automatically creates the project and continues
 * to the project page - no unnecessary button presses. Accessible throughout.
 */
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import { AlertIcon, FileVideoIcon, UploadCloudIcon, XIcon } from "@/components/icons";
import { useToast } from "@/components/notifications/ToastProvider";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/apiClient";
import { formatBytes, formatEta, formatSpeed } from "@/lib/format";
import { probeVideo, type VideoProbe } from "@/lib/media";
import { useCreateProject } from "@/lib/queries";
import {
  UploadCancelledError,
  uploadVideo,
  type UploadHandle,
  type UploadProgress,
} from "@/lib/upload";

const ACCEPT = "video/*,.mp4,.mov,.avi,.mkv,.webm";
const ACCEPTED_EXTENSIONS = ["mp4", "mov", "avi", "mkv", "webm"];

type Status = "idle" | "uploading" | "finalizing" | "error";

function hasAcceptedExtension(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return ACCEPTED_EXTENSIONS.includes(ext);
}

export function UploadCard() {
  const router = useRouter();
  const { notify } = useToast();
  const createProject = useCreateProject();

  const [status, setStatus] = useState<Status>("idle");
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const handleRef = useRef<UploadHandle | null>(null);
  const probeRef = useRef<Promise<VideoProbe> | null>(null);
  const startRef = useRef<number>(0);

  const reset = useCallback(() => {
    handleRef.current?.cancel();
    handleRef.current = null;
    setStatus("idle");
    setFile(null);
    setProgress(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const beginUpload = useCallback(
    (selected: File) => {
      setFile(selected);
      setError(null);
      setProgress({ loaded: 0, total: selected.size, percent: 0, speedBps: null, etaSeconds: null });
      setStatus("uploading");
      probeRef.current = probeVideo(selected);
      startRef.current = performance.now();

      const handle = uploadVideo(selected, setProgress);
      handleRef.current = handle;
      handle.promise
        .then(async (result) => {
          setStatus("finalizing");
          const probe = (await probeRef.current) ?? null;
          const project = await createProject.mutateAsync({
            storage_key: result.storage_key,
            source_filename: result.filename,
            size_bytes: result.size_bytes,
            video_format: result.video_format,
            content_type: result.content_type,
            duration_seconds: probe?.durationSeconds ?? null,
            width: probe?.width ?? null,
            height: probe?.height ?? null,
            upload_duration_ms: Math.round(performance.now() - startRef.current),
          });
          // Best-effort: attach the captured frame as the project thumbnail.
          if (probe?.thumbnail) {
            try {
              await api.uploadThumbnail(project.id, probe.thumbnail);
            } catch {
              /* a missing thumbnail is non-fatal; a placeholder is shown */
            }
          }
          notify({ tone: "success", title: "Upload complete", description: result.filename });
          router.push(`/projects/${project.id}`);
        })
        .catch((err: unknown) => {
          if (err instanceof UploadCancelledError) return;
          const message = err instanceof Error ? err.message : "Something went wrong.";
          setError(message);
          setStatus("error");
          notify({ tone: "error", title: "Upload failed", description: message });
        });
    },
    [createProject, notify, router],
  );

  const onFileChosen = useCallback(
    (selected: File | undefined) => {
      if (!selected) return;
      if (!hasAcceptedExtension(selected.name)) {
        setFile(selected);
        setError("Unsupported format. Please use MP4, MOV, AVI, MKV, or WEBM.");
        setStatus("error");
        return;
      }
      beginUpload(selected);
    },
    [beginUpload],
  );

  const onDragOver = (event: React.DragEvent) => {
    if (status !== "idle") return;
    event.preventDefault();
    setDragging(true);
  };
  const onDragLeave = (event: React.DragEvent) => {
    event.preventDefault();
    setDragging(false);
  };
  const onDrop = (event: React.DragEvent) => {
    if (status !== "idle") return;
    event.preventDefault();
    setDragging(false);
    onFileChosen(event.dataTransfer.files?.[0]);
  };

  return (
    <section
      aria-label="Upload your video"
      className="w-full rounded-2xl border border-white/10 bg-surface p-6 shadow-2xl shadow-black/30 sm:p-8"
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        aria-hidden="true"
        tabIndex={-1}
        onChange={(event) => onFileChosen(event.target.files?.[0])}
      />

      <div className="sr-only" role="status" aria-live="polite">
        {status === "uploading" && `Uploading ${progress?.percent ?? 0} percent.`}
        {status === "finalizing" && "Upload complete. Preparing your project."}
        {status === "error" && (error ?? "Upload failed.")}
      </div>

      {status === "idle" && (
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-14 text-center transition-colors ${
            dragging ? "border-accent bg-accent/10" : "border-white/15"
          }`}
        >
          <UploadCloudIcon className={`h-14 w-14 ${dragging ? "text-accent" : "text-muted"}`} />
          <p className="mt-5 text-lg font-medium">Drag &amp; Drop your video here</p>
          <p className="mt-1 text-sm text-muted">or</p>
          <div className="mt-4">
            <Button onClick={() => inputRef.current?.click()}>Browse files</Button>
          </div>
        </div>
      )}

      {(status === "uploading" || status === "finalizing") && file && (
        <div>
          <div className="flex items-start gap-3">
            <FileVideoIcon className="mt-0.5 h-6 w-6 shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium" title={file.name}>
                {file.name}
              </p>
              <p className="text-sm text-muted">
                {status === "finalizing"
                  ? "Preparing your project…"
                  : `${formatBytes(progress?.loaded ?? 0)} of ${formatBytes(progress?.total ?? file.size)}`}
              </p>
            </div>
            {status === "uploading" && (
              <button
                type="button"
                onClick={reset}
                aria-label="Cancel upload"
                className="rounded-md p-1 text-muted transition-colors hover:bg-white/10 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <XIcon className="h-5 w-5" />
              </button>
            )}
          </div>

          <div
            className="mt-5 h-2 w-full overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            aria-valuenow={status === "finalizing" ? 100 : (progress?.percent ?? 0)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Upload progress"
          >
            <div
              className={`h-full rounded-full bg-accent transition-[width] duration-200 ${status === "finalizing" ? "animate-pulse-soft" : ""}`}
              style={{ width: `${status === "finalizing" ? 100 : (progress?.percent ?? 0)}%` }}
            />
          </div>

          {status === "uploading" && progress && (
            <div className="mt-3 flex items-center justify-between text-sm text-muted">
              <span className="font-medium text-white">{progress.percent}%</span>
              <span className="flex gap-4">
                <span>{formatSpeed(progress.speedBps ?? 0)}</span>
                <span>{formatEta(progress.etaSeconds)}</span>
              </span>
            </div>
          )}
        </div>
      )}

      {status === "error" && (
        <div className="text-center">
          <AlertIcon className="mx-auto h-10 w-10 text-red-400" />
          <h2 className="mt-4 text-lg font-semibold">Upload failed</h2>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted">{error}</p>
          <div className="mt-6 flex justify-center gap-3">
            {file && hasAcceptedExtension(file.name) && (
              <Button onClick={() => beginUpload(file)}>Retry</Button>
            )}
            <Button variant="secondary" onClick={reset}>
              Choose another file
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
