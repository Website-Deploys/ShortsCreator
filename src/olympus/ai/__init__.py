"""AI service adapters implementing the domain AI contracts.

The foundation provides the transcription adapter family (a ``noop`` provider
for wiring/tests, with managed-ASR and self-hosted adapters added later) and a
factory that selects the configured provider. Every adapter is hidden behind the
:class:`olympus.domain.contracts.TranscriptionProvider` contract.
"""

from olympus.ai.factory import build_transcription_provider

__all__ = ["build_transcription_provider"]
