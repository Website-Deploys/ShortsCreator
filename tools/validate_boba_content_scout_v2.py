"""Validate BOBA Content Scout V2 without media or network access."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba.content_scout import (  # noqa: E402
    BobaContentScoutSetV2,
    BobaContentScoutV2,
    BobaScoutRecommendationV2,
    BobaScoutScoreV2,
    BobaSuggestedShortAngleV2,
    _duplicate_map,
)
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.platform.errors import ValidationError  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_content_scout_v2"


class BobaContentScoutValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    creator_learning_available: bool = False
    performance_feedback_available: bool = False
    report_path_writable: bool = False
    items_imported: int = 0
    invalid_items_rejected: bool = False
    scores_bounded: bool = False
    review_queue_created: bool = False
    rights_ready_review_now: bool = False
    unknown_requires_review: bool = False
    permission_needed_seek_permission: bool = False
    blocked_queued: bool = False
    duplicates_detected: bool = False
    suggested_angles_created: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    downloading_used_false: bool = False
    scenario_count: int = Field(default=0, ge=0)
    passed_scenario_count: int = Field(default=0, ge=0)
    scenario_results: dict[str, bool] = Field(default_factory=dict)
    scenarios_not_applicable: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_scout_items() -> list[dict[str, Any]]:
    """Return varied metadata-only records, including one intentionally bad row."""
    return [
        {
            "item_id": "owned_emotional_story",
            "title": "Why my biggest failure became an unexpected comeback",
            "description": (
                "A personal emotional story about struggle, regret, growth, surprise, "
                "a turning point, and the lesson behind the final success reveal."
            ),
            "source_label": "synthetic_owned",
            "source_url": "https://example.invalid/owned-reference",
            "duration_seconds": 840,
            "tags": ["emotional story", "comeback", "motivation", "lesson"],
            "categories": ["creator journey"],
            "creator": "Synthetic Creator",
            "rights_status": "owned",
            "permission_notes": "Creator marked this source as owned.",
        },
        {
            "item_id": "motivational_podcast",
            "title": "The secret reason this motivational breakthrough worked",
            "description": (
                "A permission-granted podcast story with struggle, hope, a surprising "
                "turn, a clear lesson, and an emotional payoff."
            ),
            "duration": "18:30",
            "tags": "podcast, motivation, curiosity, breakthrough",
            "categories": "interview",
            "rights_status": "permission_granted",
            "permission_notes": "Synthetic permission record for validation.",
        },
        {
            "item_id": "licensed_tutorial",
            "title": "How to avoid the mistake that ruins a clear tutorial",
            "description": (
                "A licensed educational tutorial with a before-and-after result, "
                "specific lesson, and concise reveal."
            ),
            "duration_seconds": 620,
            "tags": ["tutorial", "education", "mistake", "result"],
            "categories": ["how to"],
            "rights_status": "licensed",
        },
        {
            "item_id": "funny_unknown",
            "title": "Why the unexpected reaction made everyone laugh",
            "description": (
                "User notes describe a funny reaction and surprise, but provide no "
                "permission evidence."
            ),
            "tags": ["reaction", "funny", "surprise"],
            "rights_status": "unknown",
        },
        {
            "item_id": "owned_emotional_duplicate",
            "title": "Why my biggest failure became an unexpected comeback",
            "description": (
                "A personal emotional story about struggle, regret, growth, surprise, "
                "a turning point, and the lesson behind the final success reveal."
            ),
            "tags": ["emotional story", "comeback", "motivation", "lesson"],
            "rights_status": "owned",
        },
        {
            "item_id": "weak_generic",
            "title": "Weekly update",
            "description": "General notes without a specific hook or story.",
            "duration_seconds": 300,
            "rights_status": "owned",
        },
        {
            "item_id": "blocked_source",
            "title": "The surprising rescue story",
            "description": "A potentially emotional reveal that must not be used.",
            "tags": ["rescue", "story", "reveal"],
            "rights_status": "blocked",
        },
        {
            "item_id": "permission_needed_high_potential",
            "title": "The mystery behind a failure-to-success transformation",
            "description": (
                "A high-potential story with conflict, struggle, surprise, comeback, "
                "growth, and a final lesson, pending explicit permission."
            ),
            "tags": ["story", "transformation", "mystery", "comeback"],
            "rights_status": "permission_needed",
        },
        {
            # C9. Saturates the hook component to its structural ceiling (0.91) so
            # the four-decimal rounding limb of _clamp has more values to bite on.
            # item_id deliberately excludes "duplicate" so the validator's
            # rights_ready_ids filter includes it and its top_items placement is a
            # live assertion rather than an accident.
            "item_id": "hook_saturated_owned",
            "title": "Why the secret mistake nobody reveals became my unexpected lesson?",
            "description": (
                "A tutorial story about the turning point before and after a hard "
                "struggle: the failure, the regret, the surprise reveal, the growth, "
                "the emotional comeback, the hope, the breakthrough, and the success "
                "lesson behind that transformation and its truth."
            ),
            "source_label": "synthetic_owned",
            "duration_seconds": 900,
            "tags": ["emotional story", "tutorial", "comeback", "lesson", "curiosity"],
            "categories": ["creator journey"],
            "creator": "Synthetic Creator",
            "rights_status": "owned",
            "published_at": "2026-02-01",
            "user_notes": "A timely current topic the creator wants reviewed concisely.",
        },
        {
            # C10. Blocked AND a duplicate of blocked_source. This is the only way to
            # reach R3.5: the blocked branch must be shown to run ahead of the
            # duplicate branch. Title repeats blocked_source's exactly so
            # _duplicate_map pairs them by normalized-title equality.
            "item_id": "blocked_emotional_duplicate",
            "title": "The surprising rescue story",
            "description": "A potentially emotional reveal that must not be used.",
            "tags": ["rescue", "story", "reveal"],
            "rights_status": "blocked",
        },
        {},
    ]


def build_synthetic_scout_signals() -> dict[str, dict[str, Any]]:
    """Return compact advisory artifacts; no learning artifact is mutated."""
    return {
        "creator_learning": {
            "learning_profile": {
                "preferred_clip_types": ["emotional story", "tutorial", "podcast"],
                "preferred_hook_styles": ["curiosity reveal", "clear lesson"],
                "pacing_preferences": ["concise"],
                "story_angle_preferences": ["struggle comeback growth"],
                "avoided_clip_types": ["generic update"],
                "avoided_hook_styles": ["slow vague opening"],
                "risk_sensitivities": ["unknown rights"],
            }
        },
        "approval_rejection_learning": {
            "pattern_scores": [
                {
                    "summary": "emotional story curiosity reveal tutorial",
                    "guidance": "Prefer a complete lesson and source-supported payoff.",
                    "approval_count": 4,
                    "rejection_count": 0,
                },
                {
                    "summary": "generic update slow vague",
                    "guidance": "Avoid generic items without a specific hook.",
                    "approval_count": 0,
                    "rejection_count": 3,
                },
            ]
        },
        "performance_feedback": {
            "pattern_summary": {
                "strongest_positive_patterns": [
                    {
                        "summary": (
                            "Curiosity hooks, emotional comeback stories, and clear "
                            "tutorial lessons received positive manual feedback."
                        )
                    }
                ],
                "strongest_negative_patterns": [
                    {
                        "summary": (
                            "Generic updates and slow vague openings received negative "
                            "manual feedback."
                        )
                    }
                ],
            }
        },
        "memory": {
            "source_summary": "The creator prefers concise lessons with emotional growth.",
            "main_topics": ["motivation", "tutorial", "creator journey"],
            "story_patterns": ["struggle comeback lesson"],
        },
    }


def _signals_kwargs() -> dict[str, Any]:
    """Map the fixture signals onto ``analyze()``'s parameter names.

    ``build_synthetic_scout_signals()`` returns the key ``memory`` while
    ``analyze()`` takes ``boba_memory=``; ``analyze()`` accepts a missing
    ``boba_memory`` silently, so a dropped mapping would exercise the degraded
    path invisibly.
    """
    signals = build_synthetic_scout_signals()
    return {
        "creator_learning": signals["creator_learning"],
        "approval_rejection_learning": signals["approval_rejection_learning"],
        "performance_feedback": signals["performance_feedback"],
        "boba_memory": signals["memory"],
    }


def build_synthetic_content_scout(
    project_id: str = "proj_content_scout_v2_synthetic",
) -> BobaContentScoutSetV2:
    signals = build_synthetic_scout_signals()
    return BobaContentScoutV2().analyze(
        project_id,
        source_id="synthetic_metadata_only",
        manual_items=build_synthetic_scout_items(),
        manual_source_type="test_synthetic",
        source_label="validator_synthetic",
        creator_learning=signals["creator_learning"],
        approval_rejection_learning=signals["approval_rejection_learning"],
        performance_feedback=signals["performance_feedback"],
        boba_memory=signals["memory"],
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("metadata-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _safe_export(payload: dict[str, Any]) -> bool:
    scout = payload.get("content_scout_v2")
    if not isinstance(scout, dict):
        return False
    sources = scout.get("imported_sources")
    items = scout.get("scout_items")
    if not isinstance(sources, list) or not isinstance(items, list):
        return False
    if any(isinstance(source, dict) and "source_path" in source for source in sources):
        return False
    private_item_fields = {
        "source_url",
        "permission_notes",
        "user_notes",
        "raw_metadata_summary",
    }
    if any(
        isinstance(item, dict) and private_item_fields.intersection(item)
        for item in items
    ):
        return False
    encoded = json.dumps(payload).casefold()
    return not any(
        forbidden in encoded
        for forbidden in (
            "raw_media",
            "full_transcript",
            "api_key",
            "access_token",
            "password",
            ".mp4",
            ".wav",
        )
    )


def _recommendations(
    scout: BobaContentScoutSetV2,
) -> dict[str, BobaScoutRecommendationV2]:
    groups = (
        scout.review_queue.top_items,
        scout.review_queue.backup_items,
        scout.review_queue.permission_needed_items,
        scout.review_queue.blocked_items,
        scout.review_queue.duplicate_or_similar_items,
    )
    return {
        recommendation.item_id: recommendation
        for group in groups
        for recommendation in group
    }


# ---------------------------------------------------------------------------
# Observation vocabulary shared by the scenarios.
# ---------------------------------------------------------------------------
SCORE_FIELDS: tuple[str, ...] = (
    "creator_fit_score",
    "topic_fit_score",
    "shortability_score",
    "hook_potential_score",
    "emotional_story_score",
    "trend_context_score",
    "novelty_score",
    "rights_readiness_score",
    "review_priority_score",
    "confidence",
)
ANGLE_FIELDS: frozenset[str] = frozenset(
    {
        "angle_id",
        "title",
        "hook_direction",
        "why_it_might_work",
        "risk",
        "confidence",
    }
)
TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "created_at",
        "imported_sources",
        "limitations",
        "project_id",
        "rejected_items",
        "review_queue",
        "schema_version",
        "scored_items",
        "scout_items",
        "scout_summary",
        "signal_usage",
        "source_id",
        "warnings",
    }
)
QUEUE_LISTS: tuple[str, ...] = (
    "top_items",
    "backup_items",
    "permission_needed_items",
    "blocked_items",
    "duplicate_or_similar_items",
)
# EXACT key equality only. Substring matching would be wrong: `published_at`
# contains `publish`, and it is legitimate source metadata.
AUTHORITY_KEYS: frozenset[str] = frozenset(
    {"approved", "authorized", "selected", "render_ready", "publish"}
)
PRIVATE_SOURCE_KEYS: tuple[str, ...] = ("source_path",)
PRIVATE_ITEM_KEYS: tuple[str, ...] = (
    "source_url",
    "permission_notes",
    "user_notes",
    "raw_metadata_summary",
)
ENGINE_LIMITATIONS: tuple[str, ...] = (
    "Scores estimate metadata fit only and do not predict audience performance.",
    "No external trend knowledge was verified or used.",
    "Human review and an independent rights check remain required.",
)
BLOCKED_REASON = "The user-provided rights status is blocked."
COPYRIGHT_WARNING = "content scout cannot confirm copyright safety."
UNSUPPORTED_RIGHTS_MARKER = "unsupported rights status"
# ---------------------------------------------------------------------------
# Fixture ground truth. These are THIS FILE'S OWN fixture design, not values
# read back out of the engine: `build_synthetic_scout_items()` deliberately
# repeats a title verbatim to construct each pairing below, and
# `_rights_normalization_probe()` deliberately feeds in the raw rights label
# below. Scenarios 03/04/05 assert against these constants instead of against
# the engine helper they are testing, so neutralising an engine guard
# (`_duplicate_map`, `_normalized_rights`) makes the scenario FAIL rather than
# silently select nothing and skip as not-applicable.
# ---------------------------------------------------------------------------
# (duplicate_item_id, original_item_id) pairs the fixture builds by repeating
# the original's title exactly. Independent of `_duplicate_map`.
FIXTURE_DUPLICATE_PAIRS: tuple[tuple[str, str], ...] = (
    ("owned_emotional_duplicate", "owned_emotional_story"),
    ("blocked_emotional_duplicate", "blocked_source"),
)
# The item `_rights_normalization_probe()` submits, and the unsupported raw
# rights label it submits it with. Independent of `_normalized_rights`.
RIGHTS_PROBE_ITEM_ID = "probably_safe_item"
RIGHTS_PROBE_RAW_STATUS = "probably_safe"
_NEGATION_MARKERS: tuple[str, ...] = (
    "not",
    "no ",
    "cannot",
    "do not",
    "does not",
    "without",
    "must",
    "remain",
    "never",
    "?",
)
_CLEARANCE_TOKENS: tuple[str, ...] = ("cleared", "verified", "confirmed")
_PERFORMANCE_TOKENS: tuple[str, ...] = (
    "predict",
    "prediction",
    "forecast",
    "guarantee",
    "guaranteed",
    "will perform",
    "viral",
)
_CLEARANCE_CONTROL = "Rights are cleared and copyright is confirmed."
_PERFORMANCE_CONTROL = "This short will predict a viral audience response."


def _walk_strings(payload: Any) -> Iterator[str]:
    """Yield every string value at any depth."""
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, Mapping):
        for value in payload.values():
            yield from _walk_strings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_strings(value)


def _walk_keys(payload: Any) -> Iterator[str]:
    """Yield every mapping key at any depth, for exact-equality comparison only."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_keys(value)


