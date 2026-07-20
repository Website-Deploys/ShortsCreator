"""Validate BOBA Scout and Creative Director V1 without network or media processing."""

from __future__ import annotations

import argparse
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

from olympus.boba import (  # noqa: E402
    BobaApprovalService,
    BobaCreativeDirector,
    BobaMemoryStore,
    BobaScout,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_scout_creative_director"


class BobaScoutCreativeValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_candidates", "synthetic_project"]
    passed: bool
    candidates_created: int = Field(default=0, ge=0)
    candidates_scored: int = Field(default=0, ge=0)
    approval_events_created: int = Field(default=0, ge=0)
    memory_lessons_created: int = Field(default=0, ge=0)
    creative_briefs_created: int = Field(default=0, ge=0)
    rights_gate_passed: bool = False
    memory_learning_passed: bool = False
    json_safe: bool = False
    external_api_required: bool = False
    secrets_required: bool = False
    download_or_processing_triggered: bool = False
    rendering_triggered: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _candidate(
    candidate_id: str,
    *,
    rights_status: str = "unknown",
    permission_confirmed: bool = False,
    emotional_potential: float = 0.75,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "source_type": "manual_link",
        "title": "Why this unexpected focus mistake changes everything",
        "url": "https://example.com/metadata-only-video",
        "creator": "Synthetic Creator",
        "duration_seconds": 480.0,
        "metadata": {
            "topic": "focus",
            "emotion": "motivational",
            "emotional_potential": emotional_potential,
            "novelty_score": 0.75,
            "clip_density": 0.82,
        },
        "rights_status": rights_status,
        "permission_confirmed": permission_confirmed,
        "status": "idea_only",
    }


def _signals() -> dict[str, Any]:
    return {
        "selected_plans": [
            {
                "clip_id": "clip_synthetic",
                "start": 12.0,
                "end": 46.0,
                "hook_line": "Why does focus fail even when you care?",
                "hook_category": "curiosity_gap",
                "scores": {"hook": 0.86, "emotion": 0.72},
                "selected_reason": "Complete setup, tension, and practical payoff.",
                "story": {"story_shape": "problem_to_solution", "context_risk": 0.2},
                "virality": {
                    "why_this_can_work": "A concrete question creates a bounded open loop."
                },
            }
        ],
        "analysis_signals_v2": {"dominant_emotion": "hopeful"},
        "transcript_available": True,
        "transcript_segments": [
            {
                "start": 12.0,
                "end": 15.0,
                "text": "Why does focus fail even when you care?",
            }
        ],
        "editing_timelines": [
            {"clip_id": "clip_synthetic", "pacing_style": "fast"}
        ],
        "safety_status": "low",
        "safety_manual_review_required": False,
    }


def _self_check() -> BobaScoutCreativeValidationReport:
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        scout = BobaScout(store)
        candidate = scout.create_candidate(_candidate("candidate_self_check"))
        score = scout.score_candidate(candidate.candidate_id)
        encoded = json.dumps(
            {
                "candidate": candidate.model_dump(mode="json"),
                "score": score.model_dump(mode="json"),
            }
        )
        passed = bool(
            json.loads(encoded)
            and score.recommended_action == "review_rights_first"
            and store.load_scout_candidate(candidate.candidate_id) is not None
        )
        return BobaScoutCreativeValidationReport(
            mode="self_check",
            passed=passed,
            candidates_created=1,
            candidates_scored=1,
            rights_gate_passed=score.recommended_action != "process_now",
            json_safe=True,
            warnings=[
                "Self-check used temporary local JSON and metadata only.",
                "No official API, download, media inspection, or rendering was requested.",
            ],
        )


def _synthetic_candidates() -> BobaScoutCreativeValidationReport:
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        scout = BobaScout(store)
        approvals = BobaApprovalService(store)
        unknown = scout.create_candidate(_candidate("candidate_unknown"))
        permitted = scout.create_candidate(
            _candidate(
                "candidate_permitted",
                rights_status="permission_confirmed",
                permission_confirmed=True,
            )
        )
        rejected = scout.create_candidate(
            _candidate("candidate_rejected", emotional_potential=0.15)
        )
        future = scout.create_candidate(
            _candidate("candidate_future", emotional_potential=0.15)
        )
        unknown_score = scout.score_candidate(unknown.candidate_id)
        permitted_score = scout.score_candidate(permitted.candidate_id)
        before = scout.score_candidate(future.candidate_id).overall_score
        approvals.decide_candidate(
            permitted.candidate_id,
            decision="approved",
            reason="Synthetic explicit permission-confirmed approval.",
            approve_for_processing=True,
        )
        approvals.decide_candidate(
            rejected.candidate_id,
            decision="rejected",
            reason="Synthetic low-emotion rejection.",
        )
        after = scout.score_candidate(future.candidate_id).overall_score
        events = approvals.list_events()
        saved_permitted = store.load_scout_candidate(permitted.candidate_id)
        lessons = [
            item
            for item in store.list_records()
            if item.source == "explicit_boba_approval"
        ]
        rights_gate_passed = (
            unknown_score.recommended_action == "review_rights_first"
            and permitted_score.recommended_action == "process_now"
            and saved_permitted is not None
            and saved_permitted.status == "approved_for_processing"
        )
        passed = rights_gate_passed and after < before and len(events) == 2
        return BobaScoutCreativeValidationReport(
            mode="synthetic_candidates",
            passed=passed,
            candidates_created=4,
            candidates_scored=4,
            approval_events_created=len(events),
            memory_lessons_created=len(lessons),
            rights_gate_passed=rights_gate_passed,
            memory_learning_passed=after < before,
            json_safe=True,
            warnings=[
                "Synthetic candidates used fake metadata and example.com URLs only.",
                "approved_for_processing is stored status only; no workflow was triggered.",
            ],
        )


def _synthetic_project() -> BobaScoutCreativeValidationReport:
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        director = BobaCreativeDirector(store)
        briefs = director.create_briefs("proj_synthetic", _signals())
        if briefs:
            BobaApprovalService(store).decide_clip_idea(
                "proj_synthetic",
                briefs[0].clip_id,
                decision="approved",
                reason="Synthetic explicit clip-idea approval.",
            )
        encoded = json.dumps([item.model_dump(mode="json") for item in briefs])
        lessons = [
            item
            for item in store.list_records("project", {"project_id": "proj_synthetic"})
            if item.source == "explicit_boba_approval"
        ]
        passed = bool(
            briefs
            and json.loads(encoded)
            and briefs[0].hook_type
            and briefs[0].music_mood
            and "track" not in briefs[0].model_dump(mode="json")
        )
        return BobaScoutCreativeValidationReport(
            mode="synthetic_project",
            passed=passed,
            approval_events_created=len(store.list_approval_events()),
            memory_lessons_created=len(lessons),
            creative_briefs_created=len(briefs),
            memory_learning_passed=bool(lessons),
            json_safe=True,
            warnings=[
                "Synthetic project artifacts were in-memory metadata fixtures.",
                "Creative briefs are advisory and did not trigger rendering.",
                "Music output is a mood label only, not a song or track selection.",
            ],
        )


def _write_report(report: BobaScoutCreativeValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_scout_creative_director_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Scout + Creative Director V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Candidates created: `{report.candidates_created}`",
        f"- Creative briefs created: `{report.creative_briefs_created}`",
        f"- Rights gate passed: `{report.rights_gate_passed}`",
        f"- External API required: `{report.external_api_required}`",
        f"- Download or processing triggered: `{report.download_or_processing_triggered}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        "",
        "This validator uses metadata-only synthetic fixtures. It does not establish copyright "
        "safety, audience performance, or production readiness.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_scout_creative_director_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic-candidates", action="store_true")
    modes.add_argument("--synthetic-project", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.self_check:
        report = _self_check()
    elif args.synthetic_candidates:
        report = _synthetic_candidates()
    else:
        report = _synthetic_project()
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
