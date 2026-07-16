"""Safe migration helpers from BOBA Core project summaries to Memory V1."""

from __future__ import annotations

from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.store import BobaMemoryStore


def migrate_legacy_project_memory(
    store: BobaMemoryStore, project_id: str
) -> BobaProjectMemoryV1 | None:
    current = store.load_project_memory(project_id)
    if current is not None:
        return current
    state = store.load_brain_state(project_id)
    if state is None:
        return None
    summary = state.project_memory_summary
    migrated = BobaProjectMemoryV1(
        project_id=project_id,
        source_summary="Migrated from bounded BOBA Core Brain V1 project memory summary.",
        video_duration=state.source_understanding.duration_seconds,
        main_topics=summary.main_topics,
        speakers_or_roles=summary.speakers_or_roles,
        story_threads=summary.story_threads,
        emotional_moments=summary.emotional_moments,
        selected_clip_ids=[],
        rejected_clip_ids=[],
        used_source_ranges=summary.already_selected_ranges,
        unused_opportunities=summary.unused_opportunities,
        decisions_count=len(store.list_decisions(project_id)),
        known_limitations=state.decision_context.known_limitations,
        warnings=["Migrated summary contains no full transcript or media content."],
    )
    return store.save_project_memory(migrated)