def _key_paths(
    payload: Any,
    leaf_names: tuple[str, ...],
    path: str = "",
) -> set[str]:
    """Collect the dotted/indexed path of every leaf whose key name is in leaf_names."""
    found: set[str] = set()
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            here = f"{path}.{key}" if path else str(key)
            if key in leaf_names:
                found.add(here)
            found |= _key_paths(value, leaf_names, here)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found |= _key_paths(value, leaf_names, f"{path}[{index}]")
    return found


def _differing_paths(first: Any, second: Any, path: str = "") -> set[str]:
    """Key paths whose values differ between two payloads."""
    out: set[str] = set()
    if isinstance(first, Mapping) and isinstance(second, Mapping):
        for key in set(first) | set(second):
            here = f"{path}.{key}" if path else str(key)
            out |= _differing_paths(first.get(key), second.get(key), here)
    elif isinstance(first, list) and isinstance(second, list):
        if len(first) != len(second):
            out.add(path or "<root>")
        else:
            for index, (left, right) in enumerate(zip(first, second, strict=True)):
                out |= _differing_paths(left, right, f"{path}[{index}]")
    elif first != second:
        out.add(path or "<root>")
    return out


def _json_snapshot(value: Any) -> str:
    """Stable textual snapshot of caller-supplied input, for mutation comparison."""
    return json.dumps(value, sort_keys=True, default=repr)


