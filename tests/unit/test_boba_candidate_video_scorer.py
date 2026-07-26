"""BOBA Candidate Video Scorer V1 contracts, behavior, and safety tests."""

from __future__ import annotations

import asyncio
import csv
import json
import socket
import subprocess
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_candidate_video_scorer import (
    build_synthetic_candidate_metadata,
    build_synthetic_candidate_video_scorer,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import BobaIntegration, BobaMemoryStore, BobaProjectMemoryV1
from olympus.boba.candidate_video_scorer import (
    BobaCandidateRightsReviewV1,
    BobaCandidateVideoImportSourceV1,
    BobaCandidateVideoRecommendationV1,
    BobaCandidateVideoReviewQueueV1,
    BobaCandidateVideoScorerSetV1,
    BobaCandidateVideoScorerV1,
    BobaCandidateVideoScoreV1,
    BobaCandidateVideoSignalUsageV1,
    BobaCandidateVideoSourceHandoffV1,
    BobaCandidateVideoSummaryV1,
    BobaCandidateVideoV1,
    BobaScoredCandidateVideoV1,
    BobaShortsPotentialReviewV1,
    import_candidate_videos_from_csv,
    import_candidate_videos_from_json,
    import_candidate_videos_from_manual,
    score_candidate_videos,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_candidate_video_scorer_test"


@lru_cache(maxsize=4)
def _result(
    project_id: str = PROJECT_ID,
) -> BobaCandidateVideoScorerSetV1:
    return build_synthetic_candidate_video_scorer(project_id)


def _candidate(
    result: BobaCandidateVideoScorerSetV1,
    candidate_video_id: str,
) -> BobaScoredCandidateVideoV1:
    return next(
        item
        for item in result.scored_candidates
        if item.candidate_video.candidate_video_id == candidate_video_id
    )


def _single_candidate_result(
    title: str,
    *,
    description: str = "Practical local metadata.",
    rights_status: str = "owned",
    **signals: Any,
) -> BobaScoredCandidateVideoV1:
    candidate_id = "candidate_single_test"
    result = BobaCandidateVideoScorerV1().analyze(
        f"proj_{title.casefold().replace(' ', '_')[:40]}",
        manual_candidates=[
            {
                "candidate_video_id": candidate_id,
                "title": title,
                "description": description,
                "tags": ["creator", "workflow"],
                "rights_status": rights_status,
            }
        ],
        **signals,
    )
    return _candidate(result, candidate_id)


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Candidate Video Scorer V1 Test",
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


def test_01_scorer_set_contract_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_candidate_video_scorer_v1"
    assert BobaCandidateVideoScorerSetV1.model_validate(payload) == _result()


def test_02_import_source_contract_serializes() -> None:
    value = _result().imported_sources[0]
    assert BobaCandidateVideoImportSourceV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_03_candidate_video_contract_serializes() -> None:
    value = _result().candidate_videos[0]
    assert BobaCandidateVideoV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_04_score_contract_serializes() -> None:
    value = _result().scored_candidates[0].score
    assert BobaCandidateVideoScoreV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_05_shorts_potential_review_contract_serializes() -> None:
    value = _result().scored_candidates[0].shorts_potential
    assert BobaShortsPotentialReviewV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_06_rights_review_contract_serializes() -> None:
    value = _result().scored_candidates[0].rights_review
    assert BobaCandidateRightsReviewV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_07_recommendation_contract_serializes() -> None:
    value = _result().scored_candidates[0].recommendation
    assert BobaCandidateVideoRecommendationV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_08_review_queue_contract_serializes() -> None:
    value = _result().review_queue
    assert BobaCandidateVideoReviewQueueV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_09_source_handoff_contract_serializes() -> None:
    value = _result().source_handoffs
    assert BobaCandidateVideoSourceHandoffV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_10_summary_contract_serializes() -> None:
    value = _result().scorer_summary
    assert BobaCandidateVideoSummaryV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_11_signal_usage_contract_serializes() -> None:
    value = _result().signal_usage
    assert BobaCandidateVideoSignalUsageV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_12_csv_import_accepts_flexible_headers(tmp_path: Path) -> None:
    path = tmp_path / "candidates.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "title",
                "description",
                "url",
                "source",
                "creator",
                "duration",
                "published_at",
                "tags",
                "categories",
                "rights_status",
                "permission_notes",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "title": "Creator workflow reveal",
                "description": "A tutorial story with payoff.",
                "url": "https://example.test/metadata-only",
                "source": "local worksheet",
                "creator": "Example Creator",
                "duration": "12:30",
                "published_at": "2026-01-01",
                "tags": "creator,workflow,story",
                "categories": "tutorial|education",
                "rights_status": "licensed",
                "permission_notes": "License must be reviewed.",
                "notes": "Metadata only.",
            }
        )
    imported, candidates, rejected = import_candidate_videos_from_csv(path)
    assert imported.source_type == "csv"
    assert imported.accepted_count == 1
    assert rejected == []
    assert candidates[0].creator_or_channel == "Example Creator"
    assert candidates[0].duration_seconds == 750
    assert candidates[0].rights_status == "licensed"
    assert candidates[0].source_url == "https://example.test/metadata-only"


