"""BOBA Rights + Permission Gate V1 contracts, behavior, and safety tests."""

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
from tools.validate_boba_rights_permission_gate import (
    build_synthetic_rights_permission_gate,
    run_self_check,
    run_synthetic_project,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import BobaIntegration, BobaMemoryStore, BobaProjectMemoryV1
from olympus.boba.rights_permission_gate import (
    BobaFutureIngestionHandoffV1,
    BobaPermissionChecklistItemV1,
    BobaPermissionChecklistV1,
    BobaRightsEvidenceSnippetV1,
    BobaRightsGateDecisionV1,
    BobaRightsPermissionGateSetV1,
    BobaRightsPermissionGateV1,
    BobaRightsPermissionSignalUsageV1,
    BobaRightsReviewedItemV1,
    BobaRightsRiskReviewV1,
    BobaRightsSummaryV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_rights_permission_gate_test"


@lru_cache(maxsize=4)
def _result(
    project_id: str = PROJECT_ID,
) -> BobaRightsPermissionGateSetV1:
    return build_synthetic_rights_permission_gate(project_id)


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Rights + Permission Gate V1 Test",
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


def _reviewed(
    gate: BobaRightsPermissionGateSetV1,
    item_id: str,
) -> BobaRightsReviewedItemV1:
    return next(
        item
        for item in gate.reviewed_items
        if item.candidate_video_id == item_id or item.review_item_id == item_id
    )


def _decision(
    gate: BobaRightsPermissionGateSetV1,
    item_id: str,
) -> BobaRightsGateDecisionV1:
    return next(
        item
        for item in gate.gate_decisions
        if item.candidate_video_id == item_id or item.review_item_id == item_id
    )


def _checklist(
    gate: BobaRightsPermissionGateSetV1,
    item_id: str,
) -> BobaPermissionChecklistV1:
    reviewed = _reviewed(gate, item_id)
    return next(
        item
        for item in gate.permission_checklists
        if item.review_item_id == reviewed.review_item_id
    )


def _risk(
    gate: BobaRightsPermissionGateSetV1,
    item_id: str,
) -> BobaRightsRiskReviewV1:
    reviewed = _reviewed(gate, item_id)
    return next(
        item
        for item in gate.risk_reviews
        if item.review_item_id == reviewed.review_item_id
    )


def _handoff(
    gate: BobaRightsPermissionGateSetV1,
    item_id: str,
) -> BobaFutureIngestionHandoffV1:
    reviewed = _reviewed(gate, item_id)
    return next(
        item
        for item in gate.future_ingestion_handoffs
        if item.review_item_id == reviewed.review_item_id
    )


def _single_gate(
    item: dict[str, Any],
    **signals: Any,
) -> BobaRightsPermissionGateSetV1:
    return BobaRightsPermissionGateV1().analyze(
        f"proj_single_{item.get('candidate_video_id', 'rights')}",
        manual_items=[item],
        source_label="unit_test",
        **signals,
    )


def test_01_gate_set_contract_serializes() -> None:
    payload = json.loads(_result().model_dump_json())
    assert payload["schema_version"] == "boba_rights_permission_gate_v1"
    assert BobaRightsPermissionGateSetV1.model_validate(payload) == _result()


def test_02_reviewed_item_contract_serializes() -> None:
    value = _reviewed(_result(), "rights_owned")
    assert BobaRightsReviewedItemV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_03_evidence_snippet_contract_serializes() -> None:
    value = _reviewed(_result(), "rights_owned").evidence_snippets[0]
    assert len(value.snippet) <= 300
    assert BobaRightsEvidenceSnippetV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_04_gate_decision_contract_serializes() -> None:
    value = _decision(_result(), "rights_owned")
    assert BobaRightsGateDecisionV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_05_permission_checklist_contract_serializes() -> None:
    value = _checklist(_result(), "rights_owned")
    assert BobaPermissionChecklistV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_06_checklist_item_contract_serializes() -> None:
    value = _checklist(_result(), "rights_owned").checklist_items[0]
    assert BobaPermissionChecklistItemV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_07_risk_review_contract_serializes() -> None:
    value = _risk(_result(), "rights_owned")
    assert BobaRightsRiskReviewV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_08_future_ingestion_handoff_contract_serializes() -> None:
    value = _handoff(_result(), "rights_owned")
    assert BobaFutureIngestionHandoffV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_09_rights_summary_contract_serializes() -> None:
    value = _result().rights_summary
    assert BobaRightsSummaryV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_10_signal_usage_contract_serializes() -> None:
    value = _result().signal_usage
    assert BobaRightsPermissionSignalUsageV1.model_validate(
        value.model_dump(mode="json")
    ) == value


def test_11_owned_item_with_notes_becomes_ready_for_human_review() -> None:
    decision = _decision(_result(), "rights_owned")
    assert decision.gate_status == "ready_for_human_review"
    assert decision.allow_human_review is True
    assert decision.allow_future_ingestion_precheck is True


def test_12_licensed_without_license_note_requires_rights_review() -> None:
    gate = _single_gate(
        {
            "candidate_video_id": "licensed_without_note",
            "title": "Licensed claim without compact note",
            "rights_status": "licensed",
        }
    )
    assert _decision(gate, "licensed_without_note").gate_status == (
        "needs_rights_review"
    )


def test_13_permission_granted_without_note_requires_rights_review() -> None:
    gate = _single_gate(
        {
            "candidate_video_id": "granted_without_note",
            "title": "Permission claim without compact note",
            "rights_status": "permission_granted",
        }
    )
    assert _decision(gate, "granted_without_note").gate_status == (
        "needs_rights_review"
    )


def test_14_permission_needed_becomes_needs_permission() -> None:
    decision = _decision(_result(), "rights_permission_needed")
    assert decision.gate_status == "needs_permission"
    assert decision.requires_permission is True
    assert decision.allow_future_ingestion_precheck is False


def test_15_unknown_becomes_needs_rights_review() -> None:
    decision = _decision(_result(), "rights_unknown")
    assert decision.gate_status == "needs_rights_review"
    assert decision.requires_rights_review is True


def test_16_blocked_becomes_blocked() -> None:
    decision = _decision(_result(), "rights_blocked")
    assert decision.gate_status == "blocked"
    assert decision.blocked is True
    assert decision.allow_human_review is False


def test_17_public_domain_claimed_still_requires_human_review() -> None:
    decision = _decision(_result(), "rights_public_domain_claimed")
    assert decision.gate_status == "needs_rights_review"
    assert decision.requires_rights_review is True
    assert decision.allow_future_ingestion_precheck is False


def test_18_fair_use_claimed_still_requires_human_review() -> None:
    decision = _decision(_result(), "rights_fair_use_claimed")
    assert decision.gate_status == "needs_rights_review"
    assert decision.requires_rights_review is True
    assert decision.allow_future_ingestion_precheck is False


def test_19_unsupported_rights_status_becomes_unknown_with_warning() -> None:
    gate = _single_gate(
        {
            "candidate_video_id": "unsupported_status",
            "title": "Unsupported rights status",
            "rights_status": "copyright_safe",
        }
    )
    item = _reviewed(gate, "unsupported_status")
    assert item.declared_rights_status == "unknown"
    assert any("unsupported" in warning.casefold() for warning in item.warnings)


def test_20_conflicting_notes_lower_confidence() -> None:
    clean = _single_gate(
        {
            "candidate_video_id": "clean_owned",
            "title": "Clean owned source",
            "source_reference": "OWN-CLEAN",
            "rights_status": "owned",
            "ownership_notes": "Creator declares ownership under OWN-CLEAN.",
        }
    )
    conflict = _single_gate(
        {
            "candidate_video_id": "conflict_owned",
            "title": "Conflicting owned source",
            "source_reference": "OWN-CONFLICT",
            "rights_status": "owned",
            "ownership_notes": "Creator declares ownership.",
            "platform_source_notes": "Rights unknown and unverified.",
        }
    )
    clean_decision = _decision(clean, "clean_owned")
    conflict_decision = _decision(conflict, "conflict_owned")
    assert conflict_decision.gate_status == "needs_rights_review"
    assert conflict_decision.confidence < clean_decision.confidence


def test_21_missing_source_evidence_becomes_insufficient_information() -> None:
    decision = _decision(_result(), "rights_missing_source")
    assert decision.gate_status == "insufficient_information"
    assert decision.requires_rights_review is True


def test_22_unknown_rights_are_never_marked_safe() -> None:
    decision = _decision(_result(), "rights_unknown")
    handoff = _handoff(_result(), "rights_unknown")
    assert decision.allow_future_ingestion_precheck is False
    assert handoff.ingestion_precheck_status != (
        "eligible_for_manual_ingestion_review"
    )
    assert handoff.allowed_next_step == "add_rights_evidence"


def test_23_future_ingestion_handoff_never_auto_ingests() -> None:
    gate = _result()
    assert gate.future_ingestion_handoffs
    assert all(
        handoff.apply_automatically is False
        for handoff in gate.future_ingestion_handoffs
    )
    assert all(
        "automatic" in " ".join(handoff.warnings).casefold()
        or handoff.allowed_next_step
        in {
            "human_review_only",
            "seek_permission",
            "add_rights_evidence",
            "do_not_process",
            "blocked",
        }
        for handoff in gate.future_ingestion_handoffs
    )


def test_24_apply_automatically_defaults_false() -> None:
    payload = _handoff(_result(), "rights_owned").model_dump(mode="json")
    payload.pop("apply_automatically")
    handoff = BobaFutureIngestionHandoffV1.model_validate(payload)
    assert handoff.apply_automatically is False


def test_25_checklist_always_requires_final_human_approval() -> None:
    gate = _result()
    assert gate.permission_checklists
    assert all(
        checklist.final_human_approval_required
        for checklist in gate.permission_checklists
    )
    assert all(
        any(
            item.category == "final_approval" and item.required
            for item in checklist.checklist_items
        )
        for checklist in gate.permission_checklists
    )


def test_26_music_audio_risk_appears_with_audio_rights_warning() -> None:
    gate = _single_gate(
        {
            "candidate_video_id": "audio_risk",
            "title": "Owned source with soundtrack",
            "rights_status": "owned",
            "ownership_notes": "Creator declares source ownership.",
        },
        music_mood={
            "rights_review_warning": (
                "Music and source-audio rights require human verification."
            )
        },
    )
    assert _risk(gate, "audio_risk").music_audio_rights_risk is True
    assert _checklist(
        gate, "audio_risk"
    ).music_audio_rights_review_needed is True


def test_27_platform_terms_review_appears_when_platform_present() -> None:
    gate = _single_gate(
        {
            "candidate_video_id": "platform_risk",
            "title": "Platform source reference",
            "source_url": "https://example.test/reference-only",
            "rights_status": "owned",
            "ownership_notes": "Creator declares source ownership.",
        }
    )
    assert _risk(gate, "platform_risk").platform_terms_risk is True
    assert _checklist(
        gate, "platform_risk"
    ).platform_terms_review_needed is True


def test_28_people_privacy_review_appears_when_people_tags_exist() -> None:
    gate = _single_gate(
        {
            "candidate_video_id": "people_risk",
            "title": "Creator interview",
            "rights_status": "owned",
            "ownership_notes": "Creator declares source ownership.",
            "tags": ["people", "guest", "faces"],
        }
    )
    assert _risk(gate, "people_risk").privacy_release_risk is True
    assert _checklist(
        gate, "people_risk"
    ).people_privacy_release_review_needed is True
    assert any(
        snippet.source_field == "tags"
        for snippet in _reviewed(gate, "people_risk").evidence_snippets
    )


def test_29_export_excludes_private_and_unsafe_content(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_rights_permission_gate(_result())
    payload = store.export_rights_permission_gate(PROJECT_ID)
    gate = payload["rights_permission_gate"]
    private_fields = {
        "source_reference",
        "source_url",
        "permission_notes",
        "license_notes",
        "ownership_notes",
        "platform_source_notes",
        "source_artifact_refs",
        "evidence_snippets",
    }
    for item in gate["reviewed_items"]:
        assert not private_fields.intersection(item)
    assert payload["privacy"]["private_paths_excluded"] is True
    assert payload["privacy"]["full_transcripts_excluded"] is True
    assert payload["privacy"]["full_legal_documents_excluded"] is True
    assert payload["privacy"]["credentials_excluded"] is True
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


def test_30_reset_removes_only_rights_permission_gate_artifact(
    tmp_path: Path,
) -> None:
    store = BobaMemoryStore(
        tmp_path / "boba",
        memory_root=tmp_path / "memory",
    )
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated memory survives Rights Gate reset.",
        )
    )
    store.save_rights_permission_gate(_result())
    assert store.reset_rights_permission_gate(PROJECT_ID) is True
    assert store.load_rights_permission_gate(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_31_missing_optional_artifacts_degrade_gracefully() -> None:
    gate = _single_gate(
        {
            "candidate_video_id": "manual_only",
            "title": "Manual-only owned source",
            "rights_status": "owned",
            "ownership_notes": "Creator declares ownership.",
        }
    )
    assert gate.reviewed_items
    assert gate.signal_usage.manual_input_used is True
    assert gate.signal_usage.fallback_used is True
    assert "candidate_video_scorer" in gate.signal_usage.unavailable_signals
    assert _decision(gate, "manual_only").gate_status == (
        "ready_for_human_review"
    )


def test_32_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_rights_permission_gate(_result())
    path = store.rights_permission_gate_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(
        f"projects/{PROJECT_ID}/rights_permission_gate/index.json"
    )
    assert payload["schema_version"] == "boba_rights_permission_gate_v1"
    assert store.load_rights_permission_gate(PROJECT_ID) == saved


def test_33_api_get_returns_saved_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_rights_permission_gate(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/rights-permission-gate"
        )
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == (
        "boba_rights_permission_gate_v1"
    )


def test_34_api_export_returns_safe_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_rights_permission_gate(_result())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/rights-permission-gate/export"
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["privacy"]["external_api_used"] is False
    assert payload["privacy"]["legal_validation_used"] is False
    assert payload["privacy"]["media_ingestion_used"] is False
    for item in payload["rights_permission_gate"]["reviewed_items"]:
        assert "source_url" not in item
        assert "permission_notes" not in item
        assert "evidence_snippets" not in item


def test_35_api_delete_resets_project_artifact(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration, store = _integration(tmp_path)
    store.save_rights_permission_gate(_result())
    store.save_project_memory(
        BobaProjectMemoryV1(
            project_id=PROJECT_ID,
            source_summary="Unrelated project memory survives.",
        )
    )
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/rights-permission-gate"
        )
    assert response.status_code == 200, response.text
    assert response.json()["rights_permission_gate_removed"] is True
    assert response.json()["memory_removed"] is False
    assert response.json()["media_ingested"] is False
    assert response.json()["legal_validation_used"] is False
    assert store.load_rights_permission_gate(PROJECT_ID) is None
    assert store.load_project_memory(PROJECT_ID) is not None


def test_36_validator_self_check_passes(tmp_path: Path) -> None:
    report = run_self_check(tmp_path / "reports")
    assert report.passed is True
    assert report.legal_validation_used_false is True
    assert report.external_api_used_false is True
    assert report.media_ingestion_used_false is True


def test_37_validator_synthetic_project_passes(tmp_path: Path) -> None:
    report = run_synthetic_project(tmp_path / "reports")
    assert report.passed is True
    assert report.reviewed_items_created is True
    assert report.unknown_never_safe is True
    assert report.reset_project_only is True


def test_38_legal_validation_used_remains_false() -> None:
    assert _result().signal_usage.legal_validation_used is False


def test_39_external_api_used_remains_false() -> None:
    assert _result().signal_usage.external_api_used is False


def test_40_url_fetching_used_remains_false() -> None:
    assert _result().signal_usage.url_fetching_used is False


def test_41_scraping_used_remains_false() -> None:
    assert _result().signal_usage.scraping_used is False


def test_42_downloading_used_remains_false() -> None:
    assert _result().signal_usage.downloading_used is False


def test_43_media_ingestion_used_remains_false() -> None:
    assert _result().signal_usage.media_ingestion_used is False


def test_44_no_rendering_is_triggered(monkeypatch: Any) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Rights + Permission Gate V1 must not render.")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    gate = _single_gate(
        {
            "candidate_video_id": "no_render",
            "title": "No render metadata",
            "rights_status": "unknown",
        }
    )
    assert gate.reviewed_items


def test_45_no_downloading_is_triggered(monkeypatch: Any) -> None:
    def fail_binary_write(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Rights + Permission Gate V1 must not download media."
        )

    monkeypatch.setattr(Path, "write_bytes", fail_binary_write)
    gate = _single_gate(
        {
            "candidate_video_id": "no_download",
            "title": "No download metadata",
            "rights_status": "unknown",
        }
    )
    assert gate.signal_usage.downloading_used is False


def test_46_no_url_fetching_is_triggered(monkeypatch: Any) -> None:
    def fail_url_fetch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Rights + Permission Gate V1 must not fetch a URL."
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail_url_fetch)
    gate = _single_gate(
        {
            "candidate_video_id": "no_url_fetch",
            "title": "Reference-only URL",
            "source_url": "https://example.test/reference-only",
            "rights_status": "unknown",
        }
    )
    assert gate.signal_usage.url_fetching_used is False


def test_47_no_external_calls_are_made(monkeypatch: Any) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Rights + Permission Gate V1 must not use the network."
        )

    monkeypatch.setattr(socket, "create_connection", fail_network)
    gate = _single_gate(
        {
            "candidate_video_id": "no_network",
            "title": "Local metadata only",
            "rights_status": "unknown",
        }
    )
    assert gate.signal_usage.external_api_used is False


def test_48_no_media_ingestion_is_triggered(monkeypatch: Any) -> None:
    async def fail_storage_put(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError(
            "Rights + Permission Gate V1 must not ingest media."
        )

    monkeypatch.setattr(LocalStorage, "put", fail_storage_put)
    gate = _single_gate(
        {
            "candidate_video_id": "no_ingestion",
            "title": "Metadata-only review",
            "rights_status": "permission_needed",
        }
    )
    assert gate.signal_usage.media_ingestion_used is False
    assert _decision(gate, "no_ingestion").allow_future_ingestion_precheck is (
        False
    )


def test_49_no_reports_or_media_are_staged() -> None:
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
