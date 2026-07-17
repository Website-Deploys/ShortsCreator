"""Build bounded project memory from existing Olympus and BOBA artifacts."""

from __future__ import annotations

from typing import Any

from olympus.boba.contracts import BobaDecisionV1
from olympus.boba.memory_contracts import BobaMemoryRecordV1, BobaProjectMemoryV1
from olympus.boba.memory_summarizer import memory_strings, memory_summary, safe_excerpt, safe_range
from olympus.boba.store import BobaMemoryStore

KNOWN_PROJECT_LIMITATIONS = [
    "Canonical render checkpoint compatibility must be validated against "
    "render/<project_id>/run/index.json and referenced MP4s.",
    "A/V voice delay has been user-reported and is not resolved by BOBA Memory.",
    "Abrupt clip cuts have been user-reported and are not resolved by BOBA Memory.",
    "Real face-tracked motion remains unproven until rendered output is visually validated.",
    "Music audibility and speech clarity remain unverified without objective or "
    "manual playback validation.",
    "Git metadata is unavailable in the current extracted workspace, so change "
    "history cannot be verified.",
]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clip_id(value: dict[str, Any], fallback: str) -> str:
    return str(
        value.get("clip_id")
        or value.get("id")
        or value.get("plan_id")
        or value.get("candidate_id")
        or fallback
    )[:128]


def _confidence(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 3)


def _selection_record(project_id: str, item: dict[str, Any], index: int) -> BobaMemoryRecordV1:
    clip_id = _clip_id(item, f"selected_{index + 1}")
    scores = _dict(item.get("scores"))
    hook = str(item.get("hook_line") or item.get("hook") or item.get("title") or "")
    reason = str(item.get("selected_reason") or item.get("reason") or "Selected by planning.")
    source_range = safe_range(item)
    evidence = [reason]
    if source_range:
        evidence.append(
            f"Source range {source_range['start']:.2f}-{source_range['end']:.2f} seconds."
        )
    return BobaMemoryRecordV1(
        memory_id=f"clip_selection_{project_id}_{clip_id}"[:128],
        scope="project",
        record_type="clip_selection",
        source="olympus_planning_v2",
        project_id=project_id,
        clip_id=clip_id,
        confidence=_confidence(item.get("confidence") or scores.get("overall"), 0.6),
        importance=0.8,
        tags=memory_strings(
            ["selected_clip", item.get("hook_category"), item.get("story_shape")],
            limit=8,
            max_chars=80,
        ),
        summary=memory_summary([f"Selected clip {clip_id}", reason]),
        evidence=memory_strings(evidence, limit=8, max_chars=300),
        safe_excerpt=safe_excerpt(hook),
        applies_to=["planning", "ranking", "editorial_policy", "frontend"],
        metadata={"source_range": source_range, "content_niche": item.get("content_niche")},
    )


def _rejection_record(project_id: str, item: dict[str, Any], index: int) -> BobaMemoryRecordV1:
    clip_id = _clip_id(item, f"rejected_{index + 1}")
    reason = str(
        item.get("rejection_reason")
        or item.get("reason")
        or "Candidate was not selected."
    )
    return BobaMemoryRecordV1(
        memory_id=f"clip_rejection_{project_id}_{clip_id}"[:128],
        scope="project",
        record_type="clip_rejection",
        source="olympus_planning_v2",
        project_id=project_id,
        clip_id=clip_id,
        confidence=_confidence(item.get("confidence"), 0.5),
        importance=0.55,
        tags=["rejected_clip"],
        summary=memory_summary([f"Rejected clip {clip_id}", reason]),
        evidence=memory_strings([reason], max_chars=300),
        applies_to=["planning", "ranking", "frontend"],
        metadata={"source_range": safe_range(item)},
    )


def _decision_record(project_id: str, decision: BobaDecisionV1) -> BobaMemoryRecordV1 | None:
    record_types = {
        "editing_policy": "editing_decision",
        "caption_policy": "caption_decision",
        "music_policy": "music_decision",
        "motion_policy": "motion_decision",
        "upload_metadata_policy": "title_decision",
    }
    record_type = record_types.get(decision.decision_type)
    if record_type is None:
        return None
    target = decision.output_directive.target_system
    target_system = "upload_metadata" if target == "upload_metadata" else target
    applies_to = [target_system] if target_system in {
        "planning",
        "ranking",
        "editorial_policy",
        "captions",
        "music",
        "motion",
        "upload_metadata",
        "safety",
        "frontend",
    } else ["frontend"]
    return BobaMemoryRecordV1(
        memory_id=f"memory_{decision.decision_id}"[:128],
        scope="project",
        record_type=record_type,
        source="boba_core_decision",
        project_id=project_id,
        clip_id=decision.clip_id,
        confidence=decision.confidence,
        importance=0.65,
        tags=[decision.decision_type, target],
        summary=safe_excerpt(decision.answer, max_chars=600),
        evidence=memory_strings(decision.reasoning.evidence, limit=12, max_chars=300),
        applies_to=applies_to,
        warnings=memory_strings(decision.validation.warnings, max_chars=240),
    )


