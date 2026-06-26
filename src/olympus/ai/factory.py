"""AI adapter factories.

Select and construct AI providers from configuration, returning them typed as
their domain contract. New providers are registered here as they are added,
keeping provider selection in one place.
"""

from __future__ import annotations

from olympus.domain.contracts.ai import TranscriptionProvider
from olympus.platform.config import Settings, get_settings
from olympus.platform.errors import ConfigurationError


def build_transcription_provider(settings: Settings | None = None) -> TranscriptionProvider:
    """Construct the configured transcription provider."""

    settings = settings or get_settings()
    provider = settings.ai.transcription_provider.lower()

    if provider == "noop":
        from olympus.ai.transcription.noop import NoopTranscriptionProvider

        return NoopTranscriptionProvider()

    # Managed-ASR and self-hosted Whisper adapters are registered here in later
    # milestones (e.g. "deepgram", "assemblyai", "whisper").
    raise ConfigurationError(f"Unknown transcription provider: {provider!r}")
