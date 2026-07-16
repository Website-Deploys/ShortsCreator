"""Deterministic, truth-first Upload Metadata V2 generation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from olympus.metadata.contracts import (
    UPLOAD_METADATA_V2_VERSION,
    SocialCaptionMetadata,
    TitleCandidate,
    UploadMetadataV2,
    YouTubeShortsMetadata,
)
from olympus.metadata.hashtags import build_hashtag_plan
from olympus.metadata.platforms import PlatformName, platform_rules
from olympus.metadata.validation import validate_upload_metadata
from olympus.personalization import apply as P  # noqa: N812
from olympus.platform.config import get_settings

_SPACE = re.compile(r"\s+")
_WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")
_TRAILING_PUNCTUATION = re.compile(r"[.!?,;:]+$")
_BANNED_CLAIMS = (
    "copyright safe",
    "guaranteed viral",
    "safe to upload",
    "trending now",
)
_STOPWORDS = {
    "about",
    "around",
    "after",
    "ahead",
    "again",
    "also",
    "and",
    "because",
    "before",
    "being",
    "back",
    "best",
    "could",
    "come",
    "does",
    "doing",
    "for",
    "face",
    "from",
    "gentlemen",
    "good",
    "great",
    "guy",
    "have",
    "happen",
    "how",
    "into",
    "just",
    "know",
    "ladies",
    "lady",
    "looking",
    "make",
    "man",
    "more",
    "most",
    "matters",
    "nobody",
    "not",
    "now",
    "one",
    "particular",
    "people",
    "personally",
    "says",
    "send",
    "sometimes",
    "scream",
    "standing",
    "that",
    "that's",
    "their",
    "there",
    "there's",
    "these",
    "they",
    "the",
    "then",
    "them",
    "this",
    "those",
    "very",
    "walking",
    "what",
    "when",
    "where",
    "which",
    "while",
    "will",
    "why",
    "with",
    "works",
    "watching",
    "would",
    "yelling",
    "you",
    "your",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return _SPACE.sub(" ", value.strip()) if isinstance(value, str) else ""


def _multiline_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "\n".join(
        _SPACE.sub(" ", line).strip() for line in value.strip().splitlines() if line.strip()
    )


def _number(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _setting(settings: Any, name: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _settings_dict(settings: Any) -> dict[str, Any]:
    names = (
        "enabled",
        "generate_youtube",
        "generate_instagram",
        "generate_tiktok",
        "max_title_length",
        "max_youtube_hashtags",
        "max_instagram_hashtags",
        "max_tiktok_hashtags",
        "allow_emojis",
        "allow_curiosity_titles",
        "block_misleading_claims",
        "block_spam_hashtags",
        "require_safety_check",
        "require_manual_review_warning",
        "generate_ab_variants",
        "title_variant_count",
    )
    return {name: _setting(settings, name, _default_setting(name)) for name in names}


def _default_setting(name: str) -> Any:
    defaults = {
        "enabled": True,
        "generate_youtube": True,
        "generate_instagram": True,
        "generate_tiktok": True,
        "max_title_length": 70,
        "max_youtube_hashtags": 8,
        "max_instagram_hashtags": 12,
        "max_tiktok_hashtags": 8,
        "allow_emojis": False,
        "allow_curiosity_titles": True,
        "block_misleading_claims": True,
        "block_spam_hashtags": True,
        "require_safety_check": True,
        "require_manual_review_warning": True,
        "generate_ab_variants": True,
        "title_variant_count": 5,
    }
    return defaults[name]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _metadata_id(project_id: str, clip_id: str, render_id: str | None) -> str:
    seed = f"{project_id}:{clip_id}:{render_id or 'unrendered'}:{UPLOAD_METADATA_V2_VERSION}"
    return f"uploadmeta_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


def _bounded_phrase(value: str, *, max_words: int = 12, max_chars: int = 120) -> str:
    words = _WORDS.findall(_text(value))[:max_words]
    phrase = " ".join(words)
    if len(phrase) <= max_chars:
        return phrase
    shortened = phrase[:max_chars].rsplit(" ", 1)[0].strip()
    return shortened or phrase[:max_chars].strip()


def _humanize(value: str, fallback: str = "the main idea") -> str:
    cleaned = _SPACE.sub(" ", value.replace("_", " ").replace("-", " ")).strip()
    return cleaned or fallback


def _title_case(value: str) -> str:
    small = {"a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with"}
    words = value.split()
    result: list[str] = []
    for index, word in enumerate(words):
        if word.upper() in {"AI", "DIY", "NBA", "NFL", "UFC"}:
            result.append(word.upper())
        elif index > 0 and word.casefold() in small and not words[index - 1].endswith(":"):
            result.append(word.casefold())
        else:
            result.append(word[:1].upper() + word[1:].lower())
    return " ".join(result)


def _truncate_title(value: str, limit: int) -> str:
    clean = _SPACE.sub(" ", value).strip(" -:,.!?")
    if len(clean) <= limit:
        return clean
    shortened = clean[: limit + 1].rsplit(" ", 1)[0].rstrip(" -:,.!?")
    return shortened or clean[:limit].rstrip(" -:,.!?")


def _contains_banned_claim(value: str) -> bool:
    normalized = value.casefold()
    return any(phrase in normalized for phrase in _BANNED_CLAIMS)


def _direct_title_source(value: str, *, limit: int) -> str:
    clean = _text(value).strip(" -:,.!?")
    words = _WORDS.findall(clean)
    normalized = clean.casefold()
    weak_starts = (
        "and ",
        "but ",
        "ladies and gentlemen",
        "so what ",
        "well ",
        "you know ",
    )
    weak_endings = (" and", " because", " but", " or", " that", " which")
    if (
        not clean
        or len(clean) > limit
        or not 3 <= len(words) <= 10
        or clean.count(",") >= 2
        or normalized.startswith(weak_starts)
        or normalized.endswith(weak_endings)
        or _contains_banned_claim(clean)
    ):
        return ""
    return clean


def _topic_words(signals: Mapping[str, Any]) -> list[str]:
    raw_values = [
        signals.get("payoff_line"),
        *_list(signals.get("caption_keywords")),
        signals.get("hook_line"),
        signals.get("clip_title_source"),
        signals.get("transcript_excerpt_used"),
    ]
    words: list[str] = []
    for raw in raw_values:
        for word in _WORDS.findall(_text(raw)):
            normalized = word.casefold().strip("'-")
            if (
                len(normalized) < 3
                or normalized in _STOPWORDS
                or normalized.isdigit()
                or "'" in normalized
                or normalized in words
            ):
                continue
            words.append(normalized)
            if len(words) >= 6:
                return words
    return words[:6]


def _topic(signals: Mapping[str, Any]) -> tuple[str, list[str]]:
    words = _topic_words(signals)
    if words:
        selected = words[:2]
        return _title_case(" ".join(selected)), words
    niche = _humanize(_text(signals.get("content_niche")), "the main idea")
    return _title_case(niche), []


def _title_candidate(
    text: str,
    *,
    pattern: str,
    hook_category: str,
    limit: int,
    truth_score: float,
    curiosity_score: float,
) -> TitleCandidate:
    bounded = _truncate_title(_title_case(text), limit)
    warnings: list[str] = []
    if _contains_banned_claim(bounded):
        warnings.append("Candidate contains blocked claim language.")
    return {
        "text": bounded,
        "platform": "youtube_shorts",
        "pattern": pattern,
        "hook_category": hook_category or "context",
        "truth_score": round(truth_score, 3),
        "curiosity_score": round(curiosity_score, 3),
        "clarity_score": round(min(1.0, 0.72 + (0.12 if len(bounded) <= 55 else 0.0)), 3),
        "safety_score": 0.0 if warnings else 1.0,
        "length": len(bounded),
        "warnings": warnings,
    }


def _generate_titles(
    signals: Mapping[str, Any], config: Mapping[str, Any]
) -> list[TitleCandidate]:
    rules = platform_rules(
        "youtube_shorts",
        max_title_length=int(config["max_title_length"]),
        max_youtube_hashtags=int(config["max_youtube_hashtags"]),
        max_instagram_hashtags=int(config["max_instagram_hashtags"]),
        max_tiktok_hashtags=int(config["max_tiktok_hashtags"]),
    )
    topic, _keywords = _topic(signals)
    hook_category = _text(signals.get("hook_category")).casefold().replace(" ", "_")
    source = _direct_title_source(
        _text(signals.get("clip_title_source")) or _text(signals.get("hook_line")),
        limit=rules.title_max_chars,
    )
    patterns: list[tuple[str, str, float, float]] = []
    if source and not _contains_banned_claim(source):
        patterns.append((source, "grounded_hook", 0.95, 0.72))

    if hook_category in {"curiosity", "curiosity_gap", "open_loop"} and config[
        "allow_curiosity_titles"
    ]:
        patterns.append((f"What This Reveals About {topic}", "curiosity_gap", 0.82, 0.86))
    elif hook_category in {"mistake", "mistake_warning", "warning"}:
        patterns.append((f"The {topic} Mistake to Avoid", "mistake_warning", 0.84, 0.76))
    elif hook_category in {"education", "educational", "how_to"}:
        patterns.append((f"{topic}, Explained Clearly", "education", 0.9, 0.62))
    elif hook_category in {"podcast", "opinion", "contrarian"}:
        patterns.append((f"A Clear Take on {topic}", "podcast", 0.88, 0.66))
    elif hook_category in {"gaming", "reaction"}:
        patterns.append((f"The {topic} Moment, Explained", "gaming", 0.86, 0.7))
    elif hook_category in {"music", "singing", "performance"}:
        patterns.append((f"A Focused {topic} Performance Moment", "performance", 0.84, 0.65))
    elif hook_category in {"emotional", "emotion", "story"}:
        patterns.append((f"The Lesson Behind This {topic} Moment", "emotional", 0.86, 0.72))
    elif hook_category == "context" and _keywords:
        patterns.append((f"{topic}: A Clear Take", "context", 0.9, 0.64))
    elif hook_category == "context":
        patterns.append((f"A Clear {topic} Moment", "context", 0.86, 0.6))
    else:
        patterns.append((f"{topic}: Why It Matters", "specific_takeaway", 0.9, 0.68))

    if _keywords:
        patterns.extend(
            [
                (f"{topic}: The Key Takeaway", "clear_payoff", 0.92, 0.58),
                (f"A Better Perspective on {topic}", "perspective", 0.86, 0.72),
                (f"The Main Point: {topic}", "clarity", 0.94, 0.5),
                (f"{topic}: Worth a Closer Look", "specific_curiosity", 0.84, 0.7),
            ]
        )
    else:
        patterns.extend(
            [
                (f"The Key Point From This {topic}", "niche_fallback", 0.82, 0.48),
                (f"One Focused {topic} Take", "niche_fallback", 0.8, 0.54),
                (f"A {topic} Moment in Context", "niche_fallback", 0.8, 0.5),
                (f"The Main Point From This {topic}", "niche_fallback", 0.84, 0.46),
            ]
        )
    candidates: list[TitleCandidate] = []
    seen: set[str] = set()
    requested_count = int(config["title_variant_count"]) if config["generate_ab_variants"] else 1
    for text, pattern, truth, curiosity in patterns:
        candidate = _title_candidate(
            text,
            pattern=pattern,
            hook_category=hook_category,
            limit=rules.title_max_chars,
            truth_score=truth,
            curiosity_score=curiosity,
        )
        key = candidate["text"].casefold()
        if not candidate["text"] or key in seen or candidate["warnings"]:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= max(1, min(5, requested_count)):
            break
    candidates.sort(
        key=lambda item: (
            item["truth_score"] * 0.45
            + item["clarity_score"] * 0.25
            + item["curiosity_score"] * 0.2
            + item["safety_score"] * 0.1
        ),
        reverse=True,
    )
    return candidates


def _extract_signals(
    *,
    unified_clip_intelligence: Mapping[str, Any],
    timeline: Mapping[str, Any] | None,
    render_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    unified = _dict(unified_clip_intelligence)
    story = _dict(unified.get("story"))
    virality = _dict(unified.get("virality"))
    trend = _dict(unified.get("trend_research"))
    safety = _dict(unified.get("copyright_safety"))
    captions = _dict(unified.get("caption_intelligence"))
    music = _dict(unified.get("music_intelligence"))
    motion = _dict(unified.get("motion_graphics"))
    personalization = _dict(unified.get("personalization"))
    timeline_data = _dict(timeline)
    timeline_metadata = _dict(timeline_data.get("metadata"))
    render_data = _dict(render_metadata)
    full_safety = _dict(render_data.get("copyright_safety_v2"))
    safety_overall = _dict(full_safety.get("overall"))
    safety_manual = _dict(full_safety.get("manual_review"))
    hook = _dict(timeline_metadata.get("hook_v2"))
    trend_snapshot = _dict(timeline_metadata.get("internet_trend_research_v2"))
    detected_niche = _dict(trend_snapshot.get("detected_niche"))
    v2_metadata = _dict(timeline_metadata.get("v2_metadata"))
    story_guidance = _dict(timeline_metadata.get("story_v2_guidance"))
    personalization_directives = _dict(
        timeline_metadata.get("personalization_directives_v2")
    )
    title_source = _text(timeline_metadata.get("title"))
    hook_line = _text(virality.get("hook_line")) or _text(hook.get("hook_line"))
    payoff = _text(story.get("payoff")) or _text(story_guidance.get("payoff"))
    excerpt = _bounded_phrase(hook_line or payoff or title_source)
    trend_patterns = [
        _text(_dict(pattern).get("label") or _dict(pattern).get("pattern_id") or pattern)
        for pattern in _list(trend.get("matched_patterns"))
    ]
    trend_patterns = [pattern for pattern in trend_patterns if pattern]
    niche = (
        _text(trend.get("niche"))
        or _text(detected_niche.get("primary"))
        or _text(_dict(timeline_metadata.get("content_niche")).get("primary"))
        or _text(v2_metadata.get("content_category"))
        or "unknown"
    )
    risk = _text(safety_overall.get("risk_level")) or _text(safety.get("risk_level")) or "unknown"
    readiness = (
        _text(safety_overall.get("upload_readiness"))
        or _text(safety.get("upload_readiness"))
        or "needs_manual_review"
    )
    return {
        "clip_title_source": title_source,
        "transcript_excerpt_used": excerpt,
        "hook_line": hook_line,
        "payoff_line": _bounded_phrase(payoff),
        "hook_category": _text(virality.get("hook_category"))
        or _text(hook.get("category"))
        or "context",
        "story_shape": _text(story.get("story_shape")) or "unknown",
        "payoff_type": _text(story.get("ending_reason"))
        or ("present" if payoff else "unknown"),
        "content_niche": niche,
        "virality_score": _number(virality.get("overall_score")),
        "trend_patterns": trend_patterns,
        "trend_provider_status": _text(trend.get("provider_status"))
        or _text(trend.get("research_status"))
        or "unavailable",
        "trend_provider_used": _text(trend.get("provider_used")) or "none",
        "trend_cache_status": _text(trend.get("cache_status")) or "unavailable",
        "live_research_succeeded": trend.get("live_research_succeeded") is True,
        "trend_source_count": int(_number(trend.get("source_count")) or 0),
        "trend_confidence": _number(trend.get("confidence")),
        "safety_risk_level": risk,
        "upload_readiness": readiness,
        "safety_check_available": bool(full_safety or safety),
        "safety_manual_review_required": safety_manual.get("required") is True
        or safety.get("manual_review_required") is True,
        "caption_keywords": [
            _text(word) for word in _list(captions.get("highlighted_words")) if _text(word)
        ],
        "music_role": _text(music.get("role")) or "none",
        "motion_style": _text(motion.get("motion_style")) or "none",
        "platform_focus": ["youtube_shorts", "instagram_reels", "tiktok"],
        "story_payoff_present": bool(payoff),
        "personalization": personalization,
        "personalization_directives_v2": personalization_directives,
    }


def _safety_warnings(signals: Mapping[str, Any]) -> tuple[list[str], bool, bool]:
    risk = _text(signals.get("safety_risk_level")).casefold() or "unknown"
    readiness = _text(signals.get("upload_readiness")).casefold() or "needs_manual_review"
    manual = signals.get("safety_manual_review_required") is True or risk in {
        "unknown",
        "medium",
        "high",
        "blocked",
    }
    manual = manual or readiness not in {"ready_with_low_risk", "ready"}
    blocked = risk == "blocked" or readiness in {"blocked", "not_ready"}
    warnings: list[str] = []
    if blocked:
        warnings.append("The technical safety assessment marks this output as not ready.")
    elif risk == "high":
        warnings.append(
            "The technical safety assessment found high risk; manual review is required."
        )
    elif risk == "medium":
        warnings.append(
            "The technical safety assessment found medium risk; review before publishing."
        )
    elif risk == "unknown":
        warnings.append("Source or licensing risk is unknown; manual review is required.")
    elif manual:
        warnings.append("The safety assessment requires manual review before publishing.")
    return warnings, manual, blocked


def _confidence(signals: Mapping[str, Any], *, manual_review: bool) -> float:
    available = sum(
        bool(signals.get(name))
        for name in (
            "clip_title_source",
            "hook_line",
            "story_shape",
            "content_niche",
            "caption_keywords",
        )
    )
    score = 0.48 + available * 0.08
    if _number(signals.get("virality_score")) is not None:
        score += 0.05
    if manual_review:
        score -= 0.08
    return round(min(0.92, max(0.35, score)), 3)


def _platform_rules_for(platform: PlatformName, config: Mapping[str, Any]) -> Any:
    return platform_rules(
        platform,
        max_title_length=int(config["max_title_length"]),
        max_youtube_hashtags=int(config["max_youtube_hashtags"]),
        max_instagram_hashtags=int(config["max_instagram_hashtags"]),
        max_tiktok_hashtags=int(config["max_tiktok_hashtags"]),
    )


def generate_upload_metadata(
    *,
    project_id: str,
    clip_id: str,
    unified_clip_intelligence: Mapping[str, Any],
    timeline: Mapping[str, Any] | None = None,
    render_metadata: Mapping[str, Any] | None = None,
    render_id: str | None = None,
    created_at: str | None = None,
    settings: Any = None,
) -> UploadMetadataV2:
    """Generate platform-specific metadata from already-persisted clip intelligence."""

    config = _settings_dict(settings)
    if not config["enabled"]:
        return unavailable_upload_metadata(
            project_id=project_id,
            clip_id=clip_id,
            render_id=render_id,
            created_at=created_at,
            reason="Upload Metadata V2 is disabled by configuration.",
        )
    if not any(
        config[name] for name in ("generate_youtube", "generate_instagram", "generate_tiktok")
    ):
        return unavailable_upload_metadata(
            project_id=project_id,
            clip_id=clip_id,
            render_id=render_id,
            created_at=created_at,
            reason="All Upload Metadata V2 platforms are disabled by configuration.",
        )

    signals = _extract_signals(
        unified_clip_intelligence=unified_clip_intelligence,
        timeline=timeline,
        render_metadata=render_metadata,
    )
    titles = _generate_titles(signals, config)
    if not titles:
        return unavailable_upload_metadata(
            project_id=project_id,
            clip_id=clip_id,
            render_id=render_id,
            created_at=created_at,
            reason="No truthful, bounded title candidate could be produced from clip signals.",
            input_signals=signals,
        )
    personalization_settings = get_settings().creator_personalization
    titles, upload_personalization = P.rerank_title_candidates(
        titles,
        _dict(signals.get("personalization_directives_v2")) or None
        if personalization_settings.apply_to_upload_metadata
        else None,
    )

    best_title = titles[0]["text"]
    topic, topic_keywords = _topic(signals)
    topic_lower = topic.casefold() if topic else "the main idea"
    story_shape = _humanize(_text(signals.get("story_shape")), "a concise takeaway")
    payoff_present = signals.get("story_payoff_present") is True
    safety_warnings, manual_review, blocked = _safety_warnings(signals)
    confidence = _confidence(signals, manual_review=manual_review)
    hook_category = _text(signals.get("hook_category")).casefold()
    emotion = (
        "Emotional"
        if payoff_present and hook_category in {"emotion", "emotional", "story", "storytime"}
        else None
    )

    platforms: tuple[PlatformName, ...] = (
        "youtube_shorts",
        "instagram_reels",
        "tiktok",
    )
    hashtag_plans = {
        platform: build_hashtag_plan(
            rules=_platform_rules_for(platform, config),
            niche=_text(signals.get("content_niche")),
            keywords=topic_keywords,
            emotion=emotion,
        )
        for platform in platforms
    }

    relevant_terms = list(
        dict.fromkeys(
            [
                *topic_keywords,
                *re.split(r"[^a-z0-9]+", _text(signals.get("content_niche")).lower()),
                *[
                    _text(tag).lstrip("#").lower()
                    for plan in hashtag_plans.values()
                    for tag in _list(plan.get("niche_tags"))
                ],
            ]
        )
    )
    all_added: list[str] = []
    all_removed: list[str] = []
    for platform in platforms:
        plan = hashtag_plans[platform]
        personalized, added, removed = P.personalize_hashtags(
            _list(plan.get("hashtags")),
            _dict(signals.get("personalization_directives_v2")) or None
            if personalization_settings.apply_to_upload_metadata
            else None,
            relevant_terms=relevant_terms,
            limit=_platform_rules_for(platform, config).hashtag_max,
        )
        plan["hashtags"] = personalized
        plan["removed_tags"] = [
            *_list(plan.get("removed_tags")),
            *[{"tag": tag, "reason": "creator_profile"} for tag in removed],
        ]
        all_added.extend(added)
        all_removed.extend(removed)
    if all_added or all_removed:
        upload_personalization["applied"] = True
        upload_personalization["affected_systems"] = ["upload_metadata"]
    upload_personalization["hashtags_added"] = list(dict.fromkeys(all_added))
    upload_personalization["hashtags_removed"] = list(dict.fromkeys(all_removed))

    description_style = _text(upload_personalization.get("description_style"))
    description_prefix = (
        "A direct, energetic Short"
        if description_style in {"punchy", "energetic"}
        else "A reflective Short"
        if description_style in {"emotional", "reflective"}
        else "A conversational Short"
        if description_style == "conversational"
        else "A focused Short"
    )
    youtube_description = f"{description_prefix} about {topic_lower}."
    if payoff_present:
        youtube_description += f"\nIt follows a {story_shape} arc and lands on its key takeaway."
    else:
        youtube_description += "\nThe caption stays focused on the point made in the clip."
    instagram_caption = f"A focused moment about {topic_lower}."
    if payoff_present:
        instagram_caption += " The takeaway lands at the end."
    instagram_caption += "\nWhat stood out to you?"
    tiktok_caption = f"A quick take on {topic_lower}."
    pinned_comment = f"What is your take on {topic_lower}?"

    youtube: YouTubeShortsMetadata = {
        "title": best_title if config["generate_youtube"] else "",
        "title_variants": titles if config["generate_youtube"] else [],
        "description": youtube_description if config["generate_youtube"] else "",
        "hashtags": hashtag_plans["youtube_shorts"]["hashtags"]
        if config["generate_youtube"]
        else [],
        "hashtag_plan": hashtag_plans["youtube_shorts"],
        "pinned_comment": pinned_comment if config["generate_youtube"] else None,
        "safety_warnings": list(safety_warnings),
        "confidence": confidence,
    }
    instagram: SocialCaptionMetadata = {
        "caption": instagram_caption if config["generate_instagram"] else "",
        "caption_variants": (
            [
                f"A clear takeaway about {topic_lower}.\nHow do you see it?",
                f"One focused point about {topic_lower}, without the noise.",
            ]
            if config["generate_instagram"]
            else []
        ),
        "hashtags": hashtag_plans["instagram_reels"]["hashtags"]
        if config["generate_instagram"]
        else [],
        "hashtag_plan": hashtag_plans["instagram_reels"],
        "safety_warnings": list(safety_warnings),
        "confidence": confidence,
    }
    tiktok: SocialCaptionMetadata = {
        "caption": tiktok_caption if config["generate_tiktok"] else "",
        "caption_variants": (
            [f"The key point about {topic_lower}.", f"A concise {topic_lower} takeaway."]
            if config["generate_tiktok"]
            else []
        ),
        "hashtags": hashtag_plans["tiktok"]["hashtags"]
        if config["generate_tiktok"]
        else [],
        "hashtag_plan": hashtag_plans["tiktok"],
        "safety_warnings": list(safety_warnings),
        "confidence": confidence,
    }
    metadata_warnings = list(safety_warnings)
    if not topic_keywords:
        metadata_warnings.append(
            "Topic-specific keywords were sparse; titles use a niche-level fallback."
        )
    payload = UploadMetadataV2(
        metadata_id=_metadata_id(project_id, clip_id, render_id),
        project_id=project_id,
        clip_id=clip_id,
        render_id=render_id,
        created_at=created_at or _iso_now(),
        generator_version=UPLOAD_METADATA_V2_VERSION,
        status="not_ready" if blocked else "generated_needs_review" if manual_review else "ready",
        reason=None,
        input_signals=signals,
        youtube_shorts=youtube,
        instagram_reels=instagram,
        tiktok=tiktok,
        universal={
            "best_title": best_title,
            "short_caption": tiktok_caption,
            "hook_phrase": _bounded_phrase(_text(signals.get("hook_line")), max_words=8),
            "keyword_tags": list(dict.fromkeys(topic_keywords)),
            "niche_tags": hashtag_plans["youtube_shorts"]["niche_tags"],
            "emotional_tags": hashtag_plans["instagram_reels"]["emotional_tags"],
            "avoid_tags": ["#FYP", "#TrendingNow", "#Viral", "#ViralClip"],
            "manual_review_required": manual_review,
            "ready_for_upload": not blocked and not manual_review,
            "warnings": metadata_warnings,
        },
        upload_metadata_personalization=upload_personalization,
        validation={},
        artifact={
            "status": "pending",
            "storage_key": None,
            "version": UPLOAD_METADATA_V2_VERSION,
        },
    )
    source_text = " ".join(
        _text(signals.get(name))
        for name in ("transcript_excerpt_used", "hook_line", "clip_title_source")
    )
    payload["validation"] = validate_upload_metadata(
        payload,
        source_text=source_text,
        settings=config,
    )
    if not payload["validation"]["passed"] and not blocked:
        payload["status"] = "invalid"
        payload["reason"] = "Upload metadata validation failed."
    payload["universal"]["validation_passed"] = payload["validation"]["passed"]
    return payload


def unavailable_upload_metadata(
    *,
    project_id: str,
    clip_id: str,
    reason: str,
    render_id: str | None = None,
    created_at: str | None = None,
    input_signals: Mapping[str, Any] | None = None,
) -> UploadMetadataV2:
    """Return a complete, honest unavailable payload instead of fabricating copy."""

    empty_plan = {
        "platform": "",
        "hashtags": [],
        "niche_tags": [],
        "topic_tags": [],
        "trend_tags": [],
        "emotional_tags": [],
        "removed_tags": [],
        "relevance_score": 0.0,
        "warnings": [reason],
    }
    youtube: YouTubeShortsMetadata = {
        "title": "",
        "title_variants": [],
        "description": "",
        "hashtags": [],
        "hashtag_plan": {**empty_plan, "platform": "youtube_shorts"},
        "pinned_comment": None,
        "safety_warnings": [reason],
        "confidence": 0.0,
    }
    def social(platform: str) -> SocialCaptionMetadata:
        return SocialCaptionMetadata(
            caption="",
            caption_variants=[],
            hashtags=[],
            hashtag_plan={**empty_plan, "platform": platform},
            safety_warnings=[reason],
            confidence=0.0,
        )
    return UploadMetadataV2(
        metadata_id=_metadata_id(project_id, clip_id, render_id),
        project_id=project_id,
        clip_id=clip_id,
        render_id=render_id,
        created_at=created_at or _iso_now(),
        generator_version=UPLOAD_METADATA_V2_VERSION,
        status="unavailable",
        reason=reason,
        input_signals=dict(input_signals or {}),
        youtube_shorts=youtube,
        instagram_reels=social("instagram_reels"),
        tiktok=social("tiktok"),
        universal={
            "best_title": "",
            "short_caption": "",
            "hook_phrase": "",
            "keyword_tags": [],
            "niche_tags": [],
            "emotional_tags": [],
            "avoid_tags": ["#FYP", "#TrendingNow", "#Viral", "#ViralClip"],
            "manual_review_required": True,
            "ready_for_upload": False,
            "validation_passed": False,
            "warnings": [reason],
        },
        upload_metadata_personalization=P.empty_application(reason),
        validation={
            "passed": False,
            "title_truthful": False,
            "description_truthful": False,
            "hashtags_relevant": False,
            "no_copied_content": True,
            "no_spam_tags": True,
            "safety_checked": False,
            "title_validation": {"passed": False, "warnings": [], "errors": [reason]},
            "description_validation": {"passed": False, "warnings": [], "errors": [reason]},
            "hashtag_validation": {"passed": False, "warnings": [], "errors": [reason]},
            "safety_validation": {"passed": False, "warnings": [reason], "errors": []},
            "platform_validation": {"passed": False, "platforms": []},
            "warnings": [reason],
            "errors": [reason],
        },
        artifact={
            "status": "unavailable",
            "storage_key": None,
            "version": UPLOAD_METADATA_V2_VERSION,
        },
    )


def compact_upload_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bounded view carried by unified clip intelligence and the UI."""

    youtube = _dict(metadata.get("youtube_shorts"))
    instagram = _dict(metadata.get("instagram_reels"))
    tiktok = _dict(metadata.get("tiktok"))
    universal = _dict(metadata.get("universal"))
    validation = _dict(metadata.get("validation"))
    personalization = _dict(metadata.get("upload_metadata_personalization"))
    warnings = [
        _text(item)
        for item in [*_list(universal.get("warnings")), *_list(validation.get("warnings"))]
        if _text(item)
    ]
    return {
        "status": _text(metadata.get("status")) or "unavailable",
        "reason": _text(metadata.get("reason")) or None,
        "youtube_title": _text(youtube.get("title")),
        "youtube_description": _multiline_text(youtube.get("description")),
        "youtube_hashtags": [
            _text(tag) for tag in _list(youtube.get("hashtags")) if _text(tag)
        ],
        "instagram_caption": _multiline_text(instagram.get("caption")),
        "instagram_hashtags": [
            _text(tag) for tag in _list(instagram.get("hashtags")) if _text(tag)
        ],
        "tiktok_caption": _multiline_text(tiktok.get("caption")),
        "tiktok_hashtags": [
            _text(tag) for tag in _list(tiktok.get("hashtags")) if _text(tag)
        ],
        "best_title": _text(universal.get("best_title")) or _text(youtube.get("title")),
        "manual_review_required": universal.get("manual_review_required") is True,
        "validation_passed": validation.get("passed") is True,
        "personalization": {
            "applied": personalization.get("applied") is True,
            "profile_id": personalization.get("profile_id"),
            "title_style": personalization.get("title_style"),
            "hashtags_added": _list(personalization.get("hashtags_added")),
            "hashtags_removed": _list(personalization.get("hashtags_removed")),
            "variant_reranking_reason": personalization.get(
                "variant_reranking_reason"
            ),
            "warnings": _list(personalization.get("warnings")),
        },
        "warnings": list(dict.fromkeys(warnings)),
    }
