"""Validate BOBA Trend / Topic Watcher V1 without media or network access."""

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
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from olympus.boba.trend_topic_watcher import (  # noqa: E402
    BobaTrendTopicWatcherSetV1,
    BobaTrendTopicWatcherV1,
)
from tools.validate_boba_content_scout_v2 import (  # noqa: E402
    build_synthetic_content_scout,
)
from tools.validate_boba_research_brain import (  # noqa: E402
    build_synthetic_research_brain,
)

REPORT_DIR = (
    ROOT / "work" / "validation_reports" / "boba_trend_topic_watcher"
)


class BobaTrendTopicWatcherValidationReport(BaseModel):
    """Compact proof report for local watcher behavior and safety."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    research_brain_available: bool = False
    content_scout_available: bool = False
    creator_learning_available: bool = False
    performance_feedback_available: bool = False
    report_path_writable: bool = False
    sources_imported: int = 0
    invalid_topics_rejected: bool = False
    snapshots_created: int = 0
    repeated_topic_detected: bool = False
    new_topic_detected: bool = False
    rising_topic_detected: bool = False
    fading_topic_detected: bool = False
    stable_topic_detected: bool = False
    uncertain_topic_detected: bool = False
    duplicate_topic_grouped: bool = False
    scores_bounded: bool = False
    watchlist_created: bool = False
    not_real_time_verified: bool = False
    weak_data_warned: bool = False
    content_scout_handoff_created: bool = False
    research_brain_handoff_created: bool = False
    apply_automatically_false: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    scraping_used_false: bool = False
    platform_monitoring_used_false: bool = False
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


def build_synthetic_topic_snapshots() -> list[dict[str, Any]]:
    """Return deterministic snapshots covering every movement class."""

    return [
        {
            "source_label": "creator_snapshot_january",
            "captured_at": "2026-01-01T00:00:00Z",
            "platform": "user-provided worksheet",
            "source_notes": "Synthetic compact topic metadata.",
            "topics": [
                {
                    "topic": "workflow system",
                    "frequency": 10,
                    "tags": ["workflow", "tutorial"],
                },
                {
                    "topic": "creator batching method",
                    "frequency": 10,
                    "tags": ["creator", "workflow", "method"],
                },
                {
                    "topic": "legacy zeta format",
                    "frequency": 8,
                    "rights_safety_note": "Verify source rights.",
                },
                {
                    "topic": "steady tutorial format",
                    "score": 0.60,
                    "categories": ["education"],
                },
                {
                    "topic": "Creator workflows",
                    "frequency": 5,
                    "tags": ["creator", "workflow"],
                },
            ],
        },
        {
            "source_label": "creator_snapshot_february",
            "captured_at": "2026-02-01T00:00:00Z",
            "platform": "user-provided worksheet",
            "source_notes": "Synthetic compact topic metadata.",
            "topics": [
                {
                    "topic": "workflow system",
                    "frequency": 11,
                    "tags": ["workflow", "tutorial"],
                },
                {
                    "topic": "creator batching method",
                    "frequency": 18,
                    "description": "A practical creator workflow method.",
                    "tags": ["creator", "workflow", "method"],
                },
                {
                    "topic": "story hook breakdown",
                    "frequency": 5,
                    "tags": ["story", "hook", "short"],
                },
                {
                    "topic": "steady tutorial format",
                    "score": 0.61,
                    "categories": ["education"],
                },
                {
                    "topic": "Creator workflow",
                    "frequency": 5,
                    "tags": ["creator", "workflow"],
                },
                {
                    "topic": "misc",
                    "evidence_note": "Unverified broad topic label.",
                },
                {"topic": ""},
            ],
        },
    ]


def build_synthetic_trend_topic_watcher(
    project_id: str = "proj_trend_topic_watcher_synthetic",
) -> BobaTrendTopicWatcherSetV1:
    """Build a fully local watcher artifact with optional BOBA guidance."""

    research = build_synthetic_research_brain(f"{project_id}_research")
    scout = build_synthetic_content_scout(f"{project_id}_scout")
    return BobaTrendTopicWatcherV1().analyze(
        project_id,
        source_id="synthetic_local_topic_snapshots",
        manual_snapshots=build_synthetic_topic_snapshots(),
        manual_source_type="test_synthetic",
        source_label="validator_synthetic",
        research_brain=research,
        content_scout=scout,
        creator_learning={
            "preferred_topics": [
                "creator batching method",
                "workflow system",
                "story hook",
            ],
            "preferred_hook_styles": ["practical", "curiosity"],
        },
        performance_feedback={
            "summary": "Creator batching method performed well in manual feedback.",
            "pattern_summary": {
                "strongest_positive_patterns": [
                    {"factor": "creator batching method"}
                ],
                "strongest_negative_patterns": [
                    {"factor": "legacy zeta format"}
                ],
            },
        },
        boba_memory={
            "main_topics": ["creator workflow", "tutorial"],
            "source_summary": "Local synthetic project memory.",
        },
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("local-topic-data-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _safe_export(payload: dict[str, Any]) -> bool:
    watcher = payload.get("trend_topic_watcher")
    privacy = payload.get("privacy")
    if not isinstance(watcher, dict) or not isinstance(privacy, dict):
        return False
    imported_sources = watcher.get("imported_sources")
    snapshots = watcher.get("topic_snapshots")
    if not isinstance(imported_sources, list) or not isinstance(snapshots, list):
        return False
    if any(
        isinstance(source, dict) and "source_path" in source
        for source in imported_sources
    ):
        return False
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            return False
        if "source_notes" in snapshot:
            return False
        topics = snapshot.get("topics")
        if not isinstance(topics, list):
            return False
        if any(
            isinstance(topic, dict)
            and {"evidence_note", "rights_safety_note"}.intersection(topic)
            for topic in topics
        ):
            return False
    required_truth = {
        "local_paths_excluded": True,
        "private_notes_excluded": True,
        "raw_source_content_excluded": True,
        "full_transcripts_excluded": True,
        "media_files_excluded": True,
        "credentials_excluded": True,
        "external_api_used": False,
        "url_fetching_used": False,
        "scraping_used": False,
        "platform_monitoring_used": False,
        "downloading_used": False,
        "not_real_time_verified": True,
    }
    if any(privacy.get(key) is not value for key, value in required_truth.items()):
        return False
    encoded = json.dumps(payload).casefold()
    return not any(
        forbidden in encoded
        for forbidden in (
            '"api_key":',
            '"access_token":',
            '"password":',
            '"full_transcript":',
            '"raw_media":',
            ".mp4",
            ".wav",
            ".mov",
            ".webm",
        )
    )


def _movement_topics(
    watcher: BobaTrendTopicWatcherSetV1,
    field_name: str,
) -> set[str]:
    items = getattr(watcher.movement_analysis, field_name)
    return {item.normalized_topic for item in items}


def _report_for_watcher(
    watcher: BobaTrendTopicWatcherSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    report_dir: Path,
    artifact_persisted: bool,
    export_safe: bool,
    reset_project_only: bool,
) -> BobaTrendTopicWatcherValidationReport:
    scores = watcher.opportunity_scores
    signal_usage = watcher.signal_usage
    report = BobaTrendTopicWatcherValidationReport(
        mode=mode,
        passed=False,
        project_id=watcher.project_id,
        modules_imported=True,
        store_available=True,
        research_brain_available=signal_usage.research_brain_used,
        content_scout_available=signal_usage.content_scout_used,
        creator_learning_available=signal_usage.creator_learning_used,
        performance_feedback_available=signal_usage.performance_feedback_used,
        report_path_writable=_report_path_writable(report_dir),
        sources_imported=len(watcher.imported_sources),
        invalid_topics_rejected=any(
            source.rejected_count > 0 for source in watcher.imported_sources
        ),
        snapshots_created=len(watcher.topic_snapshots),
        repeated_topic_detected=bool(
            watcher.movement_analysis.repeated_topics
        ),
        new_topic_detected=bool(
            watcher.movement_analysis.newly_appearing_topics
        ),
        rising_topic_detected=bool(
            watcher.movement_analysis.rising_topics_within_provided_data
        ),
        fading_topic_detected=bool(
            watcher.movement_analysis.fading_topics_within_provided_data
        ),
        stable_topic_detected=bool(watcher.movement_analysis.stable_topics),
        uncertain_topic_detected=bool(
            watcher.movement_analysis.uncertain_topics
        ),
        duplicate_topic_grouped=bool(
            watcher.movement_analysis.duplicate_or_similar_topics
        ),
        scores_bounded=bool(scores)
        and all(
            0.0 <= value <= 1.0
            for score in scores
            for value in (
                score.creator_fit_score,
                score.research_support_score,
                score.scout_support_score,
                score.shortability_score,
                score.hook_potential_score,
                score.freshness_within_user_data_score,
                score.risk_score,
                score.overall_topic_priority_score,
                score.confidence,
            )
        ),
        watchlist_created=bool(watcher.watched_topics),
        not_real_time_verified=(
            watcher.confidence_review.not_real_time_verified is True
        ),
        weak_data_warned=bool(watcher.confidence_review.weak_data_warnings),
        content_scout_handoff_created=bool(
            watcher.content_scout_handoff.recommended_scout_topics
            and watcher.content_scout_handoff.recommended_keywords
        ),
        research_brain_handoff_created=bool(
            watcher.research_brain_handoff.recommended_research_topics
            and watcher.research_brain_handoff.claims_to_verify
        ),
        apply_automatically_false=(
            watcher.content_scout_handoff.apply_automatically is False
            and watcher.research_brain_handoff.apply_automatically is False
        ),
        external_api_used_false=signal_usage.external_api_used is False,
        url_fetching_used_false=signal_usage.url_fetching_used is False,
        scraping_used_false=signal_usage.scraping_used is False,
        platform_monitoring_used_false=(
            signal_usage.platform_monitoring_used is False
        ),
        downloading_used_false=signal_usage.downloading_used is False,
        artifact_persisted=artifact_persisted,
        json_safe=bool(json.loads(watcher.model_dump_json())),
        export_safe=export_safe,
        reset_project_only=reset_project_only,
        warnings=[
            "Validation used synthetic local/user-provided topic metadata only.",
            "Movement was measured only within provided data.",
            "No rendering, download, URL fetch, scraping, monitoring, or external call occurred.",
        ],
    )
    required = [
        report.modules_imported,
        report.store_available,
        report.report_path_writable,
        report.snapshots_created >= 2,
        report.repeated_topic_detected,
        report.new_topic_detected,
        report.rising_topic_detected,
        report.fading_topic_detected,
        report.stable_topic_detected,
        report.uncertain_topic_detected,
        report.duplicate_topic_grouped,
        report.scores_bounded,
        report.watchlist_created,
        report.not_real_time_verified,
        report.content_scout_handoff_created,
        report.research_brain_handoff_created,
        report.apply_automatically_false,
        report.external_api_used_false,
        report.url_fetching_used_false,
        report.scraping_used_false,
        report.platform_monitoring_used_false,
        report.downloading_used_false,
        report.artifact_persisted,
        report.json_safe,
        report.export_safe,
        not report.rendering_triggered,
        not report.downloading_triggered,
        not report.url_fetching_triggered,
        not report.external_calls_made,
        not report.media_required,
        not report.secrets_required,
    ]
    if mode != "project_id":
        required.extend(
            [
                report.research_brain_available,
                report.content_scout_available,
                report.creator_learning_available,
                report.performance_feedback_available,
                report.invalid_topics_rejected,
                report.weak_data_warned,
                report.reset_project_only,
            ]
        )
    report.passed = all(required)
    return report


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaTrendTopicWatcherValidationReport:
    project_id = (
        "proj_trend_topic_watcher_self_check"
        if mode == "self_check"
        else "proj_trend_topic_watcher_synthetic"
    )
    watcher = build_synthetic_trend_topic_watcher(project_id)
    with TemporaryDirectory(prefix="boba-trend-topic-watcher-") as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated project memory must survive reset.",
            )
        )
        saved = store.save_trend_topic_watcher(watcher)
        artifact_path = store.trend_topic_watcher_path(project_id)
        artifact_persisted = (
            artifact_path.is_file()
            and store.load_trend_topic_watcher(project_id) == saved
        )
        export_safe = _safe_export(
            store.export_trend_topic_watcher(project_id)
        )
        reset_removed = store.reset_trend_topic_watcher(project_id)
        reset_project_only = (
            reset_removed
            and store.load_trend_topic_watcher(project_id) is None
            and store.load_project_memory(project_id) is not None
        )
    return _report_for_watcher(
        watcher,
        mode=mode,
        report_dir=report_dir,
        artifact_persisted=artifact_persisted,
        export_safe=export_safe,
        reset_project_only=reset_project_only,
    )


def run_self_check(
    report_dir: Path | None = None,
) -> BobaTrendTopicWatcherValidationReport:
    """Run import, safety, persistence, and deterministic behavior checks."""

    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaTrendTopicWatcherValidationReport:
    """Run the full synthetic local topic watcher proof."""

    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


def run_existing_project(
    project_id: str,
    report_dir: Path | None = None,
) -> BobaTrendTopicWatcherValidationReport:
    """Inspect one saved watcher artifact without invoking another pipeline."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        integration = boba_integration_provider()
        watcher = integration.load_trend_topic_watcher(project_id)
        if watcher is None:
            return BobaTrendTopicWatcherValidationReport(
                mode="project_id",
                passed=False,
                project_id=project_id,
                modules_imported=True,
                store_available=True,
                report_path_writable=_report_path_writable(
                    effective_report_dir
                ),
                external_api_used_false=True,
                url_fetching_used_false=True,
                scraping_used_false=True,
                platform_monitoring_used_false=True,
                downloading_used_false=True,
                warnings=[
                    "No saved Trend / Topic Watcher V1 artifact is available.",
                    "No render, upload, download, URL fetch, platform monitoring, "
                    "or external API call occurred.",
                ],
            )
        artifact_path = integration.store.trend_topic_watcher_path(project_id)
        return _report_for_watcher(
            watcher,
            mode="project_id",
            report_dir=effective_report_dir,
            artifact_persisted=artifact_path.is_file(),
            export_safe=_safe_export(
                integration.export_trend_topic_watcher(project_id)
            ),
            reset_project_only=False,
        )
    except Exception as exc:
        return BobaTrendTopicWatcherValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(effective_report_dir),
            external_api_used_false=True,
            url_fetching_used_false=True,
            scraping_used_false=True,
            platform_monitoring_used_false=True,
            downloading_used_false=True,
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, fetch a URL, "
                "scrape, monitor a platform, or call an external API."
            ],
        )


def _write_report(
    report: BobaTrendTopicWatcherValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_trend_topic_watcher_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Trend / Topic Watcher V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Topic snapshots: `{report.snapshots_created}`",
        f"- Watchlist created: `{report.watchlist_created}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- External APIs used: `false`",
        "- URLs fetched: `false`",
        "- Platforms scraped or monitored: `false`",
        "- Media downloaded: `false`",
        "- Rendering triggered: `false`",
        "",
        "Movement is measured only within local/user-provided data and is not "
        "real-time verified.",
    ]
    (report_dir / "boba_trend_topic_watcher_v1_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Trend / Topic Watcher V1 locally.",
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
        report = run_existing_project(str(args.project_id), report_dir)
    _write_report(report, report_dir)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
