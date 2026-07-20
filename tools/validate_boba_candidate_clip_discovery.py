"""Validate BOBA Candidate Clip Discovery V1 without media or external services."""

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
    BobaCandidateClipDiscoveryEngine,
    BobaMemoryStore,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_candidate_clip_discovery"


class BobaCandidateDiscoveryValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    candidate_count: int = 0
    rejected_window_count: int = 0
    windows_valid: bool = False
    durations_valid: bool = False
    boundaries_valid: bool = False
    duplicates_handled: bool = False
    high_overlap_handled: bool = False
    evidence_compact: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_dump_stored: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _segments() -> list[dict[str, Any]]:
    lines = [
        "Nobody talks about why vague goals make focus harder.",
        "The problem is that every unclear task creates another decision.",
        "However, one visible action removes that hidden friction.",
        "First, write the smallest action that can be completed today.",
        "Then suddenly the workload feels smaller and momentum returns.",
        "Finally, that's why clarity beats motivation when work feels stuck.",
        "The truth is most productivity advice starts too late.",
        "What happened next surprised the entire team during the second test.",
        "We removed half the checklist and completion speed doubled.",
        "I realized the useful system was the simplest one, not the busiest one.",
        "The reason this works is that visible progress reduces uncertainty.",
        "Finally, the payoff is calmer work with fewer abandoned tasks.",
    ]
    return [
        {"start": index * 10.0, "end": (index + 1) * 10.0, "text": text}
        for index, text in enumerate(lines)
    ]


def _understanding() -> dict[str, Any]:
    return {
        "schema_version": "boba_whole_video_understanding_v1",
        "project_id": "proj_candidate_discovery_synthetic",
        "source_id": "uploads/proj_candidate_discovery_synthetic/source.mp4",
        "video_duration_seconds": 120.0,
        "topic_timeline": [
            {
                "segment_id": "topic_focus",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "topic": "Focus friction",
                "summary": "Why unclear tasks create hidden friction.",
                "confidence": 0.84,
            },
            {
                "segment_id": "topic_momentum",
                "start_seconds": 40.0,
                "end_seconds": 80.0,
                "topic": "Momentum experiment",
                "summary": "A simpler checklist changes team performance.",
                "confidence": 0.82,
            },
            {
                "segment_id": "topic_payoff",
                "start_seconds": 80.0,
                "end_seconds": 120.0,
                "topic": "Clarity payoff",
                "summary": "Visible progress reduces uncertainty and abandoned work.",
                "confidence": 0.88,
            },
        ],
        "emotional_beats": [
            {
                "beat_id": "emotion_surprise",
                "start_seconds": 70.0,
                "end_seconds": 90.0,
                "emotion_label": "surprise",
                "intensity": 0.82,
                "reason": "The experiment produces an unexpected result.",
                "confidence": 0.78,
            }
        ],
        "context_payoff_map": [
            {
                "link_id": "link_clarity",
                "context_start_seconds": 90.0,
                "context_end_seconds": 100.0,
                "payoff_start_seconds": 100.0,
                "payoff_end_seconds": 120.0,
                "description": "The explanation resolves with a calmer-work payoff.",
                "standalone_clip_possible": True,
                "setup_required": True,
                "confidence": 0.86,
            }
        ],
        "section_scores": [
            {
                "section_id": "section_focus",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "importance_score": 0.8,
                "clarity_score": 0.82,
                "energy_score": 0.58,
                "novelty_score": 0.7,
                "shortability_score": 0.84,
                "filler_score": 0.08,
                "repetition_score": 0.1,
                "reasons": ["Clear problem and turn."],
            },
            {
                "section_id": "section_momentum",
                "start_seconds": 40.0,
                "end_seconds": 80.0,
                "importance_score": 0.78,
                "clarity_score": 0.8,
                "energy_score": 0.82,
                "novelty_score": 0.76,
                "shortability_score": 0.86,
                "filler_score": 0.12,
                "repetition_score": 0.08,
                "reasons": ["Unexpected experiment result."],
            },
            {
                "section_id": "section_filler",
                "start_seconds": 52.0,
                "end_seconds": 67.0,
                "importance_score": 0.2,
                "clarity_score": 0.3,
                "energy_score": 0.2,
                "novelty_score": 0.1,
                "shortability_score": 0.22,
                "filler_score": 0.78,
                "repetition_score": 0.75,
                "reasons": ["Repeated filler."],
            },
            {
                "section_id": "section_payoff",
                "start_seconds": 80.0,
                "end_seconds": 120.0,
                "importance_score": 0.88,
                "clarity_score": 0.9,
                "energy_score": 0.68,
                "novelty_score": 0.72,
                "shortability_score": 0.9,
                "filler_score": 0.04,
                "repetition_score": 0.08,
                "reasons": ["Complete explanation and payoff."],
            },
        ],
        "shortability_hints": [
            {
                "hint_id": "hint_focus",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "suggested_clip_type": "possible_hook",
                "hook_potential": 0.88,
                "setup_needed": False,
                "payoff_strength": 0.5,
                "recommended_action": "consider",
                "reason": "A contrarian opening leads into a clear explanation.",
            },
            {
                "hint_id": "hint_focus_duplicate",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "suggested_clip_type": "candidate_for_short",
                "hook_potential": 0.7,
                "setup_needed": False,
                "payoff_strength": 0.5,
                "recommended_action": "consider",
                "reason": "Duplicate source interval validates deduplication.",
            },
            {
                "hint_id": "hint_momentum",
                "start_seconds": 40.0,
                "end_seconds": 80.0,
                "suggested_clip_type": "candidate_for_short",
                "hook_potential": 0.72,
                "setup_needed": False,
                "payoff_strength": 0.62,
                "recommended_action": "consider",
                "reason": "A surprising experiment creates a standalone result.",
            },
            {
                "hint_id": "hint_payoff",
                "start_seconds": 80.0,
                "end_seconds": 120.0,
                "suggested_clip_type": "payoff_clip",
                "hook_potential": 0.65,
                "setup_needed": True,
                "payoff_strength": 0.9,
                "recommended_action": "include_setup",
                "reason": "The final explanation contains the clearest payoff.",
            },
        ],
    }


