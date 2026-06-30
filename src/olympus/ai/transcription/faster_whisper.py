"""Faster-Whisper transcription provider.

The first production speech-to-text adapter. Implements the existing
:class:`olympus.domain.contracts.ai.TranscriptionProvider` contract using
`faster-whisper <https://github.com/SYSTRAN/faster-whisper>`_ (a CTranslate2
backend for OpenAI Whisper) so the rest of the pipeline (story -> virality ->
clip planner) receives a real, timestamped transcript.

Design notes (kept consistent with the rest of the codebase):

* **Never blocks the event loop.** Model loading and inference are blocking, so
  they run in a worker thread via :func:`asyncio.to_thread`; the model instance
  is loaded lazily once and reused.
* **Concurrency-safe.** A single CTranslate2 model is not safe for concurrent
  inference, so calls are serialized with an :class:`asyncio.Lock`.
* **Device auto-detect + CPU fallback.** ``device="auto"`` selects CUDA when a
  GPU is visible and otherwise CPU; if CUDA model init fails we fall back to CPU
  rather than failing the run.
* **Timeout protection + graceful cancellation.** A wall-clock deadline is
  enforced inside the worker thread between segments (Whisper yields segments
  lazily), so a runaway transcription stops at the next segment boundary.
* **Clear error reporting.** Provider failures raise
  :class:`olympus.platform.errors.ExternalServiceError` per the contract; a
  missing dependency raises :class:`ConfigurationError`.

This adapter intentionally holds no business logic - it only turns audio bytes
(resolved from the storage key) into a :class:`TranscriptResult`.
"""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from olympus.domain.contracts.ai import (
    TranscriptionProvider,
    TranscriptResult,
    TranscriptSegment,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.platform.errors import ConfigurationError, ExternalServiceError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


class _ModelFactory(Protocol):
    """Callable that builds a Whisper model (real ``WhisperModel`` or a test fake)."""

    def __call__(
        self, model: str, *, device: str, compute_type: str, download_root: str | None
    ) -> Any: ...


def _logprob_to_confidence(avg_logprob: float | None) -> float | None:
    """Map Whisper's average token log-probability to an approximate ``[0, 1]``.

    ``avg_logprob`` is a natural-log probability (<= 0); ``exp`` brings it into a
    bounded, monotonic confidence proxy. This is an estimate, surfaced as such -
    downstream gates treat low values cautiously rather than as ground truth.
    """

    if avg_logprob is None:
        return None
    return max(0.0, min(1.0, math.exp(avg_logprob)))


class FasterWhisperTranscriptionProvider(TranscriptionProvider):
    """Speech-to-text via faster-whisper / CTranslate2."""

    def __init__(
        self,
        storage: StoragePort,
        *,
        model: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
        beam_size: int = 5,
        language: str | None = None,
        download_root: str | None = None,
        timeout_seconds: float = 1800.0,
        model_factory: _ModelFactory | None = None,
    ) -> None:
        self._storage = storage
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._language = language or None
        self._download_root = download_root or None
        self._timeout = timeout_seconds
        self._model_factory = model_factory  # injectable for tests (no model download)
        self._model: Any = None
        self._resolved_device: str | None = None
        self._resolved_compute: str | None = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "faster-whisper"

    # -- device/compute resolution ----------------------------------------- #
    def _auto_device(self) -> str:
        if self._device != "auto":
            return self._device
        try:
            import ctranslate2  # type: ignore[import-untyped]

            return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            return "cpu"

    def _auto_compute(self, device: str) -> str:
        if self._compute_type != "auto":
            return self._compute_type
        return "float16" if device == "cuda" else "int8"

    def _build_model_factory(self) -> _ModelFactory:
        if self._model_factory is not None:
            return self._model_factory
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - covered via ConfigurationError
            raise ConfigurationError(
                "faster-whisper is not installed. Install it to use the "
                "'faster-whisper' transcription provider."
            ) from exc

        def _factory(
            model: str, *, device: str, compute_type: str, download_root: str | None
        ) -> Any:
            return WhisperModel(
                model, device=device, compute_type=compute_type, download_root=download_root
            )

        return _factory

    # -- model loading (blocking; runs in a worker thread) ------------------ #
    def _load_model(self) -> Any:
        factory = self._build_model_factory()
        device = self._auto_device()
        compute = self._auto_compute(device)
        try:
            model = factory(
                self._model_name,
                device=device,
                compute_type=compute,
                download_root=self._download_root,
            )
        except Exception as exc:
            if device == "cuda":
                log.warning("whisper_cuda_init_failed_cpu_fallback", error=str(exc))
                device, compute = "cpu", self._auto_compute("cpu")
                model = factory(
                    self._model_name,
                    device=device,
                    compute_type=compute,
                    download_root=self._download_root,
                )
            else:
                raise
        self._resolved_device, self._resolved_compute = device, compute
        log.info(
            "whisper_model_loaded", model=self._model_name, device=device, compute_type=compute
        )
        return model

    # -- inference (blocking; runs in a worker thread) ---------------------- #
    def _transcribe_sync(
        self, audio_path: str, language_hint: str | None, deadline: float
    ) -> TranscriptResult:
        if self._model is None:
            self._model = self._load_model()
        segments_iter, info = self._model.transcribe(
            audio_path,
            beam_size=self._beam_size,
            language=self._language or language_hint or None,
            word_timestamps=True,
        )
        segments: list[TranscriptSegment] = []
        confidences: list[float] = []
        for seg in segments_iter:  # lazy generator: the actual work happens here
            if time.monotonic() > deadline:
                raise TimeoutError(f"transcription exceeded {self._timeout:.0f}s")
            words = None
            seg_words = getattr(seg, "words", None)
            if seg_words:
                words = [
                    {
                        "start": float(w.start) if w.start is not None else None,
                        "end": float(w.end) if w.end is not None else None,
                        "word": w.word,
                        "confidence": getattr(w, "probability", None),
                    }
                    for w in seg_words
                ]
            confidence = _logprob_to_confidence(getattr(seg, "avg_logprob", None))
            if confidence is not None:
                confidences.append(confidence)
            segments.append(
                TranscriptSegment(
                    start=float(seg.start),
                    end=float(seg.end),
                    text=(seg.text or "").strip(),
                    confidence=confidence,
                    speaker=None,
                    words=words,
                )
            )
        overall = (sum(confidences) / len(confidences)) if confidences else None
        language = getattr(info, "language", None)
        log.info(
            "whisper_transcription_complete",
            language=language,
            segments=len(segments),
            device=self._resolved_device,
        )
        return TranscriptResult(language=language, segments=segments, confidence=overall)

    # -- public contract ---------------------------------------------------- #
    async def transcribe(
        self, audio_key: str, *, language_hint: str | None = None
    ) -> TranscriptResult:
        try:
            data = await self._storage.get(audio_key)
        except Exception as exc:
            raise ExternalServiceError(
                "Failed to read audio for transcription.",
                details={"audio_key": audio_key, "error": str(exc)},
            ) from exc

        suffix = Path(audio_key).suffix or ".wav"
        log.info(
            "whisper_transcription_started", audio_key=audio_key, model=self._model_name
        )
        with TemporaryDirectory() as tmp:
            audio_path = str(Path(tmp) / f"audio{suffix}")
            await asyncio.to_thread(Path(audio_path).write_bytes, data)
            deadline = time.monotonic() + self._timeout
            try:
                # Serialize inference (a single CTranslate2 model is not safe for
                # concurrent use) and bound it with a wall-clock timeout.
                async with self._lock:
                    return await asyncio.wait_for(
                        asyncio.to_thread(
                            self._transcribe_sync, audio_path, language_hint, deadline
                        ),
                        timeout=self._timeout + 30.0,
                    )
            except TimeoutError as exc:
                raise ExternalServiceError(
                    "Transcription timed out.",
                    details={"audio_key": audio_key, "timeout_seconds": self._timeout},
                ) from exc
            except ConfigurationError:
                raise
            except ExternalServiceError:
                raise
            except Exception as exc:
                raise ExternalServiceError(
                    "Transcription failed.",
                    details={"audio_key": audio_key, "error": str(exc)},
                ) from exc
