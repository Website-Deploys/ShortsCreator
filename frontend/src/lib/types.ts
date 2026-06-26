/**
 * Shared API types.
 *
 * These mirror the backend's response contracts. They are hand-written for the
 * foundation; a later milestone generates them from the backend's OpenAPI
 * schema so the frontend and backend types can never drift.
 */

/** Lifecycle states a project moves through (mirrors the pipeline state machine). */
export type ProjectState =
  | "intake"
  | "ingested"
  | "audio_ready"
  | "transcribed"
  | "understood"
  | "selected"
  | "planned"
  | "rendered"
  | "complete"
  | "failed"
  | "cancelled";

/** Runtime information returned by GET /system/info. */
export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  adapters: {
    storage: string;
    transcription: string;
    rendering: string;
  };
}

/** A project (the unit of work). Shape anticipates the Milestone 2 API. */
export interface Project {
  id: string;
  state: ProjectState;
  source_type: "url" | "upload";
  created_at: string;
  failure_reason?: string | null;
  clip_count?: number;
}

/** A finished Short. */
export interface Clip {
  id: string;
  project_id: string;
  rank: number;
  thesis: string;
  state: string;
  download_url?: string | null;
  thumbnail_url?: string | null;
}

/** The canonical API error envelope returned by the backend. */
export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
  request_id?: string;
}
