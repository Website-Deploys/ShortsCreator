"""FFmpeg rendering adapter.

FFmpeg is the MVP's media workhorse (per the Video Processing Stack). This
adapter implements the :class:`Renderer` contract by translating an edit plan
into FFmpeg operations and executing them as a subprocess.

The foundation release wires the adapter, verifies the FFmpeg binary is
discoverable, and defines the execution shape. The plan-to-FFmpeg translation
(trim, vertical reframe, zoom, caption burn, audio cleanup) is implemented in
the Editing/Rendering milestone, where the edit-plan schema is finalised - so
this adapter currently rejects execution loudly rather than rendering silently
wrong output.
"""

from __future__ import annotations

import shutil

from olympus.domain.contracts.rendering import Renderer, RenderRequest, RenderResult
from olympus.platform.config import Settings, get_settings
from olympus.platform.errors import ConfigurationError, ExternalServiceError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


class FfmpegRenderer(Renderer):
    """Render Shorts using FFmpeg."""

    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._binary = settings.rendering.ffmpeg_binary

    @property
    def name(self) -> str:
        return "ffmpeg"

    def _resolve_binary(self) -> str:
        path = shutil.which(self._binary)
        if path is None:
            raise ConfigurationError(
                "FFmpeg binary not found on PATH.",
                details={"binary": self._binary},
            )
        return path

    async def render(self, request: RenderRequest) -> RenderResult:
        # Verify the toolchain is present (fail loudly if misconfigured).
        self._resolve_binary()
        log.info("render_requested", source=request.source_key, output=request.output_key)
        # The plan->FFmpeg translation is implemented in the Rendering milestone.
        raise ExternalServiceError(
            "Rendering is not implemented in the foundation release.",
            code="not_implemented",
            details={"output_key": request.output_key},
        )
