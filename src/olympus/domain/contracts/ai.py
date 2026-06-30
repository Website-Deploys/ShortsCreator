"""AI service contracts (ports).

These define the AI *capabilities* Olympus needs, decoupled from any specific
model or vendor (per the AI Model Strategy: "models are commodities; the
interfaces are the asset"). The foundation release defines the transcription
contract - the backbone capability - and its data shapes. Understanding,
selection, captioning, and editing-decision contracts follow the same pattern
in later milestones.

Adapters live in ``olympus.ai`` (e.g. a managed-ASR adapter, a self-hosted
Whisper adapter, and a ``noop`` adapter for wiring/tests).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TranscriptSegment:
    """A single timestamped segment of transcribed speech.

    Timestamps are in seconds from the start of the media. ``confidence`` is in
    ``[0, 1]`` where available; low-confidence segments are flagged downstream
    rather than blindly trusted (per the Story Understanding gates).
    """

    start: float
    end: float
    text: str
    confidence: float | None = None
    speaker: str | None = None
    # Optional per-word timings ``[{"start","end","word","confidence"}]`` when the
    # provider supplies them. Additive and optional: existing consumers that read
    # only segment-level fields are unaffected.
    words: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class TranscriptResult:
    """The full result of a transcription request."""

    language: str | None
    segments: list[TranscriptSegment] = field(default_factory=list)
    # Overall confidence across the transcript, where the provider reports it.
    confidence: float | None = None

    @property
    def text(self) -> str:
        """The concatenated transcript text."""

        return " ".join(segment.text.strip() for segment in self.segments).strip()


class TranscriptionProvider(abc.ABC):
    """Abstract speech-to-text provider.

    Implementations turn an audio artifact (referenced by storage key) into a
    timestamped transcript. They must surface confidence where the underlying
    model provides it, and raise
    :class:`olympus.platform.errors.ExternalServiceError` on provider failure.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable provider identifier (for logging and metrics)."""

    @abc.abstractmethod
    async def transcribe(
        self, audio_key: str, *, language_hint: str | None = None
    ) -> TranscriptResult:
        """Transcribe the audio stored at ``audio_key`` into a timestamped result."""
