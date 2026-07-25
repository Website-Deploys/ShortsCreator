"""BOBA Content Scout V2 contracts, behavior, integration, and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_content_scout_v2 import (
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
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
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
