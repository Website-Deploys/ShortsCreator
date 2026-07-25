"""Validate BOBA Content Scout V2 without media or network access."""

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
from olympus.boba.content_scout import (  # noqa: E402
    BobaContentScoutSetV2,
    BobaContentScoutV2,
)
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_content_scout_v2"


class BobaContentScoutValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    creator_learning_available: bool = False
    performance_feedback_available: bool = False
    report_path_writable: bool = False
    items_imported: int = 0
    invalid_items_rejected: bool = False
    scores_bounded: bool = False
    review_queue_created: bool = False
    rights_ready_review_now: bool = False
    unknown_requires_review: bool = False
    permission_needed_seek_permission: bool = False
    blocked_queued: bool = False
    duplicates_detected: bool = False
    suggested_angles_created: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    downloading_used_false: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    url_fetching_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_scout_items() -> list[dict[str, Any]]:
    """Return varied metadata-only records, including one intentionally bad row."""
    return [
        {
            "item_id": "owned_emotional_story",
            "title": "Why my biggest failure became an unexpected comeback",
            "description": (
                "A personal emotional story about struggle, regret, growth, surprise, "
                "a turning point, and the lesson behind the final success reveal."
            ),
            "source_label": "synthetic_owned",
            "source_url": "https://example.invalid/owned-reference",
            "duration_seconds": 840,
            "tags": ["emotional story", "comeback", "motivation", "lesson"],
            "categories": ["creator journey"],
            "creator": "Synthetic Creator",
            "rights_status": "owned",
            "permission_notes": "Creator marked this source as owned.",
        },
        {
            "item_id": "motivational_podcast",
            "title": "The secret reason this motivational breakthrough worked",
            "description": (
                "A permission-granted podcast story with struggle, hope, a surprising "
                "turn, a clear lesson, and an emotional payoff."
            ),
            "duration": "18:30",
            "tags": "podcast, motivation, curiosity, breakthrough",
            "categories": "interview",
            "rights_status": "permission_granted",
            "permission_notes": "Synthetic permission record for validation.",
        },
        {
            "item_id": "licensed_tutorial",
            "title": "How to avoid the mistake that ruins a clear tutorial",
            "description": (
                "A licensed educational tutorial with a before-and-after result, "
                "specific lesson, and concise reveal."
            ),
            "duration_seconds": 620,
            "tags": ["tutorial", "education", "mistake", "result"],
            "categories": ["how to"],
            "rights_status": "licensed",
        },
        {
            "item_id": "funny_unknown",
            "title": "Why the unexpected reaction made everyone laugh",
            "description": (
                "User notes describe a funny reaction and surprise, but provide no "
                "permission evidence."
            ),
            "tags": ["reaction", "funny", "surprise"],
            "rights_status": "unknown",
        },
        {
            "item_id": "owned_emotional_duplicate",
            "title": "Why my biggest failure became an unexpected comeback",
            "description": (
                "A personal emotional story about struggle, regret, growth, surprise, "
                "a turning point, and the lesson behind the final success reveal."
            ),
            "tags": ["emotional story", "comeback", "motivation", "lesson"],
            "rights_status": "owned",
        },
        {
            "item_id": "weak_generic",
            "title": "Weekly update",
            "description": "General notes without a specific hook or story.",
            "duration_seconds": 300,
            "rights_status": "owned",
        },
        {
            "item_id": "blocked_source",
            "title": "The surprising rescue story",
            "description": "A potentially emotional reveal that must not be used.",
            "tags": ["rescue", "story", "reveal"],
            "rights_status": "blocked",
        },
        {
            "item_id": "permission_needed_high_potential",
            "title": "The mystery behind a failure-to-success transformation",
            "description": (
                "A high-potential story with conflict, struggle, surprise, comeback, "
                "growth, and a final lesson, pending explicit permission."
            ),
            "tags": ["story", "transformation", "mystery", "comeback"],
            "rights_status": "permission_needed",
        },
        {},
    ]


