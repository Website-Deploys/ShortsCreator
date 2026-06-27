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
  ActivityFeedResponse,
  Analysis,
  ApiError,
  AssetsResponse,
  CleanupResultResponse,
  ClipsResponse,
  CreateProjectInput,
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
  createProject: (input: CreateProjectInput) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(input) }),
  renameProject: (id: string, name: string) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  processProject: (id: string) =>
    request<Project>(`/projects/${id}/process`, { method: "POST" }),
  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: "DELETE" }),

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
