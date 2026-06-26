/**
 * Typed HTTP client for the Olympus backend.
 *
 * A thin wrapper around `fetch` that:
 * - prefixes the versioned API base URL,
 * - parses JSON responses,
 * - normalises backend errors (the `{ error: { code, message } }` envelope)
 *   into a thrown `ApiClientError` carrying the code and request id.
 *
 * Endpoints that do not yet exist on the backend (projects, clips) are declared
 * here against their planned contracts so the UI is ready for Milestone 2; the
 * UI handles their absence gracefully until they ship.
 */

import { API_V1 } from "@/lib/config";
import type { ApiError, Project, SystemInfo } from "@/lib/types";

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
  } catch (cause) {
    throw new ApiClientError(
      "Could not reach the Olympus backend.",
      "network_error",
      0,
    );
  }

  if (!response.ok) {
    let body: ApiError | undefined;
    try {
      body = (await response.json()) as ApiError;
    } catch {
      // Non-JSON error body; fall through to a generic message.
    }
    throw new ApiClientError(
      body?.error.message ?? `Request failed (${response.status}).`,
      body?.error.code ?? "http_error",
      response.status,
      body?.request_id,
    );
  }

  // 204 No Content -> nothing to parse.
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  /** GET /system/info - implemented on the backend today. */
  getSystemInfo: () => request<SystemInfo>("/system/info"),

  /** GET /projects - planned for Milestone 2. */
  listProjects: () => request<Project[]>("/projects"),

  /** GET /projects/{id} - planned for Milestone 2. */
  getProject: (id: string) => request<Project>(`/projects/${id}`),

  /** POST /projects - planned for Milestone 2. */
  createProject: (payload: { source_type: "url"; url: string }) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
