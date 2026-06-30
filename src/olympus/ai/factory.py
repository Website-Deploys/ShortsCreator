"""AI adapter factories.

Select and construct AI providers from configuration, returning them typed as
their domain contract. New providers are registered here as they are added,
keeping provider selection in one place.
"""

from __future__ import annotations

from olympus.domain.contracts.ai import TranscriptionProvider
from olympus.domain.contracts.storage import StoragePort
from olympus.platform.config import Settings, get_settings
from olympus.platform.errors import ConfigurationError


def build_transcription_provider(
    settings: Settings | None = None, *, storage: StoragePort | None = None
) -> TranscriptionProvider:
    """Construct the configured transcription provider.

    ``storage`` is required by real providers (they resolve the audio artifact
    from its storage key); ``noop`` ignores it, so the parameter is optional to
    preserve backward compatibility with existing callers.
    """

    settings = settings or get_settings()
    provider = settings.ai.transcription_provider.lower()

    if provider == "noop":
        from olympus.ai.transcription.noop import NoopTranscriptionProvider

        return NoopTranscriptionProvider()

    if provider in ("faster-whisper", "faster_whisper", "whisper"):
        if storage is None:
            raise ConfigurationError(
                "The 'faster-whisper' transcription provider requires a storage "
                "adapter to read audio; none was provided."
            )
        from olympus.ai.transcription.faster_whisper import (
            FasterWhisperTranscriptionProvider,
        )

        ai = settings.ai
        return FasterWhisperTranscriptionProvider(
            storage,
            model=ai.whisper_model,
            device=ai.whisper_device,
            compute_type=ai.whisper_compute_type,
            beam_size=ai.whisper_beam_size,
            language=ai.whisper_language,
            download_root=ai.whisper_download_root,
            timeout_seconds=ai.whisper_timeout_seconds,
        )

    # Managed-ASR adapters (e.g. "deepgram", "assemblyai") register here later.
    raise ConfigurationError(f"Unknown transcription provider: {provider!r}")
