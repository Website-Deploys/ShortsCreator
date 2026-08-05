"""BOBA Clip Brief Panel V1 contracts, projection, evidence, routing and API tests."""

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
from tools._boba_clip_brief_review_fixtures import (
    seed_project,
    synthetic_brief,
    synthetic_brief_set,
)
from tools.validate_boba_clip_brief_review import (
    SCENARIO_NAMES,
    ScenarioResult,
    run_all_scenarios,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.clip_brief_review import (
    CLIP_BRIEF_QUEUE_PRIORITY_TIERS,
    MAX_ANNOTATION_LENGTH,
    MAX_BOUNDED_DISPLAY_CHARS,
    MAX_COMPARISON_BRIEFS,
    MAX_QUEUE_PAGE_SIZE,
    SUPPORTED_BRIEF_SCHEMA_ID,
    BobaClipBriefActionDescriptorV1,
    BobaClipBriefActionReceiptV1,
    BobaClipBriefActionRequestV1,
    BobaClipBriefComparisonV1,
    BobaClipBriefCompletenessV1,
    BobaClipBriefConflictV1,
    BobaClipBriefEvidenceLinkV1,
    BobaClipBriefFieldProjectionV1,
    BobaClipBriefQueueItemV1,
    BobaClipBriefReferenceV1,
    BobaClipBriefRegistrySnapshotV1,
    BobaClipBriefReviewEventV1,
    BobaClipBriefReviewNotificationV1,
    BobaClipBriefReviewSessionV1,
    BobaClipBriefReviewSetV1,
    BobaClipBriefReviewSignalUsageV1,
    BobaClipBriefReviewSummaryV1,
    BobaClipBriefReviewTimelineEntryV1,
    BobaClipBriefReviewV1,
    BobaClipBriefSectionProjectionV1,
    BobaClipBriefSnapshotV1,
    BobaClipBriefSourceCardV1,
    build_fixed_clip_brief_action_registry,
    build_fixed_clip_brief_section_registry,
    build_fixed_clip_brief_source_registry,
    owner_schema_optional_field_paths,
    owner_schema_required_field_paths,
)
from olympus.boba.integration import BobaIntegration
from olympus.boba.integration_layer import (
    build_boba_module_registry,
    build_boba_operation_registry,
)
from olympus.boba.safety_gate import build_safety_module_operation_registry
from olympus.boba.store import BobaMemoryStore
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError, register_exception_handlers
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_clip_brief_review_test"
_FEEDBACK = "clip_brief_action_submit_feedback_v1"
_NOTE = "clip_brief_action_record_review_note_v1"

CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaClipBriefRegistrySnapshotV1,
    BobaClipBriefReferenceV1,
    BobaClipBriefReviewSessionV1,
    BobaClipBriefQueueItemV1,
    BobaClipBriefFieldProjectionV1,
    BobaClipBriefSectionProjectionV1,
    BobaClipBriefSourceCardV1,
    BobaClipBriefEvidenceLinkV1,
    BobaClipBriefCompletenessV1,
    BobaClipBriefConflictV1,
    BobaClipBriefComparisonV1,
    BobaClipBriefActionDescriptorV1,
    BobaClipBriefActionRequestV1,
    BobaClipBriefActionReceiptV1,
    BobaClipBriefSnapshotV1,
    BobaClipBriefReviewEventV1,
    BobaClipBriefReviewTimelineEntryV1,
    BobaClipBriefReviewNotificationV1,
    BobaClipBriefReviewSummaryV1,
    BobaClipBriefReviewSignalUsageV1,
    BobaClipBriefReviewSetV1,
)


class _StubOwner:
    """Stands in for Creator Learning, the canonical owner of creator feedback."""

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


def _engine(tmp_path: Path, **seed: Any) -> tuple[BobaClipBriefReviewV1, _StubOwner]:
    store = BobaMemoryStore(tmp_path / "boba")
    owner = _StubOwner()
    engine = BobaClipBriefReviewV1(store, owner)  # type: ignore[arg-type]
    if seed.pop("seed", True):
        seed_project(store, PROJECT_ID, **seed)
    return engine, owner


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
) -> BobaClipBriefActionRequestV1:
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


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Clip Brief Review Test",
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
    seed_project(integration.store, PROJECT_ID, selected_candidates=["cand_a"])
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    return TestClient(app), integration


# ---------------------------------------------------------------------------
# Offline validator coverage: one test per catalogued correctness condition
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def scenario_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_all_scenarios()}


@pytest.fixture(scope="module")
def self_check_results() -> dict[str, ScenarioResult]:
    return {item.name: item for item in run_self_check()}


@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
def test_validator_scenario(
    scenario: str, scenario_results: dict[str, ScenarioResult]
) -> None:
    result = scenario_results[scenario]
    assert result.passed, f"{scenario}: {result.detail}"


SELF_CHECK_NAMES: tuple[str, ...] = tuple(
    item.name for item in run_self_check()
)


@pytest.mark.parametrize("check", SELF_CHECK_NAMES)
def test_declared_boundary_self_check(
    check: str, self_check_results: dict[str, ScenarioResult]
) -> None:
    result = self_check_results[check]
    assert result.passed, f"{check}: {result.detail}"


