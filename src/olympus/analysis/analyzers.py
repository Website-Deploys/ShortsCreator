"""The eleven analysis stages.

Each analyzer is an isolated, replaceable module behind the :class:`Analyzer`
contract. Where the required tool (FFmpeg) or model (speech-to-text, CV) is
available and configured, the analyzer produces real output. Where it is not,
the analyzer returns ``UNAVAILABLE`` with a clear reason - it never invents
results. This is the project's "models are commodities; interfaces are the
asset" principle applied to understanding.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from olympus.domain.contracts.analysis import (
    Analyzer,
    ProgressReporter,
    StageContext,
    StageOutcome,
)
from olympus.domain.entities.analysis import StageStatus
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


async def _run(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
    """Run a subprocess, returning (returncode, stdout, stderr)."""

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, stdout, stderr


def _parse_fps(rate: str | None) -> float | None:
    if not rate or "/" not in rate:
        return None
    num, _, den = rate.partition("/")
    try:
        n, d = float(num), float(den)
        return round(n / d, 3) if d else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 1. Video Inspection - always completes (real, never fabricated).
# --------------------------------------------------------------------------- #
class VideoInspectionAnalyzer(Analyzer):
    name = "video_inspection"
    version = "1"

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        project = ctx.project
        # Baseline from genuinely-known values (client-probed + stored).
        aspect = None
        if project.width and project.height:
            aspect = round(project.width / project.height, 4)
        data: dict[str, Any] = {
            "source": "client_metadata",
            "container": project.video_format,
            "content_type": project.content_type,
            "duration_seconds": project.duration_seconds,
            "width": project.width,
            "height": project.height,
            "aspect_ratio": aspect,
            "file_size_bytes": project.size_bytes,
            "fps": None,
            "video_codec": None,
            "video_bitrate": None,
            "audio_tracks": None,
            "frame_count": None,
            "notes": (
                "Deep media probe (ffprobe) is not available in this environment; "
                "fields requiring it are null rather than estimated."
            ),
        }

        path = ctx.storage.local_path(project.storage_key)
        if _has("ffprobe") and path:
            try:
                code, out, _ = await _run(
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams", path,
                )
                if code == 0:
                    probe = json.loads(out or b"{}")
                    data = _from_ffprobe(probe, data)
            except (OSError, json.JSONDecodeError, TimeoutError) as exc:
                log.warning("ffprobe_failed", error=str(exc))
        report(1.0)
        return StageOutcome.completed(data)


def _from_ffprobe(probe: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    return {
        **base,
        "source": "ffprobe",
        "notes": None,
        "container": fmt.get("format_name") or base["container"],
        "duration_seconds": (
            float(fmt["duration"]) if fmt.get("duration") else base["duration_seconds"]
        ),
        "width": video.get("width") or base["width"],
        "height": video.get("height") or base["height"],
        "fps": _parse_fps(video.get("avg_frame_rate")),
        "video_codec": video.get("codec_name"),
        "video_bitrate": int(video["bit_rate"]) if video.get("bit_rate") else None,
        "frame_count": int(video["nb_frames"]) if video.get("nb_frames") else None,
        "audio_tracks": [
            {
                "codec": a.get("codec_name"),
                "channels": a.get("channels"),
                "sample_rate": int(a["sample_rate"]) if a.get("sample_rate") else None,
                "bitrate": int(a["bit_rate"]) if a.get("bit_rate") else None,
            }
            for a in audios
        ],
    }


# --------------------------------------------------------------------------- #
# 2. Audio Extraction - real with FFmpeg, else honest unavailable.
# --------------------------------------------------------------------------- #
class AudioExtractionAnalyzer(Analyzer):
    name = "audio_extraction"
    version = "1"
    depends_on = ("video_inspection",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        path = ctx.storage.local_path(ctx.project.storage_key)
        if not _has("ffmpeg") or not path:
            return StageOutcome.unavailable(
                "Audio extraction requires FFmpeg, which is not available in this "
                "environment. Install FFmpeg to enable it."
            )
        with tempfile.TemporaryDirectory() as tmp:
            out_path = str(Path(tmp) / "audio.wav")
            code, _, err = await _run(
                "ffmpeg", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", out_path
            )
            if code != 0:
                return StageOutcome(
                    status=StageStatus.FAILED,
                    reason=(err or b"").decode(errors="ignore")[-500:],
                )
            audio_bytes = await asyncio.to_thread(Path(out_path).read_bytes)
        audio_key = f"analysis/{ctx.project.id}/audio.wav"
        await ctx.storage.put(audio_key, audio_bytes, content_type="audio/wav")
        report(1.0)
        return StageOutcome.completed(
            {"audio_key": audio_key, "format": "wav", "sample_rate": 16000, "channels": 1}
        )


# --------------------------------------------------------------------------- #
# 3. Speech Transcription - uses the configured provider; honest if none.
# --------------------------------------------------------------------------- #
class SpeechTranscriptionAnalyzer(Analyzer):
    name = "speech_transcription"
    version = "1"
    depends_on = ("audio_extraction",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        audio = ctx.data_of("audio_extraction")
        if not audio:
            return StageOutcome.unavailable(
                "No extracted audio is available (audio extraction did not run)."
            )
        provider = ctx.transcription_provider
        if provider is None or getattr(provider, "name", "noop") == "noop":
            return StageOutcome.unavailable(
                "No speech-to-text provider is configured. Set "
                "OLYMPUS_AI__TRANSCRIPTION_PROVIDER to a real provider to enable it."
            )
        result = await provider.transcribe(audio["audio_key"])
        report(1.0)
        return StageOutcome.completed(
            {
                "language": result.language,
                "confidence": result.confidence,
                "word_count": len(result.text.split()),
                "has_word_timestamps": any(
                    s.start is not None for s in result.segments
                ),
                "segments": [
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                        "confidence": s.confidence,
                        "speaker": s.speaker,
                    }
                    for s in result.segments
                ],
            }
        )


# --------------------------------------------------------------------------- #
# 4. Speaker Segmentation - derived from the transcript's speaker labels.
# --------------------------------------------------------------------------- #
class SpeakerSegmentationAnalyzer(Analyzer):
    name = "speaker_segmentation"
    version = "1"
    depends_on = ("speech_transcription",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        transcript = ctx.data_of("speech_transcription")
        if not transcript:
            return StageOutcome.unavailable("Requires a transcript to identify speakers.")
        segments = transcript.get("segments", [])
        if not any(s.get("speaker") for s in segments):
            return StageOutcome.unavailable(
                "The transcript contains no speaker information (diarization not "
                "provided by the speech-to-text provider)."
            )
        timeline: list[dict[str, Any]] = []
        for seg in segments:
            speaker = seg.get("speaker") or "unknown"
            if timeline and timeline[-1]["speaker"] == speaker:
                timeline[-1]["end"] = seg.get("end")
            else:
                timeline.append(
                    {"speaker": speaker, "start": seg.get("start"), "end": seg.get("end")}
                )
        report(1.0)
        speakers = sorted({t["speaker"] for t in timeline})
        return StageOutcome.completed({"speakers": speakers, "timeline": timeline})


# --------------------------------------------------------------------------- #
# 5-9. Vision/audio stages requiring FFmpeg + CV/ML models. Honest unavailable.
# --------------------------------------------------------------------------- #
class _UnavailableModelStage(Analyzer):
    """Base for stages whose model/tooling is not configured in this environment."""

    _reason = "This analyzer is not configured in this environment."

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        return StageOutcome.unavailable(self._reason)


class SceneDetectionAnalyzer(_UnavailableModelStage):
    name = "scene_detection"
    version = "1"
    depends_on = ("video_inspection",)
    _reason = (
        "Scene detection requires frame decoding (FFmpeg) and a scene-detection "
        "step, which are not available in this environment."
    )


class ShotDetectionAnalyzer(_UnavailableModelStage):
    name = "shot_detection"
    version = "1"
    depends_on = ("video_inspection",)
    _reason = (
        "Shot/cut detection requires frame decoding (FFmpeg), which is not "
        "available in this environment."
    )


class OcrAnalyzer(_UnavailableModelStage):
    name = "ocr"
    version = "1"
    depends_on = ("video_inspection",)
    _reason = (
        "On-screen text extraction requires frame sampling (FFmpeg) and an OCR "
        "engine, which are not available in this environment."
    )


class FaceDetectionAnalyzer(_UnavailableModelStage):
    name = "face_detection"
    version = "1"
    depends_on = ("video_inspection",)
    _reason = (
        "Face detection requires frame sampling (FFmpeg) and a face-detection "
        "model, which are not available in this environment. Faces are tracked by "
        "consistent IDs only - people are never identified."
    )


class ObjectDetectionAnalyzer(_UnavailableModelStage):
    name = "object_detection"
    version = "1"
    depends_on = ("video_inspection",)
    _reason = (
        "Object detection requires frame sampling (FFmpeg) and an object-detection "
        "model, which are not available in this environment."
    )


# --------------------------------------------------------------------------- #
# 10. Emotion Timeline - requires transcript + an emotion model. Honest.
# --------------------------------------------------------------------------- #
class EmotionTimelineAnalyzer(Analyzer):
    name = "emotion_timeline"
    version = "1"
    depends_on = ("speech_transcription",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        transcript = ctx.data_of("speech_transcription")
        if not transcript:
            return StageOutcome.unavailable(
                "Emotion estimation requires a transcript and an emotion model. "
                "It is an estimation and is never reported with false certainty."
            )
        # A real emotion model is not configured; we do not guess.
        return StageOutcome.unavailable(
            "A transcript is available, but no emotion-estimation model is "
            "configured. Emotion is an estimation and is never fabricated."
        )


# --------------------------------------------------------------------------- #
# 11. Knowledge Graph - real aggregation of whatever is genuinely known.
# --------------------------------------------------------------------------- #
class KnowledgeGraphAnalyzer(Analyzer):
    name = "knowledge_graph"
    version = "1"
    depends_on = (
        "video_inspection",
        "speech_transcription",
        "scene_detection",
        "speaker_segmentation",
        "emotion_timeline",
        "object_detection",
        "ocr",
    )

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        completed: list[str] = []
        pending: list[dict[str, str]] = []
        for name, result in ctx.results.items():
            if name == self.name:
                continue
            if result.status is StageStatus.COMPLETED:
                completed.append(name)
            elif result.status in (StageStatus.UNAVAILABLE, StageStatus.FAILED):
                pending.append({"stage": name, "reason": result.reason or result.error or ""})

        metadata = ctx.data_of("video_inspection") or {}
        transcript = ctx.data_of("speech_transcription")
        graph: dict[str, Any] = {
            "metadata": metadata,
            "available_signals": completed,
            "pending_signals": pending,
            "transcript_available": transcript is not None,
            "transcript_word_count": (transcript or {}).get("word_count"),
            "scenes": (ctx.data_of("scene_detection") or {}).get("scenes", []),
            "speakers": (ctx.data_of("speaker_segmentation") or {}).get("speakers", []),
            "emotion": (ctx.data_of("emotion_timeline") or {}).get("timeline", []),
            "summary": _understanding_summary(metadata, completed, pending),
        }
        report(1.0)
        return StageOutcome.completed(graph)


def _understanding_summary(
    metadata: dict[str, Any], completed: list[str], pending: list[dict[str, str]]
) -> str:
    known = []
    if metadata.get("duration_seconds"):
        known.append("duration")
    if metadata.get("width") and metadata.get("height"):
        known.append("resolution")
    base = (
        f"Olympus has established the technical profile of this video "
        f"({', '.join(known) or 'basic metadata'})."
    )
    if pending:
        base += (
            f" Deeper semantic understanding ({len(pending)} signal(s) such as "
            "speech, scenes, and emotion) is pending the relevant analyzers, which "
            "are not configured in this environment. Nothing has been fabricated."
        )
    return base
