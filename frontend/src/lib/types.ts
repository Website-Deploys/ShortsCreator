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
  source_type: string;
  source_url: string | null;
  link_ingestion_id: string | null;
  desired_clip_count: number | null;
  content_category: string;
  editing_intensity: string;
  music_enabled: boolean;
  sfx_enabled: boolean;
  captions_enabled: boolean;
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
  desired_clip_count?: number | null;
  content_category?: string;
  editing_intensity?: string;
  music_enabled?: boolean;
  sfx_enabled?: boolean;
  captions_enabled?: boolean;
}

export interface CreateProjectFromLinkInput {
  url: string;
  permission_confirmed: boolean;
  start_processing?: boolean;
  quality?: "best";
  mode?: "metadata_only" | "download_only" | "full_pipeline";
  desired_clip_count?: number | null;
  content_category?: string;
  editing_intensity?: string;
  music_enabled?: boolean;
  sfx_enabled?: boolean;
  captions_enabled?: boolean;
}

export interface LinkDownloadStatus {
  ingestion_id: string;
  status: string;
  url: string;
  original_url: string;
  reason: string | null;
  filename: string | null;
  storage_key: string | null;
  size_bytes: number | null;
  video_format: string | null;
  content_type: string | null;
  project_id: string | null;
  job_id?: string | null;
  status_url?: string | null;
  resume_url?: string | null;
  link_source: {
    platform?: string;
    video_id?: string;
    url_type?: string;
    validation_status?: string;
    validation_warnings?: string[];
  };
  video_metadata: {
    title?: string | null;
    channel?: string | null;
    uploader?: string | null;
    duration?: number | null;
    thumbnail_url?: string | null;
    availability?: string | null;
    is_live?: boolean;
  };
  download_selection: {
    selected_resolution?: string | null;
    selected_video_codec?: string | null;
    selected_audio_codec?: string | null;
    selected_container?: string | null;
    estimated_filesize?: number | null;
    selection_reason?: string | null;
  };
  link_ingestion_status: {
    status?: string;
    progress_percent?: number | null;
    downloaded_bytes?: number | null;
    total_bytes?: number | null;
    speed?: number | null;
    eta_seconds?: number | null;
    current_stage?: string;
    error_code?: string | null;
    error_message?: string | null;
  };
  rights_confirmation: {
    confirmed?: boolean;
    confirmed_at?: string | null;
    source?: string;
  };
  media_probe: Record<string, unknown> | null;
  error: {
    code?: string;
    user_message?: string;
    developer_message?: string;
    retryable?: boolean;
    stage?: string;
    suggestion?: string;
  } | null;
  warnings: string[];
}

