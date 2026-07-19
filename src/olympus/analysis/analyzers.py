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
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from olympus.analysis.audio_signals import analyze_wav_file
from olympus.analysis.availability import analysis_capabilities
from olympus.analysis.emotion_signals import build_emotion_timeline
from olympus.analysis.signals import build_analysis_signals_v2, unavailable_signal_entry
from olympus.analysis.speaker_signals import build_speaker_segmentation
from olympus.analysis.visual_signals import (
    build_scene_signal,
    build_shot_signal,
    parse_brightness_metadata,
    parse_scene_metadata,
)
from olympus.domain.contracts.analysis import (
    Analyzer,
    ProgressReporter,
    StageContext,
    StageOutcome,
)
from olympus.domain.entities.analysis import StageStatus
from olympus.platform.errors import ExternalServiceError
from olympus.platform.logging import get_logger

log = get_logger(__name__)

# A generous ceiling for audio extraction. FFmpeg audio extraction runs much
# faster than real time, so this covers multi-hour videos; if it is exceeded
# (e.g. a pathological or very slow source) the stage degrades honestly to
# UNAVAILABLE rather than failing the whole analysis or wasting retries.
_AUDIO_EXTRACTION_TIMEOUT_SECONDS = 900.0


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _ffmpeg_unavailable_reason() -> str | None:
    """Return an honest reason if FFmpeg is unusable, else ``None``.

    This isolates the *one* genuine FFmpeg precondition (the binary being on the
    backend process's PATH) so it is never conflated with unrelated problems such
    as the source file not being locally addressable.
    """

    if not _has("ffmpeg"):
        return (
            "Audio extraction requires the FFmpeg binary, which was not found on "
            "the backend process's PATH. Install FFmpeg (and ensure the server "
            "process inherits a PATH that includes it) to enable it."
        )
    return None


async def _materialize_source(
    ctx: StageContext, dest_dir: str
) -> tuple[str | None, str | None]:
    """Resolve a real on-disk path for the project's source video.

    The analyzer's true requirement is "a file FFmpeg can open", not specifically
    a path produced by the local-disk backend. We therefore:

    1. Prefer ``storage.local_path`` (zero-copy) when the backend can expose one.
    2. Otherwise fetch the object's real bytes through the storage port and write
       them to a temp file in ``dest_dir``. This makes audio extraction work for
       cloud backends and for any local-root/working-directory mismatch, using
       the genuine uploaded bytes - never a fabricated or hardcoded path.

    Returns ``(path, error_reason)``; exactly one is non-``None``.
    """

    key = ctx.project.storage_key
    local = ctx.storage.local_path(key)
    if local:
        return local, None

    # No local path (cloud backend, or a local root that does not contain the
    # file under the current working directory). Fall back to the bytes.
    if not await ctx.storage.exists(key):
        return None, (
            "The project's source video could not be found in storage "
            f"(key={key!r}); audio extraction cannot run."
        )
    try:
        data = await ctx.storage.get(key)
    except Exception as exc:  # storage backends raise StorageError on failure
        return None, (
            "The project's source video exists but could not be read from "
            f"storage ({type(exc).__name__}); audio extraction cannot run."
        )
    suffix = Path(ctx.project.source_filename or key).suffix or ".bin"
    src_path = str(Path(dest_dir) / f"source{suffix}")
    await asyncio.to_thread(Path(src_path).write_bytes, data)
    return src_path, None


class SubprocessUnavailableError(RuntimeError):
    """Subprocess execution is not supported in this environment.

    Kept as a defensive, catchable signal so analyzers can degrade *honestly*
    (exactly as they do when FFmpeg is absent) rather than crashing a stage with
    an opaque error, should any platform refuse to spawn a child process.
    """


