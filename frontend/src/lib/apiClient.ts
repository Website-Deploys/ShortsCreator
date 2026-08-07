/**
 * Typed HTTP client for the Olympus backend.
 *
 * A thin wrapper around `fetch` that prefixes the versioned API base URL, parses
 * JSON, and normalises the backend's `{ error: { code, message } }` envelope
 * into a thrown `ApiClientError`. All endpoints here are real and implemented on
 * the backend.
 */

import { API_V1 } from "@/lib/config";
import type {
  CandidateActionDescriptor,
  CandidateActionReceipt,
  CandidateOverlapRecord,
  CandidateQueueItem,
  CandidateReference,
  CandidateScoreCard,
  CandidateSnapshot,
} from "@/lib/candidateReview";
import type {
  RepairApprovalRequirement,
  RepairEvidenceCard,
  RepairPlanActionDescriptor,
  RepairPlanActionReceipt,
  RepairPlanConflict,
  RepairPlanQueueItem,
  RepairPlanReference,
  RepairPlanSnapshot,
  RepairRecoveryLink,
  RepairRiskProjection,
  RepairStepProjection,
  RepairVerificationRequirement,
} from "@/lib/repairPlanReview";
import type {
  DiagnosisProjection,
  ErrorConflict,
  ErrorDoctorActionDescriptor,
  ErrorDoctorActionReceipt,
  ErrorEvidenceCard,
  IncidentQueueItem,
  IncidentReference,
  IncidentSnapshot,
  RecoveryAttemptProjection,
  RepairPlanProjection,
  RootCauseProjection,
} from "@/lib/errorDoctorReview";
import type {
  ClipBriefActionDescriptor,
  ClipBriefActionReceipt,
  ClipBriefComparison,
  ClipBriefCompleteness,
  ClipBriefConflict,
  ClipBriefEvidenceLink,
  ClipBriefFieldProjection,
  ClipBriefQueueItem,
  ClipBriefReference,
  ClipBriefSectionProjection,
  ClipBriefSnapshot,
  ClipBriefSourceCard,
} from "@/lib/clipBriefReview";
import type {
  ReviewActionReceipt,
  ReviewEvent,
  ReviewQueueItem,
  ReviewSnapshot,
  ReviewSourceCard,
} from "@/lib/reviewUi";
import type {
  ActivityFeedResponse,
  Analysis,
  ApiError,
  AssetsResponse,
  CleanupResultResponse,
  ClipsResponse,
  CreateProjectInput,
  CreatorPersonalizationSummary,
  CreatorProfileExportResponse,
  CreatorProfileV2,
  CreatorProfilesResponse,
  DurableJob,
  DurableJobListResponse,
  ClipFeedbackInput,
  ClipFeedbackV2,
  CreateProjectFromLinkInput,
  CreateProjectFromLinkResponse,
  Editing,
  ExportsResponse,
  LibraryDashboard,
  LibraryMetaResponse,
  LibraryVersion,
  MusicRecommendations,
  Optimization,
  PackageList,
  PackageResponse,
  PlanList,
  Planning,
  PlanningSummary,
  PlanResponse,
  Project,
  QualityReport,
  RenderLogs,
  RenderManifestResponse,
  RenderRun,
  RenderValidation,
  SchedulerStatus,
  SearchResponse,
  StorageResponse,
  Story,
  StorySummary,
  SystemInfo,
  TrendResearchResponse,
  Timeline,
  TimelineEvent,
  TimelineList,
  ValidationReport,
  VariantList,
  VersionEnginesResponse,
  VersionsResponse,
  Virality,
  ViralitySummary,
  Workflow,
  WorkflowHistoryResponse,
  WorkersResponse,
  JobLogsResponse,
  AdminSnapshot,
  AlertsResponse,
  AuditResponse,
  BobaApprovalRejectionLearningSetV1,
  BobaAutopilotControllerSetV1,
  BobaAutopilotCoordinateInputV1,
  BobaAutopilotCreateRunInputV1,
  BobaAutopilotHumanDecisionInputV1,
  BobaBrainStateV1,
  BobaIntegrationLayerSetV1,
  BobaCaptionMotionRecommendationSetV1,
  BobaCandidateClipDiscoveryV1,
  BobaCodeSurgeonCommitInputV1,
  BobaCodeSurgeonExecuteInputV1,
  BobaCodeSurgeonProposalInputV1,
  BobaCodeSurgeonSetV1,
  BobaToolRecoveryBrainSetV1,
  BobaToolRecoveryExecuteInputV1,
  BobaToolRecoveryHealthInputV1,
  BobaToolRecoveryPlanInputV1,
  BobaToolRecoveryRollbackInputV1,
  BobaToolRecoveryValidationInputV1,
  BobaOutputHumanReviewInputV1,
  BobaOutputQualityCompareInputV1,
  BobaOutputQualityReviewerSetV1,
  BobaOutputQualityReviewInputV1,
  BobaCandidateVideoScorerGenerateInputV1,
  BobaCandidateVideoScorerSetV1,
  BobaErrorDoctorGenerateInputV1,
  BobaErrorDoctorSetV1,
  BobaObserverGenerateInputV1,
  BobaObserverSetV1,
  BobaRepairPlannerGenerateInputV1,
  BobaRepairPlannerSetV1,
  BobaRootCauseAnalyzerGenerateInputV1,
  BobaRootCauseAnalyzerSetV1,
  BobaRightsPermissionGateGenerateInputV1,
  BobaRightsPermissionGateSetV1,
  BobaSafetyActionInputV1,
  BobaSafetyActionRequestV1,
  BobaSafetyDecisionV1,
  BobaSafetyEvaluationCaseV1,
  BobaSafetyGateSetV1,
  BobaSafetyHumanReviewInputV1,
  BobaSafetyPolicySnapshotV1,
  BobaWorkflowAdvanceInputV1,
  BobaWorkflowControllerSetV1,
  BobaWorkflowCoordinateInputV1,
  BobaWorkflowCreateRunInputV1,
  BobaWorkflowDefinitionSnapshotV1,
  BobaWorkflowEventV1,
  BobaWorkflowHumanDecisionInputV1,
  BobaWorkflowHumanDecisionV1,
  BobaWorkflowNextStagePlanV1,
  BobaWorkflowPauseInputV1,
  BobaWorkflowPauseRecordV1,
  BobaWorkflowRecoveryHoldInputV1,
  BobaWorkflowRecoveryHoldV1,
  BobaWorkflowResumeEligibilityInputV1,
  BobaWorkflowResumeEligibilityReviewV1,
  BobaWorkflowRunInspectionV1,
  BobaWorkflowRunV1,
  BobaWorkflowTransitionCreateInputV1,
  BobaWorkflowTransitionDecisionV1,
  BobaWorkflowTransitionEvaluateInputV1,
  BobaWorkflowTransitionRequestV1,
  BobaIntegrationResponseV1,
  BobaCandidateV1,
  BobaCandidatesResponse,
  BobaClipBriefSetV1,
  BobaClipRankingV1,
  BobaContentScoutGenerateInputV2,
  BobaContentScoutSetV2,
  BobaCreativeBriefsResponse,
  BobaCreativeDirectionSetV2,
  BobaCreatorFeedbackEventInput,
  BobaCreatorFeedbackEventV1,
  BobaCreatorLearningSetV1,
  BobaCreatorMemoryV1,
  BobaEditorialDecisionSetV1,
  BobaExplanationSetV1,
  BobaExperimentationSetV1,
  BobaExperimentManualResultV1,
  BobaGlobalMemoryV1,
  BobaHookRetentionSetV1,
  BobaMusicMoodRecommendationSetV1,
  BobaPerformanceFeedbackEventInput,
  BobaPerformanceFeedbackEventResponse,
  BobaPerformanceFeedbackSetV1,
  BobaProjectMemoryV1,
  BobaResearchBrainGenerateInputV1,
  BobaResearchBrainSetV1,
  BobaScoutScoreV1,
  BobaTrendTopicWatcherGenerateInputV1,
  BobaTrendTopicWatcherSetV1,
  BobaWholeVideoUnderstandingV1,
  CostEstimate,
  EnginesResponse,
  FailuresResponse,
  MonitoringHealthResponse,
  QueueSnapshot,
  StorageAnalytics,
  SystemMetrics,
  UsageStats,
  WorkflowAnalytics,
} from "@/lib/types";

