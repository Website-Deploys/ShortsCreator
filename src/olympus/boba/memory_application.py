"""Translate retrieved memory into bounded BOBA advisory adjustments."""

from __future__ import annotations

from olympus.boba.memory_contracts import (
    BobaMemoryApplicationV1,
    BobaMemoryRetrievalResultV1,
    MemoryTargetSystem,
)


def create_memory_application(
    project_id: str,
    target_system: MemoryTargetSystem,
    retrieval: BobaMemoryRetrievalResultV1,
    *,
    clip_id: str | None = None,
) -> BobaMemoryApplicationV1:
    adjustments: list[dict[str, object]] = []
    warnings = list(retrieval.warnings)
    for record in retrieval.records:
        text = " ".join([record.summary, *record.tags]).lower()
        if target_system == "ranking" and "emotional" in text and any(
            word in text for word in ("prefer", "liked", "payoff")
        ):
            adjustments.append(
                {
                    "field": "emotional_payoff_advisory",
                    "value": "prefer_when_story_complete",
                    "max_score_delta": 0.08,
                    "reason": record.summary,
                }
            )
        if target_system == "ranking" and record.record_type == "clip_selection":
            adjustments.append(
                {
                    "field": "duplicate_source_range_warning",
                    "value": record.metadata.get("source_range"),
                    "reason": "A source range was already selected in this project.",
                }
            )
        if target_system == "upload_metadata" and "generic" in text:
            adjustments.append(
                {
                    "field": "title_warning",
                    "value": "avoid_generic_title",
                    "reason": record.summary,
                }
            )
        if target_system == "music" and any(
            phrase in text
            for phrase in (
                "music_overpowers_speech",
                "high_music_intensity",
                "music too loud",
            )
        ):
            adjustments.append(
                {
                    "field": "music_mix_advisory",
                    "value": "speech_first_lower_intensity",
                    "max_gain_adjustment_db": -2.0,
                    "reason": record.summary,
                }
            )
        if target_system == "motion" and any(
            phrase in text
            for phrase in (
                "face unavailable",
                "face-tracked motion remains unproven",
            )
        ):
            adjustments.append(
                {
                    "field": "face_motion_advisory",
                    "value": "stable_center_fallback",
                    "reason": record.summary,
                }
            )
        if target_system == "editorial_policy" and "payoff" in text and "tail" in text:
            adjustments.append(
                {
                    "field": "ending_hold_advisory",
                    "value": "preserve_payoff_tail",
                    "reason": record.summary,
                }
            )
    unique: list[dict[str, object]] = []
    seen: set[tuple[object, object]] = set()
    for adjustment in adjustments:
        key = (adjustment.get("field"), str(adjustment.get("value")))
        if key not in seen:
            unique.append(adjustment)
            seen.add(key)
    if not unique and retrieval.records:
        warnings.append(
            "Relevant memory was retrieved but produced no bounded advisory adjustment."
        )
    return BobaMemoryApplicationV1(
        project_id=project_id,
        clip_id=clip_id,
        target_system=target_system,
        memory_used=[record.memory_id for record in retrieval.records],
        adjustments=unique[:32],
        confidence=retrieval.confidence,
        explanation=(
            f"BOBA used {len(retrieval.records)} memory record(s) to create "
            f"{len(unique)} advisory adjustment(s)."
        ),
        warnings=list(dict.fromkeys(warnings)),
    )
