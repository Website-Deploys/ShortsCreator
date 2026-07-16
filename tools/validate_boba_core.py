"""Validate BOBA Core Brain V1 without downloading or rendering media."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.boba import BobaBrain, BobaIntegration, BobaMemoryStore  # noqa: E402
from olympus.boba.contracts import BobaValidationResultV1  # noqa: E402
from olympus.boba.editorial_policy import create_editorial_policy  # noqa: E402
from olympus.boba.ranking import rank_candidates  # noqa: E402
from olympus.boba.validation import compact_boba_summary, self_check  # noqa: E402
from olympus.data.repositories import StorageProjectRepository  # noqa: E402
from olympus.data.storage import build_storage  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402


def _signals() -> dict[str, Any]:
    return {
        "project": {
            "source_type": "upload",
            "duration_seconds": 420.0,
        },
        "transcript_available": True,
        "visual_signals_available": False,
        "face_signals_available": False,
        "speaker_signals_available": True,
        "trend_signals_available": True,
        "safety_signals_available": True,
        "personalization_signals_available": False,
        "trend_fallback_used": True,
        "safety_manual_review_required": True,
        "render_manifest_available": False,
        "planning_candidates_available": True,
        "editing_timelines_available": False,
        "content_niche": "podcast",
        "main_topics": ["creator discipline", "attention habits"],
        "story_threads": ["problem to lesson"],
        "known_limitations": [
            "A/V sync perception has not been manually verified.",
            "Abrupt-cut risk remains a separate rendering concern.",
        ],
    }


def _candidates() -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": "strong",
            "start": 20.0,
            "end": 52.0,
            "scores": {
                "hook": 0.88,
                "story_completion": 0.86,
                "payoff": 0.84,
                "emotion": 0.7,
                "trend_fit": 0.55,
            },
            "editing_opportunity": 0.8,
            "boundary_quality": 0.9,
        },
        {
            "candidate_id": "weak",
            "start": 21.0,
            "end": 39.0,
            "scores": {
                "hook": 0.35,
                "story_completion": 0.25,
                "payoff": 0.1,
                "emotion": 0.4,
            },
            "context_requirement": 0.8,
            "boundary_risk": True,
        },
    ]


def _write_report(report: BobaValidationResultV1) -> None:
    directory = ROOT / "work" / "validation_reports" / "boba_core"
    directory.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (directory / "boba_core_validation_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Core Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'simulation'}`",
        f"- Brain state created: `{report.brain_state_created}`",
        f"- Memory written: `{report.memory_written}`",
        f"- Decisions created: `{report.decisions_created}`",
        f"- Ranking created: `{report.ranking_created}`",
        f"- Editorial policy created: `{report.editorial_policy_created}`",
        "",
        "BOBA Core Brain V1 is advisory. It does not render, publish, scout YouTube, "
        "learn from analytics, establish copyright safety, or guarantee virality.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.missing_signals:
        summary.extend(
            ["", "## Missing Signals", *[f"- {item}" for item in report.missing_signals]]
        )
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (directory / "boba_core_validation_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )


def _simulate_project() -> BobaValidationResultV1:
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(temporary)
        state = BobaBrain(store).create_brain_state("proj_simulated", _signals())
        compact = compact_boba_summary(brain=state.model_dump(mode="json"))
        return BobaValidationResultV1(
            passed=bool(state.brain_id and compact.get("advisory_only")),
            mode="simulate_project",
            project_id=state.project_id,
            brain_state_created=True,
            memory_written=store.load_brain_state(state.project_id) is not None,
            unified_metadata_present=bool(compact),
            unified_metadata_checked=True,
            missing_signals=state.source_understanding.missing_signals,
            warnings=state.result.warnings,
        )


def _simulate_ranking() -> BobaValidationResultV1:
    ranking = rank_candidates("proj_simulated", _candidates())
    passed = bool(
        ranking.ranked_candidates
        and ranking.ranked_candidates[0].candidate_id == "strong"
        and ranking.duplicate_groups
    )
    return BobaValidationResultV1(
        passed=passed,
        mode="simulate_ranking",
        project_id=ranking.project_id,
        ranking_created=True,
        warnings=ranking.warnings,
    )


def _simulate_policy() -> BobaValidationResultV1:
    policy = create_editorial_policy(
        "proj_simulated",
        "clip_strong",
        {"hook_strength": 0.85, "emotion": 0.75, "content_niche": "motivational"},
        {
            "transcript_available": True,
            "face_layout_available": False,
            "music_available": True,
            "safety_status": "unknown",
        },
    )
    return BobaValidationResultV1(
        passed=bool(
            policy.ending_directives.get("avoid_cutting_final_word")
            and policy.music_directives.get("ducking_priority") == "speech_first"
        ),
        mode="simulate_editorial_policy",
        project_id=policy.project_id,
        editorial_policy_created=True,
        warnings=policy.warnings,
    )


async def _existing(project_id: str | None, latest: bool) -> BobaValidationResultV1:
    settings = get_settings()
    storage = build_storage()
    projects = StorageProjectRepository(storage)
    if latest:
        available = await projects.list()
        project_id = available[0].id if available else None
    if not project_id:
        return BobaValidationResultV1(
            passed=False,
            mode="existing_project",
            errors=["No existing project is available."],
        )
    integration = BobaIntegration(
        storage,
        BobaMemoryStore(
            settings.boba.storage_dir,
            max_excerpt_chars=settings.boba.max_excerpt_chars,
            max_decisions_per_project=settings.boba.max_decisions_per_project,
        ),
        mode=settings.boba.mode,
    )
    try:
        state = await integration.generate_boba_for_project(project_id)
        ranking = await integration.rank_project_candidates(project_id)
    except Exception as exc:
        return BobaValidationResultV1(
            passed=False,
            mode="existing_project",
            project_id=project_id,
            errors=[f"{type(exc).__name__}: {exc}"],
        )
    return BobaValidationResultV1(
        passed=True,
        mode="existing_project",
        project_id=project_id,
        brain_state_created=True,
        memory_written=integration.store.load_brain_state(project_id) is not None,
        decisions_created=len(integration.store.list_decisions(project_id)),
        ranking_created=True,
        unified_metadata_checked=True,
        missing_signals=state.source_understanding.missing_signals,
        warnings=[
            *state.result.warnings,
            *ranking.warnings,
            "Existing-project validation did not rerender or manually inspect media.",
        ],
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--simulate-project", action="store_true")
    modes.add_argument("--simulate-ranking", action="store_true")
    modes.add_argument("--simulate-editorial-policy", action="store_true")
    modes.add_argument("--project-id")
    modes.add_argument("--latest", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.self_check:
        report = self_check()
    elif args.simulate_project:
        report = _simulate_project()
    elif args.simulate_ranking:
        report = _simulate_ranking()
    elif args.simulate_editorial_policy:
        report = _simulate_policy()
    else:
        report = asyncio.run(_existing(args.project_id, args.latest))
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