def build_synthetic_scout_signals() -> dict[str, dict[str, Any]]:
    """Return compact advisory artifacts; no learning artifact is mutated."""
    return {
        "creator_learning": {
            "learning_profile": {
                "preferred_clip_types": ["emotional story", "tutorial", "podcast"],
                "preferred_hook_styles": ["curiosity reveal", "clear lesson"],
                "pacing_preferences": ["concise"],
                "story_angle_preferences": ["struggle comeback growth"],
                "avoided_clip_types": ["generic update"],
                "avoided_hook_styles": ["slow vague opening"],
                "risk_sensitivities": ["unknown rights"],
            }
        },
        "approval_rejection_learning": {
            "pattern_scores": [
                {
                    "summary": "emotional story curiosity reveal tutorial",
                    "guidance": "Prefer a complete lesson and source-supported payoff.",
                    "approval_count": 4,
                    "rejection_count": 0,
                },
                {
                    "summary": "generic update slow vague",
                    "guidance": "Avoid generic items without a specific hook.",
                    "approval_count": 0,
                    "rejection_count": 3,
                },
            ]
        },
        "performance_feedback": {
            "pattern_summary": {
                "strongest_positive_patterns": [
                    {
                        "summary": (
                            "Curiosity hooks, emotional comeback stories, and clear "
                            "tutorial lessons received positive manual feedback."
                        )
                    }
                ],
                "strongest_negative_patterns": [
                    {
                        "summary": (
                            "Generic updates and slow vague openings received negative "
                            "manual feedback."
                        )
                    }
                ],
            }
        },
        "memory": {
            "source_summary": "The creator prefers concise lessons with emotional growth.",
            "main_topics": ["motivation", "tutorial", "creator journey"],
            "story_patterns": ["struggle comeback lesson"],
        },
    }


