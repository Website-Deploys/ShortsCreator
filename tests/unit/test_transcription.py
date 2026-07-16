"""Tests for the transcription providers and factory.

The faster-whisper provider is tested with an *injected fake model* so the suite
never downloads weights or needs a GPU - we verify the adapter's mapping,
device/compute resolution, CPU fallback, timeout, and error handling, not
Whisper itself.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from olympus.ai.factory import build_transcription_provider
from olympus.ai.transcription.faster_whisper import FasterWhisperTranscriptionProvider
from olympus.ai.transcription.noop import NoopTranscriptionProvider
from olympus.platform.config import Settings
from olympus.platform.errors import ConfigurationError, ExternalServiceError


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeStorage:
    """Minimal StoragePort stand-in returning fixed audio bytes."""

    def __init__(self, data: bytes = b"RIFF....WAVEfake", fail: bool = False) -> None:
        self._data = data
        self._fail = fail

    async def get(self, key: str) -> bytes:
        if self._fail:
            raise OSError("storage unavailable")
        return self._data


@dataclass
class _Word:
    start: float
    end: float
    word: str
    probability: float


@dataclass
class _Seg:
    start: float
    end: float
    text: str
    avg_logprob: float
    words: list[_Word]


class _Info:
    language = "en"


class FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel."""

    def __init__(self, model, *, device, compute_type, download_root):
        self.model, self.device, self.compute_type = model, device, compute_type

    def transcribe(self, audio_path, **kwargs):
        segs = [
            _Seg(0.0, 2.0, " Hello world", -0.1, [
                _Word(0.0, 0.5, "Hello", 0.9), _Word(0.5, 2.0, "world", 0.8)]),
            _Seg(2.0, 4.0, " second segment", -0.2, []),
        ]
        return iter(segs), _Info()


def _factory(*, fail_on_cuda: bool = False):
    def make(model, *, device, compute_type, download_root):
        if fail_on_cuda and device == "cuda":
            raise RuntimeError("CUDA driver not found")
        return FakeWhisperModel(
            model, device=device, compute_type=compute_type, download_root=download_root
        )
    return make


# --------------------------------------------------------------------------- #
# noop
# --------------------------------------------------------------------------- #
async def test_noop_returns_empty_transcript() -> None:
    provider = NoopTranscriptionProvider()
    assert provider.name == "noop"
    result = await provider.transcribe("analysis/p/audio.wav")
    assert result.segments == []
    assert result.text == ""


# --------------------------------------------------------------------------- #
# faster-whisper provider (with injected fake model)
# --------------------------------------------------------------------------- #
async def test_faster_whisper_maps_segments_words_and_language() -> None:
    provider = FasterWhisperTranscriptionProvider(
        FakeStorage(), device="cpu", compute_type="int8", model_factory=_factory()
    )
    assert provider.name == "faster-whisper"

    result = await provider.transcribe("analysis/p/audio.wav")

    assert result.language == "en"
    assert len(result.segments) == 2
    assert result.text == "Hello world second segment"
    first = result.segments[0]
    assert first.start == 0.0 and first.end == 2.0
    assert first.words and first.words[0]["word"] == "Hello"
    assert 0.0 <= (first.confidence or 0) <= 1.0  # logprob -> bounded confidence
    assert result.confidence is not None and 0.0 <= result.confidence <= 1.0


async def test_faster_whisper_writes_temp_audio_before_transcribing() -> None:
    seen: dict[str, int] = {}

    class RecordingWhisperModel(FakeWhisperModel):
        def transcribe(self, audio_path, **kwargs):
            path = Path(audio_path)
            seen["size"] = path.stat().st_size
            seen["bytes"] = len(path.read_bytes())
            return super().transcribe(audio_path, **kwargs)

    def make(model, *, device, compute_type, download_root):
        return RecordingWhisperModel(
            model, device=device, compute_type=compute_type, download_root=download_root
        )

    provider = FasterWhisperTranscriptionProvider(
        FakeStorage(b"RIFFfake-wav-data"), model_factory=make
    )

    await provider.transcribe("analysis/p/audio.wav")

    assert seen == {"size": len(b"RIFFfake-wav-data"), "bytes": len(b"RIFFfake-wav-data")}


async def test_faster_whisper_storage_failure_is_external_error() -> None:
    provider = FasterWhisperTranscriptionProvider(
        FakeStorage(fail=True), model_factory=_factory()
    )
    with pytest.raises(ExternalServiceError):
        await provider.transcribe("analysis/p/audio.wav")