/** Error thrown when the API returns a non-2xx response. */
export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;

  constructor(message: string, code: string, status: number, requestId?: string) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_V1}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiClientError(
      "Could not reach Olympus. Please check your connection.",
      "network_error",
      0,
    );
  }

  if (!response.ok) {
    let body: ApiError | undefined;
    try {
      body = (await response.json()) as ApiError;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiClientError(
      body?.error.message ?? `Request failed (${response.status}).`,
      body?.error.code ?? "http_error",
      response.status,
      body?.request_id,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Build a query string from defined params (skips undefined/empty values). */
function _qs(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const str = search.toString();
  return str ? `?${str}` : "";
}

export const api = {
  getSystemInfo: () => request<SystemInfo>("/system/info"),

  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  getBobaBrain: (id: string) =>
    request<BobaBrainStateV1>(`/boba/projects/${id}/brain`),
  getBobaProjectMemory: (id: string) =>
    request<BobaProjectMemoryV1>(`/boba/memory/projects/${id}`),
  getBobaCreatorMemory: (profileId: string) =>
    request<BobaCreatorMemoryV1>(`/boba/memory/creators/${profileId}`),
  getBobaGlobalMemory: () => request<BobaGlobalMemoryV1>("/boba/memory/global"),
  getBobaCandidates: () => request<BobaCandidatesResponse>("/boba/candidates"),
  getBobaContentScoutV2: (projectId: string) =>
    request<BobaContentScoutSetV2>(
      `/boba/projects/${projectId}/content-scout-v2`,
    ),
  generateBobaContentScoutV2: (
    projectId: string,
    input: BobaContentScoutGenerateInputV2 = {},
  ) =>
    request<BobaContentScoutSetV2>(
      `/boba/projects/${projectId}/content-scout-v2`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaContentScoutV2: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/content-scout-v2/export`,
    ),
  resetBobaContentScoutV2: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      content_scout_v2_removed: boolean;
      scout_v1_removed: false;
      creator_learning_removed: false;
      performance_feedback_removed: false;
      memory_removed: false;
    }>(`/boba/projects/${projectId}/content-scout-v2`, {
      method: "DELETE",
    }),
  getBobaResearchBrain: (projectId: string) =>
    request<BobaResearchBrainSetV1>(
      `/boba/projects/${projectId}/research-brain`,
    ),
  generateBobaResearchBrain: (
    projectId: string,
    input: BobaResearchBrainGenerateInputV1 = {},
  ) =>
    request<BobaResearchBrainSetV1>(
      `/boba/projects/${projectId}/research-brain`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaResearchBrain: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/research-brain/export`,
    ),
  resetBobaResearchBrain: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      research_brain_removed: boolean;
      content_scout_removed: false;
      creator_learning_removed: false;
      approval_rejection_learning_removed: false;
      performance_feedback_removed: false;
      memory_removed: false;
    }>(`/boba/projects/${projectId}/research-brain`, {
      method: "DELETE",
    }),
  getBobaTrendTopicWatcher: (projectId: string) =>
    request<BobaTrendTopicWatcherSetV1>(
      `/boba/projects/${projectId}/trend-topic-watcher`,
    ),
  generateBobaTrendTopicWatcher: (
    projectId: string,
    input: BobaTrendTopicWatcherGenerateInputV1 = {},
  ) =>
    request<BobaTrendTopicWatcherSetV1>(
      `/boba/projects/${projectId}/trend-topic-watcher`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaTrendTopicWatcher: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/trend-topic-watcher/export`,
    ),
  resetBobaTrendTopicWatcher: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      trend_topic_watcher_removed: boolean;
      research_brain_removed: false;
      content_scout_removed: false;
      creator_learning_removed: false;
      performance_feedback_removed: false;
      memory_removed: false;
    }>(`/boba/projects/${projectId}/trend-topic-watcher`, {
      method: "DELETE",
    }),
  getBobaCandidateVideoScorer: (projectId: string) =>
    request<BobaCandidateVideoScorerSetV1>(
      `/boba/projects/${projectId}/candidate-video-scorer`,
    ),
  generateBobaCandidateVideoScorer: (
    projectId: string,
    input: BobaCandidateVideoScorerGenerateInputV1 = {},
  ) =>
    request<BobaCandidateVideoScorerSetV1>(
      `/boba/projects/${projectId}/candidate-video-scorer`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaCandidateVideoScorer: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/candidate-video-scorer/export`,
    ),
  resetBobaCandidateVideoScorer: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      candidate_video_scorer_removed: boolean;
      trend_topic_watcher_removed: false;
      research_brain_removed: false;
      content_scout_removed: false;
      creator_learning_removed: false;
      approval_rejection_learning_removed: false;
      performance_feedback_removed: false;
      memory_removed: false;
      media_ingested: false;
    }>(`/boba/projects/${projectId}/candidate-video-scorer`, {
      method: "DELETE",
    }),
  getBobaRightsPermissionGate: (projectId: string) =>
    request<BobaRightsPermissionGateSetV1>(
      `/boba/projects/${projectId}/rights-permission-gate`,
    ),
  generateBobaRightsPermissionGate: (
    projectId: string,
    input: BobaRightsPermissionGateGenerateInputV1 = {},
  ) =>
    request<BobaRightsPermissionGateSetV1>(
      `/boba/projects/${projectId}/rights-permission-gate`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaRightsPermissionGate: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/rights-permission-gate/export`,
    ),
  resetBobaRightsPermissionGate: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      rights_permission_gate_removed: boolean;
      candidate_video_scorer_removed: false;
      trend_topic_watcher_removed: false;
      research_brain_removed: false;
      content_scout_removed: false;
      clip_briefs_removed: false;
      music_mood_removed: false;
      memory_removed: false;
      media_ingested: false;
      legal_validation_used: false;
    }>(`/boba/projects/${projectId}/rights-permission-gate`, {
      method: "DELETE",
    }),
  getBobaObserver: (projectId: string) =>
    request<BobaObserverSetV1>(`/boba/projects/${projectId}/observer`),
  generateBobaObserver: (
    projectId: string,
    input: BobaObserverGenerateInputV1 = {},
  ) =>
    request<BobaObserverSetV1>(`/boba/projects/${projectId}/observer`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  exportBobaObserver: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/observer/export`,
    ),
  resetBobaObserver: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      observer_removed: boolean;
      other_boba_artifacts_removed: false;
      unrelated_files_deleted: false;
      validators_executed: false;
      commands_executed: false;
      code_modified: false;
      media_downloaded: false;
      media_ingested: false;
      rendering_triggered: false;
    }>(`/boba/projects/${projectId}/observer`, {
      method: "DELETE",
    }),
  getBobaErrorDoctor: (projectId: string) =>
    request<BobaErrorDoctorSetV1>(
      `/boba/projects/${projectId}/error-doctor`,
    ),
  generateBobaErrorDoctor: (
    projectId: string,
    input: BobaErrorDoctorGenerateInputV1 = {},
  ) =>
    request<BobaErrorDoctorSetV1>(
      `/boba/projects/${projectId}/error-doctor`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  exportBobaErrorDoctor: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor/export`,
    ),
  resetBobaErrorDoctor: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      error_doctor_removed: boolean;
      observer_removed: false;
      other_boba_artifacts_removed: false;
      unrelated_files_deleted: false;
      validators_executed: false;
      commands_executed: false;
      code_modified: false;
      artifacts_modified: false;
      media_downloaded: false;
      media_ingested: false;
      rendering_triggered: false;
      repairs_applied: false;
    }>(`/boba/projects/${projectId}/error-doctor`, {
      method: "DELETE",
    }),
  getBobaRootCauseAnalyzer: (projectId: string) =>
    request<BobaRootCauseAnalyzerSetV1>(
      `/boba/projects/${projectId}/root-cause-analyzer`,
    ),
  generateBobaRootCauseAnalyzer: (
    projectId: string,
    input: BobaRootCauseAnalyzerGenerateInputV1 = {},
  ) =>
    request<BobaRootCauseAnalyzerSetV1>(
      `/boba/projects/${projectId}/root-cause-analyzer`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  exportBobaRootCauseAnalyzer: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/root-cause-analyzer/export`,
    ),
  resetBobaRootCauseAnalyzer: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      root_cause_analyzer_removed: boolean;
      error_doctor_removed: false;
      observer_removed: false;
      other_boba_artifacts_removed: false;
      unrelated_files_deleted: false;
      validators_executed: false;
      commands_executed: false;
      code_modified: false;
      artifacts_modified: false;
      media_downloaded: false;
      media_ingested: false;
      rendering_triggered: false;
      repairs_applied: false;
      fallback_tools_executed: false;
      workflow_resume_authorized: false;
    }>(`/boba/projects/${projectId}/root-cause-analyzer`, {
      method: "DELETE",
    }),
  getBobaRepairPlanner: (projectId: string) =>
    request<BobaRepairPlannerSetV1>(
      `/boba/projects/${projectId}/repair-planner`,
    ),
  generateBobaRepairPlanner: (
    projectId: string,
    input: BobaRepairPlannerGenerateInputV1 = {},
  ) =>
    request<BobaRepairPlannerSetV1>(
      `/boba/projects/${projectId}/repair-planner`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  exportBobaRepairPlanner: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-planner/export`,
    ),
  resetBobaRepairPlanner: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      repair_planner_removed: boolean;
      root_cause_analyzer_removed: false;
      error_doctor_removed: false;
      observer_removed: false;
      other_boba_artifacts_removed: false;
      unrelated_files_deleted: false;
      validators_executed: false;
      commands_executed: false;
      code_modified: false;
      artifacts_modified: false;
      media_downloaded: false;
      media_ingested: false;
      rendering_triggered: false;
      repairs_applied: false;
      fallback_tools_executed: false;
      workflow_resumed: false;
      services_restarted: false;
      packages_installed: false;
    }>(`/boba/projects/${projectId}/repair-planner`, {
      method: "DELETE",
    }),
  getBobaCodeSurgeon: (projectId: string) =>
    request<BobaCodeSurgeonSetV1>(
      `/boba/projects/${projectId}/code-surgeon`,
    ),
  proposeBobaCodeSurgeon: (
    projectId: string,
    input: BobaCodeSurgeonProposalInputV1,
  ) =>
    request<BobaCodeSurgeonSetV1>(
      `/boba/projects/${projectId}/code-surgeon/propose`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  validateBobaCodeSurgeonPatch: (
    projectId: string,
    input: BobaCodeSurgeonProposalInputV1,
  ) =>
    request<BobaCodeSurgeonSetV1>(
      `/boba/projects/${projectId}/code-surgeon/validate-patch`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  executeApprovedBobaCodeSurgeonPatch: (
    projectId: string,
    input: BobaCodeSurgeonExecuteInputV1,
  ) =>
    request<BobaCodeSurgeonSetV1>(
      `/boba/projects/${projectId}/code-surgeon/execute-approved`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  prepareBobaCodeSurgeonLocalCommit: (
    projectId: string,
    input: BobaCodeSurgeonCommitInputV1,
  ) =>
    request<BobaCodeSurgeonSetV1>(
      `/boba/projects/${projectId}/code-surgeon/prepare-local-commit`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  exportBobaCodeSurgeon: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/code-surgeon/export`,
    ),
  resetBobaCodeSurgeon: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      code_surgeon_removed: boolean;
      repair_planner_removed: false;
      root_cause_analyzer_removed: false;
      other_boba_artifacts_removed: false;
      source_code_deleted: false;
      isolated_worktree_deleted: false;
      branches_deleted: false;
      main_modified: false;
      push_used: false;
      remote_pr_created: false;
      merge_used: false;
      tag_used: false;
      deployment_used: false;
      package_installation_used: false;
      service_restart_used: false;
      destructive_git_used: false;
    }>(`/boba/projects/${projectId}/code-surgeon`, {
      method: "DELETE",
    }),
  getBobaToolRecovery: (projectId: string) =>
    request<BobaToolRecoveryBrainSetV1>(
      `/boba/projects/${projectId}/tool-recovery`,
    ),
  generateBobaToolRecoveryPlan: (
    projectId: string,
    input: BobaToolRecoveryPlanInputV1 = {},
  ) =>
    request<BobaToolRecoveryBrainSetV1>(
      `/boba/projects/${projectId}/tool-recovery/plan`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  runBobaToolRecoveryHealthChecks: (
    projectId: string,
    input: BobaToolRecoveryHealthInputV1 = {},
  ) =>
    request<BobaToolRecoveryBrainSetV1>(
      `/boba/projects/${projectId}/tool-recovery/health-check`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  executeApprovedBobaToolRecovery: (
    projectId: string,
    input: BobaToolRecoveryExecuteInputV1,
  ) =>
    request<BobaToolRecoveryBrainSetV1>(
      `/boba/projects/${projectId}/tool-recovery/execute-approved`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  validateBobaToolRecoveryOutput: (
    projectId: string,
    input: BobaToolRecoveryValidationInputV1,
  ) =>
    request<BobaToolRecoveryBrainSetV1>(
      `/boba/projects/${projectId}/tool-recovery/validate-output`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  rollbackBobaToolRecovery: (
    projectId: string,
    input: BobaToolRecoveryRollbackInputV1,
  ) =>
    request<BobaToolRecoveryBrainSetV1>(
      `/boba/projects/${projectId}/tool-recovery/rollback`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  exportBobaToolRecovery: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/tool-recovery/export`,
    ),
  resetBobaToolRecovery: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      tool_recovery_removed: boolean;
      repair_planner_removed: false;
      code_surgeon_removed: false;
      source_media_deleted: false;
      accepted_outputs_deleted: false;
      recovery_workspace_deleted: false;
      commands_executed: false;
      network_access_used: false;
      packages_installed: false;
      services_restarted: false;
      processes_killed: false;
      workflow_resumed: false;
      code_modified: false;
    }>(`/boba/projects/${projectId}/tool-recovery`, {
      method: "DELETE",
    }),
  getBobaOutputQualityReviewer: (projectId: string) =>
    request<BobaOutputQualityReviewerSetV1>(
      `/boba/projects/${projectId}/output-quality-reviewer`,
    ),
  reviewBobaOutputQuality: (
    projectId: string,
    input: BobaOutputQualityReviewInputV1,
  ) =>
    request<BobaOutputQualityReviewerSetV1>(
      `/boba/projects/${projectId}/output-quality-reviewer/review`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  compareBobaOutputQuality: (
    projectId: string,
    input: BobaOutputQualityCompareInputV1,
  ) =>
    request<BobaOutputQualityReviewerSetV1>(
      `/boba/projects/${projectId}/output-quality-reviewer/compare`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  recordBobaOutputHumanReview: (
    projectId: string,
    input: BobaOutputHumanReviewInputV1,
  ) =>
    request<BobaOutputQualityReviewerSetV1>(
      `/boba/projects/${projectId}/output-quality-reviewer/human-review`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  exportBobaOutputQualityReviewer: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/output-quality-reviewer/export`,
    ),
  resetBobaOutputQualityReviewer: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      output_quality_reviewer_removed: boolean;
      reviewed_output_deleted: false;
      source_media_deleted: false;
      tool_recovery_artifact_deleted: false;
      code_surgeon_artifact_deleted: false;
      render_manifest_deleted: false;
      sample_evidence_deleted: false;
      commands_executed: false;
      rendering_used: false;
      fallback_execution_used: false;
      workflow_resumed: false;
      network_access_used: false;
      uploading_used: false;
      publication_used: false;
      destructive_action_used: false;
    }>(`/boba/projects/${projectId}/output-quality-reviewer`, {
      method: "DELETE",
    }),
  createBobaWorkflowDefinition: (
    projectId: string,
    sourceId?: string,
  ) =>
    request<BobaWorkflowDefinitionSnapshotV1>(
      `/boba/projects/${projectId}/workflow-controller/definitions`,
      {
        method: "POST",
        body: JSON.stringify({ source_id: sourceId }),
      },
    ),
  getBobaWorkflowController: (projectId: string) =>
    request<BobaWorkflowControllerSetV1>(
      `/boba/projects/${projectId}/workflow-controller`,
    ),
  createBobaWorkflowRun: (
    projectId: string,
    input: BobaWorkflowCreateRunInputV1 = {},
  ) =>
    request<BobaWorkflowControllerSetV1>(
      `/boba/projects/${projectId}/workflow-controller/runs`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  getBobaWorkflowRun: (projectId: string, runId: string) =>
    request<BobaWorkflowRunInspectionV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}`,
    ),
  planBobaWorkflowNext: (projectId: string, runId: string) =>
    request<BobaWorkflowNextStagePlanV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/plan-next`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    ),
  createBobaWorkflowTransition: (
    projectId: string,
    runId: string,
    input: BobaWorkflowTransitionCreateInputV1,
  ) =>
    request<BobaWorkflowTransitionRequestV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/transitions`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  evaluateBobaWorkflowTransition: (
    projectId: string,
    runId: string,
    transitionId: string,
    input: BobaWorkflowTransitionEvaluateInputV1,
  ) =>
    request<BobaWorkflowTransitionDecisionV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/transitions/${transitionId}/evaluate`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  advanceBobaWorkflowSafe: (
    projectId: string,
    runId: string,
    input: BobaWorkflowAdvanceInputV1,
  ) =>
    request<BobaIntegrationResponseV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/advance-safe`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  coordinateBobaWorkflowApproved: (
    projectId: string,
    runId: string,
    input: BobaWorkflowCoordinateInputV1,
  ) =>
    request<BobaIntegrationResponseV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/coordinate-approved-transition`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  pauseBobaWorkflow: (
    projectId: string,
    runId: string,
    input: BobaWorkflowPauseInputV1,
  ) =>
    request<BobaWorkflowPauseRecordV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/pause`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  continueBobaWorkflowController: (
    projectId: string,
    runId: string,
    expectedRevision: number,
  ) =>
    request<BobaWorkflowRunV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/continue`,
      {
        method: "POST",
        body: JSON.stringify({ expected_revision: expectedRevision }),
      },
    ),
  cancelBobaWorkflow: (
    projectId: string,
    runId: string,
    expectedRevision: number,
    reason: string,
  ) =>
    request<BobaWorkflowRunV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/cancel`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_revision: expectedRevision,
          reason,
        }),
      },
    ),
  createBobaWorkflowRecoveryHold: (
    projectId: string,
    runId: string,
    input: BobaWorkflowRecoveryHoldInputV1,
  ) =>
    request<BobaWorkflowRecoveryHoldV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/recovery-holds`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  receiveBobaWorkflowRecoveryResult: (
    projectId: string,
    runId: string,
    expectedRevision: number,
    recoveryHoldId: string,
    recoveryResult: Record<string, unknown>,
  ) =>
    request<BobaWorkflowRecoveryHoldV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/recovery-result`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_revision: expectedRevision,
          recovery_hold_id: recoveryHoldId,
          recovery_result: recoveryResult,
        }),
      },
    ),
  evaluateBobaWorkflowResumeEligibility: (
    projectId: string,
    runId: string,
    input: BobaWorkflowResumeEligibilityInputV1,
  ) =>
    request<BobaWorkflowResumeEligibilityReviewV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/resume-eligibility`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  recordBobaWorkflowHumanDecision: (
    projectId: string,
    runId: string,
    input: BobaWorkflowHumanDecisionInputV1,
  ) =>
    request<BobaWorkflowHumanDecisionV1>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/human-decision`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  getBobaWorkflowEvents: (projectId: string, runId: string) =>
    request<{
      schema_version: "boba_workflow_event_stream_v1";
      project_id: string;
      run_id: string;
      events: BobaWorkflowEventV1[];
    }>(
      `/boba/projects/${projectId}/workflow-controller/runs/${runId}/events`,
    ),
  exportBobaWorkflowController: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/workflow-controller/export`,
    ),
  resetBobaWorkflowController: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/workflow-controller`,
      { method: "DELETE" },
    ),
  getBobaAutopilotController: (projectId: string) =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot`,
    ),
  createBobaAutopilotRun: (
    projectId: string,
    input: BobaAutopilotCreateRunInputV1 = {},
  ) =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  planBobaAutopilotNext: (projectId: string, runId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/plan-next`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    ),
  advanceBobaAutopilotSafe: (
    projectId: string,
    runId: string,
    maximumSteps = 12,
  ) =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/advance-safe`,
      {
        method: "POST",
        body: JSON.stringify({ maximum_steps: maximumSteps }),
      },
    ),
  coordinateBobaAutopilotApproved: (
    projectId: string,
    runId: string,
    input: BobaAutopilotCoordinateInputV1,
  ) =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/coordinate-approved`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  pauseBobaAutopilot: (projectId: string, runId: string, reason = "") =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/pause`,
      {
        method: "POST",
        body: JSON.stringify({ reason }),
      },
    ),
  continueBobaAutopilot: (projectId: string, runId: string) =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/continue`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    ),
  cancelBobaAutopilot: (projectId: string, runId: string, reason = "") =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/cancel`,
      {
        method: "POST",
        body: JSON.stringify({ reason }),
      },
    ),
  recordBobaAutopilotHumanDecision: (
    projectId: string,
    runId: string,
    input: BobaAutopilotHumanDecisionInputV1,
  ) =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/human-decision`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  requestBobaAutopilotBudgetReset: (
    projectId: string,
    runId: string,
    reason: string,
  ) =>
    request<BobaAutopilotControllerSetV1>(
      `/boba/projects/${projectId}/autopilot/runs/${runId}/budget-reset-request`,
      {
        method: "POST",
        body: JSON.stringify({ reason }),
      },
    ),
  exportBobaAutopilot: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/autopilot/export`,
    ),
  resetBobaAutopilot: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      autopilot_metadata_removed: boolean;
      upstream_boba_artifacts_deleted: false;
      source_media_deleted: false;
      accepted_outputs_deleted: false;
      code_surgeon_worktrees_deleted: false;
      tool_recovery_workspaces_deleted: false;
      checkpoints_deleted: false;
      workflow_resumed: false;
      publication_used: false;
    }>(`/boba/projects/${projectId}/autopilot`, {
      method: "DELETE",
    }),
  getBobaSafetyGate: (projectId: string) =>
    request<BobaSafetyGateSetV1>(
      `/boba/projects/${projectId}/safety-gate`,
    ),
  createBobaSafetyPolicy: (
    projectId: string,
    projectPolicy: Record<string, unknown> = {},
  ) =>
    request<BobaSafetyPolicySnapshotV1>(
      `/boba/projects/${projectId}/safety-gate/policies`,
      {
        method: "POST",
        body: JSON.stringify({ project_policy: projectPolicy }),
      },
    ),
  createBobaSafetyRequest: (
    projectId: string,
    input: BobaSafetyActionInputV1,
  ) =>
    request<BobaSafetyActionRequestV1>(
      `/boba/projects/${projectId}/safety-gate/requests`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  evaluateBobaSafetyRequest: (
    projectId: string,
    actionRequestId: string,
    approvalRecord?: Record<string, unknown>,
  ) =>
    request<BobaSafetyDecisionV1>(
      `/boba/projects/${projectId}/safety-gate/evaluate`,
      {
        method: "POST",
        body: JSON.stringify({
          action_request_id: actionRequestId,
          approval_record: approvalRecord,
        }),
      },
    ),
  revalidateBobaSafetyDecision: (
    projectId: string,
    decisionId: string,
    approvalRecord?: Record<string, unknown>,
    currentBindings: Record<string, unknown> = {},
  ) =>
    request<BobaSafetyDecisionV1>(
      `/boba/projects/${projectId}/safety-gate/decisions/${decisionId}/revalidate`,
      {
        method: "POST",
        body: JSON.stringify({
          approval_record: approvalRecord,
          current_bindings: currentBindings,
        }),
      },
    ),
  invalidateBobaSafetyDecision: (
    projectId: string,
    decisionId: string,
    reason: string,
  ) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/safety-gate/decisions/${decisionId}/invalidate`,
      {
        method: "POST",
        body: JSON.stringify({ reason, changes: {} }),
      },
    ),
  recordBobaSafetyHumanReview: (
    projectId: string,
    caseId: string,
    input: BobaSafetyHumanReviewInputV1,
  ) =>
    request<BobaSafetyDecisionV1>(
      `/boba/projects/${projectId}/safety-gate/evaluations/${caseId}/human-review`,
      {
        method: "POST",
        body: JSON.stringify(input),
      },
    ),
  getBobaSafetyEvaluation: (projectId: string, caseId: string) =>
    request<BobaSafetyEvaluationCaseV1>(
      `/boba/projects/${projectId}/safety-gate/evaluations/${caseId}`,
    ),
  getBobaSafetyDecision: (projectId: string, decisionId: string) =>
    request<BobaSafetyDecisionV1>(
      `/boba/projects/${projectId}/safety-gate/decisions/${decisionId}`,
    ),
  exportBobaSafetyGate: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/safety-gate/export`,
    ),
  resetBobaSafetyGate: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      safety_gate_summary_removed: boolean;
      immutable_policy_history_deleted: false;
      immutable_decision_history_deleted: false;
      upstream_boba_artifacts_deleted: false;
      approvals_deleted: false;
      source_media_deleted: false;
      accepted_outputs_deleted: false;
      autopilot_history_deleted: false;
      workflow_resumed: false;
      checkpoint_restored: false;
      publication_used: false;
      action_execution_used: false;
    }>(`/boba/projects/${projectId}/safety-gate`, {
      method: "DELETE",
    }),
  getBobaIntegrationLayer: (projectId: string) =>
    request<BobaIntegrationLayerSetV1>(
      `/boba/projects/${projectId}/integration-layer`,
    ),
  exportBobaIntegrationLayer: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/integration-layer/export`,
    ),
  resetBobaIntegrationLayer: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/integration-layer`,
      { method: "DELETE" },
    ),
  createBobaCandidate: (input: Omit<BobaCandidateV1, "created_at">) =>
    request<BobaCandidateV1>("/boba/candidates", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  scoreBobaCandidate: (candidateId: string) =>
    request<BobaScoutScoreV1>(`/boba/candidates/${candidateId}/score`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  decideBobaCandidate: (
    candidateId: string,
    decision: "approve" | "reject",
    reason = "",
  ) =>
    request<Record<string, unknown>>(`/boba/candidates/${candidateId}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ reason, approve_for_processing: false }),
    }),
  getBobaCreativeBriefs: (projectId: string) =>
    request<BobaCreativeBriefsResponse>(`/boba/projects/${projectId}/creative-briefs`),
  createBobaCreativeBriefs: (projectId: string) =>
    request<BobaCreativeBriefsResponse>(`/boba/projects/${projectId}/creative-briefs`, {
      method: "POST",
    }),
  getBobaWholeVideoUnderstanding: (projectId: string) =>
    request<BobaWholeVideoUnderstandingV1>(
      `/boba/projects/${projectId}/whole-video-understanding`,
    ),
  createBobaWholeVideoUnderstanding: (projectId: string) =>
    request<BobaWholeVideoUnderstandingV1>(
      `/boba/projects/${projectId}/whole-video-understanding`,
      { method: "POST" },
    ),
  getBobaCandidateClipDiscovery: (projectId: string) =>
    request<BobaCandidateClipDiscoveryV1>(
      `/boba/projects/${projectId}/candidate-clips`,
    ),
  discoverBobaCandidateClips: (projectId: string) =>
    request<BobaCandidateClipDiscoveryV1>(
      `/boba/projects/${projectId}/candidate-clips/discover`,
      { method: "POST" },
    ),
  getBobaClipRanking: (projectId: string) =>
    request<BobaClipRankingV1>(`/boba/projects/${projectId}/clip-ranking`),
  rankBobaCandidateClips: (projectId: string) =>
    request<BobaClipRankingV1>(`/boba/projects/${projectId}/clip-ranking/rank`, {
      method: "POST",
    }),
  getBobaEditorialDecisions: (projectId: string) =>
    request<BobaEditorialDecisionSetV1>(
      `/boba/projects/${projectId}/editorial-decisions`,
    ),
  createBobaEditorialDecisions: (projectId: string) =>
    request<BobaEditorialDecisionSetV1>(
      `/boba/projects/${projectId}/editorial-decisions`,
      { method: "POST" },
    ),
  getBobaExplanations: (projectId: string) =>
    request<BobaExplanationSetV1>(`/boba/projects/${projectId}/explanations`),
  createBobaExplanations: (projectId: string) =>
    request<BobaExplanationSetV1>(`/boba/projects/${projectId}/explanations`, {
      method: "POST",
    }),
  getBobaCreativeDirectionV2: (projectId: string) =>
    request<BobaCreativeDirectionSetV2>(
      `/boba/projects/${projectId}/creative-direction-v2`,
    ),
  createBobaCreativeDirectionV2: (projectId: string) =>
    request<BobaCreativeDirectionSetV2>(
      `/boba/projects/${projectId}/creative-direction-v2`,
      { method: "POST" },
    ),
  getBobaClipBriefs: (projectId: string) =>
    request<BobaClipBriefSetV1>(`/boba/projects/${projectId}/clip-briefs`),
  createBobaClipBriefs: (projectId: string) =>
    request<BobaClipBriefSetV1>(`/boba/projects/${projectId}/clip-briefs`, {
      method: "POST",
    }),
  getBobaHookRetention: (projectId: string) =>
    request<BobaHookRetentionSetV1>(
      `/boba/projects/${projectId}/hook-retention`,
    ),
  createBobaHookRetention: (projectId: string) =>
    request<BobaHookRetentionSetV1>(
      `/boba/projects/${projectId}/hook-retention`,
      { method: "POST" },
    ),
  getBobaCaptionMotion: (projectId: string) =>
    request<BobaCaptionMotionRecommendationSetV1>(
      `/boba/projects/${projectId}/caption-motion`,
    ),
  createBobaCaptionMotion: (projectId: string) =>
    request<BobaCaptionMotionRecommendationSetV1>(
      `/boba/projects/${projectId}/caption-motion`,
      { method: "POST" },
    ),
  getBobaMusicMood: (projectId: string) =>
    request<BobaMusicMoodRecommendationSetV1>(
      `/boba/projects/${projectId}/music-mood`,
    ),
  createBobaMusicMood: (projectId: string) =>
    request<BobaMusicMoodRecommendationSetV1>(
      `/boba/projects/${projectId}/music-mood`,
      { method: "POST" },
    ),
  getBobaExperimentation: (projectId: string) =>
    request<BobaExperimentationSetV1>(
      `/boba/projects/${projectId}/experimentation`,
    ),
  generateBobaExperimentation: (
    projectId: string,
    input: { creator_id?: string; dry_run?: boolean } = {},
  ) =>
    request<BobaExperimentationSetV1>(
      `/boba/projects/${projectId}/experimentation`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaExperimentation: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/experimentation/export`,
    ),
  resetBobaExperimentation: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      experimentation_removed: boolean;
      unrelated_memory_removed: boolean;
    }>(`/boba/projects/${projectId}/experimentation`, { method: "DELETE" }),
  recordBobaExperimentManualResult: (
    projectId: string,
    input: Omit<BobaExperimentManualResultV1, "result_id" | "created_at" | "warnings">,
  ) =>
    request<BobaExperimentManualResultV1>(
      `/boba/projects/${projectId}/experimentation/results`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  getBobaPerformanceFeedback: (projectId: string) =>
    request<BobaPerformanceFeedbackSetV1>(
      `/boba/projects/${projectId}/performance-feedback`,
    ),
  recordBobaPerformanceFeedbackEvent: (
    projectId: string,
    input: BobaPerformanceFeedbackEventInput,
  ) =>
    request<BobaPerformanceFeedbackEventResponse>(
      `/boba/projects/${projectId}/performance-feedback/events`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  generateBobaPerformanceFeedback: (
    projectId: string,
    input: { dry_run?: boolean } = {},
  ) =>
    request<BobaPerformanceFeedbackSetV1>(
      `/boba/projects/${projectId}/performance-feedback`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaPerformanceFeedback: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/performance-feedback/export`,
    ),
  resetBobaPerformanceFeedback: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      performance_feedback_removed: boolean;
      experimentation_removed: false;
      creator_learning_removed: false;
      approval_rejection_learning_removed: false;
      unrelated_memory_removed: false;
    }>(`/boba/projects/${projectId}/performance-feedback`, {
      method: "DELETE",
    }),
  getBobaCreatorLearning: (projectId: string) =>
    request<BobaCreatorLearningSetV1>(
      `/boba/projects/${projectId}/creator-learning`,
    ),
  recordBobaCreatorLearningEvent: (
    projectId: string,
    input: BobaCreatorFeedbackEventInput,
  ) =>
    request<BobaCreatorFeedbackEventV1>(
      `/boba/projects/${projectId}/creator-learning/events`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  generateBobaCreatorLearning: (
    projectId: string,
    input: { creator_id?: string; dry_run?: boolean } = {},
  ) =>
    request<BobaCreatorLearningSetV1>(
      `/boba/projects/${projectId}/creator-learning`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaCreatorLearning: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/creator-learning/export`,
    ),
  resetBobaCreatorLearning: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      creator_learning_removed: boolean;
      unrelated_memory_removed: boolean;
    }>(`/boba/projects/${projectId}/creator-learning`, { method: "DELETE" }),
  getBobaApprovalRejectionLearning: (projectId: string) =>
    request<BobaApprovalRejectionLearningSetV1>(
      `/boba/projects/${projectId}/approval-rejection-learning`,
    ),
  generateBobaApprovalRejectionLearning: (
    projectId: string,
    input: { creator_id?: string; dry_run?: boolean } = {},
  ) =>
    request<BobaApprovalRejectionLearningSetV1>(
      `/boba/projects/${projectId}/approval-rejection-learning`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  exportBobaApprovalRejectionLearning: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/approval-rejection-learning/export`,
    ),
  resetBobaApprovalRejectionLearning: (projectId: string) =>
    request<{
      reset: boolean;
      project_id: string;
      approval_rejection_learning_removed: boolean;
      creator_learning_removed: boolean;
      unrelated_memory_removed: boolean;
    }>(`/boba/projects/${projectId}/approval-rejection-learning`, {
      method: "DELETE",
    }),
  decideBobaCreativeBrief: (
    projectId: string,
    clipId: string,
    decision: "approve" | "reject",
    reason = "",
  ) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/creative-briefs/${clipId}/${decision}`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  createProject: (input: CreateProjectInput) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(input) }),
  createProjectFromLink: (input: CreateProjectFromLinkInput) =>
    request<CreateProjectFromLinkResponse>("/projects/from-link", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  getLinkIngestion: (id: string) =>
    request<CreateProjectFromLinkResponse>(`/projects/link-ingestions/${id}`),
  renameProject: (id: string, name: string) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  processProject: (id: string) =>
    request<Project>(`/projects/${id}/process`, { method: "POST" }),
  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: "DELETE" }),

  /* Creator Personalization V2 - local profiles and explicit feedback only. */
  listCreatorProfiles: () =>
    request<CreatorProfilesResponse>("/personalization/profiles"),
  getCreatorPersonalizationSummary: () =>
    request<CreatorPersonalizationSummary>("/personalization/summary"),
  createCreatorProfile: (input: {
    preset_id: string;
    profile_name?: string;
    learning_enabled?: boolean;
    activate?: boolean;
  }) =>
    request<CreatorProfileV2>("/personalization/profiles", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateCreatorProfile: (profileId: string, updates: Record<string, unknown>) =>
    request<CreatorProfileV2>(`/personalization/profiles/${profileId}`, {
      method: "PATCH",
      body: JSON.stringify({ updates }),
    }),
  activateCreatorProfile: (profileId: string) =>
    request<CreatorProfileV2>(`/personalization/profiles/${profileId}/activate`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
  resetCreatorProfile: (profileId: string) =>
    request<CreatorProfileV2>(`/personalization/profiles/${profileId}/reset`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
  exportCreatorProfile: (profileId: string) =>
    request<CreatorProfileExportResponse>(
      `/personalization/profiles/${profileId}/export`,
    ),
  submitClipFeedback: (input: ClipFeedbackInput) =>
    request<ClipFeedbackV2>("/personalization/feedback", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  /* Cognitive Engine — video understanding. */
  getAnalysis: (id: string) => request<Analysis>(`/projects/${id}/analysis`),
  runAnalysis: (id: string) =>
    request<Analysis>(`/projects/${id}/analysis/run`, { method: "POST" }),
  rerunStage: (id: string, stage: string) =>
    request<Analysis>(`/projects/${id}/analysis/stages/${stage}/rerun`, { method: "POST" }),
  cancelAnalysis: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/analysis/cancel`, { method: "POST" }),

  /* Story Engine — narrative understanding. */
  getStory: (id: string) => request<Story>(`/projects/${id}/story`),
  runStory: (id: string) =>
    request<Story>(`/projects/${id}/story/run`, { method: "POST" }),
  rerunStoryStage: (id: string, stage: string) =>
    request<Story>(`/projects/${id}/story/stages/${stage}/rerun`, { method: "POST" }),
  cancelStory: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/story/cancel`, { method: "POST" }),
  getStorySummary: (id: string) => request<StorySummary>(`/projects/${id}/story/summary`),

  /* Virality Engine — viral-potential assessment. */
  getVirality: (id: string) => request<Virality>(`/projects/${id}/virality`),
  runVirality: (id: string) =>
    request<Virality>(`/projects/${id}/virality/run`, { method: "POST" }),
  rerunViralityStage: (id: string, stage: string) =>
    request<Virality>(`/projects/${id}/virality/stages/${stage}/rerun`, { method: "POST" }),
  cancelVirality: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/virality/cancel`, { method: "POST" }),
  getViralitySummary: (id: string) =>
    request<ViralitySummary>(`/projects/${id}/virality/summary`),
  getTrendResearch: (id: string) =>
    request<TrendResearchResponse>(`/projects/${id}/virality/trend-research`),

  /* Clip Planner — editing blueprints. */
  getPlanning: (id: string) => request<Planning>(`/projects/${id}/planning`),
  runPlanning: (id: string) =>
    request<Planning>(`/projects/${id}/planning/run`, { method: "POST" }),
  rerunPlanningStage: (id: string, stage: string) =>
    request<Planning>(`/projects/${id}/planning/stages/${stage}/rerun`, { method: "POST" }),
  cancelPlanning: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/planning/cancel`, { method: "POST" }),
  getPlanningSummary: (id: string) =>
    request<PlanningSummary>(`/projects/${id}/planning/summary`),
  listPlans: (id: string) => request<PlanList>(`/projects/${id}/planning/plans`),
  getPlan: (id: string, planId: string) =>
    request<PlanResponse>(`/projects/${id}/planning/plans/${planId}`),

  /* Editing Engine — non-destructive edit timelines. */
  getEditing: (id: string) => request<Editing>(`/projects/${id}/editing`),
  runEditing: (id: string) =>
    request<Editing>(`/projects/${id}/editing/run`, { method: "POST" }),
  rerunEditingStage: (id: string, stage: string) =>
    request<Editing>(`/projects/${id}/editing/stages/${stage}/rerun`, { method: "POST" }),
  cancelEditing: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/editing/cancel`, { method: "POST" }),
  listTimelines: (id: string) => request<TimelineList>(`/projects/${id}/editing/timelines`),
  getTimeline: (id: string, clipId: string) =>
    request<{ project_id: string; timeline: Timeline }>(
      `/projects/${id}/editing/timelines/${clipId}`,
    ),
  getTimelineEvents: (id: string, clipId: string) =>
    request<{ project_id: string; clip_id: string; event_count: number; events: TimelineEvent[] }>(
      `/projects/${id}/editing/timelines/${clipId}/events`,
    ),
  getValidationReport: (id: string) =>
    request<ValidationReport>(`/projects/${id}/editing/validation`),

  /* Optimization Engine — post-render polish. */
  getOptimization: (id: string) => request<Optimization>(`/projects/${id}/optimization`),
  runOptimization: (id: string) =>
    request<Optimization>(`/projects/${id}/optimization/run`, { method: "POST" }),
  rerunOptimizationStage: (id: string, stage: string) =>
    request<Optimization>(`/projects/${id}/optimization/stages/${stage}/rerun`, {
      method: "POST",
    }),
  cancelOptimization: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/optimization/cancel`, { method: "POST" }),
  getQualityReport: (id: string) =>
    request<QualityReport>(`/projects/${id}/optimization/quality`),
  getVariants: (id: string) => request<VariantList>(`/projects/${id}/optimization/variants`),
  getMusicRecommendations: (id: string) =>
    request<MusicRecommendations>(`/projects/${id}/optimization/music`),
  listPackages: (id: string) => request<PackageList>(`/projects/${id}/optimization/packages`),
  getPackage: (id: string, clipId: string) =>
    request<PackageResponse>(`/projects/${id}/optimization/packages/${clipId}`),

  /* Rendering Engine - deterministic execution into real MP4s. */
  getRender: (id: string) => request<RenderRun>(`/projects/${id}/rendering`),
  runRender: (id: string) =>
    request<RenderRun>(`/projects/${id}/rendering/run`, { method: "POST" }),
  rerunRenderStage: (id: string, stage: string) =>
    request<RenderRun>(`/projects/${id}/rendering/stages/${stage}/rerun`, { method: "POST" }),
  cancelRender: (id: string) =>
    request<{ cancelled: boolean }>(`/projects/${id}/rendering/cancel`, { method: "POST" }),
  getRenderManifest: (id: string) =>
    request<RenderManifestResponse>(`/projects/${id}/rendering/manifest`),
  getRenderValidation: (id: string) =>
    request<RenderValidation>(`/projects/${id}/rendering/validation`),
  getRenderLogs: (id: string) => request<RenderLogs>(`/projects/${id}/rendering/logs`),

  /* Project Management & Asset Library. */
  getLibraryDashboard: () => request<LibraryDashboard>(`/library/dashboard`),
  getLibraryAssets: (params: Record<string, string | boolean | undefined> = {}) =>
    request<AssetsResponse>(`/library/assets${_qs(params)}`),
  getLibraryClips: (params: Record<string, string | boolean | undefined> = {}) =>
    request<ClipsResponse>(`/library/clips${_qs(params)}`),
  getLibraryExports: (params: Record<string, string | boolean | undefined> = {}) =>
    request<ExportsResponse>(`/library/exports${_qs(params)}`),
  librarySearch: (q: string) => request<SearchResponse>(`/library/search${_qs({ q })}`),
  getLibraryActivity: (params: Record<string, string | boolean | undefined> = {}) =>
    request<ActivityFeedResponse>(`/library/activity${_qs(params)}`),
  getLibraryStorage: (projectId?: string) =>
    request<StorageResponse>(`/library/storage${_qs({ project_id: projectId })}`),
  getLibraryVersionEngines: (id: string) =>
    request<VersionEnginesResponse>(`/library/projects/${id}/versions`),
  getLibraryVersions: (id: string, engine: string) =>
    request<VersionsResponse>(`/library/projects/${id}/versions/${engine}`),
  captureLibraryVersions: (id: string) =>
    request<{ project_id: string; captured: LibraryVersion[] }>(
      `/library/projects/${id}/versions/capture`,
      { method: "POST" },
    ),
  setProjectFavorite: (id: string, favorite: boolean) =>
    request<LibraryMetaResponse>(`/library/projects/${id}/favorite`, {
      method: "POST",
      body: JSON.stringify({ favorite }),
    }),
  addProjectTag: (id: string, tag: string) =>
    request<LibraryMetaResponse>(`/library/projects/${id}/tags`, {
      method: "POST",
      body: JSON.stringify({ tag }),
    }),
  archiveProject: (id: string) =>
    request<LibraryMetaResponse>(`/library/projects/${id}/archive`, { method: "POST" }),
  restoreProject: (id: string) =>
    request<LibraryMetaResponse>(`/library/projects/${id}/restore`, { method: "POST" }),
  libraryCleanup: (operation: string, projectId?: string) =>
    request<CleanupResultResponse>(
      `/library/cleanup/${operation}${_qs({ project_id: projectId })}`,
      { method: "POST" },
    ),

  /* Workflow Orchestration Engine - the central nervous system. */
  getWorkflow: (id: string) => request<Workflow>(`/projects/${id}/workflow`),
  startWorkflow: (id: string) =>
    request<Workflow>(`/projects/${id}/workflow/start`, { method: "POST" }),
  pauseWorkflow: (id: string) =>
    request<Workflow>(`/projects/${id}/workflow/pause`, { method: "POST" }),
  resumeWorkflow: (id: string) =>
    request<Workflow>(`/projects/${id}/workflow/resume`, { method: "POST" }),
  cancelWorkflow: (id: string) =>
    request<Workflow>(`/projects/${id}/workflow/cancel`, { method: "POST" }),
  retryWorkflow: (id: string) =>
    request<Workflow>(`/projects/${id}/workflow/retry`, { method: "POST" }),
  retryWorkflowJob: (id: string, jobId: string) =>
    request<Workflow>(`/projects/${id}/workflow/jobs/${jobId}/retry`, { method: "POST" }),
  getWorkflowHistory: (id: string) =>
    request<WorkflowHistoryResponse>(`/projects/${id}/workflow/history`),
  getWorkflowJobLogs: (id: string, jobId: string) =>
    request<JobLogsResponse>(`/projects/${id}/workflow/jobs/${jobId}/logs`),
  getWorkers: () => request<WorkersResponse>(`/workflow/workers`),
  getScheduler: () => request<SchedulerStatus>(`/workflow/scheduler`),

  /* Durable Job Queue / Resume V2. */
  getJobs: (projectId?: string) =>
    request<DurableJobListResponse>(`/jobs${_qs({ project_id: projectId })}`),
  getJob: (jobId: string) => request<DurableJob>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) =>
    request<DurableJob>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  retryJob: (jobId: string) =>
    request<DurableJob>(`/jobs/${jobId}/retry`, { method: "POST" }),
  resumeJob: (jobId: string) =>
    request<DurableJob>(`/jobs/${jobId}/resume`, { method: "POST" }),

  /* Production Monitoring & Analytics - observational only. */
  getMonitoringHealth: () => request<MonitoringHealthResponse>(`/monitoring/health`),
  getMonitoringEngines: () => request<EnginesResponse>(`/monitoring/engines`),
  getMonitoringWorkflows: () => request<WorkflowAnalytics>(`/monitoring/workflows`),
  getMonitoringQueue: () => request<QueueSnapshot>(`/monitoring/queue`),
  getMonitoringSystem: () => request<SystemMetrics>(`/monitoring/system`),
  getMonitoringStorage: (capture = false) =>
    request<StorageAnalytics>(`/monitoring/storage${_qs({ capture })}`),
  getMonitoringFailures: () => request<FailuresResponse>(`/monitoring/failures`),
  getMonitoringUsage: () => request<UsageStats>(`/monitoring/usage`),
  getMonitoringCost: () => request<CostEstimate>(`/monitoring/cost`),
  getMonitoringAudit: (limit?: number) =>
    request<AuditResponse>(`/monitoring/audit${_qs({ limit: limit ? String(limit) : undefined })}`),
  getMonitoringAlerts: () => request<AlertsResponse>(`/monitoring/alerts`),
  getMonitoringAdmin: () => request<AdminSnapshot>(`/monitoring/admin`),

  /* BOBA Candidate Review Panel V1 - read-only projection and safe routing. */
  getBobaCandidateReview: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/candidate-review`),
  getBobaCandidateReviewRegistry: (projectId: string) =>
    request<BobaCandidateRegistryResponse>(
      `/boba/projects/${projectId}/candidate-review/registry`,
    ),
  createBobaCandidateReviewSession: (
    projectId: string,
    input: { reviewer_context_id: string; selected_candidate_id?: string | null },
  ) =>
    request<BobaCandidateReviewSession>(
      `/boba/projects/${projectId}/candidate-review/sessions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  getBobaCandidateReviewSession: (projectId: string, sessionId: string) =>
    request<BobaCandidateReviewSession>(
      `/boba/projects/${projectId}/candidate-review/sessions/${sessionId}`,
    ),
  updateBobaCandidateReviewSession: (
    projectId: string,
    sessionId: string,
    updates: Record<string, unknown>,
  ) =>
    request<BobaCandidateReviewSession>(
      `/boba/projects/${projectId}/candidate-review/sessions/${sessionId}`,
      { method: "PATCH", body: JSON.stringify(updates) },
    ),
  deleteBobaCandidateReviewSession: (projectId: string, sessionId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/candidate-review/sessions/${sessionId}`,
      { method: "DELETE" },
    ),
  getBobaCandidateQueue: (
    projectId: string,
    params: { review_filter?: string; sort?: string; offset?: number; limit?: number } = {},
  ) =>
    request<BobaCandidateQueueResponse>(
      `/boba/projects/${projectId}/candidate-review/queue${_qs({
        review_filter: params.review_filter,
        sort: params.sort,
        offset: params.offset === undefined ? undefined : String(params.offset),
        limit: params.limit === undefined ? undefined : String(params.limit),
      })}`,
    ),
  getBobaCandidate: (projectId: string, candidateId: string) =>
    request<BobaCandidateDetailResponse>(
      `/boba/projects/${projectId}/candidate-review/candidates/${candidateId}`,
    ),
  getBobaCandidateTranscript: (projectId: string, candidateId: string, contextSeconds = 15) =>
    request<BobaCandidateTranscriptResponse>(
      `/boba/projects/${projectId}/candidate-review/candidates/${candidateId}/transcript${_qs({
        context_seconds: String(contextSeconds),
      })}`,
    ),
  getBobaCandidateOverlaps: (projectId: string, candidateId: string) =>
    request<BobaCandidateOverlapsResponse>(
      `/boba/projects/${projectId}/candidate-review/candidates/${candidateId}/overlaps`,
    ),
  createBobaCandidateSnapshot: (
    projectId: string,
    candidateId: string,
    sessionId: string,
  ) =>
    request<BobaCandidateSnapshotResponse>(
      `/boba/projects/${projectId}/candidate-review/candidates/${candidateId}/snapshot`,
      { method: "POST", body: JSON.stringify({ candidate_review_session_id: sessionId }) },
    ),
  refreshBobaCandidateSnapshot: (projectId: string, snapshotId: string) =>
    request<BobaCandidateSnapshotResponse>(
      `/boba/projects/${projectId}/candidate-review/snapshots/${snapshotId}/refresh`,
      { method: "POST" },
    ),
  compareBobaCandidates: (
    projectId: string,
    candidateIds: string[],
    comparisonType = "side_by_side",
  ) =>
    request<BobaCandidateComparisonResponse>(
      `/boba/projects/${projectId}/candidate-review/compare`,
      {
        method: "POST",
        body: JSON.stringify({
          candidate_ids: candidateIds,
          comparison_type: comparisonType,
        }),
      },
    ),
  createBobaCandidateAction: (projectId: string, input: BobaCandidateActionInput) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/candidate-review/actions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  validateBobaCandidateAction: (projectId: string, requestId: string) =>
    request<{ valid: boolean; code: string; message: string }>(
      `/boba/projects/${projectId}/candidate-review/actions/${requestId}/validate`,
      { method: "POST" },
    ),
  submitBobaCandidateAction: (projectId: string, requestId: string) =>
    request<CandidateActionReceipt>(
      `/boba/projects/${projectId}/candidate-review/actions/${requestId}/submit`,
      { method: "POST" },
    ),
  getBobaCandidateActionReceipt: (projectId: string, requestId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/candidate-review/actions/${requestId}`,
    ),
  getBobaCandidateReviewTimeline: (projectId: string, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/candidate-review/timeline${_qs({ limit: String(limit) })}`,
    ),
  getBobaCandidateReviewEvents: (projectId: string, afterSequence = 0, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/candidate-review/events${_qs({
        after_sequence: String(afterSequence),
        limit: String(limit),
      })}`,
    ),
  exportBobaCandidateReview: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/candidate-review/export`,
    ),

  /* BOBA Clip Brief Panel V1 - read-only brief projection and safe routing. */
  getBobaClipBriefReview: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/clip-brief-review`),
  getBobaClipBriefReviewRegistry: (projectId: string) =>
    request<BobaClipBriefRegistryResponse>(
      `/boba/projects/${projectId}/clip-brief-review/registry`,
    ),
  createBobaClipBriefReviewSession: (
    projectId: string,
    input: { reviewer_context_id: string; selected_brief_id?: string | null },
  ) =>
    request<BobaClipBriefReviewSession>(
      `/boba/projects/${projectId}/clip-brief-review/sessions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  getBobaClipBriefReviewSession: (projectId: string, sessionId: string) =>
    request<BobaClipBriefReviewSession>(
      `/boba/projects/${projectId}/clip-brief-review/sessions/${sessionId}`,
    ),
  updateBobaClipBriefReviewSession: (
    projectId: string,
    sessionId: string,
    updates: Record<string, unknown>,
  ) =>
    request<BobaClipBriefReviewSession>(
      `/boba/projects/${projectId}/clip-brief-review/sessions/${sessionId}`,
      { method: "PATCH", body: JSON.stringify(updates) },
    ),
  deleteBobaClipBriefReviewSession: (projectId: string, sessionId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/clip-brief-review/sessions/${sessionId}`,
      { method: "DELETE" },
    ),
  getBobaClipBriefQueue: (
    projectId: string,
    params: { review_filter?: string; sort?: string; offset?: number; limit?: number } = {},
  ) =>
    request<BobaClipBriefQueueResponse>(
      `/boba/projects/${projectId}/clip-brief-review/queue${_qs({
        review_filter: params.review_filter,
        sort: params.sort,
        offset: params.offset === undefined ? undefined : String(params.offset),
        limit: params.limit === undefined ? undefined : String(params.limit),
      })}`,
    ),
  getBobaClipBrief: (projectId: string, briefId: string) =>
    request<BobaClipBriefDetailResponse>(
      `/boba/projects/${projectId}/clip-brief-review/briefs/${briefId}`,
    ),
  getBobaClipBriefCompleteness: (projectId: string, briefId: string) =>
    request<BobaClipBriefCompletenessResponse>(
      `/boba/projects/${projectId}/clip-brief-review/briefs/${briefId}/completeness`,
    ),
  getBobaClipBriefEvidence: (projectId: string, briefId: string) =>
    request<BobaClipBriefEvidenceResponse>(
      `/boba/projects/${projectId}/clip-brief-review/briefs/${briefId}/evidence`,
    ),
  getBobaClipBriefConflicts: (projectId: string, briefId: string) =>
    request<BobaClipBriefConflictsResponse>(
      `/boba/projects/${projectId}/clip-brief-review/briefs/${briefId}/conflicts`,
    ),
  createBobaClipBriefSnapshot: (projectId: string, briefId: string, sessionId: string) =>
    request<BobaClipBriefSnapshotResponse>(
      `/boba/projects/${projectId}/clip-brief-review/briefs/${briefId}/snapshot`,
      { method: "POST", body: JSON.stringify({ clip_brief_review_session_id: sessionId }) },
    ),
  refreshBobaClipBriefSnapshot: (projectId: string, snapshotId: string) =>
    request<BobaClipBriefSnapshotResponse>(
      `/boba/projects/${projectId}/clip-brief-review/snapshots/${snapshotId}/refresh`,
      { method: "POST" },
    ),
  compareBobaClipBriefs: (
    projectId: string,
    briefIds: string[],
    comparisonType = "side_by_side",
  ) =>
    request<{ comparison: ClipBriefComparison }>(
      `/boba/projects/${projectId}/clip-brief-review/compare`,
      {
        method: "POST",
        body: JSON.stringify({ brief_ids: briefIds, comparison_type: comparisonType }),
      },
    ),
  createBobaClipBriefAction: (projectId: string, input: BobaClipBriefActionInput) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/clip-brief-review/actions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  validateBobaClipBriefAction: (projectId: string, requestId: string) =>
    request<{ valid: boolean; code: string; message: string }>(
      `/boba/projects/${projectId}/clip-brief-review/actions/${requestId}/validate`,
      { method: "POST" },
    ),
  submitBobaClipBriefAction: (projectId: string, requestId: string) =>
    request<ClipBriefActionReceipt>(
      `/boba/projects/${projectId}/clip-brief-review/actions/${requestId}/submit`,
      { method: "POST" },
    ),
  getBobaClipBriefActionReceipt: (projectId: string, requestId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/clip-brief-review/actions/${requestId}`,
    ),
  getBobaClipBriefReviewTimeline: (projectId: string, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/clip-brief-review/timeline${_qs({ limit: String(limit) })}`,
    ),
  getBobaClipBriefReviewEvents: (projectId: string, afterSequence = 0, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/clip-brief-review/events${_qs({
        after_sequence: String(afterSequence),
        limit: String(limit),
      })}`,
    ),
  exportBobaClipBriefReview: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/clip-brief-review/export`,
    ),

  /* BOBA Error Doctor Panel V1 - read-only incident projection and safe routing. */
  getBobaErrorDoctorReview: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/error-doctor-review`),
  getBobaErrorDoctorReviewRegistry: (projectId: string) =>
    request<BobaErrorDoctorRegistryResponse>(
      `/boba/projects/${projectId}/error-doctor-review/registry`,
    ),
  createBobaErrorDoctorReviewSession: (
    projectId: string,
    input: { reviewer_context_id: string; selected_incident_id?: string | null },
  ) =>
    request<BobaErrorDoctorReviewSession>(
      `/boba/projects/${projectId}/error-doctor-review/sessions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  getBobaErrorDoctorReviewSession: (projectId: string, sessionId: string) =>
    request<BobaErrorDoctorReviewSession>(
      `/boba/projects/${projectId}/error-doctor-review/sessions/${sessionId}`,
    ),
  updateBobaErrorDoctorReviewSession: (
    projectId: string,
    sessionId: string,
    updates: Record<string, unknown>,
  ) =>
    request<BobaErrorDoctorReviewSession>(
      `/boba/projects/${projectId}/error-doctor-review/sessions/${sessionId}`,
      { method: "PATCH", body: JSON.stringify(updates) },
    ),
  deleteBobaErrorDoctorReviewSession: (projectId: string, sessionId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/sessions/${sessionId}`,
      { method: "DELETE" },
    ),
  getBobaIncidentQueue: (
    projectId: string,
    params: { review_filter?: string; sort?: string; offset?: number; limit?: number } = {},
  ) =>
    request<BobaIncidentQueueResponse>(
      `/boba/projects/${projectId}/error-doctor-review/queue${_qs({
        review_filter: params.review_filter,
        sort: params.sort,
        offset: params.offset === undefined ? undefined : String(params.offset),
        limit: params.limit === undefined ? undefined : String(params.limit),
      })}`,
    ),
  getBobaIncident: (projectId: string, incidentId: string) =>
    request<BobaIncidentDetailResponse>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}`,
    ),
  createBobaIncidentSnapshot: (
    projectId: string,
    incidentId: string,
    sessionId: string,
  ) =>
    request<BobaIncidentSnapshotResponse>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/snapshot`,
      {
        method: "POST",
        body: JSON.stringify({ error_doctor_review_session_id: sessionId }),
      },
    ),
  refreshBobaIncidentSnapshot: (projectId: string, snapshotId: string) =>
    request<BobaIncidentSnapshotResponse>(
      `/boba/projects/${projectId}/error-doctor-review/snapshots/${snapshotId}/refresh`,
      { method: "POST" },
    ),
  getBobaIncidentDiagnosis: (projectId: string, incidentId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/diagnosis`,
    ),
  getBobaIncidentRootCause: (projectId: string, incidentId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/root-cause`,
    ),
  getBobaIncidentRepairPlan: (projectId: string, incidentId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/repair-plan`,
    ),
  getBobaIncidentRecoveryHistory: (projectId: string, incidentId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/recovery-history`,
    ),
  getBobaIncidentValidationEvidence: (projectId: string, incidentId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/validation`,
    ),
  getBobaIncidentArtifactEvidence: (projectId: string, incidentId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/artifacts`,
    ),
  getBobaIncidentConflicts: (projectId: string, incidentId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/incidents/${incidentId}/conflicts`,
    ),
  compareBobaIncidents: (
    projectId: string,
    incidentIds: string[],
    comparisonType = "side_by_side",
  ) =>
    request<{ comparison: Record<string, unknown> }>(
      `/boba/projects/${projectId}/error-doctor-review/compare`,
      {
        method: "POST",
        body: JSON.stringify({
          incident_ids: incidentIds,
          comparison_type: comparisonType,
        }),
      },
    ),
  createBobaErrorDoctorAction: (
    projectId: string,
    input: BobaErrorDoctorActionInput,
  ) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/actions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  validateBobaErrorDoctorAction: (projectId: string, requestId: string) =>
    request<{ valid: boolean; code: string; message: string }>(
      `/boba/projects/${projectId}/error-doctor-review/actions/${requestId}/validate`,
      { method: "POST" },
    ),
  submitBobaErrorDoctorAction: (projectId: string, requestId: string) =>
    request<ErrorDoctorActionReceipt>(
      `/boba/projects/${projectId}/error-doctor-review/actions/${requestId}/submit`,
      { method: "POST" },
    ),
  getBobaErrorDoctorActionReceipt: (projectId: string, requestId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/actions/${requestId}`,
    ),
  getBobaIncidentTimeline: (projectId: string, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/timeline${_qs({
        limit: String(limit),
      })}`,
    ),
  getBobaIncidentEvents: (projectId: string, afterSequence = 0, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/events${_qs({
        after_sequence: String(afterSequence),
        limit: String(limit),
      })}`,
    ),
  exportBobaErrorDoctorReview: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/error-doctor-review/export`,
    ),

  /* BOBA Repair Plan Panel V1 - read-only plan projection and safe routing.
     No method here approves, rejects, revises or executes a repair plan, runs a
     command, restores a checkpoint, restarts a process or changes a workflow. */
  getBobaRepairPlanReview: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/repair-plan-review`),
  getBobaRepairPlanReviewRegistry: (projectId: string) =>
    request<BobaRepairPlanRegistryResponse>(
      `/boba/projects/${projectId}/repair-plan-review/registry`,
    ),
  createBobaRepairPlanReviewSession: (
    projectId: string,
    input: { reviewer_context_id: string; selected_repair_plan_id?: string | null },
  ) =>
    request<BobaRepairPlanReviewSession>(
      `/boba/projects/${projectId}/repair-plan-review/sessions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  getBobaRepairPlanReviewSession: (projectId: string, sessionId: string) =>
    request<BobaRepairPlanReviewSession>(
      `/boba/projects/${projectId}/repair-plan-review/sessions/${sessionId}`,
    ),
  updateBobaRepairPlanReviewSession: (
    projectId: string,
    sessionId: string,
    updates: Record<string, unknown>,
  ) =>
    request<BobaRepairPlanReviewSession>(
      `/boba/projects/${projectId}/repair-plan-review/sessions/${sessionId}`,
      { method: "PATCH", body: JSON.stringify(updates) },
    ),
  deleteBobaRepairPlanReviewSession: (projectId: string, sessionId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/sessions/${sessionId}`,
      { method: "DELETE" },
    ),
  getBobaRepairPlanQueue: (
    projectId: string,
    params: { review_filter?: string; sort?: string; offset?: number; limit?: number } = {},
  ) =>
    request<BobaRepairPlanQueueResponse>(
      `/boba/projects/${projectId}/repair-plan-review/queue${_qs({
        review_filter: params.review_filter,
        sort: params.sort,
        offset: params.offset === undefined ? undefined : String(params.offset),
        limit: params.limit === undefined ? undefined : String(params.limit),
      })}`,
    ),
  getBobaRepairPlan: (projectId: string, repairPlanId: string) =>
    request<BobaRepairPlanDetailResponse>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}`,
    ),
  createBobaRepairPlanSnapshot: (
    projectId: string,
    repairPlanId: string,
    sessionId: string,
  ) =>
    request<BobaRepairPlanSnapshotResponse>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/snapshot`,
      {
        method: "POST",
        body: JSON.stringify({ repair_plan_review_session_id: sessionId }),
      },
    ),
  refreshBobaRepairPlanSnapshot: (projectId: string, snapshotId: string) =>
    request<BobaRepairPlanSnapshotResponse>(
      `/boba/projects/${projectId}/repair-plan-review/snapshots/${snapshotId}/refresh`,
      { method: "POST" },
    ),
  getBobaRepairPlanSteps: (projectId: string, repairPlanId: string) =>
    request<BobaRepairPlanStepsResponse>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/steps`,
    ),
  getBobaRepairPlanRisk: (projectId: string, repairPlanId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/risk`,
    ),
  getBobaRepairPlanApprovals: (projectId: string, repairPlanId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/approvals`,
    ),
  getBobaRepairPlanVerification: (projectId: string, repairPlanId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/verification`,
    ),
  getBobaRepairPlanEvidence: (projectId: string, repairPlanId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/evidence`,
    ),
  getBobaRepairPlanRecoveryHistory: (projectId: string, repairPlanId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/recovery-history`,
    ),
  getBobaRepairPlanConflicts: (projectId: string, repairPlanId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/plans/${repairPlanId}/conflicts`,
    ),
  compareBobaRepairPlans: (
    projectId: string,
    repairPlanIds: string[],
    comparisonType = "side_by_side",
  ) =>
    request<{ comparison: Record<string, unknown> }>(
      `/boba/projects/${projectId}/repair-plan-review/compare`,
      {
        method: "POST",
        body: JSON.stringify({
          repair_plan_ids: repairPlanIds,
          comparison_type: comparisonType,
        }),
      },
    ),
  describeBobaRepairPlanActionConfirmation: (
    projectId: string,
    snapshotId: string,
    actionDescriptorId: string,
  ) =>
    request<BobaRepairPlanConfirmationResponse>(
      `/boba/projects/${projectId}/repair-plan-review/snapshots/${snapshotId}/confirmations/${actionDescriptorId}`,
    ),
  createBobaRepairPlanAction: (projectId: string, input: BobaRepairPlanActionInput) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/actions`,
      { method: "POST", body: JSON.stringify(input) },
    ),
  validateBobaRepairPlanAction: (projectId: string, requestId: string) =>
    request<{ valid: boolean; code: string; message: string }>(
      `/boba/projects/${projectId}/repair-plan-review/actions/${requestId}/validate`,
      { method: "POST" },
    ),
  submitBobaRepairPlanAction: (projectId: string, requestId: string) =>
    request<RepairPlanActionReceipt>(
      `/boba/projects/${projectId}/repair-plan-review/actions/${requestId}/submit`,
      { method: "POST" },
    ),
  getBobaRepairPlanActionReceipt: (projectId: string, requestId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/actions/${requestId}`,
    ),
  getBobaRepairPlanTimeline: (projectId: string, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/timeline${_qs({
        limit: String(limit),
      })}`,
    ),
  getBobaRepairPlanEvents: (projectId: string, afterSequence = 0, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/events${_qs({
        after_sequence: String(afterSequence),
        limit: String(limit),
      })}`,
    ),
  exportBobaRepairPlanReview: (projectId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/repair-plan-review/export`,
    ),

  /* BOBA Review UI V1 - presentation and canonical action routing only. */
  getBobaReviewUi: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/review-ui`),
  getBobaReviewUiRegistry: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/review-ui/registry`),
  getBobaReviewUiViews: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/review-ui/views`),
  getBobaReviewUiActions: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/review-ui/actions`),
  getBobaReviewQueue: (
    projectId: string,
    params: {
      category?: string;
      include_historical?: boolean;
      sort?: string;
      offset?: number;
      limit?: number;
    } = {},
  ) =>
    request<BobaReviewQueueResponse>(
      `/boba/projects/${projectId}/review-ui/queue${_qs({
        category: params.category,
        include_historical: params.include_historical,
        sort: params.sort,
        offset: params.offset === undefined ? undefined : String(params.offset),
        limit: params.limit === undefined ? undefined : String(params.limit),
      })}`,
    ),
  createBobaReviewSession: (projectId: string, input: BobaReviewSessionInput) =>
    request<BobaReviewSession>(`/boba/projects/${projectId}/review-ui/sessions`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  getBobaReviewSession: (projectId: string, sessionId: string) =>
    request<BobaReviewSession>(
      `/boba/projects/${projectId}/review-ui/sessions/${sessionId}`,
    ),
  updateBobaReviewSession: (
    projectId: string,
    sessionId: string,
    updates: Record<string, unknown>,
  ) =>
    request<BobaReviewSession>(
      `/boba/projects/${projectId}/review-ui/sessions/${sessionId}`,
      { method: "PATCH", body: JSON.stringify(updates) },
    ),
  deleteBobaReviewSession: (projectId: string, sessionId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/review-ui/sessions/${sessionId}`,
      { method: "DELETE" },
    ),
  getBobaReviewTarget: (projectId: string, targetId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/review-ui/targets/${targetId}`,
    ),
  createBobaReviewSnapshot: (projectId: string, targetId: string, sessionId: string) =>
    request<BobaReviewSnapshotResponse>(
      `/boba/projects/${projectId}/review-ui/targets/${targetId}/snapshot`,
      { method: "POST", body: JSON.stringify({ review_session_id: sessionId }) },
    ),
  refreshBobaReviewSnapshot: (projectId: string, snapshotId: string) =>
    request<BobaReviewSnapshotResponse>(
      `/boba/projects/${projectId}/review-ui/snapshots/${snapshotId}/refresh`,
      { method: "POST" },
    ),
  createBobaReviewAction: (projectId: string, input: BobaReviewActionInput) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/review-ui/actions`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  validateBobaReviewAction: (projectId: string, actionRequestId: string) =>
    request<BobaReviewActionValidation>(
      `/boba/projects/${projectId}/review-ui/actions/${actionRequestId}/validate`,
      { method: "POST" },
    ),
  submitBobaReviewAction: (projectId: string, actionRequestId: string) =>
    request<ReviewActionReceipt>(
      `/boba/projects/${projectId}/review-ui/actions/${actionRequestId}/submit`,
      { method: "POST" },
    ),
  getBobaReviewAction: (projectId: string, actionRequestId: string) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/review-ui/actions/${actionRequestId}`,
    ),
  getBobaReviewTimeline: (projectId: string, limit = 100) =>
    request<Record<string, unknown>>(
      `/boba/projects/${projectId}/review-ui/timeline${_qs({ limit: String(limit) })}`,
    ),
  getBobaReviewEvents: (projectId: string, afterSequence = 0, limit = 100) =>
    request<BobaReviewEventsResponse>(
      `/boba/projects/${projectId}/review-ui/events${_qs({
        after_sequence: String(afterSequence),
        limit: String(limit),
      })}`,
    ),
  acknowledgeBobaReviewNotification: (
    projectId: string,
    notificationId: string,
    sessionId: string,
  ) =>
    request<BobaReviewSession>(
      `/boba/projects/${projectId}/review-ui/notifications/${notificationId}/acknowledge`,
      { method: "POST", body: JSON.stringify({ review_session_id: sessionId }) },
    ),
  exportBobaReviewUi: (projectId: string) =>
    request<Record<string, unknown>>(`/boba/projects/${projectId}/review-ui/export`),

  /** Upload a captured thumbnail frame (multipart; not JSON). */
  uploadThumbnail: async (id: string, blob: Blob): Promise<Project> => {
    const form = new FormData();
    form.append("file", blob, "thumbnail.jpg");
    const response = await fetch(`${API_V1}/projects/${id}/thumbnail`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      throw new ApiClientError("Failed to store thumbnail.", "thumbnail_error", response.status);
    }
    return (await response.json()) as Project;
  },
};


/* BOBA Review UI V1 request and response shapes. */
export interface BobaReviewSessionInput {
  reviewer_context_id: string;
  review_mode?: string;
  target_type?: string;
  target_id?: string;
  expires_in_seconds?: number;
}

export interface BobaReviewSession {
  review_session_id: string;
  project_id: string;
  reviewer_context_id: string;
  selected_review_mode: string;
  selected_target_type: string;
  selected_target_id: string;
  active_filter_id: string;
  active_sort: string;
  active_tab: string;
  evidence_drawer_open: boolean;
  event_drawer_open: boolean;
  compact_mode: boolean;
  acknowledged_notification_ids: string[];
  expires_at: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaReviewQueueResponse {
  schema_version: string;
  project_id: string;
  total: number;
  offset: number;
  limit: number;
  priority_tiers: { priority: number; reason: string; display_category: string }[];
  items: ReviewQueueItem[];
}

export interface BobaReviewSnapshotResponse {
  snapshot: ReviewSnapshot;
  target: Record<string, unknown>;
  source_cards: ReviewSourceCard[];
  sections: Record<string, unknown>[];
  /** Server-issued confirmation token per available action, keyed by descriptor id. */
  action_confirmations: Record<string, string>;
}

export interface BobaReviewEventsResponse {
  schema_version: string;
  project_id: string;
  events: ReviewEvent[];
  has_more: boolean;
  latest_sequence: number;
}

export interface BobaReviewActionInput {
  review_session_id: string;
  review_snapshot_id: string;
  action_descriptor_id: string;
  decision_value?: string | null;
  reason?: string;
  confirmation_context_digest: string;
  idempotency_key: string;
  confirmed: boolean;
}

export interface BobaReviewActionValidation {
  valid: boolean;
  code: string;
  message: string;
}


/* BOBA Candidate Review Panel V1 request and response shapes. */
export interface BobaCandidateReviewSession {
  candidate_review_session_id: string;
  project_id: string;
  reviewer_context_id: string;
  selected_candidate_id: string | null;
  comparison_candidate_ids: string[];
  locally_shortlisted_candidate_ids: string[];
  active_filter: string;
  active_sort: string;
  show_rejected: boolean;
  show_historical: boolean;
  show_technical_details: boolean;
  transcript_context_seconds: number;
  evidence_drawer_open: boolean;
  timeline_drawer_open: boolean;
  expires_at: string;
  limitations: string[];
}

export interface BobaCandidateRegistryResponse {
  registry_snapshot: Record<string, unknown>;
  sources: Record<string, unknown>[];
  actions: CandidateActionDescriptor[];
}

export interface BobaCandidateQueueResponse {
  schema_version: string;
  project_id: string;
  total: number;
  offset: number;
  limit: number;
  active_filter: string;
  active_sort: string;
  priority_tiers: { priority: number; reason: string }[];
  items: CandidateQueueItem[];
}

export interface BobaCandidateSnapshotResponse {
  snapshot: CandidateSnapshot;
  candidate_reference: CandidateReference;
  queue_item: CandidateQueueItem;
  source_cards: Record<string, unknown>[];
  score_cards: CandidateScoreCard[];
  overlap_records: CandidateOverlapRecord[];
  action_confirmations: Record<string, string>;
}

export interface BobaCandidateDetailResponse {
  candidate_reference: CandidateReference;
  queue_item: CandidateQueueItem;
  source_cards: Record<string, unknown>[];
  score_cards: CandidateScoreCard[];
  overlap_records: CandidateOverlapRecord[];
  transcript: BobaCandidateTranscriptResponse;
}

export interface BobaCandidateTranscriptResponse {
  candidate_id: string;
  candidate_start_seconds: number;
  candidate_end_seconds: number;
  context_seconds: number;
  context_start_seconds: number;
  context_end_seconds: number;
  candidate_transcript_snippets: string[];
  transcript_segment_ids: string[];
  source_module_id: string;
  limitations: string[];
}

export interface BobaCandidateOverlapsResponse {
  candidate_id: string;
  substantial_overlap_iou_threshold: number;
  overlap_records: CandidateOverlapRecord[];
  limitations: string[];
}

export interface BobaCandidateComparisonResponse {
  comparison: Record<string, unknown>;
  overlap_records: CandidateOverlapRecord[];
}

export interface BobaCandidateActionInput {
  candidate_review_session_id: string;
  candidate_snapshot_id: string;
  action_descriptor_id: string;
  decision_value?: string | null;
  reason?: string;
  confirmation_context_digest: string;
  idempotency_key: string;
  confirmed: boolean;
}

export interface BobaClipBriefReviewSession {
  clip_brief_review_session_id: string;
  project_id: string;
  reviewer_context_id: string;
  selected_brief_id: string | null;
  selected_candidate_id: string | null;
  comparison_brief_ids: string[];
  active_filter: string;
  active_sort: string;
  active_section_id: string;
  show_historical: boolean;
  show_technical_details: boolean;
  show_source_evidence: boolean;
  show_empty_optional_fields: boolean;
  evidence_drawer_open: boolean;
  timeline_drawer_open: boolean;
  local_annotations: { annotation_id: string; field_path: string; text: string; notice: string }[];
  expires_at: string;
  limitations: string[];
}

export interface BobaClipBriefRegistryResponse {
  registry_snapshot: Record<string, unknown>;
  sources: Record<string, unknown>[];
  sections: Record<string, unknown>[];
  actions: ClipBriefActionDescriptor[];
  required_field_paths: string[];
  optional_field_paths: string[];
  supported_brief_schema_id: string;
}

export interface BobaClipBriefQueueResponse {
  schema_version: string;
  project_id: string;
  total: number;
  offset: number;
  limit: number;
  active_filter: string;
  active_sort: string;
  priority_tiers: { priority: number; reason: string }[];
  items: ClipBriefQueueItem[];
}

export interface BobaClipBriefSnapshotResponse {
  snapshot: ClipBriefSnapshot;
  brief_reference: ClipBriefReference;
  field_projections: ClipBriefFieldProjection[];
  section_projections: ClipBriefSectionProjection[];
  source_cards: ClipBriefSourceCard[];
  evidence_links: ClipBriefEvidenceLink[];
  completeness: ClipBriefCompleteness;
  conflict_records: ClipBriefConflict[];
  action_confirmations: Record<string, string>;
}

export interface BobaClipBriefDetailResponse {
  schema_version: string;
  project_id: string;
  brief_id: string;
  brief_reference: ClipBriefReference;
  field_projections: ClipBriefFieldProjection[];
  section_projections: ClipBriefSectionProjection[];
  source_cards: ClipBriefSourceCard[];
  evidence_links: ClipBriefEvidenceLink[];
  completeness: ClipBriefCompleteness;
  conflict_records: ClipBriefConflict[];
}

export interface BobaClipBriefCompletenessResponse {
  schema_version: string;
  project_id: string;
  brief_id: string;
  completeness: ClipBriefCompleteness;
  limitations: string[];
}

export interface BobaClipBriefEvidenceResponse {
  schema_version: string;
  project_id: string;
  brief_id: string;
  evidence_links: ClipBriefEvidenceLink[];
  missing_evidence_count: number;
  limitations: string[];
}

export interface BobaClipBriefConflictsResponse {
  schema_version: string;
  project_id: string;
  brief_id: string;
  conflict_records: ClipBriefConflict[];
  blocking_conflict_count: number;
  limitations: string[];
}

export interface BobaClipBriefActionInput {
  clip_brief_review_session_id: string;
  brief_snapshot_id: string;
  action_descriptor_id: string;
  decision_value?: string | null;
  reason?: string;
  confirmation_context_digest: string;
  idempotency_key: string;
  confirmed: boolean;
}

export interface BobaErrorDoctorReviewSession {
  error_doctor_review_session_id: string;
  project_id: string;
  reviewer_context_id: string;
  selected_incident_id: string | null;
  comparison_incident_ids: string[];
  active_filter: string;
  active_sort: string;
  active_section_id: string;
  show_recovered: boolean;
  show_resolved: boolean;
  show_historical: boolean;
  show_technical_details: boolean;
  show_bounded_logs: boolean;
  show_repair_history: boolean;
  evidence_drawer_open: boolean;
  timeline_drawer_open: boolean;
  local_annotations: {
    annotation_id: string;
    incident_id: string;
    section_id: string;
    text: string;
    notice: string;
  }[];
  read_incident_ids: string[];
  expires_at: string;
  limitations: string[];
}

export interface BobaErrorDoctorRegistryResponse {
  registry_snapshot: Record<string, unknown>;
  sources: Record<string, unknown>[];
  sections: Record<string, unknown>[];
  actions: ErrorDoctorActionDescriptor[];
  priority_tiers: { priority: number; reason: string }[];
  source_severity_order: string[];
  supported_incident_schema_id: string;
}

export interface BobaIncidentQueueResponse {
  schema_version: string;
  project_id: string;
  total: number;
  offset: number;
  limit: number;
  active_filter: string;
  active_sort: string;
  priority_tiers: { priority: number; reason: string }[];
  items: IncidentQueueItem[];
}

export interface BobaIncidentSnapshotResponse {
  snapshot: IncidentSnapshot;
  incident_reference: IncidentReference;
  diagnosis_projections: DiagnosisProjection[];
  root_cause_projections: RootCauseProjection[];
  evidence_cards: ErrorEvidenceCard[];
  repair_plan_projections: RepairPlanProjection[];
  recovery_attempt_projections: RecoveryAttemptProjection[];
  validation_evidence: Record<string, unknown>;
  artifact_evidence: Record<string, unknown>;
  conflict_records: ErrorConflict[];
  action_confirmations: Record<string, string>;
}

export interface BobaIncidentDetailResponse {
  schema_version: string;
  project_id: string;
  incident_id: string;
  incident_reference: IncidentReference;
  diagnosis_projections: DiagnosisProjection[];
  root_cause_projections: RootCauseProjection[];
  evidence_cards: ErrorEvidenceCard[];
  repair_plan_projections: RepairPlanProjection[];
  recovery_attempt_projections: RecoveryAttemptProjection[];
  conflict_records: ErrorConflict[];
}

export interface BobaRepairPlanReviewSession {
  repair_plan_review_session_id: string;
  project_id: string;
  reviewer_context_id: string;
  selected_repair_plan_id: string | null;
  comparison_repair_plan_ids: string[];
  active_filter: string;
  active_sort: string;
  active_section_id: string;
  show_historical: boolean;
  show_superseded: boolean;
  show_completed: boolean;
  show_technical_details: boolean;
  show_recovery_history: boolean;
  evidence_drawer_open: boolean;
  timeline_drawer_open: boolean;
  local_annotations: {
    annotation_id: string;
    repair_plan_id: string;
    section_id: string;
    text: string;
    notice: string;
  }[];
  read_repair_plan_ids: string[];
  session_digest: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaRepairPlanRegistryResponse {
  registry_snapshot: Record<string, unknown>;
  sources: Record<string, unknown>[];
  sections: Record<string, unknown>[];
  actions: RepairPlanActionDescriptor[];
  priority_tiers: { priority: number; reason: string }[];
  source_risk_order: string[];
  risk_dimensions: string[];
  supported_repair_plan_schema_id: string;
  withheld_notices: {
    command: string;
    private_path: string;
    not_executable: string;
    source_retained: string;
  };
}

export interface BobaRepairPlanQueueResponse {
  schema_version: string;
  project_id: string;
  active_filter: string;
  active_sort: string;
  offset: number;
  limit: number;
  total_count: number;
  filtered_count: number;
  returned_count: number;
  has_more: boolean;
  items: RepairPlanQueueItem[];
  priority_tiers: { priority: number; reason: string }[];
  limitations: string[];
}

export interface BobaRepairPlanSnapshotResponse {
  snapshot: RepairPlanSnapshot;
  repair_plan_reference: RepairPlanReference;
  step_projections: RepairStepProjection[];
  risk_projections: RepairRiskProjection[];
  approval_requirements: RepairApprovalRequirement[];
  verification_requirements: RepairVerificationRequirement[];
  evidence_cards: RepairEvidenceCard[];
  recovery_links: RepairRecoveryLink[];
  conflict_records: RepairPlanConflict[];
  action_confirmations: Record<string, string>;
}

export interface BobaRepairPlanDetailResponse {
  schema_version: string;
  project_id: string;
  repair_plan_id: string;
  repair_plan_reference: RepairPlanReference;
  step_projections: RepairStepProjection[];
  risk_projections: RepairRiskProjection[];
  approval_requirements: RepairApprovalRequirement[];
  verification_requirements: RepairVerificationRequirement[];
  evidence_cards: RepairEvidenceCard[];
  recovery_links: RepairRecoveryLink[];
  conflict_records: RepairPlanConflict[];
  notices: {
    command: string;
    private_path: string;
    not_executable: string;
    source_retained: string;
  };
  limitations: string[];
}

export interface BobaRepairPlanStepsResponse {
  schema_version: string;
  project_id: string;
  repair_plan_id: string;
  step_projections: RepairStepProjection[];
  step_count: number;
  command_bearing_step_count: number;
  destructive_step_count: number;
  read_only_step_count: number;
  raw_command_exposed: false;
  private_path_exposed: false;
  executable_by_panel: false;
  notices: {
    command: string;
    private_path: string;
    not_executable: string;
    source_retained: string;
  };
}

export interface BobaRepairPlanConfirmationResponse {
  schema_version: string;
  project_id: string;
  repair_plan_snapshot_id: string;
  repair_plan_id: string;
  action_descriptor_id: string;
  available: boolean;
  unavailable_reason: string;
  confirmation_context_digest: string | null;
  owning_module_id: string;
  owning_operation_id: string;
  consequences: string[];
  does_not_do: string[];
  confirmation_statement: string;
}

export interface BobaRepairPlanActionInput {
  repair_plan_review_session_id: string;
  repair_plan_snapshot_id: string;
  action_descriptor_id: string;
  decision_value?: string | null;
  reason?: string;
  confirmation_context_digest: string;
  idempotency_key: string;
  confirmed: boolean;
}

export interface BobaErrorDoctorActionInput {
  error_doctor_review_session_id: string;
  incident_snapshot_id: string;
  action_descriptor_id: string;
  decision_value?: string | null;
  reason?: string;
  confirmation_context_digest: string;
  idempotency_key: string;
  confirmed: boolean;
}

/** Direct media URLs served by the backend (no external services). */
export const mediaUrls = {
  source: (id: string) => `${API_V1}/projects/${id}/source`,
  download: (id: string) => `${API_V1}/projects/${id}/source?download=true`,
  thumbnail: (id: string) => `${API_V1}/projects/${id}/thumbnail`,
  /** Download a publish-package asset (metadata / captions / mp4) by kind. */
  packageAsset: (id: string, clipId: string, kind: string) =>
    `${API_V1}/projects/${id}/optimization/packages/${clipId}/assets/${kind}`,
  packageMetadata: (id: string, clipId: string) =>
    `${API_V1}/projects/${id}/optimization/packages/${clipId}/metadata`,
  /** Download a rendered clip's MP4. */
  renderClip: (id: string, clipId: string) =>
    `${API_V1}/projects/${id}/rendering/clips/${clipId}/download`,
  /** Download the render manifest JSON. */
  renderManifest: (id: string) => `${API_V1}/projects/${id}/rendering/manifest/download`,
};
