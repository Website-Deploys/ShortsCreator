"""Validate BOBA Whole Video Understanding V1 without media or external services."""

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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba import (  # noqa: E402
    BobaMemoryStore,
    BobaWholeVideoUnderstandingEngine,
    build_whole_video_memory_summary,
)
from olympus.boba.whole_video import whole_video_memory_record  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_whole_video_understanding"


class BobaWholeVideoValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    summary_exists: bool = False
    topic_timeline_exists: bool = False
    story_arc_exists: bool = False
    emotional_beats_exist: bool = False
    context_payoff_map_exists: bool = False
    context_payoff_warning_exists: bool = False
    section_scores_exist: bool = False
    shortability_hints_exist: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_stored: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _segments() -> list[dict[str, Any]]:
    return [
        {
            "start": 0.0,
            "end": 5.0,
            "text": "Why does focus fail even when the goal matters?",
        },
        {
            "start": 5.0,
            "end": 12.0,
            "text": "The reason is that vague tasks create friction and confusion.",
        },
        {
            "start": 12.0,
            "end": 20.0,
            "text": "Now let's move to one specific action and remove every competing task.",
        },
        {
            "start": 20.0,
            "end": 28.0,
            "text": "Wow, the unexpected result is calmer work and faster progress!",
        },
        {
            "start": 28.0,
            "end": 36.0,
            "text": "Finally, that's why a visible next action restores focus.",
        },
    ]


def _story() -> dict[str, Any]:
    return {
        "schema": "story_analysis_v2",
        "primary_themes": ["focus", "specific action"],
        "topic_sections": [
            {
                "section_id": "topic_problem",
                "start": 0.0,
                "end": 12.0,
                "title": "Focus Friction",
                "summary": "Vague tasks are introduced as the source of focus friction.",
                "story_potential": 0.7,
                "evidence": ["Why does focus fail?"],
            },
            {
                "section_id": "topic_solution",
                "start": 12.0,
                "end": 36.0,
                "title": "Specific Next Action",
                "summary": "A specific action creates a clear practical payoff.",
                "story_potential": 0.86,
                "evidence": ["A visible next action restores focus."],
            },
        ],
        "micro_stories": [
            {
                "story_id": "story_focus",
                "start": 0.0,
                "end": 36.0,
                "summary": "A focus problem leads to one practical action.",
                "completeness_score": 0.86,
                "setup": {
                    "setup_start": 0.0,
                    "setup_end": 5.0,
                    "setup_text": "Why does focus fail?",
                    "confidence": 0.8,
                },
                "context": {"score": 0.2, "reason": "The setup is contained."},
                "tension": {
                    "unresolved_question": "What removes the friction?",
                    "confidence": 0.72,
                },
                "payoff": {
                    "payoff_present": True,
                    "payoff_start": 28.0,
                    "payoff_end": 36.0,
                    "payoff_text": "A visible next action restores focus.",
                    "payoff_strength": 0.84,
                },
                "ending": {
                    "final_line": "A visible next action restores focus.",
                    "final_line_strength": 0.82,
                },
                "risks": [],
            }
        ],
        "emotional_timeline": [
            {
                "start": 0.0,
                "end": 5.0,
                "emotion": "curiosity",
                "intensity": 0.7,
                "evidence": "The opening asks a question.",
            },
            {
                "start": 20.0,
                "end": 28.0,
                "emotion": "surprise",
                "intensity": 0.78,
                "evidence": "The result is unexpected.",
            },
        ],
        "filler_sections": [],
        "repeated_sections": [],
    }


