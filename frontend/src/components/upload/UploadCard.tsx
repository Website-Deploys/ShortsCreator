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

import { AlertIcon, FileVideoIcon, NetworkIcon, UploadCloudIcon, XIcon } from "@/components/icons";
import { useToast } from "@/components/notifications/ToastProvider";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/apiClient";
import { formatBytes, formatDuration, formatEta, formatSpeed } from "@/lib/format";
import { probeVideo, type VideoProbe } from "@/lib/media";
import { useCreateProject, useCreateProjectFromLink } from "@/lib/queries";
import type { CreateProjectFromLinkResponse } from "@/lib/types";
import {
  UploadCancelledError,
  uploadVideo,
  type UploadHandle,
  type UploadProgress,
} from "@/lib/upload";

const ACCEPT = "video/*,.mp4,.mov,.avi,.mkv,.webm";
const ACCEPTED_EXTENSIONS = ["mp4", "mov", "avi", "mkv", "webm"];

type Status = "idle" | "uploading" | "linking" | "finalizing" | "error";
type IntakeMode = "upload" | "link";
type V2Settings = {
  desired_clip_count: number | null;
  content_category: string;
  editing_intensity: string;
  music_enabled: boolean;
  sfx_enabled: boolean;
  captions_enabled: boolean;
};

const CONTENT_TYPES = [
  "auto",
  "podcast / talking",
  "stream",
  "motivation",
  "educational",
  "entertainment",
];
const INTENSITIES = ["auto", "clean", "balanced", "high-energy"];

const TERMINAL_LINK_STATUSES = new Set(["failed", "unavailable"]);

function isSupportedLink(value: string): boolean {
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    return (
      parsed.protocol === "https:" &&
      ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"].includes(host)
    );
  } catch {
    return false;
  }
}

function linkStageLabel(stage: string | undefined): string {
  return {
    metadata_extracting: "Fetching metadata",
    validated: "Metadata ready",
    downloading: "Downloading source",
    merging: "Merging video and audio",
    probing: "Validating source video",
    stored: "Preparing project",
    processing_started: "Analyzing story",
  }[stage ?? ""] ?? "Preparing linked video";
}

function hasAcceptedExtension(name: string): boolean {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return ACCEPTED_EXTENSIONS.includes(ext);
}