def _flagged(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    if not any(token in lowered for token in tokens):
        return False
    return not any(marker in lowered for marker in _NEGATION_MARKERS)


def _claims_clearance(text: str) -> bool:
    """True only when a clearance token appears without a negation marker."""
    return _flagged(text, _CLEARANCE_TOKENS)


def _claims_performance(text: str) -> bool:
    """True only when a performance-claim token appears without a negation marker."""
    return _flagged(text, _PERFORMANCE_TOKENS)


SCENARIO_NAMES: tuple[str, ...] = (
    "01_scores_rounded_to_four_decimals",
    "02_angle_confidence_rounded_to_four_decimals",
    "03_duplicate_recommends_reject",
    "04_blocked_precedes_duplicate",
    "05_unsupported_rights_normalizes_to_unknown",
    "06_permission_needed_seeks_permission",
    "07_unknown_rights_seeks_permission",
    "08_blocked_rights_queued_blocked",
    "09_copyright_uncertainty_warned",
    "10_no_rights_clearance_claimed",
    "11_determinism_two_timestamp_exceptions",
    "12_queue_order_stable",
    "13_upstream_inputs_unmutated",
    "14_no_authority_fields_present",
    "15_top_level_field_set_exact",
    "16_human_review_always_required",
    "17_human_review_independent_of_rights_review",
    "18_performance_limitations_present",
    "19_no_performance_claim_strings",
    "20_angle_field_set_exact",
    "21_store_round_trip",
    "22_store_keys_off_scout_project_id",
    "23_export_omits_private_keys",
    "24_export_empties_review_questions",
    "25_export_json_safe",
    "26_missing_artifact_not_fabricated",
)

# Structurally fixture-only: each needs a second analyze() run or a pre-call
# input snapshot. A loaded artifact is a past result, so neither is observable
# from it and reporting a result would be a fabricated finding.
ALWAYS_FIXTURE_ONLY_SCENARIOS: frozenset[str] = frozenset(
    {
        "11_determinism_two_timestamp_exceptions",
        "12_queue_order_stable",
        "13_upstream_inputs_unmutated",
    }
)
# Conditionally applicable: each declares a precondition over the loaded
# artifact that a real project need not satisfy.
CONDITIONAL_SCENARIOS: frozenset[str] = frozenset(
    {
        "03_duplicate_recommends_reject",
        "04_blocked_precedes_duplicate",
        "05_unsupported_rights_normalizes_to_unknown",
        "06_permission_needed_seeks_permission",
        "07_unknown_rights_seeks_permission",
        "08_blocked_rights_queued_blocked",
    }
)
PROJECT_SKIPPABLE_SCENARIOS: frozenset[str] = (
    ALWAYS_FIXTURE_ONLY_SCENARIOS | CONDITIONAL_SCENARIOS
)


class _StoreObservation(NamedTuple):
    """Values observed from real ``BobaMemoryStore`` behaviour in a temp store."""

    scout_project_id: str
    artifact_path: str
    artifact_path_parts: tuple[str, ...]
    artifact_file_exists: bool
    round_trip_equal: bool
    loaded_project_id: str | None
    absent_project_id: str
    absent_artifact_path: str
    absent_file_exists: bool
    absent_load_is_none: bool
    absent_export_rejected: bool
    export: dict[str, Any]


class _Context(NamedTuple):
    """Inputs the scenario callables read.

    Every field after ``duplicate_map`` defaults to ``None`` because a mode may
    be structurally unable to supply it: ``--project-id`` inspects a stored
    artifact and can neither observe a second ``analyze()`` run nor compare
    pre-call input snapshots. A scenario whose inputs are ``None`` MUST report
    itself not-applicable through its ``applies`` precondition rather than
    guessing a result from partial data.
    """

    scout: BobaContentScoutSetV2
    payload: dict[str, Any]
    recommendations: dict[str, BobaScoutRecommendationV2]
    score_by_id: dict[str, BobaScoutScoreV2]
    duplicate_map: dict[str, str]
    store_observation: _StoreObservation | None = None
    second_payload: dict[str, Any] | None = None
    rights_probe: BobaContentScoutSetV2 | None = None
    immutability_probe: BobaContentScoutSetV2 | None = None
    upstream_before: str | None = None
    upstream_after: str | None = None
    upstream_ids_before: tuple[str, ...] | None = None
    upstream_ids_after: tuple[str, ...] | None = None


class _Scenario(NamedTuple):
    """One named check plus the precondition that decides whether it can run."""

    name: str
    applies: Callable[[_Context], bool]
    check: Callable[[_Context], tuple[bool, str]]


def _run_scenarios(
    scenarios: Sequence[_Scenario],
    context: _Context,
) -> tuple[dict[str, bool], list[str], list[str], list[str]]:
    """Run each scenario in isolation and return results, evidence, skips, errors.

    A scenario whose ``applies`` returns ``False`` is recorded in
    ``not_applicable`` and is absent from ``results`` — never defaulted to
    ``True`` and never defaulted to ``False``. A scenario that raises is recorded
    as ``results[name] = False`` with its exception text in ``errors``, so a
    crashing scenario cannot silently disappear from the gate. ``results``
    preserves ``scenarios`` order.
    """
    results: dict[str, bool] = {}
    evidence: list[str] = []
    not_applicable: list[str] = []
    errors: list[str] = []
    for scenario in scenarios:
        try:
            if not scenario.applies(context):
                not_applicable.append(scenario.name)
                continue
            ok, detail = scenario.check(context)
            results[scenario.name] = ok
            evidence.append(
                f"{scenario.name}: {'passed' if ok else 'FAILED'}: {detail}"
            )
        except Exception as exc:
            errors.append(f"{scenario.name}: {type(exc).__name__}: {exc}")
            results[scenario.name] = False
    return results, evidence, not_applicable, errors


# ---------------------------------------------------------------------------
# Scenario preconditions and checks. Every check derives its result from a value
# observed in real analyze() / store output.
# ---------------------------------------------------------------------------
def _always(_: _Context) -> bool:
    return True


def _angles(context: _Context) -> list[BobaSuggestedShortAngleV2]:
    return [
        angle
        for recommendation in context.recommendations.values()
        for angle in recommendation.suggested_short_angles
    ]


def _status_by_id(context: _Context) -> dict[str, str]:
    return {item.item_id: item.rights_status for item in context.scout.scout_items}


def _queue_ids(scout: BobaContentScoutSetV2, group: str) -> list[str]:
    recommendations: list[BobaScoutRecommendationV2] = getattr(
        scout.review_queue,
        group,
    )
    return [recommendation.item_id for recommendation in recommendations]


def _rights_probe_items(context: _Context) -> list[Any]:
    """Items that really carry the engine's unsupported-rights warning.

    Warning-based selection only. Used for the project-mode fallback, where a
    stored artifact offers no other handle on which item was normalized.
    """
    source = context.rights_probe or context.scout
    return [
        item
        for item in source.scout_items
        if any(
            UNSUPPORTED_RIGHTS_MARKER in warning.casefold()
            for warning in item.warnings
        )
    ]


def _rights_probe_targets(context: _Context) -> list[Any]:
    """The items scenario 05 judges.

    Fixture mode (``rights_probe is not None``): select by the FIXTURE-AUTHORED
    ``RIGHTS_PROBE_ITEM_ID`` and ignore warnings entirely. Selecting by the
    presence of the warning the check then asserts would be circular — deleting
    the warning would empty the selection and turn the scenario into a silent
    skip instead of a failure.

    Project mode (no probe): fall back to warning-based selection, because a
    stored artifact gives no independent handle on the normalized item.
    """
    probe = context.rights_probe
    if probe is not None:
        return [
            item
            for item in probe.scout_items
            if item.item_id == RIGHTS_PROBE_ITEM_ID
        ]
    return _rights_probe_items(context)


def _designed_duplicate_pairs(context: _Context) -> tuple[tuple[str, str], ...]:
    """Fixture-designed ``(duplicate, original)`` pairs present in this run.

    Derived from ``FIXTURE_DUPLICATE_PAIRS`` and the observed item ids only —
    never from ``context.duplicate_map``. Non-empty exactly in fixture mode.
    """
    ids = {item.item_id for item in context.scout.scout_items}
    return tuple(
        (duplicate, original)
        for duplicate, original in FIXTURE_DUPLICATE_PAIRS
        if duplicate in ids and original in ids
    )


def _duplicate_pairs(context: _Context) -> list[tuple[str, str]]:
    """Pairs scenarios 03/04 judge: engine-observed union fixture-designed.

    The engine's own pairing stays in the set because it is still informative in
    project mode, but the fixture-designed pairs are asserted unconditionally in
    fixture mode. An engine guard that stops reporting duplicates therefore
    produces a FAILURE, not an evaporated scenario.
    """
    merged = {**context.duplicate_map, **dict(_designed_duplicate_pairs(context))}
    return sorted(merged.items())


def _check_01_scores_rounded(context: _Context) -> tuple[bool, str]:
    unrounded: list[str] = []
    observed = 0
    sample = ""
    for score in context.scout.scored_items:
        dumped = score.model_dump(mode="json")
        for field in SCORE_FIELDS:
            value = float(dumped[field])
            observed += 1
            if not sample:
                sample = f"{score.item_id}.{field}={value!r}"
            if round(value, 4) != value:
                unrounded.append(f"{score.item_id}.{field}={value!r}")
    detail = (
        f"observed {observed} score value(s) across "
        f"{len(context.scout.scored_items)} scored item(s); sample {sample}; "
        f"values carrying a float tail: {unrounded[:3] or 'none'}"
    )
    return (observed > 0 and not unrounded), detail


def _check_02_angle_confidence_rounded(context: _Context) -> tuple[bool, str]:
    angles = _angles(context)
    unrounded = [
        f"{angle.angle_id}={angle.confidence!r}"
        for angle in angles
        if round(angle.confidence, 4) != angle.confidence
    ]
    sample = f"{angles[0].angle_id}={angles[0].confidence!r}" if angles else "none"
    detail = (
        f"observed {len(angles)} angle confidence value(s); sample {sample}; "
        f"values carrying a float tail: {unrounded[:3] or 'none'}"
    )
    return (bool(angles) and not unrounded), detail


def _applies_03_duplicate_reject(context: _Context) -> bool:
    status = _status_by_id(context)
    designed = _designed_duplicate_pairs(context)
    if designed:
        # Fixture mode: the fixture authored these pairs, so applicability is
        # decided from the fixture design alone. `context.duplicate_map` is the
        # engine helper under test; using it here would let neutralising that
        # helper turn a real regression into a silent skip.
        return any(status.get(duplicate) != "blocked" for duplicate, _ in designed)
    return any(
        status.get(item_id) != "blocked" and item_id in context.recommendations
        for item_id in context.duplicate_map
    )


def _check_03_duplicate_reject(context: _Context) -> tuple[bool, str]:
    status = _status_by_id(context)
    observed: list[str] = []
    ok = True
    pairs = [
        (item_id, original)
        for item_id, original in _duplicate_pairs(context)
        if status.get(item_id) != "blocked"
    ]
    for item_id, original in pairs:
        recommendation = context.recommendations.get(item_id)
        value = recommendation.recommendation if recommendation else None
        names_original = bool(recommendation) and original in str(
            getattr(recommendation, "reason", "")
        )
        similar = bool(recommendation) and "similar" in str(
            getattr(recommendation, "reason", "")
        ).casefold()
        observed.append(
            f"item_id={item_id!r} duplicate_of={original!r} "
            f"engine_duplicate_of={context.duplicate_map.get(item_id)!r} "
            f"recommendation={value!r} "
            f"reason_names_original={names_original} reason_says_similar={similar}"
        )
        if value != "reject" or not names_original or not similar:
            ok = False
    return (ok and bool(pairs)), "; ".join(observed) or "no duplicate pairing observed"


def _applies_04_blocked_precedes_duplicate(context: _Context) -> bool:
    status = _status_by_id(context)
    designed = _designed_duplicate_pairs(context)
    if designed:
        # Fixture mode: decided from the fixture design only, never from
        # `context.duplicate_map` (the engine helper under test).
        return any(status.get(duplicate) == "blocked" for duplicate, _ in designed)
    return any(
        status.get(item_id) == "blocked" for item_id in context.duplicate_map
    )


def _check_04_blocked_precedes_duplicate(context: _Context) -> tuple[bool, str]:
    status = _status_by_id(context)
    blocked_ids = set(_queue_ids(context.scout, "blocked_items"))
    duplicate_ids = set(_queue_ids(context.scout, "duplicate_or_similar_items"))
    observed: list[str] = []
    ok = True
    pairs = [
        (item_id, original)
        for item_id, original in _duplicate_pairs(context)
        if status.get(item_id) == "blocked"
    ]
    for item_id, original in pairs:
        recommendation = context.recommendations.get(item_id)
        value = recommendation.recommendation if recommendation else None
        reason = str(getattr(recommendation, "reason", ""))
        in_blocked = item_id in blocked_ids
        in_duplicates = item_id in duplicate_ids
        observed.append(
            f"item_id={item_id!r} duplicate_of={original!r} "
            f"engine_duplicate_of={context.duplicate_map.get(item_id)!r} "
            f"recommendation={value!r} "
            f"reason={reason!r} in_blocked_items={in_blocked} "
            f"in_duplicate_or_similar_items={in_duplicates}"
        )
        if (
            value != "blocked"
            or reason != BLOCKED_REASON
            or not in_blocked
            or not in_duplicates
        ):
            ok = False
    return (ok and bool(pairs)), "; ".join(observed) or "no blocked duplicate observed"


def _applies_05_unsupported_rights(context: _Context) -> bool:
    # Fixture mode: applicable whenever the probe ran and produced the designed
    # probe item, regardless of any warning. Project mode: warning-based.
    return bool(_rights_probe_targets(context))


def _check_05_unsupported_rights(context: _Context) -> tuple[bool, str]:
    fixture_mode = context.rights_probe is not None
    items = _rights_probe_targets(context)
    observed: list[str] = []
    ok = True
    for item in items:
        warning = next(
            (
                text
                for text in item.warnings
                if UNSUPPORTED_RIGHTS_MARKER in text.casefold()
            ),
            "",
        )
        lowered = warning.casefold()
        # Limb (a): the label was normalized to "unknown".
        normalized = item.rights_status == "unknown"
        # Limb (b): a warning names the raw status and records that it was
        # treated as unknown and requires review. Asserted independently of the
        # selection, so a missing warning is a failure.
        names_raw_status = (
            RIGHTS_PROBE_RAW_STATUS in lowered if fixture_mode else bool(warning)
        )
        records = "unknown" in lowered and "review" in lowered
        observed.append(
            f"item_id={item.item_id!r} rights_status={item.rights_status!r} "
            f"warning={warning!r} warning_names_raw_status={names_raw_status} "
            f"warning_records_unknown_and_review={records}"
        )
        if not normalized or not names_raw_status or not records:
            ok = False
    return (ok and bool(items)), "; ".join(observed) or "no normalization observed"


def _applies_06_permission_needed(context: _Context) -> bool:
    return any(
        item.rights_status == "permission_needed"
        and item.item_id not in context.duplicate_map
        for item in context.scout.scout_items
    )


def _check_06_permission_needed(context: _Context) -> tuple[bool, str]:
    targets = [
        item.item_id
        for item in context.scout.scout_items
        if item.rights_status == "permission_needed"
        and item.item_id not in context.duplicate_map
    ]
    observed = {
        item_id: getattr(context.recommendations.get(item_id), "recommendation", None)
        for item_id in targets
    }
    ok = bool(observed) and all(
        value == "seek_permission" for value in observed.values()
    )
    return ok, f"observed permission_needed recommendations {observed}"


def _applies_07_unknown_rights(context: _Context) -> bool:
    return any(
        item.rights_status == "unknown" and item.item_id not in context.duplicate_map
        for item in context.scout.scout_items
    )


def _check_07_unknown_rights(context: _Context) -> tuple[bool, str]:
    targets = [
        item.item_id
        for item in context.scout.scout_items
        if item.rights_status == "unknown"
        and item.item_id not in context.duplicate_map
    ]
    observed = {
        item_id: (
            getattr(context.recommendations.get(item_id), "recommendation", None),
            getattr(
                context.recommendations.get(item_id),
                "rights_review_required",
                None,
            ),
        )
        for item_id in targets
    }
    ok = bool(observed) and all(
        value == ("seek_permission", True) for value in observed.values()
    )
    return ok, f"observed unknown-rights (recommendation, rights_review) {observed}"


def _applies_08_blocked_rights(context: _Context) -> bool:
    return any(item.rights_status == "blocked" for item in context.scout.scout_items)


def _check_08_blocked_rights(context: _Context) -> tuple[bool, str]:
    blocked_ids = set(_queue_ids(context.scout, "blocked_items"))
    targets = [
        item.item_id
        for item in context.scout.scout_items
        if item.rights_status == "blocked"
    ]
    observed = {
        item_id: (
            getattr(context.recommendations.get(item_id), "recommendation", None),
            item_id in blocked_ids,
        )
        for item_id in targets
    }
    ok = bool(observed) and all(
        value == ("blocked", True) for value in observed.values()
    )
    return ok, f"observed blocked-rights (recommendation, in blocked_items) {observed}"


def _applies_recommendations(context: _Context) -> bool:
    return bool(context.recommendations)


def _check_09_copyright_uncertainty(context: _Context) -> tuple[bool, str]:
    silent = [
        recommendation.item_id
        for recommendation in context.recommendations.values()
        if not any(
            COPYRIGHT_WARNING in warning.casefold()
            for warning in recommendation.warnings
        )
    ]
    sample = next(
        (
            warning
            for recommendation in context.recommendations.values()
            for warning in recommendation.warnings
            if COPYRIGHT_WARNING in warning.casefold()
        ),
        "",
    )
    detail = (
        f"observed {len(context.recommendations)} recommendation(s); "
        f"warning sample={sample!r}; without the warning: {silent[:3] or 'none'}"
    )
    return (bool(context.recommendations) and not silent), detail


def _check_10_no_clearance_claim(context: _Context) -> tuple[bool, str]:
    strings = list(_walk_strings(context.payload))
    offenders = [text for text in strings if _claims_clearance(text)]
    tainted = copy.deepcopy(context.payload)
    tainted["warnings"] = [*_string_list(tainted.get("warnings")), _CLEARANCE_CONTROL]
    control = [text for text in _walk_strings(tainted) if _claims_clearance(text)]
    detail = (
        f"scanned {len(strings)} output string(s); clearance claims="
        f"{offenders[:2] or 'none'}; matcher fired on the injected control="
        f"{bool(control)}"
    )
    return (not offenders and bool(control)), detail


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _applies_11_determinism(context: _Context) -> bool:
    return context.second_payload is not None


def _check_11_determinism(context: _Context) -> tuple[bool, str]:
    second = context.second_payload
    if second is None:
        return False, "no second analyze() run was observed"
    left = copy.deepcopy(context.payload)
    right = copy.deepcopy(second)
    sources = left.get("imported_sources")
    source_count = len(sources) if isinstance(sources, list) else 0
    allowed = {"created_at"} | {
        f"imported_sources[{index}].imported_at" for index in range(source_count)
    }
    timestamps = ("created_at", "imported_at")
    left_paths = _key_paths(left, timestamps)
    right_paths = _key_paths(right, timestamps)
    published = _key_paths(left, ("published_at",))
    differing = _differing_paths(left, right)
    # Exclude exactly the two documented locations, positionally, and require
    # everything else to be identical.
    for payload in (left, right):
        payload.pop("created_at", None)
        for source in payload.get("imported_sources", []):
            if isinstance(source, dict):
                source.pop("imported_at", None)
    remainder_equal = json.dumps(left, sort_keys=True) == json.dumps(
        right,
        sort_keys=True,
    )
    ok = (
        left_paths == allowed
        and right_paths == allowed
        and bool(published)
        and published.isdisjoint(allowed)
        and published.isdisjoint(differing)
        and differing <= allowed
        and remainder_equal
    )
    detail = (
        f"observed timestamp path(s) {sorted(left_paths)} against expected "
        f"{sorted(allowed)}; {len(published)} published_at path(s) stayed inside the "
        f"compared surface; differing path(s)={sorted(differing) or 'none'}; "
        f"remaining payload identical={remainder_equal}"
    )
    return ok, detail


def _check_12_queue_order_stable(context: _Context) -> tuple[bool, str]:
    second = context.second_payload
    if second is None:
        return False, "no second analyze() run was observed"
    observed: dict[str, int] = {}
    ok = True
    for group in QUEUE_LISTS:
        left = _payload_queue_ids(context.payload, group)
        right = _payload_queue_ids(second, group)
        observed[group] = len(left)
        if not left or left != right:
            ok = False
    for name in ("scout_items", "scored_items"):
        left_ids = _payload_ids(context.payload, name)
        right_ids = _payload_ids(second, name)
        observed[name] = len(left_ids)
        if not left_ids or left_ids != right_ids:
            ok = False
    return ok, f"observed identical id order across two runs for {observed}"


def _payload_queue_ids(payload: Mapping[str, Any], group: str) -> list[str]:
    queue = payload.get("review_queue")
    rows = queue.get(group, []) if isinstance(queue, Mapping) else []
    return [
        str(row.get("item_id"))
        for row in rows
        if isinstance(row, Mapping)
    ]


def _payload_ids(payload: Mapping[str, Any], name: str) -> list[str]:
    rows = payload.get(name, [])
    return [
        str(row.get("item_id"))
        for row in rows
        if isinstance(row, Mapping)
    ] if isinstance(rows, list) else []


def _applies_13_immutability(context: _Context) -> bool:
    return (
        context.upstream_before is not None
        and context.upstream_after is not None
        and context.immutability_probe is not None
    )


def _check_13_upstream_unmutated(context: _Context) -> tuple[bool, str]:
    probe = context.immutability_probe
    if probe is None or context.upstream_ids_before is None:
        return False, "no pre-call input snapshot was observed"
    usage = probe.signal_usage
    arrived = (
        usage.creator_learning_used
        and usage.approval_rejection_learning_used
        and usage.performance_feedback_used
        and usage.memory_used
    )
    unchanged = context.upstream_before == context.upstream_after
    ids_unchanged = context.upstream_ids_before == context.upstream_ids_after
    length_unchanged = len(context.upstream_ids_before) == len(
        context.upstream_ids_after or ()
    )
    ok = (
        unchanged
        and ids_unchanged
        and length_unchanged
        and arrived
        and bool(probe.scout_items)
    )
    detail = (
        f"observed {len(context.upstream_before or '')}-char input snapshot "
        f"unchanged={unchanged}; caller list length "
        f"{len(context.upstream_ids_before)} and id order unchanged={ids_unchanged}; "
        f"all four advisory artifacts arrived={arrived}; "
        f"{len(probe.scout_items)} item(s) analyzed"
    )
    return ok, detail


def _check_14_no_authority_fields(context: _Context) -> tuple[bool, str]:
    keys = set(_walk_keys(context.payload))
    found = keys & AUTHORITY_KEYS
    tainted = copy.deepcopy(context.payload)
    tainted["approved"] = True
    control = set(_walk_keys(tainted)) & AUTHORITY_KEYS
    near_miss = "published_at" in keys
    ok = not found and control == {"approved"} and near_miss
    detail = (
        f"scanned {len(keys)} distinct key name(s) by exact equality; authority "
        f"key(s)={sorted(found) or 'none'}; the near-miss key 'published_at' is "
        f"present={near_miss}; injected control found={sorted(control)}"
    )
    return ok, detail


def _check_15_top_level_fields(context: _Context) -> tuple[bool, str]:
    observed = set(context.payload)
    ok = observed == set(TOP_LEVEL_FIELDS) and "recommendations" not in observed
    detail = (
        f"observed {len(observed)} top-level field(s); unexpected="
        f"{sorted(observed - TOP_LEVEL_FIELDS) or 'none'}; missing="
        f"{sorted(TOP_LEVEL_FIELDS - observed) or 'none'}"
    )
    return ok, detail


def _check_16_human_review_required(context: _Context) -> tuple[bool, str]:
    relaxed = [
        recommendation.item_id
        for recommendation in context.recommendations.values()
        if recommendation.human_review_required is not True
    ]
    kinds = sorted(
        {
            recommendation.recommendation
            for recommendation in context.recommendations.values()
        }
    )
    detail = (
        f"observed human_review_required on {len(context.recommendations)} "
        f"recommendation(s) spanning {kinds}; without it: {relaxed[:3] or 'none'}"
    )
    return (bool(context.recommendations) and not relaxed), detail


def _check_17_human_review_independent(context: _Context) -> tuple[bool, str]:
    relaxed = [
        recommendation
        for recommendation in context.recommendations.values()
        if recommendation.rights_review_required is False
    ]
    strict = [
        recommendation
        for recommendation in context.recommendations.values()
        if recommendation.rights_review_required is True
    ]
    offenders = [
        recommendation.item_id
        for recommendation in relaxed
        if recommendation.human_review_required is not True
    ]
    ok = bool(relaxed) and bool(strict) and not offenders
    detail = (
        f"observed {len(relaxed)} recommendation(s) with "
        f"rights_review_required=False (e.g. "
        f"{relaxed[0].item_id if relaxed else 'none'}) and {len(strict)} with True; "
        f"human review dropped on: {offenders[:3] or 'none'}"
    )
    return ok, detail


def _check_18_limitations_present(context: _Context) -> tuple[bool, str]:
    observed = list(context.scout.limitations)
    missing = [text for text in ENGINE_LIMITATIONS if text not in observed]
    detail = (
        f"observed {len(observed)} engine-authored limitation(s); missing verbatim: "
        f"{missing or 'none'}"
    )
    return (not missing and bool(observed)), detail


def _check_19_no_performance_claim(context: _Context) -> tuple[bool, str]:
    strings = list(_walk_strings(context.payload))
    offenders = [text for text in strings if _claims_performance(text)]
    tainted = copy.deepcopy(context.payload)
    tainted["warnings"] = [*_string_list(tainted.get("warnings")), _PERFORMANCE_CONTROL]
    control = [text for text in _walk_strings(tainted) if _claims_performance(text)]
    detail = (
        f"scanned {len(strings)} output string(s); performance claim(s)="
        f"{offenders[:2] or 'none'}; matcher fired on the injected control="
        f"{bool(control)}"
    )
    return (not offenders and bool(control)), detail


def _applies_angles(context: _Context) -> bool:
    return bool(_angles(context))


def _check_20_angle_field_set(context: _Context) -> tuple[bool, str]:
    angles = _angles(context)
    offenders = [
        f"{angle.angle_id}:{sorted(set(angle.model_dump(mode='json')))}"
        for angle in angles
        if set(angle.model_dump(mode="json")) != set(ANGLE_FIELDS)
    ]
    sample = sorted(set(angles[0].model_dump(mode="json"))) if angles else []
    detail = (
        f"observed {len(angles)} angle(s); field set sample={sample}; "
        f"mismatching angle(s)={offenders[:2] or 'none'}"
    )
    return (bool(angles) and not offenders), detail


def _applies_store(context: _Context) -> bool:
    return context.store_observation is not None


def _check_21_store_round_trip(context: _Context) -> tuple[bool, str]:
    observation = context.store_observation
    if observation is None:
        return False, "no store observation was made"
    ok = (
        observation.artifact_file_exists
        and observation.round_trip_equal
        and observation.loaded_project_id == observation.scout_project_id
    )
    detail = (
        f"saved to {observation.artifact_path!r} (file exists="
        f"{observation.artifact_file_exists}); reload equals the saved object="
        f"{observation.round_trip_equal}; reloaded project_id="
        f"{observation.loaded_project_id!r}"
    )
    return ok, detail


def _check_22_store_keys_off_project_id(context: _Context) -> tuple[bool, str]:
    observation = context.store_observation
    if observation is None:
        return False, "no store observation was made"
    keyed = observation.scout_project_id in observation.artifact_path_parts
    distinct = observation.absent_artifact_path != observation.artifact_path
    ok = (
        keyed
        and observation.artifact_file_exists
        and distinct
        and not observation.absent_file_exists
        and observation.absent_load_is_none
    )
    detail = (
        f"the Scout's own project_id {observation.scout_project_id!r} is a path "
        f"segment of {observation.artifact_path!r}={keyed}; the path computed for "
        f"{observation.absent_project_id!r} differs={distinct} and holds no file="
        f"{not observation.absent_file_exists}"
    )
    return ok, detail


def _check_23_export_omits_private_keys(context: _Context) -> tuple[bool, str]:
    observation = context.store_observation
    if observation is None:
        return False, "no store observation was made"
    exported = observation.export.get("content_scout_v2")
    if not isinstance(exported, dict):
        return False, f"export carried no content_scout_v2 payload: {observation.export!r}"
    payload_sources = _mapping_rows(context.payload.get("imported_sources"))
    payload_items = _mapping_rows(context.payload.get("scout_items"))
    exported_sources = _mapping_rows(exported.get("imported_sources"))
    exported_items = _mapping_rows(exported.get("scout_items"))
    present_before = sorted(
        key
        for key in (*PRIVATE_SOURCE_KEYS, *PRIVATE_ITEM_KEYS)
        if any(
            key in row
            for row in (
                payload_sources if key in PRIVATE_SOURCE_KEYS else payload_items
            )
        )
    )
    leaked = sorted(
        key
        for key in (*PRIVATE_SOURCE_KEYS, *PRIVATE_ITEM_KEYS)
        if any(
            key in row
            for row in (
                exported_sources if key in PRIVATE_SOURCE_KEYS else exported_items
            )
        )
    )
    same_items = {
        str(row.get("item_id")) for row in exported_items
    } == {str(row.get("item_id")) for row in payload_items}
    expected = sorted({*PRIVATE_SOURCE_KEYS, *PRIVATE_ITEM_KEYS})
    ok = present_before == expected and not leaked and same_items and bool(exported_items)
    detail = (
        f"private key(s) present in the saved payload={present_before}; still present "
        f"after export={leaked or 'none'}; the export retains all "
        f"{len(exported_items)} item id(s)={same_items}"
    )
    return ok, detail


def _mapping_rows(value: Any) -> list[Mapping[str, Any]]:
    return (
        [row for row in value if isinstance(row, Mapping)]
        if isinstance(value, list)
        else []
    )


def _check_24_export_empties_review_questions(context: _Context) -> tuple[bool, str]:
    observation = context.store_observation
    if observation is None:
        return False, "no store observation was made"
    exported = observation.export.get("content_scout_v2")
    if not isinstance(exported, dict):
        return False, "export carried no content_scout_v2 payload"
    populated_before = 0
    emptied_after = 0
    offenders: list[str] = []
    for group in QUEUE_LISTS:
        before = {
            str(row.get("item_id")): _string_list(row.get("suggested_review_questions"))
            for row in _payload_group_rows(context.payload, group)
        }
        for row in _payload_group_rows(exported, group):
            item_id = str(row.get("item_id"))
            questions = _string_list(row.get("suggested_review_questions"))
            if before.get(item_id):
                populated_before += 1
            if questions:
                offenders.append(f"{group}:{item_id}={questions[:1]}")
            else:
                emptied_after += 1
    ok = populated_before > 0 and not offenders and emptied_after > 0
    detail = (
        f"observed {populated_before} recommendation(s) carrying review questions "
        f"before export and {emptied_after} emptied in the export; still populated="
        f"{offenders[:2] or 'none'}"
    )
    return ok, detail


def _payload_group_rows(
    payload: Mapping[str, Any],
    group: str,
) -> list[Mapping[str, Any]]:
    queue = payload.get("review_queue")
    return _mapping_rows(queue.get(group)) if isinstance(queue, Mapping) else []


def _check_25_export_json_safe(context: _Context) -> tuple[bool, str]:
    observation = context.store_observation
    if observation is None:
        return False, "no store observation was made"
    encoded = json.dumps(observation.export)
    round_tripped = json.loads(encoded)
    ok = round_tripped == observation.export
    detail = (
        f"the export re-read identically through json.dumps/json.loads={ok}; "
        f"encoded length={len(encoded)} char(s)"
    )
    return ok, detail


def _check_26_missing_artifact(context: _Context) -> tuple[bool, str]:
    observation = context.store_observation
    if observation is None:
        return False, "no store observation was made"
    ok = (
        observation.absent_load_is_none
        and not observation.absent_file_exists
        and observation.absent_export_rejected
    )
    detail = (
        f"loading {observation.absent_project_id!r} returned None="
        f"{observation.absent_load_is_none} with no file at "
        f"{observation.absent_artifact_path!r}; exporting it was refused="
        f"{observation.absent_export_rejected}"
    )
    return ok, detail


SCENARIOS: tuple[_Scenario, ...] = (
    _Scenario(
        "01_scores_rounded_to_four_decimals",
        lambda context: bool(context.scout.scored_items),
        _check_01_scores_rounded,
    ),
    _Scenario(
        "02_angle_confidence_rounded_to_four_decimals",
        _applies_angles,
        _check_02_angle_confidence_rounded,
    ),
    _Scenario(
        "03_duplicate_recommends_reject",
        _applies_03_duplicate_reject,
        _check_03_duplicate_reject,
    ),
    _Scenario(
        "04_blocked_precedes_duplicate",
        _applies_04_blocked_precedes_duplicate,
        _check_04_blocked_precedes_duplicate,
    ),
    _Scenario(
        "05_unsupported_rights_normalizes_to_unknown",
        _applies_05_unsupported_rights,
        _check_05_unsupported_rights,
    ),
    _Scenario(
        "06_permission_needed_seeks_permission",
        _applies_06_permission_needed,
        _check_06_permission_needed,
    ),
    _Scenario(
        "07_unknown_rights_seeks_permission",
        _applies_07_unknown_rights,
        _check_07_unknown_rights,
    ),
    _Scenario(
        "08_blocked_rights_queued_blocked",
        _applies_08_blocked_rights,
        _check_08_blocked_rights,
    ),
    _Scenario(
        "09_copyright_uncertainty_warned",
        _applies_recommendations,
        _check_09_copyright_uncertainty,
    ),
    _Scenario(
        "10_no_rights_clearance_claimed",
        _always,
        _check_10_no_clearance_claim,
    ),
    _Scenario(
        "11_determinism_two_timestamp_exceptions",
        _applies_11_determinism,
        _check_11_determinism,
    ),
    _Scenario(
        "12_queue_order_stable",
        _applies_11_determinism,
        _check_12_queue_order_stable,
    ),
    _Scenario(
        "13_upstream_inputs_unmutated",
        _applies_13_immutability,
        _check_13_upstream_unmutated,
    ),
    _Scenario(
        "14_no_authority_fields_present",
        _always,
        _check_14_no_authority_fields,
    ),
    _Scenario(
        "15_top_level_field_set_exact",
        _always,
        _check_15_top_level_fields,
    ),
    _Scenario(
        "16_human_review_always_required",
        _applies_recommendations,
        _check_16_human_review_required,
    ),
    _Scenario(
        "17_human_review_independent_of_rights_review",
        _applies_recommendations,
        _check_17_human_review_independent,
    ),
    _Scenario(
        "18_performance_limitations_present",
        _always,
        _check_18_limitations_present,
    ),
    _Scenario(
        "19_no_performance_claim_strings",
        _always,
        _check_19_no_performance_claim,
    ),
    _Scenario(
        "20_angle_field_set_exact",
        _applies_angles,
        _check_20_angle_field_set,
    ),
    _Scenario(
        "21_store_round_trip",
        _applies_store,
        _check_21_store_round_trip,
    ),
    _Scenario(
        "22_store_keys_off_scout_project_id",
        _applies_store,
        _check_22_store_keys_off_project_id,
    ),
    _Scenario(
        "23_export_omits_private_keys",
        _applies_store,
        _check_23_export_omits_private_keys,
    ),
    _Scenario(
        "24_export_empties_review_questions",
        _applies_store,
        _check_24_export_empties_review_questions,
    ),
    _Scenario(
        "25_export_json_safe",
        _applies_store,
        _check_25_export_json_safe,
    ),
    _Scenario(
        "26_missing_artifact_not_fabricated",
        _applies_store,
        _check_26_missing_artifact,
    ),
)


def _scenario_table_errors() -> list[str]:
    """Structural guards on the scenario table itself (checked by --self-check)."""
    problems: list[str] = []
    duplicates = sorted(
        {name for name in SCENARIO_NAMES if SCENARIO_NAMES.count(name) > 1}
    )
    if duplicates:
        problems.append(f"SCENARIO_NAMES contains duplicate id(s): {duplicates}")
    registered = tuple(scenario.name for scenario in SCENARIOS)
    if registered != SCENARIO_NAMES:
        problems.append(
            "the registered scenario table does not match SCENARIO_NAMES in name "
            f"and order: {list(registered)} != {list(SCENARIO_NAMES)}"
        )
    return problems


def _observe_store(
    scout: BobaContentScoutSetV2,
    store: BobaMemoryStore,
) -> _StoreObservation:
    """Save the Scout_Set and observe real persistence, keying, and export."""
    saved = store.save_content_scout_v2(scout)
    artifact_path = store.content_scout_v2_path(scout.project_id)
    loaded = store.load_content_scout_v2(scout.project_id)
    absent_project_id = f"{scout.project_id}_absent"[:120]
    absent_path = store.content_scout_v2_path(absent_project_id)
    absent_load = store.load_content_scout_v2(absent_project_id)
    try:
        store.export_content_scout_v2(absent_project_id)
        absent_export_rejected = False
    except ValidationError:
        absent_export_rejected = True
    return _StoreObservation(
        scout_project_id=scout.project_id,
        artifact_path=str(artifact_path),
        artifact_path_parts=artifact_path.parts,
        artifact_file_exists=artifact_path.is_file(),
        round_trip_equal=loaded == saved,
        loaded_project_id=loaded.project_id if loaded is not None else None,
        absent_project_id=absent_project_id,
        absent_artifact_path=str(absent_path),
        absent_file_exists=absent_path.is_file(),
        absent_load_is_none=absent_load is None,
        absent_export_rejected=absent_export_rejected,
        export=store.export_content_scout_v2(scout.project_id),
    )


class _UpstreamProbe(NamedTuple):
    """A dedicated analyze() run whose caller-supplied inputs are snapshotted."""

    scout: BobaContentScoutSetV2
    before: str
    after: str
    ids_before: tuple[str, ...]
    ids_after: tuple[str, ...]


def _upstream_probe(project_id: str) -> _UpstreamProbe:
    items = build_synthetic_scout_items()
    signals = _signals_kwargs()
    inputs: dict[str, Any] = {"manual_items": items, **signals}
    before = _json_snapshot(inputs)
    ids_before = tuple(str(row.get("item_id", "")) for row in items)
    scout = BobaContentScoutV2().analyze(project_id, manual_items=items, **signals)
    return _UpstreamProbe(
        scout=scout,
        before=before,
        after=_json_snapshot(inputs),
        ids_before=ids_before,
        ids_after=tuple(str(row.get("item_id", "")) for row in items),
    )


def _rights_normalization_probe(project_id: str) -> BobaContentScoutSetV2:
    """Drive an unsupported rights label through real analyze() (not the helper)."""
    return BobaContentScoutV2().analyze(
        project_id,
        manual_items=[
            {
                "item_id": "probably_safe_item",
                "title": "A story about an unexpected lesson",
                "description": "Metadata with an unsupported rights label.",
                "rights_status": "probably_safe",
            }
        ],
        **_signals_kwargs(),
    )


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaContentScoutValidationReport:
    project_id = (
        "proj_content_scout_v2_self_check"
        if mode == "self_check"
        else "proj_content_scout_v2_synthetic"
    )
    scout = build_synthetic_content_scout(project_id)
    recommendations = _recommendations(scout)
    score_by_id = {score.item_id: score for score in scout.scored_items}
    rights_ready_ids = {
        item.item_id
        for item in scout.scout_items
        if item.rights_status in {"owned", "licensed", "permission_granted"}
        and "duplicate" not in item.item_id
        and item.item_id != "weak_generic"
    }
    # --self-check stays a cheap structural gate: no scenarios, and none of the
    # extra analyze() runs the scenarios would need (R11.1).
    full_run = mode == "synthetic_project"
    second_payload: dict[str, Any] | None = None
    upstream: _UpstreamProbe | None = None
    rights_probe: BobaContentScoutSetV2 | None = None
    if full_run:
        second_payload = build_synthetic_content_scout(project_id).model_dump(
            mode="json",
        )
        upstream = _upstream_probe(f"{project_id}_immutability")
        rights_probe = _rights_normalization_probe(f"{project_id}_rights")
    with TemporaryDirectory(prefix="boba-content-scout-v2-") as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(
            root / "boba",
            memory_root=root / "memory",
        )
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated project memory must survive Scout V2 reset.",
            )
        )
        observation = _observe_store(scout, store)
        artifact_persisted = (
            observation.artifact_file_exists and observation.round_trip_equal
        )
        export = observation.export
        export_safe = _safe_export(export)
        reset_removed = store.reset_content_scout_v2(project_id)
        reset_project_only = (
            reset_removed
            and store.load_content_scout_v2(project_id) is None
            and store.load_project_memory(project_id) is not None
        )

    report = BobaContentScoutValidationReport(
        mode=mode,
        passed=False,
        project_id=project_id,
        modules_imported=True,
        store_available=True,
        creator_learning_available=scout.signal_usage.creator_learning_used,
        performance_feedback_available=(
            scout.signal_usage.performance_feedback_used
        ),
        report_path_writable=_report_path_writable(report_dir),
        items_imported=len(scout.scout_items),
        invalid_items_rejected=any(
            "title or description" in item.reason_rejected.casefold()
            for item in scout.rejected_items
        ),
        scores_bounded=all(
            0.0 <= value <= 1.0
            for score in scout.scored_items
            for value in (
                score.creator_fit_score,
                score.topic_fit_score,
                score.shortability_score,
                score.hook_potential_score,
                score.emotional_story_score,
                score.trend_context_score,
                score.novelty_score,
                score.rights_readiness_score,
                score.review_priority_score,
                score.confidence,
            )
        ),
        review_queue_created=bool(scout.review_queue.queue_summary),
        rights_ready_review_now=rights_ready_ids.issubset(
            {
                item.item_id
                for item in scout.review_queue.top_items
            }
        ),
        unknown_requires_review=(
            recommendations["funny_unknown"].recommendation == "seek_permission"
            and recommendations["funny_unknown"].rights_review_required
        ),
        permission_needed_seek_permission=(
            recommendations["permission_needed_high_potential"].recommendation
            == "seek_permission"
        ),
        blocked_queued=(
            recommendations["blocked_source"].recommendation == "blocked"
            and any(
                item.item_id == "blocked_source"
                for item in scout.review_queue.blocked_items
            )
        ),
        duplicates_detected=(
            "owned_emotional_duplicate" in recommendations
            and score_by_id["owned_emotional_duplicate"].novelty_score
            < score_by_id["owned_emotional_story"].novelty_score
        ),
        suggested_angles_created=all(
            recommendations[item_id].suggested_short_angles
            for item_id in (
                "owned_emotional_story",
                "permission_needed_high_potential",
            )
        ),
        external_api_used_false=scout.signal_usage.external_api_used is False,
        url_fetching_used_false=scout.signal_usage.url_fetching_used is False,
        downloading_used_false=scout.signal_usage.downloading_used is False,
        artifact_persisted=artifact_persisted,
        json_safe=bool(json.loads(scout.model_dump_json())),
        export_safe=export_safe,
        reset_project_only=reset_project_only,
        warnings=[
            "Validation used synthetic local metadata only.",
            "No rendering, download, URL fetch, external API, or external call occurred.",
            "Rights statuses are synthetic user-provided labels, not copyright findings.",
        ],
        errors=_scenario_table_errors(),
    )
    # Environment and fixture-integrity gates. Each is genuinely assigned from an
    # observed value; the behavioural burden sits on the scenarios.
    preconditions = (
        report.modules_imported
        and report.store_available
        and report.report_path_writable
        and report.items_imported >= 8
        and report.invalid_items_rejected
    )
    if not full_run:
        report.warnings.append(
            "Self-check mode is a structural gate: the 26 behavioural scenarios "
            "were not executed and no scenario result is reported."
        )
        report.passed = preconditions and not report.errors
        return report

    context = _Context(
        scout=scout,
        payload=scout.model_dump(mode="json"),
        recommendations=recommendations,
        score_by_id=score_by_id,
        duplicate_map=_duplicate_map(scout.scout_items),
        store_observation=observation,
        second_payload=second_payload,
        rights_probe=rights_probe,
        immutability_probe=upstream.scout if upstream else None,
        upstream_before=upstream.before if upstream else None,
        upstream_after=upstream.after if upstream else None,
        upstream_ids_before=upstream.ids_before if upstream else None,
        upstream_ids_after=upstream.ids_after if upstream else None,
    )
    results, evidence, not_applicable, errors = _run_scenarios(SCENARIOS, context)
    report.scenario_results = results
    report.scenario_count = len(results)
    report.passed_scenario_count = sum(1 for value in results.values() if value)
    report.scenarios_not_applicable = not_applicable
    report.evidence = evidence
    report.errors = [*report.errors, *errors]
    report.passed = (
        tuple(results) == SCENARIO_NAMES
        and bool(results)
        and all(results.values())
        and not report.errors
        and not not_applicable
        and preconditions
    )
    return report