def _build(store: BobaMemoryStore, project_id: str) -> BobaWholeVideoValidationReport:
    transcript = _segments()
    understanding = BobaWholeVideoUnderstandingEngine().build(
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        video_duration_seconds=36.0,
        transcript_segments=transcript,
        analysis_signals_v2={
            "contract_version": "analysis_signals_v2",
            "audio_energy": {
                "timeline": {
                    "events": [
                        {"start_seconds": 20.0, "end_seconds": 36.0, "score": 0.8}
                    ]
                }
            },
        },
        story_artifact=_story(),
        virality_artifact={
            "heatmap": [{"start": 20.0, "end": 36.0, "heat": 0.82}]
        },
        planning_artifact={
            "selected_plans": [
                {
                    "clip_id": "clip_focus",
                    "start": 12.0,
                    "end": 36.0,
                    "selected_reason": "Complete action-to-payoff arc.",
                    "confidence": 0.8,
                }
            ]
        },
    )
    store.save_whole_video_understanding(understanding)
    memory_summary = build_whole_video_memory_summary(understanding)
    store.save_record(whole_video_memory_record(memory_summary))
    encoded = json.dumps(understanding.model_dump(mode="json"))
    full_transcript = " ".join(item["text"] for item in transcript)
    raw_transcript_stored = (
        "transcript_segments" in encoded or full_transcript.casefold() in encoded.casefold()
    )
    context_or_warning = bool(understanding.context_payoff_map) or any(
        "context-to-payoff" in warning for warning in understanding.warnings
    )
    passed = bool(
        understanding.overall_summary
        and understanding.topic_timeline
        and understanding.story_arc.setup
        and understanding.section_scores
        and understanding.shortability_hints
        and context_or_warning
        and not raw_transcript_stored
        and store.load_whole_video_understanding(project_id) is not None
    )
    return BobaWholeVideoValidationReport(
        mode="synthetic_project",
        passed=passed,
        project_id=project_id,
        summary_exists=bool(understanding.overall_summary),
        topic_timeline_exists=bool(understanding.topic_timeline),
        story_arc_exists=bool(understanding.story_arc.setup),
        emotional_beats_exist=bool(understanding.emotional_beats),
        context_payoff_map_exists=bool(understanding.context_payoff_map),
        context_payoff_warning_exists=any(
            "context-to-payoff" in warning for warning in understanding.warnings
        ),
        section_scores_exist=bool(understanding.section_scores),
        shortability_hints_exist=bool(understanding.shortability_hints),
        artifact_persisted=store.whole_video_understanding_path(project_id).is_file(),
        json_safe=bool(json.loads(encoded)),
        raw_transcript_stored=raw_transcript_stored,
        warnings=[
            "Synthetic validation used transcript-shaped metadata only; no media was read.",
            "Scores are deterministic editorial hints, not audience-performance proof.",
        ],
    )


def _self_check() -> BobaWholeVideoValidationReport:
    with TemporaryDirectory() as temporary:
        report = _build(
            BobaMemoryStore(Path(temporary) / "boba"),
            "proj_whole_video_self_check",
        )
        report.mode = "self_check"
        report.warnings.append(
            "Self-check used temporary local JSON and required no media, network, or secrets."
        )
        return report


def _synthetic_project() -> BobaWholeVideoValidationReport:
    with TemporaryDirectory() as temporary:
        return _build(
            BobaMemoryStore(Path(temporary) / "boba"),
            "proj_whole_video_synthetic",
        )


async def _existing_project(project_id: str) -> BobaWholeVideoValidationReport:
    try:
        integration = boba_integration_provider()
        understanding = await integration.generate_whole_video_understanding(project_id)
        encoded = json.dumps(understanding.model_dump(mode="json"))
        context_or_warning = bool(understanding.context_payoff_map) or any(
            "context-to-payoff" in warning for warning in understanding.warnings
        )
        return BobaWholeVideoValidationReport(
            mode="project_id",
            passed=bool(
                understanding.overall_summary
                and understanding.topic_timeline
                and understanding.section_scores
                and understanding.shortability_hints
                and context_or_warning
            ),
            project_id=project_id,
            summary_exists=bool(understanding.overall_summary),
            topic_timeline_exists=bool(understanding.topic_timeline),
            story_arc_exists=bool(understanding.story_arc.setup),
            emotional_beats_exist=bool(understanding.emotional_beats),
            context_payoff_map_exists=bool(understanding.context_payoff_map),
            context_payoff_warning_exists=any(
                "context-to-payoff" in warning for warning in understanding.warnings
            ),
            section_scores_exist=bool(understanding.section_scores),
            shortability_hints_exist=bool(understanding.shortability_hints),
            artifact_persisted=(
                integration.store.load_whole_video_understanding(project_id) is not None
            ),
            json_safe=bool(json.loads(encoded)),
            raw_transcript_stored="transcript_segments" in encoded,
            warnings=[
                "Existing-project mode read only local Olympus artifacts and did not render "
                "or download."
            ],
        )
    except Exception as exc:
        return BobaWholeVideoValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            errors=[str(exc)],
            warnings=["Missing or unreadable project artifacts were not replaced with fake data."],
        )


def _write_report(report: BobaWholeVideoValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_whole_video_understanding_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Whole Video Understanding V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Topic timeline: `{report.topic_timeline_exists}`",
        f"- Story arc: `{report.story_arc_exists}`",
        f"- Emotional beats: `{report.emotional_beats_exist}`",
        f"- Context/payoff map: `{report.context_payoff_map_exists}`",
        f"- Section scores: `{report.section_scores_exist}`",
        f"- Shortability hints: `{report.shortability_hints_exist}`",
        f"- External calls made: `{report.external_calls_made}`",
        f"- Media required: `{report.media_required}`",
        "",
        "This validator does not establish human-level understanding, audience performance, "
        "copyright safety, or production readiness.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_whole_video_understanding_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
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
        report = _self_check()
    elif args.synthetic_project:
        report = _synthetic_project()
    else:
        report = asyncio.run(_existing_project(str(args.project_id)))
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
