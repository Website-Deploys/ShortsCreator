"""Pure timeline-to-FFmpeg translation - the deterministic render plan.

The Rendering Engine executes the Editing Engine's decisions; it never makes new
ones. These pure functions translate a clip-relative editing timeline into the
concrete render operations and the FFmpeg invocation that realises them: source
trim range, segment list, jump-cut/zoom/crop/transition operations, caption cues
(+ a standards-compliant SRT), the audio-mix plan, and finally the full FFmpeg
argument vector.

Everything here is deterministic and side-effect-free (no subprocess, no I/O), so
it is fully unit-testable and is the single source of truth shared by both the
"apply_*" planning stages (which report what will be done) and the FFmpeg
renderer (which executes it). It is intentionally self-contained - it imports no
other engine - so the Rendering Engine stays independently replaceable.
"""

from __future__ import annotations

from typing import Any

# Marker/event type tokens we recognise on the timeline (substring/prefix match).
_JUMP_TOKENS = ("jump_cut", "silence", "cut")
_ZOOM_TOKENS = ("zoom",)
_TRANSITION_TOKENS = ("transition", "crossfade", "dissolve", "fade")
_BROLL_TOKENS = ("broll", "b_roll", "b-roll")
_MUSIC_TOKENS = ("music",)


# -- coercion (local, to keep this module engine-independent) -----------------
def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _track(timeline: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    for track in _as_list(timeline.get("tracks")):
        if isinstance(track, dict) and track.get("kind") == kind:
            return _as_list(track.get("events"))
    return []


def _all_events(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for track in _as_list(timeline.get("tracks")):
        events.extend(e for e in _as_list(_as_dict(track).get("events")) if isinstance(e, dict))
    return events


def _matches(event_type: str, tokens: tuple[str, ...]) -> bool:
    low = event_type.lower()
    return any(tok in low for tok in tokens)


# -- source range ------------------------------------------------------------
def source_range(timeline: dict[str, Any]) -> tuple[float, float]:
    """The (start, end) range in the *source* video this clip is taken from."""

    start = _as_float(timeline.get("source_start"))
    end = _as_float(timeline.get("source_end"))
    if end <= start:
        end = start + _as_float(timeline.get("duration"))
    return start, end


# -- video / audio segments --------------------------------------------------
def video_segments(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered video segments (clip-relative). Falls back to one full segment."""

    events = _track(timeline, "video")
    segments = [
        {
            "start": _as_float(e.get("start")),
            "end": _as_float(e.get("end")),
            "duration": _as_float(e.get("duration"))
            or _as_float(e.get("end")) - _as_float(e.get("start")),
            "type": _as_str(e.get("type")) or "segment",
        }
        for e in events
    ]
    if not segments:
        duration = _as_float(timeline.get("duration"))
        segments = [{"start": 0.0, "end": duration, "duration": duration, "type": "segment"}]
    return segments


def audio_segments(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered audio segments (clip-relative). Falls back to one full segment."""

    events = _track(timeline, "audio")
    segments = [
        {
            "start": _as_float(e.get("start")),
            "end": _as_float(e.get("end")),
            "type": _as_str(e.get("type")) or "speech",
        }
        for e in events
    ]
    if not segments:
        duration = _as_float(timeline.get("duration"))
        segments = [{"start": 0.0, "end": duration, "type": "speech"}]
    return segments


# -- edit operations ----------------------------------------------------------
def jump_cut_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"at": _as_float(e.get("start")), "type": _as_str(e.get("type")), "reason": e.get("reason")}
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _JUMP_TOKENS)
    ]


def zoom_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "at": _as_float(e.get("start")),
            "end": _as_float(e.get("end")) or None,
            "scale": e.get("scale"),
            "type": _as_str(e.get("type")),
            "reason": e.get("reason"),
        }
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _ZOOM_TOKENS)
    ]


def crop_op(timeline: dict[str, Any]) -> dict[str, Any]:
    meta = _as_dict(timeline.get("metadata"))
    crop = meta.get("crop")
    aspect = _as_str(meta.get("aspect_ratio")) or "9:16"
    return {
        "mode": _as_str(crop) if isinstance(crop, str) and crop else "center",
        "target_aspect": aspect,
        "reason": "reframe source to the vertical target while keeping the focal subject centered",
    }


