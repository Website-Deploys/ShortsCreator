"""Explicit approval events and bounded BOBA learning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.creative_director import BobaCreativeBriefV1
from olympus.boba.memory_contracts import BobaMemoryRecordV1
from olympus.boba.scout import (
    BobaCandidateV1,
    approval_memory_record,
)
from olympus.platform.errors import NotFoundError, ValidationError

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore

BobaApprovalTargetType = Literal["candidate", "clip_idea"]
BobaApprovalDecision = Literal[
    "approved",
    "rejected",
    "needs_changes",
    "saved_for_later",
]


class BobaApprovalEventV1(BobaContract):
    event_id: str = Field(
        default_factory=lambda: f"approval_{uuid4().hex[:20]}",
        min_length=1,
        max_length=128,
    )
    target_type: BobaApprovalTargetType
    target_id: str = Field(min_length=1, max_length=128)
    decision: BobaApprovalDecision
    reason: str = Field(default="", max_length=500)
    created_at: str = Field(default_factory=now_iso)


class BobaApprovalService:
    """Record only explicit decisions; never infer approval from passive behavior."""

    def __init__(self, store: BobaMemoryStore) -> None:
        self.store = store

    def decide_candidate(
        self,
        candidate_id: str,
        *,
        decision: BobaApprovalDecision,
        reason: str = "",
        approve_for_processing: bool = False,
        creator_profile_id: str | None = None,
    ) -> tuple[BobaApprovalEventV1, BobaCandidateV1, BobaMemoryRecordV1]:
        candidate = self.store.load_scout_candidate(candidate_id)
        if candidate is None:
            raise NotFoundError(
                "BOBA candidate was not found.", details={"candidate_id": candidate_id}
            )
        if approve_for_processing and decision != "approved":
            raise ValidationError("Only an approved decision may request processing status.")
        if approve_for_processing and not candidate.processing_permitted:
            raise ValidationError(
                "BOBA cannot approve processing without confirmed permission and allowed rights."
            )
        updated = candidate.model_copy(deep=True)
        if decision == "approved":
            updated.status = (
                "approved_for_processing"
                if approve_for_processing
                else "approved_for_review"
            )
        elif decision == "rejected":
            updated.status = "rejected"
        elif decision == "saved_for_later":
            updated.status = "idea_only"
        else:
            updated.status = "approved_for_review"
        self.store.save_scout_candidate(updated)
        event = BobaApprovalEventV1(
            target_type="candidate",
            target_id=candidate_id,
            decision=decision,
            reason=reason,
        )
        self.store.append_approval_event(event)
        record = approval_memory_record(
            updated,
            event_id=event.event_id,
            decision=decision,
            reason=reason,
            creator_profile_id=creator_profile_id,
        )
        saved_record = self.store.save_record(record)
        return event, updated, saved_record

    def decide_clip_idea(
        self,
        project_id: str,
        clip_id: str,
        *,
        decision: BobaApprovalDecision,
        reason: str = "",
        creator_profile_id: str | None = None,
    ) -> tuple[BobaApprovalEventV1, BobaMemoryRecordV1]:
        brief = next(
            (
                item
                for item in self.store.list_creative_briefs(project_id)
                if item.clip_id == clip_id
            ),
            None,
        )
        if brief is None:
            raise NotFoundError(
                "BOBA creative brief was not found.",
                details={"project_id": project_id, "clip_id": clip_id},
            )
        event = BobaApprovalEventV1(
            target_type="clip_idea",
            target_id=clip_id,
            decision=decision,
            reason=reason,
        )
        self.store.append_approval_event(event)
        record = self._creative_memory_record(
            project_id,
            brief,
            event,
            creator_profile_id=creator_profile_id,
        )
        return event, self.store.save_record(record)

    def list_events(
        self,
        *,
        target_type: BobaApprovalTargetType | None = None,
        target_id: str | None = None,
    ) -> list[BobaApprovalEventV1]:
        return self.store.list_approval_events(
            target_type=target_type, target_id=target_id
        )

    @staticmethod
    def _creative_memory_record(
        project_id: str,
        brief: BobaCreativeBriefV1,
        event: BobaApprovalEventV1,
        *,
        creator_profile_id: str | None,
    ) -> BobaMemoryRecordV1:
        amount = {
            "approved": 0.06,
            "rejected": -0.09,
            "needs_changes": -0.03,
            "saved_for_later": 0.0,
        }[event.decision]
        preferences = {
            "pacing_level": {brief.pacing_level: amount},
            "caption_style": {brief.caption_style: amount},
            "motion_style": {brief.motion_style: amount},
            "music_mood": {brief.music_mood: amount},
            "hook_type": {brief.hook_type: amount},
        }
        scope: Literal["project", "creator"] = (
            "creator" if creator_profile_id else "project"
        )
        return BobaMemoryRecordV1(
            memory_id=f"approval_memory_{event.event_id}"[:128],
            scope=scope,
            record_type=(
                "learned_pattern"
                if event.decision == "approved"
                else "failed_pattern"
                if event.decision == "rejected"
                else "user_feedback"
            ),
            source="explicit_boba_approval",
            project_id=project_id if scope == "project" else None,
            clip_id=brief.clip_id,
            creator_profile_id=creator_profile_id if scope == "creator" else None,
            confidence=0.55,
            importance=0.6,
            decay_rate=0.08,
            tags=[
                "explicit_approval",
                event.decision,
                f"hook:{brief.hook_type}",
                f"pacing:{brief.pacing_level}",
            ],
            summary=(
                f"Explicit {event.decision} decision recorded for bounded creative traits."
            ),
            evidence=[event.reason] if event.reason else [],
            applies_to=["editorial_policy", "captions", "music", "motion", "frontend"],
            metadata={
                "approval_event_id": event.event_id,
                "target_type": "clip_idea",
                "creative_preferences": preferences,
            },
            warnings=["This lesson came only from explicit user input."],
        )
