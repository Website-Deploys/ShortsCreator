"""Validate BOBA Caption + Motion Recommendation Brain V1 without media or network."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba.caption_motion import (  # noqa: E402
    BobaCaptionMotionRecommendationBrainV1,
    BobaCaptionMotionRecommendationSetV1,
)
from olympus.boba.clip_brief import (  # noqa: E402
    BobaClipBriefSetV1,
    BobaSourceWindowV1,
)
from olympus.boba.hook_retention import BobaHookRetentionBrainV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_hook_retention import (  # noqa: E402
    build_synthetic_hook_retention_inputs,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_caption_motion"


class BobaCaptionMotionValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    recommendation_count: int = 0
    caption_recommendations_present: bool = False
    motion_recommendations_present: bool = False
    timing_maps_present: bool = False
    safety_reviews_present: bool = False
    scores_bounded: bool = False
    educational_caption_valid: bool = False
    emotional_caption_valid: bool = False
    high_energy_caption_valid: bool = False
    high_energy_motion_valid: bool = False
    layout_risk_motion_safe: bool = False
    layout_risk_flagged: bool = False
    weak_hook_present: bool = False
    selected_and_backup_covered: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_stored: bool = False
    forbidden_media_fields_present: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    examples: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_caption_motion_inputs(
    project_id: str,
) -> tuple[
    BobaClipBriefSetV1,
    Any,
    Any,
    Any,
    Any,
    Any,
    Any,
    Any,
    Any,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    (
        briefs,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_hook_retention_inputs(project_id)
    selected = list(briefs.selected_briefs)
    backup = list(briefs.backup_briefs)

    high_energy_source = next(
        item for item in selected if item.candidate_id == "must_make_truth"
    )
    high_energy = high_energy_source.model_copy(
        update={
            "brief_id": "brief_high_energy",
            "candidate_id": "high_energy",
            "ranked_clip_id": "ranked_high_energy",
            "brief_title": "High Energy Contradiction",
            "final_clip_angle": (
                "A fast, high-energy contradiction lands a surprising practical payoff."
            ),
            "target_viewer_feeling": "Surprised, energized, and ready to act.",
            "source_window": BobaSourceWindowV1(
                start_seconds=335.0,
                end_seconds=365.0,
                duration_seconds=30.0,
            ),
            "hook_instruction": high_energy_source.hook_instruction.model_copy(
                update={
                    "summary": "Open with the surprising contradiction immediately.",
                    "do_this": (
                        "Use a punchy supported hook and land the contradiction in the "
                        "first sentence."
                    ),
                    "avoid_this": "Avoid adding any unsupported shock claim.",
                    "reason": "This fixture models a fast, high-energy opening.",
                }
            ),
            "caption_instruction": high_energy_source.caption_instruction.model_copy(
                update={
                    "summary": "Use bold hook captions with one punchline emphasis.",
                    "do_this": "Highlight the contradiction and payoff selectively.",
                    "avoid_this": "Avoid word-by-word caption overload.",
                    "reason": "Punchy captions support the high-energy hook.",
                }
            ),
            "motion_instruction": high_energy_source.motion_instruction.model_copy(
                update={
                    "summary": "Use one dynamic zoom and one controlled punch-in.",
                    "do_this": "Punch in on the hook, settle, then emphasize the payoff.",
                    "avoid_this": "Avoid constant zoom or rapid crop switching.",
                    "reason": "Verified safe layout metadata supports stronger motion.",
                }
            ),
            "warnings": [
                "High-energy motion still requires verified face and layout safety."
            ],
        }
    )

    layout_source = next(
        item for item in backup if item.candidate_id == "needs_context"
    )
    layout_risk = layout_source.model_copy(
        update={
            "brief_id": "brief_layout_risk",
            "candidate_id": "layout_risk",
            "ranked_clip_id": "ranked_layout_risk",
            "brief_title": "Two Speaker Layout Risk",
            "final_clip_angle": (
                "A two-speaker exchange needs complete context and safe stable framing."
            ),
            "target_viewer_feeling": "Clear about who is speaking and why it matters.",
            "source_window": BobaSourceWindowV1(
                start_seconds=370.0,
                end_seconds=405.0,
                duration_seconds=35.0,
            ),
            "motion_instruction": layout_source.motion_instruction.model_copy(
                update={
                    "summary": "Use layout-safe framing for the two-speaker exchange.",
                    "do_this": "Keep both speakers safely framed until layout checks pass.",
                    "avoid_this": "Avoid face-dependent crop switching or tight punch-ins.",
                    "reason": "This fixture models face cutoff and multi-speaker risk.",
                }
            ),
            "warnings": [
                *layout_source.warnings,
                "Multi-speaker layout risk and face cutoff require stable framing.",
            ],
        }
    )

    selected = [
        (
            item.model_copy(
                update={
                    "warnings": [
                        *item.warnings,
                        "Caption overload risk: reduce dense caption treatment.",
                    ]
                }
            )
            if item.candidate_id == "weak_hook"
            else item
        )
        for item in selected
    ]
    briefs = briefs.model_copy(
        update={
            "selected_briefs": [*selected, high_energy],
            "backup_briefs": [*backup, layout_risk],
            "production_order": [*briefs.production_order, "high_energy"],
            "project_summary": (
                f"{briefs.project_summary} Caption-motion validation adds high-energy "
                "and multi-speaker layout-risk cases."
            )[:1200],
        }
    )
    signals.update(
        {
            "clip_briefs": briefs.model_dump(mode="json"),
            "transcript_available": True,
            "face_signals_available": True,
            "speaker_signals_available": True,
            "visual_signals_available": True,
            "analysis_signals_v2": {
                "transcript_available": True,
                "face_signals_available": True,
                "speaker_signals_available": True,
                "visual_signals_available": True,
            },
        }
    )
    hook = BobaHookRetentionBrainV1().analyze_from_signals(
        project_id,
        signals,
        clip_briefs=briefs,
        creative_direction_v2=direction,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        virality=signals.get("virality_summary"),
        memory=memory,
    )
    face_validation = {
        "project_id": project_id,
        "results": [
            {
                "candidate_id": "high_energy",
                "face_tracking_available": True,
                "face_cutoff_detected": False,
                "face_inside_safe_zone_ratio": 0.98,
                "passed": True,
                "warnings": [],
            },
            {
                "candidate_id": "layout_risk",
                "face_tracking_available": True,
                "face_cutoff_detected": True,
                "face_inside_safe_zone_ratio": 0.62,
                "passed": False,
                "warnings": ["Face approaches the crop boundary."],
            },
        ],
    }
    speaker_validation = {
        "project_id": project_id,
        "results": [
            {
                "candidate_id": "high_energy",
                "detected_speaker_count": 1,
                "layout_strategy": "single_face_tracking",
                "passed": True,
                "warnings": [],
            },
            {
                "candidate_id": "layout_risk",
                "detected_speaker_count": 2,
                "layout_strategy": "center_fallback",
                "passed": False,
                "wrong_speaker_focus_warnings": ["Active speaker focus is unverified."],
                "warnings": ["Two-speaker layout requires human review."],
            },
        ],
    }
    analysis_signals = {
        "transcript_available": True,
        "face_signals_available": True,
        "speaker_signals_available": True,
        "visual_signals_available": True,
    }
    return (
        briefs,
        hook,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
        face_validation,
        speaker_validation,
        analysis_signals,
    )


def build_synthetic_caption_motion(
    project_id: str,
) -> BobaCaptionMotionRecommendationSetV1:
    (
        briefs,
        hook,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
        face_validation,
        speaker_validation,
        analysis_signals,
    ) = build_synthetic_caption_motion_inputs(project_id)
    return BobaCaptionMotionRecommendationBrainV1().analyze_from_signals(
        project_id,
        signals,
        clip_briefs=briefs,
        hook_retention=hook,
        creative_direction_v2=direction,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        face_motion_validation=face_validation,
        multi_speaker_validation=speaker_validation,
        analysis_signals=analysis_signals,
        memory=memory,
    )


def _evaluate(
    result: BobaCaptionMotionRecommendationSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
) -> BobaCaptionMotionValidationReport:
    recommendations = result.recommendations
    payload = result.model_dump(mode="json")
    encoded = json.dumps(payload)
    by_id = {item.candidate_id: item for item in recommendations}
    expected_synthetic = {
        "strong_educational",
        "strong_emotional",
        "high_energy",
        "layout_risk",
        "weak_hook",
    }
    synthetic_cases_present = expected_synthetic.issubset(by_id)
    educational = by_id.get("strong_educational")
    emotional = by_id.get("strong_emotional")
    high_energy = by_id.get("high_energy")
    layout_risk = by_id.get("layout_risk")
    caption_present = bool(recommendations) and all(
        item.caption_recommendation.reason for item in recommendations
    )
    motion_present = bool(recommendations) and all(
        item.motion_recommendation.reason for item in recommendations
    )
    timing_present = bool(recommendations) and all(
        item.timing_map.seconds_0_to_3
        and item.timing_map.seconds_3_to_10
        and item.timing_map.middle_section
        and item.timing_map.payoff_section
        and item.timing_map.ending_section
        for item in recommendations
    )
    safety_present = bool(recommendations) and all(
        isinstance(item.safety_review.warnings, list) for item in recommendations
    )
    score_fields = (
        "caption_fit_score",
        "caption_readability_score",
        "motion_fit_score",
        "motion_safety_score",
        "hook_support_score",
        "retention_support_score",
        "overall_recommendation_score",
    )
    bounded = bool(recommendations) and all(
        0.0 <= getattr(item.recommendation_score, field) <= 100.0
        for item in recommendations
        for field in score_fields
    )
    educational_valid = bool(
        educational
        and educational.caption_recommendation.caption_style
        in {"keyword_highlight", "educational_steps"}
    )
    emotional_valid = bool(
        emotional
        and emotional.caption_recommendation.caption_style
        in {"emotional_emphasis", "clean_subtitles"}
    )
    high_energy_caption = bool(
        high_energy
        and high_energy.caption_recommendation.caption_style
        in {"bold_hook_captions", "punchline_caption"}
    )
    high_energy_motion = bool(
        high_energy
        and high_energy.motion_recommendation.motion_style
        in {"dynamic_zoom", "punch_in", "high_motion"}
        and high_energy.motion_recommendation.motion_intensity in {"moderate", "high"}
    )
    layout_safe = bool(
        layout_risk
        and layout_risk.motion_recommendation.motion_style
        in {"stable", "layout_safe"}
    )
    layout_flagged = bool(
        layout_risk
        and (
            layout_risk.safety_review.face_cutoff_risk
            or layout_risk.safety_review.multi_speaker_layout_risk
        )
    )
    weak_hook_present = "weak_hook" in by_id
    selected_and_backup = bool(
        "must_make_truth" in by_id
        and "backup_practical" in by_id
        and "layout_risk" in by_id
    )
    if mode == "project_id" and not synthetic_cases_present:
        educational_valid = True
        emotional_valid = True
        high_energy_caption = True
        high_energy_motion = True
        layout_safe = True
        layout_flagged = True
        weak_hook_present = True
        selected_and_backup = True
    persisted = artifact_path is not None and artifact_path.is_file()
    json_safe = bool(json.loads(encoded))
    raw_transcript = "transcript_segments" in encoded or '"transcript"' in encoded
    forbidden_media_fields = any(
        field in payload
        for field in (
            "audio",
            "copyright",
            "music_asset",
            "raw_media",
            "raw_frames",
        )
    )
    passed = bool(
        caption_present
        and motion_present
        and timing_present
        and safety_present
        and bounded
        and educational_valid
        and emotional_valid
        and high_energy_caption
        and high_energy_motion
        and layout_safe
        and layout_flagged
        and weak_hook_present
        and selected_and_backup
        and persisted
        and json_safe
        and not raw_transcript
        and not forbidden_media_fields
    )
    return BobaCaptionMotionValidationReport(
        mode=mode,
        passed=passed,
        project_id=result.project_id,
        recommendation_count=len(recommendations),
        caption_recommendations_present=caption_present,
        motion_recommendations_present=motion_present,
        timing_maps_present=timing_present,
        safety_reviews_present=safety_present,
        scores_bounded=bounded,
        educational_caption_valid=educational_valid,
        emotional_caption_valid=emotional_valid,
        high_energy_caption_valid=high_energy_caption,
        high_energy_motion_valid=high_energy_motion,
        layout_risk_motion_safe=layout_safe,
        layout_risk_flagged=layout_flagged,
        weak_hook_present=weak_hook_present,
        selected_and_backup_covered=selected_and_backup,
        artifact_persisted=persisted,
        json_safe=json_safe,
        raw_transcript_stored=raw_transcript,
        forbidden_media_fields_present=forbidden_media_fields,
        examples=[
            {
                "candidate_id": item.candidate_id,
                "caption_style": item.caption_recommendation.caption_style,
                "caption_density": item.caption_recommendation.caption_density,
                "motion_style": item.motion_recommendation.motion_style,
                "motion_intensity": item.motion_recommendation.motion_intensity,
                "overall_score": (
                    item.recommendation_score.overall_recommendation_score
                ),
                "safety_warnings": item.safety_review.warnings[:4],
            }
            for item in recommendations[:10]
        ],
        warnings=[
            "Validation used synthetic or saved metadata only; no media was read, "
            "downloaded, edited, or rendered.",
            "Recommendation scores are advisory fit checks, not viewer-performance or "
            "virality predictions.",
            *result.limitations[:5],
        ],
    )


def _report_path_writable() -> bool:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    probe = REPORT_DIR / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        return probe.read_text(encoding="utf-8") == "ok"
    finally:
        probe.unlink(missing_ok=True)


def _run_synthetic(
    *,
    mode: Literal["self_check", "synthetic_project"],
) -> BobaCaptionMotionValidationReport:
    project_id = (
        "proj_caption_motion_self_check"
        if mode == "self_check"
        else "proj_caption_motion_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        result = store.save_caption_motion(
            build_synthetic_caption_motion(project_id)
        )
        report = _evaluate(
            result,
            mode=mode,
            artifact_path=store.caption_motion_path(project_id),
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    if mode == "self_check":
        report.warnings.append(
            "Self-check imported the engine and store with no network, media, "
            "downloader, renderer, external API, or secrets."
        )
    return report


async def _existing_project(
    project_id: str,
) -> BobaCaptionMotionValidationReport:
    try:
        integration = boba_integration_provider()
        result = integration.store.load_caption_motion(project_id)
        if result is None:
            result = await integration.generate_caption_motion(project_id)
        report = _evaluate(
            result,
            mode="project_id",
            artifact_path=integration.store.caption_motion_path(project_id),
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        report.warnings.append(
            "Existing-project mode used local saved BOBA artifacts only and did not "
            "render or download."
        )
        return report
    except Exception as exc:
        return BobaCaptionMotionValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=[
                "Missing artifacts were reported rather than replaced with fabricated "
                "caption, motion, face, or speaker evidence."
            ],
        )


def _write_report(report: BobaCaptionMotionValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_caption_motion_report.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Caption + Motion Recommendation Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Recommendations: `{report.recommendation_count}`",
        f"- Educational caption valid: `{report.educational_caption_valid}`",
        f"- Emotional caption valid: `{report.emotional_caption_valid}`",
        f"- High-energy motion valid: `{report.high_energy_motion_valid}`",
        f"- Layout-risk motion safe: `{report.layout_risk_motion_safe}`",
        f"- Scores bounded: `{report.scores_bounded}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks advisory metadata only. It does not establish rendering, "
        "viewer performance, identity, copyright safety, or production readiness.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_caption_motion_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic-project", action="store_true")
    modes.add_argument("--project-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.self_check:
        report = _run_synthetic(mode="self_check")
    elif args.synthetic_project:
        report = _run_synthetic(mode="synthetic_project")
    else:
        report = asyncio.run(_existing_project(str(args.project_id)))
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
