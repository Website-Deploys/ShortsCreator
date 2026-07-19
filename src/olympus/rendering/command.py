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

import re
from itertools import pairwise
from typing import Any

# Marker/event type tokens we recognise on the timeline (substring/prefix match).
_JUMP_TOKENS = ("jump_cut", "silence", "cut")
_ZOOM_TOKENS = ("zoom", "punch_in", "push_in", "payoff_hold", "quote_hold")
_TRANSITION_TOKENS = ("transition", "crossfade", "dissolve", "fade")
_BROLL_TOKENS = ("broll", "b_roll", "b-roll")
_MUSIC_TOKENS = ("music",)
_SFX_TOKENS = ("sfx", "impact", "whoosh", "pop", "riser", "hit")
VOICE_PROCESSING_LATENCY_SECONDS = 0.025


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
def source_window_metadata(timeline: dict[str, Any]) -> dict[str, Any]:
    """Return canonical repaired-window truth with a legacy-safe fallback."""

    direct = _as_dict(timeline.get("source_window_v1"))
    nested = _as_dict(_as_dict(timeline.get("metadata")).get("timeline"))
    for canonical in (direct, nested):
        repaired_start = _as_float(canonical.get("repaired_start_seconds"), -1.0)
        repaired_end = _as_float(canonical.get("repaired_end_seconds"), -1.0)
        if repaired_start >= 0.0 and repaired_end > repaired_start:
            return canonical

    start = _as_float(timeline.get("source_start"))
    end = _as_float(timeline.get("source_end"))
    if end <= start:
        end = start + max(0.1, _as_float(timeline.get("duration"), 0.1))
    return {
        "contract_version": "legacy",
        "project_id": timeline.get("project_id"),
        "clip_id": timeline.get("clip_id"),
        "requested_start_seconds": start,
        "requested_end_seconds": end,
        "repaired_start_seconds": start,
        "repaired_end_seconds": end,
        "duration_seconds": end - start,
        "preroll_seconds": 0.0,
        "postroll_seconds": 0.0,
        "boundary_repair_applied": False,
        "start_reason": "legacy timeline fallback",
        "end_reason": "legacy timeline fallback",
        "warnings": ["Canonical repaired source-window metadata was unavailable."],
    }


def source_range(timeline: dict[str, Any]) -> tuple[float, float]:
    """The (start, end) range in the *source* video this clip is taken from."""

    source_window = source_window_metadata(timeline)
    return (
        _as_float(source_window.get("repaired_start_seconds")),
        _as_float(source_window.get("repaired_end_seconds")),
    )


def expected_duration(timeline: dict[str, Any]) -> float:
    start, end = source_range(timeline)
    return max(0.1, end - start)


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
    operations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in _all_events(timeline):
        event_type = _as_str(event.get("type"))
        if not _matches(event_type, _ZOOM_TOKENS):
            continue
        identity = _as_str(event.get("effect_id") or event.get("id")) or (
            f"{event_type}:{_as_float(event.get('start')):.3f}:"
            f"{_as_float(event.get('end')):.3f}"
        )
        if identity in seen:
            continue
        seen.add(identity)
        operations.append(
            {
                "effect_id": identity,
                "at": _as_float(event.get("start")),
                "end": _as_float(event.get("end")) or None,
                "scale": event.get("scale"),
                "type": event_type,
                "reason": event.get("reason"),
                "easing": event.get("easing"),
                "expected_filter": event.get("expected_filter") or "zoompan",
            }
        )
    return operations


def motion_intelligence(timeline: dict[str, Any]) -> dict[str, Any]:
    meta = _as_dict(timeline.get("metadata"))
    editing = _as_dict(meta.get("editing_v2"))
    value = meta.get("motion_intelligence_v2") or editing.get("motion_intelligence_v2")
    return value if isinstance(value, dict) else {}


