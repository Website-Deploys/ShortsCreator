"""Deterministic, local whole-video understanding from existing Olympus artifacts."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.memory_contracts import BobaMemoryRecordV1, BobaProjectMemoryV1
from olympus.platform.errors import ValidationError

_WORD = re.compile(r"[A-Za-z0-9']+")
_STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "been",
    "before",
    "being",
    "but",
    "can",
    "could",
    "did",
    "does",
    "doing",
    "for",
    "from",
    "had",
    "has",
    "have",
    "here",
    "how",
    "into",
    "its",
    "just",
    "like",
    "more",
    "most",
    "not",
    "now",
    "our",
    "out",
    "really",
    "should",
    "some",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "too",
    "very",
    "was",
    "way",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}
_FILLER_WORDS = {
    "actually",
    "basically",
    "honestly",
    "just",
    "kind",
    "like",
    "literally",
    "maybe",
    "okay",
    "really",
    "right",
    "sort",
    "thing",
    "things",
    "um",
    "uh",
    "well",
    "yeah",
    "you know",
}
_TOPIC_SHIFT_CUES = (
    "another thing",
    "but then",
    "finally",
    "let's move",
    "moving on",
    "next",
    "now let's",
    "on the other hand",
    "the second",
    "turning to",
)
_CONTEXT_CUES = (
    "because",
    "first",
    "here is the context",
    "the reason",
    "to understand",
    "what happened was",
)
_PAYOFF_CUES = (
    "finally",
    "so the lesson",
    "that's why",
    "that is why",
    "the answer",
    "the result",
    "it turns out",
    "what changed",
)
_EMOTION_TERMS: dict[str, tuple[str, ...]] = {
    "curiosity": ("curious", "imagine", "secret", "what if", "why", "wonder"),
    "surprise": ("amazing", "can't believe", "shocked", "surprise", "unexpected", "wow"),
    "tension": ("challenge", "danger", "difficult", "fear", "problem", "risk", "struggle"),
    "humor": ("funny", "haha", "hilarious", "joke", "laugh"),
    "motivation": ("can do", "keep going", "must", "never give up", "take action"),
    "inspiration": ("hope", "inspire", "possible", "proud", "transformed", "win"),
    "confusion": ("confused", "doesn't make sense", "lost", "unclear"),
}


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: Any, *, maximum: int = 300) -> str:
    return " ".join(str(value or "").split())[:maximum].strip()


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _score(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    if number > 1.0 and number <= 100.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 3)


def _first_number(values: Sequence[Any], default: float = 0.0) -> float:
    for value in values:
        if value is not None and not isinstance(value, bool):
            return _number(value, default)
    return default


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD.findall(text)]


def _keywords(text: str, limit: int = 8) -> list[str]:
    counts = Counter(
        word
        for word in _words(text)
        if len(word) >= 3 and word not in _STOP_WORDS and not word.isdigit()
    )
    return [word for word, _count in counts.most_common(limit)]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _overlap(start: float, end: float, other_start: float, other_end: float) -> float:
    shared = max(0.0, min(end, other_end) - max(start, other_start))
    duration = max(0.001, end - start)
    return min(1.0, shared / duration)


def _range(item: Mapping[str, Any]) -> tuple[float, float]:
    start = _first_number(
        [
            item.get("start_seconds"),
            item.get("start"),
            item.get("source_start"),
            item.get("timestamp"),
            item.get("time"),
        ]
    )
    end = _first_number(
        [item.get("end_seconds"), item.get("end"), item.get("source_end")],
        start,
    )
    if end <= start:
        duration = _number(item.get("duration"), 0.0)
        end = start + max(0.0, duration)
    return start, end


def _bounded_unique(values: Sequence[str], *, limit: int, maximum: int = 300) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _text(value, maximum=maximum)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


@dataclass(frozen=True, slots=True)
class _TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str = ""


class BobaTopicSegmentV1(BobaContract):
    segment_id: str = Field(min_length=1, max_length=128)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    topic: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list, max_length=6)
    source_signals: list[str] = Field(default_factory=list, max_length=12)


class BobaStoryBeatV1(BobaContract):
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    summary: str = Field(min_length=1, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)
    source_signals: list[str] = Field(default_factory=list, max_length=12)


class BobaStoryArcV1(BobaContract):
    setup: list[BobaStoryBeatV1] = Field(default_factory=list, max_length=12)
    context: list[BobaStoryBeatV1] = Field(default_factory=list, max_length=12)
    build_up: list[BobaStoryBeatV1] = Field(default_factory=list, max_length=24)
    key_moments: list[BobaStoryBeatV1] = Field(default_factory=list, max_length=24)
    payoff: list[BobaStoryBeatV1] = Field(default_factory=list, max_length=16)
    conclusion: list[BobaStoryBeatV1] = Field(default_factory=list, max_length=12)
    unresolved_threads: list[str] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0.0, le=1.0)


class BobaEmotionalBeatV1(BobaContract):
    beat_id: str = Field(min_length=1, max_length=128)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    emotion_label: str = Field(min_length=1, max_length=80)
    intensity: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0)
    source_signals: list[str] = Field(default_factory=list, max_length=12)


class BobaContextPayoffLinkV1(BobaContract):
    link_id: str = Field(min_length=1, max_length=128)
    context_start_seconds: float = Field(ge=0.0)
    context_end_seconds: float = Field(ge=0.0)
    payoff_start_seconds: float = Field(ge=0.0)
    payoff_end_seconds: float = Field(ge=0.0)
    description: str = Field(min_length=1, max_length=400)
    standalone_clip_possible: bool
    setup_required: bool
    confidence: float = Field(ge=0.0, le=1.0)


class BobaSectionScoreV1(BobaContract):
    section_id: str = Field(min_length=1, max_length=128)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    importance_score: float = Field(ge=0.0, le=1.0)
    clarity_score: float = Field(ge=0.0, le=1.0)
    energy_score: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    shortability_score: float = Field(ge=0.0, le=1.0)
    filler_score: float = Field(ge=0.0, le=1.0)
    repetition_score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=16)


BobaSuggestedClipType = Literal[
    "candidate_for_short",
    "needs_more_context",
    "avoid_as_standalone",
    "possible_hook",
    "payoff_clip",
]
BobaRecommendedAction = Literal["consider", "include_setup", "avoid", "review"]


class BobaShortabilityHintV1(BobaContract):
    hint_id: str = Field(min_length=1, max_length=128)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    suggested_clip_type: BobaSuggestedClipType
    hook_potential: float = Field(ge=0.0, le=1.0)
    setup_needed: bool
    payoff_strength: float = Field(ge=0.0, le=1.0)
    recommended_action: BobaRecommendedAction
    reason: str = Field(min_length=1, max_length=500)


class BobaSignalUsageV1(BobaContract):
    transcript_used: bool
    analysis_signals_used: bool
    story_used: bool
    virality_used: bool
    planning_used: bool
    memory_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    fallback_used: bool
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaWholeVideoMemorySummaryV1(BobaContract):
    project_id: str = Field(min_length=1, max_length=128)
    video_type: str = Field(min_length=1, max_length=80)
    primary_topic: str = Field(min_length=1, max_length=160)
    strongest_sections: list[str] = Field(default_factory=list, max_length=12)
    weakest_sections: list[str] = Field(default_factory=list, max_length=12)
    best_shortability_patterns: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=16)


class BobaWholeVideoUnderstandingV1(BobaContract):
    schema_version: Literal["boba_whole_video_understanding_v1"] = (
        "boba_whole_video_understanding_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    video_duration_seconds: float = Field(ge=0.0)
    overall_summary: str = Field(min_length=1, max_length=600)
    video_type: str = Field(min_length=1, max_length=80)
    primary_topic: str = Field(min_length=1, max_length=160)
    secondary_topics: list[str] = Field(default_factory=list, max_length=16)
    creator_intent: str = Field(min_length=1, max_length=160)
    audience_value: str = Field(min_length=1, max_length=240)
    tone: str = Field(min_length=1, max_length=80)
    topic_timeline: list[BobaTopicSegmentV1] = Field(default_factory=list, max_length=60)
    story_arc: BobaStoryArcV1
    emotional_beats: list[BobaEmotionalBeatV1] = Field(default_factory=list, max_length=100)
    context_payoff_map: list[BobaContextPayoffLinkV1] = Field(
        default_factory=list, max_length=60
    )
    section_scores: list[BobaSectionScoreV1] = Field(default_factory=list, max_length=60)
    shortability_hints: list[BobaShortabilityHintV1] = Field(
        default_factory=list, max_length=60
    )
    signal_usage: BobaSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaWholeVideoUnderstandingEngine:
    """Build a bounded understanding artifact without media access or external calls."""

    def build(
        self,
        *,
        project_id: str,
        transcript_segments: Sequence[Mapping[str, Any]],
        source_id: str = "",
        video_duration_seconds: float | None = None,
        analysis_signals_v2: Mapping[str, Any] | None = None,
        story_artifact: Mapping[str, Any] | None = None,
        virality_artifact: Mapping[str, Any] | None = None,
        planning_artifact: Mapping[str, Any] | None = None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
        project_metadata: Mapping[str, Any] | None = None,
    ) -> BobaWholeVideoUnderstandingV1:
        segments = self._normalize_segments(transcript_segments)
        if not segments:
            raise ValidationError(
                "BOBA whole-video understanding requires transcript segments.",
                details={"project_id": project_id, "missing_signal": "transcript"},
            )

        analysis = _dict(analysis_signals_v2)
        story = self._artifact_data(story_artifact)
        virality = self._artifact_data(virality_artifact)
        planning = self._artifact_data(planning_artifact)
        memory_data = _dict(memory)
        metadata = _dict(project_metadata)
        duration = max(
            0.0,
            _number(video_duration_seconds, 0.0),
            max(segment.end for segment in segments),
        )
        topic_timeline, topic_fallback = self._topic_timeline(segments, story)
        primary_topic, secondary_topics = self._topics(
            segments, story, memory_data, topic_timeline
        )
        story_arc = self._story_arc(segments, story, planning)
        emotional_beats, emotion_fallback = self._emotional_beats(
            segments, story, analysis
        )
        context_payoff_map = self._context_payoff_map(segments, story)
        section_scores = self._section_scores(
            segments,
            topic_timeline,
            story,
            virality,
            planning,
            analysis,
            context_payoff_map,
            emotional_beats,
        )
        shortability_hints = self._shortability_hints(
            segments,
            topic_timeline,
            section_scores,
            context_payoff_map,
        )
        video_type = self._video_type(segments, analysis, metadata)
        creator_intent = self._creator_intent(segments, video_type)
        audience_value = self._audience_value(creator_intent, primary_topic)
        tone = self._tone(emotional_beats)
        usage = self._signal_usage(
            analysis=analysis,
            story=story,
            virality=virality,
            planning=planning,
            memory=memory_data,
            topic_fallback=topic_fallback,
            emotion_fallback=emotion_fallback,
        )
        warnings = list(usage.warnings)
        if not context_payoff_map:
            warnings.append(
                "No defensible context-to-payoff relationship was found; none was invented."
            )
        if not emotional_beats:
            warnings.append(
                "No defensible emotional beat was found from available transcript or "
                "analysis signals."
            )
        if not story_arc.payoff:
            warnings.append("A clear payoff could not be confirmed from available signals.")
        limitations = [
            "V1 uses deterministic local heuristics and existing Olympus artifacts, not "
            "human-level semantic understanding.",
            "Emotion labels are transcript/audio heuristics unless an upstream provider "
            "reports stronger evidence.",
            "Scores are editorial hints and do not prove audience performance or virality.",
            "No raw frames, biometric identity, media, or full transcript are stored in "
            "this artifact.",
        ]
        if usage.unavailable_signals:
            limitations.append(
                "Unavailable upstream signals: " + ", ".join(usage.unavailable_signals) + "."
            )
        overall_summary = self._summary(
            video_type,
            primary_topic,
            secondary_topics,
            story_arc,
        )
        return BobaWholeVideoUnderstandingV1(
            project_id=project_id,
            source_id=_text(source_id, maximum=512),
            video_duration_seconds=round(duration, 3),
            overall_summary=overall_summary,
            video_type=video_type,
            primary_topic=primary_topic,
            secondary_topics=secondary_topics,
            creator_intent=creator_intent,
            audience_value=audience_value,
            tone=tone,
            topic_timeline=topic_timeline,
            story_arc=story_arc,
            emotional_beats=emotional_beats,
            context_payoff_map=context_payoff_map,
            section_scores=section_scores,
            shortability_hints=shortability_hints,
            signal_usage=usage,
            warnings=_bounded_unique(warnings, limit=64, maximum=400),
            limitations=_bounded_unique(limitations, limit=32, maximum=500),
        )

    def build_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
    ) -> BobaWholeVideoUnderstandingV1:
        project = _dict(signals.get("project"))
        planning = {
            "selected_plans": _list(signals.get("selected_plans")),
            "planning_candidates": _list(signals.get("planning_candidates")),
            "planning_summary": _dict(signals.get("planning_summary")),
        }
        return self.build(
            project_id=project_id,
            source_id=str(project.get("storage_key") or project.get("source_id") or ""),
            video_duration_seconds=_number(
                signals.get("duration_seconds") or project.get("duration_seconds"), 0.0
            ),
            transcript_segments=[
                _dict(item) for item in _list(signals.get("transcript_segments"))
            ],
            analysis_signals_v2=_dict(signals.get("analysis_signals_v2")),
            story_artifact=_dict(signals.get("story_analysis_v2")),
            virality_artifact=_dict(signals.get("virality_summary")),
            planning_artifact=planning,
            memory=memory,
            project_metadata={
                **project,
                "speakers_or_roles": _list(signals.get("speakers_or_roles")),
            },
        )

    @staticmethod
    def _artifact_data(value: Mapping[str, Any] | None) -> dict[str, Any]:
        artifact = _dict(value)
        data = _dict(artifact.get("data"))
        return data or artifact

    @staticmethod
    def _normalize_segments(
        values: Sequence[Mapping[str, Any]],
    ) -> list[_TranscriptSegment]:
        segments: list[_TranscriptSegment] = []
        for value in values[:10_000]:
            item = _dict(value)
            text = _text(item.get("text") or item.get("transcript"), maximum=1_200)
            if not text:
                continue
            start, end = _range(item)
            if end <= start:
                end = start + max(0.25, min(8.0, len(text.split()) / 2.5))
            segments.append(
                _TranscriptSegment(
                    start=max(0.0, start),
                    end=max(0.0, end),
                    text=text,
                    speaker=_text(
                        item.get("speaker") or item.get("speaker_id"), maximum=80
                    ),
                )
            )
        return sorted(segments, key=lambda item: (item.start, item.end))

    def _topic_timeline(
        self,
        segments: list[_TranscriptSegment],
        story: dict[str, Any],
    ) -> tuple[list[BobaTopicSegmentV1], bool]:
        story_sections = [
            _dict(item) for item in _list(story.get("topic_sections")) if _dict(item)
        ]
        timeline: list[BobaTopicSegmentV1] = []
        for index, section in enumerate(story_sections[:60]):
            start, end = _range(section)
            if end <= start:
                continue
            evidence = [
                _text(item, maximum=180)
                for item in _list(section.get("evidence"))[:2]
                if _text(item, maximum=180)
            ]
            if not evidence:
                evidence = self._evidence_for_range(segments, start, end)
            topic = _text(
                section.get("title")
                or section.get("topic")
                or " ".join(_list(section.get("keywords"))[:4]),
                maximum=160,
            )
            summary = _text(
                section.get("summary") or (evidence[0] if evidence else topic),
                maximum=400,
            )
            if not topic or not summary:
                continue
            timeline.append(
                BobaTopicSegmentV1(
                    segment_id=_text(
                        section.get("section_id") or f"topic_{index}", maximum=128
                    ),
                    start_seconds=round(start, 3),
                    end_seconds=round(end, 3),
                    topic=topic,
                    summary=summary,
                    confidence=_score(
                        section.get("confidence") or section.get("story_potential"),
                        0.65,
                    ),
                    supporting_evidence=evidence,
                    source_signals=["transcript", "story_analysis_v2"],
                )
            )
        if timeline:
            return timeline, False
        return self._local_topic_timeline(segments), True

    def _local_topic_timeline(
        self, segments: list[_TranscriptSegment]
    ) -> list[BobaTopicSegmentV1]:
        groups: list[list[_TranscriptSegment]] = []
        current: list[_TranscriptSegment] = []
        current_words: set[str] = set()
        for segment in segments:
            segment_words = set(_keywords(segment.text, 12))
            elapsed = segment.start - current[0].start if current else 0.0
            gap = segment.start - current[-1].end if current else 0.0
            low = segment.text.casefold()
            shift_cue = any(cue in low for cue in _TOPIC_SHIFT_CUES)
            lexical_shift = bool(
                current
                and elapsed >= 18.0
                and segment_words
                and _jaccard(current_words, segment_words) < 0.08
            )
            should_split = bool(
                current
                and (
                    gap >= 6.0
                    or (elapsed >= 6.0 and shift_cue)
                    or lexical_shift
                    or elapsed >= 75.0
                )
            )
            if should_split:
                groups.append(current)
                current = []
                current_words = set()
            current.append(segment)
            current_words.update(segment_words)
        if current:
            groups.append(current)

        timeline: list[BobaTopicSegmentV1] = []
        for index, group in enumerate(groups[:60]):
            combined = " ".join(item.text for item in group)
            keys = _keywords(combined, 4)
            topic = " ".join(keys[:3]).title() or f"Section {index + 1}"
            evidence = [_text(group[0].text, maximum=180)]
            summary = self._range_summary(group)
            confidence = 0.58 if keys else 0.35
            timeline.append(
                BobaTopicSegmentV1(
                    segment_id=f"topic_local_{index}",
                    start_seconds=round(group[0].start, 3),
                    end_seconds=round(group[-1].end, 3),
                    topic=topic,
                    summary=summary,
                    confidence=confidence,
                    supporting_evidence=evidence,
                    source_signals=["transcript", "local_keyword_clustering"],
                )
            )
        return timeline

    @staticmethod
    def _range_summary(group: list[_TranscriptSegment]) -> str:
        first = _text(group[0].text, maximum=200)
        if len(group) == 1:
            return first
        last = _text(group[-1].text, maximum=160)
        if first.casefold() == last.casefold():
            return first
        return _text(f"{first} {last}", maximum=400)

    @staticmethod
    def _evidence_for_range(
        segments: list[_TranscriptSegment], start: float, end: float
    ) -> list[str]:
        return [
            _text(segment.text, maximum=180)
            for segment in segments
            if segment.end >= start and segment.start <= end
        ][:2]

    @staticmethod
    def _topics(
        segments: list[_TranscriptSegment],
        story: dict[str, Any],
        memory: dict[str, Any],
        timeline: list[BobaTopicSegmentV1],
    ) -> tuple[str, list[str]]:
        story_themes = [
            _text(item, maximum=160)
            for item in _list(story.get("primary_themes"))
            if _text(item, maximum=160)
        ]
        timeline_topics = [item.topic for item in timeline]
        transcript_topics = _keywords(" ".join(item.text for item in segments), 10)
        memory_topics = [
            _text(item, maximum=160)
            for item in _list(memory.get("main_topics"))
            if _text(item, maximum=160)
        ]
        combined = _bounded_unique(
            [*story_themes, *timeline_topics, *transcript_topics, *memory_topics],
            limit=12,
            maximum=160,
        )
        primary = combined[0] if combined else "general discussion"
        return primary, combined[1:9]

    def _story_arc(
        self,
        segments: list[_TranscriptSegment],
        story: dict[str, Any],
        planning: dict[str, Any],
    ) -> BobaStoryArcV1:
        micro_stories = [
            _dict(item) for item in _list(story.get("micro_stories")) if _dict(item)
        ]
        strongest = max(
            micro_stories,
            key=lambda item: _score(
                item.get("completeness_score")
                or _dict(item.get("scores")).get("completeness")
            ),
            default={},
        )
        setup: list[BobaStoryBeatV1] = []
        context: list[BobaStoryBeatV1] = []
        build_up: list[BobaStoryBeatV1] = []
        key_moments: list[BobaStoryBeatV1] = []
        payoff: list[BobaStoryBeatV1] = []
        conclusion: list[BobaStoryBeatV1] = []
        unresolved: list[str] = []

        if strongest:
            story_start, story_end = _range(strongest)
            setup_data = _dict(strongest.get("setup") or strongest.get("setup_analysis"))
            setup_text = _text(
                setup_data.get("setup_text") or strongest.get("summary"), maximum=400
            )
            if setup_text:
                setup.append(
                    self._beat(
                        setup_text,
                        _first_number(
                            [setup_data.get("setup_start"), story_start], story_start
                        ),
                        _first_number(
                            [setup_data.get("setup_end"), min(story_end, story_start + 8.0)],
                            min(story_end, story_start + 8.0),
                        ),
                        _score(setup_data.get("confidence"), 0.62),
                        ["story_analysis_v2", "transcript"],
                    )
                )
            context_data = _dict(strongest.get("context"))
            context_text = _text(
                context_data.get("required_context")
                or context_data.get("reason")
                or setup_data.get("context_caption"),
                maximum=400,
            )
            if context_text:
                context.append(
                    self._beat(
                        context_text,
                        story_start,
                        min(story_end, story_start + 12.0),
                        1.0 - _score(context_data.get("score"), 0.5),
                        ["story_analysis_v2"],
                    )
                )
            tension = _dict(strongest.get("tension") or strongest.get("tension_analysis"))
            tension_text = _text(
                tension.get("unresolved_question")
                or tension.get("viewer_question")
                or strongest.get("conflict_or_question"),
                maximum=400,
            )
            if tension_text:
                build_up.append(
                    self._beat(
                        tension_text,
                        story_start,
                        max(story_start, story_end - 4.0),
                        _score(tension.get("confidence"), 0.6),
                        ["story_analysis_v2"],
                    )
                )
            turning = _dict(strongest.get("turning_point"))
            turning_text = _text(
                turning.get("text") or turning.get("description"), maximum=400
            )
            if turning_text:
                turn_time = _first_number(
                    [turning.get("time"), turning.get("start"), (story_start + story_end) / 2]
                )
                key_moments.append(
                    self._beat(
                        turning_text,
                        turn_time,
                        _first_number([turning.get("end")], turn_time + 2.0),
                        _score(turning.get("confidence"), 0.58),
                        ["story_analysis_v2"],
                    )
                )
            payoff_data = _dict(strongest.get("payoff") or strongest.get("payoff_analysis"))
            payoff_text = _text(
                payoff_data.get("payoff_text") or strongest.get("lesson_or_takeaway"),
                maximum=400,
            )
            if payoff_text and payoff_data.get("payoff_present", True):
                payoff_start = _first_number(
                    [payoff_data.get("payoff_start"), story_end - 4.0],
                    max(story_start, story_end - 4.0),
                )
                payoff.append(
                    self._beat(
                        payoff_text,
                        payoff_start,
                        _first_number([payoff_data.get("payoff_end")], story_end),
                        _score(payoff_data.get("payoff_strength"), 0.65),
                        ["story_analysis_v2", "transcript"],
                    )
                )
            ending = _dict(strongest.get("ending") or strongest.get("ending_quality"))
            ending_text = _text(
                ending.get("final_line") or payoff_text or segments[-1].text, maximum=400
            )
            if ending_text:
                conclusion.append(
                    self._beat(
                        ending_text,
                        max(story_start, story_end - 6.0),
                        story_end,
                        _score(ending.get("final_line_strength"), 0.55),
                        ["story_analysis_v2", "transcript"],
                    )
                )

        if not setup:
            setup.append(
                self._beat(
                    _text(segments[0].text, maximum=400),
                    segments[0].start,
                    segments[0].end,
                    0.42,
                    ["transcript_heuristic"],
                )
            )
        if not build_up and len(segments) >= 3:
            middle = segments[len(segments) // 2]
            build_up.append(
                self._beat(
                    _text(middle.text, maximum=400),
                    middle.start,
                    middle.end,
                    0.36,
                    ["transcript_heuristic"],
                )
            )
        if not payoff:
            payoff_segment = next(
                (
                    segment
                    for segment in reversed(segments)
                    if any(cue in segment.text.casefold() for cue in _PAYOFF_CUES)
                ),
                None,
            )
            if payoff_segment:
                payoff.append(
                    self._beat(
                        _text(payoff_segment.text, maximum=400),
                        payoff_segment.start,
                        payoff_segment.end,
                        0.46,
                        ["transcript_payoff_heuristic"],
                    )
                )
        if not conclusion:
            conclusion.append(
                self._beat(
                    _text(segments[-1].text, maximum=400),
                    segments[-1].start,
                    segments[-1].end,
                    0.4,
                    ["transcript_heuristic"],
                )
            )

        for item in micro_stories:
            payoff_data = _dict(item.get("payoff"))
            context_data = _dict(item.get("context"))
            risks = [str(value) for value in _list(item.get("risks"))]
            if not payoff_data.get("payoff_present", False):
                unresolved.append(
                    _text(
                        item.get("rejection_reason")
                        or item.get("summary")
                        or "A story section has no confirmed payoff.",
                        maximum=300,
                    )
                )
            if _score(context_data.get("score")) >= 0.6 or "missing payoff" in risks:
                unresolved.extend(_text(value, maximum=300) for value in risks)

        for item in self._planning_items(planning)[:6]:
            start, end = _range(item)
            reason = _text(
                item.get("selected_reason")
                or item.get("reason")
                or item.get("hook_line"),
                maximum=400,
            )
            if reason and end > start:
                key_moments.append(
                    self._beat(
                        reason,
                        start,
                        end,
                        _score(
                            item.get("confidence")
                            or _dict(item.get("scores")).get("overall"),
                            0.6,
                        ),
                        ["planning_v2"],
                    )
                )

        completeness = _score(strongest.get("completeness_score"), 0.0)
        confidence = max(
            0.3,
            min(
                0.9,
                (0.35 if setup else 0.0)
                + (0.25 if payoff else 0.0)
                + (0.15 if build_up else 0.0)
                + 0.25 * completeness,
            ),
        )
        return BobaStoryArcV1(
            setup=setup[:12],
            context=context[:12],
            build_up=build_up[:24],
            key_moments=key_moments[:24],
            payoff=payoff[:16],
            conclusion=conclusion[:12],
            unresolved_threads=_bounded_unique(unresolved, limit=24, maximum=300),
            confidence=round(confidence, 3),
        )

    @staticmethod
    def _beat(
        summary: str,
        start: float,
        end: float,
        confidence: float,
        source_signals: list[str],
    ) -> BobaStoryBeatV1:
        safe_start = max(0.0, start)
        return BobaStoryBeatV1(
            start_seconds=round(safe_start, 3),
            end_seconds=round(max(safe_start, end), 3),
            summary=_text(summary, maximum=400),
            confidence=_score(confidence),
            source_signals=source_signals,
        )

    def _emotional_beats(
        self,
        segments: list[_TranscriptSegment],
        story: dict[str, Any],
        analysis: dict[str, Any],
    ) -> tuple[list[BobaEmotionalBeatV1], bool]:
        beats: list[BobaEmotionalBeatV1] = []
        story_values = [
            _dict(item)
            for item in _list(story.get("emotional_timeline"))
            if _dict(item)
        ]
        for index, item in enumerate(story_values[:100]):
            start, end = _range(item)
            label = self._normalize_emotion(
                item.get("emotion") or item.get("label") or item.get("after_state")
            )
            reason = _text(
                item.get("evidence") or item.get("reason") or f"Upstream story label: {label}",
                maximum=400,
            )
            if label and reason:
                beats.append(
                    BobaEmotionalBeatV1(
                        beat_id=f"emotion_story_{index}",
                        start_seconds=round(start, 3),
                        end_seconds=round(max(start, end), 3),
                        emotion_label=label,
                        intensity=_score(item.get("intensity"), 0.5),
                        reason=reason,
                        confidence=_score(item.get("confidence"), 0.62),
                        source_signals=["story_analysis_v2"],
                    )
                )
        if beats:
            return self._dedupe_beats(beats), False

        analysis_entry = _dict(analysis.get("emotion_timeline"))
        timeline = analysis_entry.get("timeline")
        analysis_values = (
            _list(_dict(timeline).get("events"))
            if isinstance(timeline, Mapping)
            else _list(timeline)
        )
        for index, raw in enumerate(analysis_values[:100]):
            item = _dict(raw)
            start, end = _range(item)
            label = self._normalize_emotion(item.get("label") or item.get("emotion"))
            if not label:
                continue
            beats.append(
                BobaEmotionalBeatV1(
                    beat_id=f"emotion_analysis_{index}",
                    start_seconds=round(start, 3),
                    end_seconds=round(max(start, end), 3),
                    emotion_label=label,
                    intensity=_score(item.get("score") or item.get("intensity"), 0.5),
                    reason=_text(
                        item.get("reason")
                        or item.get("evidence")
                        or f"Upstream analysis labeled this interval {label}.",
                        maximum=400,
                    ),
                    confidence=_score(
                        item.get("confidence")
                        or _dict(analysis_entry.get("status")).get("confidence"),
                        0.5,
                    ),
                    source_signals=["analysis_signals_v2", "emotion_timeline"],
                )
            )
        if beats:
            return self._dedupe_beats(beats), False

        for index, segment in enumerate(segments):
            low = segment.text.casefold()
            matches = [
                (label, sum(term in low for term in terms))
                for label, terms in _EMOTION_TERMS.items()
            ]
            label, hits = max(matches, key=lambda item: item[1])
            if hits <= 0:
                if self._filler_score(segment.text) >= 0.6:
                    label, hits = "low_energy", 1
                else:
                    continue
            punctuation = min(0.2, (segment.text.count("!") + segment.text.count("?")) * 0.05)
            beats.append(
                BobaEmotionalBeatV1(
                    beat_id=f"emotion_heuristic_{index}",
                    start_seconds=round(segment.start, 3),
                    end_seconds=round(segment.end, 3),
                    emotion_label=label,
                    intensity=_score(0.35 + min(0.35, hits * 0.12) + punctuation),
                    reason=_text(
                        "Transcript keyword and punctuation heuristic matched "
                        f"{label}: {segment.text}",
                        maximum=400,
                    ),
                    confidence=0.38,
                    source_signals=["transcript_emotion_heuristic"],
                )
            )
        return self._dedupe_beats(beats), True

    @staticmethod
    def _normalize_emotion(value: Any) -> str:
        label = _text(value, maximum=80).casefold().replace(" ", "_")
        aliases = {
            "positive": "inspiration",
            "excited": "surprise",
            "negative": "tension",
            "sad": "tension",
            "motivational": "motivation",
            "hopeful": "inspiration",
            "energetic": "motivation",
        }
        return aliases.get(label, label)

    @staticmethod
    def _dedupe_beats(beats: list[BobaEmotionalBeatV1]) -> list[BobaEmotionalBeatV1]:
        result: list[BobaEmotionalBeatV1] = []
        seen: set[tuple[str, int]] = set()
        for beat in sorted(beats, key=lambda item: (item.start_seconds, -item.intensity)):
            key = (beat.emotion_label, round(beat.start_seconds / 2))
            if key in seen:
                continue
            seen.add(key)
            result.append(beat)
        return result[:100]

    def _context_payoff_map(
        self,
        segments: list[_TranscriptSegment],
        story: dict[str, Any],
    ) -> list[BobaContextPayoffLinkV1]:
        links: list[BobaContextPayoffLinkV1] = []
        micro_stories = [
            _dict(item) for item in _list(story.get("micro_stories")) if _dict(item)
        ]
        for index, item in enumerate(micro_stories[:60]):
            payoff = _dict(item.get("payoff") or item.get("payoff_analysis"))
            if not payoff.get("payoff_present", False):
                continue
            setup = _dict(item.get("setup") or item.get("setup_analysis"))
            context = _dict(item.get("context") or item.get("context_dependency"))
            story_start, story_end = _range(item)
            context_start = _first_number(
                [setup.get("setup_start"), item.get("recommended_start"), story_start],
                story_start,
            )
            context_end = _first_number(
                [setup.get("setup_end"), min(story_end, context_start + 10.0)],
                min(story_end, context_start + 10.0),
            )
            payoff_start = _first_number(
                [payoff.get("payoff_start"), story_end - 4.0],
                max(context_end, story_end - 4.0),
            )
            payoff_end = _first_number([payoff.get("payoff_end"), story_end], story_end)
            context_risk = _score(
                context.get("score") or item.get("context_dependency_score"), 0.45
            )
            payoff_strength = _score(payoff.get("payoff_strength"), 0.55)
            setup_required = context_risk >= 0.5
            span = max(0.0, payoff_end - context_start)
            description = _text(
                payoff.get("payoff_text")
                or item.get("lesson_or_takeaway")
                or "Story V2 linked setup to a later payoff.",
                maximum=400,
            )
            links.append(
                BobaContextPayoffLinkV1(
                    link_id=f"context_payoff_story_{index}",
                    context_start_seconds=round(max(0.0, context_start), 3),
                    context_end_seconds=round(max(context_start, context_end), 3),
                    payoff_start_seconds=round(max(context_end, payoff_start), 3),
                    payoff_end_seconds=round(max(payoff_start, payoff_end), 3),
                    description=description,
                    standalone_clip_possible=(
                        not setup_required and payoff_strength >= 0.45 and span <= 75.0
                    ),
                    setup_required=setup_required,
                    confidence=_score(
                        (payoff_strength + (1.0 - context_risk)) / 2, 0.5
                    ),
                )
            )
        if links:
            return links[:60]

        context_segments = [
            segment
            for segment in segments
            if any(cue in segment.text.casefold() for cue in _CONTEXT_CUES)
        ]
        payoff_segments = [
            segment
            for segment in segments
            if any(cue in segment.text.casefold() for cue in _PAYOFF_CUES)
        ]
        for index, payoff_segment in enumerate(payoff_segments[:20]):
            context_segment = next(
                (
                    segment
                    for segment in reversed(context_segments)
                    if segment.start < payoff_segment.start
                ),
                None,
            )
            if context_segment is None:
                continue
            span = payoff_segment.end - context_segment.start
            links.append(
                BobaContextPayoffLinkV1(
                    link_id=f"context_payoff_heuristic_{index}",
                    context_start_seconds=round(context_segment.start, 3),
                    context_end_seconds=round(context_segment.end, 3),
                    payoff_start_seconds=round(payoff_segment.start, 3),
                    payoff_end_seconds=round(payoff_segment.end, 3),
                    description=_text(payoff_segment.text, maximum=400),
                    standalone_clip_possible=span <= 75.0,
                    setup_required=True,
                    confidence=0.43,
                )
            )
        return links

    def _section_scores(
        self,
        segments: list[_TranscriptSegment],
        topics: list[BobaTopicSegmentV1],
        story: dict[str, Any],
        virality: dict[str, Any],
        planning: dict[str, Any],
        analysis: dict[str, Any],
        links: list[BobaContextPayoffLinkV1],
        emotional_beats: list[BobaEmotionalBeatV1],
    ) -> list[BobaSectionScoreV1]:
        fillers = [_dict(item) for item in _list(story.get("filler_sections"))]
        repeated = [_dict(item) for item in _list(story.get("repeated_sections"))]
        micro_stories = [_dict(item) for item in _list(story.get("micro_stories"))]
        selected = self._planning_items(planning)
        heatmap = [
            _dict(item)
            for item in _list(
                virality.get("heatmap")
                or _dict(virality.get("virality_summary")).get("heatmap")
            )
        ]
        energy_events = self._energy_events(analysis)
        scores: list[BobaSectionScoreV1] = []
        for index, topic in enumerate(topics):
            start, end = topic.start_seconds, topic.end_seconds
            section_segments = [
                item for item in segments if item.end >= start and item.start <= end
            ]
            section_text = " ".join(item.text for item in section_segments)
            lexical_filler = self._filler_score(section_text)
            filler_overlap = max(
                (
                    _overlap(start, end, *_range(item))
                    for item in fillers
                    if _range(item)[1] > _range(item)[0]
                ),
                default=0.0,
            )
            filler = _score(max(lexical_filler, filler_overlap))
            repeated_overlap = max(
                (
                    _overlap(start, end, *_range(item))
                    for item in repeated
                    if _range(item)[1] > _range(item)[0]
                ),
                default=0.0,
            )
            lexical_repetition = self._repetition_score(section_text, segments)
            repetition = _score(max(repeated_overlap, lexical_repetition))
            story_values = [
                item
                for item in micro_stories
                if _overlap(start, end, *_range(item)) >= 0.15
            ]
            story_strength = max(
                (
                    _score(
                        item.get("completeness_score")
                        or _dict(item.get("scores")).get("completeness")
                    )
                    for item in story_values
                ),
                default=topic.confidence,
            )
            context_risk = max(
                (
                    _score(
                        item.get("context_dependency_score")
                        or _dict(item.get("context")).get("score")
                    )
                    for item in story_values
                ),
                default=0.0,
            )
            planning_hit = max(
                (
                    _overlap(start, end, *_range(item))
                    for item in selected
                    if _range(item)[1] > _range(item)[0]
                ),
                default=0.0,
            )
            viral_heat = max(
                (
                    _score(item.get("heat") or item.get("score"))
                    * _overlap(start, end, *_range(item))
                    for item in heatmap
                    if _range(item)[1] > _range(item)[0]
                ),
                default=0.0,
            )
            payoff_strength = max(
                (
                    link.confidence
                    for link in links
                    if _overlap(
                        start,
                        end,
                        link.payoff_start_seconds,
                        link.payoff_end_seconds,
                    )
                    > 0
                ),
                default=0.0,
            )
            emotion_strength = max(
                (
                    beat.intensity
                    for beat in emotional_beats
                    if _overlap(start, end, beat.start_seconds, beat.end_seconds) > 0
                ),
                default=0.0,
            )
            energy = max(
                self._energy_for_range(start, end, energy_events),
                emotion_strength * 0.8,
                min(1.0, (section_text.count("!") + section_text.count("?")) * 0.12),
            )
            hook_signal = float(
                "?" in section_text
                or any(term in section_text.casefold() for term in ("secret", "mistake", "why"))
            )
            importance = _score(
                0.12
                + 0.28 * story_strength
                + 0.16 * planning_hit
                + 0.14 * viral_heat
                + 0.14 * payoff_strength
                + 0.1 * energy
                + 0.06 * hook_signal
            )
            clarity = _score(
                0.72
                + 0.08 * float(len(section_text.split()) >= 5)
                - 0.34 * context_risk
                - 0.3 * filler
            )
            words = _words(section_text)
            content_words = [word for word in words if word not in _STOP_WORDS]
            lexical_diversity = len(set(content_words)) / max(1, len(content_words))
            novelty = _score(0.25 + 0.65 * lexical_diversity - 0.5 * repetition)
            shortability = _score(
                0.23 * importance
                + 0.2 * clarity
                + 0.13 * energy
                + 0.14 * novelty
                + 0.18 * payoff_strength
                + 0.12 * planning_hit
                - 0.22 * filler
                - 0.16 * context_risk
            )
            reasons = [
                f"Story completeness contribution {story_strength:.2f}.",
                f"Clarity {clarity:.2f}; filler risk {filler:.2f}.",
            ]
            if planning_hit > 0:
                reasons.append("Overlaps an existing Planning V2 candidate or selection.")
            if payoff_strength > 0:
                reasons.append("Contains a linked payoff interval.")
            if viral_heat > 0:
                reasons.append("Overlaps an available Virality V2 heat interval.")
            warnings: list[str] = []
            if context_risk >= 0.55:
                warnings.append("High context dependency; include earlier setup.")
            if filler >= 0.55:
                warnings.append("Filler-heavy section may need trimming or rejection.")
            if repetition >= 0.6:
                warnings.append("Section appears repetitive relative to the source.")
            scores.append(
                BobaSectionScoreV1(
                    section_id=topic.segment_id or f"section_{index}",
                    start_seconds=start,
                    end_seconds=end,
                    importance_score=importance,
                    clarity_score=clarity,
                    energy_score=_score(energy),
                    novelty_score=novelty,
                    shortability_score=shortability,
                    filler_score=filler,
                    repetition_score=repetition,
                    reasons=reasons,
                    warnings=warnings,
                )
            )
        return scores[:60]

    @staticmethod
    def _planning_items(planning: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("selected_plans", "plans", "planning_candidates", "candidates"):
            values = [_dict(item) for item in _list(planning.get(key)) if _dict(item)]
            if values:
                return values
        summary = _dict(planning.get("planning_summary"))
        return [
            _dict(item)
            for item in _list(summary.get("selected_plans") or summary.get("plans"))
            if _dict(item)
        ]

    @staticmethod
    def _energy_events(analysis: dict[str, Any]) -> list[dict[str, Any]]:
        entry = _dict(analysis.get("audio_energy"))
        timeline = entry.get("timeline")
        if isinstance(timeline, Mapping):
            return [_dict(item) for item in _list(_dict(timeline).get("events"))]
        return [_dict(item) for item in _list(timeline)]

    @staticmethod
    def _energy_for_range(
        start: float, end: float, events: list[dict[str, Any]]
    ) -> float:
        values: list[float] = []
        for event in events:
            event_start, event_end = _range(event)
            if _overlap(start, end, event_start, event_end) <= 0:
                continue
            label = _text(event.get("label"), maximum=40).casefold()
            default = 0.8 if label == "loud" else 0.2 if label == "quiet" else 0.5
            values.append(_score(event.get("score") or event.get("energy"), default))
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _filler_score(text: str) -> float:
        words = _words(text)
        if not words:
            return 0.0
        low = text.casefold()
        hits = sum(words.count(term) for term in _FILLER_WORDS if " " not in term)
        hits += sum(low.count(term) for term in _FILLER_WORDS if " " in term) * 2
        return _score((hits / len(words)) * 3.0)

    @staticmethod
    def _repetition_score(text: str, segments: list[_TranscriptSegment]) -> float:
        keys = set(_keywords(text, 12))
        if not keys:
            return 0.0
        similarities = [
            _jaccard(keys, set(_keywords(segment.text, 12)))
            for segment in segments
            if segment.text.casefold() not in text.casefold()
        ]
        return _score(max(similarities, default=0.0))

    def _shortability_hints(
        self,
        segments: list[_TranscriptSegment],
        topics: list[BobaTopicSegmentV1],
        scores: list[BobaSectionScoreV1],
        links: list[BobaContextPayoffLinkV1],
    ) -> list[BobaShortabilityHintV1]:
        score_by_id = {item.section_id: item for item in scores}
        hints: list[BobaShortabilityHintV1] = []
        for index, topic in enumerate(topics):
            score = score_by_id.get(topic.segment_id)
            if score is None:
                continue
            text = " ".join(
                segment.text
                for segment in segments
                if segment.end >= topic.start_seconds and segment.start <= topic.end_seconds
            )
            hook_cue = float(
                "?" in text
                or any(term in text.casefold() for term in ("mistake", "secret", "why"))
            )
            related_links = [
                link
                for link in links
                if _overlap(
                    topic.start_seconds,
                    topic.end_seconds,
                    link.payoff_start_seconds,
                    link.payoff_end_seconds,
                )
                > 0
            ]
            payoff_strength = max((link.confidence for link in related_links), default=0.0)
            setup_needed = any(link.setup_required for link in related_links)
            hook_potential = _score(
                0.45 * score.shortability_score
                + 0.3 * hook_cue
                + 0.25 * score.importance_score
            )
            if score.filler_score >= 0.58 or score.clarity_score < 0.35:
                suggested: BobaSuggestedClipType = "avoid_as_standalone"
                action: BobaRecommendedAction = "avoid"
                reason = "Filler or low clarity makes this unsafe as a standalone clip."
            elif setup_needed:
                suggested = "needs_more_context"
                action = "include_setup"
                reason = "The payoff depends on an earlier context interval."
            elif payoff_strength >= 0.55:
                suggested = "payoff_clip"
                action = "consider"
                reason = "The section contains a linked payoff with bounded setup risk."
            elif hook_potential >= 0.62 and hook_cue:
                suggested = "possible_hook"
                action = "review"
                reason = "Transcript wording creates a possible standalone hook; verify context."
            elif score.shortability_score >= 0.5:
                suggested = "candidate_for_short"
                action = "consider"
                reason = "Balanced clarity, importance, and shortability support review."
            else:
                suggested = "avoid_as_standalone"
                action = "review"
                reason = "Available signals do not support a strong standalone recommendation."
            hints.append(
                BobaShortabilityHintV1(
                    hint_id=f"shortability_{index}",
                    start_seconds=topic.start_seconds,
                    end_seconds=topic.end_seconds,
                    suggested_clip_type=suggested,
                    hook_potential=hook_potential,
                    setup_needed=setup_needed,
                    payoff_strength=_score(payoff_strength),
                    recommended_action=action,
                    reason=reason,
                )
            )
        return hints[:60]

    @staticmethod
    def _video_type(
        segments: list[_TranscriptSegment],
        analysis: dict[str, Any],
        metadata: dict[str, Any],
    ) -> str:
        text = " ".join(item.text for item in segments).casefold()
        speakers = {
            item.speaker.casefold() for item in segments if item.speaker
        } | {
            _text(item, maximum=80).casefold()
            for item in _list(metadata.get("speakers_or_roles"))
            if _text(item, maximum=80)
        }
        speaker_entry = _dict(analysis.get("speaker_segmentation"))
        speakers.update(
            _text(_dict(item).get("speaker_id") or _dict(item).get("label"), maximum=80)
            for item in _list(speaker_entry.get("speakers"))
            if _dict(item)
        )
        if len({item for item in speakers if item}) >= 2:
            return "conversation_or_interview"
        if any(term in text for term in ("step one", "how to", "tutorial", "first step")):
            return "tutorial_or_how_to"
        if any(term in text for term in ("when i", "my story", "then i", "happened to me")):
            return "personal_story"
        if any(term in text for term in ("welcome to the podcast", "episode", "our guest")):
            return "podcast_or_interview"
        if any(term in text for term in ("why", "because", "the reason")):
            return "explainer_or_commentary"
        return "general_talk"

    @staticmethod
    def _creator_intent(segments: list[_TranscriptSegment], video_type: str) -> str:
        text = " ".join(item.text for item in segments).casefold()
        if "tutorial" in video_type or any(
            term in text for term in ("how to", "step one", "here's how")
        ):
            return "teach a practical method"
        if any(term in text for term in ("you should", "you need", "must")):
            return "persuade the audience to change or act"
        if any(term in text for term in ("hope", "never give up", "possible")):
            return "motivate or inspire"
        if "personal_story" in video_type:
            return "share an experience and its lesson"
        return "explain a topic or point of view"

    @staticmethod
    def _audience_value(intent: str, primary_topic: str) -> str:
        if intent.startswith("teach"):
            return f"Practical guidance about {primary_topic}."[:240]
        if intent.startswith("motivate"):
            return f"Encouragement and perspective related to {primary_topic}."[:240]
        if intent.startswith("share"):
            return f"A lived example and takeaway about {primary_topic}."[:240]
        if intent.startswith("persuade"):
            return f"A reasoned prompt to reconsider or act on {primary_topic}."[:240]
        return f"A compact explanation and context for {primary_topic}."[:240]

    @staticmethod
    def _tone(beats: list[BobaEmotionalBeatV1]) -> str:
        if not beats:
            return "informative_or_uncertain"
        totals: dict[str, float] = {}
        for beat in beats:
            totals[beat.emotion_label] = totals.get(beat.emotion_label, 0.0) + (
                beat.intensity * beat.confidence
            )
        return max(totals, key=lambda item: totals[item])

    @staticmethod
    def _signal_usage(
        *,
        analysis: dict[str, Any],
        story: dict[str, Any],
        virality: dict[str, Any],
        planning: dict[str, Any],
        memory: dict[str, Any],
        topic_fallback: bool,
        emotion_fallback: bool,
    ) -> BobaSignalUsageV1:
        analysis_used = any(
            bool(analysis.get(name))
            for name in ("audio_energy", "emotion_timeline", "speaker_segmentation")
        )
        story_used = any(
            bool(story.get(name))
            for name in (
                "topic_sections",
                "micro_stories",
                "emotional_timeline",
                "filler_sections",
                "repeated_sections",
            )
        )
        virality_used = bool(
            virality.get("heatmap")
            or _dict(virality.get("virality_summary")).get("heatmap")
        )
        memory_used = bool(_list(memory.get("main_topics")))
        availability = {
            "analysis_signals_v2": analysis_used,
            "story_analysis_v2": story_used,
            "virality": virality_used,
            "planning": bool(BobaWholeVideoUnderstandingEngine._planning_items(planning)),
            "boba_project_memory": memory_used,
        }
        unavailable = [name for name, available in availability.items() if not available]
        warnings: list[str] = []
        if topic_fallback:
            warnings.append("Topic timeline used local transcript keyword clustering.")
        if emotion_fallback:
            warnings.append("Emotional beats used a transparent transcript heuristic fallback.")
        if unavailable:
            warnings.append(
                "Some optional upstream signals were unavailable: "
                + ", ".join(unavailable)
            )
        return BobaSignalUsageV1(
            transcript_used=True,
            analysis_signals_used=availability["analysis_signals_v2"],
            story_used=availability["story_analysis_v2"],
            virality_used=availability["virality"],
            planning_used=availability["planning"],
            memory_used=availability["boba_project_memory"],
            unavailable_signals=unavailable,
            fallback_used=topic_fallback or emotion_fallback or bool(unavailable),
            warnings=warnings,
        )

    @staticmethod
    def _summary(
        video_type: str,
        primary_topic: str,
        secondary_topics: list[str],
        story_arc: BobaStoryArcV1,
    ) -> str:
        related = ", ".join(secondary_topics[:3])
        payoff = story_arc.payoff[0].summary if story_arc.payoff else "no confirmed payoff"
        parts = [
            f"A {video_type.replace('_', ' ')} centered on {primary_topic}.",
            (
                f"Related sections cover {related}."
                if related
                else "No distinct secondary topic was confirmed."
            ),
            f"The clearest detected payoff is: {payoff}",
        ]
        return _text(" ".join(parts), maximum=600)


def build_whole_video_memory_summary(
    understanding: BobaWholeVideoUnderstandingV1,
) -> BobaWholeVideoMemorySummaryV1:
    strongest = sorted(
        understanding.section_scores,
        key=lambda item: (item.shortability_score, item.importance_score),
        reverse=True,
    )[:5]
    weakest = sorted(
        understanding.section_scores,
        key=lambda item: (item.filler_score, 1.0 - item.clarity_score),
        reverse=True,
    )[:5]
    topic_by_id = {item.segment_id: item.topic for item in understanding.topic_timeline}
    strong_labels = [
        f"{item.start_seconds:.1f}-{item.end_seconds:.1f}s: "
        f"{topic_by_id.get(item.section_id, item.section_id)}"
        for item in strongest
    ]
    weak_labels = [
        f"{item.start_seconds:.1f}-{item.end_seconds:.1f}s: "
        f"{topic_by_id.get(item.section_id, item.section_id)}"
        for item in weakest
        if item.filler_score >= 0.35 or item.clarity_score < 0.5
    ]
    patterns = _bounded_unique(
        [
            f"{item.suggested_clip_type}: {item.reason}"
            for item in understanding.shortability_hints
            if item.recommended_action in {"consider", "include_setup"}
        ],
        limit=12,
        maximum=300,
    )
    return BobaWholeVideoMemorySummaryV1(
        project_id=understanding.project_id,
        video_type=understanding.video_type,
        primary_topic=understanding.primary_topic,
        strongest_sections=strong_labels,
        weakest_sections=weak_labels,
        best_shortability_patterns=patterns,
        warnings=understanding.warnings[:8],
    )


def whole_video_memory_record(
    summary: BobaWholeVideoMemorySummaryV1,
) -> BobaMemoryRecordV1:
    return BobaMemoryRecordV1(
        memory_id=f"whole_video_summary_{summary.project_id}"[:128],
        scope="project",
        record_type="project_summary",
        source="boba_whole_video_understanding_v1",
        project_id=summary.project_id,
        confidence=0.68,
        importance=0.82,
        tags=["whole_video", summary.video_type, summary.primary_topic][:16],
        summary=_text(
            f"{summary.video_type.replace('_', ' ')} about {summary.primary_topic}.",
            maximum=600,
        ),
        evidence=summary.strongest_sections[:6],
        applies_to=["planning", "ranking", "editorial_policy", "frontend"],
        metadata={
            "schema_version": "boba_whole_video_memory_summary_v1",
            "video_type": summary.video_type,
            "primary_topic": summary.primary_topic,
            "strongest_sections": summary.strongest_sections,
            "weakest_sections": summary.weakest_sections,
            "best_shortability_patterns": summary.best_shortability_patterns,
        },
        warnings=summary.warnings[:8],
    )
