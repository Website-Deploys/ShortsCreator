"""BOBA Memory System V1 contracts, safety, storage, learning, API, and CLI tests."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import (
    boba_integration_provider,
    personalization_service_provider,
)
from olympus.boba import BobaIntegration, BobaMemoryStore
from olympus.boba.creator_memory import build_creator_memory
from olympus.boba.global_memory import build_global_memory
from olympus.boba.memory_application import create_memory_application
from olympus.boba.memory_contracts import (
    BobaCreatorMemoryV1,
    BobaGlobalMemoryV1,
    BobaMemoryApplicationV1,
    BobaMemoryQueryV1,
    BobaMemoryRecordV1,
    BobaMemoryRetrievalResultV1,
    BobaProjectMemoryV1,
)
from olympus.boba.memory_learning import BobaMemoryLearner
from olympus.boba.memory_retrieval import retrieve_memory
from olympus.boba.memory_validation import (
    detect_copyright_risk_text,
    detect_secret_like_text,
    truncate_safe_excerpt,
    validate_memory_record,
)
from olympus.boba.project_memory import build_project_memory
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.personalization import CreatorPersonalizationService, ProfileStore
from olympus.personalization.contracts import (
    ClipFeedbackV2,
    FeedbackLabels,
    FeedbackRating,
    SafeLearning,
)
from olympus.personalization.presets import profile_from_preset
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now


def _record(**updates: Any) -> BobaMemoryRecordV1:
    payload: dict[str, Any] = {
        "memory_id": "memory_one",
        "scope": "project",
        "record_type": "project_summary",
        "source": "test",
        "project_id": "proj_memory",
        "confidence": 0.7,
        "importance": 0.8,
        "tags": ["podcast", "summary"],
        "summary": "A bounded project memory summary.",
        "evidence": ["Selected one complete story clip."],
        "safe_excerpt": "A short safe excerpt.",
        "applies_to": ["planning", "frontend"],
    }
    payload.update(updates)
    return BobaMemoryRecordV1.model_validate(payload)


def _project(project_id: str = "proj_memory") -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="Memory Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=180.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _feedback(
    feedback_id: str = "feedback_one",
    *,
    overall: str = "like",
    labels: FeedbackLabels | None = None,
    notes: str = "Explicit short feedback.",
    music: str | None = None,
) -> ClipFeedbackV2:
    return ClipFeedbackV2(
        feedback_id=feedback_id,
        profile_id="creator_one",
        project_id="proj_memory",
        clip_id="clip_one",
        rating=FeedbackRating(overall=overall, music=music),  # type: ignore[arg-type]
        labels=labels or FeedbackLabels(liked=overall == "like"),
        notes=notes,
        extracted_safe_learning=SafeLearning(
            liked_clip_traits=["emotional_payoff"] if overall == "like" else [],
            disliked_title_patterns=["generic"] if overall == "dislike" else [],
        ),
    )


def _project_memory() -> BobaProjectMemoryV1:
    return BobaProjectMemoryV1(
        project_id="proj_memory",
        source_summary="A bounded source summary.",
        selected_clip_ids=["clip_one"],
        rejected_clip_ids=["clip_two"],
        used_source_ranges=[{"start": 10.0, "end": 30.0}],
        known_limitations=["Manual playback validation remains unavailable."],
    )


def _creator_memory() -> BobaCreatorMemoryV1:
    return BobaCreatorMemoryV1(
        creator_profile_id="creator_one",
        explicit_feedback_only=True,
        style_summary="Prefers complete emotional stories.",
        preferred_clip_traits=["emotional_payoff"],
        avoided_title_styles=["generic"],
        feedback_count=2,
        confidence=0.4,
    )


def _global_memory() -> BobaGlobalMemoryV1:
    return BobaGlobalMemoryV1(
        principles=["Preserve story meaning."],
        hook_patterns=["Use a truthful curiosity gap."],
        safety_principles=["Never copy scripts."],
        source_attribution=["BOBA constitution"],
        confidence=0.7,
    )


@pytest.mark.parametrize(
    "model",
    [
        _record(),
        _project_memory(),
        _creator_memory(),
        _global_memory(),
        BobaMemoryQueryV1(project_id="proj_memory", target_system="planning"),
        BobaMemoryRetrievalResultV1(
            query_id="query_one", records=[_record()], summary="One result.", confidence=0.7
        ),
        BobaMemoryApplicationV1(
            project_id="proj_memory",
            target_system="planning",
            memory_used=["memory_one"],
            explanation="One bounded advisory.",
        ),
    ],
)
def test_memory_contracts_round_trip_json(model: Any) -> None:
    assert type(model).model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize(
    "unsafe",
    [
        "sk-secret1234",
        "ghp_abcdefgh",
        "xoxb-abcdefgh",
        "api_key=secret-value",
        "password=hunter2",
        "cookie: session-value",
        "Bearer token",
    ],
)
def test_secret_like_text_is_rejected(unsafe: str) -> None:
    assert detect_secret_like_text(unsafe) is True
    with pytest.raises(ValidationError):
        validate_memory_record(_record(summary=unsafe))


def test_long_transcript_and_lyric_like_text_are_rejected_but_excerpt_truncates() -> None:
    transcript = " ".join(["spoken transcript sentence"] * 300)
    lyrics = "\n".join([f"lyric line {index}" for index in range(20)]) * 4
    assert detect_copyright_risk_text(transcript) is True
    assert detect_copyright_risk_text(lyrics) is True
    with pytest.raises(ValidationError):
        validate_memory_record(_record(metadata={"transcript": transcript}))
    with pytest.raises(ValidationError):
        validate_memory_record(_record(metadata={"lyrics": lyrics}))
    assert truncate_safe_excerpt("word " * 100, max_chars=80).endswith("...")
    assert len(truncate_safe_excerpt("word " * 100, max_chars=80)) <= 80


def test_store_saves_loads_records_summaries_and_indexes(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    saved = store.save_record(_record())
    assert store.get_record(saved.memory_id) == saved
    assert store.list_records("project", {"project_id": "proj_memory"}) == [saved]
    assert store.save_project_memory(_project_memory()).project_id == "proj_memory"
    assert store.save_creator_memory(_creator_memory()).creator_profile_id == "creator_one"
    assert store.save_global_memory(_global_memory()).global_memory_id == "global_memory_v1"
    indexes = store.rebuild_indexes()
    assert saved.memory_id in indexes["by_scope"]["project"]
    assert saved.memory_id in indexes["by_project"]["proj_memory"]
    assert saved.memory_id in indexes["by_tag"]["podcast"]
    assert store.load_project_memory("proj_memory") is not None
    assert store.load_creator_memory("creator_one") is not None
    assert store.load_global_memory() is not None


def test_store_rejects_secret_record_and_handles_corrupt_json(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    with pytest.raises(ValidationError):
        store.save_record(_record(summary="api_key=do-not-store"))
    path = tmp_path / "boba" / "memory" / "projects" / "proj_memory" / "records.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValidationError, match="corrupt"):
        store.list_records("project")


def test_export_import_and_reset_backup_round_trip(tmp_path: Path) -> None:
    source = BobaMemoryStore(tmp_path / "source")
    source.save_record(_record())
    source.save_project_memory(_project_memory())
    source.save_creator_memory(_creator_memory())
    source.save_global_memory(_global_memory())
    exported = source.export_memory()
    assert exported["schema_version"] == "boba_memory_export_v1"
    assert exported["project_memories"]
    assert exported["creator_memories"]

    target = BobaMemoryStore(tmp_path / "target")
    imported = target.import_memory(exported)
    assert imported == {
        "records": 1,
        "project_memories": 1,
        "creator_memories": 1,
        "global_memories": 1,
    }
    assert target.get_record("memory_one") is not None
    backup = target.reset_project_memory("proj_memory")
    assert backup is not None and backup.exists()
    assert target.load_project_memory("proj_memory") is None


def test_project_memory_builds_from_partial_signals_without_transcript_storage() -> None:
    transcript = "private transcript words " * 500
    signals = {
        "project": {"name": "A useful talk", "content_category": "education"},
        "duration_seconds": 180.0,
        "transcript_available": True,
        "transcript": transcript,
        "content_niche": "education",
        "main_topics": ["focus"],
        "story_threads": ["problem to lesson"],
        "emotional_moments": ["A short turning point"],
        "speakers_or_roles": ["host", "guest"],
        "planning_candidates": [
            {"candidate_id": "candidate_one", "start": 10.0, "end": 40.0}
        ],
        "selected_plans": [
            {
                "clip_id": "clip_one",
                "start": 10.0,
                "end": 40.0,
                "hook_line": "Here is the real reason.",
                "selected_reason": "Complete story and payoff.",
            }
        ],
        "rejected_candidates": [
            {"candidate_id": "candidate_two", "start": 50.0, "end": 60.0, "reason": "Weak payoff."}
        ],
        "unused_opportunities": ["A second bounded story."],
    }
    memory, records = build_project_memory("proj_memory", signals)
    serialized = json.dumps(
        {
            "memory": memory.model_dump(mode="json"),
            "records": [item.model_dump(mode="json") for item in records],
        }
    )
    assert memory.selected_clip_ids == ["clip_one"]
    assert memory.rejected_clip_ids == ["candidate_two"]
    assert memory.used_source_ranges == [{"start": 10.0, "end": 40.0}]
    assert memory.known_limitations
    assert transcript not in serialized
    assert "voice delay" in serialized.lower()


def test_creator_memory_uses_explicit_profile_feedback_and_music_pattern() -> None:
    profile = profile_from_preset(
        "balanced_default",
        profile_id="creator_one",
        profile_name="Creator One",
        learning_enabled=True,
    )
    profile.learned_patterns.liked_hook_categories = ["curiosity"]
    profile.learned_patterns.disliked_title_patterns = ["generic"]
    feedback = [
        _feedback(
            f"feedback_{index}",
            overall="neutral",
            labels=FeedbackLabels(music_bad=True),
            notes="The music is too loud and overpowers speech.",
            music="dislike",
        )
        for index in range(3)
    ]
    memory, records = build_creator_memory(profile, feedback)
    assert memory.explicit_feedback_only is True
    assert "curiosity" in memory.preferred_hook_styles
    assert "generic" in memory.avoided_title_styles
    assert "high_music_intensity" in memory.avoided_music_moods
    assert "speech_first_mix" in memory.preferred_clip_traits
    assert memory.feedback_count == 3
    assert all(
        record.source in {"creator_personalization_v2", "creator_profile_v2"}
        for record in records
    )


def test_global_memory_is_seeded_pattern_level_without_copied_content() -> None:
    memory, records = build_global_memory()
    serialized = json.dumps(memory.model_dump(mode="json"))
    assert memory.hook_patterns and memory.editing_patterns and memory.safety_principles
    assert "no autonomous web crawling" in serialized.lower()
    assert all(record.scope == "global" for record in records)
    assert all(len(record.safe_excerpt) == 0 for record in records)


def test_retrieval_filters_scope_tags_target_confidence_limit_and_rank(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    records = [
        _record(memory_id="project_high", importance=0.95, applies_to=["music"], tags=["podcast"]),
        _record(memory_id="project_low", confidence=0.1, importance=1.0, applies_to=["music"]),
        _record(
            memory_id="creator_high",
            scope="creator",
            record_type="creator_preference",
            project_id=None,
            creator_profile_id="creator_one",
            importance=0.9,
            applies_to=["music"],
            tags=["podcast"],
        ),
        _record(
            memory_id="global_high",
            scope="global",
            record_type="learned_pattern",
            project_id=None,
            importance=0.85,
            applies_to=["music"],
            tags=["podcast"],
        ),
    ]
    for record in records:
        store.save_record(record)
    result = retrieve_memory(
        store,
        BobaMemoryQueryV1(
            project_id="proj_memory",
            creator_profile_id="creator_one",
            target_system="music",
            tags=["podcast"],
            min_confidence=0.2,
            limit=2,
        ),
    )
    assert len(result.records) == 2
    assert result.records[0].memory_id == "project_high"
    assert "project_low" not in {item.memory_id for item in result.records}
    scoped = retrieve_memory(
        store,
        BobaMemoryQueryV1(
            scope_filter=["global"], target_system="music", min_confidence=0.2
        ),
    )
    assert [item.memory_id for item in scoped.records] == ["global_high"]


def test_learning_is_explicit_gradual_and_validation_driven(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    learner = BobaMemoryLearner(store)
    first = learner.learn_from_feedback(_feedback("feedback_one"))
    second = learner.learn_from_feedback(_feedback("feedback_two"))
    assert second.memory_id == first.memory_id
    assert second.confidence > first.confidence
    with pytest.raises(ValidationError, match="passive"):
        learner.learn_from_feedback(
            {**_feedback("feedback_passive").model_dump(mode="json"), "passive": True}
        )
    failures = learner.learn_from_validation_report(
        {"project_id": "proj_memory", "passed": False, "warnings": ["Caption CPS too high."]}
    )
    success = learner.create_learning_note_from_success(
        "proj_memory", "Duration validation passed."
    )
    assert failures[0].record_type == "failed_pattern"
    assert success.record_type == "learned_pattern"
    assert "does not prove" in success.warnings[0]


@pytest.mark.parametrize(
    ("target", "record", "expected_field"),
    [
        (
            "ranking",
            _record(
                memory_id="emotional",
                scope="creator",
                record_type="creator_preference",
                project_id=None,
                creator_profile_id="creator_one",
                summary="Prefer emotional payoff clips.",
                tags=["emotional_payoff", "prefer"],
                applies_to=["ranking"],
            ),
            "emotional_payoff_advisory",
        ),
        (
            "upload_metadata",
            _record(
                summary="Avoid generic titles.",
                tags=["generic"],
                applies_to=["upload_metadata"],
            ),
            "title_warning",
        ),
        (
            "music",
            _record(
                summary="Music too loud; use speech first.",
                tags=["music_too_loud"],
                applies_to=["music"],
            ),
            "music_mix_advisory",
        ),
        (
            "motion",
            _record(
                summary="Face unavailable; use a stable crop.",
                tags=["face_unavailable"],
                applies_to=["motion"],
            ),
            "face_motion_advisory",
        ),
        (
            "ranking",
            _record(
                record_type="clip_selection",
                metadata={"source_range": {"start": 1.0, "end": 4.0}},
                applies_to=["ranking"],
            ),
            "duplicate_source_range_warning",
        ),
    ],
)
def test_memory_application_creates_bounded_advice(
    target: str, record: BobaMemoryRecordV1, expected_field: str
) -> None:
    retrieval = BobaMemoryRetrievalResultV1(
        query_id="query_one", records=[record], summary="One result.", confidence=0.7
    )
    application = create_memory_application(
        "proj_memory", target, retrieval  # type: ignore[arg-type]
    )
    assert application.memory_used == [record.memory_id]
    assert any(item["field"] == expected_field for item in application.adjustments)


@pytest.mark.asyncio
async def test_boba_integration_builds_memory_and_records_application(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project("proj_integration_memory")
    await StorageProjectRepository(storage).save(project)
    store = BobaMemoryStore(tmp_path / "boba")
    integration = BobaIntegration(storage, store)
    state = await integration.generate_boba_for_project(project.id)
    assert store.load_project_memory(project.id) is not None
    assert store.load_global_memory() is not None
    assert state.decisions[-1].memory_application_v1 is not None
    assert state.decisions[-1].memory_application_v1.memory_used


def test_memory_api_routes_build_query_feedback_export_import_and_reset(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project("proj_api_memory")

    async def seed() -> None:
        await StorageProjectRepository(storage).save(project)

    asyncio.run(seed())
    boba = BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))
    personalization = CreatorPersonalizationService(
        ProfileStore(tmp_path / "personalization")
    )
    personalization.initialize()
    app.dependency_overrides[boba_integration_provider] = lambda: boba
    app.dependency_overrides[personalization_service_provider] = lambda: personalization

    with TestClient(app) as client:
        project_response = client.post(
            f"/api/v1/boba/memory/projects/{project.id}/build"
        )
        creator_response = client.post(
            "/api/v1/boba/memory/creators/default/build"
        )
        global_response = client.post("/api/v1/boba/memory/global/build")
        query_response = client.post(
            "/api/v1/boba/memory/query",
            json={
                "project_id": project.id,
                "creator_profile_id": "default",
                "target_system": "planning",
                "reason": "API test",
            },
        )
        feedback_response = client.post(
            "/api/v1/boba/memory/feedback",
            json={
                "profile_id": "default",
                "project_id": project.id,
                "clip_id": "clip_one",
                "rating": "like",
                "labels": ["liked"],
                "notes": "Explicit API memory feedback.",
                "clip_traits": {"clip_traits": ["emotional_payoff"]},
            },
        )
        export_response = client.get("/api/v1/boba/memory/export")
        import_response = client.post(
            "/api/v1/boba/memory/import",
            json={"confirm": True, "payload": export_response.json()},
        )
        rejected_reset = client.post(
            "/api/v1/boba/memory/reset",
            json={"confirm": False, "scope": "project", "identifier": project.id},
        )
        reset_response = client.post(
            "/api/v1/boba/memory/reset",
            json={"confirm": True, "scope": "project", "identifier": project.id},
        )

    assert project_response.status_code == 200
    assert creator_response.status_code == 200
    assert global_response.status_code == 200
    assert query_response.status_code == 200
    assert feedback_response.status_code == 200
    assert feedback_response.json()["creator_memory"]["explicit_feedback_only"] is True
    assert export_response.status_code == 200
    assert import_response.status_code == 200
    assert rejected_reset.status_code == 422
    assert reset_response.status_code == 200
    assert reset_response.json()["backup_created"] is True


@pytest.mark.parametrize(
    "argument",
    [
        "--self-check",
        "--simulate-project",
        "--simulate-creator",
        "--simulate-global",
        "--simulate-feedback",
        "--simulate-query",
        "--simulate-export-import",
    ],
)
def test_boba_memory_cli_modes(argument: str) -> None:
    result = subprocess.run(
        [sys.executable, "tools/validate_boba_memory.py", argument],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["passed"] is True
