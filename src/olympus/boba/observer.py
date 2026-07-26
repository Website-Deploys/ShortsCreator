"""Read-only local project-state observation for BOBA."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaArtifactFreshnessStatusV1 = Literal[
    "fresh",
    "stale",
    "unknown",
    "missing",
]
BobaArtifactDependencyStatusV1 = Literal[
    "satisfied",
    "missing_upstream",
    "stale_upstream",
    "unknown",
    "not_applicable",
]
BobaObserverIssueLevelV1 = Literal[
    "ok",
    "info",
    "warning",
    "blocker",
    "unknown",
]
BobaObserverModuleCategoryV1 = Literal[
    "core",
    "video_intelligence",
    "creative",
    "learning",
    "scouting",
    "rights_safety",
    "self_healing",
    "frontend",
    "validation",
]
BobaObserverHealthStatusV1 = Literal[
    "healthy",
    "partial",
    "missing",
    "stale",
    "blocked",
    "unknown",
]
BobaObserverDependencyStatusV1 = Literal[
    "satisfied",
    "missing",
    "stale",
    "broken",
    "unknown",
]
BobaObserverValidationStatusV1 = Literal[
    "passed",
    "failed",
    "partial",
    "unknown",
    "missing",
]
BobaObserverSafetyAreaV1 = Literal[
    "rights_permission",
    "ingestion",
    "rendering",
    "downloading",
    "external_api",
    "secrets",
    "destructive_action",
    "validation_gap",
    "unknown",
]
BobaObserverSafetyStatusV1 = Literal[
    "safe_to_review",
    "needs_human_review",
    "blocked",
    "unknown",
]
BobaObserverActionTypeV1 = Literal[
    "inspect",
    "validate",
    "generate_missing_artifact",
    "run_future_validator",
    "human_review",
    "merge_required",
    "do_not_process",
    "blocked",
    "unknown",
]
BobaObserverPriorityV1 = Literal["low", "medium", "high", "urgent"]
BobaObserverFindingCategoryV1 = Literal[
    "missing_artifact",
    "stale_artifact",
    "unreadable_artifact",
    "missing_validation",
    "stale_validation",
    "broken_dependency",
    "unsafe_action",
    "rights_gap",
    "unknown_state",
    "info",
]

JsonObject: TypeAlias = dict[str, Any]

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SPACE = re.compile(r"\s+")
_MAX_ARTIFACT_BYTES = 10_000_000
_DEFAULT_STALE_AFTER = timedelta(days=30)


def _text(value: Any, *, maximum: int = 700) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _unique(
    values: Sequence[Any],
    *,
    limit: int = 64,
    maximum: int = 700,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value, maximum=maximum)
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value, maximum=80)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _timestamp_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _extract_nested_string(
    payload: Any,
    keys: Sequence[str],
    *,
    depth: int = 0,
) -> str:
    if depth > 3 or not isinstance(payload, Mapping):
        return ""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _text(value, maximum=160)
    for value in payload.values():
        nested = _extract_nested_string(value, keys, depth=depth + 1)
        if nested:
            return nested
    return ""


class BobaObserverFindingV1(BobaContract):
    finding_id: str = Field(min_length=1, max_length=128)
    category: BobaObserverFindingCategoryV1
    message: str = Field(min_length=1, max_length=700)
    evidence: list[str] = Field(default_factory=list, max_length=24)
    issue_level: BobaObserverIssueLevelV1
    related_module: str = Field(default="", max_length=120)
    related_artifact: str = Field(default="", max_length=120)
    recommended_followup: str = Field(default="", max_length=700)


class BobaArtifactObservationV1(BobaContract):
    artifact_id: str = Field(min_length=1, max_length=120)
    module_name: str = Field(min_length=1, max_length=120)
    artifact_type: str = Field(min_length=1, max_length=120)
    expected_path: str = Field(min_length=1, max_length=500)
    exists: bool
    readable: bool
    schema_version: str = Field(default="", max_length=160)
    created_at: str = Field(default="", max_length=80)
    freshness_status: BobaArtifactFreshnessStatusV1
    dependency_status: BobaArtifactDependencyStatusV1
    size_bytes: int = Field(default=0, ge=0)
    issue_level: BobaObserverIssueLevelV1
    findings: list[BobaObserverFindingV1] = Field(
        default_factory=list,
        max_length=32,
    )
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaModuleHealthObservationV1(BobaContract):
    module_name: str = Field(min_length=1, max_length=120)
    module_category: BobaObserverModuleCategoryV1
    expected_artifacts: list[str] = Field(default_factory=list, max_length=16)
    required_dependencies: list[str] = Field(default_factory=list, max_length=32)
    optional_dependencies: list[str] = Field(default_factory=list, max_length=32)
    health_status: BobaObserverHealthStatusV1
    missing_inputs: list[str] = Field(default_factory=list, max_length=32)
    missing_outputs: list[str] = Field(default_factory=list, max_length=16)
    stale_outputs: list[str] = Field(default_factory=list, max_length=16)
    blocked_reason: str = Field(default="", max_length=700)
    confidence: float = Field(ge=0.0, le=1.0)
    findings: list[BobaObserverFindingV1] = Field(
        default_factory=list,
        max_length=32,
    )
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaWorkflowObservationV1(BobaContract):
    workflow_stage: str = Field(min_length=1, max_length=120)
    completed_modules: list[str] = Field(default_factory=list, max_length=64)
    ready_modules: list[str] = Field(default_factory=list, max_length=64)
    incomplete_modules: list[str] = Field(default_factory=list, max_length=64)
    blocked_modules: list[str] = Field(default_factory=list, max_length=64)
    unsafe_next_actions: list[str] = Field(default_factory=list, max_length=32)
    safe_next_actions: list[str] = Field(default_factory=list, max_length=32)
    findings: list[BobaObserverFindingV1] = Field(
        default_factory=list,
        max_length=32,
    )
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaDependencyObservationV1(BobaContract):
    dependency_id: str = Field(min_length=1, max_length=128)
    downstream_module: str = Field(min_length=1, max_length=120)
    upstream_module: str = Field(min_length=1, max_length=120)
    upstream_artifact: str = Field(min_length=1, max_length=120)
    downstream_artifact: str = Field(min_length=1, max_length=120)
    status: BobaObserverDependencyStatusV1
    reason: str = Field(min_length=1, max_length=700)
    recommended_inspection: str = Field(min_length=1, max_length=700)
    issue_level: BobaObserverIssueLevelV1
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaValidationObservationV1(BobaContract):
    validator_name: str = Field(min_length=1, max_length=160)
    report_path: str = Field(default="", max_length=500)
    report_exists: bool
    latest_status: BobaObserverValidationStatusV1
    report_created_at: str = Field(default="", max_length=80)
    freshness_status: BobaArtifactFreshnessStatusV1
    missing_reason: str = Field(default="", max_length=700)
    issue_level: BobaObserverIssueLevelV1
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSafetyObservationV1(BobaContract):
    safety_id: str = Field(min_length=1, max_length=128)
    safety_area: BobaObserverSafetyAreaV1
    status: BobaObserverSafetyStatusV1
    reason: str = Field(min_length=1, max_length=700)
    related_artifacts: list[str] = Field(default_factory=list, max_length=32)
    required_human_checks: list[str] = Field(default_factory=list, max_length=32)
    unsafe_next_actions: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaNextActionRecommendationV1(BobaContract):
    recommendation_id: str = Field(min_length=1, max_length=128)
    action_type: BobaObserverActionTypeV1
    action: str = Field(min_length=1, max_length=700)
    safe: bool
    reason: str = Field(min_length=1, max_length=700)
    prerequisites: list[str] = Field(default_factory=list, max_length=32)
    suggested_owner_module: str = Field(default="", max_length=160)
    human_review_required: bool
    priority: BobaObserverPriorityV1
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaObserverSummaryV1(BobaContract):
    total_modules_observed: int = Field(default=0, ge=0)
    healthy_count: int = Field(default=0, ge=0)
    partial_count: int = Field(default=0, ge=0)
    missing_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    safest_next_step: str = Field(default="", max_length=700)
    riskiest_next_step: str = Field(default="", max_length=700)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaObserverSignalUsageV1(BobaContract):
    boba_store_used: bool = False
    local_artifacts_read: bool = False
    validation_reports_read: bool = False
    rights_gate_used: bool = False
    candidate_video_scorer_used: bool = False
    research_brain_used: bool = False
    content_scout_used: bool = False
    trend_topic_watcher_used: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    command_execution_used: Literal[False] = False
    code_modification_used: Literal[False] = False
    destructive_action_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaObserverSetV1(BobaContract):
    schema_version: Literal["boba_observer_v1"] = "boba_observer_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    workflow_observations: list[BobaWorkflowObservationV1] = Field(
        default_factory=list,
        max_length=32,
    )
    artifact_observations: list[BobaArtifactObservationV1] = Field(
        default_factory=list,
        max_length=256,
    )
    module_health_observations: list[BobaModuleHealthObservationV1] = Field(
        default_factory=list,
        max_length=256,
    )
    dependency_observations: list[BobaDependencyObservationV1] = Field(
        default_factory=list,
        max_length=512,
    )
    validation_observations: list[BobaValidationObservationV1] = Field(
        default_factory=list,
        max_length=256,
    )
    safety_observations: list[BobaSafetyObservationV1] = Field(
        default_factory=list,
        max_length=64,
    )
    next_action_recommendations: list[BobaNextActionRecommendationV1] = Field(
        default_factory=list,
        max_length=256,
    )
    observer_summary: BobaObserverSummaryV1
    signal_usage: BobaObserverSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


@dataclass(frozen=True, slots=True)
class BobaArtifactRegistryEntryV1:
    """Internal read-only registry entry for one BOBA project artifact."""

    artifact_id: str
    module_name: str
    artifact_type: str
    relative_path: str
    module_category: BobaObserverModuleCategoryV1
    required_dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    validator_name: str = ""
    validation_directory: str = ""


def build_boba_artifact_registry() -> tuple[BobaArtifactRegistryEntryV1, ...]:
    """Return the deterministic V1 artifact and dependency registry."""

    return (
        BobaArtifactRegistryEntryV1(
            "whole_video",
            "whole_video",
            "whole_video_understanding",
            "whole_video_understanding/index.json",
            "video_intelligence",
            validator_name="BOBA Whole Video Understanding",
            validation_directory="boba_whole_video_understanding",
        ),
        BobaArtifactRegistryEntryV1(
            "candidate_clip_discovery",
            "candidate_clip_discovery",
            "candidate_clip_discovery",
            "candidate_clip_discovery/index.json",
            "video_intelligence",
            required_dependencies=("whole_video",),
            validator_name="BOBA Candidate Clip Discovery",
            validation_directory="boba_candidate_clip_discovery",
        ),
        BobaArtifactRegistryEntryV1(
            "clip_ranking",
            "clip_ranking",
            "clip_ranking",
            "clip_ranking/index.json",
            "video_intelligence",
            required_dependencies=("candidate_clip_discovery",),
            validator_name="BOBA Clip Ranking",
            validation_directory="boba_clip_ranking",
        ),
        BobaArtifactRegistryEntryV1(
            "editorial_decision",
            "editorial_decision",
            "editorial_decision",
            "editorial_decision/index.json",
            "creative",
            required_dependencies=("clip_ranking",),
            validator_name="BOBA Editorial Decision",
            validation_directory="boba_editorial_decision",
        ),
        BobaArtifactRegistryEntryV1(
            "explanation",
            "explanation",
            "explanation",
            "explanation/index.json",
            "creative",
            required_dependencies=("editorial_decision",),
            validator_name="BOBA Explanation Engine",
            validation_directory="boba_explanation_engine",
        ),
        BobaArtifactRegistryEntryV1(
            "creative_direction_v2",
            "creative_direction_v2",
            "creative_direction_v2",
            "creative_direction_v2/index.json",
            "creative",
            required_dependencies=("explanation",),
            validator_name="BOBA Creative Director V2",
            validation_directory="boba_creative_director_v2",
        ),
        BobaArtifactRegistryEntryV1(
            "clip_briefs",
            "clip_briefs",
            "clip_briefs",
            "clip_briefs/index.json",
            "creative",
            required_dependencies=("creative_direction_v2",),
            optional_dependencies=("editorial_decision",),
            validator_name="BOBA Clip Brief Generator",
            validation_directory="boba_clip_brief_generator",
        ),
        BobaArtifactRegistryEntryV1(
            "hook_retention",
            "hook_retention",
            "hook_retention",
            "hook_retention/index.json",
            "creative",
            required_dependencies=("clip_briefs",),
            validator_name="BOBA Hook + Retention Brain",
            validation_directory="boba_hook_retention",
        ),
        BobaArtifactRegistryEntryV1(
            "caption_motion",
            "caption_motion",
            "caption_motion",
            "caption_motion/index.json",
            "creative",
            required_dependencies=("hook_retention",),
            optional_dependencies=("clip_briefs",),
            validator_name="BOBA Caption + Motion",
            validation_directory="boba_caption_motion",
        ),
        BobaArtifactRegistryEntryV1(
            "music_mood",
            "music_mood",
            "music_mood",
            "music_mood/index.json",
            "creative",
            required_dependencies=("caption_motion",),
            optional_dependencies=("clip_briefs",),
            validator_name="BOBA Music Mood",
            validation_directory="boba_music_mood",
        ),
        BobaArtifactRegistryEntryV1(
            "creator_learning",
            "creator_learning",
            "creator_learning",
            "creator_learning/index.json",
            "learning",
            validator_name="BOBA Creator Learning",
            validation_directory="boba_creator_learning",
        ),
        BobaArtifactRegistryEntryV1(
            "approval_rejection_learning",
            "approval_rejection_learning",
            "approval_rejection_learning",
            "approval_rejection_learning/index.json",
            "learning",
            required_dependencies=("creator_learning",),
            validator_name="BOBA Approval / Rejection Learning",
            validation_directory="boba_approval_rejection_learning",
        ),
        BobaArtifactRegistryEntryV1(
            "experimentation",
            "experimentation",
            "experimentation",
            "experimentation/index.json",
            "learning",
            required_dependencies=("approval_rejection_learning",),
            validator_name="BOBA Experimentation",
            validation_directory="boba_experimentation",
        ),
        BobaArtifactRegistryEntryV1(
            "performance_feedback",
            "performance_feedback",
            "performance_feedback",
            "performance_feedback/index.json",
            "learning",
            required_dependencies=("experimentation",),
            validator_name="BOBA Performance Feedback",
            validation_directory="boba_performance_feedback",
        ),
        BobaArtifactRegistryEntryV1(
            "content_scout_v2",
            "content_scout_v2",
            "content_scout_v2",
            "content_scout_v2/index.json",
            "scouting",
            validator_name="BOBA Content Scout V2",
            validation_directory="boba_content_scout_v2",
        ),
        BobaArtifactRegistryEntryV1(
            "research_brain",
            "research_brain",
            "research_brain",
            "research_brain/index.json",
            "scouting",
            required_dependencies=("content_scout_v2",),
            validator_name="BOBA Research Brain",
            validation_directory="boba_research_brain",
        ),
        BobaArtifactRegistryEntryV1(
            "trend_topic_watcher",
            "trend_topic_watcher",
            "trend_topic_watcher",
            "trend_topic_watcher/index.json",
            "scouting",
            required_dependencies=("research_brain",),
            validator_name="BOBA Trend / Topic Watcher",
            validation_directory="boba_trend_topic_watcher",
        ),
        BobaArtifactRegistryEntryV1(
            "candidate_video_scorer",
            "candidate_video_scorer",
            "candidate_video_scorer",
            "candidate_video_scorer/index.json",
            "scouting",
            required_dependencies=("trend_topic_watcher",),
            optional_dependencies=("content_scout_v2", "research_brain"),
            validator_name="BOBA Candidate Video Scorer",
            validation_directory="boba_candidate_video_scorer",
        ),
        BobaArtifactRegistryEntryV1(
            "rights_permission_gate",
            "rights_permission_gate",
            "rights_permission_gate",
            "rights_permission_gate/index.json",
            "rights_safety",
            required_dependencies=("candidate_video_scorer",),
            optional_dependencies=(
                "content_scout_v2",
                "research_brain",
                "trend_topic_watcher",
            ),
            validator_name="BOBA Rights + Permission Gate",
            validation_directory="boba_rights_permission_gate",
        ),
    )


def _finding(
    *,
    category: BobaObserverFindingCategoryV1,
    message: str,
    evidence: Sequence[str],
    issue_level: BobaObserverIssueLevelV1,
    related_module: str,
    related_artifact: str,
    recommended_followup: str,
) -> BobaObserverFindingV1:
    return BobaObserverFindingV1(
        finding_id=_stable_id(
            "observer_finding",
            category,
            related_module,
            related_artifact,
            message,
        ),
        category=category,
        message=message,
        evidence=_unique(evidence, limit=24, maximum=500),
        issue_level=issue_level,
        related_module=related_module,
        related_artifact=related_artifact,
        recommended_followup=recommended_followup,
    )


def _safe_json(path: Path) -> tuple[Any | None, int, str | None]:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None, 0, None
    except OSError as exc:
        return None, 0, f"Artifact metadata could not be read: {exc.__class__.__name__}."
    if size > _MAX_ARTIFACT_BYTES:
        return (
            None,
            size,
            f"Artifact exceeds the Observer V1 read limit of {_MAX_ARTIFACT_BYTES} bytes.",
        )
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), size, None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, size, f"Artifact JSON is unreadable: {exc.__class__.__name__}."


def _path_timestamp(path: Path, payload: Any) -> tuple[datetime | None, str]:
    created_text = _extract_nested_string(
        payload,
        ("created_at", "generated_at", "updated_at", "timestamp"),
    )
    created = _parse_datetime(created_text)
    if created is not None:
        return created, created_text
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return None, ""
    return modified, ""


def _freshness(
    timestamp: datetime | None,
    *,
    observed_at: datetime,
    stale_after: timedelta,
) -> BobaArtifactFreshnessStatusV1:
    if timestamp is None:
        return "unknown"
    age = observed_at - timestamp
    if age < timedelta(days=-1):
        return "unknown"
    return "stale" if age > stale_after else "fresh"


def observe_boba_artifacts(
    project_id: str,
    store_root: str | Path,
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
    observed_at: datetime | None = None,
    stale_after: timedelta = _DEFAULT_STALE_AFTER,
) -> list[BobaArtifactObservationV1]:
    """Observe expected local artifacts without using typed loaders or writes."""

    if not _PROJECT_ID.fullmatch(project_id):
        raise ValidationError(
            "Invalid BOBA Observer project id.",
            details={"project_id": project_id},
        )
    effective_registry = tuple(registry or build_boba_artifact_registry())
    root = Path(store_root).expanduser().resolve()
    project_root = root / "projects" / project_id
    now = (observed_at or datetime.now(UTC)).astimezone(UTC)
    observations: list[BobaArtifactObservationV1] = []
    for spec in effective_registry:
        path = project_root / spec.relative_path
        expected_path = f"projects/{project_id}/{spec.relative_path}"
        if not path.exists():
            finding = _finding(
                category="missing_artifact",
                message=f"{spec.module_name} output is missing.",
                evidence=[expected_path],
                issue_level="warning",
                related_module=spec.module_name,
                related_artifact=spec.artifact_id,
                recommended_followup=(
                    "Inspect required upstream artifacts before approved generation."
                ),
            )
            observations.append(
                BobaArtifactObservationV1(
                    artifact_id=spec.artifact_id,
                    module_name=spec.module_name,
                    artifact_type=spec.artifact_type,
                    expected_path=expected_path,
                    exists=False,
                    readable=False,
                    freshness_status="missing",
                    dependency_status=(
                        "unknown"
                        if spec.required_dependencies
                        else "not_applicable"
                    ),
                    issue_level="warning",
                    findings=[finding],
                    warnings=[
                        "Missing output was observed only; Observer did not generate it."
                    ],
                )
            )
            continue
        payload, size, read_error = _safe_json(path)
        if read_error is not None:
            finding = _finding(
                category="unreadable_artifact",
                message=f"{spec.module_name} output is unreadable.",
                evidence=[expected_path, read_error],
                issue_level="blocker",
                related_module=spec.module_name,
                related_artifact=spec.artifact_id,
                recommended_followup=(
                    "Inspect the artifact safely; future Error Doctor may analyze the cause."
                ),
            )
            observations.append(
                BobaArtifactObservationV1(
                    artifact_id=spec.artifact_id,
                    module_name=spec.module_name,
                    artifact_type=spec.artifact_type,
                    expected_path=expected_path,
                    exists=True,
                    readable=False,
                    freshness_status="unknown",
                    dependency_status="unknown",
                    size_bytes=size,
                    issue_level="blocker",
                    findings=[finding],
                    warnings=[
                        read_error,
                        "Observer did not modify or repair the unreadable artifact.",
                    ],
                )
            )
            continue
        schema_version = _extract_nested_string(
            payload,
            ("schema_version", "version"),
        )
        timestamp, created_at = _path_timestamp(path, payload)
        freshness = _freshness(
            timestamp,
            observed_at=now,
            stale_after=stale_after,
        )
        findings: list[BobaObserverFindingV1] = []
        issue_level: BobaObserverIssueLevelV1 = "ok"
        warnings: list[str] = []
        if freshness == "stale":
            issue_level = "warning"
            findings.append(
                _finding(
                    category="stale_artifact",
                    message=(
                        f"{spec.module_name} output is older than the configured "
                        "review window."
                    ),
                    evidence=[
                        expected_path,
                        f"review_window_days={stale_after.days}",
                    ],
                    issue_level="warning",
                    related_module=spec.module_name,
                    related_artifact=spec.artifact_id,
                    recommended_followup=(
                        "Inspect upstream changes and run the validator manually if appropriate."
                    ),
                )
            )
            warnings.append(
                "Stale means timestamp-old for review; it does not prove semantic invalidity."
            )
        elif freshness == "unknown":
            issue_level = "unknown"
            findings.append(
                _finding(
                    category="unknown_state",
                    message=f"{spec.module_name} freshness could not be determined.",
                    evidence=[expected_path],
                    issue_level="unknown",
                    related_module=spec.module_name,
                    related_artifact=spec.artifact_id,
                    recommended_followup="Inspect artifact timestamp metadata.",
                )
            )
        observations.append(
            BobaArtifactObservationV1(
                artifact_id=spec.artifact_id,
                module_name=spec.module_name,
                artifact_type=spec.artifact_type,
                expected_path=expected_path,
                exists=True,
                readable=True,
                schema_version=schema_version,
                created_at=created_at,
                freshness_status=freshness,
                dependency_status=(
                    "unknown"
                    if spec.required_dependencies
                    else "not_applicable"
                ),
                size_bytes=size,
                issue_level=issue_level,
                findings=findings,
                warnings=warnings,
            )
        )
    return observations


def _artifact_path(
    project_id: str,
    store_root: Path,
    spec: BobaArtifactRegistryEntryV1,
) -> Path:
    return store_root / "projects" / project_id / spec.relative_path


def observe_boba_dependencies(
    project_id: str,
    store_root: str | Path,
    artifact_observations: Sequence[BobaArtifactObservationV1],
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
) -> list[BobaDependencyObservationV1]:
    """Compare required and optional local artifact edges."""

    effective_registry = tuple(registry or build_boba_artifact_registry())
    spec_by_id = {entry.artifact_id: entry for entry in effective_registry}
    observed = {item.artifact_id: item for item in artifact_observations}
    root = Path(store_root).expanduser().resolve()
    results: list[BobaDependencyObservationV1] = []
    for downstream_spec in effective_registry:
        dependency_ids = (
            *downstream_spec.required_dependencies,
            *downstream_spec.optional_dependencies,
        )
        for upstream_id in dependency_ids:
            upstream_spec = spec_by_id[upstream_id]
            upstream = observed[upstream_id]
            downstream = observed[downstream_spec.artifact_id]
            required = upstream_id in downstream_spec.required_dependencies
            status: BobaObserverDependencyStatusV1
            issue: BobaObserverIssueLevelV1
            warnings: list[str] = []
            if downstream.exists and not upstream.exists:
                status = "broken" if required else "missing"
                issue = "blocker" if required else "warning"
                reason = (
                    "Downstream output exists while its upstream artifact is missing."
                    if required
                    else "Optional upstream artifact is missing."
                )
            elif downstream.exists and not upstream.readable:
                status = "broken" if required else "unknown"
                issue = "blocker" if required else "warning"
                reason = (
                    "Downstream output exists but its upstream artifact is unreadable."
                )
            elif not downstream.exists and upstream.exists and upstream.readable:
                status = "missing"
                issue = "warning"
                reason = (
                    "Upstream output exists, but the downstream artifact is missing."
                )
            elif not downstream.exists and not upstream.exists:
                status = "missing"
                issue = "blocker" if required else "warning"
                reason = "Both upstream and downstream outputs are missing."
            elif upstream.freshness_status == "stale":
                status = "stale"
                issue = "warning"
                reason = "The upstream artifact is timestamp-stale."
                warnings.append(
                    "Timestamp staleness is advisory and not a semantic failure."
                )
            elif upstream.readable and downstream.readable:
                upstream_path = _artifact_path(
                    project_id,
                    root,
                    upstream_spec,
                )
                downstream_path = _artifact_path(
                    project_id,
                    root,
                    downstream_spec,
                )
                try:
                    downstream_older = (
                        downstream_path.stat().st_mtime + 1.0
                        < upstream_path.stat().st_mtime
                    )
                except OSError:
                    downstream_older = False
                if downstream_older:
                    status = "stale"
                    issue = "warning"
                    reason = (
                        "Downstream output predates its upstream artifact."
                    )
                    warnings.append(
                        "Dependency ordering indicates review is needed; "
                        "Observer did not rerun either module."
                    )
                else:
                    status = "satisfied"
                    issue = "ok"
                    reason = "Upstream and downstream artifacts are present and readable."
            else:
                status = "unknown"
                issue = "unknown"
                reason = "Dependency state could not be determined."
            results.append(
                BobaDependencyObservationV1(
                    dependency_id=_stable_id(
                        "observer_dependency",
                        upstream_id,
                        downstream_spec.artifact_id,
                    ),
                    downstream_module=downstream_spec.module_name,
                    upstream_module=upstream_spec.module_name,
                    upstream_artifact=upstream_id,
                    downstream_artifact=downstream_spec.artifact_id,
                    status=status,
                    reason=reason,
                    recommended_inspection=(
                        f"Inspect {upstream_spec.module_name} before "
                        f"{downstream_spec.module_name}."
                    ),
                    issue_level=issue,
                    warnings=warnings,
                )
            )
    return results


def _apply_dependency_state(
    observations: Sequence[BobaArtifactObservationV1],
    dependencies: Sequence[BobaDependencyObservationV1],
    registry: Sequence[BobaArtifactRegistryEntryV1],
) -> list[BobaArtifactObservationV1]:
    observation_by_id = {
        observation.artifact_id: observation for observation in observations
    }
    dependencies_by_downstream: dict[str, list[BobaDependencyObservationV1]] = {}
    for dependency in dependencies:
        dependencies_by_downstream.setdefault(
            dependency.downstream_artifact,
            [],
        ).append(dependency)
    required_by_artifact = {
        entry.artifact_id: set(entry.required_dependencies)
        for entry in registry
    }
    results: list[BobaArtifactObservationV1] = []
    for observation in observations:
        edges = dependencies_by_downstream.get(observation.artifact_id, [])
        required_edges = [
            edge
            for edge in edges
            if edge.upstream_artifact
            in required_by_artifact.get(observation.artifact_id, set())
        ]
        unavailable_required_edges = [
            edge
            for edge in required_edges
            if (
                not observation_by_id[edge.upstream_artifact].exists
                or not observation_by_id[edge.upstream_artifact].readable
                or edge.status in {"broken", "unknown"}
            )
        ]
        if not edges:
            dependency_status: BobaArtifactDependencyStatusV1 = "not_applicable"
        elif unavailable_required_edges:
            dependency_status = "missing_upstream"
        elif any(edge.status == "stale" for edge in required_edges):
            dependency_status = "stale_upstream"
        elif required_edges and all(
            edge.status in {"satisfied", "missing"} for edge in required_edges
        ):
            dependency_status = "satisfied"
        else:
            dependency_status = "unknown"
        updates: dict[str, Any] = {"dependency_status": dependency_status}
        if (
            observation.exists
            and observation.readable
            and any(edge.status == "stale" for edge in required_edges)
        ):
            updates["freshness_status"] = "stale"
            updates["issue_level"] = "warning"
            updates["findings"] = [
                *observation.findings,
                _finding(
                    category="stale_artifact",
                    message=(
                        f"{observation.module_name} output needs review because "
                        "an upstream dependency is stale or newer."
                    ),
                    evidence=[
                        edge.reason
                        for edge in required_edges
                        if edge.status == "stale"
                    ],
                    issue_level="warning",
                    related_module=observation.module_name,
                    related_artifact=observation.artifact_id,
                    recommended_followup=(
                        "Inspect the dependency chain and run validators manually."
                    ),
                ),
            ]
        results.append(observation.model_copy(update=updates))
    return results


def _module_health(
    artifacts: Sequence[BobaArtifactObservationV1],
    dependencies: Sequence[BobaDependencyObservationV1],
    registry: Sequence[BobaArtifactRegistryEntryV1],
) -> list[BobaModuleHealthObservationV1]:
    artifact_by_id = {item.artifact_id: item for item in artifacts}
    dependency_by_downstream: dict[str, list[BobaDependencyObservationV1]] = {}
    for dependency in dependencies:
        dependency_by_downstream.setdefault(
            dependency.downstream_artifact,
            [],
        ).append(dependency)
    results: list[BobaModuleHealthObservationV1] = []
    for spec in registry:
        artifact = artifact_by_id[spec.artifact_id]
        edges = dependency_by_downstream.get(spec.artifact_id, [])
        required_edges = [
            edge
            for edge in edges
            if edge.upstream_artifact in spec.required_dependencies
        ]
        optional_edges = [
            edge
            for edge in edges
            if edge.upstream_artifact in spec.optional_dependencies
        ]
        missing_inputs = [
            edge.upstream_artifact
            for edge in required_edges
            if (
                not artifact_by_id[edge.upstream_artifact].exists
                or not artifact_by_id[edge.upstream_artifact].readable
                or edge.status in {"broken", "unknown"}
            )
        ]
        missing_outputs = [] if artifact.exists else [artifact.artifact_id]
        stale_outputs = (
            [artifact.artifact_id]
            if artifact.freshness_status == "stale"
            else []
        )
        findings = list(artifact.findings)
        blocked_reason = ""
        warnings: list[str] = []
        if artifact.exists and not artifact.readable:
            health: BobaObserverHealthStatusV1 = "blocked"
            blocked_reason = "Expected output exists but is unreadable."
            confidence = 0.98
        elif missing_inputs:
            health = "blocked"
            blocked_reason = (
                "Required upstream artifacts are missing, unreadable, or unknown."
            )
            confidence = 0.92
            findings.append(
                _finding(
                    category="broken_dependency",
                    message=f"{spec.module_name} has missing required inputs.",
                    evidence=missing_inputs,
                    issue_level="blocker",
                    related_module=spec.module_name,
                    related_artifact=spec.artifact_id,
                    recommended_followup="Inspect the nearest missing upstream artifact.",
                )
            )
        elif missing_outputs and spec.required_dependencies:
            health = "partial"
            confidence = 0.9
        elif missing_outputs:
            health = "missing"
            confidence = 0.95
        elif stale_outputs or any(
            edge.status == "stale" for edge in required_edges
        ):
            health = "stale"
            confidence = 0.9
        elif any(edge.status != "satisfied" for edge in optional_edges):
            health = "partial"
            confidence = 0.82
            warnings.append(
                "Optional context is unavailable; this is advisory, not a blocker."
            )
        elif artifact.issue_level == "unknown":
            health = "unknown"
            confidence = 0.5
        else:
            health = "healthy"
            confidence = 0.96
        results.append(
            BobaModuleHealthObservationV1(
                module_name=spec.module_name,
                module_category=spec.module_category,
                expected_artifacts=[spec.artifact_id],
                required_dependencies=list(spec.required_dependencies),
                optional_dependencies=list(spec.optional_dependencies),
                health_status=health,
                missing_inputs=_unique(missing_inputs),
                missing_outputs=missing_outputs,
                stale_outputs=stale_outputs,
                blocked_reason=blocked_reason,
                confidence=confidence,
                findings=findings[:32],
                warnings=warnings,
            )
        )
    return results


def _validation_status(payload: Any) -> BobaObserverValidationStatusV1:
    if not isinstance(payload, Mapping):
        return "unknown"
    passed = payload.get("passed")
    if passed is True:
        return "passed"
    if passed is False:
        return "failed"
    for key in ("status", "result", "latest_status"):
        value = _text(payload.get(key), maximum=40).casefold()
        if value in {"passed", "pass", "success", "healthy"}:
            return "passed"
        if value in {"failed", "fail", "error", "blocked"}:
            return "failed"
        if value in {"partial", "warning", "warnings"}:
            return "partial"
        if value == "unknown":
            return "unknown"
        if value == "missing":
            return "missing"
    return "unknown"


def observe_validation_reports(
    validation_report_root: str | Path | None,
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
    observed_at: datetime | None = None,
    stale_after: timedelta = _DEFAULT_STALE_AFTER,
) -> list[BobaValidationObservationV1]:
    """Read newest local JSON reports without invoking any validator."""

    effective_registry = tuple(registry or build_boba_artifact_registry())
    now = (observed_at or datetime.now(UTC)).astimezone(UTC)
    root = (
        Path(validation_report_root).expanduser().resolve()
        if validation_report_root is not None
        else None
    )
    results: list[BobaValidationObservationV1] = []
    seen: set[str] = set()
    for spec in effective_registry:
        if not spec.validation_directory or spec.validation_directory in seen:
            continue
        seen.add(spec.validation_directory)
        relative_directory = spec.validation_directory
        if root is None:
            reports: list[Path] = []
        else:
            directory = root / relative_directory
            try:
                reports = sorted(
                    directory.glob("*.json"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                reports = []
        if not reports:
            results.append(
                BobaValidationObservationV1(
                    validator_name=spec.validator_name,
                    report_path=relative_directory,
                    report_exists=False,
                    latest_status="missing",
                    freshness_status="missing",
                    missing_reason=(
                        "No local JSON validation report was found; Observer "
                        "did not run the validator."
                    ),
                    issue_level="warning",
                    warnings=[
                        "Validation status remains unknown until a human runs the validator."
                    ],
                )
            )
            continue
        report_path = reports[0]
        payload, _, read_error = _safe_json(report_path)
        relative_path = f"{relative_directory}/{report_path.name}"
        if read_error is not None:
            results.append(
                BobaValidationObservationV1(
                    validator_name=spec.validator_name,
                    report_path=relative_path,
                    report_exists=True,
                    latest_status="unknown",
                    freshness_status="unknown",
                    missing_reason="The newest report could not be parsed safely.",
                    issue_level="warning",
                    warnings=[
                        read_error,
                        "Observer did not rerun or repair the validator report.",
                    ],
                )
            )
            continue
        status = _validation_status(payload)
        timestamp, created_text = _path_timestamp(report_path, payload)
        freshness = _freshness(
            timestamp,
            observed_at=now,
            stale_after=stale_after,
        )
        if status == "failed":
            issue: BobaObserverIssueLevelV1 = "blocker"
        elif status in {"partial", "unknown", "missing"}:
            issue = "warning" if status != "unknown" else "unknown"
        elif freshness == "stale":
            issue = "warning"
        else:
            issue = "ok"
        warnings = [
            "Observer read this report only; it did not execute the validator."
        ]
        if freshness == "stale":
            warnings.append(
                "The report is older than the configured review window."
            )
        if status == "unknown":
            warnings.append(
                "The report format did not provide a recognized pass/fail status."
            )
        results.append(
            BobaValidationObservationV1(
                validator_name=spec.validator_name,
                report_path=relative_path,
                report_exists=True,
                latest_status=status,
                report_created_at=created_text
                or (_timestamp_iso(timestamp) if timestamp else ""),
                freshness_status=freshness,
                missing_reason=(
                    "Recognized validation status was not available."
                    if status == "unknown"
                    else ""
                ),
                issue_level=issue,
                warnings=warnings,
            )
        )
    return results


_WORKFLOW_CHAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "content_scouting",
        (
            "content_scout_v2",
            "research_brain",
            "trend_topic_watcher",
            "candidate_video_scorer",
            "rights_permission_gate",
        ),
    ),
    (
        "video_intelligence",
        (
            "whole_video",
            "candidate_clip_discovery",
            "clip_ranking",
            "editorial_decision",
            "explanation",
            "creative_direction_v2",
            "clip_briefs",
        ),
    ),
    (
        "creative_refinement",
        ("clip_briefs", "hook_retention", "caption_motion", "music_mood"),
    ),
    (
        "learning",
        (
            "creator_learning",
            "approval_rejection_learning",
            "experimentation",
            "performance_feedback",
        ),
    ),
    (
        "rights_safety",
        ("candidate_video_scorer", "rights_permission_gate"),
    ),
)


def _workflow_observations(
    health: Sequence[BobaModuleHealthObservationV1],
    workflow_context: Mapping[str, Any] | None,
) -> list[BobaWorkflowObservationV1]:
    health_by_module = {item.module_name: item for item in health}
    results: list[BobaWorkflowObservationV1] = []
    for stage, modules in _WORKFLOW_CHAINS:
        selected = [
            health_by_module[module]
            for module in modules
            if module in health_by_module
        ]
        completed = [
            item.module_name
            for item in selected
            if item.health_status == "healthy"
        ]
        ready = [
            item.module_name
            for item in selected
            if item.health_status in {"missing", "partial"}
            and not item.missing_inputs
        ]
        incomplete = [
            item.module_name
            for item in selected
            if item.health_status in {"partial", "missing", "stale", "unknown"}
        ]
        blocked = [
            item.module_name
            for item in selected
            if item.health_status == "blocked"
        ]
        findings: list[BobaObserverFindingV1] = []
        if blocked:
            findings.append(
                _finding(
                    category="broken_dependency",
                    message=f"{stage} contains blocked modules.",
                    evidence=blocked,
                    issue_level="blocker",
                    related_module=stage,
                    related_artifact="",
                    recommended_followup="Inspect the nearest blocked upstream module.",
                )
            )
        safe_actions = [
            f"Inspect {module} through its normal approved workflow."
            for module in [*blocked, *incomplete][:4]
        ] or ["Review the healthy artifact chain and validation evidence."]
        unsafe_actions = [
            "Do not let Observer modify files or execute recovery actions."
        ]
        if stage in {"content_scouting", "rights_safety"}:
            unsafe_actions.append(
                "Do not ingest candidates without acceptable rights status and human approval."
            )
        if stage in {"video_intelligence", "creative_refinement"}:
            unsafe_actions.append(
                "Do not auto-render while required outputs or safety reviews are incomplete."
            )
        results.append(
            BobaWorkflowObservationV1(
                workflow_stage=stage,
                completed_modules=completed,
                ready_modules=ready,
                incomplete_modules=incomplete,
                blocked_modules=blocked,
                unsafe_next_actions=unsafe_actions,
                safe_next_actions=safe_actions,
                findings=findings,
                warnings=[
                    "Workflow state is inferred from local artifact evidence only."
                ],
            )
        )
    if workflow_context:
        stage = _text(
            workflow_context.get("workflow_stage") or "manual_context",
            maximum=120,
        )

        def context_list(key: str) -> list[str]:
            value = workflow_context.get(key)
            return (
                _unique(value, limit=32, maximum=160)
                if isinstance(value, list | tuple)
                else []
            )

        results.append(
            BobaWorkflowObservationV1(
                workflow_stage=stage or "manual_context",
                completed_modules=context_list("completed_modules"),
                ready_modules=context_list("ready_modules"),
                incomplete_modules=context_list("incomplete_modules"),
                blocked_modules=context_list("blocked_modules"),
                unsafe_next_actions=context_list("unsafe_next_actions"),
                safe_next_actions=context_list("safe_next_actions"),
                findings=[
                    _finding(
                        category="info",
                        message="Manual workflow context was included as unverified context.",
                        evidence=["local/user-provided workflow metadata"],
                        issue_level="info",
                        related_module="observer",
                        related_artifact="",
                        recommended_followup=(
                            "Compare manual context with persisted artifact evidence."
                        ),
                    )
                ],
                warnings=[
                    "Observer did not independently verify manual workflow context."
                ],
            )
        )
    return results


def _read_rights_statuses(
    project_id: str,
    store_root: Path,
    registry: Sequence[BobaArtifactRegistryEntryV1],
) -> tuple[list[str], str | None]:
    spec = next(
        item for item in registry if item.artifact_id == "rights_permission_gate"
    )
    payload, _, read_error = _safe_json(
        _artifact_path(project_id, store_root, spec)
    )
    if read_error is not None or not isinstance(payload, Mapping):
        return [], read_error
    decisions = payload.get("gate_decisions")
    if not isinstance(decisions, list):
        return [], "Rights Gate decisions were not available in the saved artifact."
    statuses = [
        _text(item.get("gate_status"), maximum=50)
        for item in decisions
        if isinstance(item, Mapping) and item.get("gate_status")
    ]
    return _unique(statuses, limit=128, maximum=50), None


def observe_safety_state(
    project_id: str,
    store_root: str | Path,
    artifact_observations: Sequence[BobaArtifactObservationV1],
    validation_observations: Sequence[BobaValidationObservationV1],
    *,
    registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
) -> list[BobaSafetyObservationV1]:
    """Observe rights and operational safety without authorizing actions."""

    effective_registry = tuple(registry or build_boba_artifact_registry())
    root = Path(store_root).expanduser().resolve()
    artifact_by_id = {item.artifact_id: item for item in artifact_observations}
    rights_artifact = artifact_by_id["rights_permission_gate"]
    statuses, rights_error = _read_rights_statuses(
        project_id,
        root,
        effective_registry,
    )
    unsafe_rights = {
        "permission_needed",
        "needs_permission",
        "needs_rights_review",
        "blocked",
        "insufficient_information",
        "unknown",
    }
    if not rights_artifact.exists:
        rights_status: BobaObserverSafetyStatusV1 = "needs_human_review"
        rights_reason = (
            "Rights + Permission Gate is missing; ingestion is unsafe until review."
        )
    elif not rights_artifact.readable or rights_error:
        rights_status = "unknown"
        rights_reason = "Rights + Permission Gate could not be read safely."
    elif "blocked" in statuses:
        rights_status = "blocked"
        rights_reason = "At least one saved Rights Gate decision is blocked."
    elif any(status in unsafe_rights for status in statuses):
        rights_status = "needs_human_review"
        rights_reason = (
            "Unknown, permission-needed, or insufficient rights decisions require human review."
        )
    elif statuses and all(
        status == "ready_for_human_review" for status in statuses
    ):
        rights_status = "safe_to_review"
        rights_reason = (
            "Saved decisions permit human review only; they do not authorize ingestion."
        )
    else:
        rights_status = "unknown"
        rights_reason = "Saved Rights Gate state did not contain recognized decisions."
    validation_gaps = [
        item.validator_name
        for item in validation_observations
        if item.latest_status in {"missing", "failed", "partial", "unknown"}
        or item.freshness_status == "stale"
    ]
    creative_required = (
        "clip_briefs",
        "hook_retention",
        "caption_motion",
        "music_mood",
    )
    rendering_gaps = [
        artifact_id
        for artifact_id in creative_required
        if (
            not artifact_by_id[artifact_id].exists
            or not artifact_by_id[artifact_id].readable
            or artifact_by_id[artifact_id].dependency_status
            in {"missing_upstream", "stale_upstream", "unknown"}
        )
    ]

    def safety(
        area: BobaObserverSafetyAreaV1,
        status: BobaObserverSafetyStatusV1,
        reason: str,
        *,
        related: Sequence[str] = (),
        checks: Sequence[str] = (),
        unsafe: Sequence[str] = (),
        warnings: Sequence[str] = (),
    ) -> BobaSafetyObservationV1:
        return BobaSafetyObservationV1(
            safety_id=_stable_id("observer_safety", project_id, area),
            safety_area=area,
            status=status,
            reason=reason,
            related_artifacts=_unique(related),
            required_human_checks=_unique(checks),
            unsafe_next_actions=_unique(unsafe),
            warnings=_unique(warnings),
        )

    return [
        safety(
            "rights_permission",
            rights_status,
            rights_reason,
            related=["rights_permission_gate", "candidate_video_scorer"],
            checks=[
                "Review source ownership, license, permission, and final approval.",
                "Treat unknown or claimed rights as unsafe.",
            ],
            unsafe=[
                "Process media with unknown, blocked, or permission-needed rights.",
            ],
            warnings=[
                rights_error or "",
                "Observer does not confirm copyright safety.",
            ],
        ),
        safety(
            "ingestion",
            (
                "needs_human_review"
                if rights_status == "safe_to_review"
                else "blocked"
            ),
            (
                "Future ingestion always requires human approval; Observer never triggers it."
                if rights_status == "safe_to_review"
                else "Ingestion is blocked by missing, unknown, or unsafe rights state."
            ),
            related=["rights_permission_gate"],
            checks=["Record explicit human approval before future ingestion."],
            unsafe=["Automatically ingest media from Observer findings."],
        ),
        safety(
            "rendering",
            "blocked" if rendering_gaps else "needs_human_review",
            (
                "Required creative outputs or dependency evidence are incomplete."
                if rendering_gaps
                else (
                    "Artifacts are observable, but rendering still requires "
                    "the normal approved pipeline."
                )
            ),
            related=rendering_gaps or list(creative_required),
            checks=["Review required artifacts and render validation manually."],
            unsafe=["Automatically render from Observer recommendations."],
        ),
        safety(
            "downloading",
            "blocked",
            "Observer V1 never downloads media.",
            checks=["Use a separately approved rights-aware ingestion system."],
            unsafe=["Download media from a source reference or URL."],
        ),
        safety(
            "external_api",
            "blocked",
            "Observer V1 makes no external API or URL requests.",
            checks=["Use explicit approved integrations outside Observer."],
            unsafe=["Fetch URLs, scrape platforms, or call external APIs."],
        ),
        safety(
            "secrets",
            "safe_to_review",
            "Observer stores compact status metadata and does not request secrets.",
            checks=["Keep credentials and tokens outside Observer artifacts."],
            unsafe=["Add secrets or authentication tokens to workflow context."],
        ),
        safety(
            "destructive_action",
            "blocked",
            "Observer V1 does not delete, repair, or modify files.",
            checks=["Future repair modules require explicit human approval."],
            unsafe=["Delete or rewrite artifacts based on Observer findings."],
        ),
        safety(
            "validation_gap",
            "needs_human_review" if validation_gaps else "safe_to_review",
            (
                "One or more validation reports are missing, failed, stale, partial, or unknown."
                if validation_gaps
                else "Known local reports are present, fresh, and passed."
            ),
            related=validation_gaps,
            checks=["Run relevant validators manually and inspect their output."],
            unsafe=["Assume validation passed when a report is missing or unknown."],
            warnings=[
                "Observer inspected report files only and executed no validators."
            ],
        ),
    ]


def _recommendations(
    artifacts: Sequence[BobaArtifactObservationV1],
    modules: Sequence[BobaModuleHealthObservationV1],
    validations: Sequence[BobaValidationObservationV1],
    safety_observations: Sequence[BobaSafetyObservationV1],
) -> list[BobaNextActionRecommendationV1]:
    recommendations: list[BobaNextActionRecommendationV1] = []

    def add(
        action_type: BobaObserverActionTypeV1,
        action: str,
        *,
        safe: bool,
        reason: str,
        prerequisites: Sequence[str],
        owner: str,
        priority: BobaObserverPriorityV1,
        warnings: Sequence[str] = (),
    ) -> None:
        recommendation = BobaNextActionRecommendationV1(
            recommendation_id=_stable_id(
                "observer_recommendation",
                action_type,
                action,
            ),
            action_type=action_type,
            action=action,
            safe=safe,
            reason=reason,
            prerequisites=_unique(prerequisites),
            suggested_owner_module=owner,
            human_review_required=True,
            priority=priority,
            warnings=_unique(warnings),
        )
        if all(
            existing.recommendation_id != recommendation.recommendation_id
            for existing in recommendations
        ):
            recommendations.append(recommendation)

    module_by_name = {item.module_name: item for item in modules}
    for artifact in artifacts:
        module = module_by_name[artifact.module_name]
        if artifact.exists and not artifact.readable:
            add(
                "inspect",
                f"Inspect unreadable {artifact.artifact_id} artifact.",
                safe=True,
                reason="Unreadable local JSON blocks reliable observation.",
                prerequisites=["Preserve the original artifact.", "Do not repair automatically."],
                owner="Future BOBA Error Doctor",
                priority="urgent",
            )
        elif not artifact.exists and not module.missing_inputs:
            add(
                "generate_missing_artifact",
                (
                    f"Generate {artifact.artifact_id} through its normal approved "
                    "module workflow."
                ),
                safe=True,
                reason="Required upstream artifacts are currently available.",
                prerequisites=[
                    "Human reviews upstream evidence.",
                    "Use the existing module entry point, not Observer.",
                ],
                owner=artifact.module_name,
                priority="high",
            )
        elif module.missing_inputs:
            add(
                "inspect",
                f"Inspect upstream inputs for {artifact.module_name}.",
                safe=True,
                reason="Required upstream artifacts are missing or unreadable.",
                prerequisites=module.missing_inputs,
                owner="Future BOBA Root Cause Analyzer",
                priority="high",
            )
        if artifact.freshness_status == "stale":
            add(
                "validate",
                f"Review freshness and validation for {artifact.artifact_id}.",
                safe=True,
                reason="Timestamp evidence indicates the output needs review.",
                prerequisites=["Inspect upstream timestamps.", "Run validators manually."],
                owner=artifact.module_name,
                priority="medium",
                warnings=["Observer did not rerun the module or validator."],
            )
    for validation in validations:
        if validation.latest_status in {"missing", "unknown"}:
            add(
                "run_future_validator",
                f"Run {validation.validator_name} manually.",
                safe=True,
                reason="A recognized current validation result is unavailable.",
                prerequisites=["Human selects and starts the validator."],
                owner=validation.validator_name,
                priority="medium",
                warnings=["Observer never executes validators."],
            )
        elif validation.latest_status in {"failed", "partial"}:
            add(
                "inspect",
                f"Inspect the latest {validation.validator_name} report.",
                safe=True,
                reason=f"Latest known status is {validation.latest_status}.",
                prerequisites=["Preserve report evidence.", "Do not hide failures."],
                owner="Future BOBA Error Doctor",
                priority="high",
            )
        elif validation.freshness_status == "stale":
            add(
                "run_future_validator",
                f"Refresh {validation.validator_name} validation manually.",
                safe=True,
                reason="The newest known report is timestamp-stale.",
                prerequisites=["Human confirms the validator is safe to run."],
                owner=validation.validator_name,
                priority="medium",
            )
    rights = next(
        item
        for item in safety_observations
        if item.safety_area == "rights_permission"
    )
    if rights.status != "safe_to_review":
        add(
            "human_review",
            "Review rights and permission evidence before any ingestion.",
            safe=True,
            reason=rights.reason,
            prerequisites=rights.required_human_checks,
            owner="BOBA Rights + Permission Gate",
            priority="urgent",
        )
        add(
            "do_not_process",
            "Do not process candidates with unresolved rights state.",
            safe=False,
            reason="Unknown, blocked, or permission-needed rights are unsafe.",
            prerequisites=["Acceptable rights status.", "Explicit human approval."],
            owner="Future BOBA Safety Gate",
            priority="urgent",
        )
    add(
        "blocked",
        "Do not modify code, delete artifacts, or execute repair actions from Observer.",
        safe=False,
        reason="Observer V1 is an observation-only foundation.",
        prerequisites=["Future approved Error Doctor and Repair Planner workflow."],
        owner="Future BOBA Safety Gate",
        priority="urgent",
    )
    return recommendations[:256]


def _summary(
    modules: Sequence[BobaModuleHealthObservationV1],
    artifacts: Sequence[BobaArtifactObservationV1],
    dependencies: Sequence[BobaDependencyObservationV1],
    validations: Sequence[BobaValidationObservationV1],
    recommendations: Sequence[BobaNextActionRecommendationV1],
) -> BobaObserverSummaryV1:
    status_counts = {
        status: sum(item.health_status == status for item in modules)
        for status in (
            "healthy",
            "partial",
            "missing",
            "blocked",
            "stale",
            "unknown",
        )
    }
    blocker_count = (
        sum(item.issue_level == "blocker" for item in artifacts)
        + sum(item.issue_level == "blocker" for item in dependencies)
        + sum(item.issue_level == "blocker" for item in validations)
    )
    warning_count = (
        sum(
            item.issue_level in {"warning", "unknown"}
            for item in artifacts
        )
        + sum(
            item.issue_level in {"warning", "unknown"}
            for item in dependencies
        )
        + sum(
            item.issue_level in {"warning", "unknown"}
            for item in validations
        )
    )
    safe = sorted(
        (item for item in recommendations if item.safe),
        key=lambda item: (
            {"urgent": 0, "high": 1, "medium": 2, "low": 3}[item.priority],
            item.action,
        ),
    )
    unsafe = sorted(
        (item for item in recommendations if not item.safe),
        key=lambda item: (
            {"urgent": 0, "high": 1, "medium": 2, "low": 3}[item.priority],
            item.action,
        ),
    )
    return BobaObserverSummaryV1(
        total_modules_observed=len(modules),
        healthy_count=status_counts["healthy"],
        partial_count=status_counts["partial"],
        missing_count=status_counts["missing"],
        blocked_count=status_counts["blocked"],
        stale_count=status_counts["stale"],
        unknown_count=status_counts["unknown"],
        blocker_count=blocker_count,
        warning_count=warning_count,
        safest_next_step=(
            safe[0].action
            if safe
            else "Human reviews the observation report."
        ),
        riskiest_next_step=(
            unsafe[0].action
            if unsafe
            else "Acting without human review or current validation."
        ),
        human_review_notes=[
            "Observer findings are advisory local evidence only.",
            "A human must choose and authorize every next action.",
            "Future Error Doctor or Repair Planner modules may consume findings later.",
        ],
    )


class BobaObserverV1:
    """Observe BOBA artifacts and reports without executing or modifying."""

    def __init__(
        self,
        store_root: str | Path,
        *,
        validation_report_root: str | Path | None = None,
        registry: Sequence[BobaArtifactRegistryEntryV1] | None = None,
        stale_after: timedelta = _DEFAULT_STALE_AFTER,
    ) -> None:
        self.store_root = Path(store_root).expanduser().resolve()
        self.validation_report_root = (
            Path(validation_report_root).expanduser().resolve()
            if validation_report_root is not None
            else self.store_root.parent / "validation_reports"
        )
        self.registry = tuple(registry or build_boba_artifact_registry())
        self.stale_after = stale_after

    def analyze(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        workflow_context: Mapping[str, Any] | None = None,
        observed_at: datetime | None = None,
        dry_run: bool = False,
    ) -> BobaObserverSetV1:
        now = (observed_at or datetime.now(UTC)).astimezone(UTC)
        artifacts = observe_boba_artifacts(
            project_id,
            self.store_root,
            registry=self.registry,
            observed_at=now,
            stale_after=self.stale_after,
        )
        dependencies = observe_boba_dependencies(
            project_id,
            self.store_root,
            artifacts,
            registry=self.registry,
        )
        artifacts = _apply_dependency_state(
            artifacts,
            dependencies,
            self.registry,
        )
        modules = _module_health(artifacts, dependencies, self.registry)
        validations = observe_validation_reports(
            self.validation_report_root,
            registry=self.registry,
            observed_at=now,
            stale_after=self.stale_after,
        )
        workflows = _workflow_observations(modules, workflow_context)
        safety = observe_safety_state(
            project_id,
            self.store_root,
            artifacts,
            validations,
            registry=self.registry,
        )
        recommendations = _recommendations(
            artifacts,
            modules,
            validations,
            safety,
        )
        observed_by_id = {item.artifact_id: item for item in artifacts}
        unavailable = [
            item.artifact_id
            for item in artifacts
            if not item.exists or not item.readable
        ]
        validation_missing = any(
            item.latest_status in {"missing", "unknown"}
            for item in validations
        )
        warnings = [
            "BOBA Observer V1 observed local files only.",
            "Observer did not fix files, edit code, execute commands, run "
            "validators, delete files, fetch URLs, call external APIs, "
            "download media, ingest media, or render.",
            "Unsafe next actions require human review or future safety modules.",
        ]
        if dry_run:
            warnings.append("Dry run: the Observer artifact was not persisted.")
        return BobaObserverSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            created_at=_timestamp_iso(now),
            workflow_observations=workflows,
            artifact_observations=artifacts,
            module_health_observations=modules,
            dependency_observations=dependencies,
            validation_observations=validations,
            safety_observations=safety,
            next_action_recommendations=recommendations,
            observer_summary=_summary(
                modules,
                artifacts,
                dependencies,
                validations,
                recommendations,
            ),
            signal_usage=BobaObserverSignalUsageV1(
                boba_store_used=True,
                local_artifacts_read=any(
                    item.exists and item.readable for item in artifacts
                ),
                validation_reports_read=any(
                    item.report_exists for item in validations
                ),
                rights_gate_used=(
                    observed_by_id["rights_permission_gate"].exists
                    and observed_by_id["rights_permission_gate"].readable
                ),
                candidate_video_scorer_used=(
                    observed_by_id["candidate_video_scorer"].exists
                    and observed_by_id["candidate_video_scorer"].readable
                ),
                research_brain_used=(
                    observed_by_id["research_brain"].exists
                    and observed_by_id["research_brain"].readable
                ),
                content_scout_used=(
                    observed_by_id["content_scout_v2"].exists
                    and observed_by_id["content_scout_v2"].readable
                ),
                trend_topic_watcher_used=(
                    observed_by_id["trend_topic_watcher"].exists
                    and observed_by_id["trend_topic_watcher"].readable
                ),
                external_api_used=False,
                url_fetching_used=False,
                scraping_used=False,
                downloading_used=False,
                command_execution_used=False,
                code_modification_used=False,
                destructive_action_used=False,
                fallback_used=bool(unavailable or validation_missing),
                unavailable_signals=_unique(unavailable),
                warnings=[
                    "Signals report file observation only, not execution.",
                ],
            ),
            warnings=warnings,
            limitations=[
                "V1 observes evidence but does not diagnose or repair code.",
                "V1 does not execute validators, commands, rendering, ingestion, or downloads.",
                "V1 freshness uses timestamps and dependency ordering only.",
                "V1 cannot prove semantic correctness, copyright safety, or production readiness.",
                "Future Error Doctor, Root Cause Analyzer, Repair Planner, "
                "Code Surgeon, Tool Recovery Brain, and Safety Gate remain separate.",
            ],
        )


def generate_boba_observer_report(
    project_id: str,
    *,
    store_root: str | Path,
    validation_report_root: str | Path | None = None,
    **kwargs: Any,
) -> BobaObserverSetV1:
    """Convenience wrapper for deterministic local observation."""

    return BobaObserverV1(
        store_root,
        validation_report_root=validation_report_root,
    ).analyze(project_id, **kwargs)
