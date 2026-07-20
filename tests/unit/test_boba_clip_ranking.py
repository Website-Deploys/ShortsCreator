"""BOBA Clip Ranking Brain V1 contracts, engine, API, and validator tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaBoundarySuggestionV1,
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
    BobaCandidateDiscoverySignalUsageV1,
    BobaCandidateDiversitySummaryV1,
    BobaCandidateEvidenceV1,
    BobaClipRankingEngine,
    BobaClipScoreBreakdownV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaRankedClipV1,
    BobaRankingDiversitySummaryV1,
    BobaRankingSignalUsageV1,
    BobaRejectedRankCandidateV1,
)
from olympus.boba.clip_ranking import BobaClipRankingV1
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]


def _candidate(
    candidate_id: str,
    *,
    start: float = 0.0,
    end: float = 35.0,
    hook: str = "Why does this hidden mistake change everything?",
    story: str = "A clear problem leads to one useful lesson and payoff.",
    candidate_type: str = "curiosity_gap",
    topic: str = "focus",
    emotion: str = "surprise",
    confidence: float = 0.9,
    standalone: float = 0.9,
    setup_required: bool = False,
    payoff_present: bool = True,
    context_needed: bool = False,
    abrupt_start: bool = False,
    abrupt_end: bool = False,
    warnings: list[str] | None = None,
    source_signals: list[str] | None = None,
) -> BobaCandidateClipV1:
    return BobaCandidateClipV1(
        candidate_id=candidate_id,
        project_id="proj_ranking",
        start_seconds=start,
        end_seconds=end,
        duration_seconds=end - start,
        suggested_title=f"Title {candidate_id}",
        hook_idea=hook,
        story_angle=story,
        candidate_type=candidate_type,  # type: ignore[arg-type]
        discovery_reason="Synthetic local test candidate.",
        confidence=confidence,
        standalone_score=standalone,
        setup_required=setup_required,
        payoff_present=payoff_present,
        context_needed=context_needed,
        source_topic=topic,
        emotion_label=emotion,
        virality_cues=["curiosity", "payoff"] if payoff_present else [],
        boundary_suggestion=BobaBoundarySuggestionV1(
            recommended_start_seconds=start,
            recommended_end_seconds=end,
            abrupt_start_warning=abrupt_start,
            abrupt_end_warning=abrupt_end,
            reason="Synthetic boundary.",
        ),
        evidence=BobaCandidateEvidenceV1(
            transcript_snippets=[hook],
            source_signals=source_signals or ["synthetic_local_metadata"],
            topic_segment_ids=[f"topic_{topic}"],
            emotional_beat_ids=[f"emotion_{emotion}"],
            context_payoff_link_ids=["link_payoff"] if payoff_present else [],
            section_score_ids=[f"section_{candidate_id}"],
            virality_reasons=["Synthetic deterministic cue."],
        ),
        warnings=warnings or [],
    )


def _discovery(
    candidates: list[BobaCandidateClipV1] | None = None,
) -> BobaCandidateClipDiscoveryV1:
    values = candidates if candidates is not None else [_candidate("candidate_default")]
    return BobaCandidateClipDiscoveryV1(
        project_id="proj_ranking",
        source_id="uploads/proj_ranking/source.mp4",
        video_duration_seconds=max((item.end_seconds for item in values), default=0.0),
        summary="Synthetic discovery for ranking tests.",
        candidates=values,
        rejected_windows=[],
        diversity_summary=BobaCandidateDiversitySummaryV1(
            candidate_count=len(values),
            topic_count=len({item.source_topic for item in values}),
            emotion_count=len({item.emotion_label for item in values}),
            candidate_types=list(dict.fromkeys(item.candidate_type for item in values)),
            duplicate_windows_removed=0,
            high_overlap_windows_removed=0,
            warnings=[],
        ),
        signal_usage=BobaCandidateDiscoverySignalUsageV1(
            whole_video_understanding_used=False,
            transcript_used=True,
            analysis_signals_used=False,
            story_used=False,
            virality_used=False,
            planning_used=False,
            memory_used=False,
            fallback_used=True,
            unavailable_signals=["whole_video_understanding"],
            warnings=[],
        ),
        warnings=[],
        limitations=["Synthetic metadata only."],
    )


def _rank(
    candidates: list[BobaCandidateClipV1],
    **signals: Any,
) -> BobaClipRankingV1:
    return BobaClipRankingEngine().rank(
        project_id="proj_ranking",
        candidate_discovery=_discovery(candidates),
        **signals,
    )


def _item(result: BobaClipRankingV1, candidate_id: str) -> BobaRankedClipV1:
    return next(item for item in result.ranked_candidates if item.candidate_id == candidate_id)


def _project() -> Project:
    now = utc_now()
    return Project(
        id="proj_ranking",
        name="BOBA Ranking Test",
        source_filename="source.mp4",
        storage_key="uploads/proj_ranking/source.mp4",
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


def test_ranking_contract_serializes() -> None:
    payload = _rank([_candidate("contract")]).model_dump(mode="json")
    assert payload["schema_version"] == "boba_clip_ranking_brain_v1"
    assert json.loads(json.dumps(payload))["project_id"] == "proj_ranking"


def test_ranked_clip_contract_serializes() -> None:
    ranked = _rank([_candidate("ranked")]).ranked_candidates[0]
    assert BobaRankedClipV1.model_validate(ranked.model_dump(mode="json")) == ranked


def test_score_breakdown_contract_serializes() -> None:
    breakdown = _rank([_candidate("breakdown")]).ranked_candidates[0].score_breakdown
    assert BobaClipScoreBreakdownV1.model_validate(
        breakdown.model_dump(mode="json")
    ) == breakdown


def test_diversity_summary_contract_serializes() -> None:
    summary = _rank([_candidate("diversity")]).diversity_summary
    assert BobaRankingDiversitySummaryV1.model_validate(
        summary.model_dump(mode="json")
    ) == summary


def test_signal_usage_contract_serializes() -> None:
    usage = _rank([_candidate("signals")]).signal_usage
    assert BobaRankingSignalUsageV1.model_validate(usage.model_dump(mode="json")) == usage


def test_rejected_rank_candidate_serializes() -> None:
    rejected = BobaRejectedRankCandidateV1(
        candidate_id="duplicate",
        reason="Exact duplicate removed.",
        score=42.0,
        overlap_with_candidate_id="stronger",
        warning="Duplicate promotion prevented.",
    )
    assert json.loads(rejected.model_dump_json())["score"] == 42.0


def test_strong_hook_increases_score() -> None:
    strong = _item(_rank([_candidate("strong")]), "strong")
    weak = _item(
        _rank(
            [
                _candidate(
                    "weak",
                    hook="Additional information",
                    candidate_type="explanation_section",
                )
            ]
        ),
        "weak",
    )
    assert strong.score_breakdown.hook_score > weak.score_breakdown.hook_score


def test_payoff_increases_score() -> None:
    with_payoff = _item(_rank([_candidate("payoff")]), "payoff")
    without_payoff = _item(
        _rank([_candidate("no_payoff", payoff_present=False, abrupt_end=True)]),
        "no_payoff",
    )
    assert with_payoff.score_breakdown.payoff_score > without_payoff.score_breakdown.payoff_score
    assert with_payoff.total_score > without_payoff.total_score


def test_setup_required_context_risk_reduces_score() -> None:
    standalone = _item(_rank([_candidate("standalone")]), "standalone")
    dependent = _item(
        _rank(
            [
                _candidate(
                    "dependent",
                    setup_required=True,
                    context_needed=True,
                    abrupt_start=True,
                )
            ]
        ),
        "dependent",
    )
    assert (
        dependent.score_breakdown.context_risk_score
        > standalone.score_breakdown.context_risk_score
    )
    assert (
        dependent.score_breakdown.standalone_score
        < standalone.score_breakdown.standalone_score
    )


def test_emotional_intensity_increases_score() -> None:
    candidate = _candidate("emotion", emotion="unknown")
    baseline = _item(_rank([candidate]), "emotion")
    boosted = _item(
        _rank(
            [candidate],
            whole_video_understanding={
                "emotional_beats": [
                    {
                        "start_seconds": 0.0,
                        "end_seconds": 35.0,
                        "intensity": 0.96,
                    }
                ]
            },
        ),
        "emotion",
    )
    assert boosted.score_breakdown.emotional_score > baseline.score_breakdown.emotional_score


def test_clarity_warnings_reduce_score() -> None:
    clear = _item(_rank([_candidate("clear")]), "clear")
    warned = _item(
        _rank(
            [
                _candidate(
                    "warned",
                    warnings=["Unclear.", "Missing context.", "Abrupt ending."],
                )
            ]
        ),
        "warned",
    )
    assert clear.score_breakdown.clarity_score > warned.score_breakdown.clarity_score


def test_ideal_duration_improves_pacing_score() -> None:
    ideal = _item(_rank([_candidate("ideal", end=35.0)]), "ideal")
    long = _item(_rank([_candidate("long", end=75.0)]), "long")
    assert ideal.score_breakdown.pacing_score > long.score_breakdown.pacing_score


def test_too_short_and_too_long_reduce_pacing_score() -> None:
    ideal = _item(_rank([_candidate("ideal", end=35.0)]), "ideal")
    short = _item(_rank([_candidate("short", end=8.0)]), "short")
    long = _item(_rank([_candidate("long", end=90.0)]), "long")
    assert ideal.score_breakdown.pacing_score > short.score_breakdown.pacing_score
    assert ideal.score_breakdown.pacing_score > long.score_breakdown.pacing_score


def test_duplicate_candidates_are_rejected() -> None:
    result = _rank(
        [
            _candidate("strong", confidence=0.95),
            _candidate("duplicate", confidence=0.6),
        ]
    )
    assert result.diversity_summary.duplicate_candidates_removed == 1
    assert "duplicate" in result.rejected_clip_ids


def test_high_overlap_candidates_are_penalized() -> None:
    result = _rank(
        [
            _candidate("strong", start=0.0, end=35.0, confidence=0.95),
            _candidate("overlap", start=2.0, end=36.0, confidence=0.72),
        ]
    )
    assert _item(result, "overlap").score_breakdown.overlap_penalty > 0.0


def test_diversity_can_promote_different_topic_and_type() -> None:
    engine = BobaClipRankingEngine()
    template = _item(_rank([_candidate("template")]), "template")
    ranked = [
        template.model_copy(
            update={
                "candidate_id": "first",
                "total_score": 90.0,
                "source_topic": "same",
                "emotion_label": "same",
                "candidate_type": "hook_moment",
            }
        ),
        template.model_copy(
            update={
                "candidate_id": "second",
                "total_score": 89.0,
                "source_topic": "same",
                "emotion_label": "same",
                "candidate_type": "hook_moment",
            }
        ),
        template.model_copy(
            update={
                "candidate_id": "diverse",
                "total_score": 86.0,
                "source_topic": "new",
                "emotion_label": "new",
                "candidate_type": "payoff_moment",
            }
        ),
    ]
    selected, warnings = engine._recommend(ranked)
    assert [item.candidate_id for item in selected[:2]] == ["first", "diverse"]
    assert warnings


def test_unknown_external_rights_prevent_immediate_priority() -> None:
    ranked = _item(
        _rank(
            [_candidate("external", source_signals=["external_scout_candidate"])],
            source_context={"source_type": "scout", "rights_status": "unknown"},
        ),
        "external",
    )
    assert ranked.score_breakdown.rights_safety_penalty >= 50.0
    assert ranked.production_priority != "immediate"


def test_memory_alignment_slightly_affects_score() -> None:
    candidate = _candidate(
        "motivational",
        hook="Why this motivational payoff works",
        story="A motivational lesson reaches a strong payoff.",
        candidate_type="motivational_moment",
        emotion="hope",
    )
    baseline = _item(_rank([candidate]), "motivational")
    aligned = _item(
        _rank(
            [candidate],
            memory={"source_summary": "The user prefers motivational clips and strong payoff."},
        ),
        "motivational",
    )
    assert (
        aligned.score_breakdown.memory_alignment_score
        > baseline.score_breakdown.memory_alignment_score
    )
    assert 0.0 < aligned.total_score - baseline.total_score < 3.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (90.0, "must_make"),
        (75.0, "strong_candidate"),
        (60.0, "backup_candidate"),
        (45.0, "needs_revision"),
        (30.0, "reject"),
    ],
)
def test_tiering_maps_scores(score: float, expected: str) -> None:
    assert (
        BobaClipRankingEngine.tier_for_score(
            score,
            hook_score=95.0,
            payoff_present=True,
            context_risk_score=10.0,
        )
        == expected
    )


def test_recommended_list_returns_three_to_ten_when_available() -> None:
    candidates = [
        _candidate(
            f"candidate_{index}",
            start=index * 40.0,
            end=index * 40.0 + 35.0,
            topic=f"topic_{index}",
            emotion=f"emotion_{index}",
        )
        for index in range(12)
    ]
    result = _rank(candidates)
    assert 3 <= len(result.recommended_clip_ids) <= 10


def test_missing_candidate_discovery_fails_clearly() -> None:
    with pytest.raises(ValidationError, match="requires a saved candidate discovery"):
        BobaClipRankingEngine().rank(
            project_id="proj_ranking",
            candidate_discovery=None,
        )


def test_empty_candidate_discovery_fails_clearly() -> None:
    with pytest.raises(ValidationError, match="cannot rank an empty"):
        BobaClipRankingEngine().rank(
            project_id="proj_ranking",
            candidate_discovery=_discovery([]),
        )


def test_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    ranking = store.save_clip_ranking(_rank([_candidate("persisted")]))
    payload = json.loads(store.clip_ranking_path("proj_ranking").read_text())
    assert store.load_clip_ranking("proj_ranking") == ranking
    assert payload["schema_version"] == "boba_clip_ranking_brain_v1"
    assert "transcript_segments" not in payload


def test_api_routes_rank_and_return_saved_ranking(app: FastAPI, tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_candidate_clip_discovery(
        _discovery(
            [
                _candidate("api_one", start=0.0, end=35.0),
                _candidate(
                    "api_two",
                    start=45.0,
                    end=80.0,
                    topic="systems",
                    candidate_type="payoff_moment",
                ),
                _candidate(
                    "api_three",
                    start=90.0,
                    end=125.0,
                    topic="teamwork",
                    candidate_type="emotional_beat",
                ),
            ]
        )
    )
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        ranked = client.post("/api/v1/boba/projects/proj_ranking/clip-ranking/rank")
        saved = client.get("/api/v1/boba/projects/proj_ranking/clip-ranking")
    assert ranked.status_code == 200
    assert saved.status_code == 200
    assert ranked.json()["ranked_candidates"] == saved.json()["ranked_candidates"]
    signals = asyncio.run(integration.collect_project_signals("proj_ranking"))
    assert signals["ranked_candidate_clips"][0]["candidate_id"] == (
        saved.json()["recommended_clip_ids"][0]
    )


def test_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_clip_ranking.py"),
            "--self-check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"passed": true' in result.stdout.casefold()


def test_validator_synthetic_project_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_clip_ranking.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"ranked_candidate_count": 7' in result.stdout


def test_ranking_does_not_trigger_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert _rank([_candidate("offline")]).ranked_candidates


def test_ranking_makes_no_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    assert _rank([_candidate("local")]).signal_usage.candidate_discovery_used is True


def test_reports_and_artifacts_stay_under_ignored_work() -> None:
    from tools.validate_boba_clip_ranking import REPORT_DIR

    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_clip_ranking"
    assert "media" not in REPORT_DIR.parts
    assert "storage_data" not in REPORT_DIR.parts
