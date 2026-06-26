"""Domain contracts (ports).

These abstract base classes define the *capabilities* Olympus needs - storage,
transcription, rendering - without binding to any concrete technology. Adapters
in ``olympus.data``, ``olympus.ai``, and ``olympus.rendering`` implement them.

This is the seam that makes "every subsystem replaceable" real: swapping a
provider means writing a new adapter for an existing contract, with zero changes
to callers.
"""

from olympus.domain.contracts.ai import (
    TranscriptionProvider,
    TranscriptResult,
    TranscriptSegment,
)
from olympus.domain.contracts.rendering import Renderer, RenderRequest, RenderResult
from olympus.domain.contracts.storage import StorageObject, StoragePort

__all__ = [
    "RenderRequest",
    "RenderResult",
    "Renderer",
    "StorageObject",
    "StoragePort",
    "TranscriptResult",
    "TranscriptSegment",
    "TranscriptionProvider",
]
