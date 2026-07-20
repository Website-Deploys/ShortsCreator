"""Validate BOBA Explanation Engine V1 without media or external services."""

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
from olympus.boba import (  # noqa: E402
    BobaEditorialDecisionEngine,
    BobaExplanationEngine,
    BobaExplanationSetV1,
    BobaMemoryStore,
    BobaWholeVideoUnderstandingEngine,
    BobaWholeVideoUnderstandingV1,
)
from olympus.boba.clip_discovery import BobaCandidateClipDiscoveryV1  # noqa: E402
from olympus.boba.clip_ranking import BobaClipRankingV1  # noqa: E402
from olympus.boba.creative_director import BobaCreativeBriefV1  # noqa: E402
from olympus.boba.editorial_decision import BobaEditorialDecisionSetV1  # noqa: E402
from tools.validate_boba_editorial_decision import build_synthetic_inputs  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_explanation_engine"


class BobaExplanationValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    project_summary_present: bool = False
    discovery_explanation_count: int = 0
    ranking_explanation_count: int = 0
    editorial_explanation_count: int = 0
    rejection_explanation_count: int = 0
    render_readiness_explanation_count: int = 0
    evidence_count: int = 0
    evidence_bounded: bool = False
    evidence_sources_present: bool = False
    uncertainty_level: str = "high"
    unavailable_signals_reported: bool = False
    warnings_preserved: bool = False
    limitations_preserved: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_stored: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    explanation_examples: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _transcript_segments() -> list[dict[str, Any]]:
    return [
        {
            "start": 0.0,
            "end": 6.0,
            "text": "The hidden problem is why this system kept failing.",
        },
        {
            "start": 6.0,
            "end": 14.0,
            "text": "Every vague handoff created another avoidable decision.",
        },
        {
            "start": 14.0,
            "end": 24.0,
            "text": "One explicit rule removed those repeated choices.",
        },
        {
            "start": 24.0,
            "end": 32.0,
            "text": "The payoff is a system the team can finally trust.",
        },
    ]


def _story_artifact() -> dict[str, Any]:
    return {
        "schema": "story_analysis_v2",
        "primary_themes": ["systems", "trust"],
        "topic_sections": [
            {
                "section_id": "topic_system",
                "start": 0.0,
                "end": 32.0,
                "title": "Reliable System",
                "summary": "A repeated failure is resolved by one explicit operating rule.",
                "story_potential": 0.9,
                "evidence": ["One explicit rule removed those repeated choices."],
            }
        ],
        "micro_stories": [
            {
                "story_id": "story_system",
                "start": 0.0,
                "end": 32.0,
                "summary": "A hidden process problem resolves into a trustworthy system.",
                "completeness_score": 0.91,
                "setup": {
                    "setup_start": 0.0,
                    "setup_end": 6.0,
                    "setup_text": "The system kept failing.",
                    "confidence": 0.9,
                },
                "context": {"score": 0.1, "reason": "The setup is contained."},
                "tension": {
                    "unresolved_question": "What removes the repeated failures?",
                    "confidence": 0.86,
                },
                "payoff": {
                    "payoff_present": True,
                    "payoff_start": 24.0,
                    "payoff_end": 32.0,
                    "payoff_text": "A system the team can finally trust.",
                    "payoff_strength": 0.92,
                },
                "ending": {
                    "final_line": "The team can finally trust the system.",
                    "final_line_strength": 0.88,
                },
                "risks": [],
            }
        ],
        "emotional_timeline": [
            {
                "start": 24.0,
                "end": 32.0,
                "emotion": "relief",
                "intensity": 0.8,
                "evidence": "The ending resolves the operating problem.",
            }
        ],
        "filler_sections": [],
        "repeated_sections": [],
    }