async def _run(*args: str, timeout: float = 120.0) -> tuple[int, bytes, bytes]:
    """Run an external command, returning ``(returncode, stdout, stderr)``.

    Executes via a blocking :func:`subprocess.run` dispatched to a worker thread
    (:func:`asyncio.to_thread`) rather than ``asyncio.create_subprocess_exec``.
    The latter delegates child-process creation to the *running event loop*,
    which on some loops - notably a Windows ``SelectorEventLoop`` - raises a bare
    ``NotImplementedError``. That was the real cause of ``video_inspection`` and
    ``audio_extraction`` failing on Windows: ffprobe/ffmpeg could never be
    spawned. Running the command in a thread works identically on every platform
    and event-loop policy, while keeping the async event loop responsive.

    Raises :class:`TimeoutError` if the process exceeds ``timeout``. A missing
    binary surfaces as ``OSError`` (``FileNotFoundError``), exactly as before.
    """

    def _exec() -> tuple[int, bytes, bytes]:
        try:
            completed = subprocess.run(
                list(args),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"{args[0]!r} timed out after {timeout:.0f}s") from exc
        except NotImplementedError as exc:  # defensive: the threaded path should never hit this
            raise SubprocessUnavailableError(
                "Subprocess execution is not supported in this environment, so "
                "external tools (FFmpeg/ffprobe) cannot be run."
            ) from exc
        return completed.returncode or 0, completed.stdout or b"", completed.stderr or b""

    return await asyncio.to_thread(_exec)


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
            except SubprocessUnavailableError as exc:
                # The loop cannot run ffprobe; keep the client-metadata baseline
                # (this stage must always complete) and note it honestly.
                log.warning("ffprobe_subprocess_unavailable", error=str(exc))
        report(1.0)
        return StageOutcome.completed(data)


