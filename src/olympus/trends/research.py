"""Internet Trend Research V2 orchestration and downstream guidance helpers."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from olympus.domain.contracts.storage import StoragePort
from olympus.platform.config.settings import TrendResearchSettings
from olympus.trends.contracts import TrendResearchProvider, TrendSearchResult
from olympus.trends.library import (
    ALL_PLATFORMS,
    DO_NOT_COPY_WARNING,
    NICHE_KEYWORDS,
    PATTERN_LIBRARY,
    SUPPORTED_NICHES,
    normalize_niche,
    pattern_by_id,
    patterns_by_category,
    patterns_for_niche,
)
from olympus.trends.providers import build_trend_research_provider
from olympus.trends.store import (
    TrendSnapshotStore,
    snapshot_is_fresh,
    snapshot_is_stale_usable,
)

TREND_RESEARCH_V2_VERSION = 2
_SUMMARY_LIMIT = 320
_TITLE_LIMIT = 180
_SAFE_QUERY_BLOCKLIST = (
    "download viral",
    "copy script",
    "copy caption",
    "private scrape",
    "bypass login",
    "steal video",
)
_CATEGORY_FIELDS = {
    "hook": "hook_patterns",
    "storytelling": "storytelling_patterns",
    "retention": "retention_patterns",
    "ending": "ending_patterns",
    "caption": "caption_patterns",
    "pacing": "pacing_patterns",
    "music": "audio_music_patterns",
    "editing": "editing_patterns",
    "title": "title_patterns",
    "hashtag": "hashtag_patterns",
}

_NICHE_LABELS = {
    niche: niche.replace("_", " ") for niche in SUPPORTED_NICHES
}
_NICHE_LABELS.update(
    {
        "business_money": "business and money",
        "education_tutorial": "education and tutorial",
        "entertainment_comedy": "entertainment and comedy",
        "gaming_stream": "gaming and livestream highlights",
        "music_singing": "music performance and singing",
        "relationship_life_advice": "relationship and life advice",
        "tech_ai": "technology and AI",
        "unknown_mixed": "general short form",
    }
)

_BUILTIN_OFFICIAL_SOURCES = (
    TrendSearchResult(
        url=(
            "https://support.google.com/youtube/answer/11914225"
            "?co=YOUTUBE._YTVideoType%3Dshorts&hl=en"
        ),
        title="YouTube Search and Discovery tips for Shorts",
        summary=(
            "YouTube says Shorts ranking follows viewer choice, watch behavior, enjoyment, "
            "topic interest, competition, and seasonality rather than a preferred format."
        ),
        source_type="official_platform_docs",
        credibility=0.94,
        credibility_level="high",
        recency_score=0.45,
        provider="bundled_reference",
        patterns_supported=(
            "fast_first_sentence",
            "avoid_filler",
            "satisfying_answer",
            "replay_worthy_moment",
        ),
        warning="Bundled official-doc summary; the page was not fetched during this run.",
    ),
    TrendSearchResult(
        url="https://support.google.com/youtube/answer/16559651?hl=en",
        title="YouTube recommendation guidance",
        summary=(
            "YouTube recommends using the precise length a video needs, avoiding filler, "
            "and learning from audience-retention behavior instead of chasing one ideal length."
        ),
        source_type="official_platform_docs",
        credibility=0.94,
        credibility_level="high",
        recency_score=0.45,
        provider="bundled_reference",
        patterns_supported=("tight_clarity", "quick_context", "avoid_filler"),
        warning="Bundled official-doc summary; the page was not fetched during this run.",
    ),
    TrendSearchResult(
        url="https://ads.tiktok.com/business/library/AUNZ_Creative_Starter_Pack_TakeItToTikTok.pdf",
        title="TikTok Creative Starter Pack",
        summary=(
            "TikTok's public business guidance emphasizes sound-on creative, clear native "
            "communication, and readable text rather than copied creator expression."
        ),
        source_type="official_platform_docs",
        credibility=0.84,
        credibility_level="high",
        recency_score=0.4,
        provider="bundled_reference",
        patterns_supported=(
            "short_high_contrast",
            "subtle_speech_bed",
            "avoid_overpowering_audio",
        ),
        warning="Bundled official-doc summary; the PDF was not fetched during this run.",
    ),
)


def default_platform_focus() -> dict[str, Any]:
    """Return the three short-form targets Olympus renders for."""

    return {
        "youtube_shorts": True,
        "instagram_reels": True,
        "tiktok": True,
        "platform_reason": (
            "Olympus renders vertical short-form clips for YouTube Shorts, Instagram "
            "Reels, and TikTok; guidance remains pattern-level and platform-safe."
        ),
    }


def detect_content_niche_v2(
    transcript: str,
    *,
    title: str = "",
    description: str = "",
    source_metadata: dict[str, Any] | None = None,
    story_data: dict[str, Any] | None = None,
    candidate_types: list[str] | None = None,
    content_category: str | None = None,
) -> dict[str, Any]:
    """Infer one of the canonical niches from multiple existing source signals."""

    metadata = source_metadata if isinstance(source_metadata, dict) else {}
    story = story_data if isinstance(story_data, dict) else {}
    story_text = _story_signal_text(story)
    source_title = str(metadata.get("title") or "")
    source_description = str(metadata.get("description_excerpt_if_allowed") or "")
    fields = {
        "user_content_category": str(content_category or ""),
        "title": " ".join(part for part in (title, source_title) if part),
        "description": " ".join(part for part in (description, source_description) if part),
        "story_v2": story_text,
        "transcript": transcript,
        "candidate_types": " ".join(candidate_types or []),
    }
    weights = {
        "user_content_category": 4.0,
        "title": 2.2,
        "description": 1.4,
        "story_v2": 2.0,
        "transcript": 1.0,
        "candidate_types": 1.2,
    }
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    sources: dict[str, list[str]] = {}

    category_niche = normalize_niche(content_category)
    if category_niche != "unknown_mixed":
        scores[category_niche] = scores.get(category_niche, 0.0) + 6.0
        evidence.setdefault(category_niche, []).append(str(content_category))
        sources.setdefault(category_niche, []).append("user_content_category")

    for niche, keywords in NICHE_KEYWORDS.items():
        if niche == "unknown_mixed":
            continue
        for field_name, value in fields.items():
            normalized = _normalize_text(value)
            if not normalized:
                continue
            hits = [keyword for keyword in keywords if _contains_term(normalized, keyword)]
            if not hits:
                continue
            unique_hits = list(dict.fromkeys(hits))
            scores[niche] = scores.get(niche, 0.0) + weights[field_name] * min(
                4.0, float(len(unique_hits))
            )
            evidence.setdefault(niche, []).extend(unique_hits)
            sources.setdefault(niche, []).append(field_name)

    if not scores:
        primary = "unknown_mixed"
        secondary: list[str] = []
        confidence = 0.28
        evidence_keywords: list[str] = []
        source_fields: list[str] = []
    else:
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        primary, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        secondary = [name for name, score in ranked[1:4] if score >= max(2.0, top * 0.35)]
        margin = max(0.0, top - second)
        confidence = min(0.94, 0.42 + min(0.3, top / 35.0) + min(0.2, margin / 20.0))
        evidence_keywords = list(dict.fromkeys(evidence.get(primary, [])))[:10]
        source_fields = list(dict.fromkeys(sources.get(primary, [])))

    evidence_segments = _evidence_segments(transcript, evidence_keywords)
    niche_label = _NICHE_LABELS[primary]
    recommended_queries = [
        f"current {niche_label} short form hook and storytelling patterns",
        f"{niche_label} YouTube Shorts retention best practices",
    ]
    recommended_platforms = [
        platform
        for platform in ALL_PLATFORMS
        if primary != "news_commentary" or platform != "tiktok"
    ]
    return {
        "primary": primary,
        "secondary": secondary,
        "confidence": round(confidence, 3),
        "evidence": evidence_keywords,
        "evidence_keywords": evidence_keywords,
        "evidence_segments": evidence_segments,
        "source_fields_used": source_fields,
        "source": "multi_signal_heuristic_v2",
        "method": "multi_signal_heuristic_v2",
        "recommended_platforms": recommended_platforms,
        "recommended_research_queries": recommended_queries,
    }


def build_trend_query_plan(
    detected_niche: dict[str, Any] | str,
    *,
    platform_focus: dict[str, Any] | None = None,
    max_queries: int = 5,
    max_sources: int = 12,
    recency_window_days: int = 30,
    language: str = "en",
    region: str | None = None,
    provider_scope: str = "evergreen",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a stable, niche-specific and copyright-safe research plan."""

    current = now or datetime.now(UTC)
    niche_value = (
        str(detected_niche.get("primary") or "")
        if isinstance(detected_niche, dict)
        else str(detected_niche)
    )
    niche = normalize_niche(niche_value)
    focus = platform_focus or default_platform_focus()
    niche_label = _NICHE_LABELS[niche]
    candidates: list[dict[str, Any]] = [
        {
            "query": f"current {niche_label} short form hook storytelling retention patterns",
            "query_type": "niche_patterns",
            "reason": "Find current high-level structures relevant to the detected niche.",
        }
    ]
    platform_queries = {
        "youtube_shorts": "YouTube Shorts search discovery best practices official",
        "instagram_reels": "Instagram Reels creator best practices official",
        "tiktok": "TikTok creator short form best practices official",
    }
    for platform, query in platform_queries.items():
        if focus.get(platform) is True:
            candidates.append(
                {
                    "query": query,
                    "query_type": "official_platform_guidance",
                    "platform": platform,
                    "reason": "Prefer official platform guidance over creator-specific copying.",
                }
            )
    candidates.append(
        {
            "query": "short form copyright safe music and original content guidance official",
            "query_type": "safety",
            "reason": "Keep editing and audio recommendations copyright-safe.",
        }
    )
    limit = max(1, min(5, max_queries))
    queries = [item for item in candidates if _safe_query(str(item["query"]))][:limit]
    stable_payload = {
        "version": TREND_RESEARCH_V2_VERSION,
        "niche": niche,
        "platforms": sorted(key for key in ALL_PLATFORMS if focus.get(key) is True),
        "queries": [item["query"] for item in queries],
        "language": language,
        "region": region,
        "provider_scope": provider_scope,
    }
    cache_key = hashlib.sha256(
        json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "plan_id": f"trend_plan_{cache_key[:16]}",
        "created_at": current.isoformat(),
        "niche": niche,
        "queries": queries,
        "max_sources": max(1, min(12, max_sources)),
        "recency_window_days": max(1, recency_window_days),
        "cache_key": cache_key,
        "language": language,
        "region": region,
        "provider_scope": provider_scope,
        "reason": (
            "Niche-specific pattern research plus official platform and safety guidance; "
            "queries never request scripts, captions, downloads, or private content."
        ),
    }


