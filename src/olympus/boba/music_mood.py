"""Deterministic advisory music-mood and audio-handling recommendations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from olympus.boba.clip_brief import BobaSourceWindowV1
from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaMusicMoodName = Literal[
    "motivational",
    "emotional",
    "cinematic",
    "calm",
    "tense",
    "suspenseful",
    "inspiring",
    "funny",
    "dramatic",
    "educational_clean",
    "luxury",
    "heroic",
    "mysterious",
    "upbeat",
    "minimal",
    "no_music",
    "unknown",
]
BobaAudioEnergyLevel = Literal["none", "low", "medium", "high"]
BobaMusicRole = Literal[
    "support_speech",
    "build_emotion",
    "create_tension",
    "increase_energy",
    "preserve_silence",
    "emphasize_payoff",
    "stay_minimal",
]
BobaSpeechPriority = Literal["low", "medium", "high", "critical"]
BobaSfxIntensity = Literal["none", "light", "moderate", "high"]

_MOTIVATIONAL_CUES = (
    "motivational",
    "motivation",
    "inspiring",
    "inspiration",
    "overcome",
    "transformation",
    "take action",
    "ready to act",
    "ambition",
    "breakthrough",
    "heroic",
)
_EMOTIONAL_CUES = (
    "emotional",
    "vulnerable",
    "heartfelt",
    "grief",
    "loss",
    "healing",
    "relief",
    "personal story",
    "emotional reveal",
    "reflection",
)
_EDUCATIONAL_CUES = (
    "educational",
    "explain",
    "explainer",
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
_TENSE_CUES = (
    "tense",
    "tension",
    "suspense",
    "suspenseful",
    "mystery",
    "mysterious",
    "danger",
    "threat",
    "uncertainty",
)
_FUNNY_CUES = (
    "funny",
    "humor",
    "humour",
    "comedy",
    "punchline",
    "playful",
    "joke",
)
_LUXURY_CUES = (
    "luxury",
    "premium",
    "status",
    "exclusive",
    "prestige",
    "high-end",
    "aspirational",
)
_SERIOUS_CUES = (
    "serious",
    "speech-heavy",
    "speech heavy",
    "commentary",
    "interview",
    "thoughtful",
    "measured",
    "calm authority",
)
_HIGH_ENERGY_CUES = (
    "high energy",
    "high-energy",
    "fast",
    "punchy",
    "rapid",
    "excited",
    "energetic",
    "aggressive",
    "shocking",
    "contradiction",
)
_WEAK_EVIDENCE_CUES = (
    "weak evidence",
    "unclear evidence",
    "unknown angle",
    "generic clip",
    "weak hook",
    "insufficient context",
)
_MUSIC_MOOD_VALUES = {
    "motivational",
    "emotional",
    "cinematic",
    "calm",
    "tense",
    "suspenseful",
    "inspiring",
    "funny",
    "dramatic",
    "educational_clean",
    "luxury",
    "heroic",
    "mysterious",
    "upbeat",
    "minimal",
    "no_music",
    "unknown",
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
    return " ".join(str(value).split())[:maximum].strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _unit(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    if number > 1.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 4)


def _score(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    if 0.0 <= number <= 1.0:
        number *= 100.0
    return _clamp(number)


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 3)


def _flatten_strings(value: Any, *, depth: int = 0) -> list[str]:
    if depth > 3:
        return []
    if isinstance(value, str):
        return [_text(value)]
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


def _joined(*values: Any, maximum: int = 8_000) -> str:
    return " ".join(
        item
        for value in values
        for item in _flatten_strings(value)
        if item
    )[:maximum].casefold()


def _contains(text: str, cues: Sequence[str]) -> bool:
    return any(cue in text for cue in cues)


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


def _by_id(values: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in _list(values):
        item = _dict(value)
        identifier = _text(
            item.get("candidate_id") or item.get("clip_id"),
            maximum=128,
        )
        if identifier:
            result[identifier] = item
    return result


def _source_window(value: Mapping[str, Any]) -> BobaSourceWindowV1:
    window = _dict(value.get("source_window"))
    start = max(0.0, _number(window.get("start_seconds") or window.get("start")))
    end = max(
        start,
        _number(window.get("end_seconds") or window.get("end"), start),
    )
    duration = _number(window.get("duration_seconds"), end - start)
    duration = max(0.0, min(180.0, duration or end - start))
    if end <= start:
        end = start + duration
    return BobaSourceWindowV1(
        start_seconds=round(start, 3),
        end_seconds=round(end, 3),
        duration_seconds=round(duration, 3),
    )


def _safe_source_id(value: Any) -> str:
    source_id = _text(value, maximum=512)
    if any(marker in source_id for marker in ("/", "\\", "://")):
        return ""
    return source_id


def _signal_entry(value: dict[str, Any], name: str) -> dict[str, Any]:
    direct = _dict(value.get(name))
    if direct:
        return direct
    data = _dict(value.get("data"))
    return _dict(data.get(name))


def _signal_available(value: dict[str, Any]) -> bool:
    if not value:
        return False
    status = _dict(value.get("status"))
    timeline = _dict(value.get("timeline"))
    if status.get("available") is True:
        return True
    return bool(_list(timeline.get("events")) or _list(value.get("events")))


def _signal_events(value: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = _dict(value.get("timeline"))
    events = _list(timeline.get("events")) or _list(value.get("events"))
    return [_dict(item) for item in events if _dict(item)]


def _relative_events(
    value: dict[str, Any],
    source_window: BobaSourceWindowV1,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    clip_start = source_window.start_seconds
    clip_end = source_window.end_seconds
    duration = source_window.duration_seconds
    for event in _signal_events(value):
        start = _number(event.get("start_seconds") or event.get("start"))
        end = _number(event.get("end_seconds") or event.get("end"), start)
        if end < start:
            continue
        if clip_start > 0.0 and end >= clip_start and start <= clip_end:
            relative_start = max(0.0, start - clip_start)
            relative_end = min(duration, end - clip_start)
        elif 0.0 <= start <= duration and 0.0 <= end <= duration:
            relative_start = start
            relative_end = end
        else:
            continue
        result.append(
            {
                "start": round(relative_start, 3),
                "end": round(max(relative_start, relative_end), 3),
                "label": _text(event.get("label"), maximum=40).casefold(),
                "score": _unit(event.get("score"), 0.5),
            }
        )
    return result


class BobaMusicMoodV1(BobaContract):
    primary_mood: BobaMusicMoodName
    secondary_mood: BobaMusicMoodName
    energy_level: BobaAudioEnergyLevel
    emotional_direction: str = Field(min_length=1, max_length=500)
    pacing_fit: str = Field(min_length=1, max_length=500)
    music_role: BobaMusicRole
    avoid_this: list[str] = Field(default_factory=list, max_length=16)
    reason: str = Field(min_length=1, max_length=1000)


class BobaAudioEnergyMapV1(BobaContract):
    seconds_0_to_3: str = Field(min_length=1, max_length=800)
    seconds_3_to_10: str = Field(min_length=1, max_length=800)
    middle_section: str = Field(min_length=1, max_length=800)
    payoff_section: str = Field(min_length=1, max_length=800)
    ending_section: str = Field(min_length=1, max_length=800)
    energy_shift_notes: list[str] = Field(default_factory=list, max_length=16)
    silence_moments: list[str] = Field(default_factory=list, max_length=16)


class BobaSpeechClarityPlanV1(BobaContract):
    speech_priority: BobaSpeechPriority
    ducking_guidance: str = Field(min_length=1, max_length=800)
    music_volume_guidance: str = Field(min_length=1, max_length=800)
    sfx_volume_guidance: str = Field(min_length=1, max_length=800)
    silence_guidance: str = Field(min_length=1, max_length=800)
    clarity_risk: bool
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaSfxRecommendationV1(BobaContract):
    sfx_intensity: BobaSfxIntensity
    hook_sfx_guidance: str = Field(min_length=1, max_length=700)
    transition_sfx_guidance: str = Field(min_length=1, max_length=700)
    payoff_sfx_guidance: str = Field(min_length=1, max_length=700)
    avoid_sfx_moments: list[str] = Field(default_factory=list, max_length=16)
    reason: str = Field(min_length=1, max_length=1000)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaAudioRiskReviewV1(BobaContract):
    music_overpowering_risk: bool
    wrong_mood_risk: bool
    speech_clarity_risk: bool
    sfx_overload_risk: bool
    silence_damage_risk: bool
    emotional_mismatch_risk: bool
    rights_review_required: bool
    blockers: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    fixes: list[str] = Field(default_factory=list, max_length=24)


class BobaMusicMoodScoreV1(BobaContract):
    mood_fit_score: float = Field(ge=0.0, le=100.0)
    speech_clarity_score: float = Field(ge=0.0, le=100.0)
    sfx_fit_score: float = Field(ge=0.0, le=100.0)
    emotional_fit_score: float = Field(ge=0.0, le=100.0)
    retention_support_score: float = Field(ge=0.0, le=100.0)
    overall_audio_score: float = Field(ge=0.0, le=100.0)


class BobaMusicMoodBriefEnhancementV1(BobaContract):
    brief_id: str = Field(min_length=1, max_length=160)
    improved_audio_instruction: str = Field(min_length=1, max_length=1000)
    improved_music_mood: BobaMusicMoodName
    improved_sfx_instruction: str = Field(min_length=1, max_length=1000)
    ducking_warning: str = Field(min_length=1, max_length=700)
    speech_clarity_warning: str = Field(min_length=1, max_length=700)
    rights_review_warning: str = Field(min_length=1, max_length=700)
    apply_suggestion: Literal[False] = False


class BobaMusicMoodSignalUsageV1(BobaContract):
    clip_briefs_used: bool
    hook_retention_used: bool
    caption_motion_used: bool
    creative_direction_used: bool
    editorial_decision_used: bool
    clip_ranking_used: bool
    candidate_discovery_used: bool
    whole_video_understanding_used: bool
    explanation_used: bool
    audio_signals_used: bool
    silence_signals_used: bool
    music_manifest_seen: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaMusicMoodRecommendationV1(BobaContract):
    recommendation_id: str = Field(min_length=1, max_length=180)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    brief_id: str = Field(min_length=1, max_length=160)
    source_window: BobaSourceWindowV1
    music_mood: BobaMusicMoodV1
    audio_energy_map: BobaAudioEnergyMapV1
    speech_clarity_plan: BobaSpeechClarityPlanV1
    sfx_recommendation: BobaSfxRecommendationV1
    audio_risk_review: BobaAudioRiskReviewV1
    recommendation_score: BobaMusicMoodScoreV1
    brief_enhancement: BobaMusicMoodBriefEnhancementV1
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class BobaMusicMoodRecommendationSetV1(BobaContract):
    schema_version: Literal["boba_music_mood_brain_v1"] = "boba_music_mood_brain_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    recommendations: list[BobaMusicMoodRecommendationV1] = Field(
        default_factory=list,
        max_length=60,
    )
    project_audio_summary: str = Field(min_length=1, max_length=1500)
    signal_usage: BobaMusicMoodSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaMusicMoodBrainV1:
    """Create local mood-level audio advice without selecting or applying media."""

    def analyze(
        self,
        *,
        project_id: str,
        clip_briefs: Mapping[str, Any] | BaseModel | None,
        hook_retention: Mapping[str, Any] | BaseModel | None = None,
        caption_motion: Mapping[str, Any] | BaseModel | None = None,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None = None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        audio_signals: Mapping[str, Any] | BaseModel | None = None,
        silence_signals: Mapping[str, Any] | BaseModel | None = None,
        music_manifest_metadata: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaMusicMoodRecommendationSetV1:
        briefs = _artifact(clip_briefs)
        if not briefs:
            raise ValidationError(
                "BOBA Music Mood Brain requires saved clip briefs.",
                details={
                    "project_id": project_id,
                    "required_artifact": "clip_briefs",
                },
            )
        self._validate_project(project_id, briefs, "clip_briefs")

        hook = _artifact(hook_retention)
        caption = _artifact(caption_motion)
        creative = _artifact(creative_direction_v2)
        editorial = _artifact(editorial_decisions)
        ranking = _artifact(clip_ranking)
        discovery = _artifact(candidate_discovery)
        understanding = _artifact(whole_video_understanding)
        explanation_set = _artifact(explanations)
        audio = _artifact(audio_signals)
        silence = _artifact(silence_signals)
        manifest = _artifact(music_manifest_metadata)
        memory_data = _artifact(memory)
        for artifact, label in (
            (hook, "hook_retention"),
            (caption, "caption_motion"),
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
        caption_by_id = _by_id(caption.get("recommendations"))
        creative_by_id = _by_id(creative.get("clip_directions"))
        editorial_by_id = _by_id(editorial.get("decisions"))
        ranking_by_id = _by_id(ranking.get("ranked_candidates"))
        discovery_by_id = _by_id(discovery.get("candidates"))
        explanation_by_id = _by_id(
            explanation_set.get("candidate_explanations")
            or explanation_set.get("clip_explanations")
        )

        recommendations: list[BobaMusicMoodRecommendationV1] = []
        brief_values = [
            *_list(briefs.get("selected_briefs")),
            *_list(briefs.get("backup_briefs")),
        ]
        for raw in brief_values[:60]:
            brief = _dict(raw)
            candidate_id = _text(brief.get("candidate_id"), maximum=128)
            if not candidate_id:
                continue
            recommendations.append(
                self._recommend(
                    project_id=project_id,
                    brief=brief,
                    hook=hook_by_id.get(candidate_id, {}),
                    caption=caption_by_id.get(candidate_id, {}),
                    creative=creative_by_id.get(candidate_id, {}),
                    editorial=editorial_by_id.get(candidate_id, {}),
                    ranking=ranking_by_id.get(candidate_id, {}),
                    discovery=discovery_by_id.get(candidate_id, {}),
                    understanding=understanding,
                    explanation=explanation_by_id.get(candidate_id, {}),
                    audio=audio,
                    silence=silence,
                    manifest=manifest,
                    memory=memory_data,
                )
            )

        audio_available = _signal_available(audio)
        silence_available = _signal_available(silence)
        manifest_seen = bool(
            manifest.get("seen")
            or manifest.get("available")
            or manifest.get("manifest_seen")
        )
        optional = (
            (bool(hook), "hook_retention"),
            (bool(caption), "caption_motion"),
            (bool(creative), "creative_direction_v2"),
            (bool(editorial), "editorial_decisions"),
            (bool(ranking), "clip_ranking"),
            (bool(discovery), "candidate_discovery"),
            (bool(understanding), "whole_video_understanding"),
            (bool(explanation_set), "explanations"),
            (audio_available, "audio_signals"),
            (silence_available, "silence_signals"),
            (manifest_seen, "music_manifest"),
            (bool(memory_data), "memory"),
        )
        unavailable = [label for available, label in optional if not available]
        usage = BobaMusicMoodSignalUsageV1(
            clip_briefs_used=True,
            hook_retention_used=bool(hook),
            caption_motion_used=bool(caption),
            creative_direction_used=bool(creative),
            editorial_decision_used=bool(editorial),
            clip_ranking_used=bool(ranking),
            candidate_discovery_used=bool(discovery),
            whole_video_understanding_used=bool(understanding),
            explanation_used=bool(explanation_set),
            audio_signals_used=audio_available,
            silence_signals_used=silence_available,
            music_manifest_seen=manifest_seen,
            memory_used=bool(memory_data),
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=_unique(
                [
                    *(
                        [
                            "Missing optional signals lower confidence; conservative "
                            "mood-only guidance was used."
                        ]
                        if unavailable
                        else []
                    ),
                    "Manifest awareness never selects music or proves usage rights.",
                ],
                limit=32,
                maximum=700,
            ),
        )
        safe_count = int(_number(manifest.get("safe_asset_count"), 0.0))
        warnings = _unique(
            [
                *(
                    [
                        "No selected or backup clip briefs were available; no audio "
                        "recommendations were fabricated."
                    ]
                    if not recommendations
                    else []
                ),
                *(
                    [
                        "The local music manifest exposes no confirmed safe automatic "
                        "assets; recommendations remain mood-only."
                    ]
                    if manifest_seen and safe_count <= 0
                    else []
                ),
                *(
                    [
                        "Optional BOBA or local signal artifacts were unavailable; "
                        "conservative fallbacks were used."
                    ]
                    if unavailable
                    else []
                ),
            ],
            limit=64,
            maximum=700,
        )
        return BobaMusicMoodRecommendationSetV1(
            project_id=project_id,
            source_id=_safe_source_id(
                briefs.get("source_id")
                or hook.get("source_id")
                or caption.get("source_id")
                or creative.get("source_id")
            ),
            recommendations=recommendations,
            project_audio_summary=self._project_summary(recommendations),
            signal_usage=usage,
            warnings=warnings,
            limitations=[
                "Music Mood Brain V1 is advisory metadata and does not render, mix, "
                "download, or apply audio.",
                "It recommends mood and handling only; it does not name or select music.",
                "Local signal metadata can indicate energy and silence but does not "
                "replace human listening or final render validation.",
                "Any external music requires documented rights review before use.",
            ],
        )

    def analyze_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        clip_briefs: Mapping[str, Any] | BaseModel | None = None,
        hook_retention: Mapping[str, Any] | BaseModel | None = None,
        caption_motion: Mapping[str, Any] | BaseModel | None = None,
        creative_direction_v2: Mapping[str, Any] | BaseModel | None = None,
        editorial_decisions: Mapping[str, Any] | BaseModel | None = None,
        clip_ranking: Mapping[str, Any] | BaseModel | None = None,
        candidate_discovery: Mapping[str, Any] | BaseModel | None = None,
        whole_video_understanding: Mapping[str, Any] | BaseModel | None = None,
        explanations: Mapping[str, Any] | BaseModel | None = None,
        audio_signals: Mapping[str, Any] | BaseModel | None = None,
        silence_signals: Mapping[str, Any] | BaseModel | None = None,
        music_manifest_metadata: Mapping[str, Any] | BaseModel | None = None,
        memory: Mapping[str, Any] | BaseModel | None = None,
    ) -> BobaMusicMoodRecommendationSetV1:
        analysis = _dict(signals.get("analysis_signals_v2"))
        return self.analyze(
            project_id=project_id,
            clip_briefs=clip_briefs or _dict(signals.get("clip_briefs")),
            hook_retention=hook_retention or _dict(signals.get("hook_retention")),
            caption_motion=caption_motion or _dict(signals.get("caption_motion")),
            creative_direction_v2=(
                creative_direction_v2
                or _dict(signals.get("creative_direction_v2"))
            ),
            editorial_decisions=(
                editorial_decisions or _dict(signals.get("editorial_decisions"))
            ),
            clip_ranking=clip_ranking or _dict(signals.get("clip_ranking")),
            candidate_discovery=(
                candidate_discovery
                or _dict(signals.get("candidate_clip_discovery"))
            ),
            whole_video_understanding=(
                whole_video_understanding
                or _dict(signals.get("whole_video_understanding"))
            ),
            explanations=explanations or _dict(signals.get("explanations")),
            audio_signals=(
                audio_signals
                or _signal_entry(analysis, "audio_energy")
                or _dict(signals.get("audio_signals"))
            ),
            silence_signals=(
                silence_signals
                or _signal_entry(analysis, "silence")
                or _dict(signals.get("silence_signals"))
            ),
            music_manifest_metadata=(
                music_manifest_metadata
                or _dict(signals.get("music_manifest_metadata"))
            ),
            memory=memory
            or _dict(signals.get("project_memory"))
            or _dict(signals.get("memory")),
        )

    def _recommend(
        self,
        *,
        project_id: str,
        brief: dict[str, Any],
        hook: dict[str, Any],
        caption: dict[str, Any],
        creative: dict[str, Any],
        editorial: dict[str, Any],
        ranking: dict[str, Any],
        discovery: dict[str, Any],
        understanding: dict[str, Any],
        explanation: dict[str, Any],
        audio: dict[str, Any],
        silence: dict[str, Any],
        manifest: dict[str, Any],
        memory: dict[str, Any],
    ) -> BobaMusicMoodRecommendationV1:
        candidate_id = _text(brief.get("candidate_id"), maximum=128)
        brief_id = _text(
            brief.get("brief_id") or f"brief_{candidate_id}",
            maximum=160,
        )
        source_window = _source_window(brief)
        hook_analysis = _dict(hook.get("hook_analysis"))
        hook_plan = _dict(hook.get("retention_plan"))
        hook_risk = _dict(hook.get("retention_risk_review"))
        hook_score = _dict(hook.get("retention_score"))
        caption_recommendation = _dict(caption.get("caption_recommendation"))
        motion_recommendation = _dict(caption.get("motion_recommendation"))
        caption_safety = _dict(caption.get("safety_review"))
        audio_direction = _dict(creative.get("audio_direction"))
        emotional_arc = _dict(creative.get("emotional_arc"))
        pacing_map = _dict(creative.get("pacing_map"))
        editorial_risk = _dict(editorial.get("risk_review"))
        ranking_scores = _dict(ranking.get("score_breakdown"))

        classification_text = _joined(
            brief.get("brief_title"),
            brief.get("final_clip_angle"),
            brief.get("target_viewer_feeling"),
            _dict(brief.get("hook_instruction")).get("summary"),
            _dict(brief.get("story_instruction")).get("summary"),
            hook_analysis.get("hook_type"),
            hook_analysis.get("opening_line_direction"),
            hook_plan,
            audio_direction.get("music_mood"),
            emotional_arc,
            pacing_map.get("pacing_intensity"),
            editorial.get("final_story_angle"),
            editorial.get("final_hook_strategy"),
            editorial.get("music_mood"),
            editorial.get("pacing_intensity"),
            ranking.get("candidate_type"),
            ranking.get("suggested_title"),
            discovery.get("candidate_type"),
            discovery.get("hook_idea"),
            explanation.get("why_it_works"),
            understanding.get("content_identity"),
        )
        evidence_fields = [
            brief.get("brief_title"),
            brief.get("final_clip_angle"),
            brief.get("target_viewer_feeling"),
            hook_analysis.get("hook_type"),
            audio_direction.get("music_mood"),
            emotional_arc.get("intended_viewer_feeling"),
            editorial.get("music_mood"),
            discovery.get("candidate_type"),
        ]
        evidence_count = sum(bool(_text(value)) for value in evidence_fields)
        weak_evidence = bool(
            _contains(classification_text, _WEAK_EVIDENCE_CUES)
            or _unit(brief.get("confidence"), 0.6) < 0.45
            or evidence_count < 2
        )
        classification = self._classify(
            classification_text,
            weak_evidence=weak_evidence,
            requested_mood=_text(
                audio_direction.get("music_mood")
                or editorial.get("music_mood"),
                maximum=80,
            ).casefold(),
        )
        music_mood = self._music_mood(
            classification=classification,
            classification_text=classification_text,
            weak_evidence=weak_evidence,
        )
        silence_events = _relative_events(silence, source_window)
        audio_events = _relative_events(audio, source_window)
        energy_map = self._energy_map(
            mood=music_mood,
            source_window=source_window,
            retention_plan=hook_plan,
            silence_events=silence_events,
            audio_events=audio_events,
        )

        speech_heavy = bool(
            classification in {"educational", "serious"}
            or _contains(classification_text, _SERIOUS_CUES)
            or _contains(
                _joined(
                    _dict(brief.get("audio_instruction")),
                    audio_direction.get("speech_clarity_notes"),
                ),
                (
                    "speech-heavy",
                    "speech heavy",
                    "dialogue primary",
                    "voice-only",
                    "critical clarity",
                ),
            )
        )
        emotional = classification == "emotional"
        audio_available = _signal_available(audio)
        silence_available = _signal_available(silence)
        source_signal_warning = bool(
            _list(_dict(audio.get("status")).get("warnings"))
            or _list(audio.get("warnings"))
            or not audio_available
        )
        priority = self._speech_priority(
            classification=classification,
            speech_heavy=speech_heavy,
        )
        caption_or_motion_risk = bool(
            caption_safety.get("caption_overload_risk")
            or caption_safety.get("over_motion_risk")
            or hook_risk.get("audio_distraction_risk")
        )
        sfx = self._sfx_recommendation(
            classification=classification,
            energy_level=music_mood.energy_level,
            hook_score=_score(hook_score.get("hook_score"), 60.0),
            motion_intensity=_text(
                motion_recommendation.get("motion_intensity"),
                maximum=40,
            ).casefold(),
            caption_rhythm=_text(
                caption_recommendation.get("caption_rhythm"),
                maximum=40,
            ).casefold(),
            audio_distraction_risk=caption_or_motion_risk,
            emotional=emotional,
            speech_heavy=speech_heavy,
            preserve_silence=bool(energy_map.silence_moments),
        )
        clarity_risk = bool(
            source_signal_warning
            or priority == "critical"
            or hook_risk.get("audio_distraction_risk")
            or editorial_risk.get("audio_risk")
        )
        clarity = self._speech_clarity_plan(
            priority=priority,
            music_mood=music_mood,
            sfx=sfx,
            clarity_risk=clarity_risk,
            audio_available=audio_available,
            silence_available=silence_available,
            emotional=emotional,
        )
        category_count = sum(
            (
                _contains(classification_text, _MOTIVATIONAL_CUES),
                _contains(classification_text, _EMOTIONAL_CUES),
                _contains(classification_text, _EDUCATIONAL_CUES),
                _contains(classification_text, _TENSE_CUES),
                _contains(classification_text, _FUNNY_CUES),
                _contains(classification_text, _LUXURY_CUES),
            )
        )
        risk = self._risk_review(
            mood=music_mood,
            clarity=clarity,
            sfx=sfx,
            weak_evidence=weak_evidence,
            conflicting_categories=category_count >= 3,
            audio_distraction_risk=caption_or_motion_risk,
            silence_moments=energy_map.silence_moments,
            emotional=emotional,
            manifest=manifest,
        )
        scores = self._scores(
            weak_evidence=weak_evidence,
            classification=classification,
            clarity=clarity,
            sfx=sfx,
            risk=risk,
            hook_score=_score(hook_score.get("hook_score"), 60.0),
            retention_score=_score(
                hook_score.get("overall_retention_score"),
                _score(ranking_scores.get("retention_strength"), 60.0),
            ),
        )
        enhancement = BobaMusicMoodBriefEnhancementV1(
            brief_id=brief_id,
            improved_audio_instruction=(
                f"Use {music_mood.primary_mood.replace('_', ' ')} mood only as "
                f"{music_mood.music_role.replace('_', ' ')} guidance at "
                f"{music_mood.energy_level} energy. {clarity.music_volume_guidance}"
            ),
            improved_music_mood=music_mood.primary_mood,
            improved_sfx_instruction=(
                f"Use {sfx.sfx_intensity} SFX intensity. "
                f"{sfx.hook_sfx_guidance} {sfx.payoff_sfx_guidance}"
            ),
            ducking_warning=clarity.ducking_guidance,
            speech_clarity_warning=(
                "Source audio evidence is incomplete; verify every spoken word remains "
                "clear before approving any music or SFX."
                if clarity.clarity_risk
                else "Speech remains the priority; verify clarity after any audio mix."
            ),
            rights_review_warning=(
                "Any externally sourced music requires documented rights review before use."
            ),
        )
        missing_count = sum(
            not available
            for available in (
                bool(hook),
                bool(caption),
                bool(creative),
                bool(editorial),
                bool(ranking),
                bool(discovery),
                bool(understanding),
                bool(explanation),
                audio_available,
                silence_available,
                bool(memory),
            )
        )
        confidence = max(
            0.2,
            min(
                0.96,
                _unit(brief.get("confidence"), 0.62)
                + 0.025 * (11 - missing_count)
                - 0.025 * missing_count
                - (0.15 if weak_evidence else 0.0)
                - (0.05 if risk.blockers else 0.0),
            ),
        )
        warnings = _unique(
            [
                *(
                    [
                        "Mood evidence is weak; minimal or no-music guidance is used "
                        "until a human reviews the clip."
                    ]
                    if weak_evidence
                    else []
                ),
                *risk.warnings,
                *clarity.warnings,
                *sfx.warnings,
            ],
            limit=32,
            maximum=700,
        )
        return BobaMusicMoodRecommendationV1(
            recommendation_id=f"music_mood_{candidate_id}",
            project_id=project_id,
            candidate_id=candidate_id,
            brief_id=brief_id,
            source_window=source_window,
            music_mood=music_mood,
            audio_energy_map=energy_map,
            speech_clarity_plan=clarity,
            sfx_recommendation=sfx,
            audio_risk_review=risk,
            recommendation_score=scores,
            brief_enhancement=enhancement,
            confidence=round(confidence, 4),
            warnings=warnings,
            limitations=[
                "This recommendation is mood-level advisory metadata, not an applied mix.",
                "Energy timing is clip-relative guidance and does not modify an edit timeline.",
                "No music is named, selected, downloaded, licensed, or rendered.",
            ],
        )

    @staticmethod
    def _classify(
        text: str,
        *,
        weak_evidence: bool,
        requested_mood: str,
    ) -> str:
        if weak_evidence:
            return "weak"
        if _contains(text, _FUNNY_CUES):
            return "funny"
        if _contains(text, _LUXURY_CUES):
            return "luxury"
        if any(cue in text for cue in ("educational", "tutorial", "how to", "framework")):
            return "educational"
        if any(
            cue in text
            for cue in ("emotional", "vulnerable", "heartfelt", "grief", "healing")
        ):
            return "emotional"
        if any(cue in text for cue in ("tense", "suspense", "mysterious", "danger")):
            return "tense"
        if _contains(text, _EMOTIONAL_CUES):
            return "emotional"
        if _contains(text, _MOTIVATIONAL_CUES):
            return "motivational"
        if _contains(text, _TENSE_CUES):
            return "tense"
        if _contains(text, _EDUCATIONAL_CUES):
            return "educational"
        if _contains(text, _SERIOUS_CUES):
            return "serious"
        requested_map = {
            "motivational": "motivational",
            "inspiring": "motivational",
            "heroic": "motivational",
            "emotional": "emotional",
            "cinematic": "cinematic",
            "dramatic": "cinematic",
            "calm": "serious",
            "minimal": "serious",
            "educational": "educational",
            "educational_clean": "educational",
            "tense": "tense",
            "suspenseful": "tense",
            "mysterious": "tense",
            "funny": "funny",
            "upbeat": "funny",
            "luxury": "luxury",
        }
        return requested_map.get(requested_mood, "neutral")

    @staticmethod
    def _music_mood(
        *,
        classification: str,
        classification_text: str,
        weak_evidence: bool,
    ) -> BobaMusicMoodV1:
        high_energy = _contains(classification_text, _HIGH_ENERGY_CUES)
        if classification == "motivational":
            primary: BobaMusicMoodName = (
                "heroic" if "heroic" in classification_text else "motivational"
            )
            secondary: BobaMusicMoodName = "inspiring"
            energy: BobaAudioEnergyLevel = "high" if high_energy else "medium"
            role: BobaMusicRole = "increase_energy"
            emotional_direction = "Build confidence and forward motion without forcing emotion."
            pacing_fit = "Use a controlled rise from the hook toward the payoff."
            avoid = ["triumphal excess", "busy vocal-forward music", "constant maximum energy"]
        elif classification == "emotional":
            primary = "emotional"
            secondary = "minimal"
            energy = "low"
            role = "build_emotion"
            emotional_direction = "Support the authentic emotional turn without manipulating it."
            pacing_fit = "Enter gently, preserve pauses, and avoid a hard rhythmic push."
            avoid = ["heavy percussion", "sentimental excess", "music over vulnerable speech"]
        elif classification == "educational":
            primary = "educational_clean"
            secondary = "minimal"
            energy = "low"
            role = "support_speech"
            emotional_direction = "Keep attention on comprehension, usefulness, and credibility."
            pacing_fit = "Use a steady unobtrusive bed with no competing rhythmic detail."
            avoid = ["busy arrangements", "dramatic swells", "vocal-forward music"]
        elif classification == "tense":
            primary = "tense"
            secondary = "suspenseful"
            energy = "medium"
            role = "create_tension"
            emotional_direction = "Maintain a clean open loop until the supported reveal."
            pacing_fit = "Build gradually and release pressure at the payoff."
            avoid = ["horror exaggeration", "constant risers", "false urgency"]
        elif classification == "funny":
            primary = "funny"
            secondary = "upbeat"
            energy = "high" if high_energy else "medium"
            role = "increase_energy"
            emotional_direction = "Support timing and lightness without explaining the joke."
            pacing_fit = "Use short clean energy changes around setup and punchline."
            avoid = ["novelty overload", "laugh cues", "SFX on every caption"]
        elif classification == "luxury":
            primary = "luxury"
            secondary = "cinematic"
            energy = "medium"
            role = "emphasize_payoff"
            emotional_direction = "Create polished aspiration without overstating status."
            pacing_fit = "Use smooth restrained movement and a measured payoff lift."
            avoid = ["cheap novelty sounds", "aggressive drops", "overly playful music"]
        elif classification == "cinematic":
            primary = "cinematic"
            secondary = "dramatic"
            energy = "medium"
            role = "emphasize_payoff"
            emotional_direction = "Support scale and story movement without masking dialogue."
            pacing_fit = "Build in one restrained arc and resolve under the ending."
            avoid = ["trailer-style excess", "constant impact hits", "dialogue masking"]
        elif classification == "serious":
            primary = "minimal"
            secondary = "educational_clean"
            energy = "low"
            role = "stay_minimal"
            emotional_direction = "Preserve authority, nuance, and natural speech."
            pacing_fit = "Keep the bed nearly static and let verbal pacing lead."
            avoid = ["dramatic manipulation", "frequent SFX", "rhythmic distraction"]
        elif weak_evidence or classification == "weak":
            primary = "no_music"
            secondary = "minimal"
            energy = "none"
            role = "preserve_silence"
            emotional_direction = "Avoid imposing an unsupported emotional interpretation."
            pacing_fit = "Use source speech and natural pauses until the intended tone is reviewed."
            avoid = ["invented emotional framing", "automatic mood escalation", "unreviewed music"]
        else:
            primary = "minimal"
            secondary = "calm"
            energy = "low"
            role = "stay_minimal"
            emotional_direction = "Stay neutral and let the clip's spoken meaning lead."
            pacing_fit = "Use a restrained bed only if human review confirms it helps."
            avoid = ["strong genre assumptions", "busy rhythm", "forced drama"]
        return BobaMusicMoodV1(
            primary_mood=primary,
            secondary_mood=secondary,
            energy_level=energy,
            emotional_direction=emotional_direction,
            pacing_fit=pacing_fit,
            music_role=role,
            avoid_this=avoid,
            reason=(
                f"The supplied BOBA guidance best supports a "
                f"{primary.replace('_', ' ')} mood with "
                f"{energy} energy and a {role.replace('_', ' ')} role."
            ),
        )

    @staticmethod
    def _energy_map(
        *,
        mood: BobaMusicMoodV1,
        source_window: BobaSourceWindowV1,
        retention_plan: dict[str, Any],
        silence_events: list[dict[str, Any]],
        audio_events: list[dict[str, Any]],
    ) -> BobaAudioEnergyMapV1:
        level = mood.energy_level
        if level == "none":
            opening = "None: preserve source speech and natural room tone."
            context = "None: do not introduce a background bed without human review."
            middle = "None: let spoken pacing carry retention."
            payoff = "None: emphasize the payoff through delivery and silence."
            ending = "None: preserve the final word and natural tail."
        elif level == "high":
            opening = "High but controlled: enter under the hook without masking first words."
            context = "Medium: settle quickly so context stays intelligible."
            middle = "Medium: maintain momentum without constant escalation."
            payoff = "High: allow one short lift only after the payoff words remain clear."
            ending = "Low: release energy and leave the final phrase unobstructed."
        elif level == "medium":
            opening = "Medium: establish tone cleanly under the opening hook."
            context = "Low to medium: support context while speech remains dominant."
            middle = "Medium: add one gradual rise only where retention benefits."
            payoff = "Medium: use a restrained lift or release around the payoff."
            ending = "Low: taper beneath the final line and replay cue."
        else:
            opening = "Low: use a gentle entry or preserve silence under first words."
            context = "Low: stay nearly static beneath speech."
            middle = "Low: follow natural pacing rather than adding urgency."
            payoff = "Low to medium: permit only a subtle supported lift."
            ending = "Low: fade beneath the ending without shortening its tail."

        silence_moments = [
            (
                f"Preserve the source pause near {event['start']:.1f}-"
                f"{event['end']:.1f}s unless review confirms it is dead air."
            )
            for event in silence_events[:8]
            if event["end"] - event["start"] >= 0.2
        ]
        if not silence_moments and mood.music_role in {
            "build_emotion",
            "create_tension",
            "preserve_silence",
        }:
            silence_moments.append(
                "Preserve any intentional pause before the payoff after source review."
            )
        energy_labels = Counter(
            event.get("label") for event in audio_events if event.get("label")
        )
        signal_note = (
            "Local energy metadata is quiet/silent-heavy; avoid filling every low-energy gap."
            if energy_labels["quiet"] + energy_labels["silence"]
            > energy_labels["loud"] + energy_labels["normal"]
            else "Local energy metadata supports the planned contour; verify by listening."
            if energy_labels
            else (
                "No usable local energy timeline was supplied; treat section levels "
                "as conservative."
            )
        )
        return BobaAudioEnergyMapV1(
            seconds_0_to_3=opening,
            seconds_3_to_10=context,
            middle_section=middle,
            payoff_section=payoff,
            ending_section=ending,
            energy_shift_notes=_unique(
                [
                    signal_note,
                    _text(retention_plan.get("seconds_0_to_3"), maximum=300),
                    _text(retention_plan.get("payoff_timing_strategy"), maximum=300),
                    (
                        f"Keep the full {source_window.duration_seconds:.1f}s clip duration; "
                        "audio guidance must not change boundaries."
                    ),
                ],
                limit=8,
                maximum=500,
            ),
            silence_moments=silence_moments,
        )

    @staticmethod
    def _speech_priority(
        *,
        classification: str,
        speech_heavy: bool,
    ) -> BobaSpeechPriority:
        if classification == "educational" or speech_heavy:
            return "critical"
        if classification in {"emotional", "serious", "tense"}:
            return "high"
        if classification in {"motivational", "cinematic", "luxury"}:
            return "high"
        return "medium"

    @staticmethod
    def _speech_clarity_plan(
        *,
        priority: BobaSpeechPriority,
        music_mood: BobaMusicMoodV1,
        sfx: BobaSfxRecommendationV1,
        clarity_risk: bool,
        audio_available: bool,
        silence_available: bool,
        emotional: bool,
    ) -> BobaSpeechClarityPlanV1:
        if music_mood.energy_level == "none":
            music_volume = (
                "Use no background music unless a human explicitly approves a minimal bed."
            )
        elif priority == "critical":
            music_volume = "Keep music very low beneath all speech; never trade clarity for energy."
        elif priority == "high":
            music_volume = (
                "Keep music low under dialogue and allow only brief lifts between phrases."
            )
        else:
            music_volume = "Keep music subordinate to speech and verify every word after mixing."
        ducking = (
            "Use speech-led ducking whenever music is present: lower music during spoken "
            "phrases, use gentle attack/release, and restore level only in verified gaps."
        )
        sfx_volume = (
            "Use no SFX."
            if sfx.sfx_intensity == "none"
            else "Keep SFX subtle, brief, and below speech; audition each event in context."
        )
        silence_guidance = (
            "Preserve emotional pauses and do not fill every gap."
            if emotional
            else "Preserve intentional pauses; remove only confirmed dead air."
        )
        warnings = _unique(
            [
                *(
                    ["Local audio-energy metadata is unavailable; verify speech by listening."]
                    if not audio_available
                    else []
                ),
                *(
                    ["Local silence metadata is unavailable; pause guidance needs human review."]
                    if not silence_available
                    else []
                ),
                *(
                    ["Speech clarity risk is present; reject any mix that masks words."]
                    if clarity_risk
                    else []
                ),
            ],
            limit=24,
            maximum=600,
        )
        return BobaSpeechClarityPlanV1(
            speech_priority=priority,
            ducking_guidance=ducking,
            music_volume_guidance=music_volume,
            sfx_volume_guidance=sfx_volume,
            silence_guidance=silence_guidance,
            clarity_risk=clarity_risk,
            warnings=warnings,
        )

    @staticmethod
    def _sfx_recommendation(
        *,
        classification: str,
        energy_level: BobaAudioEnergyLevel,
        hook_score: float,
        motion_intensity: str,
        caption_rhythm: str,
        audio_distraction_risk: bool,
        emotional: bool,
        speech_heavy: bool,
        preserve_silence: bool,
    ) -> BobaSfxRecommendationV1:
        if emotional or classification in {"educational", "serious", "weak"}:
            intensity: BobaSfxIntensity = "none" if preserve_silence else "light"
        elif audio_distraction_risk:
            intensity = "light"
        elif classification in {"funny", "motivational"} and (
            energy_level == "high"
            or hook_score >= 72.0
            or motion_intensity in {"moderate", "high"}
            or caption_rhythm == "punchy"
        ):
            intensity = "moderate"
        elif classification in {"tense", "cinematic", "luxury"}:
            intensity = "light"
        else:
            intensity = "light"
        if speech_heavy and intensity == "moderate":
            intensity = "light"
        hook_guidance = (
            "Use no hook SFX; let the first meaningful words lead."
            if intensity == "none"
            else (
                "Use at most one clean, subtle hook accent after confirming it does "
                "not mask speech."
            )
        )
        transition_guidance = (
            "Use no transition SFX."
            if intensity == "none"
            else "Use a clean transition accent only for a real structural turn, not every cut."
        )
        payoff_guidance = (
            "Use silence or delivery for payoff emphasis."
            if intensity == "none"
            else "Use at most one restrained payoff accent after the key words remain fully clear."
        )
        avoid = [
            "first meaningful words",
            "important explanation phrases",
            "vulnerable or emotional pauses",
            "every caption change",
        ]
        warnings = _unique(
            [
                *(
                    ["Upstream guidance flags audio distraction; reduce or remove SFX."]
                    if audio_distraction_risk
                    else []
                ),
                *(
                    ["Speech-heavy content should use none or light SFX only."]
                    if speech_heavy
                    else []
                ),
                "Use only clean, non-noise-like SFX after rights and safety review.",
            ],
            limit=24,
            maximum=600,
        )
        return BobaSfxRecommendationV1(
            sfx_intensity=intensity,
            hook_sfx_guidance=hook_guidance,
            transition_sfx_guidance=transition_guidance,
            payoff_sfx_guidance=payoff_guidance,
            avoid_sfx_moments=avoid,
            reason=(
                f"{classification.replace('_', ' ')} content with {energy_level} "
                f"energy supports {intensity} SFX at most."
            ),
            warnings=warnings,
        )

    @staticmethod
    def _risk_review(
        *,
        mood: BobaMusicMoodV1,
        clarity: BobaSpeechClarityPlanV1,
        sfx: BobaSfxRecommendationV1,
        weak_evidence: bool,
        conflicting_categories: bool,
        audio_distraction_risk: bool,
        silence_moments: list[str],
        emotional: bool,
        manifest: dict[str, Any],
    ) -> BobaAudioRiskReviewV1:
        overpowering = bool(
            clarity.speech_priority in {"high", "critical"}
            and mood.energy_level in {"medium", "high"}
        )
        wrong_mood = weak_evidence or conflicting_categories
        sfx_overload = bool(
            audio_distraction_risk
            or (
                sfx.sfx_intensity in {"moderate", "high"}
                and clarity.speech_priority in {"high", "critical"}
            )
        )
        silence_damage = bool(
            silence_moments
            and (emotional or mood.music_role in {"create_tension", "preserve_silence"})
        )
        emotional_mismatch = conflicting_categories
        safe_count = int(_number(manifest.get("safe_asset_count"), 0.0))
        blockers = _unique(
            [
                *(
                    ["Mood evidence is too weak for automatic audio application."]
                    if weak_evidence
                    else []
                ),
                *(
                    ["No safe local music availability is confirmed."]
                    if manifest and safe_count <= 0
                    else []
                ),
            ],
            limit=24,
            maximum=500,
        )
        warnings = _unique(
            [
                *(
                    ["Music could overpower priority speech at the recommended energy."]
                    if overpowering
                    else []
                ),
                *(
                    ["Multiple emotional categories conflict; verify the intended mood."]
                    if conflicting_categories
                    else []
                ),
                *(
                    ["SFX may compete with speech or visual emphasis."]
                    if sfx_overload
                    else []
                ),
                *(
                    ["Filling natural pauses could damage emotion or tension."]
                    if silence_damage
                    else []
                ),
                "Any externally sourced music requires documented rights review.",
            ],
            limit=32,
            maximum=600,
        )
        fixes = _unique(
            [
                "Keep speech dominant and compare the mix against source dialogue.",
                *(
                    ["Use minimal or no music until the intended mood is confirmed."]
                    if wrong_mood
                    else []
                ),
                *(
                    ["Reduce SFX to light or none and remove events that mask words."]
                    if sfx_overload
                    else []
                ),
                *(
                    ["Mark natural pauses as protected before any audio edit."]
                    if silence_damage
                    else []
                ),
                "Complete rights review before using any external music.",
            ],
            limit=24,
            maximum=500,
        )
        return BobaAudioRiskReviewV1(
            music_overpowering_risk=overpowering,
            wrong_mood_risk=wrong_mood,
            speech_clarity_risk=clarity.clarity_risk,
            sfx_overload_risk=sfx_overload,
            silence_damage_risk=silence_damage,
            emotional_mismatch_risk=emotional_mismatch,
            rights_review_required=True,
            blockers=blockers,
            warnings=warnings,
            fixes=fixes,
        )

    @staticmethod
    def _scores(
        *,
        weak_evidence: bool,
        classification: str,
        clarity: BobaSpeechClarityPlanV1,
        sfx: BobaSfxRecommendationV1,
        risk: BobaAudioRiskReviewV1,
        hook_score: float,
        retention_score: float,
    ) -> BobaMusicMoodScoreV1:
        mood_fit = 58.0 if weak_evidence else 84.0
        if classification in {"neutral", "weak"}:
            mood_fit -= 8.0
        if risk.emotional_mismatch_risk:
            mood_fit -= 14.0
        clarity_score = 90.0
        if clarity.clarity_risk:
            clarity_score -= 18.0
        if risk.music_overpowering_risk:
            clarity_score -= 12.0
        sfx_fit = 88.0
        if risk.sfx_overload_risk:
            sfx_fit -= 22.0
        if sfx.sfx_intensity == "none" and classification in {"funny", "motivational"}:
            sfx_fit -= 5.0
        emotional_fit = 80.0 if classification not in {"neutral", "weak"} else 62.0
        if risk.wrong_mood_risk:
            emotional_fit -= 16.0
        retention_support = 0.45 * hook_score + 0.55 * retention_score
        if risk.sfx_overload_risk:
            retention_support -= 8.0
        if risk.silence_damage_risk:
            retention_support -= 4.0
        mood_fit = _clamp(mood_fit)
        clarity_score = _clamp(clarity_score)
        sfx_fit = _clamp(sfx_fit)
        emotional_fit = _clamp(emotional_fit)
        retention_support = _clamp(retention_support)
        overall = _clamp(
            0.25 * mood_fit
            + 0.25 * clarity_score
            + 0.15 * sfx_fit
            + 0.15 * emotional_fit
            + 0.20 * retention_support
        )
        return BobaMusicMoodScoreV1(
            mood_fit_score=mood_fit,
            speech_clarity_score=clarity_score,
            sfx_fit_score=sfx_fit,
            emotional_fit_score=emotional_fit,
            retention_support_score=retention_support,
            overall_audio_score=overall,
        )

    @staticmethod
    def _project_summary(
        recommendations: list[BobaMusicMoodRecommendationV1],
    ) -> str:
        if not recommendations:
            return (
                "No selected or backup clips were available, so BOBA produced no "
                "music-mood guidance."
            )
        moods = Counter(item.music_mood.primary_mood for item in recommendations)
        dominant = ", ".join(
            f"{mood.replace('_', ' ')} ({count})"
            for mood, count in moods.most_common(3)
        )
        low_music = sum(
            item.music_mood.energy_level in {"none", "low"}
            for item in recommendations
        )
        sfx_caution = sum(
            item.sfx_recommendation.sfx_intensity in {"none", "light"}
            or item.audio_risk_review.sfx_overload_risk
            for item in recommendations
        )
        clarity_checks = sum(
            item.speech_clarity_plan.clarity_risk
            or item.speech_clarity_plan.speech_priority == "critical"
            for item in recommendations
        )
        return (
            f"Recommended dominant moods: {dominant}. "
            f"{low_music} clip(s) need low or no music; "
            f"{sfx_caution} need conservative SFX; "
            f"{clarity_checks} need explicit speech-clarity review. "
            "All guidance is advisory, and any external music requires documented "
            "rights review."
        )

    @staticmethod
    def _validate_project(
        project_id: str,
        artifact: dict[str, Any],
        label: str,
    ) -> None:
        artifact_project = _text(artifact.get("project_id"), maximum=128)
        if artifact and artifact_project and artifact_project != project_id:
            raise ValidationError(
                f"BOBA {label} belongs to a different project.",
                details={
                    "project_id": project_id,
                    "artifact_project_id": artifact_project,
                },
            )


def music_manifest_awareness(registry: Mapping[str, Any] | None) -> dict[str, Any]:
    """Reduce a local music registry to non-identifying availability metadata."""

    data = _dict(registry)
    if not data:
        return {}
    return {
        "seen": bool(data.get("manifest_path") or data.get("version")),
        "safe_asset_count": len(_list(data.get("safe_assets"))),
        "rejected_asset_count": len(_list(data.get("unsafe_assets"))),
        "warning_count": len(_list(data.get("warnings"))),
    }


def is_music_mood(value: str) -> bool:
    """Return whether a value is a supported V1 mood label."""

    return value in _MUSIC_MOOD_VALUES
