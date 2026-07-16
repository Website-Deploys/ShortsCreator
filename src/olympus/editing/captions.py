"""Caption Intelligence V2 planning, timing, placement, and readability truth."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from itertools import pairwise
from math import ceil
from typing import Any

from olympus.editing import timeline as T  # noqa: N812
from olympus.personalization import apply as P  # noqa: N812
from olympus.platform.config import get_settings

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_WORD_LEVEL_MAX_CPS = 30.0
_ESTIMATED_MAX_CPS = 23.0
_MAX_CHARACTERS_PER_LINE = 22
_MAX_CAPTION_CHARACTERS = _MAX_CHARACTERS_PER_LINE * 2
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "i",
        "if",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "this",
        "to",
        "was",
        "we",
        "with",
        "you",
    }
)
_FORBIDDEN_EMPHASIS = frozenset({"um", "uh", "like", "actually", "basically", "literally"})
_EMOTIONAL_WORDS = frozenset(
    {"afraid", "alone", "changed", "fear", "felt", "hope", "hurt", "love", "proud", "truth"}
)

STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "motivational_impact": {
        "typography_mood": "bold_confident",
        "font_size": 82,
        "hook_font_size": 96,
        "outline": 6,
        "shadow": 2,
        "primary": "&H00FFFFFF",
        "accent": "&H0030D5FF",
        "animation": "pop_in",
        "uppercase": True,
    },
    "clean_podcast": {
        "typography_mood": "clean_conversational",
        "font_size": 70,
        "hook_font_size": 80,
        "outline": 5,
        "shadow": 2,
        "primary": "&H00FFFFFF",
        "accent": "&H00FFD166",
        "animation": "phrase_reveal",
        "uppercase": False,
    },
    "educational_clear": {
        "typography_mood": "clear_authoritative",
        "font_size": 72,
        "hook_font_size": 84,
        "outline": 5,
        "shadow": 1,
        "primary": "&H00FFFFFF",
        "accent": "&H0032F4FF",
        "animation": "subtle_scale",
        "uppercase": False,
    },
    "emotional_soft": {
        "typography_mood": "restrained_emotional",
        "font_size": 68,
        "hook_font_size": 78,
        "outline": 4,
        "shadow": 2,
        "primary": "&H00FFFFFF",
        "accent": "&H00D8B4FE",
        "animation": "subtle_scale",
        "uppercase": False,
    },
    "gaming_energy": {
        "typography_mood": "high_energy_playful",
        "font_size": 80,
        "hook_font_size": 92,
        "outline": 6,
        "shadow": 2,
        "primary": "&H00FFFFFF",
        "accent": "&H004DFF88",
        "animation": "bounce_light",
        "uppercase": True,
    },
    "music_minimal": {
        "typography_mood": "minimal_performance_safe",
        "font_size": 62,
        "hook_font_size": 70,
        "outline": 4,
        "shadow": 1,
        "primary": "&H00FFFFFF",
        "accent": "&H00E5E7EB",
        "animation": "none",
        "uppercase": False,
    },
    "comedy_pop": {
        "typography_mood": "playful_precise",
        "font_size": 78,
        "hook_font_size": 90,
        "outline": 6,
        "shadow": 2,
        "primary": "&H00FFFFFF",
        "accent": "&H006BFFEA",
        "animation": "bounce_light",
        "uppercase": False,
    },
    "cinematic_quote": {
        "typography_mood": "cinematic_restrained",
        "font_size": 66,
        "hook_font_size": 76,
        "outline": 4,
        "shadow": 3,
        "primary": "&H00FFFFFF",
        "accent": "&H00E7D7C1",
        "animation": "quote_hold",
        "uppercase": False,
    },
    "bold_hook": {
        "typography_mood": "hook_first",
        "font_size": 86,
        "hook_font_size": 98,
        "outline": 6,
        "shadow": 2,
        "primary": "&H00FFFFFF",
        "accent": "&H0032F4FF",
        "animation": "pop_in",
        "uppercase": True,
    },
    "default_clean": {
        "typography_mood": "clean_mobile_readable",
        "font_size": 74,
        "hook_font_size": 86,
        "outline": 5,
        "shadow": 2,
        "primary": "&H00FFFFFF",
        "accent": "&H0032F4FF",
        "animation": "phrase_reveal",
        "uppercase": False,
    },
}


def _normalize_word(value: Any) -> str:
    match = _WORD_RE.findall(T.as_str(value).lower())
    return match[0] if match else ""


def _join_words(words: list[str]) -> str:
    text = " ".join(word.strip() for word in words if word.strip())
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def _valid_word_timings(segment: dict[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for raw in T.as_list(segment.get("words")):
        item = T.as_dict(raw)
        text = T.as_str(item.get("word")).strip()
        start = T.as_float(item.get("start"), -1.0)
        end = T.as_float(item.get("end"), -1.0)
        if text and start >= 0 and end > start:
            words.append(
                {
                    "word": text,
                    "start": T.round3(start),
                    "end": T.round3(end),
                    "confidence": item.get("confidence"),
                    "source_start": item.get("source_start"),
                    "source_end": item.get("source_end"),
                    "boundary_clipped": item.get("boundary_clipped") is True,
                }
            )
    return words


def caption_chunks_for_segment(
    segment: dict[str, Any], *, max_words_per_line: int | None = None
) -> list[dict[str, Any]]:
    """Create compact caption units while preserving genuine word timing when present."""

    settings = get_settings().caption_intelligence
    max_words = max(1, max_words_per_line or settings.max_words_per_line)
    max_caption_words = max_words * max(1, settings.max_lines)
    all_words = _valid_word_timings(segment)
    clipped_count = sum(word.get("boundary_clipped") is True for word in all_words)
    words = [word for word in all_words if word.get("boundary_clipped") is not True]
    chunk_warnings = (
        [
            f"Skipped {clipped_count} transcript word(s) clipped by the selected clip boundary."
        ]
        if clipped_count
        else []
    )
    speaker = T.as_str(segment.get("speaker")) or None
    if all_words and not words:
        return [
            {
                "text": "",
                "segment_start": segment.get("start"),
                "segment_end": segment.get("end"),
                "speaker": speaker,
                "word_timings": [],
                "timing_source": "word_level",
                "timing_quality": "boundary_clipped",
                "skip": True,
                "warnings": chunk_warnings,
            }
        ]
    if settings.prefer_word_level and words:
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for word in words:
            candidate = [*current, word]
            candidate_text = _join_words(
                [T.as_str(candidate_word.get("word")) for candidate_word in candidate]
            )
            if current and (
                len(candidate) > max_caption_words
                or len(candidate_text) > _MAX_CAPTION_CHARACTERS
            ):
                groups.append(current)
                current = [word]
            else:
                current = candidate
            current_text = _join_words(
                [T.as_str(current_word.get("word")) for current_word in current]
            )
            current_duration = T.as_float(current[-1].get("end")) - T.as_float(
                current[0].get("start")
            )
            readable = (
                len(current_text) / max(current_duration, 0.001) <= _WORD_LEVEL_MAX_CPS
            )
            punctuation_break = T.as_str(word.get("word")).rstrip().endswith(
                (".", "?", "!", ",", ";")
            )
            at_capacity = len(current) >= max_caption_words
            readable_break = readable and (
                len(current) >= max_words or (len(current) >= 2 and punctuation_break)
            )
            if at_capacity or readable_break:
                groups.append(current)
                current = []
        if current:
            merged_tail = [*groups[-1], *current] if groups else []
            merged_text = _join_words(
                [T.as_str(tail_word.get("word")) for tail_word in merged_tail]
            )
            merged_duration = (
                T.as_float(merged_tail[-1].get("end"))
                - T.as_float(merged_tail[0].get("start"))
                if merged_tail
                else 0.0
            )
            if (
                groups
                and len(current) == 1
                and len(merged_tail) <= max_caption_words
                and len(merged_text) <= _MAX_CAPTION_CHARACTERS
                and merged_duration <= settings.max_display_time_seconds
                and len(merged_text) / max(merged_duration, 0.001)
                <= _WORD_LEVEL_MAX_CPS
            ):
                groups[-1] = merged_tail
            else:
                groups.append(current)
        chunks = [
            {
                "text": _join_words([T.as_str(word.get("word")) for word in group]),
                "segment_start": segment.get("start"),
                "segment_end": segment.get("end"),
                "speaker": speaker,
                "word_timings": group,
                "timing_source": "word_level",
                "timing_quality": "word_level",
                "warnings": chunk_warnings if index == 0 else [],
            }
            for index, group in enumerate(groups)
            if group
        ]
        return chunks

    fallback_text = (
        _join_words([T.as_str(word.get("word")) for word in words])
        if all_words
        else T.as_str(segment.get("text"))
    )
    estimated_chunks = T.split_caption(fallback_text, max_words=max_words)
    quality = "phrase_level" if len(estimated_chunks) > 1 else "segment_level"
    return [
        {
            "text": text,
            "segment_start": segment.get("start"),
            "segment_end": segment.get("end"),
            "speaker": speaker,
            "word_timings": [],
            "timing_source": "estimated",
            "timing_quality": quality,
            "warnings": chunk_warnings if index == 0 else [],
        }
        for index, text in enumerate(estimated_chunks)
    ]


def _characters_per_second(event: dict[str, Any]) -> float:
    duration = T.as_float(event.get("end")) - T.as_float(event.get("start"))
    return len(T.as_str(event.get("text"))) / max(duration, 0.001)


def _caption_speed_limit(event: dict[str, Any]) -> float:
    return (
        _WORD_LEVEL_MAX_CPS
        if event.get("timing_source") == "word_level"
        else _ESTIMATED_MAX_CPS
    )


def _combine_adjacent_events(
    first: dict[str, Any], second: dict[str, Any]
) -> dict[str, Any] | None:
    settings = get_settings().caption_intelligence
    gap = T.as_float(second.get("start")) - T.as_float(first.get("end"))
    if not (
        T.as_str(first.get("timing_source")) == T.as_str(second.get("timing_source"))
        and first.get("speaker") == second.get("speaker")
        and 0.0 <= gap <= 0.35
    ):
        return None
    combined_words = _WORD_RE.findall(
        f"{T.as_str(first.get('text'))} {T.as_str(second.get('text'))}"
    )
    combined_start = T.as_float(first.get("start"))
    combined_end = T.as_float(second.get("end"))
    combined_duration = combined_end - combined_start
    if (
        len(combined_words) > settings.max_words_per_line * settings.max_lines
        or combined_duration > settings.max_display_time_seconds
    ):
        return None
    combined_text = _join_words(
        [T.as_str(first.get("text")), T.as_str(second.get("text"))]
    )
    combined = dict(first)
    combined.update(
        {
            "id": f"caption_{T.ms(combined_start)}_{T.ms(combined_end)}",
            "end": T.round3(combined_end),
            "duration": T.round3(combined_duration),
            "text": combined_text,
            "word_timings": [
                *T.as_list(first.get("word_timings")),
                *T.as_list(second.get("word_timings")),
            ],
            "reason": "adjacent dense transcript bursts merged for two-line readability",
            "readability": T.caption_readability(
                combined_text, combined_start, combined_end
            ),
        }
    )
    return combined


def _split_word_level_event_for_visual_width(
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    words = _valid_word_timings({"words": event.get("word_timings")})
    if len(T.as_str(event.get("text"))) <= _MAX_CAPTION_CHARACTERS or not words:
        return [event]
    settings = get_settings().caption_intelligence
    max_words = settings.max_words_per_line * settings.max_lines
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        candidate = [*current, word]
        candidate_text = _join_words(
            [T.as_str(candidate_word.get("word")) for candidate_word in candidate]
        )
        if current and (
            len(candidate) > max_words or len(candidate_text) > _MAX_CAPTION_CHARACTERS
        ):
            groups.append(current)
            current = [word]
        else:
            current = candidate
    if current:
        groups.append(current)
    split_events: list[dict[str, Any]] = []
    for group in groups:
        start = T.as_float(group[0].get("start"))
        end = T.as_float(group[-1].get("end"))
        text = _join_words([T.as_str(word.get("word")) for word in group])
        split_event = dict(event)
        split_event.update(
            {
                "id": f"caption_{T.ms(start)}_{T.ms(end)}",
                "start": T.round3(start),
                "end": T.round3(end),
                "duration": T.round3(end - start),
                "text": text,
                "word_timings": group,
                "reason": "dense transcript run rebalanced for visual two-line readability",
                "readability": T.caption_readability(text, start, end),
            }
        )
        split_events.append(split_event)
    return split_events


def _merge_fast_adjacent_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge dense runs, including bursts that need more than one look-ahead event."""

    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(events):
        current = dict(events[index])
        current_parts = [current]
        speed_limit = _caption_speed_limit(current)
        if _characters_per_second(current) > speed_limit:
            candidate = current
            look_ahead = index + 1
            while look_ahead < len(events):
                combined = _combine_adjacent_events(candidate, events[look_ahead])
                if combined is None:
                    break
                candidate = combined
                if _characters_per_second(candidate) <= speed_limit:
                    candidate_parts = _split_word_level_event_for_visual_width(candidate)
                    if all(
                        _characters_per_second(part) <= speed_limit
                        for part in candidate_parts
                    ):
                        current_parts = candidate_parts
                        index = look_ahead
                        break
                look_ahead += 1
        if len(current_parts) > 1:
            merged.extend(current_parts)
            index += 1
            continue
        current = current_parts[0]
        if _characters_per_second(current) > speed_limit and merged:
            combined = _combine_adjacent_events(merged[-1], current)
            if combined is not None and _characters_per_second(combined) <= speed_limit:
                candidate_parts = _split_word_level_event_for_visual_width(combined)
                if all(
                    _characters_per_second(part) <= speed_limit for part in candidate_parts
                ):
                    merged[-1:] = candidate_parts
                    index += 1
                    continue
        merged.append(current)
        index += 1
    return merged