def test_scenario_catalogue_is_unique_and_grouped() -> None:
    assert len(SCENARIO_NAMES) == len(set(SCENARIO_NAMES))
    assert len(SCENARIO_NAMES) >= 230
    assert all(":" in name for name in SCENARIO_NAMES)


def test_synthetic_project_reports_real_counts() -> None:
    report = run_synthetic_project()
    assert report["brief_count"] == 2
    assert report["field_projection_count"] == 27
    assert report["section_projection_count"] == 9
    assert report["source_card_count"] == 14
    assert report["comparison_no_automatic_winner"] is True
    assert report["available_action_descriptor_ids"] == [_FEEDBACK, _NOTE]


# ---------------------------------------------------------------------------
# Contracts and fixed registries
# ---------------------------------------------------------------------------
def test_every_contract_forbids_unknown_fields() -> None:
    for contract in CONTRACT_TYPES:
        assert contract.model_config.get("extra") == "forbid", contract.__name__


def test_contract_count_covers_the_module_surface() -> None:
    assert len(CONTRACT_TYPES) == 21


def test_source_registry_is_fixed_and_unique() -> None:
    registry = build_fixed_clip_brief_source_registry()
    assert len(registry) == 14
    assert len(set(registry)) == 14
    assert [key for key, item in registry.items() if item["required"]] == ["clip_brief"]


def test_advisory_sources_are_marked_advisory() -> None:
    registry = build_fixed_clip_brief_source_registry()
    for module_id in (
        "explanation",
        "creative_director",
        "hook_retention",
        "caption_motion",
        "music_mood",
    ):
        assert registry[module_id]["advisory_only"] is True
    for module_id in (
        "clip_brief",
        "clip_discovery",
        "clip_ranking",
        "editorial_decision",
        "rights_permission_gate",
        "safety_gate",
        "workflow_controller",
        "artifact_inspector",
        "validator_runner",
    ):
        assert registry[module_id]["advisory_only"] is False


def test_source_registry_names_only_real_store_loaders() -> None:
    store = BobaMemoryStore(Path("/tmp/does-not-need-to-exist"))
    for descriptor in build_fixed_clip_brief_source_registry().values():
        assert hasattr(store, str(descriptor["loader"])), descriptor


def test_section_registry_matches_owner_schema_fields() -> None:
    registry = build_fixed_clip_brief_section_registry()
    assert len(registry) == 9
    covered = {path for item in registry.values() for path in item["field_paths"]}
    assert covered == set(owner_schema_required_field_paths()) | set(
        owner_schema_optional_field_paths()
    )


def test_section_registry_defines_no_beats_or_ending_section() -> None:
    registry = build_fixed_clip_brief_section_registry()
    assert "beats" not in registry
    assert "ending" not in registry
    assert "narrative_arc" not in registry


def test_owner_schema_field_paths_are_fixed_counts() -> None:
    assert len(owner_schema_required_field_paths()) == 22
    assert len(owner_schema_optional_field_paths()) == 5
    assert set(owner_schema_required_field_paths()).isdisjoint(
        owner_schema_optional_field_paths()
    )


def test_owner_schema_never_lists_an_unowned_field() -> None:
    from olympus.boba.clip_brief import BobaClipBriefV1

    owned = set(BobaClipBriefV1.model_fields)
    for path in owner_schema_required_field_paths() + owner_schema_optional_field_paths():
        assert path.split(".")[0] in owned, path


def test_action_registry_declares_six_actions_with_owners() -> None:
    registry = build_fixed_clip_brief_action_registry()
    assert len(registry) == 6
    for descriptor in registry.values():
        assert descriptor.owning_module_id
        assert descriptor.owning_operation_id
        assert not descriptor.upload_or_publication
        assert not descriptor.execution_capable
        assert not descriptor.destructive


def test_only_advisory_actions_are_available_in_v1() -> None:
    registry = build_fixed_clip_brief_action_registry()
    available = [item for item in registry.values() if item.availability == "available"]
    assert {item.action_descriptor_id for item in available} == {_FEEDBACK, _NOTE}
    assert all(item.authoritative is False for item in available)
    assert all(item.owning_module_id == "creator_learning" for item in available)


def test_authoritative_brief_actions_are_declared_unavailable() -> None:
    registry = build_fixed_clip_brief_action_registry()
    for action_id in (
        "clip_brief_action_approve_v1",
        "clip_brief_action_reject_v1",
        "clip_brief_action_request_revision_v1",
        "clip_brief_action_request_regeneration_v1",
    ):
        descriptor = registry[action_id]
        assert descriptor.availability == "unavailable"
        assert descriptor.authoritative is True
        assert descriptor.limitations, action_id


def test_unavailable_actions_name_no_substitute_owner() -> None:
    registry = build_fixed_clip_brief_action_registry()
    for descriptor in registry.values():
        if descriptor.availability == "unavailable":
            assert descriptor.owning_operation_id.startswith("unavailable_")


def test_priority_tiers_are_twelve_and_ordered() -> None:
    tiers = [priority for priority, _reason in CLIP_BRIEF_QUEUE_PRIORITY_TIERS]
    assert len(tiers) == 12
    assert tiers == sorted(tiers)
    assert len(set(tiers)) == 12


