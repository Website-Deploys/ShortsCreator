"""The Rendering Engine - deterministic execution of edit decisions into MP4s.

Where the Editing Engine decides *what* the cut should be, the Rendering Engine
*executes* it: it consumes the editing timelines (plus the source media) and
produces real, encoded MP4 files, then publishes the **render manifest** that the
Optimization Engine consumes. It makes no creative decisions of its own.

It is a fully independent, replaceable sibling of the other engines - its own
pipeline-state entities, contracts, stages, pipeline, repository, service, and
API - and it talks to the actual encoder only through the replaceable
:class:`ClipRenderer` port (FFmpeg today; GPU/cloud/distributed tomorrow). When
the renderer or a dependency is absent it reports ``UNAVAILABLE`` honestly and
never fabricates a rendered file or manifest.
"""

from olympus.rendering.factory import build_renderer
from olympus.rendering.ffmpeg_renderer import FfmpegClipRenderer, build_clip_renderer
from olympus.rendering.pipeline import (
    RENDER_PIPELINE_VERSION,
    RenderPipeline,
    build_default_render_stages,
)

__all__ = [
    "RENDER_PIPELINE_VERSION",
    "FfmpegClipRenderer",
    "RenderPipeline",
    "build_clip_renderer",
    "build_default_render_stages",
    "build_renderer",
]