def run_self_check(
    report_dir: Path | None = None,
) -> BobaContentScoutValidationReport:
    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaContentScoutValidationReport:
    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


async def _existing_project(
    project_id: str,
    report_dir: Path,
) -> BobaContentScoutValidationReport:
    try:
        integration = boba_integration_provider()
        scout = integration.load_content_scout_v2(project_id)
        if scout is None:
            # R11.8: report the absence instead of fabricating a result. The only
            # honest observation available is that the load returned nothing.
            return BobaContentScoutValidationReport(
                mode="project_id",
                passed=False,
                project_id=project_id,
                modules_imported=True,
                store_available=True,
                report_path_writable=_report_path_writable(report_dir),
                scenario_count=1,
                passed_scenario_count=1,
                scenario_results={"26_missing_artifact_not_fabricated": True},
                scenarios_not_applicable=[
                    name
                    for name in SCENARIO_NAMES
                    if name != "26_missing_artifact_not_fabricated"
                ],
                evidence=[
                    "26_missing_artifact_not_fabricated: passed: observed "
                    f"load_content_scout_v2({project_id!r}) is None; no artifact "
                    "was fabricated",
                ],
                warnings=[
                    "No saved Content Scout V2 artifact is available for this project.",
                    "The validator did not render, upload, download, fetch a URL, "
                    "or call an external API.",
                    "No behavioural scenario could be evaluated, so this run does "
                    "not pass.",
                ],
            )
        export = integration.export_content_scout_v2(project_id)
        with TemporaryDirectory(prefix="boba-content-scout-v2-project-") as temporary:
            observation = _observe_store(
                scout,
                BobaMemoryStore(Path(temporary) / "boba"),
            )
        report = BobaContentScoutValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            creator_learning_available=scout.signal_usage.creator_learning_used,
            performance_feedback_available=(
                scout.signal_usage.performance_feedback_used
            ),
            report_path_writable=_report_path_writable(report_dir),
            items_imported=len(scout.scout_items),
            invalid_items_rejected=True,
            scores_bounded=all(
                0.0 <= score.review_priority_score <= 1.0
                and 0.0 <= score.confidence <= 1.0
                for score in scout.scored_items
            ),
            review_queue_created=bool(scout.review_queue.queue_summary),
            artifact_persisted=integration.store.content_scout_v2_path(
                project_id
            ).is_file(),
            json_safe=bool(json.loads(scout.model_dump_json())),
            export_safe=_safe_export(export),
            external_api_used_false=True,
            url_fetching_used_false=True,
            downloading_used_false=True,
            warnings=[
                "Existing-project mode inspected the saved local metadata artifact only.",
                "No rendering, upload, download, URL fetch, or external call occurred.",
            ],
            errors=_scenario_table_errors(),
        )
        context = _Context(
            scout=scout,
            payload=scout.model_dump(mode="json"),
            recommendations=_recommendations(scout),
            score_by_id={score.item_id: score for score in scout.scored_items},
            duplicate_map=_duplicate_map(scout.scout_items),
            store_observation=observation,
        )
        results, evidence, not_applicable, errors = _run_scenarios(
            SCENARIOS,
            context,
        )
        report.scenario_results = results
        report.scenario_count = len(results)
        report.passed_scenario_count = sum(1 for value in results.values() if value)
        report.scenarios_not_applicable = not_applicable
        report.evidence = evidence
        report.errors = [*report.errors, *errors]
        if not_applicable:
            report.warnings.append(
                "Scenarios whose precondition the stored artifact does not satisfy "
                "were not evaluated and carry no result: "
                f"{', '.join(not_applicable)}."
            )
        # The expected id sequence is computed from the preconditions observed on
        # this artifact, never hardcoded, and skips are confined to the scenarios
        # a stored past result genuinely cannot answer.
        applicable = tuple(
            name for name in SCENARIO_NAMES if name not in set(not_applicable)
        )
        report.passed = (
            tuple(results) == applicable
            and set(results) | set(not_applicable) == set(SCENARIO_NAMES)
            and set(not_applicable) <= PROJECT_SKIPPABLE_SCENARIOS
            and bool(results)
            and all(results.values())
            and not report.errors
            and report.modules_imported
            and report.store_available
            and report.report_path_writable
            and report.review_queue_created
            and report.artifact_persisted
        )
        return report
    except Exception as exc:
        return BobaContentScoutValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, fetch a URL, "
                "or call an external API."
            ],
        )