def test_13_json_import_accepts_list_format(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "Local story",
                    "description": "A problem and payoff.",
                    "rights_status": "owned",
                }
            ]
        ),
        encoding="utf-8",
    )
    imported, candidates, rejected = import_candidate_videos_from_json(path)
    assert imported.accepted_count == 1
    assert candidates[0].title == "Local story"
    assert rejected == []


def test_14_json_import_accepts_object_with_candidates_format(
    tmp_path: Path,
) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "title": "Local tutorial",
                        "description": "A practical lesson.",
                        "rights_status": "licensed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    imported, candidates, rejected = import_candidate_videos_from_json(path)
    assert imported.accepted_count == 1
    assert candidates[0].title == "Local tutorial"
    assert rejected == []


def test_15_manual_candidate_import_works() -> None:
    imported, candidates, rejected = import_candidate_videos_from_manual(
        [
            {
                "title": "Manual candidate",
                "description": "Metadata only.",
                "rights_status": "owned",
            }
        ],
        source_label="manual_test",
    )
    assert imported.source_type == "manual"
    assert imported.source_label == "manual_test"
    assert imported.accepted_count == 1
    assert candidates[0].source_label == "manual_test"
    assert rejected == []


def test_16_empty_candidate_rejected_with_warning() -> None:
    result = BobaCandidateVideoScorerV1().analyze(
        "proj_empty_candidate",
        manual_candidates=[
            {},
            {
                "title": "Valid local metadata",
                "rights_status": "unknown",
            },
        ],
    )
    source = result.imported_sources[0]
    assert source.accepted_count == 1
    assert source.rejected_count == 1
    assert any("rejected" in warning.casefold() for warning in result.warnings)


def test_17_unsupported_rights_status_becomes_unknown_with_warning() -> None:
    imported, candidates, rejected = import_candidate_videos_from_manual(
        [{"title": "Candidate", "rights_status": "probably safe"}]
    )
    assert imported.accepted_count == 1
    assert rejected == []
    assert candidates[0].rights_status == "unknown"
    assert any(
        "unsupported rights status" in warning.casefold()
        for warning in candidates[0].warnings
    )


def test_18_owned_candidate_can_become_review_now() -> None:
    item = _candidate(_result(), "candidate_owned_story")
    assert item.rights_review.rights_status == "owned"
    assert item.recommendation.recommendation == "review_now"


def test_19_licensed_candidate_can_become_review_now() -> None:
    item = _candidate(_result(), "candidate_licensed_tutorial")
    assert item.rights_review.rights_status == "licensed"
    assert item.recommendation.recommendation == "review_now"


def test_20_permission_granted_candidate_can_become_review_now() -> None:
    item = _candidate(
        _result(),
        "candidate_permission_granted_podcast",
    )
    assert item.rights_review.rights_status == "permission_granted"
    assert item.recommendation.recommendation == "review_now"


def test_21_permission_needed_candidate_recommends_seek_permission() -> None:
    item = _candidate(_result(), "candidate_permission_needed")
    assert item.recommendation.recommendation == "seek_permission"
    assert item.rights_review.permission_required is True
    assert item.rights_review.rights_readiness == "needs_permission"