def motion_effects(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    plan = _as_dict(motion_intelligence(timeline).get("effect_plan"))
    return [item for item in _as_list(plan.get("effects")) if isinstance(item, dict)]


def motion_expected_filters(timeline: dict[str, Any]) -> list[str]:
    render_plan = _as_dict(motion_intelligence(timeline).get("render_plan"))
    return list(
        dict.fromkeys(
            _as_str(item)
            for item in _as_list(render_plan.get("ffmpeg_filters_expected"))
            if _as_str(item)
        )
    )


def crop_op(timeline: dict[str, Any]) -> dict[str, Any]:
    meta = _as_dict(timeline.get("metadata"))
    crop = meta.get("crop")
    face_plan = face_tracking_plan(timeline)
    aspect = _as_str(meta.get("aspect_ratio")) or "9:16"
    return {
        "mode": _as_str(face_plan.get("mode"))
        or (_as_str(crop) if isinstance(crop, str) and crop else "center"),
        "target_aspect": aspect,
        "face_tracking_applied": face_tracking_renderable(timeline),
        "keyframes_count": len(_as_list(face_plan.get("crop_keyframes"))),
        "reason": "reframe source to the vertical target while keeping the focal subject centered",
    }


def face_tracking_plan(timeline: dict[str, Any]) -> dict[str, Any]:
    meta = _as_dict(timeline.get("metadata"))
    plan = meta.get("multi_speaker_layout_v2") or meta.get("face_tracking_plan")
    if isinstance(plan, dict):
        return plan
    editing = _as_dict(meta.get("editing_v2"))
    plan = editing.get("multi_speaker_layout_v2") or editing.get("face_tracking_plan")
    return plan if isinstance(plan, dict) else {}


def face_tracking_renderable(timeline: dict[str, Any]) -> bool:
    plan = face_tracking_plan(timeline)
    if _as_str(plan.get("mode")) == "center_fallback":
        return False
    render_plan = _as_dict(plan.get("render_plan"))
    if render_plan and render_plan.get("renderable") is False:
        return False
    if _as_str(plan.get("mode")) == "two_speaker_stack":
        regions = [_as_dict(item) for item in _as_list(plan.get("layout_regions"))]
        return len(regions) >= 2 and all(
            len(_as_list(region.get("crop_keyframes"))) >= 2 for region in regions[:2]
        )
    keyframes = _as_list(plan.get("crop_keyframes"))
    if _as_str(plan.get("mode")) == "active_speaker_focus":
        return len(keyframes) >= 2 and len(_as_list(plan.get("speaker_switches"))) >= 1
    return len(keyframes) >= 2


def multi_speaker_stack_renderable(timeline: dict[str, Any]) -> bool:
    plan = face_tracking_plan(timeline)
    return _as_str(plan.get("mode")) == "two_speaker_stack" and face_tracking_renderable(
        timeline
    )


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
    cues = []
    for event in _track(timeline, "caption"):
        text = _as_str(event.get("text")).strip()
        if not text:
            continue
        cues.append(
            {
                **event,
                "start": _as_float(event.get("start")),
                "end": _as_float(event.get("end")),
                "text": text,
            }
        )
    cues.sort(key=lambda c: _as_float(c.get("start")))
    return cues


def broll_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"at": _as_float(e.get("start")), "type": _as_str(e.get("type")), "reason": e.get("reason")}
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _BROLL_TOKENS)
    ]


def music_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    meta = _as_dict(timeline.get("metadata"))
    editing = _as_dict(meta.get("editing_v2"))
    intelligence = _as_dict(
        meta.get("music_intelligence_v2") or editing.get("music_intelligence_v2")
    )
    should_use = _as_dict(intelligence.get("decision")).get("should_use_music")
    if should_use is False:
        return []
    return [
        {"at": _as_float(e.get("start")), "type": _as_str(e.get("type")), "reason": e.get("reason")}
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _MUSIC_TOKENS)
    ]


def sfx_ops(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "at": _as_float(e.get("start")),
            "type": _as_str(e.get("type")),
            "gain_db": e.get("volume_db"),
            "reason": e.get("reason"),
        }
        for e in _all_events(timeline)
        if _matches(_as_str(e.get("type")), _SFX_TOKENS)
    ]


def audio_mix_plan(timeline: dict[str, Any]) -> dict[str, Any]:
    assets = render_assets(timeline)
    music = _as_dict(assets.get("music"))
    sfx = _as_dict(assets.get("sfx"))
    has_music = bool(music.get("mixed"))
    mix = _as_dict(music.get("mix_plan"))
    ducking = _as_dict(music.get("ducking_plan"))
    sfx_count = int(sfx.get("mixed_count") or 0)
    return {
        "ducking": bool(has_music and ducking.get("enabled")),
        "ducking_method": ducking.get("method") if has_music else None,
        "music_gain_db_under_speech": mix.get("music_gain_db") if has_music else None,
        "speech_gain_db": 0,
        "fade_in_s": 0.3,
        "fade_out_s": 0.5,
        "silence_trim": bool(jump_cut_ops(timeline)),
        "voice_enhancement": True,
        "loudness_normalization": True,
        "music_mixed": has_music,
        "sfx_mixed_count": sfx_count,
    }