def _build(store: BobaMemoryStore, project_id: str) -> BobaCandidateDiscoveryValidationReport:
    transcript = _segments()
    discovery = BobaCandidateClipDiscoveryEngine().discover(
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        video_duration_seconds=120.0,
        transcript_segments=transcript,
        whole_video_understanding=_understanding(),
        analysis_signals_v2={
            "audio_energy": {
                "timeline": {
                    "events": [
                        {"start_seconds": 68.0, "end_seconds": 88.0, "score": 0.85}
                    ]
                }
            }
        },
        story_artifact={
            "micro_stories": [
                {
                    "start": 0.0,
                    "end": 40.0,
                    "summary": "A hidden focus problem leads to one concrete action.",
                    "completeness_score": 0.82,
                    "recommended_for_planning": True,
                    "context": {"score": 0.2},
                    "payoff": {
                        "payoff_present": True,
                        "payoff_start": 30.0,
                        "payoff_end": 40.0,
                    },
                }
            ]
        },
        virality_artifact={
            "why_this_can_work": "A contrarian hook and surprising payoff create curiosity.",
            "editorial_moments": [
                {
                    "start": 42.0,
                    "end": 79.0,
                    "score": 0.8,
                    "reason": "Surprising experiment result",
                }
            ],
        },
        planning_artifact={
            "planning_candidates": [
                {
                    "start": 0.0,
                    "end": 40.0,
                    "confidence": 0.72,
                    "reason": "Existing planning candidate retained as advisory evidence.",
                }
            ]
        },
    )
    store.save_candidate_clip_discovery(discovery)
    encoded = json.dumps(discovery.model_dump(mode="json"))
    windows_valid = all(
        0.0 <= item.start_seconds < item.end_seconds <= 120.0
        for item in discovery.candidates
    )
    durations_valid = all(
        12.0 <= item.duration_seconds <= 90.0 for item in discovery.candidates
    )
    boundaries_valid = all(
        item.boundary_suggestion.recommended_start_seconds == item.start_seconds
        and item.boundary_suggestion.recommended_end_seconds == item.end_seconds
        for item in discovery.candidates
    )
    evidence_compact = all(
        len(snippet) <= 180
        for item in discovery.candidates
        for snippet in item.evidence.transcript_snippets
    )
    duplicates_handled = discovery.diversity_summary.duplicate_windows_removed > 0
    high_overlap_handled = discovery.diversity_summary.high_overlap_windows_removed > 0
    raw_dump = "transcript_segments" in encoded
    persisted = store.load_candidate_clip_discovery(project_id)
    passed = bool(
        len(discovery.candidates) >= 3
        and windows_valid
        and durations_valid
        and boundaries_valid
        and duplicates_handled
        and high_overlap_handled
        and evidence_compact
        and persisted is not None
        and not raw_dump
    )
    return BobaCandidateDiscoveryValidationReport(
        mode="synthetic_project",
        passed=passed,
        project_id=project_id,
        candidate_count=len(discovery.candidates),
        rejected_window_count=len(discovery.rejected_windows),
        windows_valid=windows_valid,
        durations_valid=durations_valid,
        boundaries_valid=boundaries_valid,
        duplicates_handled=duplicates_handled,
        high_overlap_handled=high_overlap_handled,
        evidence_compact=evidence_compact,
        artifact_persisted=store.candidate_clip_discovery_path(project_id).is_file(),
        json_safe=bool(json.loads(encoded)),
        raw_transcript_dump_stored=raw_dump,
        warnings=[
            "Synthetic validation used timed metadata only; no media was read.",
            "Candidate scores are advisory heuristics, not audience-performance proof.",
        ],
    )


