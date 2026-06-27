"use client";

/**
 * A professional, self-contained video player.
 *
 * Custom controls (play/pause, seek, volume, mute, fullscreen, current/total
 * time) over a native <video> element streamed from the backend (no external
 * services). Supports keyboard, shows a loading state, and an honest error
 * state for formats the browser cannot decode (with a download fallback).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  AlertIcon,
  DownloadIcon,
  FullscreenIcon,
  PauseIcon,
  PlayIcon,
  VolumeIcon,
  VolumeMuteIcon,
} from "@/components/icons";
import { mediaUrls } from "@/lib/apiClient";
import { formatDuration } from "@/lib/format";

interface VideoPlayerProps {
  projectId: string;
  hasThumbnail: boolean;
}

export function VideoPlayer({ projectId, hasThumbnail }: VideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }, []);

  const onSeek = (value: number) => {
    const video = videoRef.current;
    if (video) video.currentTime = value;
    setCurrent(value);
  };

  const onVolume = (value: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.volume = value;
    video.muted = value === 0;
    setVolume(value);
    setMuted(value === 0);
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setMuted(video.muted);
  };

  const toggleFullscreen = () => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  // Keyboard: space / k toggles play when the player has focus.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === " " || e.key === "k") {
        e.preventDefault();
        togglePlay();
      }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [togglePlay]);

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      className="group relative aspect-video w-full overflow-hidden rounded-xl border border-white/10 bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {errored ? (
        <div className="flex h-full flex-col items-center justify-center px-6 text-center">
          <AlertIcon className="h-8 w-8 text-muted" />
          <p className="mt-3 text-sm font-medium">Preview unavailable</p>
          <p className="mt-1 max-w-xs text-xs text-muted">
            Your browser can&apos;t play this format directly. You can still download the original.
          </p>
          <a
            href={mediaUrls.download(projectId)}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-elevated px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/10"
          >
            <DownloadIcon className="h-4 w-4" />
            Download original
          </a>
        </div>
      ) : (
        <>
          <video
            ref={videoRef}
            src={mediaUrls.source(projectId)}
            poster={hasThumbnail ? mediaUrls.thumbnail(projectId) : undefined}
            preload="metadata"
            playsInline
            onClick={togglePlay}
            onLoadedMetadata={(e) => {
              setDuration(e.currentTarget.duration || 0);
              setLoading(false);
            }}
            onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onWaiting={() => setLoading(true)}
            onPlaying={() => setLoading(false)}
            onError={() => {
              setErrored(true);
              setLoading(false);
            }}
            className="h-full w-full bg-black"
          />

          {loading && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white/80" />
            </div>
          )}

          {/* Controls */}
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-3 opacity-100 transition-opacity">
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.1}
              value={current}
              onChange={(e) => onSeek(Number(e.target.value))}
              aria-label="Seek"
              className="h-1 w-full cursor-pointer appearance-none rounded-full bg-white/25 accent-accent"
            />
            <div className="mt-2 flex items-center gap-3 text-white">
              <button
                type="button"
                onClick={togglePlay}
                aria-label={playing ? "Pause" : "Play"}
                className="rounded-md p-1 transition-colors hover:bg-white/15"
              >
                {playing ? <PauseIcon className="h-5 w-5" /> : <PlayIcon className="h-5 w-5" />}
              </button>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={toggleMute}
                  aria-label={muted ? "Unmute" : "Mute"}
                  className="rounded-md p-1 transition-colors hover:bg-white/15"
                >
                  {muted || volume === 0 ? (
                    <VolumeMuteIcon className="h-5 w-5" />
                  ) : (
                    <VolumeIcon className="h-5 w-5" />
                  )}
                </button>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={muted ? 0 : volume}
                  onChange={(e) => onVolume(Number(e.target.value))}
                  aria-label="Volume"
                  className="hidden h-1 w-20 cursor-pointer appearance-none rounded-full bg-white/25 accent-accent sm:block"
                />
              </div>

              <span className="ml-1 text-xs tabular-nums text-white/90">
                {formatDuration(current)} / {formatDuration(duration)}
              </span>

              <button
                type="button"
                onClick={toggleFullscreen}
                aria-label="Fullscreen"
                className="ml-auto rounded-md p-1 transition-colors hover:bg-white/15"
              >
                <FullscreenIcon className="h-5 w-5" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
