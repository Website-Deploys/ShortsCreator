"""Per-platform export profiles - deterministic, real publishing specifications.

These describe *what* a finished vertical Short should conform to for each
destination platform: resolution, frame rate, codec, container, recommended
bitrate, audio spec, caption safe-area, and the platform's UI-overlay safe zones
(so captions/important content are not hidden behind the platform's own buttons).

They are real, published technical recommendations encoded as deterministic
constants with a short reasoning string - not AI output and not guesses. They are
intentionally a *registry* so future platforms can be added without touching any
stage. The Optimization Engine reads these to plan exports and compression; it
does not itself encode anything (that is the Rendering Engine's job).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExportProfile:
    """A single platform's vertical-Short export specification."""

    platform: str
    label: str
    width: int
    height: int
    fps_options: tuple[int, ...]
    video_codec: str
    audio_codec: str
    container: str
    recommended_bitrate_kbps: int
    max_bitrate_kbps: int
    audio_bitrate_kbps: int
    audio_sample_rate: int
    max_duration_s: int
    # Fractions of frame height reserved for the platform's own UI overlays.
    safe_area: dict[str, float]
    reason: str

    @property
    def aspect_ratio(self) -> str:
        return "9:16"

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "label": self.label,
            "width": self.width,
            "height": self.height,
            "resolution": self.resolution,
            "aspect_ratio": self.aspect_ratio,
            "fps_options": list(self.fps_options),
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "container": self.container,
            "recommended_bitrate_kbps": self.recommended_bitrate_kbps,
            "max_bitrate_kbps": self.max_bitrate_kbps,
            "audio_bitrate_kbps": self.audio_bitrate_kbps,
            "audio_sample_rate": self.audio_sample_rate,
            "max_duration_s": self.max_duration_s,
            "safe_area": self.safe_area,
            "reason": self.reason,
        }


# 1080x1920 (9:16) is the shared baseline for vertical short-form video; the
# safe-area and duration caps differ per platform UI.
EXPORT_PROFILES: dict[str, ExportProfile] = {
    "youtube_shorts": ExportProfile(
        platform="youtube_shorts",
        label="YouTube Shorts",
        width=1080,
        height=1920,
        fps_options=(30, 60),
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
        recommended_bitrate_kbps=12000,
        max_bitrate_kbps=20000,
        audio_bitrate_kbps=192,
        audio_sample_rate=48000,
        max_duration_s=180,
        safe_area={"top_pct": 0.10, "bottom_pct": 0.20, "left_pct": 0.05, "right_pct": 0.12},
        reason="H.264/AAC in MP4 at 1080x1920 is YouTube Shorts' broadly compatible "
        "high-quality target; right/bottom margins clear the like/share/subscribe rail.",
    ),
    "tiktok": ExportProfile(
        platform="tiktok",
        label="TikTok",
        width=1080,
        height=1920,
        fps_options=(30, 60),
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
        recommended_bitrate_kbps=10000,
        max_bitrate_kbps=16000,
        audio_bitrate_kbps=128,
        audio_sample_rate=44100,
        max_duration_s=180,
        safe_area={"top_pct": 0.09, "bottom_pct": 0.22, "left_pct": 0.05, "right_pct": 0.14},
        reason="H.264/AAC MP4 at 1080x1920 is TikTok's recommended upload spec; the "
        "wider right/bottom safe area clears the action rail and caption/handle overlay.",
    ),
    "instagram_reels": ExportProfile(
        platform="instagram_reels",
        label="Instagram Reels",
        width=1080,
        height=1920,
        fps_options=(30,),
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
        recommended_bitrate_kbps=9000,
        max_bitrate_kbps=15000,
        audio_bitrate_kbps=128,
        audio_sample_rate=44100,
        max_duration_s=90,
        safe_area={"top_pct": 0.12, "bottom_pct": 0.22, "left_pct": 0.06, "right_pct": 0.14},
        reason="H.264/AAC MP4 at 1080x1920, 30fps is Reels' reliable target; larger "
        "top/bottom margins clear the profile header and caption/audio attribution.",
    ),
    "facebook_reels": ExportProfile(
        platform="facebook_reels",
        label="Facebook Reels",
        width=1080,
        height=1920,
        fps_options=(30,),
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
        recommended_bitrate_kbps=9000,
        max_bitrate_kbps=15000,
        audio_bitrate_kbps=128,
        audio_sample_rate=44100,
        max_duration_s=90,
        safe_area={"top_pct": 0.12, "bottom_pct": 0.20, "left_pct": 0.06, "right_pct": 0.12},
        reason="Facebook Reels shares the Meta vertical spec (H.264/AAC MP4, 1080x1920); "
        "safe margins clear the overlaid title, CTA, and engagement controls.",
    ),
    "snapchat_spotlight": ExportProfile(
        platform="snapchat_spotlight",
        label="Snapchat Spotlight",
        width=1080,
        height=1920,
        fps_options=(30,),
        video_codec="h264",
        audio_codec="aac",
        container="mp4",
        recommended_bitrate_kbps=8000,
        max_bitrate_kbps=12000,
        audio_bitrate_kbps=128,
        audio_sample_rate=44100,
        max_duration_s=60,
        safe_area={"top_pct": 0.10, "bottom_pct": 0.22, "left_pct": 0.06, "right_pct": 0.12},
        reason="Spotlight expects full-bleed 1080x1920 H.264/AAC MP4 with a short "
        "duration; generous bottom margin clears the caption and subscribe overlay.",
    ),
}

#: Stable ordering for display and iteration.
EXPORT_PLATFORM_ORDER: tuple[str, ...] = (
    "youtube_shorts",
    "tiktok",
    "instagram_reels",
    "facebook_reels",
    "snapchat_spotlight",
)


@dataclass(slots=True)
class ExportProfileRegistry:
    """A replaceable registry of export profiles (future platforms plug in here)."""

    profiles: dict[str, ExportProfile] = field(default_factory=lambda: dict(EXPORT_PROFILES))

    def get(self, platform: str) -> ExportProfile | None:
        return self.profiles.get(platform)

    def ordered(self) -> list[ExportProfile]:
        ordered = [self.profiles[p] for p in EXPORT_PLATFORM_ORDER if p in self.profiles]
        extra = [p for k, p in self.profiles.items() if k not in EXPORT_PLATFORM_ORDER]
        return ordered + extra

    def to_dict(self) -> dict[str, Any]:
        return {p.platform: p.to_dict() for p in self.ordered()}


def build_default_export_registry() -> ExportProfileRegistry:
    """Return the default registry of the five supported platforms."""

    return ExportProfileRegistry()