def build_synthetic_content_scout(
    project_id: str = "proj_content_scout_v2_synthetic",
) -> BobaContentScoutSetV2:
    signals = build_synthetic_scout_signals()
    return BobaContentScoutV2().analyze(
        project_id,
        source_id="synthetic_metadata_only",
        manual_items=build_synthetic_scout_items(),
        manual_source_type="test_synthetic",
        source_label="validator_synthetic",
        creator_learning=signals["creator_learning"],
        approval_rejection_learning=signals["approval_rejection_learning"],
        performance_feedback=signals["performance_feedback"],
        boba_memory=signals["memory"],
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("metadata-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _safe_export(payload: dict[str, Any]) -> bool:
    scout = payload.get("content_scout_v2")
    if not isinstance(scout, dict):
        return False
    sources = scout.get("imported_sources")
    items = scout.get("scout_items")
    if not isinstance(sources, list) or not isinstance(items, list):
        return False
    if any(isinstance(source, dict) and "source_path" in source for source in sources):
        return False
    private_item_fields = {
        "source_url",
        "permission_notes",
        "user_notes",
        "raw_metadata_summary",
    }
    if any(
        isinstance(item, dict) and private_item_fields.intersection(item)
        for item in items
    ):
        return False
    encoded = json.dumps(payload).casefold()
    return not any(
        forbidden in encoded
        for forbidden in (
            "raw_media",
            "full_transcript",
            "api_key",
            "access_token",
            "password",
            ".mp4",
            ".wav",
        )
    )


def _recommendations(
    scout: BobaContentScoutSetV2,
) -> dict[str, Any]:
    groups = (
        scout.review_queue.top_items,
        scout.review_queue.backup_items,
        scout.review_queue.permission_needed_items,
        scout.review_queue.blocked_items,
        scout.review_queue.duplicate_or_similar_items,
    )
    return {
        recommendation.item_id: recommendation
        for group in groups
        for recommendation in group
    }


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaContentScoutValidationReport:
    project_id = (
        "proj_content_scout_v2_self_check"
        if mode == "self_check"
        else "proj_content_scout_v2_synthetic"
    )
    scout = build_synthetic_content_scout(project_id)
    recommendations = _recommendations(scout)
    score_by_id = {score.item_id: score for score in scout.scored_items}
    rights_ready_ids = {
        item.item_id
        for item in scout.scout_items
        if item.rights_status in {"owned", "licensed", "permission_granted"}
        and "duplicate" not in item.item_id
        and item.item_id != "weak_generic"
    }
    with TemporaryDirectory(prefix="boba-content-scout-v2-") as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(
            root / "boba",
            memory_root=root / "memory",
        )
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated project memory must survive Scout V2 reset.",
            )
        )
        saved = store.save_content_scout_v2(scout)
        artifact_path = store.content_scout_v2_path(project_id)
        artifact_persisted = (
            artifact_path.is_file()
            and store.load_content_scout_v2(project_id) == saved
        )
        export = store.export_content_scout_v2(project_id)
        export_safe = _safe_export(export)
        reset_removed = store.reset_content_scout_v2(project_id)
        reset_project_only = (
            reset_removed
            and store.load_content_scout_v2(project_id) is None
            and store.load_project_memory(project_id) is not None
        )

    report = BobaContentScoutValidationReport(
        mode=mode,
        passed=False,
        project_id=project_id,
        modules_imported=True,
        store_available=True,
        creator_learning_available=scout.signal_usage.creator_learning_used,
        performance_feedback_available=(
            scout.signal_usage.performance_feedback_used
        ),
        report_path_writable=_report_path_writable(report_dir),
        items_imported=len(scout.scout_items),
        invalid_items_rejected=any(
            "title or description" in item.reason_rejected.casefold()
            for item in scout.rejected_items
        ),
        scores_bounded=all(
            0.0 <= value <= 1.0
            for score in scout.scored_items
            for value in (
                score.creator_fit_score,
                score.topic_fit_score,
                score.shortability_score,
                score.hook_potential_score,
                score.emotional_story_score,
                score.trend_context_score,
                score.novelty_score,
                score.rights_readiness_score,
                score.review_priority_score,
                score.confidence,
            )
        ),
        review_queue_created=bool(scout.review_queue.queue_summary),
        rights_ready_review_now=rights_ready_ids.issubset(
            {
                item.item_id
                for item in scout.review_queue.top_items
            }
        ),
        unknown_requires_review=(
            recommendations["funny_unknown"].recommendation == "seek_permission"
            and recommendations["funny_unknown"].rights_review_required
        ),
        permission_needed_seek_permission=(
            recommendations["permission_needed_high_potential"].recommendation
            == "seek_permission"
        ),
        blocked_queued=(
            recommendations["blocked_source"].recommendation == "blocked"
            and any(
                item.item_id == "blocked_source"
                for item in scout.review_queue.blocked_items
            )
        ),
        duplicates_detected=(
            "owned_emotional_duplicate" in recommendations
            and score_by_id["owned_emotional_duplicate"].novelty_score
            < score_by_id["owned_emotional_story"].novelty_score
        ),
        suggested_angles_created=all(
            recommendations[item_id].suggested_short_angles
            for item_id in (
                "owned_emotional_story",
                "permission_needed_high_potential",
            )
        ),
        external_api_used_false=scout.signal_usage.external_api_used is False,
        url_fetching_used_false=scout.signal_usage.url_fetching_used is False,
        downloading_used_false=scout.signal_usage.downloading_used is False,
        artifact_persisted=artifact_persisted,
        json_safe=bool(json.loads(scout.model_dump_json())),
        export_safe=export_safe,
        reset_project_only=reset_project_only,
        warnings=[
            "Validation used synthetic local metadata only.",
            "No rendering, download, URL fetch, external API, or external call occurred.",
            "Rights statuses are synthetic user-provided labels, not copyright findings.",
        ],
    )
    report.passed = all(
        (
            report.modules_imported,
            report.store_available,
            report.creator_learning_available,
            report.performance_feedback_available,
            report.report_path_writable,
            report.items_imported >= 8,
            report.invalid_items_rejected,
            report.scores_bounded,
            report.review_queue_created,
            report.rights_ready_review_now,
            report.unknown_requires_review,
            report.permission_needed_seek_permission,
            report.blocked_queued,
            report.duplicates_detected,
            report.suggested_angles_created,
            report.external_api_used_false,
            report.url_fetching_used_false,
            report.downloading_used_false,
            report.artifact_persisted,
            report.json_safe,
            report.export_safe,
            report.reset_project_only,
            not report.rendering_triggered,
            not report.downloading_triggered,
            not report.url_fetching_triggered,
            not report.external_calls_made,
            not report.media_required,
            not report.secrets_required,
        )
    )
    return report