def transition_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "at": _as_float(e.get("start")),
            "transition_type": _as_str(e.get("transition_type")) or _as_str(e.get("type")),
            "duration": _as_float(e.get("duration")) or 0.3,
            "reason": e.get("reason"),
        }
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _TRANSITION_TOKENS)
    ]


def caption_cues(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    cues = [
        {
            "start": _as_float(e.get("start")),
            "end": _as_float(e.get("end")),
            "text": _as_str(e.get("text")),
        }
        for e in _track(timeline, "caption")
        if _as_str(e.get("text")).strip()
    ]
    cues.sort(key=lambda c: _as_float(c.get("start")))
    return cues


def broll_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"at": _as_float(e.get("start")), "type": _as_str(e.get("type")), "reason": e.get("reason")}
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _BROLL_TOKENS)
    ]


def music_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"at": _as_float(e.get("start")), "type": _as_str(e.get("type")), "reason": e.get("reason")}
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _MUSIC_TOKENS)
    ]


def audio_mix_plan(timeline: dict[str, Any]) -> dict[str, Any]:
    has_music = bool(music_ops(timeline))
    return {
        "ducking": has_music,
        "music_gain_db_under_speech": -18 if has_music else None,
        "speech_gain_db": 0,
        "fade_in_s": 0.3,
        "fade_out_s": 0.5,
        "silence_trim": bool(jump_cut_ops(timeline)),
    }


def subtitles_included(timeline: dict[str, Any]) -> bool:
    return bool(caption_cues(timeline))


def music_included(timeline: dict[str, Any]) -> bool:
    return bool(music_ops(timeline))


# -- SRT generation (self-contained) -----------------------------------------
def _ts_srt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = round((seconds - int(seconds)) * 1000)
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues: list[dict[str, Any]]) -> str:
    """Build a standards-compliant SRT document from caption cues."""

    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        text = _as_str(cue.get("text")).strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(
            f"{_ts_srt(_as_float(cue.get('start')))} --> {_ts_srt(_as_float(cue.get('end')))}"
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# -- FFmpeg command builder ---------------------------------------------------
def video_filter(
    timeline: dict[str, Any], width: int, height: int, *, srt_path: str | None = None
) -> str:
    """Build the FFmpeg ``-vf`` filter chain that realises the timeline's reframe.

    Scales the source to cover the vertical target, center-crops to exactly
    WxH, applies a gentle global zoom when the timeline contains zoom moments,
    and burns captions from ``srt_path`` when provided. Deterministic and real.
    """

    filters = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    if zoom_ops(timeline):
        # A gentle, even punch-in conveying the planned zoom emphasis.
        filters.append("zoompan=z='min(zoom+0.0005,1.1)':d=1")
    if srt_path:
        escaped = srt_path.replace(":", "\\:").replace("'", "\\'")
        filters.append(f"subtitles='{escaped}'")
    return ",".join(filters)


def build_ffmpeg_command(
    *,
    binary: str,
    source_path: str,
    output_path: str,
    timeline: dict[str, Any],
    width: int,
    height: int,
    fps: int,
    video_bitrate_kbps: int,
    audio_bitrate_kbps: int,
    srt_path: str | None = None,
) -> list[str]:
    """Build the full FFmpeg argument vector to render one clip (real, runnable).

    Trims the source to the clip's source range, reframes to the vertical target,
    burns captions when present, and encodes H.264/AAC in MP4 at the requested
    bitrate/fps. This is exactly what the FFmpeg renderer executes.
    """

    start, end = source_range(timeline)
    return [
        binary,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        source_path,
        "-vf",
        video_filter(timeline, width, height, srt_path=srt_path),
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        f"{video_bitrate_kbps}k",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        f"{audio_bitrate_kbps}k",
        "-movflags",
        "+faststart",
        output_path,
    ]


def build_ffprobe_command(*, binary: str, path: str) -> list[str]:
    """Build an ffprobe command that returns the encoded file's real metadata."""

    return [
        binary,
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate:stream=codec_type,codec_name,width,height,sample_rate,r_frame_rate",
        "-of",
        "json",
        path,
    ]
