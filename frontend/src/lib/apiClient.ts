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
  Analysis,
  ApiError,
  CreateProjectInput,
  PlanList,
  Planning,
  PlanningSummary,
  PlanResponse,
  Project,
  Story,
  StorySummary,
  SystemInfo,
  Virality,
  ViralitySummary,
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
};
