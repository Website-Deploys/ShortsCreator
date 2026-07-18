"""Validate editorial clip-boundary quality with synthetic transcript fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.planning.boundary_quality import (  # noqa: E402
    ClipBoundaryQualityV1,
    recommend_clip_boundaries,
)

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "clip_boundary_quality"
REPORT_NAME = "clip_boundary_quality_report.json"
SUMMARY_NAME = "clip_boundary_quality_summary.md"
SYNTHETIC_INPUT_POLICY = {
    "generated_synthetic_transcript_only": True,
    "real_user_media_used": False,
    "downloads_used": False,
    "external_api_calls_used": False,
    "network_used": False,
}


def _segments(*, words: bool = True) -> list[dict[str, Any]]:
    raw = [
        (0.0, 4.0, "Why does this strategy fail?"),
        (4.0, 8.0, "Here is the context you need before the answer."),
        (8.0, 14.0, "But the real problem is that people skip the setup."),
        (14.0, 20.0, "So the answer is to preserve context and payoff together."),
        (20.0, 24.0, "That is why the complete story works."),
        (24.0, 30.0, "Um, and then there is some low-value trailing chatter."),
    ]
    output: list[dict[str, Any]] = []
    for start, end, text in raw:
        segment: dict[str, Any] = {"start": start, "end": end, "text": text}
        if words:
            tokens = text.split()
            step = (end - start) / max(1, len(tokens))
            segment["words"] = [
                {
                    "word": token,
                    "start": round(start + index * step, 3),
                    "end": round(start + (index + 1) * step, 3),
                }
                for index, token in enumerate(tokens)
            ]
        output.append(segment)
    return output


def _story(
    *,
    context_start: float = 0.0,
    payoff_end: float = 24.0,
    confidence: float = 0.9,
    context_risk: float = 0.1,
) -> dict[str, Any]:
    return {
        "story_guidance_used": True,
        "story_guidance_source": "synthetic_story_v2",
        "story_id": "story_complete",
        "story_start": 0.0,
        "recommended_start": context_start,
        "recommended_end": payoff_end,
        "completeness_score": 0.92,
        "payoff_strength": 0.9,
        "context_risk": context_risk,
        "ending_strength": confidence,
        "planning_guidance": {
            "recommended_start": context_start,
            "recommended_end": payoff_end,
            "boundary_confidence": confidence,
            "must_include_spans": [
                {"kind": "payoff", "start": 20.0, "end": payoff_end}
            ],
        },
    }


def _context(
    *,
    words: bool = True,
    story: dict[str, Any] | None = None,
    previous: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    return {
        "project_id": "synthetic_project",
        "transcript_segments": _segments(words=words),
        "story_guidance": story if story is not None else _story(),
        "hook_start_seconds": 0.0,
        "payoff_end_seconds": 24.0,
        "previous_selected_ranges": previous or [],
        "source_duration_seconds": 30.0,
        "minimum_duration_seconds": 8.0,
        "maximum_duration_seconds": 30.0,
    }


def _candidate(start: float, end: float, name: str) -> dict[str, Any]:
    return {
        "candidate_id": name,
        "raw_start": start,
        "raw_end": end,
        "start": start,
        "end": end,
        "hook_potential": 0.85,
        "payoff_potential": 0.85,
        "confidence": 0.85,
    }


def _record(
    name: str,
    quality: ClipBoundaryQualityV1,
    *,
    passed: bool,
    expectation: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "expectation": expectation,
        "boundary_quality": quality.to_dict(),
    }


def synthetic_scenarios() -> list[dict[str, Any]]:
    good = recommend_clip_boundaries(_candidate(0.0, 24.0, "good"), _context())
    after_hook = recommend_clip_boundaries(_candidate(2.0, 24.0, "after_hook"), _context())
    missing_context_context = _context(story=_story(context_start=0.0, context_risk=0.72))
    missing_context_context["hook_start_seconds"] = None
    missing_context = recommend_clip_boundaries(
        _candidate(4.0, 24.0, "missing_context"),
        missing_context_context,
    )
    before_payoff = recommend_clip_boundaries(
        _candidate(0.0, 18.0, "before_payoff"), _context()
    )
    drag_context = _context(story=_story(payoff_end=20.0))
    drag_context["payoff_end_seconds"] = 20.0
    dragging = recommend_clip_boundaries(_candidate(0.0, 30.0, "dragging"), drag_context)
    duplicate = recommend_clip_boundaries(
        _candidate(0.0, 24.0, "duplicate"),
        _context(previous=[{"start": 0.0, "end": 24.0}]),
    )
    no_words = recommend_clip_boundaries(
        _candidate(0.0, 24.0, "no_words"), _context(words=False)
    )
    low_confidence = recommend_clip_boundaries(
        _candidate(0.0, 24.0, "low_confidence"),
        _context(story=_story(confidence=0.2)),
    )
    return [
        _record(
            "good_complete_clip",
            good,
            passed=good.quality_score >= 0.75,
            expectation="complete candidate scores high",
        ),
        _record(
            "starts_after_hook",
            after_hook,
            passed=after_hook.recommended_start_seconds <= 0.05
            and after_hook.abrupt_start_risk >= 0.7,
            expectation="missed hook pulls start earlier",
        ),
        _record(
            "starts_without_context",
            missing_context,
            passed=missing_context.recommended_start_seconds <= 0.05,
            expectation="required context pulls start earlier",
        ),
        _record(
            "ends_before_payoff",
            before_payoff,
            passed=before_payoff.recommended_end_seconds >= 24.0,
            expectation="payoff is included",
        ),
        _record(
            "drags_after_payoff",
            dragging,
            passed=dragging.recommended_end_seconds < 30.0,
            expectation="low-value tail is tightened",
        ),
        _record(
            "duplicate_overlap",
            duplicate,
            passed=duplicate.duplicate_risk >= 0.45 and bool(duplicate.warnings),
            expectation="overlap is penalized and warned",
        ),
        _record(
            "no_word_timings",
            no_words,
            passed=any("segment timing fallback" in item for item in no_words.warnings),
            expectation="segment fallback remains explicit",
        ),
        _record(
            "low_confidence_story",
            low_confidence,
            passed=any("low confidence" in item for item in low_confidence.warnings),
            expectation="uncertain story evidence warns instead of claiming confidence",
        ),
    ]


def _summary(report: dict[str, Any]) -> str:
    lines = [
        "# Clip Boundary Quality Validation",
        "",
        f"- Mode: `{report.get('mode')}`",
        f"- Passed: `{str(report.get('passed')).lower()}`",
        f"- Generated: `{report.get('generated_at')}`",
        "",
    ]
    for scenario in report.get("scenarios", []):
        if isinstance(scenario, dict):
            lines.append(f"- `{scenario.get('name')}`: `{scenario.get('passed')}`")
    for warning in report.get("warnings", []):
        lines.append(f"- Warning: {warning}")
    return "\n".join(lines) + "\n"


def _write_report(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    final = {"generated_at": datetime.now(UTC).isoformat(), **report}
    (output_dir / REPORT_NAME).write_text(
        json.dumps(final, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / SUMMARY_NAME).write_text(_summary(final), encoding="utf-8")
    return final


def run_self_check(*, output_dir: Path = DEFAULT_REPORT_DIR) -> dict[str, Any]:
    quality = recommend_clip_boundaries(_candidate(0.0, 24.0, "self_check"), _context())
    restored = ClipBoundaryQualityV1.from_dict(quality.to_dict())
    return _write_report(
        output_dir,
        {
            "mode": "self-check",
            "passed": quality.quality_score >= 0.75 and restored.to_dict() == quality.to_dict(),
            "checks": {
                "contract_round_trip": {"passed": restored.to_dict() == quality.to_dict()},
                "complete_clip_quality": {
                    "passed": quality.quality_score >= 0.75,
                    "quality_score": quality.quality_score,
                },
                "synthetic_input_policy": {"passed": True, **SYNTHETIC_INPUT_POLICY},
            },
            "warnings": [
                "Synthetic transcript validation improves confidence but does not replace playback."
            ],
        },
    )


def run_simulation(*, output_dir: Path = DEFAULT_REPORT_DIR) -> dict[str, Any]:
    scenarios = synthetic_scenarios()
    return _write_report(
        output_dir,
        {
            "mode": "simulate",
            "passed": all(item["passed"] is True for item in scenarios),
            "scenario_count": len(scenarios),
            "scenarios": scenarios,
            "input_policy": SYNTHETIC_INPUT_POLICY,
            "warnings": [
                "No real media or external service was used; editorial quality is not human-proven."
            ],
        },
    )


def _stage_data(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def run_project_inspection(
    project_id: str,
    *,
    output_dir: Path = DEFAULT_REPORT_DIR,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    root = (storage_root or ROOT / "storage_data").resolve()
    project_path = root / "projects" / project_id / "project.json"
    boundary_path = root / "planning" / project_id / "stages" / "boundary_refinement.json"
    editing_path = root / "editing" / project_id / "stages" / "timeline_validation.json"
    searched_paths = [str(project_path), str(boundary_path), str(editing_path)]
    if not project_path.is_file():
        return _write_report(
            output_dir,
            {
                "mode": "project-id",
                "project_id": project_id,
                "passed": False,
                "project_found": False,
                "inspection_only": True,
                "searched_paths": searched_paths,
                "checks": {"project": {"passed": False, "reason": "project not found"}},
                "warnings": ["Project not found; no artifact was modified."],
            },
        )
    boundary_data = _stage_data(boundary_path) if boundary_path.is_file() else {}
    candidates = boundary_data.get("candidates")
    candidate_list = candidates if isinstance(candidates, list) else []
    candidate_checks = [
        {
            "clip_id": item.get("candidate_id") or item.get("id"),
            "passed": bool(isinstance(item.get("boundary_quality"), dict)),
            "boundary_quality": item.get("boundary_quality"),
        }
        for item in candidate_list
        if isinstance(item, dict)
    ]
    editing_data = _stage_data(editing_path) if editing_path.is_file() else {}
    timelines = editing_data.get("timelines")
    timeline_list = timelines if isinstance(timelines, list) else []
    timeline_checks = [
        {
            "clip_id": item.get("clip_id"),
            "passed": bool(
                isinstance(item.get("boundary_quality"), dict)
                or isinstance(
                    (item.get("metadata") or {}).get("boundary_quality")
                    if isinstance(item.get("metadata"), dict)
                    else None,
                    dict,
                )
            ),
        }
        for item in timeline_list
        if isinstance(item, dict)
    ]
    checks = {
        "project": {"passed": True, "path": str(project_path)},
        "planning_boundary_quality": {
            "passed": boundary_path.is_file()
            and bool(candidate_checks)
            and all(item["passed"] for item in candidate_checks),
            "path": str(boundary_path),
            "candidates": candidate_checks,
        },
        "editing_boundary_quality": {
            "passed": not editing_path.is_file()
            or (bool(timeline_checks) and all(item["passed"] for item in timeline_checks)),
            "path": str(editing_path),
            "status": "not_rendered_yet" if not editing_path.is_file() else "inspected",
            "timelines": timeline_checks,
        },
    }
    return _write_report(
        output_dir,
        {
            "mode": "project-id",
            "project_id": project_id,
            "project_found": True,
            "inspection_only": True,
            "passed": all(item["passed"] is True for item in checks.values()),
            "searched_paths": searched_paths,
            "checks": checks,
            "warnings": [],
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--simulate", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--storage-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.self_check:
            report = run_self_check(output_dir=args.output_dir)
        elif args.simulate:
            report = run_simulation(output_dir=args.output_dir)
        else:
            report = run_project_inspection(
                str(args.project_id),
                output_dir=args.output_dir,
                storage_root=args.storage_root,
            )
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
