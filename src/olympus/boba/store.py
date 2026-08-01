"""Atomic local JSON persistence for BOBA project memory."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from olympus.boba.approval_rejection_learning import (
    BobaApprovalRejectionLearningSetV1,
)
from olympus.boba.approvals import BobaApprovalEventV1, BobaApprovalTargetType
from olympus.boba.autopilot_controller import (
    BobaAutopilotControllerSetV1,
    BobaAutopilotEventV1,
    BobaAutopilotProjectLockV1,
    sanitize_autopilot_export,
)
from olympus.boba.candidate_video_scorer import BobaCandidateVideoScorerSetV1
from olympus.boba.caption_motion import BobaCaptionMotionRecommendationSetV1
from olympus.boba.clip_brief import BobaClipBriefSetV1
from olympus.boba.clip_discovery import BobaCandidateClipDiscoveryV1
from olympus.boba.clip_ranking import (
    BobaClipRankingV1 as BobaDiscoveryClipRankingV1,
)
from olympus.boba.code_surgeon import BobaCodeSurgeonSetV1
from olympus.boba.content_scout import BobaContentScoutSetV2
from olympus.boba.contracts import (
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaLearningNoteV1,
    BobaObservationV1,
)
from olympus.boba.creative_director import (
    BobaCreativeBriefV1,
    BobaCreativeDirectionSetV2,
)
from olympus.boba.creator_learning import (
    BobaCreatorFeedbackEventV1,
    BobaCreatorLearningSetV1,
)
from olympus.boba.editorial_decision import BobaEditorialDecisionSetV1
from olympus.boba.error_doctor import BobaErrorDoctorSetV1
from olympus.boba.experimentation import (
    BobaExperimentationSetV1,
    BobaExperimentManualResultV1,
)
from olympus.boba.explanation import BobaExplanationSetV1
from olympus.boba.hook_retention import BobaHookRetentionSetV1
from olympus.boba.integration_layer import (
    BobaIntegrationEventV1,
    BobaIntegrationIdempotencyRecordV1,
    BobaIntegrationLayerSetV1,
    BobaIntegrationRegistrySnapshotV1,
    BobaIntegrationTransactionV1,
    sanitize_integration_export,
)
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
from olympus.boba.music_mood import BobaMusicMoodRecommendationSetV1
from olympus.boba.observer import BobaObserverSetV1
from olympus.boba.output_quality_reviewer import (
    BobaOutputQualityReviewerSetV1,
    sanitize_review_export,
)
from olympus.boba.performance_feedback import (
    BobaPerformanceFeedbackEventV1,
    BobaPerformanceFeedbackSetV1,
)
from olympus.boba.repair_planner import BobaRepairPlannerSetV1
from olympus.boba.research_brain import BobaResearchBrainSetV1
from olympus.boba.rights_permission_gate import (
    BobaRightsPermissionGateSetV1,
)
from olympus.boba.root_cause_analyzer import BobaRootCauseAnalyzerSetV1
from olympus.boba.safety_gate import (
    BobaSafetyDecisionV1,
    BobaSafetyEvaluationCaseV1,
    BobaSafetyGateSetV1,
    sanitize_safety_export,
)
from olympus.boba.scout import BobaCandidateV1, BobaScoutScoreV1
from olympus.boba.tool_recovery import BobaToolRecoveryBrainSetV1
from olympus.boba.trend_topic_watcher import BobaTrendTopicWatcherSetV1
from olympus.boba.validator_runner import (
    BobaValidationEventV1,
    BobaValidationLeaseV1,
    BobaValidatorRunnerSetV1,
    sanitize_validator_export,
)
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1
from olympus.boba.workflow_controller import (
    BobaWorkflowControllerSetV1,
    BobaWorkflowDefinitionSnapshotV1,
    BobaWorkflowEventV1,
    BobaWorkflowExecutionLeaseV1,
    BobaWorkflowStageDefinitionV1,
    sanitize_workflow_export,
)
from olympus.platform.errors import ValidationError

_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ModelT = TypeVar("ModelT", bound=BaseModel)


def _sanitize_code_surgeon_payload(value: Any, *, max_excerpt_chars: int) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_code_surgeon_payload(
                item,
                max_excerpt_chars=max_excerpt_chars,
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [
            _sanitize_code_surgeon_payload(
                item,
                max_excerpt_chars=max_excerpt_chars,
            )
            for item in value
        ]
    return sanitize_memory_payload(
        value,
        max_excerpt_chars=max_excerpt_chars,
        path="boba.code_surgeon.value",
    )


def _sanitize_tool_recovery_payload(value: Any, *, max_excerpt_chars: int) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_tool_recovery_payload(
                item,
                max_excerpt_chars=max_excerpt_chars,
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [
            _sanitize_tool_recovery_payload(
                item,
                max_excerpt_chars=max_excerpt_chars,
            )
            for item in value
        ]
    return sanitize_memory_payload(
        value,
        max_excerpt_chars=max_excerpt_chars,
        path="boba.tool_recovery.value",
    )


def _sanitize_output_quality_payload(
    value: Any,
    *,
    max_excerpt_chars: int,
) -> Any:
    return sanitize_memory_payload(
        sanitize_review_export(value),
        max_excerpt_chars=max_excerpt_chars,
        path="boba.output_quality_reviewer.value",
    )


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
    def _atomic_write_text(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write_compact(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
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

    def clip_ranking_path(self, project_id: str) -> Path:
        return self._path(project_id, "clip_ranking/index.json")

    def save_clip_ranking(
        self, ranking: BobaDiscoveryClipRankingV1
    ) -> BobaDiscoveryClipRankingV1:
        with self._lock:
            self._write(
                self.clip_ranking_path(ranking.project_id),
                ranking.model_dump(mode="json"),
            )
        return ranking

    def load_clip_ranking(
        self, project_id: str
    ) -> BobaDiscoveryClipRankingV1 | None:
        raw = self._read(self.clip_ranking_path(project_id), None)
        return (
            BobaDiscoveryClipRankingV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def editorial_decision_path(self, project_id: str) -> Path:
        return self._path(project_id, "editorial_decision/index.json")

    def save_editorial_decisions(
        self, decisions: BobaEditorialDecisionSetV1
    ) -> BobaEditorialDecisionSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                decisions.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_000),
            )
            self._atomic_write(self.editorial_decision_path(decisions.project_id), safe)
        return decisions

    def load_editorial_decisions(
        self, project_id: str
    ) -> BobaEditorialDecisionSetV1 | None:
        raw = self._read(self.editorial_decision_path(project_id), None)
        return (
            BobaEditorialDecisionSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def explanation_path(self, project_id: str) -> Path:
        return self._path(project_id, "explanation/index.json")

    def save_explanations(
        self, explanations: BobaExplanationSetV1
    ) -> BobaExplanationSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                explanations.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(self.explanation_path(explanations.project_id), safe)
        return explanations

    def load_explanations(self, project_id: str) -> BobaExplanationSetV1 | None:
        raw = self._read(self.explanation_path(project_id), None)
        return BobaExplanationSetV1.model_validate(raw) if isinstance(raw, dict) else None

    def creative_direction_v2_path(self, project_id: str) -> Path:
        return self._path(project_id, "creative_direction_v2/index.json")

    def save_creative_direction_v2(
        self, direction: BobaCreativeDirectionSetV2
    ) -> BobaCreativeDirectionSetV2:
        with self._lock:
            safe = sanitize_memory_payload(
                direction.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(self.creative_direction_v2_path(direction.project_id), safe)
        return direction

    def load_creative_direction_v2(
        self, project_id: str
    ) -> BobaCreativeDirectionSetV2 | None:
        raw = self._read(self.creative_direction_v2_path(project_id), None)
        return (
            BobaCreativeDirectionSetV2.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def clip_briefs_path(self, project_id: str) -> Path:
        return self._path(project_id, "clip_briefs/index.json")

    def save_clip_briefs(self, briefs: BobaClipBriefSetV1) -> BobaClipBriefSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                briefs.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(self.clip_briefs_path(briefs.project_id), safe)
        return briefs

    def load_clip_briefs(self, project_id: str) -> BobaClipBriefSetV1 | None:
        raw = self._read(self.clip_briefs_path(project_id), None)
        return BobaClipBriefSetV1.model_validate(raw) if isinstance(raw, dict) else None

    def hook_retention_path(self, project_id: str) -> Path:
        return self._path(project_id, "hook_retention/index.json")

    def save_hook_retention(
        self, analysis: BobaHookRetentionSetV1
    ) -> BobaHookRetentionSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                analysis.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(self.hook_retention_path(analysis.project_id), safe)
        return analysis

    def load_hook_retention(
        self, project_id: str
    ) -> BobaHookRetentionSetV1 | None:
        raw = self._read(self.hook_retention_path(project_id), None)
        return BobaHookRetentionSetV1.model_validate(raw) if isinstance(raw, dict) else None

    def caption_motion_path(self, project_id: str) -> Path:
        return self._path(project_id, "caption_motion/index.json")

    def save_caption_motion(
        self,
        recommendations: BobaCaptionMotionRecommendationSetV1,
    ) -> BobaCaptionMotionRecommendationSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                recommendations.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(
                self.caption_motion_path(recommendations.project_id),
                safe,
            )
        return recommendations

    def load_caption_motion(
        self,
        project_id: str,
    ) -> BobaCaptionMotionRecommendationSetV1 | None:
        raw = self._read(self.caption_motion_path(project_id), None)
        return (
            BobaCaptionMotionRecommendationSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def music_mood_path(self, project_id: str) -> Path:
        return self._path(project_id, "music_mood/index.json")

    def save_music_mood(
        self,
        recommendations: BobaMusicMoodRecommendationSetV1,
    ) -> BobaMusicMoodRecommendationSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                recommendations.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(
                self.music_mood_path(recommendations.project_id),
                safe,
            )
        return recommendations

    def load_music_mood(
        self,
        project_id: str,
    ) -> BobaMusicMoodRecommendationSetV1 | None:
        raw = self._read(self.music_mood_path(project_id), None)
        return (
            BobaMusicMoodRecommendationSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def experimentation_path(self, project_id: str) -> Path:
        return self._path(project_id, "experimentation/index.json")

    def experimentation_results_path(self, project_id: str) -> Path:
        return self._path(project_id, "experimentation/results.jsonl")

    def save_experimentation_plan(
        self,
        experimentation: BobaExperimentationSetV1,
    ) -> BobaExperimentationSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                experimentation.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(
                self.experimentation_path(experimentation.project_id),
                safe,
            )
        return experimentation

    def load_experimentation_plan(
        self,
        project_id: str,
    ) -> BobaExperimentationSetV1 | None:
        raw = self._read(self.experimentation_path(project_id), None)
        return (
            BobaExperimentationSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def record_manual_experiment_result(
        self,
        project_id: str,
        result: BobaExperimentManualResultV1,
    ) -> BobaExperimentManualResultV1:
        safe_payload = sanitize_memory_payload(
            result.model_dump(mode="json"),
            max_excerpt_chars=max(self.max_excerpt_chars, 500),
        )
        safe_result = BobaExperimentManualResultV1.model_validate(safe_payload)
        with self._lock:
            results = self.list_manual_experiment_results(project_id)
            existing = next(
                (item for item in results if item.result_id == result.result_id),
                None,
            )
            if existing is not None:
                return existing
            results.append(safe_result)
            lines = [
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                for item in results[-500:]
            ]
            self._atomic_write_text(
                self.experimentation_results_path(project_id),
                "\n".join(lines) + "\n",
            )
        return safe_result

    def list_manual_experiment_results(
        self,
        project_id: str,
    ) -> list[BobaExperimentManualResultV1]:
        path = self.experimentation_results_path(project_id)
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ValidationError(
                "BOBA manual experiment result storage could not be read.",
                details={"path": path.name},
            ) from exc
        results: list[BobaExperimentManualResultV1] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                results.append(BobaExperimentManualResultV1.model_validate(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValidationError(
                    "BOBA manual experiment result storage is corrupt.",
                    details={"path": path.name, "line": line_number},
                ) from exc
        return results

    def export_experimentation_plan(self, project_id: str) -> dict[str, Any]:
        experimentation = self.load_experimentation_plan(project_id)
        if experimentation is None:
            raise ValidationError(
                "BOBA experimentation plan is not available for export.",
                details={"project_id": project_id},
            )
        manual_results = [
            item.model_dump(mode="json", exclude={"creator_note"})
            for item in self.list_manual_experiment_results(project_id)
        ]
        payload = {
            "schema_version": "boba_experimentation_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "experimentation": experimentation.model_dump(mode="json"),
            "manual_results": manual_results,
            "privacy": {
                "advisory_plans_only": True,
                "manual_results_only": True,
                "manual_notes_excluded": True,
                "media_files_excluded": True,
                "source_text_excluded": True,
                "credentials_excluded": True,
                "viewer_analytics_excluded": True,
            },
        }
        safe = sanitize_memory_payload(
            payload,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA experimentation export is invalid.")
        return safe

    def reset_experimentation_plan(self, project_id: str) -> bool:
        paths = (
            self.experimentation_path(project_id),
            self.experimentation_results_path(project_id),
        )
        removed = False
        with self._lock:
            for path in paths:
                if path.exists():
                    path.unlink()
                    removed = True
            directory = self.experimentation_path(project_id).parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def performance_feedback_path(self, project_id: str) -> Path:
        return self._path(project_id, "performance_feedback/index.json")

    def performance_feedback_events_path(self, project_id: str) -> Path:
        return self._path(project_id, "performance_feedback/events.jsonl")

    def save_performance_feedback(
        self,
        feedback: BobaPerformanceFeedbackSetV1,
    ) -> BobaPerformanceFeedbackSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                feedback.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(
                self.performance_feedback_path(feedback.project_id),
                safe,
            )
        return feedback

    def load_performance_feedback(
        self,
        project_id: str,
    ) -> BobaPerformanceFeedbackSetV1 | None:
        raw = self._read(self.performance_feedback_path(project_id), None)
        return (
            BobaPerformanceFeedbackSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def record_performance_feedback_event(
        self,
        event: BobaPerformanceFeedbackEventV1,
    ) -> BobaPerformanceFeedbackEventV1:
        safe_payload = sanitize_memory_payload(
            event.model_dump(mode="json"),
            max_excerpt_chars=max(self.max_excerpt_chars, 500),
        )
        safe_event = BobaPerformanceFeedbackEventV1.model_validate(safe_payload)
        with self._lock:
            events = self.list_performance_feedback_events(event.project_id)
            existing = next(
                (item for item in events if item.event_id == event.event_id),
                None,
            )
            if existing is not None:
                return existing
            events.append(safe_event)
            lines = [
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                for item in events[-5000:]
            ]
            self._atomic_write_text(
                self.performance_feedback_events_path(event.project_id),
                "\n".join(lines) + "\n",
            )
        return safe_event

    def list_performance_feedback_events(
        self,
        project_id: str,
    ) -> list[BobaPerformanceFeedbackEventV1]:
        path = self.performance_feedback_events_path(project_id)
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ValidationError(
                "BOBA performance feedback event storage could not be read.",
                details={"path": path.name},
            ) from exc
        events: list[BobaPerformanceFeedbackEventV1] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                events.append(BobaPerformanceFeedbackEventV1.model_validate(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValidationError(
                    "BOBA performance feedback event storage is corrupt.",
                    details={"path": path.name, "line": line_number},
                ) from exc
        return events

    def export_performance_feedback(self, project_id: str) -> dict[str, Any]:
        feedback = self.load_performance_feedback(project_id)
        if feedback is None:
            raise ValidationError(
                "BOBA performance feedback is not available for export.",
                details={"project_id": project_id},
            )
        payload = feedback.model_dump(mode="json")
        for event in payload.get("performance_events", []):
            if isinstance(event, dict):
                event.pop("creator_note", None)
                event.pop("retention_notes", None)
                event.pop("creator_interpretation", None)
        for snapshot in payload.get("performance_snapshots", []):
            if isinstance(snapshot, dict):
                snapshot.pop("creator_notes", None)
                snapshot.pop("retention_notes", None)
        for outcome in payload.get("experiment_outcomes", []):
            if not isinstance(outcome, dict):
                continue
            for field in ("likely_success_factors", "likely_failure_factors"):
                for factor in outcome.get(field, []):
                    if isinstance(factor, dict):
                        factor.pop("evidence", None)
        pattern_summary = payload.get("pattern_summary", {})
        if isinstance(pattern_summary, dict):
            for field in (
                "strongest_positive_patterns",
                "strongest_negative_patterns",
            ):
                for factor in pattern_summary.get(field, []):
                    if isinstance(factor, dict):
                        factor.pop("evidence", None)
        export = {
            "schema_version": "boba_performance_feedback_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "performance_feedback": payload,
            "privacy": {
                "manual_input_only": True,
                "manual_notes_excluded": True,
                "media_files_excluded": True,
                "source_text_excluded": True,
                "credentials_excluded": True,
                "platform_connections_used": False,
                "automatic_collection_used": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA performance feedback export is invalid.")
        return safe

    def reset_performance_feedback(self, project_id: str) -> bool:
        paths = (
            self.performance_feedback_path(project_id),
            self.performance_feedback_events_path(project_id),
        )
        removed = False
        with self._lock:
            for path in paths:
                if path.exists():
                    path.unlink()
                    removed = True
            directory = self.performance_feedback_path(project_id).parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def content_scout_v2_path(self, project_id: str) -> Path:
        return self._path(project_id, "content_scout_v2/index.json")

    def save_content_scout_v2(
        self,
        scout: BobaContentScoutSetV2,
    ) -> BobaContentScoutSetV2:
        with self._lock:
            safe = sanitize_memory_payload(
                scout.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(self.content_scout_v2_path(scout.project_id), safe)
        return scout

    def load_content_scout_v2(
        self,
        project_id: str,
    ) -> BobaContentScoutSetV2 | None:
        raw = self._read(self.content_scout_v2_path(project_id), None)
        return (
            BobaContentScoutSetV2.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def export_content_scout_v2(self, project_id: str) -> dict[str, Any]:
        scout = self.load_content_scout_v2(project_id)
        if scout is None:
            raise ValidationError(
                "BOBA Content Scout V2 is not available for export.",
                details={"project_id": project_id},
            )
        payload = scout.model_dump(mode="json")
        for source in payload.get("imported_sources", []):
            if isinstance(source, dict):
                source.pop("source_path", None)
        for item in payload.get("scout_items", []):
            if isinstance(item, dict):
                item.pop("source_url", None)
                item.pop("permission_notes", None)
                item.pop("user_notes", None)
                item.pop("raw_metadata_summary", None)
        for recommendation_group in (
            "top_items",
            "backup_items",
            "permission_needed_items",
            "blocked_items",
            "duplicate_or_similar_items",
        ):
            values = payload.get("review_queue", {}).get(
                recommendation_group,
                [],
            )
            for recommendation in values:
                if isinstance(recommendation, dict):
                    recommendation["suggested_review_questions"] = []
        export = {
            "schema_version": "boba_content_scout_export_v2",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "content_scout_v2": payload,
            "privacy": {
                "metadata_only": True,
                "local_paths_excluded": True,
                "source_urls_excluded": True,
                "user_notes_excluded": True,
                "media_files_excluded": True,
                "source_text_excluded": True,
                "credentials_excluded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "downloading_used": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Content Scout V2 export is invalid.")
        return safe

    def reset_content_scout_v2(self, project_id: str) -> bool:
        path = self.content_scout_v2_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def research_brain_path(self, project_id: str) -> Path:
        return self._path(project_id, "research_brain/index.json")

    def save_research_brain(
        self,
        research: BobaResearchBrainSetV1,
    ) -> BobaResearchBrainSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                research.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 700),
            )
            self._atomic_write(self.research_brain_path(research.project_id), safe)
        return research

    def load_research_brain(
        self,
        project_id: str,
    ) -> BobaResearchBrainSetV1 | None:
        raw = self._read(self.research_brain_path(project_id), None)
        return (
            BobaResearchBrainSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def export_research_brain(self, project_id: str) -> dict[str, Any]:
        research = self.load_research_brain(project_id)
        if research is None:
            raise ValidationError(
                "BOBA Research Brain V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = research.model_dump(mode="json")
        for source in payload.get("imported_sources", []):
            if isinstance(source, dict):
                source.pop("source_path", None)
        for source in payload.get("research_sources", []):
            if isinstance(source, dict):
                source.pop("rights_usage_notes", None)
                source.pop("user_notes", None)
        export = {
            "schema_version": "boba_research_brain_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "research_brain": payload,
            "privacy": {
                "local_paths_excluded": True,
                "raw_source_content_excluded": True,
                "full_transcripts_excluded": True,
                "media_files_excluded": True,
                "user_notes_excluded": True,
                "credentials_excluded": True,
                "evidence_snippets_bounded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "scraping_used": False,
                "downloading_used": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 700),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Research Brain V1 export is invalid.")
        return safe

    def reset_research_brain(self, project_id: str) -> bool:
        path = self.research_brain_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def trend_topic_watcher_path(self, project_id: str) -> Path:
        return self._path(project_id, "trend_topic_watcher/index.json")

    def save_trend_topic_watcher(
        self,
        watcher: BobaTrendTopicWatcherSetV1,
    ) -> BobaTrendTopicWatcherSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                watcher.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
            )
            self._atomic_write(
                self.trend_topic_watcher_path(watcher.project_id),
                safe,
            )
        return watcher

    def load_trend_topic_watcher(
        self,
        project_id: str,
    ) -> BobaTrendTopicWatcherSetV1 | None:
        raw = self._read(self.trend_topic_watcher_path(project_id), None)
        return (
            BobaTrendTopicWatcherSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def export_trend_topic_watcher(self, project_id: str) -> dict[str, Any]:
        watcher = self.load_trend_topic_watcher(project_id)
        if watcher is None:
            raise ValidationError(
                "BOBA Trend / Topic Watcher V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = watcher.model_dump(mode="json")
        for source in payload.get("imported_sources", []):
            if isinstance(source, dict):
                source.pop("source_path", None)
        for snapshot in payload.get("topic_snapshots", []):
            if not isinstance(snapshot, dict):
                continue
            snapshot.pop("source_notes", None)
            for entry in snapshot.get("topics", []):
                if isinstance(entry, dict):
                    entry.pop("evidence_note", None)
                    entry.pop("rights_safety_note", None)
        export = {
            "schema_version": "boba_trend_topic_watcher_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "trend_topic_watcher": payload,
            "privacy": {
                "local_paths_excluded": True,
                "private_notes_excluded": True,
                "raw_source_content_excluded": True,
                "full_transcripts_excluded": True,
                "media_files_excluded": True,
                "credentials_excluded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "scraping_used": False,
                "platform_monitoring_used": False,
                "downloading_used": False,
                "not_real_time_verified": True,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_200),
        )
        if not isinstance(safe, dict):
            raise ValidationError(
                "BOBA Trend / Topic Watcher V1 export is invalid."
            )
        return safe

    def reset_trend_topic_watcher(self, project_id: str) -> bool:
        path = self.trend_topic_watcher_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def candidate_video_scorer_path(self, project_id: str) -> Path:
        return self._path(project_id, "candidate_video_scorer/index.json")

    def save_candidate_video_scorer(
        self,
        scorer: BobaCandidateVideoScorerSetV1,
    ) -> BobaCandidateVideoScorerSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                scorer.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(
                self.candidate_video_scorer_path(scorer.project_id),
                safe,
            )
        return scorer

    def load_candidate_video_scorer(
        self,
        project_id: str,
    ) -> BobaCandidateVideoScorerSetV1 | None:
        raw = self._read(self.candidate_video_scorer_path(project_id), None)
        return (
            BobaCandidateVideoScorerSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def export_candidate_video_scorer(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        scorer = self.load_candidate_video_scorer(project_id)
        if scorer is None:
            raise ValidationError(
                "BOBA Candidate Video Scorer V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = scorer.model_dump(mode="json")
        for source in payload.get("imported_sources", []):
            if isinstance(source, dict):
                source.pop("source_path", None)

        def redact_candidate(candidate: Any) -> None:
            if not isinstance(candidate, dict):
                return
            for field_name in (
                "source_url",
                "permission_notes",
                "user_notes",
                "raw_metadata_summary",
            ):
                candidate.pop(field_name, None)

        for candidate in payload.get("candidate_videos", []):
            redact_candidate(candidate)
        for scored in payload.get("scored_candidates", []):
            if isinstance(scored, dict):
                redact_candidate(scored.get("candidate_video"))
        export = {
            "schema_version": "boba_candidate_video_scorer_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "candidate_video_scorer": payload,
            "privacy": {
                "local_paths_excluded": True,
                "source_urls_excluded": True,
                "private_notes_excluded": True,
                "raw_metadata_excluded": True,
                "raw_source_content_excluded": True,
                "full_transcripts_excluded": True,
                "media_files_excluded": True,
                "credentials_excluded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "scraping_used": False,
                "downloading_used": False,
                "media_ingestion_used": False,
                "copyright_safety_confirmed": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError(
                "BOBA Candidate Video Scorer V1 export is invalid."
            )
        return safe

    def reset_candidate_video_scorer(self, project_id: str) -> bool:
        path = self.candidate_video_scorer_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def rights_permission_gate_path(self, project_id: str) -> Path:
        return self._path(project_id, "rights_permission_gate/index.json")

    def save_rights_permission_gate(
        self,
        gate: BobaRightsPermissionGateSetV1,
    ) -> BobaRightsPermissionGateSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                gate.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(
                self.rights_permission_gate_path(gate.project_id),
                safe,
            )
        return gate

    def load_rights_permission_gate(
        self,
        project_id: str,
    ) -> BobaRightsPermissionGateSetV1 | None:
        raw = self._read(self.rights_permission_gate_path(project_id), None)
        return (
            BobaRightsPermissionGateSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def export_rights_permission_gate(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        gate = self.load_rights_permission_gate(project_id)
        if gate is None:
            raise ValidationError(
                "BOBA Rights + Permission Gate V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = gate.model_dump(mode="json")
        for item in payload.get("reviewed_items", []):
            if not isinstance(item, dict):
                continue
            for field_name in (
                "source_reference",
                "source_url",
                "permission_notes",
                "license_notes",
                "ownership_notes",
                "platform_source_notes",
                "source_artifact_refs",
                "evidence_snippets",
            ):
                item.pop(field_name, None)
        export = {
            "schema_version": "boba_rights_permission_gate_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "rights_permission_gate": payload,
            "privacy": {
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
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError(
                "BOBA Rights + Permission Gate V1 export is invalid."
            )
        return safe

    def reset_rights_permission_gate(self, project_id: str) -> bool:
        path = self.rights_permission_gate_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def observer_path(self, project_id: str) -> Path:
        return self._path(project_id, "observer/index.json")

    def save_observer_report(
        self,
        report: BobaObserverSetV1,
    ) -> BobaObserverSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                report.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(self.observer_path(report.project_id), safe)
        return report

    def load_observer_report(
        self,
        project_id: str,
    ) -> BobaObserverSetV1 | None:
        raw = self._read(self.observer_path(project_id), None)
        return (
            BobaObserverSetV1.model_validate(raw)
            if isinstance(raw, dict)
            else None
        )

    def export_observer_report(self, project_id: str) -> dict[str, Any]:
        report = self.load_observer_report(project_id)
        if report is None:
            raise ValidationError(
                "BOBA Observer V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = report.model_dump(mode="json")
        for artifact in payload.get("artifact_observations", []):
            if not isinstance(artifact, dict):
                continue
            artifact.pop("expected_path", None)
            for finding in artifact.get("findings", []):
                if isinstance(finding, dict):
                    finding.pop("evidence", None)
        for module in payload.get("module_health_observations", []):
            if not isinstance(module, dict):
                continue
            for finding in module.get("findings", []):
                if isinstance(finding, dict):
                    finding.pop("evidence", None)
        for workflow in payload.get("workflow_observations", []):
            if not isinstance(workflow, dict):
                continue
            for finding in workflow.get("findings", []):
                if isinstance(finding, dict):
                    finding.pop("evidence", None)
        for validation in payload.get("validation_observations", []):
            if isinstance(validation, dict):
                validation.pop("report_path", None)
        export = {
            "schema_version": "boba_observer_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "observer": payload,
            "privacy": {
                "private_paths_excluded": True,
                "finding_evidence_excluded": True,
                "raw_artifact_content_excluded": True,
                "full_transcripts_excluded": True,
                "media_files_excluded": True,
                "credentials_excluded": True,
                "command_logs_excluded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "scraping_used": False,
                "downloading_used": False,
                "command_execution_used": False,
                "code_modification_used": False,
                "destructive_action_used": False,
                "validator_execution_used": False,
                "rendering_used": False,
                "media_ingestion_used": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Observer V1 export is invalid.")
        return safe

    def reset_observer_report(self, project_id: str) -> bool:
        path = self.observer_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def error_doctor_path(self, project_id: str) -> Path:
        return self._path(project_id, "error_doctor/index.json")

    def save_boba_error_doctor(
        self,
        report: BobaErrorDoctorSetV1,
    ) -> BobaErrorDoctorSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                report.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(self.error_doctor_path(report.project_id), safe)
        return report

    def load_boba_error_doctor(
        self,
        project_id: str,
    ) -> BobaErrorDoctorSetV1 | None:
        try:
            raw = self._read(self.error_doctor_path(project_id), None)
            return (
                BobaErrorDoctorSetV1.model_validate(raw)
                if isinstance(raw, dict)
                else None
            )
        except (PydanticValidationError, ValidationError):
            return None

    def export_boba_error_doctor(self, project_id: str) -> dict[str, Any]:
        report = self.load_boba_error_doctor(project_id)
        if report is None:
            raise ValidationError(
                "BOBA Error Doctor V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = report.model_dump(mode="json")
        for collection_name in ("diagnostic_cases", "classified_findings"):
            collection = payload.get(collection_name, [])
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, dict):
                    continue
                evidence_items = item.get("evidence", [])
                if not isinstance(evidence_items, list):
                    continue
                for evidence in evidence_items:
                    if not isinstance(evidence, dict):
                        continue
                    evidence.pop("observed_value", None)
                    evidence.pop("expected_value", None)
                    evidence.pop("timestamp", None)
        export = {
            "schema_version": "boba_error_doctor_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "error_doctor": payload,
            "privacy": {
                "private_paths_excluded": True,
                "full_evidence_values_excluded": True,
                "raw_logs_excluded": True,
                "observer_report_excluded": True,
                "full_transcripts_excluded": True,
                "media_files_excluded": True,
                "credentials_excluded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "scraping_used": False,
                "downloading_used": False,
                "command_execution_used": False,
                "code_modification_used": False,
                "artifact_modification_used": False,
                "destructive_action_used": False,
                "validator_execution_used": False,
                "rendering_used": False,
                "media_ingestion_used": False,
                "repairs_applied": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Error Doctor V1 export is invalid.")
        return safe

    def reset_boba_error_doctor(self, project_id: str) -> bool:
        path = self.error_doctor_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def root_cause_analyzer_path(self, project_id: str) -> Path:
        return self._path(project_id, "root_cause_analyzer/index.json")

    def save_boba_root_cause_analyzer(
        self,
        report: BobaRootCauseAnalyzerSetV1,
    ) -> BobaRootCauseAnalyzerSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                report.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(
                self.root_cause_analyzer_path(report.project_id),
                safe,
            )
        return report

    def load_boba_root_cause_analyzer(
        self,
        project_id: str,
    ) -> BobaRootCauseAnalyzerSetV1 | None:
        try:
            raw = self._read(self.root_cause_analyzer_path(project_id), None)
            return (
                BobaRootCauseAnalyzerSetV1.model_validate(raw)
                if isinstance(raw, dict)
                else None
            )
        except (PydanticValidationError, ValidationError):
            return None

    def export_boba_root_cause_analyzer(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        report = self.load_boba_root_cause_analyzer(project_id)
        if report is None:
            raise ValidationError(
                "BOBA Root Cause Analyzer V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = report.model_dump(mode="json")
        evidence_items = payload.get("evidence", [])
        if isinstance(evidence_items, list):
            for evidence in evidence_items:
                if not isinstance(evidence, dict):
                    continue
                evidence.pop("observed_value", None)
                evidence.pop("expected_value", None)
                evidence.pop("observed_at", None)
        for timeline in payload.get("failure_timelines", []):
            if not isinstance(timeline, dict):
                continue
            for event in timeline.get("events", []):
                if isinstance(event, dict):
                    event.pop("observed_at", None)
        export = {
            "schema_version": "boba_root_cause_analyzer_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "root_cause_analyzer": payload,
            "privacy": {
                "private_paths_excluded": True,
                "full_evidence_values_excluded": True,
                "raw_logs_excluded": True,
                "error_doctor_report_excluded": True,
                "observer_report_excluded": True,
                "full_transcripts_excluded": True,
                "media_files_excluded": True,
                "credentials_excluded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "scraping_used": False,
                "downloading_used": False,
                "command_execution_used": False,
                "validator_execution_used": False,
                "code_modification_used": False,
                "artifact_modification_used": False,
                "repair_execution_used": False,
                "tool_fallback_execution_used": False,
                "destructive_action_used": False,
                "rendering_used": False,
                "media_ingestion_used": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError(
                "BOBA Root Cause Analyzer V1 export is invalid."
            )
        return safe

    def reset_boba_root_cause_analyzer(self, project_id: str) -> bool:
        path = self.root_cause_analyzer_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def repair_planner_path(self, project_id: str) -> Path:
        return self._path(project_id, "repair_planner/index.json")

    def save_boba_repair_planner(
        self,
        report: BobaRepairPlannerSetV1,
    ) -> BobaRepairPlannerSetV1:
        with self._lock:
            safe = sanitize_memory_payload(
                report.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(
                self.repair_planner_path(report.project_id),
                safe,
            )
        return report

    def load_boba_repair_planner(
        self,
        project_id: str,
    ) -> BobaRepairPlannerSetV1 | None:
        try:
            raw = self._read(self.repair_planner_path(project_id), None)
            return (
                BobaRepairPlannerSetV1.model_validate(raw)
                if isinstance(raw, dict)
                else None
            )
        except (PydanticValidationError, ValidationError):
            return None

    def export_boba_repair_planner(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        report = self.load_boba_repair_planner(project_id)
        if report is None:
            raise ValidationError(
                "BOBA Repair Planner V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = report.model_dump(mode="json")
        for strategy in payload.get("repair_strategies", []):
            if isinstance(strategy, dict):
                strategy.pop("previously_attempted_strategies", None)
        export = {
            "schema_version": "boba_repair_planner_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "repair_planner": payload,
            "privacy": {
                "private_paths_excluded": True,
                "sensitive_evidence_excluded": True,
                "manual_context_excluded": True,
                "root_cause_analyzer_report_excluded": True,
                "error_doctor_report_excluded": True,
                "observer_report_excluded": True,
                "raw_logs_excluded": True,
                "full_transcripts_excluded": True,
                "media_files_excluded": True,
                "credentials_excluded": True,
                "external_api_used": False,
                "url_fetching_used": False,
                "scraping_used": False,
                "downloading_used": False,
                "command_execution_used": False,
                "validator_execution_used": False,
                "code_modification_used": False,
                "artifact_modification_used": False,
                "repair_execution_used": False,
                "tool_fallback_execution_used": False,
                "workflow_resume_used": False,
                "service_restart_used": False,
                "package_installation_used": False,
                "destructive_action_used": False,
                "rendering_used": False,
                "media_ingestion_used": False,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Repair Planner V1 export is invalid.")
        return safe

    def reset_boba_repair_planner(self, project_id: str) -> bool:
        path = self.repair_planner_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def code_surgeon_path(self, project_id: str) -> Path:
        return self._path(project_id, "code_surgeon/index.json")

    def code_surgeon_run_path(self, project_id: str, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", run_id):
            raise ValidationError("Invalid BOBA Code Surgeon run id.")
        return self._path(project_id, f"code_surgeon/runs/{run_id}/index.json")

    def code_surgeon_patch_path(self, project_id: str, reference_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", reference_id):
            raise ValidationError("Invalid BOBA Code Surgeon patch reference.")
        return self._path(project_id, f"code_surgeon/runs/{reference_id}/patch.diff")

    def save_boba_code_surgeon(
        self,
        report: BobaCodeSurgeonSetV1,
        *,
        unified_diff: str | None = None,
        patch_proposal_id: str | None = None,
    ) -> BobaCodeSurgeonSetV1:
        with self._lock:
            safe = _sanitize_code_surgeon_payload(
                report.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
            )
            self._atomic_write(self.code_surgeon_path(report.project_id), safe)
            if report.isolated_runs:
                run = report.isolated_runs[-1]
                run_payload = {
                    "schema_version": "boba_code_surgeon_run_v1",
                    "project_id": report.project_id,
                    "isolated_run": run.model_dump(mode="json"),
                    "validation_run": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.validation_runs)
                            if item.isolated_run_id == run.isolated_run_id
                        ),
                        None,
                    ),
                    "rollback_record": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.rollback_records)
                            if item.isolated_run_id == run.isolated_run_id
                        ),
                        None,
                    ),
                    "review_package": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.review_packages)
                            if item.isolated_run_id == run.isolated_run_id
                        ),
                        None,
                    ),
                }
                self._atomic_write(
                    self.code_surgeon_run_path(report.project_id, run.isolated_run_id),
                    _sanitize_code_surgeon_payload(
                        run_payload,
                        max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
                    ),
                )
            if unified_diff is not None:
                reference_id = patch_proposal_id or (
                    report.patch_proposals[-1].patch_proposal_id
                    if report.patch_proposals
                    else ""
                )
                if not reference_id:
                    raise ValidationError(
                        "A patch proposal id is required to store a Code Surgeon diff."
                    )
                if len(unified_diff.encode("utf-8")) > 2_000_000:
                    raise ValidationError("Code Surgeon diff exceeds the hard storage limit.")
                self._atomic_write_text(
                    self.code_surgeon_patch_path(report.project_id, reference_id),
                    unified_diff,
                )
        return report

    def load_boba_code_surgeon(
        self,
        project_id: str,
    ) -> BobaCodeSurgeonSetV1 | None:
        try:
            raw = self._read(self.code_surgeon_path(project_id), None)
            return (
                BobaCodeSurgeonSetV1.model_validate(raw)
                if isinstance(raw, dict)
                else None
            )
        except (PydanticValidationError, ValidationError):
            return None

    def load_boba_code_surgeon_patch(
        self,
        project_id: str,
        patch_proposal_id: str,
    ) -> str:
        path = self.code_surgeon_patch_path(project_id, patch_proposal_id)
        try:
            if path.stat().st_size > 2_000_000:
                raise ValidationError("Stored Code Surgeon diff exceeds the hard limit.")
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValidationError(
                "Stored Code Surgeon diff is unavailable.",
                details={
                    "project_id": project_id,
                    "patch_proposal_id": patch_proposal_id,
                },
            ) from exc
        except OSError as exc:
            raise ValidationError("Stored Code Surgeon diff could not be read.") from exc

    def export_boba_code_surgeon(self, project_id: str) -> dict[str, Any]:
        report = self.load_boba_code_surgeon(project_id)
        if report is None:
            raise ValidationError(
                "BOBA Code Surgeon V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = report.model_dump(mode="json")
        for run in payload.get("isolated_runs", []):
            if isinstance(run, dict):
                run["sanitized_worktree_reference"] = str(
                    run.get("sanitized_worktree_reference", "")
                ).replace("\\", "/")
        export = {
            "schema_version": "boba_code_surgeon_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "code_surgeon": payload,
            "privacy": {
                "full_unified_diffs_excluded": True,
                "unbounded_logs_excluded": True,
                "private_absolute_paths_excluded": True,
                "credentials_excluded": True,
                "repair_planner_report_excluded": True,
                "root_cause_analyzer_report_excluded": True,
                "external_api_used": False,
                "network_access_used": False,
                "push_used": False,
                "remote_pr_created": False,
                "merge_used": False,
                "tag_used": False,
                "package_installation_used": False,
                "service_restart_used": False,
                "destructive_git_used": False,
            },
        }
        safe = _sanitize_code_surgeon_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 1_500),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Code Surgeon V1 export is invalid.")
        return safe

    def reset_boba_code_surgeon(self, project_id: str) -> bool:
        report = self.load_boba_code_surgeon(project_id)
        if report and any(
            run.worktree_created
            and run.run_status
            in {
                "worktree_ready",
                "patch_applied",
                "validation_running",
                "validation_passed",
                "local_commit_prepared",
            }
            for run in report.isolated_runs
        ):
            raise ValidationError(
                "Code Surgeon metadata cannot be reset while an isolated worktree "
                "may still require review or explicit cleanup."
            )
        directory = self.code_surgeon_path(project_id).parent.resolve()
        project_directory = self._project_dir(project_id).resolve()
        if directory.parent != project_directory or directory.name != "code_surgeon":
            raise ValidationError("Invalid BOBA Code Surgeon reset path.")
        with self._lock:
            if not directory.exists():
                return False
            shutil.rmtree(directory)
        return True

    def tool_recovery_path(self, project_id: str) -> Path:
        return self._path(project_id, "tool_recovery/index.json")

    def tool_recovery_run_path(self, project_id: str, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", run_id):
            raise ValidationError("Invalid BOBA Tool Recovery run id.")
        return self._path(project_id, f"tool_recovery/runs/{run_id}/index.json")

    def save_boba_tool_recovery(
        self,
        report: BobaToolRecoveryBrainSetV1,
    ) -> BobaToolRecoveryBrainSetV1:
        with self._lock:
            safe = _sanitize_tool_recovery_payload(
                report.model_dump(mode="json"),
                max_excerpt_chars=max(self.max_excerpt_chars, 2_000),
            )
            self._atomic_write(self.tool_recovery_path(report.project_id), safe)
            if report.recovery_attempts:
                attempt = report.recovery_attempts[-1]
                run_payload = {
                    "schema_version": "boba_tool_recovery_run_v1",
                    "project_id": report.project_id,
                    "recovery_attempt": attempt.model_dump(mode="json"),
                    "output_validation": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.output_validations)
                            if item.recovery_attempt_id
                            == attempt.recovery_attempt_id
                        ),
                        None,
                    ),
                    "rollback_record": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.rollback_records)
                            if item.recovery_attempt_id
                            == attempt.recovery_attempt_id
                        ),
                        None,
                    ),
                    "recovery_handoffs": [
                        item.model_dump(mode="json")
                        for item in report.recovery_handoffs
                        if item.recovery_attempt_id
                        == attempt.recovery_attempt_id
                    ],
                }
                self._atomic_write(
                    self.tool_recovery_run_path(
                        report.project_id,
                        attempt.recovery_attempt_id,
                    ),
                    _sanitize_tool_recovery_payload(
                        run_payload,
                        max_excerpt_chars=max(self.max_excerpt_chars, 2_000),
                    ),
                )
        return report

    def load_boba_tool_recovery(
        self,
        project_id: str,
    ) -> BobaToolRecoveryBrainSetV1 | None:
        try:
            raw = self._read(self.tool_recovery_path(project_id), None)
            return (
                BobaToolRecoveryBrainSetV1.model_validate(raw)
                if isinstance(raw, dict)
                else None
            )
        except (PydanticValidationError, ValidationError):
            return None

    def export_boba_tool_recovery(self, project_id: str) -> dict[str, Any]:
        report = self.load_boba_tool_recovery(project_id)
        if report is None:
            raise ValidationError(
                "BOBA Tool Recovery Brain V1 is not available for export.",
                details={"project_id": project_id},
            )
        payload = report.model_dump(mode="json")
        for attempt in payload.get("recovery_attempts", []):
            if not isinstance(attempt, dict):
                continue
            attempt["failure_summary"] = str(
                attempt.get("failure_summary") or ""
            )[:500]
            for command in attempt.get("command_records", []):
                if isinstance(command, dict):
                    command["arguments"] = [
                        str(item)[:300]
                        for item in command.get("arguments", [])[:128]
                    ]
        export = {
            "schema_version": "boba_tool_recovery_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "tool_recovery": payload,
            "privacy": {
                "private_absolute_paths_excluded": True,
                "unbounded_command_output_excluded": True,
                "credentials_excluded": True,
                "raw_source_media_excluded": True,
                "generated_media_excluded": True,
                "repair_planner_report_excluded": True,
                "network_access_used": False,
                "external_api_used": False,
                "package_installation_used": False,
                "service_restart_used": False,
                "process_kill_used": False,
                "code_modification_used": False,
                "workflow_resume_used": False,
                "source_media_modified": False,
                "completed_outputs_modified": False,
            },
        }
        safe = _sanitize_tool_recovery_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 2_000),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Tool Recovery Brain V1 export is invalid.")
        return safe

    def reset_boba_tool_recovery(self, project_id: str) -> bool:
        report = self.load_boba_tool_recovery(project_id)
        if report and any(
            attempt.status == "running" for attempt in report.recovery_attempts
        ):
            raise ValidationError(
                "Tool Recovery metadata cannot be reset while an attempt is running."
            )
        directory = self.tool_recovery_path(project_id).parent.resolve()
        project_directory = self._project_dir(project_id).resolve()
        if directory.parent != project_directory or directory.name != "tool_recovery":
            raise ValidationError("Invalid BOBA Tool Recovery reset path.")
        with self._lock:
            if not directory.exists():
                return False
            shutil.rmtree(directory)
        return True

    def output_quality_reviewer_path(self, project_id: str) -> Path:
        return self._path(project_id, "output_quality_reviewer/index.json")

    def output_quality_reviewer_review_path(
        self,
        project_id: str,
        review_id: str,
    ) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", review_id):
            raise ValidationError("Invalid BOBA Output Quality Reviewer review id.")
        return self._path(
            project_id,
            f"output_quality_reviewer/reviews/{review_id}/index.json",
        )

    def save_boba_output_quality_reviewer(
        self,
        report: BobaOutputQualityReviewerSetV1,
    ) -> BobaOutputQualityReviewerSetV1:
        payload = report.model_dump(mode="json")
        safe = _sanitize_output_quality_payload(
            payload,
            max_excerpt_chars=max(self.max_excerpt_chars, 2_000),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Output Quality Reviewer V1 report is invalid.")
        with self._lock:
            self._atomic_write_compact(
                self.output_quality_reviewer_path(report.project_id),
                safe,
            )
            if report.review_cases:
                review_case = report.review_cases[-1]
                review_id = review_case.review_case_id
                review_payload = {
                    "schema_version": "boba_output_quality_review_record_v1",
                    "project_id": report.project_id,
                    "source_id": report.source_id,
                    "review_case": review_case.model_dump(mode="json"),
                    "output_artifacts": [
                        item.model_dump(mode="json")
                        for item in report.output_artifacts
                        if item.output_artifact_id
                        in {
                            review_case.output_artifact_id,
                            review_case.baseline_artifact_id,
                        }
                    ],
                    "quality_evidence": [
                        item.model_dump(mode="json")
                        for item in report.quality_evidence
                        if item.source_id == review_id
                        or item.evidence_id
                        in {
                            evidence_id
                            for check in report.technical_assessments
                            if check.review_case_id == review_id
                            for item in check.checks
                            for evidence_id in item.evidence_ids
                        }
                    ],
                    "technical_assessment": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.technical_assessments)
                            if item.review_case_id == review_id
                        ),
                        None,
                    ),
                    "creative_assessment": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.creative_assessments)
                            if item.review_case_id == review_id
                        ),
                        None,
                    ),
                    "baseline_comparison": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.baseline_comparisons)
                            if item.review_case_id == review_id
                        ),
                        None,
                    ),
                    "quality_regressions": [
                        item.model_dump(mode="json")
                        for item in report.quality_regressions
                        if item.review_case_id == review_id
                    ],
                    "quality_issues": [
                        item.model_dump(mode="json")
                        for item in report.quality_issues
                        if item.review_case_id == review_id
                    ],
                    "acceptance_decision": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.acceptance_decisions)
                            if item.review_case_id == review_id
                        ),
                        None,
                    ),
                    "human_review_package": next(
                        (
                            item.model_dump(mode="json")
                            for item in reversed(report.human_review_packages)
                            if item.review_case_id == review_id
                        ),
                        None,
                    ),
                    "review_handoffs": [
                        item.model_dump(mode="json")
                        for item in report.review_handoffs
                        if item.review_case_id == review_id
                    ],
                    "signal_usage": report.signal_usage.model_dump(mode="json"),
                    "warnings": review_case.warnings,
                    "limitations": review_case.limitations,
                }
                safe_review = _sanitize_output_quality_payload(
                    review_payload,
                    max_excerpt_chars=max(self.max_excerpt_chars, 2_000),
                )
                self._atomic_write_compact(
                    self.output_quality_reviewer_review_path(
                        report.project_id,
                        review_id,
                    ),
                    safe_review,
                )
        return report

    def load_boba_output_quality_reviewer(
        self,
        project_id: str,
    ) -> BobaOutputQualityReviewerSetV1 | None:
        try:
            raw = self._read(self.output_quality_reviewer_path(project_id), None)
            return (
                BobaOutputQualityReviewerSetV1.model_validate(raw)
                if isinstance(raw, dict)
                else None
            )
        except (PydanticValidationError, ValidationError):
            return None

    def export_boba_output_quality_reviewer(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        report = self.load_boba_output_quality_reviewer(project_id)
        if report is None:
            raise ValidationError(
                "BOBA Output Quality Reviewer V1 is not available for export.",
                details={"project_id": project_id},
            )
        export = {
            "schema_version": "boba_output_quality_reviewer_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "output_quality_reviewer": report.model_dump(mode="json"),
            "privacy": {
                "private_absolute_paths_excluded": True,
                "sensitive_evidence_excluded": True,
                "full_command_logs_excluded": True,
                "credentials_excluded": True,
                "raw_source_media_excluded": True,
                "generated_media_excluded": True,
                "output_modified": False,
                "source_media_modified": False,
                "workflow_resume_used": False,
                "rendering_used": False,
                "fallback_execution_used": False,
                "external_api_used": False,
                "network_access_used": False,
                "uploading_used": False,
                "publication_used": False,
                "rights_bypass_used": False,
                "safety_bypass_used": False,
                "destructive_action_used": False,
            },
        }
        safe = _sanitize_output_quality_payload(
            export,
            max_excerpt_chars=max(self.max_excerpt_chars, 2_000),
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Output Quality Reviewer V1 export is invalid.")
        return safe

    def reset_boba_output_quality_reviewer(self, project_id: str) -> bool:
        directory = self.output_quality_reviewer_path(project_id).parent.resolve()
        project_directory = self._project_dir(project_id).resolve()
        if (
            directory.parent != project_directory
            or directory.name != "output_quality_reviewer"
        ):
            raise ValidationError("Invalid BOBA Output Quality Reviewer reset path.")
        with self._lock:
            if not directory.exists():
                return False
            shutil.rmtree(directory)
        return True

    def boba_autopilot_controller_path(self, project_id: str) -> Path:
        return self._path(project_id, "autopilot_controller/index.json")

    def boba_autopilot_run_path(self, project_id: str, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", run_id):
            raise ValidationError("Invalid BOBA Autopilot run id.")
        return self._path(
            project_id,
            f"autopilot_controller/runs/{run_id}/index.json",
        )

    def boba_autopilot_events_path(self, project_id: str, run_id: str) -> Path:
        return self.boba_autopilot_run_path(project_id, run_id).with_name(
            "events.jsonl"
        )

    def boba_autopilot_lock_path(self, project_id: str) -> Path:
        return self._path(project_id, "autopilot_controller/active.lock.json")

    @staticmethod
    def _autopilot_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def load_boba_autopilot_lock(
        self,
        project_id: str,
    ) -> BobaAutopilotProjectLockV1 | None:
        path = self.boba_autopilot_lock_path(project_id)
        raw = self._read(path, None)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValidationError("BOBA Autopilot lock metadata is malformed.")
        try:
            lock = BobaAutopilotProjectLockV1.model_validate(raw)
        except PydanticValidationError as exc:
            raise ValidationError(
                "BOBA Autopilot lock metadata is malformed."
            ) from exc
        expires_at = self._autopilot_time(lock.expires_at)
        lock.stale = expires_at is None or expires_at <= datetime.now(UTC)
        if lock.stale and "Lease is stale and requires explicit confirmation." not in (
            lock.warnings
        ):
            lock.warnings.append(
                "Lease is stale and requires explicit confirmation."
            )
        return lock

    def acquire_boba_autopilot_lock(
        self,
        project_id: str,
        *,
        run_id: str,
        owner_identifier: str,
        mode: str,
        lease_seconds: int = 300,
        confirm_stale: bool = False,
    ) -> BobaAutopilotProjectLockV1:
        path = self.boba_autopilot_lock_path(project_id)
        lease_seconds = max(30, min(int(lease_seconds), 900))
        with self._lock:
            existing = self.load_boba_autopilot_lock(project_id)
            if existing is not None and not existing.stale:
                if (
                    existing.run_id == run_id
                    and existing.owner_identifier == owner_identifier
                ):
                    return self.refresh_boba_autopilot_lock(
                        project_id,
                        run_id=run_id,
                        owner_identifier=owner_identifier,
                        lease_seconds=lease_seconds,
                    )
                raise ValidationError(
                    "A BOBA Autopilot project lease is already active.",
                    details={"active_run_id": existing.run_id},
                )
            stale_warning: list[str] = []
            if existing is not None:
                if not confirm_stale:
                    raise ValidationError(
                        "A stale BOBA Autopilot lease requires explicit confirmation.",
                        details={"stale_run_id": existing.run_id},
                    )
                stale_copy = path.with_name(
                    f"active.lock.stale.{uuid4().hex}.json"
                )
                with suppress(FileNotFoundError):
                    os.replace(path, stale_copy)
                stale_warning = [
                    f"Confirmed stale lease from run {existing.run_id} was preserved."
                ]
            now = datetime.now(UTC)
            lock = BobaAutopilotProjectLockV1(
                project_id=project_id,
                run_id=run_id,
                acquired_at=now.isoformat(),
                refreshed_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
                owner_identifier=owner_identifier,
                mode=mode,
                warnings=stale_warning,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8", newline="\n") as handle:
                    json.dump(
                        lock.model_dump(mode="json"),
                        handle,
                        indent=2,
                        ensure_ascii=False,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError as exc:
                raise ValidationError(
                    "A BOBA Autopilot project lease was acquired concurrently."
                ) from exc
            return lock

    def refresh_boba_autopilot_lock(
        self,
        project_id: str,
        *,
        run_id: str,
        owner_identifier: str,
        lease_seconds: int = 300,
        confirm_stale: bool = False,
    ) -> BobaAutopilotProjectLockV1:
        with self._lock:
            lock = self.load_boba_autopilot_lock(project_id)
            if lock is None:
                raise ValidationError("BOBA Autopilot project lease is missing.")
            if lock.run_id != run_id or lock.owner_identifier != owner_identifier:
                raise ValidationError(
                    "BOBA Autopilot project lease belongs to another run or owner."
                )
            if lock.stale and not confirm_stale:
                raise ValidationError(
                    "A stale BOBA Autopilot lease requires explicit confirmation."
                )
            now = datetime.now(UTC)
            lock.refreshed_at = now.isoformat()
            lock.expires_at = (
                now + timedelta(seconds=max(30, min(int(lease_seconds), 900)))
            ).isoformat()
            lock.stale = False
            self._atomic_write(
                self.boba_autopilot_lock_path(project_id),
                lock.model_dump(mode="json"),
            )
            return lock

    def release_boba_autopilot_lock(
        self,
        project_id: str,
        *,
        run_id: str,
        owner_identifier: str,
    ) -> bool:
        path = self.boba_autopilot_lock_path(project_id)
        with self._lock:
            lock = self.load_boba_autopilot_lock(project_id)
            if lock is None:
                return False
            if lock.run_id != run_id or lock.owner_identifier != owner_identifier:
                raise ValidationError(
                    "BOBA Autopilot lease release did not match its run and owner."
                )
            path.unlink(missing_ok=True)
            return True

    def _append_boba_autopilot_events(
        self,
        project_id: str,
        run_id: str,
        events: list[BobaAutopilotEventV1],
    ) -> None:
        path = self.boba_autopilot_events_path(project_id, run_id)
        existing_ids: set[str] = set()
        if path.exists():
            try:
                for line in path.read_text(encoding="utf-8-sig").splitlines():
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(raw, dict) and raw.get("event_id"):
                        existing_ids.add(str(raw["event_id"]))
            except OSError as exc:
                raise ValidationError(
                    "BOBA Autopilot event stream is unreadable."
                ) from exc
        new_events = [item for item in events if item.event_id not in existing_ids]
        if not new_events:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for event in new_events:
                safe = sanitize_autopilot_export(event.model_dump(mode="json"))
                handle.write(
                    json.dumps(
                        safe,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def load_boba_autopilot_events(
        self,
        project_id: str,
        run_id: str,
    ) -> list[BobaAutopilotEventV1]:
        path = self.boba_autopilot_events_path(project_id, run_id)
        if not path.exists():
            controller = self.load_boba_autopilot_controller(project_id)
            return (
                [
                    item
                    for item in controller.event_stream
                    if item.run_id == run_id
                ]
                if controller is not None
                else []
            )
        events: list[BobaAutopilotEventV1] = []
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                try:
                    raw = json.loads(line)
                    events.append(BobaAutopilotEventV1.model_validate(raw))
                except (json.JSONDecodeError, PydanticValidationError):
                    continue
        except OSError as exc:
            raise ValidationError(
                "BOBA Autopilot event stream is unreadable."
            ) from exc
        return sorted(events, key=lambda item: item.sequence)

    @staticmethod
    def _autopilot_run_payload(
        controller: BobaAutopilotControllerSetV1,
        run_id: str,
    ) -> dict[str, Any]:
        budget_ids = {
            item.budget_id
            for item in controller.recovery_budgets
            if item.run_id == run_id
        }
        return {
            "schema_version": "boba_autopilot_run_record_v1",
            "project_id": controller.project_id,
            "run": next(
                (
                    item.model_dump(mode="json")
                    for item in controller.runs
                    if item.run_id == run_id
                ),
                None,
            ),
            "project_snapshots": [
                item.model_dump(mode="json")
                for item in controller.project_snapshots
                if any(
                    run.run_id == run_id
                    and run.project_snapshot_id == item.project_snapshot_id
                    for run in controller.runs
                )
            ],
            "state_transitions": [
                item.model_dump(mode="json")
                for item in controller.state_transitions
                if item.run_id == run_id
            ],
            "planned_actions": [
                item.model_dump(mode="json")
                for item in controller.planned_actions
                if item.run_id == run_id
            ],
            "module_invocations": [
                item.model_dump(mode="json")
                for item in controller.module_invocations
                if item.run_id == run_id
            ],
            "approval_bindings": [
                item.model_dump(mode="json")
                for item in controller.approval_bindings
                if item.run_id == run_id
            ],
            "recovery_budgets": [
                item.model_dump(mode="json")
                for item in controller.recovery_budgets
                if item.run_id == run_id
            ],
            "budget_usages": [
                item.model_dump(mode="json")
                for item in controller.budget_usages
                if item.budget_id in budget_ids
            ],
            "checkpoint_requirements": [
                item.model_dump(mode="json")
                for item in controller.checkpoint_requirements
                if item.run_id == run_id
            ],
            "incidents": [
                item.model_dump(mode="json")
                for item in controller.incidents
                if item.run_id == run_id
            ],
            "decisions": [
                item.model_dump(mode="json")
                for item in controller.decisions
                if item.run_id == run_id
            ],
            "handoffs": [
                item.model_dump(mode="json")
                for item in controller.handoffs
                if item.run_id == run_id
            ],
            "signal_usage": controller.signal_usage.model_dump(mode="json"),
        }

    def save_boba_autopilot_controller(
        self,
        controller: BobaAutopilotControllerSetV1,
    ) -> BobaAutopilotControllerSetV1:
        with self._lock:
            payload = {
                "schema_version": "boba_autopilot_controller_record_v1",
                "autopilot_controller": controller.model_dump(mode="json"),
            }
            safe = sanitize_autopilot_export(payload)
            self._atomic_write_compact(
                self.boba_autopilot_controller_path(controller.project_id),
                safe,
            )
            for run in controller.runs:
                run_payload = sanitize_autopilot_export(
                    self._autopilot_run_payload(controller, run.run_id)
                )
                self._atomic_write_compact(
                    self.boba_autopilot_run_path(
                        controller.project_id,
                        run.run_id,
                    ),
                    run_payload,
                )
                self._append_boba_autopilot_events(
                    controller.project_id,
                    run.run_id,
                    [
                        item
                        for item in controller.event_stream
                        if item.run_id == run.run_id
                    ],
                )
        return controller

    def load_boba_autopilot_controller(
        self,
        project_id: str,
    ) -> BobaAutopilotControllerSetV1 | None:
        try:
            raw = self._read(self.boba_autopilot_controller_path(project_id), None)
        except ValidationError:
            return None
        if not isinstance(raw, dict):
            return None
        payload = raw.get("autopilot_controller", raw)
        if not isinstance(payload, dict):
            return None
        try:
            controller = BobaAutopilotControllerSetV1.model_validate(payload)
        except PydanticValidationError:
            return None
        lock = self.load_boba_autopilot_lock(project_id)
        controller.lock_metadata = lock
        return controller

    def load_boba_autopilot_run(
        self,
        project_id: str,
        run_id: str,
    ) -> dict[str, Any] | None:
        try:
            raw = self._read(self.boba_autopilot_run_path(project_id, run_id), None)
        except ValidationError:
            return None
        return raw if isinstance(raw, dict) else None

    def export_boba_autopilot_controller(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        controller = self.load_boba_autopilot_controller(project_id)
        if controller is None:
            raise ValidationError(
                "BOBA Autopilot Controller V1 is not available for export."
            )
        payload = {
            "schema_version": "boba_autopilot_controller_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "autopilot_controller": controller.model_dump(mode="json"),
            "privacy": {
                "private_paths_excluded": True,
                "secrets_excluded": True,
                "credentials_excluded": True,
                "raw_media_excluded": True,
                "full_command_output_excluded": True,
                "source_media_modified": False,
                "accepted_outputs_modified": False,
                "workflow_resume_used": False,
                "publication_used": False,
            },
        }
        safe = sanitize_autopilot_export(payload)
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Autopilot export is invalid.")
        return safe

    def reset_boba_autopilot_controller(self, project_id: str) -> bool:
        directory = self.boba_autopilot_controller_path(project_id).parent.resolve()
        project_directory = self._project_dir(project_id).resolve()
        if directory.parent != project_directory or directory.name != (
            "autopilot_controller"
        ):
            raise ValidationError("Invalid BOBA Autopilot reset path.")
        controller = self.load_boba_autopilot_controller(project_id)
        if controller is not None and any(
            run.run_status
            in {
                "created",
                "active",
                "awaiting_approval",
                "awaiting_human_review",
                "paused",
            }
            for run in controller.runs
        ):
            raise ValidationError(
                "Active Autopilot runs must be safely cancelled before reset."
            )
        with self._lock:
            if not directory.exists():
                return False
            shutil.rmtree(directory)
        return True

    @staticmethod
    def _validate_safety_record_id(value: str, *, label: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,180}", value):
            raise ValidationError(f"Invalid BOBA Safety Gate {label}.")
        return value

    def boba_safety_gate_path(self, project_id: str) -> Path:
        return self._path(project_id, "safety_gate/index.json")

    def boba_safety_evaluation_path(
        self,
        project_id: str,
        safety_case_id: str,
    ) -> Path:
        case_id = self._validate_safety_record_id(
            safety_case_id,
            label="case id",
        )
        return self._path(
            project_id,
            f"safety_gate/evaluations/{case_id}/index.json",
        )

    def boba_safety_decision_path(
        self,
        project_id: str,
        decision_id: str,
    ) -> Path:
        safe_decision_id = self._validate_safety_record_id(
            decision_id,
            label="decision id",
        )
        return self._path(
            project_id,
            f"safety_gate/decisions/{safe_decision_id}/index.json",
        )

    def boba_safety_policy_path(
        self,
        project_id: str,
        policy_id: str,
    ) -> Path:
        safe_policy_id = self._validate_safety_record_id(
            policy_id,
            label="policy id",
        )
        return self._path(
            project_id,
            f"safety_gate/policies/{safe_policy_id}.json",
        )

    def _write_immutable_safety_record(
        self,
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        existing = self._read(path, None)
        if existing is not None:
            if existing != payload:
                raise ValidationError(
                    "BOBA Safety Gate immutable history record changed."
                )
            return
        self._atomic_write_compact(path, payload)

    def save_boba_safety_gate(
        self,
        gate: BobaSafetyGateSetV1,
    ) -> BobaSafetyGateSetV1:
        with self._lock:
            safe_gate = sanitize_safety_export(gate.model_dump(mode="json"))
            if not isinstance(safe_gate, dict):
                raise ValidationError("BOBA Safety Gate payload is invalid.")
            self._atomic_write_compact(
                self.boba_safety_gate_path(gate.project_id),
                {
                    "schema_version": "boba_safety_gate_record_v1",
                    "safety_gate": safe_gate,
                },
            )
            policy_payload = sanitize_safety_export(
                gate.policy_snapshot.model_dump(mode="json")
            )
            if not isinstance(policy_payload, dict):
                raise ValidationError("BOBA Safety Gate policy payload is invalid.")
            self._write_immutable_safety_record(
                self.boba_safety_policy_path(
                    gate.project_id,
                    gate.policy_snapshot.policy_snapshot_id,
                ),
                {
                    "schema_version": "boba_safety_policy_snapshot_v1",
                    "policy_snapshot": policy_payload,
                },
            )
            for case in gate.evaluation_cases:
                case_payload = sanitize_safety_export(case.model_dump(mode="json"))
                if not isinstance(case_payload, dict):
                    raise ValidationError(
                        "BOBA Safety Gate evaluation payload is invalid."
                    )
                self._atomic_write_compact(
                    self.boba_safety_evaluation_path(
                        gate.project_id,
                        case.safety_case_id,
                    ),
                    {
                        "schema_version": "boba_safety_evaluation_v1",
                        "evaluation_case": case_payload,
                    },
                )
            for decision in gate.safety_decisions:
                decision_payload = sanitize_safety_export(
                    decision.model_dump(mode="json")
                )
                if not isinstance(decision_payload, dict):
                    raise ValidationError(
                        "BOBA Safety Gate decision payload is invalid."
                    )
                self._write_immutable_safety_record(
                    self.boba_safety_decision_path(
                        gate.project_id,
                        decision.safety_decision_id,
                    ),
                    {
                        "schema_version": "boba_safety_decision_v1",
                        "safety_decision": decision_payload,
                    },
                )
        return gate

    def load_boba_safety_gate(
        self,
        project_id: str,
    ) -> BobaSafetyGateSetV1 | None:
        try:
            raw = self._read(self.boba_safety_gate_path(project_id), None)
        except ValidationError:
            return None
        if not isinstance(raw, dict):
            return None
        payload = raw.get("safety_gate", raw)
        if not isinstance(payload, dict):
            return None
        try:
            return BobaSafetyGateSetV1.model_validate(payload)
        except PydanticValidationError:
            return None

    def load_boba_safety_evaluation(
        self,
        project_id: str,
        safety_case_id: str,
    ) -> BobaSafetyEvaluationCaseV1 | None:
        raw = self._read(
            self.boba_safety_evaluation_path(project_id, safety_case_id),
            None,
        )
        if isinstance(raw, dict):
            payload = raw.get("evaluation_case", raw)
            if isinstance(payload, dict):
                try:
                    return BobaSafetyEvaluationCaseV1.model_validate(payload)
                except PydanticValidationError:
                    pass
        gate = self.load_boba_safety_gate(project_id)
        if gate is None:
            return None
        return next(
            (
                item
                for item in gate.evaluation_cases
                if item.safety_case_id == safety_case_id
            ),
            None,
        )

    def load_boba_safety_decision(
        self,
        project_id: str,
        decision_id: str,
    ) -> BobaSafetyDecisionV1 | None:
        raw = self._read(
            self.boba_safety_decision_path(project_id, decision_id),
            None,
        )
        if isinstance(raw, dict):
            payload = raw.get("safety_decision", raw)
            if isinstance(payload, dict):
                try:
                    return BobaSafetyDecisionV1.model_validate(payload)
                except PydanticValidationError:
                    pass
        gate = self.load_boba_safety_gate(project_id)
        if gate is None:
            return None
        return next(
            (
                item
                for item in gate.safety_decisions
                if item.safety_decision_id == decision_id
            ),
            None,
        )

    def export_boba_safety_gate(self, project_id: str) -> dict[str, Any]:
        gate = self.load_boba_safety_gate(project_id)
        if gate is None:
            raise ValidationError("BOBA Safety Gate V1 is not available for export.")
        payload = {
            "schema_version": "boba_safety_gate_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "safety_gate": gate.model_dump(mode="json"),
            "privacy": {
                "private_paths_excluded": True,
                "secrets_excluded": True,
                "credentials_excluded": True,
                "tokens_excluded": True,
                "raw_patches_excluded": True,
                "raw_media_excluded": True,
                "full_command_logs_excluded": True,
                "action_execution_used": False,
                "workflow_resume_used": False,
                "publication_used": False,
            },
        }
        safe = sanitize_safety_export(payload)
        if not isinstance(safe, dict):
            raise ValidationError("BOBA Safety Gate export is invalid.")
        return safe

    def reset_boba_safety_gate(self, project_id: str) -> bool:
        path = self.boba_safety_gate_path(project_id)
        directory = path.parent.resolve()
        project_directory = self._project_dir(project_id).resolve()
        if directory.parent != project_directory or directory.name != "safety_gate":
            raise ValidationError("Invalid BOBA Safety Gate reset path.")
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
        return True

    def approval_rejection_learning_path(self, project_id: str) -> Path:
        return self._path(project_id, "approval_rejection_learning/index.json")

    def save_approval_rejection_learning(
        self,
        learning: BobaApprovalRejectionLearningSetV1,
    ) -> BobaApprovalRejectionLearningSetV1:
        with self._lock:
            self._write(
                self.approval_rejection_learning_path(learning.project_id),
                {
                    "schema_version": "boba_approval_rejection_learning_v1",
                    "approval_rejection_learning": learning.model_dump(mode="json"),
                },
            )
        return learning

    def load_approval_rejection_learning(
        self,
        project_id: str,
    ) -> BobaApprovalRejectionLearningSetV1 | None:
        raw = self._read(self.approval_rejection_learning_path(project_id), None)
        if not isinstance(raw, dict):
            return None
        value = raw.get("approval_rejection_learning", raw)
        return (
            BobaApprovalRejectionLearningSetV1.model_validate(value)
            if isinstance(value, dict)
            else None
        )

    def export_approval_rejection_learning(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        learning = self.load_approval_rejection_learning(project_id)
        if learning is None:
            raise ValidationError(
                "BOBA approval/rejection learning is not available for export.",
                details={"project_id": project_id},
            )
        payload = learning.model_dump(mode="json")
        for case in payload.get("approval_cases", []):
            if isinstance(case, dict):
                case.pop("supporting_evidence", None)
                for factor in case.get("approval_factors", []):
                    if isinstance(factor, dict):
                        factor.pop("evidence_snippet", None)
        for case in payload.get("rejection_cases", []):
            if isinstance(case, dict):
                case.pop("supporting_evidence", None)
                for factor in case.get("likely_rejection_causes", []):
                    if isinstance(factor, dict):
                        factor.pop("evidence_snippet", None)
        for attribution in payload.get("decision_attributions", []):
            if isinstance(attribution, dict):
                attribution.pop("evidence", None)
        export = {
            "schema_version": "boba_approval_rejection_learning_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "approval_rejection_learning": payload,
            "privacy": {
                "explicit_feedback_only": True,
                "compact_decision_learning_only": True,
                "raw_feedback_notes_excluded": True,
                "media_excluded": True,
            },
        }
        safe = sanitize_memory_payload(
            export,
            max_excerpt_chars=self.max_excerpt_chars,
        )
        if not isinstance(safe, dict):
            raise ValidationError(
                "BOBA approval/rejection learning export is invalid."
            )
        return safe

    def reset_approval_rejection_learning(self, project_id: str) -> bool:
        path = self.approval_rejection_learning_path(project_id)
        removed = False
        with self._lock:
            if path.exists():
                path.unlink()
                removed = True
            directory = path.parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

    def creator_learning_path(self, project_id: str) -> Path:
        return self._path(project_id, "creator_learning/index.json")

    def creator_learning_events_path(self, project_id: str) -> Path:
        return self._path(project_id, "creator_learning/events.jsonl")

    def save_creator_learning(
        self,
        learning: BobaCreatorLearningSetV1,
    ) -> BobaCreatorLearningSetV1:
        with self._lock:
            self._write(
                self.creator_learning_path(learning.project_id),
                {
                    "schema_version": "boba_creator_learning_loop_v1",
                    "creator_learning": learning.model_dump(mode="json"),
                },
            )
        return learning

    def load_creator_learning(
        self,
        project_id: str,
    ) -> BobaCreatorLearningSetV1 | None:
        raw = self._read(self.creator_learning_path(project_id), None)
        if not isinstance(raw, dict):
            return None
        value = raw.get("creator_learning", raw)
        return (
            BobaCreatorLearningSetV1.model_validate(value)
            if isinstance(value, dict)
            else None
        )

    def load_creator_learning_profile(
        self,
        project_id: str,
    ) -> BobaCreatorLearningSetV1 | None:
        return self.load_creator_learning(project_id)

    def append_creator_feedback_event(
        self,
        event: BobaCreatorFeedbackEventV1,
    ) -> BobaCreatorFeedbackEventV1:
        safe_payload = sanitize_memory_payload(
            event.model_dump(mode="json"),
            max_excerpt_chars=self.max_excerpt_chars,
        )
        safe_event = BobaCreatorFeedbackEventV1.model_validate(safe_payload)
        with self._lock:
            events = self.list_creator_feedback_events(event.project_id)
            existing = next(
                (item for item in events if item.event_id == event.event_id),
                None,
            )
            if existing is not None:
                return existing
            events.append(safe_event)
            lines = [
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                for item in events[-5000:]
            ]
            self._atomic_write_text(
                self.creator_learning_events_path(event.project_id),
                "\n".join(lines) + "\n",
            )
        return safe_event

    def record_creator_feedback_event(
        self,
        event: BobaCreatorFeedbackEventV1,
    ) -> BobaCreatorFeedbackEventV1:
        return self.append_creator_feedback_event(event)

    def list_creator_feedback_events(
        self,
        project_id: str,
    ) -> list[BobaCreatorFeedbackEventV1]:
        path = self.creator_learning_events_path(project_id)
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ValidationError(
                "BOBA creator feedback event storage could not be read.",
                details={"path": path.name},
            ) from exc
        events: list[BobaCreatorFeedbackEventV1] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                events.append(BobaCreatorFeedbackEventV1.model_validate(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValidationError(
                    "BOBA creator feedback event storage is corrupt.",
                    details={"path": path.name, "line": line_number},
                ) from exc
        return events

    def export_creator_learning_profile(self, project_id: str) -> dict[str, Any]:
        learning = self.load_creator_learning(project_id)
        if learning is None:
            raise ValidationError(
                "BOBA creator learning is not available for export.",
                details={"project_id": project_id},
            )
        compact_events = [
            event.model_dump(
                mode="json",
                exclude={"note", "source_artifacts"},
            )
            for event in self.list_creator_feedback_events(project_id)
        ]
        learning_payload = learning.model_dump(mode="json")
        learning_payload["feedback_events"] = compact_events
        payload = {
            "schema_version": "boba_creator_learning_export_v1",
            "project_id": project_id,
            "exported_at": memory_now_iso(),
            "creator_learning": learning_payload,
            "privacy": {
                "explicit_feedback_only": True,
                "compact_preferences_only": True,
            },
        }
        safe = sanitize_memory_payload(
            payload,
            max_excerpt_chars=self.max_excerpt_chars,
        )
        if not isinstance(safe, dict):
            raise ValidationError("BOBA creator learning export is invalid.")
        return safe

    def reset_creator_learning_profile(self, project_id: str) -> bool:
        paths = (
            self.creator_learning_path(project_id),
            self.creator_learning_events_path(project_id),
        )
        removed = False
        with self._lock:
            for path in paths:
                if path.exists():
                    path.unlink()
                    removed = True
            directory = self.creator_learning_path(project_id).parent
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed

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

    @staticmethod
    def _validate_integration_record_id(value: str, *, label: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value):
            raise ValidationError(f"Invalid BOBA Integration Layer {label}.")
        return value

    def boba_integration_layer_path(self, project_id: str) -> Path:
        return self._path(project_id, "integration_layer/index.json")

    def boba_integration_registry_path(
        self,
        project_id: str,
        registry_snapshot_id: str,
    ) -> Path:
        registry_id = self._validate_integration_record_id(
            registry_snapshot_id,
            label="registry snapshot id",
        )
        return self._path(
            project_id,
            f"integration_layer/registries/{registry_id}.json",
        )

    def boba_integration_transaction_path(
        self,
        project_id: str,
        transaction_id: str,
    ) -> Path:
        safe_transaction_id = self._validate_integration_record_id(
            transaction_id,
            label="transaction id",
        )
        return self._path(
            project_id,
            f"integration_layer/transactions/{safe_transaction_id}/index.json",
        )

    def boba_integration_events_path(
        self,
        project_id: str,
        transaction_id: str,
    ) -> Path:
        return self.boba_integration_transaction_path(
            project_id,
            transaction_id,
        ).with_name("events.jsonl")

    def boba_integration_idempotency_path(self, project_id: str) -> Path:
        return self._path(project_id, "integration_layer/idempotency/index.json")

    def save_boba_integration_layer(
        self,
        layer: BobaIntegrationLayerSetV1,
    ) -> BobaIntegrationLayerSetV1:
        safe = sanitize_integration_export(layer.model_dump(mode="json"))
        validated = BobaIntegrationLayerSetV1.model_validate(safe)
        with self._lock:
            self._atomic_write(
                self.boba_integration_layer_path(layer.project_id),
                validated.model_dump(mode="json"),
            )
        return validated

    def load_boba_integration_layer(
        self,
        project_id: str,
    ) -> BobaIntegrationLayerSetV1 | None:
        raw = self._read(self.boba_integration_layer_path(project_id), None)
        if not isinstance(raw, dict):
            return None
        try:
            return BobaIntegrationLayerSetV1.model_validate(raw)
        except PydanticValidationError:
            return None

    def save_boba_integration_registry_snapshot(
        self,
        project_id: str,
        snapshot: BobaIntegrationRegistrySnapshotV1,
    ) -> BobaIntegrationRegistrySnapshotV1:
        path = self.boba_integration_registry_path(
            project_id,
            snapshot.registry_snapshot_id,
        )
        with self._lock:
            existing = self._read(path, None)
            if isinstance(existing, dict):
                try:
                    saved = BobaIntegrationRegistrySnapshotV1.model_validate(
                        existing
                    )
                except PydanticValidationError as exc:
                    raise ValidationError(
                        "Stored Integration Layer registry snapshot is malformed."
                    ) from exc
                if saved.registry_sha256 != snapshot.registry_sha256:
                    raise ValidationError(
                        "Integration Layer registry snapshots are immutable."
                    )
                return saved
            self._atomic_write(path, snapshot.model_dump(mode="json"))
        return snapshot

    def save_boba_integration_transaction(
        self,
        transaction: BobaIntegrationTransactionV1,
    ) -> BobaIntegrationTransactionV1:
        path = self.boba_integration_transaction_path(
            transaction.project_id,
            transaction.transaction_id,
        )
        terminal_states = {
            "blocked",
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
            "duplicate_reused",
            "future_gated",
        }
        safe = BobaIntegrationTransactionV1.model_validate(
            sanitize_integration_export(transaction.model_dump(mode="json"))
        )
        with self._lock:
            existing = self._read(path, None)
            if isinstance(existing, dict):
                try:
                    saved = BobaIntegrationTransactionV1.model_validate(existing)
                except PydanticValidationError:
                    saved = None
                if (
                    saved is not None
                    and saved.state in terminal_states
                    and saved.model_dump(mode="json")
                    != safe.model_dump(mode="json")
                ):
                    raise ValidationError(
                        "Completed Integration Layer transactions are immutable."
                    )
            self._atomic_write(path, safe.model_dump(mode="json"))
        return safe

    def load_boba_integration_transaction(
        self,
        project_id: str,
        transaction_id: str,
    ) -> BobaIntegrationTransactionV1 | None:
        raw = self._read(
            self.boba_integration_transaction_path(project_id, transaction_id),
            None,
        )
        if not isinstance(raw, dict):
            return None
        try:
            return BobaIntegrationTransactionV1.model_validate(raw)
        except PydanticValidationError:
            return None

    def append_boba_integration_event(
        self,
        event: BobaIntegrationEventV1,
    ) -> None:
        path = self.boba_integration_events_path(
            event.project_id,
            event.transaction_id,
        )
        with self._lock:
            existing = self.load_boba_integration_events(
                event.project_id,
                event.transaction_id,
            )
            if any(item.event_id == event.event_id for item in existing):
                return
            if existing and event.sequence <= existing[-1].sequence:
                raise ValidationError(
                    "Integration Layer event sequence must be monotonic."
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            safe = BobaIntegrationEventV1.model_validate(
                sanitize_integration_export(event.model_dump(mode="json"))
            )
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        safe.model_dump(mode="json"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

    def load_boba_integration_events(
        self,
        project_id: str,
        transaction_id: str,
    ) -> list[BobaIntegrationEventV1]:
        path = self.boba_integration_events_path(project_id, transaction_id)
        if not path.exists():
            return []
        events: list[BobaIntegrationEventV1] = []
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                try:
                    raw = json.loads(line)
                    events.append(BobaIntegrationEventV1.model_validate(raw))
                except (json.JSONDecodeError, PydanticValidationError):
                    continue
        except OSError as exc:
            raise ValidationError(
                "BOBA Integration Layer event stream is unreadable."
            ) from exc
        return sorted(events, key=lambda item: item.sequence)

    def save_boba_integration_idempotency_records(
        self,
        project_id: str,
        records: list[BobaIntegrationIdempotencyRecordV1],
    ) -> list[BobaIntegrationIdempotencyRecordV1]:
        if len(records) > 512:
            records = records[-512:]
        safe_records = [
            BobaIntegrationIdempotencyRecordV1.model_validate(
                sanitize_integration_export(item.model_dump(mode="json"))
            )
            for item in records
        ]
        payload = {
            "schema_version": "boba_integration_idempotency_v1",
            "project_id": project_id,
            "records": [item.model_dump(mode="json") for item in safe_records],
        }
        with self._lock:
            self._atomic_write(
                self.boba_integration_idempotency_path(project_id),
                payload,
            )
        return safe_records

    def load_boba_integration_idempotency_records(
        self,
        project_id: str,
    ) -> list[BobaIntegrationIdempotencyRecordV1]:
        raw = self._read(
            self.boba_integration_idempotency_path(project_id),
            {},
        )
        values = raw.get("records", []) if isinstance(raw, dict) else []
        records: list[BobaIntegrationIdempotencyRecordV1] = []
        for value in values if isinstance(values, list) else []:
            try:
                records.append(
                    BobaIntegrationIdempotencyRecordV1.model_validate(value)
                )
            except PydanticValidationError:
                continue
        return records

    def export_boba_integration_layer(self, project_id: str) -> dict[str, Any]:
        layer = self.load_boba_integration_layer(project_id)
        payload = (
            layer.model_dump(mode="json")
            if layer is not None
            else {
                "schema_version": "boba_integration_layer_v1",
                "project_id": project_id,
                "available": False,
            }
        )
        safe = sanitize_integration_export(payload)
        if not isinstance(safe, dict):
            raise ValidationError("Integration Layer export is malformed.")
        safe["export_metadata"] = {
            "private_paths_removed": True,
            "secrets_removed": True,
            "raw_patches_removed": True,
            "full_logs_removed": True,
            "source_media_included": False,
            "accepted_outputs_modified": False,
        }
        return safe

    def reset_boba_integration_layer(self, project_id: str) -> dict[str, Any]:
        layer = self.load_boba_integration_layer(project_id)
        if layer is not None and any(
            item.state
            not in {
                "blocked",
                "succeeded",
                "failed",
                "timed_out",
                "cancelled",
                "duplicate_reused",
                "future_gated",
            }
            for item in layer.integration_transactions
        ):
            raise ValidationError(
                "Active Integration Layer transaction history cannot be erased."
            )
        active_path = self.boba_integration_layer_path(project_id)
        idempotency_path = self.boba_integration_idempotency_path(project_id)
        with self._lock:
            active_removed = active_path.exists()
            idempotency_removed = idempotency_path.exists()
            active_path.unlink(missing_ok=True)
            idempotency_path.unlink(missing_ok=True)
        return {
            "schema_version": "boba_integration_layer_reset_v1",
            "project_id": project_id,
            "active_metadata_removed": active_removed,
            "idempotency_metadata_removed": idempotency_removed,
            "immutable_transactions_preserved": True,
            "registry_snapshots_preserved": True,
            "upstream_boba_artifacts_removed": False,
            "approvals_removed": False,
            "safety_decisions_removed": False,
            "autopilot_history_removed": False,
            "source_media_removed": False,
            "accepted_outputs_removed": False,
        }

    @staticmethod
    def _validate_workflow_record_id(value: str, *, label: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,180}", value):
            raise ValidationError(f"Invalid BOBA Workflow Controller {label}.")
        return value

    def boba_workflow_controller_path(self, project_id: str) -> Path:
        return self._path(project_id, "workflow_controller/index.json")

    def boba_workflow_definition_path(
        self,
        project_id: str,
        definition_id: str,
    ) -> Path:
        safe_id = self._validate_workflow_record_id(
            definition_id,
            label="definition id",
        )
        return self._path(
            project_id,
            f"workflow_controller/definitions/{safe_id}.json",
        )

    def boba_workflow_run_path(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> Path:
        safe_id = self._validate_workflow_record_id(
            workflow_run_id,
            label="run id",
        )
        return self._path(
            project_id,
            f"workflow_controller/runs/{safe_id}/index.json",
        )

    def boba_workflow_stage_path(
        self,
        project_id: str,
        workflow_run_id: str,
        stage_instance_id: str,
    ) -> Path:
        safe_stage_id = self._validate_workflow_record_id(
            stage_instance_id,
            label="stage instance id",
        )
        return self.boba_workflow_run_path(
            project_id,
            workflow_run_id,
        ).parent / "stages" / f"{safe_stage_id}.json"

    def boba_workflow_transition_path(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_request_id: str,
    ) -> Path:
        safe_transition_id = self._validate_workflow_record_id(
            transition_request_id,
            label="transition request id",
        )
        return self.boba_workflow_run_path(
            project_id,
            workflow_run_id,
        ).parent / "transitions" / f"{safe_transition_id}.json"

    def boba_workflow_events_path(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> Path:
        return self.boba_workflow_run_path(
            project_id,
            workflow_run_id,
        ).with_name("events.jsonl")

    def boba_workflow_execution_lease_path(self, project_id: str) -> Path:
        return self._path(project_id, "workflow_controller/active.lock.json")

    def save_boba_workflow_definition(
        self,
        project_id: str,
        snapshot: BobaWorkflowDefinitionSnapshotV1,
        stages: list[BobaWorkflowStageDefinitionV1],
    ) -> BobaWorkflowDefinitionSnapshotV1:
        path = self.boba_workflow_definition_path(
            project_id,
            snapshot.workflow_definition_id,
        )
        payload = {
            "schema_version": "boba_workflow_definition_record_v1",
            "project_id": project_id,
            "definition": snapshot.model_dump(mode="json"),
            "stage_definitions": [
                item.model_dump(mode="json") for item in stages
            ],
        }
        safe = sanitize_workflow_export(payload)
        with self._lock:
            existing = self._read(path, None)
            if isinstance(existing, dict):
                if existing != safe:
                    raise ValidationError(
                        "Completed workflow definition snapshots are immutable."
                    )
                return snapshot
            self._atomic_write_compact(path, safe)
        return snapshot

    @staticmethod
    def _workflow_run_payload(
        controller: BobaWorkflowControllerSetV1,
        workflow_run_id: str,
    ) -> dict[str, Any]:
        stage_ids = {
            item.stage_instance_id
            for item in controller.stage_instances
            if item.workflow_run_id == workflow_run_id
        }
        return {
            "schema_version": "boba_workflow_run_record_v1",
            "project_id": controller.project_id,
            "run": next(
                (
                    item.model_dump(mode="json")
                    for item in controller.workflow_runs
                    if item.workflow_run_id == workflow_run_id
                ),
                None,
            ),
            "stage_instance_ids": sorted(stage_ids),
            "transition_request_ids": [
                item.transition_request_id
                for item in controller.transition_requests
                if item.workflow_run_id == workflow_run_id
            ],
            "pause_record_ids": [
                item.pause_record_id
                for item in controller.pause_records
                if item.workflow_run_id == workflow_run_id
            ],
            "recovery_hold_ids": [
                item.recovery_hold_id
                for item in controller.recovery_holds
                if item.workflow_run_id == workflow_run_id
            ],
            "incident_ids": [
                item.incident_id
                for item in controller.incidents
                if item.workflow_run_id == workflow_run_id
            ],
            "human_decision_ids": [
                item.human_decision_id
                for item in controller.human_decisions
                if item.workflow_run_id == workflow_run_id
            ],
        }

    def _save_boba_workflow_stage_record(
        self,
        controller: BobaWorkflowControllerSetV1,
        stage: Any,
    ) -> None:
        path = self.boba_workflow_stage_path(
            controller.project_id,
            stage.workflow_run_id,
            stage.stage_instance_id,
        )
        payload = sanitize_workflow_export(
            {
                "schema_version": "boba_workflow_stage_record_v1",
                "project_id": controller.project_id,
                "stage_instance": stage.model_dump(mode="json"),
            }
        )
        existing = self._read(path, None)
        if isinstance(existing, dict):
            saved_stage = existing.get("stage_instance")
            saved_status = (
                str(saved_stage.get("status") or "")
                if isinstance(saved_stage, dict)
                else ""
            )
            if (
                saved_status
                in {
                    "completed",
                    "completed_with_limitations",
                    "failed",
                    "timed_out",
                    "cancelled",
                    "superseded",
                    "skipped_not_required",
                }
                and existing != payload
            ):
                raise ValidationError(
                    "Completed workflow stage records are immutable."
                )
        self._atomic_write_compact(path, payload)

    def _save_boba_workflow_transition_records(
        self,
        controller: BobaWorkflowControllerSetV1,
        workflow_run_id: str,
    ) -> None:
        decisions_by_request: dict[str, list[Any]] = {}
        for decision in controller.transition_decisions:
            if decision.workflow_run_id == workflow_run_id:
                decisions_by_request.setdefault(
                    decision.transition_request_id,
                    [],
                ).append(decision)
        for request in controller.transition_requests:
            if request.workflow_run_id != workflow_run_id:
                continue
            path = self.boba_workflow_transition_path(
                controller.project_id,
                workflow_run_id,
                request.transition_request_id,
            )
            payload = sanitize_workflow_export(
                {
                    "schema_version": "boba_workflow_transition_record_v1",
                    "project_id": controller.project_id,
                    "request": request.model_dump(mode="json"),
                    "decisions": [
                        item.model_dump(mode="json")
                        for item in decisions_by_request.get(
                            request.transition_request_id,
                            [],
                        )
                    ],
                }
            )
            existing = self._read(path, None)
            if isinstance(existing, dict):
                existing_decisions = existing.get("decisions")
                if (
                    isinstance(existing_decisions, list)
                    and existing_decisions
                    and existing != payload
                ):
                    raise ValidationError(
                        "Completed workflow transition decisions are immutable."
                    )
            self._atomic_write_compact(path, payload)

    def append_boba_workflow_events(
        self,
        project_id: str,
        workflow_run_id: str,
        events: list[BobaWorkflowEventV1],
    ) -> None:
        path = self.boba_workflow_events_path(project_id, workflow_run_id)
        existing = self.load_boba_workflow_events(project_id, workflow_run_id)
        existing_ids = {item.event_id for item in existing}
        sequence = existing[-1].sequence if existing else 0
        new_events = sorted(
            [item for item in events if item.event_id not in existing_ids],
            key=lambda item: item.sequence,
        )
        if not new_events:
            return
        for event in new_events:
            if event.sequence <= sequence:
                raise ValidationError(
                    "Workflow event sequence must be monotonic."
                )
            sequence = event.sequence
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for event in new_events:
                safe = sanitize_workflow_export(event.model_dump(mode="json"))
                handle.write(
                    json.dumps(
                        safe,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def load_boba_workflow_events(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> list[BobaWorkflowEventV1]:
        path = self.boba_workflow_events_path(project_id, workflow_run_id)
        if not path.exists():
            return []
        events: list[BobaWorkflowEventV1] = []
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                try:
                    events.append(
                        BobaWorkflowEventV1.model_validate(json.loads(line))
                    )
                except (json.JSONDecodeError, PydanticValidationError):
                    continue
        except OSError as exc:
            raise ValidationError(
                "BOBA Workflow Controller event stream is unreadable."
            ) from exc
        return sorted(events, key=lambda item: item.sequence)

    def save_boba_workflow_controller(
        self,
        controller: BobaWorkflowControllerSetV1,
    ) -> BobaWorkflowControllerSetV1:
        safe = sanitize_workflow_export(controller.model_dump(mode="json"))
        validated = BobaWorkflowControllerSetV1.model_validate(safe)
        with self._lock:
            for snapshot in validated.workflow_definition_snapshots:
                stages = [
                    item
                    for item in validated.stage_definitions
                    if item.workflow_definition_id
                    == snapshot.workflow_definition_id
                ]
                self.save_boba_workflow_definition(
                    validated.project_id,
                    snapshot,
                    stages,
                )
            for run in validated.workflow_runs:
                self._atomic_write_compact(
                    self.boba_workflow_run_path(
                        validated.project_id,
                        run.workflow_run_id,
                    ),
                    sanitize_workflow_export(
                        self._workflow_run_payload(
                            validated,
                            run.workflow_run_id,
                        )
                    ),
                )
                for stage in validated.stage_instances:
                    if stage.workflow_run_id == run.workflow_run_id:
                        self._save_boba_workflow_stage_record(validated, stage)
                self._save_boba_workflow_transition_records(
                    validated,
                    run.workflow_run_id,
                )
                self.append_boba_workflow_events(
                    validated.project_id,
                    run.workflow_run_id,
                    [
                        item
                        for item in validated.workflow_events
                        if item.workflow_run_id == run.workflow_run_id
                    ],
                )
            self._atomic_write_compact(
                self.boba_workflow_controller_path(controller.project_id),
                {
                    "schema_version": "boba_workflow_controller_record_v1",
                    "workflow_controller": validated.model_dump(mode="json"),
                },
            )
        return validated

    def load_boba_workflow_controller(
        self,
        project_id: str,
    ) -> BobaWorkflowControllerSetV1 | None:
        try:
            raw = self._read(self.boba_workflow_controller_path(project_id), None)
        except ValidationError:
            return None
        if not isinstance(raw, dict):
            return None
        payload = raw.get("workflow_controller", raw)
        if not isinstance(payload, dict):
            return None
        try:
            return BobaWorkflowControllerSetV1.model_validate(payload)
        except PydanticValidationError:
            return None

    def load_boba_workflow_execution_lease(
        self,
        project_id: str,
    ) -> BobaWorkflowExecutionLeaseV1 | None:
        raw = self._read(
            self.boba_workflow_execution_lease_path(project_id),
            None,
        )
        if not isinstance(raw, dict):
            return None
        try:
            lease = BobaWorkflowExecutionLeaseV1.model_validate(raw)
        except PydanticValidationError as exc:
            raise ValidationError(
                "BOBA Workflow Controller lease metadata is malformed."
            ) from exc
        expires_at = self._autopilot_time(lease.expires_at)
        lease.stale = expires_at is None or expires_at <= datetime.now(UTC)
        if lease.stale:
            lease.lease_status = "expired"
        return lease

    def acquire_boba_workflow_execution_lease(
        self,
        project_id: str,
        *,
        workflow_run_id: str,
        transition_request_id: str,
        stage_instance_id: str,
        owner_id: str,
        lease_mode: str,
        revision: int,
        project_snapshot_digest: str,
        lease_seconds: int = 300,
        confirm_stale: bool = False,
    ) -> BobaWorkflowExecutionLeaseV1:
        path = self.boba_workflow_execution_lease_path(project_id)
        with self._lock:
            existing = self.load_boba_workflow_execution_lease(project_id)
            if existing is not None and not existing.stale:
                if (
                    existing.workflow_run_id == workflow_run_id
                    and existing.transition_request_id == transition_request_id
                    and existing.stage_instance_id == stage_instance_id
                    and existing.owner_id == owner_id
                ):
                    return self.refresh_boba_workflow_execution_lease(
                        project_id,
                        workflow_run_id=workflow_run_id,
                        owner_id=owner_id,
                        lease_seconds=lease_seconds,
                    )
                raise ValidationError(
                    "A conflicting workflow execution lease is active."
                )
            warnings: list[str] = []
            if existing is not None:
                if not confirm_stale:
                    raise ValidationError(
                        "A stale workflow lease requires explicit replacement."
                    )
                stale_path = path.with_name(
                    f"active.lock.stale.{uuid4().hex}.json"
                )
                with suppress(FileNotFoundError):
                    os.replace(path, stale_path)
                warnings.append(
                    "The explicitly replaced stale lease was preserved."
                )
            now = datetime.now(UTC)
            lease = BobaWorkflowExecutionLeaseV1(
                execution_lease_id=f"workflow_lease_{uuid4().hex}",
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                transition_request_id=transition_request_id,
                stage_instance_id=stage_instance_id,
                lease_mode=lease_mode,
                owner_id=owner_id,
                acquired_at=now.isoformat(),
                refreshed_at=now.isoformat(),
                expires_at=(
                    now
                    + timedelta(seconds=max(30, min(lease_seconds, 900)))
                ).isoformat(),
                lease_status="active",
                revision_at_acquisition=revision,
                project_snapshot_digest=project_snapshot_digest,
                warnings=warnings,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8", newline="\n") as handle:
                    json.dump(
                        lease.model_dump(mode="json"),
                        handle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError as exc:
                raise ValidationError(
                    "A workflow lease was acquired concurrently."
                ) from exc
            return lease

    def refresh_boba_workflow_execution_lease(
        self,
        project_id: str,
        *,
        workflow_run_id: str,
        owner_id: str,
        lease_seconds: int = 300,
        confirm_stale: bool = False,
    ) -> BobaWorkflowExecutionLeaseV1:
        with self._lock:
            lease = self.load_boba_workflow_execution_lease(project_id)
            if lease is None:
                raise ValidationError("Workflow execution lease is missing.")
            if (
                lease.workflow_run_id != workflow_run_id
                or lease.owner_id != owner_id
            ):
                raise ValidationError(
                    "Workflow execution lease belongs to another run or owner."
                )
            if lease.stale and not confirm_stale:
                raise ValidationError(
                    "A stale workflow lease requires explicit refresh confirmation."
                )
            now = datetime.now(UTC)
            lease.refreshed_at = now.isoformat()
            lease.expires_at = (
                now + timedelta(seconds=max(30, min(lease_seconds, 900)))
            ).isoformat()
            lease.stale = False
            lease.lease_status = "active"
            self._atomic_write_compact(
                self.boba_workflow_execution_lease_path(project_id),
                lease.model_dump(mode="json"),
            )
            return lease

    def release_boba_workflow_execution_lease(
        self,
        project_id: str,
        *,
        workflow_run_id: str,
        owner_id: str,
    ) -> bool:
        path = self.boba_workflow_execution_lease_path(project_id)
        with self._lock:
            lease = self.load_boba_workflow_execution_lease(project_id)
            if lease is None:
                return False
            if (
                lease.workflow_run_id != workflow_run_id
                or lease.owner_id != owner_id
            ):
                raise ValidationError(
                    "Workflow lease release does not match its run and owner."
                )
            path.unlink(missing_ok=True)
            return True

    def export_boba_workflow_controller(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        controller = self.load_boba_workflow_controller(project_id)
        if controller is None:
            raise ValidationError(
                "BOBA Workflow Controller is not available for export."
            )
        safe = sanitize_workflow_export(
            {
                "schema_version": "boba_workflow_controller_export_v1",
                "project_id": project_id,
                "exported_at": memory_now_iso(),
                "workflow_controller": controller.model_dump(mode="json"),
                "privacy": {
                    "private_paths_excluded": True,
                    "secrets_excluded": True,
                    "credentials_excluded": True,
                    "raw_media_excluded": True,
                    "complete_command_logs_excluded": True,
                    "source_media_modified": False,
                    "accepted_outputs_modified": False,
                    "workflow_resume_used": False,
                    "upload_used": False,
                    "publication_used": False,
                },
            }
        )
        if not isinstance(safe, dict):
            raise ValidationError("Workflow Controller export is malformed.")
        return safe

    def reset_boba_workflow_controller(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        controller = self.load_boba_workflow_controller(project_id)
        if controller is not None and any(
            run.run_status not in {"completed", "cancelled", "failed"}
            for run in controller.workflow_runs
        ):
            raise ValidationError(
                "Active workflow runs must be safely cancelled before reset."
            )
        index_path = self.boba_workflow_controller_path(project_id)
        lock_path = self.boba_workflow_execution_lease_path(project_id)
        with self._lock:
            active_removed = index_path.exists()
            lease_removed = lock_path.exists()
            index_path.unlink(missing_ok=True)
            lock_path.unlink(missing_ok=True)
        return {
            "schema_version": "boba_workflow_controller_reset_v1",
            "project_id": project_id,
            "active_metadata_removed": active_removed,
            "active_lease_removed": lease_removed,
            "immutable_workflow_history_preserved": True,
            "stage_records_preserved": True,
            "transition_records_preserved": True,
            "event_streams_preserved": True,
            "recovery_records_preserved": True,
            "source_media_removed": False,
            "accepted_outputs_removed": False,
            "autopilot_history_removed": False,
            "safety_decisions_removed": False,
            "integration_transactions_removed": False,
            "approvals_removed": False,
        }
    @staticmethod
    def _validate_validator_runner_record_id(value: str, *, label: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,180}", value):
            raise ValidationError(f"Invalid BOBA Validator Runner {label}.")
        return value

    def boba_validator_runner_path(self, project_id: str) -> Path:
        return self._path(project_id, "validator_runner/index.json")

    def boba_validator_registry_path(
        self,
        project_id: str,
        registry_snapshot_id: str,
    ) -> Path:
        safe_id = self._validate_validator_runner_record_id(
            registry_snapshot_id,
            label="registry snapshot id",
        )
        return self._path(
            project_id,
            f"validator_runner/registries/{safe_id}.json",
        )

    def boba_validation_plan_path(
        self,
        project_id: str,
        validation_plan_id: str,
    ) -> Path:
        safe_id = self._validate_validator_runner_record_id(
            validation_plan_id,
            label="plan id",
        )
        return self._path(
            project_id,
            f"validator_runner/plans/{safe_id}/index.json",
        )

    def boba_validation_run_path(
        self,
        project_id: str,
        validation_run_id: str,
    ) -> Path:
        safe_id = self._validate_validator_runner_record_id(
            validation_run_id,
            label="run id",
        )
        return self._path(
            project_id,
            f"validator_runner/runs/{safe_id}/index.json",
        )

    def boba_validation_check_path(
        self,
        project_id: str,
        validation_run_id: str,
        check_run_id: str,
    ) -> Path:
        safe_id = self._validate_validator_runner_record_id(
            check_run_id,
            label="check run id",
        )
        return self.boba_validation_run_path(
            project_id,
            validation_run_id,
        ).parent / "checks" / f"{safe_id}.json"

    def boba_validation_events_path(
        self,
        project_id: str,
        validation_run_id: str,
    ) -> Path:
        return self.boba_validation_run_path(
            project_id,
            validation_run_id,
        ).with_name("events.jsonl")

    def boba_validation_lease_path(self, project_id: str) -> Path:
        return self._path(project_id, "validator_runner/active.lock.json")

    def save_boba_validator_runner(
        self,
        runner: BobaValidatorRunnerSetV1,
    ) -> BobaValidatorRunnerSetV1:
        validated = BobaValidatorRunnerSetV1.model_validate(
            runner.model_dump(mode="json")
        )
        with self._lock:
            for snapshot in validated.registry_snapshots:
                path = self.boba_validator_registry_path(
                    validated.project_id,
                    snapshot.registry_snapshot_id,
                )
                payload = {
                    "schema_version": "boba_validator_registry_record_v1",
                    "project_id": validated.project_id,
                    "registry_snapshot": snapshot.model_dump(mode="json"),
                    "validator_descriptors": [
                        item.model_dump(mode="json")
                        for item in validated.validator_descriptors
                        if item.validator_id in snapshot.validator_ids
                        and snapshot.validator_versions.get(item.validator_id)
                        == item.validator_version
                    ],
                }
                existing = self._read(path, None)
                if isinstance(existing, dict) and existing != payload:
                    raise ValidationError(
                        "Completed Validator Runner registry snapshots are immutable."
                    )
                self._atomic_write_compact(path, payload)
            for plan in validated.validation_plans:
                path = self.boba_validation_plan_path(
                    validated.project_id,
                    plan.validation_plan_id,
                )
                execution_policy_payload: dict[str, Any] | None = None
                for execution_policy in validated.execution_policies:
                    if execution_policy.execution_policy_id == plan.execution_policy_id:
                        execution_policy_payload = execution_policy.model_dump(mode="json")
                        break
                resource_budget_payload: dict[str, Any] | None = None
                for resource_budget in validated.resource_budgets:
                    if resource_budget.resource_budget_id == plan.resource_budget_id:
                        resource_budget_payload = resource_budget.model_dump(mode="json")
                        break
                plan_payload: dict[str, Any] = {
                    "schema_version": "boba_validation_plan_record_v1",
                    "project_id": validated.project_id,
                    "plan": plan.model_dump(mode="json"),
                    "checks": [
                        item.model_dump(mode="json")
                        for item in validated.plan_checks
                        if item.validation_plan_id == plan.validation_plan_id
                    ],
                    "input_bindings": [
                        item.model_dump(mode="json")
                        for item in validated.input_bindings
                        if item.validation_plan_id == plan.validation_plan_id
                    ],
                    "execution_policy": execution_policy_payload,
                    "resource_budget": resource_budget_payload,
                }
                existing = self._read(path, None)
                if isinstance(existing, dict) and existing != plan_payload:
                    raise ValidationError(
                        "Completed Validator Runner plans are immutable."
                    )
                self._atomic_write_compact(path, plan_payload)
            for run in validated.validation_runs:
                run_checks = [
                    item
                    for item in validated.check_runs
                    if item.validation_run_id == run.validation_run_id
                ]
                for check in run_checks:
                    path = self.boba_validation_check_path(
                        validated.project_id,
                        run.validation_run_id,
                        check.check_run_id,
                    )
                    result_payload: dict[str, Any] | None = None
                    for result in validated.validation_results:
                        if result.check_run_id == check.check_run_id:
                            result_payload = result.model_dump(mode="json")
                            break
                    check_payload: dict[str, Any] = {
                        "schema_version": "boba_validation_check_record_v1",
                        "project_id": validated.project_id,
                        "check_run": check.model_dump(mode="json"),
                        "result": result_payload,
                        "evidence": [
                            item.model_dump(mode="json")
                            for item in validated.evidence_records
                            if item.check_run_id == check.check_run_id
                        ],
                    }
                    existing = self._read(path, None)
                    existing_check = (
                        existing.get("check_run")
                        if isinstance(existing, dict)
                        else None
                    )
                    existing_status = (
                        str(existing_check.get("status") or "")
                        if isinstance(existing_check, dict)
                        else ""
                    )
                    if (
                        existing_status
                        in {
                            "passed",
                            "failed",
                            "unavailable",
                            "blocked",
                            "errored",
                            "timed_out",
                            "cancelled",
                            "skipped_not_required",
                            "superseded",
                            "dependency_blocked",
                        }
                        and existing != check_payload
                    ):
                        raise ValidationError(
                            "Completed Validator Runner check records are immutable."
                        )
                    self._atomic_write_compact(path, check_payload)
                run_path = self.boba_validation_run_path(
                    validated.project_id,
                    run.validation_run_id,
                )
                run_payload = {
                    "schema_version": "boba_validation_run_record_v1",
                    "project_id": validated.project_id,
                    "run": run.model_dump(mode="json"),
                    "environment_snapshot": next(
                        (
                            item.model_dump(mode="json")
                            for item in validated.environment_snapshots
                            if item.environment_snapshot_id
                            == run.environment_snapshot_id
                        ),
                        None,
                    ),
                    "check_run_ids": [item.check_run_id for item in run_checks],
                    "suite_decision": next(
                        (
                            item.model_dump(mode="json")
                            for item in validated.suite_decisions
                            if item.validation_run_id == run.validation_run_id
                        ),
                        None,
                    ),
                    "incident_ids": [
                        item.incident_id
                        for item in validated.incidents
                        if item.validation_run_id == run.validation_run_id
                    ],
                    "handoff_ids": [
                        item.handoff_id
                        for item in validated.handoffs
                        if item.validation_run_id == run.validation_run_id
                    ],
                }
                existing = self._read(run_path, None)
                existing_run = (
                    existing.get("run") if isinstance(existing, dict) else None
                )
                existing_status = (
                    str(existing_run.get("run_status") or "")
                    if isinstance(existing_run, dict)
                    else ""
                )
                if (
                    existing_status
                    in {
                        "completed",
                        "failed",
                        "blocked",
                        "incomplete",
                        "timed_out",
                        "cancelled",
                    }
                    and existing != run_payload
                ):
                    raise ValidationError(
                        "Completed Validator Runner run records are immutable."
                    )
                self._atomic_write_compact(run_path, run_payload)
                self.append_boba_validation_events(
                    validated.project_id,
                    run.validation_run_id,
                    [
                        item
                        for item in validated.events
                        if item.validation_run_id == run.validation_run_id
                    ],
                )
            self._atomic_write_compact(
                self.boba_validator_runner_path(validated.project_id),
                {
                    "schema_version": "boba_validator_runner_record_v1",
                    "validator_runner": validated.model_dump(mode="json"),
                },
            )
        return validated

    def load_boba_validator_runner(
        self,
        project_id: str,
    ) -> BobaValidatorRunnerSetV1 | None:
        try:
            raw = self._read(self.boba_validator_runner_path(project_id), None)
        except ValidationError:
            return None
        if not isinstance(raw, dict):
            return None
        payload = raw.get("validator_runner", raw)
        if not isinstance(payload, dict):
            return None
        try:
            return BobaValidatorRunnerSetV1.model_validate(payload)
        except PydanticValidationError:
            return None

    def append_boba_validation_events(
        self,
        project_id: str,
        validation_run_id: str,
        events: list[BobaValidationEventV1],
    ) -> None:
        path = self.boba_validation_events_path(project_id, validation_run_id)
        existing_ids: set[str] = set()
        sequence = 0
        if path.exists():
            try:
                for line in path.read_text(encoding="utf-8-sig").splitlines():
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        existing_ids.add(str(payload.get("event_id") or ""))
                        sequence = max(sequence, int(payload.get("sequence") or 0))
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValidationError(
                    "BOBA Validator Runner event stream is unreadable."
                ) from exc
        new_events = sorted(
            [item for item in events if item.event_id not in existing_ids],
            key=lambda item: item.sequence,
        )
        if not new_events:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for event in new_events:
                if event.sequence <= sequence:
                    raise ValidationError(
                        "Validator Runner event sequence must be monotonic."
                    )
                sequence = event.sequence
                handle.write(
                    json.dumps(
                        event.model_dump(mode="json"),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def load_boba_validation_lease(
        self,
        project_id: str,
    ) -> BobaValidationLeaseV1 | None:
        raw = self._read(self.boba_validation_lease_path(project_id), None)
        if not isinstance(raw, dict):
            return None
        try:
            lease = BobaValidationLeaseV1.model_validate(raw)
        except PydanticValidationError as exc:
            raise ValidationError(
                "BOBA Validator Runner lease metadata is malformed."
            ) from exc
        expires_at = self._autopilot_time(lease.expires_at)
        lease.stale = expires_at is None or expires_at <= datetime.now(UTC)
        if lease.stale:
            lease.lease_status = "expired"
        return lease

    def acquire_boba_validation_lease(
        self,
        project_id: str,
        *,
        validation_run_id: str,
        validation_plan_id: str,
        target_id: str,
        owner_id: str,
        environment_digest: str,
        workspace_reference: str,
        lease_seconds: int = 300,
        confirm_stale: bool = False,
    ) -> BobaValidationLeaseV1:
        path = self.boba_validation_lease_path(project_id)
        with self._lock:
            existing = self.load_boba_validation_lease(project_id)
            if existing is not None and not existing.stale:
                if (
                    existing.validation_run_id == validation_run_id
                    and existing.owner_id == owner_id
                ):
                    return existing
                raise ValidationError(
                    "A conflicting Validator Runner execution lease is active."
                )
            warnings: list[str] = []
            if existing is not None:
                if not confirm_stale:
                    raise ValidationError(
                        "A stale Validator Runner lease requires explicit replacement."
                    )
                stale_path = path.with_name(
                    f"active.lock.stale.{uuid4().hex}.json"
                )
                with suppress(FileNotFoundError):
                    os.replace(path, stale_path)
                warnings.append("The explicitly replaced stale lease was preserved.")
            now = datetime.now(UTC)
            lease = BobaValidationLeaseV1(
                lease_id=f"validation_lease_{uuid4().hex}",
                project_id=project_id,
                validation_run_id=validation_run_id,
                validation_plan_id=validation_plan_id,
                target_id=target_id,
                owner_id=owner_id,
                acquired_at=now.isoformat(),
                refreshed_at=now.isoformat(),
                expires_at=(
                    now + timedelta(seconds=max(30, min(lease_seconds, 900)))
                ).isoformat(),
                lease_status="active",
                stale=False,
                environment_digest=environment_digest,
                workspace_reference=workspace_reference,
                warnings=warnings,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8", newline="\n") as handle:
                    json.dump(
                        lease.model_dump(mode="json"),
                        handle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError as exc:
                raise ValidationError(
                    "A Validator Runner lease was acquired concurrently."
                ) from exc
            return lease

    def release_boba_validation_lease(
        self,
        project_id: str,
        *,
        validation_run_id: str,
        owner_id: str,
    ) -> bool:
        path = self.boba_validation_lease_path(project_id)
        with self._lock:
            lease = self.load_boba_validation_lease(project_id)
            if lease is None:
                return False
            if (
                lease.validation_run_id != validation_run_id
                or lease.owner_id != owner_id
            ):
                raise ValidationError(
                    "Validator Runner lease belongs to another run or owner."
                )
            path.unlink(missing_ok=True)
            return True

    def export_boba_validator_runner(self, project_id: str) -> dict[str, Any]:
        runner = self.load_boba_validator_runner(project_id)
        if runner is None:
            raise ValidationError(
                "BOBA Validator Runner is not available for export."
            )
        safe = sanitize_validator_export(
            {
                "schema_version": "boba_validator_runner_export_v1",
                "project_id": project_id,
                "exported_at": memory_now_iso(),
                "validator_runner": runner.model_dump(mode="json"),
                "privacy": {
                    "private_paths_excluded": True,
                    "secrets_excluded": True,
                    "complete_logs_excluded": True,
                    "raw_media_excluded": True,
                    "source_media_modified": False,
                    "accepted_outputs_modified": False,
                    "network_used": False,
                    "upload_used": False,
                    "publication_used": False,
                },
            }
        )
        if not isinstance(safe, dict):
            raise ValidationError("Validator Runner export is malformed.")
        return safe

    def reset_boba_validator_runner(self, project_id: str) -> dict[str, Any]:
        runner = self.load_boba_validator_runner(project_id)
        if runner is not None and any(
            run.run_status
            not in {
                "completed",
                "failed",
                "blocked",
                "incomplete",
                "timed_out",
                "cancelled",
            }
            for run in runner.validation_runs
        ):
            raise ValidationError(
                "Active validation runs must be cancelled before reset."
            )
        index_path = self.boba_validator_runner_path(project_id)
        lock_path = self.boba_validation_lease_path(project_id)
        with self._lock:
            active_removed = index_path.exists()
            lease_removed = lock_path.exists()
            index_path.unlink(missing_ok=True)
            lock_path.unlink(missing_ok=True)
        return {
            "schema_version": "boba_validator_runner_reset_v1",
            "project_id": project_id,
            "active_metadata_removed": active_removed,
            "active_lease_removed": lease_removed,
            "immutable_registry_history_preserved": True,
            "immutable_plan_history_preserved": True,
            "immutable_run_history_preserved": True,
            "check_records_preserved": True,
            "evidence_records_preserved": True,
            "event_streams_preserved": True,
            "source_media_removed": False,
            "accepted_outputs_removed": False,
            "workflow_history_removed": False,
            "safety_decisions_removed": False,
            "approvals_removed": False,
        }
