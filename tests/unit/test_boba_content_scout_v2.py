"""BOBA Content Scout V2 contracts, behavior, integration, and safety tests."""

from __future__ import annotations

import asyncio
import copy
import json
import socket
import subprocess
import urllib.request
from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_content_scout_v2 import (
    _recommendations,
    build_synthetic_content_scout,
    build_synthetic_scout_items,
    build_synthetic_scout_signals,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaCandidateV1,
    BobaContentScoutSetV2,
    BobaContentScoutSignalUsageV2,
    BobaContentScoutSummaryV2,
    BobaContentScoutV2,
    BobaIntegration,
    BobaMemoryStore,
    BobaProjectMemoryV1,
    BobaScoutImportSourceV2,
    BobaScoutItemV2,
    BobaScoutRecommendationV2,
    BobaScoutRejectedItemV2,
    BobaScoutReviewQueueV2,
    BobaScoutScoreV2,
    BobaSuggestedShortAngleV2,
    import_scout_items_from_csv,
    import_scout_items_from_json,
    normalize_scout_item,
    score_scout_items,
)
from olympus.boba.content_scout import _duplicate_map
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_content_scout_v2_test"


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaContentScoutSetV2:
    return build_synthetic_content_scout(project_id)


def _item(item_id: str) -> BobaScoutItemV2:
    return next(item for item in _result().scout_items if item.item_id == item_id)


def _score(item_id: str) -> BobaScoutScoreV2:
    return next(
        score for score in _result().scored_items if score.item_id == item_id
    )


