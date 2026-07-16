"""Application boundary for local creator profiles and explicit feedback."""

from __future__ import annotations

from typing import Any

from olympus.personalization.contracts import (
    ClipFeedbackV2,
    CreatorProfileV2,
    FeedbackRating,
)
from olympus.personalization.feedback import (
    apply_feedback_to_profile,
    build_feedback,
    feedback_labels,
)
from olympus.personalization.presets import preset_names
from olympus.personalization.store import ProfileStore


class CreatorPersonalizationService:
    def __init__(
        self,
        store: ProfileStore,
        *,
        conservative_until_feedback_count: int = 5,
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.conservative_until_feedback_count = conservative_until_feedback_count
        self.enabled = enabled

    def initialize(self) -> CreatorProfileV2:
        return self.store.initialize_default()

    def list_profiles(self) -> list[CreatorProfileV2]:
        self.initialize()
        return self.store.list_profiles()

    def get_profile(self, profile_id: str) -> CreatorProfileV2:
        self.initialize()
        return self.store.get_profile(profile_id)

    def create_profile(
        self,
        preset_id: str,
        *,
        profile_name: str | None = None,
        learning_enabled: bool = False,
        activate: bool = False,
    ) -> CreatorProfileV2:
        return self.store.create_profile(
            preset_id,
            profile_name=profile_name,
            learning_enabled=learning_enabled,
            activate=activate,
        )

    def update_profile(self, profile_id: str, updates: dict[str, Any]) -> CreatorProfileV2:
        return self.store.update_profile(profile_id, updates)

    def activate_profile(self, profile_id: str) -> CreatorProfileV2:
        return self.store.set_active_profile(profile_id)

    def reset_profile(self, profile_id: str) -> CreatorProfileV2:
        return self.store.reset_profile(profile_id)

    def export_profile(self, profile_id: str) -> dict[str, Any]:
        profile, path = self.store.export_profile(profile_id)
        return {
            "profile": profile.model_dump(mode="json"),
            "exported": True,
            "filename": path.name,
        }

    def import_profile(
        self, payload: dict[str, Any], *, activate: bool = False
    ) -> CreatorProfileV2:
        return self.store.import_profile(payload, activate=activate)

    def record_feedback(
        self,
        *,
        profile_id: str,
        project_id: str,
        clip_id: str,
        rating: dict[str, Any] | str,
        labels: list[str] | None = None,
        notes: str = "",
        clip_traits: dict[str, Any] | None = None,
    ) -> ClipFeedbackV2:
        profile = self.store.get_profile(profile_id)
        rating_model = (
            FeedbackRating(overall=rating)
            if isinstance(rating, str)
            else FeedbackRating.model_validate(rating)
        )
        feedback = build_feedback(
            profile_id=profile_id,
            project_id=project_id,
            clip_id=clip_id,
            rating=rating_model,
            labels=feedback_labels(labels),
            notes=notes,
            clip_traits=clip_traits,
            max_note_chars=self.store.max_note_chars,
        )
        updated, applied = apply_feedback_to_profile(
            profile,
            feedback,
            conservative_until=self.conservative_until_feedback_count,
        )
        feedback.applied_to_profile = applied
        self.store.save_profile(updated)
        self.store.record_feedback(feedback)
        return feedback

    def summary(self) -> dict[str, Any]:
        default = self.initialize()
        active = self.store.get_active_profile(fallback_id=default.profile_id) or default
        feedback = self.store.list_feedback(active.profile_id)
        return {
            "version": "2",
            "enabled": self.enabled,
            "active_profile": active.model_dump(mode="json"),
            "profile_count": len(self.store.list_profiles()),
            "feedback_count": len(feedback),
            "presets": preset_names(),
            "privacy": active.privacy.model_dump(mode="json"),
            "message": "Personalization is local and based only on explicit feedback.",
        }
