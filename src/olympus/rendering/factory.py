"""Rendering adapter factory."""

from __future__ import annotations

from olympus.domain.contracts.rendering import Renderer
from olympus.platform.config import Settings, get_settings
from olympus.platform.errors import ConfigurationError


def build_renderer(settings: Settings | None = None) -> Renderer:
    """Construct the configured rendering backend."""

    settings = settings or get_settings()
    backend = settings.rendering.backend.lower()

    if backend == "ffmpeg":
        from olympus.rendering.ffmpeg import FfmpegRenderer

        return FfmpegRenderer(settings)

    raise ConfigurationError(f"Unknown rendering backend: {backend!r}")