def test_22_unknown_rights_requires_rights_review() -> None:
    item = _candidate(_result(), "candidate_unknown_rights")
    assert item.rights_review.rights_status == "unknown"
    assert item.rights_review.rights_review_required is True
    assert item.rights_review.rights_readiness == "unknown_needs_review"
    assert item.recommendation.recommendation == "seek_permission"


def test_23_blocked_rights_goes_to_blocked_queue() -> None:
    queue = _result().review_queue
    assert any(
        item.candidate_video_id == "candidate_blocked"
        for item in queue.blocked_candidates
    )
    assert (
        _candidate(_result(), "candidate_blocked").recommendation.recommendation
        == "blocked"
    )


def test_24_duplicate_candidate_lowers_priority() -> None:
    original = _candidate(_result(), "candidate_owned_story")
    duplicate = _candidate(_result(), "candidate_owned_story_duplicate")
    assert duplicate.duplicate_of_candidate_video_id == "candidate_owned_story"
    assert duplicate.score.review_priority_score < (
        original.score.review_priority_score
    )
    assert duplicate.recommendation.recommendation == "reject"


def test_25_creator_learning_preference_raises_creator_fit() -> None:
    baseline = _single_candidate_result("Creator workflow story")
    guided = _single_candidate_result(
        "Creator workflow story",
        creator_learning={
            "preferred_clip_types": ["creator workflow story"],
            "preferred_hook_styles": ["workflow"],
        },
    )
    assert guided.score.creator_fit_score > baseline.score.creator_fit_score


def test_26_approval_rejection_pattern_affects_scoring_conservatively() -> None:
    baseline = _single_candidate_result("Creator workflow reveal")
    guided = _single_candidate_result(
        "Creator workflow reveal",
        approval_rejection_learning={
            "pattern_scores": [
                {
                    "summary": "creator workflow reveal",
                    "guidance": "prefer this story",
                    "approval_count": 3,
                    "rejection_count": 0,
                }
            ]
        },
    )
    delta = guided.score.creator_fit_score - baseline.score.creator_fit_score
    assert 0 < delta <= 0.0801


def test_27_performance_feedback_affects_scoring_conservatively() -> None:
    baseline = _single_candidate_result("Tutorial lesson")
    guided = _single_candidate_result(
        "Tutorial lesson",
        performance_feedback={
            "pattern_summary": {
                "strongest_positive_patterns": [
                    {"factor": "tutorial lesson"}
                ]
            }
        },
    )
    delta = guided.score.creator_fit_score - baseline.score.creator_fit_score
    assert 0 < delta <= 0.0801


def test_28_research_support_raises_research_score() -> None:
    baseline = _single_candidate_result("Creator workflow reveal")
    guided = _single_candidate_result(
        "Creator workflow reveal",
        research_brain={
            "research_summary": {
                "strongest_topics": ["creator workflow reveal"]
            },
            "shorts_ideas": [],
            "research_insights": [],
        },
    )
    assert (
        guided.score.research_support_score
        > baseline.score.research_support_score
    )


def test_29_trend_watcher_support_raises_trend_score_within_provided_data() -> None:
    baseline = _single_candidate_result("Creator workflow reveal")
    guided = _single_candidate_result(
        "Creator workflow reveal",
        trend_topic_watcher={
            "watched_topics": [
                {
                    "watched_topic_id": "watched_creator_workflow",
                    "topic": "creator workflow",
                    "reason_for_watch": "Repeated within provided data.",
                    "content_angle_potential": 0.8,
                }
            ],
            "opportunity_scores": [
                {
                    "topic": "creator workflow",
                    "overall_topic_priority_score": 0.85,
                }
            ],
        },
    )
    assert guided.score.trend_support_score > baseline.score.trend_support_score
    assert any(
        "within provided data" in reason.casefold()
        for reason in guided.score.score_reasons
    )


def test_30_content_scout_support_raises_review_priority() -> None:
    baseline = _single_candidate_result("Creator workflow reveal")
    guided = _single_candidate_result(
        "Creator workflow reveal",
        content_scout={
            "scout_items": [
                {
                    "item_id": "scout_creator_workflow",
                    "title": "Creator workflow reveal",
                    "description": "Local scout metadata.",
                    "rights_status": "owned",
                }
            ],
            "scored_items": [
                {
                    "item_id": "scout_creator_workflow",
                    "review_priority_score": 0.9,
                }
            ],
        },
    )
    assert (
        guided.score.review_priority_score
        > baseline.score.review_priority_score
    )


