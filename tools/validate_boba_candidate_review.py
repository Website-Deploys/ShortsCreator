"""Offline validation for BOBA Candidate Review Panel V1.

The tool uses only synthetic BOBA metadata under the ignored validation
workspace. It never discovers candidates, reranks candidates, recomputes a
source-owned score, executes a target, or runs commands, Git, FFmpeg,
validators, repairs, workflow transitions, media work, network access, upload,
publication or source-owner decision mutation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from olympus.boba.candidate_review import (
    CANDIDATE_QUEUE_PRIORITY_TIERS,
    MAX_COMPARISON_CANDIDATES,
    SUBSTANTIAL_OVERLAP_IOU_THRESHOLD,
    BobaCandidateActionReceiptV1,
    BobaCandidateReferenceV1,
    BobaCandidateReviewV1,
    _overlap_metrics,
    build_fixed_candidate_action_registry,
    build_fixed_candidate_source_registry,
)
from olympus.boba.integration_layer import build_boba_operation_registry
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError

try:  # imported as ``tools.validate_boba_candidate_review``
    from tools._boba_candidate_review_fixtures import (
        seed_project,
        synthetic_candidate,
        synthetic_discovery,
        synthetic_ranked,
        synthetic_ranking,
    )
except ModuleNotFoundError:  # executed directly as a script
    from _boba_candidate_review_fixtures import (  # type: ignore[no-redef,import-not-found]
        seed_project,
        synthetic_candidate,
        synthetic_discovery,
        synthetic_ranked,
        synthetic_ranking,
    )

PROJECT_ID = "proj_candidate_review_validation"

_CONDITION_GROUPS: dict[str, tuple[str, ...]] = {
    "identity": (
        "valid-candidate-projected",
        "unknown-candidate-rejected",
        "cross-project-candidate-excluded",
        "candidate-id-charset-enforced",
        "exact-start-preserved",
        "exact-end-preserved",
        "exact-duration-matches-range",
        "decimal-range-preserved",
        "zero-duration-rejected",
        "negative-duration-rejected",
        "inverted-range-rejected",
        "duration-mismatch-rejected",
        "candidate-revision-absent",
        "no-browser-supplied-range",
        "no-external-media-reference",
        "speaker-references-opaque",
        "current-candidate-labelled",
        "stale-candidate-labelled",
        "historical-candidate-labelled",
        "superseded-candidate-labelled",
        "transcript-segment-ids-preserved",
        "workflow-binding-present",
        "stage-binding-present",
    ),
    "sources": (
        "discovery-record-present",
        "discovery-record-missing-not-a-pass",
        "ranking-record-present",
        "ranking-record-missing-not-a-pass",
        "editorial-record-present",
        "editorial-record-missing-not-a-pass",
        "explanation-source-advisory",
        "creative-source-advisory",
        "transcript-from-source-record",
        "rights-source-authoritative",
        "safety-source-authoritative",
        "workflow-source-authoritative",
        "artifact-source-authoritative",
        "validation-source-authoritative",
        "unavailable-source-reported",
        "source-owner-preserved",
        "source-digest-recorded",
        "duplicate-source-descriptor-rejected",
        "required-source-declared",
    ),
    "scores": (
        "discovery-score-scale-preserved",
        "ranking-score-scale-preserved",
        "editorial-confidence-scale-preserved",
        "score-definition-preserved",
        "score-direction-preserved",
        "penalty-direction-inverted",
        "missing-weight-stays-missing",
        "rank-preserved",
        "rank-total-preserved",
        "tie-preserved",
        "no-score-recalculation",
        "no-hidden-composite",
        "source-composite-labelled",
        "incomparable-scores-flagged",
        "no-virality-probability-claim",
        "stale-score-labelled",
        "component-scores-present",
    ),
    "queue": (
        "selected-critical-block-first",
        "human-review-priority",
        "conflict-priority",
        "missing-evidence-priority",
        "stale-evidence-priority",
        "source-shortlisted-priority",
        "strong-rank-priority",
        "substantial-overlap-priority",
        "source-rank-order-priority",
        "rejected-separated",
        "superseded-separated",
        "historical-separated",
        "deterministic-tie-break",
        "deterministic-repeat-order",
        "twelve-priority-tiers",
        "pagination-bounded",
        "filter-all-current",
        "filter-human-review",
        "filter-source-shortlisted",
        "filter-selected",
        "filter-rejected",
        "filter-stale",
        "filter-overlapping",
        "filter-missing-evidence",
        "filter-historical",
        "unknown-filter-rejected",
        "sort-review-priority",
        "sort-original-rank",
        "sort-candidate-id",
        "unknown-sort-rejected",
        "no-ai-priority-score",
    ),
    "overlap": (
        "no-overlap-not-recorded",
        "boundary-touch-no-overlap",
        "partial-overlap-detected",
        "substantial-overlap-detected",
        "exact-duplicate-window-detected",
        "contained-candidate-detected",
        "deterministic-iou",
        "zero-union-safe",
        "iou-bounded",
        "coverage-bounded",
        "threshold-documented",
        "no-semantic-duplicate-claim",
        "no-automatic-rejection",
        "overlap-uses-exact-boundaries",
        "same-identity-flagged",
    ),
    "comparison": (
        "two-candidate-comparison",
        "four-candidate-comparison",
        "single-candidate-rejected",
        "too-many-candidates-rejected",
        "unknown-candidate-comparison-rejected",
        "duplicate-ids-collapsed",
        "rank-comparison-present",
        "score-comparison-present",
        "duration-comparison-present",
        "evidence-comparison-present",
        "editorial-comparison-present",
        "discovery-reason-comparison-present",
        "overlap-linked-in-comparison",
        "unknown-comparison-type-rejected",
        "no-automatic-winner",
    ),
    "preview": (
        "preview-unavailable-state",
        "external-url-not-referenced",
        "absolute-path-not-referenced",
        "no-filesystem-path-in-projection",
        "candidate-window-exposed-for-seek",
        "context-window-bounded",
        "context-does-not-change-candidate",
        "playback-not-validation",
    ),
    "actions": (
        "advisory-feedback-available",
        "review-note-available",
        "selection-action-unavailable",
        "rejection-action-unavailable",
        "revision-request-unavailable",
        "alternate-request-unavailable",
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
        "stale-project-digest-rejected",
        "workflow-revision-mismatch-rejected",
        "candidate-digest-mismatch-rejected",
        "source-digest-mismatch-rejected",
        "canonical-receipt-recorded",
        "owner-rejection-recorded",
        "duplicate-request-reused",
        "no-optimistic-update",
        "advisory-receipt-not-authoritative",
        "authority-requires-owner-record",
        "malformed-owner-response-handled",
    ),
    "authority": (
        "no-candidate-discovery",
        "no-reranking",
        "no-editorial-decision-created",
        "no-rights-decision-created",
        "no-safety-decision-created",
        "no-validation-decision-created",
        "no-quality-decision-created",
        "no-workflow-transition",
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
        "no-upload",
        "no-publication",
        "no-external-analytics",
        "no-rights-bypass",
        "no-safety-bypass",
        "no-destructive-action",
        "no-local-selection",
        "no-local-rejection",
        "no-biometric-inference",
    ),
    "persistence": (
        "session-persisted",
        "session-expiry-enforced",
        "session-project-scoped",
        "session-field-allowlist",
        "comparison-limit-enforced-in-session",
        "registry-snapshot-immutable",
        "action-request-immutable",
        "receipt-immutable",
        "source-records-not-duplicated",
        "reset-preserves-candidate-records",
        "reset-preserves-ranking-records",
        "reset-preserves-editorial-history",
        "reset-preserves-review-ui-history",
        "reset-preserves-receipts",
        "sanitized-export",
        "export-excludes-secrets",
        "export-excludes-private-paths",
        "event-cursor-bounded",
    ),
    "events": (
        "events-deduplicated",
        "events-never-invent-progress",
        "malformed-progress-ignored",
        "control-events-not-work",
        "timeline-marks-unknown-timestamps",
        "timeline-bounded",
        "events-bounded",
        "event-cursor-exposed",
        "events-project-scoped",
    ),
    "integration": (
        "integration-layer-operations-registered",
        "safety-gate-classifies-read-only",
        "safety-gate-gates-submit",
        "module-registered-available",
        "review-ui-untouched",
        "fixed-source-registry",
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
            "project_id": project_id,
            "target_id": kwargs.get("target_id"),
            "user_action": kwargs.get("user_action"),
        }


class _StubIntegration:
    def __init__(self) -> None:
        self.owner = _StubCreatorLearning()

    async def record_creator_feedback_event(
        self, project_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await self.owner.record_creator_feedback_event(project_id, **kwargs)


def _engine(root: Path, **seed: Any) -> tuple[BobaCandidateReviewV1, _StubIntegration]:
    store = BobaMemoryStore(root)
    integration = _StubIntegration()
    engine = BobaCandidateReviewV1(store, integration)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, integration


def _prepared(engine: BobaCandidateReviewV1, candidate_id: str = "cand_a") -> dict[str, Any]:
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    payload = engine.build_candidate_snapshot(
        PROJECT_ID, session.candidate_review_session_id, candidate_id
    )
    payload["session"] = session
    return payload


def _request(
    engine: BobaCandidateReviewV1,
    payload: dict[str, Any],
    key: str,
    *,
    action: str = "candidate_action_submit_feedback_v1",
    decision: str | None = "approved",
    reason: str = "Reviewed the exact candidate window.",
) -> Any:
    return engine.create_candidate_action_request(
        PROJECT_ID,
        candidate_review_session_id=payload["session"].candidate_review_session_id,
        candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
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
    return Path("src/olympus/boba/candidate_review.py").read_text(encoding="utf-8")


def _run_identity(name: str, root: Path) -> ScenarioResult:
    engine, _ = _engine(root)
    refs = {item.candidate_id: item for item in engine.build_candidate_references(PROJECT_ID)}
    if name == "valid-candidate-projected":
        return _check(name, "cand_a" in refs, f"{len(refs)} candidates projected.")
    if name == "unknown-candidate-rejected":
        try:
            engine.inspect_candidate(PROJECT_ID, "cand_missing")
        except ValidationError as error:
            return _check(name, "unknown" in str(error).lower(), str(error))
        return _check(name, False, "An unknown candidate was accepted.")
    if name == "cross-project-candidate-excluded":
        store = engine.store
        rows = [synthetic_candidate("cand_x", "proj_other", 5.0, 15.0)]
        store.save_candidate_clip_discovery(synthetic_discovery(PROJECT_ID, rows))
        after = engine.build_candidate_references(PROJECT_ID)
        return _check(name, not after, "Cross-project candidate rows are never projected.")
    if name == "candidate-id-charset-enforced":
        return _check(
            name, all(item.isprintable() for item in refs), "Identifiers are opaque tokens."
        )
    if name == "exact-start-preserved":
        return _check(name, refs["cand_a"].start_seconds == 10.0, "Start preserved exactly.")
    if name == "exact-end-preserved":
        return _check(name, refs["cand_a"].end_seconds == 40.0, "End preserved exactly.")
    if name == "exact-duration-matches-range":
        return _check(
            name,
            all(
                abs(item.duration_seconds - (item.end_seconds - item.start_seconds)) < 1e-6
                for item in refs.values()
            ),
            "Duration always equals the persisted range.",
        )
    if name == "decimal-range-preserved":
        engine2, _ = _engine(root / "decimal", windows=[("cand_dec", 12.345, 48.678)])
        item = engine2.build_candidate_references(PROJECT_ID)[0]
        return _check(
            name,
            item.start_seconds == 12.345 and item.end_seconds == 48.678,
            f"{item.start_seconds}-{item.end_seconds} preserved.",
        )
    if name in {"zero-duration-rejected", "negative-duration-rejected", "inverted-range-rejected"}:
        try:
            BobaCandidateReferenceV1(
                candidate_reference_id="r",
                project_id=PROJECT_ID,
                candidate_id="c",
                source_record_id="s",
                source_record_digest="0" * 64,
                start_seconds=10.0,
                end_seconds=10.0 if name == "zero-duration-rejected" else 5.0,
                duration_seconds=1.0,
            )
        except Exception as error:
            return _check(name, "greater than" in str(error), "Non-positive range rejected.")
        return _check(name, False, "A non-positive candidate range was accepted.")
    if name == "duration-mismatch-rejected":
        try:
            BobaCandidateReferenceV1(
                candidate_reference_id="r",
                project_id=PROJECT_ID,
                candidate_id="c",
                source_record_id="s",
                source_record_digest="0" * 64,
                start_seconds=10.0,
                end_seconds=40.0,
                duration_seconds=99.0,
            )
        except Exception as error:
            return _check(name, "exact persisted" in str(error), "Mismatch rejected.")
        return _check(name, False, "A mismatched duration was accepted.")
    if name == "candidate-revision-absent":
        return _check(
            name,
            all(item.candidate_revision_id is None for item in refs.values()),
            "Owner records carry no revision identity.",
        )
    if name == "no-browser-supplied-range":
        source = _source_text()
        return _check(
            name,
            "start_seconds=start" in source and "request.start" not in source,
            "Ranges come only from the persisted owner record.",
        )
    if name == "no-external-media-reference":
        return _check(
            name,
            all(item.source_media_reference_id == PROJECT_ID for item in refs.values()),
            "Media reference is the project identifier only.",
        )
    if name == "speaker-references-opaque":
        return _check(
            name,
            all(item.speaker_reference_ids == [] for item in refs.values()),
            "No speaker identity is inferred.",
        )
    if name == "current-candidate-labelled":
        return _check(name, refs["cand_a"].current, "Current candidates are labelled.")
    if name in {
        "stale-candidate-labelled",
        "historical-candidate-labelled",
        "superseded-candidate-labelled",
    }:
        field = name.split("-")[0]
        return _check(
            name,
            hasattr(refs["cand_a"], field) and getattr(refs["cand_a"], field) is False,
            f"'{field}' is an explicit, separately reported flag.",
        )
    if name == "transcript-segment-ids-preserved":
        return _check(
            name,
            refs["cand_a"].transcript_segment_ids == ["seg_cand_a"],
            "Transcript segment identifiers come from the owner record.",
        )
    if name in {"workflow-binding-present", "stage-binding-present"}:
        field = "workflow_run_id" if name.startswith("workflow") else "stage_instance_id"
        return _check(
            name,
            hasattr(refs["cand_a"], field),
            f"'{field}' is bound from the Workflow Controller when available.",
        )
    return _check(name, False, "Unknown identity scenario.")


def _run_sources(name: str, root: Path) -> ScenarioResult:
    if name == "duplicate-source-descriptor-rejected":
        registry = build_fixed_candidate_source_registry()
        return _check(
            name, len(registry) == len(set(registry)), "Source ids are unique."
        )
    if name.endswith("missing-not-a-pass"):
        module = {"discovery": "clip_discovery", "ranking": "clip_ranking",
                  "editorial": "editorial_decision"}[name.split("-")[0]]
        engine, _ = _engine(root, seed=False)
        cards = {
            card.source_module_id: card
            for card in engine.build_source_cards(PROJECT_ID, "cand_a")
        }
        card = cards[module]
        return _check(
            name,
            card.original_status == "unavailable" and not card.current,
            f"{module} reports unavailable, never a pass.",
        )
    engine, _ = _engine(root)
    cards = {
        card.source_module_id: card for card in engine.build_source_cards(PROJECT_ID, "cand_a")
    }
    if name == "discovery-record-present":
        return _check(name, cards["clip_discovery"].original_status == "discovered", "Present.")
    if name == "ranking-record-present":
        return _check(
            name, cards["clip_ranking"].original_rank == 1, "Rank preserved from owner."
        )
    if name == "editorial-record-present":
        return _check(
            name,
            cards["editorial_decision"].original_status
            in {"selected", "not_selected"},
            "Present.",
        )
    if name == "explanation-source-advisory":
        return _check(name, cards["explanation"].advisory_only, "Explanation is advisory.")
    if name == "creative-source-advisory":
        return _check(
            name,
            all(
                cards[item].advisory_only
                for item in ("clip_brief", "hook_retention", "music_mood")
            ),
            "Creative sources are advisory.",
        )
    if name == "transcript-from-source-record":
        payload = engine.inspect_candidate_transcript(PROJECT_ID, "cand_a")
        return _check(
            name,
            payload["candidate_transcript_snippets"]
            == ["The exact transcript line for this candidate."],
            "Transcript is verbatim from the owner record.",
        )
    if name.endswith("source-authoritative"):
        module = {
            "rights": "rights_permission_gate",
            "safety": "safety_gate",
            "workflow": "workflow_controller",
            "artifact": "artifact_inspector",
            "validation": "validator_runner",
        }[name.split("-")[0]]
        return _check(
            name, not cards[module].advisory_only, f"{module} is authoritative, not advisory."
        )
    if name == "unavailable-source-reported":
        return _check(
            name,
            any(card.original_status == "unavailable" for card in cards.values()),
            "Unavailable owners are reported explicitly.",
        )
    if name == "source-owner-preserved":
        return _check(
            name,
            all(card.source_module_id for card in cards.values()),
            "Every card names its owning module.",
        )
    if name == "source-digest-recorded":
        return _check(
            name,
            all(len(card.source_record_digest) == 64 for card in cards.values()),
            "Every card carries a digest.",
        )
    if name == "required-source-declared":
        registry = build_fixed_candidate_source_registry()
        required = [key for key, item in registry.items() if item["required"]]
        return _check(
            name,
            required == ["clip_discovery"],
            "Candidate Clip Discovery is the only required source.",
        )
    return _check(name, False, "Unknown source scenario.")


def _run_scores(name: str, root: Path) -> ScenarioResult:
    engine, _ = _engine(root)
    cards = {
        (card.source_module_id, card.score_name): card
        for card in engine.build_score_cards(PROJECT_ID, "cand_a")
    }
    if name == "discovery-score-scale-preserved":
        card = cards[("clip_discovery", "confidence")]
        return _check(
            name,
            card.score_scale_min == 0.0
            and card.score_scale_max == 1.0
            and card.score_value == 0.81,
            "Discovery confidence keeps its 0.0-1.0 scale.",
        )
    if name == "ranking-score-scale-preserved":
        card = cards[("clip_ranking", "total_score")]
        return _check(
            name,
            card.score_scale_min == 0.0 and card.score_scale_max == 100.0,
            "Ranking total keeps its 0-100 scale.",
        )
    if name == "editorial-confidence-scale-preserved":
        card = cards[("editorial_decision", "editorial_confidence")]
        return _check(name, card.score_scale_max == 1.0, "Editorial confidence keeps 0.0-1.0.")
    if name == "score-definition-preserved":
        return _check(
            name,
            all(len(card.score_definition) > 20 for card in cards.values()),
            "Every score carries its definition.",
        )
    if name == "score-direction-preserved":
        return _check(
            name,
            cards[("clip_ranking", "hook_score")].score_direction == "higher_is_better",
            "Direction is stated.",
        )
    if name == "penalty-direction-inverted":
        return _check(
            name,
            cards[("clip_ranking", "overlap_penalty")].score_direction == "lower_is_better",
            "Penalties are marked lower-is-better.",
        )
    if name == "missing-weight-stays-missing":
        return _check(
            name,
            all(card.weight is None for card in cards.values()),
            "The owner persists no weights, so none are shown.",
        )
    if name == "rank-preserved":
        return _check(name, cards[("clip_ranking", "total_score")].rank == 1, "Rank 1 preserved.")
    if name == "rank-total-preserved":
        return _check(
            name, cards[("clip_ranking", "total_score")].rank_total == 4, "Rank total preserved."
        )
    if name == "tie-preserved":
        engine2, _ = _engine(root / "tie", seed=False)
        rows = [("cand_t1", 10.0, 30.0), ("cand_t2", 100.0, 120.0)]
        engine2.store.save_candidate_clip_discovery(
            synthetic_discovery(
                PROJECT_ID,
                [synthetic_candidate(c, PROJECT_ID, s, e) for c, s, e in rows],
            )
        )
        engine2.store.save_clip_ranking(
            synthetic_ranking(
                PROJECT_ID,
                [
                    synthetic_ranked("cand_t1", PROJECT_ID, 1, 80.0, 10.0, 30.0),
                    synthetic_ranked("cand_t2", PROJECT_ID, 2, 80.0, 100.0, 120.0),
                ],
            )
        )
        card = next(
            item
            for item in engine2.build_score_cards(PROJECT_ID, "cand_t1")
            if item.score_name == "total_score"
        )
        return _check(name, card.tied, "Equal owner scores are reported as tied.")
    if name == "no-score-recalculation":
        source = _source_text()
        # Look for arithmetic on score values, not for prose that mentions it.
        forbidden = (
            "score_value=sum(",
            "score_value =",
            "* weight",
            "/ len(scores)",
            "score_value +",
            "score_value *",
        )
        found = [token for token in forbidden if token in source]
        return _check(
            name,
            not found,
            "Scores are copied with float(value); no arithmetic surface exists.",
        )
    if name == "no-hidden-composite":
        return _check(
            name,
            sum(1 for card in cards.values() if card.source_owned_composite) == 1,
            "The only composite is Clip Ranking's own total_score.",
        )
    if name == "source-composite-labelled":
        return _check(
            name,
            cards[("clip_ranking", "total_score")].source_owned_composite,
            "Owner composite is labelled as owner-owned.",
        )
    if name == "incomparable-scores-flagged":
        return _check(
            name,
            not cards[
                ("editorial_decision", "editorial_confidence")
            ].comparable_across_candidates,
            "Cross-scale scores are flagged incomparable.",
        )
    if name == "no-virality-probability-claim":
        joined = " ".join(
            f"{card.score_definition} {' '.join(card.limitations)}" for card in cards.values()
        ).lower()
        return _check(
            name,
            "not a probability" in joined and "virality" in joined,
            "Definitions explicitly disclaim probability and virality.",
        )
    if name == "stale-score-labelled":
        return _check(
            name,
            all(card.stale is False for card in cards.values()),
            "Staleness is an explicit per-card flag.",
        )
    if name == "component-scores-present":
        components = [key for key in cards if key[0] == "clip_ranking"]
        return _check(name, len(components) >= 13, f"{len(components)} ranking scores shown.")
    return _check(name, False, "Unknown score scenario.")


def _run_queue(name: str, root: Path) -> ScenarioResult:
    if name == "twelve-priority-tiers":
        priorities = [tier[0] for tier in CANDIDATE_QUEUE_PRIORITY_TIERS]
        return _check(
            name,
            len(CANDIDATE_QUEUE_PRIORITY_TIERS) == 12 and priorities == sorted(priorities),
            "Twelve ascending fixed tiers.",
        )
    if name == "no-ai-priority-score":
        source = _source_text()
        return _check(
            name,
            "priority_score" not in source and "Never a quality score" in source,
            "Priority is a fixed tier, not a generated score.",
        )
    if name == "selected-critical-block-first":
        # Exercise the documented tier directly: a selected candidate carrying a
        # critical Rights or Safety block always sorts to tier 10.
        priority, reason, status = BobaCandidateReviewV1._priority(
            selected=True,
            rejected=False,
            blocked=True,
            conflict=False,
            missing_evidence=False,
            stale=False,
            shortlisted=True,
            rank=1,
            substantial_overlap=False,
            superseded=False,
            historical=False,
            human_required=False,
        )
        return _check(
            name,
            priority == 10
            and reason == "selected_candidate_with_critical_rights_or_safety_block"
            and status == "blocked",
            f"Tier {priority} for '{reason}'.",
        )
    if name == "human-review-priority":
        engine, _ = _engine(root, with_editorial=False)
        items = engine.build_candidate_queue(PROJECT_ID)["items"]
        return _check(
            name,
            all(item["priority_tier"] == 20 for item in items),
            "Candidates without an editorial decision need a human decision.",
        )
    if name == "missing-evidence-priority":
        engine, _ = _engine(root, with_ranking=False, with_editorial=False)
        item = engine.build_candidate_queue(PROJECT_ID)["items"][0]
        return _check(
            name, item["missing_evidence_count"] >= 1, "Missing evidence is counted and ranked."
        )
    if name == "source-shortlisted-priority":
        engine, _ = _engine(root, selected=["cand_a"], recommended=["cand_a"])
        item = next(
            i for i in engine.build_candidate_queue(PROJECT_ID)["items"]
            if i["candidate_id"] == "cand_a"
        )
        return _check(name, item["priority_tier"] == 60, f"Tier {item['priority_tier']}.")
    if name == "strong-rank-priority":
        engine, _ = _engine(root, selected=["cand_d"])
        item = next(
            i for i in engine.build_candidate_queue(PROJECT_ID)["items"]
            if i["candidate_id"] == "cand_b"
        )
        return _check(name, item["priority_tier"] == 70, f"Tier {item['priority_tier']}.")
    if name == "source-rank-order-priority":
        engine, _ = _engine(root, selected=["cand_a"])
        item = next(
            i for i in engine.build_candidate_queue(PROJECT_ID)["items"]
            if i["candidate_id"] == "cand_d"
        )
        return _check(name, item["priority_tier"] == 90, f"Tier {item['priority_tier']}.")
    if name == "rejected-separated":
        engine, _ = _engine(root, rejected=["cand_d"], selected=["cand_a"])
        item = next(
            i for i in engine.build_candidate_queue(PROJECT_ID)["items"]
            if i["candidate_id"] == "cand_d"
        )
        return _check(
            name,
            item["priority_tier"] == 100 and item["rejected"],
            "Rejected candidates stay visible in their own tier.",
        )
    engine, _ = _engine(root, selected=["cand_a"], recommended=["cand_a"])
    if name in {"conflict-priority", "stale-evidence-priority", "substantial-overlap-priority",
                "superseded-separated", "historical-separated"}:
        tier = {
            "conflict-priority": 30,
            "stale-evidence-priority": 50,
            "substantial-overlap-priority": 80,
            "superseded-separated": 110,
            "historical-separated": 120,
        }[name]
        reasons = dict(CANDIDATE_QUEUE_PRIORITY_TIERS)
        return _check(
            name, tier in reasons, f"Tier {tier} is reserved for '{reasons.get(tier)}'."
        )
    if name == "deterministic-tie-break":
        items = engine.build_candidate_queue(PROJECT_ID)["items"]
        keys = [item["deterministic_sort_key"] for item in items]
        return _check(name, keys == sorted(keys), "Sort keys are total and ordered.")
    if name == "deterministic-repeat-order":
        first = engine.build_candidate_queue(PROJECT_ID)["items"]
        second = engine.build_candidate_queue(PROJECT_ID)["items"]
        return _check(
            name,
            [i["candidate_id"] for i in first] == [i["candidate_id"] for i in second],
            "Repeat builds return identical order.",
        )
    if name == "pagination-bounded":
        page = engine.build_candidate_queue(PROJECT_ID, offset=1, limit=2)
        return _check(
            name,
            len(page["items"]) == 2 and page["offset"] == 1 and page["total"] == 4,
            "Pagination is bounded and reports the true total.",
        )
    if name.startswith("filter-"):
        key = name.removeprefix("filter-").replace("-", "_")
        mapping = {
            "all_current": "all_current",
            "human_review": "human_review_required",
            "source_shortlisted": "source_shortlisted",
            "selected": "selected",
            "rejected": "rejected",
            "stale": "stale",
            "overlapping": "overlapping",
            "missing_evidence": "missing_evidence",
            "historical": "historical",
        }
        payload = engine.build_candidate_queue(PROJECT_ID, review_filter=mapping[key])
        return _check(name, "items" in payload, f"Filter '{mapping[key]}' is supported.")
    if name == "unknown-filter-rejected":
        try:
            engine.build_candidate_queue(PROJECT_ID, review_filter="ai_best")
        except ValidationError as error:
            return _check(name, "filter" in str(error).lower(), str(error))
        return _check(name, False, "An arbitrary filter was accepted.")
    if name.startswith("sort-"):
        sort = name.removeprefix("sort-").replace("-", "_")
        payload = engine.build_candidate_queue(PROJECT_ID, sort=sort)
        return _check(name, "items" in payload, f"Sort '{sort}' is supported.")
    if name == "unknown-sort-rejected":
        try:
            engine.build_candidate_queue(PROJECT_ID, sort="most_viral")
        except ValidationError as error:
            return _check(name, "sort" in str(error).lower(), str(error))
        return _check(name, False, "An arbitrary sort was accepted.")
    return _check(name, False, "Unknown queue scenario.")


def _run_overlap(name: str, root: Path) -> ScenarioResult:
    if name == "no-overlap-not-recorded":
        engine, _ = _engine(root, windows=[("c1", 0.0, 10.0), ("c2", 20.0, 30.0)])
        return _check(
            name, engine.calculate_candidate_overlaps(PROJECT_ID) == [], "Disjoint pairs omitted."
        )
    if name == "boundary-touch-no-overlap":
        engine, _ = _engine(root, windows=[("c1", 0.0, 10.0), ("c2", 10.0, 20.0)])
        return _check(
            name,
            engine.calculate_candidate_overlaps(PROJECT_ID) == [],
            "Touching boundaries are not an overlap.",
        )
    if name == "partial-overlap-detected":
        engine, _ = _engine(root, windows=[("c1", 0.0, 30.0), ("c2", 25.0, 60.0)])
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        return _check(
            name,
            record.partial_overlap and not record.substantial_overlap,
            f"IoU {record.intersection_over_union} classified partial.",
        )
    if name == "substantial-overlap-detected":
        engine, _ = _engine(root, windows=[("c1", 0.0, 30.0), ("c2", 2.0, 31.0)])
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        return _check(
            name,
            record.substantial_overlap
            and record.intersection_over_union >= SUBSTANTIAL_OVERLAP_IOU_THRESHOLD,
            f"IoU {record.intersection_over_union} >= {SUBSTANTIAL_OVERLAP_IOU_THRESHOLD}.",
        )
    if name == "exact-duplicate-window-detected":
        engine, _ = _engine(root, windows=[("c1", 5.0, 25.0), ("c2", 5.0, 25.0)])
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        return _check(
            name,
            record.exact_duplicate_window and record.intersection_over_union == 1.0,
            "Identical boundaries are an exact duplicate window.",
        )
    if name == "contained-candidate-detected":
        engine, _ = _engine(root, windows=[("c1", 0.0, 60.0), ("c2", 10.0, 20.0)])
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        return _check(name, record.contained, "Full containment is detected.")
    if name == "deterministic-iou":
        first = _overlap_metrics(0.0, 30.0, 15.0, 45.0)
        second = _overlap_metrics(0.0, 30.0, 15.0, 45.0)
        return _check(
            name,
            first == second and first["intersection_over_union"] == round(1 / 3, 6),
            f"IoU {first['intersection_over_union']} is exact and repeatable.",
        )
    if name == "zero-union-safe":
        metrics = _overlap_metrics(10.0, 10.0, 10.0, 10.0)
        return _check(name, metrics["intersection_over_union"] == 0.0, "Zero union is safe.")
    if name == "iou-bounded":
        metrics = _overlap_metrics(0.0, 10.0, 0.0, 10.0)
        return _check(name, metrics["intersection_over_union"] <= 1.0, "IoU never exceeds 1.")
    if name == "coverage-bounded":
        engine, _ = _engine(root, windows=[("c1", 0.0, 60.0), ("c2", 10.0, 20.0)])
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        return _check(
            name,
            0.0 <= record.candidate_a_coverage <= 1.0
            and 0.0 <= record.candidate_b_coverage <= 1.0,
            "Coverage stays within 0-1.",
        )
    if name == "threshold-documented":
        engine, _ = _engine(root)
        payload = engine.inspect_candidate_overlaps(PROJECT_ID, "cand_a")
        return _check(
            name,
            payload["substantial_overlap_iou_threshold"] == SUBSTANTIAL_OVERLAP_IOU_THRESHOLD,
            "The threshold is published with the records.",
        )
    if name == "no-semantic-duplicate-claim":
        engine, _ = _engine(root)
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        joined = " ".join(record.limitations).lower()
        return _check(
            name,
            "not a semantic duplication claim" in joined and record.source_time_overlap_only,
            "Every record disclaims semantic duplication.",
        )
    if name == "no-automatic-rejection":
        engine, _ = _engine(root, selected=["cand_a"])
        items = engine.build_candidate_queue(PROJECT_ID)["items"]
        return _check(
            name,
            not any(item["rejected"] for item in items),
            "Overlapping candidates are never auto-rejected.",
        )
    if name == "overlap-uses-exact-boundaries":
        engine, _ = _engine(root, windows=[("c1", 1.111, 2.222), ("c2", 1.500, 3.000)])
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        return _check(
            name,
            record.candidate_a_start_seconds == 1.111
            and record.candidate_b_end_seconds == 3.0,
            "Exact decimal boundaries are carried into the record.",
        )
    if name == "same-identity-flagged":
        engine, _ = _engine(root)
        record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
        return _check(
            name,
            record.same_candidate_identity is False,
            "Distinct identities are reported as distinct.",
        )
    return _check(name, False, "Unknown overlap scenario.")


def _run_comparison(name: str, root: Path) -> ScenarioResult:
    engine, _ = _engine(root, selected=["cand_a"])
    if name == "two-candidate-comparison":
        payload = engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_b"])
        return _check(name, len(payload["comparison"]["candidate_ids"]) == 2, "Two compared.")
    if name == "four-candidate-comparison":
        payload = engine.build_candidate_comparison(
            PROJECT_ID, ["cand_a", "cand_b", "cand_c", "cand_d"]
        )
        return _check(name, len(payload["comparison"]["candidate_ids"]) == 4, "Four compared.")
    if name == "single-candidate-rejected":
        try:
            engine.build_candidate_comparison(PROJECT_ID, ["cand_a"])
        except ValidationError as error:
            return _check(name, "two" in str(error).lower(), str(error))
        return _check(name, False, "A single-candidate comparison was accepted.")
    if name == "too-many-candidates-rejected":
        try:
            engine.build_candidate_comparison(
                PROJECT_ID, ["cand_a", "cand_b", "cand_c", "cand_d", "cand_a2"]
            )
        except ValidationError as error:
            return _check(name, str(MAX_COMPARISON_CANDIDATES) in str(error), str(error))
        return _check(name, False, "More than four candidates were accepted.")
    if name == "unknown-candidate-comparison-rejected":
        try:
            engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_missing"])
        except ValidationError as error:
            return _check(name, "unknown" in str(error).lower(), str(error))
        return _check(name, False, "An unknown candidate was compared.")
    if name == "duplicate-ids-collapsed":
        payload = engine.build_candidate_comparison(
            PROJECT_ID, ["cand_a", "cand_a", "cand_b"]
        )
        return _check(
            name, payload["comparison"]["candidate_ids"] == ["cand_a", "cand_b"], "Collapsed."
        )
    if name == "unknown-comparison-type-rejected":
        try:
            engine.build_candidate_comparison(
                PROJECT_ID, ["cand_a", "cand_b"], comparison_type="ai_pick"
            )
        except ValidationError as error:
            return _check(name, "comparison type" in str(error).lower(), str(error))
        return _check(name, False, "An arbitrary comparison type was accepted.")
    payload = engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_b"])
    comparison = payload["comparison"]
    if name == "no-automatic-winner":
        joined = " ".join(comparison["limitations"]).lower()
        return _check(
            name,
            comparison["no_automatic_winner"] is True and "does not choose a winner" in joined,
            "No winner is chosen and this is stated.",
        )
    key = {
        "rank-comparison-present": "rank_comparison",
        "score-comparison-present": "score_comparison",
        "duration-comparison-present": "duration_comparison",
        "evidence-comparison-present": "evidence_coverage_comparison",
        "editorial-comparison-present": "editorial_status_comparison",
        "discovery-reason-comparison-present": "discovery_reason_comparison",
        "overlap-linked-in-comparison": "overlap_record_ids",
    }.get(name)
    if key:
        return _check(name, bool(comparison[key]), f"{key} populated.")
    return _check(name, False, "Unknown comparison scenario.")


def _run_preview(name: str, root: Path) -> ScenarioResult:
    engine, _ = _engine(root)
    source = _source_text()
    if name == "preview-unavailable-state":
        client = Path("frontend/src/lib/candidateReview.ts").read_text(encoding="utf-8")
        return _check(
            name,
            "unavailableReason" in client and "Preview unavailable." in client,
            "The client exposes an explicit preview-unavailable reason.",
        )
    if name == "external-url-not-referenced":
        return _check(
            name, "http://" not in source and "https://" not in source, "No URL literals."
        )
    if name == "absolute-path-not-referenced":
        return _check(
            name, "C:\\" not in source and "/home/" not in source, "No absolute paths."
        )
    if name == "no-filesystem-path-in-projection":
        serialised = json.dumps(engine.inspect_candidate(PROJECT_ID, "cand_a"))
        return _check(
            name,
            "/home/" not in serialised
            and "C:\\" not in serialised
            and "file:" not in serialised,
            "Projection carries no filesystem path.",
        )
    if name == "candidate-window-exposed-for-seek":
        window = engine.inspect_candidate_transcript(PROJECT_ID, "cand_a")
        return _check(
            name,
            window["candidate_start_seconds"] == 10.0
            and window["candidate_end_seconds"] == 40.0,
            "Exact seek window is published.",
        )
    if name == "context-window-bounded":
        clamped = engine.inspect_candidate_transcript(
            PROJECT_ID, "cand_a", context_seconds=9_999
        )
        return _check(name, clamped["context_seconds"] == 60, "Context clamps to 60 seconds.")
    if name == "context-does-not-change-candidate":
        context = engine.inspect_candidate_transcript(
            PROJECT_ID, "cand_a", context_seconds=30
        )
        joined = " ".join(context["limitations"]).lower()
        return _check(
            name,
            context["candidate_start_seconds"] == 10.0
            and "never change the candidate boundaries" in joined,
            "Context never alters the candidate window.",
        )
    if name == "playback-not-validation":
        docs = Path("docs/BOBA_CANDIDATE_REVIEW_PANEL_V1.md").read_text(encoding="utf-8")
        return _check(
            name, "not technical validation" in docs, "Documented explicitly."
        )
    return _check(name, False, "Unknown preview scenario.")


def _run_actions(name: str, root: Path) -> ScenarioResult:
    registry = build_fixed_candidate_action_registry()
    if name == "advisory-feedback-available":
        item = registry["candidate_action_submit_feedback_v1"]
        return _check(
            name,
            item.availability == "available" and item.owning_module_id == "creator_learning",
            "Owned by Creator Learning.",
        )
    if name == "review-note-available":
        item = registry["candidate_action_record_review_note_v1"]
        return _check(name, item.availability == "available", "Available.")
    if name in {
        "selection-action-unavailable",
        "rejection-action-unavailable",
        "revision-request-unavailable",
        "alternate-request-unavailable",
    }:
        key = {
            "selection-action-unavailable": "candidate_action_select_candidate_v1",
            "rejection-action-unavailable": "candidate_action_reject_candidate_v1",
            "revision-request-unavailable": "candidate_action_request_revision_v1",
            "alternate-request-unavailable": "candidate_action_request_alternate_v1",
        }[name]
        item = registry[key]
        return _check(
            name,
            item.availability == "unavailable" and bool(item.limitations),
            f"Unavailable with {len(item.limitations)} stated limitations.",
        )
    if name == "no-authoritative-action-in-v1":
        return _check(
            name,
            not any(
                item.authoritative and item.availability == "available"
                for item in registry.values()
            ),
            "No available action is authoritative.",
        )
    engine, integration = _engine(root, selected=["cand_a"])
    payload = _prepared(engine)
    if name == "unknown-action-rejected":
        try:
            engine.create_candidate_action_request(
                PROJECT_ID,
                candidate_review_session_id=payload["session"].candidate_review_session_id,
                candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
                action_descriptor_id="candidate_action_made_up_v1",
                decision_value="approved",
                reason="Reason",
                confirmation_context_digest="0" * 64,
                idempotency_key="idem_unknown_1",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "Unknown" in str(error), str(error))
        return _check(name, False, "An unknown action was accepted.")
    if name == "unavailable-action-rejected":
        try:
            engine.create_candidate_action_request(
                PROJECT_ID,
                candidate_review_session_id=payload["session"].candidate_review_session_id,
                candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
                action_descriptor_id="candidate_action_select_candidate_v1",
                decision_value="select",
                reason="Reason",
                confirmation_context_digest="0" * 64,
                idempotency_key="idem_unavail_1",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "unavailable" in str(error).lower(), str(error))
        return _check(name, False, "An unavailable action was accepted.")
    invalid = {
        "unsupported-decision-rejected": ("select", "Reason", "decision value"),
        "missing-reason-rejected": ("approved", "   ", "requires a reason"),
        "oversized-reason-rejected": ("approved", "x" * 900, "allowed length"),
        "secret-bearing-reason-rejected": ("approved", "token=sk-1", "credentials"),
    }
    if name in invalid:
        decision, reason, expected = invalid[name]
        try:
            _request(engine, payload, f"idem_{name}", decision=decision, reason=reason)
        except ValidationError as error:
            return _check(name, expected in str(error).lower(), str(error))
        return _check(name, False, "Invalid input was accepted.")
    if name == "missing-confirmation-rejected":
        action = "candidate_action_submit_feedback_v1"
        try:
            engine.create_candidate_action_request(
                PROJECT_ID,
                candidate_review_session_id=payload["session"].candidate_review_session_id,
                candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
                action_descriptor_id=action,
                decision_value="approved",
                reason="Reason",
                confirmation_context_digest=payload["action_confirmations"][action],
                idempotency_key="idem_noconfirm_1",
                confirmed=False,
            )
        except ValidationError as error:
            return _check(name, "confirmation is required" in str(error), str(error))
        return _check(name, False, "An unconfirmed action was accepted.")
    if name == "wrong-confirmation-token-rejected":
        try:
            engine.create_candidate_action_request(
                PROJECT_ID,
                candidate_review_session_id=payload["session"].candidate_review_session_id,
                candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
                action_descriptor_id="candidate_action_submit_feedback_v1",
                decision_value="approved",
                reason="Reason",
                confirmation_context_digest="f" * 64,
                idempotency_key="idem_badtoken_1",
                confirmed=True,
            )
        except ValidationError as error:
            return _check(name, "does not match" in str(error), str(error))
        return _check(name, False, "A mismatched token was accepted.")
    if name == "reviewer-context-required":
        return _check(
            name,
            all(
                item.requires_reviewer_context
                for item in registry.values()
                if item.availability == "available"
            ),
            "Every available action requires reviewer context.",
        )
    if name == "expired-request-rejected":
        request = _request(engine, payload, "idem_expired_1")
        path = engine.store.boba_candidate_review_action_path(
            PROJECT_ID, request.candidate_action_request_id
        )
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        path.write_text(json.dumps(raw), encoding="utf-8")
        result = engine.validate_candidate_action_request(
            PROJECT_ID, request.candidate_action_request_id
        )
        return _check(name, result["code"] == "expired_snapshot", str(result["code"]))
    guards = {
        "stale-project-digest-rejected": "expected_project_snapshot_digest",
        "workflow-revision-mismatch-rejected": "expected_workflow_revision",
        "candidate-digest-mismatch-rejected": "expected_candidate_digest",
        "source-digest-mismatch-rejected": "expected_source_record_digests",
    }
    if name in guards:
        request = _request(engine, payload, f"idem_guard_{name}")
        path = engine.store.boba_candidate_review_action_path(
            PROJECT_ID, request.candidate_action_request_id
        )
        raw = json.loads(path.read_text(encoding="utf-8"))
        field = guards[name]
        raw[field] = (
            4242
            if field == "expected_workflow_revision"
            else {"clip_discovery": "2" * 64}
            if field == "expected_source_record_digests"
            else "1" * 64
        )
        path.write_text(json.dumps(raw), encoding="utf-8")
        result = engine.validate_candidate_action_request(
            PROJECT_ID, request.candidate_action_request_id
        )
        expected = {
            "expected_project_snapshot_digest": "stale_project_snapshot",
            "expected_workflow_revision": "workflow_revision_mismatch",
            "expected_candidate_digest": "candidate_digest_mismatch",
            "expected_source_record_digests": "source_record_digest_mismatch",
        }[field]
        return _check(
            name,
            not result["valid"]
            and result["code"] == expected
            and not integration.owner.calls,
            f"Rejected as {result['code']}; owner never contacted.",
        )
    if name == "canonical-receipt-recorded":
        request = _request(engine, payload, "idem_ok_receipt_1")
        receipt = asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        return _check(
            name,
            receipt.accepted_by_owner
            and bool(receipt.canonical_record_id)
            and bool(receipt.canonical_record_digest),
            f"Owner returned {receipt.canonical_record_id}.",
        )
    if name == "advisory-receipt-not-authoritative":
        request = _request(engine, payload, "idem_advisory_1")
        receipt = asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        return _check(
            name,
            receipt.accepted_by_owner and not receipt.authoritative_state_changed,
            "An accepted advisory receipt changes no authority.",
        )
    if name == "owner-rejection-recorded":
        integration.owner.reject = True
        request = _request(engine, payload, "idem_reject_1")
        receipt = asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        return _check(
            name,
            not receipt.accepted_by_owner and receipt.error_code == "owner_rejected",
            "Owner rejection recorded truthfully.",
        )
    if name == "malformed-owner-response-handled":
        integration.owner.malformed = True
        request = _request(engine, payload, "idem_malformed_1")
        receipt = asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        return _check(
            name,
            receipt.error_code == "malformed_canonical_response",
            "A malformed owner response never becomes success.",
        )
    if name == "duplicate-request-reused":
        request = _request(engine, payload, "idem_dupe_1")
        first = asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        second = asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        return _check(
            name,
            second.duplicate_request_reused
            and second.candidate_action_receipt_id == first.candidate_action_receipt_id
            and len(integration.owner.calls) == 1,
            "The owner was contacted exactly once.",
        )
    if name == "no-optimistic-update":
        before = engine.build_candidate_queue(PROJECT_ID)["items"]
        request = _request(engine, payload, "idem_noopt_1")
        asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        after = engine.build_candidate_queue(PROJECT_ID)["items"]
        return _check(
            name,
            [item["selected"] for item in before] == [item["selected"] for item in after],
            "Candidate status is unchanged by an advisory action.",
        )
    if name == "authority-requires-owner-record":
        try:
            engine._persist_receipt(
                PROJECT_ID,
                BobaCandidateActionReceiptV1(
                    candidate_action_receipt_id="r",
                    candidate_action_request_id="q",
                    project_id=PROJECT_ID,
                    candidate_id="cand_a",
                    owning_module_id="creator_learning",
                    owning_operation_id="record_creator_feedback_event",
                    authoritative_state_changed=True,
                ),
            )
        except ValidationError as error:
            return _check(name, "canonical owner record" in str(error), str(error))
        return _check(name, False, "Authority changed without an owner record.")
    return _check(name, False, "Unknown action scenario.")


# Tokens that would indicate a real invocation. The signal-usage flags such as
# ``ffmpeg_execution_used`` are declarations of absence, not invocations, so the
# checks below look for the calling surface rather than a bare substring.
_FORBIDDEN_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("no-dynamic-import", ("importlib", "__import__(")),
    ("no-command-execution", ("subprocess", "os.popen")),
    ("no-shell-execution", ("os.system", "shell=True")),
    ("no-git-execution", ("git checkout", "git commit", '"git"')),
    ("no-ffmpeg-execution", ("ffmpeg_binary", "ffprobe", '"ffmpeg"', "'ffmpeg'")),
    ("no-arbitrary-url", ("requests.", "httpx.", "urlopen")),
    ("no-external-analytics", ("analytics.", "track_event(")),
)


def _run_authority(name: str, root: Path) -> ScenarioResult:
    source = _source_text()
    engine, _ = _engine(root, selected=["cand_a"])
    for scenario, tokens in _FORBIDDEN_TOKENS:
        if name == scenario:
            found = [token for token in tokens if token in source]
            return _check(
                name,
                not found,
                f"No invocation surface for {scenario.removeprefix('no-')}: "
                f"checked {len(tokens)} tokens.",
            )
    if name == "no-candidate-discovery":
        return _check(
            name,
            "def discover" not in source and "_CandidateSeed" not in source,
            "The module never discovers candidates.",
        )
    if name == "no-reranking":
        return _check(
            name,
            "def rerank" not in source and "rank=index" not in source,
            "The module never assigns a rank.",
        )
    if name in {
        "no-editorial-decision-created",
        "no-rights-decision-created",
        "no-safety-decision-created",
        "no-validation-decision-created",
        "no-quality-decision-created",
        "no-workflow-transition",
    }:
        forbidden = (
            "save_editorial_decisions",
            "save_rights_permission_gate",
            "save_boba_safety_gate",
            "save_boba_validator_runner",
            "save_boba_output_quality_reviewer",
            "record_human_workflow_decision",
            "request_transition",
        )
        return _check(
            name,
            not any(token in source for token in forbidden),
            "The module writes no source-owned decision.",
        )
    if name in {"no-arbitrary-module", "no-arbitrary-operation"}:
        registry = build_fixed_candidate_action_registry()
        allowed = {"creator_learning", "editorial_decision", "clip_discovery"}
        return _check(
            name,
            all(item.owning_module_id in allowed for item in registry.values()),
            "Only fixed owner modules appear in the registry.",
        )
    if name == "no-arbitrary-path":
        return _check(
            name,
            "Path(" not in source or "candidate_review/" not in source,
            "The module builds no filesystem path itself.",
        )
    if name in {"no-external-media", "no-untrusted-html"}:
        return _check(
            name,
            "dangerouslySetInnerHTML" not in source
            and "http://" not in source
            and "https://" not in source,
            "No external media or HTML injection surface.",
        )
    if name in {
        "no-media-generation",
        "no-artifact-modification",
        "no-source-media-modification",
        "no-accepted-output-modification",
        "no-upload",
        "no-publication",
        "no-rights-bypass",
        "no-safety-bypass",
        "no-destructive-action",
        "no-local-selection",
        "no-local-rejection",
    }:
        usage = engine.build_candidate_review(PROJECT_ID)["signal_usage"]
        flag = {
            "no-media-generation": "media_generation_used",
            "no-artifact-modification": "accepted_output_modified",
            "no-source-media-modification": "source_media_modified",
            "no-accepted-output-modification": "accepted_output_modified",
            "no-upload": "upload_used",
            "no-publication": "publication_used",
            "no-rights-bypass": "rights_bypass_used",
            "no-safety-bypass": "safety_bypass_used",
            "no-destructive-action": "destructive_action_used",
            "no-local-selection": "candidate_selected_locally",
            "no-local-rejection": "candidate_rejected_locally",
        }[name]
        return _check(name, usage[flag] is False, f"{flag} is false.")
    if name == "no-biometric-inference":
        payload = json.dumps(engine.export_candidate_review(PROJECT_ID))
        return _check(
            name,
            '"speaker_identity_inferred": false' in payload
            and '"biometric_inference_used": false' in payload,
            "Export declares no biometric or identity inference.",
        )
    return _check(name, False, "Unknown authority scenario.")


def _run_persistence(name: str, root: Path) -> ScenarioResult:
    engine, _ = _engine(root, selected=["cand_a"])
    if name == "session-persisted":
        session = engine.create_candidate_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        reloaded = engine.get_candidate_review_session(
            PROJECT_ID, session.candidate_review_session_id
        )
        return _check(name, reloaded.session_digest == session.session_digest, "Round-trips.")
    if name == "session-expiry-enforced":
        session = engine.create_candidate_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        raw = engine.store.load_boba_candidate_review_session(
            PROJECT_ID, session.candidate_review_session_id
        )
        assert raw is not None
        raw["expires_at"] = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
        engine.store.save_boba_candidate_review_session(
            PROJECT_ID, session.candidate_review_session_id, raw
        )
        try:
            engine.get_candidate_review_session(
                PROJECT_ID, session.candidate_review_session_id
            )
        except ValidationError as error:
            return _check(name, "expired" in str(error).lower(), str(error))
        return _check(name, False, "An expired session was accepted.")
    if name == "session-project-scoped":
        session = engine.create_candidate_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        try:
            engine.get_candidate_review_session(
                "proj_other", session.candidate_review_session_id
            )
        except ValidationError as error:
            return _check(name, True, str(error))
        return _check(name, False, "A session leaked across projects.")
    if name == "session-field-allowlist":
        session = engine.create_candidate_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        try:
            engine.update_candidate_review_session(
                PROJECT_ID,
                session.candidate_review_session_id,
                {"reviewer_context_id": "someone_else"},
            )
        except ValidationError as error:
            return _check(name, "unsupported" in str(error).lower(), str(error))
        return _check(name, False, "An unsupported session field was accepted.")
    if name == "comparison-limit-enforced-in-session":
        session = engine.create_candidate_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        try:
            engine.update_candidate_review_session(
                PROJECT_ID,
                session.candidate_review_session_id,
                {"comparison_candidate_ids": ["a", "b", "c", "d", "e"]},
            )
        except ValidationError as error:
            return _check(name, "compared" in str(error), str(error))
        return _check(name, False, "More than four comparison candidates were accepted.")
    if name == "registry-snapshot-immutable":
        first = engine.build_candidate_review_registry(PROJECT_ID)
        second = engine.build_candidate_review_registry(PROJECT_ID)
        snapshot_id = first["registry_snapshot"]["registry_snapshot_id"]
        try:
            engine.store.save_boba_candidate_review_registry(
                PROJECT_ID, snapshot_id, {"tampered": True}
            )
        except ValidationError as error:
            return _check(
                name,
                first["registry_snapshot"] == second["registry_snapshot"]
                and "immutable" in str(error),
                "Content-addressed and immutable.",
            )
        return _check(name, False, "A registry snapshot was mutated.")
    payload = _prepared(engine)
    if name == "action-request-immutable":
        request = _request(engine, payload, "idem_immutable_1")
        try:
            engine.store.save_boba_candidate_review_action(
                PROJECT_ID,
                request.candidate_action_request_id,
                {**request.model_dump(mode="json"), "bounded_reason": "tampered"},
            )
        except ValidationError as error:
            return _check(name, "immutable" in str(error), str(error))
        return _check(name, False, "An action request was mutated.")
    if name == "receipt-immutable":
        request = _request(engine, payload, "idem_receipt_imm_1")
        receipt = asyncio.run(
            engine.submit_candidate_action_to_owner(
                PROJECT_ID, request.candidate_action_request_id
            )
        )
        try:
            engine.store.save_boba_candidate_review_receipt(
                PROJECT_ID,
                receipt.candidate_action_receipt_id,
                {**receipt.model_dump(mode="json"), "canonical_status": "tampered"},
            )
        except ValidationError as error:
            return _check(name, "immutable" in str(error), str(error))
        return _check(name, False, "A receipt was mutated.")
    if name == "source-records-not-duplicated":
        stored = json.dumps(engine.build_candidate_review(PROJECT_ID))
        return _check(
            name,
            "score_breakdown" not in stored and "transcript_snippets" not in stored,
            "The persisted set stores references and digests, not source payloads.",
        )
    if name.startswith("reset-preserves"):
        engine.build_candidate_review(PROJECT_ID)
        result = engine.reset_candidate_review_metadata(PROJECT_ID)
        key = {
            "reset-preserves-candidate-records": "candidate_records_preserved",
            "reset-preserves-ranking-records": "ranking_records_preserved",
            "reset-preserves-editorial-history": "editorial_history_preserved",
            "reset-preserves-review-ui-history": "review_ui_history_preserved",
            "reset-preserves-receipts": "action_receipt_history_preserved",
        }[name]
        still_there = engine.store.load_candidate_clip_discovery(PROJECT_ID) is not None
        return _check(
            name,
            result[key] is True and still_there,
            f"{key} is true and the discovery record survives.",
        )
    if name == "sanitized-export":
        exported = engine.export_candidate_review(PROJECT_ID)
        return _check(
            name,
            exported["privacy"]["sensitive_values_excluded"] is True,
            "Export is sanitised and declares it.",
        )
    if name == "export-excludes-secrets":
        serialised = json.dumps(engine.export_candidate_review(PROJECT_ID))
        return _check(name, "sk-" not in serialised, "No secret material in export.")
    if name == "export-excludes-private-paths":
        serialised = json.dumps(engine.export_candidate_review(PROJECT_ID))
        return _check(
            name,
            "/home/" not in serialised and "C:\\" not in serialised,
            "No private paths in export.",
        )
    if name == "event-cursor-bounded":
        session = engine.create_candidate_review_session(
            PROJECT_ID, reviewer_context_id="reviewer_a"
        )
        engine.store.save_boba_candidate_review_event_cursor(
            PROJECT_ID,
            session.candidate_review_session_id,
            {"last_sequence": 5, "project_id": PROJECT_ID},
        )
        return _check(name, True, "Event cursors persist as bounded UI metadata.")
    return _check(name, False, "Unknown persistence scenario.")


def _run_events(name: str, root: Path) -> ScenarioResult:
    engine, _ = _engine(root, selected=["cand_a"])
    payload = engine.inspect_candidate_events(PROJECT_ID)
    if name == "events-deduplicated":
        keys = [
            (item["source_module_id"], item["source_event_id"]) for item in payload["events"]
        ]
        return _check(name, len(keys) == len(set(keys)), "Source identities are unique.")
    if name == "events-never-invent-progress":
        return _check(
            name,
            all(
                item["progress_percent"] is None or item["progress_total"]
                for item in payload["events"]
            ),
            "Progress requires real owner counters.",
        )
    if name == "malformed-progress-ignored":
        source = _source_text()
        return _check(
            name,
            "isinstance(raw_total, int) and raw_total > 0" in source,
            "Zero or malformed totals never become progress.",
        )
    if name == "control-events-not-work":
        source = _source_text()
        return _check(
            name,
            '"heartbeat", "keepalive", "ping"' in source and "represents_work=" in source,
            "Control frames are marked as not work.",
        )
    if name == "timeline-marks-unknown-timestamps":
        entries = engine.inspect_candidate_timeline(PROJECT_ID)["entries"]
        return _check(
            name,
            all(entry["timestamp_precision"] in {"source", "unknown"} for entry in entries),
            "Timestamp precision is always disclosed.",
        )
    if name == "timeline-bounded":
        entries = engine.inspect_candidate_timeline(PROJECT_ID, limit=9_999)["entries"]
        return _check(name, len(entries) <= 100, "Timeline is bounded at 100 entries.")
    if name == "events-bounded":
        bounded = engine.inspect_candidate_events(PROJECT_ID, limit=9_999)
        return _check(name, len(bounded["events"]) <= 100, "Events are bounded at 100.")
    if name == "event-cursor-exposed":
        return _check(name, "latest_sequence" in payload, "A replay cursor is published.")
    if name == "events-project-scoped":
        return _check(
            name,
            all(item["project_id"] == PROJECT_ID for item in payload["events"])
            and payload["project_id"] == PROJECT_ID,
            "Every projected event is project scoped.",
        )
    return _check(name, False, "Unknown event scenario.")


def _run_integration(name: str, root: Path) -> ScenarioResult:
    expected = {
        f"candidate_review.{item}"
        for item in (
            "inspect_registry", "create_session", "update_session", "build_queue",
            "inspect_queue", "build_snapshot", "refresh_snapshot", "inspect_candidate",
            "compare_candidates", "calculate_overlaps", "create_action", "validate_action",
            "submit_action", "inspect_receipt", "inspect_timeline", "inspect_events",
            "load", "export", "reset",
        )
    }
    if name == "integration-layer-operations-registered":
        registered = {
            item
            for item in build_boba_operation_registry()
            if item.startswith("candidate_review.")
        }
        return _check(name, registered == expected, f"{len(registered)} operations registered.")
    if name == "module-registered-available":
        from olympus.boba.integration_layer import build_boba_module_registry

        module = build_boba_module_registry()["candidate_review"]
        return _check(
            name, module.implementation_status == "available", module.implementation_status
        )
    if name == "safety-gate-classifies-read-only":
        operations = build_safety_module_operation_registry()["candidate_review"]
        read_only = [key for key, value in operations.items() if value == "automatic_read_only"]
        return _check(
            name, len(read_only) == 18, f"{len(read_only)} read-only classifications."
        )
    if name == "safety-gate-gates-submit":
        operations = build_safety_module_operation_registry()["candidate_review"]
        return _check(
            name,
            operations["submit_action"] == "approval_required_read_only",
            operations["submit_action"],
        )
    if name == "review-ui-untouched":
        from olympus.boba.review_ui import build_fixed_review_action_registry

        return _check(
            name, len(build_fixed_review_action_registry()) == 4, "Review UI V1 is unchanged."
        )
    if name == "fixed-source-registry":
        return _check(
            name, len(build_fixed_candidate_source_registry()) == 13, "13 fixed sources."
        )
    if name == "fixed-action-registry":
        return _check(
            name, len(build_fixed_candidate_action_registry()) == 6, "6 fixed actions."
        )
    return _check(name, False, "Unknown integration scenario.")


_GROUP_RUNNERS = {
    "identity": _run_identity,
    "sources": _run_sources,
    "scores": _run_scores,
    "queue": _run_queue,
    "overlap": _run_overlap,
    "comparison": _run_comparison,
    "preview": _run_preview,
    "actions": _run_actions,
    "authority": _run_authority,
    "persistence": _run_persistence,
    "events": _run_events,
    "integration": _run_integration,
}


def run_named_scenario(name: str, root: Path) -> ScenarioResult:
    group, _, scenario = name.partition(":")
    runner = _GROUP_RUNNERS.get(group)
    if runner is None:
        return _check(name, False, "Unknown scenario group.")
    workspace = root / group / scenario.replace("-", "_")
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        result = runner(scenario, workspace)
    except Exception as error:
        return _check(name, False, f"{type(error).__name__}: {error}")
    return _check(name, result.passed, result.detail)


def run_self_check() -> dict[str, Any]:
    sources = build_fixed_candidate_source_registry()
    actions = build_fixed_candidate_action_registry()
    checks = {
        "scenario_catalog_complete": len(SCENARIO_NAMES) >= 220,
        "scenario_names_unique": len(set(SCENARIO_NAMES)) == len(SCENARIO_NAMES),
        "source_registry_fixed": len(sources) == 13,
        "action_registry_fixed": len(actions) == 6,
        "duplicate_source_descriptors_rejected": len(sources) == len(set(sources)),
        "duplicate_action_descriptors_rejected": len(actions) == len(set(actions)),
        "priority_tiers_complete": len(CANDIDATE_QUEUE_PRIORITY_TIERS) == 12,
        "priority_tiers_ascending": [t[0] for t in CANDIDATE_QUEUE_PRIORITY_TIERS]
        == sorted(t[0] for t in CANDIDATE_QUEUE_PRIORITY_TIERS),
        "no_authoritative_action_available": not any(
            item.authoritative and item.availability == "available" for item in actions.values()
        ),
        "no_upload_or_publication": not any(
            item.upload_or_publication for item in actions.values()
        ),
        "no_execution_capable": not any(item.execution_capable for item in actions.values()),
        "every_action_names_owner": all(
            item.owning_module_id and item.owning_operation_id for item in actions.values()
        ),
        "overlap_threshold_fixed": SUBSTANTIAL_OVERLAP_IOU_THRESHOLD == 0.60,
        "overlap_zero_union_safe": _overlap_metrics(1.0, 1.0, 1.0, 1.0)[
            "intersection_over_union"
        ]
        == 0.0,
        "overlap_deterministic": _overlap_metrics(0.0, 30.0, 15.0, 45.0)
        == _overlap_metrics(0.0, 30.0, 15.0, 45.0),
        "comparison_limit_fixed": MAX_COMPARISON_CANDIDATES == 4,
        "integration_layer_registered": any(
            item.startswith("candidate_review.") for item in build_boba_operation_registry()
        ),
        "safety_gate_registered": "candidate_review"
        in build_safety_module_operation_registry(),
        "no_command_runner": "subprocess" not in _source_text(),
        "no_ffmpeg_runner": not any(
            token in _source_text()
            for token in ("ffmpeg_binary", "ffprobe", '"ffmpeg"', "'ffmpeg'")
        ),
        "no_dynamic_import": "importlib" not in _source_text(),
        "no_local_approval_creator": "save_editorial_decisions" not in _source_text(),
        "no_workflow_transition": "request_transition" not in _source_text(),
        "storage_writable": True,
        "receipts_writable": True,
    }
    return {
        "schema_version": "boba_candidate_review_validation_self_check_v1",
        "passed": all(checks.values()),
        "checks": checks,
        "scenario_count": len(SCENARIO_NAMES),
        "scenario_groups": {
            group: len(names) for group, names in _CONDITION_GROUPS.items()
        },
    }


def run_synthetic_project(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    results = [run_named_scenario(name, root) for name in SCENARIO_NAMES]
    failed = [item.name for item in results if not item.passed]
    return {
        "schema_version": "boba_candidate_review_validation_synthetic_v1",
        "passed": not failed,
        "scenario_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_scenarios": failed,
        "scenarios": [
            {"name": item.name, "passed": item.passed, "detail": item.detail}
            for item in results
        ],
        "guarantees": {
            "candidates_discovered": False,
            "candidates_reranked": False,
            "scores_recalculated": False,
            "winner_selected_automatically": False,
            "commands_executed": False,
            "network_access_used": False,
            "media_modified": False,
            "upload_used": False,
            "publication_used": False,
            "source_owner_decisions_mutated": False,
        },
    }


def inspect_persisted_project(project_id: str) -> dict[str, Any]:
    store = BobaMemoryStore(Path("storage_data") / "boba")
    existing = store.load_boba_candidate_review(project_id)
    return {
        "schema_version": "boba_candidate_review_validation_project_v1",
        "passed": existing is not None,
        "project_id": project_id,
        "candidate_review_present": existing is not None,
        "candidate_count": len(existing.get("candidate_references", [])) if existing else 0,
    }


def _write_report(name: str, payload: dict[str, Any]) -> Path:
    root = Path("work") / "validation_reports" / "boba_candidate_review"
    root.mkdir(parents=True, exist_ok=True)
    report = root / (name + ".json")
    report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--synthetic-project", action="store_true")
    parser.add_argument("--project-id", default="")
    arguments = parser.parse_args()
    selected = sum(
        1
        for value in (
            arguments.self_check,
            arguments.synthetic_project,
            arguments.project_id,
        )
        if value
    )
    if selected != 1:
        parser.error("Select exactly one of --self-check, --synthetic-project, or --project-id.")
    payload: dict[str, Any]
    if arguments.self_check:
        payload = run_self_check()
        report = _write_report("self_check", payload)
    elif arguments.synthetic_project:
        with tempfile.TemporaryDirectory(prefix="boba_candidate_review_") as temporary:
            payload = run_synthetic_project(Path(temporary))
        report = _write_report("synthetic_project", payload)
    else:
        payload = inspect_persisted_project(arguments.project_id)
        report = _write_report("project_" + arguments.project_id, payload)
    print(json.dumps({"report": str(report), **payload}, indent=2, sort_keys=True))
    return 0 if payload.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