def build_project_memory(
    project_id: str,
    signals: dict[str, Any],
    *,
    decisions: list[BobaDecisionV1] | None = None,
    feedback: list[Any] | None = None,
) -> tuple[BobaProjectMemoryV1, list[BobaMemoryRecordV1]]:
    project = _dict(signals.get("project"))
    selected = [_dict(item) for item in _list(signals.get("selected_plans")) if _dict(item)]
    rejected = [_dict(item) for item in _list(signals.get("rejected_candidates")) if _dict(item)]
    candidates = [_dict(item) for item in _list(signals.get("planning_candidates")) if _dict(item)]
    used_ranges = [value for item in selected if (value := safe_range(item))]
    limitations = memory_strings(
        [*KNOWN_PROJECT_LIMITATIONS, *_list(signals.get("known_limitations"))],
        limit=64,
        max_chars=360,
    )
    records: list[BobaMemoryRecordV1] = []
    summary_text = memory_summary(
        [
            project.get("title") or project.get("name") or f"Project {project_id}",
            "Category: "
            f"{project.get('content_category') or signals.get('content_niche') or 'unknown'}",
            f"Selected {len(selected)} of {len(candidates)} available candidates",
        ]
    )
    records.append(
        BobaMemoryRecordV1(
            memory_id=f"project_summary_{project_id}"[:128],
            scope="project",
            record_type="project_summary",
            source="olympus_v2_artifacts",
            project_id=project_id,
            confidence=0.7 if signals.get("transcript_available") else 0.35,
            importance=0.9,
            tags=memory_strings(
                [
                    "project_summary",
                    signals.get("content_niche"),
                    *_list(signals.get("main_topics")),
                ],
                limit=16,
                max_chars=80,
            ),
            summary=summary_text,
            evidence=memory_strings(
                [
                    f"Transcript available: {bool(signals.get('transcript_available'))}",
                    f"Render manifest available: {bool(signals.get('render_manifest_available'))}",
                ],
                max_chars=200,
            ),
            applies_to=["planning", "ranking", "editorial_policy", "frontend"],
            metadata={"content_niche": signals.get("content_niche")},
        )
    )
    records.extend(
        _selection_record(project_id, item, index)
        for index, item in enumerate(selected)
    )
    records.extend(
        _rejection_record(project_id, item, index)
        for index, item in enumerate(rejected)
    )
    for decision in decisions or []:
        record = _decision_record(project_id, decision)
        if record is not None:
            records.append(record)
    safety_status = str(signals.get("safety_status") or "unknown")
    if safety_status != "clear" or signals.get("safety_manual_review_required"):
        records.append(
            BobaMemoryRecordV1(
                scope="project",
                record_type="safety_warning",
                source="olympus_safety_metadata",
                project_id=project_id,
                confidence=0.8 if signals.get("safety_signals_available") else 0.3,
                importance=1.0,
                tags=[
                    "safety",
                    "manual_review"
                    if signals.get("safety_manual_review_required")
                    else "unknown",
                ],
                summary=(
                    f"Safety status is {safety_status}; BOBA Memory does not "
                    "override safety review."
                ),
                applies_to=["safety", "planning", "frontend"],
            )
        )
    for index, limitation in enumerate(limitations):
        records.append(
            BobaMemoryRecordV1(
                memory_id=f"limitation_{project_id}_{index + 1}"[:128],
                scope="project",
                record_type="known_limitation",
                source="known_project_limitations",
                project_id=project_id,
                confidence=1.0,
                importance=0.9,
                tags=["known_limitation"],
                summary=limitation,
                applies_to=["planning", "editorial_policy", "motion", "music", "frontend"],
            )
        )
    project_memory = BobaProjectMemoryV1(
        project_id=project_id,
        source_summary=summary_text,
        video_duration=signals.get("duration_seconds"),
        main_topics=memory_strings(signals.get("main_topics"), limit=24),
        speakers_or_roles=memory_strings(signals.get("speakers_or_roles"), limit=24),
        story_threads=memory_strings(signals.get("story_threads"), limit=24),
        emotional_moments=memory_strings(signals.get("emotional_moments"), limit=24),
        candidate_count=len(candidates),
        selected_clip_ids=[
            _clip_id(item, f"selected_{index + 1}")
            for index, item in enumerate(selected)
        ],
        rejected_clip_ids=[
            _clip_id(item, f"rejected_{index + 1}")
            for index, item in enumerate(rejected)
        ],
        used_source_ranges=used_ranges,
        unused_opportunities=memory_strings(signals.get("unused_opportunities"), limit=100),
        decisions_count=len(decisions or []),
        feedback_count=len(feedback or []),
        known_limitations=limitations,
        memory_records=[record.memory_id for record in records],
        warnings=memory_strings(signals.get("warnings"), limit=64),
    )
    return project_memory, records


def build_and_save_project_memory(
    store: BobaMemoryStore,
    project_id: str,
    signals: dict[str, Any],
    *,
    decisions: list[BobaDecisionV1] | None = None,
    feedback: list[Any] | None = None,
) -> BobaProjectMemoryV1:
    project_memory, records = build_project_memory(
        project_id, signals, decisions=decisions, feedback=feedback
    )
    saved_records = [store.save_record(record) for record in records]
    project_memory.memory_records = [record.memory_id for record in saved_records]
    return store.save_project_memory(project_memory)