def test_31_hook_potential_terms_raise_hook_score() -> None:
    weak = _single_candidate_result("Ordinary material")
    strong = _single_candidate_result(
        "Why the surprising mistake reveals the secret result?"
    )
    assert strong.score.hook_potential_score > weak.score.hook_potential_score


def test_32_story_potential_terms_raise_story_score() -> None:
    weak = _single_candidate_result("Ordinary material")
    strong = _single_candidate_result(
        "Transformation story",
        description=(
            "A problem creates tension and struggle, then a turn, result, "
            "payoff, and lesson."
        ),
    )
    assert strong.score.story_potential_score > weak.score.story_potential_score


def test_33_weak_generic_candidate_gets_low_priority() -> None:
    item = _candidate(_result(), "candidate_weak_generic")
    assert item.score.review_priority_score < 0.42
    assert item.recommendation.priority == "low"
    assert item.recommendation.recommendation == "reject"


def test_34_shorts_potential_review_does_not_invent_facts() -> None:
    item = _candidate(_result(), "candidate_owned_story")
    potential = item.shorts_potential
    suggestions = [
        *potential.possible_clip_types,
        *potential.possible_hook_directions,
        *potential.possible_story_angles,
        *potential.possible_format_styles,
    ]
    assert suggestions
    assert all(
        "possible" in suggestion.casefold()
        for suggestion in suggestions
    )
    assert (
        "may" in potential.emotional_story_promise.casefold()
        or "does not establish" in potential.emotional_story_promise.casefold()
    )
    assert any(
        "metadata only" in warning.casefold()
        for warning in potential.warnings
    )


def test_35_review_queue_separates_candidate_groups() -> None:
    queue = _result().review_queue
    assert queue.top_candidates
    assert isinstance(queue.backup_candidates, list)
    assert any(
        item.candidate_video_id == "candidate_permission_needed"
        for item in queue.permission_needed_candidates
    )
    assert any(
        item.candidate_video_id == "candidate_blocked"
        for item in queue.blocked_candidates
    )
    assert any(
        item.candidate_video_id == "candidate_owned_story_duplicate"
        for item in queue.duplicate_or_similar_candidates
    )
    assert any(
        item.candidate_video_id == "candidate_weak_generic"
        for item in queue.rejected_candidates
    )


def test_36_source_handoff_apply_automatically_defaults_false() -> None:
    handoffs = _result().source_handoffs
    assert handoffs.apply_automatically is False
    assert all(
        handoff.apply_automatically is False
        for handoff in (
            handoffs.content_scout_handoff,
            handoffs.research_brain_handoff,
            handoffs.trend_topic_handoff,
            handoffs.rights_permission_gate_handoff,
            handoffs.future_ingestion_handoff,
        )
    )


def test_37_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_38_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_39_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_40_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_41_media_ingestion_used_remains_false() -> None:
    assert _result().signal_usage.media_ingestion_used is False