def timed_caption_events(
    chunks: list[dict[str, Any]], clip_duration: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn caption units into clip-relative events and mark estimated timing honestly."""

    settings = get_settings().caption_intelligence
    by_segment: dict[int, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    for chunk in chunks:
        warnings.extend(T.as_str(item) for item in T.as_list(chunk.get("warnings")) if item)
        if chunk.get("skip") is True:
            continue
        by_segment.setdefault(int(T.as_float(chunk.get("segment_index"))), []).append(chunk)
    events: list[dict[str, Any]] = []
    for group in by_segment.values():
        if not group:
            continue
        has_word_timing = all(
            _valid_word_timings({"words": item.get("word_timings")}) for item in group
        )
        if has_word_timing:
            timed_group = [
                {
                    "text": T.as_str(item.get("text")),
                    "start": T.as_float(T.as_list(item.get("word_timings"))[0].get("start")),
                    "end": T.as_float(T.as_list(item.get("word_timings"))[-1].get("end")),
                    "chunk": item,
                }
                for item in group
            ]
        elif settings.allow_estimated_word_timing:
            start = T.as_float(group[0].get("segment_start"))
            end = T.as_float(group[0].get("segment_end"))
            distributed = T.distribute_timing(
                [T.as_str(item.get("text")) for item in group], start, end
            )
            timed_group = [
                {**timed, "chunk": chunk}
                for timed, chunk in zip(distributed, group, strict=True)
            ]
        else:
            warnings.append(
                "Estimated timing was disabled; untimed transcript captions were skipped."
            )
            continue
        for timed in timed_group:
            chunk = T.as_dict(timed.get("chunk"))
            start = max(0.0, T.as_float(timed.get("start")))
            available_duration = max(0.0, clip_duration - start)
            if available_duration < settings.min_display_time_seconds - 0.001:
                warnings.append(
                    f"Caption at {start:.3f}s had only {available_duration:.3f}s before "
                    "the clip boundary and was skipped."
                )
                continue
            raw_end = min(clip_duration, T.as_float(timed.get("end")))
            end = min(
                clip_duration,
                start + settings.max_display_time_seconds,
                max(raw_end, start + settings.min_display_time_seconds),
            )
            if end <= start:
                warnings.append(
                    f"Caption at {start:.3f}s had no valid display interval and was skipped."
                )
                continue
            text = T.as_str(timed.get("text")).strip()
            if not text:
                continue
            timing_source = T.as_str(chunk.get("timing_source")) or "estimated"
            events.append(
                T.event(
                    "caption",
                    start,
                    end,
                    reason=(
                        "caption uses transcription word timestamps"
                        if timing_source == "word_level"
                        else "caption timing estimated within its transcript segment"
                    ),
                    confidence=0.94 if timing_source == "word_level" else 0.68,
                    evidence=[{"type": "transcript", "detail": text[:80]}],
                    text=text,
                    speaker=chunk.get("speaker"),
                    word_timings=T.as_list(chunk.get("word_timings")),
                    timing_source=timing_source,
                    timing_quality=T.as_str(chunk.get("timing_quality")) or "segment_level",
                    estimated=timing_source != "word_level",
                    highlighted_words=[],
                    style="default_clean",
                    animation="phrase_reveal",
                    readability=T.caption_readability(text, start, end),
                )
            )
    events.sort(key=lambda item: T.as_float(item.get("start")))
    events = _merge_fast_adjacent_events(events)
    for current, following in pairwise(events):
        if T.as_float(current.get("end")) > T.as_float(following.get("start")):
            current["end"] = T.round3(
                max(
                    T.as_float(current.get("start")),
                    T.as_float(following.get("start")),
                )
            )
            current["duration"] = T.round3(
                T.as_float(current.get("end")) - T.as_float(current.get("start"))
            )
            current["readability"] = T.caption_readability(
                T.as_str(current.get("text")),
                T.as_float(current.get("start")),
                T.as_float(current.get("end")),
            )
    estimated_count = sum(item.get("estimated") is True for item in events)
    word_count = sum(len(_WORD_RE.findall(T.as_str(item.get("text")))) for item in events)
    if estimated_count:
        warnings.append(
            "Word timestamps were unavailable for some captions; proportional timing is estimated."
        )
    source = (
        "unavailable"
        if not events
        else "word_level"
        if estimated_count == 0
        else "estimated"
    )
    qualities = {T.as_str(item.get("timing_quality")) for item in events}
    return events, {
        "source": source,
        "estimated": bool(estimated_count),
        "confidence": 0.94 if source == "word_level" else 0.68 if events else 0.0,
        "quality_level": next(iter(qualities)) if len(qualities) == 1 else "mixed",
        "words_total": word_count,
        "caption_events_total": len(events),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _style_for(blueprint: dict[str, Any]) -> tuple[str, str]:
    settings = get_settings().caption_intelligence
    niche = T.as_str(T.as_dict(blueprint.get("content_niche")).get("primary"))
    metadata = T.as_dict(blueprint.get("v2_metadata"))
    category = T.as_str(metadata.get("content_category"))
    planned = T.as_str(T.as_dict(blueprint.get("caption_decision_v2")).get("style"))
    trend = T.as_str(T.as_dict(blueprint.get("editing_trend_guidance")).get("caption_style"))
    for source, candidate in (("planning", planned), ("trend", trend)):
        if candidate in STYLE_PRESETS:
            return candidate, f"caption preset follows exact {source} guidance: {candidate}"
    signal = " ".join((niche, category, planned, trend)).lower()
    mappings = (
        (("motivation", "inspiration"), "motivational_impact"),
        (("podcast", "interview", "talking", "business"), "clean_podcast"),
        (("education", "tutorial", "explainer"), "educational_clear"),
        (("gaming", "stream", "reaction"), "gaming_energy"),
        (("music", "singing", "performance"), "music_minimal"),
        (("emotional", "confession", "vulnerable"), "emotional_soft"),
        (("comedy", "funny", "humor"), "comedy_pop"),
    )
    for tokens, style in mappings:
        if any(token in signal for token in tokens):
            return style, f"caption preset follows upstream niche/category signal: {signal.strip()}"
    return settings.default_style, "caption preset uses the configured clean fallback"


def _speaker_plan(
    events: list[dict[str, Any]], face_plan: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    settings = get_settings().caption_intelligence
    speakers = sorted(
        {
            T.as_str(event.get("speaker"))
            for event in events
            if T.as_str(event.get("speaker"))
        }
    )
    neutral = {speaker: f"Speaker {index + 1}" for index, speaker in enumerate(speakers)}
    track_roles = {
        T.as_str(region.get("source_face_track_id")): T.as_str(region.get("role"))
        for region in T.as_list(face_plan.get("layout_regions"))
        if T.as_str(T.as_dict(region).get("source_face_track_id"))
    }
    speaker_roles: dict[str, str] = {}
    confidences: list[float] = []
    for participant in T.as_list(face_plan.get("participants")):
        item = T.as_dict(participant)
        speaker = T.as_str(item.get("speaker_id"))
        role = track_roles.get(T.as_str(item.get("face_track_id")))
        confidence = T.as_float(item.get("association_confidence"))
        if speaker and role in {"top", "bottom"} and confidence >= 0.6:
            speaker_roles[speaker] = role
            confidences.append(confidence)
    enabled = bool(
        settings.enable_speaker_aware_captions
        and speakers
        and speaker_roles
        and T.as_str(face_plan.get("mode")) == "two_speaker_stack"
    )
    return {
        "enabled": enabled,
        "speaker_labels_used": [neutral[speaker] for speaker in speakers] if enabled else [],
        "association_confidence": T.round3(sum(confidences) / len(confidences))
        if confidences
        else None,
        "placement_strategy": "speaker_half_safe" if enabled else "shared_safe_position",
        "fallback_reason": None
        if enabled
        else "speaker-to-face region association unavailable"
        if speakers
        else "speaker labels unavailable",
    }, speaker_roles


def _safe_zone(face_plan: dict[str, Any], speaker_aware: bool) -> dict[str, Any]:
    settings = get_settings().caption_intelligence
    mode = T.as_str(face_plan.get("mode")) or "center_fallback"
    keyframes = [T.as_dict(item) for item in T.as_list(face_plan.get("crop_keyframes"))]
    mean_y = (
        sum(T.as_float(item.get("y_center"), 0.46) for item in keyframes) / len(keyframes)
        if keyframes
        else None
    )
    if mode == "two_speaker_stack":
        strategy = "speaker_aware_regions" if speaker_aware else "center_divider_safe"
        chosen = "speaker_aware" if speaker_aware else "mid_lower"
        layout_mode = "speaker_aware" if speaker_aware else "two_speaker_stack_safe"
        alignment, margin_v = 5, 0
        collision = "low" if face_plan.get("layout_regions") else "unknown"
    elif mode in {"single_face_tracking", "active_speaker_focus"} and mean_y is not None:
        chosen = "top_safe" if mean_y >= 0.58 else "bottom_center"
        strategy = "tracked_face_opposite_zone"
        layout_mode = "face_avoidant"
        alignment, margin_v = (8, 230) if chosen == "top_safe" else (2, 260)
        collision = "low"
    elif mode in {"multi_face_safe_frame", "natural_frame_preserved"}:
        chosen = "top_safe" if mean_y is not None and mean_y >= 0.55 else "mid_lower"
        strategy = "multi_face_group_safe"
        layout_mode = "top_safe" if chosen == "top_safe" else "mid_lower"
        alignment, margin_v = (8, 230) if chosen == "top_safe" else (2, 500)
        collision = "medium"
    else:
        strategy = "platform_safe_fallback"
        chosen = "bottom_center"
        layout_mode = "bottom_center"
        alignment, margin_v = 2, 260
        collision = "unknown"
    face_used = bool(
        settings.enable_face_avoidance
        and mode != "center_fallback"
        and (keyframes or face_plan.get("layout_regions"))
    )
    warnings = []
    if not face_used:
        warnings.append(
            "Face-aware caption placement was unavailable; platform-safe fallback used."
        )
    return {
        "strategy": strategy,
        "chosen_position": chosen,
        "layout_mode": layout_mode,
        "alignment": alignment,
        "margin_v": margin_v,
        "face_avoidance_used": face_used,
        "layout_aware": mode != "center_fallback",
        "collision_risk": collision,
        "fallback_used": not face_used,
        "warnings": warnings,
    }


def _candidate_emphasis(
    events: list[dict[str, Any]], blueprint: dict[str, Any]
) -> dict[str, Any]:
    spoken: dict[str, str] = {}
    for event in events:
        for raw in _WORD_RE.findall(T.as_str(event.get("text"))):
            spoken.setdefault(raw.lower(), raw)
    hook = T.as_dict(blueprint.get("hook_v2"))
    story = T.as_dict(blueprint.get("story_v2_guidance"))
    story_editing = T.as_dict(story.get("editing_guidance"))
    editing = T.as_dict(blueprint.get("editing_guidance_v2"))
    ending = T.as_dict(blueprint.get("ending_payoff_v2"))
    explicit_values: list[Any] = [
        *T.as_list(story_editing.get("caption_emphasis_words")),
        *T.as_list(editing.get("caption_emphasis_words")),
        T.as_dict(editing.get("first_3_seconds")).get("highlight_word"),
    ]
    explicit = [
        normalized
        for value in explicit_values
        if (normalized := _normalize_word(value)) in spoken
        and normalized not in _FORBIDDEN_EMPHASIS
    ]
    hook_text = T.as_str(
        hook.get("hook_line") or hook.get("caption_hook_text") or hook.get("overlay_text")
    )
    hook_highlights = [
        word for word in T.highlight_words(hook_text) if word in spoken
    ]
    hook_candidates = [
        word
        for word in _WORD_RE.findall(hook_text.lower())
        if word in spoken and word not in _STOP_WORDS and word not in _FORBIDDEN_EMPHASIS
    ]
    hook_words = list(
        dict.fromkeys([*explicit, *hook_highlights, *hook_candidates])
    )[:3]
    payoff_text = T.as_str(ending.get("ending_line") or story.get("payoff"))
    payoff_highlights = [
        word for word in T.highlight_words(payoff_text) if word in spoken
    ]
    payoff_candidates = [
        word
        for word in _WORD_RE.findall(payoff_text.lower())
        if word in spoken and word not in _STOP_WORDS and word not in _FORBIDDEN_EMPHASIS
    ]
    payoff_words = list(dict.fromkeys([*payoff_highlights, *payoff_candidates]))[-3:]
    emotional = [word for word in spoken if word in _EMOTIONAL_WORDS]
    automatic = [
        word
        for event in events
        for word in T.highlight_words(T.as_str(event.get("text")))
    ]
    keywords = list(dict.fromkeys([*explicit, *automatic, *hook_words, *payoff_words, *emotional]))
    return {
        "explicit_words": explicit,
        "hook_words": hook_words,
        "keyword_highlights": keywords[:12],
        "emotional_words": emotional[:6],
        "payoff_words": payoff_words,
        "forbidden_overemphasis": sorted(_FORBIDDEN_EMPHASIS),
        "reason": "only upstream-guided words present in the spoken caption text are eligible",
    }


def _style_definitions(
    style_name: str, safe_zone: dict[str, Any], font_name: str
) -> list[dict[str, Any]]:
    preset = STYLE_PRESETS.get(style_name, STYLE_PRESETS["default_clean"])
    alignment = int(safe_zone.get("alignment") or 2)
    margin_v = int(safe_zone.get("margin_v") or 260)

    def style(
        name: str,
        font_size: int,
        *,
        accent: bool = False,
        style_alignment: int | None = None,
        style_margin_v: int | None = None,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "font_family": font_name,
            "font_size": font_size,
            "primary_color": preset["accent"] if accent else preset["primary"],
            "secondary_color": preset["accent"],
            "outline_color": "&H00101010",
            "back_color": "&H70000000",
            "bold": True,
            "outline": preset["outline"],
            "shadow": preset["shadow"],
            "alignment": style_alignment or alignment,
            "margin_l": 72,
            "margin_r": 72,
            "margin_v": style_margin_v if style_margin_v is not None else margin_v,
        }

    return [
        style("Normal", int(preset["font_size"])),
        style("Hook", int(preset["hook_font_size"]), accent=False),
        style("Emphasis", int(preset["font_size"]) + 4, accent=True),
        style("Quote", max(58, int(preset["font_size"]) - 4)),
        style(
            "SpeakerTop",
            max(58, int(preset["font_size"]) - 8),
            style_alignment=8,
            style_margin_v=650,
        ),
        style(
            "SpeakerBottom",
            max(58, int(preset["font_size"]) - 8),
            style_alignment=2,
            style_margin_v=250,
        ),
    ]


def validate_readability(
    events: list[dict[str, Any]], safe_zone: dict[str, Any], style_names: set[str]
) -> dict[str, Any]:
    settings = get_settings().caption_intelligence
    reading: list[str] = []
    lines: list[str] = []
    overlaps: list[str] = []
    timing: list[str] = []
    safe: list[str] = list(safe_zone.get("warnings") or [])
    warnings: list[str] = []
    errors: list[str] = []
    event_readability: list[dict[str, Any]] = []
    for event in events:
        text = T.as_str(event.get("text")).strip()
        start = T.as_float(event.get("start"))
        end = T.as_float(event.get("end"))
        duration = end - start
        words = _WORD_RE.findall(text)
        event_warnings: list[str] = []
        if not text:
            message = "empty caption event"
            timing.append(message)
            errors.append(message)
            event_warnings.append(message)
        if start < 0 or end <= start:
            message = f"invalid caption timestamp at {start:.3f}s"
            timing.append(message)
            errors.append(message)
            event_warnings.append(message)
        if duration < settings.min_display_time_seconds - 0.001:
            message = f"caption at {start:.3f}s displays for only {duration:.3f}s"
            timing.append(message)
            event_warnings.append(message)
        if duration > settings.max_display_time_seconds + 0.001:
            message = f"caption at {start:.3f}s exceeds maximum display time"
            timing.append(message)
            event_warnings.append(message)
        line_count = max(
            1,
            ceil(len(words) / settings.max_words_per_line),
            ceil(len(text) / _MAX_CHARACTERS_PER_LINE),
        )
        if line_count > settings.max_lines:
            message = f"caption at {start:.3f}s requires {line_count} lines"
            lines.append(message)
            event_warnings.append(message)
        cps = len(text) / max(duration, 0.001)
        words_per_second = len(words) / max(duration, 0.001)
        speed_limit = _caption_speed_limit(event)
        if cps > speed_limit:
            message = f"caption at {start:.3f}s reads at {cps:.1f} characters/second"
            reading.append(message)
            event_warnings.append(message)
        if T.as_str(event.get("ass_style")) not in style_names:
            message = f"caption at {start:.3f}s references an undefined ASS style"
            warnings.append(message)
            errors.append(message)
            event_warnings.append(message)
        caption_words = {_normalize_word(word) for word in words}
        for highlighted in T.as_list(event.get("highlighted_words")):
            if _normalize_word(highlighted) not in caption_words:
                message = f"highlight word {highlighted!r} is absent from its caption"
                warnings.append(message)
                event_warnings.append(message)
        event_readability.append(
            {
                "event_id": event.get("id"),
                "start": T.round3(start),
                "end": T.round3(end),
                "duration": T.round3(duration),
                "text": text,
                "word_count": len(words),
                "line_count": line_count,
                "words_per_second": T.round3(words_per_second),
                "characters_per_second": T.round3(cps),
                "speed_limit_characters_per_second": speed_limit,
                "timing_source": T.as_str(event.get("timing_source")) or "unknown",
                "passed": not event_warnings,
                "warnings": event_warnings,
            }
        )
    for first, second in pairwise(sorted(events, key=lambda item: T.as_float(item.get("start")))):
        if T.as_float(first.get("end")) > T.as_float(second.get("start")) + 0.01:
            overlaps.append(
                f"captions overlap at {T.as_float(second.get('start')):.3f}s without intent"
            )
    if not safe_zone.get("strategy"):
        safe.append("caption safe-zone strategy is missing")
    all_warnings = [*reading, *lines, *overlaps, *timing, *safe, *warnings]
    safe_zone_passed = bool(safe_zone.get("strategy")) or not settings.enable_safe_zone_validation
    passed = not (reading or lines or overlaps or timing or warnings) and safe_zone_passed
    observed_durations = [
        T.as_float(item.get("duration"))
        for item in event_readability
        if T.as_float(item.get("duration")) > 0
    ]
    timing_sources = {
        T.as_str(item.get("timing_source"))
        for item in event_readability
        if T.as_str(item.get("timing_source"))
    }
    return {
        "version": "2",
        "passed": passed,
        "blocking": bool(errors),
        "severity": "error" if errors else "warning" if not passed else "ok",
        "errors": list(dict.fromkeys(errors)),
        "timing_source": next(iter(timing_sources)) if len(timing_sources) == 1 else "mixed"
        if timing_sources
        else "unavailable",
        "event_count": len(event_readability),
        "failed_event_count": sum(item.get("passed") is False for item in event_readability),
        "max_words_per_caption": settings.max_words_per_line * settings.max_lines,
        "max_characters_per_line": _MAX_CHARACTERS_PER_LINE,
        "max_characters_per_caption": _MAX_CAPTION_CHARACTERS,
        "max_lines": settings.max_lines,
        "max_words_per_second": max(
            (T.as_float(item.get("words_per_second")) for item in event_readability),
            default=0.0,
        ),
        "max_chars_per_second": max(
            (T.as_float(item.get("characters_per_second")) for item in event_readability),
            default=0.0,
        ),
        "min_caption_duration": min(observed_durations) if observed_durations else None,
        "dense_event_count": len(reading),
        "overlap_count": len(overlaps),
        "safe_zone_passed": safe_zone_passed,
        "source_subtitle_collision_risk": safe_zone.get(
            "source_subtitle_collision_risk"
        )
        or safe_zone.get("collision_risk")
        or "unknown",
        "limits": {
            "word_level_max_characters_per_second": _WORD_LEVEL_MAX_CPS,
            "estimated_max_characters_per_second": _ESTIMATED_MAX_CPS,
            "min_display_time_seconds": settings.min_display_time_seconds,
            "max_display_time_seconds": settings.max_display_time_seconds,
            "max_words_per_line": settings.max_words_per_line,
            "max_characters_per_line": _MAX_CHARACTERS_PER_LINE,
            "max_lines": settings.max_lines,
        },
        "caption_event_readability": event_readability,
        "reading_speed_warnings": reading,
        "line_length_warnings": lines,
        "overlap_warnings": overlaps,
        "timing_warnings": timing,
        "safe_zone_warnings": safe,
        "warnings": list(dict.fromkeys(all_warnings)),
    }


def build_caption_intelligence(
    *,
    clip: dict[str, Any],
    events: list[dict[str, Any]],
    timing_quality: dict[str, Any],
    blueprint: dict[str, Any],
    face_plan: dict[str, Any],
    project_id: str | None,
    captions_enabled: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the canonical contract and decorate the exact events the renderer consumes."""

    settings = get_settings().caption_intelligence
    fonts = get_settings().caption_fonts
    caption_decision = T.as_dict(blueprint.get("caption_decision_v2"))
    enabled = bool(
        settings.enabled
        and captions_enabled
        and caption_decision.get("status") != "disabled"
    )
    working = [dict(event) for event in events] if enabled else []
    style_name, style_reason = _style_for(blueprint)
    personalization_settings = get_settings().creator_personalization
    caption_directives = (
        T.as_dict(blueprint.get("personalization_directives_v2")) or None
        if personalization_settings.apply_to_captions
        else None
    )
    caption_personalization = P.caption_personalization(
        caption_directives,
        default_style=style_name,
        default_max_words=settings.max_words_per_line,
    )
    personalized_style = T.as_str(caption_personalization.get("style"))
    if personalized_style in STYLE_PRESETS:
        style_name = personalized_style
        if caption_personalization.get("applied"):
            style_reason = f"{style_reason}; adjusted by the active creator profile"
    elif personalized_style:
        caption_personalization["warnings"] = list(
            dict.fromkeys(
                [
                    *T.as_list(caption_personalization.get("warnings")),
                    f"Unknown caption style '{personalized_style}' was ignored.",
                ]
            )
        )
    preset = STYLE_PRESETS.get(style_name, STYLE_PRESETS["default_clean"])
    speaker_captioning, speaker_roles = _speaker_plan(working, face_plan)
    safe_zone = _safe_zone(face_plan, speaker_captioning["enabled"] is True)
    emphasis = _candidate_emphasis(working, blueprint)
    styles = _style_definitions(style_name, safe_zone, fonts.primary)
    style_names = {T.as_str(item.get("name")) for item in styles}
    hook = T.as_dict(blueprint.get("hook_v2"))
    hook_category = T.as_str(hook.get("category"))
    hook_events = 0
    emphasis_events = 0
    speaker_events = 0
    quote_events = 0
    highlight_density = T.as_float(caption_personalization.get("highlight_density"), 0.4)
    highlight_limit = (
        0
        if highlight_density <= 0.05
        else 1
        if highlight_density <= 0.4
        else 2
        if highlight_density <= 0.7
        else 3
    )
    casing = T.as_str(caption_personalization.get("casing")) or "natural"
    last_index = len(working) - 1
    neutral_labels = {
        speaker: f"Speaker {index + 1}"
        for index, speaker in enumerate(
            sorted(
                {
                    T.as_str(event.get("speaker"))
                    for event in working
                    if T.as_str(event.get("speaker"))
                }
            )
        )
    }
    for index, event in enumerate(working):
        text_words = {_normalize_word(word) for word in T.as_str(event.get("text")).split()}
        start = T.as_float(event.get("start"))
        is_hook = bool(settings.enable_hook_treatment and index == 0 and start <= 3.0)
        is_quote = bool(index == last_index and set(emphasis["payoff_words"]) & text_words)
        candidates = (
            [*emphasis["hook_words"], *emphasis["keyword_highlights"]]
            if is_hook
            else [
                *emphasis["explicit_words"],
                *emphasis["payoff_words"],
                *emphasis["keyword_highlights"],
            ]
            if is_quote
            else list(emphasis["keyword_highlights"])
        )
        highlighted = [word for word in dict.fromkeys(candidates) if word in text_words][
            : min(highlight_limit, 1 if len(text_words) <= 3 else 3)
        ]
        speaker = T.as_str(event.get("speaker"))
        role = speaker_roles.get(speaker)
        if speaker_captioning["enabled"] and role:
            ass_style = "SpeakerTop" if role == "top" else "SpeakerBottom"
            speaker_events += 1
        elif is_hook:
            ass_style = "Hook"
            hook_events += 1
        elif is_quote:
            ass_style = "Quote"
            quote_events += 1
        else:
            ass_style = "Normal"
        if is_hook:
            animation = "subtle_scale" if style_name == "emotional_soft" else "pop_in"
        elif is_quote:
            animation = "quote_hold"
        elif event.get("timing_source") == "word_level" and style_name in {
            "motivational_impact",
            "gaming_energy",
            "comedy_pop",
            "bold_hook",
        }:
            animation = "karaoke_word"
        else:
            animation = T.as_str(preset.get("animation"))
        event.update(
            {
                "style": style_name,
                "ass_style": ass_style,
                "animation": animation,
                "highlighted_words": highlighted if settings.enable_keyword_emphasis else [],
                "speaker_label": neutral_labels.get(speaker),
                "caption_position": safe_zone["chosen_position"],
                "uppercase": casing == "uppercase"
                or (casing == "natural" and bool(preset.get("uppercase"))),
                "hook_caption": is_hook,
                "payoff_caption": is_quote,
                "readability": T.caption_readability(
                    T.as_str(event.get("text")),
                    T.as_float(event.get("start")),
                    T.as_float(event.get("end")),
                ),
            }
        )
        if event["highlighted_words"]:
            emphasis_events += 1
    readability = validate_readability(working, safe_zone, style_names)
    words_total = sum(len(_WORD_RE.findall(T.as_str(event.get("text")))) for event in working)
    duration = max(0.001, T.as_float(clip.get("duration")))
    input_warnings = list(timing_quality.get("warnings") or [])
    if not fonts.allow_custom_font_paths:
        input_warnings.append(
            "Font file paths are disabled; libass uses the configured system-family fallback chain."
        )
    disabled_reason = (
        "captions disabled by project/configuration"
        if not enabled
        else "transcript caption events unavailable"
        if not working
        else None
    )
    if disabled_reason:
        input_warnings.append(disabled_reason)
    decision_seed = (
        f"{project_id}|{clip.get('clip_id')}|{style_name}|{len(working)}|"
        f"{timing_quality.get('source')}|{safe_zone.get('strategy')}"
    )
    decision_id = "caption_" + hashlib.sha256(decision_seed.encode()).hexdigest()[:16]
    first_time = min((T.as_float(event.get("start")) for event in working), default=None)
    last_time = max((T.as_float(event.get("end")) for event in working), default=None)
    contract: dict[str, Any] = {
        "version": "2",
        "caption_decision_id": decision_id,
        "clip_id": clip.get("clip_id"),
        "project_id": project_id,
        "created_at": datetime.now(UTC).isoformat(),
        "input_signals": {
            "transcript_available": bool(events),
            "word_timing_available": timing_quality.get("source") == "word_level",
            "segment_timing_available": bool(events),
            "speaker_labels_available": bool(neutral_labels),
            "story_shape": T.as_dict(blueprint.get("storytelling_v2")).get("story_shape")
            or T.as_dict(blueprint.get("story_v2_guidance")).get("story_shape"),
            "hook_category": hook_category,
            "payoff_type": T.as_dict(blueprint.get("ending_payoff_v2")).get("ending_type"),
            "content_niche": T.as_dict(blueprint.get("content_niche")).get("primary"),
            "trend_patterns": [
                T.as_dict(item).get("label")
                for item in T.as_list(
                    T.as_dict(blueprint.get("trend_match_v2")).get("matched_patterns")
                )
            ],
            "face_tracking_mode": face_plan.get("mode"),
            "multi_speaker_layout": face_plan.get("mode"),
            "music_role": T.as_dict(
                T.as_dict(blueprint.get("music_decision_v2")).get("decision")
                or blueprint.get("music_decision_v2")
            ).get("music_role"),
            "speech_density": T.round3(words_total / duration),
            "warnings": input_warnings,
        },
        "style_decision": {
            "caption_style": style_name,
            "typography_mood": preset["typography_mood"],
            "layout_mode": safe_zone["layout_mode"],
            "animation_style": preset["animation"],
            "emphasis_strategy": "selective_hook_keyword_payoff",
            "speaker_strategy": speaker_captioning["placement_strategy"],
            "safe_zone_strategy": safe_zone["strategy"],
            "reason": style_reason,
            "confidence": 0.9 if working and timing_quality.get("source") == "word_level" else 0.72,
        },
        "timing_plan": {
            "timing_source": timing_quality.get("source") or "unavailable",
            "caption_units": timing_quality.get("quality_level") or "unavailable",
            "max_words_per_line": caption_personalization.get("max_words_per_line"),
            "max_lines": settings.max_lines,
            "min_display_time": settings.min_display_time_seconds,
            "max_display_time": settings.max_display_time_seconds,
            "gap_handling": "bounded hold without overlap",
            "first_caption_time": T.round3(first_time) if first_time is not None else None,
            "last_caption_time": T.round3(last_time) if last_time is not None else None,
        },
        "emphasis_plan": emphasis,
        "caption_timing_quality": {**timing_quality, "caption_events_total": len(working)},
        "caption_safe_zone": safe_zone,
        "hook_caption_treatment": {
            "applied": bool(hook_events),
            "hook_category": hook_category,
            "hook_words": emphasis["hook_words"],
            "first_caption_time": T.round3(first_time) if first_time is not None else None,
            "animation": working[0].get("animation") if working else None,
            "style": working[0].get("ass_style") if working else None,
            "reason": "first faithful transcript caption receives stronger hook treatment"
            if hook_events
            else disabled_reason or "hook treatment unavailable",
            "warnings": [],
        },
        "caption_emphasis": {
            "highlighted_words": sorted(
                {word for event in working for word in T.as_list(event.get("highlighted_words"))}
            ),
            "source": "story+virality+planning+spoken_text_intersection",
            "events_with_emphasis": emphasis_events,
            "overemphasis_prevented": True,
            "warnings": [],
        },
        "caption_personalization": caption_personalization,
        "speaker_captioning": speaker_captioning,
        "render_plan": {
            "format": "ass",
            "ass_path": None,
            "styles": styles,
            "styles_count": len(styles),
            "events_count": len(working),
            "validation_expected": settings.enable_caption_render_validation,
            "font_family": fonts.primary,
            "font_fallback": fonts.fallback,
            "font_availability_verified": False,
            "warnings": input_warnings,
        },
        "ass_generation": {
            "path": None,
            "styles_count": len(styles),
            "events_count": len(working),
            "hook_events_count": hook_events,
            "emphasis_events_count": emphasis_events,
            "speaker_events_count": speaker_events,
            "quote_events_count": quote_events,
            "warnings": [],
        },
        "caption_readability_validation": readability,
        "validation": {
            "captions_planned": bool(working),
            "captions_file_created": False,
            "captions_rendered": False,
            "ass_valid": None,
            "event_count": len(working),
            "timing_passed": not readability["timing_warnings"],
            "safe_zone_passed": bool(safe_zone.get("strategy")),
            "render_manifest_confirmed": False,
            "warnings": [*input_warnings, *readability["warnings"]],
            "passed": bool(not working and not enabled),
        },
        "warnings": [*input_warnings, *readability["warnings"]],
    }
    return working, contract
