"""BOBA Trend / Topic Watcher V1 contracts, behavior, and safety tests."""

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
from tools.validate_boba_content_scout_v2 import build_synthetic_content_scout
from tools.validate_boba_trend_topic_watcher import (
    build_synthetic_trend_topic_watcher,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaIntegration,
    BobaMemoryStore,
    BobaProjectMemoryV1,
    BobaTopicEntryV1,
    BobaTopicMovementAnalysisV1,
    BobaTopicMovementItemV1,
    BobaTopicOpportunityScoreV1,
    BobaTopicSnapshotV1,
    BobaTrendConfidenceReviewV1,
    BobaTrendContentScoutHandoffV1,
    BobaTrendResearchBrainHandoffV1,
    BobaTrendTopicImportSourceV1,
    BobaTrendTopicSignalUsageV1,
    BobaTrendTopicWatcherSetV1,
    BobaTrendTopicWatcherV1,
    BobaTrendWatcherSummaryV1,
    BobaWatchedTopicV1,
    import_topics_from_csv,
    import_topics_from_json,
    import_topics_from_pasted_text,
    normalize_topic_text,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_trend_topic_watcher_test"


@lru_cache(maxsize=4)
def _result(
    project_id: str = PROJECT_ID,
) -> BobaTrendTopicWatcherSetV1:
    return build_synthetic_trend_topic_watcher(project_id)


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Trend Topic Watcher V1 Test",
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


def _movement_names(field_name: str) -> set[str]:
    items = getattr(_result().movement_analysis, field_name)
    return {item.normalized_topic for item in items}


def _topic_score(
    result: BobaTrendTopicWatcherSetV1,
    topic: str,
) -> BobaTopicOpportunityScoreV1:
    normalized = normalize_topic_text(topic)
    return next(
        score
        for score in result.opportunity_scores
        if score.normalized_topic == normalized
    )


def _single_topic_result(
    topic: str,
    **signals: Any,
) -> BobaTrendTopicWatcherSetV1:
    return BobaTrendTopicWatcherV1().analyze(
        f"proj_{normalize_topic_text(topic).replace(' ', '_')}",
        manual_snapshots=[
            {
                "source_label": "single_local_snapshot",
                "captured_at": "2026-01-01T00:00:00Z",
                "topics": [
                    {
                        "topic": topic,
                        "description": "Practical creator tutorial and hook.",
                    }
                ],
            }
        ],
        **signals,
    )


def test_01_watcher_set_contract_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_trend_topic_watcher_v1"
    assert BobaTrendTopicWatcherSetV1.model_validate(payload) == _result()


def test_02_import_source_contract_serializes() -> None:
    value = _result().imported_sources[0]
    assert BobaTrendTopicImportSourceV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_03_topic_snapshot_contract_serializes() -> None:
    value = _result().topic_snapshots[0]
    assert BobaTopicSnapshotV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_04_topic_entry_contract_serializes() -> None:
    value = _result().topic_snapshots[0].topics[0]
    assert BobaTopicEntryV1.model_validate(value.model_dump(mode="json")) == value


def test_05_watched_topic_contract_serializes() -> None:
    value = _result().watched_topics[0]
    assert BobaWatchedTopicV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_06_movement_analysis_contract_serializes() -> None:
    value = _result().movement_analysis
    assert BobaTopicMovementAnalysisV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_07_movement_item_contract_serializes() -> None:
    value = _result().movement_analysis.repeated_topics[0]
    assert BobaTopicMovementItemV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_08_opportunity_score_contract_serializes() -> None:
    value = _result().opportunity_scores[0]
    assert BobaTopicOpportunityScoreV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_09_confidence_review_contract_serializes() -> None:
    value = _result().confidence_review
    assert BobaTrendConfidenceReviewV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_10_content_scout_handoff_contract_serializes() -> None:
    value = _result().content_scout_handoff
    assert BobaTrendContentScoutHandoffV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_11_research_brain_handoff_contract_serializes() -> None:
    value = _result().research_brain_handoff
    assert BobaTrendResearchBrainHandoffV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_12_summary_contract_serializes() -> None:
    value = _result().watcher_summary
    assert BobaTrendWatcherSummaryV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_13_signal_usage_contract_serializes() -> None:
    value = _result().signal_usage
    assert BobaTrendTopicSignalUsageV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_14_csv_import_accepts_flexible_headers(tmp_path: Path) -> None:
    path = tmp_path / "topics.csv"
    header = ",".join(
        (
            "title",
            "description",
            "tags",
            "category",
            "rank",
            "frequency",
            "score",
            "platform",
            "source",
            "date",
            "notes",
            "rights_safety_note",
        )
    )
    first_row = ",".join(
        (
            "Creator workflow",
            "Practical routine",
            "creator|workflow",
            "education",
            "4",
            "12",
            "0.8",
            "manual sheet",
            "January",
            "2026-01-01",
            "Local note",
            "Verify rights",
        )
    )
    second_row = ",".join(
        (
            "Story hook",
            "Open loop",
            "story;hook",
            "creative",
            "2",
            "18",
            "0.9",
            "manual sheet",
            "February",
            "2026-02-01",
            "Local note",
            "Verify facts",
        )
    )
    path.write_text(
        "\n".join((header, first_row, second_row, "")),
        encoding="utf-8",
    )
    imported, snapshots, rejected = import_topics_from_csv(path)
    assert imported.source_type == "csv"
    assert imported.accepted_count == 2
    assert len(snapshots) == 2
    assert rejected == []


def test_15_json_import_accepts_list_format(tmp_path: Path) -> None:
    path = tmp_path / "topics.json"
    path.write_text(
        json.dumps(
            [
                {
                    "topic": "Creator workflow",
                    "captured_at": "2026-01-01",
                    "frequency": 4,
                }
            ]
        ),
        encoding="utf-8",
    )
    imported, snapshots, rejected = import_topics_from_json(path)
    assert imported.accepted_count == 1
    assert snapshots[0].topics[0].topic == "Creator workflow"
    assert rejected == []


def test_16_json_import_accepts_object_with_topics_format(
    tmp_path: Path,
) -> None:
    path = tmp_path / "topics.json"
    path.write_text(
        json.dumps(
            {
                "topics": [
                    {
                        "keyword": "Story hook",
                        "captured_at": "2026-01-01",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    imported, snapshots, rejected = import_topics_from_json(path)
    assert imported.accepted_count == 1
    assert snapshots[0].topics[0].topic == "Story hook"
    assert rejected == []


def test_17_pasted_text_import_works() -> None:
    imported, snapshots, rejected = import_topics_from_pasted_text(
        [
            {
                "text": "creator workflow, story hook; editing tutorial",
                "captured_at": "2026-01-01",
                "source_label": "pasted_local",
            }
        ]
    )
    assert imported.source_type == "pasted_text"
    assert imported.accepted_count == 3
    assert len(snapshots[0].topics) == 3
    assert rejected == []


def test_18_empty_topic_rejected_with_warning() -> None:
    result = BobaTrendTopicWatcherV1().analyze(
        "proj_empty_topic",
        manual_snapshots=[
            {
                "source_label": "local",
                "captured_at": "2026-01-01",
                "topics": [{"topic": ""}, {"topic": "valid topic"}],
            }
        ],
    )
    assert result.imported_sources[0].rejected_count == 1
    assert any("rejected" in warning.casefold() for warning in result.warnings)


def test_19_topic_normalization_works_conservatively() -> None:
    assert normalize_topic_text("  Creator Workflows!!! ") == "creator workflow"
    assert normalize_topic_text("creator workflow") != normalize_topic_text(
        "creator workplace"
    )


def test_20_repeated_topic_detected_across_snapshots() -> None:
    assert "creator batching method" in _movement_names("repeated_topics")


def test_21_new_topic_detected_in_latest_snapshot() -> None:
    assert "story hook breakdown" in _movement_names(
        "newly_appearing_topics"
    )


def test_22_rising_topic_labeled_within_provided_data() -> None:
    items = _result().movement_analysis.rising_topics_within_provided_data
    item = next(
        value
        for value in items
        if value.normalized_topic == "creator batching method"
    )
    assert item.movement_type == "rising_within_provided_data"
    assert "within provided data" in item.reason
    assert item.delta == 8.0


def test_23_fading_topic_labeled_within_provided_data() -> None:
    items = _result().movement_analysis.fading_topics_within_provided_data
    item = next(
        value for value in items if value.normalized_topic == "legacy zeta format"
    )
    assert item.movement_type == "fading_within_provided_data"
    assert "provided data" in item.reason


def test_24_stable_topic_detected_when_little_movement() -> None:
    assert "steady tutorial format" in _movement_names("stable_topics")


def test_25_insufficient_data_creates_uncertain_topic() -> None:
    assert "misc" in _movement_names("uncertain_topics")


def test_26_duplicate_similar_topic_grouped_conservatively() -> None:
    items = _result().movement_analysis.duplicate_or_similar_topics
    assert any(
        item.normalized_topic == "creator workflow"
        and "Conservatively grouped" in item.reason
        for item in items
    )


def test_27_creator_learning_influences_creator_fit_conservatively() -> None:
    baseline = _single_topic_result("creator batching method")
    guided = _single_topic_result(
        "creator batching method",
        creator_learning={
            "preferred_topics": ["creator batching method"],
        },
    )
    baseline_score = _topic_score(baseline, "creator batching method")
    guided_score = _topic_score(guided, "creator batching method")
    assert guided_score.creator_fit_score > baseline_score.creator_fit_score
    assert guided_score.creator_fit_score <= 1.0


def test_28_research_support_raises_research_score() -> None:
    baseline = _single_topic_result("evidence tutorial")
    guided = _single_topic_result(
        "evidence tutorial",
        research_brain={
            "research_summary": {"strongest_topics": ["evidence tutorial"]}
        },
    )
    assert (
        _topic_score(guided, "evidence tutorial").research_support_score
        > _topic_score(baseline, "evidence tutorial").research_support_score
    )


def test_29_content_scout_support_raises_scout_score() -> None:
    baseline = _single_topic_result("creator lesson")
    guided = _single_topic_result(
        "creator lesson",
        content_scout={
            "scout_summary": {"strongest_topics": ["creator lesson"]}
        },
    )
    assert (
        _topic_score(guided, "creator lesson").scout_support_score
        > _topic_score(baseline, "creator lesson").scout_support_score
    )


def test_30_performance_feedback_influences_score_conservatively() -> None:
    baseline = _single_topic_result("practical tutorial")
    guided = _single_topic_result(
        "practical tutorial",
        performance_feedback={
            "summary": "Practical tutorial received positive manual feedback."
        },
    )
    baseline_fit = _topic_score(baseline, "practical tutorial").creator_fit_score
    guided_fit = _topic_score(guided, "practical tutorial").creator_fit_score
    adjustment = round(guided_fit - baseline_fit, 4)
    assert 0.0 < adjustment <= 0.08


def test_31_opportunity_scores_are_clamped() -> None:
    assert _result().opportunity_scores
    for score in _result().opportunity_scores:
        for value in (
            score.creator_fit_score,
            score.research_support_score,
            score.scout_support_score,
            score.shortability_score,
            score.hook_potential_score,
            score.freshness_within_user_data_score,
            score.risk_score,
            score.overall_topic_priority_score,
            score.confidence,
        ):
            assert 0.0 <= value <= 1.0


def test_32_watchlist_includes_high_priority_topics() -> None:
    assert _result().watched_topics
    highest = _result().opportunity_scores[0].normalized_topic
    assert highest in {
        topic.normalized_topic for topic in _result().watched_topics
    }


def test_33_not_real_time_verified_is_true() -> None:
    assert _result().confidence_review.not_real_time_verified is True


def test_34_weak_data_lowers_confidence() -> None:
    weak = _single_topic_result("misc")
    assert (
        weak.confidence_review.overall_confidence
        < _result().confidence_review.overall_confidence
    )
    assert weak.confidence_review.weak_data_warnings


def test_35_content_scout_handoff_includes_topics_keywords() -> None:
    handoff = _result().content_scout_handoff
    assert handoff.recommended_scout_topics
    assert handoff.recommended_keywords
    assert handoff.rights_review_reminders


def test_36_research_brain_handoff_includes_verification_questions() -> None:
    handoff = _result().research_brain_handoff
    assert handoff.recommended_research_topics
    assert handoff.claims_to_verify
    assert handoff.audience_questions_to_research


def test_37_apply_automatically_defaults_false() -> None:
    assert _result().content_scout_handoff.apply_automatically is False
    assert _result().research_brain_handoff.apply_automatically is False


def test_38_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_39_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_40_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_41_platform_monitoring_used_remains_false() -> None:
    assert _result().signal_usage.platform_monitoring_used is False


def test_42_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_43_export_excludes_private_and_unsafe_content(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_trend_topic_watcher(_result())
    payload = store.export_trend_topic_watcher(PROJECT_ID)
    watcher = payload["trend_topic_watcher"]
    assert isinstance(watcher, dict)
    for source in watcher["imported_sources"]:
        assert "source_path" not in source
    for snapshot in watcher["topic_snapshots"]:
        assert "source_notes" not in snapshot
        for topic in snapshot["topics"]:
            assert "evidence_note" not in topic
            assert "rights_safety_note" not in topic
    assert payload["privacy"]["full_transcripts_excluded"] is True
    assert payload["privacy"]["media_files_excluded"] is True
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


def test_44_reset_removes_only_trend_topic_watcher_artifact(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    store.save_content_scout_v2(build_synthetic_content_scout(PROJECT_ID))
    store.save_trend_topic_watcher(_result())
    assert store.reset_trend_topic_watcher(PROJECT_ID) is True
    assert store.load_trend_topic_watcher(PROJECT_ID) is None
    assert store.load_content_scout_v2(PROJECT_ID) is not None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_45_missing_optional_artifacts_degrade_gracefully() -> None:
    result = _single_topic_result("creator workflow")
    assert result.opportunity_scores
    assert result.signal_usage.fallback_used is True
    assert {
        "research_brain",
        "content_scout",
        "creator_learning",
        "performance_feedback",
        "memory",
    }.issubset(result.signal_usage.unavailable_signals)


def test_46_artifact_persistence_writes_json_safe_output(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_trend_topic_watcher(_result())
    path = store.trend_topic_watcher_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/trend_topic_watcher/index.json"
    )
    assert payload["schema_version"] == "boba_trend_topic_watcher_v1"
    assert store.load_trend_topic_watcher(PROJECT_ID) == saved


def test_47_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_trend_topic_watcher(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/trend-topic-watcher"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_trend_topic_watcher_v1"
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Trend / Topic Watcher V1" in panel
    assert (
        "Trend / Topic Watcher V1 uses local/user-provided topic data only."
        in panel
    )
    assert "Movement is measured only within provided data." in panel


def test_48_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_trend_topic_watcher(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/trend-topic-watcher/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["privacy"]["not_real_time_verified"] is True
    assert payload["privacy"]["external_api_used"] is False
    for source in payload["trend_topic_watcher"]["imported_sources"]:
        assert "source_path" not in source


def test_49_api_delete_resets_project_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_trend_topic_watcher(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/trend-topic-watcher"
        )
    assert response.status_code == 200, response.text
    assert response.json()["trend_topic_watcher_removed"] is True
    assert response.json()["memory_removed"] is False
    assert store.load_trend_topic_watcher(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_50_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.external_api_used_false is True
    assert report.url_fetching_used_false is True
    assert report.platform_monitoring_used_false is True


def test_51_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.snapshots_created >= 2
    assert report.rising_topic_detected is True
    assert report.reset_project_only is True


def test_52_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Trend / Topic Watcher V1 must not render.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert build_synthetic_trend_topic_watcher(
        "proj_watcher_no_render"
    ).watched_topics


def test_53_no_downloading_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Trend / Topic Watcher V1 must not download media.")

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    result = build_synthetic_trend_topic_watcher("proj_watcher_no_download")
    assert result.signal_usage.downloading_used is False


def test_54_no_url_fetching_is_triggered(monkeypatch: Any) -> None:
    def fail_url_fetch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Trend / Topic Watcher V1 must not fetch a URL.")

    monkeypatch.setattr(urllib.request, "urlopen", fail_url_fetch)
    result = build_synthetic_trend_topic_watcher("proj_watcher_no_url")
    assert result.signal_usage.url_fetching_used is False


def test_55_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Trend / Topic Watcher V1 must not use the network.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = build_synthetic_trend_topic_watcher("proj_watcher_no_network")
    assert result.signal_usage.external_api_used is False


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
    assert not any(
        path.casefold().endswith((".mp4", ".mov", ".wav", ".webm"))
        for path in staged
    )
