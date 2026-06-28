"""The FFmpeg clip renderer - real execution, honest availability.

Implements the :class:`ClipRenderer` port using FFmpeg. It probes for the FFmpeg
(and ffprobe) binaries and reports availability honestly; when they are absent it
raises :class:`RendererUnavailableError` with the exact reason rather than
fabricating output. When present, it executes the deterministic FFmpeg command
built from the timeline (trim, reframe, caption burn, encode), measures the real
output with ffprobe, and writes the encoded bytes to storage.

FFmpeg is never hardcoded into business logic: the pipeline depends only on the
``ClipRenderer`` abstraction, so GPU, cloud, or distributed renderers can replace
this without touching any stage.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from olympus.domain.contracts.rendering import (
    ClipRenderer,
    ClipRenderOutput,
    ClipRenderSpec,
    RendererAvailability,
    RendererUnavailableError,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.platform.errors import ExternalServiceError
from olympus.platform.logging import get_logger
from olympus.rendering import command as C  # noqa: N812 (module alias is intentional)

log = get_logger(__name__)

_MAX_LOG_LINES = 40


class FfmpegClipRenderer(ClipRenderer):
    """Render a clip's timeline to a real MP4 via FFmpeg."""

    name = "ffmpeg"

    def __init__(self, ffmpeg_binary: str = "ffmpeg", ffprobe_binary: str = "ffprobe") -> None:
        self._ffmpeg = ffmpeg_binary
        self._ffprobe = ffprobe_binary

    def availability(self) -> RendererAvailability:
        ffmpeg_path = shutil.which(self._ffmpeg)
        if ffmpeg_path is None:
            return RendererAvailability(
                available=False,
                renderer=self.name,
                reason=(
                    f"FFmpeg binary {self._ffmpeg!r} was not found on PATH. Install FFmpeg to "
                    "enable rendering; no MP4 can be produced without it."
                ),
            )
        return RendererAvailability(available=True, renderer=self.name, version=ffmpeg_path)

    async def render_clip(self, spec: ClipRenderSpec, storage: StoragePort) -> ClipRenderOutput:
        availability = self.availability()
        if not availability.available:
            raise RendererUnavailableError(availability.reason or "FFmpeg is unavailable.")

        with tempfile.TemporaryDirectory(prefix="olympus-render-") as tmp:
            tmp_dir = Path(tmp)
            source_path = await self._materialize_source(spec.source_key, storage, tmp_dir)
            srt_path = self._write_srt(spec.timeline, tmp_dir)
            output_path = tmp_dir / "out.mp4"

            args = C.build_ffmpeg_command(
                binary=self._ffmpeg,
                source_path=str(source_path),
                output_path=str(output_path),
                timeline=spec.timeline,
                width=spec.width,
                height=spec.height,
                fps=spec.fps,
                video_bitrate_kbps=spec.video_bitrate_kbps,
                audio_bitrate_kbps=spec.audio_bitrate_kbps,
                srt_path=str(srt_path) if srt_path else None,
            )
            logs = await self._run(args, label="ffmpeg")
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise ExternalServiceError(
                    "FFmpeg completed but produced no output file.",
                    code="render_failed",
                    details={"clip_id": spec.clip_id},
                )

            data = output_path.read_bytes()
            await storage.put(spec.output_key, data, content_type="video/mp4")
            probe = await self._probe(output_path)
            return self._build_output(spec, data, probe, logs)

    # -- internals ------------------------------------------------------------
    async def _materialize_source(
        self, source_key: str, storage: StoragePort, tmp_dir: Path
    ) -> Path:
        local = storage.local_path(source_key)
        if local is not None and Path(local).exists():
            return Path(local)
        if not await storage.exists(source_key):
            raise ExternalServiceError(
                "Source media is missing from storage; cannot render.",
                code="missing_source",
                details={"source_key": source_key},
            )
        data = await storage.get(source_key)
        dest = tmp_dir / "source"
        dest.write_bytes(data)
        return dest

    def _write_srt(self, timeline: dict, tmp_dir: Path) -> Path | None:
        cues = C.caption_cues(timeline)
        if not cues:
            return None
        srt_path = tmp_dir / "captions.srt"
        srt_path.write_text(C.build_srt(cues), encoding="utf-8")
        return srt_path

    async def _run(self, args: list[str], *, label: str) -> list[str]:
        log.info("render_exec", renderer=self.name, label=label, arg0=args[0])

        # Run via a blocking subprocess on a worker thread rather than
        # asyncio.create_subprocess_exec: the latter raises NotImplementedError on
        # event loops without subprocess support (e.g. a Windows
        # SelectorEventLoop). The threaded path works on every platform/loop.
        def _exec() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(list(args), capture_output=True, check=False)

        completed = await asyncio.to_thread(_exec)
        tail = (completed.stderr or b"").decode("utf-8", "replace").splitlines()[-_MAX_LOG_LINES:]
        if completed.returncode != 0:
            raise ExternalServiceError(
                f"{label} exited with code {completed.returncode}.",
                code="render_failed",
                details={"stderr_tail": tail[-5:]},
            )
        return [f"[{label}] {line}" for line in tail]

    async def _probe(self, path: Path) -> dict:
        if shutil.which(self._ffprobe) is None:
            return {}
        args = C.build_ffprobe_command(binary=self._ffprobe, path=str(path))

        def _exec() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(list(args), capture_output=True, check=False)

        completed = await asyncio.to_thread(_exec)
        if completed.returncode != 0:
            return {}
        try:
            return json.loads((completed.stdout or b"").decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            return {}

    @staticmethod
    def _build_output(
        spec: ClipRenderSpec, data: bytes, probe: dict, logs: list[str]
    ) -> ClipRenderOutput:
        fmt = probe.get("format", {}) if isinstance(probe, dict) else {}
        streams = probe.get("streams", []) if isinstance(probe, dict) else []
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

        def _to_float(value: object) -> float | None:
            try:
                return float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        duration = _to_float(fmt.get("duration"))
        bitrate = _to_float(fmt.get("bit_rate"))
        return ClipRenderOutput(
            clip_id=spec.clip_id,
            output_key=spec.output_key,
            width=video.get("width") or spec.width,
            height=video.get("height") or spec.height,
            duration=duration,
            fps=float(spec.fps),
            video_codec=video.get("codec_name") or "h264",
            audio_codec=(audio or {}).get("codec_name") if audio else None,
            has_audio=audio is not None,
            bitrate_kbps=int(bitrate / 1000) if bitrate else spec.video_bitrate_kbps,
            audio_sample_rate=int((audio or {}).get("sample_rate", 0)) or None if audio else None,
            size_bytes=len(data),
            logs=logs,
        )


def build_clip_renderer(ffmpeg_binary: str = "ffmpeg") -> ClipRenderer:
    """Construct the default clip renderer (FFmpeg).

    The Rendering Engine depends only on the :class:`ClipRenderer` abstraction, so
    a future deployment can swap this for a GPU/cloud/distributed renderer here
    without touching any pipeline stage.
    """

    return FfmpegClipRenderer(ffmpeg_binary=ffmpeg_binary)
