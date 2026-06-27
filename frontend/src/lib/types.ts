/**
 * Shared API types, mirroring the backend's response contracts.
 *
 * Hand-written for the MVP; a later milestone generates them from the backend's
 * OpenAPI schema so frontend and backend types can never drift.
 */

/** Honest lifecycle status of a project (never fabricated by the backend). */
export type ProjectStatus =
  | "uploaded"
  | "analyzing"
  | "analyzed"
  | "queued"
  | "processing"
  | "complete"
  | "failed";

/** A project: an uploaded video and everything Olympus will do with it. */
export interface Project {
  id: string;
  name: string;
  source_filename: string;
  size_bytes: number;
  video_format: string;
  content_type: string | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  has_thumbnail: boolean;
  upload_duration_ms: number | null;
}

/** Payload for creating a project from an uploaded video. */
export interface CreateProjectInput {
  storage_key: string;
  source_filename: string;
  size_bytes: number;
  video_format: string;
  content_type?: string | null;
  duration_seconds?: number | null;
  width?: number | null;
  height?: number | null;
  upload_duration_ms?: number | null;
}

/** A finished Short (rendered by the pipeline; none exist until it is connected). */
export interface Clip {
  id: string;
  project_id: string;
  title: string;
  duration_seconds: number | null;
  status: string;
  thumbnail_url: string | null;
  download_url: string | null;
}

/** Runtime info returned by GET /system/info. */
export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  adapters: { storage: string; transcription: string; rendering: string };
}

/** The canonical API error envelope returned by the backend. */
export interface ApiError {
  error: { code: string; message: string; details?: unknown };
  request_id?: string;
}

/* -------------------------------------------------------------------------- */
/* Cognitive Engine — video understanding                                     */
/* -------------------------------------------------------------------------- */

/**
 * Honest status of a single analysis stage.
 *
 * `unavailable` means the analyzer's tooling/model is not configured in this
 * environment — the stage produced no fabricated output and explains why in
 * `reason`. `failed` is reserved for genuine errors (never silently skipped).
 */
export type AnalysisStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "cancelled";

/** Overall status of a project's analysis. */
export type AnalysisStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/** One analysis stage and its honest result. */
export interface AnalysisStage {
  stage: string;
  label: string;
  status: AnalysisStageStatus;
  version: string;
  progress: number;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  reason: string | null;
  /** Stage output; present only for completed stages, omitted from the index. */
  data: Record<string, unknown> | null;
}

/** A project's complete, evolving video understanding. */
export interface Analysis {
  project_id: string;
  pipeline_version: string;
  status: AnalysisStatus;
  created_at: string;
  updated_at: string;
  completed_stages: number;
  total_stages: number;
  stages: AnalysisStage[];
}

/* -------------------------------------------------------------------------- */
/* Story Engine — narrative understanding                                     */
/* -------------------------------------------------------------------------- */

/**
 * Honest status of a single story stage. `unavailable` means the stage lacked
 * the inputs it needs (most need a transcript) — nothing is fabricated, and the
 * reason is given. `failed` is reserved for genuine errors.
 */
export type StoryStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "cancelled";

/** Overall status of a project's story analysis. */
export type StoryStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/** One story stage and its honest result (data carries confidence + evidence). */
export interface StoryStage {
  stage: string;
  label: string;
  status: StoryStageStatus;
  version: string;
  progress: number;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  reason: string | null;
  data: Record<string, unknown> | null;
}

/** A project's complete, evolving narrative understanding. */
export interface Story {
  project_id: string;
  pipeline_version: string;
  status: StoryStatus;
  created_at: string;
  updated_at: string;
  completed_stages: number;
  total_stages: number;
  stages: StoryStage[];
}

/** The engineering story summary (Story Summary stage output). */
export interface StorySummary {
  project_id: string;
  summary: Record<string, unknown>;
}

/* -------------------------------------------------------------------------- */
/* Virality Engine — viral-potential assessment                               */
/* -------------------------------------------------------------------------- */

/**
 * Honest status of a single virality stage. `unavailable` means the stage lacked
 * the evidence it needs (most need a transcript / story signals) — no score is
 * fabricated, and the reason is given. `failed` is reserved for genuine errors.
 */
export type ViralityStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "cancelled";

/** Overall status of a project's virality analysis. */
export type ViralityStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/**
 * One virality stage and its honest result. A completed scoring stage's `data`
 * carries `score`, `confidence`, `evidence`, and `limitations`.
 */
export interface ViralityStage {
  stage: string;
  label: string;
  status: ViralityStageStatus;
  version: string;
  progress: number;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  reason: string | null;
  data: Record<string, unknown> | null;
}

/** A project's complete, evolving virality assessment. */
export interface Virality {
  project_id: string;
  pipeline_version: string;
  status: ViralityStatus;
  created_at: string;
  updated_at: string;
  completed_stages: number;
  total_stages: number;
  stages: ViralityStage[];
}

/** The aggregated virality summary (Virality Summary stage output). */
export interface ViralitySummary {
  project_id: string;
  summary: Record<string, unknown>;
}
