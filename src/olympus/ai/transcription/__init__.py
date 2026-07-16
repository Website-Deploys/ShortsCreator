"""Transcription provider adapters."""

from olympus.ai.transcription.faster_whisper import FasterWhisperTranscriptionProvider
from olympus.ai.transcription.noop import NoopTranscriptionProvider

__all__ = ["FasterWhisperTranscriptionProvider", "NoopTranscriptionProvider"]