def test_module_bounds_are_explicit() -> None:
    assert MAX_COMPARISON_BRIEFS == 4
    assert MAX_QUEUE_PAGE_SIZE == 50
    assert MAX_ANNOTATION_LENGTH == 4_000
    assert MAX_BOUNDED_DISPLAY_CHARS == 16_384
    assert SUPPORTED_BRIEF_SCHEMA_ID == "boba_clip_brief_generator_v1"


def test_reference_rejects_inverted_source_window() -> None:
    with pytest.raises(PydanticValidationError):
        BobaClipBriefReferenceV1(
            brief_reference_id="ref",
            project_id=PROJECT_ID,
            candidate_id="cand_a",
            clip_id="cand_a",
            brief_id="brief_a",
            source_record_id="record",
            source_record_digest="0" * 64,
            project_snapshot_digest="0" * 64,
            start_seconds=40.0,
            end_seconds=10.0,
            duration_seconds=30.0,
        )


def test_comparison_contract_pins_no_automatic_winner() -> None:
    field = BobaClipBriefComparisonV1.model_fields["no_automatic_winner"]
    assert field.default is True
    with pytest.raises(PydanticValidationError):
        BobaClipBriefComparisonV1(
            comparison_id="cmp",
            project_id=PROJECT_ID,
            brief_ids=["brief_a", "brief_b"],
            no_automatic_winner=False,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Projection behaviour
# ---------------------------------------------------------------------------
def test_references_project_every_persisted_brief(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    references = engine.build_clip_brief_references(PROJECT_ID)
    assert [item.brief_id for item in references] == ["brief_a", "brief_b"]
    assert all(item.schema_supported for item in references)


def test_references_are_empty_without_a_brief_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, with_briefs=False)
    assert engine.build_clip_brief_references(PROJECT_ID) == []


def test_unknown_brief_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.inspect_clip_brief(PROJECT_ID, "brief_missing")


def test_brief_id_charset_is_enforced(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.inspect_clip_brief(PROJECT_ID, "../../etc/passwd")


def test_field_projections_cover_only_owner_schema_fields(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    fields = engine.build_field_projections(PROJECT_ID, "brief_a")
    assert {item.field_path for item in fields} == set(
        owner_schema_required_field_paths()
    ) | set(owner_schema_optional_field_paths())
    assert all(item.human_editable is False for item in fields)
    assert all(item.source_owned for item in fields)


def test_field_projection_preserves_the_owner_value(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    fields = {
        item.field_path: item
        for item in engine.build_field_projections(PROJECT_ID, "brief_a")
    }
    assert fields["brief_title"].original_value == "Brief brief_a"
    assert fields["confidence"].original_value == 0.78
    assert fields["source_window.duration_seconds"].original_value == 30.0


def test_field_explanation_never_contains_the_value(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    for item in engine.build_field_projections(PROJECT_ID, "brief_a"):
        if isinstance(item.original_value, str) and item.original_value:
            assert item.original_value not in item.bounded_explanation


def test_empty_owner_list_is_empty_not_absent(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    fields = {
        item.field_path: item
        for item in engine.build_field_projections(PROJECT_ID, "brief_a")
    }
    assert fields["warnings"].empty is True
    assert fields["warnings"].unavailable is False
    assert fields["warnings"].present is False


def test_sections_group_every_field_exactly_once(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    fields = engine.build_field_projections(PROJECT_ID, "brief_a")
    sections = engine.build_section_projections(PROJECT_ID, "brief_a", fields)
    members = [item for section in sections for item in section.field_projection_ids]
    assert sorted(members) == sorted(item.field_projection_id for item in fields)


def test_completeness_is_field_presence_only(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    inspected = engine.inspect_clip_brief_completeness(PROJECT_ID, "brief_a")
    record = inspected["completeness"]
    assert record["complete_for_owner_schema"] is True
    assert record["creative_quality_assessed"] is False
    assert record["technical_quality_assessed"] is False
    assert any("not creative quality" in item for item in inspected["limitations"])


def test_completeness_ratios_are_deterministic(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first = engine.inspect_clip_brief_completeness(PROJECT_ID, "brief_a")["completeness"]
    second = engine.inspect_clip_brief_completeness(PROJECT_ID, "brief_a")["completeness"]
    assert first == second
    assert first["required_completion_ratio"] == 1.0


def test_evidence_links_are_identity_bound(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    links = engine.build_evidence_links(PROJECT_ID, "brief_a")
    present = [item for item in links if not item.missing]
    assert all(item.candidate_id == "cand_a" for item in present)
    assert all(item.exact_identity_match or item.source_module_id != "clip_discovery"
               for item in present)


def test_missing_evidence_is_never_a_pass(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    result = engine.inspect_clip_brief_evidence(PROJECT_ID, "brief_a")
    assert result["missing_evidence_count"] == 6
    missing = [item for item in result["evidence_links"] if item["missing"]]
    assert all(item["limitations"] for item in missing)


def test_clean_project_reports_no_conflict(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    assert engine.detect_clip_brief_conflicts(PROJECT_ID, "brief_a") == []


def test_conflicts_require_the_same_identity(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, brief_windows=[("brief_a", "cand_zz", 10.0, 40.0)])
    conflicts = engine.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")
    assert conflicts
    assert all(item.same_candidate and item.same_clip for item in conflicts)
    assert all(item.resolved is False for item in conflicts)
    assert all(item.explicit_supersession_found is False for item in conflicts)


def test_blocking_conflict_withholds_the_current_snapshot_action(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, brief_windows=[("brief_a", "cand_zz", 10.0, 40.0)])
    payload = _prepared(engine)
    available = payload["snapshot"]["available_action_descriptor_ids"]
    assert _FEEDBACK not in available
    assert _NOTE in available


def test_source_window_mismatch_is_reported_not_corrected(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, brief_windows=[("brief_a", "cand_a", 12.5, 44.0)])
    conflicts = engine.detect_clip_brief_conflicts(PROJECT_ID, "brief_a")
    types = {item.conflict_type for item in conflicts}
    assert "source_window_conflict" in types
    reference = engine.build_clip_brief_references(PROJECT_ID)[0]
    assert (reference.start_seconds, reference.end_seconds) == (12.5, 44.0)


def test_queue_is_deterministic_and_bounded(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    first = engine.build_clip_brief_queue(PROJECT_ID, limit=10_000)
    second = engine.build_clip_brief_queue(PROJECT_ID, limit=10_000)
    assert first["items"] == second["items"]
    assert first["limit"] == MAX_QUEUE_PAGE_SIZE


def test_queue_rejects_an_unsupported_filter_and_sort(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.build_clip_brief_queue(PROJECT_ID, review_filter="ai_best")
    with pytest.raises(ValidationError):
        engine.build_clip_brief_queue(PROJECT_ID, sort="most_viral")


def test_queue_item_never_invents_a_candidate_rank(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, brief_windows=[("brief_a", "cand_zz", 10.0, 40.0)])
    item = engine.build_clip_brief_queue(PROJECT_ID)["items"][0]
    assert item["candidate_rank"] is None


def test_queue_carries_source_owned_rank_when_present(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    ranks = {
        item["brief_id"]: item["candidate_rank"]
        for item in engine.build_clip_brief_queue(PROJECT_ID)["items"]
    }
    assert ranks == {"brief_a": 1, "brief_b": 2}


def test_comparison_requires_two_distinct_briefs(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.build_clip_brief_comparison(PROJECT_ID, ["brief_a"])
    with pytest.raises(ValidationError):
        engine.build_clip_brief_comparison(PROJECT_ID, ["brief_a", "brief_a"])


def test_comparison_rejects_more_than_four_briefs(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    with pytest.raises(ValidationError):
        engine.build_clip_brief_comparison(
            PROJECT_ID, ["brief_a", "brief_b", "brief_c", "brief_d", "brief_e"]
        )


def test_comparison_shows_missing_fields_explicitly(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    comparison = engine.build_clip_brief_comparison(
        PROJECT_ID, ["brief_a", "brief_b"]
    )["comparison"]
    rows = {row["field_path"]: row for row in comparison["field_comparisons"]}
    assert rows["warnings"]["values"][0]["present"] is False
    assert comparison["no_automatic_winner"] is True


def test_snapshot_records_source_digests_and_statuses(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    snapshot = _prepared(engine)["snapshot"]
    assert len(snapshot["snapshot_digest"]) == 64
    assert len(snapshot["brief_digest"]) == 64
    assert snapshot["rights_status"] == "unavailable"
    assert snapshot["brief_status"] == "selected"
    assert len(snapshot["source_record_digests"]) == 14


def test_snapshot_refresh_rebuilds_from_canonical_state(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    refreshed = engine.refresh_clip_brief_snapshot(
        PROJECT_ID, payload["snapshot"]["brief_snapshot_id"]
    )
    assert refreshed["snapshot"]["brief_digest"] == payload["snapshot"]["brief_digest"]
    assert (
        refreshed["snapshot"]["brief_snapshot_id"]
        != payload["snapshot"]["brief_snapshot_id"]
    )


def test_confirmation_tokens_are_issued_only_for_available_actions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    assert set(payload["action_confirmations"]) == set(
        payload["snapshot"]["available_action_descriptor_ids"]
    )
    assert all(len(value) == 64 for value in payload["action_confirmations"].values())


def test_action_request_requires_the_server_issued_token(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    with pytest.raises(ValidationError):
        engine.create_clip_brief_action_request(
            PROJECT_ID,
            clip_brief_review_session_id=payload["session"].clip_brief_review_session_id,
            brief_snapshot_id=payload["snapshot"]["brief_snapshot_id"],
            action_descriptor_id=_FEEDBACK,
            decision_value="approved",
            reason="Reviewed the brief.",
            confirmation_context_digest="0" * 64,
            idempotency_key="idem_bad_token_key",
            confirmed=True,
        )


def test_snapshot_from_another_session_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    other = engine.create_clip_brief_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_b"
    )
    with pytest.raises(ValidationError):
        engine.create_clip_brief_action_request(
            PROJECT_ID,
            clip_brief_review_session_id=other.clip_brief_review_session_id,
            brief_snapshot_id=payload["snapshot"]["brief_snapshot_id"],
            action_descriptor_id=_FEEDBACK,
            decision_value="approved",
            reason="Reviewed the brief.",
            confirmation_context_digest=payload["action_confirmations"][_FEEDBACK],
            idempotency_key="idem_cross_session_key",
            confirmed=True,
        )


def test_submission_records_a_canonical_advisory_receipt(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_submit_key")
    receipt = asyncio.run(
        engine.submit_clip_brief_action_to_owner(
            PROJECT_ID, request.clip_brief_action_request_id
        )
    )
    assert receipt.accepted_by_owner is True
    assert receipt.owning_module_id == "creator_learning"
    assert receipt.authoritative_state_changed is False
    assert owner.calls[0]["target_type"] == "clip_brief"
    assert owner.calls[0]["target_id"] == "brief_a"


def test_review_note_is_routed_as_a_preference_note(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(
        engine, payload, "idem_note_key", action=_NOTE, decision="noted",
        reason="A reviewer note about the exact brief.",
    )
    asyncio.run(
        engine.submit_clip_brief_action_to_owner(
            PROJECT_ID, request.clip_brief_action_request_id
        )
    )
    assert owner.calls[0]["event_type"] == "preference_note"
    assert owner.calls[0]["reversible"] is True


def test_owner_rejection_is_recorded_without_authority_change(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_owner_reject_key")
    owner.reject = True
    receipt = asyncio.run(
        engine.submit_clip_brief_action_to_owner(
            PROJECT_ID, request.clip_brief_action_request_id
        )
    )
    assert receipt.canonical_status == "rejected_by_owner"
    assert receipt.authoritative_state_changed is False


def test_duplicate_submission_reuses_the_receipt(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_duplicate_key")
    first = asyncio.run(
        engine.submit_clip_brief_action_to_owner(
            PROJECT_ID, request.clip_brief_action_request_id
        )
    )
    second = asyncio.run(
        engine.submit_clip_brief_action_to_owner(
            PROJECT_ID, request.clip_brief_action_request_id
        )
    )
    assert len(owner.calls) == 1
    assert second.duplicate_request_reused is True
    assert second.clip_brief_action_receipt_id == first.clip_brief_action_receipt_id


def test_stale_project_state_is_refused_before_the_owner_is_called(tmp_path: Path) -> None:
    engine, owner = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_stale_key")
    path = engine.store.boba_clip_brief_review_action_path(
        PROJECT_ID, request.clip_brief_action_request_id
    )
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["expected_brief_digest"] = "9" * 64
    path.write_text(json.dumps(stored), encoding="utf-8")
    receipt = asyncio.run(
        engine.submit_clip_brief_action_to_owner(
            PROJECT_ID, request.clip_brief_action_request_id
        )
    )
    assert receipt.stale_state_rejected is True
    assert receipt.error_code == "brief_digest_mismatch"
    assert owner.calls == []


def test_expired_action_request_is_refused(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    payload = _prepared(engine)
    request = _request(engine, payload, "idem_expired_key")
    path = engine.store.boba_clip_brief_review_action_path(
        PROJECT_ID, request.clip_brief_action_request_id
    )
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(stored), encoding="utf-8")
    outcome = engine.validate_clip_brief_action_request(
        PROJECT_ID, request.clip_brief_action_request_id
    )
    assert outcome == {
        "valid": False,
        "code": "expired_snapshot",
        "message": "The clip brief review action expired before submission.",
    }


def test_receipt_cannot_claim_authority_without_an_owner_record(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    forged = BobaClipBriefActionReceiptV1(
        clip_brief_action_receipt_id="clip_brief_receipt_forged",
        clip_brief_action_request_id="clip_brief_action_forged",
        project_id=PROJECT_ID,
        brief_id="brief_a",
        candidate_id="cand_a",
        clip_id="cand_a",
        owning_module_id="creator_learning",
        owning_operation_id="record_creator_feedback_event",
        authoritative_state_changed=True,
    )
    with pytest.raises(ValidationError):
        engine._persist_receipt(PROJECT_ID, forged)


def test_session_updates_are_allowlisted(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_clip_brief_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    updated = engine.update_clip_brief_review_session(
        PROJECT_ID,
        session.clip_brief_review_session_id,
        {"active_filter": "missing_evidence", "show_historical": True},
    )
    assert updated.active_filter == "missing_evidence"
    with pytest.raises(ValidationError):
        engine.update_clip_brief_review_session(
            PROJECT_ID,
            session.clip_brief_review_session_id,
            {"available_action_descriptor_ids": ["clip_brief_action_approve_v1"]},
        )


def test_annotations_are_bounded_and_labelled(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_clip_brief_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    updated = engine.update_clip_brief_review_session(
        PROJECT_ID,
        session.clip_brief_review_session_id,
        {
            "local_annotations": [
                {"field_path": "hook_instruction", "text": "x" * (MAX_ANNOTATION_LENGTH + 50)}
            ]
        },
    )
    assert len(updated.local_annotations) == 1
    assert len(updated.local_annotations[0]["text"]) == MAX_ANNOTATION_LENGTH
    assert (
        updated.local_annotations[0]["notice"]
        == "Review-session annotation — not part of the canonical clip brief."
    )


def test_annotations_reject_credentials(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    session = engine.create_clip_brief_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    with pytest.raises(ValidationError):
        engine.update_clip_brief_review_session(
            PROJECT_ID,
            session.clip_brief_review_session_id,
            {"local_annotations": [{"text": "the api_token is abc"}]},
        )


def test_reset_preserves_canonical_records(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    engine.build_clip_brief_review(PROJECT_ID)
    result = engine.reset_clip_brief_review_metadata(PROJECT_ID)
    assert result["clip_brief_records_preserved"] is True
    assert result["source_media_removed"] is False
    assert result["accepted_outputs_removed"] is False
    assert engine.store.load_clip_briefs(PROJECT_ID) is not None
    assert engine.store.load_candidate_clip_discovery(PROJECT_ID) is not None


def test_export_is_sanitised_and_states_its_limits(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    export = engine.export_clip_brief_review(PROJECT_ID)
    assert export["privacy"]["sensitive_values_excluded"] is True
    assert export["privacy"]["brief_text_rewritten"] is False
    assert export["privacy"]["upload_used"] is False
    assert str(tmp_path) not in json.dumps(export)


def test_review_set_states_the_panel_limits(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    review = engine.build_clip_brief_review(PROJECT_ID)
    joined = " ".join(review["limitations"])
    assert "does not generate, regenerate or rewrite briefs" in joined
    assert "No authoritative clip brief action exists in V1." in joined
    assert review["signal_usage"]["brief_generated_by_panel"] is False


def test_review_set_round_trips_through_the_store(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    built = engine.build_clip_brief_review(PROJECT_ID)
    loaded = engine.load_clip_brief_review(PROJECT_ID)
    assert loaded is not None
    assert loaded["project_id"] == built["project_id"]
    assert BobaClipBriefReviewSetV1.model_validate(loaded)


def test_summary_counts_describe_projections_not_decisions(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path)
    summary = engine.build_clip_brief_review(PROJECT_ID)["review_summary"]
    assert summary["total_brief_count"] == 2
    assert summary["complete_brief_count"] == 2
    assert summary["conflict_count"] == 0
    assert any("not quality counts" in item for item in summary["limitations"])


# ---------------------------------------------------------------------------
# Integration layer, safety gate and facade
# ---------------------------------------------------------------------------
def test_integration_layer_registers_the_module_as_read_only() -> None:
    descriptor = build_boba_module_registry()["clip_brief_review"]
    assert descriptor.implementation_status == "available"
    assert descriptor.implementation_import_path == "olympus.boba.clip_brief_review"
    assert descriptor.read_only is True
    assert descriptor.execution_capable is False
    assert descriptor.planning_capable is False


def test_integration_layer_registers_twenty_one_operations() -> None:
    operations = build_boba_operation_registry()
    ours = {
        key: value
        for key, value in operations.items()
        if key.startswith("clip_brief_review.")
    }
    assert len(ours) == 21
    assert all(item.module_id == "clip_brief_review" for item in ours.values())


def test_only_submit_action_requires_target_approval() -> None:
    operations = build_boba_operation_registry()
    approvals = {
        key
        for key, value in operations.items()
        if key.startswith("clip_brief_review.") and value.target_approval_required
    }
    assert approvals == {"clip_brief_review.submit_action"}


def test_no_operation_is_execution_capable() -> None:
    operations = build_boba_operation_registry()
    ours = {
        key: value
        for key, value in operations.items()
        if key.startswith("clip_brief_review.")
    }
    assert {value.operation_class for value in ours.values()} == {
        "read_only",
        "metadata_reset",
        "export",
    }
    for key, value in ours.items():
        assert value.operation_class not in {
            "approved_execution",
            "planning",
            "repair",
        }, key
        assert value.side_effect_class in {"none", "BOBA_metadata_only"}, key


def test_safety_gate_classifies_every_operation() -> None:
    registry = build_safety_module_operation_registry()["clip_brief_review"]
    assert len(registry) == 21
    assert registry["submit_action"] == "approval_required_read_only"
    read_only = [key for key, value in registry.items() if value == "automatic_read_only"]
    assert len(read_only) == 20


def test_safety_gate_and_layer_agree_on_operation_names() -> None:
    layer = {
        key.split(".", 1)[1]
        for key in build_boba_operation_registry()
        if key.startswith("clip_brief_review.")
    }
    assert layer == set(build_safety_module_operation_registry()["clip_brief_review"])


def test_review_ui_module_is_not_modified() -> None:
    text = Path("src/olympus/boba/review_ui.py").read_text(encoding="utf-8")
    assert "clip_brief_review" not in text


def test_candidate_review_module_is_not_modified() -> None:
    text = Path("src/olympus/boba/candidate_review.py").read_text(encoding="utf-8")
    assert "clip_brief_review" not in text


def test_module_exports_the_public_surface() -> None:
    import olympus.boba as boba_package

    for name in (
        "BobaClipBriefReviewV1",
        "BobaClipBriefReferenceV1",
        "BobaClipBriefSnapshotV1",
        "build_fixed_clip_brief_action_registry",
        "build_fixed_clip_brief_source_registry",
        "owner_schema_required_field_paths",
    ):
        assert hasattr(boba_package, name), name


def test_facade_exposes_every_clip_brief_review_operation(tmp_path: Path) -> None:
    integration = BobaIntegration(
        LocalStorage(root=str(tmp_path / "storage")), BobaMemoryStore(tmp_path / "boba")
    )
    for name in (
        "build_boba_clip_brief_review_registry",
        "inspect_boba_clip_brief_review_registry",
        "create_boba_clip_brief_review_session",
        "inspect_boba_clip_brief_review_session",
        "update_boba_clip_brief_review_session",
        "build_boba_clip_brief_queue",
        "inspect_boba_clip_brief_queue",
        "inspect_boba_clip_brief",
        "build_boba_clip_brief_snapshot",
        "refresh_boba_clip_brief_snapshot",
        "build_boba_clip_brief_comparison",
        "inspect_boba_clip_brief_completeness",
        "inspect_boba_clip_brief_evidence",
        "detect_boba_clip_brief_conflicts",
        "create_boba_clip_brief_action_request",
        "validate_boba_clip_brief_action_request",
        "submit_boba_clip_brief_action_to_owner",
        "inspect_boba_clip_brief_action_receipt",
        "inspect_boba_clip_brief_review_timeline",
        "inspect_boba_clip_brief_review_events",
        "load_boba_clip_brief_review",
        "export_boba_clip_brief_review",
        "reset_boba_clip_brief_review_metadata",
    ):
        assert callable(getattr(integration, name)), name


def test_facade_projects_the_review_set(tmp_path: Path) -> None:
    integration = BobaIntegration(
        LocalStorage(root=str(tmp_path / "storage")), BobaMemoryStore(tmp_path / "boba")
    )
    seed_project(integration.store, PROJECT_ID, selected_candidates=["cand_a"])
    review = integration.clip_brief_review.build_clip_brief_review(PROJECT_ID)
    assert len(review["brief_references"]) == 2
    assert integration.load_boba_clip_brief_review(PROJECT_ID) is not None


def test_facade_routes_a_full_action_round_trip(tmp_path: Path) -> None:
    integration = BobaIntegration(
        LocalStorage(root=str(tmp_path / "storage")), BobaMemoryStore(tmp_path / "boba")
    )
    seed_project(integration.store, PROJECT_ID, selected_candidates=["cand_a"])
    session = integration.create_boba_clip_brief_review_session(
        PROJECT_ID, reviewer_context_id="reviewer_a"
    )
    snapshot = integration.build_boba_clip_brief_snapshot(
        PROJECT_ID, session["clip_brief_review_session_id"], "brief_a"
    )
    request = integration.create_boba_clip_brief_action_request(
        PROJECT_ID,
        clip_brief_review_session_id=session["clip_brief_review_session_id"],
        brief_snapshot_id=snapshot["snapshot"]["brief_snapshot_id"],
        action_descriptor_id=_NOTE,
        decision_value="noted",
        reason="A reviewer note routed through the facade.",
        confirmation_context_digest=snapshot["action_confirmations"][_NOTE],
        idempotency_key="idem_facade_key",
        confirmed=True,
    )
    validation = integration.validate_boba_clip_brief_action_request(
        PROJECT_ID, request["clip_brief_action_request_id"]
    )
    assert validation["valid"] is True
    receipt = asyncio.run(
        integration.submit_boba_clip_brief_action_to_owner(
            PROJECT_ID, request["clip_brief_action_request_id"]
        )
    )
    assert receipt["authoritative_state_changed"] is False
    assert receipt["owning_module_id"] == "creator_learning"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_api_root_and_registry(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    root = client.get(base)
    assert root.status_code == 200
    assert root.json()["project_id"] == PROJECT_ID
    registry = client.get(f"{base}/registry")
    assert registry.status_code == 200
    assert len(registry.json()["sources"]) == 14
    assert len(registry.json()["sections"]) == 9
    assert len(registry.json()["actions"]) == 6


def test_api_registry_reports_the_owner_schema_field_paths(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review/registry"
    ).json()
    assert len(payload["required_field_paths"]) == 22
    assert len(payload["optional_field_paths"]) == 5
    assert payload["supported_brief_schema_id"] == SUPPORTED_BRIEF_SCHEMA_ID


def test_api_queue_reports_priority_tiers(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review/queue"
    )
    assert response.status_code == 200
    assert len(response.json()["priority_tiers"]) == 12
    assert response.json()["total"] == 2


def test_api_rejects_arbitrary_filter_and_sort(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review/queue"
    assert client.get(base, params={"review_filter": "ai_best"}).status_code >= 400
    assert client.get(base, params={"sort": "most_viral"}).status_code >= 400


def test_api_session_lifecycle(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    created = client.post(f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"})
    assert created.status_code == 200
    session_id = created.json()["clip_brief_review_session_id"]
    assert client.get(f"{base}/sessions/{session_id}").status_code == 200
    patched = client.patch(
        f"{base}/sessions/{session_id}", json={"active_filter": "missing_evidence"}
    )
    assert patched.status_code == 200
    assert patched.json()["active_filter"] == "missing_evidence"
    deleted = client.delete(f"{base}/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json()["clip_brief_records_preserved"] is True


def test_api_session_update_rejects_unsupported_fields(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["clip_brief_review_session_id"]
    response = client.patch(
        f"{base}/sessions/{session_id}",
        json={"available_action_descriptor_ids": ["clip_brief_action_approve_v1"]},
    )
    assert response.status_code >= 400


def test_api_brief_projection_endpoints(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review/briefs/brief_a"
    brief = client.get(base)
    assert brief.status_code == 200
    assert len(brief.json()["field_projections"]) == 27
    completeness = client.get(f"{base}/completeness")
    assert completeness.status_code == 200
    assert completeness.json()["completeness"]["complete_for_owner_schema"] is True
    evidence = client.get(f"{base}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()["missing_evidence_count"] == 6
    conflicts = client.get(f"{base}/conflicts")
    assert conflicts.status_code == 200
    assert conflicts.json()["conflict_records"] == []


def test_api_unknown_brief_returns_an_error(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review/briefs/brief_zz"
    )
    assert response.status_code >= 400


def test_api_snapshot_and_refresh(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["clip_brief_review_session_id"]
    snapshot = client.post(
        f"{base}/briefs/brief_a/snapshot",
        json={"clip_brief_review_session_id": session_id},
    )
    assert snapshot.status_code == 200
    snapshot_id = snapshot.json()["snapshot"]["brief_snapshot_id"]
    refreshed = client.post(f"{base}/snapshots/{snapshot_id}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["snapshot"]["brief_id"] == "brief_a"


def test_api_comparison_requires_two_briefs(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review/compare"
    good = client.post(base, json={"brief_ids": ["brief_a", "brief_b"]})
    assert good.status_code == 200
    assert good.json()["comparison"]["no_automatic_winner"] is True
    assert client.post(base, json={"brief_ids": ["brief_a"]}).status_code >= 400


def test_api_action_round_trip(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["clip_brief_review_session_id"]
    snapshot = client.post(
        f"{base}/briefs/brief_a/snapshot",
        json={"clip_brief_review_session_id": session_id},
    ).json()
    created = client.post(
        f"{base}/actions",
        json={
            "clip_brief_review_session_id": session_id,
            "brief_snapshot_id": snapshot["snapshot"]["brief_snapshot_id"],
            "action_descriptor_id": _NOTE,
            "decision_value": "noted",
            "reason": "A reviewer note recorded through the API.",
            "confirmation_context_digest": snapshot["action_confirmations"][_NOTE],
            "idempotency_key": "idem_api_note_key",
            "confirmed": True,
        },
    )
    assert created.status_code == 200
    request_id = created.json()["clip_brief_action_request_id"]
    validated = client.post(f"{base}/actions/{request_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    submitted = client.post(f"{base}/actions/{request_id}/submit")
    assert submitted.status_code == 200
    assert submitted.json()["authoritative_state_changed"] is False
    inspected = client.get(f"{base}/actions/{request_id}")
    assert inspected.status_code == 200
    assert inspected.json()["receipt"] is not None


def test_api_refuses_an_unavailable_action(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    session_id = client.post(
        f"{base}/sessions", json={"reviewer_context_id": "reviewer_a"}
    ).json()["clip_brief_review_session_id"]
    snapshot = client.post(
        f"{base}/briefs/brief_a/snapshot",
        json={"clip_brief_review_session_id": session_id},
    ).json()
    response = client.post(
        f"{base}/actions",
        json={
            "clip_brief_review_session_id": session_id,
            "brief_snapshot_id": snapshot["snapshot"]["brief_snapshot_id"],
            "action_descriptor_id": "clip_brief_action_approve_v1",
            "decision_value": "approve",
            "reason": "Trying to approve the brief.",
            "confirmation_context_digest": "0" * 64,
            "idempotency_key": "idem_api_approve_key",
            "confirmed": True,
        },
    )
    assert response.status_code >= 400


def test_api_timeline_events_and_export(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    timeline = client.get(f"{base}/timeline")
    assert timeline.status_code == 200
    assert timeline.json()["entries"] == []
    events = client.get(f"{base}/events")
    assert events.status_code == 200
    assert events.json()["events"] == []
    export = client.get(f"{base}/export")
    assert export.status_code == 200
    assert export.json()["privacy"]["private_paths_excluded"] is True


def test_api_never_exposes_a_generation_route(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    base = f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review"
    for path in ("/generate", "/regenerate", "/briefs/brief_a/approve"):
        assert client.post(f"{base}{path}", json={}).status_code in {404, 405, 422}


def test_api_export_excludes_private_paths(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    export = client.get(
        f"/api/v1/boba/projects/{PROJECT_ID}/clip-brief-review/export"
    ).json()
    assert str(tmp_path) not in json.dumps(export)


def test_blocked_brief_bucket_is_preserved_end_to_end(tmp_path: Path) -> None:
    engine, _ = _engine(tmp_path, blocked_brief_ids=["brief_b"])
    references = {
        item.brief_id: item.lifecycle_bucket
        for item in engine.build_clip_brief_references(PROJECT_ID)
    }
    assert references == {"brief_a": "selected", "brief_b": "blocked"}


def test_brief_set_with_only_blocked_briefs_still_projects(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    seed_project(store, PROJECT_ID, with_briefs=False)
    store.save_clip_briefs(
        synthetic_brief_set(
            PROJECT_ID,
            blocked=[
                synthetic_brief("brief_z", PROJECT_ID, "cand_a", "cand_a", 10.0, 40.0)
            ],
        )
    )
    engine = BobaClipBriefReviewV1(store, _StubOwner())  # type: ignore[arg-type]
    references = engine.build_clip_brief_references(PROJECT_ID)
    assert [item.lifecycle_bucket for item in references] == ["blocked"]
