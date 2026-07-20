"""Deterministic advisory candidate-clip discovery from existing Olympus signals."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1
from olympus.platform.errors import ValidationError

BobaCandidateType = Literal[
    "hook_moment",
    "payoff_moment",
    "emotional_beat",
    "story_turn",
    "high_energy_section",
    "explanation_section",
    "curiosity_gap",
    "motivational_moment",
    "funny_moment",
    "controversial_moment",
    "educational_moment",
    "unknown",
]

_CUE_TYPES: tuple[tuple[str, BobaCandidateType], ...] = (
    ("this changed everything", "story_turn"),
    ("what happened next", "curiosity_gap"),
    ("nobody talks about", "controversial_moment"),
    ("then suddenly", "story_turn"),
    ("the problem is", "explanation_section"),
    ("the truth is", "controversial_moment"),
    ("the reason", "explanation_section"),
    ("i realized", "story_turn"),
    ("that's why", "payoff_moment"),
    ("however", "story_turn"),
    ("finally", "payoff_moment"),
    ("but", "story_turn"),
)
_WORD = re.compile(r"[a-z0-9']+")


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


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
    return max(0.0, min(1.0, _number(value, default)))


def _artifact(value: Mapping[str, Any] | BaseModel | None) -> dict[str, Any]:
    raw = _dict(value)
    data = _dict(raw.get("data"))
    return data or raw


def _value(item: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def _range(item: Mapping[str, Any]) -> tuple[float, float]:
    start = _number(
        _value(
            item,
            (
                "start_seconds",
                "start",
                "raw_start",
                "source_start",
                "recommended_start",
                "recommended_start_seconds",
                "timestamp",
                "time",
            ),
        )
    )
    end = _number(
        _value(
            item,
            (
                "end_seconds",
                "end",
                "raw_end",
                "source_end",
                "recommended_end",
                "recommended_end_seconds",
            ),
        ),
        start,
    )
    if end <= start:
        duration = _number(item.get("duration_seconds") or item.get("duration"))
        end = start + max(0.0, duration)
    return max(0.0, start), max(0.0, end)


def _overlap_seconds(
    start: float, end: float, other_start: float, other_end: float
) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))


def _overlap_ratio(
    start: float, end: float, other_start: float, other_end: float
) -> float:
    intersection = _overlap_seconds(start, end, other_start, other_end)
    shorter = min(max(0.0, end - start), max(0.0, other_end - other_start))
    return intersection / shorter if shorter > 0.0 else 0.0


def _words(value: str) -> set[str]:
    return set(_WORD.findall(value.casefold()))


def _unique(values: Sequence[str], *, limit: int, maximum: int = 300) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _text(value, maximum=maximum)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


class BobaBoundarySuggestionV1(BobaContract):
    recommended_start_seconds: float = Field(ge=0.0)
    recommended_end_seconds: float = Field(ge=0.0)
    pre_roll_seconds: float = Field(default=0.0, ge=0.0, le=30.0)
    post_roll_seconds: float = Field(default=0.0, ge=0.0, le=30.0)
    abrupt_start_warning: bool = False
    abrupt_end_warning: bool = False
    reason: str = Field(min_length=1, max_length=500)


class BobaCandidateEvidenceV1(BobaContract):
    transcript_snippets: list[str] = Field(default_factory=list, max_length=5)
    source_signals: list[str] = Field(default_factory=list, max_length=20)
    topic_segment_ids: list[str] = Field(default_factory=list, max_length=12)
    emotional_beat_ids: list[str] = Field(default_factory=list, max_length=12)
    context_payoff_link_ids: list[str] = Field(default_factory=list, max_length=12)
    section_score_ids: list[str] = Field(default_factory=list, max_length=12)
    virality_reasons: list[str] = Field(default_factory=list, max_length=12)


class BobaCandidateClipV1(BobaContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(gt=0.0, le=90.0)
    suggested_title: str = Field(min_length=1, max_length=160)
    hook_idea: str = Field(min_length=1, max_length=300)
    story_angle: str = Field(min_length=1, max_length=400)
    candidate_type: BobaCandidateType
    discovery_reason: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)
    standalone_score: float = Field(ge=0.0, le=1.0)
    setup_required: bool
    payoff_present: bool
    context_needed: bool
    source_topic: str = Field(min_length=1, max_length=160)
    emotion_label: str = Field(min_length=1, max_length=80)
    virality_cues: list[str] = Field(default_factory=list, max_length=12)
    boundary_suggestion: BobaBoundarySuggestionV1
    evidence: BobaCandidateEvidenceV1
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaRejectedWindowV1(BobaContract):
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    reason: str = Field(min_length=1, max_length=300)
    overlap_with_candidate_id: str | None = Field(default=None, max_length=128)
    confidence: float = Field(ge=0.0, le=1.0)


class BobaCandidateDiversitySummaryV1(BobaContract):
    candidate_count: int = Field(default=0, ge=0, le=20)
    topic_count: int = Field(default=0, ge=0, le=20)
    emotion_count: int = Field(default=0, ge=0, le=20)
    candidate_types: list[BobaCandidateType] = Field(default_factory=list, max_length=12)
    duplicate_windows_removed: int = Field(default=0, ge=0)
    high_overlap_windows_removed: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaCandidateDiscoverySignalUsageV1(BobaContract):
    whole_video_understanding_used: bool
    transcript_used: bool
    analysis_signals_used: bool
    story_used: bool
    virality_used: bool
    planning_used: bool
    memory_used: bool
    fallback_used: bool
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateClipDiscoveryV1(BobaContract):
    schema_version: Literal["boba_candidate_clip_discovery_v1"] = (
        "boba_candidate_clip_discovery_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=512)
    created_at: str = Field(default_factory=now_iso)
    video_duration_seconds: float = Field(ge=0.0)
    summary: str = Field(min_length=1, max_length=600)
    candidates: list[BobaCandidateClipV1] = Field(default_factory=list, max_length=20)
    rejected_windows: list[BobaRejectedWindowV1] = Field(
        default_factory=list, max_length=100
    )
    diversity_summary: BobaCandidateDiversitySummaryV1
    signal_usage: BobaCandidateDiscoverySignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


@dataclass(frozen=True, slots=True)
class _TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class _CandidateSeed:
    start: float
    end: float
    candidate_type: BobaCandidateType
    reason: str
    confidence: float
    standalone_score: float = 0.55
    setup_required: bool = False
    payoff_present: bool = False
    context_needed: bool = False
    source_topic: str = "unknown"
    emotion_label: str = "unknown"
    hook_idea: str = ""
    story_angle: str = ""
    required_end: float = 0.0
    source_signals: list[str] = field(default_factory=list)
    topic_ids: list[str] = field(default_factory=list)
    emotion_ids: list[str] = field(default_factory=list)
    link_ids: list[str] = field(default_factory=list)
    section_ids: list[str] = field(default_factory=list)
    virality_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BobaCandidateClipDiscoveryEngine:
    """Discover bounded candidate windows without planning, rendering, or I/O."""

    def __init__(
        self,
        *,
        minimum_duration_seconds: float = 12.0,
        ideal_minimum_seconds: float = 25.0,
        ideal_maximum_seconds: float = 45.0,
        maximum_duration_seconds: float = 90.0,
        maximum_candidates: int = 20,
    ) -> None:
        if not 1.0 <= minimum_duration_seconds <= ideal_minimum_seconds:
            raise ValueError("minimum duration must not exceed ideal minimum")
        if not ideal_minimum_seconds <= ideal_maximum_seconds <= maximum_duration_seconds:
            raise ValueError("ideal duration bounds must not exceed maximum duration")
        if not 1 <= maximum_candidates <= 20:
            raise ValueError("maximum_candidates must be between 1 and 20")
        self.minimum_duration_seconds = minimum_duration_seconds
        self.ideal_minimum_seconds = ideal_minimum_seconds
        self.ideal_maximum_seconds = ideal_maximum_seconds
        self.maximum_duration_seconds = maximum_duration_seconds
        self.maximum_candidates = maximum_candidates

    def discover(
        self,
        *,
        project_id: str,
        transcript_segments: Sequence[Mapping[str, Any]] = (),
        source_id: str = "",
        video_duration_seconds: float | None = None,
        whole_video_understanding: (
            BobaWholeVideoUnderstandingV1 | Mapping[str, Any] | None
        ) = None,
        analysis_signals_v2: Mapping[str, Any] | None = None,
        story_artifact: Mapping[str, Any] | None = None,
        virality_artifact: Mapping[str, Any] | None = None,
        planning_artifact: Mapping[str, Any] | None = None,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
    ) -> BobaCandidateClipDiscoveryV1:
        transcript = self._normalize_transcript(transcript_segments)
        understanding = _artifact(whole_video_understanding)
        analysis = _artifact(analysis_signals_v2)
        story = _artifact(story_artifact)
        virality = _artifact(virality_artifact)
        planning = _artifact(planning_artifact)
        memory_data = _dict(memory)
        duration = self._duration(
            video_duration_seconds,
            transcript,
            understanding,
            story,
            analysis,
            planning,
        )
        seeds: list[_CandidateSeed] = []
        rejected: list[BobaRejectedWindowV1] = []
        if understanding:
            seeds.extend(self._whole_video_seeds(understanding, rejected))
        seeds.extend(self._story_seeds(story))
        seeds.extend(self._analysis_seeds(analysis))
        seeds.extend(self._planning_seeds(planning))
        seeds.extend(self._virality_seeds(virality))
        seeds.extend(self._transcript_cue_seeds(transcript))
        if len(seeds) < 3 and transcript:
            seeds.extend(self._transcript_fallback_seeds(transcript, duration))
        if not seeds:
            raise ValidationError(
                "BOBA candidate discovery requires at least one timed transcript or "
                "upstream candidate signal.",
                details={"project_id": project_id, "missing_signal": "timed_content"},
            )
        self._enrich_from_understanding(seeds, understanding)
        global_virality_reasons = self._virality_reasons(virality)
        self._apply_virality(seeds, global_virality_reasons)
        self._apply_memory(seeds, memory_data)
        candidates: list[BobaCandidateClipV1] = []
        for seed in seeds:
            candidate, reason = self._finalize_seed(
                project_id,
                seed,
                transcript,
                duration,
            )
            if candidate is not None:
                candidates.append(candidate)
            elif reason is not None:
                rejected.append(reason)
        candidates, dedup_rejected, duplicate_count, overlap_count = self._deduplicate(
            candidates
        )
        rejected.extend(dedup_rejected)
        candidates, limit_rejected = self._limit_with_diversity(candidates)
        rejected.extend(limit_rejected)
        usage = self._signal_usage(
            understanding=understanding,
            transcript=transcript,
            analysis=analysis,
            story=story,
            virality=virality,
            planning=planning,
            memory=memory_data,
        )
        diversity = self._diversity_summary(
            candidates,
            duplicate_count=duplicate_count,
            overlap_count=overlap_count,
        )
        warnings = list(usage.warnings)
        if len(candidates) < 3:
            warnings.append(
                "Fewer than three defensible distinct windows were found; candidates were "
                "not fabricated to reach a quota."
            )
        if not candidates:
            warnings.append("All timed windows failed duration, filler, or overlap checks.")
        summary = (
            f"BOBA found {len(candidates)} advisory candidate clip window(s) across "
            f"{diversity.topic_count} topic(s) and rejected {len(rejected)} window(s)."
        )
        return BobaCandidateClipDiscoveryV1(
            project_id=project_id,
            source_id=_text(source_id, maximum=512),
            video_duration_seconds=round(duration, 3),
            summary=summary,
            candidates=candidates,
            rejected_windows=rejected[:100],
            diversity_summary=diversity,
            signal_usage=usage,
            warnings=_unique(warnings, limit=64, maximum=400),
            limitations=[
                "V1 discovers advisory windows; it does not rank, plan, edit, or render clips.",
                "Scores are deterministic editorial heuristics and do not predict audience "
                "performance.",
                "Boundary suggestions are not frame-accurate A/V boundary repair.",
                "Only compact transcript evidence is retained; no raw media is stored.",
                "Human review remains required before downstream use.",
            ],
        )

    def build(self, **kwargs: Any) -> BobaCandidateClipDiscoveryV1:
        return self.discover(**kwargs)

    def discover_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
    ) -> BobaCandidateClipDiscoveryV1:
        project = _dict(signals.get("project"))
        selected_plans = _list(signals.get("selected_plans"))
        planning_candidates = _list(signals.get("planning_candidates"))
        planning_summary = _dict(signals.get("planning_summary"))
        planning = (
            {
                "selected_plans": selected_plans,
                "planning_candidates": planning_candidates,
                "planning_summary": planning_summary,
            }
            if selected_plans or planning_candidates or planning_summary
            else {}
        )
        return self.discover(
            project_id=project_id,
            source_id=_text(
                project.get("storage_key") or project.get("source_id"), maximum=512
            ),
            video_duration_seconds=_number(
                signals.get("duration_seconds") or project.get("duration_seconds")
            ),
            transcript_segments=[
                _dict(item) for item in _list(signals.get("transcript_segments"))
            ],
            whole_video_understanding=_dict(
                signals.get("whole_video_understanding")
            ),
            analysis_signals_v2=_dict(signals.get("analysis_signals_v2")),
            story_artifact=_dict(signals.get("story_analysis_v2")),
            virality_artifact=_dict(signals.get("virality_summary")),
            planning_artifact=planning,
            memory=memory,
        )

    def build_from_signals(
        self,
        project_id: str,
        signals: Mapping[str, Any],
        *,
        memory: BobaProjectMemoryV1 | Mapping[str, Any] | None = None,
    ) -> BobaCandidateClipDiscoveryV1:
        return self.discover_from_signals(project_id, signals, memory=memory)

    @staticmethod
    def _normalize_transcript(
        values: Sequence[Mapping[str, Any]],
    ) -> list[_TranscriptSegment]:
        segments: list[_TranscriptSegment] = []
        for value in values[:3000]:
            item = _dict(value)
            start, end = _range(item)
            text = _text(item.get("text") or item.get("transcript"), maximum=300)
            if not text or end <= start:
                continue
            segments.append(_TranscriptSegment(start=start, end=end, text=text))
        return sorted(segments, key=lambda item: (item.start, item.end, item.text))

    @staticmethod
    def _duration(
        supplied: float | None,
        transcript: list[_TranscriptSegment],
        *artifacts: Mapping[str, Any],
    ) -> float:
        supplied_duration = max(0.0, _number(supplied))
        if supplied_duration > 0.0:
            return round(supplied_duration, 3)
        explicit = [
            _number(artifact.get("video_duration_seconds")) for artifact in artifacts
        ]
        transcript_end = max((item.end for item in transcript), default=0.0)
        explicit_duration = max([transcript_end, *explicit], default=0.0)
        if explicit_duration > 0.0:
            return round(explicit_duration, 3)
        candidates: list[float] = []
        for artifact in artifacts:
            candidates.extend(
                end
                for _, end in BobaCandidateClipDiscoveryEngine._timed_ranges(artifact)
            )
        return round(max(candidates, default=0.0), 3)

    @staticmethod
    def _timed_ranges(artifact: Mapping[str, Any]) -> list[tuple[float, float]]:
        keys = (
            "shortability_hints",
            "emotional_beats",
            "context_payoff_map",
            "section_scores",
            "topic_timeline",
            "micro_stories",
            "recommended_clip_stories",
            "candidates",
            "plans",
            "selected_plans",
            "planning_candidates",
            "events",
            "moments",
            "hotspots",
            "windows",
        )
        ranges: list[tuple[float, float]] = []
        for key in keys:
            for value in _list(artifact.get(key)):
                item = _dict(value)
                start, end = _range(item)
                if end > start:
                    ranges.append((start, end))
        for value in artifact.values():
            nested = _dict(value)
            if nested:
                for key in keys:
                    for child in _list(nested.get(key)):
                        start, end = _range(_dict(child))
                        if end > start:
                            ranges.append((start, end))
        return ranges[:500]

    def _whole_video_seeds(
        self,
        understanding: dict[str, Any],
        rejected: list[BobaRejectedWindowV1],
    ) -> list[_CandidateSeed]:
        seeds: list[_CandidateSeed] = []
        for hint in [_dict(item) for item in _list(understanding.get("shortability_hints"))]:
            start, end = _range(hint)
            suggested = _text(hint.get("suggested_clip_type"), maximum=80)
            confidence = _score(
                0.45
                + 0.25 * _score(hint.get("hook_potential"))
                + 0.2 * _score(hint.get("payoff_strength"))
                + (0.1 if hint.get("recommended_action") == "consider" else 0.0)
            )
            if suggested in {"avoid_as_standalone", "needs_more_context"} and hint.get(
                "recommended_action"
            ) == "avoid":
                rejected.append(
                    BobaRejectedWindowV1(
                        start_seconds=start,
                        end_seconds=max(start, end),
                        reason="whole_video_recommended_avoid",
                        confidence=confidence,
                    )
                )
                continue
            if suggested not in {"candidate_for_short", "payoff_clip", "possible_hook"}:
                continue
            candidate_type: BobaCandidateType = "explanation_section"
            if suggested == "payoff_clip":
                candidate_type = "payoff_moment"
            elif suggested == "possible_hook":
                candidate_type = "hook_moment"
            setup_required = bool(hint.get("setup_needed"))
            payoff_present = _score(hint.get("payoff_strength")) >= 0.45
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type=candidate_type,
                    reason=_text(hint.get("reason"), maximum=500)
                    or "Whole-video shortability guidance identified this interval.",
                    confidence=confidence,
                    standalone_score=_score(
                        0.62
                        + 0.18 * _score(hint.get("hook_potential"))
                        + 0.15 * _score(hint.get("payoff_strength"))
                        - (0.25 if setup_required else 0.0)
                    ),
                    setup_required=setup_required,
                    context_needed=setup_required,
                    payoff_present=payoff_present,
                    source_signals=["whole_video_shortability_hint"],
                )
            )
        for beat in [_dict(item) for item in _list(understanding.get("emotional_beats"))]:
            intensity = _score(beat.get("intensity"))
            if intensity < 0.55:
                continue
            start, end = _range(beat)
            emotion = _text(beat.get("emotion_label"), maximum=80) or "emotional"
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type=self._emotion_type(emotion),
                    reason=_text(beat.get("reason"), maximum=500)
                    or f"A strong {emotion} beat was detected.",
                    confidence=_score(0.45 + 0.45 * intensity),
                    standalone_score=_score(0.48 + 0.25 * intensity),
                    emotion_label=emotion,
                    emotion_ids=[_text(beat.get("beat_id"), maximum=128)],
                    source_signals=["whole_video_emotional_beat"],
                )
            )
        for link in [_dict(item) for item in _list(understanding.get("context_payoff_map"))]:
            context_start = _number(link.get("context_start_seconds"))
            context_end = _number(link.get("context_end_seconds"), context_start)
            payoff_start = _number(link.get("payoff_start_seconds"), context_end)
            payoff_end = _number(link.get("payoff_end_seconds"), payoff_start)
            setup_required = bool(link.get("setup_required"))
            start = context_start if setup_required else max(context_end, payoff_start - 8.0)
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=payoff_end,
                    candidate_type="payoff_moment",
                    reason=_text(link.get("description"), maximum=500)
                    or "Whole-video understanding linked setup to a later payoff.",
                    confidence=_score(link.get("confidence"), 0.55),
                    standalone_score=_score(
                        _score(link.get("confidence"), 0.55)
                        + (0.18 if link.get("standalone_clip_possible") else -0.15)
                    ),
                    setup_required=setup_required,
                    context_needed=setup_required,
                    payoff_present=True,
                    required_end=payoff_end,
                    link_ids=[_text(link.get("link_id"), maximum=128)],
                    source_signals=["whole_video_context_payoff_link"],
                )
            )
        for section in [_dict(item) for item in _list(understanding.get("section_scores"))]:
            start, end = _range(section)
            filler = _score(section.get("filler_score"))
            repetition = _score(section.get("repetition_score"))
            confidence = _score(
                0.45 * _score(section.get("shortability_score"))
                + 0.3 * _score(section.get("clarity_score"))
                + 0.15 * _score(section.get("energy_score"))
                + 0.1 * _score(section.get("novelty_score"))
                - 0.25 * filler
                - 0.15 * repetition
            )
            if filler >= 0.55 or repetition >= 0.72:
                rejected.append(
                    BobaRejectedWindowV1(
                        start_seconds=start,
                        end_seconds=max(start, end),
                        reason="high_filler_or_repetition",
                        confidence=confidence,
                    )
                )
                continue
            if (
                _score(section.get("shortability_score")) < 0.52
                or _score(section.get("clarity_score")) < 0.45
            ):
                continue
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type=(
                        "high_energy_section"
                        if _score(section.get("energy_score")) >= 0.72
                        else "educational_moment"
                    ),
                    reason=_text(
                        "; ".join(str(item) for item in _list(section.get("reasons"))),
                        maximum=500,
                    )
                    or "High shortability and clarity with limited filler.",
                    confidence=confidence,
                    standalone_score=_score(
                        0.45
                        + 0.35 * _score(section.get("clarity_score"))
                        + 0.2 * _score(section.get("shortability_score"))
                        - 0.25 * filler
                    ),
                    section_ids=[_text(section.get("section_id"), maximum=128)],
                    source_signals=["whole_video_section_score"],
                )
            )
        for topic in [_dict(item) for item in _list(understanding.get("topic_timeline"))]:
            confidence = _score(topic.get("confidence"), 0.5)
            start, end = _range(topic)
            if confidence < 0.45 or end <= start:
                continue
            topic_name = _text(topic.get("topic"), maximum=160) or "unknown"
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type="explanation_section",
                    reason=_text(topic.get("summary"), maximum=500)
                    or "A bounded topic section may form a standalone explanation.",
                    confidence=_score(0.35 + 0.35 * confidence),
                    standalone_score=_score(0.45 + 0.3 * confidence),
                    source_topic=topic_name,
                    story_angle=_text(topic.get("summary"), maximum=400),
                    topic_ids=[_text(topic.get("segment_id"), maximum=128)],
                    source_signals=["whole_video_topic_segment"],
                )
            )
        return seeds

    @staticmethod
    def _story_seeds(story: dict[str, Any]) -> list[_CandidateSeed]:
        seeds: list[_CandidateSeed] = []
        items = [
            *[_dict(item) for item in _list(story.get("micro_stories"))],
            *[_dict(item) for item in _list(story.get("recommended_clip_stories"))],
        ]
        for item in items[:80]:
            start, end = _range(item)
            if end <= start:
                continue
            payoff = _dict(item.get("payoff") or item.get("payoff_analysis"))
            context = _dict(item.get("context") or item.get("context_dependency"))
            completeness = _score(item.get("completeness_score"), 0.5)
            if not item.get("recommended_for_planning", completeness >= 0.55):
                continue
            payoff_present = bool(payoff.get("payoff_present"))
            payoff_end = _number(payoff.get("payoff_end"), end)
            context_score = _score(
                context.get("score") or item.get("context_dependency_score")
            )
            setup_required = context_score >= 0.5
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=max(end, payoff_end if payoff_present else end),
                    candidate_type="story_turn" if payoff_present else "explanation_section",
                    reason=_text(
                        item.get("why_story_works")
                        or item.get("summary")
                        or item.get("one_sentence_summary"),
                        maximum=500,
                    )
                    or "Story analysis identified a potentially complete micro-story.",
                    confidence=_score(0.35 + 0.55 * completeness),
                    standalone_score=_score(
                        0.45 + 0.35 * completeness + (0.15 if payoff_present else 0.0)
                        - 0.3 * context_score
                    ),
                    setup_required=setup_required,
                    context_needed=setup_required,
                    payoff_present=payoff_present,
                    required_end=payoff_end if payoff_present else 0.0,
                    story_angle=_text(
                        item.get("story_shape") or item.get("summary"), maximum=400
                    ),
                    source_signals=["story_analysis_v2_micro_story"],
                )
            )
        return seeds

    @staticmethod
    def _analysis_seeds(analysis: dict[str, Any]) -> list[_CandidateSeed]:
        energy = _dict(analysis.get("audio_energy"))
        timeline = _dict(energy.get("timeline"))
        events = [
            *[_dict(item) for item in _list(timeline.get("events"))],
            *[_dict(item) for item in _list(energy.get("events"))],
            *[_dict(item) for item in _list(analysis.get("energy_peaks"))],
        ]
        seeds: list[_CandidateSeed] = []
        for item in events[:80]:
            score = _score(
                item.get("score") or item.get("energy") or item.get("intensity")
            )
            if score < 0.65:
                continue
            start, end = _range(item)
            if end <= start:
                end = start + 4.0
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type="high_energy_section",
                    reason=_text(item.get("reason"), maximum=500)
                    or "Analysis Signals V2 reports a high-energy interval.",
                    confidence=_score(0.4 + 0.5 * score),
                    standalone_score=_score(0.42 + 0.25 * score),
                    source_signals=["analysis_signals_v2_audio_energy"],
                )
            )
        return seeds

    @staticmethod
    def _planning_seeds(planning: dict[str, Any]) -> list[_CandidateSeed]:
        values: list[dict[str, Any]] = []
        for key in ("planning_candidates", "candidates", "selected_plans", "plans"):
            values.extend(_dict(item) for item in _list(planning.get(key)))
        seeds: list[_CandidateSeed] = []
        for item in values[:100]:
            start, end = _range(item)
            if end <= start:
                continue
            scores = _dict(item.get("scores"))
            confidence = _score(
                item.get("confidence")
                or item.get("overall_score")
                or item.get("viral_score")
                or scores.get("overall"),
                0.55,
            )
            payoff_present = bool(
                item.get("payoff_present")
                or _dict(item.get("payoff")).get("payoff_present")
                or _score(scores.get("payoff")) >= 0.55
            )
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type=BobaCandidateClipDiscoveryEngine._classify_text(
                        _text(
                            item.get("hook_category")
                            or item.get("candidate_type")
                            or item.get("selected_reason"),
                            maximum=300,
                        )
                    ),
                    reason=_text(
                        item.get("selected_reason")
                        or item.get("reason")
                        or item.get("why_selected"),
                        maximum=500,
                    )
                    or "Existing Olympus planning marked this as a candidate interval.",
                    confidence=confidence,
                    standalone_score=_score(
                        item.get("standalone_score") or scores.get("clarity"), 0.58
                    ),
                    setup_required=bool(item.get("setup_required")),
                    context_needed=bool(
                        item.get("context_needed") or item.get("setup_required")
                    ),
                    payoff_present=payoff_present,
                    source_topic=_text(item.get("source_topic"), maximum=160) or "unknown",
                    hook_idea=_text(item.get("hook_line"), maximum=300),
                    story_angle=_text(
                        item.get("story_shape") or item.get("story_summary"), maximum=400
                    ),
                    source_signals=["olympus_planning_candidate"],
                )
            )
        return seeds

    @staticmethod
    def _virality_seeds(virality: dict[str, Any]) -> list[_CandidateSeed]:
        values: list[dict[str, Any]] = []
        for key in (
            "editorial_moments",
            "viral_moments",
            "hotspots",
            "candidate_windows",
            "windows",
        ):
            values.extend(_dict(item) for item in _list(virality.get(key)))
        heatmap = virality.get("heatmap")
        values.extend(_dict(item) for item in _list(heatmap))
        timeline = _dict(virality.get("timeline") or heatmap)
        values.extend(_dict(item) for item in _list(timeline.get("events")))
        seeds: list[_CandidateSeed] = []
        for item in values[:80]:
            start, end = _range(item)
            if end <= start:
                end = start + 4.0
            reason = _text(
                item.get("reason") or item.get("detail") or item.get("label"), maximum=500
            )
            score = _score(
                item.get("confidence")
                or item.get("score")
                or item.get("heat")
                or item.get("strength"),
                0.55,
            )
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type=BobaCandidateClipDiscoveryEngine._classify_text(reason),
                    reason=reason or "Virality V2 identified a timed editorial moment.",
                    confidence=_score(0.35 + 0.55 * score),
                    standalone_score=_score(0.48 + 0.2 * score),
                    virality_reasons=[reason] if reason else [],
                    source_signals=["virality_v2_timed_cue"],
                )
            )
        return seeds

    @staticmethod
    def _transcript_cue_seeds(
        transcript: list[_TranscriptSegment],
    ) -> list[_CandidateSeed]:
        seeds: list[_CandidateSeed] = []
        for segment in transcript:
            folded = segment.text.casefold().replace("\u2019", "'")
            match = next(
                (
                    (phrase, candidate_type)
                    for phrase, candidate_type in _CUE_TYPES
                    if phrase in folded
                ),
                None,
            )
            if match is None:
                continue
            phrase, candidate_type = match
            payoff = candidate_type == "payoff_moment"
            seeds.append(
                _CandidateSeed(
                    start=segment.start,
                    end=segment.end,
                    candidate_type=candidate_type,
                    reason=f'Transcript cue "{phrase}" marks a possible editorial turn.',
                    confidence=0.58 if phrase != "but" else 0.5,
                    standalone_score=0.55 + (0.1 if payoff else 0.0),
                    payoff_present=payoff,
                    hook_idea=segment.text,
                    source_signals=["transcript_hook_cue"],
                )
            )
        return seeds

    def _transcript_fallback_seeds(
        self,
        transcript: list[_TranscriptSegment],
        duration: float,
    ) -> list[_CandidateSeed]:
        if not transcript:
            return []
        target = min(self.ideal_maximum_seconds, max(self.ideal_minimum_seconds, 30.0))
        seeds: list[_CandidateSeed] = []
        cursor = transcript[0].start
        while cursor < duration and len(seeds) < 12:
            group = [
                item
                for item in transcript
                if item.end > cursor and item.start < cursor + target
            ]
            if not group:
                cursor += target
                continue
            start = group[0].start
            end = group[-1].end
            text = " ".join(item.text for item in group)
            seeds.append(
                _CandidateSeed(
                    start=start,
                    end=end,
                    candidate_type=self._classify_text(text),
                    reason="Transcript fallback formed a bounded review window because stronger "
                    "whole-video signals were insufficient.",
                    confidence=0.42,
                    standalone_score=0.48,
                    hook_idea=group[0].text,
                    source_signals=["transcript_window_fallback"],
                    warnings=["Fallback transcript window; review context and payoff manually."],
                )
            )
            cursor = max(cursor + target, end)
        return seeds

    @staticmethod
    def _enrich_from_understanding(
        seeds: list[_CandidateSeed], understanding: dict[str, Any]
    ) -> None:
        if not understanding:
            return
        topics = [_dict(item) for item in _list(understanding.get("topic_timeline"))]
        emotions = [_dict(item) for item in _list(understanding.get("emotional_beats"))]
        links = [_dict(item) for item in _list(understanding.get("context_payoff_map"))]
        sections = [_dict(item) for item in _list(understanding.get("section_scores"))]
        for seed in seeds:
            overlapping_topics = [
                item
                for item in topics
                if _overlap_seconds(seed.start, seed.end, *_range(item)) > 0.0
            ]
            if overlapping_topics:
                topic = max(
                    overlapping_topics,
                    key=lambda item: _overlap_seconds(seed.start, seed.end, *_range(item)),
                )
                seed.source_topic = _text(topic.get("topic"), maximum=160) or seed.source_topic
                seed.topic_ids.append(_text(topic.get("segment_id"), maximum=128))
                if not seed.story_angle:
                    seed.story_angle = _text(topic.get("summary"), maximum=400)
            overlapping_emotions = [
                item
                for item in emotions
                if _overlap_seconds(seed.start, seed.end, *_range(item)) > 0.0
            ]
            if overlapping_emotions:
                beat = max(overlapping_emotions, key=lambda item: _score(item.get("intensity")))
                seed.emotion_label = (
                    _text(beat.get("emotion_label"), maximum=80) or seed.emotion_label
                )
                seed.emotion_ids.append(_text(beat.get("beat_id"), maximum=128))
            for link in links:
                context_start = _number(link.get("context_start_seconds"))
                payoff_end = _number(link.get("payoff_end_seconds"))
                if _overlap_seconds(seed.start, seed.end, context_start, payoff_end) <= 0.0:
                    continue
                seed.link_ids.append(_text(link.get("link_id"), maximum=128))
                payoff_start = _number(link.get("payoff_start_seconds"))
                if seed.end >= payoff_start:
                    seed.payoff_present = True
                    seed.required_end = max(seed.required_end, payoff_end)
                if bool(link.get("setup_required")) and seed.start > context_start + 0.5:
                    seed.setup_required = True
                    seed.context_needed = True
            for section in sections:
                if _overlap_seconds(seed.start, seed.end, *_range(section)) > 0.0:
                    seed.section_ids.append(_text(section.get("section_id"), maximum=128))

    @staticmethod
    def _virality_reasons(virality: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in (
            "why_this_can_work",
            "why_this_clip_works",
            "summary",
            "reason",
            "story_reasoning",
        ):
            value = virality.get(key)
            if isinstance(value, str):
                values.append(value)
        for key in ("recommendations", "strengths", "evidence", "editorial_moments"):
            for item in _list(virality.get(key)):
                data = _dict(item)
                values.append(
                    _text(
                        data.get("reason")
                        or data.get("detail")
                        or data.get("title")
                        or item,
                        maximum=260,
                    )
                )
        for item in _list(virality.get("category_scores")):
            data = _dict(item)
            if _score(data.get("score")) >= 0.6:
                values.append(
                    f"{_text(data.get('category') or data.get('label'), maximum=80)} "
                    f"score {_score(data.get('score')):.2f}"
                )
        return _unique(values, limit=12, maximum=260)

    @staticmethod
    def _apply_virality(seeds: list[_CandidateSeed], reasons: list[str]) -> None:
        if not reasons:
            return
        joined = " ".join(reasons).casefold()
        for seed in seeds:
            matched = [
                reason
                for reason in reasons
                if _words(seed.reason + " " + seed.hook_idea) & _words(reason)
            ]
            if not matched and seed.candidate_type in {
                "hook_moment",
                "curiosity_gap",
                "controversial_moment",
            } and any(term in joined for term in ("hook", "curiosity", "controvers")):
                matched = reasons[:1]
            if matched:
                seed.virality_reasons.extend(matched[:3])
                seed.source_signals.append("virality_v2_reason")
                seed.confidence = _score(seed.confidence + 0.04)

    @staticmethod
    def _apply_memory(seeds: list[_CandidateSeed], memory: dict[str, Any]) -> None:
        if not memory:
            return
        memory_texts: list[str] = []
        for key in ("source_summary", "summary", "preferred_patterns"):
            value = memory.get(key)
            if isinstance(value, str):
                memory_texts.append(value)
            else:
                memory_texts.extend(_text(item, maximum=180) for item in _list(value))
        for record in _list(memory.get("memory_records")):
            data = _dict(record)
            memory_texts.append(_text(data.get("summary"), maximum=180))
            memory_texts.extend(_text(item, maximum=180) for item in _list(data.get("evidence")))
        memory_words = _words(" ".join(memory_texts))
        if not memory_words:
            return
        for seed in seeds:
            seed_words = _words(seed.source_topic + " " + seed.story_angle + " " + seed.reason)
            if seed_words & memory_words:
                seed.source_signals.append("boba_project_memory_advisory")
                seed.confidence = _score(seed.confidence + 0.02)

    def _finalize_seed(
        self,
        project_id: str,
        seed: _CandidateSeed,
        transcript: list[_TranscriptSegment],
        duration: float,
    ) -> tuple[BobaCandidateClipV1 | None, BobaRejectedWindowV1 | None]:
        original_start = max(0.0, seed.start)
        original_end = min(duration, max(original_start, seed.end)) if duration else seed.end
        if original_end <= original_start:
            return None, BobaRejectedWindowV1(
                start_seconds=original_start,
                end_seconds=max(original_start, original_end),
                reason="invalid_window",
                confidence=_score(seed.confidence),
            )
        start, end = original_start, original_end
        warnings = list(seed.warnings)
        if duration > 0.0 and seed.end > duration:
            warnings.append("Candidate end was clamped to source duration.")
        if end - start > self.maximum_duration_seconds:
            if seed.payoff_present or seed.required_end:
                end = min(duration or end, max(end, seed.required_end))
                start = max(0.0, end - self.maximum_duration_seconds)
            else:
                center = (start + end) / 2.0
                start = max(0.0, center - self.maximum_duration_seconds / 2.0)
                end = start + self.maximum_duration_seconds
                if duration and end > duration:
                    end = duration
                    start = max(0.0, end - self.maximum_duration_seconds)
            warnings.append("Overlong source window was clamped to 90 seconds.")
        target = min(
            self.ideal_minimum_seconds,
            duration if duration > 0.0 else self.ideal_minimum_seconds,
        )
        if end - start < target:
            missing = target - (end - start)
            before_share = 0.65 if seed.setup_required else 0.45
            start = max(0.0, start - missing * before_share)
            end = min(duration or end + missing, end + (target - (end - start)))
            if end - start < target:
                start = max(0.0, end - target)
            if duration and end - start < target:
                end = min(duration, start + target)
        if seed.required_end > end:
            end = min(duration or seed.required_end, seed.required_end)
            if end - start > self.maximum_duration_seconds:
                start = max(0.0, end - self.maximum_duration_seconds)
                warnings.append(
                    "Payoff was preserved by moving the start; earlier context may be missing."
                )
                seed.context_needed = True
        if end - start < self.minimum_duration_seconds - 0.001:
            return None, BobaRejectedWindowV1(
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                reason="below_minimum_duration",
                confidence=_score(seed.confidence),
            )
        if end - start > self.maximum_duration_seconds:
            end = start + self.maximum_duration_seconds
        snippets = self._snippets(transcript, start, end)
        hook = _text(seed.hook_idea, maximum=300) or (snippets[0] if snippets else "")
        if not hook:
            hook = self._fallback_hook(seed)
        story_angle = _text(seed.story_angle, maximum=400) or _text(
            seed.source_topic if seed.source_topic != "unknown" else seed.reason,
            maximum=400,
        )
        title = self._title(seed, hook)
        pre_roll = max(0.0, original_start - start)
        post_roll = max(0.0, end - original_end)
        abrupt_start = bool(
            start > 0.0
            and pre_roll < 0.75
            and (seed.setup_required or self._starts_with_transition(hook))
        )
        abrupt_end = not seed.payoff_present
        if abrupt_start:
            warnings.append("Candidate may start abruptly; review the preceding sentence.")
        if abrupt_end:
            warnings.append("No confirmed payoff was found before the suggested end.")
        if seed.context_needed:
            warnings.append("This window may depend on context before its suggested start.")
        if end - start < self.ideal_minimum_seconds:
            warnings.append("Source duration prevents reaching the 25-second ideal minimum.")
        boundary = BobaBoundarySuggestionV1(
            recommended_start_seconds=round(start, 3),
            recommended_end_seconds=round(end, 3),
            pre_roll_seconds=round(pre_roll, 3),
            post_roll_seconds=round(post_roll, 3),
            abrupt_start_warning=abrupt_start,
            abrupt_end_warning=abrupt_end,
            reason=self._boundary_reason(seed, pre_roll, post_roll),
        )
        candidate_id = self._candidate_id(project_id, start, end, seed.candidate_type)
        evidence = BobaCandidateEvidenceV1(
            transcript_snippets=snippets,
            source_signals=_unique(seed.source_signals, limit=20, maximum=120),
            topic_segment_ids=_unique(seed.topic_ids, limit=12, maximum=128),
            emotional_beat_ids=_unique(seed.emotion_ids, limit=12, maximum=128),
            context_payoff_link_ids=_unique(seed.link_ids, limit=12, maximum=128),
            section_score_ids=_unique(seed.section_ids, limit=12, maximum=128),
            virality_reasons=_unique(seed.virality_reasons, limit=12, maximum=260),
        )
        return (
            BobaCandidateClipV1(
                candidate_id=candidate_id,
                project_id=project_id,
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                duration_seconds=round(end - start, 3),
                suggested_title=title,
                hook_idea=hook,
                story_angle=story_angle,
                candidate_type=seed.candidate_type,
                discovery_reason=_text(seed.reason, maximum=600),
                confidence=_score(seed.confidence),
                standalone_score=_score(seed.standalone_score),
                setup_required=seed.setup_required,
                payoff_present=seed.payoff_present,
                context_needed=seed.context_needed,
                source_topic=_text(seed.source_topic, maximum=160) or "unknown",
                emotion_label=_text(seed.emotion_label, maximum=80) or "unknown",
                virality_cues=evidence.virality_reasons,
                boundary_suggestion=boundary,
                evidence=evidence,
                warnings=_unique(warnings, limit=24, maximum=300),
            ),
            None,
        )

    @staticmethod
    def _snippets(
        transcript: list[_TranscriptSegment], start: float, end: float
    ) -> list[str]:
        values = [
            item.text
            for item in transcript
            if _overlap_seconds(start, end, item.start, item.end) > 0.0
        ]
        return _unique(values, limit=3, maximum=180)

    @staticmethod
    def _fallback_hook(seed: _CandidateSeed) -> str:
        if seed.candidate_type == "payoff_moment":
            return "Lead with the result, then preserve the explanation."
        if seed.candidate_type == "curiosity_gap":
            return "Open the loop without revealing the answer too early."
        if seed.source_topic != "unknown":
            return f"Why {seed.source_topic} matters in this moment."
        return "Open with the clearest self-contained claim in this interval."

    @staticmethod
    def _title(seed: _CandidateSeed, hook: str) -> str:
        if seed.source_topic != "unknown":
            label = seed.candidate_type.replace("_", " ").title()
            return _text(f"{seed.source_topic}: {label}", maximum=160)
        words = hook.rstrip(".!?").split()[:12]
        return _text(" ".join(words), maximum=160) or "Candidate Clip"

    @staticmethod
    def _starts_with_transition(text: str) -> bool:
        folded = text.casefold().lstrip("\"' ")
        return any(
            folded.startswith(value)
            for value in ("but ", "however ", "then ", "finally ", "and ")
        )

    @staticmethod
    def _boundary_reason(seed: _CandidateSeed, pre_roll: float, post_roll: float) -> str:
        reasons = ["Window was clamped to valid source time and a practical Shorts duration."]
        if pre_roll > 0.0:
            reasons.append("Pre-roll was added to reduce an abrupt opening.")
        if post_roll > 0.0:
            reasons.append("Post-roll was added to avoid an abrupt ending.")
        if seed.payoff_present:
            reasons.append("The known payoff remains inside the suggested boundary.")
        if seed.setup_required:
            reasons.append("Setup dependency is retained as an explicit review warning.")
        return " ".join(reasons)[:500]

    @staticmethod
    def _candidate_id(
        project_id: str, start: float, end: float, candidate_type: str
    ) -> str:
        value = f"{project_id}|{start:.3f}|{end:.3f}|{candidate_type}".encode()
        return f"candidate_{hashlib.sha256(value).hexdigest()[:16]}"

    @staticmethod
    def _priority(candidate: BobaCandidateClipV1) -> tuple[float, float, int, float]:
        return (
            candidate.confidence,
            candidate.standalone_score,
            int(candidate.payoff_present),
            -candidate.start_seconds,
        )

    def _deduplicate(
        self, candidates: list[BobaCandidateClipV1]
    ) -> tuple[list[BobaCandidateClipV1], list[BobaRejectedWindowV1], int, int]:
        kept: list[BobaCandidateClipV1] = []
        rejected: list[BobaRejectedWindowV1] = []
        duplicate_count = 0
        overlap_count = 0
        for candidate in sorted(candidates, key=self._priority, reverse=True):
            exact = next(
                (
                    item
                    for item in kept
                    if abs(item.start_seconds - candidate.start_seconds) <= 0.01
                    and abs(item.end_seconds - candidate.end_seconds) <= 0.01
                ),
                None,
            )
            if exact is not None:
                duplicate_count += 1
                rejected.append(
                    BobaRejectedWindowV1(
                        start_seconds=candidate.start_seconds,
                        end_seconds=candidate.end_seconds,
                        reason="exact_duplicate_window",
                        overlap_with_candidate_id=exact.candidate_id,
                        confidence=candidate.confidence,
                    )
                )
                continue
            overlapping = max(
                kept,
                key=lambda item: _overlap_ratio(
                    candidate.start_seconds,
                    candidate.end_seconds,
                    item.start_seconds,
                    item.end_seconds,
                ),
                default=None,
            )
            ratio = (
                _overlap_ratio(
                    candidate.start_seconds,
                    candidate.end_seconds,
                    overlapping.start_seconds,
                    overlapping.end_seconds,
                )
                if overlapping is not None
                else 0.0
            )
            if overlapping is not None and ratio > 0.8:
                overlap_count += 1
                rejected.append(
                    BobaRejectedWindowV1(
                        start_seconds=candidate.start_seconds,
                        end_seconds=candidate.end_seconds,
                        reason="high_overlap_lower_confidence",
                        overlap_with_candidate_id=overlapping.candidate_id,
                        confidence=candidate.confidence,
                    )
                )
                continue
            if overlapping is not None and ratio >= 0.5 and not self._meaningfully_diverse(
                candidate, overlapping
            ):
                candidate.warnings = _unique(
                    [
                        *candidate.warnings,
                        f"Overlaps {ratio:.0%} with {overlapping.candidate_id}; review both.",
                    ],
                    limit=24,
                    maximum=300,
                )
            kept.append(candidate)
        return kept, rejected, duplicate_count, overlap_count

    @staticmethod
    def _meaningfully_diverse(
        left: BobaCandidateClipV1, right: BobaCandidateClipV1
    ) -> bool:
        return bool(
            (
                left.source_topic != "unknown"
                and right.source_topic != "unknown"
                and left.source_topic != right.source_topic
            )
            or left.payoff_present != right.payoff_present
            or (
                left.emotion_label != "unknown"
                and right.emotion_label != "unknown"
                and left.emotion_label != right.emotion_label
            )
            or left.candidate_type != right.candidate_type
        )

    def _limit_with_diversity(
        self, candidates: list[BobaCandidateClipV1]
    ) -> tuple[list[BobaCandidateClipV1], list[BobaRejectedWindowV1]]:
        remaining = list(candidates)
        selected: list[BobaCandidateClipV1] = []
        topics: set[str] = set()
        emotions: set[str] = set()
        candidate_types: set[str] = set()
        while remaining and len(selected) < self.maximum_candidates:
            best = max(
                remaining,
                key=lambda item: (
                    item.confidence
                    + 0.08 * int(item.source_topic not in topics)
                    + 0.05 * int(item.emotion_label not in emotions)
                    + 0.06 * int(item.candidate_type not in candidate_types),
                    item.standalone_score,
                    int(item.payoff_present),
                    -item.start_seconds,
                ),
            )
            remaining.remove(best)
            selected.append(best)
            topics.add(best.source_topic)
            emotions.add(best.emotion_label)
            candidate_types.add(best.candidate_type)
        rejected = [
            BobaRejectedWindowV1(
                start_seconds=item.start_seconds,
                end_seconds=item.end_seconds,
                reason="candidate_limit_after_diversity_selection",
                confidence=item.confidence,
            )
            for item in remaining
        ]
        return selected, rejected

    @staticmethod
    def _diversity_summary(
        candidates: list[BobaCandidateClipV1],
        *,
        duplicate_count: int,
        overlap_count: int,
    ) -> BobaCandidateDiversitySummaryV1:
        topics = {item.source_topic for item in candidates if item.source_topic != "unknown"}
        emotions = {
            item.emotion_label for item in candidates if item.emotion_label != "unknown"
        }
        types = sorted({item.candidate_type for item in candidates})
        warnings: list[str] = []
        if len(candidates) >= 3 and len(topics) <= 1:
            warnings.append("Candidate topics have limited diversity.")
        if len(candidates) >= 3 and len(types) <= 1:
            warnings.append("Candidate types have limited diversity.")
        return BobaCandidateDiversitySummaryV1(
            candidate_count=len(candidates),
            topic_count=len(topics),
            emotion_count=len(emotions),
            candidate_types=types,
            duplicate_windows_removed=duplicate_count,
            high_overlap_windows_removed=overlap_count,
            warnings=warnings,
        )

    @staticmethod
    def _signal_usage(
        *,
        understanding: dict[str, Any],
        transcript: list[_TranscriptSegment],
        analysis: dict[str, Any],
        story: dict[str, Any],
        virality: dict[str, Any],
        planning: dict[str, Any],
        memory: dict[str, Any],
    ) -> BobaCandidateDiscoverySignalUsageV1:
        planning_used = bool(
            _list(planning.get("selected_plans"))
            or _list(planning.get("planning_candidates"))
            or _list(planning.get("plans"))
            or _list(planning.get("candidates"))
            or _dict(planning.get("planning_summary"))
        )
        availability = {
            "whole_video_understanding": bool(understanding),
            "transcript": bool(transcript),
            "analysis_signals_v2": bool(analysis),
            "story_analysis_v2": bool(story),
            "virality_v2": bool(virality),
            "planning_v2": planning_used,
            "boba_project_memory": bool(memory),
        }
        unavailable = [key for key, available in availability.items() if not available]
        warnings = []
        if not understanding:
            warnings.append(
                "Whole-video understanding was unavailable; local timed-signal fallback was used."
            )
        if not transcript:
            warnings.append("Transcript evidence was unavailable; candidate snippets are empty.")
        return BobaCandidateDiscoverySignalUsageV1(
            whole_video_understanding_used=bool(understanding),
            transcript_used=bool(transcript),
            analysis_signals_used=bool(analysis),
            story_used=bool(story),
            virality_used=bool(virality),
            planning_used=planning_used,
            memory_used=bool(memory),
            fallback_used=not bool(understanding),
            unavailable_signals=unavailable,
            warnings=warnings,
        )

    @staticmethod
    def _emotion_type(emotion: str) -> BobaCandidateType:
        folded = emotion.casefold()
        if any(value in folded for value in ("fun", "humor", "laugh", "amusement")):
            return "funny_moment"
        if any(value in folded for value in ("hope", "triumph", "motivat", "inspir")):
            return "motivational_moment"
        if any(value in folded for value in ("anger", "outrage", "controvers")):
            return "controversial_moment"
        return "emotional_beat"

    @staticmethod
    def _classify_text(value: str) -> BobaCandidateType:
        folded = value.casefold().replace("\u2019", "'")
        if any(term in folded for term in ("what happened next", "curiosity", "open loop")):
            return "curiosity_gap"
        if any(term in folded for term in ("controvers", "nobody talks", "truth is")):
            return "controversial_moment"
        if any(term in folded for term in ("funny", "laugh", "humor")):
            return "funny_moment"
        if any(term in folded for term in ("motiv", "inspir", "changed my life")):
            return "motivational_moment"
        if any(term in folded for term in ("payoff", "finally", "that's why")):
            return "payoff_moment"
        if any(term in folded for term in ("hook", "question")):
            return "hook_moment"
        if any(term in folded for term in ("suddenly", "turn", "realized", "however")):
            return "story_turn"
        if any(term in folded for term in ("learn", "how to", "lesson", "tip")):
            return "educational_moment"
        return "explanation_section"
