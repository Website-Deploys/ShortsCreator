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

/* -------------------------------------------------------------------------- */
/* Clip Planner — editing blueprints                                          */
/* -------------------------------------------------------------------------- */

/**
 * Honest status of a single planning stage. `unavailable` means the stage lacked
 * the evidence it needs (no upstream signals) — no clip is fabricated, and the
 * reason is given. `failed` is reserved for genuine errors.
 */
export type PlanningStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "cancelled";

/** Overall status of a project's clip planning. */
export type PlanningStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/** One planning stage and its honest result. */
export interface PlanningStage {
  stage: string;
  label: string;
  status: PlanningStageStatus;
  version: string;
  progress: number;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  reason: string | null;
  data: Record<string, unknown> | null;
}

/** A project's complete, evolving set of editing plans. */
export interface Planning {
  project_id: string;
  pipeline_version: string;
  status: PlanningStatus;
  created_at: string;
  updated_at: string;
  completed_stages: number;
  total_stages: number;
  stages: PlanningStage[];
}

/**
 * One editing plan (a future Short). The blueprint is rich and evolving, so it
 * is kept as a loose record; `lib/planning.ts` parses the parts the UI renders.
 */
export interface ClipPlan {
  id: string;
  rank?: number;
  start: number;
  end: number;
  duration: number;
  start_frame?: number | null;
  end_frame?: number | null;
  fps?: number | null;
  quality_score: number;
  confidence: number;
  source?: string;
  explanation?: string;
  scores: Record<string, number>;
  evidence: Record<string, unknown>[];
  alternatives: Record<string, unknown>[];
  source_video?: { filename?: string; storage_key?: string };
  blueprint: Record<string, unknown>;
}

/** The full ranked plans (each with its complete blueprint). */
export interface PlanList {
  project_id: string;
  plan_count: number;
  plans: ClipPlan[];
}

/** A single full editing plan. */
export interface PlanResponse {
  project_id: string;
  plan: ClipPlan;
}

/** The aggregated planning summary (Planning Summary stage output). */
export interface PlanningSummary {
  project_id: string;
  summary: Record<string, unknown>;
}

/* -------------------------------------------------------------------------- */
/* Editing Engine — non-destructive edit timelines                            */
/* -------------------------------------------------------------------------- */

/**
 * Honest status of a single editing stage. `unavailable` means the stage lacked
 * its inputs (e.g. no approved clips / no transcript) — no edit is fabricated,
 * and the reason is given. `failed` is reserved for genuine errors.
 */
export type EditingStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "cancelled";

/** Overall status of a project's editing analysis. */
export type EditingStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/** One editing stage and its honest result. */
export interface EditingStage {
  stage: string;
  label: string;
  status: EditingStageStatus;
  version: string;
  progress: number;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  reason: string | null;
  data: Record<string, unknown> | null;
}

/** A project's complete, evolving set of edit timelines. */
export interface Editing {
  project_id: string;
  pipeline_version: string;
  status: EditingStatus;
  created_at: string;
  updated_at: string;
  completed_stages: number;
  total_stages: number;
  stages: EditingStage[];
}

/**
 * One timeline event (clip-relative seconds). `confidence` is `null` when the
 * engine honestly could not determine it (UNKNOWN). Extra fields (scale,
 * transition_type, text, word, ...) vary by event type and are kept loose.
 */
export interface TimelineEvent {
  id: string;
  type: string;
  start: number;
  end: number;
  duration: number;
  reason: string;
  confidence: number | null;
  evidence: Record<string, unknown>[];
  [key: string]: unknown;
}

/** One track of a timeline (video / audio / caption / markers). */
export interface TimelineTrack {
  kind: string;
  events: TimelineEvent[];
}

/** A single clip's complete, non-destructive edit timeline. */
export interface Timeline {
  clip_id: string;
  plan_id?: string;
  rank?: number | null;
  source_video?: { filename?: string; storage_key?: string };
  source_start: number;
  source_end: number;
  duration: number;
  fps: number;
  tracks: TimelineTrack[];
  metadata: Record<string, unknown>;
}

