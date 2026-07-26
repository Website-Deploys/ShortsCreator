"""Validate BOBA Candidate Video Scorer V1 without media or network access."""

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
from olympus.boba.candidate_video_scorer import (  # noqa: E402
    BobaCandidateVideoScorerSetV1,
    BobaCandidateVideoScorerV1,
    BobaScoredCandidateVideoV1,
)
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_content_scout_v2 import (  # noqa: E402
    build_synthetic_content_scout,
)
from tools.validate_boba_research_brain import (  # noqa: E402
    build_synthetic_research_brain,
)
from tools.validate_boba_trend_topic_watcher import (  # noqa: E402
    build_synthetic_trend_topic_watcher,
)

REPORT_DIR = (
    ROOT / "work" / "validation_reports" / "boba_candidate_video_scorer"
)


class BobaCandidateVideoScorerValidationReport(BaseModel):
    """Compact local proof for candidate scoring behavior and safety."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    content_scout_available: bool = False
    research_brain_available: bool = False
    trend_topic_watcher_available: bool = False
    creator_learning_available: bool = False
    approval_rejection_learning_available: bool = False
    performance_feedback_available: bool = False
    memory_available: bool = False
    report_path_writable: bool = False
    sources_imported: int = 0
    candidates_imported: int = 0
    invalid_candidates_rejected: bool = False
    scores_bounded: bool = False
    shorts_reviews_created: bool = False
    rights_reviews_created: bool = False
    owned_review_now: bool = False
    licensed_review_now: bool = False
    permission_granted_review_now: bool = False
    permission_needed_seek_permission: bool = False
    unknown_rights_review_required: bool = False
    blocked_candidate_queued: bool = False
    duplicate_candidate_handled: bool = False
    review_queue_created: bool = False
    source_handoffs_created: bool = False
    apply_automatically_false: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    scraping_used_false: bool = False
    downloading_used_false: bool = False
    media_ingestion_used_false: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    url_fetching_triggered: bool = False
    external_calls_made: bool = False
    media_ingestion_triggered: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_candidate_metadata() -> list[dict[str, Any]]:
    """Return deterministic local metadata covering every rights queue."""

    return [
        {
            "candidate_video_id": "candidate_owned_story",
            "title": "Why creator workflow failure became a comeback reveal",
            "description": (
                "An emotional story about a problem, struggle, tension, turn, "
                "result, payoff, lesson, and transformation."
            ),
            "source_label": "creator_library",
            "source_reference": "owned-story-001",
            "source_url": "https://example.test/metadata-only/owned-story",
            "duration_seconds": 1_200,
            "creator": "Local Creator",
            "published_at": "2026-01-10",
            "tags": [
                "creator workflow",
                "story hook",
                "comeback",
                "reveal",
            ],
            "categories": ["story", "commentary"],
            "rights_status": "owned",
            "permission_notes": "Creator states this source is owned.",
            "notes": "Review the full source manually.",
        },
        {
            "candidate_video_id": "candidate_permission_granted_podcast",
            "title": "The surprising creator batching mistake and result",
            "description": (
                "A motivational podcast interview with conflict, breakthrough, "
                "turn, payoff, and a practical lesson."
            ),
            "source_label": "permission_log",
            "source_reference": "podcast-014",
            "duration": "00:22:00",
            "channel": "Partner Podcast",
            "tags": ["creator batching method", "podcast", "motivation"],
            "categories": ["interview", "story"],
            "rights_status": "permission_granted",
            "permission_notes": "User recorded explicit clipping permission.",
        },
        {
            "candidate_video_id": "candidate_licensed_tutorial",
            "title": "How this workflow mistake reveals a better result",
            "description": (
                "An educational tutorial comparison with a problem, list, "
                "lesson, transformation, and final payoff."
            ),
            "source_label": "licensed_library",
            "source_reference": "tutorial-021",
            "duration_seconds": 840,
            "creator_or_channel": "Licensed Educator",
            "tags": ["workflow system", "tutorial", "story hook"],
            "categories": ["education", "comparison"],
            "rights_status": "licensed",
            "permission_notes": "User supplied a license record for review.",
        },
        {
            "candidate_video_id": "candidate_unknown_rights",
            "title": "The mystery behind a creator workflow breakthrough",
            "description": (
                "A high-potential story reveal with tension, turn, result, and "
                "an emotional lesson."
            ),
            "source_label": "research_notes",
            "source_reference": "unknown-007",
            "duration_seconds": 1_050,
            "tags": ["creator workflow", "breakthrough", "story"],
            "categories": ["commentary"],
            "rights_status": "unknown",
        },
        {
            "candidate_video_id": "candidate_permission_needed",
            "title": "Why this podcast failure became a surprising lesson",
            "description": (
                "An interview story with struggle, conflict, result, reveal, "
                "payoff, and motivation."
            ),
            "source_label": "permission_backlog",
            "source_reference": "permission-needed-009",
            "duration_seconds": 1_400,
            "tags": ["podcast", "story hook", "motivation"],
            "categories": ["interview", "story"],
            "rights_status": "permission_needed",
            "permission_notes": "Contact the source owner before any ingestion.",
        },
        {
            "candidate_video_id": "candidate_blocked",
            "title": "Blocked private source story",
            "description": (
                "Metadata mentions a story reveal, but the user marked this "
                "source blocked."
            ),
            "source_label": "blocked_register",
            "source_reference": "blocked-003",
            "duration_seconds": 600,
            "tags": ["story", "reveal"],
            "rights_status": "blocked",
            "permission_notes": "Do not use.",
        },
        {
            "candidate_video_id": "candidate_owned_story_duplicate",
            "title": "Why creator workflow failure became a comeback reveal",
            "description": (
                "Similar metadata for the same emotional problem, turn, payoff, "
                "lesson, and transformation."
            ),
            "source_label": "duplicate_sheet",
            "source_reference": "owned-story-duplicate",
            "duration_seconds": 1_205,
            "tags": ["creator workflow", "story hook", "comeback"],
            "categories": ["story"],
            "rights_status": "owned",
        },
        {
            "candidate_video_id": "candidate_weak_generic",
            "title": "Video",
            "description": "Misc generic content.",
            "source_label": "weak_metadata",
            "rights_status": "owned",
        },
        {},
    ]


def build_synthetic_candidate_video_scorer(
    project_id: str = "proj_candidate_video_scorer_synthetic",
) -> BobaCandidateVideoScorerSetV1:
    """Build a fully local scorer artifact with saved-BOBA-style guidance."""

    content_scout = build_synthetic_content_scout(f"{project_id}_scout")
    research_brain = build_synthetic_research_brain(f"{project_id}_research")
    trend_watcher = build_synthetic_trend_topic_watcher(f"{project_id}_trend")
    return BobaCandidateVideoScorerV1().analyze(
        project_id,
        source_id="synthetic_local_candidate_metadata",
        manual_candidates=build_synthetic_candidate_metadata(),
        manual_source_type="test_synthetic",
        source_label="validator_synthetic",
        content_scout=content_scout,
        research_brain=research_brain,
        trend_topic_watcher=trend_watcher,
        creator_learning={
            "preferred_clip_types": [
                "story",
                "tutorial",
                "podcast",
                "interview",
            ],
            "preferred_hook_styles": [
                "curiosity",
                "mistake",
                "reveal",
            ],
            "story_angle_preferences": [
                "creator workflow",
                "comeback",
                "transformation",
            ],
            "summary": "Creator prefers practical stories and workflow lessons.",
        },
        approval_rejection_learning={
            "pattern_scores": [
                {
                    "summary": "Creator workflow story reveal",
                    "guidance": "Prefer comeback lesson hooks.",
                    "approval_count": 4,
                    "rejection_count": 0,
                },
                {
                    "summary": "Misc generic content",
                    "guidance": "Avoid vague generic videos.",
                    "approval_count": 0,
                    "rejection_count": 3,
                },
            ]
        },
        performance_feedback={
            "pattern_summary": {
                "strongest_positive_patterns": [
                    {"factor": "creator workflow comeback story"},
                    {"factor": "educational tutorial lesson"},
                ],
                "strongest_negative_patterns": [
                    {"factor": "misc generic content"}
                ],
                "repeated_winners": ["story hook reveal"],
                "repeated_failures": ["vague video"],
            }
        },
        boba_memory={
            "main_topics": [
                "creator workflow",
                "story hooks",
                "educational tutorial",
            ],
            "source_summary": "Synthetic compact project memory.",
        },
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("local-candidate-metadata-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _safe_export(payload: dict[str, Any]) -> bool:
    scorer = payload.get("candidate_video_scorer")
    privacy = payload.get("privacy")
    if not isinstance(scorer, dict) or not isinstance(privacy, dict):
        return False
    sources = scorer.get("imported_sources")
    candidates = scorer.get("candidate_videos")
    scored = scorer.get("scored_candidates")
    if not isinstance(sources, list) or not isinstance(candidates, list):
        return False
    if not isinstance(scored, list):
        return False
    if any(
        isinstance(source, dict) and "source_path" in source
        for source in sources
    ):
        return False
    private_fields = {
        "source_url",
        "permission_notes",
        "user_notes",
        "raw_metadata_summary",
    }
    if any(
        isinstance(candidate, dict) and private_fields.intersection(candidate)
        for candidate in candidates
    ):
        return False
    for item in scored:
        if not isinstance(item, dict):
            return False
        candidate = item.get("candidate_video")
        if isinstance(candidate, dict) and private_fields.intersection(candidate):
            return False
    required_truth = {
        "local_paths_excluded": True,
        "source_urls_excluded": True,
        "private_notes_excluded": True,
        "raw_metadata_excluded": True,
        "raw_source_content_excluded": True,
        "full_transcripts_excluded": True,
        "media_files_excluded": True,
        "credentials_excluded": True,
        "external_api_used": False,
        "url_fetching_used": False,
        "scraping_used": False,
        "downloading_used": False,
        "media_ingestion_used": False,
        "copyright_safety_confirmed": False,
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


def _candidate(
    scorer: BobaCandidateVideoScorerSetV1,
    candidate_video_id: str,
) -> BobaScoredCandidateVideoV1:
    return next(
        item
        for item in scorer.scored_candidates
        if item.candidate_video.candidate_video_id == candidate_video_id
    )


def _report_for_scorer(
    scorer: BobaCandidateVideoScorerSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    report_dir: Path,
    artifact_persisted: bool,
    export_safe: bool,
    reset_project_only: bool,
) -> BobaCandidateVideoScorerValidationReport:
    signal_usage = scorer.signal_usage
    manual_ids = {
        item.candidate_video.candidate_video_id
        for item in scorer.scored_candidates
    }
    scores_bounded = bool(scorer.scored_candidates) and all(
        0.0 <= value <= 1.0
        for item in scorer.scored_candidates
        for value in (
            item.score.creator_fit_score,
            item.score.topic_opportunity_score,
            item.score.research_support_score,
            item.score.trend_support_score,
            item.score.shortability_score,
            item.score.hook_potential_score,
            item.score.story_potential_score,
            item.score.format_fit_score,
            item.score.rights_readiness_score,
            item.score.risk_score,
            item.score.review_priority_score,
            item.score.overall_candidate_score,
            item.score.confidence,
        )
    )
    expected_manual = {
        "candidate_owned_story",
        "candidate_permission_granted_podcast",
        "candidate_licensed_tutorial",
        "candidate_unknown_rights",
        "candidate_permission_needed",
        "candidate_blocked",
        "candidate_owned_story_duplicate",
        "candidate_weak_generic",
    }
    has_synthetic_cases = expected_manual.issubset(manual_ids)
    owned = (
        _candidate(scorer, "candidate_owned_story")
        if "candidate_owned_story" in manual_ids
        else None
    )
    licensed = (
        _candidate(scorer, "candidate_licensed_tutorial")
        if "candidate_licensed_tutorial" in manual_ids
        else None
    )
    granted = (
        _candidate(scorer, "candidate_permission_granted_podcast")
        if "candidate_permission_granted_podcast" in manual_ids
        else None
    )
    permission = (
        _candidate(scorer, "candidate_permission_needed")
        if "candidate_permission_needed" in manual_ids
        else None
    )
    unknown = (
        _candidate(scorer, "candidate_unknown_rights")
        if "candidate_unknown_rights" in manual_ids
        else None
    )
    duplicate = (
        _candidate(scorer, "candidate_owned_story_duplicate")
        if "candidate_owned_story_duplicate" in manual_ids
        else None
    )
    queue = scorer.review_queue
    report = BobaCandidateVideoScorerValidationReport(
        mode=mode,
        passed=False,
        project_id=scorer.project_id,
        modules_imported=True,
        store_available=True,
        content_scout_available=signal_usage.content_scout_used,
        research_brain_available=signal_usage.research_brain_used,
        trend_topic_watcher_available=signal_usage.trend_topic_watcher_used,
        creator_learning_available=signal_usage.creator_learning_used,
        approval_rejection_learning_available=(
            signal_usage.approval_rejection_learning_used
        ),
        performance_feedback_available=(
            signal_usage.performance_feedback_used
        ),
        memory_available=signal_usage.memory_used,
        report_path_writable=_report_path_writable(report_dir),
        sources_imported=len(scorer.imported_sources),
        candidates_imported=len(scorer.candidate_videos),
        invalid_candidates_rejected=any(
            source.rejected_count > 0 for source in scorer.imported_sources
        ),
        scores_bounded=scores_bounded,
        shorts_reviews_created=all(
            item.shorts_potential.human_review_questions
            and item.shorts_potential.emotional_story_promise
            for item in scorer.scored_candidates
        ),
        rights_reviews_created=all(
            item.rights_review.reason
            and item.rights_review.human_review_notes
            for item in scorer.scored_candidates
        ),
        owned_review_now=(
            owned is not None
            and owned.recommendation.recommendation == "review_now"
        ),
        licensed_review_now=(
            licensed is not None
            and licensed.recommendation.recommendation == "review_now"
        ),
        permission_granted_review_now=(
            granted is not None
            and granted.recommendation.recommendation == "review_now"
        ),
        permission_needed_seek_permission=(
            permission is not None
            and permission.recommendation.recommendation == "seek_permission"
            and permission.rights_review.permission_required
        ),
        unknown_rights_review_required=(
            unknown is not None
            and unknown.rights_review.rights_status == "unknown"
            and unknown.rights_review.rights_review_required
            and unknown.rights_review.rights_readiness
            == "unknown_needs_review"
        ),
        blocked_candidate_queued=any(
            item.candidate_video_id == "candidate_blocked"
            for item in queue.blocked_candidates
        ),
        duplicate_candidate_handled=(
            duplicate is not None
            and duplicate.duplicate_of_candidate_video_id is not None
            and any(
                item.candidate_video_id
                == "candidate_owned_story_duplicate"
                for item in queue.duplicate_or_similar_candidates
            )
        ),
        review_queue_created=bool(
            queue.top_candidates
            and queue.permission_needed_candidates
            and queue.blocked_candidates
            and queue.rejected_candidates
        ),
        source_handoffs_created=all(
            handoff.recommended_actions
            for handoff in (
                scorer.source_handoffs.content_scout_handoff,
                scorer.source_handoffs.research_brain_handoff,
                scorer.source_handoffs.trend_topic_handoff,
                scorer.source_handoffs.rights_permission_gate_handoff,
                scorer.source_handoffs.future_ingestion_handoff,
            )
        ),
        apply_automatically_false=(
            scorer.source_handoffs.apply_automatically is False
            and all(
                handoff.apply_automatically is False
                for handoff in (
                    scorer.source_handoffs.content_scout_handoff,
                    scorer.source_handoffs.research_brain_handoff,
                    scorer.source_handoffs.trend_topic_handoff,
                    scorer.source_handoffs.rights_permission_gate_handoff,
                    scorer.source_handoffs.future_ingestion_handoff,
                )
            )
        ),
        external_api_used_false=signal_usage.external_api_used is False,
        url_fetching_used_false=signal_usage.url_fetching_used is False,
        scraping_used_false=signal_usage.scraping_used is False,
        downloading_used_false=signal_usage.downloading_used is False,
        media_ingestion_used_false=signal_usage.media_ingestion_used is False,
        artifact_persisted=artifact_persisted,
        json_safe=bool(json.loads(scorer.model_dump_json())),
        export_safe=export_safe,
        reset_project_only=reset_project_only,
        warnings=[
            "Validation used synthetic local/user-provided candidate metadata only.",
            "No rendering, downloading, URL fetching, external call, or media ingestion occurred.",
            "Rights states were user-provided and do not confirm copyright safety.",
        ],
    )
    required = [
        report.modules_imported,
        report.store_available,
        report.report_path_writable,
        report.candidates_imported > 0,
        report.scores_bounded,
        report.shorts_reviews_created,
        report.rights_reviews_created,
        report.review_queue_created,
        report.source_handoffs_created,
        report.apply_automatically_false,
        report.external_api_used_false,
        report.url_fetching_used_false,
        report.scraping_used_false,
        report.downloading_used_false,
        report.media_ingestion_used_false,
        report.artifact_persisted,
        report.json_safe,
        report.export_safe,
        not report.rendering_triggered,
        not report.downloading_triggered,
        not report.url_fetching_triggered,
        not report.external_calls_made,
        not report.media_ingestion_triggered,
        not report.media_required,
        not report.secrets_required,
    ]
    if mode != "project_id":
        required.extend(
            [
                has_synthetic_cases,
                report.content_scout_available,
                report.research_brain_available,
                report.trend_topic_watcher_available,
                report.creator_learning_available,
                report.approval_rejection_learning_available,
                report.performance_feedback_available,
                report.memory_available,
                report.invalid_candidates_rejected,
                report.owned_review_now,
                report.licensed_review_now,
                report.permission_granted_review_now,
                report.permission_needed_seek_permission,
                report.unknown_rights_review_required,
                report.blocked_candidate_queued,
                report.duplicate_candidate_handled,
                report.reset_project_only,
            ]
        )
    report.passed = all(required)
    return report


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaCandidateVideoScorerValidationReport:
    project_id = (
        "proj_candidate_video_scorer_self_check"
        if mode == "self_check"
        else "proj_candidate_video_scorer_synthetic"
    )
    scorer = build_synthetic_candidate_video_scorer(project_id)
    with TemporaryDirectory(prefix="boba-candidate-video-scorer-") as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated project memory must survive reset.",
            )
        )
        saved = store.save_candidate_video_scorer(scorer)
        artifact_path = store.candidate_video_scorer_path(project_id)
        artifact_persisted = (
            artifact_path.is_file()
            and store.load_candidate_video_scorer(project_id) == saved
        )
        export_safe = _safe_export(
            store.export_candidate_video_scorer(project_id)
        )
        reset_removed = store.reset_candidate_video_scorer(project_id)
        reset_project_only = (
            reset_removed
            and store.load_candidate_video_scorer(project_id) is None
            and store.load_project_memory(project_id) is not None
        )
    return _report_for_scorer(
        scorer,
        mode=mode,
        report_dir=report_dir,
        artifact_persisted=artifact_persisted,
        export_safe=export_safe,
        reset_project_only=reset_project_only,
    )


def run_self_check(
    report_dir: Path | None = None,
) -> BobaCandidateVideoScorerValidationReport:
    """Run import, safety, persistence, and deterministic behavior checks."""

    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaCandidateVideoScorerValidationReport:
    """Run the full synthetic candidate source scoring proof."""

    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


def run_existing_project(
    project_id: str,
    report_dir: Path | None = None,
) -> BobaCandidateVideoScorerValidationReport:
    """Inspect one saved scorer artifact without invoking another pipeline."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        integration = boba_integration_provider()
        scorer = integration.load_candidate_video_scorer(project_id)
        if scorer is None:
            return BobaCandidateVideoScorerValidationReport(
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
                downloading_used_false=True,
                media_ingestion_used_false=True,
                warnings=[
                    "No saved Candidate Video Scorer V1 artifact is available.",
                    "No render, upload, download, URL fetch, external API call, "
                    "or media ingestion occurred.",
                ],
            )
        artifact_path = integration.store.candidate_video_scorer_path(
            project_id
        )
        return _report_for_scorer(
            scorer,
            mode="project_id",
            report_dir=effective_report_dir,
            artifact_persisted=artifact_path.is_file(),
            export_safe=_safe_export(
                integration.export_candidate_video_scorer(project_id)
            ),
            reset_project_only=False,
        )
    except Exception as exc:
        return BobaCandidateVideoScorerValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(effective_report_dir),
            external_api_used_false=True,
            url_fetching_used_false=True,
            scraping_used_false=True,
            downloading_used_false=True,
            media_ingestion_used_false=True,
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, fetch a URL, "
                "call an external API, or ingest media."
            ],
        )


def _write_report(
    report: BobaCandidateVideoScorerValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_candidate_video_scorer_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Candidate Video Scorer V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Candidate records: `{report.candidates_imported}`",
        f"- Scores bounded: `{report.scores_bounded}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- External APIs used: `false`",
        "- URLs fetched: `false`",
        "- Platforms scraped: `false`",
        "- Media downloaded or ingested: `false`",
        "- Rendering triggered: `false`",
        "",
        "Rights states are user-provided and do not confirm copyright safety.",
    ]
    (report_dir / "boba_candidate_video_scorer_v1_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Candidate Video Scorer V1 locally.",
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
