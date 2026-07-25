"""Manual-only performance feedback and advisory learning summaries for BOBA."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from olympus.boba.contracts import BobaContract, now_iso

BobaPerformanceEventType = Literal[
    "manual_clip_result",
    "manual_experiment_result",
    "manual_rating",
    "manual_note",
    "creator_interpretation",
    "reset",
    "export",
]
BobaPerformanceTargetType = Literal[
    "clip",
    "candidate",
    "clip_brief",
    "experiment",
    "experiment_variant",
    "project",
]
BobaPerformanceOutcomeLabel = Literal[
    "baseline_won",
    "variant_won",
    "no_clear_winner",
    "rejected_all",
    "inconclusive",
    "not_enough_data",
]
BobaPerformanceFactorCategory = Literal[
    "clip_type",
    "hook",
    "retention",
    "pacing",
    "context",
    "payoff",
    "caption",
    "motion",
    "music_mood",
    "sfx",
    "speech_clarity",
    "experiment_variant",
    "platform_fit",
    "general",
]
BobaPerformanceFactorPolarity = Literal[
    "positive",
    "negative",
    "neutral",
    "uncertain",
]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None

_SPACE = re.compile(r"\s+")
_NORMALIZE = re.compile(r"[^a-z0-9]+")
_SAFE_METRIC = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_DECISIVE_OUTCOMES = {"baseline_won", "variant_won"}
_EXPERIMENT_CATEGORY: dict[str, BobaPerformanceFactorCategory] = {
    "hook_ab_test": "hook",
    "caption_ab_test": "caption",
    "motion_ab_test": "motion",
    "music_mood_ab_test": "music_mood",
    "sfx_ab_test": "sfx",
    "opening_ab_test": "hook",
    "retention_ab_test": "retention",
    "brief_ab_test": "general",
    "project_style_test": "general",
}


def _text(value: Any, *, maximum: int = 700) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _normalized(value: Any, *, maximum: int = 120) -> str:
    return _NORMALIZE.sub("_", _text(value, maximum=maximum).casefold()).strip("_")


def _unique(values: Sequence[str], *, maximum: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:maximum]


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _confidence(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


class BobaManualPerformanceMetricsV1(BobaContract):
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    average_watch_time_seconds: float | None = Field(default=None, ge=0.0)
    average_view_duration_seconds: float | None = Field(default=None, ge=0.0)
    retention_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    click_through_rate_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )
    completion_rate_percent: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )
    follower_gain: int | None = Field(default=None, ge=0)
    manual_rank: int | None = Field(default=None, ge=1)
    custom_metrics: dict[str, float] = Field(default_factory=dict, max_length=24)

    @field_validator("custom_metrics")
    @classmethod
    def validate_custom_metrics(cls, value: dict[str, float]) -> dict[str, float]:
        cleaned: dict[str, float] = {}
        for key, metric_value in value.items():
            if not _SAFE_METRIC.fullmatch(key):
                raise ValueError("custom metric names must be compact safe identifiers")
            if metric_value < 0:
                raise ValueError("custom metric values cannot be negative")
            cleaned[key] = round(float(metric_value), 6)
        return cleaned

    def supplied_count(self) -> int:
        payload = self.model_dump(exclude={"custom_metrics"})
        return sum(value is not None for value in payload.values()) + len(
            self.custom_metrics
        )


class BobaPerformanceFeedbackEventV1(BobaContract):
    event_id: str = Field(
        default_factory=lambda: f"performance_event_{uuid4().hex[:20]}",
        min_length=1,
        max_length=128,
    )
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    event_type: BobaPerformanceEventType
    target_type: BobaPerformanceTargetType
    target_id: str = Field(min_length=1, max_length=180)
    candidate_id: str = Field(default="", max_length=128)
    brief_id: str = Field(default="", max_length=160)
    experiment_id: str = Field(default="", max_length=128)
    variant_id: str = Field(default="", max_length=128)
    user_entered: bool = True
    manual_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    creator_note: str = Field(default="", max_length=500)
    platform: str = Field(default="", max_length=80)
    source_label: str = Field(default="manual_entry", min_length=1, max_length=120)
    metrics: BobaManualPerformanceMetricsV1 = Field(
        default_factory=BobaManualPerformanceMetricsV1
    )
    retention_notes: str = Field(default="", max_length=500)
    creator_interpretation: str = Field(default="", max_length=500)
    outcome_label: BobaPerformanceOutcomeLabel | None = None
    baseline_id: str = Field(default="", max_length=128)
    selected_variant_id: str = Field(default="", max_length=128)
    should_feed_learning: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)

    @field_validator(
        "creator_note",
        "retention_notes",
        "creator_interpretation",
    )
    @classmethod
    def normalize_notes(cls, value: str) -> str:
        return _text(value, maximum=500)

    @field_validator("platform", "source_label")
    @classmethod
    def normalize_labels(cls, value: str) -> str:
        return _text(value, maximum=120)

    @model_validator(mode="after")
    def validate_manual_event(self) -> BobaPerformanceFeedbackEventV1:
        if not self.user_entered:
            raise ValueError("performance feedback must be explicitly user-entered")
        if self.event_type == "manual_experiment_result":
            if not self.experiment_id:
                raise ValueError("manual experiment results require experiment_id")
            if self.outcome_label is None:
                raise ValueError("manual experiment results require outcome_label")
            if self.outcome_label == "variant_won" and not (
                self.selected_variant_id or self.variant_id
            ):
                raise ValueError("variant_won requires a selected variant")
        if self.event_type in {"manual_note", "creator_interpretation"} and not (
            self.creator_note or self.creator_interpretation
        ):
            raise ValueError(f"{self.event_type} requires explicit creator text")
        if self.event_type == "manual_rating" and self.manual_rating is None:
            raise ValueError("manual_rating events require a rating")
        return self


class BobaPerformanceSnapshotV1(BobaContract):
    snapshot_id: str = Field(min_length=1, max_length=128)
    source_event_id: str = Field(default="", max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=180)
    candidate_id: str = Field(default="", max_length=128)
    brief_id: str = Field(default="", max_length=160)
    platform: str = Field(default="", max_length=80)
    metrics: BobaManualPerformanceMetricsV1
    manual_quality_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    creator_notes: str = Field(default="", max_length=500)
    retention_notes: str = Field(default="", max_length=500)
    data_confidence: float = Field(ge=0.0, le=1.0)
    entered_at: str = Field(default_factory=now_iso)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaPerformanceFactorV1(BobaContract):
    factor_id: str = Field(min_length=1, max_length=128)
    category: BobaPerformanceFactorCategory
    polarity: BobaPerformanceFactorPolarity
    summary: str = Field(min_length=1, max_length=500)
    source_artifact: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=180)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=12)


class BobaExperimentOutcomeReviewV1(BobaContract):
    outcome_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    experiment_id: str = Field(min_length=1, max_length=128)
    baseline_id: str = Field(default="", max_length=128)
    selected_variant_id: str = Field(default="", max_length=128)
    outcome_label: BobaPerformanceOutcomeLabel
    what_worked: list[str] = Field(default_factory=list, max_length=16)
    what_failed: list[str] = Field(default_factory=list, max_length=16)
    likely_success_factors: list[BobaPerformanceFactorV1] = Field(
        default_factory=list,
        max_length=24,
    )
    likely_failure_factors: list[BobaPerformanceFactorV1] = Field(
        default_factory=list,
        max_length=24,
    )
    confidence: float = Field(ge=0.0, le=1.0)
    should_feed_learning: bool = False
    learning_targets: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaPerformancePatternSummaryV1(BobaContract):
    strongest_positive_patterns: list[BobaPerformanceFactorV1] = Field(
        default_factory=list,
        max_length=32,
    )
    strongest_negative_patterns: list[BobaPerformanceFactorV1] = Field(
        default_factory=list,
        max_length=32,
    )
    repeated_winners: list[str] = Field(default_factory=list, max_length=32)
    repeated_failures: list[str] = Field(default_factory=list, max_length=32)
    contradictions: list[str] = Field(default_factory=list, max_length=32)
    risky_conclusions: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaPerformanceLearningHandoffV1(BobaContract):
    creator_learning_updates: list[str] = Field(default_factory=list, max_length=32)
    approval_rejection_updates: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    experimentation_updates: list[str] = Field(default_factory=list, max_length=32)
    ranking_guidance: list[str] = Field(default_factory=list, max_length=32)
    editorial_guidance: list[str] = Field(default_factory=list, max_length=32)
    hook_retention_guidance: list[str] = Field(default_factory=list, max_length=32)
    caption_motion_guidance: list[str] = Field(default_factory=list, max_length=32)
    music_mood_guidance: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False


class BobaPerformanceAuditSummaryV1(BobaContract):
    total_events: int = Field(default=0, ge=0)
    manual_clip_results: int = Field(default=0, ge=0)
    manual_experiment_results: int = Field(default=0, ge=0)
    snapshots_count: int = Field(default=0, ge=0)
    outcomes_count: int = Field(default=0, ge=0)
    user_entered_count: int = Field(default=0, ge=0)
    auto_collected_count: Literal[0] = 0
    export_available: bool = True
    reset_available: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaPerformanceFeedbackSignalUsageV1(BobaContract):
    experimentation_used: bool = False
    creator_learning_used: bool = False
    approval_rejection_used: bool = False
    clip_briefs_used: bool = False
    hook_retention_used: bool = False
    caption_motion_used: bool = False
    music_mood_used: bool = False
    clip_ranking_used: bool = False
    editorial_decision_used: bool = False
    memory_used: bool = False
    manual_feedback_used: bool = False
    analytics_api_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaPerformanceFeedbackSetV1(BobaContract):
    schema_version: Literal["boba_performance_feedback_v1"] = (
        "boba_performance_feedback_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    performance_events: list[BobaPerformanceFeedbackEventV1] = Field(
        default_factory=list,
        max_length=5000,
    )
    performance_snapshots: list[BobaPerformanceSnapshotV1] = Field(
        default_factory=list,
        max_length=2000,
    )
    experiment_outcomes: list[BobaExperimentOutcomeReviewV1] = Field(
        default_factory=list,
        max_length=1000,
    )
    pattern_summary: BobaPerformancePatternSummaryV1
    learning_handoff: BobaPerformanceLearningHandoffV1
    audit_summary: BobaPerformanceAuditSummaryV1
    signal_usage: BobaPerformanceFeedbackSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaPerformanceFeedbackBrainV1:
    """Summarize explicit creator-entered results without collecting analytics."""

    def create_event(
        self,
        project_id: str,
        *,
        event_type: BobaPerformanceEventType,
        target_type: BobaPerformanceTargetType,
        target_id: str,
        candidate_id: str = "",
        brief_id: str = "",
        experiment_id: str = "",
        variant_id: str = "",
        manual_rating: float | None = None,
        creator_note: str = "",
        platform: str = "",
        source_label: str = "manual_entry",
        metrics: BobaManualPerformanceMetricsV1 | Mapping[str, Any] | None = None,
        retention_notes: str = "",
        creator_interpretation: str = "",
        outcome_label: BobaPerformanceOutcomeLabel | None = None,
        baseline_id: str = "",
        selected_variant_id: str = "",
        should_feed_learning: bool = False,
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> BobaPerformanceFeedbackEventV1:
        metric_model = (
            metrics
            if isinstance(metrics, BobaManualPerformanceMetricsV1)
            else BobaManualPerformanceMetricsV1.model_validate(metrics or {})
        )
        warnings = [
            "This event contains creator-entered data only.",
            "No platform connection or analytics collection occurred.",
        ]
        if metric_model.supplied_count() == 0:
            warnings.append("No numeric performance metrics were entered.")
        return BobaPerformanceFeedbackEventV1(
            **({"event_id": event_id} if event_id else {}),
            **({"created_at": created_at} if created_at else {}),
            project_id=project_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            candidate_id=candidate_id,
            brief_id=brief_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
            user_entered=True,
            manual_rating=manual_rating,
            creator_note=creator_note,
            platform=platform,
            source_label=source_label,
            metrics=metric_model,
            retention_notes=retention_notes,
            creator_interpretation=creator_interpretation,
            outcome_label=outcome_label,
            baseline_id=baseline_id,
            selected_variant_id=selected_variant_id,
            should_feed_learning=should_feed_learning,
            warnings=warnings,
        )

    def analyze(
        self,
        project_id: str,
        performance_events: Sequence[BobaPerformanceFeedbackEventV1],
        *,
        source_id: str | None = None,
        performance_snapshots: Sequence[
            BobaPerformanceSnapshotV1 | Mapping[str, Any]
        ] = (),
        manual_experiment_outcomes: Sequence[
            BobaExperimentOutcomeReviewV1 | Mapping[str, Any]
        ] = (),
        experimentation: ArtifactValue = None,
        experiment_manual_results: Sequence[BaseModel | Mapping[str, Any]] = (),
        creator_learning: ArtifactValue = None,
        approval_rejection_learning: ArtifactValue = None,
        clip_briefs: ArtifactValue = None,
        hook_retention: ArtifactValue = None,
        caption_motion: ArtifactValue = None,
        music_mood: ArtifactValue = None,
        clip_ranking: ArtifactValue = None,
        editorial_decision: ArtifactValue = None,
        boba_memory: ArtifactValue = None,
        dry_run: bool = False,
    ) -> BobaPerformanceFeedbackSetV1:
        events = list(performance_events)
        if any(event.project_id != project_id for event in events):
            raise ValueError("performance events must belong to the requested project")
        if any(not event.user_entered for event in events):
            raise ValueError("V1 accepts explicit user-entered performance data only")

        artifacts = {
            "experimentation": _dict(experimentation),
            "creator_learning": _dict(creator_learning),
            "approval_rejection_learning": _dict(approval_rejection_learning),
            "clip_briefs": _dict(clip_briefs),
            "hook_retention": _dict(hook_retention),
            "caption_motion": _dict(caption_motion),
            "music_mood": _dict(music_mood),
            "clip_ranking": _dict(clip_ranking),
            "editorial_decision": _dict(editorial_decision),
            "memory": _dict(boba_memory),
        }
        events = self._merge_experiment_manual_results(
            project_id,
            events,
            experiment_manual_results,
        )
        snapshots = self._snapshots(events, performance_snapshots)
        outcomes = self._outcomes(
            project_id,
            events,
            manual_experiment_outcomes,
            artifacts["experimentation"],
            snapshots,
        )
        factors = [
            factor
            for snapshot in snapshots
            for factor in self._snapshot_factors(snapshot, artifacts)
        ]
        factors.extend(
            factor
            for outcome in outcomes
            for factor in [
                *outcome.likely_success_factors,
                *outcome.likely_failure_factors,
            ]
        )
        pattern_summary = self._patterns(factors)
        handoff = self._learning_handoff(pattern_summary, outcomes)
        audit = self._audit(events, snapshots, outcomes)
        usage = self._signal_usage(artifacts, events)
        warnings = [
            "Performance data is manual in V1; no platform connection was used.",
            "No analytics API, scraping, hidden tracking, or fabricated metric was used.",
            "Learning guidance is advisory and was not applied automatically.",
        ]
        limitations = [
            "User-entered metrics are not independently verified.",
            "Cross-platform metric totals are not directly comparable without context.",
            "One result is weak evidence; repeated consistent results are required.",
        ]
        if not events:
            warnings.append("No manual performance feedback events were available.")
            limitations.append(
                "Performance patterns and experiment winners cannot be inferred."
            )
        if not snapshots:
            warnings.append("No performance snapshot could be created.")
        if pattern_summary.contradictions:
            warnings.append(
                "Contradictory manual results were retained and reduced confidence."
            )
        if dry_run:
            warnings.append("Dry run: performance feedback was not persisted.")
        created_at = max((event.created_at for event in events), default="") or now_iso()
        return BobaPerformanceFeedbackSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            created_at=created_at,
            performance_events=events[-5000:],
            performance_snapshots=snapshots[-2000:],
            experiment_outcomes=outcomes[-1000:],
            pattern_summary=pattern_summary,
            learning_handoff=handoff,
            audit_summary=audit,
            signal_usage=usage,
            warnings=_unique(warnings, maximum=64),
            limitations=_unique(limitations, maximum=64),
        )

    def snapshot_from_event(
        self,
        event: BobaPerformanceFeedbackEventV1,
    ) -> BobaPerformanceSnapshotV1 | None:
        if event.event_type in {"reset", "export"}:
            return None
        has_manual_content = bool(
            event.metrics.supplied_count()
            or event.manual_rating is not None
            or event.creator_note
            or event.retention_notes
            or event.creator_interpretation
        )
        if not has_manual_content and event.event_type == "manual_experiment_result":
            return None
        confidence = 0.12
        metric_count = event.metrics.supplied_count()
        confidence += min(0.42, metric_count * 0.07)
        confidence += 0.14 if event.manual_rating is not None else 0.0
        confidence += 0.1 if event.creator_note or event.creator_interpretation else 0.0
        confidence += 0.08 if event.retention_notes else 0.0
        confidence += 0.04 if event.platform else 0.0
        warnings: list[str] = []
        limitations = [
            "Snapshot values are creator-entered and not platform-verified.",
        ]
        if metric_count == 0:
            warnings.append("No numeric metrics were supplied; confidence is limited.")
        if event.manual_rating is None:
            warnings.append("No manual quality rating was supplied.")
        if not event.creator_note and not event.creator_interpretation:
            limitations.append("No creator interpretation explains the entered result.")
        target_id = (
            event.selected_variant_id
            or event.variant_id
            or event.target_id
        )
        return BobaPerformanceSnapshotV1(
            snapshot_id=_stable_id("performance_snapshot", event.event_id),
            source_event_id=event.event_id,
            project_id=event.project_id,
            target_id=target_id,
            candidate_id=event.candidate_id,
            brief_id=event.brief_id,
            platform=event.platform,
            metrics=event.metrics,
            manual_quality_rating=event.manual_rating,
            creator_notes=event.creator_note or event.creator_interpretation,
            retention_notes=event.retention_notes,
            data_confidence=_confidence(confidence),
            entered_at=event.created_at,
            warnings=warnings,
            limitations=limitations,
        )

    def _snapshots(
        self,
        events: Sequence[BobaPerformanceFeedbackEventV1],
        supplied: Sequence[BobaPerformanceSnapshotV1 | Mapping[str, Any]],
    ) -> list[BobaPerformanceSnapshotV1]:
        by_id: dict[str, BobaPerformanceSnapshotV1] = {}
        for item in supplied:
            snapshot = (
                item
                if isinstance(item, BobaPerformanceSnapshotV1)
                else BobaPerformanceSnapshotV1.model_validate(item)
            )
            by_id[snapshot.snapshot_id] = snapshot
        for event in events:
            event_snapshot = self.snapshot_from_event(event)
            if event_snapshot is not None:
                by_id[event_snapshot.snapshot_id] = event_snapshot
        return sorted(by_id.values(), key=lambda item: (item.entered_at, item.snapshot_id))

    def _merge_experiment_manual_results(
        self,
        project_id: str,
        events: list[BobaPerformanceFeedbackEventV1],
        results: Sequence[BaseModel | Mapping[str, Any]],
    ) -> list[BobaPerformanceFeedbackEventV1]:
        by_id = {event.event_id: event for event in events}
        label_map: dict[str, BobaPerformanceOutcomeLabel] = {
            "baseline_preferred": "baseline_won",
            "variant_preferred": "variant_won",
            "no_clear_winner": "no_clear_winner",
            "rejected_all": "rejected_all",
            "needs_more_review": "inconclusive",
        }
        for raw_result in results:
            item = _dict(raw_result)
            result_id = _text(item.get("result_id"), maximum=128)
            experiment_id = _text(item.get("experiment_id"), maximum=128)
            selected_variant_id = _text(
                item.get("selected_variant_id"),
                maximum=128,
            )
            raw_label = _text(item.get("outcome_label"), maximum=80)
            if not result_id or not experiment_id or raw_label not in label_map:
                continue
            event_id = _stable_id("performance_from_experiment", result_id)
            by_id.setdefault(
                event_id,
                self.create_event(
                    project_id,
                    event_type="manual_experiment_result",
                    target_type="experiment",
                    target_id=experiment_id,
                    experiment_id=experiment_id,
                    variant_id=selected_variant_id,
                    selected_variant_id=selected_variant_id,
                    manual_rating=(
                        float(item["manual_rating"])
                        if item.get("manual_rating") is not None
                        else None
                    ),
                    creator_note=_text(item.get("creator_note"), maximum=500),
                    source_label="experimentation_manual_result",
                    outcome_label=label_map[raw_label],
                    should_feed_learning=bool(item.get("should_feed_learning")),
                    event_id=event_id,
                    created_at=_text(item.get("created_at"), maximum=80) or None,
                ),
            )
        return sorted(by_id.values(), key=lambda item: (item.created_at, item.event_id))

    def _outcomes(
        self,
        project_id: str,
        events: Sequence[BobaPerformanceFeedbackEventV1],
        supplied: Sequence[BobaExperimentOutcomeReviewV1 | Mapping[str, Any]],
        experimentation: Mapping[str, Any],
        snapshots: Sequence[BobaPerformanceSnapshotV1],
    ) -> list[BobaExperimentOutcomeReviewV1]:
        by_id: dict[str, BobaExperimentOutcomeReviewV1] = {}
        for item in supplied:
            outcome = (
                item
                if isinstance(item, BobaExperimentOutcomeReviewV1)
                else BobaExperimentOutcomeReviewV1.model_validate(item)
            )
            by_id[outcome.outcome_id] = outcome
        plans = {
            _text(plan.get("experiment_id"), maximum=128): plan
            for plan in (
                _dict(item)
                for item in _list(experimentation.get("experiment_plans"))
            )
            if plan.get("experiment_id")
        }
        snapshots_by_event = {
            snapshot.source_event_id: snapshot for snapshot in snapshots
        }
        for event in events:
            if event.event_type != "manual_experiment_result":
                continue
            outcome = self._outcome_from_event(
                project_id,
                event,
                plans.get(event.experiment_id, {}),
                snapshots_by_event.get(event.event_id),
            )
            by_id[outcome.outcome_id] = outcome
        return sorted(by_id.values(), key=lambda item: item.outcome_id)

    def _outcome_from_event(
        self,
        project_id: str,
        event: BobaPerformanceFeedbackEventV1,
        plan: Mapping[str, Any],
        snapshot: BobaPerformanceSnapshotV1 | None,
    ) -> BobaExperimentOutcomeReviewV1:
        label = event.outcome_label or "not_enough_data"
        baseline = _dict(plan.get("baseline"))
        variants = [_dict(item) for item in _list(plan.get("variants"))]
        selected_variant_id = event.selected_variant_id or event.variant_id
        selected_variant = next(
            (
                item
                for item in variants
                if _text(item.get("variant_id"), maximum=128)
                == selected_variant_id
            ),
            {},
        )
        baseline_id = event.baseline_id or _text(
            baseline.get("baseline_id"),
            maximum=128,
        )
        experiment_type = _text(plan.get("experiment_type"), maximum=80)
        category = _EXPERIMENT_CATEGORY.get(experiment_type, "experiment_variant")
        what_worked: list[str] = []
        what_failed: list[str] = []
        success_factors: list[BobaPerformanceFactorV1] = []
        failure_factors: list[BobaPerformanceFactorV1] = []
        evidence = _unique(
            [
                event.creator_note,
                event.creator_interpretation,
                *(
                    [f"manual rating {event.manual_rating:.1f}/5"]
                    if event.manual_rating is not None
                    else []
                ),
            ],
            maximum=8,
        )
        base_confidence = 0.24
        base_confidence += 0.12 if plan else 0.0
        base_confidence += 0.14 if event.manual_rating is not None else 0.0
        base_confidence += 0.12 if event.creator_note or event.creator_interpretation else 0.0
        base_confidence += (
            min(0.2, snapshot.metrics.supplied_count() * 0.04)
            if snapshot is not None
            else 0.0
        )
        if label == "variant_won":
            description = _text(
                selected_variant.get("summary")
                or selected_variant.get("instruction")
                or selected_variant_id,
                maximum=500,
            )
            what_worked.append(
                f"The creator marked the selected variant as the winner: {description}."
            )
            what_failed.append(
                "The baseline was less preferred in this explicit comparison."
            )
            success_factors.append(
                self._factor(
                    category=category,
                    polarity="positive",
                    summary=f"{category}: selected experiment variant won",
                    source_artifact="experimentation",
                    source_field="experiment_plans[].variants",
                    confidence=base_confidence,
                    evidence=evidence,
                    identity=event.event_id,
                )
            )
        elif label == "baseline_won":
            description = _text(
                baseline.get("summary")
                or baseline.get("current_instruction")
                or baseline_id,
                maximum=500,
            )
            what_worked.append(
                f"The creator marked the traceable baseline as the winner: {description}."
            )
            what_failed.append(
                "The selected variant did not improve the explicit comparison."
            )
            failure_factors.append(
                self._factor(
                    category=category,
                    polarity="negative",
                    summary=f"{category}: tested variant lost to baseline",
                    source_artifact="experimentation",
                    source_field="experiment_plans[].variants",
                    confidence=base_confidence,
                    evidence=evidence,
                    identity=event.event_id,
                )
            )
        else:
            what_failed.append(
                "The explicit result did not establish a reliable winner."
            )
            base_confidence -= 0.14
            success_factors.append(
                self._factor(
                    category=category,
                    polarity="uncertain",
                    summary=f"{category}: experiment outcome is inconclusive",
                    source_artifact="performance_feedback",
                    source_field="performance_events[].outcome_label",
                    confidence=base_confidence,
                    evidence=evidence,
                    identity=event.event_id,
                )
            )
        decisive = label in _DECISIVE_OUTCOMES
        confidence = _confidence(base_confidence)
        should_feed = bool(
            event.should_feed_learning and decisive and confidence >= 0.45
        )
        learning_targets = (
            _unique(
                [
                    "creator_learning",
                    "approval_rejection_learning",
                    "experimentation",
                    self._module_for_category(category),
                ],
                maximum=16,
            )
            if should_feed
            else []
        )
        warnings = [
            "Outcome is based on explicit creator-entered information.",
            "No winner was applied automatically.",
        ]
        if not plan:
            warnings.append("The saved experimentation plan was unavailable.")
        if not decisive:
            warnings.append("Inconclusive outcomes must not create strong learning.")
        if event.should_feed_learning and not should_feed:
            warnings.append(
                "Learning handoff was withheld because evidence is weak or inconclusive."
            )
        return BobaExperimentOutcomeReviewV1(
            outcome_id=_stable_id(
                "performance_outcome",
                event.event_id,
                event.experiment_id,
            ),
            project_id=project_id,
            experiment_id=event.experiment_id,
            baseline_id=baseline_id,
            selected_variant_id=selected_variant_id,
            outcome_label=label,
            what_worked=what_worked,
            what_failed=what_failed,
            likely_success_factors=success_factors,
            likely_failure_factors=failure_factors,
            confidence=confidence,
            should_feed_learning=should_feed,
            learning_targets=learning_targets,
            warnings=warnings,
            limitations=[
                "Manual experiment results do not prove audience causality.",
                "Other creative and distribution variables may differ outside V1.",
            ],
        )

    def _snapshot_factors(
        self,
        snapshot: BobaPerformanceSnapshotV1,
        artifacts: Mapping[str, dict[str, Any]],
    ) -> list[BobaPerformanceFactorV1]:
        polarity = self._snapshot_polarity(snapshot)
        evidence = self._snapshot_evidence(snapshot)
        factors: list[BobaPerformanceFactorV1] = []
        note_text = " ".join(
            [snapshot.creator_notes, snapshot.retention_notes]
        ).casefold()
        note_specs: tuple[
            tuple[tuple[str, ...], BobaPerformanceFactorCategory, str],
            ...,
        ] = (
            (
                ("clean caption", "captions worked", "caption readable"),
                "caption",
                "caption: clean readable treatment",
            ),
            (
                ("heavy motion", "too much zoom", "motion hurt"),
                "motion",
                "motion: heavy treatment hurt clarity",
            ),
            (
                ("slow hook", "slow opening"),
                "hook",
                "hook: slow opening underperformed",
            ),
            (
                ("dropped before payoff", "drop before payoff"),
                "retention",
                "retention: viewers reportedly dropped before payoff",
            ),
            (
                ("payoff worked", "strong payoff"),
                "payoff",
                "payoff: supported ending worked",
            ),
            (
                ("wrong music", "music mood"),
                "music_mood",
                "music mood: creator reported fit difference",
            ),
            (
                ("speech unclear", "could not hear"),
                "speech_clarity",
                "speech clarity: creator reported reduced clarity",
            ),
        )
        for terms, category, summary in note_specs:
            if any(term in note_text for term in terms):
                note_polarity = polarity
                if any(
                    negative in note_text
                    for negative in ("hurt", "wrong", "slow", "dropped", "unclear")
                ):
                    note_polarity = "negative"
                if any(
                    positive in note_text
                    for positive in ("worked", "readable", "strong payoff")
                ):
                    note_polarity = "positive"
                factors.append(
                    self._factor(
                        category=category,
                        polarity=note_polarity,
                        summary=summary,
                        source_artifact="performance_feedback",
                        source_field="performance_snapshots[].creator_notes",
                        confidence=snapshot.data_confidence - 0.04,
                        evidence=evidence,
                        identity=snapshot.snapshot_id,
                    )
                )
        candidate_traits = self._candidate_traits(snapshot.candidate_id, artifacts)
        for category, value, source_artifact, source_field in candidate_traits:
            factors.append(
                self._factor(
                    category=category,
                    polarity=polarity,
                    summary=f"{category}: {_text(value, maximum=140)}",
                    source_artifact=source_artifact,
                    source_field=source_field,
                    confidence=snapshot.data_confidence,
                    evidence=evidence,
                    identity=f"{snapshot.snapshot_id}:{category}:{value}",
                )
            )
        if not factors:
            factors.append(
                self._factor(
                    category="general",
                    polarity=polarity,
                    summary="general: explicit manual performance result",
                    source_artifact="performance_feedback",
                    source_field="performance_snapshots",
                    confidence=snapshot.data_confidence,
                    evidence=evidence,
                    identity=snapshot.snapshot_id,
                )
            )
        if snapshot.platform:
            factors.append(
                self._factor(
                    category="platform_fit",
                    polarity="uncertain",
                    summary=f"platform fit: {snapshot.platform}",
                    source_artifact="performance_feedback",
                    source_field="performance_snapshots[].platform",
                    confidence=snapshot.data_confidence - 0.18,
                    evidence=[
                        "Platform was entered manually; cross-platform causality is unknown."
                    ],
                    identity=f"{snapshot.snapshot_id}:platform",
                )
            )
        return factors

    @staticmethod
    def _snapshot_polarity(
        snapshot: BobaPerformanceSnapshotV1,
    ) -> BobaPerformanceFactorPolarity:
        rating = snapshot.manual_quality_rating
        if rating is not None:
            if rating >= 4.0:
                return "positive"
            if rating <= 2.5:
                return "negative"
            return "neutral"
        metrics = snapshot.metrics
        if metrics.manual_rank is not None and metrics.manual_rank <= 3:
            return "positive"
        high_rates = [
            value
            for value in (
                metrics.retention_percent,
                metrics.completion_rate_percent,
            )
            if value is not None
        ]
        if high_rates and max(high_rates) >= 70.0:
            return "positive"
        if high_rates and min(high_rates) < 35.0:
            return "negative"
        return "uncertain"

    @staticmethod
    def _snapshot_evidence(snapshot: BobaPerformanceSnapshotV1) -> list[str]:
        evidence: list[str] = []
        if snapshot.manual_quality_rating is not None:
            evidence.append(
                f"manual quality rating {snapshot.manual_quality_rating:.1f}/5"
            )
        if snapshot.creator_notes:
            evidence.append(snapshot.creator_notes)
        if snapshot.retention_notes:
            evidence.append(snapshot.retention_notes)
        metric_payload = snapshot.metrics.model_dump(
            exclude_none=True,
            exclude={"custom_metrics"},
        )
        evidence.extend(
            f"user-entered {key}={value}"
            for key, value in list(metric_payload.items())[:5]
        )
        evidence.extend(
            f"user-entered {key}={value}"
            for key, value in list(snapshot.metrics.custom_metrics.items())[:3]
        )
        return _unique(
            [_text(item, maximum=300) for item in evidence],
            maximum=12,
        )

    def _candidate_traits(
        self,
        candidate_id: str,
        artifacts: Mapping[str, dict[str, Any]],
    ) -> list[
        tuple[BobaPerformanceFactorCategory, str, str, str]
    ]:
        if not candidate_id:
            return []
        traits: list[
            tuple[BobaPerformanceFactorCategory, str, str, str]
        ] = []
        hook = self._matching_item(
            artifacts["hook_retention"],
            ("analyses",),
            candidate_id,
        )
        hook_analysis = _dict(hook.get("hook_analysis"))
        hook_type = _text(hook_analysis.get("hook_type"), maximum=120)
        if hook_type:
            traits.append(
                (
                    "hook",
                    hook_type.replace("_", " "),
                    "hook_retention",
                    "analyses[].hook_analysis.hook_type",
                )
            )
        caption_motion = self._matching_item(
            artifacts["caption_motion"],
            ("recommendations",),
            candidate_id,
        )
        caption = _dict(caption_motion.get("caption_recommendation"))
        caption_style = _text(caption.get("caption_style"), maximum=120)
        if caption_style:
            traits.append(
                (
                    "caption",
                    caption_style.replace("_", " "),
                    "caption_motion",
                    "recommendations[].caption_recommendation.caption_style",
                )
            )
        motion = _dict(caption_motion.get("motion_recommendation"))
        motion_style = _text(motion.get("motion_style"), maximum=120)
        if motion_style:
            traits.append(
                (
                    "motion",
                    motion_style.replace("_", " "),
                    "caption_motion",
                    "recommendations[].motion_recommendation.motion_style",
                )
            )
        music_item = self._matching_item(
            artifacts["music_mood"],
            ("recommendations",),
            candidate_id,
        )
        mood = _dict(music_item.get("music_mood"))
        primary_mood = _text(mood.get("primary_mood"), maximum=120)
        if primary_mood:
            traits.append(
                (
                    "music_mood",
                    primary_mood.replace("_", " "),
                    "music_mood",
                    "recommendations[].music_mood.primary_mood",
                )
            )
        brief = self._matching_item(
            artifacts["clip_briefs"],
            ("selected_briefs", "backup_briefs", "blocked_briefs"),
            candidate_id,
        )
        clip_type = _text(
            brief.get("clip_type")
            or brief.get("candidate_type")
            or brief.get("story_shape"),
            maximum=120,
        )
        if clip_type:
            traits.append(
                (
                    "clip_type",
                    clip_type.replace("_", " "),
                    "clip_briefs",
                    "selected_briefs[].clip_type",
                )
            )
        return traits[:8]

    @staticmethod
    def _matching_item(
        artifact: Mapping[str, Any],
        collections: Sequence[str],
        candidate_id: str,
    ) -> dict[str, Any]:
        for collection in collections:
            for raw in _list(artifact.get(collection)):
                item = _dict(raw)
                if _text(
                    item.get("candidate_id") or item.get("clip_id"),
                    maximum=128,
                ) == candidate_id:
                    return item
        return {}

    @staticmethod
    def _factor(
        *,
        category: BobaPerformanceFactorCategory,
        polarity: BobaPerformanceFactorPolarity,
        summary: str,
        source_artifact: str,
        source_field: str,
        confidence: float,
        evidence: Sequence[str],
        identity: str,
    ) -> BobaPerformanceFactorV1:
        return BobaPerformanceFactorV1(
            factor_id=_stable_id(
                "performance_factor",
                identity,
                category,
                polarity,
                summary,
            ),
            category=category,
            polarity=polarity,
            summary=_text(summary, maximum=500),
            source_artifact=source_artifact,
            source_field=source_field,
            confidence=_confidence(confidence),
            evidence=_unique(
                [_text(item, maximum=300) for item in evidence],
                maximum=12,
            ),
        )

    def _patterns(
        self,
        factors: Sequence[BobaPerformanceFactorV1],
    ) -> BobaPerformancePatternSummaryV1:
        groups: dict[
            tuple[str, str],
            list[BobaPerformanceFactorV1],
        ] = defaultdict(list)
        for factor in factors:
            groups[(factor.category, _normalized(factor.summary))].append(factor)

        aggregated: list[BobaPerformanceFactorV1] = []
        repeated_winners: list[str] = []
        repeated_failures: list[str] = []
        risky: list[str] = []
        contradictions: list[str] = []
        for (category, _summary_key), items in groups.items():
            polarities = [item.polarity for item in items]
            positive_count = polarities.count("positive")
            negative_count = polarities.count("negative")
            dominant: BobaPerformanceFactorPolarity
            if positive_count and negative_count:
                dominant = "uncertain"
            elif positive_count:
                dominant = "positive"
            elif negative_count:
                dominant = "negative"
            elif "neutral" in polarities:
                dominant = "neutral"
            else:
                dominant = "uncertain"
            average_confidence = sum(item.confidence for item in items) / len(items)
            repeat_boost = min(0.2, max(0, len(items) - 1) * 0.06)
            contradiction_penalty = 0.2 if positive_count and negative_count else 0.0
            aggregate = self._factor(
                category=category,  # type: ignore[arg-type]
                polarity=dominant,
                summary=items[0].summary,
                source_artifact="performance_feedback",
                source_field="pattern_summary",
                confidence=average_confidence + repeat_boost - contradiction_penalty,
                evidence=[
                    evidence
                    for item in items
                    for evidence in item.evidence[:2]
                ][:12],
                identity="|".join(item.factor_id for item in items),
            )
            aggregated.append(aggregate)
            if positive_count >= 2 and negative_count == 0:
                repeated_winners.append(
                    f"{items[0].summary} repeated in {positive_count} positive result(s)."
                )
            if negative_count >= 2 and positive_count == 0:
                repeated_failures.append(
                    f"{items[0].summary} repeated in {negative_count} negative result(s)."
                )
            if positive_count and negative_count:
                contradictions.append(
                    f"{items[0].summary} has both positive and negative manual results."
                )
            if len(items) == 1 and dominant in {"positive", "negative"}:
                risky.append(
                    f"{items[0].summary} has only one explicit result and remains weak evidence."
                )
        positives = sorted(
            (item for item in aggregated if item.polarity == "positive"),
            key=lambda item: item.confidence,
            reverse=True,
        )[:32]
        negatives = sorted(
            (item for item in aggregated if item.polarity == "negative"),
            key=lambda item: item.confidence,
            reverse=True,
        )[:32]
        decisive = [
            item
            for item in aggregated
            if item.polarity in {"positive", "negative"}
        ]
        confidence = (
            sum(item.confidence for item in decisive) / len(decisive)
            if decisive
            else 0.0
        )
        confidence += min(0.12, (len(repeated_winners) + len(repeated_failures)) * 0.04)
        confidence -= min(0.3, len(contradictions) * 0.12)
        warnings = [
            "Patterns summarize creator-entered evidence, not audience causality.",
        ]
        if risky:
            warnings.append("Single-result conclusions remain provisional.")
        if contradictions:
            warnings.append("Contradictions were retained and reduced confidence.")
        return BobaPerformancePatternSummaryV1(
            strongest_positive_patterns=positives,
            strongest_negative_patterns=negatives,
            repeated_winners=_unique(repeated_winners, maximum=32),
            repeated_failures=_unique(repeated_failures, maximum=32),
            contradictions=_unique(contradictions, maximum=32),
            risky_conclusions=_unique(risky, maximum=32),
            confidence=_confidence(confidence),
            warnings=warnings,
        )

    def _learning_handoff(
        self,
        patterns: BobaPerformancePatternSummaryV1,
        outcomes: Sequence[BobaExperimentOutcomeReviewV1],
    ) -> BobaPerformanceLearningHandoffV1:
        positive = patterns.strongest_positive_patterns
        negative = patterns.strongest_negative_patterns
        reviewed_outcomes = [
            outcome
            for outcome in outcomes
            if outcome.should_feed_learning
        ]
        creator_updates = [
            f"Review explicit preference signal: {factor.summary}."
            for factor in [*positive, *negative]
            if factor.confidence >= 0.35
        ]
        approval_updates = [
            (
                "Review as a provisional "
                f"{'approval' if factor.polarity == 'positive' else 'rejection'} "
                f"factor: {factor.summary}."
            )
            for factor in [*positive, *negative]
            if factor.confidence >= 0.4
        ]
        experimentation_updates = [
            (
                f"Experiment {outcome.experiment_id} reported "
                f"{outcome.outcome_label.replace('_', ' ')}; review before reuse."
            )
            for outcome in reviewed_outcomes
        ]
        ranking_guidance = [
            f"Use cautiously as a future ranking feature: {factor.summary}."
            for factor in positive
            if factor.category in {"clip_type", "hook", "retention", "payoff", "pacing"}
        ]
        editorial_guidance = [
            f"Human-review editorial caution: {factor.summary}."
            for factor in negative
            if factor.category
            in {"context", "payoff", "pacing", "retention", "clip_type"}
        ]
        hook_guidance = [
            f"Review hook/retention evidence: {factor.summary}."
            for factor in [*positive, *negative]
            if factor.category in {"hook", "retention", "payoff", "pacing"}
        ]
        caption_motion_guidance = [
            f"Review caption/motion evidence: {factor.summary}."
            for factor in [*positive, *negative]
            if factor.category in {"caption", "motion"}
        ]
        music_guidance = [
            f"Review audio evidence: {factor.summary}."
            for factor in [*positive, *negative]
            if factor.category in {"music_mood", "sfx", "speech_clarity"}
        ]
        return BobaPerformanceLearningHandoffV1(
            creator_learning_updates=_unique(creator_updates, maximum=32),
            approval_rejection_updates=_unique(approval_updates, maximum=32),
            experimentation_updates=_unique(experimentation_updates, maximum=32),
            ranking_guidance=_unique(ranking_guidance, maximum=32),
            editorial_guidance=_unique(editorial_guidance, maximum=32),
            hook_retention_guidance=_unique(hook_guidance, maximum=32),
            caption_motion_guidance=_unique(
                caption_motion_guidance,
                maximum=32,
            ),
            music_mood_guidance=_unique(music_guidance, maximum=32),
        )

    @staticmethod
    def _audit(
        events: Sequence[BobaPerformanceFeedbackEventV1],
        snapshots: Sequence[BobaPerformanceSnapshotV1],
        outcomes: Sequence[BobaExperimentOutcomeReviewV1],
    ) -> BobaPerformanceAuditSummaryV1:
        return BobaPerformanceAuditSummaryV1(
            total_events=len(events),
            manual_clip_results=sum(
                event.event_type == "manual_clip_result" for event in events
            ),
            manual_experiment_results=sum(
                event.event_type == "manual_experiment_result"
                for event in events
            ),
            snapshots_count=len(snapshots),
            outcomes_count=len(outcomes),
            user_entered_count=sum(event.user_entered for event in events),
            auto_collected_count=0,
            export_available=True,
            reset_available=True,
            warnings=[
                "All V1 events were explicitly entered by a creator.",
                "No automatic collection path exists.",
            ],
        )

    @staticmethod
    def _signal_usage(
        artifacts: Mapping[str, dict[str, Any]],
        events: Sequence[BobaPerformanceFeedbackEventV1],
    ) -> BobaPerformanceFeedbackSignalUsageV1:
        availability = {key: bool(value) for key, value in artifacts.items()}
        unavailable = [key for key, value in availability.items() if not value]
        warnings = (
            ["Missing optional BOBA artifacts limited factor attribution."]
            if unavailable
            else []
        )
        return BobaPerformanceFeedbackSignalUsageV1(
            experimentation_used=availability["experimentation"],
            creator_learning_used=availability["creator_learning"],
            approval_rejection_used=availability[
                "approval_rejection_learning"
            ],
            clip_briefs_used=availability["clip_briefs"],
            hook_retention_used=availability["hook_retention"],
            caption_motion_used=availability["caption_motion"],
            music_mood_used=availability["music_mood"],
            clip_ranking_used=availability["clip_ranking"],
            editorial_decision_used=availability["editorial_decision"],
            memory_used=availability["memory"],
            manual_feedback_used=bool(events),
            analytics_api_used=False,
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=warnings,
        )

    @staticmethod
    def _module_for_category(category: BobaPerformanceFactorCategory) -> str:
        if category in {"hook", "retention", "pacing", "payoff"}:
            return "hook_retention"
        if category in {"caption", "motion"}:
            return "caption_motion"
        if category in {"music_mood", "sfx", "speech_clarity"}:
            return "music_mood"
        if category in {"clip_type", "platform_fit"}:
            return "clip_ranking"
        return "editorial_decision"