/** All assembled timelines for a project. */
export interface TimelineList {
  project_id: string;
  timeline_count: number;
  timelines: Timeline[];
}

/** A single clip's timeline. */
export interface TimelineResponse {
  project_id: string;
  timeline: Timeline;
}

/** The timeline validation report. */
export interface ValidationReport {
  project_id: string;
  report: {
    valid: boolean;
    clips: { clip_id: string; valid: boolean; issues: Record<string, unknown>[] }[];
    issue_count: number;
  };
}



/* -------------------------------------------------------------------------- */
/* Optimization Engine — post-render polish                                   */
/* -------------------------------------------------------------------------- */

/**
 * Honest status of a single optimization stage. `unavailable` means the stage
 * lacked the rendered media or an enhancement model it needs — no enhancement is
 * fabricated, and the reason is given. `failed` is reserved for genuine errors.
 */
export type OptimizationStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "cancelled";

/** Overall status of a project's optimization analysis. */
export type OptimizationStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/** One optimization stage and its honest result. */
export interface OptimizationStage {
  stage: string;
  label: string;
  status: OptimizationStageStatus;
  version: string;
  progress: number;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  reason: string | null;
  data: Record<string, unknown> | null;
}

/** A project's complete, evolving optimization result. */
export interface Optimization {
  project_id: string;
  pipeline_version: string;
  status: OptimizationStatus;
  created_at: string;
  updated_at: string;
  completed_stages: number;
  total_stages: number;
  stages: OptimizationStage[];
}

/** The per-clip quality evaluation (graded dimensions + honest UNKNOWNs). */
export interface QualityReport {
  project_id: string;
  report: Record<string, unknown>;
}

/** The generated export variants per clip. */
export interface VariantList {
  project_id: string;
  variants: Record<string, unknown>;
}

/** Copyright-free music recommendations + provider availability. */
export interface MusicRecommendations {
  project_id: string;
  music: Record<string, unknown>;
}

/** One downloadable (or honestly-unavailable) asset in a publish package. */
export interface PackageAsset {
  kind: string;
  status: "available" | "unavailable";
  storage_key?: string;
  reason?: string;
  note?: string;
}

/** A single clip's publish package. */
export interface PublishPackage {
  clip_id: string;
  title?: string;
  assets: PackageAsset[];
  available_assets: string[];
  complete: boolean;
}

/** All publish packages for a project. */
export interface PackageList {
  project_id: string;
  package_count: number;
  packages: PublishPackage[];
}

/** A single clip's publish package. */
export interface PackageResponse {
  project_id: string;
  package: PublishPackage;
}


/* -------------------------------------------------------------------------- */
/* Rendering Engine - deterministic execution into real MP4s                  */
/* -------------------------------------------------------------------------- */

/**
 * Honest status of a single render stage. `unavailable` means the renderer or a
 * dependency (e.g. FFmpeg) is absent - the stage reports the exact reason and no
 * file is fabricated. `failed` is reserved for genuine execution errors.
 */
export type RenderStageStatus =
  | "pending"
  | "running"
  | "completed"
  | "unavailable"
  | "failed"
  | "cancelled";

/** Overall status of a project's render run. */
export type RenderRunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";

/** One render stage and its honest result. */
export interface RenderStage {
  stage: string;
  label: string;
  status: RenderStageStatus;
  version: string;
  progress: number;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  reason: string | null;
  data: Record<string, unknown> | null;
}

/** A project's complete, evolving render run. */
export interface RenderRun {
  project_id: string;
  pipeline_version: string;
  status: RenderRunStatus;
  created_at: string;
  updated_at: string;
  completed_stages: number;
  total_stages: number;
  stages: RenderStage[];
}

