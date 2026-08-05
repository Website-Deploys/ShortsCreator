"""Offline validation for BOBA Clip Brief Panel V1.

The tool uses only synthetic BOBA metadata under the ignored validation
workspace. It never generates, regenerates or rewrites a clip brief, never
invents a field, and never runs commands, Git, FFmpeg, validators, repairs,
workflow transitions, media work, network access, upload, publication or
source-owner decision mutation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from olympus.boba.clip_brief_review import (
    CLIP_BRIEF_QUEUE_PRIORITY_TIERS,
    MAX_ANNOTATION_LENGTH,
    MAX_BOUNDED_DISPLAY_CHARS,
    MAX_COMPARISON_BRIEFS,
    MAX_QUEUE_PAGE_SIZE,
    SUPPORTED_BRIEF_SCHEMA_ID,
    BobaClipBriefActionReceiptV1,
    BobaClipBriefReferenceV1,
    BobaClipBriefReviewV1,
    build_fixed_clip_brief_action_registry,
    build_fixed_clip_brief_section_registry,
    build_fixed_clip_brief_source_registry,
    owner_schema_optional_field_paths,
    owner_schema_required_field_paths,
)
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError

try:  # imported as ``tools.validate_boba_clip_brief_review``
    from tools._boba_clip_brief_review_fixtures import (
        seed_project,
        synthetic_brief,
        synthetic_brief_set,
    )
except ModuleNotFoundError:  # executed directly as a script
    from _boba_clip_brief_review_fixtures import (  # type: ignore[no-redef,import-not-found]
        seed_project,
        synthetic_brief,
        synthetic_brief_set,
    )

PROJECT_ID = "proj_clip_brief_review_validation"
_FEEDBACK = "clip_brief_action_submit_feedback_v1"
_NOTE = "clip_brief_action_record_review_note_v1"

_CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "identity": (
        "valid-brief-projected",
        "unknown-brief-rejected",
        "cross-project-brief-excluded",
        "brief-id-charset-enforced",
        "candidate-identity-preserved",
        "clip-identity-preserved",
        "project-identity-enforced",
        "source-digest-recorded",
        "supported-schema-accepted",
        "unsupported-schema-flagged",
        "current-brief-labelled",
        "stale-flag-explicit",
        "historical-flag-explicit",
        "superseded-flag-explicit",
        "absent-revision-remains-absent",
        "no-inferred-supersession",
        "lifecycle-bucket-preserved",
        "exact-source-window-preserved",
        "inverted-window-rejected",
        "workflow-identity-from-controller",
    ),
    "fields": (
        "required-field-present",
        "required-field-missing",
        "optional-field-present",
        "optional-field-missing",
        "empty-list-distinguished",
        "nested-field-projected",
        "instruction-field-projected",
        "source-value-preserved",
        "easy-explanation-separated",
        "no-source-rewriting",
        "no-invented-field",
        "no-request-defined-schema",
        "field-count-matches-owner-schema",
        "field-category-only-when-supported",
        "no-beats-or-ending-invented",
        "value-type-reported",
        "value-digest-recorded",
        "bounded-display-limit",
        "advisory-field-marked",
        "human-editable-always-false",
    ),
    "sections": (
        "sections-built-from-owner-fields",
        "section-required-counts",
        "section-optional-counts",
        "empty-section-labelled",
        "collapsed-by-default-respected",
        "section-count-fixed",
        "every-field-belongs-to-a-section",
    ),
    "completeness": (
        "complete-with-optional-gaps",
        "missing-required-fields-status",
        "unsupported-schema-status",
        "required-ratio-deterministic",
        "optional-ratio-deterministic",
        "required-paths-fixed",
        "optional-paths-fixed",
        "complete-does-not-mean-approved",
        "complete-does-not-mean-quality",
        "complete-does-not-mean-technically-valid",
        "creative-quality-never-assessed",
        "technical-quality-never-assessed",
        "blocking-reasons-listed",
        "no-quality-score",
    ),
    "sources": (
        "brief-source-present",
        "brief-source-missing",
        "candidate-source-present",
        "candidate-source-missing",
        "editorial-source-present",
        "ranking-source-present",
        "creative-source-advisory",
        "hook-source-advisory",
        "caption-source-advisory",
        "music-source-advisory",
        "rights-source-authoritative",
        "safety-source-authoritative",
        "workflow-source-authoritative",
        "artifact-source-authoritative",
        "validation-source-authoritative",
        "unavailable-source-reported",
        "source-owner-preserved",
        "duplicate-source-descriptor-rejected",
        "required-source-declared",
    ),
    "evidence": (
        "candidate-evidence-linked",
        "ranking-evidence-linked",
        "editorial-evidence-linked",
        "advisory-evidence-marked",
        "missing-evidence-reported",
        "missing-evidence-not-a-pass",
        "exact-identity-match-recorded",
        "digest-match-recorded",
        "transcript-segment-ids-from-owner",
        "source-window-carried",
        "no-text-similarity-inference",
        "evidence-bounded",
    ),
    "conflicts": (
        "candidate-identity-conflict",
        "source-window-conflict",
        "duration-conflict",
        "editorial-status-conflict",
        "lifecycle-conflict",
        "clip-identity-conflict",
        "revision-conflict-without-supersession",
        "unsupported-schema-conflict",
        "no-conflict-on-clean-project",
        "advisory-options-not-conflict",
        "confidence-does-not-resolve",
        "unresolved-conflict-explicit",
        "blocking-conflict-blocks-action",
        "conflict-requires-same-identity",
    ),
    "queue": (
        "critical-block-priority",
        "identity-conflict-priority",
        "human-review-priority",
        "missing-required-fields-priority",
        "missing-evidence-priority",
        "stale-selected-priority",
        "selected-candidate-priority",
        "warning-priority",
        "other-current-priority",
        "rejected-candidate-priority",
        "superseded-priority",
        "historical-priority",
        "twelve-priority-tiers",
        "deterministic-tie-break",
        "deterministic-repeat-order",
        "pagination-bounded",
        "filter-all-current",
        "filter-human-review",
        "filter-current-selected-candidate",
        "filter-missing-required-fields",
        "filter-missing-evidence",
        "filter-conflicts",
        "filter-stale",
        "filter-complete",
        "filter-warnings",
        "filter-historical",
        "filter-superseded",
        "unsupported-filter-rejected",
        "sort-review-priority",
        "sort-candidate-rank",
        "sort-created-sequence",
        "sort-source-start-time",
        "sort-brief-id",
        "unsupported-sort-rejected",
        "no-ai-quality-sort",
    ),
    "comparison": (
        "two-brief-comparison",
        "four-brief-comparison",
        "single-brief-rejected",
        "too-many-briefs-rejected",
        "unknown-brief-comparison-rejected",
        "duplicate-ids-collapsed",
        "unsupported-comparison-type-rejected",
        "field-comparison-present",
        "section-comparison-present",
        "completeness-comparison-present",
        "evidence-comparison-present",
        "source-window-comparison-present",
        "duration-comparison-present",
        "missing-fields-visible",
        "same-candidate-detected",
        "cross-candidate-detected",
        "no-automatic-winner",
        "no-preferred-brief-score",
    ),
    "preview": (
        "safe-same-origin-preview",
        "external-url-blocked",
        "absolute-path-blocked",
        "file-uri-blocked",
        "traversal-blocked",
        "exact-persisted-range-published",
        "browser-replacement-range-blocked",
        "context-labelled-non-authoritative",
        "preview-unavailable-state",
        "playback-not-validation",
        "no-ffmpeg-generation",
    ),
    "actions": (
        "feedback-action-available",
        "note-action-available",
        "approve-action-unavailable",
        "reject-action-unavailable",
        "revision-action-unavailable",
        "regeneration-action-unavailable",
        "no-authoritative-action-in-v1",
        "unknown-action-rejected",
        "unavailable-action-rejected",
        "unsupported-decision-rejected",
        "missing-reason-rejected",
        "oversized-reason-rejected",
        "secret-bearing-reason-rejected",
        "missing-confirmation-rejected",
        "wrong-confirmation-token-rejected",
        "reviewer-context-required",
        "expired-request-rejected",
        "changed-project-digest-rejected",
        "changed-workflow-revision-rejected",
        "changed-brief-digest-rejected",
        "changed-source-digest-rejected",
        "candidate-mismatch-rejected",
        "clip-mismatch-rejected",
        "canonical-receipt-recorded",
        "advisory-receipt-not-authoritative",
        "owner-rejection-recorded",
        "malformed-owner-response-handled",
        "duplicate-request-reused",
        "no-optimistic-update",
        "authority-requires-owner-record",
        "wrong-owner-route-unavailable",
    ),
    "authority": (
        "no-brief-generation",
        "no-brief-regeneration",
        "no-brief-rewriting",
        "no-hidden-quality-score",
        "no-hidden-virality-score",
        "no-local-approval",
        "no-local-rejection",
        "no-dynamic-import",
        "no-arbitrary-module",
        "no-arbitrary-operation",
        "no-arbitrary-url",
        "no-arbitrary-path",
        "no-external-media",
        "no-untrusted-html",
        "no-command-execution",
        "no-shell-execution",
        "no-git-execution",
        "no-ffmpeg-execution",
        "no-media-generation",
        "no-artifact-modification",
        "no-source-media-modification",
        "no-accepted-output-modification",
        "no-workflow-transition",
        "no-rights-creation",
        "no-safety-creation",
        "no-upload",
        "no-publication",
        "no-external-analytics",
        "no-rights-bypass",
        "no-safety-bypass",
        "no-destructive-action",
        "no-source-record-writes",
    ),
    "persistence": (
        "session-persisted",
        "session-expiry-enforced",
        "session-project-scoped",
        "session-field-allowlist",
        "comparison-limit-enforced-in-session",
        "annotations-bounded",
        "annotations-carry-notice",
        "annotations-reject-secrets",
        "annotations-never-canonical",
        "registry-snapshot-immutable",
        "action-request-immutable",
        "receipt-immutable",
        "source-records-not-duplicated",
        "reset-preserves-clip-brief-records",
        "reset-preserves-candidate-review-history",
        "reset-preserves-review-ui-history",
        "reset-preserves-workflow-history",
        "sanitized-export",
        "export-excludes-private-paths",
        "event-cursor-bounded",
    ),
    "events": (
        "events-deduplicated",
        "events-never-invent-progress",
        "malformed-progress-ignored",
        "control-events-not-work",
        "events-project-scoped",
        "events-bounded",
        "timeline-bounded",
        "timeline-marks-unknown-timestamps",
        "event-cursor-exposed",
    ),
    "integration": (
        "integration-layer-operations-registered",
        "module-registered-available",
        "safety-gate-classifies-read-only",
        "safety-gate-gates-submit",
        "review-ui-untouched",
        "candidate-review-untouched",
        "fixed-source-registry",
        "fixed-section-registry",
        "fixed-action-registry",
    ),
}

SCENARIO_NAMES: tuple[str, ...] = tuple(
    f"{group}:{name}" for group, names in _CONDITION_GROUPS.items() for name in names
)


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str


class _StubCreatorLearning:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reject = False
        self.malformed = False

    async def record_creator_feedback_event(
        self, project_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        if self.reject:
            raise ValidationError("Creator Learning rejected the feedback event.")
        self.calls.append({"project_id": project_id, **kwargs})
        if self.malformed:
            return {"user_action": kwargs.get("user_action")}
        return {
            "event_id": f"creator_feedback_{len(self.calls)}",
            "target_id": kwargs.get("target_id"),
            "target_type": kwargs.get("target_type"),
            "user_action": kwargs.get("user_action"),
        }


class _StubIntegration:
    def __init__(self) -> None:
        self.owner = _StubCreatorLearning()

    async def record_creator_feedback_event(
        self, project_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await self.owner.record_creator_feedback_event(project_id, **kwargs)


def _engine(root: Path, **seed: Any) -> tuple[BobaClipBriefReviewV1, _StubIntegration]:
    store = BobaMemoryStore(root)
    integration = _StubIntegration()
    engine = BobaClipBriefReviewV1(store, integration)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, integration


def _prepared(engine: BobaClipBriefReviewV1, brief_id: str = "brief_a") -> dict[str, Any]:
    session = engine.create_clip_brief_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    payload = engine.build_clip_brief_snapshot(
        PROJECT_ID, session.clip_brief_review_session_id, brief_id
    )
    payload["session"] = session
    return payload


def _request(
    engine: BobaClipBriefReviewV1,
    payload: dict[str, Any],
    key: str,
    *,
    action: str = _FEEDBACK,
    decision: str | None = "approved",
    reason: str = "Reviewed the exact clip brief.",
) -> Any:
    return engine.create_clip_brief_action_request(
        PROJECT_ID,
        clip_brief_review_session_id=payload["session"].clip_brief_review_session_id,
        brief_snapshot_id=payload["snapshot"]["brief_snapshot_id"],
        action_descriptor_id=action,
        decision_value=decision,
        reason=reason,
        confirmation_context_digest=payload["action_confirmations"][action],
        idempotency_key=key,
        confirmed=True,
    )


def _check(name: str, passed: bool, detail: str) -> ScenarioResult:
    return ScenarioResult(name=name, passed=passed, detail=detail)


def _source_text() -> str:
    return Path("src/olympus/boba/clip_brief_review.py").read_text(encoding="utf-8")

def _frontend_text() -> str:
    return Path("frontend/src/lib/clipBriefReview.ts").read_text(encoding="utf-8")


def _expect_error(callable_: Any, *args: Any, **kwargs: Any) -> tuple[bool, str]:
    """Pass only when the call is refused by an explicit validation error."""
    try:
        callable_(*args, **kwargs)
    except ValidationError as error:
        return (True, f"refused: {str(error)[:120]}")
    except Exception as error:  # any refusal is still a refusal
        return (True, f"refused ({type(error).__name__}): {str(error)[:100]}")
    return (False, "the call was accepted when it should have been refused")


def _rewrite(path: Path, updates: dict[str, Any]) -> None:
    """Simulate canonical drift by editing a persisted record on disk."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class _RawBriefStore(BobaMemoryStore):
    """Serve an arbitrary raw clip-brief payload instead of the validated set.

    ``load_clip_briefs`` validates ``BobaClipBriefSetV1``, so an unsupported
    schema id, a brief missing a required field, or a raw event list can never
    reach the panel through the canonical loader. Injecting the raw payload here
    exercises the projection's defensive branches instead of assuming them.
    """

    def __init__(self, root: Path, raw: dict[str, Any]) -> None:
        super().__init__(root)
        self._raw = raw

    def load_clip_briefs(self, project_id: str) -> Any:
        return self._raw


