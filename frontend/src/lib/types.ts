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
