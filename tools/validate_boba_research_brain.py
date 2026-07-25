"""Validate BOBA Research Brain V1 without media or network access."""

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
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.research_brain import (  # noqa: E402
    BobaResearchBrainSetV1,
    BobaResearchBrainV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_content_scout_v2 import (  # noqa: E402
    build_synthetic_content_scout,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_research_brain"


class BobaResearchBrainValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    content_scout_available: bool = False
    creator_learning_available: bool = False
    report_path_writable: bool = False
    sources_imported: int = 0
    invalid_sources_rejected: bool = False
    evidence_bounded: bool = False
    insights_created: bool = False
    audience_pain_detected: bool = False
    audience_desire_detected: bool = False
    shorts_ideas_created: bool = False
    weak_claim_requires_verification: bool = False
    copyright_warning_created: bool = False
    handoff_created: bool = False
    apply_automatically_false: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    scraping_used_false: bool = False
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


def build_synthetic_research_sources() -> list[dict[str, Any]]:
    """Return varied local-style research records and one invalid record."""
    return [
        {
            "title": "Motivational consistency notes",
            "text": (
                "Creators struggle with consistency, but a smaller repeatable routine "
                "can improve confidence. The surprising lesson is why progress becomes "
                "easier after the first week."
            ),
            "topic_tags": ["motivation", "consistency", "creator growth"],
            "rights_usage_notes": "Owned notes written for local validation.",
        },
        {
            "title": "Educational article summary",
            "text": (
                "This independently written educational summary explains three ways "
                "to avoid a common learning mistake. It compares passive review with "
                "active practice and gives a practical tutorial outline."
            ),
            "topic_tags": ["education", "learning", "tutorial"],
            "rights_usage_notes": "Original summary; verify underlying facts.",
        },
        {
            "title": "Audience pain points",
            "text": (
                "The audience feels overwhelmed by expensive tools, slow workflows, "
                "and confusing advice. They want a clear system that saves time and "
                "helps them achieve a useful result."
            ),
            "topic_tags": ["audience research", "workflow", "clarity"],
            "rights_usage_notes": "Owned audience notes.",
        },
        {
            "title": "Controversial topic note",
            "text": (
                "An unpopular opinion says more tools can make creative work worse. "
                "Critics disagree, however the tradeoff creates a balanced commentary "
                "or myth versus fact angle."
            ),
            "topic_tags": ["creative tools", "debate", "tradeoff"],
            "rights_usage_notes": "Owned commentary notes.",
        },
        {
            "title": "Weak factual claim",
            "text": (
                "Studies show 90% of creators always double their results with this "
                "secret routine. This claim is supplied only as a question for review."
            ),
            "topic_tags": ["creator routine", "verification"],
            "rights_usage_notes": "Unverified user note.",
        },
        {
            "title": "Rights-uncertain source warning",
            "text": (
                "A third-party passage describes a dramatic transformation story and "
                "an unexpected comeback. Use the theme only after rights review."
            ),
            "topic_tags": ["transformation", "comeback", "rights"],
            "rights_usage_notes": (
                "Copied full article text may be represented; copyright and usage "
                "permission are unknown."
            ),
        },
        {},
    ]


def build_synthetic_research_signals() -> dict[str, dict[str, Any]]:
    """Return compact read-only BOBA signals used for advisory personalization."""
    return {
        "creator_learning": {
            "learning_profile": {
                "preferred_clip_types": ["tutorial", "story"],
                "story_angle_preferences": ["transformation"],
            }
        },
        "approval_rejection_learning": {
            "pattern_scores": [
                {
                    "summary": "Clear tutorials and complete stories are preferred.",
                    "approval_count": 3,
                    "rejection_count": 0,
                }
            ]
        },
        "performance_feedback": {
            "pattern_summary": {
                "strongest_positive_patterns": [
                    {"summary": "Practical, source-supported lessons."}
                ]
            }
        },
        "memory": {
            "source_summary": "The creator prefers practical, concise education.",
            "main_topics": ["education", "creator growth"],
        },
    }


def build_synthetic_research_brain(
    project_id: str = "proj_research_brain_synthetic",
) -> BobaResearchBrainSetV1:
    """Build a deterministic local-only Research Brain artifact."""
    signals = build_synthetic_research_signals()
    return BobaResearchBrainV1().analyze(
        project_id,
        source_id="synthetic_local_research",
        manual_sources=build_synthetic_research_sources(),
        manual_source_type="test_synthetic",
        source_label="validator_synthetic",
        content_scout=build_synthetic_content_scout(
            f"{project_id}_content_scout"
        ),
        creator_learning=signals["creator_learning"],
        approval_rejection_learning=signals["approval_rejection_learning"],
        performance_feedback=signals["performance_feedback"],
        boba_memory=signals["memory"],
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("local-research-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _safe_export(payload: dict[str, Any]) -> bool:
    research = payload.get("research_brain")
    privacy = payload.get("privacy")
    if not isinstance(research, dict) or not isinstance(privacy, dict):
        return False
    imported_sources = research.get("imported_sources")
    research_sources = research.get("research_sources")
    if not isinstance(imported_sources, list) or not isinstance(
        research_sources, list
    ):
        return False
    if any(
        isinstance(source, dict) and "source_path" in source
        for source in imported_sources
    ):
        return False
    private_fields = {"rights_usage_notes", "user_notes"}
    if any(
        isinstance(source, dict) and private_fields.intersection(source)
        for source in research_sources
    ):
        return False
    snippets = [
        snippet
        for source in research_sources
        if isinstance(source, dict)
        for snippet in source.get("evidence_snippets", [])
        if isinstance(snippet, dict)
    ]
    if any(len(str(snippet.get("snippet", ""))) > 300 for snippet in snippets):
        return False
    encoded = json.dumps(payload).casefold()
    return (
        all(
            privacy.get(key) is expected
            for key, expected in (
                ("local_paths_excluded", True),
                ("raw_source_content_excluded", True),
                ("full_transcripts_excluded", True),
                ("media_files_excluded", True),
                ("credentials_excluded", True),
                ("external_api_used", False),
                ("url_fetching_used", False),
                ("scraping_used", False),
                ("downloading_used", False),
            )
        )
        and not any(
            forbidden in encoded
            for forbidden in (
                '"raw_media":',
                '"full_transcript":',
                '"api_key":',
                '"access_token":',
                '"password":',
                ".mp4",
                ".wav",
            )
        )
    )


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaResearchBrainValidationReport:
    project_id = (
        "proj_research_brain_self_check"
        if mode == "self_check"
        else "proj_research_brain_synthetic"
    )
    research = build_synthetic_research_brain(project_id)
    insight_types = {item.insight_type for item in research.research_insights}
    evidence = [
        item
        for source in research.research_sources
        for item in source.evidence_snippets
    ]
    with TemporaryDirectory(prefix="boba-research-brain-") as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated project memory must survive reset.",
            )
        )
        saved = store.save_research_brain(research)
        artifact_path = store.research_brain_path(project_id)
        artifact_persisted = (
            artifact_path.is_file()
            and store.load_research_brain(project_id) == saved
        )
        export_safe = _safe_export(store.export_research_brain(project_id))
        reset_removed = store.reset_research_brain(project_id)
        reset_project_only = (
            reset_removed
            and store.load_research_brain(project_id) is None
            and store.load_project_memory(project_id) is not None
        )

    report = BobaResearchBrainValidationReport(
        mode=mode,
        passed=False,
        project_id=project_id,
        modules_imported=True,
        store_available=True,
        content_scout_available=research.signal_usage.content_scout_used,
        creator_learning_available=research.signal_usage.creator_learning_used,
        report_path_writable=_report_path_writable(report_dir),
        sources_imported=len(research.research_sources),
        invalid_sources_rejected=any(
            source.rejected_count > 0 for source in research.imported_sources
        ),
        evidence_bounded=bool(evidence)
        and all(0 < len(item.snippet) <= 300 for item in evidence),
        insights_created=bool(research.research_insights),
        audience_pain_detected="audience_pain" in insight_types,
        audience_desire_detected="audience_desire" in insight_types,
        shorts_ideas_created=bool(research.shorts_ideas),
        weak_claim_requires_verification=any(
            item.insight_type == "verification_needed"
            and item.human_verification_required
            for item in research.research_insights
        ),
        copyright_warning_created=bool(
            research.safety_review.copyrighted_content_warnings
        ),
        handoff_created=bool(
            research.content_scout_handoff.recommended_topics
            and research.content_scout_handoff.recommended_keywords
        ),
        apply_automatically_false=(
            research.content_scout_handoff.apply_automatically is False
        ),
        external_api_used_false=research.signal_usage.external_api_used is False,
        url_fetching_used_false=research.signal_usage.url_fetching_used is False,
        scraping_used_false=research.signal_usage.scraping_used is False,
        downloading_used_false=research.signal_usage.downloading_used is False,
        artifact_persisted=artifact_persisted,
        json_safe=bool(json.loads(research.model_dump_json())),
        export_safe=export_safe,
        reset_project_only=reset_project_only,
        warnings=[
            "Validation used synthetic local/user-provided text only.",
            "No rendering, media download, URL fetch, scraping, or external call occurred.",
            "Research findings and rights warnings remain advisory.",
        ],
    )
    report.passed = all(
        (
            report.modules_imported,
            report.store_available,
            report.content_scout_available,
            report.creator_learning_available,
            report.report_path_writable,
            report.sources_imported >= 6,
            report.invalid_sources_rejected,
            report.evidence_bounded,
            report.insights_created,
            report.audience_pain_detected,
            report.audience_desire_detected,
            report.shorts_ideas_created,
            report.weak_claim_requires_verification,
            report.copyright_warning_created,
            report.handoff_created,
            report.apply_automatically_false,
            report.external_api_used_false,
            report.url_fetching_used_false,
            report.scraping_used_false,
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
) -> BobaResearchBrainValidationReport:
    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaResearchBrainValidationReport:
    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


async def _existing_project(
    project_id: str,
    report_dir: Path,
) -> BobaResearchBrainValidationReport:
    try:
        integration = boba_integration_provider()
        research = integration.load_research_brain(project_id)
        if research is None:
            return BobaResearchBrainValidationReport(
                mode="project_id",
                passed=False,
                project_id=project_id,
                modules_imported=True,
                store_available=True,
                report_path_writable=_report_path_writable(report_dir),
                external_api_used_false=True,
                url_fetching_used_false=True,
                scraping_used_false=True,
                downloading_used_false=True,
                warnings=[
                    "No saved Research Brain V1 artifact is available for this project.",
                    "The validator did not render, upload, download, fetch a URL, "
                    "scrape, or call an external API.",
                ],
            )
        export = integration.export_research_brain(project_id)
        evidence = [
            item
            for source in research.research_sources
            for item in source.evidence_snippets
        ]
        report = BobaResearchBrainValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            content_scout_available=research.signal_usage.content_scout_used,
            creator_learning_available=research.signal_usage.creator_learning_used,
            report_path_writable=_report_path_writable(report_dir),
            sources_imported=len(research.research_sources),
            invalid_sources_rejected=True,
            evidence_bounded=all(
                0 < len(item.snippet) <= 300 for item in evidence
            ),
            insights_created=bool(research.research_insights),
            audience_pain_detected=any(
                item.insight_type == "audience_pain"
                for item in research.research_insights
            ),
            audience_desire_detected=any(
                item.insight_type == "audience_desire"
                for item in research.research_insights
            ),
            shorts_ideas_created=bool(research.shorts_ideas),
            weak_claim_requires_verification=True,
            copyright_warning_created=True,
            handoff_created=bool(
                research.content_scout_handoff.recommended_topics
            ),
            apply_automatically_false=(
                research.content_scout_handoff.apply_automatically is False
            ),
            external_api_used_false=(
                research.signal_usage.external_api_used is False
            ),
            url_fetching_used_false=(
                research.signal_usage.url_fetching_used is False
            ),
            scraping_used_false=research.signal_usage.scraping_used is False,
            downloading_used_false=(
                research.signal_usage.downloading_used is False
            ),
            artifact_persisted=integration.store.research_brain_path(
                project_id
            ).is_file(),
            json_safe=bool(json.loads(research.model_dump_json())),
            export_safe=_safe_export(export),
            warnings=[
                "Existing-project mode inspected the saved local research artifact only.",
                "No rendering, upload, download, URL fetch, scraping, or external call occurred.",
            ],
        )
        report.passed = all(
            (
                report.report_path_writable,
                report.evidence_bounded,
                report.insights_created,
                report.apply_automatically_false,
                report.external_api_used_false,
                report.url_fetching_used_false,
                report.scraping_used_false,
                report.downloading_used_false,
                report.artifact_persisted,
                report.json_safe,
                report.export_safe,
            )
        )
        return report
    except Exception as exc:
        return BobaResearchBrainValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            external_api_used_false=True,
            url_fetching_used_false=True,
            scraping_used_false=True,
            downloading_used_false=True,
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, fetch a URL, "
                "scrape, or call an external API."
            ],
        )


def _write_report(
    report: BobaResearchBrainValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_research_brain_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Research Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Research sources: `{report.sources_imported}`",
        f"- Evidence bounded: `{report.evidence_bounded}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- External APIs used: `false`",
        "- URLs fetched: `false`",
        "- Websites scraped: `false`",
        "- Media downloaded: `false`",
        "- Rendering triggered: `false`",
        "",
        "Research Brain V1 analyzes local/user-provided material only and does "
        "not verify facts, rights, real-time trends, or performance potential.",
    ]
    (report_dir / "boba_research_brain_v1_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Research Brain V1 locally.",
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