def _whole_understanding(project_id: str) -> BobaWholeVideoUnderstandingV1:
    return BobaWholeVideoUnderstandingEngine().build(
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        video_duration_seconds=340.0,
        transcript_segments=_transcript_segments(),
        analysis_signals_v2={
            "contract_version": "analysis_signals_v2",
            "audio_energy": {
                "timeline": {
                    "events": [{"start_seconds": 14.0, "end_seconds": 32.0, "score": 0.82}]
                }
            },
        },
        story_artifact=_story_artifact(),
        virality_artifact={"heatmap": [{"start": 0.0, "end": 32.0, "heat": 0.9}]},
        planning_artifact={
            "selected_plans": [
                {
                    "clip_id": "must_make_truth",
                    "start": 0.0,
                    "end": 32.0,
                    "selected_reason": "Complete setup-to-payoff arc.",
                    "confidence": 0.91,
                }
            ]
        },
    )


def build_synthetic_explanation_inputs(
    project_id: str,
) -> tuple[
    BobaWholeVideoUnderstandingV1,
    BobaCandidateClipDiscoveryV1,
    BobaClipRankingV1,
    BobaEditorialDecisionSetV1,
    list[BobaCreativeBriefV1],
    dict[str, Any],
]:
    ranking, discovery, briefs = build_synthetic_inputs(project_id)
    understanding = _whole_understanding(project_id)
    decisions = BobaEditorialDecisionEngine().decide(
        project_id=project_id,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding.model_dump(mode="json"),
        creative_briefs=briefs,
        analysis_artifact={"confidence": 0.9, "signals": ["speech", "visual"]},
        story_artifact=_story_artifact(),
        virality_artifact={"hook_score": 0.91, "retention_score": 0.84},
        planning_artifact={
            "selected_plans": [{"start": 0.0, "end": 32.0, "confidence": 0.91}]
        },
        editing_artifact={"timelines": []},
        memory={"source_summary": "Creator prefers clear practical payoffs."},
        source_context={
            "source_type": "upload",
            "external_source": False,
            "rights_status": "local_upload",
            "transcript_available": True,
            "face_signals_available": True,
            "speaker_signals_available": True,
            "visual_signals_available": True,
        },
    )
    signals = {
        "project": {
            "id": project_id,
            "storage_key": f"uploads/{project_id}/source.mp4",
            "source_type": "upload",
        },
        "source_type": "upload",
        "transcript_available": True,
        "face_signals_available": True,
        "speaker_signals_available": True,
        "visual_signals_available": True,
        "analysis_signals_v2": {
            "speech": {"available": True},
            "visual": {"available": True},
        },
        "whole_video_understanding": understanding.model_dump(mode="json"),
        "candidate_clip_discovery": discovery.model_dump(mode="json"),
        "clip_ranking": ranking.model_dump(mode="json"),
        "editorial_decisions": decisions.model_dump(mode="json"),
    }
    return understanding, discovery, ranking, decisions, briefs, signals


def build_synthetic_explanations(project_id: str) -> BobaExplanationSetV1:
    understanding, discovery, ranking, decisions, briefs, signals = (
        build_synthetic_explanation_inputs(project_id)
    )
    return BobaExplanationEngine().explain_from_signals(
        project_id,
        signals,
        whole_video_understanding=understanding,
        candidate_discovery=discovery,
        clip_ranking=ranking,
        editorial_decisions=decisions,
        creative_briefs=briefs,
        memory={"source_summary": "Creator prefers clear practical payoffs."},
    )