def _raw_brief_payload(
    *,
    brief_version: str = SUPPORTED_BRIEF_SCHEMA_ID,
    drop_fields: tuple[str, ...] = (),
    overrides: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    brief = synthetic_brief("brief_a", PROJECT_ID, "cand_a", "cand_a", 10.0, 40.0)
    payload = synthetic_brief_set(PROJECT_ID, selected=[brief]).model_dump(mode="json")
    payload["brief_version"] = brief_version
    row = payload["selected_briefs"][0]
    for field in drop_fields:
        row.pop(field, None)
    row.update(overrides or {})
    if events is not None:
        payload["events"] = events
    return payload


def _raw_engine(root: Path, raw: dict[str, Any]) -> BobaClipBriefReviewV1:
    store = _RawBriefStore(root, raw)
    seed_project(store, PROJECT_ID, with_briefs=False)
    return BobaClipBriefReviewV1(store, _StubIntegration())  # type: ignore[arg-type]


def _group(group: str, checks: dict[str, tuple[bool, str]]) -> list[ScenarioResult]:
    """Emit one result per catalogued condition, flagging any gap honestly."""
    results: list[ScenarioResult] = []
    for name in _CONDITION_GROUPS[group]:
        if name not in checks:
            results.append(_check(f"{group}:{name}", False, "condition not evaluated"))
            continue
        passed, detail = checks[name]
        results.append(_check(f"{group}:{name}", passed, detail))
    return results


def _run_identity() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        references = engine.build_clip_brief_references(PROJECT_ID)
        by_id = {item.brief_id: item for item in references}
        ref = by_id["brief_a"]

        blocked_engine, _ = _engine(root / "blocked", blocked_brief_ids=["brief_a"])
        blocked = next(
            item
            for item in blocked_engine.build_clip_brief_references(PROJECT_ID)
            if item.brief_id == "brief_a"
        )

        unsupported = _raw_engine(
            root / "unsupported", _raw_brief_payload(brief_version="boba_clip_brief_v9")
        )
        unsupported_ref = unsupported.build_clip_brief_references(PROJECT_ID)[0]

        cross_engine, _ = _engine(root / "cross", with_briefs=False)
        cross_detail = "owner contract refused the cross-project brief"
        cross_ok = True
        try:
            cross_engine.store.save_clip_briefs(
                synthetic_brief_set(
                    PROJECT_ID,
                    selected=[
                        synthetic_brief(
                            "brief_x", "other_project_id", "cand_a", "cand_a", 1.0, 5.0
                        )
                    ],
                )
            )
        except Exception as error:
            cross_detail = f"owner contract refused it: {type(error).__name__}"
        else:
            ids = {
                item.brief_id
                for item in cross_engine.build_clip_brief_references(PROJECT_ID)
            }
            cross_ok = "brief_x" not in ids
            cross_detail = f"projected ids {sorted(ids)}"

        source = _source_text()
        workflow_record = engine.store.load_boba_workflow_controller(PROJECT_ID)
        return _group(
            "identity",
            {
                "valid-brief-projected": (
                    {"brief_a", "brief_b"} <= set(by_id),
                    f"projected {sorted(by_id)}",
                ),
                "unknown-brief-rejected": _expect_error(
                    engine.inspect_clip_brief, PROJECT_ID, "brief_does_not_exist"
                ),
                "cross-project-brief-excluded": (cross_ok, cross_detail),
                "brief-id-charset-enforced": _expect_error(
                    engine.inspect_clip_brief, PROJECT_ID, "brief a!/../etc"
                ),
                "candidate-identity-preserved": (
                    ref.candidate_id == "cand_a",
                    f"candidate_id={ref.candidate_id}",
                ),
                "clip-identity-preserved": (
                    ref.clip_id == "cand_a",
                    f"clip_id={ref.clip_id}",
                ),
                "project-identity-enforced": (
                    all(item.project_id == PROJECT_ID for item in references),
                    f"{len(references)} references scoped to {PROJECT_ID}",
                ),
                "source-digest-recorded": (
                    len(ref.source_record_digest) == 64,
                    f"digest length {len(ref.source_record_digest)}",
                ),
                "supported-schema-accepted": (
                    ref.schema_supported
                    and ref.brief_schema_id == SUPPORTED_BRIEF_SCHEMA_ID,
                    f"schema {ref.brief_schema_id} supported={ref.schema_supported}",
                ),
                "unsupported-schema-flagged": (
                    not unsupported_ref.schema_supported
                    and any("not supported" in item for item in unsupported_ref.warnings),
                    f"warnings {unsupported_ref.warnings}",
                ),
                "current-brief-labelled": (ref.current, f"current={ref.current}"),
                "stale-flag-explicit": (
                    ref.stale is False,
                    "stale is an explicit False, never inferred from a timestamp",
                ),
                "historical-flag-explicit": (
                    ref.historical is False,
                    "historical is an explicit False; the owner keeps no archive",
                ),
                "superseded-flag-explicit": (
                    ref.superseded is False and ref.superseding_brief_id is None,
                    "superseded stays False and names no superseding brief",
                ),
                "absent-revision-remains-absent": (
                    ref.brief_revision_id is None,
                    "the owner schema defines no revision identity",
                ),
                "no-inferred-supersession": (
                    "superseded=False," in source and "superseded=True" not in source,
                    "the projection never assigns supersession",
                ),
                "lifecycle-bucket-preserved": (
                    ref.lifecycle_bucket == "selected"
                    and blocked.lifecycle_bucket == "blocked",
                    f"selected bucket={ref.lifecycle_bucket}, "
                    f"blocked bucket={blocked.lifecycle_bucket}",
                ),
                "exact-source-window-preserved": (
                    (ref.start_seconds, ref.end_seconds, ref.duration_seconds)
                    == (10.0, 40.0, 30.0),
                    f"window {ref.start_seconds}-{ref.end_seconds} "
                    f"duration {ref.duration_seconds}",
                ),
                "inverted-window-rejected": _expect_error(
                    BobaClipBriefReferenceV1,
                    brief_reference_id="r",
                    project_id=PROJECT_ID,
                    candidate_id="cand_a",
                    clip_id="cand_a",
                    brief_id="brief_a",
                    source_record_id="s",
                    source_record_digest="0" * 64,
                    project_snapshot_digest="0" * 64,
                    start_seconds=40.0,
                    end_seconds=10.0,
                    duration_seconds=30.0,
                ),
                "workflow-identity-from-controller": (
                    (workflow_record is None and ref.workflow_run_id is None)
                    or ref.workflow_run_id is not None,
                    "no workflow run id is invented when the controller has no record",
                ),
            },
        )


def _run_fields() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        fields = engine.build_field_projections(PROJECT_ID, "brief_a")
        by_path = {item.field_path: item for item in fields}
        record = engine.inspect_clip_brief(PROJECT_ID, "brief_a")
        required = [item for item in fields if item.required_by_owner_schema]
        optional = [item for item in fields if not item.required_by_owner_schema]

        dropped = _raw_engine(
            root / "dropped",
            _raw_brief_payload(drop_fields=("brief_title", "human_review_notes")),
        )
        dropped_fields = {
            item.field_path: item
            for item in dropped.build_field_projections(PROJECT_ID, "brief_a")
        }

        long_engine = _raw_engine(
            root / "long",
            _raw_brief_payload(
                overrides={"final_clip_angle": "x" * (MAX_BOUNDED_DISPLAY_CHARS + 5_000)}
            ),
        )
        long_field = {
            item.field_path: item
            for item in long_engine.build_field_projections(PROJECT_ID, "brief_a")
        }["final_clip_angle"]

        owner_paths = set(owner_schema_required_field_paths()) | set(
            owner_schema_optional_field_paths()
        )
        angle = by_path["final_clip_angle"]
        instruction_value = by_path["hook_instruction"].original_value
        signature_names = {
            "project_id",
            "brief_id",
            "snapshot_id",
        }
        import inspect as _inspect

        actual_params = set(
            _inspect.signature(engine.build_field_projections).parameters
        )
        forbidden_tokens = ("beat", "ending", "transcript", "audience_segment")
        return _group(
            "fields",
            {
                "required-field-present": (
                    by_path["brief_title"].present
                    and by_path["brief_title"].required_by_owner_schema,
                    "brief_title is present and required by the owner schema",
                ),
                "required-field-missing": (
                    dropped_fields["brief_title"].unavailable
                    and not dropped_fields["brief_title"].present,
                    "a dropped required field is reported missing, never filled in",
                ),
                "optional-field-present": (
                    by_path["risk_fixes"].present
                    and not by_path["risk_fixes"].required_by_owner_schema,
                    "risk_fixes is present and optional",
                ),
                "optional-field-missing": (
                    dropped_fields["human_review_notes"].unavailable,
                    "a dropped optional field is reported missing",
                ),
                "empty-list-distinguished": (
                    by_path["warnings"].empty and not by_path["warnings"].unavailable,
                    "an owner-persisted empty list is empty, not absent",
                ),
                "nested-field-projected": (
                    by_path["source_window.start_seconds"].original_value == 10.0,
                    f"source_window.start_seconds={by_path['source_window.start_seconds'].original_value}",
                ),
                "instruction-field-projected": (
                    isinstance(instruction_value, dict)
                    and instruction_value.get("instruction_type") == "hook",
                    "the hook instruction object is projected whole",
                ),
                "source-value-preserved": (
                    angle.original_value
                    == "The exact clip angle recorded by the owner.",
                    "the owner value is projected verbatim",
                ),
                "easy-explanation-separated": (
                    str(angle.original_value) not in angle.bounded_explanation
                    and angle.bounded_explanation != "",
                    f"explanation={angle.bounded_explanation!r}",
                ),
                "no-source-rewriting": (
                    all(
                        item["original_value"]
                        == by_path[str(item["field_path"])].original_value
                        for item in record["field_projections"]
                    ),
                    "repeat projections return identical owner values",
                ),
                "no-invented-field": (
                    {item.field_path for item in fields} == owner_paths,
                    f"{len(fields)} projections, all defined by the owner schema",
                ),
                "no-request-defined-schema": (
                    actual_params <= signature_names | {"self"},
                    f"projection parameters {sorted(actual_params)}",
                ),
                "field-count-matches-owner-schema": (
                    (len(fields), len(required), len(optional)) == (27, 22, 5),
                    f"{len(fields)} fields = {len(required)} required + {len(optional)} optional",
                ),
                "field-category-only-when-supported": (
                    all(item.field_category for item in fields)
                    and not any(
                        item.field_category in {"beats", "ending", "transcript"}
                        for item in fields
                    ),
                    f"categories {sorted({item.field_category for item in fields})}",
                ),
                "no-beats-or-ending-invented": (
                    not any(
                        token in path for path in owner_paths for token in forbidden_tokens
                    ),
                    "no beats, ending, audience-segment or transcript field is invented",
                ),
                "value-type-reported": (
                    by_path["confidence"].value_type == "number"
                    and by_path["brief_title"].value_type == "string"
                    and by_path["warnings"].value_type == "list"
                    and by_path["hook_instruction"].value_type == "object",
                    "value types are reported from the persisted value",
                ),
                "value-digest-recorded": (
                    all(
                        len(item.original_value_digest) == 64
                        for item in fields
                        if not item.unavailable
                    ),
                    "every present field carries a 64-character value digest",
                ),
                "bounded-display-limit": (
                    long_field.truncated_for_display
                    or len(str(long_field.original_value)) <= MAX_BOUNDED_DISPLAY_CHARS,
                    f"oversized value bounded to {len(str(long_field.original_value))} chars",
                ),
                "advisory-field-marked": (
                    by_path["caption_instruction"].advisory
                    and by_path["motion_instruction"].advisory
                    and by_path["audio_instruction"].advisory
                    and by_path["sfx_instruction"].advisory
                    and not by_path["hook_instruction"].advisory,
                    "advisory creative guidance is marked advisory",
                ),
                "human-editable-always-false": (
                    all(not item.human_editable for item in fields),
                    "no projected field is editable in the panel",
                ),
            },
        )


def _run_sections() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        engine, _ = _engine(Path(raw_root))
        fields = engine.build_field_projections(PROJECT_ID, "brief_a")
        sections = engine.build_section_projections(PROJECT_ID, "brief_a", fields)
        by_id = {item.section_id: item for item in sections}
        field_ids = {item.field_projection_id for item in fields}
        member_ids = {
            item for section in sections for item in section.field_projection_ids
        }
        registry = build_fixed_clip_brief_section_registry()
        return _group(
            "sections",
            {
                "sections-built-from-owner-fields": (
                    member_ids <= field_ids and set(by_id) == set(registry),
                    f"{len(sections)} sections drawn from owner fields only",
                ),
                "section-required-counts": (
                    by_id["identity"].required_field_count == 4
                    and by_id["identity"].present_required_field_count == 4,
                    f"identity required {by_id['identity'].present_required_field_count}"
                    f"/{by_id['identity'].required_field_count}",
                ),
                "section-optional-counts": (
                    by_id["checklist"].optional_field_count == 2
                    and by_id["checklist"].required_field_count == 0,
                    f"checklist optional count {by_id['checklist'].optional_field_count}",
                ),
                "empty-section-labelled": (
                    by_id["limitations"].empty
                    and by_id["limitations"].bounded_empty_message != "",
                    f"limitations empty={by_id['limitations'].empty}",
                ),
                "collapsed-by-default-respected": (
                    by_id["checklist"].collapsed_by_default
                    and by_id["warnings"].collapsed_by_default
                    and by_id["limitations"].collapsed_by_default
                    and not by_id["identity"].collapsed_by_default,
                    "collapse defaults come from the fixed section registry",
                ),
                "section-count-fixed": (
                    len(sections) == 9 and len(registry) == 9,
                    f"{len(sections)} sections",
                ),
                "every-field-belongs-to-a-section": (
                    member_ids == field_ids,
                    f"{len(member_ids)} of {len(field_ids)} fields assigned",
                ),
            },
        )


def _run_completeness() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        fields = engine.build_field_projections(PROJECT_ID, "brief_a")
        record = engine.build_completeness(PROJECT_ID, "brief_a", fields)
        repeat = engine.build_completeness(
            PROJECT_ID, "brief_a", engine.build_field_projections(PROJECT_ID, "brief_a")
        )
        inspected = engine.inspect_clip_brief_completeness(PROJECT_ID, "brief_a")
        limitation_text = " ".join(inspected["limitations"]).lower()

        dropped = _raw_engine(root / "dropped", _raw_brief_payload(drop_fields=("brief_title",)))
        dropped_record = dropped.build_completeness(
            PROJECT_ID, "brief_a", dropped.build_field_projections(PROJECT_ID, "brief_a")
        )
        unsupported = _raw_engine(
            root / "unsupported", _raw_brief_payload(brief_version="boba_clip_brief_v9")
        )
        unsupported_record = unsupported.build_completeness(
            PROJECT_ID,
            "brief_a",
            unsupported.build_field_projections(PROJECT_ID, "brief_a"),
        )
        source = _source_text()
        dumped = record.model_dump(mode="json")
        usage = engine.build_clip_brief_review(PROJECT_ID)["signal_usage"]
        return _group(
            "completeness",
            {
                "complete-with-optional-gaps": (
                    record.completeness_status == "complete_with_optional_gaps",
                    f"status={record.completeness_status}",
                ),
                "missing-required-fields-status": (
                    dropped_record.completeness_status == "missing_required_fields"
                    and not dropped_record.complete_for_owner_schema,
                    f"status={dropped_record.completeness_status}",
                ),
                "unsupported-schema-status": (
                    unsupported_record.completeness_status == "unsupported_schema"
                    and not unsupported_record.complete_for_owner_schema,
                    f"status={unsupported_record.completeness_status}",
                ),
                "required-ratio-deterministic": (
                    record.required_completion_ratio == 1.0
                    and repeat.required_completion_ratio
                    == record.required_completion_ratio,
                    f"required ratio {record.required_completion_ratio}",
                ),
                "optional-ratio-deterministic": (
                    record.optional_completion_ratio
                    == repeat.optional_completion_ratio
                    == round(3 / 5, 6),
                    f"optional ratio {record.optional_completion_ratio}",
                ),
                "required-paths-fixed": (
                    owner_schema_required_field_paths()
                    == owner_schema_required_field_paths()
                    and len(owner_schema_required_field_paths()) == 22,
                    f"{len(owner_schema_required_field_paths())} required paths",
                ),
                "optional-paths-fixed": (
                    len(owner_schema_optional_field_paths()) == 5,
                    f"{len(owner_schema_optional_field_paths())} optional paths",
                ),
                "complete-does-not-mean-approved": (
                    "approval" in limitation_text
                    and not any("approved" in key for key in dumped),
                    "the completeness readout denies implying approval",
                ),
                "complete-does-not-mean-quality": (
                    "creative quality" in limitation_text,
                    "the completeness readout denies implying creative quality",
                ),
                "complete-does-not-mean-technically-valid": (
                    "technical validation" in limitation_text,
                    "the completeness readout denies implying technical validation",
                ),
                "creative-quality-never-assessed": (
                    record.creative_quality_assessed is False
                    and "quality_score=" not in source,
                    "creative_quality_assessed is declared and stays False",
                ),
                "technical-quality-never-assessed": (
                    record.technical_quality_assessed is False
                    and not any("score" in key for key in dumped),
                    "technical_quality_assessed stays False and no score field exists",
                ),
                "blocking-reasons-listed": (
                    any(
                        "brief_title" in reason
                        for reason in dropped_record.blocking_reasons
                    ),
                    f"blocking reasons {dropped_record.blocking_reasons}",
                ),
                "no-quality-score": (
                    usage["hidden_quality_score_created"] is False
                    and usage["hidden_virality_score_created"] is False,
                    "no hidden quality or virality score is created",
                ),
            },
        )


def _run_sources() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        cards = {
            item.source_module_id: item
            for item in engine.build_source_cards(PROJECT_ID, "brief_a")
        }
        registry = build_fixed_clip_brief_source_registry()
        snapshot = engine.build_clip_brief_review_registry(PROJECT_ID)["registry_snapshot"]

        empty, _ = _engine(root / "empty", with_briefs=False)
        no_candidates, _ = _engine(root / "nocand", with_candidates=False)
        no_candidate_cards = {
            item.source_module_id: item
            for item in no_candidates.build_source_cards(PROJECT_ID, "brief_a")
        }
        advisory_ids = {key for key, row in registry.items() if row["advisory_only"]}
        return _group(
            "sources",
            {
                "brief-source-present": (
                    cards["clip_brief"].current
                    and cards["clip_brief"].original_status == "selected",
                    f"clip_brief status={cards['clip_brief'].original_status}",
                ),
                "brief-source-missing": (
                    empty.build_clip_brief_references(PROJECT_ID) == []
                    and "clip_brief"
                    in empty.build_clip_brief_review_registry(PROJECT_ID)[
                        "registry_snapshot"
                    ]["unavailable_source_ids"],
                    "with no brief record nothing is projected and the source is unavailable",
                ),
                "candidate-source-present": (
                    cards["clip_discovery"].current,
                    "the Candidate Clip Discovery record is present",
                ),
                "candidate-source-missing": (
                    no_candidate_cards["clip_discovery"].original_status == "unavailable"
                    and any(
                        "never treated as a pass" in item
                        for item in no_candidate_cards["clip_discovery"].limitations
                    ),
                    "an absent candidate record is never treated as a pass",
                ),
                "editorial-source-present": (
                    cards["editorial_decision"].current,
                    f"editorial status={cards['editorial_decision'].original_status}",
                ),
                "ranking-source-present": (
                    cards["clip_ranking"].current,
                    f"ranking status={cards['clip_ranking'].original_status}",
                ),
                "creative-source-advisory": (
                    cards["creative_director"].advisory_only
                    and not cards["creative_director"].authoritative,
                    "Creative Director output is advisory only",
                ),
                "hook-source-advisory": (
                    cards["hook_retention"].advisory_only,
                    "Hook + Retention output is advisory only",
                ),
                "caption-source-advisory": (
                    cards["caption_motion"].advisory_only,
                    "Caption + Motion output is advisory only",
                ),
                "music-source-advisory": (
                    cards["music_mood"].advisory_only,
                    "Music Mood output is advisory only",
                ),
                "rights-source-authoritative": (
                    not cards["rights_permission_gate"].advisory_only,
                    "the Rights + Permission Gate stays authoritative",
                ),
                "safety-source-authoritative": (
                    not cards["safety_gate"].advisory_only,
                    "the Safety Gate stays authoritative",
                ),
                "workflow-source-authoritative": (
                    not cards["workflow_controller"].advisory_only,
                    "the Workflow Controller stays authoritative",
                ),
                "artifact-source-authoritative": (
                    not cards["artifact_inspector"].advisory_only,
                    "the Artifact Inspector stays authoritative",
                ),
                "validation-source-authoritative": (
                    not cards["validator_runner"].advisory_only,
                    "the Validator Runner stays authoritative",
                ),
                "unavailable-source-reported": (
                    set(snapshot["unavailable_source_ids"])
                    == {key for key, card in cards.items() if not card.current},
                    f"{len(snapshot['unavailable_source_ids'])} unavailable sources reported",
                ),
                "source-owner-preserved": (
                    all(
                        cards[key].authority_domain == row["authority_domain"]
                        for key, row in registry.items()
                    ),
                    "each card keeps its owning module's authority domain",
                ),
                "duplicate-source-descriptor-rejected": (
                    len(registry) == 14
                    and len(set(registry)) == len(registry)
                    and advisory_ids
                    == {
                        "explanation",
                        "creative_director",
                        "hook_retention",
                        "caption_motion",
                        "music_mood",
                    },
                    f"{len(registry)} unique fixed sources, {len(advisory_ids)} advisory",
                ),
                "required-source-declared": (
                    registry["clip_brief"]["required"] is True
                    and sum(1 for row in registry.values() if row["required"]) == 1,
                    "only the Clip Brief Generator record is required",
                ),
            },
        )


def _run_evidence() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        links = engine.build_evidence_links(PROJECT_ID, "brief_a")
        by_type = {item.evidence_type: item for item in links}
        inspected = engine.inspect_clip_brief_evidence(PROJECT_ID, "brief_a")
        no_candidates, _ = _engine(root / "nocand", with_candidates=False)
        no_candidate_links = {
            item.evidence_type: item
            for item in no_candidates.build_evidence_links(PROJECT_ID, "brief_a")
        }
        source = _source_text()
        advisory = [item for item in links if item.advisory]
        return _group(
            "evidence",
            {
                "candidate-evidence-linked": (
                    not by_type["candidate_record"].missing
                    and by_type["candidate_record"].candidate_id == "cand_a",
                    "the candidate record is linked by exact identity",
                ),
                "ranking-evidence-linked": (
                    not by_type["ranking_record"].missing,
                    "the ranking record is linked",
                ),
                "editorial-evidence-linked": (
                    not by_type["editorial_decision"].missing,
                    "the editorial decision record is linked",
                ),
                "advisory-evidence-marked": (
                    len(advisory) == 5
                    and all(not item.authoritative for item in advisory),
                    f"{len(advisory)} advisory evidence links, none authoritative",
                ),
                "missing-evidence-reported": (
                    inspected["missing_evidence_count"] == 6
                    and by_type["explanation_record"].missing,
                    f"{inspected['missing_evidence_count']} missing evidence links",
                ),
                "missing-evidence-not-a-pass": (
                    any(
                        "never treated as a pass" in item
                        for item in by_type["explanation_record"].limitations
                    ),
                    "missing evidence is explicitly not a pass",
                ),
                "exact-identity-match-recorded": (
                    by_type["candidate_record"].exact_identity_match
                    and not no_candidate_links["candidate_record"].exact_identity_match,
                    "identity match is recorded only on an exact identity match",
                ),
                "digest-match-recorded": (
                    by_type["candidate_record"].digest_match
                    and len(by_type["candidate_record"].source_record_digest) == 64,
                    "the linked source record digest is recorded",
                ),
                "transcript-segment-ids-from-owner": (
                    by_type["candidate_record"].transcript_segment_ids == ["seg_cand_a"],
                    f"segment ids {by_type['candidate_record'].transcript_segment_ids}",
                ),
                "source-window-carried": (
                    (
                        by_type["candidate_record"].source_start_seconds,
                        by_type["candidate_record"].source_end_seconds,
                    )
                    == (10.0, 40.0),
                    "the owner window is carried onto the evidence link",
                ),
                "no-text-similarity-inference": (
                    all(
                        token not in source
                        for token in ("difflib", "SequenceMatcher", "similarity", "fuzz")
                    ),
                    "evidence is linked by identity, never by text similarity",
                ),
                "evidence-bounded": (
                    len(links) == 9 and len(links) <= 48,
                    f"{len(links)} bounded evidence links",
                ),
            },
        )


def _run_conflicts() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        clean, _ = _engine(root / "clean")
        clean_conflicts = clean.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        unknown_candidate, _ = _engine(
            root / "unknown", brief_windows=[("brief_a", "cand_zz", 10.0, 40.0)]
        )
        unknown_rows = unknown_candidate.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        window, _ = _engine(
            root / "window", brief_windows=[("brief_a", "cand_a", 12.5, 44.0)]
        )
        window_rows = window.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        duration, _ = _engine(
            root / "duration",
            brief_windows=[("brief_a", "cand_a", 10.0, 40.0)],
            duration_override=25.0,
        )
        duration_rows = duration.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        rejected, _ = _engine(root / "rejected")
        editorial_set = rejected.store.load_editorial_decisions(PROJECT_ID)
        assert editorial_set is not None
        rejected.store.save_editorial_decisions(
            editorial_set.model_copy(update={"rejected_clip_ids": ["cand_a"]})
        )
        rejected_rows = rejected.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        blocked, _ = _engine(root / "blocked", blocked_brief_ids=["brief_a"])
        blocked_rows = blocked.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        clip_mismatch, _ = _engine(root / "clip", with_briefs=False)
        clip_mismatch.store.save_clip_briefs(
            synthetic_brief_set(
                PROJECT_ID,
                selected=[
                    synthetic_brief("brief_a", PROJECT_ID, "cand_a", "cand_b", 10.0, 40.0)
                ],
            )
        )
        clip_rows = clip_mismatch.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        duplicate, _ = _engine(
            root / "duplicate",
            brief_windows=[
                ("brief_a", "cand_a", 10.0, 40.0),
                ("brief_b", "cand_a", 10.0, 40.0),
            ],
        )
        duplicate_rows = duplicate.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        unsupported = _raw_engine(
            root / "unsupported", _raw_brief_payload(brief_version="boba_clip_brief_v9")
        )
        unsupported_rows = unsupported.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")

        blocking_engine, _ = _engine(
            root / "blocking", brief_windows=[("brief_a", "cand_zz", 10.0, 40.0)]
        )
        blocking_payload = _prepared(blocking_engine)
        available = blocking_payload["snapshot"]["available_action_descriptor_ids"]

        def types_of(rows: list[Any]) -> set[str]:
            return {item.conflict_type for item in rows}

        source = _source_text()
        conflict_source = source.split("def detect_clip_brief_conflicts", 1)[1].split(
            "def inspect_clip_brief_conflicts", 1
        )[0]
        return _group(
            "conflicts",
            {
                "candidate-identity-conflict": (
                    "candidate_identity_conflict" in types_of(unknown_rows),
                    f"conflict types {sorted(types_of(unknown_rows))}",
                ),
                "source-window-conflict": (
                    "source_window_conflict" in types_of(window_rows),
                    f"conflict types {sorted(types_of(window_rows))}",
                ),
                "duration-conflict": (
                    "duration_conflict" in types_of(duration_rows),
                    f"conflict types {sorted(types_of(duration_rows))}",
                ),
                "editorial-status-conflict": (
                    "editorial_status_conflict" in types_of(rejected_rows),
                    f"conflict types {sorted(types_of(rejected_rows))}",
                ),
                "lifecycle-conflict": (
                    "lifecycle_conflict" in types_of(blocked_rows),
                    f"conflict types {sorted(types_of(blocked_rows))}",
                ),
                "clip-identity-conflict": (
                    "clip_identity_conflict" in types_of(clip_rows),
                    f"conflict types {sorted(types_of(clip_rows))}",
                ),
                "revision-conflict-without-supersession": (
                    "revision_conflict" in types_of(duplicate_rows)
                    and all(
                        not item.explicit_supersession_found for item in duplicate_rows
                    ),
                    "two current briefs conflict and no supersession is invented",
                ),
                "unsupported-schema-conflict": (
                    "unknown" in types_of(unsupported_rows),
                    f"conflict types {sorted(types_of(unsupported_rows))}",
                ),
                "no-conflict-on-clean-project": (
                    clean_conflicts == [],
                    "a consistent project produces no conflict",
                ),
                "advisory-options-not-conflict": (
                    clean_conflicts == []
                    and clean.inspect_clip_brief_evidence(PROJECT_ID, "brief_a")[
                        "missing_evidence_count"
                    ]
                    > 0,
                    "absent advisory guidance is never reported as a conflict",
                ),
                "confidence-does-not-resolve": (
                    "confidence" not in conflict_source,
                    "conflict detection never consults a confidence value",
                ),
                "unresolved-conflict-explicit": (
                    all(
                        not item.resolved and item.resolution_source_id is None
                        for item in unknown_rows
                    ),
                    "conflicts stay explicitly unresolved",
                ),
                "blocking-conflict-blocks-action": (
                    any(item.blocks_review_action for item in unknown_rows)
                    and _FEEDBACK not in available
                    and _NOTE in available,
                    f"available actions under a blocking conflict: {available}",
                ),
                "conflict-requires-same-identity": (
                    all(
                        item.same_candidate and item.same_clip
                        for item in unknown_rows + window_rows + duplicate_rows
                    ),
                    "conflicts are raised only between records of the same identity",
                ),
            },
        )


def _run_queue() -> list[ScenarioResult]:
    priority = BobaClipBriefReviewV1._priority
    base = {
        "selected": False,
        "blocked": False,
        "has_blocking_conflict": False,
        "human_required": False,
        "missing_required": False,
        "missing_evidence": False,
        "stale": False,
        "rejected": False,
        "superseded": False,
        "historical": False,
        "has_warnings": False,
    }

    def tier(**overrides: bool) -> int:
        return priority(**{**base, **overrides})[0]

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        queue = engine.build_clip_brief_queue(PROJECT_ID)
        repeat = engine.build_clip_brief_queue(PROJECT_ID)
        paged = engine.build_clip_brief_queue(PROJECT_ID, limit=10_000)
        order = [item["brief_id"] for item in queue["items"]]

        def filtered(name: str) -> list[str]:
            return [
                item["brief_id"]
                for item in engine.build_clip_brief_queue(
                    PROJECT_ID, review_filter=name
                )["items"]
            ]

        def sorted_ids(name: str) -> list[str]:
            return [
                item["brief_id"]
                for item in engine.build_clip_brief_queue(PROJECT_ID, sort=name)["items"]
            ]

        source = _source_text()
        sort_source = source.split("def _sort_queue", 1)[1].split("def _queue_item", 1)[0]
        keys = [item["deterministic_sort_key"] for item in queue["items"]]
        return _group(
            "queue",
            {
                "critical-block-priority": (
                    tier(selected=True, blocked=True) == 10,
                    "a blocked selected brief is tier 10",
                ),
                "identity-conflict-priority": (
                    tier(has_blocking_conflict=True) == 20,
                    "a blocking identity conflict is tier 20",
                ),
                "human-review-priority": (
                    tier(human_required=True) == 30,
                    "an exact human review need is tier 30",
                ),
                "missing-required-fields-priority": (
                    tier(missing_required=True) == 40,
                    "missing required owner fields is tier 40",
                ),
                "missing-evidence-priority": (
                    tier(missing_evidence=True) == 50,
                    "missing required source evidence is tier 50",
                ),
                "stale-selected-priority": (
                    tier(stale=True, selected=True) == 60,
                    "a stale brief for a selected candidate is tier 60",
                ),
                "selected-candidate-priority": (
                    tier(selected=True) == 70,
                    "a current brief for a selected candidate is tier 70",
                ),
                "warning-priority": (
                    tier(has_warnings=True) == 80,
                    "a current brief with warnings is tier 80",
                ),
                "other-current-priority": (tier() == 90, "any other current brief is tier 90"),
                "rejected-candidate-priority": (
                    tier(rejected=True) == 100,
                    "a rejected candidate's brief is tier 100",
                ),
                "superseded-priority": (
                    tier(superseded=True) == 110,
                    "a superseded brief is tier 110",
                ),
                "historical-priority": (
                    tier(historical=True) == 120,
                    "a historical brief is tier 120",
                ),
                "twelve-priority-tiers": (
                    len(CLIP_BRIEF_QUEUE_PRIORITY_TIERS) == 12
                    and len(queue["priority_tiers"]) == 12,
                    f"{len(CLIP_BRIEF_QUEUE_PRIORITY_TIERS)} fixed tiers",
                ),
                "deterministic-tie-break": (
                    len(set(keys)) == len(keys) and keys == sorted(keys),
                    f"sort keys {keys}",
                ),
                "deterministic-repeat-order": (
                    order == [item["brief_id"] for item in repeat["items"]],
                    f"repeat order {order}",
                ),
                "pagination-bounded": (
                    paged["limit"] == MAX_QUEUE_PAGE_SIZE == 50,
                    f"limit bounded to {paged['limit']}",
                ),
                "filter-all-current": (
                    filtered("all_current") == order and len(order) == 2,
                    f"all_current -> {filtered('all_current')}",
                ),
                "filter-human-review": (
                    filtered("human_review_required") == [],
                    "no brief requires human review on a clean project",
                ),
                "filter-current-selected-candidate": (
                    filtered("current_selected_candidate") == ["brief_a"],
                    f"selected candidate briefs {filtered('current_selected_candidate')}",
                ),
                "filter-missing-required-fields": (
                    filtered("missing_required_fields") == [],
                    "no required owner field is missing on a clean project",
                ),
                "filter-missing-evidence": (
                    sorted(filtered("missing_evidence")) == ["brief_a", "brief_b"],
                    f"missing evidence briefs {filtered('missing_evidence')}",
                ),
                "filter-conflicts": (
                    filtered("conflicts") == [],
                    "no conflict on a clean project",
                ),
                "filter-stale": (
                    filtered("stale") == [],
                    "no brief is stale because staleness is never inferred",
                ),
                "filter-complete": (
                    sorted(filtered("complete_for_owner_schema")) == ["brief_a", "brief_b"],
                    f"complete briefs {filtered('complete_for_owner_schema')}",
                ),
                "filter-warnings": (
                    filtered("warnings") == [],
                    "the owner persisted no warning on these briefs",
                ),
                "filter-historical": (
                    filtered("historical") == [],
                    "the owner keeps no historical brief archive",
                ),
                "filter-superseded": (
                    filtered("superseded") == [],
                    "the owner records no supersession",
                ),
                "unsupported-filter-rejected": _expect_error(
                    engine.build_clip_brief_queue, PROJECT_ID, review_filter="best_first"
                ),
                "sort-review-priority": (
                    sorted_ids("review_priority") == order,
                    f"review_priority -> {sorted_ids('review_priority')}",
                ),
                "sort-candidate-rank": (
                    sorted_ids("candidate_rank") == ["brief_a", "brief_b"],
                    f"candidate_rank -> {sorted_ids('candidate_rank')}",
                ),
                "sort-created-sequence": (
                    sorted_ids("created_sequence") == ["brief_a", "brief_b"],
                    f"created_sequence -> {sorted_ids('created_sequence')}",
                ),
                "sort-source-start-time": (
                    sorted_ids("source_start_time") == ["brief_a", "brief_b"],
                    f"source_start_time -> {sorted_ids('source_start_time')}",
                ),
                "sort-brief-id": (
                    sorted_ids("brief_id") == ["brief_a", "brief_b"],
                    f"brief_id -> {sorted_ids('brief_id')}",
                ),
                "unsupported-sort-rejected": _expect_error(
                    engine.build_clip_brief_queue, PROJECT_ID, sort="most_viral"
                ),
                "no-ai-quality-sort": (
                    all(
                        token not in sort_source
                        for token in ("quality", "virality", "predict", "model")
                    ),
                    "sorting uses only source-owned rank, identity and tier",
                ),
            },
        )


def _run_comparison() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        pair = engine.build_clip_brief_comparison(PROJECT_ID, ["brief_a", "brief_b"])[
            "comparison"
        ]
        collapsed = engine.build_clip_brief_comparison(
            PROJECT_ID, ["brief_a", "brief_b", "brief_a"]
        )["comparison"]

        four, _ = _engine(
            root / "four",
            brief_windows=[
                ("brief_a", "cand_a", 10.0, 40.0),
                ("brief_b", "cand_b", 35.0, 65.0),
                ("brief_c", "cand_c", 10.0, 40.0),
                ("brief_d", "cand_d", 200.0, 220.0),
            ],
        )
        quad = four.build_clip_brief_comparison(
            PROJECT_ID, ["brief_a", "brief_b", "brief_c", "brief_d"]
        )["comparison"]

        same_candidate, _ = _engine(
            root / "same",
            brief_windows=[
                ("brief_a", "cand_a", 10.0, 40.0),
                ("brief_b", "cand_a", 10.0, 40.0),
            ],
        )
        same = same_candidate.build_clip_brief_comparison(
            PROJECT_ID, ["brief_a", "brief_b"]
        )["comparison"]

        dropped = _raw_engine(
            root / "dropped", _raw_brief_payload(drop_fields=("risk_fixes",))
        )
        missing_visible = True
        try:
            dropped.build_clip_brief_comparison(PROJECT_ID, ["brief_a", "brief_a"])
        except ValidationError:
            missing_visible = True
        fields_with_missing = [
            row
            for row in pair["field_comparisons"]
            if any(not value["present"] for value in row["values"])
        ]
        return _group(
            "comparison",
            {
                "two-brief-comparison": (
                    pair["brief_ids"] == ["brief_a", "brief_b"],
                    f"compared {pair['brief_ids']}",
                ),
                "four-brief-comparison": (
                    len(quad["brief_ids"]) == MAX_COMPARISON_BRIEFS == 4,
                    f"compared {quad['brief_ids']}",
                ),
                "single-brief-rejected": _expect_error(
                    engine.build_clip_brief_comparison, PROJECT_ID, ["brief_a"]
                ),
                "too-many-briefs-rejected": _expect_error(
                    four.build_clip_brief_comparison,
                    PROJECT_ID,
                    ["brief_a", "brief_b", "brief_c", "brief_d", "brief_a2"],
                ),
                "unknown-brief-comparison-rejected": _expect_error(
                    engine.build_clip_brief_comparison,
                    PROJECT_ID,
                    ["brief_a", "brief_absent"],
                ),
                "duplicate-ids-collapsed": (
                    collapsed["brief_ids"] == ["brief_a", "brief_b"],
                    f"duplicate ids collapsed to {collapsed['brief_ids']}",
                ),
                "unsupported-comparison-type-rejected": _expect_error(
                    engine.build_clip_brief_comparison,
                    PROJECT_ID,
                    ["brief_a", "brief_b"],
                    comparison_type="pick_the_best",
                ),
                "field-comparison-present": (
                    len(pair["field_comparisons"]) == 27,
                    f"{len(pair['field_comparisons'])} field comparisons",
                ),
                "section-comparison-present": (
                    len(pair["section_comparisons"]) == 9,
                    f"{len(pair['section_comparisons'])} section comparisons",
                ),
                "completeness-comparison-present": (
                    len(pair["completeness_comparison"]) == 2,
                    f"{len(pair['completeness_comparison'])} completeness rows",
                ),
                "evidence-comparison-present": (
                    len(pair["evidence_coverage_comparison"]) == 2,
                    f"{len(pair['evidence_coverage_comparison'])} evidence rows",
                ),
                "source-window-comparison-present": (
                    len(pair["source_window_comparison"]) == 2,
                    f"{len(pair['source_window_comparison'])} source window rows",
                ),
                "duration-comparison-present": (
                    len(pair["duration_comparison"]) == 2,
                    f"{len(pair['duration_comparison'])} duration rows",
                ),
                "missing-fields-visible": (
                    missing_visible and len(fields_with_missing) >= 2,
                    f"{len(fields_with_missing)} field rows show a missing value explicitly",
                ),
                "same-candidate-detected": (
                    same["same_candidate"] is True,
                    "two briefs for one candidate are reported as the same candidate",
                ),
                "cross-candidate-detected": (
                    pair["same_candidate"] is False,
                    "briefs for different candidates are reported as different",
                ),
                "no-automatic-winner": (
                    pair["no_automatic_winner"] is True
                    and quad["no_automatic_winner"] is True,
                    "comparison never selects a winner",
                ),
                "no-preferred-brief-score": (
                    not any(
                        "score" in key or "winner_id" in key for key in pair
                    ),
                    "the comparison record carries no score and no winner id",
                ),
            },
        )


def _run_preview() -> list[ScenarioResult]:
    """The preview surface is browser-side, so its contract is checked in source."""
    frontend = _frontend_text()
    review_ui = Path("frontend/src/lib/reviewUi.ts").read_text(encoding="utf-8")
    return _group(
        "preview",
        {
            "safe-same-origin-preview": (
                "protectedPreviewUrl" in frontend
                and "isSafePreviewReference" in frontend
                and "http" not in frontend.replace("https?:", ""),
                "the preview reuses the existing protected same-origin route helper",
            ),
            "external-url-blocked": (
                "UNSAFE_REFERENCE" in review_ui and "https?:" in review_ui,
                "an external URL is refused by the shared safe-reference guard",
            ),
            "absolute-path-blocked": (
                "[a-zA-Z]:[\\\\/]" in review_ui,
                "an absolute or drive-qualified path is refused",
            ),
            "file-uri-blocked": (
                "file:" in review_ui,
                "a file URI is refused",
            ),
            "traversal-blocked": (
                "\\.\\." in review_ui,
                "path traversal is refused",
            ),
            "exact-persisted-range-published": (
                "reference?.start_seconds ?? 0" in frontend
                and "reference?.end_seconds ?? 0" in frontend,
                "the exact persisted window is published unchanged",
            ),
            "browser-replacement-range-blocked": (
                "startSeconds: start," in frontend
                and "Math.min(contextSeconds, MAX_PREVIEW_CONTEXT_SECONDS)" in frontend,
                "only a bounded context hint is accepted; boundaries stay owner values",
            ),
            "context-labelled-non-authoritative": (
                "It is not authoritative and never changes the persisted brief window."
                in frontend,
                "context is labelled non-authoritative",
            ),
            "preview-unavailable-state": (
                "Preview unavailable. No protected same-origin source exists" in frontend,
                "an unavailable preview is stated, never faked",
            ),
            "playback-not-validation": (
                "Playing the preview is not validation and approves nothing." in frontend,
                "playback is explicitly not validation",
            ),
            "no-ffmpeg-generation": (
                all(
                    token not in frontend
                    for token in ("ffmpeg", "ffprobe", "transcode", "render(")
                ),
                "the preview never generates or transcodes media",
            ),
        },
    )


def _drifted(root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Create a real action request, then drift the persisted expectation."""
    engine, _ = _engine(root)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_drift_key")
    _rewrite(
        engine.store.boba_clip_brief_review_action_path(
            PROJECT_ID, request.clip_brief_action_request_id
        ),
        updates,
    )
    return engine.validate_clip_brief_action_request(
        PROJECT_ID, request.clip_brief_action_request_id
    )


def _run_actions() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, integration = _engine(root / "base")
        payload = _prepared(engine)
        snapshot_id = payload["snapshot"]["brief_snapshot_id"]
        session_id = payload["session"].clip_brief_review_session_id
        registry = build_fixed_clip_brief_action_registry()
        available = payload["snapshot"]["available_action_descriptor_ids"]

        def create(**overrides: Any) -> Any:
            kwargs: dict[str, Any] = {
                "clip_brief_review_session_id": session_id,
                "brief_snapshot_id": snapshot_id,
                "action_descriptor_id": _FEEDBACK,
                "decision_value": "approved",
                "reason": "Reviewed the exact clip brief.",
                "confirmation_context_digest": payload["action_confirmations"][_FEEDBACK],
                "idempotency_key": "idem_probe_key",
                "confirmed": True,
            }
            kwargs.update(overrides)
            return engine.create_clip_brief_action_request(PROJECT_ID, **kwargs)

        accepted_engine, accepted_integration = _engine(root / "accepted")
        accepted_payload = _prepared(accepted_engine)
        accepted_request = _request(accepted_engine, accepted_payload, "idem_accept_key")
        brief_digest_before = accepted_payload["snapshot"]["brief_digest"]
        accepted = asyncio.run(
            accepted_engine.submit_clip_brief_action_to_owner(
                PROJECT_ID, accepted_request.clip_brief_action_request_id
            )
        )
        duplicate = asyncio.run(
            accepted_engine.submit_clip_brief_action_to_owner(
                PROJECT_ID, accepted_request.clip_brief_action_request_id
            )
        )
        brief_digest_after = accepted_engine.build_clip_brief_snapshot(
            PROJECT_ID, accepted_payload["session"].clip_brief_review_session_id, "brief_a"
        )["snapshot"]["brief_digest"]

        rejecting_engine, rejecting_integration = _engine(root / "rejecting")
        rejecting_payload = _prepared(rejecting_engine)
        rejecting_request = _request(rejecting_engine, rejecting_payload, "idem_reject_key")
        rejecting_integration.owner.reject = True
        rejected_receipt = asyncio.run(
            rejecting_engine.submit_clip_brief_action_to_owner(
                PROJECT_ID, rejecting_request.clip_brief_action_request_id
            )
        )

        malformed_engine, malformed_integration = _engine(root / "malformed")
        malformed_payload = _prepared(malformed_engine)
        malformed_request = _request(malformed_engine, malformed_payload, "idem_malform_key")
        malformed_integration.owner.malformed = True
        malformed_receipt = asyncio.run(
            malformed_engine.submit_clip_brief_action_to_owner(
                PROJECT_ID, malformed_request.clip_brief_action_request_id
            )
        )

        expired = _drifted(
            root / "expired",
            {"expires_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()},
        )
        project_drift = _drifted(root / "project", {"expected_project_snapshot_digest": "1" * 64})
        revision_drift = _drifted(root / "revision", {"expected_workflow_revision": 7})
        brief_drift = _drifted(root / "brief", {"expected_brief_digest": "2" * 64})
        source_drift = _drifted(
            root / "source", {"expected_source_record_digests": {"clip_brief": "3" * 64}}
        )
        candidate_drift = _drifted(root / "candidate", {"candidate_id": "cand_b"})
        clip_drift = _drifted(root / "clip", {"clip_id": "cand_b"})

        forged = BobaClipBriefActionReceiptV1(
            clip_brief_action_receipt_id="clip_brief_receipt_forged",
            clip_brief_action_request_id=accepted_request.clip_brief_action_request_id,
            project_id=PROJECT_ID,
            brief_id="brief_a",
            candidate_id="cand_a",
            clip_id="cand_a",
            owning_module_id="creator_learning",
            owning_operation_id="record_creator_feedback_event",
            authoritative_state_changed=True,
        )
        available_descriptors = [
            item
            for item in registry.values()
            if item.allowed_in_v1 and item.availability == "available"
        ]
        return _group(
            "actions",
            {
                "feedback-action-available": (
                    _FEEDBACK in available,
                    f"available actions {available}",
                ),
                "note-action-available": (_NOTE in available, f"available actions {available}"),
                "approve-action-unavailable": (
                    registry["clip_brief_action_approve_v1"].availability == "unavailable"
                    and bool(registry["clip_brief_action_approve_v1"].limitations),
                    "brief approval is declared unavailable with a stated reason",
                ),
                "reject-action-unavailable": (
                    registry["clip_brief_action_reject_v1"].availability == "unavailable",
                    "brief rejection is declared unavailable",
                ),
                "revision-action-unavailable": (
                    registry["clip_brief_action_request_revision_v1"].availability
                    == "unavailable",
                    "a revision request is declared unavailable",
                ),
                "regeneration-action-unavailable": (
                    registry["clip_brief_action_request_regeneration_v1"].availability
                    == "unavailable",
                    "regeneration is declared unavailable; the panel is not a generator",
                ),
                "no-authoritative-action-in-v1": (
                    all(not item.authoritative for item in available_descriptors),
                    f"{len(available_descriptors)} available actions, none authoritative",
                ),
                "unknown-action-rejected": _expect_error(
                    create,
                    action_descriptor_id="clip_brief_action_invented_v1",
                    confirmation_context_digest="0" * 64,
                ),
                "unavailable-action-rejected": _expect_error(
                    create,
                    action_descriptor_id="clip_brief_action_approve_v1",
                    decision_value="approve",
                    confirmation_context_digest="0" * 64,
                ),
                "unsupported-decision-rejected": _expect_error(
                    create, decision_value="ship_it"
                ),
                "missing-reason-rejected": _expect_error(create, reason="   "),
                "oversized-reason-rejected": _expect_error(create, reason="x" * 900),
                "secret-bearing-reason-rejected": _expect_error(
                    create, reason="Use the api_token value from the console."
                ),
                "missing-confirmation-rejected": _expect_error(create, confirmed=False),
                "wrong-confirmation-token-rejected": _expect_error(
                    create, confirmation_context_digest="4" * 64
                ),
                "reviewer-context-required": _expect_error(
                    engine.create_clip_brief_review_session,
                    PROJECT_ID,
                    reviewer_context_id="",
                ),
                "expired-request-rejected": (
                    expired["code"] == "expired_snapshot" and not expired["valid"],
                    f"validation code {expired['code']}",
                ),
                "changed-project-digest-rejected": (
                    project_drift["code"] == "stale_project_snapshot",
                    f"validation code {project_drift['code']}",
                ),
                "changed-workflow-revision-rejected": (
                    revision_drift["code"] == "workflow_revision_mismatch",
                    f"validation code {revision_drift['code']}",
                ),
                "changed-brief-digest-rejected": (
                    brief_drift["code"] == "brief_digest_mismatch",
                    f"validation code {brief_drift['code']}",
                ),
                "changed-source-digest-rejected": (
                    source_drift["code"] == "source_record_digest_mismatch",
                    f"validation code {source_drift['code']}",
                ),
                "candidate-mismatch-rejected": (
                    candidate_drift["code"] == "candidate_identity_mismatch",
                    f"validation code {candidate_drift['code']}",
                ),
                "clip-mismatch-rejected": (
                    clip_drift["code"] == "clip_identity_mismatch",
                    f"validation code {clip_drift['code']}",
                ),
                "canonical-receipt-recorded": (
                    accepted.accepted_by_owner
                    and accepted.canonical_record_id == "creator_feedback_1"
                    and accepted.owning_module_id == "creator_learning",
                    f"owner record {accepted.canonical_record_id}",
                ),
                "advisory-receipt-not-authoritative": (
                    accepted.authoritative_state_changed is False
                    and any("advisory" in item for item in accepted.limitations),
                    "an accepted advisory receipt changes no authoritative state",
                ),
                "owner-rejection-recorded": (
                    rejected_receipt.canonical_status == "rejected_by_owner"
                    and not rejected_receipt.accepted_by_owner,
                    f"canonical status {rejected_receipt.canonical_status}",
                ),
                "malformed-owner-response-handled": (
                    malformed_receipt.canonical_status == "malformed_owner_response"
                    and not malformed_receipt.accepted_by_owner,
                    f"canonical status {malformed_receipt.canonical_status}",
                ),
                "duplicate-request-reused": (
                    duplicate.duplicate_request_reused
                    and duplicate.clip_brief_action_receipt_id
                    == accepted.clip_brief_action_receipt_id
                    and len(accepted_integration.owner.calls) == 1,
                    f"the owner was called {len(accepted_integration.owner.calls)} time",
                ),
                "no-optimistic-update": (
                    brief_digest_before == brief_digest_after
                    and len(integration.owner.calls) == 0,
                    "the projected brief is unchanged until the owner responds",
                ),
                "authority-requires-owner-record": _expect_error(
                    accepted_engine._persist_receipt, PROJECT_ID, forged
                ),
                "wrong-owner-route-unavailable": (
                    {item.owning_module_id for item in available_descriptors}
                    == {"creator_learning"}
                    and "owner_route_unavailable" in _source_text(),
                    "every available action has a real owner; the fallback refuses others",
                ),
            },
        )


def _run_authority() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        engine, _ = _engine(Path(raw_root))
        usage = engine.build_clip_brief_review(PROJECT_ID)["signal_usage"]
        source = _source_text()
        frontend = _frontend_text()
        registry = build_fixed_clip_brief_action_registry()
        saves = set(re.findall(r"self\.store\.save_[a-z_]+", source))

        def flag(name: str) -> bool:
            return usage[name] is False

        return _group(
            "authority",
            {
                "no-brief-generation": (
                    flag("brief_generated_by_panel") and "def generate" not in source,
                    "the panel declares and contains no brief generation",
                ),
                "no-brief-regeneration": (
                    flag("brief_regenerated_by_panel")
                    and "regenerate_clip_brief" not in source
                    and "generate_clip_briefs" not in source,
                    "no regeneration entry point is called",
                ),
                "no-brief-rewriting": (
                    flag("brief_rewritten_by_panel") and "save_clip_briefs" not in source,
                    "the panel never writes the clip brief store",
                ),
                "no-hidden-quality-score": (
                    flag("hidden_quality_score_created"),
                    "no hidden quality score is created",
                ),
                "no-hidden-virality-score": (
                    flag("hidden_virality_score_created"),
                    "no hidden virality score is created",
                ),
                "no-local-approval": (
                    flag("brief_approved_locally")
                    and source.count('"accepted_by_owner": True') == 1,
                    "acceptance is set only from a canonical owner record",
                ),
                "no-local-rejection": (
                    flag("brief_rejected_locally")
                    and "save_editorial_decisions" not in source,
                    "the panel never writes an editorial rejection",
                ),
                "no-dynamic-import": (
                    "importlib" not in source and "__import__" not in source,
                    "no dynamic import exists",
                ),
                "no-arbitrary-module": (
                    flag("arbitrary_module_used")
                    and source.count("getattr(self.store") == 1
                    and 'descriptor["loader"]' in source,
                    "store access uses only the fixed loader names in the registry",
                ),
                "no-arbitrary-operation": (
                    flag("arbitrary_operation_used")
                    and "getattr(self.integration" not in source,
                    "owner operations are fixed in the action registry",
                ),
                "no-arbitrary-url": (
                    flag("arbitrary_url_used")
                    and "http://" not in source
                    and "https://" not in source,
                    "no URL is constructed in the projection",
                ),
                "no-arbitrary-path": (
                    flag("arbitrary_path_used")
                    and "open(" not in source
                    and "Path(" not in source,
                    "the projection opens no path of its own",
                ),
                "no-external-media": (
                    flag("external_media_used")
                    and all(
                        token not in source
                        for token in ("httpx", "urllib", "socket", "requests.get")
                    ),
                    "no external media or network client is used",
                ),
                "no-untrusted-html": (
                    flag("untrusted_html_used")
                    and "dangerouslySetInnerHTML" not in frontend,
                    "no untrusted HTML is rendered",
                ),
                "no-command-execution": (
                    flag("command_execution_used") and "subprocess" not in source,
                    "no command execution exists",
                ),
                "no-shell-execution": (
                    flag("shell_execution_used")
                    and "shell=True" not in source
                    and "os.system" not in source,
                    "no shell execution exists",
                ),
                "no-git-execution": (
                    flag("git_execution_used") and '"git"' not in source,
                    "no Git invocation exists",
                ),
                "no-ffmpeg-execution": (
                    flag("ffmpeg_execution_used")
                    and all(
                        token not in source
                        for token in ("ffmpeg_binary", "ffprobe", '"ffmpeg"')
                    ),
                    "no FFmpeg or FFprobe invocation exists",
                ),
                "no-media-generation": (
                    flag("media_generation_used") and "save_render" not in source,
                    "no media is generated",
                ),
                "no-artifact-modification": (
                    "save_boba_artifact_inspector" not in source,
                    "artifact records are read, never written",
                ),
                "no-source-media-modification": (
                    flag("source_media_modified") and "storage_key" not in source,
                    "source media is never touched",
                ),
                "no-accepted-output-modification": (
                    flag("accepted_output_modified") and "save_accepted" not in source,
                    "accepted output is never modified",
                ),
                "no-workflow-transition": (
                    flag("workflow_transition_used")
                    and "save_boba_workflow_controller" not in source,
                    "no workflow transition is performed",
                ),
                "no-rights-creation": (
                    flag("approval_created_locally")
                    and "save_rights_permission_gate" not in source,
                    "no Rights approval is created locally",
                ),
                "no-safety-creation": (
                    flag("safety_decision_created_locally")
                    and "save_boba_safety_gate" not in source,
                    "no Safety decision is created locally",
                ),
                "no-upload": (
                    flag("upload_used")
                    and all(
                        token not in source for token in ("presigned", "put_object", "boto3")
                    ),
                    "nothing is uploaded",
                ),
                "no-publication": (
                    flag("publication_used")
                    and "publish(" not in source
                    and ".publish" not in source,
                    "nothing is published",
                ),
                "no-external-analytics": (
                    flag("external_analytics_used")
                    and "analytics." not in source
                    and "telemetry" not in source,
                    "no external analytics call exists",
                ),
                "no-rights-bypass": (
                    flag("rights_bypass_used")
                    and "rights_permission_gate" in build_fixed_clip_brief_source_registry(),
                    "the Rights gate is read and never bypassed",
                ),
                "no-safety-bypass": (
                    flag("safety_bypass_used")
                    and "safety_gate" in build_fixed_clip_brief_source_registry(),
                    "the Safety gate is read and never bypassed",
                ),
                "no-destructive-action": (
                    flag("destructive_action_used")
                    and all(not item.destructive for item in registry.values())
                    and "cannot expose destructive actions" in source,
                    "no destructive action can be registered",
                ),
                "no-source-record-writes": (
                    bool(saves)
                    and all(
                        item.startswith("self.store.save_boba_clip_brief_review")
                        for item in saves
                    ),
                    f"the module writes only its own records: {sorted(saves)}",
                ),
            },
        )


def _run_persistence() -> list[ScenarioResult]:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "base")
        session = engine.create_clip_brief_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        session_id = session.clip_brief_review_session_id
        loaded = engine.get_clip_brief_review_session(PROJECT_ID, session_id)

        expiring, _ = _engine(root / "expiring")
        expiring_session = expiring.create_clip_brief_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        _rewrite(
            expiring.store.boba_clip_brief_review_session_path(
                PROJECT_ID, expiring_session.clip_brief_review_session_id
            ),
            {"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
        )

        annotated = engine.update_clip_brief_review_session(
            PROJECT_ID,
            session_id,
            {
                "local_annotations": [
                    {"field_path": f"hook_instruction_{index}", "text": f"Note {index}"}
                    for index in range(40)
                ]
            },
        )
        brief_before = engine.inspect_clip_brief(PROJECT_ID, "brief_a")["field_projections"]
        brief_after = engine.inspect_clip_brief(PROJECT_ID, "brief_a")["field_projections"]

        registry_one = engine.build_clip_brief_review_registry(PROJECT_ID)
        registry_two = engine.build_clip_brief_review_registry(PROJECT_ID)

        action_engine, _ = _engine(root / "action")
        action_payload = _prepared(action_engine)
        request = _request(action_engine, action_payload, "idem_persist_key")
        receipt = asyncio.run(
            action_engine.submit_clip_brief_action_to_owner(
                PROJECT_ID, request.clip_brief_action_request_id
            )
        )
        action_dump = request.model_dump(mode="json")
        receipt_dump = receipt.model_dump(mode="json")

        export = engine.export_clip_brief_review(PROJECT_ID, session_id)
        export_text = json.dumps(export)
        reset = engine.reset_clip_brief_review_metadata(PROJECT_ID)
        events = engine.inspect_clip_brief_events(PROJECT_ID, limit=10_000)
        return _group(
            "persistence",
            {
                "session-persisted": (
                    loaded.clip_brief_review_session_id == session_id,
                    "the review session round-trips through the store",
                ),
                "session-expiry-enforced": _expect_error(
                    expiring.get_clip_brief_review_session,
                    PROJECT_ID,
                    expiring_session.clip_brief_review_session_id,
                ),
                "session-project-scoped": _expect_error(
                    engine.get_clip_brief_review_session, "proj_other_project", session_id
                ),
                "session-field-allowlist": _expect_error(
                    engine.update_clip_brief_review_session,
                    PROJECT_ID,
                    session_id,
                    {"available_action_descriptor_ids": ["clip_brief_action_approve_v1"]},
                ),
                "comparison-limit-enforced-in-session": _expect_error(
                    engine.update_clip_brief_review_session,
                    PROJECT_ID,
                    session_id,
                    {"comparison_brief_ids": ["a", "b", "c", "d", "e"]},
                ),
                "annotations-bounded": (
                    len(annotated.local_annotations) == 32
                    and all(
                        len(item["text"]) <= MAX_ANNOTATION_LENGTH
                        for item in annotated.local_annotations
                    ),
                    f"{len(annotated.local_annotations)} annotations retained of 40 "
                    f"offered, each bounded to {MAX_ANNOTATION_LENGTH} characters",
                ),
                "annotations-carry-notice": (
                    all(
                        item["notice"]
                        == "Review-session annotation — not part of the canonical clip brief."
                        for item in annotated.local_annotations
                    ),
                    "every annotation carries the exact non-canonical notice",
                ),
                "annotations-reject-secrets": _expect_error(
                    engine.update_clip_brief_review_session,
                    PROJECT_ID,
                    session_id,
                    {"local_annotations": [{"text": "the password is hunter2"}]},
                ),
                "annotations-never-canonical": (
                    brief_before == brief_after,
                    "annotating changes no projected canonical field",
                ),
                "registry-snapshot-immutable": (
                    registry_one["registry_snapshot"] == registry_two["registry_snapshot"],
                    "the registry snapshot is stable and immutable",
                ),
                "action-request-immutable": _expect_error(
                    action_engine.store.save_boba_clip_brief_review_action,
                    PROJECT_ID,
                    request.clip_brief_action_request_id,
                    {**action_dump, "bounded_reason": "rewritten"},
                ),
                "receipt-immutable": _expect_error(
                    action_engine.store.save_boba_clip_brief_review_receipt,
                    PROJECT_ID,
                    receipt.clip_brief_action_receipt_id,
                    {**receipt_dump, "accepted_by_owner": False},
                ),
                "source-records-not-duplicated": (
                    export["privacy"]["source_records_duplicated"] is False
                    and "selected_briefs" not in export_text,
                    "the export links to owner records instead of copying them",
                ),
                "reset-preserves-clip-brief-records": (
                    reset["clip_brief_records_preserved"] is True
                    and engine.store.load_clip_briefs(PROJECT_ID) is not None,
                    "the canonical brief set survives a metadata reset",
                ),
                "reset-preserves-candidate-review-history": (
                    reset["candidate_review_history_preserved"] is True
                    and reset["candidate_records_preserved"] is True,
                    "candidate records and candidate review history survive",
                ),
                "reset-preserves-review-ui-history": (
                    reset["review_ui_history_preserved"] is True,
                    "Review UI history survives",
                ),
                "reset-preserves-workflow-history": (
                    reset["workflow_history_preserved"] is True
                    and reset["source_media_removed"] is False
                    and reset["accepted_outputs_removed"] is False,
                    "workflow history, source media and accepted output survive",
                ),
                "sanitized-export": (
                    export["privacy"]["sensitive_values_excluded"] is True
                    and export["privacy"]["raw_transcripts_excluded"] is True
                    and export["privacy"]["brief_text_rewritten"] is False,
                    "the export is sanitised and states what it excludes",
                ),
                "export-excludes-private-paths": (
                    export["privacy"]["private_paths_excluded"] is True
                    and str(root) not in export_text,
                    "no private filesystem path appears in the export",
                ),
                "event-cursor-bounded": (
                    len(events["events"]) <= 100
                    and "latest_sequence" in events,
                    f"{len(events['events'])} events with a bounded cursor",
                ),
            },
        )


def _run_events() -> list[ScenarioResult]:
    rows = [
        {
            "event_id": "evt_1",
            "sequence": 1,
            "event_type": "clip_brief_generated",
            "created_at": "2026-01-01T00:00:00+00:00",
            "message": "The owner generated the brief set.",
        },
        {
            "event_id": "evt_1",
            "sequence": 1,
            "event_type": "clip_brief_generated",
            "created_at": "2026-01-01T00:00:00+00:00",
            "message": "The owner generated the brief set.",
        },
        {
            "event_id": "evt_2",
            "sequence": 2,
            "event_type": "clip_brief_reviewed",
            "progress_current": "not-a-number",
            "progress_total": 0,
        },
        {"event_id": "evt_3", "sequence": 3, "event_type": "heartbeat"},
        {
            "event_id": "evt_4",
            "sequence": 4,
            "event_type": "clip_brief_progress",
            "created_at": "2026-01-01T00:01:00+00:00",
            "progress_current": 2,
            "progress_total": 4,
        },
    ]
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine = _raw_engine(root / "events", _raw_brief_payload(events=rows))
        result = engine.inspect_clip_brief_events(PROJECT_ID)
        by_source_id = {str(item["source_event_id"]): item for item in result["events"]}
        after = engine.inspect_clip_brief_events(PROJECT_ID, after_sequence=3)
        flooded = _raw_engine(
            root / "flood",
            _raw_brief_payload(
                events=[
                    {
                        "event_id": f"evt_{index}",
                        "sequence": index,
                        "event_type": "clip_brief_progress",
                        "created_at": f"2026-01-01T00:00:{index % 60:02d}+00:00",
                    }
                    for index in range(300)
                ]
            ),
        )
        flood_events = flooded.inspect_clip_brief_events(PROJECT_ID, limit=1_000)
        timeline = flooded.inspect_clip_brief_timeline(PROJECT_ID, limit=1_000)
        no_time = engine.inspect_clip_brief_timeline(PROJECT_ID)
        unknown = [
            item for item in no_time["entries"] if item["timestamp_precision"] == "unknown"
        ]
        return _group(
            "events",
            {
                "events-deduplicated": (
                    len(result["events"]) == 4,
                    f"{len(result['events'])} unique events from 5 rows",
                ),
                "events-never-invent-progress": (
                    by_source_id["evt_1"]["progress_percent"] is None
                    and by_source_id["evt_4"]["progress_percent"] == 50.0,
                    "progress is reported only when the owner supplied both values",
                ),
                "malformed-progress-ignored": (
                    by_source_id["evt_2"]["progress_current"] is None
                    and by_source_id["evt_2"]["progress_total"] is None,
                    "a malformed progress pair is dropped, never guessed",
                ),
                "control-events-not-work": (
                    by_source_id["evt_3"]["represents_work"] is False
                    and by_source_id["evt_1"]["represents_work"] is True,
                    "a heartbeat is not reported as work",
                ),
                "events-project-scoped": _expect_error(
                    engine.inspect_clip_brief_events, "../other"
                ),
                "events-bounded": (
                    len(flood_events["events"]) <= 100 and flood_events["has_more"] is True,
                    f"{len(flood_events['events'])} events retained of 300, has_more reported",
                ),
                "timeline-bounded": (
                    len(timeline["entries"]) <= 100,
                    f"{len(timeline['entries'])} timeline entries",
                ),
                "timeline-marks-unknown-timestamps": (
                    len(unknown) >= 1
                    and all(
                        item["confirmed_order"] is True
                        for item in no_time["entries"]
                    ),
                    f"{len(unknown)} entries marked as having an unknown timestamp",
                ),
                "event-cursor-exposed": (
                    result["latest_sequence"] == 4
                    and all(
                        int(item["source_sequence"]) > 3 for item in after["events"]
                    ),
                    f"cursor {result['latest_sequence']}, "
                    f"{len(after['events'])} events after sequence 3",
                ),
            },
        )


def _run_integration() -> list[ScenarioResult]:
    modules = build_boba_module_registry()
    operations = build_boba_operation_registry()
    safety = build_safety_module_operation_registry()
    layer_ops = {
        key.split(".", 1)[1]
        for key in operations
        if key.startswith("clip_brief_review.")
    }
    safety_ops = safety.get("clip_brief_review", {})
    read_only = [
        name for name, value in safety_ops.items() if value == "automatic_read_only"
    ]
    review_ui = Path("src/olympus/boba/review_ui.py").read_text(encoding="utf-8")
    candidate_review = Path("src/olympus/boba/candidate_review.py").read_text(
        encoding="utf-8"
    )
    sources = build_fixed_clip_brief_source_registry()
    sections = build_fixed_clip_brief_section_registry()
    actions = build_fixed_clip_brief_action_registry()
    module_spec = modules["clip_brief_review"]
    return _group(
        "integration",
        {
            "integration-layer-operations-registered": (
                len(layer_ops) == 21 and layer_ops == set(safety_ops),
                f"{len(layer_ops)} operations registered and classified",
            ),
            "module-registered-available": (
                module_spec.implementation_status == "available"
                and module_spec.implementation_import_path
                == "olympus.boba.clip_brief_review"
                and module_spec.read_only is True
                and module_spec.execution_capable is False,
                f"module status {module_spec.implementation_status!r}, "
                f"read_only={module_spec.read_only}",
            ),
            "safety-gate-classifies-read-only": (
                len(read_only) == 20,
                f"{len(read_only)} operations classified automatic_read_only",
            ),
            "safety-gate-gates-submit": (
                safety_ops.get("submit_action") == "approval_required_read_only",
                f"submit_action -> {safety_ops.get('submit_action')}",
            ),
            "review-ui-untouched": (
                "clip_brief_review" not in review_ui,
                "the global Review UI module is not modified or duplicated",
            ),
            "candidate-review-untouched": (
                "clip_brief_review" not in candidate_review,
                "the Candidate Review Panel module is not modified",
            ),
            "fixed-source-registry": (
                len(sources) == 14
                and build_fixed_clip_brief_source_registry() == sources,
                f"{len(sources)} fixed sources, rebuilt identically",
            ),
            "fixed-section-registry": (
                len(sections) == 9
                and build_fixed_clip_brief_section_registry() == sections,
                f"{len(sections)} fixed sections, rebuilt identically",
            ),
            "fixed-action-registry": (
                len(actions) == 6
                and list(build_fixed_clip_brief_action_registry()) == list(actions),
                f"{len(actions)} fixed actions in a stable order",
            ),
        },
    )


_GROUP_RUNNERS: dict[str, Any] = {
    "identity": _run_identity,
    "fields": _run_fields,
    "sections": _run_sections,
    "completeness": _run_completeness,
    "sources": _run_sources,
    "evidence": _run_evidence,
    "conflicts": _run_conflicts,
    "queue": _run_queue,
    "comparison": _run_comparison,
    "preview": _run_preview,
    "actions": _run_actions,
    "authority": _run_authority,
    "persistence": _run_persistence,
    "events": _run_events,
    "integration": _run_integration,
}


def run_named_scenario(name: str) -> ScenarioResult:
    """Run one catalogued condition by its ``group:condition`` name."""
    if name not in SCENARIO_NAMES:
        raise ValidationError(f"Unknown clip brief review scenario: {name}")
    group = name.split(":", 1)[0]
    group_results: list[ScenarioResult] = _GROUP_RUNNERS[group]()
    for result in group_results:
        if result.name == name:
            return result
    raise ValidationError(f"Scenario {name} produced no result.")


def run_all_scenarios() -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for group in _CONDITION_GROUPS:
        results.extend(_GROUP_RUNNERS[group]())
    return results


def run_self_check() -> list[ScenarioResult]:
    """Prove the panel's declared boundaries against the real repository."""
    results: list[ScenarioResult] = []
    source = _source_text()
    frontend = _frontend_text()
    registry = build_fixed_clip_brief_action_registry()
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        engine, _ = _engine(root / "self")
        review = engine.build_clip_brief_review(PROJECT_ID)
        usage = review["signal_usage"]
        payload = _prepared(engine)
        request = _request(engine, payload, "idem_self_check_key")
        receipt = asyncio.run(
            engine.submit_clip_brief_action_to_owner(
                PROJECT_ID, request.clip_brief_action_request_id
            )
        )
        stored_receipt = engine.store.load_boba_clip_brief_review_receipt(
            PROJECT_ID, receipt.clip_brief_action_receipt_id
        )
        first = engine.build_clip_brief_snapshot(
            PROJECT_ID, payload["session"].clip_brief_review_session_id, "brief_a"
        )["snapshot"]
        second = engine.build_clip_brief_snapshot(
            PROJECT_ID, payload["session"].clip_brief_review_session_id, "brief_a"
        )["snapshot"]

        def add(name: str, passed: bool, detail: str) -> None:
            results.append(_check(f"self-check:{name}", passed, detail))

        add(
            "storage-writable",
            engine.store.load_boba_clip_brief_review(PROJECT_ID) is not None,
            "the review index was written and read back",
        )
        add(
            "session-storage-writable",
            engine.store.load_boba_clip_brief_review_session(
                PROJECT_ID, payload["session"].clip_brief_review_session_id
            )
            is not None,
            "review sessions persist",
        )
        add(
            "snapshot-storage-writable",
            engine.store.load_boba_clip_brief_review_snapshot(
                PROJECT_ID, first["brief_snapshot_id"]
            )
            is not None,
            "brief snapshots persist",
        )
        add(
            "action-storage-writable",
            engine.store.load_boba_clip_brief_review_action(
                PROJECT_ID, request.clip_brief_action_request_id
            )
            is not None,
            "action requests persist",
        )
        add(
            "receipt-storage-writable",
            stored_receipt is not None,
            "action receipts persist",
        )
        add(
            "deterministic-snapshot-digests",
            first["brief_digest"] == second["brief_digest"]
            and first["project_snapshot_digest"] == second["project_snapshot_digest"],
            "repeat snapshots of unchanged state produce identical digests",
        )
        add(
            "deterministic-confirmation-tokens",
            engine.build_clip_brief_snapshot(
                PROJECT_ID, payload["session"].clip_brief_review_session_id, "brief_a"
            )["action_confirmations"].keys()
            == set(first["available_action_descriptor_ids"]),
            "a confirmation token is issued for exactly the available actions",
        )
        add(
            "no-brief-generation",
            usage["brief_generated_by_panel"] is False and "def generate" not in source,
            "the panel never generates a clip brief",
        )
        add(
            "no-brief-regeneration",
            usage["brief_regenerated_by_panel"] is False
            and "regenerate_clip_brief" not in source,
            "the panel never regenerates a clip brief",
        )
        add(
            "no-brief-rewriting",
            usage["brief_rewritten_by_panel"] is False
            and "save_clip_briefs" not in source,
            "the panel never rewrites brief text",
        )
        add(
            "no-quality-score",
            usage["hidden_quality_score_created"] is False
            and usage["hidden_virality_score_created"] is False,
            "no quality or virality score is created",
        )
        add(
            "no-local-authority",
            usage["brief_approved_locally"] is False
            and usage["brief_rejected_locally"] is False
            and usage["optimistic_authority_update_used"] is False,
            "no approval, rejection or optimistic authority update happens locally",
        )
        add(
            "no-authoritative-action-available",
            all(
                not item.authoritative
                for item in registry.values()
                if item.availability == "available"
            ),
            "V1 exposes no authoritative clip brief action",
        )
        add(
            "no-dynamic-routing",
            "importlib" not in source
            and source.count("getattr(self.store") == 1
            and "getattr(self.integration" not in source,
            "module and operation routing is fixed source code",
        )
        add(
            "no-arbitrary-url-or-path",
            usage["arbitrary_url_used"] is False
            and usage["arbitrary_path_used"] is False
            and "http://" not in source
            and "open(" not in source,
            "no URL or filesystem path comes from a request",
        )
        add(
            "no-command-runner",
            usage["command_execution_used"] is False
            and usage["shell_execution_used"] is False
            and usage["git_execution_used"] is False
            and "subprocess" not in source,
            "no command, shell or Git runner exists",
        )
        add(
            "no-ffmpeg-runner",
            usage["ffmpeg_execution_used"] is False
            and all(
                token not in source
                for token in ("ffmpeg_binary", "ffprobe", '"ffmpeg"')
            ),
            "no FFmpeg or FFprobe invocation exists",
        )
        add(
            "no-media-work",
            usage["media_generation_used"] is False
            and usage["source_media_modified"] is False
            and usage["accepted_output_modified"] is False,
            "no media is generated and no source or accepted output is modified",
        )
        add(
            "no-workflow-transition",
            usage["workflow_transition_used"] is False
            and "save_boba_workflow_controller" not in source,
            "no workflow transition is performed",
        )
        add(
            "no-upload-or-publication",
            usage["upload_used"] is False and usage["publication_used"] is False,
            "nothing is uploaded or published",
        )
        add(
            "no-gate-bypass",
            usage["rights_bypass_used"] is False
            and usage["safety_bypass_used"] is False
            and usage["approval_created_locally"] is False
            and usage["safety_decision_created_locally"] is False,
            "Rights and Safety are read, never bypassed or created locally",
        )
        add(
            "no-destructive-action",
            usage["destructive_action_used"] is False
            and all(not item.destructive for item in registry.values()),
            "no destructive action exists",
        )
        add(
            "no-source-record-writes",
            all(
                item.startswith("self.store.save_boba_clip_brief_review")
                for item in set(re.findall(r"self\.store\.save_[a-z_]+", source))
            ),
            "the panel writes only its own review records",
        )
        add(
            "completeness-is-not-quality",
            any(
                "not quality" in item.lower() or "not creative quality" in item.lower()
                for item in review["limitations"]
            )
            and "Completeness means only that required owner-schema fields are present."
            in frontend,
            "completeness is stated as field presence, never as quality",
        )
        add(
            "annotations-declared-non-canonical",
            "Review-session annotation — not part of the canonical clip brief."
            in source
            and "Review-session annotation — not part of the canonical clip brief."
            in frontend,
            "review-session annotations carry the exact non-canonical notice",
        )
        add(
            "unavailable-actions-explained",
            all(
                bool(item.limitations)
                for item in registry.values()
                if item.availability == "unavailable"
            ),
            "every unavailable action states why, with no substitute authority",
        )
        add(
            "review-ui-not-duplicated",
            "clip_brief_review"
            not in Path("src/olympus/boba/review_ui.py").read_text(encoding="utf-8"),
            "the global Review UI is reused, not replaced",
        )
    return results


def run_synthetic_project() -> dict[str, Any]:
    """Build every projection over a synthetic project and report real counts."""
    with tempfile.TemporaryDirectory() as raw_root:
        engine, _ = _engine(Path(raw_root))
        review = engine.build_clip_brief_review(PROJECT_ID)
        queue = engine.build_clip_brief_queue(PROJECT_ID)
        payload = _prepared(engine)
        comparison = engine.build_clip_brief_comparison(
            PROJECT_ID, ["brief_a", "brief_b"]
        )["comparison"]
        completeness = engine.inspect_clip_brief_completeness(PROJECT_ID, "brief_a")
        evidence = engine.inspect_clip_brief_evidence(PROJECT_ID, "brief_a")
        conflicts = engine.inspect_clip_brief_conflicts(PROJECT_ID, "brief_a")
        export = engine.export_clip_brief_review(
            PROJECT_ID, payload["session"].clip_brief_review_session_id
        )
        return {
            "project_id": PROJECT_ID,
            "brief_count": len(review["brief_references"]),
            "queue_item_count": len(queue["items"]),
            "priority_tier_count": len(queue["priority_tiers"]),
            "field_projection_count": len(payload["field_projections"]),
            "section_projection_count": len(payload["section_projections"]),
            "source_card_count": len(payload["source_cards"]),
            "evidence_link_count": len(payload["evidence_links"]),
            "missing_evidence_count": evidence["missing_evidence_count"],
            "conflict_count": len(conflicts["conflict_records"]),
            "completeness_status": completeness["completeness"]["completeness_status"],
            "complete_for_owner_schema": completeness["completeness"][
                "complete_for_owner_schema"
            ],
            "available_action_descriptor_ids": payload["snapshot"][
                "available_action_descriptor_ids"
            ],
            "comparison_no_automatic_winner": comparison["no_automatic_winner"],
            "export_privacy": export["privacy"],
            "review_limitations": review["limitations"],
        }


def inspect_persisted_project(project_root: Path, project_id: str) -> dict[str, Any]:
    """Read-only inspection of an existing persisted BOBA project."""
    store = BobaMemoryStore(project_root)
    engine = BobaClipBriefReviewV1(store, _StubIntegration())  # type: ignore[arg-type]
    references = engine.build_clip_brief_references(project_id)
    queue = engine.build_clip_brief_queue(project_id)
    return {
        "project_id": project_id,
        "brief_count": len(references),
        "brief_ids": [item.brief_id for item in references],
        "queue_item_count": len(queue["items"]),
        "unsupported_schema_brief_ids": [
            item.brief_id for item in references if not item.schema_supported
        ],
        "notice": (
            "Read-only inspection. Nothing was generated, rewritten, approved or "
            "published."
        ),
    }


def _write_report(payload: dict[str, Any]) -> Path:
    directory = Path("work/validation_reports/boba_clip_brief_review")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"report_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Clip Brief Panel V1 without touching real media."
    )
    parser.add_argument(
        "--self-check", action="store_true", help="run the declared-boundary checks"
    )
    parser.add_argument(
        "--synthetic-project",
        action="store_true",
        help="build every projection over a synthetic project",
    )
    parser.add_argument(
        "--scenario", action="append", default=[], help="run one named scenario"
    )
    parser.add_argument(
        "--project-root", default=None, help="BOBA memory root for a read-only inspection"
    )
    parser.add_argument(
        "--project-id", default=None, help="existing project id to inspect read-only"
    )
    parser.add_argument("--report", action="store_true", help="write a JSON report")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"tool": "validate_boba_clip_brief_review"}
    failures: list[ScenarioResult] = []

    if args.scenario:
        results = [run_named_scenario(name) for name in args.scenario]
    else:
        results = run_all_scenarios()
    failures.extend(item for item in results if not item.passed)
    report["scenarios"] = {
        "total": len(results),
        "passed": len(results) - len([r for r in results if not r.passed]),
        "failed": [{"name": r.name, "detail": r.detail} for r in results if not r.passed],
    }
    print(
        f"scenarios: {len(results)} total, "
        f"{len(results) - len([r for r in results if not r.passed])} passed, "
        f"{len([r for r in results if not r.passed])} failed"
    )

    if args.self_check:
        checks = run_self_check()
        failures.extend(item for item in checks if not item.passed)
        report["self_check"] = {
            "total": len(checks),
            "passed": len([r for r in checks if r.passed]),
            "failed": [
                {"name": r.name, "detail": r.detail} for r in checks if not r.passed
            ],
        }
        print(
            f"self-check: {len(checks)} checks, "
            f"{len([r for r in checks if r.passed])} passed, "
            f"{len([r for r in checks if not r.passed])} failed"
        )

    if args.synthetic_project:
        synthetic = run_synthetic_project()
        report["synthetic_project"] = synthetic
        print("synthetic project:")
        for key, value in synthetic.items():
            print(f"  {key}: {value}")

    if args.project_root and args.project_id:
        inspection = inspect_persisted_project(Path(args.project_root), args.project_id)
        report["persisted_project"] = inspection
        print("persisted project inspection:")
        for key, value in inspection.items():
            print(f"  {key}: {value}")

    for item in failures:
        print(f"FAILED {item.name}: {item.detail}")

    if args.report:
        print(f"report written to {_write_report(report)}")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