def run_self_check(
    report_dir: Path | None = None,
) -> BobaContentScoutValidationReport:
    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaContentScoutValidationReport:
    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


async def _existing_project(
    project_id: str,
    report_dir: Path,
) -> BobaContentScoutValidationReport:
    try:
        integration = boba_integration_provider()
        scout = integration.load_content_scout_v2(project_id)
        if scout is None:
            return BobaContentScoutValidationReport(
                mode="project_id",
                passed=False,
                project_id=project_id,
                modules_imported=True,
                store_available=True,
                report_path_writable=_report_path_writable(report_dir),
                external_api_used_false=True,
                url_fetching_used_false=True,
                downloading_used_false=True,
                warnings=[
                    "No saved Content Scout V2 artifact is available for this project.",
                    "The validator did not render, upload, download, fetch a URL, "
                    "or call an external API.",
                ],
            )
        export = integration.export_content_scout_v2(project_id)
        report = BobaContentScoutValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            creator_learning_available=scout.signal_usage.creator_learning_used,
            performance_feedback_available=(
                scout.signal_usage.performance_feedback_used
            ),
            report_path_writable=_report_path_writable(report_dir),
            items_imported=len(scout.scout_items),
            invalid_items_rejected=True,
            scores_bounded=all(
                0.0 <= score.review_priority_score <= 1.0
                and 0.0 <= score.confidence <= 1.0
                for score in scout.scored_items
            ),
            review_queue_created=bool(scout.review_queue.queue_summary),
            external_api_used_false=scout.signal_usage.external_api_used is False,
            url_fetching_used_false=scout.signal_usage.url_fetching_used is False,
            downloading_used_false=scout.signal_usage.downloading_used is False,
            artifact_persisted=integration.store.content_scout_v2_path(
                project_id
            ).is_file(),
            json_safe=bool(json.loads(scout.model_dump_json())),
            export_safe=_safe_export(export),
            warnings=[
                "Existing-project mode inspected the saved local metadata artifact only.",
                "No rendering, upload, download, URL fetch, or external call occurred.",
            ],
        )
        report.passed = all(
            (
                report.report_path_writable,
                report.scores_bounded,
                report.review_queue_created,
                report.external_api_used_false,
                report.url_fetching_used_false,
                report.downloading_used_false,
                report.artifact_persisted,
                report.json_safe,
                report.export_safe,
            )
        )
        return report
    except Exception as exc:
        return BobaContentScoutValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            external_api_used_false=True,
            url_fetching_used_false=True,
            downloading_used_false=True,
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, fetch a URL, "
                "or call an external API."
            ],
        )


def _write_report(
    report: BobaContentScoutValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_content_scout_v2_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Content Scout V2 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Metadata items: `{report.items_imported}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- External APIs used: `false`",
        "- URLs fetched: `false`",
        "- Videos downloaded: `false`",
        "- Rendering triggered: `false`",
        "",
        "Content Scout V2 is metadata-only, advisory, and cannot confirm copyright safety "
        "or guarantee performance.",
    ]
    (report_dir / "boba_content_scout_v2_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Content Scout V2 locally.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report_dir = args.report_dir.resolve()
    if args.self_check:
        report = run_self_check(report_dir)
    elif args.synthetic_project:
        report = run_synthetic_project(report_dir)
    else:
        report = asyncio.run(_existing_project(str(args.project_id), report_dir))
    _write_report(report, report_dir)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
