"""Atomic local JSON persistence for BOBA project memory."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from olympus.boba.contracts import (
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaLearningNoteV1,
    BobaObservationV1,
)
from olympus.boba.memory import sanitize_memory_payload
from olympus.platform.errors import ValidationError

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ModelT = TypeVar("ModelT", bound=BaseModel)


class BobaMemoryStore:
    """Project-only BOBA memory; creator/global learning stays interface-level."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_excerpt_chars: int = 300,
        max_decisions_per_project: int = 500,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.max_excerpt_chars = max_excerpt_chars
        self.max_decisions_per_project = max_decisions_per_project
        self._lock = threading.RLock()

    def _project_dir(self, project_id: str) -> Path:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValidationError("Invalid BOBA project id.", details={"project_id": project_id})
        path = (self.root / "projects" / project_id).resolve()
        if self.root not in path.parents:
            raise ValidationError("Invalid BOBA project memory path.")
        return path

    def _path(self, project_id: str, name: str) -> Path:
        return self._project_dir(project_id) / name

    def _write(self, path: Path, payload: Any) -> None:
        safe = sanitize_memory_payload(payload, max_excerpt_chars=self.max_excerpt_chars)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temp.write_text(
                json.dumps(safe, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _read(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return default
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "BOBA project memory is unreadable.", details={"path": path.name}
            ) from exc

    def save_brain_state(self, state: BobaBrainStateV1) -> None:
        with self._lock:
            self._write(
                self._path(state.project_id, "brain_state.json"),
                {"schema_version": "boba_brain_state_v1", **state.model_dump(mode="json")},
            )

    def load_brain_state(self, project_id: str) -> BobaBrainStateV1 | None:
        raw = self._read(self._path(project_id, "brain_state.json"), None)
        if not isinstance(raw, dict):
            return None
        raw.pop("schema_version", None)
        return BobaBrainStateV1.model_validate(raw)

    def _append_model(
        self,
        project_id: str,
        filename: str,
        model: BaseModel,
        *,
        maximum: int = 500,
    ) -> None:
        with self._lock:
            path = self._path(project_id, filename)
            values = self._read(path, [])
            if not isinstance(values, list):
                raise ValidationError("BOBA memory list is corrupt.", details={"path": filename})
            values.append(model.model_dump(mode="json"))
            self._write(path, values[-maximum:])

    def _list_models(
        self,
        project_id: str,
        filename: str,
        model: type[ModelT],
    ) -> list[ModelT]:
        values = self._read(self._path(project_id, filename), [])
        if not isinstance(values, list):
            return []
        return [model.model_validate(value) for value in values if isinstance(value, dict)]

    def append_decision(self, decision: BobaDecisionV1) -> None:
        self._append_model(
            decision.project_id,
            "decisions.json",
            decision,
            maximum=self.max_decisions_per_project,
        )

    def list_decisions(self, project_id: str) -> list[BobaDecisionV1]:
        return self._list_models(project_id, "decisions.json", BobaDecisionV1)

    def append_observation(self, observation: BobaObservationV1) -> None:
        self._append_model(observation.project_id, "observations.json", observation)

    def list_observations(self, project_id: str) -> list[BobaObservationV1]:
        return self._list_models(project_id, "observations.json", BobaObservationV1)

    def append_learning_note(self, note: BobaLearningNoteV1) -> None:
        if note.learning_scope != "project":
            note.warnings = list(
                dict.fromkeys(
                    [*note.warnings, "Creator/global learning is interface-only in BOBA V1."]
                )
            )
        self._append_model(note.project_id, "learning_notes.json", note)

    def list_learning_notes(self, project_id: str) -> list[BobaLearningNoteV1]:
        return self._list_models(project_id, "learning_notes.json", BobaLearningNoteV1)

    def save_candidate_ranking(self, ranking: BobaClipRankingV1) -> None:
        with self._lock:
            self._write(
                self._path(ranking.project_id, "candidate_rankings.json"),
                {"schema_version": "boba_clip_ranking_v1", **ranking.model_dump(mode="json")},
            )

    def load_candidate_ranking(self, project_id: str) -> BobaClipRankingV1 | None:
        raw = self._read(self._path(project_id, "candidate_rankings.json"), None)
        if not isinstance(raw, dict):
            return None
        raw.pop("schema_version", None)
        return BobaClipRankingV1.model_validate(raw)

    def save_editorial_policy(self, policy: BobaEditorialPolicyV1) -> None:
        with self._lock:
            path = self._path(policy.project_id, "editorial_policies.json")
            values = self._read(path, {})
            if not isinstance(values, dict):
                values = {}
            values[policy.clip_id] = policy.model_dump(mode="json")
            self._write(path, values)

    def load_editorial_policy(
        self, project_id: str, clip_id: str
    ) -> BobaEditorialPolicyV1 | None:
        values = self._read(self._path(project_id, "editorial_policies.json"), {})
        raw = values.get(clip_id) if isinstance(values, dict) else None
        return BobaEditorialPolicyV1.model_validate(raw) if isinstance(raw, dict) else None