def test_42_export_excludes_private_and_unsafe_content(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_candidate_video_scorer(_result())
    payload = store.export_candidate_video_scorer(PROJECT_ID)
    scorer = payload["candidate_video_scorer"]
    assert isinstance(scorer, dict)
    for source in scorer["imported_sources"]:
        assert "source_path" not in source
    for candidate in scorer["candidate_videos"]:
        assert "source_url" not in candidate
        assert "permission_notes" not in candidate
        assert "user_notes" not in candidate
        assert "raw_metadata_summary" not in candidate
    assert payload["privacy"]["full_transcripts_excluded"] is True
    assert payload["privacy"]["media_files_excluded"] is True
    assert payload["privacy"]["copyright_safety_confirmed"] is False
    encoded = json.dumps(payload).casefold()
    for forbidden in (
        '"raw_media":',
        '"full_transcript":',
        '"api_key":',
        '"access_token":',
        '"password":',
        ".mp4",
        ".wav",
    ):
        assert forbidden not in encoded


def test_43_reset_removes_only_candidate_video_scorer_artifact(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated project memory survives.",
        )
    )
    store.save_candidate_video_scorer(_result())
    assert store.reset_candidate_video_scorer(PROJECT_ID) is True
    assert store.load_candidate_video_scorer(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_44_missing_optional_artifacts_degrade_gracefully() -> None:
    result = BobaCandidateVideoScorerV1().analyze(
        "proj_candidate_fallback",
        manual_candidates=[
            {
                "title": "Local candidate",
                "description": "A practical story lesson.",
                "rights_status": "unknown",
            }
        ],
    )
    assert result.scored_candidates
    assert result.signal_usage.fallback_used is True
    assert {
        "content_scout",
        "research_brain",
        "trend_topic_watcher",
        "creator_learning",
        "approval_rejection_learning",
        "performance_feedback",
        "memory",
    }.issubset(result.signal_usage.unavailable_signals)


def test_45_artifact_persistence_writes_json_safe_output(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_candidate_video_scorer(_result())
    path = store.candidate_video_scorer_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/candidate_video_scorer/index.json"
    )
    assert payload["schema_version"] == "boba_candidate_video_scorer_v1"
    assert store.load_candidate_video_scorer(PROJECT_ID) == saved


def test_46_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_candidate_video_scorer(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/candidate-video-scorer"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == (
        "boba_candidate_video_scorer_v1"
    )
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Candidate Video Scorer V1" in panel
    assert (
        "Candidate Video Scorer V1 uses local/user-provided metadata only."
        in panel
    )


def test_47_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_candidate_video_scorer(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/candidate-video-scorer/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["privacy"]["external_api_used"] is False
    assert payload["privacy"]["media_ingestion_used"] is False
    for source in payload["candidate_video_scorer"]["imported_sources"]:
        assert "source_path" not in source
    for candidate in payload["candidate_video_scorer"]["candidate_videos"]:
        assert "source_url" not in candidate


def test_48_api_delete_resets_project_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_candidate_video_scorer(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated project memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/candidate-video-scorer"
        )
    assert response.status_code == 200, response.text
    assert response.json()["candidate_video_scorer_removed"] is True
    assert response.json()["memory_removed"] is False
    assert response.json()["media_ingested"] is False
    assert store.load_candidate_video_scorer(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_49_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.external_api_used_false is True
    assert report.url_fetching_used_false is True
    assert report.media_ingestion_used_false is True


def test_50_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.candidates_imported >= 8
    assert report.blocked_candidate_queued is True
    assert report.reset_project_only is True


def test_51_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Candidate Video Scorer V1 must not render.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert build_synthetic_candidate_video_scorer(
        "proj_candidate_no_render"
    ).scored_candidates


def test_52_no_downloading_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Candidate Video Scorer V1 must not download media."
        )

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    result = build_synthetic_candidate_video_scorer(
        "proj_candidate_no_download"
    )
    assert result.signal_usage.downloading_used is False


def test_53_no_url_fetching_is_triggered(monkeypatch: Any) -> None:
    def fail_url_fetch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Candidate Video Scorer V1 must not fetch a URL."
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail_url_fetch)
    result = build_synthetic_candidate_video_scorer("proj_candidate_no_url")
    assert result.signal_usage.url_fetching_used is False


def test_54_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Candidate Video Scorer V1 must not use the network."
        )

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = build_synthetic_candidate_video_scorer(
        "proj_candidate_no_network"
    )
    assert result.signal_usage.external_api_used is False


def test_55_no_media_ingestion_is_triggered(monkeypatch: Any) -> None:
    async def fail_storage_put(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Candidate Video Scorer V1 must not ingest media."
        )

    monkeypatch.setattr(LocalStorage, "put", fail_storage_put)
    candidates = import_candidate_videos_from_manual(
        build_synthetic_candidate_metadata()[:2],
        source_type="test_synthetic",
    )[1]
    scored = score_candidate_videos(candidates)
    assert scored
    assert all(
        item.candidate_video.raw_metadata_summary["metadata_only"] is True
        for item in scored
    )


def test_56_no_reports_or_media_are_staged() -> None:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    staged = [
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
    ]
    forbidden = (
        "work/",
        "storage_data/",
        "media/",
        ".venv/",
        "node_modules/",
        "frontend/.next/",
    )
    assert not any(path.startswith(forbidden) for path in staged)