/** One rendered clip described in the render manifest. */
export interface RenderedVideo {
  clip_id: string;
  storage_key: string;
  plan_id?: string | null;
  rank?: number | null;
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  video_codec?: string | null;
  audio_codec?: string | null;
  has_audio?: boolean | null;
  bitrate_kbps?: number | null;
  size_bytes?: number | null;
  checksum?: string | null;
  subtitles_included?: boolean | null;
  music_included?: boolean | null;
}

/** The published render manifest (the contract the Optimization Engine consumes). */
export interface RenderManifestResponse {
  project_id: string;
  manifest: {
    render_id?: string | null;
    status: string;
    renderer: string;
    rendering_version?: string | null;
    timeline_version?: string | null;
    created_at?: string;
    updated_at?: string;
    renders: RenderedVideo[];
  };
}

/** The final render validation report. */
export interface RenderValidation {
  project_id: string;
  report: Record<string, unknown>;
}

/** Per-stage render logs, in pipeline order. */
export interface RenderLogs {
  project_id: string;
  stages: {
    stage: string;
    status: string;
    lines: string[];
    reason: string | null;
    error: string | null;
  }[];
}


/* -------------------------------------------------------------------------- */
/* Workflow Orchestration Engine - the central nervous system                 */
/* -------------------------------------------------------------------------- */

/** Honest lifecycle status of a single job (never fabricated). */
export type JobStatus =
  | "pending"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "dead"
  | "blocked";

/** Overall status of a project's workflow. */
export type WorkflowStatus =
  | "pending"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

/** Worker health status. */
export type WorkerStatus = "idle" | "busy" | "offline";

/** A structured log line attached to a job. */
export interface JobLogLine {
  ts: string;
  level: string;
  message: string;
}

/** One orchestrated job, bound to a single engine stage. */
export interface WorkflowJob {
  job_id: string;
  workflow_id: string;
  project_id: string;
  engine: string;
  stage: string;
  priority: number;
  status: JobStatus;
  depends_on: string[];
  attempts: number;
  max_attempts: number;
  worker_id: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  available_at: string | null;
  scheduled_for: string | null;
  duration_ms: number | null;
  error: string | null;
  result: Record<string, unknown>;
  logs: JobLogLine[];
}

/** An entry on the workflow's execution history / event stream. */
export interface WorkflowEvent {
  ts: string;
  type: string;
  message: string;
  stage: string | null;
  job_id: string | null;
  detail: Record<string, unknown>;
}

/** The dependency DAG (nodes + edges) for the dashboard graph. */
export interface ExecutionGraph {
  nodes: {
    stage: string;
    engine: string;
    label: string;
    status: JobStatus;
    attempts: number;
    duration_ms: number | null;
  }[];
  edges: { from: string; to: string }[];
}

/** A project's complete, recoverable workflow state. */
export interface Workflow {
  workflow_id: string;
  project_id: string;
  status: WorkflowStatus;
  created_at: string;
  updated_at: string;
  current_stage: string | null;
  overall_progress: number;
  completed_stages: string[];
  failed_stages: string[];
  pending_stages: string[];
  estimated_remaining_seconds: number;
  retry_count: number;
  total_retries: number;
  jobs: WorkflowJob[];
  history: WorkflowEvent[];
  execution_graph: ExecutionGraph;
}

/** A worker's registration and health snapshot. */
export interface WorkflowWorker {
  worker_id: string;
  status: WorkerStatus;
  registered_at: string | null;
  last_heartbeat: string | null;
  current_job_id: string | null;
  jobs_completed: number;
  jobs_failed: number;
}

export interface WorkersResponse {
  workers: WorkflowWorker[];
}

/** Queue/scheduler snapshot. */
export interface SchedulerStatus {
  queue: {
    ready: number;
    running: number;
    pending: number;
    delayed: number;
    completed: number;
    failed: number;
    dead: number;
    blocked: number;
    cancelled: number;
    active_workflows: number;
  };
  pool_running: boolean;
  worker_count: number;
}

export interface WorkflowHistoryResponse {
  project_id: string;
  history: WorkflowEvent[];
}

export interface JobLogsResponse {
  project_id: string;
  job_id: string;
  logs: JobLogLine[];
}
