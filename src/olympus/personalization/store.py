"""Atomic local JSON persistence for creator profiles and explicit feedback."""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from olympus.personalization.contracts import ClipFeedbackV2, CreatorProfileV2, utc_now
from olympus.personalization.presets import profile_from_preset
from olympus.personalization.validation import assert_privacy_safe
from olympus.platform.errors import ConflictError, NotFoundError, ValidationError


class ProfileStore:
    """A process-safe-enough local store using validation and atomic replacement."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_profiles: int = 20,
        max_note_chars: int = 500,
        learning_enabled_by_default: bool = False,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.profiles_dir = self.root / "profiles"
        self.feedback_dir = self.root / "feedback"
        self.exports_dir = self.root / "exports"
        self.backups_dir = self.root / "backups"
        self.active_path = self.root / "active_profile.json"
        self.max_profiles = max_profiles
        self.max_note_chars = max_note_chars
        self.learning_enabled_by_default = learning_enabled_by_default
        self._lock = threading.RLock()

    def ensure_layout(self) -> None:
        for directory in (
            self.profiles_dir,
            self.feedback_dir,
            self.exports_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _profile_path(self, profile_id: str) -> Path:
        CreatorProfileV2.validate_profile_id(profile_id)
        return self.profiles_dir / f"{profile_id}.json"

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise NotFoundError(
                "Personalization record was not found.", details={"name": path.name}
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "Personalization JSON is unreadable.", details={"name": path.name}
            ) from exc
        if not isinstance(raw, dict):
            raise ValidationError("Personalization JSON must contain an object.")
        return raw

    def _write_json(self, path: Path, payload: dict[str, Any], *, backup: bool = False) -> None:
        assert_privacy_safe(payload)
        self.ensure_layout()
        if backup and path.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
            shutil.copy2(path, self.backups_dir / f"{path.stem}_{stamp}.json")
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    def initialize_default(self) -> CreatorProfileV2:
        with self._lock:
            self.ensure_layout()
            path = self._profile_path("default")
            if path.exists():
                profile = self.get_profile("default")
            else:
                profile = profile_from_preset(
                    "balanced_default",
                    profile_id="default",
                    profile_name="Balanced Default",
                    learning_enabled=self.learning_enabled_by_default,
                )
                self.save_profile(profile)
            if not self.active_path.exists():
                self.set_active_profile(profile.profile_id)
            return profile

    def create_profile(
        self,
        preset_id: str,
        *,
        profile_name: str | None = None,
        profile_id: str | None = None,
        learning_enabled: bool = False,
        activate: bool = False,
    ) -> CreatorProfileV2:
        with self._lock:
            self.ensure_layout()
            if len(self.list_profiles()) >= self.max_profiles:
                raise ValidationError(
                    "Maximum local creator profiles reached.",
                    details={"max_profiles": self.max_profiles},
                )
            profile = profile_from_preset(
                preset_id,
                profile_id=profile_id,
                profile_name=profile_name,
                learning_enabled=learning_enabled,
            )
            if self._profile_path(profile.profile_id).exists():
                raise ConflictError(
                    "A creator profile with that id already exists.",
                    details={"profile_id": profile.profile_id},
                )
            self.save_profile(profile)
            if activate:
                self.set_active_profile(profile.profile_id)
            return profile

    def save_profile(self, profile: CreatorProfileV2) -> CreatorProfileV2:
        with self._lock:
            profile.updated_at = utc_now()
            payload = profile.model_dump(mode="json")
            self._write_json(self._profile_path(profile.profile_id), payload, backup=True)
            return profile

    def get_profile(self, profile_id: str) -> CreatorProfileV2:
        path = self._profile_path(profile_id)
        try:
            return CreatorProfileV2.model_validate(self._read_json(path))
        except PydanticValidationError as exc:
            raise ValidationError(
                "Stored creator profile failed schema validation.",
                details={"profile_id": profile_id},
            ) from exc

    def list_profiles(self) -> list[CreatorProfileV2]:
        self.ensure_layout()
        profiles: list[CreatorProfileV2] = []
        for path in sorted(self.profiles_dir.glob("*.json")):
            try:
                profiles.append(CreatorProfileV2.model_validate(self._read_json(path)))
            except (ValidationError, PydanticValidationError):
                continue
        return sorted(profiles, key=lambda item: item.profile_name.casefold())

    def update_profile(self, profile_id: str, updates: dict[str, Any]) -> CreatorProfileV2:
        forbidden = {"profile_id", "created_at", "version", "privacy"}
        if forbidden & updates.keys():
            raise ValidationError(
                "Immutable privacy or identity fields cannot be patched.",
                details={"fields": sorted(forbidden & updates.keys())},
            )
        current = self.get_profile(profile_id).model_dump(mode="json")

        def merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
            merged = dict(base)
            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = merge(merged[key], value)
                else:
                    merged[key] = value
            return merged

        try:
            profile = CreatorProfileV2.model_validate(merge(current, updates))
        except PydanticValidationError as exc:
            raise ValidationError(
                "Creator profile update failed validation.",
                details={"errors": exc.errors(include_url=False)},
            ) from exc
        return self.save_profile(profile)

    def set_active_profile(self, profile_id: str) -> CreatorProfileV2:
        with self._lock:
            profile = self.get_profile(profile_id)
            self._write_json(
                self.active_path,
                {"profile_id": profile_id, "updated_at": utc_now(), "version": "2"},
            )
            return profile

    def get_active_profile(self, *, fallback_id: str | None = None) -> CreatorProfileV2 | None:
        if self.active_path.exists():
            profile_id = str(self._read_json(self.active_path).get("profile_id") or "")
            return self.get_profile(profile_id) if profile_id else None
        if fallback_id and self._profile_path(fallback_id).exists():
            return self.get_profile(fallback_id)
        return None

    def reset_profile(self, profile_id: str, *, clear_feedback: bool = True) -> CreatorProfileV2:
        with self._lock:
            current = self.get_profile(profile_id)
            reset = profile_from_preset(
                current.preset_id,
                profile_id=current.profile_id,
                profile_name=current.profile_name,
                learning_enabled=False,
            )
            reset.created_at = current.created_at
            self.save_profile(reset)
            if clear_feedback:
                for path in self.feedback_dir.glob("*.json"):
                    try:
                        raw = self._read_json(path)
                    except ValidationError:
                        continue
                    if raw.get("profile_id") == profile_id:
                        path.unlink(missing_ok=True)
            return reset

    def export_profile(self, profile_id: str) -> tuple[CreatorProfileV2, Path]:
        with self._lock:
            profile = self.get_profile(profile_id)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = self.exports_dir / f"{profile_id}_{stamp}.json"
            self._write_json(path, profile.model_dump(mode="json"))
            return profile, path

    def import_profile(
        self, payload: dict[str, Any], *, activate: bool = False
    ) -> CreatorProfileV2:
        if len(self.list_profiles()) >= self.max_profiles:
            raise ValidationError(
                "Maximum local creator profiles reached.",
                details={"max_profiles": self.max_profiles},
            )
        assert_privacy_safe(payload)
        try:
            profile = CreatorProfileV2.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError(
                "Imported creator profile failed schema validation.",
                details={"errors": exc.errors(include_url=False)},
            ) from exc
        if self._profile_path(profile.profile_id).exists():
            profile.profile_id = f"profile_{uuid4().hex[:16]}"
            profile.profile_name = f"{profile.profile_name} (Imported)"
        profile.created_at = utc_now()
        profile.updated_at = profile.created_at
        self.save_profile(profile)
        if activate:
            self.set_active_profile(profile.profile_id)
        return profile

    def record_feedback(self, feedback: ClipFeedbackV2) -> Path:
        if len(feedback.notes) > self.max_note_chars:
            raise ValidationError(
                "Feedback note exceeds the configured limit.",
                details={"max_chars": self.max_note_chars},
            )
        path = self.feedback_dir / (
            f"feedback_{feedback.project_id}_{feedback.clip_id}_{feedback.feedback_id}.json"
        )
        with self._lock:
            self._write_json(path, feedback.model_dump(mode="json"))
        return path

    def list_feedback(self, profile_id: str | None = None) -> list[ClipFeedbackV2]:
        self.ensure_layout()
        feedback: list[ClipFeedbackV2] = []
        for path in sorted(self.feedback_dir.glob("*.json")):
            try:
                item = ClipFeedbackV2.model_validate(self._read_json(path))
            except (ValidationError, PydanticValidationError):
                continue
            if profile_id is None or item.profile_id == profile_id:
                feedback.append(item)
        return feedback