def _write_report(
    report: BobaContentScoutValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_content_scout_v2_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Content Scout V2 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Metadata items: `{report.items_imported}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        f"- Scenarios executed: `{report.scenario_count}`",
        f"- Scenarios passed: `{report.passed_scenario_count}`",
        "",
        "## Scenario results",
        "",
    ]
    if report.scenario_results:
        summary += [
            "| Scenario | Result |",
            "| --- | --- |",
            *(
                f"| `{name}` | `{'pass' if ok else 'FAIL'}` |"
                for name, ok in report.scenario_results.items()
            ),
        ]
    else:
        summary.append(
            "No behavioural scenario ran in this mode; `--self-check` is a "
            "structural gate only.",
        )
    summary += ["", "## Not evaluated", ""]
    if report.scenarios_not_applicable:
        summary += [
            "The scenarios below were **not evaluated** because their "
            "preconditions were not observable in this artifact. They have no "
            "result and must not be read as passing:",
            "",
            *(f"- `{name}`" for name in report.scenarios_not_applicable),
        ]
    else:
        summary.append("Every registered scenario was evaluated.")
    if report.evidence:
        summary += [
            "",
            "## Observed evidence",
            "",
            *(f"- {line}" for line in report.evidence),
        ]
    if report.warnings:
        summary += ["", "## Warnings", "", *(f"- {line}" for line in report.warnings)]
    if report.errors:
        summary += ["", "## Errors", "", *(f"- {line}" for line in report.errors)]
    summary += [
        "",
        "## Scope",
        "",
        "Content Scout V2 is metadata-only, advisory, and cannot confirm copyright "
        "safety or guarantee performance.",
        "",
        "Absence of network, download, and rendering activity is proven by "
        "`test_43`-`test_46` in `tests/unit/test_boba_content_scout_v2.py`, which "
        "block `subprocess.run`, `Path.write_bytes`, `urllib.request.urlopen`, and "
        "`socket.create_connection` and then run real Scout behaviour. Those tests "
        "are the authoritative no-network proof. The report's "
        "`external_api_used_false`, `url_fetching_used_false`, and "
        "`downloading_used_false` fields are retained for backward compatibility "
        "only; they read `Literal[False]` contract fields, so they are not "
        "findings and gate nothing.",
    ]
    (report_dir / "boba_content_scout_v2_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Content Scout V2 locally.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report_dir = args.report_dir.resolve()
    if args.self_check:
        report = run_self_check(report_dir)
    elif args.synthetic_project:
        report = run_synthetic_project(report_dir)
    else:
        report = asyncio.run(_existing_project(str(args.project_id), report_dir))
    _write_report(report, report_dir)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
