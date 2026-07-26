"""Validate BOBA Rights + Permission Gate V1 without media or network access."""

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
from olympus.boba.rights_permission_gate import (  # noqa: E402
    BobaRightsGateDecisionV1,
    BobaRightsPermissionGateSetV1,
    BobaRightsPermissionGateV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_candidate_video_scorer import (  # noqa: E402
    build_synthetic_candidate_video_scorer,
)
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
    ROOT / "work" / "validation_reports" / "boba_rights_permission_gate"
)


class BobaRightsPermissionGateValidationReport(BaseModel):
    """Compact local proof for advisory rights review and safety behavior."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    candidate_video_scorer_available: bool = False
    content_scout_available: bool = False
    research_brain_available: bool = False
    trend_topic_watcher_available: bool = False
    clip_briefs_available: bool = False
    music_mood_available: bool = False
    memory_available: bool = False
    report_path_writable: bool = False
    reviewed_items_created: bool = False
    gate_decisions_created: bool = False
    permission_checklists_created: bool = False
    risk_reviews_created: bool = False
    future_ingestion_handoffs_created: bool = False
    invalid_items_rejected: bool = False
    owned_ready_with_note: bool = False
    licensed_ready_with_note: bool = False
    permission_granted_ready_with_note: bool = False
    permission_needed_blocked: bool = False
    unknown_requires_review: bool = False
    blocked_item_blocked: bool = False
    public_domain_claim_requires_review: bool = False
    fair_use_claim_requires_review: bool = False
    conflicting_notes_require_review: bool = False
    missing_source_insufficient: bool = False
    unknown_never_safe: bool = False
    final_human_approval_required: bool = False
    apply_automatically_false: bool = False
    legal_validation_used_false: bool = False
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


def build_synthetic_rights_items() -> list[dict[str, Any]]:
    """Return deterministic user-provided metadata for every V1 gate state."""

    return [
        {
            "review_item_id": "rights_owned",
            "candidate_video_id": "rights_owned",
            "title": "Creator-owned interview with guest faces",
            "source_label": "creator_library",
            "source_reference": "OWN-001",
            "rights_status": "owned",
            "ownership_notes": (
                "Creator declares ownership; compact project note OWN-001 "
                "requires final human confirmation."
            ),
            "platform_source_notes": (
                "Review guest consent and release needs before processing."
            ),
        },
        {
            "review_item_id": "rights_licensed",
            "candidate_video_id": "rights_licensed",
            "title": "Licensed tutorial source",
            "source_label": "licensed_library",
            "source_reference": "LIC-002",
            "rights_status": "licensed",
            "license_notes": (
                "User supplied compact license reference LIC-002 for human "
                "scope and validity review."
            ),
        },
        {
            "review_item_id": "rights_permission_granted",
            "candidate_video_id": "rights_permission_granted",
            "title": "Partner podcast with declared clipping permission",
            "source_label": "permission_log",
            "source_reference": "PERM-003",
            "rights_status": "permission_granted",
            "permission_notes": (
                "User recorded permission reference PERM-003; a human must "
                "review scope before processing."
            ),
        },
        {
            "review_item_id": "rights_permission_needed",
            "candidate_video_id": "rights_permission_needed",
            "title": "Promising interview awaiting permission",
            "source_label": "permission_backlog",
            "source_reference": "PERM-004",
            "rights_status": "permission_needed",
            "permission_notes": (
                "Seek and record permission before any future review."
            ),
        },
        {
            "review_item_id": "rights_unknown",
            "candidate_video_id": "rights_unknown",
            "title": "Unknown-rights research candidate",
            "source_label": "research_notes",
            "source_reference": "UNK-005",
            "rights_status": "unknown",
        },
        {
            "review_item_id": "rights_blocked",
            "candidate_video_id": "rights_blocked",
            "title": "Explicitly blocked source",
            "source_label": "blocked_register",
            "source_reference": "BLOCK-006",
            "rights_status": "blocked",
            "permission_notes": "Do not process; permission denied.",
        },
        {
            "review_item_id": "rights_public_domain_claimed",
            "candidate_video_id": "rights_public_domain_claimed",
            "title": "Public-domain claim needing review",
            "source_label": "archive_notes",
            "source_reference": "PD-007",
            "rights_status": "public_domain_claimed",
            "license_notes": (
                "User claims public-domain status under note PD-007; no legal "
                "validation was performed."
            ),
        },
        {
            "review_item_id": "rights_fair_use_claimed",
            "candidate_video_id": "rights_fair_use_claimed",
            "title": "Fair-use claim needing review",
            "source_label": "commentary_notes",
            "source_reference": "FU-008",
            "rights_status": "fair_use_claimed",
            "platform_source_notes": (
                "User claims commentary context under note FU-008; BOBA does "
                "not determine fair use."
            ),
        },
        {
            "review_item_id": "rights_conflicting",
            "candidate_video_id": "rights_conflicting",
            "title": "Conflicting ownership notes",
            "source_label": "manual_conflict",
            "source_reference": "CONFLICT-009",
            "rights_status": "owned",
            "ownership_notes": "Creator declares this source owned.",
            "platform_source_notes": (
                "Rights unknown and unverified; resolve conflicting notes."
            ),
        },
        {
            "review_item_id": "rights_missing_source",
            "rights_status": "unknown",
            "permission_notes": (
                "Rights status is undocumented and the exact source identity "
                "was not supplied."
            ),
        },
        {},
    ]


def build_synthetic_rights_permission_gate(
    project_id: str = "proj_rights_permission_gate_synthetic",
) -> BobaRightsPermissionGateSetV1:
    """Build a complete local gate from synthetic saved-style BOBA artifacts."""

    candidate_scorer = build_synthetic_candidate_video_scorer(
        f"{project_id}_candidate"
    )
    content_scout = build_synthetic_content_scout(f"{project_id}_scout")
    research_brain = build_synthetic_research_brain(f"{project_id}_research")
    trend_watcher = build_synthetic_trend_topic_watcher(
        f"{project_id}_trend"
    )
    clip_briefs = {
        "schema_version": "boba_clip_brief_set_v1",
        "risk_warnings": [
            "Source rights and third-party content require human review."
        ],
        "limitations": ["No source media was inspected."],
    }
    music_mood = {
        "schema_version": "boba_music_mood_recommendation_v1",
        "rights_review_warning": (
            "Music and source-audio rights require separate human verification."
        ),
        "warnings": [
            "No music license or copyright status was validated."
        ],
    }
    memory = {
        "project_id": project_id,
        "source_summary": (
            "Compact project memory notes only; no media or transcript content."
        ),
    }
    return BobaRightsPermissionGateV1().analyze(
        project_id,
        source_id="synthetic_local_rights_metadata",
        manual_items=build_synthetic_rights_items(),
        source_label="validator_synthetic",
        candidate_video_scorer=candidate_scorer,
        content_scout=content_scout,
        research_brain=research_brain,
        trend_topic_watcher=trend_watcher,
        clip_briefs=clip_briefs,
        music_mood=music_mood,
        boba_memory=memory,
    )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("local-rights-metadata-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _safe_export(payload: dict[str, Any]) -> bool:
    gate = payload.get("rights_permission_gate")
    privacy = payload.get("privacy")
    if not isinstance(gate, dict) or not isinstance(privacy, dict):
        return False
    reviewed = gate.get("reviewed_items")
    if not isinstance(reviewed, list):
        return False
    private_fields = {
        "source_reference",
        "source_url",
        "permission_notes",
        "license_notes",
        "ownership_notes",
        "platform_source_notes",
        "source_artifact_refs",
        "evidence_snippets",
    }
    if any(
        isinstance(item, dict) and private_fields.intersection(item)
        for item in reviewed
    ):
        return False
    required_truth = {
        "private_paths_excluded": True,
        "source_urls_excluded": True,
        "private_notes_excluded": True,
        "evidence_snippets_excluded": True,
        "raw_source_content_excluded": True,
        "full_transcripts_excluded": True,
        "full_legal_documents_excluded": True,
        "media_files_excluded": True,
        "credentials_excluded": True,
        "external_api_used": False,
        "url_fetching_used": False,
        "scraping_used": False,
        "downloading_used": False,
        "media_ingestion_used": False,
        "legal_validation_used": False,
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


def _decision(
    gate: BobaRightsPermissionGateSetV1,
    candidate_video_id: str,
) -> BobaRightsGateDecisionV1 | None:
    return next(
        (
            item
            for item in gate.gate_decisions
            if item.candidate_video_id == candidate_video_id
            or item.review_item_id == candidate_video_id
        ),
        None,
    )


def _report_for_gate(
    gate: BobaRightsPermissionGateSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    report_dir: Path,
    artifact_persisted: bool,
    export_safe: bool,
    reset_project_only: bool,
) -> BobaRightsPermissionGateValidationReport:
    signal = gate.signal_usage
    owned = _decision(gate, "rights_owned")
    licensed = _decision(gate, "rights_licensed")
    granted = _decision(gate, "rights_permission_granted")
    permission = _decision(gate, "rights_permission_needed")
    unknown = _decision(gate, "rights_unknown")
    blocked = _decision(gate, "rights_blocked")
    public_domain = _decision(gate, "rights_public_domain_claimed")
    fair_use = _decision(gate, "rights_fair_use_claimed")
    conflict = _decision(gate, "rights_conflicting")
    missing_source = next(
        (
            item
            for item in gate.gate_decisions
            if item.review_item_id == "rights_missing_source"
        ),
        None,
    )
    unknown_handoff = next(
        (
            item
            for item in gate.future_ingestion_handoffs
            if item.candidate_video_id == "rights_unknown"
        ),
        None,
    )
    report = BobaRightsPermissionGateValidationReport(
        mode=mode,
        passed=False,
        project_id=gate.project_id,
        modules_imported=True,
        store_available=True,
        candidate_video_scorer_available=signal.candidate_video_scorer_used,
        content_scout_available=signal.content_scout_used,
        research_brain_available=signal.research_brain_used,
        trend_topic_watcher_available=signal.trend_topic_watcher_used,
        clip_briefs_available=signal.clip_briefs_used,
        music_mood_available=signal.music_mood_used,
        memory_available=signal.memory_used,
        report_path_writable=_report_path_writable(report_dir),
        reviewed_items_created=bool(gate.reviewed_items),
        gate_decisions_created=(
            len(gate.gate_decisions) == len(gate.reviewed_items)
        ),
        permission_checklists_created=(
            len(gate.permission_checklists) == len(gate.reviewed_items)
        ),
        risk_reviews_created=(
            len(gate.risk_reviews) == len(gate.reviewed_items)
        ),
        future_ingestion_handoffs_created=(
            len(gate.future_ingestion_handoffs) == len(gate.reviewed_items)
        ),
        invalid_items_rejected=any(
            "invalid rights review item" in warning.casefold()
            for warning in gate.warnings
        ),
        owned_ready_with_note=(
            owned is not None
            and owned.gate_status == "ready_for_human_review"
        ),
        licensed_ready_with_note=(
            licensed is not None
            and licensed.gate_status == "ready_for_human_review"
        ),
        permission_granted_ready_with_note=(
            granted is not None
            and granted.gate_status == "ready_for_human_review"
        ),
        permission_needed_blocked=(
            permission is not None
            and permission.gate_status == "needs_permission"
            and not permission.allow_future_ingestion_precheck
        ),
        unknown_requires_review=(
            unknown is not None
            and unknown.gate_status
            in {"needs_rights_review", "insufficient_information"}
            and unknown.requires_rights_review
        ),
        blocked_item_blocked=(
            blocked is not None
            and blocked.gate_status == "blocked"
            and blocked.blocked
        ),
        public_domain_claim_requires_review=(
            public_domain is not None
            and public_domain.gate_status == "needs_rights_review"
            and public_domain.requires_rights_review
        ),
        fair_use_claim_requires_review=(
            fair_use is not None
            and fair_use.gate_status == "needs_rights_review"
            and fair_use.requires_rights_review
        ),
        conflicting_notes_require_review=(
            conflict is not None
            and conflict.gate_status == "needs_rights_review"
            and owned is not None
            and conflict.confidence < owned.confidence
        ),
        missing_source_insufficient=(
            missing_source is not None
            and missing_source.gate_status == "insufficient_information"
        ),
        unknown_never_safe=(
            unknown is not None
            and not unknown.allow_future_ingestion_precheck
            and unknown_handoff is not None
            and unknown_handoff.ingestion_precheck_status
            != "eligible_for_manual_ingestion_review"
        ),
        final_human_approval_required=bool(gate.permission_checklists)
        and all(
            checklist.final_human_approval_required
            for checklist in gate.permission_checklists
        ),
        apply_automatically_false=bool(gate.future_ingestion_handoffs)
        and all(
            handoff.apply_automatically is False
            for handoff in gate.future_ingestion_handoffs
        ),
        legal_validation_used_false=signal.legal_validation_used is False,
        external_api_used_false=signal.external_api_used is False,
        url_fetching_used_false=signal.url_fetching_used is False,
        scraping_used_false=signal.scraping_used is False,
        downloading_used_false=signal.downloading_used is False,
        media_ingestion_used_false=signal.media_ingestion_used is False,
        artifact_persisted=artifact_persisted,
        json_safe=bool(json.loads(gate.model_dump_json())),
        export_safe=export_safe,
        reset_project_only=reset_project_only,
        warnings=[
            "Validation used synthetic local/user-provided rights metadata only.",
            "No legal validation or copyright-safety determination occurred.",
            "No rendering, downloading, URL fetching, external call, or media ingestion occurred.",
        ],
    )
    required = [
        report.modules_imported,
        report.store_available,
        report.report_path_writable,
        report.reviewed_items_created,
        report.gate_decisions_created,
        report.permission_checklists_created,
        report.risk_reviews_created,
        report.future_ingestion_handoffs_created,
        report.final_human_approval_required,
        report.apply_automatically_false,
        report.legal_validation_used_false,
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
                report.candidate_video_scorer_available,
                report.content_scout_available,
                report.research_brain_available,
                report.trend_topic_watcher_available,
                report.clip_briefs_available,
                report.music_mood_available,
                report.memory_available,
                report.invalid_items_rejected,
                report.owned_ready_with_note,
                report.licensed_ready_with_note,
                report.permission_granted_ready_with_note,
                report.permission_needed_blocked,
                report.unknown_requires_review,
                report.blocked_item_blocked,
                report.public_domain_claim_requires_review,
                report.fair_use_claim_requires_review,
                report.conflicting_notes_require_review,
                report.missing_source_insufficient,
                report.unknown_never_safe,
                report.reset_project_only,
            ]
        )
    report.passed = all(required)
    return report


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaRightsPermissionGateValidationReport:
    project_id = (
        "proj_rights_permission_gate_self_check"
        if mode == "self_check"
        else "proj_rights_permission_gate_synthetic"
    )
    gate = build_synthetic_rights_permission_gate(project_id)
    with TemporaryDirectory(prefix="boba-rights-permission-gate-") as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated project memory must survive reset.",
            )
        )
        saved = store.save_rights_permission_gate(gate)
        artifact_path = store.rights_permission_gate_path(project_id)
        artifact_persisted = (
            artifact_path.is_file()
            and store.load_rights_permission_gate(project_id) == saved
        )
        export_safe = _safe_export(
            store.export_rights_permission_gate(project_id)
        )
        reset_removed = store.reset_rights_permission_gate(project_id)
        reset_project_only = (
            reset_removed
            and store.load_rights_permission_gate(project_id) is None
            and store.load_project_memory(project_id) is not None
        )
    return _report_for_gate(
        gate,
        mode=mode,
        report_dir=report_dir,
        artifact_persisted=artifact_persisted,
        export_safe=export_safe,
        reset_project_only=reset_project_only,
    )


def run_self_check(
    report_dir: Path | None = None,
) -> BobaRightsPermissionGateValidationReport:
    """Run local imports, storage, safety, and deterministic behavior checks."""

    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaRightsPermissionGateValidationReport:
    """Run the complete synthetic advisory rights-gate proof."""

    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


def run_existing_project(
    project_id: str,
    report_dir: Path | None = None,
) -> BobaRightsPermissionGateValidationReport:
    """Load or safely generate one gate from saved local metadata only."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        integration = boba_integration_provider()
        gate = integration.load_rights_permission_gate(project_id)
        if gate is None:
            source_artifacts = (
                integration.store.load_candidate_video_scorer(project_id),
                integration.store.load_content_scout_v2(project_id),
                integration.store.load_research_brain(project_id),
                integration.store.load_trend_topic_watcher(project_id),
            )
            if any(source_artifacts):
                gate = asyncio.run(
                    integration.generate_rights_permission_gate(project_id)
                )
        if gate is None:
            return BobaRightsPermissionGateValidationReport(
                mode="project_id",
                passed=False,
                project_id=project_id,
                modules_imported=True,
                store_available=True,
                report_path_writable=_report_path_writable(
                    effective_report_dir
                ),
                legal_validation_used_false=True,
                external_api_used_false=True,
                url_fetching_used_false=True,
                scraping_used_false=True,
                downloading_used_false=True,
                media_ingestion_used_false=True,
                warnings=[
                    "No saved Rights + Permission Gate or usable saved BOBA "
                    "rights metadata is available.",
                    "No render, upload, download, URL fetch, external API call, "
                    "legal validation, or media ingestion occurred.",
                ],
            )
        artifact_path = integration.store.rights_permission_gate_path(
            project_id
        )
        return _report_for_gate(
            gate,
            mode="project_id",
            report_dir=effective_report_dir,
            artifact_persisted=artifact_path.is_file(),
            export_safe=_safe_export(
                integration.export_rights_permission_gate(project_id)
            ),
            reset_project_only=False,
        )
    except Exception as exc:
        return BobaRightsPermissionGateValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(effective_report_dir),
            legal_validation_used_false=True,
            external_api_used_false=True,
            url_fetching_used_false=True,
            scraping_used_false=True,
            downloading_used_false=True,
            media_ingestion_used_false=True,
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, fetch a URL, "
                "call an external API, perform legal validation, or ingest media."
            ],
        )


def _write_report(
    report: BobaRightsPermissionGateValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_rights_permission_gate_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Rights + Permission Gate V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Reviewed items created: `{report.reviewed_items_created}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- Legal validation performed: `false`",
        "- External APIs used: `false`",
        "- URLs fetched: `false`",
        "- Platforms scraped: `false`",
        "- Media downloaded or ingested: `false`",
        "- Rendering triggered: `false`",
        "",
        "Unknown rights are never treated as safe. Final human review is required.",
    ]
    (report_dir / "boba_rights_permission_gate_v1_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Rights + Permission Gate V1 locally.",
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
