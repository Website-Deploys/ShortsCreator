"""BOBA Candidate Review Panel V1 contracts, projection, overlap, routing, API tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from tools._boba_candidate_review_fixtures import (
    seed_project,
    synthetic_candidate,
    synthetic_discovery,
    synthetic_ranked,
    synthetic_ranking,
)
from tools.validate_boba_candidate_review import (
    SCENARIO_NAMES,
    run_named_scenario,
    run_self_check,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.candidate_review import (
    CANDIDATE_QUEUE_PRIORITY_TIERS,
    MAX_COMPARISON_CANDIDATES,
    SUBSTANTIAL_OVERLAP_IOU_THRESHOLD,
    BobaCandidateActionDescriptorV1,
    BobaCandidateActionReceiptV1,
    BobaCandidateActionRequestV1,
    BobaCandidateComparisonV1,
    BobaCandidateOverlapV1,
    BobaCandidateQueueItemV1,
    BobaCandidateReferenceV1,
    BobaCandidateReviewEventV1,
    BobaCandidateReviewNotificationV1,
    BobaCandidateReviewRegistrySnapshotV1,
    BobaCandidateReviewSessionV1,
    BobaCandidateReviewSetV1,
    BobaCandidateReviewSignalUsageV1,
    BobaCandidateReviewSummaryV1,
    BobaCandidateReviewTimelineEntryV1,
    BobaCandidateReviewV1,
    BobaCandidateScoreCardV1,
    BobaCandidateSnapshotV1,
    BobaCandidateSourceCardV1,
    _overlap_metrics,
    build_fixed_candidate_action_registry,
    build_fixed_candidate_source_registry,
)
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.review_ui import build_fixed_review_action_registry
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError, register_exception_handlers
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_candidate_review_test"

CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaCandidateReviewRegistrySnapshotV1,
    BobaCandidateReferenceV1,
    BobaCandidateReviewSessionV1,
    BobaCandidateQueueItemV1,
    BobaCandidateSourceCardV1,
    BobaCandidateScoreCardV1,
    BobaCandidateOverlapV1,
    BobaCandidateComparisonV1,
    BobaCandidateActionDescriptorV1,
    BobaCandidateActionRequestV1,
    BobaCandidateActionReceiptV1,
    BobaCandidateSnapshotV1,
    BobaCandidateReviewEventV1,
    BobaCandidateReviewTimelineEntryV1,
    BobaCandidateReviewNotificationV1,
    BobaCandidateReviewSummaryV1,
    BobaCandidateReviewSignalUsageV1,
    BobaCandidateReviewSetV1,
)


class _StubOwner:
    """Stands in for Creator Learning, the canonical owner of feedback events."""

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
            "user_action": kwargs.get("user_action"),
        }


def _engine(tmp_path: Path, **seed: Any) -> tuple[BobaCandidateReviewV1, _StubOwner]:
    store = BobaMemoryStore(tmp_path / "boba")
    owner = _StubOwner()
    engine = BobaCandidateReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


def _prepared(
    engine: BobaCandidateReviewV1, candidate_id: str = "cand_a"
) -> dict[str, Any]:
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    payload = engine.build_candidate_snapshot(
        PROJECT_ID, session.candidate_review_session_id, candidate_id
    )
    payload["session"] = session
    return payload


_FEEDBACK = "candidate_action_submit_feedback_v1"


def _request(
    engine: BobaCandidateReviewV1,
    payload: dict[str, Any],
    key: str,
    *,
    action: str = _FEEDBACK,
    decision: str | None = "approved",
    reason: str = "Reviewed the exact candidate window.",
) -> BobaCandidateActionRequestV1:
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


# ---------------------------------------------------------------------------
# Contracts and registries
# ---------------------------------------------------------------------------
def test_every_contract_forbids_unknown_fields() -> None:
    for contract in CONTRACT_TYPES:
        assert contract.model_config.get("extra") == "forbid", contract.__name__


def test_source_registry_is_fixed_and_unique() -> None:
    registry = build_fixed_candidate_source_registry()
    assert len(registry) == 13
    assert len(set(registry)) == 13
    assert [key for key, item in registry.items() if item["required"]] == ["clip_discovery"]


def test_advisory_sources_are_marked_advisory() -> None:
    registry = build_fixed_candidate_source_registry()
    for module_id in ("explanation", "clip_brief", "hook_retention", "caption_motion",
                      "music_mood"):
        assert registry[module_id]["advisory_only"] is True
    for module_id in ("clip_discovery", "clip_ranking", "editorial_decision", "safety_gate"):
        assert registry[module_id]["advisory_only"] is False


def test_action_registry_declares_six_actions_with_owners() -> None:
    registry = build_fixed_candidate_action_registry()
    assert len(registry) == 6
    for descriptor in registry.values():
        assert descriptor.owning_module_id
        assert descriptor.owning_operation_id
        assert not descriptor.upload_or_publication
        assert not descriptor.execution_capable
        assert not descriptor.destructive


def test_only_advisory_actions_are_available_in_v1() -> None:
    registry = build_fixed_candidate_action_registry()
    available = [item for item in registry.values() if item.availability == "available"]
    assert {item.action_descriptor_id for item in available} == {
        "candidate_action_submit_feedback_v1",
        "candidate_action_record_review_note_v1",
    }
    assert all(item.authoritative is False for item in available)
    assert all(item.owning_module_id == "creator_learning" for item in available)


@pytest.mark.parametrize(
    "action_id",
    [
        "candidate_action_select_candidate_v1",
        "candidate_action_reject_candidate_v1",
        "candidate_action_request_revision_v1",
        "candidate_action_request_alternate_v1",
    ],
)
def test_authoritative_actions_are_unavailable_with_stated_limitations(action_id: str) -> None:
    descriptor = build_fixed_candidate_action_registry()[action_id]
    assert descriptor.availability == "unavailable"
    assert descriptor.authoritative is True
    assert descriptor.limitations, "An unavailable action must explain why."


def test_available_actions_declare_what_they_do_not_do() -> None:
    registry = build_fixed_candidate_action_registry()
    feedback = registry[_FEEDBACK]
    joined = " ".join(feedback.does_not_do).lower()
    assert "does not select or reject the candidate editorially" in joined
    assert "rank" in joined
    assert "upload" in joined


def test_registry_snapshot_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first = engine.build_candidate_review_registry(PROJECT_ID)
    second = engine.build_candidate_review_registry(PROJECT_ID)
    assert first["registry_snapshot"] == second["registry_snapshot"]
    with pytest.raises(ValidationError, match="immutable"):
        engine.store.save_boba_candidate_review_registry(
            PROJECT_ID, first["registry_snapshot"]["registry_snapshot_id"], {"x": 1}
        )


def test_registry_reports_available_and_unavailable_sources(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    snapshot = engine.build_candidate_review_registry(PROJECT_ID)["registry_snapshot"]
    assert "clip_discovery" in snapshot["available_source_ids"]
    assert "safety_gate" in snapshot["unavailable_source_ids"]


# ---------------------------------------------------------------------------
# Candidate identity and exact ranges
# ---------------------------------------------------------------------------
def test_candidate_reference_preserves_exact_source_window(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("cand_x", 12.345, 48.678)])
    reference = engine.build_candidate_references(PROJECT_ID)[0]
    assert reference.candidate_id == "cand_x"
    assert reference.start_seconds == 12.345
    assert reference.end_seconds == 48.678
    assert reference.duration_seconds == 36.333


def test_candidate_reference_rejects_inverted_range() -> None:
    with pytest.raises(PydanticValidationError, match="greater than"):
        BobaCandidateReferenceV1(
            candidate_reference_id="r",
            project_id=PROJECT_ID,
            candidate_id="c",
            source_record_id="s",
            source_record_digest="0" * 64,
            start_seconds=40.0,
            end_seconds=10.0,
            duration_seconds=30.0,
        )


def test_candidate_reference_rejects_zero_duration() -> None:
    with pytest.raises(PydanticValidationError):
        BobaCandidateReferenceV1(
            candidate_reference_id="r",
            project_id=PROJECT_ID,
            candidate_id="c",
            source_record_id="s",
            source_record_digest="0" * 64,
            start_seconds=10.0,
            end_seconds=10.0,
            duration_seconds=0.0,
        )


def test_candidate_reference_rejects_duration_mismatch() -> None:
    with pytest.raises(PydanticValidationError, match="exact persisted source range"):
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


def test_cross_project_candidate_rows_are_excluded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, seed=False)
    engine.store.save_candidate_clip_discovery(
        synthetic_discovery(
            PROJECT_ID, [synthetic_candidate("cand_other", "proj_other", 5.0, 15.0)]
        )
    )
    assert engine.build_candidate_references(PROJECT_ID) == []


def test_unknown_candidate_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="unknown, unavailable"):
        engine.inspect_candidate(PROJECT_ID, "cand_missing")


def test_candidate_revision_identity_is_absent(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    references = engine.build_candidate_references(PROJECT_ID)
    assert references
    assert all(item.candidate_revision_id is None for item in references)


def test_speaker_references_are_never_inferred(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    assert all(
        item.speaker_reference_ids == []
        for item in engine.build_candidate_references(PROJECT_ID)
    )


def test_transcript_segment_ids_come_from_the_owner(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    reference = next(
        item
        for item in engine.build_candidate_references(PROJECT_ID)
        if item.candidate_id == "cand_a"
    )
    assert reference.transcript_segment_ids == ["seg_cand_a"]


def test_candidate_count_is_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    assert len(engine.build_candidate_references(PROJECT_ID)) == 4


# ---------------------------------------------------------------------------
# Source cards
# ---------------------------------------------------------------------------
def test_source_cards_preserve_original_status_and_rank(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    cards = {
        card.source_module_id: card
        for card in engine.build_source_cards(PROJECT_ID, "cand_a")
    }
    assert cards["clip_discovery"].original_status == "discovered"
    assert cards["clip_ranking"].original_status == "strong_candidate"
    assert cards["clip_ranking"].original_rank == 1
    assert cards["editorial_decision"].original_status == "selected"


def test_missing_source_reports_unavailable_and_never_a_pass(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, seed=False)
    cards = engine.build_source_cards(PROJECT_ID, "cand_a")
    assert cards
    for card in cards:
        assert card.original_status == "unavailable"
        assert card.current is False
        assert any("never treated as a pass" in item for item in card.limitations)


def test_ranking_rejection_is_preserved_as_rejected(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, rejected=["cand_d"])
    card = next(
        item
        for item in engine.build_source_cards(PROJECT_ID, "cand_d")
        if item.source_module_id == "clip_ranking"
    )
    assert card.original_status == "rejected"
    assert card.blocking is True


def test_advisory_cards_declare_advisory_limitation(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    card = next(
        item
        for item in engine.build_source_cards(PROJECT_ID, "cand_a")
        if item.source_module_id == "explanation"
    )
    assert card.advisory_only is True


def test_every_source_card_carries_a_digest(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    for card in engine.build_source_cards(PROJECT_ID, "cand_a"):
        assert len(card.source_record_digest) == 64


# ---------------------------------------------------------------------------
# Score cards
# ---------------------------------------------------------------------------
def test_discovery_scores_keep_their_zero_to_one_scale(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    card = next(
        item
        for item in engine.build_score_cards(PROJECT_ID, "cand_a")
        if item.score_name == "confidence"
    )
    assert card.source_module_id == "clip_discovery"
    assert (card.score_scale_min, card.score_scale_max) == (0.0, 1.0)
    assert card.score_value == 0.81


def test_ranking_scores_keep_their_zero_to_hundred_scale(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    card = next(
        item
        for item in engine.build_score_cards(PROJECT_ID, "cand_a")
        if item.score_name == "total_score"
    )
    assert (card.score_scale_min, card.score_scale_max) == (0.0, 100.0)
    assert card.source_owned_composite is True
    assert card.rank == 1


def test_only_the_owner_composite_is_marked_composite(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    cards = engine.build_score_cards(PROJECT_ID, "cand_a")
    assert sum(1 for item in cards if item.source_owned_composite) == 1


def test_no_weight_is_shown_when_the_owner_persists_none(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    cards = engine.build_score_cards(PROJECT_ID, "cand_a")
    assert cards
    assert all(item.weight is None for item in cards)
    assert all(
        item.weighted_by_source is False
        for item in cards
        if item.score_name != "total_score"
    )


def test_penalty_components_are_lower_is_better(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    cards = {item.score_name: item for item in engine.build_score_cards(PROJECT_ID, "cand_a")}
    for name in ("overlap_penalty", "repetition_penalty", "rights_safety_penalty",
                 "context_risk_score"):
        assert cards[name].score_direction == "lower_is_better"
    assert cards["hook_score"].score_direction == "higher_is_better"


def test_every_score_carries_a_definition(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    for card in engine.build_score_cards(PROJECT_ID, "cand_a"):
        assert len(card.score_definition) > 20


def test_scores_disclaim_probability_and_virality(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    joined = " ".join(
        " ".join(card.limitations) for card in engine.build_score_cards(PROJECT_ID, "cand_a")
    ).lower()
    assert "not a probability" in joined
    assert "virality" in joined


def test_editorial_confidence_is_flagged_incomparable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    card = next(
        item
        for item in engine.build_score_cards(PROJECT_ID, "cand_a")
        if item.score_name == "editorial_confidence"
    )
    assert card.comparable_across_candidates is False
    assert card.score_scale_max == 1.0


def test_equal_owner_scores_are_reported_as_tied(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, seed=False)
    rows = [("cand_t1", 10.0, 30.0), ("cand_t2", 100.0, 120.0)]
    engine.store.save_candidate_clip_discovery(
        synthetic_discovery(
            PROJECT_ID, [synthetic_candidate(c, PROJECT_ID, s, e) for c, s, e in rows]
        )
    )
    engine.store.save_clip_ranking(
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
        for item in engine.build_score_cards(PROJECT_ID, "cand_t1")
        if item.score_name == "total_score"
    )
    assert card.tied is True


def test_thirteen_ranking_component_scores_are_projected(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    ranking = [
        item
        for item in engine.build_score_cards(PROJECT_ID, "cand_a")
        if item.source_module_id == "clip_ranking"
    ]
    assert len(ranking) == 14  # 13 components plus the owner's own total_score


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------
def test_queue_exposes_twelve_ascending_priority_tiers() -> None:
    priorities = [tier[0] for tier in CANDIDATE_QUEUE_PRIORITY_TIERS]
    assert len(CANDIDATE_QUEUE_PRIORITY_TIERS) == 12
    assert priorities == sorted(priorities)
    assert len({tier[1] for tier in CANDIDATE_QUEUE_PRIORITY_TIERS}) == 12


def test_queue_order_is_deterministic(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    first = engine.build_candidate_queue(PROJECT_ID)["items"]
    second = engine.build_candidate_queue(PROJECT_ID)["items"]
    assert [item["candidate_id"] for item in first] == [
        item["candidate_id"] for item in second
    ]
    keys = [item["deterministic_sort_key"] for item in first]
    assert keys == sorted(keys)


def test_selected_candidate_with_block_is_tier_ten() -> None:
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
    assert (priority, status) == (10, "blocked")
    assert reason == "selected_candidate_with_critical_rights_or_safety_block"


def test_candidate_without_editorial_decision_requires_human_review(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, with_editorial=False)
    items = engine.build_candidate_queue(PROJECT_ID)["items"]
    assert items
    for item in items:
        assert item["priority_tier"] == 20
        assert item["human_action_required"] is True
        assert item["review_status"] == "awaiting_human_review"


def test_source_shortlisted_candidate_is_tier_sixty(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"], recommended=["cand_a"])
    item = next(
        entry
        for entry in engine.build_candidate_queue(PROJECT_ID)["items"]
        if entry["candidate_id"] == "cand_a"
    )
    assert item["priority_tier"] == 60
    assert item["editorial_status"] == "selected"


def test_rejected_candidates_stay_visible_in_their_own_tier(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, rejected=["cand_d"], selected=["cand_a"])
    item = next(
        entry
        for entry in engine.build_candidate_queue(PROJECT_ID)["items"]
        if entry["candidate_id"] == "cand_d"
    )
    assert item["rejected"] is True
    assert item["priority_tier"] == 100


def test_missing_evidence_is_counted_not_hidden(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, with_ranking=False, with_editorial=False)
    item = engine.build_candidate_queue(PROJECT_ID)["items"][0]
    assert item["missing_evidence_count"] >= 2


def test_queue_items_retain_source_identity_and_digests(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    for item in engine.build_candidate_queue(PROJECT_ID)["items"]:
        assert item["source_module_ids"]
        assert item["source_record_digests"]
        assert all(len(value) == 64 for value in item["source_record_digests"].values())


def test_queue_preserves_owner_rank_and_names_the_owner(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    item = next(
        entry
        for entry in engine.build_candidate_queue(PROJECT_ID)["items"]
        if entry["candidate_id"] == "cand_a"
    )
    assert item["original_rank"] == 1
    assert item["original_rank_total"] == 4
    assert item["rank_owner_module_id"] == "clip_ranking"


def test_primary_score_names_its_owner(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    item = engine.build_candidate_queue(PROJECT_ID)["items"][0]
    assert item["primary_score_name"] == "total_score"
    assert item["primary_score_owner_module_id"] == "clip_ranking"


def test_primary_score_falls_back_to_discovery_confidence(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, with_ranking=False, with_editorial=False)
    item = engine.build_candidate_queue(PROJECT_ID)["items"][0]
    assert item["primary_score_name"] == "confidence"
    assert item["primary_score_owner_module_id"] == "clip_discovery"


def test_queue_pagination_is_bounded_and_reports_the_total(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    page = engine.build_candidate_queue(PROJECT_ID, offset=1, limit=2)
    assert len(page["items"]) == 2
    assert page["offset"] == 1
    assert page["total"] == 4


def test_queue_limit_is_clamped(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    assert engine.build_candidate_queue(PROJECT_ID, limit=9_999)["limit"] == 50


@pytest.mark.parametrize(
    "review_filter",
    [
        "all_current",
        "human_review_required",
        "source_shortlisted",
        "selected",
        "rejected",
        "blocked",
        "stale",
        "overlapping",
        "missing_evidence",
        "historical",
    ],
)
def test_every_documented_filter_is_supported(tmp_path: Path, review_filter: str) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = engine.build_candidate_queue(PROJECT_ID, review_filter=review_filter)
    assert "items" in payload
    assert payload["active_filter"] == review_filter


@pytest.mark.parametrize(
    "sort",
    [
        "review_priority",
        "original_rank",
        "source_start_time",
        "duration",
        "creation_order",
        "candidate_id",
    ],
)
def test_every_documented_sort_is_supported(tmp_path: Path, sort: str) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    assert engine.build_candidate_queue(PROJECT_ID, sort=sort)["active_sort"] == sort


def test_arbitrary_filter_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="filter"):
        engine.build_candidate_queue(PROJECT_ID, review_filter="ai_best")


def test_arbitrary_sort_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="sort"):
        engine.build_candidate_queue(PROJECT_ID, sort="most_viral")


def test_overlapping_filter_selects_only_overlapping_candidates(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    items = engine.build_candidate_queue(PROJECT_ID, review_filter="overlapping")["items"]
    assert items
    assert all(item["overlap_group_ids"] for item in items)


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------
def test_disjoint_candidates_produce_no_overlap_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("c1", 0.0, 10.0), ("c2", 20.0, 30.0)])
    assert engine.calculate_candidate_overlaps(PROJECT_ID) == []


def test_touching_boundaries_are_not_an_overlap(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("c1", 0.0, 10.0), ("c2", 10.0, 20.0)])
    assert engine.calculate_candidate_overlaps(PROJECT_ID) == []


def test_exact_duplicate_window_is_detected(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("c1", 5.0, 25.0), ("c2", 5.0, 25.0)])
    record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
    assert record.exact_duplicate_window is True
    assert record.intersection_over_union == 1.0
    assert record.substantial_overlap is True


def test_substantial_overlap_uses_the_documented_threshold(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("c1", 0.0, 30.0), ("c2", 2.0, 31.0)])
    record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
    assert record.intersection_over_union >= SUBSTANTIAL_OVERLAP_IOU_THRESHOLD
    assert record.substantial_overlap is True
    assert record.partial_overlap is False


def test_partial_overlap_below_threshold(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("c1", 0.0, 30.0), ("c2", 27.0, 60.0)])
    record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
    assert record.partial_overlap is True
    assert record.substantial_overlap is False


def test_contained_candidate_is_detected(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("c1", 0.0, 60.0), ("c2", 10.0, 20.0)])
    record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
    assert record.contained is True
    assert record.candidate_b_coverage == 1.0


def test_overlap_metrics_are_deterministic_and_exact() -> None:
    first = _overlap_metrics(0.0, 30.0, 15.0, 45.0)
    second = _overlap_metrics(0.0, 30.0, 15.0, 45.0)
    assert first == second
    assert first["overlap_seconds"] == 15.0
    assert first["union_seconds"] == 45.0
    assert first["intersection_over_union"] == round(1 / 3, 6)


def test_overlap_zero_union_is_safe() -> None:
    assert _overlap_metrics(5.0, 5.0, 5.0, 5.0)["intersection_over_union"] == 0.0


def test_overlap_never_claims_semantic_duplication(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
    assert record.source_time_overlap_only is True
    assert any("not a semantic duplication claim" in item for item in record.limitations)


def test_overlapping_candidates_are_not_auto_rejected(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    items = engine.build_candidate_queue(PROJECT_ID)["items"]
    assert not any(item["rejected"] for item in items)


def test_overlap_carries_exact_decimal_boundaries(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("c1", 1.111, 2.222), ("c2", 1.5, 3.0)])
    record = engine.calculate_candidate_overlaps(PROJECT_ID)[0]
    assert record.candidate_a_start_seconds == 1.111
    assert record.candidate_a_end_seconds == 2.222
    assert record.candidate_b_end_seconds == 3.0


def test_overlap_inspection_publishes_the_threshold(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_candidate_overlaps(PROJECT_ID, "cand_a")
    assert payload["substantial_overlap_iou_threshold"] == SUBSTANTIAL_OVERLAP_IOU_THRESHOLD


def test_duplicate_group_is_reported_on_the_queue_item(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    item = next(
        entry
        for entry in engine.build_candidate_queue(PROJECT_ID)["items"]
        if entry["candidate_id"] == "cand_a"
    )
    assert item["duplicate_group_id"] is not None


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------
def test_snapshot_binds_project_revision_candidate_and_source_digests(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    snapshot = _prepared(engine)["snapshot"]
    assert len(snapshot["project_snapshot_digest"]) == 64
    assert len(snapshot["candidate_digest"]) == 64
    assert len(snapshot["confirmation_context_digest"]) == 64
    assert snapshot["source_record_digests"]


def test_snapshot_reports_each_domain_separately(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    snapshot = _prepared(engine)["snapshot"]
    assert snapshot["discovery_status"] == "discovered"
    assert snapshot["rank_status"] == "strong_candidate"
    assert snapshot["editorial_status"] == "selected"
    assert snapshot["rights_status"] == "unavailable"
    assert snapshot["validation_status"] == "unavailable"


def test_snapshot_publishes_bound_confirmation_tokens(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    offered = payload["snapshot"]["available_action_descriptor_ids"]
    assert offered
    assert all(len(payload["action_confirmations"][item]) == 64 for item in offered)


def test_snapshot_is_project_scoped(tmp_path: Path) -> None:
    """Snapshots are stored per project, so a cross-project read fails closed."""
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    with pytest.raises(ValidationError):
        engine._snapshot("proj_other", payload["snapshot"]["candidate_snapshot_id"])


def test_snapshot_refresh_returns_current_state(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    refreshed = engine.refresh_candidate_snapshot(
        PROJECT_ID, payload["snapshot"]["candidate_snapshot_id"]
    )
    assert refreshed["snapshot"]["candidate_id"] == "cand_a"
    assert refreshed["snapshot"]["snapshot_digest"] == payload["snapshot"]["snapshot_digest"]


def test_snapshot_only_offers_advisory_actions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    offered = _prepared(engine)["snapshot"]["available_action_descriptor_ids"]
    assert set(offered) == {
        "candidate_action_submit_feedback_v1",
        "candidate_action_record_review_note_v1",
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def test_comparison_supports_two_to_four_candidates(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    two = engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_b"])
    four = engine.build_candidate_comparison(
        PROJECT_ID, ["cand_a", "cand_b", "cand_c", "cand_d"]
    )
    assert len(two["comparison"]["candidate_ids"]) == 2
    assert len(four["comparison"]["candidate_ids"]) == 4


def test_comparison_rejects_a_single_candidate(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="two distinct"):
        engine.build_candidate_comparison(PROJECT_ID, ["cand_a"])


def test_comparison_rejects_more_than_four(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match=str(MAX_COMPARISON_CANDIDATES)):
        engine.build_candidate_comparison(
            PROJECT_ID, ["cand_a", "cand_b", "cand_c", "cand_d", "cand_e"]
        )


def test_comparison_collapses_duplicate_ids(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_a", "cand_b"])
    assert payload["comparison"]["candidate_ids"] == ["cand_a", "cand_b"]


def test_comparison_rejects_unknown_candidate(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="unknown, unavailable"):
        engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_missing"])


def test_comparison_rejects_arbitrary_type(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="comparison type"):
        engine.build_candidate_comparison(
            PROJECT_ID, ["cand_a", "cand_b"], comparison_type="ai_pick"
        )


def test_comparison_never_chooses_a_winner(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    comparison = engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_b"])[
        "comparison"
    ]
    assert comparison["no_automatic_winner"] is True
    assert any("does not choose a winner" in item for item in comparison["limitations"])


def test_comparison_includes_every_required_facet(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    comparison = engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_b"])[
        "comparison"
    ]
    for key in (
        "rank_comparison",
        "score_comparison",
        "duration_comparison",
        "evidence_coverage_comparison",
        "editorial_status_comparison",
        "discovery_reason_comparison",
        "warnings_comparison",
        "limitations_comparison",
    ):
        assert comparison[key], key


def test_comparison_reports_exact_durations(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    comparison = engine.build_candidate_comparison(PROJECT_ID, ["cand_a", "cand_d"])[
        "comparison"
    ]
    durations = {
        row["candidate_id"]: row["duration_seconds"] for row in comparison["duration_comparison"]
    }
    assert durations == {"cand_a": 30.0, "cand_d": 20.0}


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------
def test_transcript_is_verbatim_from_the_owner_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_candidate_transcript(PROJECT_ID, "cand_a")
    assert payload["candidate_transcript_snippets"] == [
        "The exact transcript line for this candidate."
    ]
    assert payload["source_module_id"] == "clip_discovery"


def test_transcript_context_is_clamped(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_candidate_transcript(PROJECT_ID, "cand_a", context_seconds=9_999)
    assert payload["context_seconds"] == 60


def test_transcript_context_never_changes_the_candidate_window(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = engine.inspect_candidate_transcript(PROJECT_ID, "cand_a", context_seconds=30)
    assert payload["candidate_start_seconds"] == 10.0
    assert payload["candidate_end_seconds"] == 40.0
    assert payload["context_start_seconds"] == 0.0
    assert any("never change the candidate boundaries" in i for i in payload["limitations"])


def test_transcript_context_start_never_goes_negative(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, windows=[("cand_early", 2.0, 20.0)])
    payload = engine.inspect_candidate_transcript(
        PROJECT_ID, "cand_early", context_seconds=60
    )
    assert payload["context_start_seconds"] == 0.0


# ---------------------------------------------------------------------------
# Action requests
# ---------------------------------------------------------------------------
def test_unknown_action_descriptor_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="Unknown fixed"):
        engine._action_descriptor("candidate_action_made_up_v1")


def test_unavailable_action_cannot_be_requested(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    with pytest.raises(ValidationError, match="unavailable in V1"):
        engine.create_candidate_action_request(
            PROJECT_ID,
            candidate_review_session_id=payload["session"].candidate_review_session_id,
            candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
            action_descriptor_id="candidate_action_select_candidate_v1",
            decision_value="select",
            reason="Reviewed.",
            confirmation_context_digest="0" * 64,
            idempotency_key="idem_unavailable_1",
            confirmed=True,
        )


def test_action_requires_explicit_confirmation(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    with pytest.raises(ValidationError, match="confirmation is required"):
        engine.create_candidate_action_request(
            PROJECT_ID,
            candidate_review_session_id=payload["session"].candidate_review_session_id,
            candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
            action_descriptor_id=_FEEDBACK,
            decision_value="approved",
            reason="Reviewed.",
            confirmation_context_digest=payload["action_confirmations"][_FEEDBACK],
            idempotency_key="idem_unconfirmed_1",
            confirmed=False,
        )


def test_action_requires_the_bound_confirmation_token(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    with pytest.raises(ValidationError, match="does not match"):
        engine.create_candidate_action_request(
            PROJECT_ID,
            candidate_review_session_id=payload["session"].candidate_review_session_id,
            candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
            action_descriptor_id=_FEEDBACK,
            decision_value="approved",
            reason="Reviewed.",
            confirmation_context_digest="f" * 64,
            idempotency_key="idem_badtoken_1",
            confirmed=True,
        )


@pytest.mark.parametrize(
    ("decision", "reason", "expected"),
    [
        ("select", "Reviewed.", "decision value"),
        ("approved", "   ", "requires a reason"),
        ("approved", "x" * 900, "allowed length"),
        ("approved", "token=sk-abc", "credentials"),
    ],
)
def test_invalid_action_input_is_refused(
    tmp_path: Path, decision: str, reason: str, expected: str
) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    with pytest.raises(ValidationError, match=expected):
        _request(engine, payload, "idem_invalid_1", decision=decision, reason=reason)


def test_action_request_records_what_it_does_not_do(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_limits_1")
    joined = " ".join(request.limitations).lower()
    assert "does not select or reject the candidate editorially" in joined


def test_action_request_binds_every_expected_digest(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_binding_1")
    assert request.expected_project_snapshot_digest == payload["snapshot"][
        "project_snapshot_digest"
    ]
    assert request.expected_candidate_digest == payload["snapshot"]["candidate_digest"]
    assert request.expected_source_record_digests


def test_action_request_from_another_session_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = _prepared(engine)
    other = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_b"
    )
    with pytest.raises(ValidationError, match="another review session"):
        engine.create_candidate_action_request(
            PROJECT_ID,
            candidate_review_session_id=other.candidate_review_session_id,
            candidate_snapshot_id=payload["snapshot"]["candidate_snapshot_id"],
            action_descriptor_id=_FEEDBACK,
            decision_value="approved",
            reason="Reviewed.",
            confirmation_context_digest=payload["action_confirmations"][_FEEDBACK],
            idempotency_key="idem_othersession_1",
            confirmed=True,
        )


# ---------------------------------------------------------------------------
# Stale-state protection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("expected_project_snapshot_digest", "0" * 64, "stale_project_snapshot"),
        ("expected_workflow_revision", 4242, "workflow_revision_mismatch"),
        ("expected_candidate_digest", "1" * 64, "candidate_digest_mismatch"),
        (
            "expected_source_record_digests",
            {"clip_discovery": "2" * 64},
            "source_record_digest_mismatch",
        ),
    ],
)
def test_each_staleness_guard_fires_independently(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    engine, owner = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), f"idem_guard_{expected}")
    path = engine.store.boba_candidate_review_action_path(
        PROJECT_ID, request.candidate_action_request_id
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[field] = value
    path.write_text(json.dumps(raw), encoding="utf-8")
    result = engine.validate_candidate_action_request(
        PROJECT_ID, request.candidate_action_request_id
    )
    assert result["valid"] is False
    assert result["code"] == expected
    assert owner.calls == []


def test_expired_action_request_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_expired_1")
    path = engine.store.boba_candidate_review_action_path(
        PROJECT_ID, request.candidate_action_request_id
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(raw), encoding="utf-8")
    result = engine.validate_candidate_action_request(
        PROJECT_ID, request.candidate_action_request_id
    )
    assert result["code"] == "expired_snapshot"


def test_candidate_removed_before_submission_is_refused(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_removed_1")
    engine.store.save_candidate_clip_discovery(
        synthetic_discovery(
            PROJECT_ID, [synthetic_candidate("cand_z", PROJECT_ID, 500.0, 520.0)]
        )
    )
    result = engine.validate_candidate_action_request(
        PROJECT_ID, request.candidate_action_request_id
    )
    assert result["valid"] is False
    assert result["code"] == "candidate_removed"
    assert owner.calls == []


def test_drift_rejection_records_a_stale_receipt_without_contacting_owner(
    tmp_path: Path,
) -> None:
    engine, owner = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_drift_1")
    path = engine.store.boba_candidate_review_action_path(
        PROJECT_ID, request.candidate_action_request_id
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["expected_candidate_digest"] = "9" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")
    receipt = asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    assert receipt.stale_state_rejected is True
    assert receipt.accepted_by_owner is False
    assert receipt.authoritative_state_changed is False
    assert receipt.canonical_record_id is None
    assert owner.calls == []


# ---------------------------------------------------------------------------
# Canonical routing and receipts
# ---------------------------------------------------------------------------
def test_confirmed_feedback_routes_to_creator_learning(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_route_1")
    receipt = asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    assert receipt.owning_module_id == "creator_learning"
    assert receipt.owning_operation_id == "record_creator_feedback_event"
    assert receipt.accepted_by_owner is True
    assert receipt.canonical_record_id
    assert receipt.canonical_record_digest
    assert len(owner.calls) == 1
    assert owner.calls[0]["target_type"] == "candidate"
    assert owner.calls[0]["target_id"] == "cand_a"


def test_advisory_receipt_never_claims_authoritative_change(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_advisory_1")
    receipt = asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    assert receipt.accepted_by_owner is True
    assert receipt.authoritative_state_changed is False
    assert any("advisory" in item.lower() for item in receipt.limitations)


def test_owner_rejection_is_recorded_truthfully(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path, selected=["cand_a"])
    owner.reject = True
    request = _request(engine, _prepared(engine), "idem_ownerreject_1")
    receipt = asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    assert receipt.accepted_by_owner is False
    assert receipt.error_code == "owner_rejected"
    assert receipt.canonical_record_id is None


def test_malformed_owner_response_never_becomes_success(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path, selected=["cand_a"])
    owner.malformed = True
    request = _request(engine, _prepared(engine), "idem_malformed_1")
    receipt = asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    assert receipt.error_code == "malformed_canonical_response"
    assert receipt.accepted_by_owner is False


def test_resubmission_reuses_receipt_and_contacts_owner_once(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_idempotent_1")
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
    assert second.duplicate_request_reused is True
    assert second.candidate_action_receipt_id == first.candidate_action_receipt_id
    assert len(owner.calls) == 1


def test_authority_cannot_change_without_a_canonical_owner_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="canonical owner record"):
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


def test_submission_does_not_optimistically_change_candidate_status(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    before = engine.build_candidate_queue(PROJECT_ID)["items"]
    request = _request(engine, _prepared(engine), "idem_noopt_1")
    asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    after = engine.build_candidate_queue(PROJECT_ID)["items"]
    assert [item["selected"] for item in before] == [item["selected"] for item in after]
    assert [item["rejected"] for item in before] == [item["rejected"] for item in after]


def test_receipt_lookup_returns_request_and_receipt(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_lookup_1")
    asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    payload = engine.inspect_candidate_action_receipt(
        PROJECT_ID, request.candidate_action_request_id
    )
    assert payload["request"]["candidate_id"] == "cand_a"
    assert payload["receipt"] is not None


def test_action_request_belonging_to_another_project_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_scope_1")
    with pytest.raises(ValidationError):
        engine._action_request("proj_other", request.candidate_action_request_id)


# ---------------------------------------------------------------------------
# Sessions, persistence, export and reset
# ---------------------------------------------------------------------------
def test_session_declares_local_shortlist_is_not_editorial(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    joined = " ".join(session.limitations)
    assert "not an Editorial Decision shortlist" in joined
    assert session.locally_shortlisted_candidate_ids == []


def test_session_rejects_credential_bearing_reviewer_context(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError, match="credentials"):
        engine.create_candidate_review_session(
            PROJECT_ID, reviewer_context_id="password_holder"
        )


def test_expired_session_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    raw = engine.store.load_boba_candidate_review_session(
        PROJECT_ID, session.candidate_review_session_id
    )
    assert raw is not None
    raw["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    engine.store.save_boba_candidate_review_session(
        PROJECT_ID, session.candidate_review_session_id, raw
    )
    with pytest.raises(ValidationError, match="expired"):
        engine.get_candidate_review_session(
            PROJECT_ID, session.candidate_review_session_id
        )


def test_session_updates_use_a_field_allowlist(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    updated = engine.update_candidate_review_session(
        PROJECT_ID,
        session.candidate_review_session_id,
        {"active_filter": "rejected", "show_rejected": True},
    )
    assert updated.active_filter == "rejected"
    assert updated.show_rejected is True
    with pytest.raises(ValidationError, match="unsupported"):
        engine.update_candidate_review_session(
            PROJECT_ID, session.candidate_review_session_id, {"session_digest": "0" * 64}
        )


def test_session_enforces_the_comparison_limit(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    with pytest.raises(ValidationError, match="compared"):
        engine.update_candidate_review_session(
            PROJECT_ID,
            session.candidate_review_session_id,
            {"comparison_candidate_ids": ["a", "b", "c", "d", "e"]},
        )


def test_local_shortlist_is_session_metadata_only(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    engine.update_candidate_review_session(
        PROJECT_ID,
        session.candidate_review_session_id,
        {"locally_shortlisted_candidate_ids": ["cand_b"]},
    )
    item = next(
        entry
        for entry in engine.build_candidate_queue(PROJECT_ID)["items"]
        if entry["candidate_id"] == "cand_b"
    )
    assert item["selected"] is False
    assert item["editorial_status"] != "selected"


def test_action_requests_and_receipts_are_immutable(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    request = _request(engine, _prepared(engine), "idem_immutable_1")
    with pytest.raises(ValidationError, match="immutable"):
        engine.store.save_boba_candidate_review_action(
            PROJECT_ID,
            request.candidate_action_request_id,
            {**request.model_dump(mode="json"), "bounded_reason": "tampered"},
        )
    receipt = asyncio.run(
        engine.submit_candidate_action_to_owner(
            PROJECT_ID, request.candidate_action_request_id
        )
    )
    with pytest.raises(ValidationError, match="immutable"):
        engine.store.save_boba_candidate_review_receipt(
            PROJECT_ID,
            receipt.candidate_action_receipt_id,
            {**receipt.model_dump(mode="json"), "canonical_status": "tampered"},
        )


def test_persisted_set_does_not_duplicate_source_payloads(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    stored = json.dumps(engine.build_candidate_review(PROJECT_ID))
    assert "score_breakdown" not in stored
    assert "transcript_snippets" not in stored
    assert "editing_instruction_packet" not in stored


def test_build_persists_and_reloads(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    built = engine.build_candidate_review(PROJECT_ID)
    reloaded = engine.load_candidate_review(PROJECT_ID)
    assert reloaded is not None
    assert reloaded["project_id"] == PROJECT_ID
    assert built["review_summary"]["total_candidate_count"] == 4


def test_summary_counts_overlap_pairs_and_duplicates(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    summary = engine.build_candidate_review(PROJECT_ID)["review_summary"]
    assert summary["exact_duplicate_window_count"] == 1
    assert summary["substantial_overlap_pair_count"] == 1
    assert summary["selected_candidate_count"] == 1


def test_signal_usage_declares_no_false_authority(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    usage = engine.build_candidate_review(PROJECT_ID)["signal_usage"]
    for flag in (
        "arbitrary_candidate_created",
        "candidate_score_recalculated",
        "hidden_composite_score_created",
        "candidate_selected_locally",
        "candidate_rejected_locally",
        "optimistic_authority_update_used",
        "arbitrary_module_used",
        "arbitrary_operation_used",
        "arbitrary_url_used",
        "arbitrary_path_used",
        "external_media_used",
        "untrusted_html_used",
        "command_execution_used",
        "shell_execution_used",
        "git_execution_used",
        "ffmpeg_execution_used",
        "media_generation_used",
        "source_media_modified",
        "accepted_output_modified",
        "workflow_transition_used",
        "approval_created_locally",
        "safety_decision_created_locally",
        "upload_used",
        "publication_used",
        "external_analytics_used",
        "rights_bypass_used",
        "safety_bypass_used",
        "destructive_action_used",
    ):
        assert usage[flag] is False, flag


def test_signal_usage_reports_which_owners_were_read(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    usage = engine.build_candidate_review(PROJECT_ID)["signal_usage"]
    assert usage["canonical_candidate_discovery_records"] is True
    assert usage["canonical_ranking_records"] is True
    assert usage["canonical_editorial_records"] is True
    assert "safety_gate" in usage["unavailable_signals"]


def test_export_is_sanitised_and_declares_privacy(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    exported = engine.export_candidate_review(PROJECT_ID)
    privacy = exported["privacy"]
    assert privacy["sensitive_values_excluded"] is True
    assert privacy["source_records_duplicated"] is False
    assert privacy["speaker_identity_inferred"] is False
    assert privacy["biometric_inference_used"] is False
    assert privacy["upload_used"] is False


def test_export_carries_no_private_paths(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    exported = json.dumps(engine.export_candidate_review(PROJECT_ID))
    assert "/home/" not in exported
    assert "C:\\" not in exported
    assert "file:" not in exported


def test_reset_preserves_every_source_owned_history(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    engine.build_candidate_review(PROJECT_ID)
    result = engine.reset_candidate_review_metadata(PROJECT_ID)
    for key in (
        "candidate_records_preserved",
        "ranking_records_preserved",
        "editorial_history_preserved",
        "review_ui_history_preserved",
        "action_receipt_history_preserved",
        "workflow_history_preserved",
    ):
        assert result[key] is True, key
    assert result["source_media_removed"] is False
    assert engine.store.load_candidate_clip_discovery(PROJECT_ID) is not None
    assert engine.store.load_clip_ranking(PROJECT_ID) is not None


def test_session_reset_removes_only_that_session(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_candidate_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    result = engine.reset_candidate_review_metadata(
        PROJECT_ID, session.candidate_review_session_id
    )
    assert result["session_removed"] is True
    assert result["candidate_records_preserved"] is True
    with pytest.raises(ValidationError):
        engine.get_candidate_review_session(
            PROJECT_ID, session.candidate_review_session_id
        )


# ---------------------------------------------------------------------------
# Events and timeline
# ---------------------------------------------------------------------------
def test_events_are_project_scoped_and_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    payload = engine.inspect_candidate_events(PROJECT_ID, limit=9_999)
    assert payload["project_id"] == PROJECT_ID
    assert len(payload["events"]) <= 100
    assert "latest_sequence" in payload


def test_timeline_is_bounded_and_discloses_precision(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, selected=["cand_a"])
    entries = engine.inspect_candidate_timeline(PROJECT_ID, limit=9_999)["entries"]
    assert len(entries) <= 100
    assert all(
        entry["timestamp_precision"] in {"source", "unknown", "exact"} for entry in entries
    )


def test_control_events_are_marked_not_work() -> None:
    source = Path("src/olympus/boba/candidate_review.py").read_text(encoding="utf-8")
    assert '"heartbeat", "keepalive", "ping"' in source
    assert "represents_work=" in source


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def test_integration_layer_registers_every_fixed_operation() -> None:
    registered = {
        item
        for item in build_boba_operation_registry()
        if item.startswith("candidate_review.")
    }
    expected = {
        f"candidate_review.{name}"
        for name in (
            "inspect_registry", "create_session", "update_session", "build_queue",
            "inspect_queue", "build_snapshot", "refresh_snapshot", "inspect_candidate",
            "compare_candidates", "calculate_overlaps", "create_action", "validate_action",
            "submit_action", "inspect_receipt", "inspect_timeline", "inspect_events",
            "load", "export", "reset",
        )
    }
    assert registered == expected


def test_integration_layer_module_is_available() -> None:
    module = build_boba_module_registry()["candidate_review"]
    assert module.implementation_status == "available"
    assert "review_ui" in module.dependency_module_ids


def test_safety_gate_classifies_candidate_review() -> None:
    operations = build_safety_module_operation_registry()["candidate_review"]
    assert len(operations) == 19
    assert operations["submit_action"] == "approval_required_read_only"
    assert sum(1 for v in operations.values() if v == "automatic_read_only") == 18


def test_review_ui_v1_registry_is_unchanged() -> None:
    assert len(build_fixed_review_action_registry()) == 4


def test_module_contains_no_dynamic_dispatch_or_execution() -> None:
    source = Path("src/olympus/boba/candidate_review.py").read_text(encoding="utf-8")
    for forbidden in (
        "importlib",
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "requests.",
        "httpx.",
        "ffmpeg_binary",
        "ffprobe",
        "http://",
        "https://",
    ):
        assert forbidden not in source, forbidden


def test_module_writes_no_source_owned_decision() -> None:
    source = Path("src/olympus/boba/candidate_review.py").read_text(encoding="utf-8")
    for forbidden in (
        "save_editorial_decisions",
        "save_clip_ranking",
        "save_candidate_clip_discovery",
        "save_rights_permission_gate",
        "save_boba_safety_gate",
        "record_human_workflow_decision",
        "request_transition",
    ):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Candidate Review Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4",
        size_bytes=24,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=600.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _client(tmp_path: Path) -> tuple[TestClient, BobaIntegration]:
    from olympus.api.v1.routes.boba import router

    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    asyncio.run(storage.put(project.storage_key, b"synthetic", content_type="video/mp4"))
    asyncio.run(StorageProjectRepository(storage).save(project))
    integration = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))
    seed_project(integration.store, PROJECT_ID, selected=["cand_a"], recommended=["cand_a"])
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    return TestClient(app), integration


def test_api_root_and_registry(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review"
    root = client.get(base)
    assert root.status_code == 200
    assert root.json()["project_id"] == PROJECT_ID
    registry = client.get(f"{base}/registry")
    assert registry.status_code == 200
    assert len(registry.json()["sources"]) == 13


def test_api_queue_reports_priority_tiers(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review/queue"
    )
    assert response.status_code == 200
    assert len(response.json()["priority_tiers"]) == 12
    assert response.json()["total"] == 4


def test_api_rejects_arbitrary_filter_and_sort(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review/queue"
    assert client.get(base, params={"review_filter": "ai_best"}).status_code >= 400
    assert client.get(base, params={"sort": "most_viral"}).status_code >= 400


def test_api_session_lifecycle(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review"
    created = client.post(f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"})
    assert created.status_code == 200
    session_id = created.json()["candidate_review_session_id"]
    assert client.get(f"{base}/sessions/{session_id}").status_code == 200
    patched = client.patch(
        f"{base}/sessions/{session_id}", json={"active_filter": "rejected"}
    )
    assert patched.status_code == 200
    assert patched.json()["active_filter"] == "rejected"
    assert client.delete(f"{base}/sessions/{session_id}").status_code == 200


def test_api_rejects_unsupported_session_fields(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["candidate_review_session_id"]
    response = client.patch(
        f"{base}/sessions/{session_id}", json={"reviewer_context_id": "other"}
    )
    assert response.status_code == 422


def test_api_candidate_snapshot_and_refresh(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["candidate_review_session_id"]
    snapshot = client.post(
        f"{base}/candidates/cand_a/snapshot",
        json={"candidate_review_session_id": session_id},
    )
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert "action_confirmations" in body
    snapshot_id = body["snapshot"]["candidate_snapshot_id"]
    assert client.post(f"{base}/snapshots/{snapshot_id}/refresh").status_code == 200


def test_api_rejects_unknown_candidate(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review/candidates/cand_missing"
    )
    assert response.status_code >= 400


def test_api_candidate_transcript_and_overlaps(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review/candidates/cand_a"
    transcript = client.get(f"{base}/transcript", params={"context_seconds": 9_999})
    assert transcript.status_code == 200
    assert transcript.json()["context_seconds"] == 60
    overlaps = client.get(f"{base}/overlaps")
    assert overlaps.status_code == 200
    assert overlaps.json()["substantial_overlap_iou_threshold"] == 0.6


def test_api_compare_enforces_bounds(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review/compare"
    ok = client.post(base, json={"candidate_ids": ["cand_a", "cand_b"]})
    assert ok.status_code == 200
    assert ok.json()["comparison"]["no_automatic_winner"] is True
    assert client.post(base, json={"candidate_ids": ["cand_a"]}).status_code == 422
    too_many = client.post(
        base, json={"candidate_ids": ["cand_a", "cand_b", "cand_c", "cand_d", "cand_e"]}
    )
    assert too_many.status_code == 422


def test_api_rejects_unknown_action_descriptor(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["candidate_review_session_id"]
    snapshot_id = client.post(
        f"{base}/candidates/cand_a/snapshot",
        json={"candidate_review_session_id": session_id},
    ).json()["snapshot"]["candidate_snapshot_id"]
    response = client.post(
        f"{base}/actions",
        json={
            "candidate_review_session_id": session_id,
            "candidate_snapshot_id": snapshot_id,
            "action_descriptor_id": "candidate_action_arbitrary_v1",
            "confirmation_context_digest": "0" * 64,
            "idempotency_key": "idem_api_unknown",
            "confirmed": True,
        },
    )
    assert response.status_code >= 400


def test_api_full_action_pipeline_records_advisory_receipt(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["candidate_review_session_id"]
    snapshot = client.post(
        f"{base}/candidates/cand_a/snapshot",
        json={"candidate_review_session_id": session_id},
    ).json()
    token = snapshot["action_confirmations"][_FEEDBACK]
    created = client.post(
        f"{base}/actions",
        json={
            "candidate_review_session_id": session_id,
            "candidate_snapshot_id": snapshot["snapshot"]["candidate_snapshot_id"],
            "action_descriptor_id": _FEEDBACK,
            "decision_value": "approved",
            "reason": "Reviewed the exact candidate window.",
            "confirmation_context_digest": token,
            "idempotency_key": "idem_api_pipeline",
            "confirmed": True,
        },
    )
    assert created.status_code == 200
    request_id = created.json()["candidate_action_request_id"]
    validated = client.post(f"{base}/actions/{request_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    submitted = client.post(f"{base}/actions/{request_id}/submit")
    assert submitted.status_code == 200
    receipt = submitted.json()
    assert receipt["accepted_by_owner"] is True
    assert receipt["authoritative_state_changed"] is False
    assert receipt["owning_module_id"] == "creator_learning"
    read_back = client.get(f"{base}/actions/{request_id}")
    assert read_back.status_code == 200


def test_api_timeline_events_and_export(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/candidate-review"
    assert client.get(f"{base}/timeline").status_code == 200
    assert client.get(f"{base}/events").status_code == 200
    exported = client.get(f"{base}/export")
    assert exported.status_code == 200
    assert exported.json()["privacy"]["upload_used"] is False


def test_api_unknown_project_is_rejected(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(
        "/api/v1/boba/projects/proj_missing/candidate-review/queue"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------
def test_validator_self_check_passes() -> None:
    payload = run_self_check()
    assert payload["passed"] is True
    assert payload["scenario_count"] >= 220
    assert all(payload["checks"].values())


def test_validator_scenario_names_are_unique() -> None:
    assert len(set(SCENARIO_NAMES)) == len(SCENARIO_NAMES)
    assert len(SCENARIO_NAMES) >= 220


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_validator_scenario_passes(name: str, tmp_path: Path) -> None:
    result = run_named_scenario(name, tmp_path)
    assert result.passed, f"{name}: {result.detail}"