def subtitles_included(timeline: dict[str, Any]) -> bool:
    return bool(caption_cues(timeline))


def music_included(timeline: dict[str, Any]) -> bool:
    return bool(_as_dict(render_assets(timeline).get("music")).get("mixed")) or bool(
        music_ops(timeline)
    )


def render_assets(timeline: dict[str, Any]) -> dict[str, Any]:
    meta = _as_dict(timeline.get("metadata"))
    return _as_dict(meta.get("render_assets_v2"))


def _music_asset_available(timeline: dict[str, Any]) -> bool:
    meta = _as_dict(timeline.get("metadata"))
    decision = _as_dict(meta.get("music_decision_v2"))
    status = _as_str(decision.get("status")).lower()
    return status in {"available", "selected"} and bool(
        decision.get("asset_key") or decision.get("path") or decision.get("file")
    )


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


# -- ASS caption generation ---------------------------------------------------
def _ts_ass(seconds: float) -> str:
    total_centiseconds = max(0, round(seconds * 100))
    h, remainder = divmod(total_centiseconds, 360_000)
    m, remainder = divmod(remainder, 6_000)
    s, cs = divmod(remainder, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return (
        text.replace("\\", "\uff3c")
        .replace("{", "\uff5b")
        .replace("}", "\uff5d")
        .replace("\r\n", r"\N")
        .replace("\n", r"\N")
    )


def _highlight_ass(text: str, words: list[str], *, reset_style: str, accent: str) -> str:
    out: list[str] = []
    highlight = {w.lower() for w in words}
    for raw in text.split():
        key = "".join(ch for ch in raw.lower() if ch.isalpha() or ch == "'")
        escaped = _ass_escape(raw)
        if key in highlight:
            out.append(
                rf"{{\c{accent}&\3c&H08111F&\b1\fscx106\fscy106}}"
                + escaped
                + rf"{{\r{reset_style}}}"
            )
        else:
            out.append(escaped)
    return " ".join(out)


def _ass_name(value: Any, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", _as_str(value))
    return cleaned or fallback


def _default_caption_styles(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    editing = _as_dict(_as_dict(timeline.get("metadata")).get("editing_v2"))
    caption_style = _as_dict(editing.get("caption_style"))
    style = _as_str(caption_style.get("style"))
    font_size = 72 if "educational" in style else 82
    return [
        {
            "name": "Normal",
            "font_family": "Arial",
            "font_size": font_size,
            "primary_color": "&H00FFFFFF",
            "secondary_color": "&H0032F4FF",
            "outline_color": "&H00101010",
            "back_color": "&H70000000",
            "bold": True,
            "outline": 5,
            "shadow": 2,
            "alignment": 2,
            "margin_l": 72,
            "margin_r": 72,
            "margin_v": 260,
        },
        {
            "name": "Hook",
            "font_family": "Arial",
            "font_size": font_size + 12,
            "primary_color": "&H00FFFFFF",
            "secondary_color": "&H0032F4FF",
            "outline_color": "&H00101010",
            "back_color": "&H70000000",
            "bold": True,
            "outline": 6,
            "shadow": 2,
            "alignment": 2,
            "margin_l": 72,
            "margin_r": 72,
            "margin_v": 260,
        },
    ]


def _ass_style_line(style: dict[str, Any]) -> str:
    name = _ass_name(style.get("name"), "Normal")
    font = _as_str(style.get("font_family")).replace(",", " ").strip() or "Arial"
    size = max(24, min(140, round(_as_float(style.get("font_size"), 74))))
    primary = _as_str(style.get("primary_color")) or "&H00FFFFFF"
    secondary = _as_str(style.get("secondary_color")) or "&H0032F4FF"
    outline_color = _as_str(style.get("outline_color")) or "&H00101010"
    back = _as_str(style.get("back_color")) or "&H70000000"
    bold = -1 if style.get("bold") else 0
    outline = max(0, min(12, round(_as_float(style.get("outline"), 5))))
    shadow = max(0, min(8, round(_as_float(style.get("shadow"), 2))))
    alignment = max(1, min(9, round(_as_float(style.get("alignment"), 2))))
    margin_l = max(0, round(_as_float(style.get("margin_l"), 72)))
    margin_r = max(0, round(_as_float(style.get("margin_r"), 72)))
    margin_v = max(0, round(_as_float(style.get("margin_v"), 260)))
    return (
        f"Style: {name},{font},{size},{primary},{secondary},{outline_color},{back},"
        f"{bold},0,0,0,100,100,0,0,1,{outline},{shadow},{alignment},"
        f"{margin_l},{margin_r},{margin_v},1"
    )


def _ass_animation(animation: str) -> str:
    if animation == "none":
        return ""
    if animation == "pop_in":
        return r"{\fad(25,70)\fscx92\fscy92\t(0,130,\fscx100\fscy100)}"
    if animation == "subtle_scale":
        return r"{\fad(55,90)\fscx97\fscy97\t(0,180,\fscx100\fscy100)}"
    if animation == "bounce_light":
        return r"{\fad(25,65)\fscx94\fscy94\t(0,90,\fscx104\fscy104)\t(90,170,\fscx100\fscy100)}"
    if animation == "quote_hold":
        return r"{\fad(120,180)}"
    if animation == "emphasis_pulse":
        return r"{\fad(35,80)\t(0,120,\fscx106\fscy106)\t(120,220,\fscx100\fscy100)}"
    return r"{\fad(55,90)}"


def _karaoke_ass(text: str, word_timings: list[dict[str, Any]]) -> str:
    if not word_timings:
        return _ass_escape(text)
    output: list[str] = []
    for item in word_timings:
        word = _ass_escape(_as_str(item.get("word")).strip())
        duration_cs = max(
            1,
            round(
                max(0.01, _as_float(item.get("end")) - _as_float(item.get("start")))
                * 100
            ),
        )
        if word:
            output.append(rf"{{\k{duration_cs}}}{word}")
    return " ".join(output) or _ass_escape(text)


def build_ass(cues: list[dict[str, Any]], timeline: dict[str, Any]) -> str:
    """Build libass-compatible V2 captions from the exact timeline events."""

    meta = _as_dict(timeline.get("metadata"))
    editing = _as_dict(meta.get("editing_v2"))
    intelligence = _as_dict(
        meta.get("caption_intelligence_v2") or editing.get("caption_intelligence_v2")
    )
    legacy_style = _as_str(_as_dict(editing.get("caption_style")).get("style"))
    render_plan = _as_dict(intelligence.get("render_plan"))
    styles = [
        _as_dict(style)
        for style in _as_list(render_plan.get("styles"))
        if _as_str(_as_dict(style).get("name"))
    ] or _default_caption_styles(timeline)
    style_map = {_ass_name(style.get("name"), "Normal"): style for style in styles}
    if "Normal" not in style_map:
        fallback = _default_caption_styles(timeline)[0]
        styles.insert(0, fallback)
        style_map["Normal"] = fallback
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *[_ass_style_line(style) for style in styles],
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events: list[str] = []
    for cue in cues:
        text = _as_str(cue.get("text")).strip()
        if not text:
            continue
        style_name = _ass_name(cue.get("ass_style"), "Normal")
        if style_name not in style_map:
            style_name = "Normal"
        style = style_map[style_name]
        accent = _as_str(style.get("secondary_color")) or "&H0032F4FF"
        words = [str(w) for w in cue.get("highlighted_words", []) if isinstance(w, str)]
        legacy_uppercase = not intelligence and any(
            token in legacy_style for token in ("motivational", "bold_hook")
        )
        display_text = text.upper() if cue.get("uppercase") is True or legacy_uppercase else text
        animation = _as_str(cue.get("animation"))
        if animation == "karaoke_word" and _as_list(cue.get("word_timings")):
            caption = _karaoke_ass(
                display_text,
                [_as_dict(word) for word in _as_list(cue.get("word_timings"))],
            )
        else:
            caption = _highlight_ass(
                display_text,
                words[:3],
                reset_style=style_name,
                accent=accent,
            )
        start = _as_float(cue.get("start"))
        animation_override = _ass_animation(animation)
        speaker_name = _as_str(cue.get("speaker_label")).replace(",", " ")[:32]
        events.append(
            f"Dialogue: 0,{_ts_ass(start)},{_ts_ass(_as_float(cue.get('end')))},"
            f"{style_name},{speaker_name},0,0,0,,{animation_override}{caption}"
        )
    return "\n".join([*header, *events]).strip() + "\n"


def validate_ass(content: str) -> dict[str, Any]:
    """Validate generated ASS structure, styles, event timestamps, and override balance."""

    warnings: list[str] = []
    required = ("[Script Info]", "[V4+ Styles]", "[Events]")
    for section in required:
        if section not in content:
            warnings.append(f"missing ASS section {section}")
    styles = {
        line.split(",", 1)[0].removeprefix("Style: ").strip()
        for line in content.splitlines()
        if line.startswith("Style: ") and "," in line
    }
    dialogues = [line for line in content.splitlines() if line.startswith("Dialogue: ")]
    for index, line in enumerate(dialogues, start=1):
        fields = line.split(",", 9)
        if len(fields) != 10:
            warnings.append(f"dialogue {index} does not contain ten ASS fields")
            continue
        if fields[3].strip() not in styles:
            warnings.append(f"dialogue {index} references undefined style {fields[3].strip()!r}")
        start_match = re.fullmatch(
            r"(\d+):([0-5]\d):([0-5]\d)\.(\d{2})", fields[1].strip()
        )
        end_match = re.fullmatch(
            r"(\d+):([0-5]\d):([0-5]\d)\.(\d{2})", fields[2].strip()
        )
        if not start_match:
            warnings.append(f"dialogue {index} has an invalid start timestamp")
        if not end_match:
            warnings.append(f"dialogue {index} has an invalid end timestamp")
        if start_match and end_match:
            start_parts = [int(value) for value in start_match.groups()]
            end_parts = [int(value) for value in end_match.groups()]
            start_centiseconds = (
                start_parts[0] * 360_000
                + start_parts[1] * 6_000
                + start_parts[2] * 100
                + start_parts[3]
            )
            end_centiseconds = (
                end_parts[0] * 360_000
                + end_parts[1] * 6_000
                + end_parts[2] * 100
                + end_parts[3]
            )
            if end_centiseconds <= start_centiseconds:
                warnings.append(f"dialogue {index} does not end after it starts")
        if fields[9].count("{") != fields[9].count("}"):
            warnings.append(f"dialogue {index} has unbalanced override braces")
    if not styles:
        warnings.append("ASS contains no styles")
    if not dialogues:
        warnings.append("ASS contains no dialogue events")
    return {
        "ass_valid": not warnings,
        "styles_count": len(styles),
        "events_count": len(dialogues),
        "warnings": warnings,
    }


# -- FFmpeg command builder ---------------------------------------------------
def _escape_filter_path(path: str) -> str:
    """Escape a filesystem path for FFmpeg's filter parser."""

    # FFmpeg's filter parser treats backslashes as escapes, so Windows paths must
    # be normalized before escaping drive-letter colons.
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _face_interp_expr(keyframes: list[dict[str, Any]], field: str) -> str:
    points = [
        (_as_float(item.get("time")), _as_float(item.get(field), 0.5))
        for item in keyframes
        if isinstance(item, dict)
    ]
    points = sorted(points, key=lambda item: item[0])[:32]
    if not points:
        return "0.5"
    expr = f"{points[-1][1]:.6f}"
    for (t0, v0), (t1, v1) in reversed(list(pairwise(points))):
        if t1 <= t0:
            continue
        delta = v1 - v0
        segment = f"{v0:.6f}+({delta:.6f})*(t-{t0:.3f})/{(t1 - t0):.3f}"
        expr = f"if(between(t,{t0:.3f},{t1:.3f}),{segment},{expr})"
    if points[0][0] > 0:
        expr = f"if(lt(t,{points[0][0]:.3f}),{points[0][1]:.6f},{expr})"
    return expr


def _face_crop_filter(timeline: dict[str, Any], width: int, height: int) -> str | None:
    if not face_tracking_renderable(timeline):
        return None
    keyframes = [
        item
        for item in _as_list(face_tracking_plan(timeline).get("crop_keyframes"))
        if isinstance(item, dict)
    ]
    x_expr = _face_interp_expr(keyframes, "x_center")
    y_expr = _face_interp_expr(keyframes, "y_center")
    x = f"max(0,min(iw-ow,({x_expr})*iw-ow/2))"
    y = f"max(0,min(ih-oh,({y_expr})*ih-oh*0.43))"
    return f"crop={width}:{height}:x='{x}':y='{y}'"


def _speaker_region_crop_filter(region: dict[str, Any], width: int, height: int) -> str:
    keyframes = [
        item
        for item in _as_list(region.get("crop_keyframes"))
        if isinstance(item, dict)
    ]
    x_expr = _face_interp_expr(keyframes, "x_center")
    y_expr = _face_interp_expr(keyframes, "y_center")
    crop_width = "min(iw,ih*9/8)"
    crop_height = "min(ih,iw*8/9)"
    x = f"max(0,min(iw-ow,({x_expr})*iw-ow/2))"
    y = f"max(0,min(ih-oh,({y_expr})*ih-oh*0.43))"
    return (
        f"crop=w='{crop_width}':h='{crop_height}':x='{x}':y='{y}',"
        f"scale={width}:{height // 2}:force_original_aspect_ratio=disable,setsar=1"
    )


def _stack_post_filters(
    timeline: dict[str, Any],
    width: int,
    height: int,
    fps: int,
    caption_path: str | None,
) -> str:
    filters: list[str] = []
    has_zoom = bool(zoom_ops(timeline))
    if has_zoom:
        filters.append(
            f"zoompan=z='{_zoom_expression(timeline, fps)}':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={width}x{height}:fps={fps}"
        )
    filters.extend(video_enhancement_filters(timeline))
    if not has_zoom:
        filters.append(f"fps={max(1, int(fps))}")
    if caption_path:
        filters.append(f"subtitles='{_escape_filter_path(caption_path)}'")
    filters.append("format=yuv420p")
    return ",".join(filters)


def _stack_video_graph(
    timeline: dict[str, Any],
    width: int,
    height: int,
    fps: int,
    caption_path: str | None,
    start: float,
    end: float,
) -> list[str]:
    plan = face_tracking_plan(timeline)
    regions = [_as_dict(item) for item in _as_list(plan.get("layout_regions"))][:2]
    top_filter = _speaker_region_crop_filter(regions[0], width, height)
    bottom_filter = _speaker_region_crop_filter(regions[1], width, height)
    post = _stack_post_filters(timeline, width, height, fps, caption_path)
    return [
        f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[layout_base]",
        "[layout_base]split=2[top_source][bottom_source]",
        f"[top_source]{top_filter}[top_region]",
        f"[bottom_source]{bottom_filter}[bottom_region]",
        "[top_region][bottom_region]vstack=inputs=2[stacked_layout]",
        f"[stacked_layout]{post}[v]",
    ]


def video_filter(
    timeline: dict[str, Any],
    width: int,
    height: int,
    *,
    fps: int | float | None = None,
    srt_path: str | None = None,
) -> str:
    """Build the FFmpeg ``-vf`` filter chain that realises the timeline's reframe.

    Scales the source to cover the vertical target, center-crops to exactly
    WxH, applies a gentle global zoom when the timeline contains zoom moments,
    and burns captions from ``srt_path`` when provided. Deterministic and real.
    """

    face_crop = _face_crop_filter(timeline, width, height)
    filters = [f"scale={width}:{height}:force_original_aspect_ratio=increase"]
    filters.append(face_crop or f"crop={width}:{height}")
    has_zoom = bool(zoom_ops(timeline))
    if has_zoom:
        # Timed zoom expression from the Editing V2 motion plan.
        target_fps = max(1, int(fps or 30))
        filters.append(
            f"zoompan=z='{_zoom_expression(timeline, target_fps)}':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={width}x{height}:fps={target_fps}"
        )
    filters.extend(video_enhancement_filters(timeline))
    if fps and not has_zoom:
        filters.append(f"fps={max(1, int(fps))}")
    if srt_path:
        escaped = _escape_filter_path(srt_path)
        filters.append(f"subtitles='{escaped}'")
    filters.append("format=yuv420p")
    return ",".join(filters)


def _zoom_expression(timeline: dict[str, Any], fps: int) -> str:
    expr = "1.0"
    events = sorted(zoom_ops(timeline), key=lambda e: _as_float(e.get("at")))[:8]
    for event in reversed(events):
        start = max(0.0, _as_float(event.get("at")))
        end = _as_float(event.get("end"), start + 0.8)
        if end <= start:
            end = start + 0.8
        scale = event.get("scale")
        strength = _as_float(scale, 1.08)
        strength = max(1.0, min(strength, 1.2))
        span = max(0.05, end - start)
        progress = f"max(0,min(1,(on/{fps}-{start:.3f})/{span:.3f}))"
        easing = _as_str(event.get("easing"))
        if easing in {"slow_push", "payoff_hold"}:
            envelope = f"(0.5-0.5*cos(PI*{progress}))"
        else:
            envelope = f"sin(PI*{progress})"
        value = f"1+({strength - 1.0:.6f})*{envelope}"
        expr = f"if(between(on/{fps},{start:.3f},{end:.3f}),{value},{expr})"
    return expr


def video_enhancement_filters(timeline: dict[str, Any]) -> list[str]:
    meta = _as_dict(timeline.get("metadata"))
    editing = _as_dict(meta.get("editing_v2"))
    profile = _as_str(_as_dict(editing.get("video_enhancement_plan")).get("profile"))
    if "warm" in profile or "cinematic" in profile or "aura" in profile:
        return ["eq=contrast=1.08:saturation=1.10:brightness=0.012", "unsharp=5:5:0.55:3:3:0.25"]
    if "high_energy" in profile:
        return ["eq=contrast=1.09:saturation=1.14:brightness=0.01", "unsharp=5:5:0.65:3:3:0.30"]
    return ["eq=contrast=1.05:saturation=1.07:brightness=0.006", "unsharp=5:5:0.45:3:3:0.20"]


def voice_filter_chain() -> str:
    return (
        "highpass=f=80,lowpass=f=9000,afftdn=nf=-25,"
        "dynaudnorm=f=150:g=11,"
        "compand=attacks=0.03:decays=0.18:points=-80/-80|-35/-26|-12/-8|0/-1,"
        "alimiter=limit=0.95"
    )


def voice_timing_compensation_filter() -> str:
    """Advance speech by the deterministic latency measured in the voice chain."""

    return (
        f"asetpts=PTS-STARTPTS-{VOICE_PROCESSING_LATENCY_SECONDS:.3f}/TB,"
        "atrim=start=0,asetpts=PTS-STARTPTS,"
        "aresample=48000:async=1:first_pts=0"
    )


def _audio_filter_complex(
    timeline: dict[str, Any], duration: float, start: float, end: float
) -> tuple[list[str], list[str]]:
    assets = render_assets(timeline)
    music = _as_dict(assets.get("music"))
    sfx = _as_dict(assets.get("sfx"))
    voice_label = "voice"
    parts = [
        f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
        f"{voice_filter_chain()},{voice_timing_compensation_filter()},"
        f"apad,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[voice]"
    ]
    inputs = ["[voice]"]
    if music.get("mixed") and music.get("path"):
        mix_plan = _as_dict(music.get("mix_plan"))
        ducking = _as_dict(music.get("ducking_plan"))
        story_events = _as_dict(music.get("music_story_events"))
        fade_out = max(0.0, duration - _as_float(music.get("fade_out_s"), 0.8))
        gain = _as_float(music.get("gain_db"), -22.0)
        swell = _as_dict(story_events.get("payoff_event"))
        swell_filter = ""
        if swell.get("enabled") and swell.get("time") is not None:
            swell_start = max(0.0, _as_float(swell.get("time")))
            swell_end = min(duration, swell_start + 1.5)
            swell_factor = 10 ** (_as_float(swell.get("gain_change_db"), 1.5) / 20.0)
            swell_filter = (
                f",volume='if(between(t,{swell_start:.3f},{swell_end:.3f}),"
                f"{swell_factor:.6f},1)':eval=frame"
            )
        parts.append(
            f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume={gain:.1f}dB,"
            f"afade=t=in:st=0:d={_as_float(music.get('fade_in_s'), 0.25):.2f},"
            f"afade=t=out:st={fade_out:.3f}:d={_as_float(music.get('fade_out_s'), 0.8):.2f},"
            f"apad,atrim=0:{duration:.3f}{swell_filter},asetpts=PTS-STARTPTS"
            "[music_pre]"
        )
        if ducking.get("enabled"):
            threshold_db = _as_float(mix_plan.get("ducking_threshold"), -24.0)
            threshold = 10 ** (threshold_db / 20.0)
            ratio = max(1.0, _as_float(mix_plan.get("ducking_ratio"), 6.0))
            attack = max(1.0, _as_float(ducking.get("attack_ms"), 120.0))
            release = max(1.0, _as_float(ducking.get("release_ms"), 450.0))
            parts.append("[voice]asplit=2[voice_mix][voice_sc]")
            parts.append(
                f"[music_pre][voice_sc]sidechaincompress=threshold={threshold:.6f}:"
                f"ratio={ratio:.2f}:attack={attack:.1f}:release={release:.1f}[music]"
            )
            voice_label = "voice_mix"
        else:
            parts.append("[music_pre]anull[music]")
        inputs = [f"[{voice_label}]", "[music]"]
    sfx_start_index = 2 if music.get("mixed") and music.get("path") else 1
    mixed_sfx = [e for e in _as_list(sfx.get("events")) if _as_dict(e).get("mixed")]
    for offset, event in enumerate(mixed_sfx):
        item = _as_dict(event)
        delay_ms = max(0, round(_as_float(item.get("time")) * 1000))
        gain = _as_float(item.get("gain_db"), -15.0)
        label = f"sfx{offset}"
        parts.append(
            f"[{sfx_start_index + offset}:a]asetpts=PTS-STARTPTS,volume={gain:.1f}dB,"
            f"adelay={delay_ms}:all=1,apad,atrim=0:{duration:.3f},"
            f"asetpts=PTS-STARTPTS[{label}]"
        )
        inputs.append(f"[{label}]")
    mix = "".join(inputs)
    parts.append(
        f"{mix}amix=inputs={len(inputs)}:duration=first:normalize=0:dropout_transition=0,"
        f"aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11,"
        f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[a]"
    )
    return parts, inputs


def filter_complex(
    timeline: dict[str, Any],
    width: int,
    height: int,
    fps: int,
    caption_path: str | None,
) -> str:
    start, end = source_range(timeline)
    duration = expected_duration(timeline)
    if multi_speaker_stack_renderable(timeline):
        video_parts = _stack_video_graph(
            timeline,
            width,
            height,
            fps,
            caption_path,
            start,
            end,
        )
    else:
        video = video_filter(timeline, width, height, fps=fps, srt_path=caption_path)
        video_parts = [
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,{video}[v]"
        ]
    audio_parts, _ = _audio_filter_complex(timeline, duration, start, end)
    return ";".join([*video_parts, *audio_parts])


def extra_audio_inputs(timeline: dict[str, Any]) -> list[str]:
    args: list[str] = []
    assets = render_assets(timeline)
    music = _as_dict(assets.get("music"))
    if music.get("mixed") and music.get("path"):
        if music.get("looped"):
            args.extend(["-stream_loop", "-1"])
        args.extend(["-i", str(music["path"])])
    sfx = _as_dict(assets.get("sfx"))
    for event in _as_list(sfx.get("events")):
        item = _as_dict(event)
        if item.get("mixed") and item.get("path"):
            args.extend(["-i", str(item["path"])])
    return args


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
    encoder_preset: str = "medium",
    encoder_threads: int | None = None,
    filter_threads: int | None = None,
) -> list[str]:
    """Build the full FFmpeg argument vector to render one clip (real, runnable).

    Trims the source to the clip's source range, reframes to the vertical target,
    burns captions when present, and encodes H.264/AAC in MP4 at the requested
    bitrate/fps. This is exactly what the FFmpeg renderer executes.
    """

    if encoder_threads is not None and encoder_threads < 1:
        raise ValueError("encoder_threads must be at least 1 when configured.")
    if filter_threads is not None and filter_threads < 1:
        raise ValueError("filter_threads must be at least 1 when configured.")
    preset = encoder_preset.strip().lower()
    if preset not in {
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    }:
        raise ValueError(f"Unsupported libx264 encoder preset: {encoder_preset!r}.")

    args = [binary, "-hide_banner", "-nostats", "-loglevel", "warning", "-y"]
    if filter_threads is not None:
        args.extend(
            [
                "-filter_threads",
                str(filter_threads),
                "-filter_complex_threads",
                str(filter_threads),
            ]
        )
    args.extend(["-i", source_path])
    args.extend(extra_audio_inputs(timeline))
    args.extend(
        [
            "-filter_complex",
            filter_complex(timeline, width, height, fps, srt_path),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-b:v",
            f"{video_bitrate_kbps}k",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if encoder_threads is not None:
        args.extend(["-threads", str(encoder_threads)])
    args.extend(
        [
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-b:a",
            f"{audio_bitrate_kbps}k",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )
    return args


def build_ffprobe_command(*, binary: str, path: str) -> list[str]:
    """Build an ffprobe command that returns the encoded file's real metadata."""

    return [
        binary,
        "-v",
        "error",
        "-show_entries",
        "format=duration,start_time,bit_rate:stream=codec_type,codec_name,width,height,"
        "sample_rate,r_frame_rate,duration,start_time",
        "-of",
        "json",
        path,
    ]
