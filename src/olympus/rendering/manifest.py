"""Helpers for building the render manifest from real rendered outputs.

The manifest is the Rendering Engine's official output contract (consumed by the
Optimization Engine). It is only ever built from *real* rendered files: each
:class:`RenderedVideo` carries a checksum computed over the actual encoded bytes
and metadata measured by the renderer. There is no path here that fabricates a
manifest entry for a file that does not exist.
"""

from __future__ import annotations

import hashlib

from olympus.domain.contracts.rendering import ClipRenderOutput
from olympus.domain.entities.rendering import RenderedVideo


def checksum_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of the encoded file bytes."""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def rendered_video_from_output(
    output: ClipRenderOutput,
    *,
    plan_id: str | None,
    rank: int | None,
    checksum: str,
    subtitles_included: bool,
    music_included: bool,
    timeline_version: str | None,
    rendered_at: str,
    source_video: dict[str, object],
) -> RenderedVideo:
    """Build a manifest entry from a real render output + measured checksum."""

    return RenderedVideo(
        clip_id=output.clip_id,
        storage_key=output.output_key,
        plan_id=plan_id,
        rank=rank,
        container="mp4",
        width=output.width,
        height=output.height,
        duration=output.duration,
        fps=output.fps,
        video_codec=output.video_codec,
        audio_codec=output.audio_codec,
        has_audio=output.has_audio,
        bitrate_kbps=output.bitrate_kbps,
        audio_sample_rate=output.audio_sample_rate,
        size_bytes=output.size_bytes,
        checksum=checksum,
        subtitles_included=subtitles_included,
        music_included=music_included,
        timeline_version=timeline_version,
        rendered_at=rendered_at,
        source_video=source_video,
    )