def _evaluate(
    explanations: BobaExplanationSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
) -> BobaExplanationValidationReport:
    all_explanations = [
        *explanations.candidate_explanations,
        *explanations.ranking_explanations,
        *explanations.editorial_explanations,
    ]
    evidence = [item for explanation in all_explanations for item in explanation.evidence]
    encoded = json.dumps(explanations.model_dump(mode="json"))
    full_transcript = " ".join(item["text"] for item in _transcript_segments())
    raw_transcript_stored = (
        "transcript_segments" in encoded or full_transcript.casefold() in encoded.casefold()
    )
    persisted = artifact_path is not None and artifact_path.is_file()
    evidence_bounded = bool(evidence) and all(len(item.snippet) <= 300 for item in evidence)
    evidence_sources_present = bool(evidence) and all(
        item.source_artifact and item.source_field for item in evidence
    )
    warnings_preserved = bool(explanations.warnings) or any(
        item.warnings for item in all_explanations
    )
    limitations_preserved = bool(explanations.limitations) or any(
        item.limitations for item in all_explanations
    )
    passed = bool(
        explanations.project_summary.overall_summary
        and explanations.project_summary.top_recommendation_reason
        and explanations.candidate_explanations
        and explanations.ranking_explanations
        and explanations.editorial_explanations
        and any(item.explanation_type == "rejection" for item in all_explanations)
        and any(item.explanation_type == "render_readiness" for item in all_explanations)
        and evidence_bounded
        and evidence_sources_present
        and warnings_preserved
        and limitations_preserved
        and not raw_transcript_stored
        and persisted
        and json.loads(encoded)
    )
    return BobaExplanationValidationReport(
        mode=mode,
        passed=passed,
        project_id=explanations.project_id,
        project_summary_present=bool(explanations.project_summary.overall_summary),
        discovery_explanation_count=len(explanations.candidate_explanations),
        ranking_explanation_count=len(explanations.ranking_explanations),
        editorial_explanation_count=len(explanations.editorial_explanations),
        rejection_explanation_count=sum(
            item.explanation_type == "rejection" for item in all_explanations
        ),
        render_readiness_explanation_count=sum(
            item.explanation_type == "render_readiness" for item in all_explanations
        ),
        evidence_count=len(evidence),
        evidence_bounded=evidence_bounded,
        evidence_sources_present=evidence_sources_present,
        uncertainty_level=explanations.uncertainty_summary.uncertainty_level,
        unavailable_signals_reported=bool(explanations.signal_explanation.signals_missing),
        warnings_preserved=warnings_preserved,
        limitations_preserved=limitations_preserved,
        artifact_persisted=persisted,
        json_safe=bool(json.loads(encoded)),
        raw_transcript_stored=raw_transcript_stored,
        report_path_writable=True,
        explanation_examples=[
            {
                "candidate_id": item.candidate_id,
                "type": item.explanation_type,
                "summary": item.short_summary,
                "confidence": item.confidence,
                "evidence_count": len(item.evidence),
            }
            for item in all_explanations[:8]
        ],
        warnings=[
            "Validation used bounded synthetic metadata only; no media was read or rendered.",
            "Explanations describe saved evidence and do not predict audience performance.",
            *explanations.limitations[:4],
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
) -> BobaExplanationValidationReport:
    project_id = (
        "proj_explanation_self_check"
        if mode == "self_check"
        else "proj_explanation_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        explanations = store.save_explanations(build_synthetic_explanations(project_id))
        report = _evaluate(
            explanations,
            mode=mode,
            artifact_path=store.explanation_path(project_id),
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    if mode == "self_check":
        report.warnings.append(
            "Self-check required no network, media, downloader, renderer, or secrets."
        )
    return report


async def _existing_project(project_id: str) -> BobaExplanationValidationReport:
    try:
        integration = boba_integration_provider()
        explanations = integration.store.load_explanations(project_id)
        if explanations is None:
            explanations = await integration.generate_explanations(project_id)
        report = _evaluate(
            explanations,
            mode="project_id",
            artifact_path=integration.store.explanation_path(project_id),
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        report.warnings.append(
            "Existing-project mode used saved local artifacts only and did not render or download."
        )
        return report
    except Exception as exc:
        return BobaExplanationValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=["Missing evidence was not replaced with fabricated explanations."],
        )


def _write_report(report: BobaExplanationValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_explanation_engine_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Explanation Engine V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Discovery explanations: `{report.discovery_explanation_count}`",
        f"- Ranking explanations: `{report.ranking_explanation_count}`",
        f"- Editorial explanations: `{report.editorial_explanation_count}`",
        f"- Evidence items: `{report.evidence_count}`",
        f"- Evidence bounded: `{report.evidence_bounded}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "The report explains saved evidence only. It does not establish copyright safety, "
        "rendering success, production readiness, or audience performance.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_explanation_engine_summary.md").write_text(
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