def _recommendation(item_id: str) -> BobaScoutRecommendationV2:
    queue = _result().review_queue
    groups = (
        queue.top_items,
        queue.backup_items,
        queue.permission_needed_items,
        queue.blocked_items,
        queue.duplicate_or_similar_items,
    )
    return next(
        recommendation
        for group in groups
        for recommendation in group
        if recommendation.item_id == item_id
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Content Scout V2 Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=120.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _integration(
    tmp_path: Path,
    project_id: str = PROJECT_ID,
) -> tuple[BobaIntegration, BobaMemoryStore]:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    asyncio.run(StorageProjectRepository(storage).save(_project(project_id)))
    return BobaIntegration(storage, store), store


def test_01_scout_set_contract_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_content_scout_v2"
    assert BobaContentScoutSetV2.model_validate(payload) == _result()


def test_02_import_source_contract_serializes() -> None:
    source = _result().imported_sources[0]
    assert BobaScoutImportSourceV2.model_validate(
        source.model_dump(mode="json")
    ) == source


def test_03_scout_item_contract_serializes() -> None:
    item = _item("owned_emotional_story")
    assert BobaScoutItemV2.model_validate(item.model_dump(mode="json")) == item


def test_04_score_contract_serializes() -> None:
    score = _score("owned_emotional_story")
    assert BobaScoutScoreV2.model_validate(score.model_dump(mode="json")) == score


def test_05_recommendation_contract_serializes() -> None:
    recommendation = _recommendation("owned_emotional_story")
    assert BobaScoutRecommendationV2.model_validate(
        recommendation.model_dump(mode="json")
    ) == recommendation


def test_06_review_queue_contract_serializes() -> None:
    queue = _result().review_queue
    assert BobaScoutReviewQueueV2.model_validate(
        queue.model_dump(mode="json")
    ) == queue


def test_07_suggested_short_angle_contract_serializes() -> None:
    angle = _recommendation("owned_emotional_story").suggested_short_angles[0]
    assert BobaSuggestedShortAngleV2.model_validate(
        angle.model_dump(mode="json")
    ) == angle


def test_08_rejected_item_contract_serializes() -> None:
    rejected = _result().rejected_items[0]
    assert BobaScoutRejectedItemV2.model_validate(
        rejected.model_dump(mode="json")
    ) == rejected


def test_09_summary_contract_serializes() -> None:
    summary = _result().scout_summary
    assert BobaContentScoutSummaryV2.model_validate(
        summary.model_dump(mode="json")
    ) == summary


def test_10_signal_usage_contract_serializes() -> None:
    usage = _result().signal_usage
    assert BobaContentScoutSignalUsageV2.model_validate(
        usage.model_dump(mode="json")
    ) == usage


def test_11_csv_import_accepts_flexible_headers(tmp_path: Path) -> None:
    path = tmp_path / "scout.csv"
    path.write_text(
        "title,summary,url,source,duration,tags,category,channel,published_date,"
        "rights_status,notes\n"
        "A reveal,An emotional lesson,https://example.invalid/ref,local list,01:30,"
        '"story,reveal",education,Creator,2026-01-01,owned,Review manually\n',
        encoding="utf-8",
    )
    source, items, rejected = import_scout_items_from_csv(path)
    assert source.accepted_count == 1
    assert rejected == []
    assert items[0].description == "An emotional lesson"
    assert items[0].duration_seconds == 90.0
    assert items[0].categories == ["education"]
    assert items[0].creator_or_channel == "Creator"


def test_12_json_import_accepts_list_format(tmp_path: Path) -> None:
    path = tmp_path / "scout.json"
    path.write_text(
        json.dumps([{"title": "List item", "rights_status": "licensed"}]),
        encoding="utf-8",
    )
    source, items, rejected = import_scout_items_from_json(path)
    assert source.source_type == "json"
    assert [item.title for item in items] == ["List item"]
    assert rejected == []


def test_13_json_import_accepts_object_with_items_format(tmp_path: Path) -> None:
    path = tmp_path / "scout.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "description": "Object-wrapped metadata",
                        "rights_status": "owned",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    source, items, rejected = import_scout_items_from_json(path)
    assert source.accepted_count == 1
    assert items[0].description == "Object-wrapped metadata"
    assert rejected == []


def test_14_empty_item_rejected_with_warning() -> None:
    result = BobaContentScoutV2().analyze(PROJECT_ID, manual_items=[{}])
    assert result.scout_items == []
    assert len(result.rejected_items) == 1
    assert "title or description" in result.rejected_items[0].reason_rejected
    assert any("rejected" in warning for warning in result.warnings)


def test_15_unsupported_rights_status_becomes_unknown_with_warning() -> None:
    item = normalize_scout_item(
        {"title": "Metadata item", "rights_status": "probably_safe"}
    )
    assert item.rights_status == "unknown"
    assert any("Unsupported rights status" in warning for warning in item.warnings)


def test_16_owned_item_can_become_review_now() -> None:
    recommendation = _recommendation("owned_emotional_story")
    assert recommendation.recommendation == "review_now"
    assert recommendation.rights_review_required is False


def test_17_licensed_item_can_become_review_now() -> None:
    recommendation = _recommendation("licensed_tutorial")
    assert recommendation.recommendation == "review_now"
    assert recommendation.rights_review_required is False


def test_18_permission_granted_item_can_become_review_now() -> None:
    recommendation = _recommendation("motivational_podcast")
    assert recommendation.recommendation == "review_now"
    assert recommendation.rights_review_required is False


def test_19_permission_needed_item_recommends_seek_permission() -> None:
    recommendation = _recommendation("permission_needed_high_potential")
    assert recommendation.recommendation == "seek_permission"
    assert recommendation.rights_review_required is True


def test_20_unknown_rights_requires_rights_review() -> None:
    recommendation = _recommendation("funny_unknown")
    assert recommendation.recommendation == "seek_permission"
    assert recommendation.rights_review_required is True
    assert any("unknown" in warning.casefold() for warning in recommendation.warnings)


def test_21_blocked_rights_goes_to_blocked_queue() -> None:
    assert any(
        item.item_id == "blocked_source"
        for item in _result().review_queue.blocked_items
    )
    assert _recommendation("blocked_source").recommendation == "blocked"


def test_22_duplicate_item_lowers_novelty() -> None:
    assert (
        _score("owned_emotional_duplicate").novelty_score
        < _score("owned_emotional_story").novelty_score
    )
    assert any(
        item.item_id == "owned_emotional_duplicate"
        for item in _result().review_queue.duplicate_or_similar_items
    )


def test_23_creator_learning_preference_raises_creator_fit() -> None:
    item = normalize_scout_item(
        {
            "title": "Emotional tutorial lesson",
            "description": "A concise creator journey.",
            "rights_status": "owned",
        }
    )
    baseline = score_scout_items([item])[0]
    learned = score_scout_items(
        [item],
        creator_learning=build_synthetic_scout_signals()["creator_learning"],
    )[0]
    assert learned.creator_fit_score > baseline.creator_fit_score


def test_24_approval_rejection_pattern_affects_scoring() -> None:
    item = normalize_scout_item(
        {
            "title": "Generic update with a slow vague opening",
            "rights_status": "owned",
        }
    )
    baseline = score_scout_items([item])[0]
    learned = score_scout_items(
        [item],
        approval_rejection_learning=build_synthetic_scout_signals()[
            "approval_rejection_learning"
        ],
    )[0]
    assert learned.creator_fit_score < baseline.creator_fit_score
    assert learned.review_priority_score < baseline.review_priority_score


def test_25_performance_feedback_affects_scoring_conservatively() -> None:
    item = normalize_scout_item(
        {
            "title": "Curiosity hook and emotional comeback",
            "description": "A clear lesson with a reveal.",
            "rights_status": "owned",
        }
    )
    baseline = score_scout_items([item])[0]
    learned = score_scout_items(
        [item],
        performance_feedback=build_synthetic_scout_signals()[
            "performance_feedback"
        ],
    )[0]
    assert learned.creator_fit_score > baseline.creator_fit_score
    assert learned.creator_fit_score - baseline.creator_fit_score <= 0.28
    assert any("conservatively" in reason for reason in learned.score_reasons)


def test_26_hook_potential_terms_raise_hook_score() -> None:
    generic = normalize_scout_item(
        {"title": "Weekly creator update", "rights_status": "owned"}
    )
    hooked = normalize_scout_item(
        {
            "title": "Why the secret mistake caused an unexpected result reveal",
            "rights_status": "owned",
        }
    )
    generic_score, hooked_score = BobaContentScoutV2().score_items(
        [generic, hooked]
    )
    assert hooked_score.hook_potential_score > generic_score.hook_potential_score


def test_27_emotional_story_terms_raise_emotional_score() -> None:
    generic = normalize_scout_item(
        {"title": "Weekly creator update", "rights_status": "owned"}
    )
    emotional = normalize_scout_item(
        {
            "title": "A struggle, regret, rescue, and comeback story",
            "description": "Growth after failure led to hope and success.",
            "rights_status": "owned",
        }
    )
    generic_score, emotional_score = BobaContentScoutV2().score_items(
        [generic, emotional]
    )
    assert emotional_score.emotional_story_score > generic_score.emotional_story_score


def test_28_weak_generic_item_gets_low_priority() -> None:
    recommendation = _recommendation("weak_generic")
    assert recommendation.priority == "low"
    assert _score("weak_generic").review_priority_score < 0.45


def test_29_suggested_short_angles_do_not_invent_facts() -> None:
    recommendation = _recommendation("owned_emotional_story")
    encoded = json.dumps(
        [angle.model_dump(mode="json") for angle in recommendation.suggested_short_angles]
    ).casefold()
    assert "possible angle" in encoded
    assert "verify the source manually" in encoded
    assert not any(term in encoded for term in ("million views", "went viral", "audience loved"))


def test_30_review_queue_separates_all_required_groups() -> None:
    queue = _result().review_queue
    assert queue.top_items
    assert queue.backup_items
    assert queue.permission_needed_items
    assert queue.blocked_items
    assert queue.duplicate_or_similar_items
    group_ids = [
        {item.item_id for item in group}
        for group in (
            queue.top_items,
            queue.backup_items,
            queue.permission_needed_items,
            queue.blocked_items,
        )
    ]
    assert all(
        left.isdisjoint(right)
        for index, left in enumerate(group_ids)
        for right in group_ids[index + 1 :]
    )


def test_31_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_32_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False
    assert _item("owned_emotional_story").source_url is not None


def test_33_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_34_export_excludes_raw_media_secrets_and_full_transcripts(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_content_scout_v2(_result())
    export = store.export_content_scout_v2(PROJECT_ID)
    scout = export["content_scout_v2"]
    assert isinstance(scout, dict)
    items = scout["scout_items"]
    assert isinstance(items, list)
    for item in items:
        assert isinstance(item, dict)
        assert "source_url" not in item
        assert "permission_notes" not in item
        assert "user_notes" not in item
        assert "raw_metadata_summary" not in item
    encoded = json.dumps(export).casefold()
    for forbidden in (
        "raw_media",
        "full_transcript",
        "api_key",
        "access_token",
        "password",
        ".mp4",
        ".wav",
    ):
        assert forbidden not in encoded


def test_35_reset_removes_only_content_scout_v2_artifact(tmp_path: Path) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    candidate = BobaCandidateV1(
        candidate_id="candidate_v1_survives",
        title="Scout V1 survives",
        rights_status="user_owned",
        permission_confirmed=True,
    )
    store.save_scout_candidate(candidate)
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    store.save_content_scout_v2(_result())
    assert store.reset_content_scout_v2(PROJECT_ID) is True
    assert store.load_content_scout_v2(PROJECT_ID) is None
    assert store.load_scout_candidate(candidate.candidate_id) == candidate
    assert store.load_project_memory(PROJECT_ID) is not None


def test_36_missing_optional_artifacts_degrade_gracefully() -> None:
    result = BobaContentScoutV2().analyze(
        PROJECT_ID,
        manual_items=[
            {
                "title": "Local metadata only",
                "description": "A possible lesson.",
                "rights_status": "unknown",
            }
        ],
    )
    assert result.scored_items
    assert result.signal_usage.fallback_used is True
    assert {
        "creator_learning",
        "approval_rejection_learning",
        "performance_feedback",
        "memory",
        "scout_v1",
    }.issubset(result.signal_usage.unavailable_signals)


def test_37_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_content_scout_v2(_result())
    path = store.content_scout_v2_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/content_scout_v2/index.json"
    )
    assert payload["schema_version"] == "boba_content_scout_v2"
    assert store.load_content_scout_v2(PROJECT_ID) == saved


def test_38_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, _store = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        create_response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/content-scout-v2",
            json={
                "manual_items": build_synthetic_scout_items(),
                "source_label": "api_test",
            },
        )
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/content-scout-v2"
        )
    assert create_response.status_code == 200, create_response.text
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_content_scout_v2"
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Content Scout V2" in panel
    assert "Content Scout V2 uses local/user-provided metadata only." in panel
    assert (
        "BOBA does not fetch URLs, scrape platforms, download videos, or" in panel
    )