export interface CreateProjectFromLinkResponse {
  download: LinkDownloadStatus;
  project: Project | null;
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

export type AnalysisSignalState =
  | "available"
  | "partial"
  | "fallback"
  | "unavailable"
  | "failed"
  | "skipped";

export interface AnalysisSignalStatus {
  signal_name: string;
  available: boolean;
  status: AnalysisSignalState;
  confidence: number;
  provider: string;
  fallback_used: boolean;
  reason: string | null;
  warnings: string[];
  metadata: Record<string, unknown>;
}

export interface AnalysisSignalHealth {
  project_id: string;
  source_id: string;
  created_at: string;
  total_signals: number;
  available_count: number;
  partial_count: number;
  fallback_count: number;
  unavailable_count: number;
  failed_count: number;
  signals: AnalysisSignalStatus[];
  warnings: string[];
  blockers: Array<{ signal_name: string; reason: string }>;
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
  signal_health?: AnalysisSignalHealth | null;
  analysis_signals_v2?: Record<string, unknown> | null;
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

/** The persisted Internet Trend Research V2 project snapshot. */
export interface TrendResearchResponse {
  project_id: string;
  internet_trend_research_v2: Record<string, unknown>;
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
  overall_score?: number;
  hook_score?: number;
  retention_score?: number;
  clarity_score?: number;
  payoff_score?: number;
  virality_score?: number;
  emotion_score?: number;
  uniqueness_score?: number;
  platform_score?: number;
  confidence: number;
  source?: string;
  source_candidate_type?: string | null;
  transcript_excerpt?: string | null;
  hook_line?: string | null;
  duplicate_group?: string | null;
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

/** One ranked title candidate produced by Upload Metadata V2. */
export interface UploadTitleCandidate {
  text: string;
  platform: string;
  pattern: string;
  hook_category: string;
  truth_score: number;
  curiosity_score: number;
  clarity_score: number;
  safety_score: number;
  length: number;
  warnings: string[];
}

/** Stable platform-specific copy attached to a finished render. */
export interface UploadMetadataV2 {
  metadata_id: string;
  project_id: string;
  clip_id: string;
  render_id?: string | null;
  created_at: string;
  generator_version: string;
  status: "ready" | "generated_needs_review" | "not_ready" | "invalid" | "unavailable";
  reason?: string | null;
  input_signals: Record<string, unknown>;
  youtube_shorts: {
    title: string;
    title_variants: UploadTitleCandidate[];
    description: string;
    hashtags: string[];
    pinned_comment?: string | null;
    safety_warnings: string[];
    confidence: number;
  };
  instagram_reels: {
    caption: string;
    caption_variants: string[];
    hashtags: string[];
    safety_warnings: string[];
    confidence: number;
  };
  tiktok: {
    caption: string;
    caption_variants: string[];
    hashtags: string[];
    safety_warnings: string[];
    confidence: number;
  };
  universal: Record<string, unknown>;
  upload_metadata_personalization?: Record<string, unknown>;
  validation: Record<string, unknown>;
  artifact: Record<string, unknown>;
}

export type CreatorRating = "like" | "dislike" | "neutral";

export interface CreatorProfileV2 {
  profile_id: string;
  profile_name: string;
  preset_id: string;
  version: "2";
  created_at: string;
  updated_at: string;
  learning: {
    enabled: boolean;
    explicit_feedback_only: true;
    total_feedback_count: number;
    last_feedback_at?: string | null;
    confidence: number;
  };
  channel_context: Record<string, unknown>;
  clip_selection_preferences: Record<string, unknown>;
  editing_preferences: Record<string, unknown> & {
    style_preset?: string;
    pacing?: string;
    motion_intensity?: number;
    zoom_intensity?: number;
    sfx_intensity?: number;
    caption_intensity?: number;
    music_intensity?: number;
  };
  caption_preferences: Record<string, unknown> & {
    style?: string;
    casing?: string;
    highlight_density?: number;
    max_words_per_line?: number;
  };
  music_preferences: Record<string, unknown> & {
    preferred_moods?: string[];
    music_presence?: string;
    max_loudness?: number;
  };
  motion_preferences: Record<string, unknown> & {
    preferred_styles?: string[];
    intensity?: number;
  };
  upload_metadata_preferences: Record<string, unknown> & { title_style?: string };
  safety_preferences: Record<string, unknown>;
  learned_patterns: Record<string, unknown>;
  privacy: {
    local_only: true;
    no_sensitive_data: true;
    no_cloud_sync: true;
    exportable: boolean;
    resettable: boolean;
  };
}

export interface CreatorProfilesResponse {
  profiles: CreatorProfileV2[];
  active_profile_id: string;
  presets: string[];
  privacy: CreatorProfileV2["privacy"];
}

export interface CreatorPersonalizationSummary {
  version: "2";
  enabled: boolean;
  active_profile: CreatorProfileV2;
  profile_count: number;
  feedback_count: number;
  presets: string[];
  privacy: CreatorProfileV2["privacy"];
  message: string;
}

export interface CreatorProfileExportResponse {
  profile: CreatorProfileV2;
  exported: boolean;
  filename: string;
}

export interface ClipFeedbackInput {
  profile_id: string;
  project_id: string;
  clip_id: string;
  rating: {
    overall: CreatorRating;
    clip_selection?: CreatorRating;
    hook?: CreatorRating;
    story?: CreatorRating;
    captions?: CreatorRating;
    editing?: CreatorRating;
    music?: CreatorRating;
    motion?: CreatorRating;
    title_metadata?: CreatorRating;
  };
  labels?: string[];
  notes?: string;
  clip_traits?: {
    hook_category?: string;
    title_pattern?: string;
    caption_style?: string;
    music_mood?: string;
    motion_style?: string;
    clip_traits?: string[];
  };
}

export interface ClipFeedbackV2 extends ClipFeedbackInput {
  feedback_id: string;
  created_at: string;
  version: "2";
  extracted_safe_learning: Record<string, string[]>;
  applied_to_profile: boolean;
}

export interface PersonalizationSummaryV2 {
  applied: boolean;
  profile_id?: string | null;
  profile_name?: string | null;
  confidence?: number | null;
  affected_systems?: string[];
  key_adjustments?: Array<Record<string, unknown>>;
  warnings?: string[];
  reasons?: string[];
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
  metadata?: Record<string, unknown> & {
    upload_metadata_v2?: UploadMetadataV2;
    personalization_applied_v2?: PersonalizationSummaryV2;
  };
}

export interface BobaBrainStateV1 {
  brain_id: string;
  project_id: string;
  created_at: string;
  updated_at: string;
  version: "1";
  mode: "observe_only" | "advise" | "influence_planning" | "influence_editing" | "full_brain";
  confidence: number;
  source_understanding: {
    source_type: string;
    duration_seconds?: number | null;
    transcript_available: boolean;
    visual_signals_available: boolean;
    speaker_signals_available: boolean;
    trend_signals_available: boolean;
    safety_signals_available: boolean;
    personalization_signals_available: boolean;
    missing_signals: string[];
    warnings: string[];
  };
  project_memory_summary: {
    main_topics: string[];
    story_threads: string[];
    unused_opportunities: string[];
    warnings: string[];
  };
  decision_context: {
    content_niche: string;
    safety_status: string;
    trend_provider_status: string;
    personalization_status: string;
    known_limitations: string[];
  };
  decisions: Array<Record<string, unknown>>;
  result: {
    ready_for_planning: boolean;
    ready_for_editing: boolean;
    ready_for_rendering: boolean;
    blockers: string[];
    warnings: string[];
  };
}

export interface BobaProjectMemoryV1 {
  project_id: string;
  created_at: string;
  updated_at: string;
  version: "1";
  source_summary: string;
  video_duration?: number | null;
  main_topics: string[];
  speakers_or_roles: string[];
  story_threads: string[];
  emotional_moments: string[];
  candidate_count: number;
  selected_clip_ids: string[];
  rejected_clip_ids: string[];
  used_source_ranges: Array<{ start: number; end: number }>;
  unused_opportunities: string[];
  decisions_count: number;
  feedback_count: number;
  known_limitations: string[];
  memory_records: string[];
  warnings: string[];
}

export interface BobaCreatorMemoryV1 {
  creator_memory_id: string;
  creator_profile_id: string;
  created_at: string;
  updated_at: string;
  version: "1";
  learning_enabled: boolean;
  explicit_feedback_only: true;
  style_summary: string;
  preferred_clip_traits: string[];
  avoided_clip_traits: string[];
  preferred_hook_styles: string[];
  avoided_hook_styles: string[];
  preferred_title_styles: string[];
  avoided_title_styles: string[];
  preferred_caption_styles: string[];
  avoided_caption_styles: string[];
  preferred_music_moods: string[];
  avoided_music_moods: string[];
  preferred_motion_styles: string[];
  avoided_motion_styles: string[];
  banned_hashtags: string[];
  preferred_hashtags: string[];
  known_good_patterns: string[];
  known_bad_patterns: string[];
  feedback_count: number;
  confidence: number;
  warnings: string[];
}

export interface BobaGlobalMemoryV1 {
  global_memory_id: string;
  created_at: string;
  updated_at: string;
  version: "1";
  principles: string[];
  platform_patterns: string[];
  hook_patterns: string[];
  editing_patterns: string[];
  caption_patterns: string[];
  music_patterns: string[];
  motion_patterns: string[];
  metadata_patterns: string[];
  safety_principles: string[];
  known_limitations: string[];
  source_attribution: string[];
  confidence: number;
  warnings: string[];
}

export type BobaRightsStatus =
  | "unknown"
  | "user_owned"
  | "permission_confirmed"
  | "licensed"
  | "not_allowed";

export type BobaCandidateStatus =
  | "idea_only"
  | "approved_for_review"
  | "approved_for_processing"
  | "rejected"
  | "archived";

export interface BobaCandidateV1 {
  candidate_id: string;
  source_type:
    | "manual_link"
    | "manual_metadata"
    | "json_import"
    | "csv_import"
    | "official_api_metadata";
  title: string;
  url?: string | null;
  creator: string;
  duration_seconds?: number | null;
  published_at?: string | null;
  metadata: Record<string, unknown>;
  rights_status: BobaRightsStatus;
  permission_confirmed: boolean;
  status: BobaCandidateStatus;
  created_at: string;
}

export interface BobaScoutScoreV1 {
  candidate_id: string;
  overall_score: number;
  hook_potential: number;
  emotional_potential: number;
  novelty_score: number;
  clarity_score: number;
  clipping_potential: number;
  risk_score: number;
  reasons: string[];
  warnings: string[];
  recommended_action:
    | "idea_only"
    | "review_rights_first"
    | "approve_for_review"
    | "process_now"
    | "do_not_process";
}

export interface BobaCandidatesResponse {
  count: number;
  candidates: BobaCandidateV1[];
  scores: Record<string, BobaScoutScoreV1>;
  metadata_only: true;
  external_calls_made: false;
}

export type BobaScoutImportSourceTypeV2 =
  | "csv"
  | "json"
  | "manual"
  | "test_synthetic";

export type BobaScoutRightsStatusV2 =
  | "owned"
  | "licensed"
  | "permission_granted"
  | "permission_needed"
  | "unknown"
  | "blocked";

export type BobaScoutRecommendationTypeV2 =
  | "review_now"
  | "save_for_later"
  | "seek_permission"
  | "reject"
  | "blocked";

export type BobaScoutPriorityV2 = "low" | "medium" | "high" | "urgent";

export interface BobaScoutImportSourceV2 {
  import_id: string;
  source_type: BobaScoutImportSourceTypeV2;
  source_label: string;
  source_path: string;
  imported_at: string;
  item_count: number;
  accepted_count: number;
  rejected_count: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaScoutItemV2 {
  item_id: string;
  title: string;
  description: string;
  source_label: string;
  source_reference: string;
  source_url: string | null;
  duration_seconds: number | null;
  tags: string[];
  categories: string[];
  creator_or_channel: string;
  published_at: string;
  rights_status: BobaScoutRightsStatusV2;
  permission_notes: string;
  user_notes: string;
  raw_metadata_summary: Record<string, unknown>;
  warnings: string[];
}

export interface BobaScoutScoreV2 {
  item_id: string;
  creator_fit_score: number;
  topic_fit_score: number;
  shortability_score: number;
  hook_potential_score: number;
  emotional_story_score: number;
  trend_context_score: number;
  novelty_score: number;
  rights_readiness_score: number;
  review_priority_score: number;
  confidence: number;
  score_reasons: string[];
  warnings: string[];
}

export interface BobaSuggestedShortAngleV2 {
  angle_id: string;
  title: string;
  hook_direction: string;
  why_it_might_work: string;
  risk: string;
  confidence: number;
}

export interface BobaScoutRecommendationV2 {
  item_id: string;
  recommendation: BobaScoutRecommendationTypeV2;
  priority: BobaScoutPriorityV2;
  reason: string;
  suggested_short_angles: BobaSuggestedShortAngleV2[];
  suggested_review_questions: string[];
  rights_review_required: boolean;
  human_review_required: boolean;
  warnings: string[];
  limitations: string[];
}

export interface BobaScoutReviewQueueV2 {
  top_items: BobaScoutRecommendationV2[];
  backup_items: BobaScoutRecommendationV2[];
  permission_needed_items: BobaScoutRecommendationV2[];
  blocked_items: BobaScoutRecommendationV2[];
  duplicate_or_similar_items: BobaScoutRecommendationV2[];
  queue_summary: string;
  warnings: string[];
}

export interface BobaScoutRejectedItemV2 {
  item_id: string;
  reason_rejected: string;
  risk: string;
  warnings: string[];
}

export interface BobaContentScoutSummaryV2 {
  total_items: number;
  review_now_count: number;
  save_for_later_count: number;
  permission_needed_count: number;
  blocked_count: number;
  strongest_topics: string[];
  weakest_topics: string[];
  repeated_themes: string[];
  rights_summary: string[];
  human_review_notes: string[];
}

export interface BobaContentScoutSignalUsageV2 {
  scout_v1_used: boolean;
  creator_learning_used: boolean;
  approval_rejection_learning_used: boolean;
  performance_feedback_used: boolean;
  memory_used: boolean;
  local_import_used: boolean;
  external_api_used: false;
  url_fetching_used: false;
  downloading_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaContentScoutSetV2 {
  schema_version: "boba_content_scout_v2";
  project_id: string;
  source_id: string;
  created_at: string;
  imported_sources: BobaScoutImportSourceV2[];
  scout_items: BobaScoutItemV2[];
  scored_items: BobaScoutScoreV2[];
  review_queue: BobaScoutReviewQueueV2;
  rejected_items: BobaScoutRejectedItemV2[];
  scout_summary: BobaContentScoutSummaryV2;
  signal_usage: BobaContentScoutSignalUsageV2;
  warnings: string[];
  limitations: string[];
}

export interface BobaContentScoutGenerateInputV2 {
  manual_items?: Record<string, unknown>[];
  import_paths?: string[];
  source_label?: string;
  dry_run?: boolean;
}

export type BobaResearchSourceTypeV1 =
  | "txt"
  | "md"
  | "csv"
  | "json"
  | "manual"
  | "pasted_text"
  | "test_synthetic";

export type BobaResearchInsightTypeV1 =
  | "topic"
  | "audience_pain"
  | "audience_desire"
  | "controversy"
  | "tension"
  | "story_angle"
  | "hook_angle"
  | "format_idea"
  | "caution"
  | "verification_needed";

export type BobaResearchFormatStyleV1 =
  | "story"
  | "explainer"
  | "list"
  | "comparison"
  | "myth_vs_fact"
  | "mistake_to_avoid"
  | "reaction"
  | "tutorial"
  | "transformation"
  | "interview_clip"
  | "commentary"
  | "unknown";

export interface BobaResearchImportSourceV1 {
  import_id: string;
  source_type: BobaResearchSourceTypeV1;
  source_label: string;
  source_path: string;
  imported_at: string;
  item_count: number;
  accepted_count: number;
  rejected_count: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaResearchEvidenceSnippetV1 {
  snippet_id: string;
  source_id: string;
  snippet: string;
  topic_tags: string[];
  start_hint: string;
  confidence: number;
  usage_warning: string;
}

export interface BobaResearchSourceV1 {
  research_source_id: string;
  source_type: BobaResearchSourceTypeV1;
  source_label: string;
  title: string;
  author_or_source_name: string;
  published_at: string;
  topic_tags: string[];
  rights_usage_notes: string;
  user_notes: string;
  content_summary: string;
  evidence_snippets: BobaResearchEvidenceSnippetV1[];
  warnings: string[];
  limitations: string[];
}

export interface BobaResearchInsightV1 {
  insight_id: string;
  insight_type: BobaResearchInsightTypeV1;
  summary: string;
  source_ids: string[];
  evidence: BobaResearchEvidenceSnippetV1[];
  content_opportunity: string;
  risk: string;
  confidence: number;
  human_verification_required: boolean;
  warnings: string[];
}

export interface BobaResearchShortsIdeaV1 {
  idea_id: string;
  title: string;
  topic: string;
  hook_direction: string;
  target_viewer: string;
  format_style: BobaResearchFormatStyleV1;
  why_it_might_work: string;
  source_ids: string[];
  evidence: BobaResearchEvidenceSnippetV1[];
  risk: string;
  confidence: number;
  human_review_required: boolean;
}

export interface BobaResearchSafetyReviewV1 {
  weak_evidence_warnings: string[];
  unverifiable_claim_warnings: string[];
  copyrighted_content_warnings: string[];
  sensitive_topic_warnings: string[];
  rights_usage_warnings: string[];
  human_verification_notes: string[];
  blockers: string[];
  warnings: string[];
}

export interface BobaContentScoutResearchHandoffV1 {
  recommended_topics: string[];
  recommended_keywords: string[];
  suggested_content_categories: string[];
  avoid_topics: string[];
  rights_review_reminders: string[];
  suggested_review_questions: string[];
  scout_item_notes: string[];
  apply_automatically: false;
}

export interface BobaResearchSummaryV1 {
  total_sources: number;
  total_insights: number;
  total_shorts_ideas: number;
  strongest_topics: string[];
  repeated_themes: string[];
  strongest_audience_problems: string[];
  strongest_hook_angles: string[];
  weak_or_risky_claims: string[];
  human_review_notes: string[];
}

export interface BobaResearchSignalUsageV1 {
  content_scout_used: boolean;
  creator_learning_used: boolean;
  approval_rejection_learning_used: boolean;
  performance_feedback_used: boolean;
  memory_used: boolean;
  local_import_used: boolean;
  manual_input_used: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaResearchBrainSetV1 {
  schema_version: "boba_research_brain_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  imported_sources: BobaResearchImportSourceV1[];
  research_sources: BobaResearchSourceV1[];
  research_insights: BobaResearchInsightV1[];
  shorts_ideas: BobaResearchShortsIdeaV1[];
  safety_review: BobaResearchSafetyReviewV1;
  content_scout_handoff: BobaContentScoutResearchHandoffV1;
  research_summary: BobaResearchSummaryV1;
  signal_usage: BobaResearchSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaResearchBrainGenerateInputV1 {
  manual_sources?: Record<string, unknown>[];
  pasted_text_entries?: (string | Record<string, unknown>)[];
  import_paths?: string[];
  source_label?: string;
  dry_run?: boolean;
}

export type BobaTrendTopicSourceTypeV1 =
  | "csv"
  | "json"
  | "manual"
  | "pasted_text"
  | "research_brain"
  | "content_scout"
  | "test_synthetic";

export type BobaTopicMovementTypeV1 =
  | "repeated"
  | "new"
  | "rising_within_provided_data"
  | "fading_within_provided_data"
  | "stable"
  | "duplicate_or_similar"
  | "uncertain";

export interface BobaTrendTopicImportSourceV1 {
  import_id: string;
  source_type: BobaTrendTopicSourceTypeV1;
  source_label: string;
  source_path: string;
  imported_at: string;
  item_count: number;
  accepted_count: number;
  rejected_count: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaTopicEntryV1 {
  topic_id: string;
  topic: string;
  normalized_topic: string;
  description: string;
  tags: string[];
  categories: string[];
  user_rank: number | null;
  user_frequency: number | null;
  user_score: number | null;
  source_label: string;
  evidence_note: string;
  rights_safety_note: string;
  warnings: string[];
}

export interface BobaTopicSnapshotV1 {
  snapshot_id: string;
  source_label: string;
  captured_at: string;
  platform_label: string;
  topics: BobaTopicEntryV1[];
  source_notes: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaTopicMovementItemV1 {
  topic: string;
  normalized_topic: string;
  movement_type: BobaTopicMovementTypeV1;
  snapshot_count: number;
  previous_score: number | null;
  latest_score: number | null;
  delta: number | null;
  evidence_sources: string[];
  reason: string;
  confidence: number;
  warnings: string[];
}

export interface BobaTopicMovementAnalysisV1 {
  repeated_topics: BobaTopicMovementItemV1[];
  newly_appearing_topics: BobaTopicMovementItemV1[];
  rising_topics_within_provided_data: BobaTopicMovementItemV1[];
  fading_topics_within_provided_data: BobaTopicMovementItemV1[];
  stable_topics: BobaTopicMovementItemV1[];
  duplicate_or_similar_topics: BobaTopicMovementItemV1[];
  uncertain_topics: BobaTopicMovementItemV1[];
  analysis_notes: string[];
  warnings: string[];
}

export interface BobaTopicOpportunityScoreV1 {
  topic: string;
  normalized_topic: string;
  creator_fit_score: number;
  research_support_score: number;
  scout_support_score: number;
  shortability_score: number;
  hook_potential_score: number;
  freshness_within_user_data_score: number;
  risk_score: number;
  overall_topic_priority_score: number;
  confidence: number;
  reasons: string[];
  warnings: string[];
}

export interface BobaWatchedTopicV1 {
  watched_topic_id: string;
  topic: string;
  normalized_topic: string;
  reason_for_watch: string;
  creator_fit: number;
  research_fit: number;
  scout_fit: number;
  content_angle_potential: number;
  suggested_angles: string[];
  human_review_notes: string[];
  confidence: number;
  warnings: string[];
}

export interface BobaTrendConfidenceReviewV1 {
  overall_confidence: number;
  snapshot_count: number;
  source_count: number;
  strongest_evidence: string[];
  weakest_evidence: string[];
  not_real_time_verified: true;
  weak_data_warnings: string[];
  human_verification_notes: string[];
  warnings: string[];
}

export interface BobaTrendContentScoutHandoffV1 {
  recommended_scout_topics: string[];
  recommended_keywords: string[];
  recommended_categories: string[];
  topics_to_avoid: string[];
  rights_review_reminders: string[];
  scout_review_questions: string[];
  apply_automatically: false;
}

export interface BobaTrendResearchBrainHandoffV1 {
  recommended_research_topics: string[];
  claims_to_verify: string[];
  audience_questions_to_research: string[];
  sources_needed: string[];
  apply_automatically: false;
}

export interface BobaTrendWatcherSummaryV1 {
  total_snapshots: number;
  total_topics: number;
  watched_topic_count: number;
  rising_count: number;
  repeated_count: number;
  fading_count: number;
  strongest_topics: string[];
  riskiest_topics: string[];
  human_review_notes: string[];
}

export interface BobaTrendTopicSignalUsageV1 {
  research_brain_used: boolean;
  content_scout_used: boolean;
  creator_learning_used: boolean;
  performance_feedback_used: boolean;
  memory_used: boolean;
  local_import_used: boolean;
  manual_input_used: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  platform_monitoring_used: false;
  downloading_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaTrendTopicWatcherSetV1 {
  schema_version: "boba_trend_topic_watcher_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  imported_sources: BobaTrendTopicImportSourceV1[];
  topic_snapshots: BobaTopicSnapshotV1[];
  watched_topics: BobaWatchedTopicV1[];
  movement_analysis: BobaTopicMovementAnalysisV1;
  opportunity_scores: BobaTopicOpportunityScoreV1[];
  confidence_review: BobaTrendConfidenceReviewV1;
  content_scout_handoff: BobaTrendContentScoutHandoffV1;
  research_brain_handoff: BobaTrendResearchBrainHandoffV1;
  watcher_summary: BobaTrendWatcherSummaryV1;
  signal_usage: BobaTrendTopicSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaTrendTopicWatcherGenerateInputV1 {
  manual_snapshots?: Record<string, unknown>[];
  pasted_topic_lists?: (string | Record<string, unknown>)[];
  import_paths?: string[];
  source_label?: string;
  dry_run?: boolean;
}

export type BobaCandidateVideoSourceTypeV1 =
  | "csv"
  | "json"
  | "manual"
  | "content_scout_v2"
  | "research_brain"
  | "trend_topic_watcher"
  | "test_synthetic";

export type BobaCandidateRightsStatusV1 =
  | "owned"
  | "licensed"
  | "permission_granted"
  | "permission_needed"
  | "unknown"
  | "blocked";

export type BobaCandidateRightsReadinessV1 =
  | "ready_for_review"
  | "needs_permission"
  | "unknown_needs_review"
  | "blocked";

export type BobaCandidateVideoRecommendationTypeV1 =
  | "review_now"
  | "save_for_later"
  | "seek_permission"
  | "reject"
  | "blocked";

export type BobaCandidateVideoPriorityV1 =
  | "low"
  | "medium"
  | "high"
  | "urgent";

export interface BobaCandidateVideoImportSourceV1 {
  import_id: string;
  source_type: BobaCandidateVideoSourceTypeV1;
  source_label: string;
  source_path: string;
  imported_at: string;
  item_count: number;
  accepted_count: number;
  rejected_count: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaCandidateVideoV1 {
  candidate_video_id: string;
  title: string;
  description: string;
  source_label: string;
  source_reference: string;
  source_url: string | null;
  duration_seconds: number | null;
  creator_or_channel: string;
  published_at: string;
  topic_tags: string[];
  categories: string[];
  rights_status: BobaCandidateRightsStatusV1;
  permission_notes: string;
  user_notes: string;
  source_artifact_refs: string[];
  raw_metadata_summary: Record<string, unknown>;
  warnings: string[];
  limitations: string[];
}

export interface BobaCandidateVideoScoreV1 {
  candidate_video_id: string;
  creator_fit_score: number;
  topic_opportunity_score: number;
  research_support_score: number;
  trend_support_score: number;
  shortability_score: number;
  hook_potential_score: number;
  story_potential_score: number;
  format_fit_score: number;
  rights_readiness_score: number;
  risk_score: number;
  review_priority_score: number;
  overall_candidate_score: number;
  confidence: number;
  score_reasons: string[];
  warnings: string[];
}

export interface BobaShortsPotentialReviewV1 {
  candidate_video_id: string;
  possible_clip_types: string[];
  possible_hook_directions: string[];
  possible_story_angles: string[];
  possible_format_styles: string[];
  emotional_story_promise: string;
  likely_weaknesses: string[];
  human_review_questions: string[];
  confidence: number;
  warnings: string[];
}

export interface BobaCandidateRightsReviewV1 {
  candidate_video_id: string;
  rights_status: BobaCandidateRightsStatusV1;
  rights_readiness: BobaCandidateRightsReadinessV1;
  rights_review_required: boolean;
  permission_required: boolean;
  blocked: boolean;
  reason: string;
  human_review_notes: string[];
  warnings: string[];
}

export interface BobaCandidateVideoRecommendationV1 {
  candidate_video_id: string;
  recommendation: BobaCandidateVideoRecommendationTypeV1;
  priority: BobaCandidateVideoPriorityV1;
  reason: string;
  shorts_potential: BobaShortsPotentialReviewV1;
  rights_review: BobaCandidateRightsReviewV1;
  next_human_action: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaScoredCandidateVideoV1 {
  candidate_video: BobaCandidateVideoV1;
  score: BobaCandidateVideoScoreV1;
  shorts_potential: BobaShortsPotentialReviewV1;
  rights_review: BobaCandidateRightsReviewV1;
  recommendation: BobaCandidateVideoRecommendationV1;
  duplicate_of_candidate_video_id: string | null;
}

export interface BobaCandidateVideoReviewQueueV1 {
  top_candidates: BobaCandidateVideoRecommendationV1[];
  backup_candidates: BobaCandidateVideoRecommendationV1[];
  permission_needed_candidates: BobaCandidateVideoRecommendationV1[];
  blocked_candidates: BobaCandidateVideoRecommendationV1[];
  duplicate_or_similar_candidates: BobaCandidateVideoRecommendationV1[];
  rejected_candidates: BobaCandidateVideoRecommendationV1[];
  queue_summary: string;
  warnings: string[];
}

export interface BobaCandidateVideoHandoffTargetV1 {
  candidate_video_ids: string[];
  topics: string[];
  recommended_actions: string[];
  prerequisites: string[];
  warnings: string[];
  apply_automatically: false;
}

export interface BobaCandidateVideoSourceHandoffV1 {
  content_scout_handoff: BobaCandidateVideoHandoffTargetV1;
  research_brain_handoff: BobaCandidateVideoHandoffTargetV1;
  trend_topic_handoff: BobaCandidateVideoHandoffTargetV1;
  rights_permission_gate_handoff: BobaCandidateVideoHandoffTargetV1;
  future_ingestion_handoff: BobaCandidateVideoHandoffTargetV1;
  apply_automatically: false;
}

export interface BobaCandidateVideoSummaryV1 {
  total_candidates: number;
  review_now_count: number;
  save_for_later_count: number;
  seek_permission_count: number;
  blocked_count: number;
  rejected_count: number;
  strongest_candidates: string[];
  strongest_topics: string[];
  common_risks: string[];
  rights_summary: string[];
  human_review_notes: string[];
}

export interface BobaCandidateVideoSignalUsageV1 {
  content_scout_used: boolean;
  research_brain_used: boolean;
  trend_topic_watcher_used: boolean;
  creator_learning_used: boolean;
  approval_rejection_learning_used: boolean;
  performance_feedback_used: boolean;
  memory_used: boolean;
  local_import_used: boolean;
  manual_input_used: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  media_ingestion_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaCandidateVideoScorerSetV1 {
  schema_version: "boba_candidate_video_scorer_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  imported_sources: BobaCandidateVideoImportSourceV1[];
  candidate_videos: BobaCandidateVideoV1[];
  scored_candidates: BobaScoredCandidateVideoV1[];
  review_queue: BobaCandidateVideoReviewQueueV1;
  scorer_summary: BobaCandidateVideoSummaryV1;
  source_handoffs: BobaCandidateVideoSourceHandoffV1;
  signal_usage: BobaCandidateVideoSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaCandidateVideoScorerGenerateInputV1 {
  manual_candidates?: Record<string, unknown>[];
  import_paths?: string[];
  source_label?: string;
  dry_run?: boolean;
}

export type BobaDeclaredRightsStatusV1 =
  | "owned"
  | "licensed"
  | "permission_granted"
  | "permission_needed"
  | "unknown"
  | "blocked"
  | "public_domain_claimed"
  | "fair_use_claimed";

export type BobaRightsGateStatusV1 =
  | "ready_for_human_review"
  | "needs_permission"
  | "needs_rights_review"
  | "blocked"
  | "insufficient_information";

export type BobaPermissionChecklistCategoryV1 =
  | "ownership"
  | "license"
  | "permission"
  | "platform_terms"
  | "third_party_content"
  | "music_audio"
  | "people_privacy"
  | "source_quality"
  | "final_approval";

export type BobaPermissionChecklistStatusV1 =
  | "passed"
  | "warning"
  | "blocked"
  | "unknown"
  | "not_applicable";

export type BobaOverallRightsRiskV1 =
  | "low"
  | "medium"
  | "high"
  | "blocked"
  | "unknown";

export type BobaIngestionPrecheckStatusV1 =
  | "eligible_for_manual_ingestion_review"
  | "permission_required_before_review"
  | "rights_review_required_before_review"
  | "blocked"
  | "insufficient_information";

export type BobaAllowedNextStepV1 =
  | "human_review_only"
  | "seek_permission"
  | "add_rights_evidence"
  | "do_not_process"
  | "blocked";

export interface BobaRightsEvidenceSnippetV1 {
  evidence_id: string;
  source_artifact: string;
  source_field: string;
  snippet: string;
  confidence: number;
  usage_warning: string;
}

export interface BobaRightsReviewedItemV1 {
  review_item_id: string;
  project_id: string;
  candidate_video_id: string;
  source_item_id: string;
  title: string;
  source_label: string;
  source_reference: string;
  source_url: string | null;
  declared_rights_status: BobaDeclaredRightsStatusV1;
  permission_notes: string;
  license_notes: string;
  ownership_notes: string;
  platform_source_notes: string;
  source_artifact_refs: string[];
  evidence_snippets: BobaRightsEvidenceSnippetV1[];
  missing_evidence: string[];
  warnings: string[];
  limitations: string[];
}

export interface BobaRightsGateDecisionV1 {
  decision_id: string;
  review_item_id: string;
  candidate_video_id: string;
  gate_status: BobaRightsGateStatusV1;
  allow_human_review: boolean;
  allow_future_ingestion_precheck: boolean;
  requires_permission: boolean;
  requires_rights_review: boolean;
  blocked: boolean;
  decision_reason: string;
  required_human_checks: string[];
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaPermissionChecklistItemV1 {
  item_id: string;
  label: string;
  category: BobaPermissionChecklistCategoryV1;
  status: BobaPermissionChecklistStatusV1;
  required: boolean;
  reason: string;
  human_action: string;
}

export interface BobaPermissionChecklistV1 {
  checklist_id: string;
  review_item_id: string;
  ownership_confirmed: boolean;
  license_confirmed: boolean;
  permission_granted: boolean;
  permission_evidence_reference_present: boolean;
  platform_terms_review_needed: boolean;
  third_party_content_review_needed: boolean;
  music_audio_rights_review_needed: boolean;
  people_privacy_release_review_needed: boolean;
  source_quality_review_needed: boolean;
  final_human_approval_required: boolean;
  checklist_items: BobaPermissionChecklistItemV1[];
  warnings: string[];
}

export interface BobaRightsRiskReviewV1 {
  risk_review_id: string;
  review_item_id: string;
  unknown_rights_risk: boolean;
  third_party_media_risk: boolean;
  music_audio_rights_risk: boolean;
  platform_terms_risk: boolean;
  privacy_release_risk: boolean;
  source_ambiguity_risk: boolean;
  copyrighted_source_material_risk: boolean;
  permission_evidence_missing_risk: boolean;
  overall_rights_risk: BobaOverallRightsRiskV1;
  blockers: string[];
  warnings: string[];
  fixes: string[];
}

export interface BobaFutureIngestionHandoffV1 {
  handoff_id: string;
  review_item_id: string;
  candidate_video_id: string;
  ingestion_precheck_status: BobaIngestionPrecheckStatusV1;
  allowed_next_step: BobaAllowedNextStepV1;
  required_before_ingestion: string[];
  blocked_reason: string;
  apply_automatically: false;
  warnings: string[];
}

export interface BobaRightsSummaryV1 {
  total_reviewed: number;
  ready_for_human_review_count: number;
  needs_permission_count: number;
  needs_rights_review_count: number;
  blocked_count: number;
  insufficient_information_count: number;
  common_risks: string[];
  rights_status_breakdown: Record<string, number>;
  human_review_notes: string[];
  limitations: string[];
}

export interface BobaRightsPermissionSignalUsageV1 {
  candidate_video_scorer_used: boolean;
  content_scout_used: boolean;
  research_brain_used: boolean;
  trend_topic_watcher_used: boolean;
  clip_briefs_used: boolean;
  music_mood_used: boolean;
  memory_used: boolean;
  manual_input_used: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  media_ingestion_used: false;
  legal_validation_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaRightsPermissionGateSetV1 {
  schema_version: "boba_rights_permission_gate_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  reviewed_items: BobaRightsReviewedItemV1[];
  gate_decisions: BobaRightsGateDecisionV1[];
  permission_checklists: BobaPermissionChecklistV1[];
  risk_reviews: BobaRightsRiskReviewV1[];
  future_ingestion_handoffs: BobaFutureIngestionHandoffV1[];
  rights_summary: BobaRightsSummaryV1;
  signal_usage: BobaRightsPermissionSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaRightsPermissionGateGenerateInputV1 {
  manual_items?: Record<string, unknown>[];
  source_label?: string;
  dry_run?: boolean;
}

export type BobaObserverFreshnessStatusV1 =
  | "fresh"
  | "stale"
  | "unknown"
  | "missing";

export type BobaObserverIssueLevelV1 =
  | "ok"
  | "info"
  | "warning"
  | "blocker"
  | "unknown";

export interface BobaObserverFindingV1 {
  finding_id: string;
  category:
    | "missing_artifact"
    | "stale_artifact"
    | "unreadable_artifact"
    | "missing_validation"
    | "stale_validation"
    | "broken_dependency"
    | "unsafe_action"
    | "rights_gap"
    | "unknown_state"
    | "info";
  message: string;
  evidence: string[];
  issue_level: BobaObserverIssueLevelV1;
  related_module: string;
  related_artifact: string;
  recommended_followup: string;
}

export interface BobaArtifactObservationV1 {
  artifact_id: string;
  module_name: string;
  artifact_type: string;
  expected_path: string;
  exists: boolean;
  readable: boolean;
  schema_version: string;
  created_at: string;
  freshness_status: BobaObserverFreshnessStatusV1;
  dependency_status:
    | "satisfied"
    | "missing_upstream"
    | "stale_upstream"
    | "unknown"
    | "not_applicable";
  size_bytes: number;
  issue_level: BobaObserverIssueLevelV1;
  findings: BobaObserverFindingV1[];
  warnings: string[];
}

export interface BobaModuleHealthObservationV1 {
  module_name: string;
  module_category:
    | "core"
    | "video_intelligence"
    | "creative"
    | "learning"
    | "scouting"
    | "rights_safety"
    | "self_healing"
    | "frontend"
    | "validation";
  expected_artifacts: string[];
  required_dependencies: string[];
  optional_dependencies: string[];
  health_status:
    | "healthy"
    | "partial"
    | "missing"
    | "stale"
    | "blocked"
    | "unknown";
  missing_inputs: string[];
  missing_outputs: string[];
  stale_outputs: string[];
  blocked_reason: string;
  confidence: number;
  findings: BobaObserverFindingV1[];
  warnings: string[];
}

export interface BobaWorkflowObservationV1 {
  workflow_stage: string;
  completed_modules: string[];
  ready_modules: string[];
  incomplete_modules: string[];
  blocked_modules: string[];
  unsafe_next_actions: string[];
  safe_next_actions: string[];
  findings: BobaObserverFindingV1[];
  warnings: string[];
}

export interface BobaDependencyObservationV1 {
  dependency_id: string;
  downstream_module: string;
  upstream_module: string;
  upstream_artifact: string;
  downstream_artifact: string;
  status: "satisfied" | "missing" | "stale" | "broken" | "unknown";
  reason: string;
  recommended_inspection: string;
  issue_level: BobaObserverIssueLevelV1;
  warnings: string[];
}

export interface BobaValidationObservationV1 {
  validator_name: string;
  report_path: string;
  report_exists: boolean;
  latest_status: "passed" | "failed" | "partial" | "unknown" | "missing";
  report_created_at: string;
  freshness_status: BobaObserverFreshnessStatusV1;
  missing_reason: string;
  issue_level: BobaObserverIssueLevelV1;
  warnings: string[];
}

export interface BobaSafetyObservationV1 {
  safety_id: string;
  safety_area:
    | "rights_permission"
    | "ingestion"
    | "rendering"
    | "downloading"
    | "external_api"
    | "secrets"
    | "destructive_action"
    | "validation_gap"
    | "unknown";
  status: "safe_to_review" | "needs_human_review" | "blocked" | "unknown";
  reason: string;
  related_artifacts: string[];
  required_human_checks: string[];
  unsafe_next_actions: string[];
  warnings: string[];
}

export interface BobaNextActionRecommendationV1 {
  recommendation_id: string;
  action_type:
    | "inspect"
    | "validate"
    | "generate_missing_artifact"
    | "run_future_validator"
    | "human_review"
    | "merge_required"
    | "do_not_process"
    | "blocked"
    | "unknown";
  action: string;
  safe: boolean;
  reason: string;
  prerequisites: string[];
  suggested_owner_module: string;
  human_review_required: boolean;
  priority: "low" | "medium" | "high" | "urgent";
  warnings: string[];
}

export interface BobaObserverSummaryV1 {
  total_modules_observed: number;
  healthy_count: number;
  partial_count: number;
  missing_count: number;
  blocked_count: number;
  stale_count: number;
  unknown_count: number;
  blocker_count: number;
  warning_count: number;
  safest_next_step: string;
  riskiest_next_step: string;
  human_review_notes: string[];
}

export interface BobaObserverSignalUsageV1 {
  boba_store_used: boolean;
  local_artifacts_read: boolean;
  validation_reports_read: boolean;
  rights_gate_used: boolean;
  candidate_video_scorer_used: boolean;
  research_brain_used: boolean;
  content_scout_used: boolean;
  trend_topic_watcher_used: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  command_execution_used: false;
  code_modification_used: false;
  destructive_action_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaObserverSetV1 {
  schema_version: "boba_observer_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  workflow_observations: BobaWorkflowObservationV1[];
  artifact_observations: BobaArtifactObservationV1[];
  module_health_observations: BobaModuleHealthObservationV1[];
  dependency_observations: BobaDependencyObservationV1[];
  validation_observations: BobaValidationObservationV1[];
  safety_observations: BobaSafetyObservationV1[];
  next_action_recommendations: BobaNextActionRecommendationV1[];
  observer_summary: BobaObserverSummaryV1;
  signal_usage: BobaObserverSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaObserverGenerateInputV1 {
  workflow_context?: Record<string, unknown>;
  dry_run?: boolean;
}

export type BobaErrorCategoryV1 =
  | "missing_artifact"
  | "stale_artifact"
  | "corrupt_artifact"
  | "unreadable_artifact"
  | "schema_mismatch"
  | "broken_dependency"
  | "missing_dependency"
  | "configuration"
  | "environment"
  | "validation_failure"
  | "validation_missing"
  | "validation_stale"
  | "rendering"
  | "audio_video_sync"
  | "media_probe"
  | "storage"
  | "permission"
  | "rights_safety"
  | "ingestion"
  | "external_tool"
  | "timeout"
  | "resource_exhaustion"
  | "data_quality"
  | "frontend"
  | "api"
  | "unknown";

export type BobaDiagnosticSeverityV1 =
  | "informational"
  | "low"
  | "medium"
  | "high"
  | "critical"
  | "blocker"
  | "unknown";

export type BobaDiagnosisStatusV1 =
  | "observed_fact"
  | "probable"
  | "possible"
  | "insufficient_evidence"
  | "conflicting_evidence"
  | "unknown";

export interface BobaDiagnosticEvidenceV1 {
  evidence_id: string;
  source_type:
    | "observer_finding"
    | "artifact_observation"
    | "module_health_observation"
    | "dependency_observation"
    | "validation_observation"
    | "safety_observation"
    | "workflow_observation"
    | "manual_context"
    | "unknown";
  source_id: string;
  module_name: string;
  artifact_id: string;
  evidence_summary: string;
  observed_value: string;
  expected_value: string;
  timestamp: string;
  confidence: number;
  usage_warning: string;
}

export interface BobaDiagnosticHypothesisV1 {
  hypothesis_id: string;
  hypothesis: string;
  category:
    | "direct_cause"
    | "contributing_factor"
    | "downstream_effect"
    | "environment_factor"
    | "data_factor"
    | "configuration_factor"
    | "safety_factor"
    | "unknown";
  supporting_evidence_ids: string[];
  conflicting_evidence_ids: string[];
  confidence: number;
  verification_needed: boolean;
  suggested_check: string;
  warnings: string[];
}

export interface BobaDiagnosticCaseV1 {
  diagnostic_case_id: string;
  title: string;
  primary_module: string;
  primary_artifact: string;
  workflow_stage: string;
  error_category: BobaErrorCategoryV1;
  severity: BobaDiagnosticSeverityV1;
  urgency: "later" | "normal" | "soon" | "immediate" | "blocked" | "unknown";
  diagnosis_status: BobaDiagnosisStatusV1;
  symptom_summary: string;
  probable_cause_summary: string;
  confirmed_facts: string[];
  hypotheses: BobaDiagnosticHypothesisV1[];
  affected_modules: string[];
  affected_artifacts: string[];
  related_finding_ids: string[];
  evidence: BobaDiagnosticEvidenceV1[];
  missing_information: string[];
  processing_impact:
    | "none"
    | "degraded"
    | "partial_block"
    | "full_block"
    | "unsafe_to_continue"
    | "unknown";
  safety_impact:
    | "none_known"
    | "human_review_needed"
    | "safety_gate_blocked"
    | "rights_gate_blocked"
    | "destructive_risk"
    | "unknown";
  recommended_investigation: string[];
  escalation_target:
    | "root_cause_analyzer"
    | "repair_planner"
    | "tool_recovery_brain"
    | "output_quality_reviewer"
    | "safety_gate"
    | "validator_runner"
    | "rights_permission_gate"
    | "human_operator"
    | "unknown";
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaClassifiedFindingV1 {
  classified_finding_id: string;
  observer_finding_id: string;
  source_observation_type:
    | "artifact"
    | "module_health"
    | "workflow"
    | "dependency"
    | "validation"
    | "safety"
    | "next_action"
    | "unknown";
  module_name: string;
  artifact_id: string;
  original_issue_level: string;
  classified_category: BobaErrorCategoryV1;
  severity: BobaDiagnosticSeverityV1;
  is_primary_symptom: boolean;
  is_secondary_symptom: boolean;
  is_possible_cause: boolean;
  is_downstream_effect: boolean;
  duplicate_group_id: string;
  cascade_group_id: string;
  explanation: string;
  evidence: BobaDiagnosticEvidenceV1[];
  confidence: number;
  warnings: string[];
}

export interface BobaCascadingImpactV1 {
  cascade_id: string;
  originating_case_id: string;
  originating_module: string;
  impacted_modules: string[];
  impacted_artifacts: string[];
  impact_chain: string[];
  blocked_workflow_stages: string[];
  severity: BobaDiagnosticSeverityV1;
  explanation: string;
  confidence: number;
  warnings: string[];
}

export interface BobaInvestigationRecommendationV1 {
  recommendation_id: string;
  diagnostic_case_id: string;
  action: string;
  action_category:
    | "inspect_artifact"
    | "inspect_dependency"
    | "inspect_configuration"
    | "inspect_environment"
    | "inspect_validation_report"
    | "run_future_validator"
    | "collect_missing_information"
    | "human_rights_review"
    | "compare_timestamps"
    | "compare_schema"
    | "inspect_logs"
    | "reproduce_manually"
    | "do_not_continue"
    | "escalate"
    | "unknown";
  safe: boolean;
  read_only: boolean;
  requires_command_execution: boolean;
  requires_code_change: boolean;
  requires_human_review: boolean;
  prerequisite: string[];
  expected_information_gain: string;
  stop_condition: string;
  suggested_owner_module: string;
  priority: "low" | "medium" | "high" | "urgent";
  warnings: string[];
}

export interface BobaErrorDoctorEscalationHandoffV1 {
  handoff_id: string;
  diagnostic_case_id: string;
  target_module:
    | "root_cause_analyzer"
    | "repair_planner"
    | "tool_recovery_brain"
    | "output_quality_reviewer"
    | "safety_gate"
    | "validator_runner"
    | "rights_permission_gate"
    | "human_operator"
    | "unknown";
  reason: string;
  evidence_ids: string[];
  unresolved_questions: string[];
  required_inputs: string[];
  blocked_actions: string[];
  apply_automatically: false;
  human_approval_required: true;
  warnings: string[];
}

export interface BobaErrorDoctorSummaryV1 {
  total_observer_findings: number;
  total_diagnostic_cases: number;
  informational_count: number;
  low_count: number;
  medium_count: number;
  high_count: number;
  critical_count: number;
  blocker_count: number;
  unknown_count: number;
  primary_problem_count: number;
  cascading_problem_count: number;
  blocked_workflow_count: number;
  highest_priority_case: string;
  safest_next_investigation: string;
  unresolved_information: string[];
  human_review_notes: string[];
}

export interface BobaErrorDoctorSignalUsageV1 {
  observer_used: boolean;
  observer_artifact_read: boolean;
  validation_observations_used: boolean;
  dependency_observations_used: boolean;
  safety_observations_used: boolean;
  manual_context_used: boolean;
  raw_logs_read: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  command_execution_used: false;
  validator_execution_used: false;
  code_modification_used: false;
  artifact_modification_used: false;
  destructive_action_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaErrorDoctorSetV1 {
  schema_version: "boba_error_doctor_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  observer_source: string;
  diagnostic_cases: BobaDiagnosticCaseV1[];
  classified_findings: BobaClassifiedFindingV1[];
  cascading_impacts: BobaCascadingImpactV1[];
  investigation_recommendations: BobaInvestigationRecommendationV1[];
  escalation_handoffs: BobaErrorDoctorEscalationHandoffV1[];
  doctor_summary: BobaErrorDoctorSummaryV1;
  signal_usage: BobaErrorDoctorSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaErrorDoctorGenerateInputV1 {
  diagnostic_context?: Record<string, unknown>;
  error_summaries?: Array<string | Record<string, unknown>>;
  dry_run?: boolean;
}

export type BobaRootCauseAnalysisStatusV1 =
  | "root_cause_supported"
  | "probable_root_cause"
  | "multiple_competing_causes"
  | "insufficient_evidence"
  | "conflicting_evidence"
  | "intentional_safety_block"
  | "no_defect_detected"
  | "unknown";

export type BobaRootCauseProcessingImpactV1 =
  | "none"
  | "degraded"
  | "partial_block"
  | "full_block"
  | "unsafe_to_continue"
  | "unknown";

export type BobaRootCauseSafetyImpactV1 =
  | "none_known"
  | "human_review_needed"
  | "safety_gate_blocked"
  | "rights_gate_blocked"
  | "destructive_risk"
  | "unknown";

export type BobaRootCauseCategoryV1 =
  | "missing_artifact"
  | "corrupt_artifact"
  | "stale_artifact"
  | "schema_mismatch"
  | "dependency_order"
  | "configuration"
  | "environment"
  | "storage"
  | "code_defect"
  | "data_quality"
  | "validation_failure"
  | "validation_gap"
  | "tool_unavailable"
  | "tool_failure"
  | "timeout"
  | "resource_exhaustion"
  | "checkpoint_failure"
  | "rendering"
  | "audio_video_sync"
  | "media_probe"
  | "rights_safety"
  | "permission"
  | "intentional_safety_block"
  | "user_input"
  | "external_service"
  | "unknown";

export type BobaRootCauseHandoffTargetV1 =
  | "repair_planner"
  | "tool_recovery_brain"
  | "validator_runner"
  | "artifact_inspector"
  | "report_reader"
  | "safety_gate"
  | "rights_permission_gate"
  | "workflow_controller"
  | "code_surgeon"
  | "human_operator"
  | "unknown";

export interface BobaRootCauseEvidenceV1 {
  evidence_id: string;
  source_type:
    | "error_doctor_fact"
    | "error_doctor_hypothesis"
    | "observer_finding"
    | "artifact_observation"
    | "dependency_observation"
    | "validation_observation"
    | "safety_observation"
    | "bounded_manual_context"
    | "unknown";
  source_id: string;
  module_name: string;
  artifact_id: string;
  evidence_summary: string;
  observed_value: string;
  expected_value: string;
  observed_at: string;
  reliability: "high" | "medium" | "low" | "conflicting" | "unknown";
  confidence: number;
  usage_warning: string;
}

export interface BobaFailureTimelineEventV1 {
  event_id: string;
  event_type:
    | "artifact_created"
    | "artifact_updated"
    | "artifact_missing"
    | "artifact_corrupt"
    | "artifact_unreadable"
    | "dependency_missing"
    | "dependency_stale"
    | "module_blocked"
    | "validation_passed"
    | "validation_failed"
    | "validation_missing"
    | "tool_unavailable"
    | "tool_failed"
    | "timeout"
    | "resource_exhaustion"
    | "configuration_missing"
    | "environment_missing"
    | "safety_blocked"
    | "rights_blocked"
    | "workflow_stopped"
    | "unknown";
  module_name: string;
  artifact_id: string;
  observed_at: string;
  source_type: string;
  source_id: string;
  event_summary: string;
  status_before: string;
  status_after: string;
  confirmed: boolean;
  causal_relevance:
    | "possible_origin"
    | "contributing_event"
    | "downstream_effect"
    | "unrelated"
    | "unknown";
  confidence: number;
  warnings: string[];
}

export interface BobaFailureTimelineV1 {
  timeline_id: string;
  analysis_case_id: string;
  events: BobaFailureTimelineEventV1[];
  earliest_event_id: string;
  first_failure_event_id: string;
  first_confirmed_failure_event_id: string;
  latest_observed_event_id: string;
  ordering_confidence: number;
  conflicting_timestamps: boolean;
  missing_time_information: boolean;
  warnings: string[];
}

export interface BobaCausalNodeV1 {
  node_id: string;
  node_type:
    | "observed_failure"
    | "missing_input"
    | "corrupt_artifact"
    | "stale_artifact"
    | "configuration_factor"
    | "environment_factor"
    | "tool_failure"
    | "resource_factor"
    | "validation_gap"
    | "safety_block"
    | "rights_block"
    | "contributing_factor"
    | "downstream_symptom"
    | "root_cause_candidate"
    | "unknown";
  module_name: string;
  artifact_id: string;
  label: string;
  description: string;
  confirmed: boolean;
  confidence: number;
  evidence_ids: string[];
  warnings: string[];
}

export interface BobaCausalEdgeV1 {
  edge_id: string;
  from_node_id: string;
  to_node_id: string;
  relationship:
    | "caused"
    | "probably_caused"
    | "may_have_caused"
    | "contributed_to"
    | "blocked"
    | "depended_on"
    | "preceded"
    | "correlated_with"
    | "contradicted_by"
    | "unrelated"
    | "unknown";
  evidence_ids: string[];
  confidence: number;
  confirmed: boolean;
  verification_needed: boolean;
  warnings: string[];
}

export interface BobaCausalGraphV1 {
  causal_graph_id: string;
  analysis_case_id: string;
  nodes: BobaCausalNodeV1[];
  edges: BobaCausalEdgeV1[];
  root_candidate_node_ids: string[];
  symptom_node_ids: string[];
  contributing_node_ids: string[];
  blocked_stage_node_ids: string[];
  graph_confidence: number;
  cycles_detected: boolean;
  unresolved_links: string[];
  warnings: string[];
}

export interface BobaRootCauseCandidateV1 {
  root_cause_candidate_id: string;
  analysis_case_id: string;
  title: string;
  category: BobaRootCauseCategoryV1;
  candidate_summary: string;
  earliest_failure_relationship: string;
  supporting_evidence_ids: string[];
  conflicting_evidence_ids: string[];
  explains_symptom_ids: string[];
  unexplained_symptom_ids: string[];
  likelihood_score: number;
  confidence: number;
  evidence_quality:
    | "strong"
    | "moderate"
    | "weak"
    | "conflicting"
    | "insufficient"
    | "unknown";
  verification_required: boolean;
  confirmation_checks: string[];
  rejection_checks: string[];
  repairability:
    | "likely_recoverable"
    | "recoverable_with_approval"
    | "requires_tool_fallback"
    | "requires_code_change"
    | "requires_configuration_change"
    | "requires_human_decision"
    | "not_a_defect"
    | "blocked"
    | "unknown";
  safety_constraints: string[];
  recommended_owner_module: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaContributingFactorV1 {
  contributing_factor_id: string;
  analysis_case_id: string;
  factor_category:
    | "resource_pressure"
    | "stale_state"
    | "incomplete_configuration"
    | "optional_dependency_missing"
    | "weak_input_data"
    | "incompatible_format"
    | "environment_difference"
    | "retry_exhaustion"
    | "checkpoint_gap"
    | "validation_gap"
    | "user_decision_required"
    | "rights_constraint"
    | "safety_constraint"
    | "unknown";
  factor_summary: string;
  related_root_cause_candidate_ids: string[];
  evidence_ids: string[];
  impact: string;
  necessary_for_failure: boolean;
  sufficient_for_failure: boolean;
  confidence: number;
  verification_needed: boolean;
  warnings: string[];
}

export interface BobaDownstreamSymptomV1 {
  downstream_symptom_id: string;
  analysis_case_id: string;
  source_finding_id: string;
  module_name: string;
  artifact_id: string;
  symptom_summary: string;
  originating_candidate_ids: string[];
  cascade_depth: number;
  processing_impact: BobaRootCauseProcessingImpactV1;
  confidence: number;
  warnings: string[];
}

export interface BobaEvidenceGapV1 {
  evidence_gap_id: string;
  analysis_case_id: string;
  missing_information: string;
  why_needed: string;
  affected_candidate_ids: string[];
  collection_method:
    | "inspect_saved_artifact"
    | "inspect_bounded_log"
    | "inspect_configuration"
    | "inspect_environment"
    | "compare_timestamps"
    | "compare_schema"
    | "run_future_validator"
    | "reproduce_manually"
    | "check_tool_health"
    | "collect_user_input"
    | "human_rights_review"
    | "unavailable"
    | "unknown";
  requires_command_execution: boolean;
  requires_validator: boolean;
  requires_external_access: boolean;
  requires_human_review: boolean;
  safe_to_collect: boolean;
  priority: "low" | "medium" | "high" | "urgent";
  warnings: string[];
}

export interface BobaRootCauseVerificationCheckV1 {
  check_id: string;
  order: number;
  check_type:
    | "inspect_artifact"
    | "inspect_dependency"
    | "inspect_timestamp"
    | "inspect_schema"
    | "inspect_configuration"
    | "inspect_environment"
    | "inspect_validation_report"
    | "check_tool_availability"
    | "check_resource_history"
    | "reproduce_failure"
    | "compare_successful_run"
    | "verify_rights_state"
    | "stop_processing"
    | "unknown";
  description: string;
  prerequisite: string;
  expected_information_gain: string;
  safe: boolean;
  read_only: boolean;
  requires_human_review: boolean;
  warnings: string[];
}

export interface BobaRootCauseVerificationPlanV1 {
  verification_plan_id: string;
  analysis_case_id: string;
  root_cause_candidate_id: string;
  objective: string;
  checks: BobaRootCauseVerificationCheckV1[];
  expected_confirmation_evidence: string[];
  expected_rejection_evidence: string[];
  safe: boolean;
  read_only: boolean;
  requires_command_execution: boolean;
  requires_validator_execution: boolean;
  requires_code_modification: false;
  requires_external_access: boolean;
  requires_human_approval: true;
  stop_conditions: string[];
  rollback_requirement: string;
  suggested_owner_module: string;
  priority: "low" | "medium" | "high" | "urgent";
  warnings: string[];
}

export interface BobaWorkflowImpactAnalysisV1 {
  workflow_impact_id: string;
  analysis_case_id: string;
  originating_module: string;
  impacted_modules: string[];
  impacted_artifacts: string[];
  blocked_stages: string[];
  degraded_stages: string[];
  safe_stages: string[];
  unsafe_next_actions: string[];
  conditionally_safe_actions: string[];
  resume_requirements: string[];
  confidence: number;
  warnings: string[];
}

export interface BobaRootCauseEscalationHandoffV1 {
  handoff_id: string;
  analysis_case_id: string;
  root_cause_candidate_ids: string[];
  target_module: BobaRootCauseHandoffTargetV1;
  reason: string;
  evidence_ids: string[];
  unresolved_questions: string[];
  required_inputs: string[];
  blocked_actions: string[];
  allowed_advisory_actions: string[];
  apply_automatically: false;
  human_approval_required: true;
  priority: "low" | "medium" | "high" | "urgent";
  warnings: string[];
}

export interface BobaRootCauseAnalysisCaseV1 {
  analysis_case_id: string;
  source_diagnostic_case_id: string;
  title: string;
  primary_module: string;
  primary_artifact: string;
  workflow_stage: string;
  analysis_status: BobaRootCauseAnalysisStatusV1;
  earliest_known_failure: string;
  most_likely_root_cause: string;
  root_cause_confidence: number;
  confirmed_facts: string[];
  probable_inferences: string[];
  unresolved_hypotheses: string[];
  contributing_factor_ids: string[];
  downstream_symptom_ids: string[];
  affected_modules: string[];
  affected_artifacts: string[];
  failure_timeline_id: string;
  causal_graph_id: string;
  evidence_gap_ids: string[];
  verification_plan_ids: string[];
  processing_impact: BobaRootCauseProcessingImpactV1;
  safety_impact: BobaRootCauseSafetyImpactV1;
  recommended_handoff: BobaRootCauseHandoffTargetV1;
  human_review_required: true;
  warnings: string[];
  limitations: string[];
}

export interface BobaRootCauseAnalyzerSummaryV1 {
  total_diagnostic_cases: number;
  total_analysis_cases: number;
  supported_root_cause_count: number;
  probable_root_cause_count: number;
  competing_cause_count: number;
  insufficient_evidence_count: number;
  intentional_safety_block_count: number;
  critical_case_count: number;
  blocked_workflow_count: number;
  strongest_root_cause_candidate: string;
  weakest_evidence_area: string;
  safest_next_verification: string;
  highest_priority_handoff: string;
  unresolved_questions: string[];
  human_review_notes: string[];
}

export interface BobaRootCauseSignalUsageV1 {
  error_doctor_used: boolean;
  error_doctor_artifact_read: boolean;
  observer_references_used: boolean;
  validation_evidence_used: boolean;
  dependency_evidence_used: boolean;
  safety_evidence_used: boolean;
  bounded_manual_context_used: boolean;
  raw_logs_read: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  command_execution_used: false;
  validator_execution_used: false;
  code_modification_used: false;
  artifact_modification_used: false;
  repair_execution_used: false;
  tool_fallback_execution_used: false;
  destructive_action_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaRootCauseAnalyzerSetV1 {
  schema_version: "boba_root_cause_analyzer_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  error_doctor_source: string;
  analysis_cases: BobaRootCauseAnalysisCaseV1[];
  failure_timelines: BobaFailureTimelineV1[];
  causal_graphs: BobaCausalGraphV1[];
  root_cause_candidates: BobaRootCauseCandidateV1[];
  contributing_factors: BobaContributingFactorV1[];
  downstream_symptoms: BobaDownstreamSymptomV1[];
  evidence: BobaRootCauseEvidenceV1[];
  evidence_gaps: BobaEvidenceGapV1[];
  verification_plans: BobaRootCauseVerificationPlanV1[];
  workflow_impacts: BobaWorkflowImpactAnalysisV1[];
  escalation_handoffs: BobaRootCauseEscalationHandoffV1[];
  analyzer_summary: BobaRootCauseAnalyzerSummaryV1;
  signal_usage: BobaRootCauseSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaRootCauseAnalyzerGenerateInputV1 {
  diagnostic_context?: Record<string, unknown>;
  dry_run?: boolean;
}

export type BobaRepairPlanningStatusV1 =
  | "plan_ready"
  | "conditional_plan"
  | "needs_more_evidence"
  | "conflicting_causes"
  | "intentional_safety_block"
  | "human_decision_required"
  | "repair_not_required"
  | "blocked"
  | "unknown";

export type BobaRepairScopeV1 =
  | "no_repair"
  | "artifact"
  | "checkpoint"
  | "workflow"
  | "configuration"
  | "environment"
  | "tool"
  | "dependency"
  | "data_input"
  | "validation"
  | "rendering"
  | "code"
  | "rights_permission"
  | "human_decision"
  | "unknown";

export type BobaRepairStrategyTypeV1 =
  | "no_action"
  | "collect_more_evidence"
  | "regenerate_artifact"
  | "restore_checkpoint"
  | "resume_from_checkpoint"
  | "retry_same_tool"
  | "retry_with_safe_settings"
  | "reduce_resource_usage"
  | "use_registered_tool_fallback"
  | "switch_safe_workflow_path"
  | "repair_generated_state"
  | "repair_configuration"
  | "repair_environment"
  | "replace_invalid_input"
  | "rerun_validation"
  | "isolate_failure"
  | "propose_code_patch"
  | "seek_permission"
  | "human_manual_action"
  | "stop_processing"
  | "unknown";

export type BobaRepairStepTypeV1 =
  | "inspect"
  | "backup"
  | "checkpoint"
  | "collect_evidence"
  | "validate_precondition"
  | "regenerate"
  | "retry"
  | "adjust_safe_setting"
  | "switch_tool"
  | "switch_workflow"
  | "restore"
  | "configure"
  | "install_dependency"
  | "restart_service"
  | "propose_patch"
  | "apply_patch"
  | "validate_result"
  | "compare_quality"
  | "resume_workflow"
  | "stop"
  | "human_review"
  | "unknown";

export type BobaRepairReversibilityV1 =
  | "fully_reversible"
  | "mostly_reversible"
  | "partially_reversible"
  | "difficult_to_reverse"
  | "irreversible"
  | "unknown";

export type BobaRepairDestructivenessV1 =
  | "none"
  | "low"
  | "medium"
  | "high"
  | "blocked"
  | "unknown";

export type BobaRepairAutomationEligibilityV1 =
  | "safe_advisory_only"
  | "potentially_automatable_after_approval"
  | "human_execution_required"
  | "blocked"
  | "unknown";

export type BobaRepairRiskLevelV1 =
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "critical"
  | "blocked"
  | "unknown";

export type BobaRepairComplexityV1 =
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "very_high"
  | "unknown";

export type BobaRepairCheckpointTypeV1 =
  | "none"
  | "artifact_snapshot"
  | "generated_state_snapshot"
  | "workflow_checkpoint"
  | "configuration_snapshot"
  | "repository_branch"
  | "database_backup"
  | "media_reference_only"
  | "unknown";

export type BobaRepairRollbackScopeV1 =
  | "none"
  | "artifact"
  | "workflow"
  | "configuration"
  | "environment"
  | "tool_selection"
  | "code_branch"
  | "database"
  | "unknown";

export type BobaRepairValidationPhaseV1 =
  | "pre_repair"
  | "during_repair"
  | "post_repair"
  | "rollback"
  | "resume"
  | "unknown";

export type BobaRepairValidationCategoryV1 =
  | "artifact_integrity"
  | "schema"
  | "dependency"
  | "checkpoint"
  | "rendering"
  | "audio_video_sync"
  | "media_probe"
  | "captions"
  | "framing"
  | "output_quality"
  | "performance"
  | "resource_usage"
  | "safety"
  | "rights_permission"
  | "regression"
  | "workflow"
  | "code_quality"
  | "frontend"
  | "api"
  | "unknown";

export type BobaRepairApprovalStatusV1 =
  | "planning_only"
  | "awaiting_human_review"
  | "blocked"
  | "not_required_for_no_action"
  | "unknown";

export type BobaRepairHandoffTargetV1 =
  | "tool_recovery_brain"
  | "code_surgeon"
  | "validator_runner"
  | "artifact_inspector"
  | "report_reader"
  | "safety_gate"
  | "rights_permission_gate"
  | "workflow_controller"
  | "checkpoint_recovery_manager"
  | "output_quality_reviewer"
  | "human_operator"
  | "unknown";

export interface BobaRepairStepV1 {
  repair_step_id: string;
  repair_strategy_id: string;
  order: number;
  step_type: BobaRepairStepTypeV1;
  description: string;
  target: string;
  read_only: boolean;
  reversible: boolean;
  requires_human_approval: true;
  requires_command_execution: boolean;
  requires_code_change: boolean;
  requires_external_access: boolean;
  safety_precondition: string;
  success_condition: string;
  failure_condition: string;
  stop_condition: string;
  rollback_step_reference: string;
  suggested_owner_module: string;
  warnings: string[];
}

export interface BobaRepairStrategyV1 {
  repair_strategy_id: string;
  repair_case_id: string;
  title: string;
  strategy_type: BobaRepairStrategyTypeV1;
  target_module: string;
  target_artifact: string;
  description: string;
  rationale: string;
  easy_explanation: string;
  root_cause_candidate_ids: string[];
  prerequisites: string[];
  proposed_steps: BobaRepairStepV1[];
  expected_result: string;
  expected_quality_effect: string;
  expected_workflow_effect: string;
  reversibility: BobaRepairReversibilityV1;
  destructiveness: BobaRepairDestructivenessV1;
  automation_eligibility: BobaRepairAutomationEligibilityV1;
  human_approval_required: true;
  requires_checkpoint: boolean;
  requires_backup: boolean;
  requires_command_execution: boolean;
  requires_validator_execution: boolean;
  requires_code_change: boolean;
  requires_configuration_change: boolean;
  requires_tool_fallback: boolean;
  requires_service_restart: boolean;
  requires_package_installation: boolean;
  requires_external_access: boolean;
  requires_paid_service: boolean;
  requires_rights_review: boolean;
  estimated_risk: BobaRepairRiskLevelV1;
  estimated_complexity: BobaRepairComplexityV1;
  estimated_confidence: number;
  strategy_score: number;
  rank: number;
  recommended: boolean;
  maximum_attempts: number | null;
  maximum_recovery_duration_seconds: number | null;
  previously_attempted_strategies: string[];
  escalation_condition: string;
  prohibited_actions: string[];
  stop_conditions: string[];
  warnings: string[];
  limitations: string[];
}

export interface BobaRepairStrategyRiskV1 {
  strategy_id: string;
  risk_level: BobaRepairRiskLevelV1;
  risk_reasons: string[];
  mitigations: string[];
  residual_risk: string;
  acceptable_only_if: string[];
  blocked: boolean;
  confidence: number;
  warnings: string[];
}

export interface BobaRepairRiskAssessmentV1 {
  risk_assessment_id: string;
  repair_case_id: string;
  strategy_risks: BobaRepairStrategyRiskV1[];
  overall_risk: BobaRepairRiskLevelV1;
  source_data_risk: BobaRepairRiskLevelV1;
  artifact_loss_risk: BobaRepairRiskLevelV1;
  output_quality_risk: BobaRepairRiskLevelV1;
  workflow_corruption_risk: BobaRepairRiskLevelV1;
  configuration_risk: BobaRepairRiskLevelV1;
  environment_risk: BobaRepairRiskLevelV1;
  security_risk: BobaRepairRiskLevelV1;
  rights_safety_risk: BobaRepairRiskLevelV1;
  external_dependency_risk: BobaRepairRiskLevelV1;
  rollback_failure_risk: BobaRepairRiskLevelV1;
  human_error_risk: BobaRepairRiskLevelV1;
  blockers: string[];
  mitigations: string[];
  residual_risks: string[];
  human_review_notes: string[];
  warnings: string[];
}

export interface BobaRepairCheckpointPlanV1 {
  checkpoint_plan_id: string;
  repair_case_id: string;
  checkpoint_required: boolean;
  checkpoint_type: BobaRepairCheckpointTypeV1;
  artifacts_to_preserve: string[];
  state_to_preserve: string[];
  source_media_must_remain_untouched: true;
  checkpoint_validation_required: boolean;
  checkpoint_success_conditions: string[];
  checkpoint_failure_conditions: string[];
  storage_requirements: string[];
  retention_notes: string[];
  human_approval_required: true;
  warnings: string[];
}

export interface BobaRepairRollbackPlanV1 {
  rollback_plan_id: string;
  repair_case_id: string;
  rollback_required: boolean;
  rollback_scope: BobaRepairRollbackScopeV1;
  rollback_trigger_conditions: string[];
  rollback_steps: string[];
  preserved_state_required: string[];
  rollback_validation: string[];
  rollback_owner_module: string;
  destructive_rollback_blocked: true;
  human_approval_required: true;
  warnings: string[];
  limitations: string[];
}

export interface BobaRepairValidationCheckV1 {
  validation_check_id: string;
  phase: BobaRepairValidationPhaseV1;
  category: BobaRepairValidationCategoryV1;
  description: string;
  validator_name: string;
  expected_result: string;
  required: boolean;
  blocks_acceptance_on_failure: boolean;
  requires_command_execution: boolean;
  requires_human_review: true;
  warnings: string[];
}

export interface BobaRepairValidationPlanV1 {
  validation_plan_id: string;
  repair_case_id: string;
  pre_repair_checks: BobaRepairValidationCheckV1[];
  post_repair_checks: BobaRepairValidationCheckV1[];
  required_validators: string[];
  acceptance_criteria: string[];
  rejection_criteria: string[];
  comparison_baseline: string[];
  regression_checks: string[];
  safety_checks: string[];
  rights_checks: string[];
  output_quality_checks: string[];
  workflow_resume_checks: string[];
  requires_validator_runner: boolean;
  requires_human_review: true;
  warnings: string[];
}

export interface BobaQualityPreservationPlanV1 {
  quality_preservation_plan_id: string;
  repair_case_id: string;
  original_requirements: string[];
  non_negotiable_requirements: string[];
  acceptable_degradations: string[];
  unacceptable_degradations: string[];
  comparison_metrics: string[];
  creative_quality_checks: string[];
  technical_quality_checks: string[];
  rights_safety_checks: string[];
  fallback_acceptance_rules: string[];
  human_review_required: true;
  warnings: string[];
}

export interface BobaRepairApprovalGateV1 {
  approval_gate_id: string;
  repair_case_id: string;
  approval_status: BobaRepairApprovalStatusV1;
  required_approvals: string[];
  actions_allowed_without_approval: string[];
  actions_requiring_approval: string[];
  prohibited_actions: string[];
  rights_gate_required: boolean;
  safety_gate_required: boolean;
  code_review_required: boolean;
  rollback_plan_required: boolean;
  validation_plan_required: boolean;
  output_quality_review_required: boolean;
  final_human_approval_required: true;
  warnings: string[];
}

export interface BobaRepairExecutionHandoffV1 {
  handoff_id: string;
  repair_case_id: string;
  repair_strategy_id: string;
  target_module: BobaRepairHandoffTargetV1;
  reason: string;
  required_inputs: string[];
  required_capability: string;
  required_quality_properties: string[];
  constraints: string[];
  prohibited_actions: string[];
  checkpoint_plan_id: string;
  rollback_plan_id: string;
  validation_plan_id: string;
  approval_gate_id: string;
  apply_automatically: false;
  human_approval_required: true;
  priority: "low" | "medium" | "high" | "urgent";
  warnings: string[];
}

export interface BobaRepairRejectedStrategyV1 {
  rejected_strategy_id: string;
  repair_case_id: string;
  title: string;
  strategy_type: BobaRepairStrategyTypeV1;
  rejection_reason: string;
  safety_reason: string;
  quality_reason: string;
  rights_reason: string;
  reversibility_reason: string;
  evidence_reason: string;
  warnings: string[];
}

export interface BobaRepairPlanningCaseV1 {
  repair_case_id: string;
  source_analysis_case_id: string;
  title: string;
  primary_module: string;
  primary_artifact: string;
  workflow_stage: string;
  root_cause_candidate_ids: string[];
  selected_root_cause_candidate_id: string;
  selected_root_cause_summary: string;
  planning_status: BobaRepairPlanningStatusV1;
  repair_needed: boolean;
  repair_scope: BobaRepairScopeV1;
  blocked_reason: string;
  strategy_ids: string[];
  recommended_strategy_id: string;
  alternative_strategy_ids: string[];
  rejected_strategy_ids: string[];
  risk_assessment_id: string;
  checkpoint_plan_id: string;
  rollback_plan_id: string;
  validation_plan_id: string;
  quality_preservation_plan_id: string;
  approval_gate_id: string;
  execution_handoff_ids: string[];
  expected_workflow_impact: string;
  human_review_required: true;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaRepairPlannerSummaryV1 {
  total_analysis_cases: number;
  total_repair_cases: number;
  plan_ready_count: number;
  conditional_plan_count: number;
  needs_more_evidence_count: number;
  safety_block_count: number;
  human_decision_count: number;
  repair_not_required_count: number;
  blocked_count: number;
  tool_recovery_handoff_count: number;
  code_surgeon_handoff_count: number;
  validator_handoff_count: number;
  highest_risk_case: string;
  safest_repair_strategy: string;
  most_reversible_strategy: string;
  strongest_quality_preservation_plan: string;
  highest_priority_handoff: string;
  unresolved_questions: string[];
  human_review_notes: string[];
}

export interface BobaRepairPlannerSignalUsageV1 {
  root_cause_analyzer_used: boolean;
  root_cause_artifact_read: boolean;
  failure_timelines_used: boolean;
  causal_graphs_used: boolean;
  root_cause_candidates_used: boolean;
  verification_plans_used: boolean;
  workflow_impacts_used: boolean;
  rights_safety_evidence_used: boolean;
  checkpoint_system_inspected: boolean;
  validation_registry_inspected: boolean;
  bounded_manual_context_used: boolean;
  external_api_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  command_execution_used: false;
  validator_execution_used: false;
  code_modification_used: false;
  artifact_modification_used: false;
  repair_execution_used: false;
  tool_fallback_execution_used: false;
  workflow_resume_used: false;
  service_restart_used: false;
  package_installation_used: false;
  destructive_action_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaRepairPlannerSetV1 {
  schema_version: "boba_repair_planner_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  root_cause_analyzer_source: string;
  repair_cases: BobaRepairPlanningCaseV1[];
  repair_strategies: BobaRepairStrategyV1[];
  risk_assessments: BobaRepairRiskAssessmentV1[];
  checkpoint_plans: BobaRepairCheckpointPlanV1[];
  rollback_plans: BobaRepairRollbackPlanV1[];
  validation_plans: BobaRepairValidationPlanV1[];
  quality_preservation_plans: BobaQualityPreservationPlanV1[];
  approval_gates: BobaRepairApprovalGateV1[];
  execution_handoffs: BobaRepairExecutionHandoffV1[];
  rejected_strategies: BobaRepairRejectedStrategyV1[];
  planner_summary: BobaRepairPlannerSummaryV1;
  signal_usage: BobaRepairPlannerSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaRepairPlannerGenerateInputV1 {
  planning_context?: Record<string, unknown>;
  dry_run?: boolean;
}

export type BobaCodeEvidenceStrengthV1 =
  | "strong"
  | "moderate"
  | "weak"
  | "conflicting"
  | "insufficient"
  | "unknown";

export type BobaCodeApprovalTypeV1 =
  | "proposal_review"
  | "isolated_patch_execution"
  | "special_path_change"
  | "dependency_change"
  | "workflow_change"
  | "local_commit_creation"
  | "unknown";

export interface BobaCodeRepairCaseV1 {
  code_repair_case_id: string;
  source_repair_case_id: string;
  source_repair_strategy_id: string;
  title: string;
  target_module: string;
  suspected_code_defect: string;
  evidence_strength: BobaCodeEvidenceStrengthV1;
  code_change_justified: boolean;
  justification: string;
  affected_paths: string[];
  protected_paths_detected: string[];
  required_behavior: string[];
  behavior_to_preserve: string[];
  validation_requirements: string[];
  quality_requirements: string[];
  rollback_requirements: string[];
  approval_required: true;
  execution_eligible: boolean;
  blocked_reason: string | null;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaCodePatchFileV1 {
  path: string;
  operation: "add" | "modify" | "delete" | "rename" | "mode_change" | "unknown";
  language: string;
  previous_sha256: string;
  proposed_sha256: string;
  additions: number;
  deletions: number;
  binary: boolean;
  generated: boolean;
  protected: boolean;
  special_approval_required: boolean;
  reason_for_change: string;
  behavior_preserved: string[];
  validation_needed: string[];
  warnings: string[];
}

export interface BobaCodePatchHunkV1 {
  file_path: string;
  old_start: number;
  old_count: number;
  new_start: number;
  new_count: number;
  bounded_summary: string;
  change_reason: string;
  related_evidence_ids: string[];
  risk: string;
  warnings: string[];
}

export interface BobaCodePatchProposalV1 {
  patch_proposal_id: string;
  code_repair_case_id: string;
  proposal_source:
    | "deterministic_template"
    | "user_provided_diff"
    | "codex_provided_diff"
    | "imported_review_patch"
    | "unknown";
  base_branch: string;
  base_commit_sha: string;
  proposed_branch: string;
  title: string;
  summary: string;
  rationale: string;
  files: BobaCodePatchFileV1[];
  hunks: BobaCodePatchHunkV1[];
  unified_diff_reference: string;
  diff_sha256: string;
  changed_file_count: number;
  additions: number;
  deletions: number;
  total_changed_lines: number;
  patch_size_bytes: number;
  applies_cleanly: boolean;
  path_policy_passed: boolean;
  secret_scan_passed: boolean;
  scope_check_passed: boolean;
  binary_change_detected: boolean;
  dependency_change_detected: boolean;
  workflow_change_detected: boolean;
  risk_level: string;
  approval_status: string;
  execution_status: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaCodeApprovalRecordV1 {
  approval_id: string;
  code_repair_case_id: string;
  patch_proposal_id: string;
  approval_type: BobaCodeApprovalTypeV1;
  approved: boolean;
  approved_at?: string;
  approved_by: string;
  approved_base_commit_sha: string;
  approved_diff_sha256: string;
  approved_scope: string[];
  approved_validation_commands: string[];
  approved_special_paths: string[];
  approval_expires_at?: string | null;
  explicit_confirmation: boolean;
  warnings?: string[];
}

export interface BobaCodeExecutionPolicyV1 {
  policy_id: string;
  protected_branches: string[];
  protected_paths: string[];
  special_approval_paths: string[];
  allowed_extensions: string[];
  blocked_extensions: string[];
  maximum_changed_files: number;
  maximum_changed_lines: number;
  maximum_diff_size_bytes: number;
  maximum_individual_file_size_bytes: number;
  maximum_validation_commands: number;
  maximum_patch_attempts: number;
  command_timeout_seconds: number;
  output_capture_limit_bytes: number;
  network_access_allowed: false;
  package_installation_allowed: false;
  service_restart_allowed: false;
  push_allowed: false;
  merge_allowed: false;
  tag_allowed: false;
  destructive_git_allowed: false;
  direct_main_modification_allowed: false;
  warnings: string[];
}

export interface BobaCodeIsolatedRunV1 {
  isolated_run_id: string;
  patch_proposal_id: string;
  mode: string;
  base_branch: string;
  base_commit_sha: string;
  repair_branch: string;
  sanitized_worktree_reference: string;
  worktree_created: boolean;
  current_worktree_clean_before_run: boolean;
  patch_apply_check_passed: boolean;
  patch_applied: boolean;
  changed_files_verified: boolean;
  approval_verified: boolean;
  execution_started_at: string | null;
  execution_completed_at: string | null;
  run_status: string;
  stop_reason: string | null;
  warnings: string[];
}

export interface BobaCodeValidationCommandV1 {
  validation_command_id: string;
  name: string;
  executable: string;
  arguments: string[];
  working_directory_scope: string;
  category: string;
  required: boolean;
  approved: boolean;
  timeout_seconds: number;
  network_forbidden: true;
  shell_used: false;
  expected_exit_codes: number[];
  output_limit_bytes: number;
  warnings: string[];
}

export interface BobaCodeValidationResultV1 {
  validation_result_id: string;
  validation_command_id: string;
  name: string;
  status: string;
  exit_code: number | null;
  duration_seconds: number;
  bounded_stdout_summary: string;
  bounded_stderr_summary: string;
  output_truncated: boolean;
  secrets_redacted: boolean;
  required: boolean;
  blocks_acceptance: boolean;
  warnings: string[];
}

export interface BobaCodeValidationRunV1 {
  validation_run_id: string;
  isolated_run_id: string;
  commands: BobaCodeValidationCommandV1[];
  results: BobaCodeValidationResultV1[];
  required_checks_passed: boolean;
  optional_checks_passed: boolean;
  failed_required_checks: string[];
  failed_optional_checks: string[];
  skipped_checks: string[];
  acceptance_criteria_met: boolean;
  rejection_reason: string | null;
  started_at: string;
  completed_at: string | null;
  warnings: string[];
}

export interface BobaCodeRollbackRecordV1 {
  rollback_record_id: string;
  isolated_run_id: string;
  rollback_trigger: string;
  rollback_scope: string;
  rollback_started_at: string | null;
  rollback_completed_at: string | null;
  patch_removed: boolean;
  temporary_worktree_removed: boolean;
  repair_branch_preserved_for_review: boolean;
  source_worktree_unchanged: boolean;
  rollback_validation_passed: boolean;
  rollback_status: string;
  human_review_required: boolean;
  warnings: string[];
}

export interface BobaCodeReviewPackageV1 {
  review_package_id: string;
  patch_proposal_id: string;
  isolated_run_id: string;
  repair_branch: string;
  base_commit_sha: string;
  local_commit_sha: string;
  commit_created: boolean;
  diff_summary: string;
  changed_files: string[];
  validation_summary: string;
  failed_or_skipped_checks: string[];
  risk_summary: string;
  rollback_summary: string;
  PR_title: string;
  PR_body: string;
  reviewer_checklist: string[];
  prohibited_next_actions: string[];
  ready_for_manual_push: boolean;
  ready_for_manual_PR: boolean;
  ready_for_merge: false;
  warnings: string[];
  limitations: string[];
}

export interface BobaCodeSurgeonExecutionHandoffV1 {
  handoff_id: string;
  code_repair_case_id: string;
  patch_proposal_id: string;
  target_module: string;
  reason: string;
  required_inputs: string[];
  validation_requirements: string[];
  constraints: string[];
  prohibited_actions: string[];
  apply_automatically: false;
  human_approval_required: true;
  priority: string;
  warnings: string[];
}

export interface BobaCodeSurgeonSummaryV1 {
  total_repair_cases: number;
  eligible_case_count: number;
  blocked_case_count: number;
  proposal_count: number;
  approved_proposal_count: number;
  isolated_execution_count: number;
  validation_pass_count: number;
  validation_failure_count: number;
  rollback_count: number;
  local_commit_count: number;
  protected_path_block_count: number;
  secret_scan_block_count: number;
  scope_block_count: number;
  current_highest_priority_case: string;
  safest_reviewable_patch: string;
  required_human_actions: string[];
  limitations: string[];
}

export interface BobaCodeSurgeonSignalUsageV1 {
  repair_planner_used: boolean;
  repair_planner_artifact_read: boolean;
  root_cause_references_used: boolean;
  approval_record_used: boolean;
  git_repository_inspected: boolean;
  isolated_worktree_used: boolean;
  provided_patch_used: boolean;
  deterministic_template_used: boolean;
  secret_scan_used: boolean;
  validation_commands_executed: boolean;
  code_modified_in_isolated_worktree: boolean;
  local_branch_created: boolean;
  local_commit_created: boolean;
  main_branch_modified: false;
  push_used: false;
  PR_created: false;
  merge_used: false;
  tag_used: false;
  external_api_used: false;
  network_access_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  package_installation_used: false;
  service_restart_used: false;
  destructive_git_used: false;
  destructive_action_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaCodeSurgeonSetV1 {
  schema_version: "boba_code_surgeon_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  repair_planner_source: string;
  repair_cases: BobaCodeRepairCaseV1[];
  patch_proposals: BobaCodePatchProposalV1[];
  approval_records: BobaCodeApprovalRecordV1[];
  execution_policies: BobaCodeExecutionPolicyV1[];
  isolated_runs: BobaCodeIsolatedRunV1[];
  validation_runs: BobaCodeValidationRunV1[];
  rollback_records: BobaCodeRollbackRecordV1[];
  review_packages: BobaCodeReviewPackageV1[];
  execution_handoffs: BobaCodeSurgeonExecutionHandoffV1[];
  surgeon_summary: BobaCodeSurgeonSummaryV1;
  signal_usage: BobaCodeSurgeonSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaCodeSurgeonProposalInputV1 {
  repair_case_id?: string;
  repair_strategy_id?: string;
  unified_diff?: string;
  proposal_source?:
    | "deterministic_template"
    | "user_provided_diff"
    | "codex_provided_diff"
    | "imported_review_patch";
  deterministic_template_identifier?: string;
  template_parameters?: Record<string, unknown>;
  base_branch?: string;
  affected_paths?: string[];
  approved_special_paths?: string[];
}

export interface BobaCodeSurgeonExecuteInputV1 {
  patch_proposal_id: string;
  approval: BobaCodeApprovalRecordV1;
  approved_validation_commands: string[];
}

export interface BobaCodeSurgeonCommitInputV1 {
  isolated_run_id: string;
  approval: BobaCodeApprovalRecordV1;
}

export interface BobaToolHealthCheckV1 {
  health_check_id: string;
  tool_id: string;
  check_type: string;
  executable: string;
  arguments: string[];
  timeout_seconds: number;
  shell_used: false;
  network_required: false;
  read_only: boolean;
  expected_exit_codes: number[];
  output_limit_bytes: number;
  warnings: string[];
}

export interface BobaToolCapabilityV1 {
  capability_id: string;
  name: string;
  description: string;
  required_input_properties: string[];
  required_output_properties: string[];
  non_negotiable_quality_properties: string[];
  acceptable_degradations: string[];
  unacceptable_degradations: string[];
  safety_constraints: string[];
  rights_constraints: string[];
  registered_tool_ids: string[];
  warnings: string[];
}

export interface BobaRegisteredRecoveryToolV1 {
  tool_id: string;
  display_name: string;
  provider_type: string;
  capability_ids: string[];
  executable: string;
  package_name: string;
  local_only: boolean;
  installed: boolean;
  available: boolean;
  health_status: string;
  version: string;
  supported_inputs: string[];
  supported_outputs: string[];
  quality_tier: string;
  resource_profile: string;
  fallback_priority: number;
  known_limitations: string[];
  prohibited_uses: string[];
  health_check: BobaToolHealthCheckV1 | null;
  warnings: string[];
}

export interface BobaToolHealthResultV1 {
  health_result_id: string;
  health_check_id: string;
  tool_id: string;
  status: string;
  exit_code: number | null;
  duration_seconds: number;
  version_detected: string;
  bounded_stdout_summary: string;
  bounded_stderr_summary: string;
  output_truncated: boolean;
  secrets_redacted: boolean;
  checked_at: string;
  confidence: number;
  warnings: string[];
}

export interface BobaToolRecoveryCaseV1 {
  recovery_case_id: string;
  source_repair_case_id: string;
  source_repair_strategy_ids: string[];
  title: string;
  target_module: string;
  workflow_stage: string;
  required_capability: string;
  failing_tool_id: string;
  failure_class: string;
  failure_evidence: string[];
  rights_status: string;
  safety_status: string;
  checkpoint_required: boolean;
  checkpoint_ready: boolean;
  rollback_ready: boolean;
  quality_requirements: string[];
  approved_strategy_ids: string[];
  recovery_eligible: boolean;
  blocked_reason: string;
  human_approval_required: true;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaToolRecoveryStrategyV1 {
  recovery_strategy_id: string;
  recovery_plan_id: string;
  order: number;
  strategy_type: string;
  tool_id: string;
  capability_id: string;
  description: string;
  rationale: string;
  configuration_overrides: Record<string, unknown>;
  expected_result: string;
  expected_quality_effect: string;
  expected_resource_effect: string;
  reversible: boolean;
  requires_checkpoint: boolean;
  requires_tool_switch: boolean;
  requires_quality_review: true;
  requires_human_approval: true;
  execution_allowed: boolean;
  maximum_attempts: number;
  timeout_seconds: number;
  failure_stop_condition: string;
  success_condition: string;
  rollback_reference: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaToolRecoveryPlanV1 {
  recovery_plan_id: string;
  recovery_case_id: string;
  approved_repair_strategy_id: string;
  required_capability: string;
  primary_tool_id: string;
  candidate_fallback_tool_ids: string[];
  ordered_strategies: BobaToolRecoveryStrategyV1[];
  retry_budget: Record<string, number>;
  time_budget_seconds: number;
  checkpoint_requirements: Record<string, unknown>;
  rollback_requirements: Record<string, unknown>;
  quality_requirements: string[];
  validation_requirements: string[];
  approval_status: string;
  execution_status: string;
  prohibited_actions: string[];
  stop_conditions: string[];
  escalation_conditions: string[];
  warnings: string[];
  limitations: string[];
}

export interface BobaToolRecoveryApprovalV1 {
  approval_id: string;
  recovery_case_id: string;
  recovery_plan_id: string;
  approved: boolean;
  approved_at: string | null;
  approved_by: string;
  approved_strategy_ids: string[];
  approved_tool_ids: string[];
  approved_configuration_overrides: Record<string, unknown>;
  approved_retry_budget: Record<string, number>;
  approved_time_budget_seconds: number;
  approved_quality_requirements: string[];
  approved_checkpoint_reference: string;
  approval_expires_at: string | null;
  explicit_confirmation: string;
  warnings: string[];
}

export interface BobaRecoveryCommandV1 {
  recovery_command_id: string;
  tool_id: string;
  executable: string;
  arguments: string[];
  working_directory_scope: string;
  category: string;
  approved: boolean;
  shell_used: false;
  network_forbidden: true;
  timeout_seconds: number;
  expected_exit_codes: number[];
  output_limit_bytes: number;
  environment_policy: string;
  warnings: string[];
}

export interface BobaToolRecoveryAttemptV1 {
  recovery_attempt_id: string;
  recovery_case_id: string;
  recovery_plan_id: string;
  recovery_strategy_id: string;
  attempt_number: number;
  tool_id: string;
  capability_id: string;
  execution_started_at: string | null;
  execution_completed_at: string | null;
  working_directory_reference: string;
  command_records: BobaRecoveryCommandV1[];
  status: string;
  exit_code: number | null;
  timeout_occurred: boolean;
  output_artifact_refs: string[];
  temporary_artifact_refs: string[];
  failure_class: string;
  failure_summary: string;
  quality_change_disclosed: boolean;
  source_media_untouched: boolean;
  completed_outputs_untouched: boolean;
  validation_required: boolean;
  next_strategy_allowed: boolean;
  stop_reason: string;
  warnings: string[];
}

export interface BobaRecoveredOutputValidationV1 {
  output_validation_id: string;
  recovery_attempt_id: string;
  output_artifact_ref: string;
  artifact_exists: boolean;
  artifact_non_empty: boolean;
  checksum_valid: boolean | null;
  media_probe_valid: boolean | null;
  duration_valid: boolean | null;
  resolution_valid: boolean | null;
  frame_rate_valid: boolean | null;
  audio_presence_valid: boolean | null;
  audio_video_sync_valid: boolean | null;
  caption_timing_status: string;
  framing_status: string;
  source_window_status: string;
  schema_valid: boolean | null;
  required_checks_passed: boolean;
  failed_required_checks: string[];
  unavailable_required_checks: string[];
  quality_review_required: true;
  accepted_for_quality_review: boolean;
  rejected_reason: string;
  warnings: string[];
}

export interface BobaToolRecoveryRollbackV1 {
  rollback_record_id: string;
  recovery_attempt_id: string;
  trigger: string;
  scope: string;
  temporary_outputs_removed: boolean;
  prior_generated_state_restored: boolean;
  original_outputs_preserved: boolean;
  source_media_preserved: boolean;
  checkpoint_unchanged: boolean;
  rollback_validation_passed: boolean;
  status: string;
  human_review_required: boolean;
  warnings: string[];
}

export interface BobaToolRecoveryHandoffV1 {
  handoff_id: string;
  recovery_case_id: string;
  recovery_plan_id: string;
  recovery_attempt_id: string;
  target_module: string;
  reason: string;
  required_inputs: string[];
  required_quality_checks: string[];
  blocked_actions: string[];
  allowed_advisory_actions: string[];
  apply_automatically: false;
  human_approval_required: true;
  priority: string;
  warnings: string[];
}

export interface BobaToolRecoverySummaryV1 {
  total_recovery_cases: number;
  eligible_case_count: number;
  blocked_case_count: number;
  health_check_count: number;
  healthy_tool_count: number;
  unavailable_tool_count: number;
  recovery_plan_count: number;
  recovery_attempt_count: number;
  successful_pending_quality_count: number;
  failed_attempt_count: number;
  timeout_count: number;
  rollback_count: number;
  fallback_switch_count: number;
  checkpoint_block_count: number;
  quality_rejection_count: number;
  current_highest_priority_case: string;
  safest_available_strategy: string;
  required_human_actions: string[];
  limitations: string[];
}

export interface BobaToolRecoverySignalUsageV1 {
  repair_planner_used: boolean;
  repair_planner_artifact_read: boolean;
  root_cause_references_used: boolean;
  approval_record_used: boolean;
  capability_registry_used: boolean;
  local_health_checks_executed: boolean;
  recovery_commands_executed: boolean;
  local_fallback_used: boolean;
  checkpoint_reference_used: boolean;
  output_validation_used: boolean;
  rollback_used: boolean;
  source_media_modified: false;
  completed_outputs_modified: false;
  workflow_resume_used: false;
  code_modification_used: false;
  package_installation_used: false;
  service_restart_used: false;
  process_kill_used: false;
  external_api_used: false;
  network_access_used: false;
  url_fetching_used: false;
  scraping_used: false;
  downloading_used: false;
  uploading_used: false;
  paid_service_used: false;
  rights_bypass_used: false;
  safety_bypass_used: false;
  destructive_action_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaToolRecoveryBrainSetV1 {
  schema_version: "boba_tool_recovery_brain_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  repair_planner_source: string;
  recovery_cases: BobaToolRecoveryCaseV1[];
  capability_registry: BobaToolCapabilityV1[];
  registered_tools: BobaRegisteredRecoveryToolV1[];
  tool_health_results: BobaToolHealthResultV1[];
  recovery_plans: BobaToolRecoveryPlanV1[];
  recovery_attempts: BobaToolRecoveryAttemptV1[];
  output_validations: BobaRecoveredOutputValidationV1[];
  rollback_records: BobaToolRecoveryRollbackV1[];
  recovery_handoffs: BobaToolRecoveryHandoffV1[];
  recovery_summary: BobaToolRecoverySummaryV1;
  signal_usage: BobaToolRecoverySignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaToolRecoveryPlanInputV1 {
  selected_handoff_id?: string;
  selected_repair_strategy_id?: string;
  failure_context?: Record<string, unknown>;
  run_health_checks?: boolean;
}

export interface BobaToolRecoveryHealthInputV1 {
  tool_ids?: string[];
}

export interface BobaToolRecoveryExecuteInputV1 {
  recovery_plan_id: string;
  recovery_strategy_id: string;
  approval: BobaToolRecoveryApprovalV1;
}

export interface BobaToolRecoveryValidationInputV1 {
  recovery_attempt_id: string;
}

export interface BobaToolRecoveryRollbackInputV1 {
  recovery_attempt_id: string;
  trigger: string;
}

export interface BobaCreativeBriefV1 {
  clip_id: string;
  project_id: string;
  target_emotion: string;
  hook_type: string;
  curiosity_trigger: string;
  story_angle: string;
  recommended_duration_seconds: number;
  pacing_level: "calm" | "balanced" | "fast" | "aggressive";
  caption_style: string;
  motion_style: string;
  music_mood: string;
  editing_notes: string[];
  risk_warnings: string[];
  why_it_may_work: string;
  whole_video_understanding_used: boolean;
  understanding_guidance: string[];
}

export interface BobaCreativeBriefsResponse {
  project_id: string;
  count: number;
  briefs: BobaCreativeBriefV1[];
  rendering_triggered?: false;
}

export interface BobaWholeVideoStoryBeatV1 {
  start_seconds: number;
  end_seconds: number;
  summary: string;
  confidence: number;
  source_signals: string[];
}

export interface BobaWholeVideoUnderstandingV1 {
  schema_version: "boba_whole_video_understanding_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  video_duration_seconds: number;
  overall_summary: string;
  video_type: string;
  primary_topic: string;
  secondary_topics: string[];
  creator_intent: string;
  audience_value: string;
  tone: string;
  topic_timeline: Array<{
    segment_id: string;
    start_seconds: number;
    end_seconds: number;
    topic: string;
    summary: string;
    confidence: number;
    supporting_evidence: string[];
    source_signals: string[];
  }>;
  story_arc: {
    setup: BobaWholeVideoStoryBeatV1[];
    context: BobaWholeVideoStoryBeatV1[];
    build_up: BobaWholeVideoStoryBeatV1[];
    key_moments: BobaWholeVideoStoryBeatV1[];
    payoff: BobaWholeVideoStoryBeatV1[];
    conclusion: BobaWholeVideoStoryBeatV1[];
    unresolved_threads: string[];
    confidence: number;
  };
  emotional_beats: Array<{
    beat_id: string;
    start_seconds: number;
    end_seconds: number;
    emotion_label: string;
    intensity: number;
    reason: string;
    confidence: number;
    source_signals: string[];
  }>;
  context_payoff_map: Array<{
    link_id: string;
    context_start_seconds: number;
    context_end_seconds: number;
    payoff_start_seconds: number;
    payoff_end_seconds: number;
    description: string;
    standalone_clip_possible: boolean;
    setup_required: boolean;
    confidence: number;
  }>;
  section_scores: Array<{
    section_id: string;
    start_seconds: number;
    end_seconds: number;
    importance_score: number;
    clarity_score: number;
    energy_score: number;
    novelty_score: number;
    shortability_score: number;
    filler_score: number;
    repetition_score: number;
    reasons: string[];
    warnings: string[];
  }>;
  shortability_hints: Array<{
    hint_id: string;
    start_seconds: number;
    end_seconds: number;
    suggested_clip_type:
      | "candidate_for_short"
      | "needs_more_context"
      | "avoid_as_standalone"
      | "possible_hook"
      | "payoff_clip";
    hook_potential: number;
    setup_needed: boolean;
    payoff_strength: number;
    recommended_action: "consider" | "include_setup" | "avoid" | "review";
    reason: string;
  }>;
  signal_usage: {
    transcript_used: boolean;
    analysis_signals_used: boolean;
    story_used: boolean;
    virality_used: boolean;
    planning_used: boolean;
    memory_used: boolean;
    unavailable_signals: string[];
    fallback_used: boolean;
    warnings: string[];
  };
  warnings: string[];
  limitations: string[];
}

export type BobaCandidateClipType =
  | "hook_moment"
  | "payoff_moment"
  | "emotional_beat"
  | "story_turn"
  | "high_energy_section"
  | "explanation_section"
  | "curiosity_gap"
  | "motivational_moment"
  | "funny_moment"
  | "controversial_moment"
  | "educational_moment"
  | "unknown";

export interface BobaCandidateClipDiscoveryV1 {
  schema_version: "boba_candidate_clip_discovery_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  video_duration_seconds: number;
  summary: string;
  candidates: Array<{
    candidate_id: string;
    project_id: string;
    start_seconds: number;
    end_seconds: number;
    duration_seconds: number;
    suggested_title: string;
    hook_idea: string;
    story_angle: string;
    candidate_type: BobaCandidateClipType;
    discovery_reason: string;
    confidence: number;
    standalone_score: number;
    setup_required: boolean;
    payoff_present: boolean;
    context_needed: boolean;
    source_topic: string;
    emotion_label: string;
    virality_cues: string[];
    boundary_suggestion: {
      recommended_start_seconds: number;
      recommended_end_seconds: number;
      pre_roll_seconds: number;
      post_roll_seconds: number;
      abrupt_start_warning: boolean;
      abrupt_end_warning: boolean;
      reason: string;
    };
    evidence: {
      transcript_snippets: string[];
      source_signals: string[];
      topic_segment_ids: string[];
      emotional_beat_ids: string[];
      context_payoff_link_ids: string[];
      section_score_ids: string[];
      virality_reasons: string[];
    };
    warnings: string[];
  }>;
  rejected_windows: Array<{
    start_seconds: number;
    end_seconds: number;
    reason: string;
    overlap_with_candidate_id: string | null;
    confidence: number;
  }>;
  diversity_summary: {
    candidate_count: number;
    topic_count: number;
    emotion_count: number;
    candidate_types: BobaCandidateClipType[];
    duplicate_windows_removed: number;
    high_overlap_windows_removed: number;
    warnings: string[];
  };
  signal_usage: {
    whole_video_understanding_used: boolean;
    transcript_used: boolean;
    analysis_signals_used: boolean;
    story_used: boolean;
    virality_used: boolean;
    planning_used: boolean;
    memory_used: boolean;
    fallback_used: boolean;
    unavailable_signals: string[];
    warnings: string[];
  };
  warnings: string[];
  limitations: string[];
}

export type BobaRankingTier =
  | "must_make"
  | "strong_candidate"
  | "backup_candidate"
  | "needs_revision"
  | "reject";

export type BobaProductionPriority =
  | "immediate"
  | "high"
  | "medium"
  | "low"
  | "do_not_produce";

export interface BobaClipScoreBreakdownV1 {
  hook_score: number;
  payoff_score: number;
  standalone_score: number;
  emotional_score: number;
  clarity_score: number;
  novelty_score: number;
  pacing_score: number;
  retention_score: number;
  context_risk_score: number;
  repetition_penalty: number;
  overlap_penalty: number;
  rights_safety_penalty: number;
  memory_alignment_score: number;
  final_score: number;
}

export interface BobaRankedClipV1 {
  candidate_id: string;
  project_id: string;
  rank: number;
  tier: BobaRankingTier;
  total_score: number;
  confidence: number;
  production_priority: BobaProductionPriority;
  score_breakdown: BobaClipScoreBreakdownV1;
  ranking_reasons: string[];
  risk_warnings: string[];
  improvement_suggestions: string[];
  source_window: {
    start_seconds: number;
    end_seconds: number;
    duration_seconds: number;
  };
  candidate_type: string;
  suggested_title: string;
  hook_idea: string;
  story_angle: string;
  source_topic: string;
  emotion_label: string;
}

export interface BobaClipRankingV1 {
  schema_version: "boba_clip_ranking_brain_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  summary: string;
  ranked_candidates: BobaRankedClipV1[];
  recommended_clip_ids: string[];
  backup_clip_ids: string[];
  rejected_clip_ids: string[];
  rejected_candidates: Array<{
    candidate_id: string;
    reason: string;
    score: number;
    overlap_with_candidate_id: string | null;
    warning: string;
  }>;
  diversity_summary: {
    ranked_count: number;
    recommended_count: number;
    topic_count: number;
    emotion_count: number;
    candidate_type_count: number;
    overlap_penalties_applied: number;
    duplicate_candidates_removed: number;
    diversity_warnings: string[];
  };
  signal_usage: {
    candidate_discovery_used: boolean;
    whole_video_understanding_used: boolean;
    virality_used: boolean;
    story_used: boolean;
    planning_used: boolean;
    memory_used: boolean;
    fallback_used: boolean;
    unavailable_signals: string[];
    warnings: string[];
  };
  warnings: string[];
  limitations: string[];
}

export type BobaRenderReadiness =
  | "ready_for_render"
  | "needs_revision"
  | "blocked";

export type BobaPacingIntensity = "calm" | "moderate" | "fast" | "aggressive";

export type BobaCaptionStyle =
  | "clean_subtitles"
  | "bold_hook_captions"
  | "emotional_emphasis"
  | "keyword_highlight"
  | "minimal"
  | "punchline_caption"
  | "educational_steps"
  | "no_captions"
  | "none";

export type BobaMotionStyle =
  | "stable"
  | "subtle_zoom"
  | "dynamic_zoom"
  | "punch_in"
  | "high_motion"
  | "layout_safe"
  | "minimal_motion";

export type BobaMusicMood =
  | "none"
  | "motivational"
  | "emotional"
  | "suspense"
  | "energetic"
  | "calm"
  | "funny"
  | "cinematic"
  | "educational";

export type BobaSfxIntensity = "none" | "light" | "moderate" | "heavy";

export type BobaHookStrategy =
  | "curiosity_gap"
  | "emotional_reveal"
  | "problem_solution"
  | "contradiction"
  | "shocking_truth"
  | "motivational_payoff"
  | "story_turn"
  | "educational_open_loop"
  | "direct_value";

export interface BobaEditingInstructionPacketV1 {
  hook_instruction: string;
  cut_instruction: string;
  caption_instruction: string;
  motion_instruction: string;
  audio_instruction: string;
  pacing_instruction: string;
  retention_instruction: string;
  risk_instruction: string;
}

export interface BobaEditorialRiskReviewV1 {
  weak_hook: boolean;
  missing_context: boolean;
  weak_payoff: boolean;
  filler_risk: boolean;
  duplicate_risk: boolean;
  rights_risk: boolean;
  audio_risk: boolean;
  visual_layout_risk: boolean;
  unavailable_signal_risk: boolean;
  blockers: string[];
  warnings: string[];
}

export interface BobaEditorialRiskSummaryV1 {
  selected_count: number;
  ready_for_render_count: number;
  needs_revision_count: number;
  blocked_count: number;
  top_risks: string[];
  blockers: string[];
  warnings: string[];
}

export interface BobaEditorialSignalUsageV1 {
  clip_ranking_used: boolean;
  candidate_discovery_used: boolean;
  whole_video_understanding_used: boolean;
  creative_briefs_used: boolean;
  analysis_signals_used: boolean;
  story_used: boolean;
  virality_used: boolean;
  planning_used: boolean;
  memory_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaEditorialDecisionV1 {
  candidate_id: string;
  ranked_clip_id: string;
  project_id: string;
  rank: number;
  ranking_score: number;
  ranking_tier: BobaRankingTier;
  suggested_title: string;
  candidate_type: string;
  source_window: {
    start_seconds: number;
    end_seconds: number;
    duration_seconds: number;
  };
  selected: boolean;
  render_readiness: BobaRenderReadiness;
  render_readiness_reason: string;
  production_priority: BobaProductionPriority;
  final_story_angle: string;
  final_hook_strategy: BobaHookStrategy;
  opening_line_direction: string;
  pacing_intensity: BobaPacingIntensity;
  caption_style: BobaCaptionStyle;
  motion_style: BobaMotionStyle;
  music_mood: BobaMusicMood;
  sfx_intensity: BobaSfxIntensity;
  visual_emphasis: string[];
  retention_tactics: string[];
  editing_instruction_packet: BobaEditingInstructionPacketV1;
  risk_review: BobaEditorialRiskReviewV1;
  decision_reasons: string[];
  improvement_notes: string[];
  confidence: number;
}

export interface BobaEditorialDecisionSetV1 {
  schema_version: "boba_editorial_decision_engine_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  summary: string;
  selected_clip_ids: string[];
  rejected_clip_ids: string[];
  production_order: string[];
  decisions: BobaEditorialDecisionV1[];
  risk_summary: BobaEditorialRiskSummaryV1;
  signal_usage: BobaEditorialSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export type BobaExplanationType =
  | "discovery"
  | "ranking"
  | "editorial"
  | "render_readiness"
  | "rejection"
  | "project_summary";

export type BobaEvidenceType =
  | "transcript_snippet"
  | "score"
  | "signal"
  | "warning"
  | "memory_lesson"
  | "context_payoff"
  | "emotional_beat"
  | "ranking_factor"
  | "editorial_risk";

export type BobaUncertaintyLevel = "low" | "medium" | "high";

export interface BobaExplanationEvidenceV1 {
  evidence_type: BobaEvidenceType;
  source_artifact: string;
  source_field: string;
  snippet: string;
  score: number | null;
  timestamp_seconds: number | null;
  confidence: number;
}

export interface BobaClipExplanationV1 {
  clip_id: string;
  candidate_id: string;
  explanation_type: BobaExplanationType;
  short_summary: string;
  detailed_explanation: string;
  key_reasons: string[];
  evidence: BobaExplanationEvidenceV1[];
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaProjectExplanationV1 {
  overall_summary: string;
  top_recommendation_reason: string;
  strongest_clip_types: string[];
  weakest_clip_types: string[];
  unavailable_signals: string[];
  main_uncertainties: string[];
  human_review_notes: string[];
}

export interface BobaSignalExplanationV1 {
  signals_used: string[];
  signals_missing: string[];
  fallback_signals: string[];
  how_signals_affected_decisions: string[];
  warnings: string[];
}

export interface BobaUncertaintySummaryV1 {
  uncertainty_level: BobaUncertaintyLevel;
  reasons: string[];
  missing_evidence: string[];
  recommended_human_checks: string[];
}

export interface BobaExplanationSetV1 {
  schema_version: "boba_explanation_engine_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  project_summary: BobaProjectExplanationV1;
  candidate_explanations: BobaClipExplanationV1[];
  ranking_explanations: BobaClipExplanationV1[];
  editorial_explanations: BobaClipExplanationV1[];
  signal_explanation: BobaSignalExplanationV1;
  uncertainty_summary: BobaUncertaintySummaryV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaOpeningThreeSecondPlanV2 {
  what_viewer_sees_first: string;
  caption_implication: string;
  curiosity_gap: string;
  motion_choice: string;
  avoid: string[];
}

export interface BobaHookTreatmentV2 {
  hook_type: string;
  opening_line_direction: string;
  first_visual_emphasis: string;
  curiosity_trigger: string;
  pattern_interrupt: string;
  reason_it_should_work: string;
  hook_risk: string;
}

export interface BobaPacingMapV2 {
  first_3_seconds: string;
  seconds_3_to_10: string;
  middle_section: string;
  payoff_section: string;
  ending: string;
  pacing_intensity: string;
  filler_cut_notes: string[];
}

export interface BobaCaptionDirectionV2 {
  style: string;
  emphasis_words: string[];
  rhythm: string;
  highlight_moments: string[];
  readability_notes: string[];
  warnings: string[];
}

export interface BobaMotionDirectionV2 {
  style: string;
  zoom_moments: string[];
  punch_in_moments: string[];
  stable_moments: string[];
  layout_safe_moments: string[];
  visual_emphasis_moments: string[];
  safety_warnings: string[];
}

export interface BobaAudioDirectionV2 {
  music_mood: string;
  sfx_intensity: string;
  ducking_guidance: string;
  silence_notes: string;
  speech_clarity_notes: string;
  warnings: string[];
}

export interface BobaRetentionPlanV2 {
  opening_hook: string;
  curiosity_loop: string;
  mid_clip_hold: string;
  payoff_delivery: string;
  replay_trigger: string;
  retention_risks: string[];
}

export interface BobaEmotionalArcV2 {
  starting_emotion: string;
  build_emotion: string;
  payoff_emotion: string;
  intended_viewer_feeling: string;
  emotional_risk: string;
}

export interface BobaCreativeQualityScoreV2 {
  hook_quality: number;
  clarity: number;
  emotional_pull: number;
  pacing_strength: number;
  visual_direction_strength: number;
  caption_strength: number;
  audio_direction_strength: number;
  overall_confidence: number;
}

export interface BobaCreativeDirectorSignalUsageV2 {
  editorial_decisions_used: boolean;
  explanations_used: boolean;
  clip_ranking_used: boolean;
  candidate_discovery_used: boolean;
  whole_video_understanding_used: boolean;
  analysis_signals_used: boolean;
  memory_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaProjectCreativeDirectionV2 {
  overall_style: string;
  tone: string;
  pacing_philosophy: string;
  caption_philosophy: string;
  motion_philosophy: string;
  audio_philosophy: string;
  target_viewer_feeling: string;
  human_review_notes: string[];
}

export interface BobaClipCreativeDirectionV2 {
  candidate_id: string;
  ranked_clip_id: string;
  project_id: string;
  selected: boolean;
  render_readiness: string;
  final_clip_angle: string;
  hook_treatment: BobaHookTreatmentV2;
  opening_three_second_plan: BobaOpeningThreeSecondPlanV2;
  story_framing: string;
  pacing_map: BobaPacingMapV2;
  caption_direction: BobaCaptionDirectionV2;
  motion_direction: BobaMotionDirectionV2;
  audio_direction: BobaAudioDirectionV2;
  retention_plan: BobaRetentionPlanV2;
  emotional_arc: BobaEmotionalArcV2;
  creative_quality_score: BobaCreativeQualityScoreV2;
  risk_fixes: string[];
  editor_notes: string[];
  warnings: string[];
  confidence: number;
}

export interface BobaCreativeDirectionSetV2 {
  schema_version: "boba_creative_director_v2";
  project_id: string;
  source_id: string;
  created_at: string;
  project_direction: BobaProjectCreativeDirectionV2;
  clip_directions: BobaClipCreativeDirectionV2[];
  creative_quality_summary: BobaCreativeQualityScoreV2;
  signal_usage: BobaCreativeDirectorSignalUsageV2;
  warnings: string[];
  limitations: string[];
}

export type BobaBriefInstructionType =
  | "hook"
  | "opening"
  | "story"
  | "cut"
  | "caption"
  | "motion"
  | "audio"
  | "sfx"
  | "retention"
  | "risk";

export type BobaBriefInstructionPriority =
  | "must_follow"
  | "should_follow"
  | "optional";

export type BobaEditorChecklistCategory =
  | "hook"
  | "context"
  | "payoff"
  | "pacing"
  | "captions"
  | "motion"
  | "audio"
  | "rights"
  | "render_safety"
  | "human_review";

export type BobaEditorChecklistStatus =
  | "pending"
  | "passed"
  | "warning"
  | "blocked";

export interface BobaSourceWindowV1 {
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
}

export interface BobaBriefInstructionV1 {
  instruction_type: BobaBriefInstructionType;
  summary: string;
  do_this: string;
  avoid_this: string;
  reason: string;
  priority: BobaBriefInstructionPriority;
}

export interface BobaEditorChecklistItemV1 {
  item_id: string;
  label: string;
  category: BobaEditorChecklistCategory;
  required: boolean;
  status: BobaEditorChecklistStatus;
  reason: string;
}

export interface BobaClipBriefSignalUsageV1 {
  creative_direction_v2_used: boolean;
  editorial_decision_used: boolean;
  explanation_used: boolean;
  clip_ranking_used: boolean;
  candidate_discovery_used: boolean;
  whole_video_understanding_used: boolean;
  memory_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaClipBriefV1 {
  brief_id: string;
  project_id: string;
  candidate_id: string;
  ranked_clip_id: string;
  source_window: BobaSourceWindowV1;
  production_priority: "immediate" | "high" | "medium" | "low" | "do_not_produce";
  render_readiness: "ready_for_render" | "needs_revision" | "blocked";
  brief_title: string;
  final_clip_angle: string;
  target_viewer_feeling: string;
  hook_instruction: BobaBriefInstructionV1;
  opening_three_second_instruction: BobaBriefInstructionV1;
  story_instruction: BobaBriefInstructionV1;
  cut_instruction: BobaBriefInstructionV1;
  caption_instruction: BobaBriefInstructionV1;
  motion_instruction: BobaBriefInstructionV1;
  audio_instruction: BobaBriefInstructionV1;
  sfx_instruction: BobaBriefInstructionV1;
  retention_instruction: BobaBriefInstructionV1;
  risk_fixes: string[];
  editor_checklist: BobaEditorChecklistItemV1[];
  human_review_notes: string[];
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaClipBriefSetV1 {
  project_id: string;
  source_id: string;
  created_at: string;
  brief_version: "boba_clip_brief_generator_v1";
  selected_briefs: BobaClipBriefV1[];
  backup_briefs: BobaClipBriefV1[];
  blocked_briefs: BobaClipBriefV1[];
  production_order: string[];
  project_summary: string;
  signal_usage: BobaClipBriefSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export type BobaHookType =
  | "curiosity_gap"
  | "emotional_reveal"
  | "contradiction"
  | "shocking_truth"
  | "problem_solution"
  | "motivational_payoff"
  | "story_turn"
  | "educational_open_loop"
  | "direct_value"
  | "mystery"
  | "tension"
  | "humor"
  | "unknown";

export type BobaHookRecommendationLabel =
  | "best"
  | "safest"
  | "boldest"
  | "backup"
  | "avoid";

export interface BobaHookAnalysisV1 {
  hook_type: BobaHookType;
  hook_strength: number;
  curiosity_gap: string;
  first_three_second_clarity: number;
  pattern_interrupt: string;
  opening_line_direction: string;
  visual_opening_direction: string;
  hook_risk: string;
  improved_hook_direction: string;
  reason: string;
}

export interface BobaHookAlternativeV1 {
  alternative_id: string;
  hook_type: BobaHookType;
  opening_line_direction: string;
  caption_direction: string;
  visual_direction: string;
  strength_score: number;
  risk_score: number;
  why_it_may_work: string;
  why_it_may_fail: string;
  recommendation_label: BobaHookRecommendationLabel;
}

export interface BobaRetentionPlanV1 {
  seconds_0_to_3: string;
  seconds_3_to_10: string;
  middle_hold_strategy: string;
  payoff_timing_strategy: string;
  ending_replay_trigger: string;
  pacing_notes: string[];
  retention_tactics: string[];
}

export interface BobaRetentionRiskReviewV1 {
  slow_start_risk: boolean;
  unclear_context_risk: boolean;
  weak_payoff_risk: boolean;
  filler_risk: boolean;
  over_editing_risk: boolean;
  under_editing_risk: boolean;
  caption_overload_risk: boolean;
  audio_distraction_risk: boolean;
  risk_fixes: string[];
  blockers: string[];
  warnings: string[];
}

export interface BobaRetentionScoreV1 {
  hook_score: number;
  curiosity_score: number;
  clarity_score: number;
  momentum_score: number;
  payoff_score: number;
  replay_score: number;
  dropoff_risk_score: number;
  overall_retention_score: number;
}

export interface BobaBriefHookEnhancementV1 {
  brief_id: string;
  enhanced_opening_line_direction: string;
  enhanced_pattern_interrupt: string;
  enhanced_caption_hook: string;
  enhanced_payoff_timing: string;
  enhanced_replay_trigger: string;
  retention_warning: string;
  apply_suggestion: false;
}

export interface BobaHookRetentionSignalUsageV1 {
  clip_briefs_used: boolean;
  creative_direction_used: boolean;
  editorial_decision_used: boolean;
  clip_ranking_used: boolean;
  candidate_discovery_used: boolean;
  whole_video_understanding_used: boolean;
  explanation_used: boolean;
  virality_used: boolean;
  memory_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaHookRetentionAnalysisV1 {
  analysis_id: string;
  project_id: string;
  candidate_id: string;
  brief_id: string;
  source_window: BobaSourceWindowV1;
  hook_analysis: BobaHookAnalysisV1;
  hook_alternatives: BobaHookAlternativeV1[];
  retention_plan: BobaRetentionPlanV1;
  retention_risk_review: BobaRetentionRiskReviewV1;
  retention_score: BobaRetentionScoreV1;
  brief_enhancements: BobaBriefHookEnhancementV1;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaHookRetentionSetV1 {
  schema_version: "boba_hook_retention_brain_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  analyses: BobaHookRetentionAnalysisV1[];
  project_retention_summary: string;
  signal_usage: BobaHookRetentionSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export type BobaCaptionDensity = "low" | "medium" | "high";
export type BobaCaptionRhythm = "calm" | "normal" | "fast" | "punchy";
export type BobaMotionIntensity = "none" | "light" | "moderate" | "high";

export interface BobaCaptionRecommendationV1 {
  caption_style: BobaCaptionStyle;
  caption_density: BobaCaptionDensity;
  caption_rhythm: BobaCaptionRhythm;
  hook_caption_instruction: string;
  keyword_highlights: string[];
  emotional_emphasis_words: string[];
  payoff_caption_instruction: string;
  readability_notes: string[];
  avoid_this: string[];
  reason: string;
}

export interface BobaMotionRecommendationV1 {
  motion_style: BobaMotionStyle;
  motion_intensity: BobaMotionIntensity;
  zoom_moments: string[];
  punch_in_moments: string[];
  stable_moments: string[];
  layout_safe_moments: string[];
  visual_emphasis_moments: string[];
  payoff_emphasis_moment: string;
  avoid_this: string[];
  reason: string;
}

export interface BobaCaptionMotionTimestampV1 {
  start_seconds: number;
  end_seconds: number;
  action: string;
  reason: string;
  priority: "required" | "recommended" | "optional";
}

export interface BobaCaptionMotionTimingMapV1 {
  seconds_0_to_3: string;
  seconds_3_to_10: string;
  middle_section: string;
  payoff_section: string;
  ending_section: string;
  caption_highlight_timestamps: BobaCaptionMotionTimestampV1[];
  motion_timestamps: BobaCaptionMotionTimestampV1[];
}

export interface BobaCaptionMotionSafetyReviewV1 {
  face_cutoff_risk: boolean;
  multi_speaker_layout_risk: boolean;
  unavailable_face_signal_risk: boolean;
  unavailable_layout_signal_risk: boolean;
  caption_overload_risk: boolean;
  readability_risk: boolean;
  over_motion_risk: boolean;
  under_motion_risk: boolean;
  hook_distraction_risk: boolean;
  blockers: string[];
  warnings: string[];
  fixes: string[];
}

export interface BobaCaptionMotionScoreV1 {
  caption_fit_score: number;
  caption_readability_score: number;
  motion_fit_score: number;
  motion_safety_score: number;
  hook_support_score: number;
  retention_support_score: number;
  overall_recommendation_score: number;
}

export interface BobaCaptionMotionBriefEnhancementV1 {
  brief_id: string;
  improved_caption_instruction: string;
  improved_motion_instruction: string;
  keyword_highlights: string[];
  zoom_notes: string[];
  punch_in_notes: string[];
  layout_safe_warning: string;
  readability_warning: string;
  apply_suggestion: false;
}

export interface BobaCaptionMotionSignalUsageV1 {
  clip_briefs_used: boolean;
  hook_retention_used: boolean;
  creative_direction_used: boolean;
  editorial_decision_used: boolean;
  clip_ranking_used: boolean;
  candidate_discovery_used: boolean;
  whole_video_understanding_used: boolean;
  explanation_used: boolean;
  face_motion_validation_used: boolean;
  multi_speaker_validation_used: boolean;
  analysis_signals_used: boolean;
  memory_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaCaptionMotionRecommendationV1 {
  recommendation_id: string;
  project_id: string;
  candidate_id: string;
  brief_id: string;
  source_window: BobaSourceWindowV1;
  caption_recommendation: BobaCaptionRecommendationV1;
  motion_recommendation: BobaMotionRecommendationV1;
  timing_map: BobaCaptionMotionTimingMapV1;
  safety_review: BobaCaptionMotionSafetyReviewV1;
  recommendation_score: BobaCaptionMotionScoreV1;
  brief_enhancement: BobaCaptionMotionBriefEnhancementV1;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaCaptionMotionRecommendationSetV1 {
  schema_version: "boba_caption_motion_recommendation_brain_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  recommendations: BobaCaptionMotionRecommendationV1[];
  project_caption_motion_summary: string;
  signal_usage: BobaCaptionMotionSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export type BobaMusicMoodRecommendationNameV1 =
  | "motivational"
  | "emotional"
  | "cinematic"
  | "calm"
  | "tense"
  | "suspenseful"
  | "inspiring"
  | "funny"
  | "dramatic"
  | "educational_clean"
  | "luxury"
  | "heroic"
  | "mysterious"
  | "upbeat"
  | "minimal"
  | "no_music"
  | "unknown";

export type BobaAudioEnergyLevelV1 = "none" | "low" | "medium" | "high";
export type BobaSpeechPriorityV1 = "low" | "medium" | "high" | "critical";
export type BobaMusicMoodSfxIntensityV1 = "none" | "light" | "moderate" | "high";

export interface BobaMusicMoodV1 {
  primary_mood: BobaMusicMoodRecommendationNameV1;
  secondary_mood: BobaMusicMoodRecommendationNameV1;
  energy_level: BobaAudioEnergyLevelV1;
  emotional_direction: string;
  pacing_fit: string;
  music_role:
    | "support_speech"
    | "build_emotion"
    | "create_tension"
    | "increase_energy"
    | "preserve_silence"
    | "emphasize_payoff"
    | "stay_minimal";
  avoid_this: string[];
  reason: string;
}

export interface BobaAudioEnergyMapV1 {
  seconds_0_to_3: string;
  seconds_3_to_10: string;
  middle_section: string;
  payoff_section: string;
  ending_section: string;
  energy_shift_notes: string[];
  silence_moments: string[];
}

export interface BobaSpeechClarityPlanV1 {
  speech_priority: BobaSpeechPriorityV1;
  ducking_guidance: string;
  music_volume_guidance: string;
  sfx_volume_guidance: string;
  silence_guidance: string;
  clarity_risk: boolean;
  warnings: string[];
}

export interface BobaMusicMoodSfxRecommendationV1 {
  sfx_intensity: BobaMusicMoodSfxIntensityV1;
  hook_sfx_guidance: string;
  transition_sfx_guidance: string;
  payoff_sfx_guidance: string;
  avoid_sfx_moments: string[];
  reason: string;
  warnings: string[];
}

export interface BobaAudioRiskReviewV1 {
  music_overpowering_risk: boolean;
  wrong_mood_risk: boolean;
  speech_clarity_risk: boolean;
  sfx_overload_risk: boolean;
  silence_damage_risk: boolean;
  emotional_mismatch_risk: boolean;
  rights_review_required: boolean;
  blockers: string[];
  warnings: string[];
  fixes: string[];
}

export interface BobaMusicMoodScoreV1 {
  mood_fit_score: number;
  speech_clarity_score: number;
  sfx_fit_score: number;
  emotional_fit_score: number;
  retention_support_score: number;
  overall_audio_score: number;
}

export interface BobaMusicMoodBriefEnhancementV1 {
  brief_id: string;
  improved_audio_instruction: string;
  improved_music_mood: BobaMusicMoodRecommendationNameV1;
  improved_sfx_instruction: string;
  ducking_warning: string;
  speech_clarity_warning: string;
  rights_review_warning: string;
  apply_suggestion: false;
}

export interface BobaMusicMoodSignalUsageV1 {
  clip_briefs_used: boolean;
  hook_retention_used: boolean;
  caption_motion_used: boolean;
  creative_direction_used: boolean;
  editorial_decision_used: boolean;
  clip_ranking_used: boolean;
  candidate_discovery_used: boolean;
  whole_video_understanding_used: boolean;
  explanation_used: boolean;
  audio_signals_used: boolean;
  silence_signals_used: boolean;
  music_manifest_seen: boolean;
  memory_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaMusicMoodRecommendationV1 {
  recommendation_id: string;
  project_id: string;
  candidate_id: string;
  brief_id: string;
  source_window: BobaSourceWindowV1;
  music_mood: BobaMusicMoodV1;
  audio_energy_map: BobaAudioEnergyMapV1;
  speech_clarity_plan: BobaSpeechClarityPlanV1;
  sfx_recommendation: BobaMusicMoodSfxRecommendationV1;
  audio_risk_review: BobaAudioRiskReviewV1;
  recommendation_score: BobaMusicMoodScoreV1;
  brief_enhancement: BobaMusicMoodBriefEnhancementV1;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaMusicMoodRecommendationSetV1 {
  schema_version: "boba_music_mood_brain_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  recommendations: BobaMusicMoodRecommendationV1[];
  project_audio_summary: string;
  signal_usage: BobaMusicMoodSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export type BobaCreatorFeedbackEventType =
  | "approval"
  | "rejection"
  | "rating"
  | "chosen_alternative"
  | "correction"
  | "preference_note"
  | "manual_tag"
  | "reset"
  | "export";

export type BobaCreatorFeedbackTargetType =
  | "clip"
  | "candidate"
  | "ranked_clip"
  | "editorial_decision"
  | "explanation"
  | "creative_direction"
  | "clip_brief"
  | "hook_alternative"
  | "caption_motion"
  | "music_mood"
  | "project";

export type BobaCreatorUserAction =
  | "approved"
  | "rejected"
  | "liked"
  | "disliked"
  | "chose"
  | "corrected"
  | "noted"
  | "tagged"
  | "reset_requested"
  | "export_requested";

export type BobaCreatorPreferenceCategory =
  | "clip_type"
  | "hook_style"
  | "caption_style"
  | "motion_style"
  | "music_mood"
  | "pacing"
  | "story_angle"
  | "risk_sensitivity"
  | "production_priority"
  | "general";

export type BobaCreatorLearningModule =
  | "ranking"
  | "editorial_decision"
  | "creative_director"
  | "clip_brief"
  | "hook_retention"
  | "caption_motion"
  | "music_mood"
  | "all";

export interface BobaExtractedPreferenceV1 {
  preference_id: string;
  category: BobaCreatorPreferenceCategory;
  preference: string;
  polarity: "prefer" | "avoid" | "neutral";
  strength: number;
  evidence: string[];
  confidence: number;
  applies_to_modules: BobaCreatorLearningModule[];
}

export interface BobaCreatorFeedbackEventV1 {
  event_id: string;
  project_id: string;
  created_at: string;
  event_type: BobaCreatorFeedbackEventType;
  target_type: BobaCreatorFeedbackTargetType;
  target_id: string;
  user_action: BobaCreatorUserAction;
  rating: number | null;
  note: string;
  tags: string[];
  extracted_preferences: BobaExtractedPreferenceV1[];
  reversible: boolean;
  source_artifacts: string[];
  warnings: string[];
}

export interface BobaCreatorFeedbackEventInput {
  event_type: BobaCreatorFeedbackEventType;
  target_type: BobaCreatorFeedbackTargetType;
  target_id: string;
  user_action: BobaCreatorUserAction;
  rating?: number | null;
  note?: string;
  tags?: string[];
  reversible?: boolean;
}

export interface BobaCreatorLearningProfileV1 {
  creator_id: string;
  profile_version: "1";
  updated_at: string;
  preferred_clip_types: string[];
  avoided_clip_types: string[];
  preferred_hook_styles: string[];
  avoided_hook_styles: string[];
  preferred_caption_styles: string[];
  avoided_caption_styles: string[];
  preferred_motion_styles: string[];
  avoided_motion_styles: string[];
  preferred_music_moods: string[];
  avoided_music_moods: string[];
  pacing_preferences: string[];
  story_angle_preferences: string[];
  risk_sensitivities: string[];
  repeated_feedback: string[];
  confidence: number;
  data_points: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaLearningInsightV1 {
  insight_id: string;
  category: BobaCreatorPreferenceCategory;
  summary: string;
  evidence_count: number;
  confidence: number;
  suggested_adjustment: string;
  affected_modules: BobaCreatorLearningModule[];
  warnings: string[];
}

export interface BobaRecommendationGuidanceV1 {
  ranking_guidance: string[];
  editorial_guidance: string[];
  creative_direction_guidance: string[];
  clip_brief_guidance: string[];
  hook_retention_guidance: string[];
  caption_motion_guidance: string[];
  music_mood_guidance: string[];
  general_guidance: string[];
  apply_automatically: false;
}

export interface BobaLearningAuditSummaryV1 {
  total_events: number;
  approval_count: number;
  rejection_count: number;
  correction_count: number;
  note_count: number;
  reversible_event_count: number;
  irreversible_event_count: number;
  last_event_at: string | null;
  reset_available: boolean;
  export_available: boolean;
  warnings: string[];
}

export interface BobaCreatorLearningSignalUsageV1 {
  boba_memory_used: boolean;
  feedback_events_used: number;
  clip_ranking_used: boolean;
  editorial_decision_used: boolean;
  explanation_used: boolean;
  creative_direction_used: boolean;
  clip_briefs_used: boolean;
  hook_retention_used: boolean;
  caption_motion_used: boolean;
  music_mood_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaCreatorLearningSetV1 {
  schema_version: "boba_creator_learning_loop_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  learning_profile: BobaCreatorLearningProfileV1;
  feedback_events: BobaCreatorFeedbackEventV1[];
  learning_insights: BobaLearningInsightV1[];
  recommendation_guidance: BobaRecommendationGuidanceV1;
  audit_summary: BobaLearningAuditSummaryV1;
  signal_usage: BobaCreatorLearningSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export type BobaFeedbackFactorCategory =
  | "clip_type"
  | "hook"
  | "retention"
  | "pacing"
  | "context"
  | "payoff"
  | "caption"
  | "motion"
  | "music_mood"
  | "sfx"
  | "speech_clarity"
  | "editorial_selection"
  | "ranking"
  | "explanation_quality"
  | "rights_risk"
  | "render_readiness"
  | "general";

export type BobaDecisionAttributionModule =
  | "candidate_discovery"
  | "clip_ranking"
  | "editorial_decision"
  | "creative_director"
  | "clip_brief"
  | "hook_retention"
  | "caption_motion"
  | "music_mood"
  | "explanation"
  | "creator_learning"
  | "unknown";

export interface BobaFeedbackFactorV1 {
  factor_id: string;
  category: BobaFeedbackFactorCategory;
  polarity: "positive" | "negative" | "neutral" | "uncertain";
  summary: string;
  source_artifact: string;
  source_field: string;
  confidence: number;
  evidence_snippet: string;
}

export interface BobaCorrectionMappingV1 {
  mapping_id: string;
  feedback_event_id: string;
  candidate_id: string;
  problem_category: BobaFeedbackFactorCategory;
  affected_module: BobaDecisionAttributionModule;
  suggested_correction: string;
  future_rule_hint: string;
  strength: number;
  confidence: number;
  apply_automatically: false;
}

export interface BobaApprovalLearningCaseV1 {
  case_id: string;
  project_id: string;
  feedback_event_id: string;
  target_type: string;
  target_id: string;
  candidate_id: string;
  approved_reason_summary: string;
  what_boba_got_right: string[];
  approval_factors: BobaFeedbackFactorV1[];
  supporting_evidence: string[];
  reusable_pattern: string;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaRejectionLearningCaseV1 {
  case_id: string;
  project_id: string;
  feedback_event_id: string;
  target_type: string;
  target_id: string;
  candidate_id: string;
  rejected_reason_summary: string;
  likely_rejection_causes: BobaFeedbackFactorV1[];
  what_boba_got_wrong: string[];
  supporting_evidence: string[];
  correction_mapping: BobaCorrectionMappingV1[];
  future_avoidance_guidance: string[];
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaDecisionAttributionV1 {
  attribution_id: string;
  project_id: string;
  feedback_event_id: string;
  candidate_id: string;
  primary_module: BobaDecisionAttributionModule;
  secondary_modules: BobaDecisionAttributionModule[];
  attribution_reason: string;
  evidence: string[];
  confidence: number;
  warnings: string[];
}

export interface BobaApprovalRejectionPatternScoreV1 {
  pattern_id: string;
  pattern_type:
    | "repeated_approval"
    | "repeated_rejection"
    | "contradiction"
    | "weak_signal"
    | "strong_signal";
  category: BobaFeedbackFactorCategory;
  summary: string;
  approval_count: number;
  rejection_count: number;
  contradiction_count: number;
  confidence: number;
  strength: number;
  affected_modules: BobaDecisionAttributionModule[];
  guidance: string;
}

export interface BobaApprovalRejectionModuleGuidanceV1 {
  ranking_guidance: string[];
  editorial_guidance: string[];
  creative_director_guidance: string[];
  clip_brief_guidance: string[];
  hook_retention_guidance: string[];
  caption_motion_guidance: string[];
  music_mood_guidance: string[];
  explanation_guidance: string[];
  general_guidance: string[];
  apply_automatically: false;
}

export interface BobaApprovalRejectionAuditSummaryV1 {
  total_feedback_events_used: number;
  approval_events_used: number;
  rejection_events_used: number;
  ambiguous_events: number;
  attributed_cases: number;
  unattributed_cases: number;
  reversible: boolean;
  dry_run: boolean;
  export_available: boolean;
  reset_available: boolean;
  warnings: string[];
}

export interface BobaApprovalRejectionSignalUsageV1 {
  creator_learning_used: boolean;
  feedback_events_used: number;
  memory_used: boolean;
  clip_ranking_used: boolean;
  editorial_decision_used: boolean;
  explanation_used: boolean;
  creative_direction_used: boolean;
  clip_briefs_used: boolean;
  hook_retention_used: boolean;
  caption_motion_used: boolean;
  music_mood_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaApprovalRejectionLearningSetV1 {
  schema_version: "boba_approval_rejection_learning_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  approval_cases: BobaApprovalLearningCaseV1[];
  rejection_cases: BobaRejectionLearningCaseV1[];
  decision_attributions: BobaDecisionAttributionV1[];
  pattern_scores: BobaApprovalRejectionPatternScoreV1[];
  module_guidance: BobaApprovalRejectionModuleGuidanceV1;
  audit_summary: BobaApprovalRejectionAuditSummaryV1;
  signal_usage: BobaApprovalRejectionSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export type BobaExperimentTargetType =
  | "clip"
  | "candidate"
  | "clip_brief"
  | "hook_alternative"
  | "caption_motion"
  | "music_mood"
  | "creative_direction"
  | "project";

export type BobaExperimentType =
  | "hook_ab_test"
  | "caption_ab_test"
  | "motion_ab_test"
  | "music_mood_ab_test"
  | "sfx_ab_test"
  | "opening_ab_test"
  | "retention_ab_test"
  | "brief_ab_test"
  | "project_style_test";

export type BobaExperimentStatus =
  | "draft"
  | "needs_creator_approval"
  | "approved"
  | "rejected"
  | "completed_manually"
  | "cancelled";

export type BobaExperimentVariantType =
  | "hook"
  | "caption"
  | "motion"
  | "music_mood"
  | "sfx"
  | "opening"
  | "retention"
  | "brief"
  | "style";

export type BobaExperimentPrimaryMetric =
  | "manual_creator_preference"
  | "approval_rate"
  | "hook_quality_review"
  | "retention_quality_review"
  | "caption_readability_review"
  | "motion_safety_review"
  | "audio_fit_review"
  | "future_viewer_retention"
  | "future_viewer_engagement";

export interface BobaExperimentBaselineV1 {
  baseline_id: string;
  source_artifact: string;
  source_field: string;
  summary: string;
  current_instruction: string;
  strengths: string[];
  weaknesses: string[];
  confidence: number;
}

export interface BobaExperimentVariantV1 {
  variant_id: string;
  label: string;
  variant_type: BobaExperimentVariantType;
  summary: string;
  changed_variable: string;
  instruction: string;
  expected_effect: string;
  risk: string;
  should_test: boolean;
  reason: string;
}

export interface BobaExperimentHypothesisV1 {
  hypothesis_id: string;
  statement: string;
  reason: string;
  expected_improvement_area: string;
  confidence: number;
  assumptions: string[];
}

export interface BobaExperimentMetricPlanV1 {
  primary_metric: BobaExperimentPrimaryMetric;
  secondary_metrics: BobaExperimentPrimaryMetric[];
  manual_review_questions: string[];
  required_result_fields: string[];
  analytics_required_later: boolean;
  notes: string[];
}

export interface BobaExperimentSuccessCriteriaV1 {
  success_definition: string;
  minimum_manual_rating: number;
  approval_required: boolean;
  failure_conditions: string[];
  decision_rule: string;
}

export interface BobaExperimentRiskReviewV1 {
  rights_risk: boolean;
  clarity_risk: boolean;
  over_editing_risk: boolean;
  under_editing_risk: boolean;
  misleading_hook_risk: boolean;
  caption_overload_risk: boolean;
  motion_safety_risk: boolean;
  audio_mismatch_risk: boolean;
  speech_clarity_risk: boolean;
  warnings: string[];
  blockers: string[];
}

export interface BobaExperimentLearningHandoffV1 {
  consume_result_in_modules: string[];
  feedback_to_collect: string[];
  expected_learning_update: string;
  approval_rejection_learning_target: string;
  creator_learning_target: string;
  apply_automatically: false;
}

export interface BobaExperimentPlanV1 {
  experiment_id: string;
  project_id: string;
  target_type: BobaExperimentTargetType;
  target_id: string;
  candidate_id: string;
  brief_id: string;
  experiment_type: BobaExperimentType;
  title: string;
  baseline: BobaExperimentBaselineV1;
  variants: BobaExperimentVariantV1[];
  hypothesis: BobaExperimentHypothesisV1;
  metric_plan: BobaExperimentMetricPlanV1;
  success_criteria: BobaExperimentSuccessCriteriaV1;
  risk_review: BobaExperimentRiskReviewV1;
  learning_handoff: BobaExperimentLearningHandoffV1;
  required_creator_approval: boolean;
  status: BobaExperimentStatus;
  confidence: number;
  warnings: string[];
  limitations: string[];
}

export interface BobaRejectedExperimentIdeaV1 {
  idea_id: string;
  target_id: string;
  experiment_type: BobaExperimentType;
  reason_rejected: string;
  risk: string;
  warnings: string[];
}

export interface BobaExperimentApprovalRequirementV1 {
  requirement_id: string;
  experiment_id: string;
  approval_type:
    | "creator_approval"
    | "rights_review"
    | "human_review"
    | "safety_review";
  reason: string;
  required_before_status: BobaExperimentStatus;
  warnings: string[];
}

export interface BobaExperimentationSignalUsageV1 {
  clip_briefs_used: boolean;
  hook_retention_used: boolean;
  caption_motion_used: boolean;
  music_mood_used: boolean;
  creative_direction_used: boolean;
  editorial_decision_used: boolean;
  explanation_used: boolean;
  creator_learning_used: boolean;
  approval_rejection_learning_used: boolean;
  memory_used: boolean;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaExperimentationSetV1 {
  schema_version: "boba_experimentation_system_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  experiment_plans: BobaExperimentPlanV1[];
  rejected_experiment_ideas: BobaRejectedExperimentIdeaV1[];
  experiment_summary: string;
  approval_requirements: BobaExperimentApprovalRequirementV1[];
  signal_usage: BobaExperimentationSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaExperimentManualResultV1 {
  result_id: string;
  experiment_id: string;
  selected_variant_id: string;
  manual_rating: number;
  creator_note: string;
  outcome_label:
    | "baseline_preferred"
    | "variant_preferred"
    | "no_clear_winner"
    | "rejected_all"
    | "needs_more_review";
  created_at: string;
  should_feed_learning: boolean;
  warnings: string[];
}

export type BobaPerformanceEventType =
  | "manual_clip_result"
  | "manual_experiment_result"
  | "manual_rating"
  | "manual_note"
  | "creator_interpretation"
  | "reset"
  | "export";

export type BobaPerformanceTargetType =
  | "clip"
  | "candidate"
  | "clip_brief"
  | "experiment"
  | "experiment_variant"
  | "project";

export type BobaPerformanceOutcomeLabel =
  | "baseline_won"
  | "variant_won"
  | "no_clear_winner"
  | "rejected_all"
  | "inconclusive"
  | "not_enough_data";

export type BobaPerformanceFactorCategory =
  | "clip_type"
  | "hook"
  | "retention"
  | "pacing"
  | "context"
  | "payoff"
  | "caption"
  | "motion"
  | "music_mood"
  | "sfx"
  | "speech_clarity"
  | "experiment_variant"
  | "platform_fit"
  | "general";

export type BobaPerformanceFactorPolarity =
  | "positive"
  | "negative"
  | "neutral"
  | "uncertain";

export interface BobaManualPerformanceMetricsV1 {
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  average_watch_time_seconds: number | null;
  average_view_duration_seconds: number | null;
  retention_percent: number | null;
  click_through_rate_percent: number | null;
  completion_rate_percent: number | null;
  follower_gain: number | null;
  manual_rank: number | null;
  custom_metrics: Record<string, number>;
}

export interface BobaPerformanceFeedbackEventV1 {
  event_id: string;
  project_id: string;
  created_at: string;
  event_type: BobaPerformanceEventType;
  target_type: BobaPerformanceTargetType;
  target_id: string;
  candidate_id: string;
  brief_id: string;
  experiment_id: string;
  variant_id: string;
  user_entered: true;
  manual_rating: number | null;
  creator_note: string;
  platform: string;
  source_label: string;
  metrics: BobaManualPerformanceMetricsV1;
  retention_notes: string;
  creator_interpretation: string;
  outcome_label: BobaPerformanceOutcomeLabel | null;
  baseline_id: string;
  selected_variant_id: string;
  should_feed_learning: boolean;
  warnings: string[];
}

export interface BobaPerformanceSnapshotV1 {
  snapshot_id: string;
  source_event_id: string;
  project_id: string;
  target_id: string;
  candidate_id: string;
  brief_id: string;
  platform: string;
  metrics: BobaManualPerformanceMetricsV1;
  manual_quality_rating: number | null;
  creator_notes: string;
  retention_notes: string;
  data_confidence: number;
  entered_at: string;
  warnings: string[];
  limitations: string[];
}

export interface BobaPerformanceFactorV1 {
  factor_id: string;
  category: BobaPerformanceFactorCategory;
  polarity: BobaPerformanceFactorPolarity;
  summary: string;
  source_artifact: string;
  source_field: string;
  confidence: number;
  evidence: string[];
}

export interface BobaExperimentOutcomeReviewV1 {
  outcome_id: string;
  project_id: string;
  experiment_id: string;
  baseline_id: string;
  selected_variant_id: string;
  outcome_label: BobaPerformanceOutcomeLabel;
  what_worked: string[];
  what_failed: string[];
  likely_success_factors: BobaPerformanceFactorV1[];
  likely_failure_factors: BobaPerformanceFactorV1[];
  confidence: number;
  should_feed_learning: boolean;
  learning_targets: string[];
  warnings: string[];
  limitations: string[];
}

export interface BobaPerformancePatternSummaryV1 {
  strongest_positive_patterns: BobaPerformanceFactorV1[];
  strongest_negative_patterns: BobaPerformanceFactorV1[];
  repeated_winners: string[];
  repeated_failures: string[];
  contradictions: string[];
  risky_conclusions: string[];
  confidence: number;
  warnings: string[];
}

export interface BobaPerformanceLearningHandoffV1 {
  creator_learning_updates: string[];
  approval_rejection_updates: string[];
  experimentation_updates: string[];
  ranking_guidance: string[];
  editorial_guidance: string[];
  hook_retention_guidance: string[];
  caption_motion_guidance: string[];
  music_mood_guidance: string[];
  apply_automatically: false;
}

export interface BobaPerformanceAuditSummaryV1 {
  total_events: number;
  manual_clip_results: number;
  manual_experiment_results: number;
  snapshots_count: number;
  outcomes_count: number;
  user_entered_count: number;
  auto_collected_count: 0;
  export_available: boolean;
  reset_available: boolean;
  warnings: string[];
}

export interface BobaPerformanceFeedbackSignalUsageV1 {
  experimentation_used: boolean;
  creator_learning_used: boolean;
  approval_rejection_used: boolean;
  clip_briefs_used: boolean;
  hook_retention_used: boolean;
  caption_motion_used: boolean;
  music_mood_used: boolean;
  clip_ranking_used: boolean;
  editorial_decision_used: boolean;
  memory_used: boolean;
  manual_feedback_used: boolean;
  analytics_api_used: false;
  fallback_used: boolean;
  unavailable_signals: string[];
  warnings: string[];
}

export interface BobaPerformanceFeedbackSetV1 {
  schema_version: "boba_performance_feedback_v1";
  project_id: string;
  source_id: string;
  created_at: string;
  performance_events: BobaPerformanceFeedbackEventV1[];
  performance_snapshots: BobaPerformanceSnapshotV1[];
  experiment_outcomes: BobaExperimentOutcomeReviewV1[];
  pattern_summary: BobaPerformancePatternSummaryV1;
  learning_handoff: BobaPerformanceLearningHandoffV1;
  audit_summary: BobaPerformanceAuditSummaryV1;
  signal_usage: BobaPerformanceFeedbackSignalUsageV1;
  warnings: string[];
  limitations: string[];
}

export interface BobaPerformanceFeedbackEventInput {
  event_type: BobaPerformanceEventType;
  target_type: BobaPerformanceTargetType;
  target_id: string;
  candidate_id?: string;
  brief_id?: string;
  experiment_id?: string;
  variant_id?: string;
  manual_rating?: number;
  creator_note?: string;
  platform?: string;
  source_label?: string;
  metrics?: Partial<BobaManualPerformanceMetricsV1>;
  retention_notes?: string;
  creator_interpretation?: string;
  outcome_label?: BobaPerformanceOutcomeLabel;
  baseline_id?: string;
  selected_variant_id?: string;
  should_feed_learning?: boolean;
}

export interface BobaPerformanceFeedbackEventResponse {
  event: BobaPerformanceFeedbackEventV1;
  performance_feedback: BobaPerformanceFeedbackSetV1;
  analytics_collected: false;
  automatically_applied: false;
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
  | "cancel_requested"
  | "stale"
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
  heartbeat_at?: string | null;
  duration_ms: number | null;
  progress_percent?: number;
  error: string | null;
  result: Record<string, unknown>;
  checkpoint?: Record<string, unknown>;
  resumable?: boolean;
  retryable?: boolean;
  skipped?: boolean;
  skip_reason?: string | null;
  warnings?: string[];
  errors?: string[];
  cancellation_requested?: boolean;
  cancellation_requested_at?: string | null;
  cancellation_reason?: string | null;
  logs: JobLogLine[];
}

export type DurableJobStatus =
  | "queued"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "canceled"
  | "cancel_requested"
  | "retrying"
  | "stale"
  | "blocked";

export interface DurableJob {
  schema_version: "durable_job_v2" | string;
  job_id: string;
  project_id: string;
  job_type: string;
  status: DurableJobStatus;
  current_stage: string | null;
  progress_percent: number;
  heartbeat_at: string | null;
  worker_id: string | null;
  resume: {
    resumable: boolean;
    resume_from_stage: string | null;
    completed_stage_count: number;
    pending_stage_count: number;
    stale_running_detected: boolean;
    reason: string | null;
  };
  cancellation: { requested: boolean; requested_at: string | null; reason: string | null };
  result: { success: boolean; warnings: string[]; errors: string[] } & Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  stages: Array<Record<string, unknown>>;
}

export interface DurableJobListResponse {
  jobs: DurableJob[];
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
  durable_job_v2?: DurableJob;
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
    cancel_requested?: number;
    stale?: number;
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


/* -------------------------------------------------------------------------- */
/* Project Management & Asset Library                                         */
/* -------------------------------------------------------------------------- */

/** Global dashboard statistics across everything Olympus has produced. */
export interface LibraryDashboard {
  total_projects: number;
  videos_processed: number;
  minutes_analyzed: number;
  clips_generated: number;
  renders_completed: number;
  exports: number;
  average_viral_score: number | null;
  storage_bytes: number;
  archived_projects: number;
}

export type AssetKind = "source_video" | "clip" | "render" | "export" | "thumbnail";

/** One managed asset in the asset library. */
export interface LibraryAsset {
  id: string;
  project_id: string;
  project_name: string;
  kind: AssetKind;
  name: string;
  created_at: string | null;
  storage_key: string | null;
  size_bytes: number | null;
  content_type: string | null;
  tags: string[];
  favorite: boolean;
  archived: boolean;
  metadata: Record<string, unknown>;
}

/** One clip Olympus produced, with its real per-clip facts. */
export interface LibraryClip {
  clip_id: string;
  project_id: string;
  project_name: string;
  title: string;
  duration: number | null;
  viral_score: number | null;
  platform: string | null;
  status: string;
  thumbnail_key: string | null;
  render_version: string | null;
  created_at: string | null;
  tags: string[];
  favorite: boolean;
}

/** One rendered export, with the renderer's real measured media facts. */
export interface LibraryExport {
  id: string;
  project_id: string;
  project_name: string;
  clip_id: string;
  platform: string | null;
  resolution: string | null;
  codec: string | null;
  bitrate_kbps: number | null;
  file_size: number | null;
  render_time_ms: number | null;
  download_status: string;
  storage_key: string | null;
  checksum: string | null;
  created_at: string | null;
}

/** One activity-feed event. */
export interface LibraryActivityEvent {
  id: string;
  ts: string;
  type: string;
  message: string;
  project_id: string | null;
  detail: Record<string, unknown>;
}

/** Per-project storage consumption broken down by namespace. */
export interface StorageBreakdown {
  project_id: string;
  project_name: string;
  namespaces: Record<string, number>;
  total: number;
}

/** A captured version snapshot of one engine's output. */
export interface LibraryVersion {
  project_id: string;
  engine: string;
  version: number;
  created_at: string;
  checksum: string;
  status: string | null;
  summary: Record<string, unknown>;
}

/** One global-search hit. */
export interface LibrarySearchHit {
  kind: string;
  id: string;
  project_id: string;
  title: string;
  subtitle: string;
  detail: Record<string, unknown>;
}

export interface AssetsResponse {
  count: number;
  assets: LibraryAsset[];
}
export interface ClipsResponse {
  count: number;
  clips: LibraryClip[];
}
export interface ExportsResponse {
  count: number;
  exports: LibraryExport[];
}
export interface ActivityFeedResponse {
  count: number;
  events: LibraryActivityEvent[];
}
export interface SearchResponse {
  query: string;
  count: number;
  hits: LibrarySearchHit[];
}
export interface StorageResponse {
  total_bytes: number;
  breakdowns: StorageBreakdown[];
}
export interface VersionEnginesResponse {
  project_id: string;
  engines: string[];
}
export interface VersionsResponse {
  project_id: string;
  engine: string;
  versions: LibraryVersion[];
}
export interface CleanupResultResponse {
  result: {
    operation: string;
    deleted_count: number;
    deleted_keys: string[];
    freed_bytes: number;
    note: string;
  };
}
export interface LibraryMetaResponse {
  meta: {
    project_id: string;
    archived: boolean;
    favorite: boolean;
    tags: string[];
    assets: Record<string, unknown>;
  };
}


/* -------------------------------------------------------------------------- */
/* Production Monitoring & Analytics                                          */
/* -------------------------------------------------------------------------- */

/** Measured per-engine performance metrics. `null` means UNKNOWN (unmeasured). */
export interface EngineMetricsItem {
  engine: string;
  runs: number;
  stage_executions: number;
  completed: number;
  failed: number;
  unavailable: number;
  cancelled: number;
  retries: number;
  avg_execution_ms: number | null;
  p95_execution_ms: number | null;
  total_execution_ms: number;
  avg_wait_ms: number | null;
  avg_queue_delay_ms: number | null;
  avg_confidence: number | null;
  throughput_per_hour: number | null;
  concurrent_executions: number;
  completion_rate: number | null;
  failure_rate: number | null;
  cancellation_rate: number | null;
}

/** A coarse health verdict for one engine. */
export interface EngineHealthItem {
  engine: string;
  status: string;
  detail: string;
  failure_rate: number | null;
}

/** Measured host metrics; `null` fields are genuinely unavailable here. */
export interface SystemMetrics {
  cpu_count: number | null;
  load_avg_1m: number | null;
  load_avg_5m: number | null;
  load_avg_15m: number | null;
  process_cpu_seconds: number | null;
  process_max_rss_bytes: number | null;
  system_memory_total_bytes: number | null;
  system_memory_available_bytes: number | null;
  disk_total_bytes: number | null;
  disk_used_bytes: number | null;
  disk_free_bytes: number | null;
  disk_used_pct: number | null;
  source: string;
  unavailable: string[];
}

/** A live snapshot of the workflow queue and worker pool. */
export interface QueueSnapshot {
  queued: number;
  running: number;
  delayed: number;
  completed: number;
  failed: number;
  dead: number;
  blocked: number;
  cancelled: number;
  active_workflows: number;
  worker_count: number;
  busy_workers: number;
  idle_workers: number;
  offline_workers: number;
  pool_running: boolean;
  worker_utilization: number | null;
  stuck_jobs: Record<string, unknown>[];
  dead_jobs: Record<string, unknown>[];
  avg_queue_latency_ms: number | null;
  workers: Record<string, unknown>[];
}

/** Aggregate workflow analytics across all project workflows. */
export interface WorkflowAnalytics {
  total_workflows: number;
  completed: number;
  failed: number;
  running: number;
  avg_duration_ms: number | null;
  avg_idle_ms: number | null;
  critical_path: Record<string, unknown>[];
  engine_bottlenecks: Record<string, unknown>[];
  slowest_projects: Record<string, unknown>[];
  fastest_projects: Record<string, unknown>[];
}

/** One captured point in the storage time series. */
export interface StoragePoint {
  ts: string;
  total_bytes: number;
  namespaces: Record<string, number>;
}

/** Current storage usage by namespace plus the captured trend series. */
export interface StorageAnalytics {
  total_bytes: number;
  namespaces: Record<string, number>;
  trend: StoragePoint[];
}

/** One observed failure (from a real persisted FAILED stage/job). */
export interface FailureRecord {
  engine: string;
  stage: string;
  project_id: string;
  ts: string | null;
  error: string | null;
  attempts: number;
}

/** Aggregated failure analytics (measured, never fabricated causes). */
export interface FailureSummary {
  total_failures: number;
  by_engine: Record<string, number>;
  by_exception: Record<string, number>;
  by_project: Record<string, number>;
  recent: FailureRecord[];
}

/** Measured platform usage totals. */
export interface UsageStats {
  projects: number;
  videos_processed: number;
  minutes_analyzed: number;
  clips: number;
  renders: number;
  exports: number;
  workflows_run: number;
  total_stage_executions: number;
  busiest_engine: string | null;
}

/** One cost line: the measured quantity, the rate, and the estimated cost. */
export interface CostLine {
  item: string;
  quantity: number | null;
  unit: string;
  rate_usd: number;
  estimated_usd: number | null;
  note: string;
}

/** An estimate (never billing) of operational cost from measured work. */
export interface CostEstimate {
  lines: CostLine[];
  total_usd: number;
  disclaimer: string;
}

/** One immutable, append-only audit entry. */
export interface AuditEntry {
  id: string;
  ts: string;
  action: string;
  message: string;
  project_id: string | null;
  source: string;
  detail: Record<string, unknown>;
}

/** An informational alert derived from measured state (no notifications). */
export interface Alert {
  id: string;
  severity: "info" | "warning" | "critical";
  category: string;
  message: string;
  evidence: Record<string, unknown>;
}

/* -- response envelopes ----------------------------------------------------- */
export interface MonitoringHealthResponse {
  overall: string;
  engines: EngineHealthItem[];
  system: SystemMetrics;
  queue: QueueSnapshot;
}
export interface EnginesResponse {
  engines: EngineMetricsItem[];
}
export interface FailuresResponse extends FailureSummary {}
export interface AuditResponse {
  count: number;
  entries: AuditEntry[];
}
export interface AlertsResponse {
  count: number;
  alerts: Alert[];
}

/** The combined admin dashboard payload (all real, measured). */
export interface AdminSnapshot {
  overall_health: string;
  engine_health: EngineHealthItem[];
  system: SystemMetrics | null;
  queue: QueueSnapshot | null;
  usage: UsageStats | null;
  storage_total_bytes: number;
  alerts: Alert[];
  recent_failures: FailureRecord[];
  recent_audit: AuditEntry[];
}
