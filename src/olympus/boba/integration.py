"""Read existing Olympus artifacts and build bounded BOBA advisory context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from olympus.boba.approval_rejection_learning import (
    BobaApprovalRejectionLearningSetV1,
    BobaApprovalRejectionLearningV1,
    BobaApprovalRejectionModuleGuidanceV1,
)
from olympus.boba.approvals import BobaApprovalService
from olympus.boba.artifact_inspector import (
    BobaArtifactInspectionModeV1,
    BobaArtifactInspectorV1,
)
from olympus.boba.autopilot_controller import (
    BobaAutopilotActionV1,
    BobaAutopilotControllerSetV1,
    BobaAutopilotControllerV1,
    BobaAutopilotControlModeV1,
    BobaAutopilotTriggerV1,
)
from olympus.boba.brain import BobaBrain
from olympus.boba.candidate_review import BobaCandidateReviewV1
from olympus.boba.candidate_video_scorer import (
    BobaCandidateVideoScorerSetV1,
    BobaCandidateVideoScorerV1,
)
from olympus.boba.caption_motion import (
    BobaCaptionMotionRecommendationBrainV1,
    BobaCaptionMotionRecommendationSetV1,
)
from olympus.boba.clip_brief import BobaClipBriefGeneratorV1, BobaClipBriefSetV1
from olympus.boba.clip_discovery import (
    BobaCandidateClipDiscoveryEngine,
    BobaCandidateClipDiscoveryV1,
)
from olympus.boba.clip_ranking import (
    BobaClipRankingEngine,
)
from olympus.boba.clip_ranking import (
    BobaClipRankingV1 as BobaDiscoveryClipRankingV1,
)
from olympus.boba.code_surgeon import (
    BobaCodeApprovalRecordV1,
    BobaCodeProposalSourceV1,
    BobaCodeSurgeonSetV1,
    BobaCodeSurgeonV1,
)
from olympus.boba.content_scout import (
    BobaContentScoutSetV2,
    BobaContentScoutV2,
)
from olympus.boba.contracts import (
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaReasoningV1,
)
from olympus.boba.creative_director import (
    BobaCreativeBriefV1,
    BobaCreativeDirectionSetV2,
    BobaCreativeDirector,
    BobaCreativeDirectorV2Engine,
)
from olympus.boba.creator_learning import (
    BobaCreatorFeedbackEventType,
    BobaCreatorFeedbackEventV1,
    BobaCreatorFeedbackTargetType,
    BobaCreatorLearningLoopV1,
    BobaCreatorLearningSetV1,
    BobaCreatorUserAction,
    BobaRecommendationGuidanceV1,
)
from olympus.boba.decision_bus import BobaDecisionBus
from olympus.boba.editorial_decision import (
    BobaEditorialDecisionEngine,
    BobaEditorialDecisionSetV1,
)
from olympus.boba.editorial_policy import create_editorial_policy
from olympus.boba.error_doctor import BobaErrorDoctorSetV1, BobaErrorDoctorV1
from olympus.boba.experimentation import (
    BobaExperimentationSetV1,
    BobaExperimentationSystemV1,
    BobaExperimentManualResultV1,
    BobaExperimentOutcomeLabel,
)
from olympus.boba.explanation import BobaExplanationEngine, BobaExplanationSetV1
from olympus.boba.final_decision_bus import BobaFinalDecisionBusV1
from olympus.boba.global_memory import build_and_save_global_memory
from olympus.boba.hook_retention import (
    BobaHookRetentionBrainV1,
    BobaHookRetentionSetV1,
)
from olympus.boba.integration_layer import (
    BobaIntegrationApprovalBindingV1,
    BobaIntegrationArtifactReferenceV1,
    BobaIntegrationEnvelopeV1,
    BobaIntegrationLayerSetV1,
    BobaIntegrationLayerV1,
    BobaIntegrationRequestV1,
    BobaIntegrationResponseV1,
    BobaIntegrationSafetyBindingV1,
    BobaIntegrationTransactionV1,
    sanitize_integration_export,
)
from olympus.boba.memory_application import create_memory_application
from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.memory_retrieval import (
    retrieve_for_clip_decision,
    retrieve_for_editorial_policy,
    retrieve_for_project,
)
from olympus.boba.music_mood import (
    BobaMusicMoodBrainV1,
    BobaMusicMoodRecommendationSetV1,
    music_manifest_awareness,
)
from olympus.boba.observer import BobaObserverSetV1, BobaObserverV1
from olympus.boba.output_quality_reviewer import (
    BobaOutputComparisonBasisV1,
    BobaOutputQualityReviewerSetV1,
    BobaOutputQualityReviewerV1,
    BobaOutputReviewModeV1,
    compare_boba_output_quality_baseline,
    generate_boba_output_quality_review,
    record_boba_output_human_review,
    run_boba_output_technical_review,
)
from olympus.boba.performance_feedback import (
    BobaManualPerformanceMetricsV1,
    BobaPerformanceEventType,
    BobaPerformanceFeedbackBrainV1,
    BobaPerformanceFeedbackEventV1,
    BobaPerformanceFeedbackSetV1,
    BobaPerformanceOutcomeLabel,
    BobaPerformanceTargetType,
)
from olympus.boba.project_memory import build_and_save_project_memory
from olympus.boba.ranking import rank_candidates
from olympus.boba.reasoning import explain_clip_selection, summarize_project_understanding
from olympus.boba.repair_planner import (
    BobaRepairPlannerSetV1,
    BobaRepairPlannerV1,
)
from olympus.boba.report_reader import (
    BobaReportReaderV1,
    BobaReportReadingModeV1,
)
from olympus.boba.research_brain import (
    BobaResearchBrainSetV1,
    BobaResearchBrainV1,
)
from olympus.boba.review_ui import (
    BobaReviewUiV1,
    ReviewMode,
    ReviewTargetType,
)
from olympus.boba.rights_permission_gate import (
    BobaRightsPermissionGateSetV1,
    BobaRightsPermissionGateV1,
)
from olympus.boba.root_cause_analyzer import (
    BobaRootCauseAnalyzerSetV1,
    BobaRootCauseAnalyzerV1,
)
from olympus.boba.safety_gate import (
    BobaSafetyActionRequestV1,
    BobaSafetyDecisionInvalidationV1,
    BobaSafetyDecisionV1,
    BobaSafetyEvaluationCaseV1,
    BobaSafetyGateSetV1,
    BobaSafetyGateV1,
)
from olympus.boba.scout import BobaScout
from olympus.boba.store import BobaMemoryStore
from olympus.boba.tool_recovery import (
    BobaToolRecoveryApprovalV1,
    BobaToolRecoveryBrainSetV1,
    BobaToolRecoveryBrainV1,
)
from olympus.boba.trend_topic_watcher import (
    BobaTrendTopicWatcherSetV1,
    BobaTrendTopicWatcherV1,
)
from olympus.boba.validation import compact_boba_summary
from olympus.boba.validator_runner import BobaValidationTargetTypeV1
from olympus.boba.validator_runner_execution import BobaValidatorRunnerV1
from olympus.boba.whole_video import (
    BobaWholeVideoUnderstandingEngine,
    BobaWholeVideoUnderstandingV1,
    build_whole_video_memory_summary,
    whole_video_memory_record,
)
from olympus.boba.workflow_controller import (
    BobaWorkflowControllerSetV1,
    BobaWorkflowControllerV1,
    BobaWorkflowDefinitionSnapshotV1,
    BobaWorkflowEventV1,
    BobaWorkflowHumanDecisionV1,
    BobaWorkflowPauseCategoryV1,
    BobaWorkflowPauseRecordV1,
    BobaWorkflowRecoveryHoldV1,
    BobaWorkflowResumeEligibilityReviewV1,
    BobaWorkflowRunV1,
    BobaWorkflowTransitionDecisionV1,
    BobaWorkflowTransitionRequestV1,
    BobaWorkflowTransitionTypeV1,
)
from olympus.data.repositories.project_repository import StorageProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.music import load_music_assets
from olympus.personalization import apply as personalization
from olympus.platform.config import get_settings
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.rendering.artifacts import resolve_render_manifest
from olympus.utils import new_id


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _data(stage: dict[str, Any]) -> dict[str, Any]:
    return _dict(stage.get("data"))


_INTEGRATION_FACADE_OPERATION_IDS = (
    "observer.generate",
    "observer.load",
    "observer.export",
    "error_doctor.generate",
    "error_doctor.load",
    "error_doctor.export",
    "root_cause_analyzer.generate",
    "root_cause_analyzer.load",
    "root_cause_analyzer.export",
    "repair_planner.generate",
    "repair_planner.load",
    "repair_planner.export",
    "code_surgeon.propose",
    "code_surgeon.load",
    "code_surgeon.export",
    "tool_recovery_brain.plan",
    "tool_recovery_brain.health_check",
    "tool_recovery_brain.validate_output",
    "tool_recovery_brain.load",
    "tool_recovery_brain.export",
    "output_quality_reviewer.review",
    "output_quality_reviewer.compare",
    "output_quality_reviewer.load",
    "output_quality_reviewer.export",
    "autopilot_controller.create_run",
    "autopilot_controller.plan_next",
    "autopilot_controller.advance_safe",
    "autopilot_controller.coordinate_approved",
    "autopilot_controller.pause",
    "autopilot_controller.continue_controller",
    "autopilot_controller.cancel",
    "autopilot_controller.load",
    "autopilot_controller.export",
    "safety_gate.create_policy",
    "safety_gate.create_request",
    "safety_gate.evaluate",
    "safety_gate.revalidate",
    "safety_gate.load",
    "safety_gate.export",
    "whole_video_understanding.generate",
    "candidate_clip_discovery.discover",
    "clip_ranking.rank",
    "editorial_decision.generate",
    "creative_director.generate",
    "clip_brief.generate",
    "hook_retention.generate",
    "caption_motion.generate",
    "music_mood.generate",
    "rights_permission_gate.generate",
    "workflow_controller.build_definition",
    "workflow_controller.create_run",
    "workflow_controller.inspect",
    "workflow_controller.plan_next",
    "workflow_controller.create_transition_request",
    "workflow_controller.evaluate_transition",
    "workflow_controller.advance_safe_read_only",
    "workflow_controller.coordinate_approved_internal_transition",
    "workflow_controller.pause",
    "workflow_controller.continue_controller",
    "workflow_controller.cancel",
    "workflow_controller.create_recovery_hold",
    "workflow_controller.receive_recovery_result",
    "workflow_controller.evaluate_resume_eligibility",
    "workflow_controller.record_human_decision",
    "workflow_controller.load",
    "workflow_controller.export",
    "workflow_controller.reset",
"workflow_controller.complete_internal_output",
    "validator_runner.build_registry",
    "validator_runner.inspect_registry",
    "validator_runner.inspect_availability",
    "validator_runner.create_plan",
    "validator_runner.validate_plan",
    "validator_runner.create_run",
    "validator_runner.execute_run",
    "validator_runner.cancel_run",
    "validator_runner.retry_check",
    "validator_runner.inspect_results",
    "validator_runner.load",
    "validator_runner.export",
    "validator_runner.reset",
    "report_reader.inspect_registry",
    "report_reader.create_read_request",
    "report_reader.validate_references",
    "report_reader.read_reports",
    "report_reader.inspect_read_run",
    "report_reader.compare_reports",
    "report_reader.build_bundle",
    "report_reader.inspect_bundle",
    "report_reader.inspect_events",
    "report_reader.load",
    "report_reader.export",
    "report_reader.reset",
    "artifact_inspector.inspect_registry",
    "artifact_inspector.create_inspection_request",
    "artifact_inspector.validate_references",
    "artifact_inspector.inspect_artifacts",
    "artifact_inspector.inspect_run",
    "artifact_inspector.build_inventory",
    "artifact_inspector.inspect_lineage",
    "artifact_inspector.compare_artifacts",
    "artifact_inspector.inspect_events",
    "artifact_inspector.load",
    "artifact_inspector.export",
    "artifact_inspector.reset",
    "final_decision_bus.build_registries",
    "final_decision_bus.inspect_registries",
    "final_decision_bus.create_request",
    "final_decision_bus.validate_request",
    "final_decision_bus.collect_source_bindings",
    "final_decision_bus.validate_source_bindings",
    "final_decision_bus.build_evidence_requirements",
    "final_decision_bus.bind_evidence",
    "final_decision_bus.detect_conflicts",
    "final_decision_bus.evaluate_policy",
    "final_decision_bus.finalize_decision",
    "final_decision_bus.build_dispatch_envelope",
    "final_decision_bus.inspect_decision",
    "final_decision_bus.inspect_dispatch_envelope",
    "final_decision_bus.consume_dispatch_envelope",
    "final_decision_bus.invalidate_decision",
    "final_decision_bus.inspect_events",
    "final_decision_bus.load",
    "final_decision_bus.export",
    "final_decision_bus.reset",
    "review_ui.inspect_registry",
    "review_ui.create_session",
    "review_ui.update_session",
    "review_ui.build_queue",
    "review_ui.inspect_queue",
    "review_ui.build_snapshot",
    "review_ui.refresh_snapshot",
    "review_ui.inspect_target",
    "review_ui.create_action",
    "review_ui.validate_action",
    "review_ui.submit_action",
    "review_ui.inspect_receipt",
    "review_ui.inspect_timeline",
    "review_ui.inspect_events",
    "review_ui.acknowledge_notification",
    "review_ui.load",
    "review_ui.export",
    "review_ui.reset",
    "candidate_review.inspect_registry",
    "candidate_review.create_session",
    "candidate_review.update_session",
    "candidate_review.build_queue",
    "candidate_review.inspect_queue",
    "candidate_review.build_snapshot",
    "candidate_review.refresh_snapshot",
    "candidate_review.inspect_candidate",
    "candidate_review.compare_candidates",
    "candidate_review.calculate_overlaps",
    "candidate_review.create_action",
    "candidate_review.validate_action",
    "candidate_review.submit_action",
    "candidate_review.inspect_receipt",
    "candidate_review.inspect_timeline",
    "candidate_review.inspect_events",
    "candidate_review.load",
    "candidate_review.export",
    "candidate_review.reset",
)


class BobaIntegration:
    def __init__(
        self,
        storage: StoragePort,
        store: BobaMemoryStore,
        *,
        mode: str = "advise",
        memory_enabled: bool = True,
        allow_global_memory: bool = True,
    ) -> None:
        self.storage = storage
        self.projects = StorageProjectRepository(storage)
        self.store = store
        self.brain = BobaBrain(store, mode=mode)  # type: ignore[arg-type]
        self.bus = BobaDecisionBus(store)
        self.scout = BobaScout(store)
        self.content_scout_v2 = BobaContentScoutV2()
        self.research_brain = BobaResearchBrainV1()
        self.trend_topic_watcher = BobaTrendTopicWatcherV1()
        self.candidate_video_scorer = BobaCandidateVideoScorerV1()
        self.rights_permission_gate = BobaRightsPermissionGateV1()
        self.observer = BobaObserverV1(
            store.root,
            validation_report_root=store.root.parent / "validation_reports",
        )
        self.error_doctor = BobaErrorDoctorV1()
        self.root_cause_analyzer = BobaRootCauseAnalyzerV1()
        self.repair_planner = BobaRepairPlannerV1()
        source_repository_root = Path(__file__).resolve().parents[3]
        current_repository_root = Path.cwd().resolve()
        repository_root = (
            current_repository_root
            if (current_repository_root / ".git").exists()
            else source_repository_root
        )
        self.code_surgeon = BobaCodeSurgeonV1(repository_root)
        runtime_settings = get_settings()
        self.tool_recovery = BobaToolRecoveryBrainV1(
            repository_root,
            workspace_root=store.root / "tool_recovery" / "workspaces",
            ffmpeg_binary=runtime_settings.rendering.ffmpeg_binary,
            ffprobe_binary=runtime_settings.rendering.ffprobe_binary,
            transcription_provider=runtime_settings.ai.transcription_provider,
        )
        self.output_quality_reviewer = BobaOutputQualityReviewerV1(
            repository_root,
            storage_root=runtime_settings.storage.local_root,
            evidence_root=(
                store.root / "output_quality_reviewer" / "samples"
            ),
            ffmpeg_binary=runtime_settings.rendering.ffmpeg_binary,
            ffprobe_binary=runtime_settings.rendering.ffprobe_binary,
        )
        self.validator_runner = BobaValidatorRunnerV1(
            store,
            repository_root=repository_root,
            storage_root=runtime_settings.storage.local_root,
            ffmpeg_binary=runtime_settings.rendering.ffmpeg_binary,
            ffprobe_binary=runtime_settings.rendering.ffprobe_binary,
        )
        self.report_reader = BobaReportReaderV1(store)
        self.artifact_inspector = BobaArtifactInspectorV1(store, storage)
        self.final_decision_bus = BobaFinalDecisionBusV1(store)
        self.safety_gate = BobaSafetyGateV1(
            store,
            context_provider=self._safety_context,
        )
        self.creative_director = BobaCreativeDirector(store)
        self.creative_director_v2 = BobaCreativeDirectorV2Engine()
        self.clip_brief_generator = BobaClipBriefGeneratorV1()
        self.hook_retention_brain = BobaHookRetentionBrainV1()
        self.caption_motion_brain = BobaCaptionMotionRecommendationBrainV1()
        self.music_mood_brain = BobaMusicMoodBrainV1()
        self.experimentation_system = BobaExperimentationSystemV1()
        self.performance_feedback_brain = BobaPerformanceFeedbackBrainV1()
        self.creator_learning_loop = BobaCreatorLearningLoopV1()
        self.approval_rejection_learning = BobaApprovalRejectionLearningV1()
        self.whole_video = BobaWholeVideoUnderstandingEngine()
        self.candidate_discovery = BobaCandidateClipDiscoveryEngine()
        self.clip_ranking = BobaClipRankingEngine()
        self.editorial_decision = BobaEditorialDecisionEngine()
        self.explanation = BobaExplanationEngine()
        self.approvals = BobaApprovalService(store)
        self.autopilot_controller = BobaAutopilotControllerV1(
            store,
            context_provider=self._autopilot_context,
            module_invoker=self._invoke_autopilot_typed_module,
            safety_decision_validator=self.safety_gate.validate_for_autopilot,
        )
        self.workflow_controller = BobaWorkflowControllerV1(
            store,
            integration_layer_factory=self._integration_layer,
        )
        self.review_ui = BobaReviewUiV1(store, self)
        self.candidate_review = BobaCandidateReviewV1(store, self)
        self.memory_enabled = memory_enabled
        self.allow_global_memory = allow_global_memory

    def _ensure_global_memory(self) -> None:
        if (
            self.memory_enabled
            and self.allow_global_memory
            and self.store.load_global_memory() is None
        ):
            build_and_save_global_memory(self.store)

    def _safety_context(
        self,
        _project_id: str,
        _request: BobaSafetyActionRequestV1,
    ) -> dict[str, Any]:
        available_validators = {
            *self.repair_planner.validator_registry,
            *self.output_quality_reviewer.validator_registry,
        }
        return {"available_validators": sorted(available_validators)}

    async def _integration_project_exists(self, project_id: str) -> bool:
        return await self.projects.get(project_id) is not None

    async def _integration_context(
        self,
        project_id: str,
        request: BobaIntegrationRequestV1,
    ) -> dict[str, Any]:
        layer = self.store.load_boba_integration_layer(project_id)
        envelope = next(
            (
                item
                for item in layer.request_envelopes
                if item.envelope_id == request.envelope_id
            ),
            None,
        ) if layer is not None else None
        approval_records: dict[str, Any] = {}
        approval_record = request.request_parameters.get("approval_record")
        if (
            envelope is not None
            and envelope.approval_binding is not None
            and isinstance(approval_record, dict)
        ):
            approval_records[
                envelope.approval_binding.approval_record_id
            ] = approval_record
        safety_decisions: dict[str, Any] = {}
        if envelope is not None and envelope.safety_binding is not None:
            decision = self.store.load_boba_safety_decision(
                project_id,
                envelope.safety_binding.safety_decision_id,
            )
            if decision is not None:
                safety_decisions[decision.safety_decision_id] = decision
        controller = self.store.load_boba_autopilot_controller(project_id)
        action_id = str(
            request.request_parameters.get("autopilot_action_id") or ""
        )
        action = next(
            (
                item
                for item in controller.planned_actions
                if item.action_id == action_id and item.run_id == request.run_id
            ),
            None,
        ) if controller is not None and action_id else None
        target_operation = request.target_operation_id.split(".", 1)[-1]
        action_matches_target = bool(
            action is not None
            and (
                request.target_module_id == "autopilot_controller"
                or (
                    action.target_module == request.target_module_id
                    and action.target_operation == target_operation
                )
            )
        )
        workflow_controller = self.store.load_boba_workflow_controller(project_id)
        workflow_run_id = str(
            request.request_parameters.get("workflow_run_id") or ""
        )
        workflow_stage_instance_id = str(
            request.request_parameters.get("workflow_stage_instance_id") or ""
        )
        workflow_transition_request_id = str(
            request.request_parameters.get("workflow_transition_request_id")
            or ""
        )
        workflow_transition_decision_id = str(
            request.request_parameters.get("workflow_transition_decision_id")
            or ""
        )
        workflow_run = next(
            (
                item
                for item in workflow_controller.workflow_runs
                if item.workflow_run_id == workflow_run_id
            ),
            None,
        ) if workflow_controller is not None else None
        workflow_stage = next(
            (
                item
                for item in workflow_controller.stage_instances
                if item.stage_instance_id == workflow_stage_instance_id
                and item.workflow_run_id == workflow_run_id
            ),
            None,
        ) if workflow_controller is not None else None
        workflow_request = next(
            (
                item
                for item in workflow_controller.transition_requests
                if item.transition_request_id == workflow_transition_request_id
                and item.workflow_run_id == workflow_run_id
            ),
            None,
        ) if workflow_controller is not None else None
        workflow_decision = next(
            (
                item
                for item in workflow_controller.transition_decisions
                if item.transition_decision_id == workflow_transition_decision_id
                and item.transition_request_id == workflow_transition_request_id
            ),
            None,
        ) if workflow_controller is not None else None
        workflow_transition_valid = bool(
            workflow_run is not None
            and workflow_stage is not None
            and workflow_stage.status == "running"
            and workflow_request is not None
            and workflow_request.requested_operation_id
            == request.target_operation_id
            and workflow_decision is not None
            and workflow_decision.decision_valid
            and workflow_decision.decision
            in {
                "allowed_read_only_transition",
                "allowed_exact_internal_transition",
            }
            and workflow_request.project_snapshot_digest
            == workflow_run.project_snapshot_digest
            and workflow_decision.project_snapshot_current
            and workflow_decision.workflow_revision_current
        )
        rights = self.store.load_rights_permission_gate(project_id)
        rights_allowed = bool(
            rights is not None
            and rights.gate_decisions
            and all(not item.blocked for item in rights.gate_decisions)
        )
        return {
            "expected_run_id": action.run_id if action is not None else "",
            "approval_records": approval_records,
            "safety_decisions": safety_decisions,
            "autopilot_action_valid": action_matches_target,
            "workflow_transition_valid": workflow_transition_valid,
            "rights_allowed": rights_allowed,
            "project_state_uncertain": False,
            "active_target_operation_ids": [],
            "retry_allowed": False,
        }

    def _integration_handlers(self) -> dict[str, Any]:
        handlers: dict[str, Any] = {}
        for operation_id in _INTEGRATION_FACADE_OPERATION_IDS:
            handlers[operation_id] = (
                self._invoke_registered_boba_integration_operation
            )
        return handlers

    def _integration_layer(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> BobaIntegrationLayerV1:
        return BobaIntegrationLayerV1(
            self.store,
            project_id=project_id,
            source_id=source_id or project_id,
            handlers=self._integration_handlers(),
            project_exists=self._integration_project_exists,
            context_provider=self._integration_context,
        )

    def build_boba_workflow_definition(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
    ) -> BobaWorkflowDefinitionSnapshotV1:
        return self.workflow_controller.build_workflow_definition(
            project_id,
            source_id=source_id,
        )

    def create_boba_workflow_run(
        self,
        project_id: str,
        *,
        source_id: str,
        project_snapshot: dict[str, Any] | None,
        source_storage_reference: str,
        source_artifact_digest: str,
        clip_ids: list[str] | None = None,
        output_ids_by_clip: dict[str, str] | None = None,
        rights_status: str = "unknown",
    ) -> BobaWorkflowControllerSetV1:
        return self.workflow_controller.create_workflow_run(
            project_id,
            source_id=source_id,
            project_snapshot=project_snapshot,
            source_storage_reference=source_storage_reference,
            source_artifact_digest=source_artifact_digest,
            clip_ids=clip_ids or [],
            output_ids_by_clip=output_ids_by_clip or {},
            rights_status=rights_status,
        )

    def inspect_boba_workflow_run(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> dict[str, Any]:
        return self.workflow_controller.inspect_workflow_run(
            project_id,
            workflow_run_id,
        )

    def plan_boba_workflow_next_stage(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> dict[str, Any]:
        return self.workflow_controller.plan_next_stage(
            project_id,
            workflow_run_id,
        )

    def create_boba_workflow_transition_request(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        source_stage_instance_id: str,
        target_stage_id: str,
        expected_revision: int,
        transition_type: BobaWorkflowTransitionTypeV1,
        reason: str,
        clip_id: str | None = None,
        output_id: str | None = None,
        approval_record_id: str | None = None,
        safety_decision_id: str | None = None,
        integration_request_id: str | None = None,
        checkpoint_reference: str | None = None,
        checkpoint_digest: str | None = None,
        quality_decision_id: str | None = None,
        human_decision_id: str | None = None,
        expires_in_seconds: int = 300,
        idempotency_key: str | None = None,
    ) -> BobaWorkflowTransitionRequestV1:
        return self.workflow_controller.create_transition_request(
            project_id,
            workflow_run_id,
            source_stage_instance_id=source_stage_instance_id,
            target_stage_id=target_stage_id,
            expected_revision=expected_revision,
            transition_type=transition_type,
            reason=reason,
            clip_id=clip_id,
            output_id=output_id,
            approval_record_id=approval_record_id,
            safety_decision_id=safety_decision_id,
            integration_request_id=integration_request_id,
            checkpoint_reference=checkpoint_reference,
            checkpoint_digest=checkpoint_digest,
            quality_decision_id=quality_decision_id,
            human_decision_id=human_decision_id,
            expires_in_seconds=expires_in_seconds,
            idempotency_key=idempotency_key,
        )

    def evaluate_boba_workflow_transition(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_request_id: str,
        *,
        expected_revision: int,
        current_project_snapshot_digest: str,
        rights_clear: bool | None = None,
        approval_record: dict[str, Any] | None = None,
        safety_decision: BobaSafetyDecisionV1 | dict[str, Any] | None = None,
        checkpoint_valid: bool | None = None,
        technical_validation: dict[str, Any] | None = None,
        quality_decision: dict[str, Any] | None = None,
        human_decision: BobaWorkflowHumanDecisionV1
        | dict[str, Any]
        | None = None,
    ) -> BobaWorkflowTransitionDecisionV1:
        return self.workflow_controller.evaluate_transition_request(
            project_id,
            workflow_run_id,
            transition_request_id,
            expected_revision=expected_revision,
            current_project_snapshot_digest=current_project_snapshot_digest,
            rights_clear=rights_clear,
            approval_record=approval_record,
            safety_decision=safety_decision,
            checkpoint_valid=checkpoint_valid,
            technical_validation=technical_validation,
            quality_decision=quality_decision,
            human_decision=human_decision,
        )

    async def advance_boba_workflow_safe_read_only_stage(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_decision_id: str,
        *,
        expected_revision: int,
        integration_parameters: dict[str, Any] | None = None,
    ) -> BobaIntegrationResponseV1:
        return await self.workflow_controller.advance_safe_read_only_stage(
            project_id,
            workflow_run_id,
            transition_decision_id,
            expected_revision=expected_revision,
            integration_parameters=integration_parameters,
        )

    async def coordinate_approved_boba_workflow_transition(
        self,
        project_id: str,
        workflow_run_id: str,
        transition_decision_id: str,
        *,
        expected_revision: int,
        integration_parameters: dict[str, Any] | None = None,
        approval_binding: BobaIntegrationApprovalBindingV1 | None = None,
        safety_binding: BobaIntegrationSafetyBindingV1 | None = None,
    ) -> BobaIntegrationResponseV1:
        return await self.workflow_controller.coordinate_approved_internal_transition(
            project_id,
            workflow_run_id,
            transition_decision_id,
            expected_revision=expected_revision,
            integration_parameters=integration_parameters,
            approval_binding=approval_binding,
            safety_binding=safety_binding,
        )

    def pause_boba_workflow(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
        reason: str,
        category: BobaWorkflowPauseCategoryV1 = "manual",
        stage_instance_id: str | None = None,
    ) -> BobaWorkflowPauseRecordV1:
        return self.workflow_controller.pause_workflow(
            project_id,
            workflow_run_id,
            expected_revision=expected_revision,
            reason=reason,
            category=category,
            stage_instance_id=stage_instance_id,
        )

    def continue_boba_workflow_controller(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
    ) -> BobaWorkflowRunV1:
        return self.workflow_controller.continue_controller(
            project_id,
            workflow_run_id,
            expected_revision=expected_revision,
        )

    def cancel_boba_workflow_run(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
        reason: str,
    ) -> BobaWorkflowRunV1:
        return self.workflow_controller.cancel_workflow_run(
            project_id,
            workflow_run_id,
            expected_revision=expected_revision,
            reason=reason,
        )

    def create_boba_workflow_recovery_hold(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        failed_stage_instance_id: str,
        expected_revision: int,
        reason: str,
        observer_record_id: str | None = None,
    ) -> BobaWorkflowRecoveryHoldV1:
        return self.workflow_controller.create_recovery_hold(
            project_id,
            workflow_run_id,
            failed_stage_instance_id=failed_stage_instance_id,
            expected_revision=expected_revision,
            reason=reason,
            observer_record_id=observer_record_id,
        )

    def receive_boba_autopilot_recovery_result(
        self,
        project_id: str,
        workflow_run_id: str,
        recovery_hold_id: str,
        recovery_result: BobaIntegrationResponseV1 | dict[str, Any],
        *,
        expected_revision: int,
    ) -> BobaWorkflowRecoveryHoldV1:
        return self.workflow_controller.receive_autopilot_recovery_result(
            project_id,
            workflow_run_id,
            recovery_hold_id,
            recovery_result,
            expected_revision=expected_revision,
        )

    def evaluate_boba_workflow_resume_eligibility(
        self,
        project_id: str,
        workflow_run_id: str,
        recovery_hold_id: str,
        *,
        expected_revision: int,
        current_project_snapshot_digest: str,
        rights_clear: bool,
        approval_record: dict[str, Any] | None,
        safety_decision: BobaSafetyDecisionV1 | dict[str, Any] | None,
        checkpoint_valid: bool,
        rollback_state_clear: bool,
        technical_validation: dict[str, Any] | None,
        quality_decision: dict[str, Any] | None,
        human_decision: BobaWorkflowHumanDecisionV1
        | dict[str, Any]
        | None = None,
    ) -> BobaWorkflowResumeEligibilityReviewV1:
        return self.workflow_controller.evaluate_resume_eligibility(
            project_id,
            workflow_run_id,
            recovery_hold_id,
            expected_revision=expected_revision,
            current_project_snapshot_digest=current_project_snapshot_digest,
            rights_clear=rights_clear,
            approval_record=approval_record,
            safety_decision=safety_decision,
            checkpoint_valid=checkpoint_valid,
            rollback_state_clear=rollback_state_clear,
            technical_validation=technical_validation,
            quality_decision=quality_decision,
            human_decision=human_decision,
        )

    def record_boba_workflow_human_decision(
        self,
        project_id: str,
        workflow_run_id: str,
        *,
        expected_revision: int,
        decision_type: str,
        decision: str,
        reason: str,
        reviewer_reference: str,
        explicit_confirmation: bool,
        stage_instance_id: str | None = None,
        transition_request_id: str | None = None,
        conditions: list[str] | None = None,
        expires_in_seconds: int | None = None,
    ) -> BobaWorkflowHumanDecisionV1:
        return self.workflow_controller.record_human_workflow_decision(
            project_id,
            workflow_run_id,
            expected_revision=expected_revision,
            decision_type=decision_type,
            decision=decision,
            reason=reason,
            reviewer_reference=reviewer_reference,
            explicit_confirmation=explicit_confirmation,
            stage_instance_id=stage_instance_id,
            transition_request_id=transition_request_id,
            conditions=conditions or [],
            expires_in_seconds=expires_in_seconds,
        )

    def inspect_boba_workflow_events(
        self,
        project_id: str,
        workflow_run_id: str,
    ) -> list[BobaWorkflowEventV1]:
        return self.workflow_controller.inspect_workflow_events(
            project_id,
            workflow_run_id,
        )

    def load_boba_workflow_controller(
        self,
        project_id: str,
    ) -> BobaWorkflowControllerSetV1 | None:
        return self.store.load_boba_workflow_controller(project_id)

    def export_boba_workflow_controller(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.workflow_controller.export_workflow_controller(project_id)

    def reset_boba_workflow_controller(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.workflow_controller.reset_workflow_controller_metadata(
            project_id
        )

    @staticmethod
    def _bounded_integration_target_result(
        value: object | None,
        *,
        target_revalidated: bool = False,
        side_effects: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = BobaIntegration._model_payload(value)
        safe = sanitize_integration_export(payload)
        safe_payload = safe if isinstance(safe, dict) else {"value": safe}
        encoded = json.dumps(
            safe_payload,
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
        if len(encoded) > 18_000:
            digest = hashlib.sha256(encoded).hexdigest()
            safe_payload = {
                "available": bool(payload),
                "schema_version": str(payload.get("schema_version") or "unknown"),
                "result_digest": digest,
                "top_level_fields": sorted(str(key) for key in payload)[:64],
                "summary": (
                    "The target result was persisted by its owning module; "
                    "Integration Layer retained only a bounded reference summary."
                ),
            }
        safe_payload["_integration_target_revalidated"] = target_revalidated
        safe_payload["_integration_side_effects"] = side_effects or []
        return safe_payload

    def load_boba_validator_runner(
        self,
        project_id: str,
    ) -> Any:
        runner = self.store.load_boba_validator_runner(project_id)
        if runner is None:
            raise NotFoundError("BOBA Validator Runner is unavailable.")
        return runner

    def export_boba_validator_runner(self, project_id: str) -> dict[str, Any]:
        return self.validator_runner.export_validator_runner(project_id)

    def reset_boba_validator_runner(self, project_id: str) -> dict[str, Any]:
        return self.validator_runner.reset_validator_runner(project_id)

    def load_boba_report_reader(self, project_id: str) -> Any:
        reader = self.store.load_boba_report_reader(project_id)
        if reader is None:
            raise NotFoundError("BOBA Report Reader is unavailable.")
        return reader

    def export_boba_report_reader(self, project_id: str) -> dict[str, Any]:
        return self.report_reader.export_report_reader(project_id)

    def reset_boba_report_reader(self, project_id: str) -> dict[str, Any]:
        return self.report_reader.reset_report_reader_metadata(project_id)

    def load_boba_artifact_inspector(self, project_id: str) -> Any:
        inspector = self.store.load_boba_artifact_inspector(project_id)
        if inspector is None:
            raise NotFoundError("BOBA Artifact Inspector is unavailable.")
        return inspector

    def export_boba_artifact_inspector(self, project_id: str) -> dict[str, Any]:
        return self.artifact_inspector.export_artifact_inspection(project_id)

    def reset_boba_artifact_inspector(self, project_id: str) -> dict[str, Any]:
        return self.artifact_inspector.reset_artifact_inspector_metadata(project_id)

    def load_boba_final_decision_bus(self, project_id: str) -> Any:
        bus = self.store.load_boba_final_decision_bus(project_id)
        if bus is None:
            raise NotFoundError("BOBA Final Decision Bus is unavailable.")
        return bus

    def export_boba_final_decision_bus(self, project_id: str) -> dict[str, Any]:
        return self.final_decision_bus.export_final_decision_bus(project_id)

    def reset_boba_final_decision_bus(self, project_id: str) -> dict[str, Any]:
        return self.final_decision_bus.reset_final_decision_bus_metadata(project_id)

    # ------------------------------------------------------------------
    # BOBA Review UI V1 - fixed presentation and routing helpers
    # ------------------------------------------------------------------
    def build_boba_review_ui_registry(self, project_id: str) -> dict[str, Any]:
        return self.review_ui.build_review_ui_registry(project_id)

    def inspect_boba_review_ui_registry(self, project_id: str) -> dict[str, Any]:
        return self.review_ui.inspect_review_ui_registry(project_id)

    def create_boba_review_session(
        self,
        project_id: str,
        *,
        reviewer_context_id: str,
        review_mode: str = "project_overview",
        target_type: str = "project",
        target_id: str = "",
        expires_in_seconds: int = 3_600,
    ) -> dict[str, Any]:
        session = self.review_ui.create_review_session(
            project_id,
            reviewer_context_id=reviewer_context_id,
            review_mode=cast(ReviewMode, review_mode),
            target_type=cast(ReviewTargetType, target_type),
            target_id=target_id,
            expires_in_seconds=expires_in_seconds,
        )
        return session.model_dump(mode="json")

    def inspect_boba_review_session(
        self,
        project_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        return self.review_ui.get_review_session(project_id, session_id).model_dump(
            mode="json"
        )

    def update_boba_review_preferences(
        self,
        project_id: str,
        session_id: str,
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self.review_ui.update_review_preferences(project_id, session_id, updates)
        return session.model_dump(mode="json")

    def build_boba_review_queue(
        self,
        project_id: str,
        *,
        category: str | None = None,
        include_historical: bool = False,
        sort: str = "priority",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self.review_ui.build_review_queue(
            project_id,
            category=category,
            include_historical=include_historical,
            sort=sort,
            offset=offset,
            limit=limit,
        )

    def inspect_boba_review_queue(
        self,
        project_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.review_ui.inspect_review_queue(project_id, **kwargs)

    def build_boba_review_snapshot(
        self,
        project_id: str,
        session_id: str,
        review_target_id: str | None = None,
    ) -> dict[str, Any]:
        return self.review_ui.build_review_snapshot(project_id, session_id, review_target_id)

    def refresh_boba_review_snapshot(
        self,
        project_id: str,
        snapshot_id: str,
    ) -> dict[str, Any]:
        return self.review_ui.refresh_review_snapshot(project_id, snapshot_id)

    def inspect_boba_review_target(
        self,
        project_id: str,
        review_target_id: str,
    ) -> dict[str, Any]:
        return self.review_ui.inspect_review_target(project_id, review_target_id)

    def create_boba_review_action_request(
        self,
        project_id: str,
        *,
        review_session_id: str,
        review_snapshot_id: str,
        action_descriptor_id: str,
        decision_value: str | None = None,
        reason: str = "",
        confirmation_context_digest: str,
        idempotency_key: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        request = self.review_ui.create_review_action_request(
            project_id,
            review_session_id=review_session_id,
            review_snapshot_id=review_snapshot_id,
            action_descriptor_id=action_descriptor_id,
            decision_value=decision_value,
            reason=reason,
            confirmation_context_digest=confirmation_context_digest,
            idempotency_key=idempotency_key,
            confirmed=confirmed,
        )
        return request.model_dump(mode="json")

    def validate_boba_review_action_request(
        self,
        project_id: str,
        action_request_id: str,
    ) -> dict[str, Any]:
        return self.review_ui.validate_review_action_request(project_id, action_request_id)

    async def submit_boba_review_action_to_owner(
        self,
        project_id: str,
        action_request_id: str,
    ) -> dict[str, Any]:
        receipt = await self.review_ui.submit_review_action_to_owner(
            project_id, action_request_id
        )
        return receipt.model_dump(mode="json")

    def inspect_boba_review_action_receipt(
        self,
        project_id: str,
        action_request_id: str,
    ) -> dict[str, Any]:
        return self.review_ui.inspect_review_action_receipt(project_id, action_request_id)

    def inspect_boba_review_timeline(
        self,
        project_id: str,
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.review_ui.inspect_review_timeline(project_id, limit=limit)

    def inspect_boba_review_events(
        self,
        project_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.review_ui.inspect_review_events(
            project_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def acknowledge_boba_review_notification(
        self,
        project_id: str,
        session_id: str,
        notification_id: str,
    ) -> dict[str, Any]:
        session = self.review_ui.acknowledge_review_notification(
            project_id, session_id, notification_id
        )
        return session.model_dump(mode="json")

    def load_boba_review_ui(self, project_id: str) -> dict[str, Any]:
        existing = self.review_ui.load_review_ui(project_id)
        if existing is None:
            existing = self.review_ui.build_review_ui(project_id)
        if existing is None:
            raise NotFoundError("BOBA Review UI is unavailable.")
        return existing

    def export_boba_review_ui(self, project_id: str) -> dict[str, Any]:
        return self.review_ui.export_review_ui(project_id)

    def reset_boba_review_ui_metadata(
        self,
        project_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.review_ui.reset_review_ui_metadata(project_id, session_id)

    # ------------------------------------------------------------------
    # BOBA Candidate Review Panel V1 - fixed projection and routing helpers
    # ------------------------------------------------------------------
    def build_boba_candidate_review_registry(self, project_id: str) -> dict[str, Any]:
        return self.candidate_review.build_candidate_review_registry(project_id)

    def inspect_boba_candidate_review_registry(self, project_id: str) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate_review_registry(project_id)

    def create_boba_candidate_review_session(
        self,
        project_id: str,
        *,
        reviewer_context_id: str,
        selected_candidate_id: str | None = None,
        expires_in_seconds: int = 3_600,
    ) -> dict[str, Any]:
        session = self.candidate_review.create_candidate_review_session(
            project_id,
            reviewer_context_id=reviewer_context_id,
            selected_candidate_id=selected_candidate_id,
            expires_in_seconds=expires_in_seconds,
        )
        return session.model_dump(mode="json")

    def inspect_boba_candidate_review_session(
        self, project_id: str, session_id: str
    ) -> dict[str, Any]:
        return self.candidate_review.get_candidate_review_session(
            project_id, session_id
        ).model_dump(mode="json")

    def update_boba_candidate_review_session(
        self, project_id: str, session_id: str, updates: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self.candidate_review.update_candidate_review_session(
            project_id, session_id, updates
        ).model_dump(mode="json")

    def build_boba_candidate_review_queue(
        self,
        project_id: str,
        *,
        review_filter: str = "all_current",
        sort: str = "review_priority",
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self.candidate_review.build_candidate_queue(
            project_id,
            review_filter=review_filter,
            sort=sort,
            offset=offset,
            limit=limit,
        )

    def inspect_boba_candidate_review_queue(
        self, project_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate_queue(project_id, **kwargs)

    def build_boba_candidate_snapshot(
        self, project_id: str, session_id: str, candidate_id: str
    ) -> dict[str, Any]:
        return self.candidate_review.build_candidate_snapshot(
            project_id, session_id, candidate_id
        )

    def refresh_boba_candidate_snapshot(
        self, project_id: str, snapshot_id: str
    ) -> dict[str, Any]:
        return self.candidate_review.refresh_candidate_snapshot(project_id, snapshot_id)

    def inspect_boba_candidate(self, project_id: str, candidate_id: str) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate(project_id, candidate_id)

    def build_boba_candidate_comparison(
        self,
        project_id: str,
        candidate_ids: list[str],
        *,
        comparison_type: str = "side_by_side",
    ) -> dict[str, Any]:
        return self.candidate_review.build_candidate_comparison(
            project_id, candidate_ids, comparison_type=comparison_type
        )

    def calculate_boba_candidate_overlaps(
        self, project_id: str, candidate_id: str
    ) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate_overlaps(project_id, candidate_id)

    def inspect_boba_candidate_transcript(
        self, project_id: str, candidate_id: str, *, context_seconds: int = 15
    ) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate_transcript(
            project_id, candidate_id, context_seconds=context_seconds
        )

    def create_boba_candidate_action_request(
        self,
        project_id: str,
        *,
        candidate_review_session_id: str,
        candidate_snapshot_id: str,
        action_descriptor_id: str,
        decision_value: str | None = None,
        reason: str = "",
        confirmation_context_digest: str,
        idempotency_key: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        request = self.candidate_review.create_candidate_action_request(
            project_id,
            candidate_review_session_id=candidate_review_session_id,
            candidate_snapshot_id=candidate_snapshot_id,
            action_descriptor_id=action_descriptor_id,
            decision_value=decision_value,
            reason=reason,
            confirmation_context_digest=confirmation_context_digest,
            idempotency_key=idempotency_key,
            confirmed=confirmed,
        )
        return request.model_dump(mode="json")

    def validate_boba_candidate_action_request(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        return self.candidate_review.validate_candidate_action_request(project_id, request_id)

    async def submit_boba_candidate_action_to_owner(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        receipt = await self.candidate_review.submit_candidate_action_to_owner(
            project_id, request_id
        )
        return receipt.model_dump(mode="json")

    def inspect_boba_candidate_action_receipt(
        self, project_id: str, request_id: str
    ) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate_action_receipt(project_id, request_id)

    def inspect_boba_candidate_review_timeline(
        self, project_id: str, *, limit: int = 100
    ) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate_timeline(project_id, limit=limit)

    def inspect_boba_candidate_review_events(
        self, project_id: str, *, after_sequence: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        return self.candidate_review.inspect_candidate_events(
            project_id, after_sequence=after_sequence, limit=limit
        )

    def load_boba_candidate_review(self, project_id: str) -> dict[str, Any]:
        existing = self.candidate_review.load_candidate_review(project_id)
        if existing is None:
            existing = self.candidate_review.build_candidate_review(project_id)
        if existing is None:
            raise NotFoundError("BOBA Candidate Review Panel is unavailable.")
        return existing

    def export_boba_candidate_review(self, project_id: str) -> dict[str, Any]:
        return self.candidate_review.export_candidate_review(project_id)

    def reset_boba_candidate_review_metadata(
        self, project_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        return self.candidate_review.reset_candidate_review_metadata(project_id, session_id)

    async def _invoke_registered_boba_integration_operation(
        self,
        request: BobaIntegrationRequestV1,
    ) -> dict[str, Any]:
        operation_id = request.target_operation_id
        project_id = request.project_id
        values = dict(request.request_parameters)
        result: object | None
        side_effects: list[str] = []
        target_revalidated = False

        load_handlers = {
            "observer.load": self.load_observer_report,
            "error_doctor.load": self.load_boba_error_doctor,
            "root_cause_analyzer.load": self.load_boba_root_cause_analyzer,
            "repair_planner.load": self.load_boba_repair_planner,
            "code_surgeon.load": self.load_boba_code_surgeon,
            "tool_recovery_brain.load": self.load_boba_tool_recovery,
            "output_quality_reviewer.load": (
                self.load_boba_output_quality_reviewer
            ),
            "autopilot_controller.load": self.load_boba_autopilot_controller,
            "safety_gate.load": self.load_boba_safety_gate,
            "workflow_controller.load": self.load_boba_workflow_controller,
            "validator_runner.load": self.load_boba_validator_runner,
            "report_reader.load": self.load_boba_report_reader,
            "artifact_inspector.load": self.load_boba_artifact_inspector,
            "final_decision_bus.load": self.load_boba_final_decision_bus,
            "review_ui.load": self.load_boba_review_ui,
            "candidate_review.load": self.load_boba_candidate_review,
        }
        export_handlers = {
            "observer.export": self.export_observer_report,
            "error_doctor.export": self.export_boba_error_doctor,
            "root_cause_analyzer.export": self.export_boba_root_cause_analyzer,
            "repair_planner.export": self.export_boba_repair_planner,
            "code_surgeon.export": self.export_boba_code_surgeon,
            "tool_recovery_brain.export": self.export_boba_tool_recovery,
            "output_quality_reviewer.export": (
                self.export_boba_output_quality_reviewer
            ),
            "autopilot_controller.export": (
                self.export_boba_autopilot_controller
            ),
            "safety_gate.export": self.export_boba_safety_gate,
            "workflow_controller.export": self.export_boba_workflow_controller,
            "validator_runner.export": self.export_boba_validator_runner,
            "report_reader.export": self.export_boba_report_reader,
            "artifact_inspector.export": self.export_boba_artifact_inspector,
            "final_decision_bus.export": self.export_boba_final_decision_bus,
            "review_ui.export": self.export_boba_review_ui,
            "candidate_review.export": self.export_boba_candidate_review,
        }
        if operation_id in load_handlers:
            result = load_handlers[operation_id](project_id)
        elif operation_id in export_handlers:
            result = export_handlers[operation_id](project_id)
        elif operation_id == "validator_runner.build_registry":
            result = self.validator_runner.build_registry(
                project_id,
                source_id=str(values.get("source_id") or ""),
            )
            side_effects.append("validator_registry_metadata_updated")
        elif operation_id == "validator_runner.inspect_registry":
            result = self.validator_runner.inspect_registry(project_id)
        elif operation_id == "validator_runner.inspect_availability":
            result = self.validator_runner.inspect_availability(project_id)
        elif operation_id == "validator_runner.create_plan":
            result = self.validator_runner.create_validation_plan(
                project_id,
                source_id=str(values.get("source_id") or ""),
                target_type=cast(
                    BobaValidationTargetTypeV1,
                    str(values.get("target_type") or "unknown"),
                ),
                target_id=str(values.get("target_id") or ""),
                checks=[
                    dict(item)
                    for item in values.get("checks", [])
                    if isinstance(item, dict)
                ],
                input_bindings=[
                    dict(item)
                    for item in values.get("input_bindings", [])
                    if isinstance(item, dict)
                ],
                validation_objective=str(
                    values.get("validation_objective") or ""
                ),
                acceptance_criteria=[
                    str(item) for item in values.get("acceptance_criteria", [])
                ],
                rejection_criteria=[
                    str(item) for item in values.get("rejection_criteria", [])
                ],
                plan_source_module=str(
                    values.get("plan_source_module") or "integration_layer"
                ),
                plan_source_record_id=str(
                    values.get("plan_source_record_id") or ""
                ),
                target_digest=str(values.get("target_digest") or ""),
                project_snapshot_digest=str(
                    values.get("project_snapshot_digest") or ""
                ),
                workflow_run_id=str(values.get("workflow_run_id") or ""),
                stage_instance_id=str(values.get("stage_instance_id") or ""),
                workflow_revision=int(values.get("workflow_revision") or 0),
                approval_record_id=str(
                    values.get("approval_record_id") or ""
                ),
                safety_decision_id=str(
                    values.get("safety_decision_id") or ""
                ),
                policy_mode=cast(
                    Literal[
                        "artifact_only",
                        "media_inspection",
                        "isolated_code",
                    ] | None,
                    str(values["policy_mode"])
                    if values.get("policy_mode")
                    else None,
                ),
                resource_budget_overrides=(
                    {
                        str(key): int(value)
                        for key, value in _dict(
                            values.get("resource_budget_overrides")
                        ).items()
                    }
                    or None
                ),
                allow_unavailable_required=bool(
                    values.get("allow_unavailable_required", False)
                ),
            )
            side_effects.append("validator_plan_metadata_updated")
        elif operation_id == "validator_runner.validate_plan":
            result = self.validator_runner.validate_validation_plan(
                project_id,
                validation_plan_id=str(
                    values.get("validation_plan_id") or ""
                ),
                allow_unavailable_required=bool(
                    values.get("allow_unavailable_required", False)
                ),
            )
        elif operation_id == "validator_runner.create_run":
            result = self.validator_runner.create_validation_run(
                project_id,
                str(values.get("validation_plan_id") or ""),
            )
            side_effects.append("validator_run_metadata_updated")
        elif operation_id == "validator_runner.execute_run":
            result = self.validator_runner.execute_validation_run(
                project_id,
                str(values.get("validation_run_id") or ""),
                confirm_stale_lease=bool(
                    values.get("confirm_stale_lease", False)
                ),
            )
            target_revalidated = True
            side_effects.append("validator_evidence_metadata_updated")
        elif operation_id == "validator_runner.cancel_run":
            result = self.validator_runner.cancel_validation_run(
                project_id,
                str(values.get("validation_run_id") or ""),
            )
            side_effects.append("validator_cancellation_metadata_updated")
        elif operation_id == "validator_runner.retry_check":
            result = self.validator_runner.retry_validation_check(
                project_id,
                str(values.get("validation_run_id") or ""),
                str(values.get("plan_check_id") or ""),
            )
            target_revalidated = True
            side_effects.append("validator_retry_metadata_updated")
        elif operation_id == "validator_runner.inspect_results":
            result = self.validator_runner.inspect_results(
                project_id,
                str(values.get("validation_run_id") or ""),
            )
        elif operation_id == "validator_runner.reset":
            result = self.reset_boba_validator_runner(project_id)
            side_effects.append("validator_active_metadata_reset")
        elif operation_id == "report_reader.inspect_registry":
            result = self.report_reader.inspect_report_source_registry(
                project_id,
                source_id=str(values.get("source_id") or "integration_layer"),
            )
        elif operation_id == "report_reader.create_read_request":
            result = self.report_reader.create_report_read_request(
                project_id,
                source_id=str(values.get("source_id") or "integration_layer"),
                requested_by_module=str(values.get("requested_by_module") or "integration_layer"),
                reading_mode=cast(
                    BobaReportReadingModeV1,
                    str(values.get("reading_mode") or "unknown"),
                ),
                report_references=[
                    dict(item)
                    for item in values.get("report_references", [])
                    if isinstance(item, dict)
                ],
                workflow_run_id=str(values.get("workflow_run_id") or ""),
                current_project_snapshot_digest=str(
                    values.get("current_project_snapshot_digest") or ""
                ),
                maximum_total_bytes=int(values.get("maximum_total_bytes") or 4_194_304),
                maximum_total_records=int(values.get("maximum_total_records") or 10_000),
                include_chronology=bool(values.get("include_chronology", True)),
                include_contradictions=bool(values.get("include_contradictions", True)),
                include_easy_summary=bool(values.get("include_easy_summary", True)),
                include_open_questions=bool(values.get("include_open_questions", True)),
            )
            side_effects.append("report_reader_request_metadata_updated")
        elif operation_id == "report_reader.validate_references":
            result = self.report_reader.validate_report_references(
                project_id,
                str(values.get("read_request_id") or ""),
            )
        elif operation_id == "report_reader.read_reports":
            result = self.report_reader.read_registered_reports(
                project_id,
                str(values.get("read_request_id") or ""),
            )
            side_effects.append("report_reader_read_metadata_updated")
        elif operation_id == "report_reader.inspect_read_run":
            result = self.report_reader.inspect_report_read_run(
                project_id,
                str(values.get("read_run_id") or ""),
            )
        elif operation_id == "report_reader.compare_reports":
            result = self.report_reader.compare_registered_reports(
                project_id,
                read_run_id=str(values.get("read_run_id") or ""),
            )
        elif operation_id == "report_reader.build_bundle":
            result = self.report_reader.build_report_bundle(
                project_id,
                read_run_id=str(values.get("read_run_id") or ""),
                purpose=str(values.get("purpose") or "Report explanation"),
            )
            side_effects.append("report_reader_bundle_metadata_updated")
        elif operation_id == "report_reader.inspect_bundle":
            result = self.report_reader.inspect_report_bundle(
                project_id,
                str(values.get("report_bundle_id") or ""),
            )
        elif operation_id == "report_reader.inspect_events":
            result = self.report_reader.inspect_report_events(
                project_id,
                str(values.get("read_run_id") or ""),
            )
        elif operation_id == "report_reader.reset":
            result = self.reset_boba_report_reader(project_id)
            side_effects.append("report_reader_active_metadata_reset")
        elif operation_id == "artifact_inspector.inspect_registry":
            result = self.artifact_inspector.inspect_artifact_registry(
                project_id,
                source_id=str(values.get("source_id") or "integration_layer"),
            )
        elif operation_id == "artifact_inspector.create_inspection_request":
            result = self.artifact_inspector.create_inspection_request(
                project_id,
                source_id=str(values.get("source_id") or "integration_layer"),
                requested_by_module=str(
                    values.get("requested_by_module") or "integration_layer"
                ),
                inspection_mode=cast(
                    BobaArtifactInspectionModeV1,
                    str(values.get("inspection_mode") or "exact_artifact"),
                ),
                artifact_references=[
                    dict(item)
                    for item in values.get("artifact_references", [])
                    if isinstance(item, dict)
                ],
                workflow_run_id=str(values.get("workflow_run_id") or ""),
                project_snapshot_digest=str(
                    values.get("project_snapshot_digest") or ""
                ),
                inspect_content=bool(values.get("inspect_content", False)),
                recompute_digests=bool(values.get("recompute_digests", True)),
                include_inventory=bool(values.get("include_inventory", True)),
                include_lineage=bool(values.get("include_lineage", True)),
            )
            side_effects.append("artifact_inspector_request_metadata_updated")
        elif operation_id == "artifact_inspector.validate_references":
            result = self.artifact_inspector.validate_artifact_references(
                project_id,
                str(values.get("inspection_request_id") or ""),
            )
        elif operation_id == "artifact_inspector.inspect_artifacts":
            result = self.artifact_inspector.inspect_artifacts(
                project_id,
                str(values.get("inspection_request_id") or ""),
            )
            side_effects.append("artifact_inspector_run_metadata_updated")
        elif operation_id == "artifact_inspector.inspect_run":
            result = self.artifact_inspector.inspect_run(
                project_id,
                str(values.get("inspection_run_id") or ""),
            )
        elif operation_id == "artifact_inspector.build_inventory":
            result = self.artifact_inspector.build_project_inventory(
                project_id,
                inspection_run_id=str(values.get("inspection_run_id") or ""),
            )
        elif operation_id == "artifact_inspector.inspect_lineage":
            result = self.artifact_inspector.inspect_lineage(
                project_id,
                inspection_run_id=str(values.get("inspection_run_id") or ""),
            )
        elif operation_id == "artifact_inspector.compare_artifacts":
            result = self.artifact_inspector.compare_artifacts(
                project_id,
                inspection_run_id=str(values.get("inspection_run_id") or ""),
                left_reference_id=str(values.get("left_reference_id") or ""),
                right_reference_id=str(values.get("right_reference_id") or ""),
            )
        elif operation_id == "artifact_inspector.inspect_events":
            result = self.artifact_inspector.inspect_events(
                project_id,
                str(values.get("inspection_run_id") or ""),
            )
        elif operation_id == "artifact_inspector.reset":
            result = self.reset_boba_artifact_inspector(project_id)
            side_effects.append("artifact_inspector_active_metadata_reset")
        elif operation_id == "final_decision_bus.build_registries":
            result = self.final_decision_bus.build_final_decision_registries(
                project_id,
                source_id=str(values.get("source_id") or "integration_layer"),
            )
            side_effects.append("final_decision_registry_metadata_updated")
        elif operation_id == "final_decision_bus.inspect_registries":
            result = self.final_decision_bus.inspect_final_decision_registries(
                project_id,
                source_id=str(values.get("source_id") or "integration_layer"),
            )
        elif operation_id == "final_decision_bus.create_request":
            source_selectors = values.get("source_selectors")
            result = self.final_decision_bus.create_final_decision_request(
                project_id,
                source_id=str(values.get("source_id") or "integration_layer"),
                requested_by_module=str(values.get("requested_by_module") or "integration_layer"),
                action_policy_id=str(values.get("action_policy_id") or ""),
                target_module_id=str(values.get("target_module_id") or ""),
                target_operation_id=str(values.get("target_operation_id") or ""),
                source_selectors=[dict(item) for item in source_selectors if isinstance(item, dict)]
                if isinstance(source_selectors, list)
                else [],
                workflow_run_id=str(values.get("workflow_run_id") or ""),
                stage_instance_id=str(values.get("stage_instance_id") or ""),
                clip_id=str(values.get("clip_id") or ""),
                output_id=str(values.get("output_id") or ""),
                artifact_reference_id=str(values.get("artifact_reference_id") or ""),
                project_snapshot_digest=str(values.get("project_snapshot_digest") or ""),
                workflow_snapshot_digest=str(values.get("workflow_snapshot_digest") or ""),
                target_parameters_digest=str(values.get("target_parameters_digest") or ""),
                expires_at=str(values.get("expires_at") or "") or None,
            )
            side_effects.append("final_decision_request_metadata_updated")
        elif operation_id == "final_decision_bus.validate_request":
            result = self.final_decision_bus.validate_final_decision_request(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
        elif operation_id == "final_decision_bus.collect_source_bindings":
            result = self.final_decision_bus.collect_source_decision_bindings(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
            side_effects.append("final_decision_source_binding_metadata_updated")
        elif operation_id == "final_decision_bus.validate_source_bindings":
            result = self.final_decision_bus.validate_source_decision_bindings(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
        elif operation_id == "final_decision_bus.build_evidence_requirements":
            result = self.final_decision_bus.build_evidence_requirements(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
            side_effects.append("final_decision_evidence_requirement_metadata_updated")
        elif operation_id == "final_decision_bus.bind_evidence":
            result = self.final_decision_bus.bind_final_decision_evidence(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
            side_effects.append("final_decision_evidence_metadata_updated")
        elif operation_id == "final_decision_bus.detect_conflicts":
            result = self.final_decision_bus.detect_final_decision_conflicts(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
            side_effects.append("final_decision_conflict_metadata_updated")
        elif operation_id == "final_decision_bus.evaluate_policy":
            result = self.final_decision_bus.evaluate_final_action_policy(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
            side_effects.append("final_decision_evaluation_metadata_updated")
        elif operation_id == "final_decision_bus.finalize_decision":
            result = self.final_decision_bus.finalize_exact_internal_decision(
                project_id,
                str(values.get("final_decision_request_id") or ""),
            )
            side_effects.append("final_decision_immutable_metadata_recorded")
        elif operation_id == "final_decision_bus.build_dispatch_envelope":
            result = self.final_decision_bus.build_exact_dispatch_envelope(
                project_id,
                str(values.get("final_decision_id") or ""),
            )
            side_effects.append("final_dispatch_envelope_metadata_recorded")
        elif operation_id == "final_decision_bus.inspect_decision":
            result = self.final_decision_bus.inspect_final_decision(
                project_id,
                str(values.get("final_decision_id") or ""),
            )
        elif operation_id == "final_decision_bus.inspect_dispatch_envelope":
            result = self.final_decision_bus.inspect_dispatch_envelope(
                project_id,
                str(values.get("dispatch_envelope_id") or ""),
            )
        elif operation_id == "final_decision_bus.consume_dispatch_envelope":
            result = self.final_decision_bus.mark_dispatch_envelope_consumed(
                project_id,
                str(values.get("dispatch_envelope_id") or ""),
                integration_transaction_id=str(values.get("integration_transaction_id") or ""),
            )
            side_effects.append("final_dispatch_consumption_metadata_recorded")
        elif operation_id == "final_decision_bus.invalidate_decision":
            result = self.final_decision_bus.invalidate_final_decision(
                project_id,
                str(values.get("final_decision_id") or ""),
                reason=str(values.get("reason") or ""),
                invalidated_by_module=str(
                    values.get("invalidated_by_module") or "integration_layer"
                ),
            )
            side_effects.append("final_decision_invalidation_metadata_recorded")
        elif operation_id == "final_decision_bus.inspect_events":
            result = self.final_decision_bus.inspect_final_decision_events(
                project_id,
                final_decision_request_id=str(values.get("final_decision_request_id") or ""),
            )
        elif operation_id == "final_decision_bus.reset":
            result = self.reset_boba_final_decision_bus(project_id)
            side_effects.append("final_decision_active_metadata_reset")
        elif operation_id == "review_ui.inspect_registry":
            result = self.inspect_boba_review_ui_registry(project_id)
        elif operation_id == "review_ui.create_session":
            result = self.create_boba_review_session(
                project_id,
                reviewer_context_id=str(values.get("reviewer_context_id") or ""),
                review_mode=str(values.get("review_mode") or "project_overview"),
                target_type=str(values.get("target_type") or "project"),
                target_id=str(values.get("target_id") or ""),
            )
            side_effects.append("review_ui_session_metadata_updated")
        elif operation_id == "review_ui.update_session":
            result = self.update_boba_review_preferences(
                project_id,
                str(values.get("review_session_id") or ""),
                _dict(values.get("updates")),
            )
            side_effects.append("review_ui_session_metadata_updated")
        elif operation_id == "review_ui.build_queue":
            result = self.build_boba_review_queue(
                project_id,
                category=str(values.get("category") or "") or None,
                include_historical=bool(values.get("include_historical")),
                sort=str(values.get("sort") or "priority"),
                offset=int(values.get("offset") or 0),
                limit=int(values.get("limit") or 50),
            )
        elif operation_id == "review_ui.inspect_queue":
            result = self.inspect_boba_review_queue(project_id)
        elif operation_id == "review_ui.build_snapshot":
            result = self.build_boba_review_snapshot(
                project_id,
                str(values.get("review_session_id") or ""),
                str(values.get("review_target_id") or "") or None,
            )
            side_effects.append("review_ui_snapshot_metadata_updated")
        elif operation_id == "review_ui.refresh_snapshot":
            result = self.refresh_boba_review_snapshot(
                project_id,
                str(values.get("review_snapshot_id") or ""),
            )
            target_revalidated = True
            side_effects.append("review_ui_snapshot_metadata_updated")
        elif operation_id == "review_ui.inspect_target":
            result = self.inspect_boba_review_target(
                project_id,
                str(values.get("review_target_id") or ""),
            )
        elif operation_id == "review_ui.create_action":
            result = self.create_boba_review_action_request(
                project_id,
                review_session_id=str(values.get("review_session_id") or ""),
                review_snapshot_id=str(values.get("review_snapshot_id") or ""),
                action_descriptor_id=str(values.get("action_descriptor_id") or ""),
                decision_value=str(values.get("decision_value") or "") or None,
                reason=str(values.get("reason") or ""),
                confirmation_context_digest=str(
                    values.get("confirmation_context_digest") or ""
                ),
                idempotency_key=str(values.get("idempotency_key") or ""),
                confirmed=bool(values.get("confirmed")),
            )
            side_effects.append("review_ui_action_request_recorded")
        elif operation_id == "review_ui.validate_action":
            result = self.validate_boba_review_action_request(
                project_id,
                str(values.get("review_action_request_id") or ""),
            )
            target_revalidated = True
        elif operation_id == "review_ui.submit_action":
            result = await self.submit_boba_review_action_to_owner(
                project_id,
                str(values.get("review_action_request_id") or ""),
            )
            target_revalidated = True
            side_effects.append("review_ui_action_receipt_recorded")
        elif operation_id == "review_ui.inspect_receipt":
            result = self.inspect_boba_review_action_receipt(
                project_id,
                str(values.get("review_action_request_id") or ""),
            )
        elif operation_id == "review_ui.inspect_timeline":
            result = self.inspect_boba_review_timeline(
                project_id,
                limit=int(values.get("limit") or 100),
            )
        elif operation_id == "review_ui.inspect_events":
            result = self.inspect_boba_review_events(
                project_id,
                after_sequence=int(values.get("after_sequence") or 0),
                limit=int(values.get("limit") or 100),
            )
        elif operation_id == "review_ui.acknowledge_notification":
            result = self.acknowledge_boba_review_notification(
                project_id,
                str(values.get("review_session_id") or ""),
                str(values.get("notification_id") or ""),
            )
            side_effects.append("review_ui_session_metadata_updated")
        elif operation_id == "review_ui.reset":
            result = self.reset_boba_review_ui_metadata(
                project_id,
                str(values.get("review_session_id") or "") or None,
            )
            side_effects.append("review_ui_active_metadata_reset")
        elif operation_id == "candidate_review.inspect_registry":
            result = self.inspect_boba_candidate_review_registry(project_id)
        elif operation_id == "candidate_review.create_session":
            result = self.create_boba_candidate_review_session(
                project_id,
                reviewer_context_id=str(values.get("reviewer_context_id") or ""),
                selected_candidate_id=str(values.get("candidate_id") or "") or None,
            )
            side_effects.append("candidate_review_session_metadata_updated")
        elif operation_id == "candidate_review.update_session":
            result = self.update_boba_candidate_review_session(
                project_id,
                str(values.get("candidate_review_session_id") or ""),
                _dict(values.get("updates")),
            )
            side_effects.append("candidate_review_session_metadata_updated")
        elif operation_id == "candidate_review.build_queue":
            result = self.build_boba_candidate_review_queue(
                project_id,
                review_filter=str(values.get("review_filter") or "all_current"),
                sort=str(values.get("sort") or "review_priority"),
                offset=int(values.get("offset") or 0),
                limit=int(values.get("limit") or 50),
            )
        elif operation_id == "candidate_review.inspect_queue":
            result = self.inspect_boba_candidate_review_queue(project_id)
        elif operation_id == "candidate_review.build_snapshot":
            result = self.build_boba_candidate_snapshot(
                project_id,
                str(values.get("candidate_review_session_id") or ""),
                str(values.get("candidate_id") or ""),
            )
            side_effects.append("candidate_review_snapshot_metadata_updated")
        elif operation_id == "candidate_review.refresh_snapshot":
            result = self.refresh_boba_candidate_snapshot(
                project_id,
                str(values.get("candidate_snapshot_id") or ""),
            )
            target_revalidated = True
            side_effects.append("candidate_review_snapshot_metadata_updated")
        elif operation_id == "candidate_review.inspect_candidate":
            result = self.inspect_boba_candidate(
                project_id, str(values.get("candidate_id") or "")
            )
        elif operation_id == "candidate_review.compare_candidates":
            raw_ids = values.get("candidate_ids")
            result = self.build_boba_candidate_comparison(
                project_id,
                [str(item) for item in raw_ids] if isinstance(raw_ids, list) else [],
                comparison_type=str(values.get("comparison_type") or "side_by_side"),
            )
        elif operation_id == "candidate_review.calculate_overlaps":
            result = self.calculate_boba_candidate_overlaps(
                project_id, str(values.get("candidate_id") or "")
            )
        elif operation_id == "candidate_review.create_action":
            result = self.create_boba_candidate_action_request(
                project_id,
                candidate_review_session_id=str(
                    values.get("candidate_review_session_id") or ""
                ),
                candidate_snapshot_id=str(values.get("candidate_snapshot_id") or ""),
                action_descriptor_id=str(values.get("action_descriptor_id") or ""),
                decision_value=str(values.get("decision_value") or "") or None,
                reason=str(values.get("reason") or ""),
                confirmation_context_digest=str(
                    values.get("confirmation_context_digest") or ""
                ),
                idempotency_key=str(values.get("idempotency_key") or ""),
                confirmed=bool(values.get("confirmed")),
            )
            side_effects.append("candidate_review_action_request_recorded")
        elif operation_id == "candidate_review.validate_action":
            result = self.validate_boba_candidate_action_request(
                project_id,
                str(values.get("candidate_action_request_id") or ""),
            )
            target_revalidated = True
        elif operation_id == "candidate_review.submit_action":
            result = await self.submit_boba_candidate_action_to_owner(
                project_id,
                str(values.get("candidate_action_request_id") or ""),
            )
            target_revalidated = True
            side_effects.append("candidate_review_action_receipt_recorded")
        elif operation_id == "candidate_review.inspect_receipt":
            result = self.inspect_boba_candidate_action_receipt(
                project_id,
                str(values.get("candidate_action_request_id") or ""),
            )
        elif operation_id == "candidate_review.inspect_timeline":
            result = self.inspect_boba_candidate_review_timeline(
                project_id, limit=int(values.get("limit") or 100)
            )
        elif operation_id == "candidate_review.inspect_events":
            result = self.inspect_boba_candidate_review_events(
                project_id,
                after_sequence=int(values.get("after_sequence") or 0),
                limit=int(values.get("limit") or 100),
            )
        elif operation_id == "candidate_review.reset":
            result = self.reset_boba_candidate_review_metadata(
                project_id,
                str(values.get("candidate_review_session_id") or "") or None,
            )
            side_effects.append("candidate_review_active_metadata_reset")
        elif operation_id == "observer.generate":
            result = await self.generate_observer_report(
                project_id,
                workflow_context=_dict(values.get("workflow_context")),
                dry_run=bool(values.get("dry_run")),
            )
            if not bool(values.get("dry_run")):
                side_effects.append("observer_metadata_updated")
        elif operation_id == "error_doctor.generate":
            error_summaries = values.get("error_summaries")
            result = await self.generate_boba_error_doctor(
                project_id,
                diagnostic_context=_dict(values.get("diagnostic_context")),
                error_summaries=(
                    list(error_summaries)
                    if isinstance(error_summaries, list)
                    else None
                ),
                dry_run=bool(values.get("dry_run")),
            )
            if not bool(values.get("dry_run")):
                side_effects.append("error_doctor_metadata_updated")
        elif operation_id == "root_cause_analyzer.generate":
            result = await self.generate_boba_root_cause_analyzer(
                project_id,
                diagnostic_context=_dict(values.get("diagnostic_context")),
                dry_run=bool(values.get("dry_run")),
            )
            if not bool(values.get("dry_run")):
                side_effects.append("root_cause_metadata_updated")
        elif operation_id == "repair_planner.generate":
            result = await self.generate_boba_repair_planner(
                project_id,
                planning_context=_dict(values.get("planning_context")),
                dry_run=bool(values.get("dry_run")),
            )
            if not bool(values.get("dry_run")):
                side_effects.append("repair_plan_metadata_updated")
        elif operation_id == "code_surgeon.propose":
            template_identifier = str(
                values.get("deterministic_template_identifier") or ""
            )
            if not template_identifier:
                raise ValidationError(
                    "Integration Layer Code Surgeon proposals require a "
                    "registered deterministic template identifier."
                )
            result = await self.generate_boba_code_surgeon_proposal(
                project_id,
                repair_case_id=str(values.get("repair_case_id") or "") or None,
                repair_strategy_id=(
                    str(values.get("repair_strategy_id") or "") or None
                ),
                proposal_source="deterministic_template",
                deterministic_template_identifier=template_identifier,
                template_parameters=_dict(values.get("template_parameters")),
                base_branch=str(values.get("base_branch") or "main"),
                affected_paths=[
                    str(item)
                    for item in values.get("affected_paths", [])
                    if isinstance(item, str)
                ],
                approved_special_paths=[
                    str(item)
                    for item in values.get("approved_special_paths", [])
                    if isinstance(item, str)
                ],
            )
            side_effects.append("code_surgeon_proposal_metadata_updated")
        elif operation_id == "tool_recovery_brain.plan":
            result = await self.generate_boba_tool_recovery_plan(
                project_id,
                selected_handoff_id=(
                    str(values.get("selected_handoff_id") or "") or None
                ),
                selected_repair_strategy_id=(
                    str(values.get("selected_repair_strategy_id") or "") or None
                ),
                failure_context=_dict(values.get("failure_context")),
                run_health_checks=(
                    bool(values["run_health_checks"])
                    if "run_health_checks" in values
                    else None
                ),
            )
            side_effects.append("tool_recovery_plan_metadata_updated")
        elif operation_id == "tool_recovery_brain.health_check":
            tool_ids = values.get("tool_ids")
            result = await self.run_boba_tool_health_checks(
                project_id,
                tool_ids=(
                    [str(item) for item in tool_ids]
                    if isinstance(tool_ids, list)
                    else None
                ),
            )
            side_effects.append("tool_health_metadata_updated")
        elif operation_id == "tool_recovery_brain.validate_output":
            result = await self.validate_boba_recovered_output(
                project_id,
                recovery_attempt_id=str(
                    values.get("recovery_attempt_id") or ""
                ),
            )
            side_effects.append("recovery_validation_metadata_updated")
        elif operation_id == "output_quality_reviewer.review":
            result = await self.generate_boba_output_quality_review(
                project_id,
                output_reference=str(values.get("output_reference") or ""),
                baseline_reference=(
                    str(values.get("baseline_reference") or "") or None
                ),
                rights_status=str(values.get("rights_status") or "unknown"),
                safety_status=str(values.get("safety_status") or "unknown"),
                workflow_stage=str(
                    values.get("workflow_stage") or "quality_review"
                ),
            )
            side_effects.append("output_quality_metadata_updated")
        elif operation_id == "output_quality_reviewer.compare":
            result = await self.compare_boba_output_quality_baseline(
                project_id,
                output_reference=str(values.get("output_reference") or ""),
                baseline_reference=str(
                    values.get("baseline_reference") or ""
                ),
                rights_status=str(values.get("rights_status") or "unknown"),
                safety_status=str(values.get("safety_status") or "unknown"),
            )
            side_effects.append("quality_comparison_metadata_updated")
        elif operation_id == "autopilot_controller.create_run":
            result = await self.create_boba_autopilot_run(project_id)
            side_effects.append("autopilot_metadata_updated")
        elif operation_id == "autopilot_controller.plan_next":
            result = await self.plan_boba_autopilot_next_action(
                project_id,
                request.run_id,
            )
            side_effects.append("autopilot_plan_metadata_updated")
        elif operation_id == "autopilot_controller.advance_safe":
            result = await self.advance_boba_autopilot_safe_read_only(
                project_id,
                request.run_id,
                maximum_steps=max(
                    1,
                    min(int(values.get("maximum_steps") or 12), 12),
                ),
            )
            side_effects.append("autopilot_read_only_metadata_updated")
        elif operation_id == "autopilot_controller.coordinate_approved":
            approval_record = _dict(values.get("approval_record"))
            result = await self.coordinate_approved_boba_autopilot_action(
                project_id,
                request.run_id,
                action_id=str(values.get("autopilot_action_id") or ""),
                approval_record=approval_record,
                safety_decision_id=str(
                    values.get("safety_decision_id") or ""
                ),
            )
            action_id = str(values.get("autopilot_action_id") or "")
            target_revalidated = any(
                item.action_id == action_id
                and item.independently_revalidated_by_target
                for item in result.module_invocations
            )
            side_effects.append("autopilot_coordination_metadata_updated")
        elif operation_id == "autopilot_controller.pause":
            result = self.pause_boba_autopilot_run(
                project_id,
                request.run_id,
                reason=str(
                    values.get("reason")
                    or "Integration Layer requested an explicit pause."
                ),
            )
            side_effects.append("autopilot_metadata_updated")
        elif operation_id == "autopilot_controller.continue_controller":
            result = self.continue_boba_autopilot_run(project_id, request.run_id)
            side_effects.append("autopilot_metadata_updated")
        elif operation_id == "autopilot_controller.cancel":
            result = self.cancel_boba_autopilot_run(
                project_id,
                request.run_id,
                reason=str(
                    values.get("reason")
                    or "Integration Layer received an explicit cancellation."
                ),
            )
            side_effects.append("autopilot_metadata_updated")
        elif operation_id == "safety_gate.create_policy":
            result = await self.create_boba_safety_policy_snapshot(
                project_id,
                project_policy=_dict(values.get("project_policy")),
            )
            side_effects.append("safety_policy_metadata_updated")
        elif operation_id == "safety_gate.create_request":
            allowed_keys = {
                "autopilot_run_id",
                "autopilot_action_id",
                "requesting_module",
                "target_module",
                "target_operation",
                "action_class",
                "action_description",
                "action_parameters",
                "project_snapshot_id",
                "project_snapshot_digest",
                "plan_id",
                "strategy_id",
                "approval_record_id",
                "patch_proposal_id",
                "patch_diff_sha256",
                "code_base_sha",
                "tool_id",
                "capability_id",
                "configuration_digest",
                "checkpoint_reference",
                "checkpoint_digest",
                "rollback_plan_id",
                "validation_plan_id",
                "quality_plan_id",
                "retry_budget_digest",
                "time_budget_seconds",
                "requested_by",
            }
            result = await self.create_boba_safety_action_request(
                project_id,
                **{
                    key: value
                    for key, value in values.items()
                    if key in allowed_keys
                },
            )
            side_effects.append("safety_request_metadata_updated")
        elif operation_id == "safety_gate.evaluate":
            result = await self.evaluate_boba_safety_action(
                project_id,
                str(values.get("action_request_id") or ""),
                approval_record=_dict(values.get("approval_record")) or None,
            )
            side_effects.append("safety_decision_metadata_updated")
        elif operation_id == "safety_gate.revalidate":
            result = self.revalidate_boba_safety_decision(
                project_id,
                str(values.get("safety_decision_id") or ""),
                approval_record=_dict(values.get("approval_record")) or None,
                current_bindings=_dict(values.get("current_bindings")) or None,
            )
            side_effects.append("safety_revalidation_metadata_updated")
        elif operation_id == "whole_video_understanding.generate":
            result = await self.generate_whole_video_understanding(project_id)
            side_effects.append("whole_video_understanding_metadata_updated")
        elif operation_id == "candidate_clip_discovery.discover":
            result = await self.discover_candidate_clips(project_id)
            side_effects.append("candidate_clip_discovery_metadata_updated")
        elif operation_id == "clip_ranking.rank":
            result = await self.rank_discovered_candidate_clips(project_id)
            side_effects.append("clip_ranking_metadata_updated")
        elif operation_id == "editorial_decision.generate":
            result = await self.generate_editorial_decisions(project_id)
            side_effects.append("editorial_decision_metadata_updated")
        elif operation_id == "creative_director.generate":
            result = await self.generate_creative_direction_v2(project_id)
            side_effects.append("creative_direction_metadata_updated")
        elif operation_id == "clip_brief.generate":
            result = await self.generate_clip_briefs(project_id)
            side_effects.append("clip_brief_metadata_updated")
        elif operation_id == "hook_retention.generate":
            result = await self.generate_hook_retention(project_id)
            side_effects.append("hook_retention_metadata_updated")
        elif operation_id == "caption_motion.generate":
            result = await self.generate_caption_motion(project_id)
            side_effects.append("caption_motion_metadata_updated")
        elif operation_id == "music_mood.generate":
            result = await self.generate_music_mood(project_id)
            side_effects.append("music_mood_metadata_updated")
        elif operation_id == "rights_permission_gate.generate":
            manual_items = values.get("manual_items")
            result = await self.generate_rights_permission_gate(
                project_id,
                manual_items=(
                    [dict(item) for item in manual_items if isinstance(item, dict)]
                    if isinstance(manual_items, list)
                    else None
                ),
                source_label=str(values.get("source_label") or "workflow"),
                dry_run=bool(values.get("dry_run")),
            )
            if not bool(values.get("dry_run")):
                side_effects.append("rights_permission_metadata_updated")
        elif operation_id == "workflow_controller.build_definition":
            result = self.build_boba_workflow_definition(
                project_id,
                source_id=str(values.get("source_id") or "") or None,
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.create_run":
            result = self.create_boba_workflow_run(
                project_id,
                source_id=str(values.get("source_id") or ""),
                project_snapshot=_dict(values.get("project_snapshot")),
                source_storage_reference=str(
                    values.get("source_storage_reference") or ""
                ),
                source_artifact_digest=str(
                    values.get("source_artifact_digest") or ""
                ),
                clip_ids=[
                    str(item)
                    for item in values.get("clip_ids", [])
                    if isinstance(item, str)
                ],
                output_ids_by_clip={
                    str(key): str(value)
                    for key, value in _dict(
                        values.get("output_ids_by_clip")
                    ).items()
                },
                rights_status=str(values.get("rights_status") or "unknown"),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.inspect":
            result = self.inspect_boba_workflow_run(
                project_id,
                request.run_id,
            )
        elif operation_id == "workflow_controller.plan_next":
            result = self.plan_boba_workflow_next_stage(
                project_id,
                request.run_id,
            )
        elif operation_id == "workflow_controller.create_transition_request":
            transition_type = cast(
                BobaWorkflowTransitionTypeV1,
                str(values.get("transition_type") or "unknown"),
            )
            result = self.create_boba_workflow_transition_request(
                project_id,
                request.run_id,
                source_stage_instance_id=str(
                    values.get("source_stage_instance_id") or ""
                ),
                target_stage_id=str(values.get("target_stage_id") or ""),
                expected_revision=int(values.get("expected_revision") or 0),
                transition_type=transition_type,
                reason=str(values.get("reason") or ""),
                clip_id=str(values.get("clip_id") or "") or None,
                output_id=str(values.get("output_id") or "") or None,
                approval_record_id=(
                    str(values.get("approval_record_id") or "") or None
                ),
                safety_decision_id=(
                    str(values.get("safety_decision_id") or "") or None
                ),
                integration_request_id=(
                    str(values.get("integration_request_id") or "") or None
                ),
                checkpoint_reference=(
                    str(values.get("checkpoint_reference") or "") or None
                ),
                checkpoint_digest=(
                    str(values.get("checkpoint_digest") or "") or None
                ),
                quality_decision_id=(
                    str(values.get("quality_decision_id") or "") or None
                ),
                human_decision_id=(
                    str(values.get("human_decision_id") or "") or None
                ),
                expires_in_seconds=int(
                    values.get("expires_in_seconds") or 300
                ),
                idempotency_key=(
                    str(values.get("idempotency_key") or "") or None
                ),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.evaluate_transition":
            result = self.evaluate_boba_workflow_transition(
                project_id,
                request.run_id,
                str(values.get("transition_request_id") or ""),
                expected_revision=int(values.get("expected_revision") or 0),
                current_project_snapshot_digest=str(
                    values.get("current_project_snapshot_digest") or ""
                ),
                rights_clear=(
                    bool(values.get("rights_clear"))
                    if "rights_clear" in values
                    else None
                ),
                approval_record=_dict(values.get("approval_record")) or None,
                safety_decision=_dict(values.get("safety_decision")) or None,
                checkpoint_valid=(
                    bool(values.get("checkpoint_valid"))
                    if "checkpoint_valid" in values
                    else None
                ),
                technical_validation=(
                    _dict(values.get("technical_validation")) or None
                ),
                quality_decision=_dict(values.get("quality_decision")) or None,
                human_decision=_dict(values.get("human_decision")) or None,
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.advance_safe_read_only":
            result = await self.advance_boba_workflow_safe_read_only_stage(
                project_id,
                request.run_id,
                str(values.get("transition_decision_id") or ""),
                expected_revision=int(values.get("expected_revision") or 0),
                integration_parameters=(
                    _dict(values.get("integration_parameters")) or None
                ),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif (
            operation_id
            == "workflow_controller.coordinate_approved_internal_transition"
        ):
            raw_approval_binding = _dict(
                values.get("downstream_approval_binding")
            )
            raw_safety_binding = _dict(values.get("downstream_safety_binding"))
            result = await self.coordinate_approved_boba_workflow_transition(
                project_id,
                request.run_id,
                str(values.get("transition_decision_id") or ""),
                expected_revision=int(values.get("expected_revision") or 0),
                integration_parameters=(
                    _dict(values.get("integration_parameters")) or None
                ),
                approval_binding=(
                    BobaIntegrationApprovalBindingV1.model_validate(
                        raw_approval_binding
                    )
                    if raw_approval_binding
                    else None
                ),
                safety_binding=(
                    BobaIntegrationSafetyBindingV1.model_validate(
                        raw_safety_binding
                    )
                    if raw_safety_binding
                    else None
                ),
            )
            target_revalidated = result.status in {
                "succeeded",
                "duplicate_reused",
            }
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.pause":
            pause_category = cast(
                BobaWorkflowPauseCategoryV1,
                str(values.get("category") or "manual"),
            )
            result = self.pause_boba_workflow(
                project_id,
                request.run_id,
                expected_revision=int(values.get("expected_revision") or 0),
                reason=str(values.get("reason") or "Explicit workflow pause."),
                category=pause_category,
                stage_instance_id=(
                    str(values.get("stage_instance_id") or "") or None
                ),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.create_recovery_hold":
            result = self.create_boba_workflow_recovery_hold(
                project_id,
                request.run_id,
                failed_stage_instance_id=str(
                    values.get("failed_stage_instance_id") or ""
                ),
                expected_revision=int(values.get("expected_revision") or 0),
                reason=str(values.get("reason") or ""),
                observer_record_id=(
                    str(values.get("observer_record_id") or "") or None
                ),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.receive_recovery_result":
            result = self.receive_boba_autopilot_recovery_result(
                project_id,
                request.run_id,
                str(values.get("recovery_hold_id") or ""),
                _dict(values.get("recovery_result")),
                expected_revision=int(values.get("expected_revision") or 0),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.evaluate_resume_eligibility":
            result = self.evaluate_boba_workflow_resume_eligibility(
                project_id,
                request.run_id,
                str(values.get("recovery_hold_id") or ""),
                expected_revision=int(values.get("expected_revision") or 0),
                current_project_snapshot_digest=str(
                    values.get("current_project_snapshot_digest") or ""
                ),
                rights_clear=bool(values.get("rights_clear")),
                approval_record=_dict(values.get("approval_record")) or None,
                safety_decision=_dict(values.get("safety_decision")) or None,
                checkpoint_valid=bool(values.get("checkpoint_valid")),
                rollback_state_clear=bool(
                    values.get("rollback_state_clear")
                ),
                technical_validation=(
                    _dict(values.get("technical_validation")) or None
                ),
                quality_decision=_dict(values.get("quality_decision")) or None,
                human_decision=_dict(values.get("human_decision")) or None,
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.continue_controller":
            result = self.continue_boba_workflow_controller(
                project_id,
                request.run_id,
                expected_revision=int(values.get("expected_revision") or 0),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.cancel":
            result = self.cancel_boba_workflow_run(
                project_id,
                request.run_id,
                expected_revision=int(values.get("expected_revision") or 0),
                reason=str(
                    values.get("reason") or "Explicit workflow cancellation."
                ),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.record_human_decision":
            result = self.record_boba_workflow_human_decision(
                project_id,
                request.run_id,
                expected_revision=int(values.get("expected_revision") or 0),
                decision_type=str(values.get("decision_type") or "review"),
                decision=str(values.get("decision") or ""),
                reason=str(values.get("reason") or ""),
                reviewer_reference=str(
                    values.get("reviewer_reference") or "local_reviewer"
                ),
                explicit_confirmation=bool(
                    values.get("explicit_confirmation")
                ),
                stage_instance_id=(
                    str(values.get("stage_instance_id") or "") or None
                ),
                transition_request_id=(
                    str(values.get("transition_request_id") or "") or None
                ),
            )
            side_effects.append("workflow_controller_metadata_updated")
        elif operation_id == "workflow_controller.complete_internal_output":
            result = {
                "schema_version": "boba_workflow_completion_target_v1",
                "project_id": project_id,
                "workflow_run_id": request.run_id,
                "stage_instance_id": str(
                    values.get("workflow_stage_instance_id") or ""
                ),
                "ready_for_controller_completion": True,
                "artifact_bindings": [
                    {
                        "project_id": project_id,
                        "workflow_run_id": request.run_id,
                        "artifact_type": "internal_output_completion",
                        "producer_record_id": request.request_id,
                        "schema_id": "boba.workflow.internal_output_completion",
                        "schema_version": "1",
                        "artifact_digest": hashlib.sha256(
                            request.request_digest.encode("utf-8")
                        ).hexdigest(),
                        "sanitized_storage_reference": (
                            f"projects/{project_id}/workflow_controller/index.json"
                        ),
                    }
                ],
            }
            target_revalidated = True
            side_effects.append("workflow_completion_evidence_returned")
        elif operation_id == "workflow_controller.reset":
            result = self.reset_boba_workflow_controller(project_id)
            side_effects.append("workflow_controller_active_metadata_reset")
        else:
            raise ValidationError(
                "Integration Layer facade has no fixed typed adapter for this "
                "registered operation."
            )
        return self._bounded_integration_target_result(
            result,
            target_revalidated=target_revalidated,
            side_effects=side_effects,
        )

    async def build_boba_integration_registry(
        self,
        project_id: str,
    ) -> BobaIntegrationLayerSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        engine = self._integration_layer(
            project_id,
            source_id=project.link_ingestion_id or project_id,
        )
        engine.build_registry_snapshot()
        return engine._load_layer()

    async def inspect_boba_integration_registry(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        layer = await self.build_boba_integration_registry(project_id)
        return {
            "registry_snapshot": layer.registry_snapshot.model_dump(mode="json"),
            "modules": [
                item.model_dump(mode="json")
                for item in layer.module_descriptors
            ],
            "operations": [
                item.model_dump(mode="json")
                for item in layer.operation_descriptors
            ],
        }

    async def create_boba_integration_request(
        self,
        project_id: str,
        *,
        requesting_module_id: str,
        target_module_id: str,
        target_operation_id: str,
        request_parameters: dict[str, Any] | None = None,
        run_id: str = "",
        request_schema_id: str = "boba.integration.request",
        request_schema_version: str = "1.0",
        artifact_references: list[
            BobaIntegrationArtifactReferenceV1
        ] | None = None,
        approval_binding: BobaIntegrationApprovalBindingV1 | None = None,
        safety_binding: BobaIntegrationSafetyBindingV1 | None = None,
        project_snapshot_digest: str = "",
        expires_in_seconds: int = 300,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        engine = self._integration_layer(
            project_id,
            source_id=project.link_ingestion_id or project_id,
        )
        envelope, request, transaction = await engine.create_validated_request(
            requesting_module_id=requesting_module_id,
            target_module_id=target_module_id,
            target_operation_id=target_operation_id,
            request_parameters=request_parameters,
            run_id=run_id,
            request_schema_id=request_schema_id,
            request_schema_version=request_schema_version,
            artifact_references=artifact_references or [],
            approval_binding=approval_binding,
            safety_binding=safety_binding,
            project_snapshot_digest=project_snapshot_digest,
            expires_in_seconds=expires_in_seconds,
            idempotency_key=idempotency_key,
        )
        return {
            "envelope": envelope.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
            "transaction": transaction.model_dump(mode="json"),
            "routed": False,
        }

    async def validate_boba_integration_request(
        self,
        project_id: str,
        envelope: BobaIntegrationEnvelopeV1,
    ) -> BobaIntegrationTransactionV1:
        return await self._integration_layer(
            project_id
        ).validate_request_envelope(envelope)

    async def route_boba_integration_request(
        self,
        project_id: str,
        transaction_id: str,
    ) -> BobaIntegrationResponseV1:
        return await self._integration_layer(project_id).route_typed_request(
            transaction_id
        )

    def inspect_boba_integration_transaction(
        self,
        project_id: str,
        transaction_id: str,
    ) -> BobaIntegrationTransactionV1:
        return self._integration_layer(project_id).inspect_transaction(
            transaction_id
        )

    def inspect_boba_integration_events(
        self,
        project_id: str,
        transaction_id: str,
    ) -> list[Any]:
        return self._integration_layer(project_id).inspect_transaction_events(
            transaction_id
        )

    def load_boba_integration_layer(
        self,
        project_id: str,
    ) -> BobaIntegrationLayerSetV1 | None:
        return self.store.load_boba_integration_layer(project_id)

    def export_boba_integration_layer(self, project_id: str) -> dict[str, Any]:
        return self.store.export_boba_integration_layer(project_id)

    def reset_boba_integration_layer(self, project_id: str) -> dict[str, Any]:
        return self.store.reset_boba_integration_layer(project_id)

    def _creator_learning_artifacts(self, project_id: str) -> dict[str, Any]:
        return {
            "clip_ranking": self.store.load_clip_ranking(project_id),
            "editorial_decision": self.store.load_editorial_decisions(project_id),
            "explanation": self.store.load_explanations(project_id),
            "creative_direction": self.store.load_creative_direction_v2(project_id),
            "clip_briefs": self.store.load_clip_briefs(project_id),
            "hook_retention": self.store.load_hook_retention(project_id),
            "caption_motion": self.store.load_caption_motion(project_id),
            "music_mood": self.store.load_music_mood(project_id),
        }

    async def record_creator_feedback_event(
        self,
        project_id: str,
        *,
        event_type: BobaCreatorFeedbackEventType,
        target_type: BobaCreatorFeedbackTargetType,
        target_id: str,
        user_action: BobaCreatorUserAction,
        rating: float | None = None,
        note: str = "",
        tags: list[str] | None = None,
        reversible: bool = True,
    ) -> BobaCreatorFeedbackEventV1:
        if await self.projects.get(project_id) is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        event = self.creator_learning_loop.create_feedback_event(
            project_id=project_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            user_action=user_action,
            rating=rating,
            note=note,
            tags=tags,
            reversible=reversible,
            artifacts=self._creator_learning_artifacts(project_id),
        )
        return self.store.record_creator_feedback_event(event)

    async def generate_creator_learning_profile(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
        dry_run: bool = False,
    ) -> BobaCreatorLearningSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        artifacts = self._creator_learning_artifacts(project_id)
        creator_memory = self.store.load_creator_memory(creator_id)
        project_memory = self.store.load_project_memory(project_id)
        learning = self.creator_learning_loop.analyze(
            project_id,
            self.store.list_creator_feedback_events(project_id),
            creator_id=creator_id,
            source_id=project.id,
            boba_memory=creator_memory or project_memory,
            clip_ranking=artifacts["clip_ranking"],
            editorial_decision=artifacts["editorial_decision"],
            explanation=artifacts["explanation"],
            creative_direction=artifacts["creative_direction"],
            clip_briefs=artifacts["clip_briefs"],
            hook_retention=artifacts["hook_retention"],
            caption_motion=artifacts["caption_motion"],
            music_mood=artifacts["music_mood"],
        )
        if dry_run:
            return learning.model_copy(
                update={
                    "warnings": [
                        *learning.warnings,
                        "Dry run: creator learning was not persisted.",
                    ]
                }
            )
        return self.store.save_creator_learning(learning)

    def load_creator_learning_profile(
        self,
        project_id: str,
    ) -> BobaCreatorLearningSetV1 | None:
        return self.store.load_creator_learning_profile(project_id)

    def export_creator_learning_profile(self, project_id: str) -> dict[str, Any]:
        return self.store.export_creator_learning_profile(project_id)

    def reset_creator_learning_profile(self, project_id: str) -> bool:
        return self.store.reset_creator_learning_profile(project_id)

    async def apply_creator_learning_guidance_dry_run(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
    ) -> BobaRecommendationGuidanceV1:
        learning = await self.generate_creator_learning_profile(
            project_id,
            creator_id=creator_id,
            dry_run=True,
        )
        return learning.recommendation_guidance

    async def generate_approval_rejection_learning(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
        dry_run: bool = False,
    ) -> BobaApprovalRejectionLearningSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        artifacts = self._creator_learning_artifacts(project_id)
        creator_memory = self.store.load_creator_memory(creator_id)
        project_memory = self.store.load_project_memory(project_id)
        learning = self.approval_rejection_learning.analyze(
            project_id,
            self.store.list_creator_feedback_events(project_id),
            source_id=project.id,
            creator_learning=self.store.load_creator_learning(project_id),
            boba_memory=creator_memory or project_memory,
            clip_ranking=artifacts["clip_ranking"],
            editorial_decision=artifacts["editorial_decision"],
            explanation=artifacts["explanation"],
            creative_direction=artifacts["creative_direction"],
            clip_briefs=artifacts["clip_briefs"],
            hook_retention=artifacts["hook_retention"],
            caption_motion=artifacts["caption_motion"],
            music_mood=artifacts["music_mood"],
            dry_run=dry_run,
        )
        if dry_run:
            return learning
        return self.store.save_approval_rejection_learning(learning)

    def load_approval_rejection_learning(
        self,
        project_id: str,
    ) -> BobaApprovalRejectionLearningSetV1 | None:
        return self.store.load_approval_rejection_learning(project_id)

    def export_approval_rejection_learning(self, project_id: str) -> dict[str, Any]:
        return self.store.export_approval_rejection_learning(project_id)

    def reset_approval_rejection_learning(self, project_id: str) -> bool:
        return self.store.reset_approval_rejection_learning(project_id)

    async def apply_approval_rejection_guidance_dry_run(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
    ) -> BobaApprovalRejectionModuleGuidanceV1:
        learning = await self.generate_approval_rejection_learning(
            project_id,
            creator_id=creator_id,
            dry_run=True,
        )
        return learning.module_guidance

    async def _json(self, key: str) -> dict[str, Any]:
        if not await self.storage.exists(key):
            return {}
        try:
            raw = json.loads(await self.storage.get(key))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return {"_warning": f"Artifact is unreadable: {key}"}
        return raw if isinstance(raw, dict) else {}

    async def _stage(self, engine: str, project_id: str, stage: str) -> dict[str, Any]:
        return await self._json(f"{engine}/{project_id}/stages/{stage}.json")

    @staticmethod
    def _model_payload(value: object | None) -> dict[str, Any]:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            payload = model_dump(mode="json")
            return payload if isinstance(payload, dict) else {}
        return value if isinstance(value, dict) else {}

    async def _output_quality_inputs(
        self,
        project_id: str,
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
    ]:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})

        artifacts_by_reference: dict[str, dict[str, Any]] = {}
        manifest_resolution = await resolve_render_manifest(self.storage, project_id)
        manifest = manifest_resolution.manifest or {}
        render_id = str(manifest.get("render_id") or "")
        for raw_render in _list(manifest.get("renders")):
            render = _dict(raw_render)
            reference = str(render.get("storage_key") or "").replace("\\", "/")
            if not reference:
                continue
            metadata = _dict(render.get("metadata"))
            clip_id = str(
                render.get("clip_id")
                or metadata.get("candidate_id")
                or metadata.get("clip_id")
                or ""
            )
            checksum = str(render.get("checksum") or "")
            artifacts_by_reference[reference] = {
                "artifact_id": (
                    f"render_output_{clip_id}"
                    if clip_id
                    else f"render_output_{checksum[-24:] or len(artifacts_by_reference)}"
                ),
                "project_id": project_id,
                "reference": reference,
                "path_scope": "storage",
                "source_type": "normal_render",
                "origin_module": "rendering",
                "origin_run_id": render_id,
                "clip_id": clip_id,
                "manifest_entry": render,
                "render_entry": render,
                "accepted_output_protected": True,
                "warnings": manifest_resolution.warnings,
            }

        tool_recovery = self.store.load_boba_tool_recovery(project_id)
        tool_payload = self._model_payload(tool_recovery)
        strategies = {
            str(item.get("recovery_strategy_id") or ""): item
            for plan in _list(tool_payload.get("recovery_plans"))
            for item in _list(_dict(plan).get("ordered_strategies"))
            if isinstance(item, dict)
        }
        validations = {
            str(item.get("output_artifact_ref") or "").replace("\\", "/"): item
            for item in _list(tool_payload.get("output_validations"))
            if isinstance(item, dict)
        }
        for raw_attempt in _list(tool_payload.get("recovery_attempts")):
            attempt = _dict(raw_attempt)
            strategy = _dict(
                strategies.get(str(attempt.get("recovery_strategy_id") or ""))
            )
            source_type = (
                "fallback_output"
                if "fallback" in str(strategy.get("strategy_type") or "").casefold()
                else "tool_recovery_output"
            )
            for raw_reference in _list(attempt.get("output_artifact_refs")):
                reference = str(raw_reference or "").strip().replace("\\", "/")
                if not reference or "://" in reference:
                    continue
                path_scope = (
                    "repository"
                    if reference.startswith("work/boba/tool_recovery/workspaces/")
                    else "storage"
                )
                validation = _dict(validations.get(reference))
                artifacts_by_reference[reference] = {
                    "artifact_id": (
                        f"recovered_output_"
                        f"{str(attempt.get('recovery_attempt_id') or '')[-80:]}"
                    ),
                    "project_id": project_id,
                    "reference": reference,
                    "path_scope": path_scope,
                    "source_type": source_type,
                    "origin_module": "tool_recovery_brain",
                    "origin_run_id": str(attempt.get("recovery_plan_id") or ""),
                    "origin_attempt_id": str(
                        attempt.get("recovery_attempt_id") or ""
                    ),
                    "source_record_id": str(
                        validation.get("output_validation_id")
                        or attempt.get("recovery_attempt_id")
                        or ""
                    ),
                    "expected_checksum": validation.get("checksum"),
                    "tool_recovery_validation": validation,
                    "quality_requirements": _list(
                        strategy.get("quality_requirements")
                    ),
                    "accepted_output_protected": True,
                    "warnings": [
                        *_list(attempt.get("warnings")),
                        *_list(validation.get("warnings")),
                    ],
                }

        code_surgeon = self.store.load_boba_code_surgeon(project_id)
        code_payload = self._model_payload(code_surgeon)
        runs = {
            str(item.get("isolated_run_id") or ""): item
            for item in _list(code_payload.get("isolated_runs"))
            if isinstance(item, dict)
        }
        for raw_validation in _list(code_payload.get("validation_runs")):
            validation = _dict(raw_validation)
            isolated_run_id = str(validation.get("isolated_run_id") or "")
            if not isolated_run_id:
                continue
            run_path = self.store.code_surgeon_run_path(
                project_id,
                isolated_run_id,
            )
            try:
                reference = run_path.resolve().relative_to(
                    self.output_quality_reviewer.repository_root
                ).as_posix()
            except ValueError:
                continue
            artifacts_by_reference[reference] = {
                "artifact_id": str(
                    validation.get("validation_run_id")
                    or f"code_validation_{isolated_run_id}"
                ),
                "project_id": project_id,
                "reference": reference,
                "path_scope": "repository",
                "artifact_type": "JSON",
                "source_type": "code_surgeon_behavior_validation",
                "origin_module": "code_surgeon",
                "origin_run_id": isolated_run_id,
                "source_record_id": str(
                    validation.get("validation_run_id") or ""
                ),
                "code_surgeon_validation": validation,
                "isolated_run": _dict(runs.get(isolated_run_id)),
                "accepted_output_protected": True,
                "warnings": _list(validation.get("warnings")),
            }

        creative_artifacts = {
            "whole_video_understanding": self._model_payload(
                self.store.load_whole_video_understanding(project_id)
            ),
            "clip_ranking": self._model_payload(
                self.store.load_clip_ranking(project_id)
            ),
            "editorial_decision": self._model_payload(
                self.store.load_editorial_decisions(project_id)
            ),
            "creative_direction": self._model_payload(
                self.store.load_creative_direction_v2(project_id)
            ),
            "clip_brief": self._model_payload(
                self.store.load_clip_briefs(project_id)
            ),
            "hook_retention": self._model_payload(
                self.store.load_hook_retention(project_id)
            ),
            "caption_motion": self._model_payload(
                self.store.load_caption_motion(project_id)
            ),
            "music_mood": self._model_payload(
                self.store.load_music_mood(project_id)
            ),
        }
        validation_artifacts: dict[str, Any] = {}
        return (
            project.to_dict(),
            list(artifacts_by_reference.values()),
            creative_artifacts,
            validation_artifacts,
        )

    async def collect_project_signals(self, project_id: str) -> dict[str, Any]:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})

        speech = await self._stage("analysis", project_id, "speech_transcription")
        video = await self._stage("analysis", project_id, "video_inspection")
        face = await self._stage("analysis", project_id, "face_detection")
        speakers = await self._stage("analysis", project_id, "speaker_segmentation")
        scenes = await self._stage("analysis", project_id, "scene_detection")
        signal_health = await self._stage("analysis", project_id, "signal_health")
        story = await self._stage("story", project_id, "story_analysis_v2")
        story_summary = await self._stage("story", project_id, "story_summary")
        emotions = await self._stage("story", project_id, "emotional_turning_points")
        virality = await self._stage("virality", project_id, "virality_summary")
        trend = await self._stage("virality", project_id, "trend_research")
        scoring = await self._stage("planning", project_id, "clip_scoring")
        ranking = await self._stage("planning", project_id, "ranking")
        planning_summary = await self._stage("planning", project_id, "planning_summary")
        editing = await self._stage("editing", project_id, "timeline_validation")
        render_run = await self._json(f"render/{project_id}/run/index.json")
        render_manifest_stage = await self._json(
            f"render/{project_id}/run/stages/generate_render_manifest.json"
        )
        canonical_manifest = _dict(_data(render_manifest_stage).get("manifest"))
        legacy_manifest = await self._json(f"render/{project_id}/index.json")
        render_manifest = canonical_manifest or legacy_manifest
        optimization = await self._stage("optimization", project_id, "copyright_safety_v2")
        personalization_directives = personalization.load_runtime_directives() or {}

        speech_data = _data(speech)
        segments = _list(speech_data.get("segments"))
        transcript_segments = [
            {
                "start": float(_dict(item).get("start") or 0.0),
                "end": float(_dict(item).get("end") or 0.0),
                "text": " ".join(str(_dict(item).get("text") or "").split())[:240],
            }
            for item in segments[:2000]
            if isinstance(item, dict)
        ]
        analysis_signals = _dict(
            _data(signal_health).get("analysis_signals_v2")
        )
        transcript_available = bool(
            segments
            or speech_data.get("transcript")
            or speech_data.get("text")
            or (speech.get("status") == "completed" and speech_data)
        )
        face_available = face.get("status") == "completed" and bool(_data(face))
        speaker_available = speakers.get("status") == "completed" and bool(_data(speakers))
        speaker_data = _data(speakers)
        speaker_roles = [
            str(
                item.get("role")
                or item.get("name")
                or item.get("label")
                or item.get("speaker_id")
                or item.get("id")
                or ""
            )
            for item in _list(speaker_data.get("speakers"))
            if isinstance(item, dict)
        ]
        visual_available = bool(
            video.get("status") == "completed"
            and (scenes.get("status") == "completed" or face_available)
        )
        trend_data = _data(trend)
        trend_snapshot = _dict(trend_data.get("internet_trend_research_v2"))
        trend_status = str(
            trend_snapshot.get("status")
            or trend_data.get("status")
            or trend.get("status")
            or "unavailable"
        )
        fallback_used = bool(
            trend_snapshot.get("fallback_used")
            or trend_snapshot.get("provider") in {"evergreen", "fallback"}
        )
        safety = _data(optimization)
        if not safety:
            for render in _list(render_manifest.get("renders")):
                metadata = _dict(_dict(render).get("metadata"))
                if metadata.get("copyright_safety_v2"):
                    safety = _dict(metadata.get("copyright_safety_v2"))
                    break
        safety_result = _dict(safety.get("result") or safety.get("overall"))
        manual_review = bool(
            safety_result.get("manual_review_required")
            or _dict(safety.get("manual_review")).get("required")
        )
        safety_status = str(
            safety_result.get("risk_level")
            or safety_result.get("upload_readiness")
            or "unknown"
        )
        story_data = _data(story)
        micro_stories = [_dict(item) for item in _list(story_data.get("micro_stories"))]
        topic_sections = [_dict(item) for item in _list(story_data.get("topic_sections"))]
        plans = [_dict(item) for item in _list(_data(ranking).get("plans"))]
        candidates = [_dict(item) for item in _list(_data(scoring).get("candidates"))]
        timelines = _list(_data(editing).get("timelines"))
        render_stage = next(
            (
                item
                for item in _list(render_run.get("stages"))
                if isinstance(item, dict) and item.get("stage") == "generate_render_manifest"
            ),
            {},
        )
        manifest_available = bool(
            (
                render_manifest.get("status") == "completed"
                and _list(render_manifest.get("renders"))
            )
            or _dict(render_stage).get("status") == "completed"
        )
        warnings = [
            str(value.get("_warning"))
            for value in (
                speech,
                face,
                speakers,
                signal_health,
                story,
                virality,
                ranking,
                render_run,
            )
            if value.get("_warning")
        ]
        render_warnings = [
            str(item)
            for render in _list(render_manifest.get("renders"))
            for item in _list(_dict(_dict(render).get("metadata")).get("warnings"))
        ]
        known_limitations = [
            warning
            for warning in render_warnings
            if any(
                needle in warning.lower()
                for needle in ("sync", "delay", "cut", "face", "music", "speech")
            )
        ]
        if not manifest_available:
            reason = _dict(render_stage).get("reason")
            if reason:
                known_limitations.append(str(reason))
        saved_understanding = None
        try:
            saved_understanding = self.store.load_whole_video_understanding(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA whole-video artifact is unreadable: {exc}")
        saved_discovery = None
        try:
            saved_discovery = self.store.load_candidate_clip_discovery(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA candidate-discovery artifact is unreadable: {exc}")
        saved_clip_ranking = None
        try:
            saved_clip_ranking = self.store.load_clip_ranking(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA clip-ranking artifact is unreadable: {exc}")
        saved_editorial_decisions = None
        try:
            saved_editorial_decisions = self.store.load_editorial_decisions(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA editorial-decision artifact is unreadable: {exc}")
        saved_explanations = None
        try:
            saved_explanations = self.store.load_explanations(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA explanation artifact is unreadable: {exc}")
        saved_creative_direction_v2 = None
        try:
            saved_creative_direction_v2 = self.store.load_creative_direction_v2(
                project_id
            )
        except ValidationError as exc:
            warnings.append(f"BOBA Creative Director V2 artifact is unreadable: {exc}")
        saved_clip_briefs = None
        try:
            saved_clip_briefs = self.store.load_clip_briefs(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA clip-brief artifact is unreadable: {exc}")
        saved_hook_retention = None
        try:
            saved_hook_retention = self.store.load_hook_retention(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA hook-retention artifact is unreadable: {exc}")
        saved_caption_motion = None
        try:
            saved_caption_motion = self.store.load_caption_motion(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA caption-motion artifact is unreadable: {exc}")
        saved_music_mood = None
        try:
            saved_music_mood = self.store.load_music_mood(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA music-mood artifact is unreadable: {exc}")
        face_motion_results: list[dict[str, Any]] = []
        multi_speaker_results: list[dict[str, Any]] = []
        for render in _list(render_manifest.get("renders")):
            render_data = _dict(render)
            metadata = _dict(render_data.get("metadata"))
            clip_id = str(
                render_data.get("clip_id")
                or metadata.get("candidate_id")
                or metadata.get("clip_id")
                or ""
            )
            if not clip_id:
                continue
            face_tracking = _dict(
                metadata.get("face_tracking")
                or metadata.get("face_tracking_plan")
            )
            motion_validation = _dict(metadata.get("motion_render_validation"))
            if face_tracking or motion_validation:
                face_motion_results.append(
                    {
                        "candidate_id": clip_id,
                        "face_tracking_available": bool(
                            face_tracking.get("applied")
                            or face_tracking.get("applied_to_render")
                            or face_tracking.get("keyframes_count")
                        ),
                        "face_cutoff_detected": bool(
                            face_tracking.get("face_cutoff_detected")
                            or motion_validation.get("face_cutoff_detected")
                        ),
                        "face_inside_safe_zone_ratio": face_tracking.get(
                            "face_inside_safe_zone_ratio"
                        ),
                        "motion_render_passed": motion_validation.get("passed"),
                        "warnings": [
                            *(
                                item
                                for item in _list(face_tracking.get("warnings"))
                                if isinstance(item, str)
                            ),
                            *(
                                item
                                for item in _list(motion_validation.get("warnings"))
                                if isinstance(item, str)
                            ),
                        ][:16],
                    }
                )
            layout = _dict(metadata.get("multi_speaker_layout_v2"))
            layout_validation = _dict(metadata.get("multi_speaker_validation"))
            if layout or layout_validation:
                layout_decision = _dict(layout.get("layout_decision"))
                multi_speaker_results.append(
                    {
                        "candidate_id": clip_id,
                        "detected_speaker_count": layout.get("speaker_count"),
                        "face_count_detected": layout.get("face_count"),
                        "layout_strategy": (
                            layout_validation.get("applied_mode")
                            or layout_decision.get("mode")
                            or layout.get("mode")
                        ),
                        "passed": layout_validation.get("passed"),
                        "face_cutoff_detected": layout_validation.get(
                            "face_cutoff_detected"
                        ),
                        "wrong_speaker_focus_warnings": _list(
                            layout_validation.get("wrong_speaker_focus_warnings")
                        )[:8],
                        "warnings": [
                            item
                            for item in _list(layout_validation.get("warnings"))
                            if isinstance(item, str)
                        ][:16],
                    }
                )
        discovery_by_id = {
            item.candidate_id: item
            for item in (saved_discovery.candidates if saved_discovery is not None else [])
        }
        ranked_candidate_clips = [
            discovery_by_id[item.candidate_id].model_dump(mode="json")
            for item in (
                saved_clip_ranking.ranked_candidates
                if saved_clip_ranking is not None
                else []
            )
            if item.tier != "reject" and item.candidate_id in discovery_by_id
        ]
        editorial_candidate_clips = [
            {
                **discovery_by_id[item.candidate_id].model_dump(mode="json"),
                "story_angle": item.final_story_angle,
                "hook_category": item.final_hook_strategy,
                "pacing_level": item.pacing_intensity,
                "caption_style": item.caption_style,
                "motion_style": item.motion_style,
                "music_mood": item.music_mood,
                "editorial_decision": item.model_dump(mode="json"),
            }
            for item in (
                saved_editorial_decisions.decisions
                if saved_editorial_decisions is not None
                else []
            )
            if item.selected
            and item.render_readiness != "blocked"
            and item.candidate_id in discovery_by_id
        ]
        summary_data = _data(story_summary)
        main_topics = [
            str(item.get("title") or item.get("topic") or item.get("summary") or "")
            for item in topic_sections
        ]
        content_niche = str(
            _dict(_data(planning_summary).get("content_niche")).get("niche")
            or trend_snapshot.get("detected_niche")
            or project.content_category
            or "unknown"
        )
        return {
            "project": project.to_dict(),
            "source_type": project.source_type,
            "duration_seconds": project.duration_seconds,
            "transcript_available": transcript_available,
            "visual_signals_available": visual_available,
            "face_signals_available": face_available,
            "speaker_signals_available": speaker_available,
            "trend_signals_available": bool(trend_snapshot or trend_data),
            "safety_signals_available": bool(safety),
            "personalization_signals_available": bool(personalization_directives),
            "trend_fallback_used": fallback_used,
            "trend_provider_status": trend_status,
            "safety_manual_review_required": manual_review,
            "safety_status": safety_status,
            "personalization_status": (
                "available" if personalization_directives else "unavailable"
            ),
            "render_manifest_available": manifest_available,
            "planning_candidates_available": bool(plans or candidates),
            "editing_timelines_available": bool(timelines),
            "content_niche": content_niche,
            "main_topics": [item for item in main_topics if item][:20],
            "story_threads": [
                str(item.get("summary") or item.get("one_sentence_summary") or "")
                for item in micro_stories
                if item
            ][:20],
            "speakers_or_roles": [item for item in speaker_roles if item][:20],
            "emotional_moments": [
                str(item.get("description") or item.get("excerpt") or "")
                for item in _list(_data(emotions).get("turning_points"))
                if isinstance(item, dict)
            ][:20],
            "already_selected_ranges": [
                {"start": float(item.get("start") or 0.0), "end": float(item.get("end") or 0.0)}
                for item in plans
            ],
            "rejected_ranges": [
                {"start": float(item.get("start") or 0.0), "end": float(item.get("end") or 0.0)}
                for item in _list(_data(ranking).get("over_target"))
                if isinstance(item, dict) and (item.get("start") is not None)
            ],
            "rejected_candidates": [
                _dict(item)
                for item in _list(_data(ranking).get("over_target"))
                if _dict(item)
            ],
            "unused_opportunities": [
                str(item.get("summary") or item.get("reason") or "")
                for item in _list(story_data.get("recommended_clip_stories"))
                if isinstance(item, dict)
            ][:20],
            "warnings": warnings,
            "known_limitations": list(dict.fromkeys(known_limitations)),
            "planning_candidates": candidates or plans,
            "selected_plans": plans,
            "planning_summary": _data(planning_summary),
            "analysis_signals_v2": analysis_signals,
            "transcript_segments": transcript_segments,
            "story_analysis_v2": story_data,
            "virality_summary": _data(virality),
            "trend_research": trend_data,
            "safety": safety,
            "creator_profile": _dict(personalization_directives),
            "story_summary": summary_data,
            "editing_summary": {
                "timeline_count": len(timelines),
                "status": editing.get("status"),
            },
            "editing_timelines": [_dict(item) for item in timelines if _dict(item)],
            "render_summary": {
                "manifest_available": manifest_available,
                "render_count": len(_list(render_manifest.get("renders"))),
                "status": render_manifest.get("status"),
            },
            "whole_video_understanding": (
                saved_understanding.model_dump(mode="json")
                if saved_understanding is not None
                else {}
            ),
            "whole_video_understanding_available": saved_understanding is not None,
            "candidate_clip_discovery": (
                saved_discovery.model_dump(mode="json")
                if saved_discovery is not None
                else {}
            ),
            "candidate_clip_discovery_available": saved_discovery is not None,
            "discovered_candidate_clips": (
                [item.model_dump(mode="json") for item in saved_discovery.candidates]
                if saved_discovery is not None
                else []
            ),
            "clip_ranking": (
                saved_clip_ranking.model_dump(mode="json")
                if saved_clip_ranking is not None
                else {}
            ),
            "clip_ranking_available": saved_clip_ranking is not None,
            "ranked_candidate_clips": ranked_candidate_clips,
            "editorial_decisions": (
                saved_editorial_decisions.model_dump(mode="json")
                if saved_editorial_decisions is not None
                else {}
            ),
            "editorial_decisions_available": saved_editorial_decisions is not None,
            "editorial_candidate_clips": editorial_candidate_clips,
            "explanations": (
                saved_explanations.model_dump(mode="json")
                if saved_explanations is not None
                else {}
            ),
            "explanations_available": saved_explanations is not None,
            "creative_direction_v2": (
                saved_creative_direction_v2.model_dump(mode="json")
                if saved_creative_direction_v2 is not None
                else {}
            ),
            "creative_direction_v2_available": saved_creative_direction_v2 is not None,
            "clip_briefs": (
                saved_clip_briefs.model_dump(mode="json")
                if saved_clip_briefs is not None
                else {}
            ),
            "clip_briefs_available": saved_clip_briefs is not None,
            "hook_retention": (
                saved_hook_retention.model_dump(mode="json")
                if saved_hook_retention is not None
                else {}
            ),
            "hook_retention_available": saved_hook_retention is not None,
            "caption_motion": (
                saved_caption_motion.model_dump(mode="json")
                if saved_caption_motion is not None
                else {}
            ),
            "caption_motion_available": saved_caption_motion is not None,
            "music_mood": (
                saved_music_mood.model_dump(mode="json")
                if saved_music_mood is not None
                else {}
            ),
            "music_mood_available": saved_music_mood is not None,
            "face_motion_validation": (
                {"project_id": project_id, "results": face_motion_results}
                if face_motion_results
                else {}
            ),
            "multi_speaker_validation": (
                {"project_id": project_id, "results": multi_speaker_results}
                if multi_speaker_results
                else {}
            ),
        }

    async def collect_clip_signals(self, project_id: str, clip_id: str) -> dict[str, Any]:
        signals = await self.collect_project_signals(project_id)
        candidates = [
            item
            for item in _list(signals.get("planning_candidates"))
            if isinstance(item, dict)
        ]
        clip = next(
            (
                item
                for item in candidates
                if str(item.get("id") or item.get("clip_id") or item.get("candidate_id"))
                == clip_id
            ),
            {},
        )
        return {**signals, "clip": clip, "clip_id": clip_id}

    async def build_boba_context(self, project_id: str) -> dict[str, Any]:
        signals = await self.collect_project_signals(project_id)
        understanding = summarize_project_understanding(signals)
        return {"signals": signals, "understanding": understanding}

    async def generate_boba_for_project(self, project_id: str) -> BobaBrainStateV1:
        signals = await self.collect_project_signals(project_id)
        if signals.get("transcript_segments") and not signals.get(
            "whole_video_understanding_available"
        ):
            try:
                understanding = self._build_and_save_whole_video(project_id, signals)
                signals["whole_video_understanding"] = understanding.model_dump(mode="json")
                signals["whole_video_understanding_available"] = True
            except ValidationError as exc:
                signals["warnings"] = [
                    *_list(signals.get("warnings")),
                    f"Whole-video understanding is unavailable: {exc}",
                ]
        state = self.brain.create_brain_state(project_id, signals)
        memory_application = None
        if self.memory_enabled:
            self._ensure_global_memory()
            build_and_save_project_memory(
                self.store,
                project_id,
                signals,
                decisions=self.store.list_decisions(project_id),
            )
            creator_profile_id = (
                str(_dict(signals.get("creator_profile")).get("profile_id") or "")
                or None
            )
            retrieval = retrieve_for_project(self.store, project_id, creator_profile_id)
            memory_application = create_memory_application(
                project_id, "planning", retrieval
            )
        explanation = summarize_project_understanding(signals)
        decision = BobaDecisionV1(
            decision_id=new_id("decision"),
            project_id=project_id,
            decision_type="whole_video_understanding",
            question="What does BOBA understand about this project?",
            answer=str(explanation["summary"]),
            confidence=float(explanation["confidence"]),
            input_signals={
                "story": _dict(signals.get("story_analysis_v2")),
                "virality": _dict(signals.get("virality_summary")),
                "trend": _dict(signals.get("trend_research")),
                "safety": _dict(signals.get("safety")),
            },
            reasoning=BobaReasoningV1.model_validate(
                {key: value for key, value in explanation.items() if key != "confidence"}
            ),
            output_directive={
                "target_system": "frontend",
                "directive_type": "display_project_understanding",
                "parameters": {"advisory_only": True},
                "priority": 40,
                "constraints": ["Do not present advisory reasoning as applied editing."],
            },
            memory_application_v1=memory_application,
        )
        self.brain.register_decision(project_id, decision)
        if self.memory_enabled:
            build_and_save_project_memory(
                self.store,
                project_id,
                signals,
                decisions=self.store.list_decisions(project_id),
            )
        return self.store.load_brain_state(project_id) or state

    async def build_project_memory(self, project_id: str) -> BobaProjectMemoryV1:
        signals = await self.collect_project_signals(project_id)
        self._ensure_global_memory()
        return build_and_save_project_memory(
            self.store,
            project_id,
            signals,
            decisions=self.store.list_decisions(project_id),
        )

    def _build_and_save_whole_video(
        self, project_id: str, signals: dict[str, Any]
    ) -> BobaWholeVideoUnderstandingV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        understanding = self.whole_video.build_from_signals(
            project_id,
            signals,
            memory=memory,
        )
        self.store.save_whole_video_understanding(understanding)
        if self.memory_enabled:
            summary = build_whole_video_memory_summary(understanding)
            self.store.save_record(whole_video_memory_record(summary))
        return understanding

    async def generate_whole_video_understanding(
        self, project_id: str
    ) -> BobaWholeVideoUnderstandingV1:
        signals = await self.collect_project_signals(project_id)
        return self._build_and_save_whole_video(project_id, signals)

    def _build_and_save_candidate_discovery(
        self, project_id: str, signals: dict[str, Any]
    ) -> BobaCandidateClipDiscoveryV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        discovery = self.candidate_discovery.discover_from_signals(
            project_id,
            signals,
            memory=memory,
        )
        return self.store.save_candidate_clip_discovery(discovery)

    async def discover_candidate_clips(
        self, project_id: str
    ) -> BobaCandidateClipDiscoveryV1:
        signals = await self.collect_project_signals(project_id)
        return self._build_and_save_candidate_discovery(project_id, signals)

    def _build_and_save_clip_ranking(
        self,
        project_id: str,
        signals: dict[str, Any],
        discovery: BobaCandidateClipDiscoveryV1 | None,
    ) -> BobaDiscoveryClipRankingV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        ranking = self.clip_ranking.rank_from_signals(
            project_id,
            signals,
            candidate_discovery=discovery,
            memory=memory,
        )
        return self.store.save_clip_ranking(ranking)

    async def rank_discovered_candidate_clips(
        self, project_id: str
    ) -> BobaDiscoveryClipRankingV1:
        signals = await self.collect_project_signals(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        return self._build_and_save_clip_ranking(project_id, signals, discovery)

    def _build_and_save_editorial_decisions(
        self,
        project_id: str,
        signals: dict[str, Any],
        ranking: BobaDiscoveryClipRankingV1 | None,
        discovery: BobaCandidateClipDiscoveryV1 | None,
    ) -> BobaEditorialDecisionSetV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        decisions = self.editorial_decision.decide_from_signals(
            project_id,
            signals,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            creative_briefs=self.creative_director.list_briefs(project_id),
            memory=memory,
        )
        return self.store.save_editorial_decisions(decisions)

    async def generate_editorial_decisions(
        self, project_id: str
    ) -> BobaEditorialDecisionSetV1:
        signals = await self.collect_project_signals(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        return self._build_and_save_editorial_decisions(
            project_id,
            signals,
            ranking,
            discovery,
        )

    async def generate_explanations(self, project_id: str) -> BobaExplanationSetV1:
        signals = await self.collect_project_signals(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        explanations = self.explanation.explain_from_signals(
            project_id,
            signals,
            whole_video_understanding=understanding,
            candidate_discovery=discovery,
            clip_ranking=ranking,
            editorial_decisions=decisions,
            creative_briefs=self.creative_director.list_briefs(project_id),
            memory=memory,
        )
        return self.store.save_explanations(explanations)

    async def generate_creative_direction_v2(
        self, project_id: str
    ) -> BobaCreativeDirectionSetV2:
        signals = await self.collect_project_signals(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        explanations = self.store.load_explanations(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        direction = self.creative_director_v2.direct_from_signals(
            project_id,
            signals,
            editorial_decisions=decisions,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            whole_video_understanding=understanding,
            explanations=explanations,
            memory=memory,
        )
        return self.store.save_creative_direction_v2(direction)

    async def generate_clip_briefs(self, project_id: str) -> BobaClipBriefSetV1:
        signals = await self.collect_project_signals(project_id)
        direction = self.store.load_creative_direction_v2(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        explanations = self.store.load_explanations(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        briefs = self.clip_brief_generator.generate_from_signals(
            project_id,
            signals,
            creative_direction_v2=direction,
            editorial_decisions=decisions,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            explanations=explanations,
            whole_video_understanding=understanding,
            memory=memory,
        )
        return self.store.save_clip_briefs(briefs)

    async def generate_hook_retention(
        self, project_id: str
    ) -> BobaHookRetentionSetV1:
        signals = await self.collect_project_signals(project_id)
        briefs = self.store.load_clip_briefs(project_id)
        creative = self.store.load_creative_direction_v2(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        explanations = self.store.load_explanations(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        analysis = self.hook_retention_brain.analyze_from_signals(
            project_id,
            signals,
            clip_briefs=briefs,
            creative_direction_v2=creative,
            editorial_decisions=decisions,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            whole_video_understanding=understanding,
            explanations=explanations,
            virality=_dict(signals.get("virality_summary")),
            memory=memory,
        )
        return self.store.save_hook_retention(analysis)

    async def generate_caption_motion(
        self,
        project_id: str,
    ) -> BobaCaptionMotionRecommendationSetV1:
        signals = await self.collect_project_signals(project_id)
        recommendations = self.caption_motion_brain.analyze_from_signals(
            project_id,
            signals,
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            creative_direction_v2=self.store.load_creative_direction_v2(project_id),
            editorial_decisions=self.store.load_editorial_decisions(project_id),
            clip_ranking=self.store.load_clip_ranking(project_id),
            candidate_discovery=self.store.load_candidate_clip_discovery(project_id),
            whole_video_understanding=self.store.load_whole_video_understanding(
                project_id
            ),
            explanations=self.store.load_explanations(project_id),
            face_motion_validation=_dict(signals.get("face_motion_validation")),
            multi_speaker_validation=_dict(
                signals.get("multi_speaker_validation")
            ),
            analysis_signals=_dict(signals.get("analysis_signals_v2")),
            memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
        )
        return self.store.save_caption_motion(recommendations)

    async def generate_music_mood(
        self,
        project_id: str,
    ) -> BobaMusicMoodRecommendationSetV1:
        signals = await self.collect_project_signals(project_id)
        try:
            registry = load_music_assets(get_settings().rendering.asset_root)
        except (OSError, ValueError):
            manifest_metadata: dict[str, Any] = {}
        else:
            manifest_metadata = music_manifest_awareness(registry)
        recommendations = self.music_mood_brain.analyze_from_signals(
            project_id,
            signals,
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            caption_motion=self.store.load_caption_motion(project_id),
            creative_direction_v2=self.store.load_creative_direction_v2(project_id),
            editorial_decisions=self.store.load_editorial_decisions(project_id),
            clip_ranking=self.store.load_clip_ranking(project_id),
            candidate_discovery=self.store.load_candidate_clip_discovery(project_id),
            whole_video_understanding=self.store.load_whole_video_understanding(
                project_id
            ),
            explanations=self.store.load_explanations(project_id),
            music_manifest_metadata=manifest_metadata,
            memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
        )
        return self.store.save_music_mood(recommendations)

    async def generate_experimentation_plan(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
        dry_run: bool = False,
    ) -> BobaExperimentationSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        experimentation = self.experimentation_system.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            caption_motion=self.store.load_caption_motion(project_id),
            music_mood=self.store.load_music_mood(project_id),
            creative_direction=self.store.load_creative_direction_v2(project_id),
            editorial_decision=self.store.load_editorial_decisions(project_id),
            explanation=self.store.load_explanations(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if creator_id != "local_creator":
            experimentation.warnings = list(
                dict.fromkeys(
                    [
                        *experimentation.warnings,
                        (
                            "Creator identifier selected the local advisory context; "
                            "no cross-project profile data was copied."
                        ),
                    ]
                )
            )
        if dry_run:
            return experimentation
        return self.store.save_experimentation_plan(experimentation)

    def load_experimentation_plan(
        self,
        project_id: str,
    ) -> BobaExperimentationSetV1 | None:
        return self.store.load_experimentation_plan(project_id)

    def export_experimentation_plan(self, project_id: str) -> dict[str, Any]:
        return self.store.export_experimentation_plan(project_id)

    def reset_experimentation_plan(self, project_id: str) -> bool:
        return self.store.reset_experimentation_plan(project_id)

    def record_manual_experiment_result(
        self,
        project_id: str,
        *,
        experiment_id: str,
        selected_variant_id: str,
        manual_rating: float,
        outcome_label: BobaExperimentOutcomeLabel,
        creator_note: str = "",
        should_feed_learning: bool = False,
    ) -> BobaExperimentManualResultV1:
        experimentation = self.store.load_experimentation_plan(project_id)
        if experimentation is None:
            raise ValidationError(
                "BOBA experimentation plan is not available.",
                details={"project_id": project_id},
            )
        experiment = next(
            (
                item
                for item in experimentation.experiment_plans
                if item.experiment_id == experiment_id
            ),
            None,
        )
        if experiment is None:
            raise ValidationError(
                "BOBA experiment was not found.",
                details={
                    "project_id": project_id,
                    "experiment_id": experiment_id,
                },
            )
        try:
            result = self.experimentation_system.create_manual_result(
                experiment,
                selected_variant_id=selected_variant_id,
                manual_rating=manual_rating,
                outcome_label=outcome_label,
                creator_note=creator_note,
                should_feed_learning=should_feed_learning,
            )
        except ValueError as exc:
            raise ValidationError(
                "BOBA manual experiment result is invalid.",
                details={"reason": str(exc)},
            ) from exc
        return self.store.record_manual_experiment_result(project_id, result)

    async def apply_experiment_guidance_dry_run(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
    ) -> BobaExperimentationSetV1:
        return await self.generate_experimentation_plan(
            project_id,
            creator_id=creator_id,
            dry_run=True,
        )

    async def record_performance_feedback_event(
        self,
        project_id: str,
        *,
        event_type: BobaPerformanceEventType,
        target_type: BobaPerformanceTargetType,
        target_id: str,
        candidate_id: str = "",
        brief_id: str = "",
        experiment_id: str = "",
        variant_id: str = "",
        manual_rating: float | None = None,
        creator_note: str = "",
        platform: str = "",
        source_label: str = "manual_entry",
        metrics: BobaManualPerformanceMetricsV1 | None = None,
        retention_notes: str = "",
        creator_interpretation: str = "",
        outcome_label: BobaPerformanceOutcomeLabel | None = None,
        baseline_id: str = "",
        selected_variant_id: str = "",
        should_feed_learning: bool = False,
    ) -> tuple[BobaPerformanceFeedbackEventV1, BobaPerformanceFeedbackSetV1]:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        experimentation = self.store.load_experimentation_plan(project_id)
        if event_type == "manual_experiment_result":
            if experimentation is None:
                raise ValidationError(
                    "BOBA experimentation plan is required for experiment results.",
                    details={"project_id": project_id},
                )
            experiment = next(
                (
                    item
                    for item in experimentation.experiment_plans
                    if item.experiment_id == experiment_id
                ),
                None,
            )
            if experiment is None:
                raise ValidationError(
                    "BOBA experiment was not found.",
                    details={
                        "project_id": project_id,
                        "experiment_id": experiment_id,
                    },
                )
            valid_targets = {
                experiment.baseline.baseline_id,
                *(variant.variant_id for variant in experiment.variants),
            }
            chosen_id = selected_variant_id or variant_id
            if chosen_id and chosen_id not in valid_targets:
                raise ValidationError(
                    "Selected experiment baseline or variant was not found.",
                    details={"selected_variant_id": chosen_id},
                )
            candidate_id = candidate_id or experiment.candidate_id
            brief_id = brief_id or experiment.brief_id
            baseline_id = baseline_id or experiment.baseline.baseline_id
        event = self.performance_feedback_brain.create_event(
            project_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            candidate_id=candidate_id,
            brief_id=brief_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
            manual_rating=manual_rating,
            creator_note=creator_note,
            platform=platform,
            source_label=source_label,
            metrics=metrics,
            retention_notes=retention_notes,
            creator_interpretation=creator_interpretation,
            outcome_label=outcome_label,
            baseline_id=baseline_id,
            selected_variant_id=selected_variant_id,
            should_feed_learning=should_feed_learning,
        )
        saved_event = self.store.record_performance_feedback_event(event)
        feedback = await self.generate_performance_feedback(project_id)
        return saved_event, feedback

    async def generate_content_scout_v2(
        self,
        project_id: str,
        *,
        manual_items: list[dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaContentScoutSetV2:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        scout = self.content_scout_v2.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_items=manual_items or [],
            import_paths=import_paths or [],
            source_label=source_label,
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            scout_v1=self.scout.list_candidates(),
            dry_run=dry_run,
        )
        if dry_run:
            return scout
        return self.store.save_content_scout_v2(scout)

    def load_content_scout_v2(
        self,
        project_id: str,
    ) -> BobaContentScoutSetV2 | None:
        return self.store.load_content_scout_v2(project_id)

    def export_content_scout_v2(self, project_id: str) -> dict[str, Any]:
        return self.store.export_content_scout_v2(project_id)

    def reset_content_scout_v2(self, project_id: str) -> bool:
        return self.store.reset_content_scout_v2(project_id)

    async def generate_research_brain(
        self,
        project_id: str,
        *,
        manual_sources: list[dict[str, Any]] | None = None,
        pasted_text_entries: list[str | dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaResearchBrainSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        research = self.research_brain.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_sources=manual_sources or [],
            pasted_text_entries=pasted_text_entries or [],
            import_paths=import_paths or [],
            source_label=source_label,
            content_scout=self.store.load_content_scout_v2(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return research
        return self.store.save_research_brain(research)

    def load_research_brain(
        self,
        project_id: str,
    ) -> BobaResearchBrainSetV1 | None:
        return self.store.load_research_brain(project_id)

    def export_research_brain(self, project_id: str) -> dict[str, Any]:
        return self.store.export_research_brain(project_id)

    def reset_research_brain(self, project_id: str) -> bool:
        return self.store.reset_research_brain(project_id)

    async def generate_trend_topic_watcher(
        self,
        project_id: str,
        *,
        manual_snapshots: list[dict[str, Any]] | None = None,
        pasted_topic_lists: list[str | dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaTrendTopicWatcherSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        watcher = self.trend_topic_watcher.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_snapshots=manual_snapshots or [],
            pasted_topic_lists=pasted_topic_lists or [],
            import_paths=import_paths or [],
            source_label=source_label,
            research_brain=self.store.load_research_brain(project_id),
            content_scout=self.store.load_content_scout_v2(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return watcher
        return self.store.save_trend_topic_watcher(watcher)

    def load_trend_topic_watcher(
        self,
        project_id: str,
    ) -> BobaTrendTopicWatcherSetV1 | None:
        return self.store.load_trend_topic_watcher(project_id)

    def export_trend_topic_watcher(self, project_id: str) -> dict[str, Any]:
        return self.store.export_trend_topic_watcher(project_id)

    def reset_trend_topic_watcher(self, project_id: str) -> bool:
        return self.store.reset_trend_topic_watcher(project_id)

    async def generate_candidate_video_scorer(
        self,
        project_id: str,
        *,
        manual_candidates: list[dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaCandidateVideoScorerSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        scorer = self.candidate_video_scorer.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_candidates=manual_candidates or [],
            import_paths=import_paths or [],
            source_label=source_label,
            content_scout=self.store.load_content_scout_v2(project_id),
            research_brain=self.store.load_research_brain(project_id),
            trend_topic_watcher=self.store.load_trend_topic_watcher(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return scorer
        return self.store.save_candidate_video_scorer(scorer)

    def load_candidate_video_scorer(
        self,
        project_id: str,
    ) -> BobaCandidateVideoScorerSetV1 | None:
        return self.store.load_candidate_video_scorer(project_id)

    def export_candidate_video_scorer(self, project_id: str) -> dict[str, Any]:
        return self.store.export_candidate_video_scorer(project_id)

    def reset_candidate_video_scorer(self, project_id: str) -> bool:
        return self.store.reset_candidate_video_scorer(project_id)

    async def generate_rights_permission_gate(
        self,
        project_id: str,
        *,
        manual_items: list[dict[str, Any]] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaRightsPermissionGateSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        gate = self.rights_permission_gate.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_items=manual_items or [],
            source_label=source_label,
            candidate_video_scorer=(
                self.store.load_candidate_video_scorer(project_id)
            ),
            content_scout=self.store.load_content_scout_v2(project_id),
            research_brain=self.store.load_research_brain(project_id),
            trend_topic_watcher=self.store.load_trend_topic_watcher(project_id),
            clip_briefs=self.store.load_clip_briefs(project_id),
            music_mood=self.store.load_music_mood(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return gate
        return self.store.save_rights_permission_gate(gate)

    def load_rights_permission_gate(
        self,
        project_id: str,
    ) -> BobaRightsPermissionGateSetV1 | None:
        return self.store.load_rights_permission_gate(project_id)

    def export_rights_permission_gate(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.store.export_rights_permission_gate(project_id)

    def reset_rights_permission_gate(self, project_id: str) -> bool:
        return self.store.reset_rights_permission_gate(project_id)

    async def generate_observer_report(
        self,
        project_id: str,
        *,
        workflow_context: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> BobaObserverSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        report = self.observer.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            workflow_context=workflow_context,
            dry_run=dry_run,
        )
        if dry_run:
            return report
        return self.store.save_observer_report(report)

    def load_observer_report(
        self,
        project_id: str,
    ) -> BobaObserverSetV1 | None:
        return self.store.load_observer_report(project_id)

    def export_observer_report(self, project_id: str) -> dict[str, Any]:
        return self.store.export_observer_report(project_id)

    def reset_observer_report(self, project_id: str) -> bool:
        return self.store.reset_observer_report(project_id)

    async def generate_boba_error_doctor(
        self,
        project_id: str,
        *,
        diagnostic_context: dict[str, Any] | None = None,
        error_summaries: list[str | dict[str, Any]] | None = None,
        dry_run: bool = False,
    ) -> BobaErrorDoctorSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        report = self.error_doctor.analyze(
            project_id,
            self.store.load_observer_report(project_id),
            source_id=project.link_ingestion_id or project_id,
            manual_context=diagnostic_context,
            error_summaries=error_summaries,
            dry_run=dry_run,
        )
        if dry_run:
            return report
        return self.store.save_boba_error_doctor(report)

    def load_boba_error_doctor(
        self,
        project_id: str,
    ) -> BobaErrorDoctorSetV1 | None:
        return self.store.load_boba_error_doctor(project_id)

    def export_boba_error_doctor(self, project_id: str) -> dict[str, Any]:
        return self.store.export_boba_error_doctor(project_id)

    def reset_boba_error_doctor(self, project_id: str) -> bool:
        return self.store.reset_boba_error_doctor(project_id)

    async def generate_boba_root_cause_analyzer(
        self,
        project_id: str,
        *,
        diagnostic_context: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> BobaRootCauseAnalyzerSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        report = self.root_cause_analyzer.analyze(
            project_id,
            self.store.load_boba_error_doctor(project_id),
            source_id=project.link_ingestion_id or project_id,
            manual_context=diagnostic_context,
            dry_run=dry_run,
        )
        if dry_run:
            return report
        return self.store.save_boba_root_cause_analyzer(report)

    def load_boba_root_cause_analyzer(
        self,
        project_id: str,
    ) -> BobaRootCauseAnalyzerSetV1 | None:
        return self.store.load_boba_root_cause_analyzer(project_id)

    def export_boba_root_cause_analyzer(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.store.export_boba_root_cause_analyzer(project_id)

    def reset_boba_root_cause_analyzer(self, project_id: str) -> bool:
        return self.store.reset_boba_root_cause_analyzer(project_id)

    async def generate_boba_repair_planner(
        self,
        project_id: str,
        *,
        planning_context: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> BobaRepairPlannerSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        report = self.repair_planner.plan(
            project_id,
            self.store.load_boba_root_cause_analyzer(project_id),
            source_id=project.link_ingestion_id or project_id,
            manual_context=planning_context,
            dry_run=dry_run,
        )
        if dry_run:
            return report
        return self.store.save_boba_repair_planner(report)

    def load_boba_repair_planner(
        self,
        project_id: str,
    ) -> BobaRepairPlannerSetV1 | None:
        return self.store.load_boba_repair_planner(project_id)

    def export_boba_repair_planner(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.store.export_boba_repair_planner(project_id)

    def reset_boba_repair_planner(self, project_id: str) -> bool:
        return self.store.reset_boba_repair_planner(project_id)

    async def generate_boba_code_surgeon_proposal(
        self,
        project_id: str,
        *,
        repair_case_id: str | None = None,
        repair_strategy_id: str | None = None,
        unified_diff: str | None = None,
        proposal_source: BobaCodeProposalSourceV1 = "user_provided_diff",
        deterministic_template_identifier: str | None = None,
        template_parameters: dict[str, Any] | None = None,
        base_branch: str = "main",
        affected_paths: list[str] | None = None,
        approved_special_paths: list[str] | None = None,
    ) -> BobaCodeSurgeonSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.code_surgeon.propose(
            project_id,
            self.store.load_boba_repair_planner(project_id),
            source_id=project.link_ingestion_id or project_id,
            repair_case_id=repair_case_id,
            repair_strategy_id=repair_strategy_id,
            unified_diff=unified_diff,
            proposal_source=proposal_source,
            deterministic_template_identifier=deterministic_template_identifier,
            template_parameters=template_parameters,
            base_branch=base_branch,
            affected_paths=affected_paths or [],
            approved_special_paths=approved_special_paths or [],
        )
        return self.store.save_boba_code_surgeon(
            report,
            unified_diff=self.code_surgeon.last_proposed_diff,
            patch_proposal_id=(
                report.patch_proposals[-1].patch_proposal_id
                if report.patch_proposals
                else None
            ),
        )

    async def validate_boba_code_surgeon_patch(
        self,
        project_id: str,
        **kwargs: Any,
    ) -> BobaCodeSurgeonSetV1:
        kwargs["proposal_source"] = "imported_review_patch"
        return await self.generate_boba_code_surgeon_proposal(project_id, **kwargs)

    async def execute_approved_boba_code_surgeon_patch(
        self,
        project_id: str,
        *,
        patch_proposal_id: str,
        approval: BobaCodeApprovalRecordV1,
        approved_validation_commands: list[str],
    ) -> BobaCodeSurgeonSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.store.load_boba_code_surgeon(project_id)
        if report is None:
            raise ValidationError("BOBA Code Surgeon V1 proposal is not available.")
        unified_diff = self.store.load_boba_code_surgeon_patch(
            project_id,
            patch_proposal_id,
        )
        updated = self.code_surgeon.execute_approved(
            report,
            patch_proposal_id=patch_proposal_id,
            unified_diff=unified_diff,
            approval=approval,
            approved_validation_commands=approved_validation_commands,
        )
        run_id = (
            updated.isolated_runs[-1].isolated_run_id
            if updated.isolated_runs
            else patch_proposal_id
        )
        return self.store.save_boba_code_surgeon(
            updated,
            unified_diff=unified_diff,
            patch_proposal_id=run_id,
        )

    async def prepare_boba_code_surgeon_local_commit(
        self,
        project_id: str,
        *,
        isolated_run_id: str,
        approval: BobaCodeApprovalRecordV1,
    ) -> BobaCodeSurgeonSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.store.load_boba_code_surgeon(project_id)
        if report is None:
            raise ValidationError("BOBA Code Surgeon V1 proposal is not available.")
        updated = self.code_surgeon.prepare_local_commit(
            report,
            isolated_run_id=isolated_run_id,
            approval=approval,
        )
        return self.store.save_boba_code_surgeon(updated)

    def load_boba_code_surgeon(
        self,
        project_id: str,
    ) -> BobaCodeSurgeonSetV1 | None:
        return self.store.load_boba_code_surgeon(project_id)

    def export_boba_code_surgeon(self, project_id: str) -> dict[str, Any]:
        return self.store.export_boba_code_surgeon(project_id)

    def reset_boba_code_surgeon(self, project_id: str) -> bool:
        return self.store.reset_boba_code_surgeon(project_id)

    async def generate_boba_tool_recovery_plan(
        self,
        project_id: str,
        *,
        selected_handoff_id: str | None = None,
        selected_repair_strategy_id: str | None = None,
        failure_context: dict[str, Any] | None = None,
        run_health_checks: bool | None = None,
    ) -> BobaToolRecoveryBrainSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.tool_recovery.plan(
            project_id,
            self.store.load_boba_repair_planner(project_id),
            source_id=project.link_ingestion_id or project_id,
            selected_handoff_id=selected_handoff_id,
            selected_repair_strategy_id=selected_repair_strategy_id,
            failure_context=failure_context,
            run_health_checks=run_health_checks,
        )
        return self.store.save_boba_tool_recovery(report)

    async def run_boba_tool_health_checks(
        self,
        project_id: str,
        *,
        tool_ids: list[str] | None = None,
    ) -> BobaToolRecoveryBrainSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.store.load_boba_tool_recovery(project_id)
        if report is None:
            raise ValidationError("BOBA Tool Recovery plan is not available.")
        updated = self.tool_recovery.run_health_checks(report, tool_ids=tool_ids)
        return self.store.save_boba_tool_recovery(updated)

    async def execute_approved_boba_tool_recovery(
        self,
        project_id: str,
        *,
        recovery_plan_id: str,
        recovery_strategy_id: str,
        approval: BobaToolRecoveryApprovalV1,
    ) -> BobaToolRecoveryBrainSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.store.load_boba_tool_recovery(project_id)
        if report is None:
            raise ValidationError("BOBA Tool Recovery plan is not available.")
        updated = self.tool_recovery.execute_approved(
            report,
            recovery_plan_id=recovery_plan_id,
            recovery_strategy_id=recovery_strategy_id,
            approval=approval,
        )
        return self.store.save_boba_tool_recovery(updated)

    async def validate_boba_recovered_output(
        self,
        project_id: str,
        *,
        recovery_attempt_id: str,
    ) -> BobaToolRecoveryBrainSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.store.load_boba_tool_recovery(project_id)
        if report is None:
            raise ValidationError("BOBA Tool Recovery report is not available.")
        updated = self.tool_recovery.validate_output(
            report,
            recovery_attempt_id=recovery_attempt_id,
        )
        return self.store.save_boba_tool_recovery(updated)

    async def rollback_boba_tool_recovery(
        self,
        project_id: str,
        *,
        recovery_attempt_id: str,
        trigger: str,
    ) -> BobaToolRecoveryBrainSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        report = self.store.load_boba_tool_recovery(project_id)
        if report is None:
            raise ValidationError("BOBA Tool Recovery report is not available.")
        updated = self.tool_recovery.rollback(
            report,
            recovery_attempt_id=recovery_attempt_id,
            trigger=trigger,
        )
        return self.store.save_boba_tool_recovery(updated)

    def load_boba_tool_recovery(
        self,
        project_id: str,
    ) -> BobaToolRecoveryBrainSetV1 | None:
        return self.store.load_boba_tool_recovery(project_id)

    def export_boba_tool_recovery(self, project_id: str) -> dict[str, Any]:
        return self.store.export_boba_tool_recovery(project_id)

    def reset_boba_tool_recovery(self, project_id: str) -> bool:
        return self.store.reset_boba_tool_recovery(project_id)

    async def generate_boba_output_quality_review(
        self,
        project_id: str,
        *,
        output_reference: str,
        baseline_reference: str | None = None,
        review_mode: BobaOutputReviewModeV1 = (
            "full_available_evidence_review"
        ),
        rights_status: str = "unknown",
        safety_status: str = "unknown",
        workflow_stage: str = "quality_review",
        comparison_basis: BobaOutputComparisonBasisV1 = "unknown",
        required_quality_properties: list[str] | None = None,
        non_negotiable_requirements: list[str] | None = None,
        output_modification_requested: bool = False,
        source_modification_requested: bool = False,
        network_review_requested: bool = False,
    ) -> BobaOutputQualityReviewerSetV1:
        (
            project,
            known_output_artifacts,
            creative_artifacts,
            validation_artifacts,
        ) = await self._output_quality_inputs(project_id)
        selected = next(
            (
                item
                for item in known_output_artifacts
                if output_reference
                in {
                    str(item.get("reference") or ""),
                    str(item.get("artifact_id") or ""),
                }
            ),
            {},
        )
        render_entry = _dict(
            selected.get("manifest_entry") or selected.get("render_entry")
        )
        render_metadata = _dict(render_entry.get("metadata"))
        validation_artifacts.update(
            {
                key: value
                for key, value in {
                    "boundary_quality": render_metadata.get("boundary_quality"),
                    "boundary_validation": render_metadata.get(
                        "boundary_validation"
                    ),
                    "caption_render_validation": render_metadata.get(
                        "caption_render_validation"
                    ),
                    "caption_readability_validation": render_metadata.get(
                        "caption_readability_validation"
                    ),
                    "caption_events": render_metadata.get("caption_events"),
                    "face_motion_validation": (
                        render_metadata.get("face_motion_validation_result_v1")
                        or render_metadata.get("motion_render_validation")
                    ),
                    "multi_speaker_validation": (
                        render_metadata.get(
                            "multi_speaker_layout_validation_result_v1"
                        )
                        or render_metadata.get("multi_speaker_validation")
                    ),
                }.items()
                if value is not None
            }
        )
        existing = self.store.load_boba_output_quality_reviewer(project_id)
        report = generate_boba_output_quality_review(
            reviewer=self.output_quality_reviewer,
            project_id=project_id,
            output_reference=output_reference,
            baseline_reference=baseline_reference,
            known_output_artifacts=known_output_artifacts,
            source_id=str(project.get("link_ingestion_id") or project_id),
            source_media_reference=str(project.get("storage_key") or ""),
            review_mode=review_mode,
            rights_status=rights_status,
            safety_status=safety_status,
            workflow_stage=workflow_stage,
            tool_recovery_report=self.store.load_boba_tool_recovery(project_id),
            code_surgeon_report=self.store.load_boba_code_surgeon(project_id),
            repair_planner_report=self.store.load_boba_repair_planner(project_id),
            creative_artifacts=creative_artifacts,
            validation_artifacts=validation_artifacts,
            required_quality_properties=required_quality_properties or [],
            non_negotiable_requirements=non_negotiable_requirements or [],
            comparison_basis=comparison_basis,
            existing_report=existing,
            output_modification_requested=output_modification_requested,
            source_modification_requested=source_modification_requested,
            network_review_requested=network_review_requested,
        )
        return self.store.save_boba_output_quality_reviewer(report)

    async def run_boba_output_technical_review(
        self,
        project_id: str,
        *,
        output_reference: str,
        rights_status: str = "unknown",
        safety_status: str = "unknown",
        required_quality_properties: list[str] | None = None,
        non_negotiable_requirements: list[str] | None = None,
    ) -> BobaOutputQualityReviewerSetV1:
        (
            project,
            known_output_artifacts,
            creative_artifacts,
            validation_artifacts,
        ) = await self._output_quality_inputs(project_id)
        report = run_boba_output_technical_review(
            reviewer=self.output_quality_reviewer,
            project_id=project_id,
            output_reference=output_reference,
            known_output_artifacts=known_output_artifacts,
            source_id=str(project.get("link_ingestion_id") or project_id),
            source_media_reference=str(project.get("storage_key") or ""),
            rights_status=rights_status,
            safety_status=safety_status,
            tool_recovery_report=self.store.load_boba_tool_recovery(project_id),
            code_surgeon_report=self.store.load_boba_code_surgeon(project_id),
            repair_planner_report=self.store.load_boba_repair_planner(project_id),
            creative_artifacts=creative_artifacts,
            validation_artifacts=validation_artifacts,
            required_quality_properties=required_quality_properties or [],
            non_negotiable_requirements=non_negotiable_requirements or [],
            existing_report=self.store.load_boba_output_quality_reviewer(
                project_id
            ),
        )
        return self.store.save_boba_output_quality_reviewer(report)

    async def compare_boba_output_quality_baseline(
        self,
        project_id: str,
        *,
        output_reference: str,
        baseline_reference: str,
        rights_status: str = "unknown",
        safety_status: str = "unknown",
        comparison_basis: BobaOutputComparisonBasisV1 = "unknown",
        required_quality_properties: list[str] | None = None,
        non_negotiable_requirements: list[str] | None = None,
    ) -> BobaOutputQualityReviewerSetV1:
        (
            project,
            known_output_artifacts,
            creative_artifacts,
            validation_artifacts,
        ) = await self._output_quality_inputs(project_id)
        report = compare_boba_output_quality_baseline(
            reviewer=self.output_quality_reviewer,
            project_id=project_id,
            output_reference=output_reference,
            baseline_reference=baseline_reference,
            known_output_artifacts=known_output_artifacts,
            source_id=str(project.get("link_ingestion_id") or project_id),
            source_media_reference=str(project.get("storage_key") or ""),
            rights_status=rights_status,
            safety_status=safety_status,
            comparison_basis=comparison_basis,
            tool_recovery_report=self.store.load_boba_tool_recovery(project_id),
            code_surgeon_report=self.store.load_boba_code_surgeon(project_id),
            repair_planner_report=self.store.load_boba_repair_planner(project_id),
            creative_artifacts=creative_artifacts,
            validation_artifacts=validation_artifacts,
            required_quality_properties=required_quality_properties or [],
            non_negotiable_requirements=non_negotiable_requirements or [],
            existing_report=self.store.load_boba_output_quality_reviewer(
                project_id
            ),
        )
        return self.store.save_boba_output_quality_reviewer(report)

    async def record_boba_output_human_review(
        self,
        project_id: str,
        *,
        review_case_id: str,
        reviewer_identity: str,
        review_decision: str,
        answers: dict[str, Any] | None = None,
        notes: str = "",
    ) -> BobaOutputQualityReviewerSetV1:
        if await self.projects.get(project_id) is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        existing = self.store.load_boba_output_quality_reviewer(project_id)
        if existing is None:
            raise ValidationError(
                "BOBA Output Quality Reviewer V1 report is not available."
            )
        updated = record_boba_output_human_review(
            existing,
            review_case_id=review_case_id,
            reviewer_identity=reviewer_identity,
            review_decision=review_decision,
            answers=answers,
            notes=notes,
        )
        return self.store.save_boba_output_quality_reviewer(updated)

    def load_boba_output_quality_reviewer(
        self,
        project_id: str,
    ) -> BobaOutputQualityReviewerSetV1 | None:
        return self.store.load_boba_output_quality_reviewer(project_id)

    def export_boba_output_quality_reviewer(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.store.export_boba_output_quality_reviewer(project_id)

    def reset_boba_output_quality_reviewer(self, project_id: str) -> bool:
        return self.store.reset_boba_output_quality_reviewer(project_id)

    async def generate_performance_feedback(
        self,
        project_id: str,
        *,
        dry_run: bool = False,
    ) -> BobaPerformanceFeedbackSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        feedback = self.performance_feedback_brain.analyze(
            project_id,
            self.store.list_performance_feedback_events(project_id),
            source_id=project.link_ingestion_id or project_id,
            experimentation=self.store.load_experimentation_plan(project_id),
            experiment_manual_results=(
                self.store.list_manual_experiment_results(project_id)
            ),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            caption_motion=self.store.load_caption_motion(project_id),
            music_mood=self.store.load_music_mood(project_id),
            clip_ranking=self.store.load_clip_ranking(project_id),
            editorial_decision=self.store.load_editorial_decisions(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return feedback
        return self.store.save_performance_feedback(feedback)

    def load_performance_feedback(
        self,
        project_id: str,
    ) -> BobaPerformanceFeedbackSetV1 | None:
        return self.store.load_performance_feedback(project_id)

    def export_performance_feedback(self, project_id: str) -> dict[str, Any]:
        return self.store.export_performance_feedback(project_id)

    def reset_performance_feedback(self, project_id: str) -> bool:
        return self.store.reset_performance_feedback(project_id)

    async def apply_performance_guidance_dry_run(
        self,
        project_id: str,
    ) -> BobaPerformanceFeedbackSetV1:
        return await self.generate_performance_feedback(
            project_id,
            dry_run=True,
        )

    async def generate_creative_briefs(
        self, project_id: str
    ) -> list[BobaCreativeBriefV1]:
        signals = await self.collect_project_signals(project_id)
        if not signals.get("whole_video_understanding") and signals.get(
            "transcript_segments"
        ):
            understanding = self._build_and_save_whole_video(project_id, signals)
            signals["whole_video_understanding"] = understanding.model_dump(mode="json")
            signals["whole_video_understanding_available"] = True
        creator_profile_id = (
            str(_dict(signals.get("creator_profile")).get("profile_id") or "")
            or None
        )
        return self.creative_director.create_briefs(
            project_id,
            signals,
            creator_profile_id=creator_profile_id,
        )

    async def rank_project_candidates(self, project_id: str) -> BobaClipRankingV1:
        signals = await self.collect_project_signals(project_id)
        candidates = [
            _dict(item) for item in _list(signals.get("planning_candidates")) if _dict(item)
        ]
        ranking = rank_candidates(
            project_id,
            candidates,
            used_source_ranges=_list(signals.get("already_selected_ranges")),
        )
        if self.memory_enabled:
            self._ensure_global_memory()
            if self.store.load_project_memory(project_id) is None:
                build_and_save_project_memory(
                    self.store,
                    project_id,
                    signals,
                    decisions=self.store.list_decisions(project_id),
                )
            creator_profile_id = (
                str(_dict(signals.get("creator_profile")).get("profile_id") or "")
                or None
            )
            clip_traits = [
                str(signals.get("content_niche") or "unknown"),
                *[str(item) for item in _list(signals.get("main_topics"))[:8]],
            ]
            retrieval = retrieve_for_clip_decision(
                self.store, project_id, clip_traits, creator_profile_id
            )
            application = create_memory_application(project_id, "ranking", retrieval)
            if any(
                item.get("field") == "emotional_payoff_advisory"
                for item in application.adjustments
            ):
                for insight in ranking.ranked_candidates:
                    delta = min(0.08, 0.08 * insight.emotional_strength)
                    insight.overall_recommendation = round(
                        min(1.0, insight.overall_recommendation + delta), 3
                    )
                    insight.reasons = list(
                        dict.fromkeys(
                            [
                                *insight.reasons,
                                "bounded creator-memory emotional-payoff advisory",
                            ]
                        )
                    )
                ranking.ranked_candidates.sort(
                    key=lambda item: item.overall_recommendation, reverse=True
                )
            ranking.memory_application_v1 = application
            if application.memory_used:
                ranking.reasoning_summary = (
                    f"{ranking.reasoning_summary} BOBA consulted "
                    f"{len(application.memory_used)} local memory record(s); "
                    "only bounded advisory adjustments were allowed."
                )[:800]
        self.store.save_candidate_ranking(ranking)
        return ranking

    async def _autopilot_context(self, project_id: str) -> dict[str, Any]:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        manifest_resolution = await resolve_render_manifest(self.storage, project_id)
        manifest = manifest_resolution.manifest or {}
        accepted_output_ids = [
            str(item.get("clip_id") or item.get("storage_key") or "")
            for item in _list(manifest.get("renders"))
            if isinstance(item, dict)
        ]
        return {
            "current_workflow_stage": project.status.value,
            "accepted_output_ids": [
                item for item in accepted_output_ids if item
            ][:128],
            "source_media_references": [project.storage_key],
            "source_media_read_only": True,
            "rights_status": "unknown",
            "safety_status": "clear_for_local_analysis",
            "active_external_operations": [],
        }

    async def _invoke_autopilot_typed_module(
        self,
        module_name: str,
        operation_name: str,
        parameters: Any,
    ) -> dict[str, Any]:
        values = dict(parameters) if isinstance(parameters, dict) else {}
        project_id = str(values.get("project_id") or "")
        if not project_id:
            raise ValidationError("Autopilot typed invocation requires a project id.")
        result: object
        if module_name == "observer" and operation_name == "generate":
            result = await self.generate_observer_report(project_id)
        elif module_name == "error_doctor" and operation_name == "generate":
            result = await self.generate_boba_error_doctor(project_id)
        elif module_name == "root_cause_analyzer" and operation_name == "generate":
            result = await self.generate_boba_root_cause_analyzer(project_id)
        elif module_name == "repair_planner" and operation_name == "generate":
            result = await self.generate_boba_repair_planner(project_id)
        elif module_name == "code_surgeon" and operation_name in {
            "proposal_only",
            "validate_proposal",
        }:
            call = (
                self.validate_boba_code_surgeon_patch
                if operation_name == "validate_proposal"
                else self.generate_boba_code_surgeon_proposal
            )
            result = await call(
                project_id,
                repair_case_id=str(values.get("repair_case_id") or "") or None,
                repair_strategy_id=(
                    str(values.get("repair_strategy_id") or "") or None
                ),
                unified_diff=str(values.get("unified_diff") or "") or None,
            )
        elif module_name == "code_surgeon" and operation_name == "execute_approved":
            approval = values.get("approval")
            if not isinstance(approval, BobaCodeApprovalRecordV1):
                raise ValidationError("Exact Code Surgeon approval is required.")
            result = await self.execute_approved_boba_code_surgeon_patch(
                project_id,
                patch_proposal_id=str(values.get("patch_proposal_id") or ""),
                approval=approval,
                approved_validation_commands=[
                    str(item)
                    for item in values.get("approved_validation_commands") or []
                ],
            )
        elif module_name == "code_surgeon" and operation_name == "prepare_local_commit":
            approval = values.get("approval")
            if not isinstance(approval, BobaCodeApprovalRecordV1):
                raise ValidationError("Exact Code Surgeon approval is required.")
            result = await self.prepare_boba_code_surgeon_local_commit(
                project_id,
                isolated_run_id=str(values.get("isolated_run_id") or ""),
                approval=approval,
            )
        elif module_name == "tool_recovery_brain" and operation_name == "plan":
            result = await self.generate_boba_tool_recovery_plan(
                project_id,
                selected_handoff_id=(
                    str(values.get("selected_handoff_id") or "") or None
                ),
                selected_repair_strategy_id=(
                    str(values.get("selected_repair_strategy_id") or "") or None
                ),
            )
        elif module_name == "tool_recovery_brain" and operation_name == "health_check":
            result = await self.run_boba_tool_health_checks(
                project_id,
                tool_ids=[str(item) for item in values.get("tool_ids") or []] or None,
            )
        elif module_name == "tool_recovery_brain" and operation_name == "execute_approved":
            approval = values.get("approval")
            if not isinstance(approval, BobaToolRecoveryApprovalV1):
                raise ValidationError("Exact Tool Recovery approval is required.")
            result = await self.execute_approved_boba_tool_recovery(
                project_id,
                recovery_plan_id=str(values.get("recovery_plan_id") or ""),
                recovery_strategy_id=str(
                    values.get("recovery_strategy_id") or ""
                ),
                approval=approval,
            )
        elif module_name == "tool_recovery_brain" and operation_name == "validate_output":
            result = await self.validate_boba_recovered_output(
                project_id,
                recovery_attempt_id=str(values.get("recovery_attempt_id") or ""),
            )
        elif module_name == "tool_recovery_brain" and operation_name == "rollback":
            result = await self.rollback_boba_tool_recovery(
                project_id,
                recovery_attempt_id=str(values.get("recovery_attempt_id") or ""),
                trigger=str(
                    values.get("rollback_trigger")
                    or "Autopilot coordinated approved rollback."
                ),
            )
        elif (
            module_name == "output_quality_reviewer"
            and operation_name == "artifact_review"
        ):
            result = await self.generate_boba_output_quality_review(
                project_id,
                output_reference=str(values.get("output_reference") or ""),
                review_mode="artifact_only",
                rights_status=str(values.get("rights_status") or "unknown"),
                safety_status=str(values.get("safety_status") or "unknown"),
            )
        elif (
            module_name == "output_quality_reviewer"
            and operation_name == "technical_review"
        ):
            result = await self.run_boba_output_technical_review(
                project_id,
                output_reference=str(values.get("output_reference") or ""),
                rights_status=str(values.get("rights_status") or "unknown"),
                safety_status=str(values.get("safety_status") or "unknown"),
            )
        elif (
            module_name == "output_quality_reviewer"
            and operation_name == "baseline_compare"
        ):
            result = await self.compare_boba_output_quality_baseline(
                project_id,
                output_reference=str(values.get("output_reference") or ""),
                baseline_reference=str(values.get("baseline_reference") or ""),
                rights_status=str(values.get("rights_status") or "unknown"),
                safety_status=str(values.get("safety_status") or "unknown"),
            )
        else:
            raise ValidationError(
                "Autopilot rejected an arbitrary module or operation.",
                details={
                    "module_name": module_name,
                    "operation_name": operation_name,
                },
            )
        return self._model_payload(result)

    async def create_boba_autopilot_run(
        self,
        project_id: str,
        *,
        control_mode: BobaAutopilotControlModeV1 = "safe_read_only_automatic",
        trigger: BobaAutopilotTriggerV1 = "manual",
        source_event_id: str | None = None,
        recovery_budget: dict[str, Any] | None = None,
    ) -> BobaAutopilotControllerSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        return await self.autopilot_controller.create_run(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            control_mode=control_mode,
            trigger=trigger,
            source_event_id=source_event_id,
            recovery_budget=recovery_budget,
        )

    def inspect_boba_autopilot_run(
        self,
        project_id: str,
        run_id: str,
    ) -> BobaAutopilotControllerSetV1:
        return self.autopilot_controller.inspect_run(project_id, run_id)

    async def plan_boba_autopilot_next_action(
        self,
        project_id: str,
        run_id: str,
    ) -> BobaAutopilotActionV1:
        return await self.autopilot_controller.plan_next_action(project_id, run_id)

    async def advance_boba_autopilot_safe_read_only(
        self,
        project_id: str,
        run_id: str,
        *,
        maximum_steps: int = 12,
    ) -> BobaAutopilotControllerSetV1:
        return await self.autopilot_controller.advance_safe_read_only(
            project_id,
            run_id,
            maximum_steps=maximum_steps,
        )

    async def coordinate_approved_boba_autopilot_action(
        self,
        project_id: str,
        run_id: str,
        *,
        action_id: str,
        approval_record: dict[str, Any],
        safety_decision_id: str,
    ) -> BobaAutopilotControllerSetV1:
        return await self.autopilot_controller.coordinate_approved_action(
            project_id,
            run_id,
            action_id=action_id,
            approval_record=approval_record,
            safety_decision_id=safety_decision_id,
        )

    def pause_boba_autopilot_run(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str = "Human requested a controller pause.",
    ) -> BobaAutopilotControllerSetV1:
        return self.autopilot_controller.pause_run(
            project_id,
            run_id,
            reason=reason,
        )

    def continue_boba_autopilot_run(
        self,
        project_id: str,
        run_id: str,
    ) -> BobaAutopilotControllerSetV1:
        return self.autopilot_controller.continue_run(project_id, run_id)

    def cancel_boba_autopilot_run(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str = "Human cancelled future Autopilot actions.",
    ) -> BobaAutopilotControllerSetV1:
        return self.autopilot_controller.cancel_run(
            project_id,
            run_id,
            reason=reason,
        )

    def record_boba_autopilot_human_decision(
        self,
        project_id: str,
        run_id: str,
        **kwargs: Any,
    ) -> BobaAutopilotControllerSetV1:
        return self.autopilot_controller.record_human_decision(
            project_id,
            run_id,
            **kwargs,
        )

    def request_boba_autopilot_budget_reset(
        self,
        project_id: str,
        run_id: str,
        *,
        reason: str,
    ) -> BobaAutopilotControllerSetV1:
        return self.autopilot_controller.request_budget_reset(
            project_id,
            run_id,
            reason=reason,
        )

    def load_boba_autopilot_controller(
        self,
        project_id: str,
    ) -> BobaAutopilotControllerSetV1 | None:
        return self.store.load_boba_autopilot_controller(project_id)

    def export_boba_autopilot_controller(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.store.export_boba_autopilot_controller(project_id)

    def export_boba_autopilot_run(
        self,
        project_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        return self.autopilot_controller.export_run(project_id, run_id)

    def reset_boba_autopilot_controller(self, project_id: str) -> bool:
        return self.autopilot_controller.reset_run_metadata(project_id)

    async def create_boba_safety_policy_snapshot(
        self,
        project_id: str,
        *,
        project_policy: dict[str, Any] | None = None,
    ) -> BobaSafetyGateSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        return self.safety_gate.create_policy_snapshot(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            project_policy=project_policy,
        )

    async def create_boba_safety_action_request(
        self,
        project_id: str,
        **kwargs: Any,
    ) -> BobaSafetyActionRequestV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        return self.safety_gate.create_action_request(project_id, **kwargs)

    async def evaluate_boba_safety_action(
        self,
        project_id: str,
        action_request_id: str,
        *,
        approval_record: dict[str, Any] | None = None,
    ) -> BobaSafetyDecisionV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        return self.safety_gate.evaluate_action(
            project_id,
            action_request_id,
            approval_record=approval_record,
        )

    def inspect_boba_safety_evaluation(
        self,
        project_id: str,
        case_id: str,
    ) -> BobaSafetyEvaluationCaseV1:
        case = self.store.load_boba_safety_evaluation(project_id, case_id)
        if case is None:
            raise NotFoundError(
                "BOBA Safety Gate evaluation was not found.",
                details={"case_id": case_id},
            )
        return case

    def inspect_boba_safety_decision(
        self,
        project_id: str,
        decision_id: str,
    ) -> BobaSafetyDecisionV1:
        return self.safety_gate.inspect_decision(project_id, decision_id)

    def revalidate_boba_safety_decision(
        self,
        project_id: str,
        decision_id: str,
        *,
        approval_record: dict[str, Any] | None = None,
        current_bindings: dict[str, Any] | None = None,
    ) -> BobaSafetyDecisionV1:
        return self.safety_gate.revalidate_decision(
            project_id,
            decision_id,
            approval_record=approval_record,
            current_bindings=current_bindings,
        )

    def invalidate_boba_safety_decision(
        self,
        project_id: str,
        decision_id: str,
        *,
        reason: str,
        changes: dict[str, bool] | None = None,
    ) -> BobaSafetyDecisionInvalidationV1:
        return self.safety_gate.invalidate_decision(
            project_id,
            decision_id,
            reason=reason,
            changes=changes,
        )

    def record_boba_human_safety_review(
        self,
        project_id: str,
        case_id: str,
        **kwargs: Any,
    ) -> BobaSafetyDecisionV1:
        return self.safety_gate.record_human_safety_review(
            project_id,
            case_id,
            **kwargs,
        )

    def load_boba_safety_gate(
        self,
        project_id: str,
    ) -> BobaSafetyGateSetV1 | None:
        return self.store.load_boba_safety_gate(project_id)

    def export_boba_safety_gate(self, project_id: str) -> dict[str, Any]:
        return self.safety_gate.export_safety_gate(project_id)

    def reset_boba_safety_gate(self, project_id: str) -> bool:
        return self.safety_gate.reset_safety_gate_metadata(project_id)

    async def generate_boba_for_clip(
        self, project_id: str, clip_id: str
    ) -> BobaEditorialPolicyV1:
        signals = await self.collect_clip_signals(project_id, clip_id)
        clip = _dict(signals.get("clip"))
        policy = create_editorial_policy(
            project_id,
            clip_id,
            clip,
            {
                "content_niche": signals.get("content_niche"),
                "transcript_available": signals.get("transcript_available"),
                "face_layout_available": signals.get("face_signals_available"),
                "music_available": True,
                "safety_status": signals.get("safety_status"),
                "manual_review_required": signals.get("safety_manual_review_required"),
            },
        )
        memory_application = None
        if self.memory_enabled:
            self._ensure_global_memory()
            if self.store.load_project_memory(project_id) is None:
                build_and_save_project_memory(
                    self.store,
                    project_id,
                    signals,
                    decisions=self.store.list_decisions(project_id),
                )
            creator_profile_id = (
                str(_dict(signals.get("creator_profile")).get("profile_id") or "")
                or None
            )
            retrieval = retrieve_for_editorial_policy(
                self.store, project_id, clip_id, creator_profile_id
            )
            memory_application = create_memory_application(
                project_id,
                "editorial_policy",
                retrieval,
                clip_id=clip_id,
            )
            policy.memory_application_v1 = memory_application
            if any(
                item.get("field") == "ending_hold_advisory"
                for item in memory_application.adjustments
            ):
                policy.ending_directives = {
                    **policy.ending_directives,
                    "memory_advisory": "preserve_payoff_tail",
                }
        self.store.save_editorial_policy(policy)
        explanation = explain_clip_selection(
            {
                **clip,
                "hook_strength": _dict(clip.get("scores")).get("hook"),
                "story_completeness": _dict(clip.get("scores")).get("story_completion"),
                "payoff_strength": _dict(clip.get("scores")).get("payoff"),
            },
            {
                "missing_signals": self.brain.assess_source_understanding(
                    project_id, signals
                ).missing_signals
            },
        )
        decision = BobaDecisionV1(
            decision_id=new_id("decision"),
            project_id=project_id,
            clip_id=clip_id,
            decision_type="editing_policy",
            question="How should this selected clip be edited?",
            answer=policy.explanation,
            confidence=policy.confidence,
            input_signals={
                "planning": clip,
                "story": _dict(signals.get("story_analysis_v2")),
                "virality": _dict(signals.get("virality_summary")),
                "safety": _dict(signals.get("safety")),
            },
            reasoning=BobaReasoningV1.model_validate(
                {key: value for key, value in explanation.items() if key != "confidence"}
            ),
            output_directive={
                "target_system": "editing",
                "directive_type": "editorial_policy_advisory",
                "parameters": policy.model_dump(mode="json"),
                "priority": 60,
                "constraints": policy.safety_constraints,
            },
            memory_application_v1=memory_application,
        )
        self.bus.register_decision(project_id, decision)
        return policy

    def attach_boba_to_unified_clip_intelligence(
        self,
        project_id: str,
        clip_id: str,
        unified: dict[str, Any],
    ) -> dict[str, Any]:
        brain = self.store.load_brain_state(project_id)
        ranking = self.store.load_candidate_ranking(project_id)
        policy = self.store.load_editorial_policy(project_id, clip_id)
        return {
            **unified,
            "boba": compact_boba_summary(
                brain=brain.model_dump(mode="json") if brain else None,
                ranking=ranking.model_dump(mode="json") if ranking else None,
                policy=policy.model_dump(mode="json") if policy else None,
            ),
        }
