"""Synthetic canonical BOBA records built through the real owning contracts.

Shared by the Clip Brief Review validator and its unit tests so both exercise
genuine module contracts rather than hand-written dictionaries.
"""

from __future__ import annotations

from typing import Any

from olympus.boba.clip_brief import (
    BobaBriefInstructionV1,
    BobaClipBriefSetV1,
    BobaClipBriefSignalUsageV1,
    BobaClipBriefV1,
    BobaEditorChecklistItemV1,
    BobaSourceWindowV1,
)
from olympus.boba.store import BobaMemoryStore

try:  # imported as ``tools._boba_clip_brief_review_fixtures``
    from tools._boba_candidate_review_fixtures import (
        seed_project as seed_candidate_project,
    )
except ModuleNotFoundError:  # imported from a script run inside ``tools``
    from _boba_candidate_review_fixtures import (  # type: ignore[no-redef,import-not-found]
        seed_project as seed_candidate_project,
    )

_INSTRUCTION_TYPES = {
    "hook_instruction": "hook",
    "opening_three_second_instruction": "opening",
    "story_instruction": "story",
    "cut_instruction": "cut",
    "caption_instruction": "caption",
    "motion_instruction": "motion",
    "audio_instruction": "audio",
    "sfx_instruction": "sfx",
    "retention_instruction": "retention",
}


def instruction(kind: str) -> BobaBriefInstructionV1:
    return BobaBriefInstructionV1(
        instruction_type=_INSTRUCTION_TYPES[kind],
        summary=f"{kind} summary from the owner record.",
        do_this=f"Do the {kind} exactly as persisted.",
        avoid_this=f"Avoid weakening the {kind}.",
        reason=f"The owner recorded this {kind} reason.",
        priority="must_follow",
    )


def synthetic_brief(
    brief_id: str,
    project_id: str,
    candidate_id: str,
    clip_id: str,
    start: float,
    end: float,
    *,
    warnings: list[str] | None = None,
    limitations: list[str] | None = None,
    with_checklist: bool = True,
    duration_override: float | None = None,
) -> BobaClipBriefV1:
    return BobaClipBriefV1(
        brief_id=brief_id,
        project_id=project_id,
        candidate_id=candidate_id,
        ranked_clip_id=clip_id,
        source_window=BobaSourceWindowV1(
            start_seconds=start,
            end_seconds=end,
            duration_seconds=(
                duration_override if duration_override is not None else round(end - start, 3)
            ),
        ),
        production_priority="high",
        render_readiness="ready_for_render",
        brief_title=f"Brief {brief_id}",
        final_clip_angle="The exact clip angle recorded by the owner.",
        target_viewer_feeling="Curious and informed.",
        hook_instruction=instruction("hook_instruction"),
        opening_three_second_instruction=instruction("opening_three_second_instruction"),
        story_instruction=instruction("story_instruction"),
        cut_instruction=instruction("cut_instruction"),
        caption_instruction=instruction("caption_instruction"),
        motion_instruction=instruction("motion_instruction"),
        audio_instruction=instruction("audio_instruction"),
        sfx_instruction=instruction("sfx_instruction"),
        retention_instruction=instruction("retention_instruction"),
        risk_fixes=["Trim the trailing silence."],
        editor_checklist=(
            [
                BobaEditorChecklistItemV1(
                    item_id="check_1",
                    label="Confirm the hook lands in the first three seconds.",
                    category="hook",
                    required=True,
                    status="pending",
                    reason="The owner marked this as required.",
                )
            ]
            if with_checklist
            else []
        ),
        human_review_notes=["The owner recorded a review note."],
        confidence=0.78,
        warnings=warnings or [],
        limitations=limitations or [],
    )


def synthetic_brief_set(
    project_id: str,
    *,
    selected: list[BobaClipBriefV1] | None = None,
    backup: list[BobaClipBriefV1] | None = None,
    blocked: list[BobaClipBriefV1] | None = None,
) -> BobaClipBriefSetV1:
    return BobaClipBriefSetV1(
        project_id=project_id,
        source_id="synthetic_source",
        selected_briefs=selected or [],
        backup_briefs=backup or [],
        blocked_briefs=blocked or [],
        production_order=[item.brief_id for item in (selected or [])],
        project_summary="Synthetic clip brief set for review projection tests.",
        signal_usage=BobaClipBriefSignalUsageV1(
            creative_direction_v2_used=True,
            editorial_decision_used=True,
            explanation_used=False,
            clip_ranking_used=True,
            candidate_discovery_used=True,
            whole_video_understanding_used=True,
            memory_used=False,
            fallback_used=False,
        ),
    )


def seed_project(
    store: BobaMemoryStore,
    project_id: str,
    *,
    with_briefs: bool = True,
    with_candidates: bool = True,
    selected_candidates: list[str] | None = None,
    brief_windows: list[tuple[str, str, float, float]] | None = None,
    duration_override: float | None = None,
    blocked_brief_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Persist canonical records for a synthetic clip-brief-review project."""
    rows = brief_windows or [
        ("brief_a", "cand_a", 10.0, 40.0),
        ("brief_b", "cand_b", 35.0, 65.0),
    ]
    if with_candidates:
        seed_candidate_project(
            store,
            project_id,
            windows=[("cand_a", 10.0, 40.0), ("cand_b", 35.0, 65.0)],
            recommended=["cand_a"],
            selected=selected_candidates if selected_candidates is not None else ["cand_a"],
        )
    if with_briefs:
        blocked_ids = set(blocked_brief_ids or [])
        selected_briefs: list[BobaClipBriefV1] = []
        blocked_briefs: list[BobaClipBriefV1] = []
        for brief_id, candidate_id, start, end in rows:
            brief = synthetic_brief(
                brief_id,
                project_id,
                candidate_id,
                candidate_id,
                start,
                end,
                duration_override=duration_override,
            )
            if brief_id in blocked_ids:
                blocked_briefs.append(brief)
            else:
                selected_briefs.append(brief)
        store.save_clip_briefs(
            synthetic_brief_set(
                project_id, selected=selected_briefs, blocked=blocked_briefs
            )
        )
    return {"brief_windows": rows}
