"""No-op transcription provider.

Implements the transcription contract without calling any model. It lets the
application start and the full pipeline be wired and tested with *no* model
credentials. It returns an empty, clearly-labelled transcript and never
pretends to have understood audio (honesty over fake output).

Real providers (managed ASR, self-hosted Whisper) implement the same contract
and are selected by configuration in deployed environments.
"""

from __future__ import annotations

from olympus.domain.contracts.ai import TranscriptionProvider, TranscriptResult
from olympus.platform.logging import get_logger

log = get_logger(__name__)


class NoopTranscriptionProvider(TranscriptionProvider):
    """A transcription provider that performs no transcription."""

    @property
    def name(self) -> str:
        return "noop"

    async def transcribe(
        self, audio_key: str, *, language_hint: str | None = None
    ) -> TranscriptResult:
        log.warning(
            "noop_transcription_used",
            audio_key=audio_key,
            detail="No real transcription performed; configure a provider.",
        )
        return TranscriptResult(language=language_hint, segments=[], confidence=None)