def _from_ffprobe(probe: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    video: dict[str, Any] = next((s for s in streams if s.get("codec_type") == "video"), {})
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
    version = "2"
    depends_on = ("video_inspection",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        # Diagnostic visibility (debug-level): the exact facts needed to tell
        # *which* precondition is at play, so an FFmpeg-present environment is
        # never silently misreported as "FFmpeg missing".
        local = ctx.storage.local_path(ctx.project.storage_key)
        log.debug(
            "audio_extraction_env",
            path_env=os.environ.get("PATH", ""),
            which_ffmpeg=shutil.which("ffmpeg"),
            which_ffprobe=shutil.which("ffprobe"),
            storage_key=ctx.project.storage_key,
            local_path=local,
        )

        # Precondition 1 (the only genuine FFmpeg requirement): the binary.
        ffmpeg_problem = _ffmpeg_unavailable_reason()
        if ffmpeg_problem is not None:
            return StageOutcome.unavailable(ffmpeg_problem)

        with tempfile.TemporaryDirectory() as tmp:
            # Precondition 2: a real file FFmpeg can open. Prefer the backend's
            # local path; otherwise materialize the real bytes (cloud backend or
            # working-directory/root mismatch). This is reported honestly and
            # never fabricated.
            src_path, source_error = await _materialize_source(ctx, tmp)
            if source_error is not None:
                return StageOutcome.unavailable(source_error)
            assert src_path is not None  # one of the two is always set

            out_path = str(Path(tmp) / "audio.wav")
            try:
                code, _, err = await _run(
                    "ffmpeg", "-y", "-i", src_path, "-vn", "-ac", "1", "-ar", "16000", out_path,
                    timeout=_AUDIO_EXTRACTION_TIMEOUT_SECONDS,
                )
            except SubprocessUnavailableError as exc:
                # FFmpeg is present, but this event loop cannot spawn it. Report
                # the truth (UNAVAILABLE), never a fabricated success or an opaque
                # NotImplementedError crash.
                return StageOutcome.unavailable(
                    f"{exc} Audio extraction needs to run FFmpeg as a subprocess; "
                    "run the backend on an event loop that supports subprocesses "
                    "to enable it."
                )
            except TimeoutError:
                # A legitimately too-long/slow source: degrade honestly instead of
                # failing the whole analysis or retrying the same slow work.
                log.warning(
                    "audio_extraction_timeout",
                    source=src_path,
                    timeout_seconds=_AUDIO_EXTRACTION_TIMEOUT_SECONDS,
                )
                return StageOutcome.unavailable(
                    "FFmpeg did not finish extracting audio within the time limit "
                    f"({_AUDIO_EXTRACTION_TIMEOUT_SECONDS:.0f}s), so audio is unavailable "
                    "for this video. The analysis still completes; audio-dependent "
                    "stages are reported unavailable rather than failing the pipeline."
                )
            if code != 0:
                stderr_text = (err or b"").decode(errors="ignore").strip()
                # Capture the complete FFmpeg stderr for diagnosis (full, in the
                # logs). A decode failure here is specific to THIS input file
                # (corrupt/unsupported/zero-audio source), not an internal error,
                # so we report it honestly as UNAVAILABLE rather than FAILED. That
                # keeps a single bad input from poisoning the whole analysis and
                # blocking every downstream engine, and avoids pointless retries.
                log.warning(
                    "audio_extraction_ffmpeg_failed",
                    return_code=code,
                    source=src_path,
                    stderr=stderr_text,
                )
                detail = stderr_text[-400:] if stderr_text else f"exit code {code}"
                return StageOutcome.unavailable(
                    "FFmpeg could not extract audio from this source file, so audio "
                    "is unavailable for this video. The analysis still completes; "
                    "audio-dependent stages are reported unavailable rather than "
                    f"failing the whole pipeline. FFmpeg: {detail}"
                )
            try:
                local_signals = await asyncio.to_thread(analyze_wav_file, out_path)
            except (OSError, EOFError, ValueError, wave.Error) as exc:
                log.warning("audio_signal_analysis_unavailable", error=str(exc))
                local_signals = {
                    name: unavailable_signal_entry(
                        name,
                        provider="local_pcm_rms",
                        reason="insufficient_input",
                        detail=f"Decoded audio could not be analyzed: {type(exc).__name__}.",
                    )
                    for name in ("audio_energy", "silence")
                }
            audio_bytes = await asyncio.to_thread(Path(out_path).read_bytes)
        audio_key = f"analysis/{ctx.project.id}/audio.wav"
        await ctx.storage.put(audio_key, audio_bytes, content_type="audio/wav")
        report(1.0)
        return StageOutcome.completed(
            {
                "audio_key": audio_key,
                "format": "wav",
                "sample_rate": 16000,
                "channels": 1,
                **local_signals,
            }
        )


# --------------------------------------------------------------------------- #
# 3. Speech Transcription - uses the configured provider; honest if none.
# --------------------------------------------------------------------------- #
class SpeechTranscriptionAnalyzer(Analyzer):
    name = "speech_transcription"
    version = "1"
    depends_on = ("audio_extraction",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        log.info("speech_transcription_analyzer_entered", project_id=ctx.project.id)
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
        log.info(
            "calling_transcription_provider",
            project_id=ctx.project.id,
            audio_key=audio["audio_key"],
            provider=getattr(provider, "name", None),
        )
        try:
            result = await provider.transcribe(audio["audio_key"])
        except ExternalServiceError as exc:
            log.warning(
                "transcription_provider_failed",
                project_id=ctx.project.id,
                audio_key=audio["audio_key"],
                provider=getattr(provider, "name", None),
                error=exc.message,
                details=exc.details,
            )
            return StageOutcome.failed(exc.message, retryable=False)

        log.info(
            "transcription_provider_returned",
            project_id=ctx.project.id,
            segments=len(result.segments),
            language=result.language,
        )
        if not result.segments or not result.text.strip():
            return StageOutcome.failed(
                "Speech transcription completed but returned no speech segments.",
                retryable=False,
            )
        report(1.0)
        return StageOutcome.completed(
            {
                "language": result.language,
                "confidence": result.confidence,
                "provider": getattr(provider, "name", "configured_transcription_provider"),
                "word_count": len(result.text.split()),
                "has_word_timestamps": any(s.words for s in result.segments),
                "segments": [
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                        "confidence": s.confidence,
                        "speaker": s.speaker,
                        "words": s.words,
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
    version = "2"
    depends_on = ("audio_extraction",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        transcript = ctx.data_of("speech_transcription")
        audio = ctx.data_of("audio_extraction") or {}
        silence = audio.get("silence")
        silence_timeline = silence.get("timeline") if isinstance(silence, dict) else None
        silence_events = (
            silence_timeline.get("events") if isinstance(silence_timeline, dict) else None
        )
        result = build_speaker_segmentation(
            transcript.get("segments", []) if transcript else None,
            silence_events=silence_events if isinstance(silence_events, list) else None,
            duration_seconds=float(ctx.project.duration_seconds or 0.0),
        )
        if result is None:
            return StageOutcome.unavailable(
                "No diarization provider, transcript turn boundaries, or usable silence gaps "
                "are available. Speaker segmentation cannot be inferred honestly."
            )
        report(1.0)
        return StageOutcome.completed(result)


# --------------------------------------------------------------------------- #
# 5-6. Deterministic local scene and shot analysis.
# --------------------------------------------------------------------------- #
class _UnavailableModelStage(Analyzer):
    """Base for stages whose model/tooling is not configured in this environment."""

    _reason = "This analyzer is not configured in this environment."

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        return StageOutcome.unavailable(self._reason)


class SceneDetectionAnalyzer(Analyzer):
    name = "scene_detection"
    version = "2"
    depends_on = ("video_inspection",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        ffmpeg_problem = _ffmpeg_unavailable_reason()
        if ffmpeg_problem is not None:
            return StageOutcome.unavailable(ffmpeg_problem)
        inspection = ctx.data_of("video_inspection") or {}
        duration = float(inspection.get("duration_seconds") or ctx.project.duration_seconds or 0.0)
        if duration <= 0:
            return StageOutcome.unavailable(
                "Scene detection requires a positive source duration, which is unavailable."
            )
        with tempfile.TemporaryDirectory(prefix="olympus-scenes-") as tmp:
            source_path, source_error = await _materialize_source(ctx, tmp)
            if source_error is not None:
                return StageOutcome.unavailable(source_error)
            assert source_path is not None
            scene_sink = str(Path(tmp) / "scene.null")
            try:
                code, out, err = await _run(
                    "ffmpeg",
                    "-hide_banner",
                    "-nostats",
                    "-threads",
                    "1",
                    "-i",
                    source_path,
                    "-an",
                    "-vf",
                    (
                        "scale=320:-2:flags=fast_bilinear,"
                        "select=gt(scene\\,0.32),"
                        "metadata=mode=print:key=lavfi.scene_score"
                    ),
                    "-filter_threads",
                    "1",
                    "-f",
                    "null",
                    scene_sink,
                    timeout=_AUDIO_EXTRACTION_TIMEOUT_SECONDS,
                )
            except (OSError, TimeoutError, SubprocessUnavailableError) as exc:
                return StageOutcome.unavailable(
                    f"Local FFmpeg scene detection could not run: {type(exc).__name__}: {exc}"
                )
            if code != 0:
                detail = (err or b"").decode(errors="ignore")[-500:].strip()
                return StageOutcome.unavailable(
                    "FFmpeg could not decode this source for scene detection. "
                    f"{detail or f'exit code {code}'}"
                )
            boundaries = parse_scene_metadata(
                (out or b"").decode(errors="ignore")
                + "\n"
                + (err or b"").decode(errors="ignore")
            )
            report(0.75)
            brightness_sink = str(Path(tmp) / "brightness.null")
            brightness_samples: list[dict[str, float]] = []
            try:
                brightness_code, brightness_out, brightness_err = await _run(
                    "ffmpeg",
                    "-hide_banner",
                    "-nostats",
                    "-threads",
                    "1",
                    "-i",
                    source_path,
                    "-an",
                    "-vf",
                    (
                        "fps=1/2,scale=160:-2:flags=fast_bilinear,signalstats,"
                        "metadata=mode=print:key=lavfi.signalstats.YAVG"
                    ),
                    "-filter_threads",
                    "1",
                    "-f",
                    "null",
                    brightness_sink,
                    timeout=_AUDIO_EXTRACTION_TIMEOUT_SECONDS,
                )
                if brightness_code == 0:
                    brightness_samples = parse_brightness_metadata(
                        (brightness_out or b"").decode(errors="ignore")
                        + "\n"
                        + (brightness_err or b"").decode(errors="ignore")
                    )
            except (OSError, TimeoutError, SubprocessUnavailableError) as exc:
                log.warning("visual_brightness_sampling_unavailable", error=str(exc))
        report(1.0)
        return StageOutcome.completed(
            {
                **build_scene_signal(
                    boundaries,
                    duration_seconds=duration,
                    brightness_samples=brightness_samples,
                ),
                "provider": "ffmpeg_scene_filter",
                "threshold": 0.32,
                "raw_frames_stored": False,
            }
        )


class ShotDetectionAnalyzer(Analyzer):
    name = "shot_detection"
    version = "2"
    depends_on = ("scene_detection",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        scenes = ctx.data_of("scene_detection")
        inspection = ctx.data_of("video_inspection") or {}
        duration = float(inspection.get("duration_seconds") or ctx.project.duration_seconds or 0.0)
        if not scenes or duration <= 0:
            return StageOutcome.unavailable(
                "Shot detection requires completed FFmpeg scene boundaries and source duration."
            )
        report(1.0)
        return StageOutcome.completed(build_shot_signal(scenes, duration_seconds=duration))


# --------------------------------------------------------------------------- #
# 7-9. Optional model-backed signals. Honest unavailable until configured.
# --------------------------------------------------------------------------- #
class OcrAnalyzer(_UnavailableModelStage):
    name = "ocr"
    version = "2"
    depends_on = ("video_inspection",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        capability = analysis_capabilities()["ocr"]
        return StageOutcome.unavailable(
            "OCR is unavailable: "
            f"{capability['reason']}. No configured local OCR provider produced text."
        )


class FaceDetectionAnalyzer(_UnavailableModelStage):
    name = "face_detection"
    version = "2"
    depends_on = ("video_inspection",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        capability = analysis_capabilities()["face_detection"]
        return StageOutcome.unavailable(
            "Face detection is unavailable: "
            f"{capability['reason']}. No configured provider produced anonymous detections; "
            "people are never identified."
        )


class ObjectDetectionAnalyzer(_UnavailableModelStage):
    name = "object_detection"
    version = "2"
    depends_on = ("video_inspection",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        capability = analysis_capabilities()["object_detection"]
        return StageOutcome.unavailable(
            "Semantic object detection is unavailable: "
            f"{capability['reason']}. Basic full-frame visual activity remains separate and "
            "no object classes are invented."
        )


# --------------------------------------------------------------------------- #
# 10. Emotion Timeline - transparent local heuristic fallback.
# --------------------------------------------------------------------------- #
class EmotionTimelineAnalyzer(Analyzer):
    name = "emotion_timeline"
    version = "2"
    depends_on = ("speech_transcription",)

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        transcript = ctx.data_of("speech_transcription")
        if not transcript or not isinstance(transcript.get("segments"), list):
            return StageOutcome.unavailable(
                "The local emotion heuristic requires transcript segments; none are available."
            )
        audio = ctx.data_of("audio_extraction") or {}
        energy = audio.get("audio_energy")
        timeline = energy.get("timeline") if isinstance(energy, dict) else None
        energy_events = timeline.get("events") if isinstance(timeline, dict) else None
        result = build_emotion_timeline(
            transcript["segments"],
            audio_energy_events=energy_events if isinstance(energy_events, list) else None,
        )
        if result is None:
            return StageOutcome.unavailable(
                "Transcript segments were empty, so no heuristic emotion timeline was produced."
            )
        report(1.0)
        return StageOutcome.completed(result)


class SignalHealthAnalyzer(Analyzer):
    """Persist the compact, normalized cross-stage signal contract."""

    name = "signal_health"
    version = "1"
    depends_on = (
        "speech_transcription",
        "audio_extraction",
        "speaker_segmentation",
        "scene_detection",
        "shot_detection",
        "ocr",
        "face_detection",
        "object_detection",
        "emotion_timeline",
    )

    async def analyze(self, ctx: StageContext, report: ProgressReporter) -> StageOutcome:
        artifact = build_analysis_signals_v2(
            project_id=ctx.project.id,
            source_id=ctx.project.storage_key,
            stages=ctx.results,
        )
        report(1.0)
        return StageOutcome.completed(
            {
                "analysis_signals_v2": artifact,
                "signal_health": artifact["signal_health"],
            }
        )


# --------------------------------------------------------------------------- #
# 12. Knowledge Graph - real aggregation of whatever is genuinely known.
# --------------------------------------------------------------------------- #
class KnowledgeGraphAnalyzer(Analyzer):
    name = "knowledge_graph"
    version = "2"
    depends_on = (
        "video_inspection",
        "speech_transcription",
        "scene_detection",
        "speaker_segmentation",
        "emotion_timeline",
        "object_detection",
        "ocr",
        "signal_health",
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
        signal_health = ctx.data_of("signal_health") or {}
        graph: dict[str, Any] = {
            "metadata": metadata,
            "available_signals": completed,
            "pending_signals": pending,
            "transcript_available": transcript is not None,
            "transcript_word_count": (transcript or {}).get("word_count"),
            "scenes": (ctx.data_of("scene_detection") or {}).get("scenes", []),
            "speakers": (ctx.data_of("speaker_segmentation") or {}).get("speakers", []),
            "emotion": (ctx.data_of("emotion_timeline") or {}).get("timeline", []),
            "signal_health": signal_health.get("signal_health"),
            "analysis_signals_v2_ref": "analysis/stages/signal_health.json",
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