class TrendResearchEngine:
    """Create, cache, and persist one project-level trend snapshot."""

    def __init__(
        self,
        settings: TrendResearchSettings,
        provider: TrendResearchProvider | None = None,
    ) -> None:
        self._settings = settings
        self._provider = provider or build_trend_research_provider(settings)

    async def research(
        self,
        storage: StoragePort,
        *,
        project_id: str | None,
        transcript: str,
        title: str = "",
        description: str = "",
        source_metadata: dict[str, Any] | None = None,
        story_data: dict[str, Any] | None = None,
        candidate_types: list[str] | None = None,
        content_category: str | None = None,
        detected_niche: dict[str, Any] | None = None,
        force_refresh: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        niche = detected_niche or detect_content_niche_v2(
            transcript,
            title=title,
            description=description,
            source_metadata=source_metadata,
            story_data=story_data,
            candidate_types=candidate_types,
            content_category=content_category,
        )
        focus = default_platform_focus()
        plan = build_trend_query_plan(
            niche,
            platform_focus=focus,
            max_queries=self._settings.max_queries_per_video,
            max_sources=self._settings.max_sources_per_snapshot,
            recency_window_days=self._settings.recency_window_days,
            language=self._settings.language,
            region=self._settings.region,
            provider_scope=self._settings.provider,
            now=current,
        )
        store = TrendSnapshotStore(storage, cache_dir=self._settings.cache_dir)
        cache_key = str(plan["cache_key"])
        stale: dict[str, Any] | None = None
        effective_force_refresh = force_refresh or self._settings.force_live_refresh
        if self._settings.cache_enabled:
            cached = await store.load_cache(cache_key)
            if (
                not effective_force_refresh
                and cached is not None
                and snapshot_is_fresh(cached, current)
            ):
                snapshot = _cached_snapshot(cached)
                if project_id:
                    await store.save_project(project_id, snapshot)
                return snapshot
            stale = cached

        if not self._settings.enabled:
            snapshot = self._fallback_or_unavailable(
                niche,
                focus,
                plan,
                story_data,
                current,
                reason="trend research is disabled by configuration",
                research_status="skipped",
            )
        elif not self._provider.live:
            snapshot = self._fallback_or_unavailable(
                niche,
                focus,
                plan,
                story_data,
                current,
                reason="no live runtime search provider is configured",
                research_status="skipped",
            )
        else:
            try:
                snapshot = await self._research_live(
                    niche=niche,
                    focus=focus,
                    plan=plan,
                    story_data=story_data,
                    stale=stale,
                    current=current,
                )
            finally:
                await self._provider.close()

        if project_id:
            await store.save_project(project_id, snapshot)
        if self._settings.cache_enabled and snapshot.get("cache_status") != "stale_fallback":
            await store.save_cache(cache_key, snapshot)
        return snapshot

    async def _research_live(
        self,
        *,
        niche: dict[str, Any],
        focus: dict[str, Any],
        plan: dict[str, Any],
        story_data: dict[str, Any] | None,
        stale: dict[str, Any] | None,
        current: datetime,
    ) -> dict[str, Any]:
        try:
            if not await self._provider.is_available():
                reason = f"runtime provider '{self._provider.name}' is unavailable"
                return self._live_failure(
                    niche,
                    focus,
                    plan,
                    story_data,
                    current,
                    reason=_stale_reason(reason, stale),
                    research_status="unavailable",
                    stale=stale,
                )
            raw_queries = plan.get("queries")
            queries: list[Any] = raw_queries if isinstance(raw_queries, list) else []
            max_sources = int(plan.get("max_sources") or 1)
            per_query = max(1, (max_sources + max(1, len(queries)) - 1) // max(1, len(queries)))
            found: list[TrendSearchResult] = []
            seen: set[str] = set()
            for item in queries:
                if not isinstance(item, dict):
                    continue
                query = str(item.get("query") or "")
                for result in await self._provider.search(query, max_results=per_query):
                    if result.url in seen or len(found) >= max_sources:
                        continue
                    summary = result.summary or await self._provider.fetch_summary(result.url) or ""
                    found.append(replace(result, summary=summary))
                    seen.add(result.url)
                if len(found) >= max_sources:
                    break
            if not found:
                return self._live_failure(
                    niche,
                    focus,
                    plan,
                    story_data,
                    current,
                    reason=_stale_reason("live provider returned no safe public sources", stale),
                    research_status="unavailable",
                    stale=stale,
                )
            found = self._provider.extract_patterns(
                found,
                str(niche.get("primary") or "unknown_mixed"),
            )
            return _live_snapshot(
                found,
                detected_niche=niche,
                platform_focus=focus,
                query_plan=plan,
                provider_name=self._provider.name,
                story_data=story_data,
                settings=self._settings,
                now=current,
                internet_available=self._provider.internet_available,
                provider_diagnostics=self._provider.diagnostics(),
            )
        except Exception as exc:
            return self._live_failure(
                niche,
                focus,
                plan,
                story_data,
                current,
                reason=_stale_reason(
                    f"live provider failed safely ({type(exc).__name__})",
                    stale,
                ),
                research_status="failed",
                stale=stale,
            )

    def _live_failure(
        self,
        niche: dict[str, Any],
        focus: dict[str, Any],
        plan: dict[str, Any],
        story_data: dict[str, Any] | None,
        current: datetime,
        *,
        reason: str,
        research_status: str,
        stale: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if stale is not None and snapshot_is_stale_usable(
            stale,
            current,
            allowed_hours=self._settings.stale_cache_allowed_hours,
        ):
            return _stale_cached_snapshot(
                stale,
                current,
                reason=reason,
                provider_requested=self._provider.name,
                provider_diagnostics=self._provider.diagnostics(),
            )
        return self._fallback_or_unavailable(
            niche,
            focus,
            plan,
            story_data,
            current,
            reason=reason,
            research_status=research_status,
            live_research_attempted=True,
            provider_diagnostics=self._provider.diagnostics(),
        )

    def _fallback_or_unavailable(
        self,
        niche: dict[str, Any],
        focus: dict[str, Any],
        plan: dict[str, Any],
        story_data: dict[str, Any] | None,
        current: datetime,
        *,
        reason: str,
        research_status: str,
        live_research_attempted: bool = False,
        provider_diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._settings.fallback_to_evergreen:
            return build_evergreen_snapshot(
                niche,
                query_plan=plan,
                platform_focus=focus,
                story_data=story_data,
                now=current,
                fallback_reason=reason,
                research_status=research_status,
                live_research_attempted=live_research_attempted,
                provider_requested=self._provider.name,
                provider_diagnostics=provider_diagnostics,
                fallback_cache_hours=(
                    self._settings.live_refresh_min_interval_hours
                    if live_research_attempted
                    else None
                ),
            )
        return _unavailable_snapshot(
            niche,
            query_plan=plan,
            platform_focus=focus,
            now=current,
            reason=reason,
            research_status=research_status,
            provider_name=self._provider.name,
            live_research_attempted=live_research_attempted,
            provider_diagnostics=provider_diagnostics,
        )


def build_evergreen_snapshot(
    detected_niche: dict[str, Any] | str,
    *,
    query_plan: dict[str, Any] | None = None,
    platform_focus: dict[str, Any] | None = None,
    story_data: dict[str, Any] | None = None,
    now: datetime | None = None,
    fallback_reason: str = "no live runtime search provider is configured",
    research_status: str = "skipped",
    live_research_attempted: bool = False,
    provider_requested: str = "evergreen",
    provider_diagnostics: dict[str, Any] | None = None,
    fallback_cache_hours: int | None = None,
) -> dict[str, Any]:
    """Build an honest offline snapshot grounded in bundled public guidance."""

    current = now or datetime.now(UTC)
    niche = _niche_contract(detected_niche)
    focus = platform_focus or default_platform_focus()
    plan = query_plan or build_trend_query_plan(niche, platform_focus=focus, now=current)
    patterns = patterns_for_niche(str(niche["primary"]))
    internal_id = "evergreen_library_v2"
    sources: list[dict[str, Any]] = [
        {
            "source_id": internal_id,
            "url": None,
            "title": "Olympus copyright-safe short-form pattern library",
            "domain": "local",
            "provider": "evergreen",
            "source_type": "evergreen_fallback",
            "retrieved_at": current.isoformat(),
            "published_at": None,
            "credibility": 0.58,
            "credibility_level": "medium",
            "recency_score": 0.35,
            "summary": (
                "Bundled structural guidance organized by niche; it contains no copied "
                "scripts, captions, titles, thumbnails, or downloaded media."
            ),
            "patterns_supported": [str(item["pattern_id"]) for item in patterns],
            "warning": "Evergreen fallback, not fresh internet research.",
            "warnings": ["Evergreen fallback, not fresh internet research."],
        }
    ]
    for result in _BUILTIN_OFFICIAL_SOURCES:
        source_id = _source_id(result.url)
        sources.append(_source_from_result(result, source_id, current))
    official_support: dict[str, list[str]] = {}
    for source in sources[1:]:
        for pattern_id in source["patterns_supported"]:
            official_support.setdefault(str(pattern_id), []).append(str(source["source_id"]))
    for pattern in patterns:
        pattern_id = str(pattern["pattern_id"])
        pattern["evidence_source_ids"] = [internal_id, *official_support.get(pattern_id, [])]
    snapshot = _snapshot_contract(
        detected_niche=niche,
        platform_focus=focus,
        query_plan=plan,
        sources=sources,
        patterns=patterns,
        now=current,
        expires_at=(
            current + timedelta(hours=max(0, fallback_cache_hours))
            if fallback_cache_hours is not None
            else None
        ),
        cache_status="evergreen_fallback",
        research_status=research_status,
        internet_available=False,
        provider_used="evergreen",
        provider_requested=provider_requested,
        provider_status="fallback",
        live_research_attempted=live_research_attempted,
        live_research_succeeded=False,
        confidence=0.52,
        fallback_used=True,
        fallback_reason=fallback_reason,
        warnings=[
            "Fresh runtime internet research was not used; evergreen guidance is marked fallback.",
            "Trend fit is advisory and must not outrank story completeness, payoff, or truth.",
            DO_NOT_COPY_WARNING,
        ],
        story_data=story_data,
        provider_diagnostics=provider_diagnostics,
    )
    return snapshot


def match_trend_patterns(
    text: str,
    snapshot: dict[str, Any] | None,
    detected_niche: dict[str, Any] | None = None,
    *,
    story_shape: str | None = None,
    hook_category: str | None = None,
    ending_type: str | None = None,
) -> dict[str, Any]:
    """Explain how a source-faithful candidate matches the snapshot patterns."""

    research = snapshot if isinstance(snapshot, dict) else {}
    niche = _niche_contract(detected_niche or research.get("detected_niche") or {})
    patterns_raw = research.get("extracted_patterns") or research.get("trend_patterns") or []
    patterns = [item for item in patterns_raw if isinstance(item, dict)]
    normalized = _normalize_text(text)
    structural = _normalize_text(
        " ".join((story_shape or "", hook_category or "", ending_type or ""))
    )
    matches: list[dict[str, Any]] = []
    for pattern in patterns:
        category = str(pattern.get("category") or "")
        if category not in {"hook", "storytelling", "retention", "ending"}:
            continue
        cues_raw = pattern.get("match_cues") or pattern.get("cues") or []
        cues = [str(item) for item in cues_raw if isinstance(item, str)]
        hits = [cue for cue in cues if _contains_term(normalized, cue)]
        pattern_id = str(pattern.get("pattern_id") or pattern.get("id") or "")
        structural_match = bool(
            structural
            and (
                _contains_term(structural, pattern_id.replace("_", " "))
                or _shape_pattern_match(structural, pattern_id)
            )
        )
        if not hits and not structural_match:
            continue
        source_ids = [
            str(item)
            for item in pattern.get("evidence_source_ids", [])
            if isinstance(item, str)
        ]
        matches.append(
            {
                "pattern_id": pattern_id,
                "id": pattern_id,
                "category": category,
                "label": str(pattern.get("label") or pattern_id.replace("_", " ")),
                "matched_cues": hits[:4],
                "reason": str(pattern.get("description") or "Pattern structure matched."),
                "source_ids": source_ids,
                "confidence": pattern.get("confidence"),
            }
        )
    matches.sort(
        key=lambda item: (
            -len(item["matched_cues"]),
            str(item["category"]),
            str(item["pattern_id"]),
        )
    )
    matches = matches[:8]
    niche_confidence = _as_float(niche.get("confidence"), 0.28)
    niche_fit = min(0.9, 0.38 + 0.5 * niche_confidence)
    enabled_platforms = sum(
        1
        for platform in ALL_PLATFORMS
        if isinstance(research.get("platform_focus"), dict)
        and research["platform_focus"].get(platform) is True
    )
    platform_fit = 0.72 if enabled_platforms else 0.5
    match_strength = min(1.0, len(matches) / 3.0)
    trend_fit = min(0.92, 0.2 + 0.42 * match_strength + 0.2 * niche_fit + 0.08 * platform_fit)
    fallback = research.get("fallback_used") is True
    source_ids = list(
        dict.fromkeys(
            source_id
            for match in matches
            for source_id in match["source_ids"]
            if source_id
        )
    )
    confidence = 0.34 + 0.12 * min(3, len(matches)) + 0.24 * niche_confidence
    if fallback:
        confidence *= 0.76
    confidence = min(0.88, confidence)
    why_not_higher: list[str] = []
    if not matches:
        why_not_higher.append("No transcript-supported hook/story/ending pattern matched strongly.")
    if fallback:
        why_not_higher.append("Only evergreen fallback research was available.")
    if niche_confidence < 0.5:
        why_not_higher.append("Detected niche confidence is limited.")
    warnings = [str(item) for item in research.get("warnings", []) if isinstance(item, str)]
    return {
        "snapshot_id": research.get("snapshot_id"),
        "research_status": research.get("research_status") or "unavailable",
        "fallback_used": fallback,
        "matched_patterns": matches,
        "pattern_categories": list(dict.fromkeys(str(item["category"]) for item in matches)),
        "trend_fit_score": round(trend_fit, 3),
        "niche_fit_score": round(niche_fit, 3),
        "platform_fit_score": round(platform_fit, 3),
        "why_it_matches": (
            "; ".join(str(item["label"]) for item in matches[:3])
            if matches
            else "No strong source-faithful structural match was detected."
        ),
        "why_not_higher": why_not_higher,
        "source_ids": source_ids,
        "confidence": round(confidence, 3),
        "warnings": warnings[:4],
        "score": round(trend_fit, 3),
        "basis": (
            "evergreen fallback research patterns"
            if fallback
            else "fresh or cached attributed trend research"
        ),
        "risk_notes": [str(item) for item in research.get("risk_notes", [])][:3],
    }


def build_story_trend_guidance(
    story_data: dict[str, Any] | None,
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Annotate Story V2 opportunities without changing any story fact."""

    story = story_data if isinstance(story_data, dict) else {}
    raw_stories = story.get("micro_stories") or story.get("recommended_clip_stories") or []
    if not isinstance(raw_stories, list):
        return []
    patterns = {
        str(item.get("pattern_id") or item.get("id") or ""): item
        for item in snapshot.get("extracted_patterns", [])
        if isinstance(item, dict)
    }
    guidance: list[dict[str, Any]] = []
    for raw in raw_stories[:120]:
        if not isinstance(raw, dict):
            continue
        shape = str(raw.get("story_shape") or "")
        pattern_ids = _story_shape_patterns(shape)
        matched = [patterns[pattern_id] for pattern_id in pattern_ids if pattern_id in patterns]
        completeness = _as_float(raw.get("completeness_score"))
        context_risk = _as_float(raw.get("context_dependency_score"))
        trend_fit = min(0.9, 0.28 + 0.18 * len(matched) + 0.28 * completeness)
        warnings: list[str] = []
        if context_risk >= 0.55:
            warnings.append("High context risk remains more important than trend fit.")
        if snapshot.get("fallback_used") is True:
            warnings.append("Story opportunity uses evergreen fallback research.")
        guidance.append(
            {
                "story_id": raw.get("story_id"),
                "matching_story_patterns": [
                    {
                        "pattern_id": item.get("pattern_id"),
                        "label": item.get("label"),
                    }
                    for item in matched
                ],
                "hook_opportunity": _first_pattern_label(snapshot, "hook"),
                "ending_opportunity": _first_pattern_label(snapshot, "ending"),
                "trend_fit_score": round(trend_fit, 3),
                "pattern_reason": (
                    f"The truth-based '{shape or 'unknown'}' story shape aligns with "
                    "the listed structural patterns; no story facts were changed."
                ),
                "warnings": warnings,
            }
        )
    return guidance


def build_editing_trend_guidance(
    snapshot: dict[str, Any] | None,
    detected_niche: dict[str, Any] | None = None,
    trend_match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate advisory trend patterns into safe Editing V2 choices."""

    research = snapshot if isinstance(snapshot, dict) else {}
    niche = normalize_niche(
        str(
            (detected_niche or {}).get("primary")
            or (research.get("detected_niche") or {}).get("primary")
            or "unknown_mixed"
        )
    )
    presets: dict[str, tuple[str, str, str, str, str, str]] = {
        "motivational": (
            "bold_hook_word_highlight",
            "restrained_cinematic_fast",
            "emotional_swell",
            "low",
            "clean_hook_punch_in",
            "payoff_quote_hold",
        ),
        "podcast_interview": (
            "clean_keyword_emphasis",
            "tight_conversational",
            "subtle_speech_bed",
            "low",
            "active_speaker_punch_in",
            "takeaway_hold",
        ),
        "education_tutorial": (
            "clean_educational_keywords",
            "structured_clarity",
            "subtle_speech_bed",
            "low",
            "clean_hook_punch_in",
            "practical_takeaway_hold",
        ),
        "gaming_stream": (
            "fast_reaction_captions",
            "fast_pattern_interrupts",
            "energetic_clean_bed",
            "medium",
            "reaction_punch_in",
            "replay_moment_hold",
        ),
        "reaction": (
            "fast_reaction_captions",
            "fast_pattern_interrupts",
            "energetic_clean_bed",
            "medium",
            "reaction_punch_in",
            "reaction_tail_hold",
        ),
        "music_singing": (
            "minimal_performance_captions",
            "performance_preserving",
            "source_audio_priority",
            "minimal",
            "subtle_performance_push",
            "performance_payoff_hold",
        ),
        "entertainment_comedy": (
            "short_high_contrast",
            "fast_setup_punchline",
            "energetic_clean_bed",
            "medium",
            "comic_reaction_punch",
            "punchline_tail_hold",
        ),
        "emotional_story": (
            "minimal_emotional_emphasis",
            "restrained_emotional",
            "emotional_swell",
            "minimal",
            "subtle_hook_push",
            "emotional_landing_hold",
        ),
    }
    default = (
        "clean_keyword_emphasis",
        "tight_clarity",
        "subtle_speech_bed",
        "low",
        "clean_hook_punch_in",
        "payoff_hold",
    )
    caption, pacing, music, sfx, motion, ending = presets.get(niche, default)
    matched = trend_match if isinstance(trend_match, dict) else {}
    warnings: list[str] = []
    if research.get("fallback_used") is True:
        warnings.append("Editing guidance uses evergreen fallback, not current live research.")
    if not research:
        warnings.append("Trend snapshot unavailable; conservative editing defaults are used.")
    warnings.append("Guidance is planned only; render metadata decides what was actually applied.")
    return {
        "trend_snapshot_id": research.get("snapshot_id"),
        "caption_style": caption,
        "pacing_style": pacing,
        "music_mood": music,
        "sfx_density": sfx,
        "hook_motion_style": motion,
        "ending_style": ending,
        "matched_pattern_ids": [
            item.get("pattern_id")
            for item in matched.get("matched_patterns", [])
            if isinstance(item, dict)
        ],
        "source": "internet_trend_research_v2" if research else "conservative_fallback",
        "warnings": warnings,
    }


def _live_snapshot(
    results: list[TrendSearchResult],
    *,
    detected_niche: dict[str, Any],
    platform_focus: dict[str, Any],
    query_plan: dict[str, Any],
    provider_name: str,
    story_data: dict[str, Any] | None,
    settings: TrendResearchSettings,
    now: datetime,
    internet_available: bool,
    provider_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    niche = _niche_contract(detected_niche)
    sources: list[dict[str, Any]] = []
    support: dict[str, list[str]] = {}
    for result in results[: settings.max_sources_per_snapshot]:
        if result.provider is None:
            result = replace(result, provider=provider_name)
        source_id = _source_id(result.url)
        inferred = _infer_pattern_ids(result)
        source = _source_from_result(
            replace(result, patterns_supported=tuple(inferred)), source_id, now
        )
        sources.append(source)
        for pattern_id in inferred:
            support.setdefault(pattern_id, []).append(source_id)

    patterns: list[dict[str, Any]] = []
    for pattern_id, source_ids in support.items():
        pattern = pattern_by_id(pattern_id)
        if pattern is None:
            continue
        pattern["evidence_source_ids"] = source_ids
        evidence_sources = [
            source for source in sources if source.get("source_id") in source_ids
        ]
        pattern["recency_score"] = round(
            sum(_as_float(source.get("recency_score"), 0.45) for source in evidence_sources)
            / max(1, len(evidence_sources)),
            3,
        )
        evidence_quality = sum(
            _as_float(source.get("credibility"), 0.35)
            * _as_float(source.get("recency_score"), 0.45)
            for source in evidence_sources
        ) / max(1, len(evidence_sources))
        pattern["confidence"] = round(
            min(0.9, 0.42 + 0.3 * evidence_quality + 0.06 * len(source_ids)),
            3,
        )
        patterns.append(pattern)

    baseline = patterns_for_niche(str(niche["primary"]))
    present_categories = {str(item.get("category")) for item in patterns}
    missing_categories = set(_CATEGORY_FIELDS) - present_categories
    fallback_used = bool(missing_categories)
    if fallback_used:
        fallback_source_id = "evergreen_library_v2"
        fallback_patterns: list[str] = []
        for category in sorted(missing_categories):
            candidate = next(
                (item for item in baseline if item.get("category") == category),
                None,
            )
            if candidate is None:
                continue
            candidate["evidence_source_ids"] = [fallback_source_id]
            patterns.append(candidate)
            fallback_patterns.append(str(candidate["pattern_id"]))
        sources.append(
            {
                "source_id": fallback_source_id,
                "url": None,
                "title": "Olympus copyright-safe short-form pattern library",
                "domain": "local",
                "provider": "evergreen",
                "source_type": "evergreen_fallback",
                "retrieved_at": now.isoformat(),
                "published_at": None,
                "credibility": 0.58,
                "credibility_level": "medium",
                "recency_score": 0.35,
                "summary": "Filled categories not supported by concise live search results.",
                "patterns_supported": fallback_patterns,
                "warning": "Partial evergreen supplement; not fresh research evidence.",
                "warnings": ["Partial evergreen supplement; not fresh research evidence."],
            }
        )
    ttl = _ttl_hours(str(niche["primary"]), settings)
    live_sources = [
        source for source in sources if source.get("source_type") != "evergreen_fallback"
    ]
    source_confidence = sum(
        _as_float(source.get("credibility"))
        * _as_float(source.get("recency_score"), 0.45)
        for source in live_sources
    ) / max(1, len(live_sources))
    confidence = min(0.88, 0.45 + 0.35 * source_confidence + 0.02 * len(support))
    warnings = [
        DO_NOT_COPY_WARNING,
        *[
            str(item)
            for item in provider_diagnostics.get("warnings", [])
            if isinstance(item, str)
        ],
        *[
            str(item)
            for item in provider_diagnostics.get("errors", [])
            if isinstance(item, str)
        ],
    ]
    if fallback_used:
        warnings.append(
            "Live source coverage was partial; missing categories use evergreen fallback."
        )
    return _snapshot_contract(
        detected_niche=niche,
        platform_focus=platform_focus,
        query_plan=query_plan,
        sources=sources,
        patterns=patterns,
        now=now,
        expires_at=now + timedelta(hours=ttl),
        cache_status="live_refreshed",
        research_status="partial" if fallback_used else "completed",
        internet_available=internet_available,
        provider_used=provider_name,
        provider_requested=str(settings.provider),
        provider_status="partial" if fallback_used else "completed",
        live_research_attempted=True,
        live_research_succeeded=True,
        confidence=confidence,
        fallback_used=fallback_used,
        fallback_reason=(
            "live sources did not support every guidance category"
            if fallback_used
            else None
        ),
        warnings=warnings,
        story_data=story_data,
        provider_diagnostics=provider_diagnostics,
    )


def _snapshot_contract(
    *,
    detected_niche: dict[str, Any],
    platform_focus: dict[str, Any],
    query_plan: dict[str, Any],
    sources: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    now: datetime,
    expires_at: datetime | None,
    cache_status: str,
    research_status: str,
    internet_available: bool,
    provider_used: str,
    provider_requested: str | None = None,
    provider_status: str | None = None,
    live_research_attempted: bool = False,
    live_research_succeeded: bool = False,
    confidence: float,
    fallback_used: bool,
    fallback_reason: str | None,
    warnings: list[str],
    story_data: dict[str, Any] | None,
    provider_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fingerprint = {
        "cache_key": query_plan.get("cache_key"),
        "created_at": now.isoformat(),
        "provider": provider_used,
    }
    digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8")).hexdigest()
    grouped = patterns_by_category(patterns)
    snapshot: dict[str, Any] = {
        "trend_research_v2_version": TREND_RESEARCH_V2_VERSION,
        "snapshot_id": f"trend_{digest[:20]}",
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "cache_status": cache_status,
        "cache_hit": False,
        "research_status": research_status,
        "internet_available": internet_available,
        "internet_research_available": internet_available,
        "provider_used": provider_used,
        "provider_requested": provider_requested or provider_used,
        "provider_status": provider_status or research_status,
        "live_research_attempted": live_research_attempted,
        "live_research_succeeded": live_research_succeeded,
        "fresh_live_evidence": bool(
            internet_available and live_research_succeeded and sources
        ),
        "query_plan": query_plan,
        "detected_niche": detected_niche,
        "content_niche_v2": detected_niche,
        "niches_detected": [detected_niche["primary"], *detected_niche.get("secondary", [])],
        "platform_focus": platform_focus,
        "sources": sources,
        "source_count": len(sources),
        "source_domains": list(
            dict.fromkeys(
                str(source.get("domain"))
                for source in sources
                if source.get("domain") and source.get("domain") != "local"
            )
        ),
        "source_credibility_summary": _source_credibility_summary(sources),
        "extracted_patterns": patterns,
        "trend_patterns": patterns,
        "risk_notes": [
            "Trend fit is advisory; story completeness, payoff, context, and truth remain primary.",
            "Do not copy exact creator wording, captions, titles, thumbnails, or scripts.",
            "Do not infer a promise that the source clip does not support.",
        ],
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "warnings": list(dict.fromkeys(warnings)),
        "provider_diagnostics": _bounded_provider_diagnostics(provider_diagnostics),
    }
    for category, field in _CATEGORY_FIELDS.items():
        snapshot[field] = grouped[category]
    snapshot["sources_used"] = [
        {
            **source,
            "type": source.get("source_type"),
            "name": source.get("title"),
        }
        for source in sources
    ]
    snapshot["story_trend_guidance"] = build_story_trend_guidance(story_data, snapshot)
    return snapshot


def _unavailable_snapshot(
    detected_niche: dict[str, Any],
    *,
    query_plan: dict[str, Any],
    platform_focus: dict[str, Any],
    now: datetime,
    reason: str,
    research_status: str,
    provider_name: str,
    live_research_attempted: bool = False,
    provider_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _snapshot_contract(
        detected_niche=_niche_contract(detected_niche),
        platform_focus=platform_focus,
        query_plan=query_plan,
        sources=[],
        patterns=[],
        now=now,
        expires_at=now + timedelta(hours=1),
        cache_status="failed",
        research_status=research_status,
        internet_available=False,
        provider_used=provider_name,
        provider_requested=provider_name,
        provider_status=research_status,
        live_research_attempted=live_research_attempted,
        live_research_succeeded=False,
        confidence=0.0,
        fallback_used=False,
        fallback_reason=reason,
        warnings=[reason, "No trend guidance was applied."],
        story_data=None,
        provider_diagnostics=provider_diagnostics,
    )


def _cached_snapshot(cached: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(cached)
    snapshot["cache_hit"] = True
    if snapshot.get("cache_status") not in {"fallback", "evergreen_fallback"}:
        snapshot["cache_status"] = "cached"
    snapshot["origin_internet_available"] = cached.get("internet_available") is True
    snapshot["internet_available"] = False
    snapshot["internet_research_available"] = False
    snapshot["live_research_attempted"] = False
    snapshot["live_research_succeeded"] = False
    snapshot["fresh_live_evidence"] = False
    snapshot["provider_status"] = "cached"
    warnings = [str(item) for item in snapshot.get("warnings", []) if isinstance(item, str)]
    note = "A reusable niche-level cache snapshot was used; no new search ran."
    if note not in warnings:
        warnings.append(note)
    snapshot["warnings"] = warnings
    return snapshot


def _stale_cached_snapshot(
    cached: dict[str, Any],
    now: datetime,
    *,
    reason: str,
    provider_requested: str,
    provider_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    snapshot = dict(cached)
    warnings = [str(item) for item in snapshot.get("warnings", []) if isinstance(item, str)]
    warnings.extend(
        [
            "A stale attributed snapshot was used because live refresh failed.",
            reason,
        ]
    )
    snapshot.update(
        {
            "served_at": now.isoformat(),
            "cache_hit": True,
            "cache_status": "stale_fallback",
            "research_status": "partial",
            "provider_requested": provider_requested,
            "provider_status": "stale_cache",
            "internet_available": False,
            "internet_research_available": False,
            "live_research_attempted": True,
            "live_research_succeeded": False,
            "fresh_live_evidence": False,
            "fallback_used": True,
            "fallback_reason": reason,
            "warnings": list(dict.fromkeys(warnings)),
            "provider_diagnostics": _bounded_provider_diagnostics(provider_diagnostics),
        }
    )
    return snapshot


def _source_from_result(
    result: TrendSearchResult,
    source_id: str,
    now: datetime,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "provider": result.provider,
        "url": result.url,
        "title": _bounded_text(result.title, _TITLE_LIMIT),
        "domain": _domain(result.url),
        "source_type": result.source_type,
        "retrieved_at": now.isoformat(),
        "published_at": result.published_at,
        "credibility": round(max(0.0, min(1.0, result.credibility)), 3),
        "credibility_level": result.credibility_level,
        "recency_score": round(max(0.0, min(1.0, result.recency_score)), 3),
        "summary": _bounded_text(result.summary, _SUMMARY_LIMIT),
        "patterns_supported": [
            pattern_id
            for pattern_id in result.patterns_supported
            if pattern_id in PATTERN_LIBRARY
        ],
        "warning": result.warning,
        "warnings": list(
            dict.fromkeys(
                [
                    *result.warnings,
                    *([result.warning] if result.warning else []),
                ]
            )
        ),
    }


def _infer_pattern_ids(result: TrendSearchResult) -> list[str]:
    identifiers = [
        pattern_id for pattern_id in result.patterns_supported if pattern_id in PATTERN_LIBRARY
    ]
    text = _normalize_text(f"{result.title} {result.summary}")
    for pattern_id, pattern in PATTERN_LIBRARY.items():
        raw_cues = pattern.get("match_cues")
        cues: list[Any] = raw_cues if isinstance(raw_cues, list) else []
        if any(_contains_term(text, str(cue)) for cue in cues):
            identifiers.append(pattern_id)
    return list(dict.fromkeys(identifiers))[:20]


def _niche_contract(value: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, dict):
        niche = dict(value)
        niche["primary"] = normalize_niche(str(niche.get("primary") or ""))
        niche["secondary"] = [
            normalize_niche(str(item))
            for item in niche.get("secondary", [])
            if normalize_niche(str(item)) != "unknown_mixed"
        ]
        niche.setdefault("confidence", 0.3)
        niche.setdefault("evidence", niche.get("evidence_keywords", []))
        niche.setdefault("evidence_keywords", niche.get("evidence", []))
        niche.setdefault("source", "compatibility_input")
        return niche
    return {
        "primary": normalize_niche(value),
        "secondary": [],
        "confidence": 0.5,
        "evidence": [],
        "evidence_keywords": [],
        "evidence_segments": [],
        "source_fields_used": ["explicit_niche"],
        "source": "explicit_niche",
        "method": "explicit_niche",
        "recommended_platforms": list(ALL_PLATFORMS),
        "recommended_research_queries": [],
    }


def _story_signal_text(story_data: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("topic_sections", "micro_stories", "recommended_clip_stories"):
        items = story_data.get(field)
        if not isinstance(items, list):
            continue
        for item in items[:80]:
            if not isinstance(item, dict):
                continue
            for key in ("title", "summary", "one_sentence_summary", "topic", "story_shape"):
                if item.get(key):
                    parts.append(str(item[key]))
            keywords = item.get("keywords")
            if isinstance(keywords, list):
                parts.extend(str(keyword) for keyword in keywords[:10])
    return " ".join(parts)


def _evidence_segments(transcript: str, keywords: list[str]) -> list[str]:
    if not transcript or not keywords:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(transcript.split()))
    matched = [
        _bounded_text(sentence, 160)
        for sentence in sentences
        if any(_contains_term(_normalize_text(sentence), keyword) for keyword in keywords)
    ]
    return list(dict.fromkeys(matched))[:3]


def _story_shape_patterns(shape: str) -> tuple[str, ...]:
    normalized = shape.lower().replace("-", "_")
    if "problem" in normalized and "solution" in normalized:
        return ("problem_solution", "practical_takeaway")
    if "mistake" in normalized or "lesson" in normalized:
        return ("mistake_lesson", "practical_takeaway")
    if "pain" in normalized or "transform" in normalized:
        return ("pain_transformation", "emotional_landing")
    if "conflict" in normalized or "debate" in normalized:
        return ("conflict_resolution", "strong_quote")
    if "confession" in normalized:
        return ("confession_meaning", "emotional_landing")
    if "question" in normalized or "answer" in normalized:
        return ("question_answer", "satisfying_answer")
    if "punchline" in normalized or "comedy" in normalized:
        return ("fast_setup_punchline", "punchline")
    return ("buildup_payoff", "satisfying_answer")


def _shape_pattern_match(structural: str, pattern_id: str) -> bool:
    structural_tokens = set(structural.split())
    pattern_tokens = set(pattern_id.replace("_", " ").split())
    return len(structural_tokens & pattern_tokens) >= min(2, len(pattern_tokens))


def _first_pattern_label(snapshot: dict[str, Any], category: str) -> str | None:
    field = _CATEGORY_FIELDS.get(category)
    values = snapshot.get(field or "")
    if not isinstance(values, list) or not values or not isinstance(values[0], dict):
        return None
    return str(values[0].get("label") or "") or None


def _ttl_hours(niche: str, settings: TrendResearchSettings) -> int:
    if niche == "unknown_mixed":
        return settings.general_ttl_hours
    if niche in {"music_singing", "entertainment_comedy", "gaming_stream"}:
        return settings.fast_ttl_hours
    return settings.niche_ttl_hours


def _stale_reason(reason: str, stale: dict[str, Any] | None) -> str:
    return f"{reason}; cached snapshot was stale" if stale is not None else reason


def _safe_query(query: str) -> bool:
    low = query.lower()
    return bool(query.strip()) and not any(blocked in low for blocked in _SAFE_QUERY_BLOCKLIST)


def _source_id(url: str) -> str:
    return f"source_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "unknown").lower()


def _normalize_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).lower().split())


def _contains_term(text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    if " " in normalized_term:
        return normalized_term in text
    return re.search(rf"\b{re.escape(normalized_term)}\b", text) is not None


def _bounded_text(value: str, limit: int) -> str:
    normalized = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(value))).split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1].rstrip() + "…"


def _source_credibility_summary(sources: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for source in sources:
        level = str(source.get("credibility_level") or "unknown").lower()
        counts[level if level in counts else "unknown"] += 1
    return {
        **counts,
        "average_credibility": round(
            sum(_as_float(source.get("credibility")) for source in sources)
            / max(1, len(sources)),
            3,
        ),
        "average_recency_score": round(
            sum(_as_float(source.get("recency_score"), 0.0) for source in sources)
            / max(1, len(sources)),
            3,
        ),
    }


def _bounded_provider_diagnostics(value: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = value if isinstance(value, dict) else {}
    attempted_providers = diagnostics.get("attempted_providers")
    warnings = diagnostics.get("warnings")
    errors = diagnostics.get("errors")
    return {
        "provider": diagnostics.get("provider"),
        "configured_provider_name": diagnostics.get("configured_provider_name"),
        "attempted": diagnostics.get("attempted") is True,
        "internet_available": diagnostics.get("internet_available") is True,
        "attempted_providers": [
            _bounded_text(str(item), 80)
            for item in (attempted_providers if isinstance(attempted_providers, list) else [])[:5]
            if isinstance(item, str)
        ],
        "warnings": [
            _bounded_text(str(item), 180)
            for item in (warnings if isinstance(warnings, list) else [])[:8]
            if isinstance(item, str)
        ],
        "errors": [
            _bounded_text(str(item), 180)
            for item in (errors if isinstance(errors, list) else [])[:8]
            if isinstance(item, str)
        ],
    }


def _as_float(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default