export function UploadCard() {
  const router = useRouter();
  const { notify } = useToast();
  const createProject = useCreateProject();
  const createProjectFromLink = useCreateProjectFromLink();

  const [status, setStatus] = useState<Status>("idle");
  const [intakeMode, setIntakeMode] = useState<IntakeMode>("upload");
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [permissionConfirmed, setPermissionConfirmed] = useState(false);
  const [linkResult, setLinkResult] = useState<CreateProjectFromLinkResponse | null>(null);
  const [contentCategory, setContentCategory] = useState("auto");
  const [editingIntensity, setEditingIntensity] = useState("auto");
  const [musicEnabled, setMusicEnabled] = useState(true);
  const [sfxEnabled, setSfxEnabled] = useState(true);
  const [captionsEnabled, setCaptionsEnabled] = useState(true);

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
    setVideoUrl("");
    setPermissionConfirmed(false);
    setLinkResult(null);
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const v2Settings = useCallback((): V2Settings => {
    return {
      desired_clip_count: null,
      content_category: contentCategory,
      editing_intensity: editingIntensity,
      music_enabled: musicEnabled,
      sfx_enabled: sfxEnabled,
      captions_enabled: captionsEnabled,
    };
  }, [
    captionsEnabled,
    contentCategory,
    editingIntensity,
    musicEnabled,
    sfxEnabled,
  ]);

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
            ...v2Settings(),
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
    [createProject, notify, router, v2Settings],
  );

  const beginLinkDownload = useCallback(async () => {
    const url = videoUrl.trim();
    if (!url) {
      setError("Paste a video link first.");
      setStatus("error");
      return;
    }
    if (!isSupportedLink(url)) {
      setError("Paste a valid public YouTube video or Shorts link.");
      setStatus("error");
      return;
    }
    if (!permissionConfirmed) {
      setError("Confirm that you own this video, have permission, or are allowed to process it.");
      setStatus("error");
      return;
    }
    setError(null);
    setLinkResult(null);
    setStatus("linking");
    try {
      let result = await createProjectFromLink.mutateAsync({
        url,
        permission_confirmed: permissionConfirmed,
        start_processing: true,
        quality: "best",
        mode: "full_pipeline",
        ...v2Settings(),
      });
      setLinkResult(result);
      for (let attempt = 0; attempt < 7200 && !result.project; attempt += 1) {
        if (TERMINAL_LINK_STATUSES.has(result.download.status)) {
          const message =
            result.download.error?.user_message ??
            result.download.reason ??
            "The video link could not be downloaded.";
          throw new Error(message);
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        result = await api.getLinkIngestion(result.download.ingestion_id);
        setLinkResult(result);
      }
      if (!result.project) {
        throw new Error("Link ingestion did not finish before the local timeout.");
      }
      notify({
        tone: "success",
        title: "Link ready",
        description: result.download.filename ?? result.project.source_filename,
      });
      router.push(`/projects/${result.project.id}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Something went wrong.";
      setError(message);
      setStatus("error");
      notify({ tone: "error", title: "Link failed", description: message });
    }
  }, [createProjectFromLink, notify, permissionConfirmed, router, v2Settings, videoUrl]);

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
        {status === "linking" &&
          linkStageLabel(linkResult?.download.link_ingestion_status.current_stage)}
        {status === "finalizing" && "Upload complete. Preparing your project."}
        {status === "error" && (error ?? "Upload failed.")}
      </div>

      {status === "idle" && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 rounded-xl bg-black/20 p-1" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={intakeMode === "upload"}
              onClick={() => setIntakeMode("upload")}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
                intakeMode === "upload" ? "bg-white/10 text-white" : "text-muted hover:text-white"
              }`}
            >
              Upload Video
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={intakeMode === "link"}
              onClick={() => setIntakeMode("link")}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
                intakeMode === "link" ? "bg-white/10 text-white" : "text-muted hover:text-white"
              }`}
            >
              Paste Link
            </button>
          </div>

          {intakeMode === "upload" ? (
            <div
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
              className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
                dragging ? "border-accent bg-accent/10" : "border-white/15"
              }`}
            >
              <UploadCloudIcon
                className={`h-14 w-14 ${dragging ? "text-accent" : "text-muted"}`}
              />
              <p className="mt-5 text-lg font-medium">Drag &amp; Drop your video here</p>
              <p className="mt-1 text-sm text-muted">or</p>
              <div className="mt-4">
                <Button onClick={() => inputRef.current?.click()}>Browse files</Button>
              </div>
            </div>
          ) : (
            <div className="grid gap-3 rounded-xl border border-white/10 bg-black/10 p-4 sm:grid-cols-[1fr_auto]">
              <label className="min-w-0">
                <span className="mb-2 flex items-center gap-2 text-sm font-medium text-white">
                  <NetworkIcon className="h-4 w-4 text-accent" />
                  YouTube video link
                </span>
                <input
                  value={videoUrl}
                  onChange={(event) => setVideoUrl(event.target.value)}
                  placeholder="Paste YouTube video or Shorts link"
                  inputMode="url"
                  autoComplete="url"
                  className="w-full rounded-lg border border-white/10 bg-ink px-3 py-2 text-sm text-white outline-none transition focus:border-accent"
                />
              </label>
              <div className="flex items-end">
                <Button onClick={beginLinkDownload} loading={createProjectFromLink.isPending}>
                  Create Shorts
                </Button>
              </div>
              <label className="flex items-start gap-2 text-xs text-muted sm:col-span-2">
                <input
                  type="checkbox"
                  checked={permissionConfirmed}
                  onChange={(event) => setPermissionConfirmed(event.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  I confirm I own this video, have permission, or am allowed to process it.
                </span>
              </label>
              <p className="text-xs text-muted sm:col-span-2">
                Only paste links to videos you own, have permission to use, or are allowed to
                process.
              </p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-muted">Content</span>
              <select
                value={contentCategory}
                onChange={(event) => setContentCategory(event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-ink px-3 py-2 text-white outline-none focus:border-accent"
              >
                {CONTENT_TYPES.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-muted">Intensity</span>
              <select
                value={editingIntensity}
                onChange={(event) => setEditingIntensity(event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-ink px-3 py-2 text-white outline-none focus:border-accent"
              >
                {INTENSITIES.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid gap-2 text-sm sm:grid-cols-3">
            <label className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2">
              <input
                type="checkbox"
                checked={musicEnabled}
                onChange={(event) => setMusicEnabled(event.target.checked)}
              />
              <span>Music</span>
            </label>
            <label className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2">
              <input
                type="checkbox"
                checked={sfxEnabled}
                onChange={(event) => setSfxEnabled(event.target.checked)}
              />
              <span>SFX</span>
            </label>
            <label className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2">
              <input
                type="checkbox"
                checked={captionsEnabled}
                onChange={(event) => setCaptionsEnabled(event.target.checked)}
              />
              <span>Captions</span>
            </label>
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
                  ? "Preparing your project..."
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

      {status === "linking" && (
        <div>
          <div className="flex items-start gap-3">
            <NetworkIcon className="mt-0.5 h-6 w-6 shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium" title={linkResult?.download.video_metadata.title ?? videoUrl}>
                {linkResult?.download.video_metadata.title ?? "Reading video metadata"}
              </p>
              <p className="text-sm text-muted">
                {linkStageLabel(linkResult?.download.link_ingestion_status.current_stage)}
              </p>
            </div>
          </div>

          {linkResult?.download.video_metadata.title && (
            <div className="mt-4 grid gap-2 rounded-lg bg-white/5 p-3 text-sm sm:grid-cols-3">
              <span className="truncate text-muted">
                {linkResult.download.video_metadata.channel ??
                  linkResult.download.video_metadata.uploader ??
                  "YouTube"}
              </span>
              <span className="text-muted">
                {formatDuration(linkResult.download.video_metadata.duration)}
              </span>
              <span className="text-muted">
                {linkResult.download.download_selection.selected_resolution ?? "Best safe quality"}
              </span>
            </div>
          )}

          <div
            className="mt-5 h-2 w-full overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            aria-valuenow={
              linkResult?.download.link_ingestion_status.progress_percent ?? undefined
            }
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Link download progress"
          >
            <div
              className={`h-full rounded-full bg-accent transition-[width] duration-300 ${
                linkResult?.download.link_ingestion_status.progress_percent == null
                  ? "w-1/3 animate-pulse-soft"
                  : ""
              }`}
              style={
                linkResult?.download.link_ingestion_status.progress_percent == null
                  ? undefined
                  : {
                      width: `${linkResult.download.link_ingestion_status.progress_percent}%`,
                    }
              }
            />
          </div>

          {linkResult?.download.link_ingestion_status.downloaded_bytes ? (
            <div className="mt-3 flex items-center justify-between text-sm text-muted">
              <span>
                {formatBytes(linkResult.download.link_ingestion_status.downloaded_bytes)}
                {linkResult.download.link_ingestion_status.total_bytes
                  ? ` of ${formatBytes(linkResult.download.link_ingestion_status.total_bytes)}`
                  : ""}
              </span>
              <span className="flex gap-4">
                <span>{formatSpeed(linkResult.download.link_ingestion_status.speed ?? 0)}</span>
                <span>{formatEta(linkResult.download.link_ingestion_status.eta_seconds)}</span>
              </span>
            </div>
          ) : null}
        </div>
      )}

      {status === "error" && (
        <div className="text-center">
          <AlertIcon className="mx-auto h-10 w-10 text-red-400" />
          <h2 className="mt-4 text-lg font-semibold">Input failed</h2>
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