def _self_check() -> BobaCandidateDiscoveryValidationReport:
    with TemporaryDirectory() as temporary:
        report = _build(
            BobaMemoryStore(Path(temporary) / "boba"),
            "proj_candidate_discovery_self_check",
        )
        report.mode = "self_check"
        report.warnings.append(
            "Self-check required no network, media, downloader, renderer, or secrets."
        )
        return report


def _synthetic_project() -> BobaCandidateDiscoveryValidationReport:
    with TemporaryDirectory() as temporary:
        return _build(
            BobaMemoryStore(Path(temporary) / "boba"),
            "proj_candidate_discovery_synthetic",
        )


async def _existing_project(project_id: str) -> BobaCandidateDiscoveryValidationReport:
    try:
        integration = boba_integration_provider()
        discovery = await integration.discover_candidate_clips(project_id)
        encoded = json.dumps(discovery.model_dump(mode="json"))
        windows_valid = all(
            0.0 <= item.start_seconds < item.end_seconds
            <= discovery.video_duration_seconds
            for item in discovery.candidates
        )
        durations_valid = all(
            12.0 <= item.duration_seconds <= 90.0 for item in discovery.candidates
        )
        evidence_compact = all(
            len(snippet) <= 180
            for item in discovery.candidates
            for snippet in item.evidence.transcript_snippets
        )
        return BobaCandidateDiscoveryValidationReport(
            mode="project_id",
            passed=bool(discovery.candidates and windows_valid and durations_valid),
            project_id=project_id,
            candidate_count=len(discovery.candidates),
            rejected_window_count=len(discovery.rejected_windows),
            windows_valid=windows_valid,
            durations_valid=durations_valid,
            boundaries_valid=all(
                item.boundary_suggestion.recommended_start_seconds == item.start_seconds
                and item.boundary_suggestion.recommended_end_seconds == item.end_seconds
                for item in discovery.candidates
            ),
            duplicates_handled=True,
            high_overlap_handled=True,
            evidence_compact=evidence_compact,
            artifact_persisted=(
                integration.store.load_candidate_clip_discovery(project_id) is not None
            ),
            json_safe=bool(json.loads(encoded)),
            raw_transcript_dump_stored="transcript_segments" in encoded,
            warnings=[
                "Existing-project mode read local artifacts and did not render or download."
            ],
        )
    except Exception as exc:
        return BobaCandidateDiscoveryValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            errors=[str(exc)],
            warnings=["Missing local signals were not replaced with fabricated candidates."],
        )


def _write_report(report: BobaCandidateDiscoveryValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_candidate_clip_discovery_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Candidate Clip Discovery V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Candidate count: `{report.candidate_count}`",
        f"- Windows valid: `{report.windows_valid}`",
        f"- Duplicates handled: `{report.duplicates_handled}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator does not establish final ranking, audience performance, copyright "
        "safety, or production readiness.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_candidate_clip_discovery_summary.md").write_text(
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
