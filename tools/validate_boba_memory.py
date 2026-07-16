"""Validate BOBA Memory System V1 without downloading or rendering media."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.boba import BobaIntegration, BobaMemoryStore  # noqa: E402
from olympus.boba.creator_memory import build_and_save_creator_memory  # noqa: E402
from olympus.boba.global_memory import build_and_save_global_memory  # noqa: E402
from olympus.boba.memory_application import create_memory_application  # noqa: E402
from olympus.boba.memory_contracts import (  # noqa: E402
    BobaMemoryQueryV1,
    BobaMemoryRecordV1,
)
from olympus.boba.memory_learning import BobaMemoryLearner  # noqa: E402
from olympus.boba.memory_validation import validate_memory_record  # noqa: E402
from olympus.boba.project_memory import build_and_save_project_memory  # noqa: E402
from olympus.data.storage import build_storage  # noqa: E402
from olympus.personalization.contracts import (  # noqa: E402
    ClipFeedbackV2,
    FeedbackLabels,
    FeedbackRating,
    SafeLearning,
)
from olympus.personalization.presets import profile_from_preset  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402
from olympus.platform.errors import ValidationError  # noqa: E402


class MemoryValidationReport(BaseModel):
    mode: str
    passed: bool
    project_id: str | None = None
    project_memory_created: bool = False
    creator_memory_created: bool = False
    global_memory_created: bool = False
    records_written: int = Field(default=0, ge=0)
    records_retrieved: int = Field(default=0, ge=0)
    unsafe_content_blocked: bool = False
    export_import_passed: bool = False
    memory_application_created: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _signals() -> dict[str, Any]:
    return {
        "project": {"name": "Simulated memory project", "content_category": "education"},
        "duration_seconds": 180.0,
        "transcript_available": True,
        "content_niche": "education",
        "main_topics": ["focus", "creative discipline"],
        "speakers_or_roles": ["host"],
        "story_threads": ["problem to practical lesson"],
        "emotional_moments": ["A short turning point"],
        "planning_candidates": [
            {"candidate_id": "candidate_one", "start": 10.0, "end": 42.0}
        ],
        "selected_plans": [
            {
                "clip_id": "clip_one",
                "start": 10.0,
                "end": 42.0,
                "hook_line": "This is why focus keeps failing.",
                "selected_reason": "Complete setup and payoff.",
            }
        ],
        "rejected_candidates": [
            {"candidate_id": "candidate_two", "reason": "Missing payoff."}
        ],
        "unused_opportunities": ["A second bounded story remains unused."],
        "safety_status": "unknown",
    }


def _feedback(feedback_id: str = "feedback_simulated") -> ClipFeedbackV2:
    return ClipFeedbackV2(
        feedback_id=feedback_id,
        profile_id="creator_simulated",
        project_id="proj_simulated",
        clip_id="clip_one",
        rating=FeedbackRating(overall="like", music="dislike"),
        labels=FeedbackLabels(liked=True, music_bad=True),
        notes="The story works, but keep music lower than speech.",
        extracted_safe_learning=SafeLearning(
            liked_clip_traits=["emotional_payoff"],
            disliked_music_moods=["high_intensity"],
        ),
    )


def _store(root: Path) -> BobaMemoryStore:
    return BobaMemoryStore(root / "boba")


def _self_check() -> MemoryValidationReport:
    with TemporaryDirectory() as temporary:
        store = _store(Path(temporary))
        record = store.save_record(
            BobaMemoryRecordV1(
                scope="project",
                record_type="project_summary",
                source="self_check",
                project_id="proj_self_check",
                summary="A bounded local test record.",
                applies_to=["frontend"],
            )
        )
        blocked = False
        try:
            validate_memory_record(record.model_copy(update={"summary": "api_key=blocked"}))
        except ValidationError:
            blocked = True
        return MemoryValidationReport(
            mode="self_check",
            passed=store.get_record(record.memory_id) is not None and blocked,
            records_written=1,
            unsafe_content_blocked=blocked,
            warnings=["Self-check used temporary local JSON only."],
        )


def _simulate_project() -> MemoryValidationReport:
    with TemporaryDirectory() as temporary:
        store = _store(Path(temporary))
        memory = build_and_save_project_memory(
            store, "proj_simulated", _signals()
        )
        return MemoryValidationReport(
            mode="simulate_project",
            passed=bool(memory.selected_clip_ids and memory.known_limitations),
            project_id=memory.project_id,
            project_memory_created=True,
            records_written=len(store.list_records("project")),
            warnings=memory.warnings,
        )


def _simulate_creator() -> MemoryValidationReport:
    with TemporaryDirectory() as temporary:
        store = _store(Path(temporary))
        profile = profile_from_preset(
            "balanced_default",
            profile_id="creator_simulated",
            profile_name="Simulated Creator",
            learning_enabled=True,
        )
        memory = build_and_save_creator_memory(store, profile, [_feedback()])
        return MemoryValidationReport(
            mode="simulate_creator",
            passed=memory.explicit_feedback_only and memory.feedback_count == 1,
            creator_memory_created=True,
            records_written=len(store.list_records("creator")),
            warnings=memory.warnings,
        )


def _simulate_global() -> MemoryValidationReport:
    with TemporaryDirectory() as temporary:
        store = _store(Path(temporary))
        memory = build_and_save_global_memory(store)
        return MemoryValidationReport(
            mode="simulate_global",
            passed=bool(memory.principles and memory.safety_principles),
            global_memory_created=True,
            records_written=len(store.list_records("global")),
            warnings=memory.warnings,
        )


def _simulate_feedback() -> MemoryValidationReport:
    with TemporaryDirectory() as temporary:
        store = _store(Path(temporary))
        record = BobaMemoryLearner(store).learn_from_feedback(_feedback())
        return MemoryValidationReport(
            mode="simulate_feedback",
            passed=record.source == "explicit_user_feedback",
            records_written=1,
            warnings=["No passive behavior was observed or stored."],
        )


def _simulate_query() -> MemoryValidationReport:
    with TemporaryDirectory() as temporary:
        store = _store(Path(temporary))
        build_and_save_project_memory(store, "proj_simulated", _signals())
        build_and_save_global_memory(store)
        result = store.query_memory(
            BobaMemoryQueryV1(
                project_id="proj_simulated",
                target_system="planning",
                tags=["education"],
                reason="Simulated advisory retrieval.",
            )
        )
        application = create_memory_application(
            "proj_simulated", "planning", result
        )
        return MemoryValidationReport(
            mode="simulate_query",
            passed=bool(result.records and application.memory_used),
            project_id="proj_simulated",
            project_memory_created=True,
            global_memory_created=True,
            records_written=len(store.list_records()),
            records_retrieved=len(result.records),
            memory_application_created=bool(application.memory_used),
            warnings=result.warnings,
        )


def _simulate_export_import() -> MemoryValidationReport:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = _store(root / "source")
        build_and_save_project_memory(source, "proj_simulated", _signals())
        build_and_save_global_memory(source)
        payload = source.export_memory()
        target = _store(root / "target")
        counts = target.import_memory(payload)
        passed = bool(
            counts["records"]
            and counts["project_memories"] == 1
            and counts["global_memories"] == 1
        )
        return MemoryValidationReport(
            mode="simulate_export_import",
            passed=passed,
            project_memory_created=target.load_project_memory("proj_simulated") is not None,
            global_memory_created=target.load_global_memory() is not None,
            records_written=counts["records"],
            export_import_passed=passed,
            warnings=["Export/import simulation used temporary local JSON only."],
        )


async def _existing_project(project_id: str) -> MemoryValidationReport:
    settings = get_settings()
    storage = build_storage()
    memory_settings = settings.boba_memory
    store = BobaMemoryStore(
        settings.boba.storage_dir,
        max_excerpt_chars=memory_settings.max_excerpt_chars,
        max_decisions_per_project=settings.boba.max_decisions_per_project,
        memory_root=memory_settings.storage_dir,
        max_records_per_project=memory_settings.max_records_per_project,
        max_records_per_creator=memory_settings.max_records_per_creator,
        max_global_records=memory_settings.max_global_records,
        allow_import_export=memory_settings.allow_import_export,
        backup_before_reset=memory_settings.backup_before_reset,
    )
    integration = BobaIntegration(
        storage,
        store,
        mode=settings.boba.mode,
        memory_enabled=memory_settings.enabled,
        allow_global_memory=memory_settings.allow_global_memory,
    )
    if await integration.projects.get(project_id) is None:
        return MemoryValidationReport(
            mode="existing_project",
            passed=False,
            project_id=project_id,
            errors=["Project was not found."],
        )
    memory = await integration.build_project_memory(project_id)
    query = store.query_memory(
        BobaMemoryQueryV1(
            project_id=project_id,
            target_system="planning",
            reason="Existing project validation.",
        )
    )
    application = create_memory_application(project_id, "planning", query)
    return MemoryValidationReport(
        mode="existing_project",
        passed=True,
        project_id=project_id,
        project_memory_created=True,
        global_memory_created=store.load_global_memory() is not None,
        records_written=len(memory.memory_records),
        records_retrieved=len(query.records),
        memory_application_created=bool(application.memory_used),
        warnings=[
            *memory.warnings,
            *memory.known_limitations,
            "Existing-project validation did not render, play, or modify media.",
        ],
    )


def _write_report(report: MemoryValidationReport) -> None:
    directory = ROOT / "work" / "validation_reports" / "boba_memory"
    directory.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (directory / "boba_memory_validation_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    lines = [
        "# BOBA Memory System V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'simulation'}`",
        f"- Records written: `{report.records_written}`",
        f"- Records retrieved: `{report.records_retrieved}`",
        f"- Unsafe content blocked: `{report.unsafe_content_blocked}`",
        f"- Export/import passed: `{report.export_import_passed}`",
        "",
        "Memory is local, explicit, bounded, inspectable, exportable, and resettable. "
        "It does not prove performance, copyright safety, or render correctness.",
    ]
    if report.warnings:
        lines.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        lines.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (directory / "boba_memory_validation_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--simulate-project", action="store_true")
    modes.add_argument("--simulate-creator", action="store_true")
    modes.add_argument("--simulate-global", action="store_true")
    modes.add_argument("--simulate-feedback", action="store_true")
    modes.add_argument("--simulate-query", action="store_true")
    modes.add_argument("--simulate-export-import", action="store_true")
    modes.add_argument("--project-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.self_check:
            report = _self_check()
        elif args.simulate_project:
            report = _simulate_project()
        elif args.simulate_creator:
            report = _simulate_creator()
        elif args.simulate_global:
            report = _simulate_global()
        elif args.simulate_feedback:
            report = _simulate_feedback()
        elif args.simulate_query:
            report = _simulate_query()
        elif args.simulate_export_import:
            report = _simulate_export_import()
        else:
            report = asyncio.run(_existing_project(args.project_id))
    except Exception as exc:
        report = MemoryValidationReport(
            mode="validation_error",
            passed=False,
            project_id=getattr(args, "project_id", None),
            errors=[f"{type(exc).__name__}: {exc}"],
        )
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
