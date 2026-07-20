"""Atomic local JSON persistence for BOBA project memory."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from olympus.boba.approvals import BobaApprovalEventV1, BobaApprovalTargetType
from olympus.boba.clip_discovery import BobaCandidateClipDiscoveryV1
from olympus.boba.contracts import (
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaLearningNoteV1,
    BobaObservationV1,
)
from olympus.boba.creative_director import BobaCreativeBriefV1
from olympus.boba.memory import sanitize_memory_payload
from olympus.boba.memory_contracts import (
    BobaCreatorMemoryV1,
    BobaGlobalMemoryV1,
    BobaMemoryQueryV1,
    BobaMemoryRecordV1,
    BobaMemoryRetrievalResultV1,
    BobaProjectMemoryV1,
    MemoryScope,
    memory_now_iso,
)
from olympus.boba.memory_validation import validate_memory_export, validate_memory_record
from olympus.boba.scout import BobaCandidateV1, BobaScoutScoreV1
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1
from olympus.platform.errors import ValidationError

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ModelT = TypeVar("ModelT", bound=BaseModel)


class BobaMemoryStore:
    """Atomic storage for BOBA Core state and BOBA Memory V1."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_excerpt_chars: int = 300,
        max_decisions_per_project: int = 500,
        memory_root: str | Path | None = None,
        max_records_per_project: int = 1000,
        max_records_per_creator: int = 5000,
        max_global_records: int = 10000,
        max_file_size_bytes: int = 10_000_000,
        allow_import_export: bool = True,
        backup_before_reset: bool = True,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.memory_root = (
            Path(memory_root).expanduser().resolve()
            if memory_root is not None
            else (self.root / "memory").resolve()
        )
        self.max_excerpt_chars = max_excerpt_chars
        self.max_decisions_per_project = max_decisions_per_project
        self.max_records_per_project = max_records_per_project
        self.max_records_per_creator = max_records_per_creator
        self.max_global_records = max_global_records
        self.max_file_size_bytes = max_file_size_bytes
        self.allow_import_export = allow_import_export
        self.backup_before_reset = backup_before_reset
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
        self._atomic_write(path, safe)

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
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

    def _scout_path(self, filename: str) -> Path:
        path = (self.root / "scout" / filename).resolve()
        if self.root not in path.parents:
            raise ValidationError("Invalid BOBA Scout storage path.")
        return path

    def save_scout_candidate(self, candidate: BobaCandidateV1) -> None:
        self._validate_memory_id(candidate.candidate_id, field="candidate_id")
        with self._lock:
            path = self._scout_path("candidates.json")
            values = self._read(path, {})
            if not isinstance(values, dict):
                raise ValidationError("BOBA Scout candidate storage is corrupt.")
            values[candidate.candidate_id] = candidate.model_dump(mode="json")
            self._write(path, values)

    def load_scout_candidate(self, candidate_id: str) -> BobaCandidateV1 | None:
        self._validate_memory_id(candidate_id, field="candidate_id")
        values = self._read(self._scout_path("candidates.json"), {})
        raw = values.get(candidate_id) if isinstance(values, dict) else None
        return BobaCandidateV1.model_validate(raw) if isinstance(raw, dict) else None

    def list_scout_candidates(self) -> list[BobaCandidateV1]:
        values = self._read(self._scout_path("candidates.json"), {})
        if not isinstance(values, dict):
            return []
        candidates = [
            BobaCandidateV1.model_validate(value)
            for value in values.values()
            if isinstance(value, dict)
        ]
        return sorted(candidates, key=lambda item: item.created_at, reverse=True)

    def save_scout_score(self, score: BobaScoutScoreV1) -> None:
        self._validate_memory_id(score.candidate_id, field="candidate_id")
        with self._lock:
            path = self._scout_path("scores.json")
            values = self._read(path, {})
            if not isinstance(values, dict):
                raise ValidationError("BOBA Scout score storage is corrupt.")
            values[score.candidate_id] = score.model_dump(mode="json")
            self._write(path, values)

    def load_scout_score(self, candidate_id: str) -> BobaScoutScoreV1 | None:
        self._validate_memory_id(candidate_id, field="candidate_id")
        values = self._read(self._scout_path("scores.json"), {})
        raw = values.get(candidate_id) if isinstance(values, dict) else None
        return BobaScoutScoreV1.model_validate(raw) if isinstance(raw, dict) else None

    def append_approval_event(self, event: BobaApprovalEventV1) -> None:
        self._validate_memory_id(event.event_id, field="event_id")
        self._validate_memory_id(event.target_id, field="target_id")
        with self._lock:
            path = self._scout_path("approval_events.json")
            values = self._read(path, [])
            if not isinstance(values, list):
                raise ValidationError("BOBA approval event storage is corrupt.")
            values.append(event.model_dump(mode="json"))
            self._write(path, values[-5000:])

    def list_approval_events(
        self,
        *,
        target_type: BobaApprovalTargetType | None = None,
        target_id: str | None = None,
    ) -> list[BobaApprovalEventV1]:
        values = self._read(self._scout_path("approval_events.json"), [])
        if not isinstance(values, list):
            return []
        events = [
            BobaApprovalEventV1.model_validate(value)
            for value in values
            if isinstance(value, dict)
        ]
        if target_type:
            events = [item for item in events if item.target_type == target_type]
        if target_id:
            events = [item for item in events if item.target_id == target_id]
        return sorted(events, key=lambda item: item.created_at, reverse=True)

    def save_creative_brief(self, brief: BobaCreativeBriefV1) -> None:
        self._validate_memory_id(brief.clip_id, field="clip_id")
        with self._lock:
            path = self._path(brief.project_id, "creative_briefs.json")
            values = self._read(path, {})
            if not isinstance(values, dict):
                raise ValidationError("BOBA creative brief storage is corrupt.")
            values[brief.clip_id] = brief.model_dump(mode="json")
            self._write(path, values)

    def list_creative_briefs(self, project_id: str) -> list[BobaCreativeBriefV1]:
        values = self._read(self._path(project_id, "creative_briefs.json"), {})
        if not isinstance(values, dict):
            return []
        return [
            BobaCreativeBriefV1.model_validate(value)
            for value in values.values()
            if isinstance(value, dict)
        ]

    def whole_video_understanding_path(self, project_id: str) -> Path:
        return self._path(project_id, "whole_video_understanding/index.json")

    def save_whole_video_understanding(
        self, understanding: BobaWholeVideoUnderstandingV1
    ) -> BobaWholeVideoUnderstandingV1:
        with self._lock:
            self._write(
                self.whole_video_understanding_path(understanding.project_id),
                understanding.model_dump(mode="json"),
            )
        return understanding

    def load_whole_video_understanding(
        self, project_id: str
    ) -> BobaWholeVideoUnderstandingV1 | None:
        raw = self._read(self.whole_video_understanding_path(project_id), None)
        return (
            BobaWholeVideoUnderstandingV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def candidate_clip_discovery_path(self, project_id: str) -> Path:
        return self._path(project_id, "candidate_clip_discovery/index.json")

    def save_candidate_clip_discovery(
        self, discovery: BobaCandidateClipDiscoveryV1
    ) -> BobaCandidateClipDiscoveryV1:
        with self._lock:
            self._write(
                self.candidate_clip_discovery_path(discovery.project_id),
                discovery.model_dump(mode="json"),
            )
        return discovery

    def load_candidate_clip_discovery(
        self, project_id: str
    ) -> BobaCandidateClipDiscoveryV1 | None:
        raw = self._read(self.candidate_clip_discovery_path(project_id), None)
        return (
            BobaCandidateClipDiscoveryV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    @staticmethod
    def _validate_memory_id(value: str, *, field: str) -> str:
        if not _PROJECT_ID.fullmatch(value):
            raise ValidationError(f"Invalid BOBA memory {field}.", details={field: value})
        return value

    def ensure_memory_layout(self) -> None:
        for relative in (
            "projects",
            "creators",
            "global",
            "indexes",
            "exports",
            "backups",
        ):
            (self.memory_root / relative).mkdir(parents=True, exist_ok=True)

    def _assert_memory_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.memory_root and self.memory_root not in resolved.parents:
            raise ValidationError("Invalid BOBA long-term memory path.")
        return resolved

    def _memory_scope_dir(self, scope: MemoryScope, identifier: str | None = None) -> Path:
        if scope == "project":
            if not identifier:
                raise ValidationError("project_id is required for project memory.")
            safe = self._validate_memory_id(identifier, field="project_id")
            return self._assert_memory_path(self.memory_root / "projects" / safe)
        if scope == "creator":
            if not identifier:
                raise ValidationError("creator_profile_id is required for creator memory.")
            safe = self._validate_memory_id(identifier, field="creator_profile_id")
            return self._assert_memory_path(self.memory_root / "creators" / safe)
        return self._assert_memory_path(self.memory_root / "global")

    def _memory_records_path(self, scope: MemoryScope, identifier: str | None = None) -> Path:
        return self._memory_scope_dir(scope, identifier) / "records.json"

    def _write_memory(self, path: Path, payload: dict[str, Any]) -> None:
        safe = validate_memory_export(payload, max_bytes=self.max_file_size_bytes)
        self._atomic_write(self._assert_memory_path(path), safe)

    def _read_memory(self, path: Path, default: Any) -> Any:
        safe_path = self._assert_memory_path(path)
        try:
            if safe_path.stat().st_size > self.max_file_size_bytes:
                raise ValidationError(
                    "BOBA memory file exceeds the configured size limit.",
                    details={"path": safe_path.name},
                )
            return json.loads(safe_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return default
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "BOBA memory JSON is corrupt.", details={"path": safe_path.name}
            ) from exc
        except OSError as exc:
            raise ValidationError(
                "BOBA memory could not be read.", details={"path": safe_path.name}
            ) from exc

    def _load_records_file(self, path: Path) -> list[BobaMemoryRecordV1]:
        raw = self._read_memory(path, {"records": []})
        values = (
            raw
            if isinstance(raw, list)
            else raw.get("records", [])
            if isinstance(raw, dict)
            else []
        )
        if not isinstance(values, list):
            raise ValidationError(
                "BOBA memory records file is corrupt.", details={"path": path.name}
            )
        records: list[BobaMemoryRecordV1] = []
        for value in values:
            if isinstance(value, dict):
                records.append(
                    validate_memory_record(value, max_excerpt_chars=self.max_excerpt_chars)
                )
        return records

    def _record_limit(self, scope: MemoryScope) -> int:
        if scope == "project":
            return self.max_records_per_project
        if scope == "creator":
            return self.max_records_per_creator
        return self.max_global_records

    @staticmethod
    def _record_identifier(record: BobaMemoryRecordV1) -> str | None:
        if record.scope == "project":
            return record.project_id
        if record.scope == "creator":
            return record.creator_profile_id
        return None

    def save_record(self, record: BobaMemoryRecordV1) -> BobaMemoryRecordV1:
        validated = validate_memory_record(record, max_excerpt_chars=self.max_excerpt_chars)
        identifier = self._record_identifier(validated)
        path = self._memory_records_path(validated.scope, identifier)
        with self._lock:
            records = self._load_records_file(path)
            existing = next(
                (item for item in records if item.memory_id == validated.memory_id), None
            )
            if existing is not None:
                validated.created_at = existing.created_at
                records = [item for item in records if item.memory_id != validated.memory_id]
            validated.updated_at = memory_now_iso()
            records.append(validated)
            maximum = self._record_limit(validated.scope)
            if len(records) > maximum:
                records = sorted(
                    records,
                    key=lambda item: (item.importance, item.confidence, item.updated_at),
                    reverse=True,
                )[:maximum]
            self._write_memory(
                path,
                {
                    "schema_version": "boba_memory_records_v1",
                    "records": [item.model_dump(mode="json") for item in records],
                },
            )
            self.rebuild_indexes()
        return validated

    def _record_files(self, scope: MemoryScope | None = None) -> list[Path]:
        self.ensure_memory_layout()
        files: list[Path] = []
        if scope in (None, "project"):
            files.extend(sorted((self.memory_root / "projects").glob("*/records.json")))
        if scope in (None, "creator"):
            files.extend(sorted((self.memory_root / "creators").glob("*/records.json")))
        if scope in (None, "global"):
            global_path = self.memory_root / "global" / "records.json"
            if global_path.exists():
                files.append(global_path)
        return files

    def get_record(self, memory_id: str) -> BobaMemoryRecordV1 | None:
        self._validate_memory_id(memory_id, field="memory_id")
        for path in self._record_files():
            for record in self._load_records_file(path):
                if record.memory_id == memory_id:
                    return record
        return None

    def list_records(
        self,
        scope: MemoryScope | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[BobaMemoryRecordV1]:
        filters = filters or {}
        records = [
            record
            for path in self._record_files(scope)
            for record in self._load_records_file(path)
        ]
        project_id = filters.get("project_id")
        creator_profile_id = filters.get("creator_profile_id")
        record_type = filters.get("record_type")
        tags = {str(item).lower() for item in filters.get("tags", [])}
        target_system = filters.get("target_system")
        if project_id:
            records = [item for item in records if item.project_id == project_id]
        if creator_profile_id:
            records = [item for item in records if item.creator_profile_id == creator_profile_id]
        if record_type:
            records = [item for item in records if item.record_type == record_type]
        if tags:
            records = [item for item in records if tags.intersection(item.tags)]
        if target_system:
            records = [item for item in records if target_system in item.applies_to]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def delete_record(self, memory_id: str) -> bool:
        self._validate_memory_id(memory_id, field="memory_id")
        with self._lock:
            for path in self._record_files():
                records = self._load_records_file(path)
                remaining = [item for item in records if item.memory_id != memory_id]
                if len(remaining) == len(records):
                    continue
                self._write_memory(
                    path,
                    {
                        "schema_version": "boba_memory_records_v1",
                        "records": [item.model_dump(mode="json") for item in remaining],
                    },
                )
                self.rebuild_indexes()
                return True
        return False

    def save_project_memory(self, project_memory: BobaProjectMemoryV1) -> BobaProjectMemoryV1:
        project_id = self._validate_memory_id(project_memory.project_id, field="project_id")
        path = self._memory_scope_dir("project", project_id) / "project_memory.json"
        existing = self.load_project_memory(project_id)
        saved = project_memory.model_copy(deep=True)
        if existing is not None:
            saved.created_at = existing.created_at
        saved.updated_at = memory_now_iso()
        with self._lock:
            self._write_memory(
                path,
                {
                    "schema_version": "boba_project_memory_v1",
                    "project_memory": saved.model_dump(mode="json"),
                },
            )
        return saved

    def load_project_memory(self, project_id: str) -> BobaProjectMemoryV1 | None:
        path = self._memory_scope_dir("project", project_id) / "project_memory.json"
        raw = self._read_memory(path, None)
        if not isinstance(raw, dict):
            return None
        value = raw.get("project_memory", raw)
        return BobaProjectMemoryV1.model_validate(value) if isinstance(value, dict) else None

    def save_creator_memory(self, creator_memory: BobaCreatorMemoryV1) -> BobaCreatorMemoryV1:
        profile_id = self._validate_memory_id(
            creator_memory.creator_profile_id, field="creator_profile_id"
        )
        path = self._memory_scope_dir("creator", profile_id) / "creator_memory.json"
        existing = self.load_creator_memory(profile_id)
        saved = creator_memory.model_copy(deep=True)
        if existing is not None:
            saved.created_at = existing.created_at
            saved.creator_memory_id = existing.creator_memory_id
        saved.updated_at = memory_now_iso()
        with self._lock:
            self._write_memory(
                path,
                {
                    "schema_version": "boba_creator_memory_v1",
                    "creator_memory": saved.model_dump(mode="json"),
                },
            )
        return saved

    def load_creator_memory(self, profile_id: str) -> BobaCreatorMemoryV1 | None:
        path = self._memory_scope_dir("creator", profile_id) / "creator_memory.json"
        raw = self._read_memory(path, None)
        if not isinstance(raw, dict):
            return None
        value = raw.get("creator_memory", raw)
        return BobaCreatorMemoryV1.model_validate(value) if isinstance(value, dict) else None

    def save_global_memory(self, global_memory: BobaGlobalMemoryV1) -> BobaGlobalMemoryV1:
        path = self._memory_scope_dir("global") / "global_memory.json"
        existing = self.load_global_memory()
        saved = global_memory.model_copy(deep=True)
        if existing is not None:
            saved.created_at = existing.created_at
            saved.global_memory_id = existing.global_memory_id
        saved.updated_at = memory_now_iso()
        with self._lock:
            self._write_memory(
                path,
                {
                    "schema_version": "boba_global_memory_v1",
                    "global_memory": saved.model_dump(mode="json"),
                },
            )
        return saved

    def load_global_memory(self) -> BobaGlobalMemoryV1 | None:
        path = self._memory_scope_dir("global") / "global_memory.json"
        raw = self._read_memory(path, None)
        if not isinstance(raw, dict):
            return None
        value = raw.get("global_memory", raw)
        return BobaGlobalMemoryV1.model_validate(value) if isinstance(value, dict) else None

    def query_memory(self, query: BobaMemoryQueryV1) -> BobaMemoryRetrievalResultV1:
        from olympus.boba.memory_retrieval import retrieve_memory

        return retrieve_memory(self, query)

    def export_memory(
        self, scope: MemoryScope | None = None, identifier: str | None = None
    ) -> dict[str, Any]:
        if not self.allow_import_export:
            raise ValidationError("BOBA memory export is disabled by configuration.")
        if identifier:
            self._validate_memory_id(identifier, field="identifier")
        filters: dict[str, Any] = {}
        if scope == "project" and identifier:
            filters["project_id"] = identifier
        if scope == "creator" and identifier:
            filters["creator_profile_id"] = identifier
        records = self.list_records(scope, filters)
        payload: dict[str, Any] = {
            "schema_version": "boba_memory_export_v1",
            "exported_at": memory_now_iso(),
            "scope": scope,
            "identifier": identifier,
            "records": [item.model_dump(mode="json") for item in records],
        }
        if scope in (None, "project"):
            if identifier:
                project = self.load_project_memory(identifier)
                payload["project_memory"] = (
                    project.model_dump(mode="json") if project else None
                )
            else:
                project_memories: list[dict[str, Any]] = []
                for path in sorted((self.memory_root / "projects").glob("*")):
                    if not path.is_dir():
                        continue
                    project_memory_item = self.load_project_memory(path.name)
                    if project_memory_item is not None:
                        project_memories.append(
                            project_memory_item.model_dump(mode="json")
                        )
                payload["project_memories"] = project_memories
        if scope in (None, "creator"):
            if identifier:
                creator = self.load_creator_memory(identifier)
                payload["creator_memory"] = (
                    creator.model_dump(mode="json") if creator else None
                )
            else:
                creator_memories: list[dict[str, Any]] = []
                for path in sorted((self.memory_root / "creators").glob("*")):
                    if not path.is_dir():
                        continue
                    creator_memory_item = self.load_creator_memory(path.name)
                    if creator_memory_item is not None:
                        creator_memories.append(
                            creator_memory_item.model_dump(mode="json")
                        )
                payload["creator_memories"] = creator_memories
        if scope in (None, "global"):
            global_memory = self.load_global_memory()
            payload["global_memory"] = (
                global_memory.model_dump(mode="json") if global_memory else None
            )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_identifier = identifier or "all"
        filename = f"boba_memory_{scope or 'all'}_{safe_identifier}_{stamp}.json"
        payload["export_filename"] = filename
        safe = validate_memory_export(payload, max_bytes=self.max_file_size_bytes)
        self._write_memory(self.memory_root / "exports" / filename, safe)
        return safe

    def import_memory(self, source: dict[str, Any] | str | Path) -> dict[str, int]:
        if not self.allow_import_export:
            raise ValidationError("BOBA memory import is disabled by configuration.")
        if isinstance(source, dict):
            payload = source
        else:
            path = Path(source).expanduser().resolve()
            exports_root = (self.memory_root / "exports").resolve()
            if exports_root not in path.parents:
                raise ValidationError(
                    "BOBA memory imports must come from the local exports folder."
                )
            payload = self._read_memory(path, None)
        if not isinstance(payload, dict):
            raise ValidationError("BOBA memory import payload must be an object.")
        safe = validate_memory_export(payload, max_bytes=self.max_file_size_bytes)
        if safe.get("schema_version") != "boba_memory_export_v1":
            raise ValidationError("Unsupported BOBA memory export schema.")
        counts = {"records": 0, "project_memories": 0, "creator_memories": 0, "global_memories": 0}
        for value in safe.get("records", []):
            if isinstance(value, dict):
                self.save_record(BobaMemoryRecordV1.model_validate(value))
                counts["records"] += 1
        if isinstance(safe.get("project_memory"), dict):
            self.save_project_memory(BobaProjectMemoryV1.model_validate(safe["project_memory"]))
            counts["project_memories"] += 1
        for value in safe.get("project_memories", []):
            if isinstance(value, dict):
                self.save_project_memory(BobaProjectMemoryV1.model_validate(value))
                counts["project_memories"] += 1
        if isinstance(safe.get("creator_memory"), dict):
            self.save_creator_memory(BobaCreatorMemoryV1.model_validate(safe["creator_memory"]))
            counts["creator_memories"] += 1
        for value in safe.get("creator_memories", []):
            if isinstance(value, dict):
                self.save_creator_memory(BobaCreatorMemoryV1.model_validate(value))
                counts["creator_memories"] += 1
        if isinstance(safe.get("global_memory"), dict):
            self.save_global_memory(BobaGlobalMemoryV1.model_validate(safe["global_memory"]))
            counts["global_memories"] += 1
        self.rebuild_indexes()
        return counts

    def _reset_scope(self, path: Path, label: str) -> Path | None:
        safe_path = self._assert_memory_path(path)
        if not safe_path.exists():
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup: Path | None = None
        if self.backup_before_reset:
            backup = self._assert_memory_path(
                self.memory_root / "backups" / f"{label}_{stamp}_{uuid4().hex[:8]}"
            )
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(safe_path, backup)
        else:
            shutil.rmtree(safe_path)
        self.rebuild_indexes()
        return backup

    def reset_project_memory(self, project_id: str) -> Path | None:
        with self._lock:
            return self._reset_scope(
                self._memory_scope_dir("project", project_id), f"project_{project_id}"
            )

    def reset_creator_memory(self, profile_id: str) -> Path | None:
        with self._lock:
            return self._reset_scope(
                self._memory_scope_dir("creator", profile_id), f"creator_{profile_id}"
            )

    def reset_global_memory(self) -> Path | None:
        with self._lock:
            return self._reset_scope(self._memory_scope_dir("global"), "global")

    def rebuild_indexes(self) -> dict[str, dict[str, list[str]]]:
        self.ensure_memory_layout()
        by_scope: dict[str, list[str]] = {"project": [], "creator": [], "global": []}
        by_project: dict[str, list[str]] = {}
        by_creator: dict[str, list[str]] = {}
        by_tag: dict[str, list[str]] = {}
        for path in self._record_files():
            for record in self._load_records_file(path):
                by_scope[record.scope].append(record.memory_id)
                if record.project_id:
                    by_project.setdefault(record.project_id, []).append(record.memory_id)
                if record.creator_profile_id:
                    by_creator.setdefault(record.creator_profile_id, []).append(record.memory_id)
                for tag in record.tags:
                    by_tag.setdefault(tag, []).append(record.memory_id)
        indexes: dict[str, dict[str, list[str]]] = {
            "by_scope": by_scope,
            "by_project": by_project,
            "by_creator": by_creator,
            "by_tag": by_tag,
        }
        for name, values in indexes.items():
            self._write_memory(
                self.memory_root / "indexes" / f"{name}.json",
                {"schema_version": "boba_memory_index_v1", "index": values},
            )
        return indexes
