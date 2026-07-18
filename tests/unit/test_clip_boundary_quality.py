from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from tools import validate_clip_boundary_quality as validator

from olympus.editing.boundary_repair import repair_clip_source_window
from olympus.planning.analyzers import BoundaryRefinementAnalyzer
from olympus.planning.boundary_quality import (
    ClipBoundaryQualityV1,
    recommend_clip_boundaries,
)


def _quality(
    start: float = 0.0,
    end: float = 24.0,
    *,
    context: dict[str, Any] | None = None,
    name: str = "candidate",
) -> ClipBoundaryQualityV1:
    return recommend_clip_boundaries(
        validator._candidate(start, end, name),
        context or validator._context(),
    )


def _context_without_story(**overrides: Any) -> dict[str, Any]:
    context = validator._context(story={})
    context.update(
        {
            "hook_start_seconds": None,
            "payoff_end_seconds": None,
            **overrides,
        }
    )
    return context


def test_boundary_quality_contract_serializes() -> None:
    quality = _quality()

    restored = ClipBoundaryQualityV1.from_dict(quality.to_dict())

    assert restored.to_dict() == quality.to_dict()
    assert quality.to_dict()["contract_version"] == "1"
    assert quality.to_dict()["decision"]["contract_version"] == "1"


def test_good_complete_clip_scores_high() -> None:
    quality = _quality()

    assert quality.quality_score >= 0.75
    assert quality.completeness_score >= 0.8


def test_start_after_hook_is_detected() -> None:
    quality = _quality(2.0, 24.0, name="after_hook")

    assert quality.abrupt_start_risk >= 0.7
    assert "pulled_start_earlier_for_hook" in quality.decision.changes


def test_start_without_context_is_detected() -> None:
    context = validator._context(
        story=validator._story(context_start=0.0, context_risk=0.72)
    )
    context["hook_start_seconds"] = None

    quality = _quality(4.0, 24.0, context=context, name="missing_context")

    assert quality.abrupt_start_risk >= 0.8


def test_recommendation_pulls_start_earlier_for_context() -> None:
    context = validator._context(
        story=validator._story(context_start=0.0, context_risk=0.72)
    )
    context["hook_start_seconds"] = None

    quality = _quality(4.0, 24.0, context=context, name="context_repair")

    assert quality.recommended_start_seconds == pytest.approx(0.0)
    assert "pulled_start_earlier_for_context" in quality.decision.changes


def test_recommendation_pulls_start_earlier_for_missed_hook() -> None:
    quality = _quality(2.0, 24.0, name="hook_repair")

    assert quality.recommended_start_seconds == pytest.approx(0.0)


def test_ending_before_payoff_is_detected() -> None:
    quality = _quality(0.0, 18.0, name="payoff_cut")

    assert quality.abrupt_end_risk >= 0.8


def test_recommendation_extends_end_for_payoff() -> None:
    quality = _quality(0.0, 18.0, name="payoff_extend")

    assert quality.recommended_end_seconds >= 24.0
    assert "extended_end_for_payoff" in quality.decision.changes


def test_dragging_after_payoff_is_detected() -> None:
    context = validator._context(story=validator._story(payoff_end=20.0))
    context["payoff_end_seconds"] = 20.0

    quality = _quality(0.0, 30.0, context=context, name="dragging")

    assert quality.drag_after_payoff_risk > 0.5


def test_recommendation_tightens_end_after_payoff() -> None:
    context = validator._context(story=validator._story(payoff_end=20.0))
    context["payoff_end_seconds"] = 20.0

    quality = _quality(0.0, 30.0, context=context, name="tighten")

    assert quality.recommended_end_seconds < 30.0
    assert "tightened_end_after_payoff" in quality.decision.changes


def test_duplicate_overlap_is_penalized() -> None:
    quality = _quality(
        context=validator._context(previous=[{"start": 0.0, "end": 24.0}]),
        name="duplicate",
    )

    assert quality.duplicate_risk >= 0.45
    assert quality.quality_score < _quality(name="unique").quality_score
    assert any("overlaps" in warning for warning in quality.warnings)


def test_no_word_transcript_fallback_works() -> None:
    quality = _quality(context=validator._context(words=False), name="no_words")

    assert quality.recommended_end_seconds > quality.recommended_start_seconds
    assert any("segment timing fallback" in warning for warning in quality.warnings)


def test_low_confidence_story_signal_creates_warning() -> None:
    quality = _quality(
        context=validator._context(story=validator._story(confidence=0.2)),
        name="low_confidence",
    )

    assert any("low confidence" in warning for warning in quality.warnings)


def test_recommended_window_respects_duration_min_max() -> None:
    quality = _quality(
        10.0,
        12.0,
        context=_context_without_story(
            minimum_duration_seconds=8.0,
            maximum_duration_seconds=12.0,
        ),
        name="duration",
    )

    duration = quality.recommended_end_seconds - quality.recommended_start_seconds
    assert 8.0 <= duration <= 12.0


def test_recommended_window_clamps_to_source_duration() -> None:
    quality = _quality(
        24.0,
        34.0,
        context=_context_without_story(source_duration_seconds=30.0),
        name="source_clamp",
    )

    assert quality.recommended_end_seconds <= 30.0
    assert "clamped_to_source_duration" in quality.decision.changes


@pytest.mark.asyncio
async def test_boundary_quality_metadata_is_attached() -> None:
    class FakeContext:
        project = SimpleNamespace(id="project_metadata")

        def planning_data(self, stage: str) -> dict[str, Any] | None:
            if stage == "candidate_generation":
                return {"candidates": [validator._candidate(0.0, 24.0, "metadata")]}
            return None

        def transcript_segments(self) -> list[dict[str, Any]]:
            return validator._segments()

        def fps(self) -> float:
            return 30.0

        def video_duration(self) -> float:
            return 30.0

        def story_data(self, stage: str) -> dict[str, Any] | None:
            if stage == "hook_detection":
                return {"has_hook": True, "window": {"start": 0.0, "end": 4.0}}
            if stage == "payoff_detection":
                return {"relationships": [{"payoff_timestamp": 20.0}]}
            return None

    outcome = await BoundaryRefinementAnalyzer().analyze(
        cast(Any, FakeContext()),
        lambda _progress: None,
    )

    candidate = outcome.data["candidates"][0]
    assert candidate["boundary_quality"]["contract_version"] == "1"
    assert candidate["boundary_quality_decision"]["decision_id"].startswith("bqd_")


def test_av_repair_consumes_recommended_window() -> None:
    quality = _quality(2.0, 18.0, name="av_handoff")

    source_window = repair_clip_source_window(
        project_id="project_av",
        clip_id="av_handoff",
        requested_start_seconds=quality.recommended_start_seconds,
        requested_end_seconds=quality.recommended_end_seconds,
        transcript_segments=validator._segments(),
        source_duration_seconds=30.0,
        planning_metadata={"boundary_quality": quality.to_dict()},
    )

    assert source_window.requested_start_seconds == quality.recommended_start_seconds
    assert source_window.requested_end_seconds == quality.recommended_end_seconds
    assert source_window.repaired_end_seconds >= source_window.requested_end_seconds


def test_validator_simulate_writes_report(tmp_path: Any) -> None:
    report = validator.run_simulation(output_dir=tmp_path)

    assert report["passed"] is True
    assert report["scenario_count"] == 8
    assert (tmp_path / validator.REPORT_NAME).is_file()
    assert (tmp_path / validator.SUMMARY_NAME).is_file()
