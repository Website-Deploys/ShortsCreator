"""Deterministic advisory caption and motion recommendations over BOBA artifacts."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, model_validator

from olympus.boba.clip_brief import BobaSourceWindowV1
from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaCaptionStyle = Literal[
    "clean_subtitles",
    "bold_hook_captions",
    "keyword_highlight",
    "emotional_emphasis",
    "minimal",
    "punchline_caption",
    "educational_steps",
    "no_captions",
]
BobaCaptionDensity = Literal["low", "medium", "high"]
BobaCaptionRhythm = Literal["calm", "normal", "fast", "punchy"]
BobaMotionStyle = Literal[
    "stable",
    "subtle_zoom",
    "dynamic_zoom",
    "punch_in",
    "layout_safe",
    "high_motion",
    "minimal_motion",
]
BobaMotionIntensity = Literal["none", "light", "moderate", "high"]
BobaCaptionMotionPriority = Literal["required", "recommended", "optional"]

_EDUCATIONAL_CUES = (
    "educational",
    "explain",
    "lesson",
    "how to",
    "step",
    "framework",
    "tutorial",
    "teach",
    "tip",
    "rule",
    "direct value",
    "problem solution",
)
_EMOTIONAL_CUES = (
    "emotional",
    "vulnerable",
    "heartfelt",
    "hope",
    "fear",
    "grief",
    "joy",
    "surprise",
    "anger",
    "relief",
    "inspiring",
    "motivational",
    "personal story",
)
_HIGH_ENERGY_CUES = (
    "high energy",
    "fast",
    "aggressive",
    "punchy",
    "humor",
    "funny",
    "shocking",
    "contradiction",
    "rapid",
    "excited",
)
_CALM_CUES = (
    "calm",
    "restrained",
    "serious",
    "thoughtful",
    "reflective",
    "subtle",
    "gentle",
)
_CAPTION_OVERLOAD_CUES = (
    "caption overload",
    "too much text",
    "dense caption",
    "too many words",
    "unreadable caption",
    "emphasize every word",
)
_READABILITY_CUES = (
    "readability",
    "unreadable",
    "low contrast",
    "safe zone",
    "avoid faces",
    "text overlap",
    "transcript unavailable",
    "transcript availability is not confirmed",
)
_OVER_MOTION_CUES = (
    "over-edit",
    "too many effects",
    "high motion",
    "aggressive motion",
    "constant zoom",
    "rapid zoom",
    "unstable",
    "jitter",
)
_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "before",
    "brief",
    "caption",
    "clip",
    "could",
    "direction",
    "does",
    "editor",
    "from",
    "have",
    "hook",
    "into",
    "motion",
    "only",
    "should",
    "that",
    "their",
    "then",
    "this",
    "through",
    "using",
    "viewer",
    "what",
    "when",
    "where",
    "which",
    "with",
    "without",
    "would",
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _artifact(value: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return _dict(value)


def _text(value: Any, *, maximum: int = 500) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text[:maximum].strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 3)


def _unit(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    if number > 1.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 4)


def _points(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    return _clamp(number * 100.0 if 0.0 <= number <= 1.0 else number)


def _unique(
    values: Sequence[Any],
    *,
    limit: int,
    maximum: int = 500,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value, maximum=maximum)
        key = item.casefold()
        if not item or key in seen:
            continue
        result.append(item)
        seen.add(key)
        if len(result) >= limit:
            break
    return result


def _flatten_strings(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(value, str):
        return [_text(value, maximum=500)]
    if isinstance(value, Mapping):
        return [
            item
            for nested in value.values()
            for item in _flatten_strings(nested, depth=depth + 1)
        ]
    if isinstance(value, (list, tuple)):
        return [
            item
            for nested in value
            for item in _flatten_strings(nested, depth=depth + 1)
        ]
    return []


def _joined(*values: Any, maximum: int = 6_000) -> str:
    return " ".join(
        _text(item, maximum=500)
        for value in values
        for item in _flatten_strings(value)
        if _text(item, maximum=500)
    )[:maximum].casefold()


def _contains(text: str, cues: Sequence[str]) -> bool:
    return any(cue in text for cue in cues)


def _by_id(values: Any, field: str = "candidate_id") -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in _list(values):
        item = _dict(value)
        identifier = _text(item.get(field), maximum=128)
        if identifier:
            result[identifier] = item
    return result


def _explanations_by_id(values: Any) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for value in _list(values):
        item = _dict(value)
        identifier = _text(item.get("candidate_id"), maximum=128)
        if identifier:
            result.setdefault(identifier, []).append(item)
    return result


def _validation_by_id(
    value: Mapping[str, Any] | BaseModel | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    artifact = _artifact(value)
    if not artifact:
        return {}, {}
    collections = (
        artifact.get("results"),
        artifact.get("validations"),
        artifact.get("clips"),
        artifact.get("recommendations"),
    )
    result: dict[str, dict[str, Any]] = {}
    for collection in collections:
        for raw in _list(collection):
            item = _dict(raw)
            identifier = _text(
                item.get("candidate_id") or item.get("clip_id"),
                maximum=128,
            )
            if identifier:
                result[identifier] = item
    direct_id = _text(
        artifact.get("candidate_id") or artifact.get("clip_id"),
        maximum=128,
    )
    if direct_id:
        result[direct_id] = artifact
    return result, artifact


def _find_bool(value: Any, keys: Sequence[str], *, depth: int = 0) -> bool | None:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        for key in keys:
            if key in value and isinstance(value[key], bool):
                return bool(value[key])
        for nested in value.values():
            found = _find_bool(nested, keys, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_bool(nested, keys, depth=depth + 1)
            if found is not None:
                return found
    return None


def _find_number(value: Any, keys: Sequence[str], *, depth: int = 0) -> float | None:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        for key in keys:
            if key in value and value[key] is not None:
                try:
                    return float(value[key])
                except (TypeError, ValueError):
                    pass
        for nested in value.values():
            found = _find_number(nested, keys, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_number(nested, keys, depth=depth + 1)
            if found is not None:
                return found
    return None


def _source_window(value: Mapping[str, Any]) -> BobaSourceWindowV1:
    window = _dict(value.get("source_window"))
    start = max(0.0, _number(window.get("start_seconds") or window.get("start")))
    end = max(start, _number(window.get("end_seconds") or window.get("end"), start))
    duration = _number(window.get("duration_seconds"), end - start)
    duration = max(0.0, min(180.0, duration or end - start))
    if end <= start:
        end = start + duration
    return BobaSourceWindowV1(
        start_seconds=round(start, 3),
        end_seconds=round(end, 3),
        duration_seconds=round(duration, 3),
    )


def _keyword_candidates(*values: Any) -> list[str]:
    candidates: list[str] = []
    for value in values:
        for text in _flatten_strings(value):
            cleaned = _text(text, maximum=240)
            words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", cleaned)
            if 1 <= len(words) <= 4 and len(cleaned) <= 48:
                candidates.append(cleaned)
            candidates.extend(
                word
                for word in words
                if word.casefold() not in _STOPWORDS and len(word) >= 4
            )
    counts = Counter(item.casefold() for item in candidates)
    ordered = sorted(
        enumerate(candidates),
        key=lambda item: (-counts[item[1].casefold()], item[0]),
    )
    return _unique([item for _, item in ordered], limit=8, maximum=48)


def _source_relative(value: float, duration: float) -> float:
    return round(max(0.0, min(duration, value)), 3)


class BobaCaptionRecommendationV1(BobaContract):
    caption_style: BobaCaptionStyle
    caption_density: BobaCaptionDensity
    caption_rhythm: BobaCaptionRhythm
    hook_caption_instruction: str = Field(min_length=1, max_length=700)
    keyword_highlights: list[str] = Field(default_factory=list, max_length=8)
    emotional_emphasis_words: list[str] = Field(default_factory=list, max_length=8)
    payoff_caption_instruction: str = Field(min_length=1, max_length=700)
    readability_notes: list[str] = Field(default_factory=list, max_length=16)
    avoid_this: list[str] = Field(default_factory=list, max_length=16)
    reason: str = Field(min_length=1, max_length=1000)


class BobaMotionRecommendationV1(BobaContract):
    motion_style: BobaMotionStyle
    motion_intensity: BobaMotionIntensity
    zoom_moments: list[str] = Field(default_factory=list, max_length=12)
    punch_in_moments: list[str] = Field(default_factory=list, max_length=12)
    stable_moments: list[str] = Field(default_factory=list, max_length=12)
    layout_safe_moments: list[str] = Field(default_factory=list, max_length=12)
    visual_emphasis_moments: list[str] = Field(default_factory=list, max_length=12)
    payoff_emphasis_moment: str = Field(min_length=1, max_length=700)
    avoid_this: list[str] = Field(default_factory=list, max_length=16)
    reason: str = Field(min_length=1, max_length=1000)


class BobaCaptionMotionTimestampV1(BobaContract):
    start_seconds: float = Field(ge=0.0, le=180.0)
    end_seconds: float = Field(ge=0.0, le=180.0)
    action: str = Field(min_length=1, max_length=180)
    reason: str = Field(min_length=1, max_length=500)
    priority: BobaCaptionMotionPriority

    @model_validator(mode="after")
    def validate_range(self) -> BobaCaptionMotionTimestampV1:
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must not precede start_seconds")
        return self


class BobaCaptionMotionTimingMapV1(BobaContract):
    seconds_0_to_3: str = Field(min_length=1, max_length=800)
    seconds_3_to_10: str = Field(min_length=1, max_length=800)
    middle_section: str = Field(min_length=1, max_length=800)
    payoff_section: str = Field(min_length=1, max_length=800)
    ending_section: str = Field(min_length=1, max_length=800)
    caption_highlight_timestamps: list[BobaCaptionMotionTimestampV1] = Field(
        default_factory=list,
        max_length=16,
    )
    motion_timestamps: list[BobaCaptionMotionTimestampV1] = Field(
        default_factory=list,
        max_length=16,
    )


class BobaCaptionMotionSafetyReviewV1(BobaContract):
    face_cutoff_risk: bool
    multi_speaker_layout_risk: bool
    unavailable_face_signal_risk: bool
    unavailable_layout_signal_risk: bool
    caption_overload_risk: bool
    readability_risk: bool
    over_motion_risk: bool
    under_motion_risk: bool
    hook_distraction_risk: bool
    blockers: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    fixes: list[str] = Field(default_factory=list, max_length=24)


class BobaCaptionMotionScoreV1(BobaContract):
    caption_fit_score: float = Field(ge=0.0, le=100.0)
    caption_readability_score: float = Field(ge=0.0, le=100.0)
    motion_fit_score: float = Field(ge=0.0, le=100.0)
    motion_safety_score: float = Field(ge=0.0, le=100.0)
    hook_support_score: float = Field(ge=0.0, le=100.0)
    retention_support_score: float = Field(ge=0.0, le=100.0)
    overall_recommendation_score: float = Field(ge=0.0, le=100.0)


class BobaCaptionMotionBriefEnhancementV1(BobaContract):
    brief_id: str = Field(min_length=1, max_length=160)
    improved_caption_instruction: str = Field(min_length=1, max_length=1000)
    improved_motion_instruction: str = Field(min_length=1, max_length=1000)
    keyword_highlights: list[str] = Field(default_factory=list, max_length=8)
    zoom_notes: list[str] = Field(default_factory=list, max_length=12)
    punch_in_notes: list[str] = Field(default_factory=list, max_length=12)
    layout_safe_warning: str = Field(min_length=1, max_length=700)
    readability_warning: str = Field(min_length=1, max_length=700)
    apply_suggestion: Literal[False] = False


class BobaCaptionMotionSignalUsageV1(BobaContract):
    clip_briefs_used: bool
    hook_retention_used: bool
    creative_direction_used: bool
    editorial_decision_used: bool
    clip_ranking_used: bool
    candidate_discovery_used: bool
    whole_video_understanding_used: bool
    explanation_used: bool
    face_motion_validation_used: bool
    multi_speaker_validation_used: bool
    analysis_signals_used: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCaptionMotionRecommendationV1(BobaContract):
    recommendation_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    source_window: BobaSourceWindowV1
    caption_recommendation: BobaCaptionRecommendationV1
    motion_recommendation: BobaMotionRecommendationV1
    timing_map: BobaCaptionMotionTimingMapV1
    safety_review: BobaCaptionMotionSafetyReviewV1
    recommendation_score: BobaCaptionMotionScoreV1
    brief_enhancement: BobaCaptionMotionBriefEnhancementV1
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaCaptionMotionRecommendationSetV1(BobaContract):
    schema_version: Literal["boba_caption_motion_recommendation_brain_v1"] = (
        "boba_caption_motion_recommendation_brain_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    recommendations: list[BobaCaptionMotionRecommendationV1] = Field(
        default_factory=list,
        max_length=60,
    )
    project_caption_motion_summary: str = Field(min_length=1, max_length=1500)
    signal_usage: BobaCaptionMotionSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaCaptionMotionRecommendationBrainV1:
    """Create local advisory caption and motion guidance without changing media."""

    def analyze(
        self,
        *,
        project_id: str,
        clip_briefs: Mapping[str, Any] | BaseModel | None,
        hook_retention: Mapping[str, Any] | BaseModel | None = None,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None = None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        face_motion_validation: Mapping[str, Any] | BaseModel | None = None,
        multi_speaker_validation: Mapping[str, Any] | BaseModel | None = None,
        analysis_signals: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaCaptionMotionRecommendationSetV1:
        briefs = _artifact(clip_briefs)
        if not briefs:
            raise ValidationError(
                "BOBA Caption + Motion Brain requires saved clip briefs.",
                details={
                    "project_id": project_id,
                    "required_artifact": "clip_briefs",
                },
            )
        self._validate_project(project_id, briefs, "clip_briefs")

        hook = _artifact(hook_retention)
        creative = _artifact(creative_direction_v2)
        editorial = _artifact(editorial_decisions)
        ranking = _artifact(clip_ranking)
        discovery = _artifact(candidate_discovery)
        understanding = _artifact(whole_video_understanding)
        explanation_set = _artifact(explanations)
        face_validation = _artifact(face_motion_validation)
        speaker_validation = _artifact(multi_speaker_validation)
        analysis = _artifact(analysis_signals)
        memory_data = _artifact(memory)
        for artifact, label in (
            (hook, "hook_retention"),
            (creative, "creative_direction_v2"),
            (editorial, "editorial_decisions"),
            (ranking, "clip_ranking"),
            (discovery, "candidate_discovery"),
            (understanding, "whole_video_understanding"),
            (explanation_set, "explanations"),
            (memory_data, "memory"),
        ):
            self._validate_project(project_id, artifact, label)

        hook_by_id = _by_id(hook.get("analyses"))
        creative_by_id = _by_id(creative.get("clip_directions"))
        editorial_by_id = _by_id(editorial.get("decisions"))
        ranking_by_id = _by_id(ranking.get("ranked_candidates"))
        discovery_by_id = _by_id(discovery.get("candidates"))
        explanations_by_id = _explanations_by_id(
            explanation_set.get("candidate_explanations")
        )
        face_by_id, face_global = _validation_by_id(face_validation)
        speaker_by_id, speaker_global = _validation_by_id(speaker_validation)
        face_default = face_global if not face_by_id else {}
        speaker_default = speaker_global if not speaker_by_id else {}

        recommendations: list[BobaCaptionMotionRecommendationV1] = []
        brief_values = [
            *_list(briefs.get("selected_briefs")),
            *_list(briefs.get("backup_briefs")),
        ]
        for value in brief_values[:60]:
            brief = _dict(value)
            candidate_id = _text(brief.get("candidate_id"), maximum=128)
            if not candidate_id:
                continue
            recommendations.append(
                self._recommend(
                    project_id=project_id,
                    brief=brief,
                    hook=hook_by_id.get(candidate_id, {}),
                    creative=creative_by_id.get(candidate_id, {}),
                    editorial=editorial_by_id.get(candidate_id, {}),
                    ranking=ranking_by_id.get(candidate_id, {}),
                    discovery=discovery_by_id.get(candidate_id, {}),
                    understanding=understanding,
                    explanations=explanations_by_id.get(candidate_id, []),
                    face_validation=face_by_id.get(candidate_id, face_default),
                    speaker_validation=speaker_by_id.get(
                        candidate_id,
                        speaker_default,
                    ),
                    analysis=analysis,
                    memory=memory_data,
                )
            )

        optional = (
            (bool(hook), "hook_retention"),
            (bool(creative), "creative_direction_v2"),
            (bool(editorial), "editorial_decisions"),
            (bool(ranking), "clip_ranking"),
            (bool(discovery), "candidate_discovery"),
            (bool(understanding), "whole_video_understanding"),
            (bool(explanation_set), "explanations"),
            (bool(face_validation), "face_motion_validation"),
            (bool(speaker_validation), "multi_speaker_validation"),
            (bool(analysis), "analysis_signals"),
            (bool(memory_data), "memory"),
        )
        unavailable = [label for available, label in optional if not available]
        usage = BobaCaptionMotionSignalUsageV1(
            clip_briefs_used=True,
            hook_retention_used=bool(hook),
            creative_direction_used=bool(creative),
            editorial_decision_used=bool(editorial),
            clip_ranking_used=bool(ranking),
            candidate_discovery_used=bool(discovery),
            whole_video_understanding_used=bool(understanding),
            explanation_used=bool(explanation_set),
            face_motion_validation_used=bool(face_validation),
            multi_speaker_validation_used=bool(speaker_validation),
            analysis_signals_used=bool(analysis),
            memory_used=bool(memory_data),
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=_unique(
                [
                    *(
                        [
                            "Missing optional signals lower confidence; recommendations "
                            "fall back to conservative advisory guidance."
                        ]
                        if unavailable
                        else []
                    ),
                    *(
                        [
                            "Face and speaker metadata is used only for anonymous layout "
                            "safety; no identity inference is performed."
                        ]
                        if face_validation or speaker_validation
                        else []
                    ),
                ],
                limit=32,
            ),
        )
        warnings = _unique(
            [
                *(
                    [
                        "No selected or backup clip briefs were available; no "
                        "recommendations were fabricated."
                    ]
                    if not recommendations
                    else []
                ),
                *(
                    [
                        "Optional BOBA or validation artifacts were unavailable; "
                        "conservative fallbacks were used."
                    ]
                    if unavailable
                    else []
                ),
                *_list(briefs.get("warnings")),
            ],
            limit=64,
            maximum=700,
        )
        return BobaCaptionMotionRecommendationSetV1(
            project_id=project_id,
            source_id=_text(
                briefs.get("source_id")
                or hook.get("source_id")
                or creative.get("source_id")
                or editorial.get("source_id")
                or ranking.get("source_id")
                or discovery.get("source_id")
                or understanding.get("source_id"),
                maximum=512,
            ),
            recommendations=recommendations,
            project_caption_motion_summary=self._project_summary(recommendations),
            signal_usage=usage,
            warnings=warnings,
            limitations=[
                "Caption + Motion Recommendation Brain V1 is advisory metadata; it does "
                "not edit, render, download, or inspect raw media.",
                "Recommendations do not override Olympus caption, motion, face-tracking, "
                "or multi-speaker execution plans.",
                "Face and speaker inputs are anonymous safety metadata only; no person "
                "identification or biometric profile is stored.",
                "Scores describe fit against saved local signals, not viewer-performance "
                "predictions or guarantees.",
                "A human must verify source wording, readability, framing, motion safety, "
                "rights, and the final rendered output.",
            ],
        )

    def analyze_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        clip_briefs: Mapping[str, Any] | BaseModel | None = None,
        hook_retention: Mapping[str, Any] | BaseModel | None = None,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None = None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        face_motion_validation: Mapping[str, Any] | BaseModel | None = None,
        multi_speaker_validation: Mapping[str, Any] | BaseModel | None = None,
        analysis_signals: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaCaptionMotionRecommendationSetV1:
        return self.analyze(
            project_id=project_id,
            clip_briefs=clip_briefs or _dict(signals.get("clip_briefs")),
            hook_retention=hook_retention or _dict(signals.get("hook_retention")),
            creative_direction_v2=(
                creative_direction_v2 or _dict(signals.get("creative_direction_v2"))
            ),
            editorial_decisions=(
                editorial_decisions or _dict(signals.get("editorial_decisions"))
            ),
            clip_ranking=clip_ranking or _dict(signals.get("clip_ranking")),
            candidate_discovery=(
                candidate_discovery or _dict(signals.get("candidate_clip_discovery"))
            ),
            whole_video_understanding=(
                whole_video_understanding
                or _dict(signals.get("whole_video_understanding"))
            ),
            explanations=explanations or _dict(signals.get("explanations")),
            face_motion_validation=(
                face_motion_validation or _dict(signals.get("face_motion_validation"))
            ),
            multi_speaker_validation=(
                multi_speaker_validation
                or _dict(signals.get("multi_speaker_validation"))
            ),
            analysis_signals=(
                analysis_signals or _dict(signals.get("analysis_signals_v2"))
            ),
            memory=memory or _dict(signals.get("project_memory")),
        )

    def _recommend(
        self,
        *,
        project_id: str,
        brief: dict[str, Any],
        hook: dict[str, Any],
        creative: dict[str, Any],
        editorial: dict[str, Any],
        ranking: dict[str, Any],
        discovery: dict[str, Any],
        understanding: dict[str, Any],
        explanations: list[dict[str, Any]],
        face_validation: dict[str, Any],
        speaker_validation: dict[str, Any],
        analysis: dict[str, Any],
        memory: dict[str, Any],
    ) -> BobaCaptionMotionRecommendationV1:
        candidate_id = _text(brief.get("candidate_id"), maximum=128)
        brief_id = _text(
            brief.get("brief_id") or f"brief_{candidate_id}",
            maximum=160,
        )
        source_window = _source_window(brief)
        hook_analysis = _dict(hook.get("hook_analysis"))
        hook_risks = _dict(hook.get("retention_risk_review"))
        hook_scores = _dict(hook.get("retention_score"))
        retention_plan = _dict(hook.get("retention_plan"))
        caption_direction = _dict(creative.get("caption_direction"))
        motion_direction = _dict(creative.get("motion_direction"))
        creative_hook = _dict(creative.get("hook_treatment"))
        editorial_risk = _dict(editorial.get("risk_review"))
        score_breakdown = _dict(ranking.get("score_breakdown"))

        classification_text = _joined(
            brief.get("brief_title"),
            brief.get("final_clip_angle"),
            brief.get("target_viewer_feeling"),
            _dict(brief.get("hook_instruction")).get("summary"),
            hook_analysis.get("hook_type"),
            hook_analysis.get("opening_line_direction"),
            creative_hook.get("hook_type"),
            creative_hook.get("opening_line_direction"),
            editorial.get("final_story_angle"),
            editorial.get("final_hook_strategy"),
            ranking.get("candidate_type"),
            ranking.get("suggested_title"),
            discovery.get("candidate_type"),
            discovery.get("hook_idea"),
        )
        warning_text = _joined(
            brief.get("warnings"),
            brief.get("human_review_notes"),
            brief.get("risk_fixes"),
            hook_risks,
            creative.get("warnings"),
            caption_direction.get("warnings"),
            motion_direction.get("safety_warnings"),
            editorial_risk,
            ranking.get("risk_warnings"),
            face_validation.get("warnings"),
            face_validation.get("errors"),
            speaker_validation.get("warnings"),
            speaker_validation.get("errors"),
            memory.get("warnings"),
        )
        hook_type = _text(
            hook_analysis.get("hook_type")
            or creative_hook.get("hook_type")
            or editorial.get("final_hook_strategy")
            or discovery.get("candidate_type")
            or "unknown",
            maximum=80,
        ).casefold()
        pacing = _text(
            editorial.get("pacing_intensity")
            or _dict(creative.get("pacing_map")).get("pacing_intensity")
            or "moderate",
            maximum=80,
        ).casefold()
        emotional = _contains(classification_text, _EMOTIONAL_CUES) or hook_type in {
            "emotional_reveal",
            "motivational_payoff",
        }
        explicit_high_energy = _contains(classification_text, _HIGH_ENERGY_CUES)
        high_energy = (
            explicit_high_energy
            or (
                not emotional
                and (
                    pacing in {"fast", "aggressive", "high", "punchy"}
                    or hook_type in {"humor", "shocking_truth", "contradiction"}
                )
            )
        )
        educational = (
            _contains(classification_text, _EDUCATIONAL_CUES)
            or hook_type
            in {
                "educational_open_loop",
                "direct_value",
                "problem_solution",
            }
        ) and not (emotional or high_energy)
        calm = _contains(classification_text, _CALM_CUES) or pacing in {
            "calm",
            "restrained",
            "slow",
        }
        transcript_available = _find_bool(
            analysis,
            ("transcript_available", "speech_transcript_available"),
        )
        if transcript_available is None:
            transcript_available = not _contains(warning_text, ("transcript unavailable",))

        caption_overload = bool(hook_risks.get("caption_overload_risk")) or _contains(
            warning_text,
            _CAPTION_OVERLOAD_CUES,
        )
        readability_risk = (
            not transcript_available
            or _contains(warning_text, _READABILITY_CUES)
            or bool(editorial_risk.get("visual_layout_risk"))
        )

        face_available = bool(face_validation) or bool(
            _find_bool(
                analysis,
                ("face_signals_available", "face_tracking_available"),
            )
        )
        layout_available = bool(speaker_validation) or bool(
            _find_bool(
                analysis,
                (
                    "layout_signals_available",
                    "speaker_signals_available",
                    "multi_speaker_layout_available",
                ),
            )
        )
        face_cutoff = bool(
            _find_bool(face_validation, ("face_cutoff_detected", "face_cutoff_risk"))
        )
        safe_zone_ratio = _find_number(
            face_validation,
            ("face_inside_safe_zone_ratio", "safe_zone_coverage_ratio"),
        )
        if safe_zone_ratio is not None and safe_zone_ratio < 0.85:
            face_cutoff = True
        speaker_count = _find_number(
            speaker_validation,
            (
                "detected_speaker_count",
                "speaker_count_detected",
                "face_count_detected",
                "detected_face_count",
            ),
        )
        layout_mode = _text(
            speaker_validation.get("layout_strategy")
            or speaker_validation.get("applied_mode")
            or _dict(speaker_validation.get("layout_decision")).get("mode"),
            maximum=80,
        ).casefold()
        speaker_passed = _find_bool(speaker_validation, ("passed",))
        wrong_focus = bool(
            _list(speaker_validation.get("wrong_speaker_focus_warnings"))
        ) or bool(
            _find_bool(speaker_validation, ("wrong_speaker_focus_detected",))
        )
        multi_speaker_risk = bool(
            speaker_count is not None
            and speaker_count >= 2
            and (
                speaker_passed is False
                or layout_mode in {"center_fallback", "unknown", ""}
                or wrong_focus
            )
        )
        multi_speaker_risk = multi_speaker_risk or bool(
            _find_bool(
                speaker_validation,
                ("multi_speaker_layout_risk", "face_cutoff_detected"),
            )
        )
        unavailable_face = not face_available
        unavailable_layout = not layout_available
        over_motion = (
            bool(hook_risks.get("over_editing_risk"))
            or _contains(warning_text, _OVER_MOTION_CUES)
            or (
                _text(editorial.get("motion_style"), maximum=80)
                in {"high_motion", "dynamic_zoom"}
                and (face_cutoff or multi_speaker_risk or unavailable_face)
            )
        )
        weak_hook = bool(hook_risks.get("under_editing_risk")) or _points(
            hook_scores.get("hook_score"),
            60.0,
        ) < 55.0

        caption = self._caption_recommendation(
            brief=brief,
            hook=hook,
            creative=creative,
            editorial=editorial,
            ranking=ranking,
            discovery=discovery,
            explanations=explanations,
            understanding=understanding,
            educational=educational,
            emotional=emotional,
            high_energy=high_energy,
            caption_overload=caption_overload,
            readability_risk=readability_risk,
            transcript_available=transcript_available,
        )
        motion = self._motion_recommendation(
            creative=creative,
            editorial=editorial,
            hook=hook,
            educational=educational,
            emotional=emotional,
            high_energy=high_energy,
            calm=calm,
            strong_hook=_points(hook_scores.get("hook_score"), 60.0) >= 72.0,
            strong_payoff=(
                _points(hook_scores.get("payoff_score"), 60.0) >= 70.0
                or discovery.get("payoff_present") is True
            ),
            face_cutoff=face_cutoff,
            multi_speaker_risk=multi_speaker_risk,
            unavailable_face=unavailable_face,
            unavailable_layout=unavailable_layout,
        )
        hook_distraction = bool(
            caption_overload
            and motion.motion_intensity in {"moderate", "high"}
        ) or bool(
            face_cutoff
            and motion.motion_style in {"dynamic_zoom", "punch_in", "high_motion"}
        )
        under_motion = bool(
            weak_hook
            and motion.motion_style in {"stable", "minimal_motion"}
            and not (face_cutoff or multi_speaker_risk)
        )
        safety = self._safety_review(
            face_cutoff=face_cutoff,
            multi_speaker_risk=multi_speaker_risk,
            unavailable_face=unavailable_face,
            unavailable_layout=unavailable_layout,
            caption_overload=caption_overload,
            readability_risk=readability_risk,
            over_motion=over_motion,
            under_motion=under_motion,
            hook_distraction=hook_distraction,
        )
        timing = self._timing_map(
            duration=source_window.duration_seconds,
            caption=caption,
            motion=motion,
            retention_plan=retention_plan,
            strong_payoff=(
                _points(hook_scores.get("payoff_score"), 60.0) >= 70.0
                or discovery.get("payoff_present") is True
            ),
        )
        scores = self._scores(
            educational=educational,
            emotional=emotional,
            high_energy=high_energy,
            caption=caption,
            motion=motion,
            safety=safety,
            hook_scores=hook_scores,
            ranking_scores=score_breakdown,
        )
        enhancement = BobaCaptionMotionBriefEnhancementV1(
            brief_id=brief_id,
            improved_caption_instruction=(
                f"Use {caption.caption_style.replace('_', ' ')} at "
                f"{caption.caption_density} density with "
                f"{caption.caption_rhythm} rhythm. {caption.hook_caption_instruction} "
                f"{caption.payoff_caption_instruction}"
            ),
            improved_motion_instruction=(
                f"Use {motion.motion_style.replace('_', ' ')} at "
                f"{motion.motion_intensity} intensity. {motion.reason}"
            ),
            keyword_highlights=caption.keyword_highlights,
            zoom_notes=motion.zoom_moments,
            punch_in_notes=motion.punch_in_moments,
            layout_safe_warning=(
                "Use only stable or layout-safe framing until anonymous face and "
                "multi-speaker layout checks pass."
                if unavailable_face
                or unavailable_layout
                or face_cutoff
                or multi_speaker_risk
                else "No layout blocker is present in supplied metadata; verify source "
                "frames before applying any crop."
            ),
            readability_warning=(
                "Readability risk is present; verify exact transcript wording, contrast, "
                "line length, timing, and safe-zone placement."
                if readability_risk or caption_overload
                else "Verify wording, timing, contrast, and safe-zone placement against "
                "the source before approval."
            ),
        )
        missing_count = sum(
            not available
            for available in (
                bool(hook),
                bool(creative),
                bool(editorial),
                bool(ranking),
                bool(discovery),
                bool(understanding),
                bool(explanations),
                bool(face_validation),
                bool(speaker_validation),
                bool(analysis),
            )
        )
        confidence = max(
            0.2,
            min(
                0.96,
                _unit(brief.get("confidence"), 0.62)
                + 0.025 * (10 - missing_count)
                - 0.035 * missing_count
                - (0.08 if safety.blockers else 0.0),
            ),
        )
        warnings = _unique(
            [
                *safety.warnings,
                *_list(brief.get("warnings")),
                *_list(creative.get("warnings")),
            ],
            limit=32,
            maximum=700,
        )
        return BobaCaptionMotionRecommendationV1(
            recommendation_id=f"caption_motion_{candidate_id}",
            project_id=project_id,
            candidate_id=candidate_id,
            brief_id=brief_id,
            source_window=source_window,
            caption_recommendation=caption,
            motion_recommendation=motion,
            timing_map=timing,
            safety_review=safety,
            recommendation_score=scores,
            brief_enhancement=enhancement,
            confidence=round(confidence, 4),
            warnings=warnings,
            limitations=[
                "Timing is clip-relative advisory metadata and is not an executable "
                "Olympus edit timeline.",
                "Caption wording is not copied from a full transcript and must be checked "
                "against source speech.",
                "Motion safety depends on supplied anonymous validation metadata and "
                "requires final render review.",
            ],
        )

    @staticmethod
    def _caption_recommendation(
        *,
        brief: dict[str, Any],
        hook: dict[str, Any],
        creative: dict[str, Any],
        editorial: dict[str, Any],
        ranking: dict[str, Any],
        discovery: dict[str, Any],
        explanations: list[dict[str, Any]],
        understanding: dict[str, Any],
        educational: bool,
        emotional: bool,
        high_energy: bool,
        caption_overload: bool,
        readability_risk: bool,
        transcript_available: bool,
    ) -> BobaCaptionRecommendationV1:
        hook_analysis = _dict(hook.get("hook_analysis"))
        retention_plan = _dict(hook.get("retention_plan"))
        caption_direction = _dict(creative.get("caption_direction"))
        caption_instruction = _dict(brief.get("caption_instruction"))
        opening_instruction = _dict(brief.get("opening_three_second_instruction"))

        if not transcript_available:
            style: BobaCaptionStyle = "no_captions"
        elif caption_overload:
            style = "minimal"
        elif high_energy:
            style = (
                "punchline_caption"
                if "humor" in _joined(hook_analysis, brief)
                else "bold_hook_captions"
            )
        elif emotional:
            style = (
                "clean_subtitles"
                if readability_risk
                else "emotional_emphasis"
            )
        elif educational:
            educational_text = _joined(
                brief.get("final_clip_angle"),
                discovery.get("candidate_type"),
                discovery.get("hook_idea"),
            )
            style = (
                "educational_steps"
                if _contains(educational_text, ("step", "how to", "framework", "list"))
                else "keyword_highlight"
            )
        else:
            requested = _text(
                caption_direction.get("style") or editorial.get("caption_style"),
                maximum=80,
            )
            style = (
                cast(BobaCaptionStyle, requested)
                if requested
                in {
                    "clean_subtitles",
                    "bold_hook_captions",
                    "keyword_highlight",
                    "emotional_emphasis",
                    "minimal",
                }
                else "clean_subtitles"
            )

        if caption_overload or emotional:
            density: BobaCaptionDensity = "low"
        elif high_energy and _number(
            _dict(hook.get("retention_score")).get("overall_retention_score"),
            60.0,
        ) >= 75.0:
            density = "high"
        else:
            density = "medium"
        if high_energy:
            rhythm: BobaCaptionRhythm = "punchy"
        elif emotional:
            rhythm = "calm"
        elif _text(editorial.get("pacing_intensity"), maximum=80) in {
            "fast",
            "aggressive",
        }:
            rhythm = "fast"
        else:
            rhythm = "normal"
        if caption_overload and rhythm in {"fast", "punchy"}:
            rhythm = "normal"

        keywords = _keyword_candidates(
            caption_direction.get("emphasis_words"),
            hook_analysis.get("improved_hook_direction"),
            hook_analysis.get("opening_line_direction"),
            _dict(hook.get("brief_enhancements")).get("enhanced_caption_hook"),
            opening_instruction.get("summary"),
            caption_instruction.get("summary"),
            brief.get("brief_title"),
            brief.get("final_clip_angle"),
            ranking.get("suggested_title"),
            discovery.get("hook_idea"),
            explanations,
            understanding.get("primary_topics"),
        )
        emotion_keywords = (
            _keyword_candidates(
                brief.get("target_viewer_feeling"),
                understanding.get("emotional_beats"),
                explanations,
            )[:6]
            if emotional
            else []
        )
        readability_notes = [
            "Keep one or two high-contrast lines inside vertical-safe margins.",
            "Highlight selectively and verify every displayed word against source speech.",
        ]
        if readability_risk:
            readability_notes.append(
                "Source or layout evidence is incomplete; verify timing, line breaks, "
                "contrast, faces, and existing on-screen text."
            )
        if style == "no_captions":
            readability_notes.append(
                "Do not fabricate captions without a verified transcript; use a human "
                "transcription review before enabling them."
            )
        avoid = [
            "Do not display full transcript paragraphs or emphasize every spoken word.",
            "Do not cover faces, mouths, existing text, or the primary visual subject.",
        ]
        if caption_overload:
            avoid.append("Do not use dense word-by-word captions in this clip.")
        clip_intent = (
            "educational"
            if educational
            else "emotional"
            if emotional
            else "high-energy"
            if high_energy
            else "general"
        )
        return BobaCaptionRecommendationV1(
            caption_style=style,
            caption_density=density,
            caption_rhythm=rhythm,
            hook_caption_instruction=(
                _text(
                    _dict(hook.get("brief_enhancements")).get("enhanced_caption_hook")
                    or hook_analysis.get("improved_hook_direction")
                    or caption_instruction.get("do_this")
                    or "Emphasize the clearest supported hook phrase in the first three "
                    "seconds.",
                    maximum=700,
                )
            ),
            keyword_highlights=keywords,
            emotional_emphasis_words=emotion_keywords,
            payoff_caption_instruction=_text(
                retention_plan.get("payoff_timing_strategy")
                or _dict(creative.get("retention_plan")).get("payoff_reinforcement")
                or "Hold the decisive payoff phrase long enough to read, then return to "
                "clean styling.",
                maximum=700,
            ),
            readability_notes=readability_notes,
            avoid_this=avoid,
            reason=(
                f"The {style.replace('_', ' ')} recommendation balances the saved "
                f"{clip_intent} "
                "clip intent, hook support, pacing, and readability risk."
            ),
        )

    @staticmethod
    def _motion_recommendation(
        *,
        creative: dict[str, Any],
        editorial: dict[str, Any],
        hook: dict[str, Any],
        educational: bool,
        emotional: bool,
        high_energy: bool,
        calm: bool,
        strong_hook: bool,
        strong_payoff: bool,
        face_cutoff: bool,
        multi_speaker_risk: bool,
        unavailable_face: bool,
        unavailable_layout: bool,
    ) -> BobaMotionRecommendationV1:
        unsafe_layout = face_cutoff or multi_speaker_risk
        missing_layout_truth = unavailable_face or unavailable_layout
        if unsafe_layout:
            style: BobaMotionStyle = "layout_safe"
            intensity: BobaMotionIntensity = "light"
        elif missing_layout_truth:
            style = "stable"
            intensity = "none"
        elif high_energy:
            style = "dynamic_zoom"
            intensity = "high" if strong_hook else "moderate"
        elif emotional or calm:
            style = "subtle_zoom"
            intensity = "light"
        elif educational:
            style = "subtle_zoom" if strong_hook else "stable"
            intensity = "light" if strong_hook else "none"
        elif strong_hook:
            style = "punch_in"
            intensity = "moderate"
        else:
            requested = _text(
                _dict(creative.get("motion_direction")).get("style")
                or editorial.get("motion_style"),
                maximum=80,
            )
            style = (
                cast(BobaMotionStyle, requested)
                if requested
                in {
                    "stable",
                    "subtle_zoom",
                    "dynamic_zoom",
                    "punch_in",
                    "layout_safe",
                    "high_motion",
                    "minimal_motion",
                }
                else "stable"
            )
            intensity = (
                "high"
                if style == "high_motion"
                else "moderate"
                if style in {"dynamic_zoom", "punch_in"}
                else "light"
                if style == "subtle_zoom"
                else "none"
            )

        zoom_moments: list[str] = []
        punch_moments: list[str] = []
        if style in {"subtle_zoom", "dynamic_zoom", "high_motion"}:
            zoom_moments.append(
                "Use one controlled opening zoom on the supported hook, then settle."
            )
        if style in {"punch_in", "dynamic_zoom", "high_motion"} and strong_hook:
            punch_moments.append(
                "Use one brief punch-in on the strongest opening hook word."
            )
        if strong_payoff and style not in {"stable", "layout_safe", "minimal_motion"}:
            zoom_moments.append(
                "Use a restrained payoff emphasis, then return to stable framing."
            )
        stable_moments = [
            "Keep framing stable while context is established.",
            "Keep the final line stable so the payoff remains readable.",
        ]
        layout_safe_moments = (
            [
                "Use full-frame or validated layout-safe framing throughout.",
                "Do not switch crops during uncertain speaker or face intervals.",
            ]
            if unsafe_layout or missing_layout_truth
            else ["Re-check face and text safe zones before each crop or zoom."]
        )
        visual_emphasis = _unique(
            [
                *_list(_dict(creative.get("motion_direction")).get("visual_emphasis_moments")),
                *_list(editorial.get("visual_emphasis")),
                "Support the opening hook with one purposeful visual emphasis.",
                *(
                    ["Support the payoff with a restrained emphasis."]
                    if strong_payoff
                    else []
                ),
            ],
            limit=12,
            maximum=500,
        )
        avoid = [
            "Do not use constant zoom, jitter, random reframing, or motion on every caption.",
            "Do not infer a speaker identity or move a crop without verified layout evidence.",
        ]
        if unsafe_layout or missing_layout_truth:
            avoid.append(
                "Do not use face-dependent punch-ins or dynamic crops until layout "
                "validation passes."
            )
        return BobaMotionRecommendationV1(
            motion_style=style,
            motion_intensity=intensity,
            zoom_moments=zoom_moments,
            punch_in_moments=punch_moments,
            stable_moments=stable_moments,
            layout_safe_moments=layout_safe_moments,
            visual_emphasis_moments=visual_emphasis,
            payoff_emphasis_moment=(
                "Hold stable on the complete payoff; use only one restrained emphasis "
                "if layout safety is verified."
                if strong_payoff
                else "Keep the ending stable and avoid inventing a payoff emphasis."
            ),
            avoid_this=avoid,
            reason=(
                f"The {style.replace('_', ' ')} recommendation matches the saved hook "
                "and emotional pacing while deferring to anonymous face and "
                "multi-speaker safety metadata."
            ),
        )

    @staticmethod
    def _safety_review(
        *,
        face_cutoff: bool,
        multi_speaker_risk: bool,
        unavailable_face: bool,
        unavailable_layout: bool,
        caption_overload: bool,
        readability_risk: bool,
        over_motion: bool,
        under_motion: bool,
        hook_distraction: bool,
    ) -> BobaCaptionMotionSafetyReviewV1:
        blockers = _unique(
            [
                *(
                    ["Dynamic face-dependent reframing is blocked by face cutoff risk."]
                    if face_cutoff
                    else []
                ),
                *(
                    [
                        "Dynamic crop switching is blocked until multi-speaker layout "
                        "safety is verified."
                    ]
                    if multi_speaker_risk
                    else []
                ),
            ],
            limit=24,
        )
        warnings = _unique(
            [
                *(
                    [
                        "Face safety metadata is unavailable; prefer stable framing and "
                        "human frame review."
                    ]
                    if unavailable_face
                    else []
                ),
                *(
                    [
                        "Layout safety metadata is unavailable; prefer stable or "
                        "layout-safe framing."
                    ]
                    if unavailable_layout
                    else []
                ),
                *(
                    ["Caption density may exceed readable limits."]
                    if caption_overload
                    else []
                ),
                *(
                    ["Caption wording or placement requires additional readability review."]
                    if readability_risk
                    else []
                ),
                *(
                    ["Requested motion may be excessive for the available safety evidence."]
                    if over_motion
                    else []
                ),
                *(
                    ["The weak hook may need one safe visual emphasis."]
                    if under_motion
                    else []
                ),
                *(
                    ["Opening captions and motion may compete with the hook message."]
                    if hook_distraction
                    else []
                ),
            ],
            limit=32,
        )
        fixes = _unique(
            [
                *(
                    ["Reduce captions to one or two short phrase groups."]
                    if caption_overload
                    else []
                ),
                *(
                    [
                        "Verify transcript wording, contrast, line breaks, timing, and "
                        "vertical safe-zone placement."
                    ]
                    if readability_risk
                    else []
                ),
                *(
                    [
                        "Use full-frame, center-safe, or validated multi-speaker framing "
                        "until anonymous face/layout checks pass."
                    ]
                    if face_cutoff
                    or multi_speaker_risk
                    or unavailable_face
                    or unavailable_layout
                    else []
                ),
                *(
                    ["Limit motion to one hook cue and one optional payoff cue."]
                    if over_motion or hook_distraction
                    else []
                ),
                *(
                    ["Add one restrained caption or visual emphasis rather than rapid motion."]
                    if under_motion
                    else []
                ),
            ],
            limit=24,
        )
        return BobaCaptionMotionSafetyReviewV1(
            face_cutoff_risk=face_cutoff,
            multi_speaker_layout_risk=multi_speaker_risk,
            unavailable_face_signal_risk=unavailable_face,
            unavailable_layout_signal_risk=unavailable_layout,
            caption_overload_risk=caption_overload,
            readability_risk=readability_risk,
            over_motion_risk=over_motion,
            under_motion_risk=under_motion,
            hook_distraction_risk=hook_distraction,
            blockers=blockers,
            warnings=warnings,
            fixes=fixes,
        )

    @staticmethod
    def _timing_map(
        *,
        duration: float,
        caption: BobaCaptionRecommendationV1,
        motion: BobaMotionRecommendationV1,
        retention_plan: dict[str, Any],
        strong_payoff: bool,
    ) -> BobaCaptionMotionTimingMapV1:
        duration = max(0.1, min(180.0, duration))
        hook_end = _source_relative(min(3.0, duration), duration)
        context_start = hook_end
        context_end = _source_relative(min(10.0, duration), duration)
        payoff_start = _source_relative(max(context_end, duration - 5.0), duration)
        ending_start = _source_relative(max(payoff_start, duration - 2.0), duration)

        caption_timestamps = [
            BobaCaptionMotionTimestampV1(
                start_seconds=0.0,
                end_seconds=hook_end,
                action="emphasize_hook_caption",
                reason=_text(caption.hook_caption_instruction, maximum=500),
                priority="required",
            )
        ]
        if context_end > context_start:
            caption_timestamps.append(
                BobaCaptionMotionTimestampV1(
                    start_seconds=context_start,
                    end_seconds=context_end,
                    action="reduce_caption_emphasis",
                    reason="Establish context with readable phrase groups.",
                    priority="recommended",
                )
            )
        if duration > payoff_start:
            caption_timestamps.append(
                BobaCaptionMotionTimestampV1(
                    start_seconds=payoff_start,
                    end_seconds=duration,
                    action="highlight_payoff",
                    reason=_text(caption.payoff_caption_instruction, maximum=500),
                    priority="required" if strong_payoff else "optional",
                )
            )

        motion_timestamps: list[BobaCaptionMotionTimestampV1] = []
        if motion.motion_style not in {"stable", "layout_safe", "minimal_motion"}:
            motion_timestamps.append(
                BobaCaptionMotionTimestampV1(
                    start_seconds=0.0,
                    end_seconds=_source_relative(min(1.25, duration), duration),
                    action=(
                        "opening_punch_in"
                        if motion.punch_in_moments
                        else "opening_controlled_zoom"
                    ),
                    reason=(
                        _text(motion.punch_in_moments[0], maximum=500)
                        if motion.punch_in_moments
                        else _text(motion.zoom_moments[0], maximum=500)
                    ),
                    priority="recommended",
                )
            )
        if context_end > min(1.25, duration):
            motion_timestamps.append(
                BobaCaptionMotionTimestampV1(
                    start_seconds=_source_relative(min(1.25, duration), duration),
                    end_seconds=context_end,
                    action="hold_stable",
                    reason="Stop opening motion and preserve context readability.",
                    priority="required",
                )
            )
        if duration > payoff_start:
            motion_timestamps.append(
                BobaCaptionMotionTimestampV1(
                    start_seconds=payoff_start,
                    end_seconds=ending_start,
                    action=(
                        "restrained_payoff_emphasis"
                        if strong_payoff
                        and motion.motion_style not in {"stable", "layout_safe"}
                        else "hold_stable_for_payoff"
                    ),
                    reason=_text(motion.payoff_emphasis_moment, maximum=500),
                    priority="recommended",
                )
            )
        motion_timestamps.append(
            BobaCaptionMotionTimestampV1(
                start_seconds=ending_start,
                end_seconds=duration,
                action="stop_motion_and_hold_ending",
                reason="Keep the complete final thought readable and support replay.",
                priority="required",
            )
        )
        return BobaCaptionMotionTimingMapV1(
            seconds_0_to_3=_text(
                retention_plan.get("seconds_0_to_3")
                or "Support the saved hook with one selective caption emphasis and no "
                "competing motion.",
                maximum=800,
            ),
            seconds_3_to_10=_text(
                retention_plan.get("seconds_3_to_10")
                or "Reduce styling intensity, establish context, and keep framing stable.",
                maximum=800,
            ),
            middle_section=_text(
                retention_plan.get("middle_hold_strategy")
                or "Use readable captions and only meaning-led visual emphasis.",
                maximum=800,
            ),
            payoff_section=_text(
                retention_plan.get("payoff_timing_strategy")
                or "Emphasize the complete payoff phrase without cutting or distracting.",
                maximum=800,
            ),
            ending_section=_text(
                retention_plan.get("ending_replay_trigger")
                or "Stop unnecessary motion and hold the complete ending clearly.",
                maximum=800,
            ),
            caption_highlight_timestamps=caption_timestamps,
            motion_timestamps=motion_timestamps,
        )

    @staticmethod
    def _scores(
        *,
        educational: bool,
        emotional: bool,
        high_energy: bool,
        caption: BobaCaptionRecommendationV1,
        motion: BobaMotionRecommendationV1,
        safety: BobaCaptionMotionSafetyReviewV1,
        hook_scores: dict[str, Any],
        ranking_scores: dict[str, Any],
    ) -> BobaCaptionMotionScoreV1:
        caption_fit = 76.0
        if educational and caption.caption_style in {
            "keyword_highlight",
            "educational_steps",
        }:
            caption_fit += 14.0
        if emotional and caption.caption_style in {
            "emotional_emphasis",
            "clean_subtitles",
        }:
            caption_fit += 12.0
        if high_energy and caption.caption_style in {
            "bold_hook_captions",
            "punchline_caption",
        }:
            caption_fit += 12.0
        if safety.caption_overload_risk:
            caption_fit -= 12.0

        readability = 91.0
        readability -= 24.0 if safety.readability_risk else 0.0
        readability -= 18.0 if safety.caption_overload_risk else 0.0
        readability -= 10.0 if caption.caption_density == "high" else 0.0

        motion_fit = 72.0
        if high_energy and motion.motion_style in {"dynamic_zoom", "punch_in", "high_motion"}:
            motion_fit += 16.0
        if emotional and motion.motion_style in {"subtle_zoom", "stable"}:
            motion_fit += 14.0
        if educational and motion.motion_style in {"subtle_zoom", "stable"}:
            motion_fit += 12.0
        if safety.under_motion_risk:
            motion_fit -= 12.0
        if safety.over_motion_risk:
            motion_fit -= 16.0

        motion_safety = 94.0
        motion_safety -= 30.0 if safety.face_cutoff_risk else 0.0
        motion_safety -= 28.0 if safety.multi_speaker_layout_risk else 0.0
        motion_safety -= 12.0 if safety.unavailable_face_signal_risk else 0.0
        motion_safety -= 12.0 if safety.unavailable_layout_signal_risk else 0.0
        motion_safety -= 15.0 if safety.over_motion_risk else 0.0
        if motion.motion_style in {"stable", "layout_safe"}:
            motion_safety += 8.0

        upstream_hook = _points(
            hook_scores.get("hook_score")
            or ranking_scores.get("hook_score"),
            62.0,
        )
        hook_support = upstream_hook
        hook_support += (
            8.0
            if caption.caption_style
            in {"bold_hook_captions", "keyword_highlight", "punchline_caption"}
            else 2.0
        )
        hook_support -= 18.0 if safety.hook_distraction_risk else 0.0

        upstream_retention = _points(
            hook_scores.get("overall_retention_score")
            or ranking_scores.get("retention_score"),
            62.0,
        )
        retention_support = upstream_retention
        retention_support += 6.0 if motion.stable_moments else 0.0
        retention_support -= 12.0 if safety.over_motion_risk else 0.0
        retention_support -= 10.0 if safety.caption_overload_risk else 0.0

        values = [
            _clamp(caption_fit),
            _clamp(readability),
            _clamp(motion_fit),
            _clamp(motion_safety),
            _clamp(hook_support),
            _clamp(retention_support),
        ]
        overall = (
            values[0] * 0.18
            + values[1] * 0.18
            + values[2] * 0.17
            + values[3] * 0.2
            + values[4] * 0.13
            + values[5] * 0.14
        )
        return BobaCaptionMotionScoreV1(
            caption_fit_score=values[0],
            caption_readability_score=values[1],
            motion_fit_score=values[2],
            motion_safety_score=values[3],
            hook_support_score=values[4],
            retention_support_score=values[5],
            overall_recommendation_score=_clamp(overall),
        )

    @staticmethod
    def _project_summary(
        recommendations: Sequence[BobaCaptionMotionRecommendationV1],
    ) -> str:
        if not recommendations:
            return (
                "No selected or backup clip briefs were available, so Caption + Motion "
                "Brain V1 did not fabricate recommendations."
            )
        caption_styles = Counter(
            item.caption_recommendation.caption_style for item in recommendations
        )
        motion_styles = Counter(
            item.motion_recommendation.motion_style for item in recommendations
        )
        risky = sum(
            bool(item.safety_review.blockers or item.safety_review.warnings)
            for item in recommendations
        )
        caption_summary = ", ".join(
            f"{style.replace('_', ' ')} ({count})"
            for style, count in caption_styles.most_common(3)
        )
        motion_summary = ", ".join(
            f"{style.replace('_', ' ')} ({count})"
            for style, count in motion_styles.most_common(3)
        )
        return (
            f"Created {len(recommendations)} advisory recommendation(s) across selected "
            f"and backup briefs. Primary caption guidance: {caption_summary}. Primary "
            f"motion guidance: {motion_summary}. {risky} recommendation(s) require "
            "explicit safety or readability review before any editor applies them."
        )

    @staticmethod
    def _validate_project(
        project_id: str,
        artifact: Mapping[str, Any],
        label: str,
    ) -> None:
        artifact_project = _text(artifact.get("project_id"), maximum=128)
        if artifact and artifact_project and artifact_project != project_id:
            raise ValidationError(
                f"BOBA {label} belongs to a different project.",
                details={
                    "project_id": project_id,
                    "artifact_project_id": artifact_project,
                    "artifact": label,
                },
            )
