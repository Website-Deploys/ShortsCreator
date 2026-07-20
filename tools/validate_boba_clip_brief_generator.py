"""Validate BOBA Clip Brief Generator V1 without media or external services."""

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
from olympus.boba.clip_brief import (  # noqa: E402
    BobaClipBriefGeneratorV1,
    BobaClipBriefSetV1,
)
from olympus.boba.creative_director import (  # noqa: E402
    BobaCreativeDirectionSetV2,
    BobaCreativeDirectorV2Engine,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_creative_director_v2 import (  # noqa: E402
    build_synthetic_creative_direction_inputs,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_clip_brief_generator"


class BobaClipBriefValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    selected_brief_count: int = 0
    backup_brief_count: int = 0
    blocked_brief_count: int = 0
    production_order_present: bool = False
    all_selected_instructions_present: bool = False
    editor_checklists_present: bool = False
    risk_fixes_preserved: bool = False
    music_mood_only: bool = False
    copyrighted_track_paths_present: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_stored: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    brief_examples: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_clip_brief_inputs(
    project_id: str,
) -> tuple[BobaCreativeDirectionSetV2, Any, Any, Any, Any, Any, Any, dict[str, Any]]:
    understanding, discovery, ranking, decisions, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(project_id)
    )
    direction = BobaCreativeDirectorV2Engine().direct_from_signals(
        project_id,
        signals,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        memory=memory,
    )
    signals["creative_direction_v2"] = direction.model_dump(mode="json")
    return (
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    )


def build_synthetic_clip_briefs(project_id: str) -> BobaClipBriefSetV1:
    (
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_clip_brief_inputs(project_id)
    return BobaClipBriefGeneratorV1().generate_from_signals(
        project_id,
        signals,
        creative_direction_v2=direction,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        explanations=explanations,
        whole_video_understanding=understanding,
        memory=memory,
    )


def _evaluate(
    briefs: BobaClipBriefSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
) -> BobaClipBriefValidationReport:
    payload = briefs.model_dump(mode="json")
    encoded = json.dumps(payload)
    instruction_fields = (
        "hook_instruction",
        "opening_three_second_instruction",
        "story_instruction",
        "cut_instruction",
        "caption_instruction",
        "motion_instruction",
        "audio_instruction",
        "sfx_instruction",
        "retention_instruction",
    )
    instructions_present = bool(briefs.selected_briefs) and all(
        all(
            getattr(item, field).summary
            and getattr(item, field).do_this
            and getattr(item, field).avoid_this
            and getattr(item, field).reason
            for field in instruction_fields
        )
        for item in briefs.selected_briefs
    )
    required_checklist = {
        "hook",
        "context",
        "payoff",
        "pacing",
        "captions",
        "motion",
        "audio",
        "rights",
        "render_safety",
        "human_review",
    }
    checklists_present = bool(briefs.selected_briefs) and all(
        required_checklist.issubset({entry.category for entry in item.editor_checklist})
        for item in briefs.selected_briefs
    )
    required_risk_terms = {"context", "payoff", "hook", "filler", "rights", "audio", "motion"}
    risk_fixes = bool(briefs.selected_briefs) and all(
        required_risk_terms.issubset(
            {term for term in required_risk_terms if term in " ".join(item.risk_fixes).casefold()}
        )
        for item in briefs.selected_briefs
    )
    forbidden_path_markers = (".mp3", ".wav", ".m4a", ".aac", ".flac", "music/", "music\\")
    audio_payloads = [
        json.dumps(item.audio_instruction.model_dump(mode="json")).casefold()
        for item in [
            *briefs.selected_briefs,
            *briefs.backup_briefs,
            *briefs.blocked_briefs,
        ]
    ]
    copyrighted_paths = any(
        marker in value for value in audio_payloads for marker in forbidden_path_markers
    )
    music_mood_only = bool(audio_payloads) and not copyrighted_paths and all(
        "mood" in value and "asset path" in value for value in audio_payloads
    )
    persisted = artifact_path is not None and artifact_path.is_file()
    json_safe = bool(json.loads(encoded))
    raw_transcript_stored = "transcript_segments" in encoded or '"transcript"' in encoded
    passed = bool(
        briefs.selected_briefs
        and briefs.backup_briefs
        and briefs.blocked_briefs
        and briefs.production_order
        and instructions_present
        and checklists_present
        and risk_fixes
        and music_mood_only
        and not copyrighted_paths
        and persisted
        and json_safe
        and not raw_transcript_stored
    )
    return BobaClipBriefValidationReport(
        mode=mode,
        passed=passed,
        project_id=briefs.project_id,
        selected_brief_count=len(briefs.selected_briefs),
        backup_brief_count=len(briefs.backup_briefs),
        blocked_brief_count=len(briefs.blocked_briefs),
        production_order_present=bool(briefs.production_order),
        all_selected_instructions_present=instructions_present,
        editor_checklists_present=checklists_present,
        risk_fixes_preserved=risk_fixes,
        music_mood_only=music_mood_only,
        copyrighted_track_paths_present=copyrighted_paths,
        artifact_persisted=persisted,
        json_safe=json_safe,
        raw_transcript_stored=raw_transcript_stored,
        brief_examples=[
            {
                "candidate_id": item.candidate_id,
                "title": item.brief_title,
                "readiness": item.render_readiness,
                "priority": item.production_priority,
                "opening": item.opening_three_second_instruction.summary,
                "music_instruction": item.audio_instruction.summary,
                "checklist_items": len(item.editor_checklist),
            }
            for item in briefs.selected_briefs[:8]
        ],
        warnings=[
            "Validation used bounded local metadata only; no media was read, edited, "
            "downloaded, or rendered.",
            "Brief confidence and instructions do not prove audience performance, rights "
            "safety, or production readiness.",
            *briefs.limitations[:5],
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
    *, mode: Literal["self_check", "synthetic_project"]
) -> BobaClipBriefValidationReport:
    project_id = (
        "proj_clip_brief_self_check"
        if mode == "self_check"
        else "proj_clip_brief_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        briefs = store.save_clip_briefs(build_synthetic_clip_briefs(project_id))
        report = _evaluate(
            briefs,
            mode=mode,
            artifact_path=store.clip_briefs_path(project_id),
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    if mode == "self_check":
        report.warnings.append(
            "Self-check required no network, media, downloader, renderer, or secrets."
        )
    return report


async def _existing_project(project_id: str) -> BobaClipBriefValidationReport:
    try:
        integration = boba_integration_provider()
        briefs = integration.store.load_clip_briefs(project_id)
        if briefs is None:
            briefs = await integration.generate_clip_briefs(project_id)
        report = _evaluate(
            briefs,
            mode="project_id",
            artifact_path=integration.store.clip_briefs_path(project_id),
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        report.warnings.append(
            "Existing-project mode used saved local BOBA artifacts only and did not "
            "render or download."
        )
        return report
    except Exception as exc:
        return BobaClipBriefValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=[
                "Missing artifacts were reported rather than replaced with fabricated "
                "creative evidence."
            ],
        )


def _write_report(report: BobaClipBriefValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_clip_brief_generator_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Clip Brief Generator V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Selected briefs: `{report.selected_brief_count}`",
        f"- Backup briefs: `{report.backup_brief_count}`",
        f"- Blocked briefs: `{report.blocked_brief_count}`",
        f"- Instructions complete: `{report.all_selected_instructions_present}`",
        f"- Music mood only: `{report.music_mood_only}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks advisory metadata only. It does not establish rendering, "
        "copyright safety, production readiness, or audience performance.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_clip_brief_generator_summary.md").write_text(
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
