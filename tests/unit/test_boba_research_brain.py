"""BOBA Research Brain V1 contracts, behavior, integration, and safety tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_content_scout_v2 import build_synthetic_content_scout
from tools.validate_boba_research_brain import (
    build_synthetic_research_brain,
    build_synthetic_research_sources,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaContentScoutResearchHandoffV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaProjectMemoryV1,
    BobaResearchBrainSetV1,
    BobaResearchBrainV1,
    BobaResearchEvidenceSnippetV1,
    BobaResearchImportSourceV1,
    BobaResearchInsightV1,
    BobaResearchSafetyReviewV1,
    BobaResearchShortsIdeaV1,
    BobaResearchSignalUsageV1,
    BobaResearchSourceV1,
    BobaResearchSummaryV1,
    import_research_from_csv,
    import_research_from_json,
    import_research_from_md,
    import_research_from_txt,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_research_brain_test"


@lru_cache(maxsize=4)
def _result(project_id: str = PROJECT_ID) -> BobaResearchBrainSetV1:
    return build_synthetic_research_brain(project_id)


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Research Brain V1 Test",
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


def test_01_research_set_contract_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_research_brain_v1"
    assert BobaResearchBrainSetV1.model_validate(payload) == _result()


def test_02_import_source_contract_serializes() -> None:
    source = _result().imported_sources[0]
    assert BobaResearchImportSourceV1.model_validate(
        source.model_dump(mode="json")
    ) == source


def test_03_research_source_contract_serializes() -> None:
    source = _result().research_sources[0]
    assert BobaResearchSourceV1.model_validate(
        source.model_dump(mode="json")
    ) == source


def test_04_evidence_snippet_contract_serializes() -> None:
    snippet = _result().research_sources[0].evidence_snippets[0]
    assert BobaResearchEvidenceSnippetV1.model_validate(
        snippet.model_dump(mode="json")
    ) == snippet


def test_05_research_insight_contract_serializes() -> None:
    insight = _result().research_insights[0]
    assert BobaResearchInsightV1.model_validate(
        insight.model_dump(mode="json")
    ) == insight


def test_06_shorts_idea_contract_serializes() -> None:
    idea = _result().shorts_ideas[0]
    assert BobaResearchShortsIdeaV1.model_validate(
        idea.model_dump(mode="json")
    ) == idea


def test_07_safety_review_contract_serializes() -> None:
    review = _result().safety_review
    assert BobaResearchSafetyReviewV1.model_validate(
        review.model_dump(mode="json")
    ) == review


def test_08_content_scout_handoff_contract_serializes() -> None:
    handoff = _result().content_scout_handoff
    assert BobaContentScoutResearchHandoffV1.model_validate(
        handoff.model_dump(mode="json")
    ) == handoff


def test_09_summary_contract_serializes() -> None:
    summary = _result().research_summary
    assert BobaResearchSummaryV1.model_validate(
        summary.model_dump(mode="json")
    ) == summary


def test_10_signal_usage_contract_serializes() -> None:
    usage = _result().signal_usage
    assert BobaResearchSignalUsageV1.model_validate(
        usage.model_dump(mode="json")
    ) == usage


def test_11_txt_import_works(tmp_path: Path) -> None:
    path = tmp_path / "research.txt"
    path.write_text(
        "Creators struggle with consistency. They want a practical routine.",
        encoding="utf-8",
    )
    imported, sources, rejected = import_research_from_txt(path)
    assert imported.source_type == "txt"
    assert imported.accepted_count == 1
    assert sources[0].title == "research"
    assert rejected == []


def test_12_md_import_works(tmp_path: Path) -> None:
    path = tmp_path / "research.md"
    path.write_text(
        "# Learning notes\n\nWhy active practice can improve confidence.",
        encoding="utf-8",
    )
    imported, sources, rejected = import_research_from_md(path)
    assert imported.source_type == "md"
    assert imported.accepted_count == 1
    assert sources[0].evidence_snippets
    assert rejected == []


def test_13_csv_import_accepts_flexible_headers(tmp_path: Path) -> None:
    path = tmp_path / "research.csv"
    path.write_text(
        "title,summary,source,author,date,tags,rights_notes,notes\n"
        'A practical lesson,"Users struggle, but want clarity.",Local notes,'
        'Creator,2026-01-01,"education,clarity",Owned,Review facts\n',
        encoding="utf-8",
    )
    imported, sources, rejected = import_research_from_csv(path)
    assert imported.accepted_count == 1
    assert sources[0].author_or_source_name == "Creator"
    assert sources[0].topic_tags[:2] == ["education", "clarity"]
    assert sources[0].rights_usage_notes == "Owned"
    assert rejected == []


def test_14_json_import_accepts_list_format(tmp_path: Path) -> None:
    path = tmp_path / "research.json"
    path.write_text(
        json.dumps([{"title": "List source", "text": "A useful tutorial idea."}]),
        encoding="utf-8",
    )
    imported, sources, rejected = import_research_from_json(path)
    assert imported.accepted_count == 1
    assert [source.title for source in sources] == ["List source"]
    assert rejected == []


def test_15_json_import_accepts_object_with_sources_format(tmp_path: Path) -> None:
    path = tmp_path / "research.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "title": "Wrapped source",
                        "content": "An audience problem and desired result.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    imported, sources, rejected = import_research_from_json(path)
    assert imported.accepted_count == 1
    assert sources[0].title == "Wrapped source"
    assert rejected == []


def test_16_empty_source_rejected_with_warning() -> None:
    result = BobaResearchBrainV1().analyze(
        PROJECT_ID,
        manual_sources=[{}],
    )
    assert result.research_sources == []
    assert result.imported_sources[0].rejected_count == 1
    assert any(
        "non-empty" in warning
        for warning in result.imported_sources[0].warnings
    )
    assert any("rejected" in warning for warning in result.warnings)


def test_17_unsupported_file_type_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "research.pdf"
    path.write_text("Not a supported research format.", encoding="utf-8")
    with pytest.raises(ValidationError, match="only local TXT, MD, CSV, and JSON"):
        BobaResearchBrainV1().analyze(PROJECT_ID, import_paths=[path])


def test_18_evidence_snippets_are_bounded() -> None:
    assert all(
        0 < len(snippet.snippet) <= 300
        for source in _result().research_sources
        for snippet in source.evidence_snippets
    )


def test_19_insight_references_source_id() -> None:
    source_ids = {
        source.research_source_id for source in _result().research_sources
    }
    assert all(insight.source_ids for insight in _result().research_insights)
    assert all(
        set(insight.source_ids).issubset(source_ids)
        for insight in _result().research_insights
    )


def test_20_audience_pain_point_extracted() -> None:
    insights = [
        item
        for item in _result().research_insights
        if item.insight_type == "audience_pain"
    ]
    assert insights
    assert all(item.human_verification_required for item in insights)


def test_21_audience_desire_extracted() -> None:
    insights = [
        item
        for item in _result().research_insights
        if item.insight_type == "audience_desire"
    ]
    assert insights
    assert any("desire" in item.summary for item in insights)


def test_22_hook_angle_extracted() -> None:
    insights = [
        item
        for item in _result().research_insights
        if item.insight_type == "hook_angle"
    ]
    assert insights
    assert all("possible" in item.summary.casefold() for item in insights)


def test_23_format_idea_extracted() -> None:
    insights = [
        item
        for item in _result().research_insights
        if item.insight_type == "format_idea"
    ]
    assert insights
    assert all("may fit" in item.summary for item in insights)
    assert all(item.source_ids for item in insights)


def test_24_weak_factual_claim_requires_verification() -> None:
    insights = [
        item
        for item in _result().research_insights
        if item.insight_type == "verification_needed"
    ]
    assert insights
    assert all(item.human_verification_required for item in insights)
    assert _result().safety_review.unverifiable_claim_warnings


def test_25_copyrighted_source_risk_creates_warning() -> None:
    assert _result().safety_review.copyrighted_content_warnings
    assert any(
        item.insight_type == "caution"
        for item in _result().research_insights
    )


def test_26_shorts_ideas_do_not_invent_facts() -> None:
    encoded = json.dumps(
        [idea.model_dump(mode="json") for idea in _result().shorts_ideas]
    ).casefold()
    assert "possible idea" in encoded
    assert "source-supported" in encoded
    assert not any(
        term in encoded
        for term in (
            "million views",
            "went viral",
            "audience loved",
            "guaranteed performance",
        )
    )


def test_27_creator_learning_can_influence_idea_style_conservatively() -> None:
    source = [
        {
            "title": "Plain research",
            "text": (
                "A clear problem can become a concise source-supported lesson "
                "for people who want clarity."
            ),
            "topic_tags": ["clarity"],
            "rights_usage_notes": "Owned notes.",
        }
    ]
    baseline = BobaResearchBrainV1().analyze(
        "proj_research_baseline",
        manual_sources=source,
    )
    learned = BobaResearchBrainV1().analyze(
        "proj_research_learned",
        manual_sources=source,
        creator_learning={
            "learning_profile": {"preferred_clip_types": ["story"]}
        },
    )
    assert baseline.shorts_ideas
    assert learned.shorts_ideas
    assert learned.shorts_ideas[0].format_style == "story"
    assert learned.shorts_ideas[0].human_review_required is True
    assert learned.shorts_ideas[0].confidence <= 0.82


def test_28_content_scout_handoff_includes_keywords_and_topics() -> None:
    handoff = _result().content_scout_handoff
    assert handoff.recommended_topics
    assert handoff.recommended_keywords
    assert handoff.suggested_review_questions
    assert any("advisory" in note for note in handoff.scout_item_notes)


def test_29_apply_automatically_defaults_false() -> None:
    assert BobaContentScoutResearchHandoffV1().apply_automatically is False
    assert _result().content_scout_handoff.apply_automatically is False


def test_30_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_31_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_32_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_33_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_34_export_excludes_raw_media_secrets_and_full_source_dumps(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_research_brain(_result())
    export = store.export_research_brain(PROJECT_ID)
    research = export["research_brain"]
    assert isinstance(research, dict)
    for source in research["imported_sources"]:
        assert "source_path" not in source
    for source in research["research_sources"]:
        assert "rights_usage_notes" not in source
        assert "user_notes" not in source
        assert all(
            len(snippet["snippet"]) <= 300
            for snippet in source["evidence_snippets"]
        )
    assert export["privacy"]["raw_source_content_excluded"] is True
    assert export["privacy"]["full_transcripts_excluded"] is True
    encoded = json.dumps(export).casefold()
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


def test_35_reset_removes_only_research_brain_artifact(tmp_path: Path) -> None:
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
    store.save_research_brain(_result())
    assert store.reset_research_brain(PROJECT_ID) is True
    assert store.load_research_brain(PROJECT_ID) is None
    assert store.load_content_scout_v2(PROJECT_ID) is not None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_36_missing_optional_artifacts_degrade_gracefully() -> None:
    result = BobaResearchBrainV1().analyze(
        PROJECT_ID,
        manual_sources=[
            {
                "title": "Local note",
                "text": "People struggle and want a practical lesson.",
            }
        ],
    )
    assert result.research_insights
    assert result.signal_usage.fallback_used is True
    assert {
        "content_scout",
        "creator_learning",
        "approval_rejection_learning",
        "performance_feedback",
        "memory",
    }.issubset(result.signal_usage.unavailable_signals)


def test_37_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_research_brain(_result())
    path = store.research_brain_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/research_brain/index.json"
    )
    assert payload["schema_version"] == "boba_research_brain_v1"
    assert store.load_research_brain(PROJECT_ID) == saved


def test_38_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, _store = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        create_response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/research-brain",
            json={
                "manual_sources": build_synthetic_research_sources(),
                "source_label": "api_test",
            },
        )
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/research-brain"
        )
    assert create_response.status_code == 200, create_response.text
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "boba_research_brain_v1"
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Research Brain V1" in panel
    assert "Research Brain V1 uses local/user-provided material only." in panel
    assert (
        "BOBA does not fetch URLs, scrape websites, call external APIs, or" in panel
    )
    assert (
        "Evidence snippets are bounded; human verification may still be" in panel
    )


def test_39_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_research_brain(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/research-brain/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["privacy"]["raw_source_content_excluded"] is True
    assert payload["privacy"]["external_api_used"] is False
    for source in payload["research_brain"]["research_sources"]:
        assert "rights_usage_notes" not in source
        assert "user_notes" not in source


def test_40_api_delete_resets_project_artifact_only(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_research_brain(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/research-brain"
        )
    assert response.status_code == 200, response.text
    assert response.json()["research_brain_removed"] is True
    assert response.json()["content_scout_removed"] is False
    assert response.json()["memory_removed"] is False
    assert store.load_research_brain(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_41_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.external_api_used_false is True
    assert report.url_fetching_used_false is True
    assert report.scraping_used_false is True
    assert report.downloading_used_false is True


def test_42_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.sources_imported >= 6
    assert report.invalid_sources_rejected is True
    assert report.reset_project_only is True


def test_43_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Research Brain V1 must not invoke a renderer.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert build_synthetic_research_brain("proj_research_no_render").shorts_ideas


def test_44_no_downloading_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Research Brain V1 must not download or write media.")

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    result = build_synthetic_research_brain("proj_research_no_download")
    assert result.signal_usage.downloading_used is False


def test_45_no_url_fetching_is_triggered(monkeypatch: Any) -> None:
    def fail_url_fetch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Research Brain V1 must not fetch a URL.")

    monkeypatch.setattr(urllib.request, "urlopen", fail_url_fetch)
    result = build_synthetic_research_brain("proj_research_no_url")
    assert result.signal_usage.url_fetching_used is False


def test_46_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Research Brain V1 must not use the network.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    result = build_synthetic_research_brain("proj_research_no_network")
    assert result.signal_usage.external_api_used is False


def test_47_no_reports_or_media_are_staged() -> None:
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
