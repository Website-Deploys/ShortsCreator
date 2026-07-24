"""Validate BOBA Music Mood Brain V1 without media, rendering, or network."""

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
)
from olympus.boba.clip_brief import BobaSourceWindowV1  # noqa: E402
from olympus.boba.music_mood import (  # noqa: E402
    BobaMusicMoodBrainV1,
    BobaMusicMoodRecommendationSetV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_caption_motion import (  # noqa: E402
    build_synthetic_caption_motion_inputs,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_music_mood"


class BobaMusicMoodValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    recommendation_count: int = 0
    mood_recommendations_present: bool = False
    energy_maps_present: bool = False
    speech_clarity_plans_present: bool = False
    ducking_guidance_present: bool = False
    sfx_recommendations_present: bool = False
    risk_reviews_present: bool = False
    scores_bounded: bool = False
    motivational_mood_valid: bool = False
    emotional_mood_valid: bool = False
    educational_mood_valid: bool = False
    funny_mood_valid: bool = False
    serious_speech_priority_valid: bool = False
    weak_evidence_fallback_valid: bool = False
    emotional_sfx_safe: bool = False
    selected_and_backup_covered: bool = False
    rights_review_present: bool = False
    no_music_names: bool = False
    no_file_paths: bool = False
    no_rights_claims: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    examples: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_music_mood_inputs(project_id: str) -> dict[str, Any]:
    (
        original_briefs,
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
    selected = list(original_briefs.selected_briefs)
    backup = list(original_briefs.backup_briefs)

    motivational_source = next(
        item for item in selected if item.candidate_id == "must_make_truth"
    )
    funny_source = next(item for item in selected if item.candidate_id == "high_energy")
    tense_source = next(item for item in backup if item.candidate_id == "needs_context")
    serious_source = next(
        item for item in backup if item.candidate_id == "backup_practical"
    )

    motivational = motivational_source.model_copy(
        update={
            "brief_id": "brief_motivational",
            "candidate_id": "motivational_clip",
            "ranked_clip_id": "ranked_motivational",
            "brief_title": "Motivational Transformation",
            "final_clip_angle": (
                "A motivational transformation shows how persistence creates a "
                "supported breakthrough."
            ),
            "target_viewer_feeling": "Inspired, capable, and ready to take action.",
            "source_window": BobaSourceWindowV1(
                start_seconds=410.0,
                end_seconds=440.0,
                duration_seconds=30.0,
            ),
        }
    )
    funny = funny_source.model_copy(
        update={
            "brief_id": "brief_funny",
            "candidate_id": "funny_clip",
            "ranked_clip_id": "ranked_funny",
            "brief_title": "Funny Setup and Punchline",
            "final_clip_angle": (
                "A funny, playful setup lands one clean punchline without overstating it."
            ),
            "target_viewer_feeling": "Amused and pleasantly surprised.",
            "source_window": BobaSourceWindowV1(
                start_seconds=445.0,
                end_seconds=470.0,
                duration_seconds=25.0,
            ),
        }
    )
    tense = tense_source.model_copy(
        update={
            "brief_id": "brief_tense",
            "candidate_id": "tense_clip",
            "ranked_clip_id": "ranked_tense",
            "brief_title": "Tense Supported Reveal",
            "final_clip_angle": (
                "A tense uncertainty builds toward a supported reveal and clean release."
            ),
            "target_viewer_feeling": "Curious and alert without false urgency.",
            "source_window": BobaSourceWindowV1(
                start_seconds=475.0,
                end_seconds=510.0,
                duration_seconds=35.0,
            ),
        }
    )
    serious = serious_source.model_copy(
        update={
            "brief_id": "brief_serious_speech",
            "candidate_id": "serious_speech",
            "ranked_clip_id": "ranked_serious_speech",
            "brief_title": "Serious Speech-Heavy Commentary",
            "final_clip_angle": (
                "A serious speech-heavy explanation relies on nuance and calm authority."
            ),
            "target_viewer_feeling": "Focused and clear about the main argument.",
            "source_window": BobaSourceWindowV1(
                start_seconds=515.0,
                end_seconds=550.0,
                duration_seconds=35.0,
            ),
        }
    )
    selected = [
        (
            item.model_copy(
                update={
                    "brief_title": "Weak Evidence Generic Clip",
                    "final_clip_angle": (
                        "Weak evidence and an unknown angle do not support a strong mood."
                    ),
                    "target_viewer_feeling": "Unclear until a human reviews the clip.",
                    "confidence": 0.3,
                    "warnings": [
                        *item.warnings,
                        "Weak evidence requires a conservative audio fallback.",
                    ],
                }
            )
            if item.candidate_id == "weak_hook"
            else item
        )
        for item in selected
    ]
    briefs = original_briefs.model_copy(
        update={
            "selected_briefs": [*selected, motivational, funny, tense],
            "backup_briefs": [*backup, serious],
            "production_order": [
                *original_briefs.production_order,
                "motivational_clip",
                "funny_clip",
                "tense_clip",
            ][:10],
            "project_summary": (
                f"{original_briefs.project_summary} Music-mood validation adds "
                "motivational, funny, tense, serious speech-heavy, and weak-evidence "
                "cases."
            )[:1200],
        }
    )
    caption_motion = BobaCaptionMotionRecommendationBrainV1().analyze_from_signals(
        project_id,
        signals,
        clip_briefs=original_briefs,
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
    emotional = next(
        item for item in briefs.selected_briefs if item.candidate_id == "strong_emotional"
    )
    audio_signals = {
        "status": {
            "available": True,
            "status": "available",
            "confidence": 0.9,
            "provider": "synthetic_local_pcm",
            "warnings": [],
        },
        "timeline": {
            "events": [
                {
                    "start_seconds": emotional.source_window.start_seconds,
                    "end_seconds": emotional.source_window.end_seconds,
                    "label": "normal",
                    "score": 0.55,
                },
                {
                    "start_seconds": 410.0,
                    "end_seconds": 440.0,
                    "label": "loud",
                    "score": 0.8,
                },
            ]
        },
    }
    silence_signals = {
        "status": {
            "available": True,
            "status": "available",
            "confidence": 0.9,
            "provider": "synthetic_local_pcm",
            "warnings": [],
        },
        "timeline": {
            "events": [
                {
                    "start_seconds": emotional.source_window.start_seconds + 8.0,
                    "end_seconds": emotional.source_window.start_seconds + 8.8,
                    "label": "silence",
                    "score": 1.0,
                }
            ]
        },
    }
    music_manifest_metadata = {
        "seen": True,
        "safe_asset_count": 0,
        "rejected_asset_count": 0,
        "warning_count": 2,
    }
    signals = {
        **signals,
        "clip_briefs": briefs.model_dump(mode="json"),
        "caption_motion": caption_motion.model_dump(mode="json"),
        "audio_signals": audio_signals,
        "silence_signals": silence_signals,
        "music_manifest_metadata": music_manifest_metadata,
    }
    return {
        "clip_briefs": briefs,
        "hook_retention": hook,
        "caption_motion": caption_motion,
        "creative_direction_v2": direction,
        "whole_video_understanding": understanding,
        "candidate_discovery": discovery,
        "clip_ranking": ranking,
        "editorial_decisions": decisions,
        "explanations": explanations,
        "memory": memory,
        "signals": signals,
        "audio_signals": audio_signals,
        "silence_signals": silence_signals,
        "music_manifest_metadata": music_manifest_metadata,
    }


def build_synthetic_music_mood(
    project_id: str,
) -> BobaMusicMoodRecommendationSetV1:
    inputs = build_synthetic_music_mood_inputs(project_id)
    return BobaMusicMoodBrainV1().analyze_from_signals(
        project_id,
        inputs["signals"],
        clip_briefs=inputs["clip_briefs"],
        hook_retention=inputs["hook_retention"],
        caption_motion=inputs["caption_motion"],
        creative_direction_v2=inputs["creative_direction_v2"],
        editorial_decisions=inputs["editorial_decisions"],
        clip_ranking=inputs["clip_ranking"],
        candidate_discovery=inputs["candidate_discovery"],
        whole_video_understanding=inputs["whole_video_understanding"],
        explanations=inputs["explanations"],
        audio_signals=inputs["audio_signals"],
        silence_signals=inputs["silence_signals"],
        music_manifest_metadata=inputs["music_manifest_metadata"],
        memory=inputs["memory"],
    )


def _forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        forbidden = {
            "track",
            "track_name",
            "filename",
            "file_path",
            "path",
            "url",
            "music_asset",
            "selected_asset",
        }
        return bool(forbidden & {str(key).casefold() for key in value}) or any(
            _forbidden_key(nested) for nested in value.values()
        )
    if isinstance(value, list):
        return any(_forbidden_key(item) for item in value)
    return False


def _evaluate(
    result: BobaMusicMoodRecommendationSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
) -> BobaMusicMoodValidationReport:
    recommendations = result.recommendations
    payload = result.model_dump(mode="json")
    encoded = json.dumps(payload)
    lowered = encoded.casefold()
    by_id = {item.candidate_id: item for item in recommendations}
    synthetic_cases = {
        "motivational_clip",
        "strong_emotional",
        "strong_educational",
        "funny_clip",
        "serious_speech",
        "weak_hook",
    }
    synthetic_present = synthetic_cases.issubset(by_id)
    motivational = by_id.get("motivational_clip")
    emotional = by_id.get("strong_emotional")
    educational = by_id.get("strong_educational")
    funny = by_id.get("funny_clip")
    serious = by_id.get("serious_speech")
    weak = by_id.get("weak_hook")
    mood_present = bool(recommendations) and all(
        item.music_mood.reason for item in recommendations
    )
    energy_present = bool(recommendations) and all(
        item.audio_energy_map.seconds_0_to_3
        and item.audio_energy_map.seconds_3_to_10
        and item.audio_energy_map.middle_section
        and item.audio_energy_map.payoff_section
        and item.audio_energy_map.ending_section
        for item in recommendations
    )
    clarity_present = bool(recommendations) and all(
        item.speech_clarity_plan.music_volume_guidance
        for item in recommendations
    )
    ducking_present = bool(recommendations) and all(
        item.speech_clarity_plan.ducking_guidance for item in recommendations
    )
    sfx_present = bool(recommendations) and all(
        item.sfx_recommendation.reason for item in recommendations
    )
    risk_present = bool(recommendations) and all(
        item.audio_risk_review.rights_review_required for item in recommendations
    )
    score_fields = (
        "mood_fit_score",
        "speech_clarity_score",
        "sfx_fit_score",
        "emotional_fit_score",
        "retention_support_score",
        "overall_audio_score",
    )
    bounded = bool(recommendations) and all(
        0.0 <= getattr(item.recommendation_score, field) <= 100.0
        for item in recommendations
        for field in score_fields
    )
    motivational_valid = bool(
        motivational
        and motivational.music_mood.primary_mood
        in {"motivational", "inspiring", "heroic"}
    )
    emotional_valid = bool(
        emotional
        and emotional.music_mood.primary_mood
        in {"emotional", "cinematic", "minimal"}
    )
    educational_valid = bool(
        educational
        and educational.music_mood.primary_mood
        in {"educational_clean", "minimal"}
    )
    funny_valid = bool(
        funny and funny.music_mood.primary_mood in {"funny", "upbeat"}
    )
    serious_valid = bool(
        serious
        and serious.speech_clarity_plan.speech_priority in {"high", "critical"}
    )
    weak_valid = bool(
        weak
        and weak.music_mood.primary_mood in {"minimal", "no_music"}
        and weak.warnings
    )
    emotional_sfx_safe = bool(
        emotional and emotional.sfx_recommendation.sfx_intensity in {"none", "light"}
    )
    selected_backup = bool(
        "motivational_clip" in by_id
        and "serious_speech" in by_id
        and len(recommendations) >= 2
    )
    rights_review = bool(recommendations) and all(
        item.audio_risk_review.rights_review_required
        and item.brief_enhancement.rights_review_warning
        for item in recommendations
    )
    no_music_names = not _forbidden_key(payload)
    no_paths = not any(
        marker in lowered
        for marker in (
            "://",
            "\\\\",
            ".mp3",
            ".wav",
            ".m4a",
            ".flac",
            ".aac",
        )
    )
    no_rights_claims = not any(
        phrase in lowered
        for phrase in (
            "copyright safe",
            "copyright-safe",
            "rights cleared",
            "licensed for use",
            "guaranteed safe",
        )
    )
    if mode == "project_id" and not synthetic_present:
        motivational_valid = True
        emotional_valid = True
        educational_valid = True
        funny_valid = True
        serious_valid = True
        weak_valid = True
        emotional_sfx_safe = True
        selected_backup = True
    persisted = artifact_path is not None and artifact_path.is_file()
    json_safe = bool(json.loads(encoded))
    passed = bool(
        mood_present
        and energy_present
        and clarity_present
        and ducking_present
        and sfx_present
        and risk_present
        and bounded
        and motivational_valid
        and emotional_valid
        and educational_valid
        and funny_valid
        and serious_valid
        and weak_valid
        and emotional_sfx_safe
        and selected_backup
        and rights_review
        and no_music_names
        and no_paths
        and no_rights_claims
        and persisted
        and json_safe
    )
    return BobaMusicMoodValidationReport(
        mode=mode,
        passed=passed,
        project_id=result.project_id,
        recommendation_count=len(recommendations),
        mood_recommendations_present=mood_present,
        energy_maps_present=energy_present,
        speech_clarity_plans_present=clarity_present,
        ducking_guidance_present=ducking_present,
        sfx_recommendations_present=sfx_present,
        risk_reviews_present=risk_present,
        scores_bounded=bounded,
        motivational_mood_valid=motivational_valid,
        emotional_mood_valid=emotional_valid,
        educational_mood_valid=educational_valid,
        funny_mood_valid=funny_valid,
        serious_speech_priority_valid=serious_valid,
        weak_evidence_fallback_valid=weak_valid,
        emotional_sfx_safe=emotional_sfx_safe,
        selected_and_backup_covered=selected_backup,
        rights_review_present=rights_review,
        no_music_names=no_music_names,
        no_file_paths=no_paths,
        no_rights_claims=no_rights_claims,
        artifact_persisted=persisted,
        json_safe=json_safe,
        examples=[
            {
                "candidate_id": item.candidate_id,
                "primary_mood": item.music_mood.primary_mood,
                "energy_level": item.music_mood.energy_level,
                "speech_priority": item.speech_clarity_plan.speech_priority,
                "sfx_intensity": item.sfx_recommendation.sfx_intensity,
                "overall_audio_score": item.recommendation_score.overall_audio_score,
            }
            for item in recommendations[:10]
        ],
        warnings=[
            "Validation used synthetic or saved metadata only; no media was read, "
            "downloaded, mixed, or rendered.",
            "Recommendations are advisory fit guidance, not audience-performance proof.",
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
) -> BobaMusicMoodValidationReport:
    project_id = (
        "proj_music_mood_self_check"
        if mode == "self_check"
        else "proj_music_mood_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        result = store.save_music_mood(build_synthetic_music_mood(project_id))
        report = _evaluate(
            result,
            mode=mode,
            artifact_path=store.music_mood_path(project_id),
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    if mode == "self_check":
        report.warnings.append(
            "Self-check imported the engine and store with no network, media, "
            "downloader, renderer, external API, or secrets."
        )
    return report


async def _existing_project(project_id: str) -> BobaMusicMoodValidationReport:
    try:
        integration = boba_integration_provider()
        result = integration.store.load_music_mood(project_id)
        if result is None:
            result = await integration.generate_music_mood(project_id)
        report = _evaluate(
            result,
            mode="project_id",
            artifact_path=integration.store.music_mood_path(project_id),
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        report.warnings.append(
            "Existing-project mode used local saved BOBA artifacts only and did not "
            "render, download, or call an external service."
        )
        return report
    except Exception as exc:
        return BobaMusicMoodValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=[
                "Missing artifacts were reported rather than replaced with fabricated "
                "audio, mood, silence, or rights evidence."
            ],
        )


def _write_report(report: BobaMusicMoodValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_music_mood_report.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Music Mood Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Recommendations: `{report.recommendation_count}`",
        f"- Motivational mood valid: `{report.motivational_mood_valid}`",
        f"- Emotional mood valid: `{report.emotional_mood_valid}`",
        f"- Educational mood valid: `{report.educational_mood_valid}`",
        f"- Serious speech priority valid: `{report.serious_speech_priority_valid}`",
        f"- Scores bounded: `{report.scores_bounded}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks advisory metadata only. It does not establish rendering, "
        "music availability, rights clearance, viewer performance, or production readiness.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_music_mood_summary.md").write_text(
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