def test_39_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_content_scout_v2(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/content-scout-v2/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["privacy"]["source_urls_excluded"] is True
    assert payload["privacy"]["external_api_used"] is False
    for item in payload["content_scout_v2"]["scout_items"]:
        assert "source_url" not in item


def test_40_api_delete_resets_project_artifact_only(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_content_scout_v2(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/content-scout-v2"
        )
    assert response.status_code == 200, response.text
    assert response.json()["content_scout_v2_removed"] is True
    assert response.json()["scout_v1_removed"] is False
    assert response.json()["memory_removed"] is False
    assert store.load_content_scout_v2(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_41_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.external_api_used_false is True
    assert report.url_fetching_used_false is True
    assert report.downloading_used_false is True


def test_42_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.items_imported >= 8
    assert report.duplicates_detected is True
    assert report.reset_project_only is True


def test_43_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Content Scout V2 must not invoke a renderer.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert build_synthetic_content_scout("proj_no_render").scout_items


def test_44_no_downloading_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Content Scout V2 must not download or write media.")

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    result = build_synthetic_content_scout("proj_no_download")
    assert result.signal_usage.downloading_used is False


def test_45_no_url_fetching_is_triggered(monkeypatch: Any) -> None:
    def fail_url_fetch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Content Scout V2 must not fetch a URL.")

    monkeypatch.setattr(urllib.request, "urlopen", fail_url_fetch)
    result = build_synthetic_content_scout("proj_no_url_fetch")
    assert result.signal_usage.url_fetching_used is False
    assert any(item.source_url for item in result.scout_items)


def test_46_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Content Scout V2 must not use the network.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = build_synthetic_content_scout("proj_no_network")
    assert result.signal_usage.external_api_used is False


def test_47_no_reports_or_media_are_staged() -> None:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    staged = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines()]
    forbidden = (
        "work/",
        "storage_data/",
        "media/",
        ".venv/",
        "node_modules/",
        "frontend/.next/",
    )
    assert not any(path.startswith(forbidden) for path in staged)
    assert not any(
        path.casefold().endswith((".mp4", ".mov", ".wav", ".webm"))
        for path in staged
    )

# ---------------------------------------------------------------------------
# Helpers for the behavioural proof (test_48 onward).
# ---------------------------------------------------------------------------
SCORE_FIELDS = (
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
ANGLE_FIELDS = {
    "angle_id",
    "title",
    "hook_direction",
    "why_it_might_work",
    "risk",
    "confidence",
}
TOP_LEVEL_FIELDS = {
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
QUEUE_LISTS = (
    "top_items",
    "backup_items",
    "permission_needed_items",
    "blocked_items",
    "duplicate_or_similar_items",
)
RECOMMENDATION_VALUES = {
    "review_now",
    "save_for_later",
    "seek_permission",
    "blocked",
    "reject",
}
AUTHORITY_KEYS = {"approved", "authorized", "selected", "render_ready", "publish"}
_NEGATION_MARKERS = (
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
_CLEARANCE_TOKENS = ("cleared", "verified", "confirmed")
_PERFORMANCE_TOKENS = (
    "predict",
    "prediction",
    "forecast",
    "guarantee",
    "guaranteed",
    "will perform",
    "viral",
)


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


def _key_paths(payload: Any, leaf_names: tuple[str, ...], path: str = "") -> set[str]:
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


def _snapshot(value: Any) -> Any:
    """Deep copy, normalising models and mappings onto one comparison surface."""
    if hasattr(value, "model_dump"):
        return copy.deepcopy(value.model_dump(mode="json"))
    return copy.deepcopy(value)


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


def _all_recommendations(
    result: BobaContentScoutSetV2,
) -> list[BobaScoutRecommendationV2]:
    return [
        item
        for name in QUEUE_LISTS
        for item in getattr(result.review_queue, name)
    ]


def _signals_kwargs() -> dict[str, Any]:
    """The fixture signals mapped onto analyze()'s parameter names.

    build_synthetic_scout_signals() returns the key ``memory``; analyze() takes
    ``boba_memory=``. analyze() accepts a missing boba_memory silently, so a
    dropped mapping would exercise the degraded path invisibly.
    """
    signals = build_synthetic_scout_signals()
    return {
        "creator_learning": signals["creator_learning"],
        "approval_rejection_learning": signals["approval_rejection_learning"],
        "performance_feedback": signals["performance_feedback"],
        "boba_memory": signals["memory"],
    }


def test_helper_matchers_are_falsifiable() -> None:
    """Positive controls for the denial-aware matchers.

    Without these, the absence assertions in test_56 and test_68 would be
    unfalsifiable: a matcher that never fires would satisfy them trivially.
    """
    assert _claims_clearance("Rights are cleared and copyright is confirmed.") is True
    assert _claims_performance("This short will predict a viral audience response.") is True
    # The engine's own honest text must NOT be flagged.
    assert _claims_clearance("Has a human independently confirmed rights and permission?") is False
    assert _claims_performance(
        "Scores estimate metadata fit only and do not predict audience performance."
    ) is False

# ---------------------------------------------------------------------------
# Requirement 1 — the clamp's reachable limb (task 4.1)
# ---------------------------------------------------------------------------
def test_48_score_values_lie_within_the_unit_interval() -> None:
    """STRUCTURAL TRIPWIRE, NOT PROOF.

    No available input can falsify this. `_clamp`'s bound limbs are structurally
    unreachable — every `_score` component caps its terms with `min(...)` and the
    global ceiling is 0.91 — and `BobaScoutScoreV2` declares `ge=0.0, le=1.0` as a
    second independent guard. Retained per R1.4 as a regression tripwire and
    excluded from the validator's `passed` formula, because a term guaranteed by
    the contract layer is exactly what R9.11 forbids. The load-bearing assertion
    is test_49.
    """
    for score in _result().scored_items:
        dumped = score.model_dump()
        for field in SCORE_FIELDS:
            assert 0.0 <= dumped[field] <= 1.0, f"{score.item_id}.{field}"


def test_49_score_values_are_rounded_to_four_decimals() -> None:
    """The real G2 detector: 32 of 100 values carry float tails without the clamp."""
    for score in _result().scored_items:
        dumped = score.model_dump()
        for field in SCORE_FIELDS:
            value = dumped[field]
            assert round(value, 4) == value, f"{score.item_id}.{field}={value!r}"


def test_50_angle_confidence_is_rounded_and_bounded() -> None:
    """Covers the second clamp site at content_scout.py:1184."""
    angles = [
        angle
        for recommendation in _all_recommendations(_result())
        for angle in recommendation.suggested_short_angles
    ]
    assert angles
    for angle in angles:
        assert round(angle.confidence, 4) == angle.confidence, angle.angle_id
        assert 0.0 <= angle.confidence <= 1.0, angle.angle_id


def test_51_hook_saturated_candidate_holds_the_fixture_maximum_hook_score() -> None:
    """Positive control keeping C9 load-bearing."""
    result = _result()
    saturated = _score("hook_saturated_owned")
    assert saturated.hook_potential_score == max(
        item.hook_potential_score for item in result.scored_items
    )
    assert saturated.hook_potential_score > _score("weak_generic").hook_potential_score


# ---------------------------------------------------------------------------
# Requirements 2 and 3 — duplicates and rights (task 4.2)
# ---------------------------------------------------------------------------
def test_52_duplicate_candidate_is_recommended_for_rejection() -> None:
    """The decision itself, not a side effect with an independent cause.

    Novelty reduction (`_score`) and `duplicate_or_similar_items` membership
    (`_queue`) are both caused by `duplicate_of`, so neither is proof (R2.4).
    `score.warnings` also names the original but survives branch removal, so it is
    barred too. `recommendation.reason` is authored inside the `elif duplicate_of:`
    branch and is therefore branch-coupled.
    """
    result = _result()
    recommendation = _recommendations(result)["owned_emotional_duplicate"]

    assert recommendation.recommendation == "reject"
    assert _duplicate_map(result.scout_items)["owned_emotional_duplicate"] == (
        "owned_emotional_story"
    )
    assert "owned_emotional_story" in recommendation.reason


def test_53_unsupported_rights_status_normalizes_through_analyze() -> None:
    """R3.1 requires the guard be driven through analyze(), not normalize_scout_item."""
    result = BobaContentScoutV2().analyze(
        "proj_unsupported_rights",
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

    item = next(row for row in result.scout_items if row.item_id == "probably_safe_item")
    assert item.rights_status == "unknown"
    assert any("Unsupported rights status" in warning for warning in item.warnings)


def test_54_blocked_check_precedes_the_duplicate_check() -> None:
    """R3.5 branch order: blocked wins over duplicate.

    Dual membership plus the blocked-branch reason is the evidence. `_queue` places
    any candidate in duplicate_or_similar_items whenever it is in the duplicate map
    regardless of recommendation, so dual membership with a "blocked" recommendation
    can only arise if the blocked branch ran first.
    """
    result = _result()
    recommendation = _recommendations(result)["blocked_emotional_duplicate"]

    assert recommendation.recommendation == "blocked"
    assert recommendation.reason == "The user-provided rights status is blocked."
    assert any(
        item.item_id == "blocked_emotional_duplicate"
        for item in result.review_queue.blocked_items
    )
    assert any(
        item.item_id == "blocked_emotional_duplicate"
        for item in result.review_queue.duplicate_or_similar_items
    )
    assert _duplicate_map(result.scout_items)["blocked_emotional_duplicate"] == (
        "blocked_source"
    )


def test_55_every_recommendation_warns_that_copyright_is_unconfirmed() -> None:
    recommendations = _all_recommendations(_result())
    assert recommendations
    for recommendation in recommendations:
        assert any(
            "cannot confirm copyright safety" in warning.casefold()
            for warning in recommendation.warnings
        ), recommendation.item_id


def test_56_no_output_string_claims_rights_are_cleared() -> None:
    payload = _result().model_dump(mode="json")

    offenders = [text for text in _walk_strings(payload) if _claims_clearance(text)]
    assert offenders == []

    # Positive control: the matcher must fire on an injected claim.
    tainted = copy.deepcopy(payload)
    tainted["warnings"] = [*tainted["warnings"], "Rights are cleared and copyright is confirmed."]
    assert [text for text in _walk_strings(tainted) if _claims_clearance(text)]


# ---------------------------------------------------------------------------
# Requirement 4 — determinism with exactly two timestamp exceptions (task 4.3)
# ---------------------------------------------------------------------------
def test_57_repeated_analysis_differs_only_at_the_two_timestamp_locations() -> None:
    """Scout has TWO timestamp locations. #44's root-only rule does not transfer.

    A recursive strip-all-`created_at` is forbidden: it would silently absorb a
    newly introduced nondeterministic field, which is what R4.3 exists to prevent.
    """
    engine = BobaContentScoutV2()
    items = build_synthetic_scout_items()
    first = engine.analyze("proj_determinism", manual_items=items, **_signals_kwargs())
    second = engine.analyze("proj_determinism", manual_items=items, **_signals_kwargs())

    left = first.model_dump(mode="json")
    right = second.model_dump(mode="json")

    allowed = {"created_at"} | {
        f"imported_sources[{index}].imported_at"
        for index in range(len(left["imported_sources"]))
    }

    # The exclusion set must be exactly the two documented locations.
    assert _key_paths(left, ("created_at", "imported_at")) == allowed
    assert _key_paths(right, ("created_at", "imported_at")) == allowed

    # published_at is deterministic source metadata and stays inside the
    # compared surface.
    published = _key_paths(left, ("published_at",))
    assert published
    assert published.isdisjoint(allowed)
    for path in published:
        assert path not in _differing_paths(left, right)

    differing = _differing_paths(left, right)
    assert differing <= allowed, f"nondeterministic fields: {sorted(differing - allowed)}"

    for payload in (left, right):
        payload.pop("created_at", None)
        for source in payload["imported_sources"]:
            source.pop("imported_at", None)
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def test_58_ordering_is_stable_across_runs() -> None:
    engine = BobaContentScoutV2()
    items = build_synthetic_scout_items()
    first = engine.analyze("proj_order", manual_items=items, **_signals_kwargs())
    second = engine.analyze("proj_order", manual_items=items, **_signals_kwargs())

    assert [row.item_id for row in first.scout_items] == [
        row.item_id for row in second.scout_items
    ]
    assert [row.item_id for row in first.scored_items] == [
        row.item_id for row in second.scored_items
    ]
    for name in QUEUE_LISTS:
        assert [row.item_id for row in getattr(first.review_queue, name)] == [
            row.item_id for row in getattr(second.review_queue, name)
        ], name


# ---------------------------------------------------------------------------
# Requirement 5 — caller-supplied inputs are never mutated (task 4.4)
# ---------------------------------------------------------------------------
def test_59_analyze_does_not_mutate_any_caller_supplied_input() -> None:
    """Nothing is excluded from the comparison; an exclusion leaves a channel unproven."""
    items = build_synthetic_scout_items()
    signals = _signals_kwargs()
    inputs = {"manual_items": items, **signals}
    before = {name: _snapshot(value) for name, value in inputs.items()}

    result = BobaContentScoutV2().analyze(
        "proj_no_mutation", manual_items=items, **signals
    )

    after = {name: _snapshot(value) for name, value in inputs.items()}
    for name in inputs:
        assert after[name] == before[name], name

    # A dropped memory -> boba_memory mapping would silently exercise the
    # degraded path, so assert the artifacts actually arrived.
    usage = result.signal_usage
    assert usage.creator_learning_used is True
    assert usage.approval_rejection_learning_used is True
    assert usage.performance_feedback_used is True
    assert usage.memory_used is True


def test_60_manual_items_length_and_order_are_unchanged() -> None:
    items = build_synthetic_scout_items()
    ids_before = [row.get("item_id") for row in items]
    length_before = len(items)

    BobaContentScoutV2().analyze("proj_order_stable", manual_items=items, **_signals_kwargs())

    assert len(items) == length_before
    assert [row.get("item_id") for row in items] == ids_before


# ---------------------------------------------------------------------------
# Requirement 6 — the advisory authority boundary (task 4.5)
# ---------------------------------------------------------------------------
def test_61_no_authority_bearing_field_exists_at_any_depth() -> None:
    """EXACT key-name equality, never substring: `published_at` contains `publish`."""
    payload = _result().model_dump(mode="json")

    keys = set(_walk_keys(payload))
    assert keys & AUTHORITY_KEYS == set()

    # Positive control: the scan must find an injected authority field.
    tainted = copy.deepcopy(payload)
    tainted["approved"] = True
    assert set(_walk_keys(tainted)) & AUTHORITY_KEYS == {"approved"}


def test_62_top_level_field_set_is_exactly_the_thirteen_documented_names() -> None:
    result = _result()
    payload = result.model_dump(mode="json")

    assert set(payload) == TOP_LEVEL_FIELDS
    assert "recommendations" not in payload

    flattened = _recommendations(result)
    assert {item.item_id for item in _all_recommendations(result)} == set(flattened)


def test_63_published_at_is_source_metadata_and_never_an_approval() -> None:
    result = _result()
    assert _item("hook_saturated_owned").published_at

    for recommendation in _all_recommendations(result):
        dumped = recommendation.model_dump(mode="json")
        assert "published_at" not in dumped, recommendation.item_id


def test_64_every_recommendation_value_is_one_of_the_five() -> None:
    recommendations = _all_recommendations(_result())
    assert recommendations
    for recommendation in recommendations:
        assert recommendation.recommendation in RECOMMENDATION_VALUES


# ---------------------------------------------------------------------------
# Requirement 7 — human review is always required (task 4.6)
# ---------------------------------------------------------------------------
def test_65_human_review_is_required_on_every_recommendation() -> None:
    """Coverage assertions matter: without them one branch of _recommend could hide."""
    result = _result()
    recommendations = _all_recommendations(result)
    assert recommendations

    for recommendation in recommendations:
        assert recommendation.human_review_required is True, recommendation.item_id

    statuses = {row.rights_status for row in result.scout_items}
    assert statuses == {
        "owned",
        "licensed",
        "permission_granted",
        "permission_needed",
        "unknown",
        "blocked",
    }
    assert {item.recommendation for item in recommendations} == RECOMMENDATION_VALUES


def test_66_human_review_is_independent_of_rights_review() -> None:
    relaxed = [
        item
        for item in _all_recommendations(_result())
        if item.rights_review_required is False
    ]
    assert relaxed, "positive control: the selection must be non-empty"
    for recommendation in relaxed:
        assert recommendation.human_review_required is True, recommendation.item_id


# ---------------------------------------------------------------------------
# Requirement 8 — no audience-performance claim (task 4.7)
# ---------------------------------------------------------------------------
def test_67_engine_authored_limitations_are_present_verbatim() -> None:
    limitations = _result().limitations
    for expected in (
        "Scores estimate metadata fit only and do not predict audience performance.",
        "No external trend knowledge was verified or used.",
        "Human review and an independent rights check remain required.",
    ):
        assert expected in limitations, expected


def test_68_no_output_string_asserts_a_prediction_or_guarantee() -> None:
    payload = _result().model_dump(mode="json")

    offenders = [text for text in _walk_strings(payload) if _claims_performance(text)]
    assert offenders == []

    tainted = copy.deepcopy(payload)
    tainted["warnings"] = [
        *tainted["warnings"],
        "This short will predict a viral audience response.",
    ]
    assert [text for text in _walk_strings(tainted) if _claims_performance(text)]


def test_69_angle_field_set_is_exact() -> None:
    angles = [
        angle
        for recommendation in _all_recommendations(_result())
        for angle in recommendation.suggested_short_angles
    ]
    assert angles
    for angle in angles:
        assert set(angle.model_dump(mode="json")) == ANGLE_FIELDS, angle.angle_id


# ---------------------------------------------------------------------------
# Requirement 10 — no-network additions around the untouched test_43-test_46
# (task 4.8)
# ---------------------------------------------------------------------------
def test_70_a_source_url_is_retained_without_being_fetched() -> None:
    result = _result()
    item = _item("owned_emotional_story")

    assert result.signal_usage.url_fetching_used is False
    assert item.source_url is not None

    recommendation = _recommendations(result)["owned_emotional_story"]
    assert any(
        "only if authorized" in question.casefold()
        for question in recommendation.suggested_review_questions
    )


def test_71_an_oversized_import_is_declined(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.json"
    oversized.write_text(
        json.dumps([{"item_id": "x", "title": "y" * 2_100_000}]), encoding="utf-8"
    )

    with pytest.raises(ValidationError) as caught:
        BobaContentScoutV2().analyze(
            "proj_oversized", import_paths=[oversized], **_signals_kwargs()
        )
    assert "2" in str(caught.value)


def test_72_a_non_local_import_path_is_declined(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        BobaContentScoutV2().analyze(
            "proj_remote", import_paths=["https://example.invalid/items.json"]
        )
    with pytest.raises(ValidationError):
        BobaContentScoutV2().analyze(
            "proj_missing", import_paths=[tmp_path / "absent.json"]
        )


# ---------------------------------------------------------------------------
# Requirement 12 — persistence and ownership boundaries (task 4.9)
# ---------------------------------------------------------------------------
def test_73_store_round_trips_and_keys_off_the_scout_project_id(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    scout = build_synthetic_content_scout("proj_round_trip")

    saved = store.save_content_scout_v2(scout)
    path = store.content_scout_v2_path(scout.project_id)

    assert path.is_file()
    assert store.load_content_scout_v2("proj_round_trip") == saved


def test_74_export_omits_private_keys_and_empties_review_questions(
    tmp_path: Path,
) -> None:
    """Reads the ACTUAL popped keys. The self-reported `privacy` block is forbidden
    as evidence: its members are hardcoded literals and would pass even if every
    private key were exported."""
    store = BobaMemoryStore(tmp_path / "boba")
    scout = build_synthetic_content_scout("proj_export")
    store.save_content_scout_v2(scout)
    export = store.export_content_scout_v2("proj_export")
    exported = export["content_scout_v2"]

    # Positive control: the keys ARE present before export, so their absence
    # afterwards is meaningful rather than trivially true of any dictionary.
    unexported = scout.model_dump(mode="json")
    assert any("source_path" in row for row in unexported["imported_sources"])
    assert any("source_url" in row for row in unexported["scout_items"])

    for source in exported["imported_sources"]:
        assert "source_path" not in source
    for item in exported["scout_items"]:
        for key in ("source_url", "permission_notes", "user_notes", "raw_metadata_summary"):
            assert key not in item, key
    for name in QUEUE_LISTS:
        for recommendation in exported["review_queue"][name]:
            assert recommendation["suggested_review_questions"] == []

    # The export carries a self-reported `privacy` block of hardcoded literals.
    # It is deliberately NOT read as evidence (R12.5): it would report success
    # even if every private key above had been exported.
    assert export["privacy"]["local_paths_excluded"] is True

    assert json.loads(json.dumps(export)) == export


def test_75_a_missing_artifact_is_not_fabricated(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")

    assert store.load_content_scout_v2("proj_absent") is None
    with pytest.raises(ValidationError) as caught:
        store.export_content_scout_v2("proj_absent")
    assert "proj_absent" in str(caught.value) or "proj_absent" in str(
        getattr(caught.value, "details", "")
    )