async def test_faster_whisper_model_load_failure_is_external_error() -> None:
    def make(model, *, device, compute_type, download_root):
        raise RuntimeError("model weights unavailable")

    provider = FasterWhisperTranscriptionProvider(FakeStorage(), model_factory=make)

    with pytest.raises(ExternalServiceError) as exc:
        await provider.transcribe("analysis/p/audio.wav")

    assert exc.value.message == "Transcription failed."


async def test_faster_whisper_cpu_fallback_when_cuda_init_fails() -> None:
    # Force device=cuda; the factory raises on cuda, so the provider must retry CPU.
    provider = FasterWhisperTranscriptionProvider(
        FakeStorage(), device="cuda", model_factory=_factory(fail_on_cuda=True)
    )
    result = await provider.transcribe("analysis/p/audio.wav")
    assert len(result.segments) == 2
    assert provider._resolved_device == "cpu"  # fell back


async def test_faster_whisper_timeout_raises_external_error() -> None:
    provider = FasterWhisperTranscriptionProvider(
        FakeStorage(), timeout_seconds=0.0, model_factory=_factory()
    )
    # deadline = now + 0 -> the first segment iteration is already past it.
    with pytest.raises(ExternalServiceError):
        await provider.transcribe("analysis/p/audio.wav")


async def test_faster_whisper_compute_auto_resolves_int8_on_cpu() -> None:
    provider = FasterWhisperTranscriptionProvider(
        FakeStorage(), device="cpu", compute_type="auto", model_factory=_factory()
    )
    await provider.transcribe("analysis/p/audio.wav")
    assert provider._resolved_compute == "int8"


async def test_faster_whisper_consumes_lazy_segment_generator() -> None:
    consumed = {"count": 0}

    class LazyWhisperModel(FakeWhisperModel):
        def transcribe(self, audio_path, **kwargs):
            def generate():
                for seg in [
                    _Seg(0.0, 1.0, " one", -0.1, []),
                    _Seg(1.0, 2.0, " two", -0.1, []),
                ]:
                    consumed["count"] += 1
                    yield seg

            return generate(), _Info()

    def make(model, *, device, compute_type, download_root):
        return LazyWhisperModel(
            model, device=device, compute_type=compute_type, download_root=download_root
        )

    provider = FasterWhisperTranscriptionProvider(FakeStorage(), model_factory=make)

    result = await provider.transcribe("analysis/p/audio.wav")

    assert consumed["count"] == 2
    assert result.text == "one two"


async def test_faster_whisper_empty_transcript_is_external_error() -> None:
    class EmptyWhisperModel(FakeWhisperModel):
        def transcribe(self, audio_path, **kwargs):
            return iter([]), _Info()

    def make(model, *, device, compute_type, download_root):
        return EmptyWhisperModel(
            model, device=device, compute_type=compute_type, download_root=download_root
        )

    provider = FasterWhisperTranscriptionProvider(FakeStorage(), model_factory=make)

    with pytest.raises(ExternalServiceError) as exc:
        await provider.transcribe("analysis/p/audio.wav")

    assert exc.value.message == "Transcription completed but returned no speech segments."


async def test_faster_whisper_serializes_concurrent_calls() -> None:
    # Two concurrent transcriptions must both succeed (lock-serialized, no crash).
    provider = FasterWhisperTranscriptionProvider(FakeStorage(), model_factory=_factory())
    results = await asyncio.gather(
        provider.transcribe("a.wav"), provider.transcribe("b.wav")
    )
    assert all(len(r.segments) == 2 for r in results)


# --------------------------------------------------------------------------- #
# factory
# --------------------------------------------------------------------------- #
def _settings(provider: str) -> Settings:
    return Settings(ai={"transcription_provider": provider})


def test_factory_builds_noop() -> None:
    assert build_transcription_provider(_settings("noop")).name == "noop"


def test_factory_builds_faster_whisper_with_storage() -> None:
    provider = build_transcription_provider(_settings("faster-whisper"), storage=FakeStorage())
    assert provider.name == "faster-whisper"
    assert isinstance(provider, FasterWhisperTranscriptionProvider)


def test_factory_faster_whisper_requires_storage() -> None:
    with pytest.raises(ConfigurationError):
        build_transcription_provider(_settings("faster-whisper"), storage=None)


def test_factory_unknown_provider_raises() -> None:
    with pytest.raises(ConfigurationError):
        build_transcription_provider(_settings("definitely-not-a-provider"), storage=FakeStorage())


def test_settings_whisper_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.ai.transcription_provider == "noop"
    assert s.ai.whisper_model == "base"
    assert s.ai.whisper_device == "auto"
    assert s.ai.whisper_compute_type == "auto"
    assert s.ai.whisper_beam_size == 5
