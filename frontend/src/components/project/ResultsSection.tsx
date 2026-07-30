"use client";

import { useState } from "react";

import { CopyIcon, DownloadIcon, ServerIcon, SparklesIcon } from "@/components/icons";
import { EmptyState } from "@/components/ui/EmptyState";
import { mediaUrls } from "@/lib/apiClient";
import {
  useActivateCreatorProfile,
  useBobaApprovalRejectionLearning,
  useBobaAutopilot,
  useBobaBrain,
  useBobaCaptionMotion,
  useBobaCandidateClipDiscovery,
  useBobaCandidateVideoScorer,
  useBobaCodeSurgeon,
  useBobaErrorDoctor,
  useBobaObserver,
  useBobaRepairPlanner,
  useBobaRootCauseAnalyzer,
  useBobaRightsPermissionGate,
  useBobaToolRecovery,
  useBobaOutputQualityReviewer,
  useBobaCandidates,
  useBobaClipBriefs,
  useBobaClipRanking,
  useBobaContentScoutV2,
  useBobaCreativeDirectionV2,
  useBobaCreatorLearning,
  useBobaCreatorMemory,
  useBobaCreativeBriefs,
  useBobaEditorialDecisions,
  useBobaExplanations,
  useBobaExperimentation,
  useBobaHookRetention,
  useBobaMusicMood,
  useBobaPerformanceFeedback,
  useBobaProjectMemory,
  useBobaResearchBrain,
  useBobaTrendTopicWatcher,
  useBobaWholeVideoUnderstanding,
  useCreateCreatorProfile,
  useCreateBobaAutopilotRun,
  useCreateBobaEditorialDecisions,
  useCreateBobaClipBriefs,
  useCreateBobaCaptionMotion,
  useCreateBobaCreativeDirectionV2,
  useCreateBobaExplanations,
  useCreateBobaHookRetention,
  useCreateBobaMusicMood,
  useCreatorProfiles,
  useExportCreatorProfile,
  useExportBobaAutopilot,
  useExportBobaApprovalRejectionLearning,
  useExportBobaCandidateVideoScorer,
  useExportBobaCodeSurgeon,
  useExportBobaErrorDoctor,
  useExportBobaObserver,
  useExportBobaRepairPlanner,
  useExportBobaRootCauseAnalyzer,
  useExportBobaRightsPermissionGate,
  useExportBobaToolRecovery,
  useExportBobaOutputQualityReviewer,
  useExportBobaContentScoutV2,
  useExportBobaCreatorLearning,
  useExportBobaExperimentation,
  useExportBobaPerformanceFeedback,
  useExportBobaResearchBrain,
  useExportBobaTrendTopicWatcher,
  useDecideBobaCandidate,
  useDecideBobaCreativeBrief,
  useDiscoverBobaCandidateClips,
  useGenerateBobaCreativeBriefs,
  useGenerateBobaApprovalRejectionLearning,
  useGenerateBobaCandidateVideoScorer,
  useGenerateBobaErrorDoctor,
  useGenerateBobaObserver,
  useGenerateBobaRepairPlanner,
  useGenerateBobaRootCauseAnalyzer,
  useGenerateBobaRightsPermissionGate,
  useGenerateBobaToolRecoveryPlan,
  useGenerateBobaContentScoutV2,
  useGenerateBobaCreatorLearning,
  useGenerateBobaExperimentation,
  useGenerateBobaPerformanceFeedback,
  useGenerateBobaResearchBrain,
  useGenerateBobaTrendTopicWatcher,
  useGenerateBobaWholeVideoUnderstanding,
  useExecuteBobaCodeSurgeonPatch,
  useExecuteBobaToolRecovery,
  useAdvanceBobaAutopilotSafe,
  useCancelBobaAutopilot,
  useContinueBobaAutopilot,
  useCoordinateBobaAutopilotApproved,
  usePlans,
  useRenderManifest,
  useResetCreatorProfile,
  useResetBobaAutopilot,
  useResetBobaApprovalRejectionLearning,
  useResetBobaCandidateVideoScorer,
  useResetBobaCodeSurgeon,
  useResetBobaErrorDoctor,
  useResetBobaObserver,
  useResetBobaRepairPlanner,
  useResetBobaRootCauseAnalyzer,
  useResetBobaRightsPermissionGate,
  useResetBobaToolRecovery,
  useResetBobaOutputQualityReviewer,
  useResetBobaContentScoutV2,
  useResetBobaExperimentation,
  useResetBobaPerformanceFeedback,
  useResetBobaResearchBrain,
  useResetBobaTrendTopicWatcher,
  useRankBobaCandidateClips,
  useRecordBobaCreatorLearningEvent,
  useRecordBobaAutopilotHumanDecision,
  useRecordBobaPerformanceFeedbackEvent,
  useResetBobaCreatorLearning,
  usePrepareBobaCodeSurgeonCommit,
  useProposeBobaCodeSurgeon,
  useScoreBobaCandidate,
  useSubmitClipFeedback,
  useUpdateCreatorProfile,
  useValidateBobaCodeSurgeonPatch,
  useValidateBobaToolRecoveryOutput,
  useRollbackBobaToolRecovery,
  usePauseBobaAutopilot,
  usePlanBobaAutopilotNext,
  useRequestBobaAutopilotBudgetReset,
  useRunBobaToolRecoveryHealthChecks,
  useReviewBobaOutputQuality,
  useCompareBobaOutputQuality,
  useRecordBobaOutputHumanReview,
} from "@/lib/queries";
import { formatBytes, formatDuration, isTerminal } from "@/lib/rendering";
import type {
  ClipFeedbackInput,
  BobaBrainStateV1,
  BobaCaptionMotionRecommendationSetV1,
  BobaCandidateClipDiscoveryV1,
  BobaCodeApprovalRecordV1,
  BobaClipBriefSetV1,
  BobaClipRankingV1,
  BobaScoutRecommendationV2,
  BobaCreativeDirectionSetV2,
  BobaCreatorFeedbackEventInput,
  BobaCreatorFeedbackTargetType,
  BobaCreatorMemoryV1,
  BobaEditorialDecisionSetV1,
  BobaExplanationSetV1,
  BobaExperimentationSetV1,
  BobaHookRetentionSetV1,
  BobaMusicMoodRecommendationSetV1,
  BobaManualPerformanceMetricsV1,
  BobaPerformanceEventType,
  BobaPerformanceFeedbackEventInput,
  BobaPerformanceOutcomeLabel,
  BobaPerformanceTargetType,
  BobaProjectMemoryV1,
  BobaToolRecoveryApprovalV1,
  BobaOutputReviewModeV1,
  BobaWholeVideoUnderstandingV1,
  ClipPlan,
  CreatorProfileV2,
  RenderRun,
  RenderedVideo,
} from "@/lib/types";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function formatPercent(value: number | null): string {
  return value === null ? "n/a" : `${Math.round(value * 100)}%`;
}

function formatDb(value: number | null): string {
  return value === null ? "n/a" : `${value} dB`;
}

function formatDelta(value: number | null): string {
  return value === null ? "n/a" : `${value.toFixed(3)}s`;
}

function planTitle(plan: ClipPlan | undefined, render: RenderedVideo): string {
  const renderMetadata = asRecord(render.metadata);
  const uploadMetadata = asRecord(renderMetadata.upload_metadata_v2);
  const universal = asRecord(uploadMetadata.universal);
  const compact = asRecord(asRecord(renderMetadata.unified_clip_intelligence).upload_metadata);
  const blueprint = asRecord(plan?.blueprint);
  const title = asString(asRecord(blueprint.title_suggestion).text);
  return (
    asString(universal.best_title) ||
    asString(compact.best_title) ||
    title ||
    plan?.id ||
    render.clip_id
  );
}

function hookLine(plan: ClipPlan | undefined): string {
  const blueprint = asRecord(plan?.blueprint);
  const hook = asRecord(blueprint.hook_v2);
  return (
    asString((plan as { hook_line?: unknown } | undefined)?.hook_line) ||
    asString(hook.hook_line) ||
    asString(hook.overlay_text)
  );
}

function reasonSelected(plan: ClipPlan | undefined): string {
  const blueprint = asRecord(plan?.blueprint);
  const metadata = asRecord(blueprint.v2_metadata);
  return asString(metadata.why_selected) || plan?.explanation || "Selected by the clip planner.";
}

function copyText(value: string) {
  if (!value) return;
  void navigator.clipboard?.writeText(value);
}

function hashtags(plan: ClipPlan | undefined): string {
  const blueprint = asRecord(plan?.blueprint);
  const metadata = asRecord(blueprint.v2_metadata);
  const category = asString(metadata.content_category);
  const base = ["#Shorts", "#Reels", "#TikTok"];
  if (category && category !== "auto") {
    base.push(`#${category.replace(/[^a-z0-9]+/gi, "")}`);
  }
  return base.join(" ");
}

function findPlan(plans: ClipPlan[], render: RenderedVideo): ClipPlan | undefined {
  return plans.find((plan) => plan.id === (render.plan_id ?? render.clip_id));
}

function effectSummary(render: RenderedVideo) {
  const metadata = asRecord(render.metadata);
  const effects = asRecord(metadata.render_effects_v2);
  const captions = asRecord(effects.captions);
  const music = asRecord(effects.music);
  const sfx = asRecord(effects.sfx);
  const voice = asRecord(effects.voice_enhancement);
  const video = asRecord(effects.video_enhancement);
  const motion = asRecord(effects.motion);
  const face = asRecord(effects.face_tracking);
  const metadataFace = asRecord(metadata.face_tracking);
  const sync = asRecord(metadata.sync_validation);
  const duration = asRecord(metadata.duration_validation);
  const hook = asRecord(metadata.hook_editing);
  const editing = asRecord(metadata.editing_v2);
  const editingHook = asRecord(editing.hook_editing);
  const captionIntelligence = asRecord(
    metadata.caption_intelligence_v2 ?? editing.caption_intelligence_v2,
  );
  const captionStyleDecision = asRecord(captionIntelligence.style_decision);
  const captionTiming = asRecord(captionIntelligence.caption_timing_quality);
  const captionHook = asRecord(captionIntelligence.hook_caption_treatment);
  const captionEmphasis = asRecord(captionIntelligence.caption_emphasis);
  const captionSpeaker = asRecord(captionIntelligence.speaker_captioning);
  const captionSafeZone = asRecord(captionIntelligence.caption_safe_zone);
  const captionReadability = asRecord(
    metadata.caption_readability_validation ??
      captionIntelligence.caption_readability_validation,
  );
  const captionValidation = asRecord(
    metadata.caption_render_validation ??
      captions.validation ??
      captionIntelligence.validation,
  );
  const captionWarnings = asArray(
    captionValidation.warnings ?? captionIntelligence.warnings,
  )
    .map((warning) => asString(warning))
    .filter(Boolean);
  const musicIntelligence = asRecord(
    metadata.music_intelligence_v2 ?? editing.music_intelligence_v2,
  );
  const musicDecision = asRecord(musicIntelligence.decision);
  const selectedMusic = asRecord(musicIntelligence.selected_asset);
  const musicLibrarySelection = asRecord(
    musicIntelligence.music_library_selection,
  );
  const musicMix = asRecord(musicIntelligence.mix_plan);
  const musicDucking = asRecord(musicIntelligence.ducking_plan);
  const musicValidation = asRecord(
    metadata.music_validation ?? musicIntelligence.validation,
  );
  const faceApplied = face.applied === true || metadataFace.applied === true;
  const faceMode = asString(face.mode) || asString(metadataFace.mode) || "center_fallback";
  const multiSpeaker = asRecord(
    metadata.multi_speaker_layout_v2 ?? editing.multi_speaker_layout_v2,
  );
  const layoutDecision = asRecord(multiSpeaker.decision);
  const layoutInput = asRecord(multiSpeaker.input_analysis);
  const layoutValidation = asRecord(
    metadata.multi_speaker_validation ?? multiSpeaker.validation,
  );
  const layoutMode =
    asString(multiSpeaker.mode) || asString(layoutDecision.mode) || faceMode;
  const layoutApplied = layoutValidation.applied === true || faceApplied;
  const motionIntelligence = asRecord(
    metadata.motion_intelligence_v2 ?? editing.motion_intelligence_v2,
  );
  const motionDecision = asRecord(motionIntelligence.decision);
  const motionPlan = asRecord(motionIntelligence.effect_plan);
  const motionSafety = asRecord(
    metadata.motion_safety_validation ?? motionIntelligence.motion_safety_validation,
  );
  const motionValidation = asRecord(
    metadata.motion_render_validation ?? motion.render_validation ?? motionIntelligence.validation,
  );
  const renderedMotionCount =
    asNumber(motionValidation.effects_rendered) ?? asNumber(motion.event_count) ?? 0;
  const plannedMotionCount =
    asNumber(motionValidation.effects_planned) ??
    asNumber(motion.planned_event_count) ??
    asArray(motionPlan.effects).length;
  const motionApplied = motion.applied === true && motionValidation.passed === true;
  const motionIntensity = asString(motionDecision.intensity) || asString(motion.intensity);
  const motionWarnings = asArray(motionValidation.warnings ?? motionPlan.warnings)
    .map((warning) => asString(warning))
    .filter(Boolean);
  const syncPassed = sync.passed === true;
  const durationPassed = duration.passed === true;
  const captionPlanned = captionValidation.captions_planned === true;
  const captionApplied = render.subtitles_included === true && captionValidation.passed !== false;
  const captionTimingSource = asString(captionTiming.source) || "unavailable";
  const captionTimingQuality = asString(captionTiming.quality_level);
  return {
    captionStyle:
      asString(captionStyleDecision.caption_style) || asString(captions.style) || "Not available",
    captionStatus: captionApplied
      ? "Applied"
      : captionPlanned
        ? "Planned, render warning"
        : "Not available",
    captionTiming:
      captionTimingSource === "word_level"
        ? "Word-level"
        : captionTimingSource === "estimated"
          ? `Estimated ${captionTimingQuality.replace(/_/g, " ") || "phrase/segment"} timing`
        : captionTimingSource === "estimated_word_level"
          ? "Estimated word timing"
          : captionTimingSource === "segment_level"
            ? "Segment-level"
            : "Not available",
    captionTimingEstimated: captionTiming.estimated === true,
    captionHookTreatment: captionHook.applied === true,
    captionHookStyle:
      asString(captionHook.style) || asString(captionHook.animation) || "Not available",
    captionHighlightedWords: asArray(captionEmphasis.highlighted_words).length,
    captionSpeakerAware: captionSpeaker.enabled === true,
    captionSpeakerStrategy: asString(captionSpeaker.placement_strategy) || "Not available",
    captionSafeZone: asString(captionSafeZone.strategy) || "Not available",
    captionReadabilityStatus:
      captionReadability.passed === true
        ? "Passed"
        : Object.keys(captionReadability).length > 0
          ? "Warning"
          : "Not available",
    captionValidationStatus:
      captionValidation.passed === true
        ? captionPlanned
          ? "Passed"
          : "Disabled"
        : Object.keys(captionValidation).length > 0
          ? "Warning"
          : "Not available",
    captionReason: asString(captionStyleDecision.reason),
    captionWarning: captionWarnings[0] || "",
    musicStatus: asString(music.status) || (render.music_included ? "mixed" : "unavailable"),
    musicMixed: music.mixed === true || render.music_included === true,
    musicGain: asNumber(music.gain_db) ?? asNumber(metadata.music_gain_db),
    musicMood: asString(musicDecision.target_mood) || asString(music.mood),
    musicRole: asString(musicDecision.music_role),
    musicTrack:
      asString(selectedMusic.title) || asString(music.title) || asString(metadata.music_asset),
    musicSourceType:
      asString(selectedMusic.folder_type) ||
      asString(musicLibrarySelection.selected_priority_tier),
    musicQuality:
      asString(selectedMusic.quality_status) ||
      asString(selectedMusic.quality_tier) ||
      asString(selectedMusic.quality),
    musicLibraryReason: asString(musicLibrarySelection.selection_reason),
    musicReason: asString(musicDecision.reason) || asString(metadata.music_reason),
    musicDisabledReason: asString(musicDecision.disabled_reason),
    musicDucking:
      musicDucking.enabled === true || musicMix.ducking_enabled === true,
    musicLicense: asString(selectedMusic.license),
    musicLicenseSafe:
      musicValidation.license_safe === true ||
      (selectedMusic.license_verified === true && selectedMusic.safe_default === true),
    musicValidationStatus:
      musicValidation.passed === true
        ? asString(musicValidation.audible) === "not_verified"
          ? "Mixed, audibility not verified"
          : "Passed"
        : Object.keys(musicValidation).length > 0
          ? "Warning"
          : "Not available",
    musicWarning: [
      asString(musicValidation.warning),
      asString(metadata.music_warning),
      asString(selectedMusic.folder_type) === "generated"
        ? "Generated validation asset used because no curated production match exists."
        : "",
    ]
      .filter(Boolean)
      .join(" "),
    layoutMode,
    layoutStatus: layoutApplied
      ? "Applied"
      : layoutMode === "center_fallback"
        ? "Fallback"
        : "Unavailable",
    layoutParticipants:
      asArray(multiSpeaker.participants).length ||
      asNumber(layoutInput.stable_face_count) ||
      0,
    layoutSpeakerCount: asNumber(layoutInput.speaker_count) ?? 0,
    layoutAssociation: layoutInput.active_speaker_evidence_available === true,
    layoutActiveSpeaker:
      layoutMode === "active_speaker_focus" &&
      asArray(multiSpeaker.speaker_switches).length > 0,
    layoutRegions:
      asNumber(layoutValidation.rendered_regions) ??
      asArray(multiSpeaker.layout_regions).length,
    layoutSwitches:
      asNumber(layoutValidation.rendered_switches) ??
      asArray(multiSpeaker.speaker_switches).length,
    layoutConfidence:
      asNumber(layoutDecision.confidence) ?? asNumber(multiSpeaker.confidence),
    layoutReason: asString(layoutDecision.reason),
    layoutFallback:
      asString(layoutValidation.fallback_reason) ||
      asString(layoutDecision.fallback_reason) ||
      asString(multiSpeaker.fallback_reason),
    layoutValidationStatus:
      layoutValidation.passed === true
        ? "Passed"
        : Object.keys(layoutValidation).length > 0
          ? "Warning"
          : "Not available",
    layoutWarning: asArray(layoutValidation.warnings)
      .map((warning) => asString(warning))
      .filter(Boolean)[0],
    sfxCount: asNumber(sfx.mixed_count) ?? asNumber(metadata.sfx_mixed_count) ?? 0,
    sfxSkipped: asNumber(sfx.skipped_count) ?? asNumber(metadata.sfx_skipped_count) ?? 0,
    sfxSafety: sfx.safety_applied === true || metadata.sfx_safety_applied === true,
    voiceApplied: voice.applied === true || metadata.voice_enhancement_applied === true,
    videoApplied: video.applied === true || metadata.video_enhancement_applied === true,
    motionCount: renderedMotionCount,
    motionPlannedCount: plannedMotionCount,
    motionStatus: motionApplied
      ? motionIntensity === "minimal" || motionIntensity === "low"
        ? "Minimal"
        : "Applied"
      : "Skipped",
    motionStyle:
      asString(motionDecision.motion_style) || asString(motion.motion_style) || "Not available",
    motionIntensity: motionIntensity || "Not available",
    motionReason: asString(motionDecision.reason),
    motionDisabledReason: asString(motionDecision.disabled_reason),
    motionHookEffect:
      asString(asRecord(motionPlan.hook_effect).type) ||
      asString(asRecord(motion.hook_effect).effect_type) ||
      "None",
    motionPayoffEffect:
      asString(asRecord(motionPlan.payoff_effect).type) ||
      asString(asRecord(motion.payoff_effect).effect_type) ||
      "None",
    motionSafetyStatus:
      motionSafety.passed === true
        ? "Passed"
        : Object.keys(motionSafety).length > 0
          ? "Warning"
          : "Not available",
    motionValidationStatus:
      motionValidation.passed === true
        ? "Passed"
        : Object.keys(motionValidation).length > 0
          ? "Warning"
          : "Not available",
    motionWarning: motionWarnings[0] || "",
    faceStatus: faceApplied ? "Applied" : faceMode === "center_fallback" ? "Fallback" : "Unavailable",
    faceMode,
    syncStatus: syncPassed ? "Passed" : "Warning",
    syncDelta: asNumber(sync.audio_video_delta),
    durationStatus: durationPassed ? "Passed" : "Warning",
    expectedDuration: asNumber(duration.planned_duration) ?? asNumber(sync.expected_duration),
    actualDuration:
      asNumber(duration.rendered_duration) ?? asNumber(sync.actual_container_duration) ?? render.duration ?? null,
    hookTreatment:
      asString(hook.hook_caption_style) ||
      asString(editingHook.hook_caption_style) ||
      "standard hook treatment",
    hasWarning:
      sync.passed === false ||
      duration.passed === false ||
      (plannedMotionCount > 0 && motionValidation.passed === false) ||
      (captionPlanned && captionValidation.passed === false),
  };
}

function viralSummary(plan: ClipPlan | undefined) {
  const blueprint = asRecord(plan?.blueprint);
  const metadata = asRecord(blueprint.v2_metadata);
  const hook = asRecord(blueprint.hook_analysis_v2);
  const hookFallback = asRecord(blueprint.hook_v2);
  const story = asRecord(blueprint.storytelling_v2);
  const ending = asRecord(blueprint.ending_payoff_v2);
  const trend = asRecord(blueprint.trend_match_v2);
  const score = asRecord(blueprint.viral_score_v2);
  const niche = asRecord(blueprint.content_niche);
  const metadataNiche = asRecord(metadata.content_niche);
  const research = asRecord(
    blueprint.internet_trend_research_v2 ?? blueprint.viral_research_snapshot,
  );
  const detectedNiche = asRecord(research.detected_niche);
  const boundary = asRecord(blueprint.boundary_optimization_v2);
  const matches = asArray(trend.matched_patterns)
    .map((match) => asString(asRecord(match).label))
    .filter(Boolean);
  const fallbackUsed = research.fallback_used === true;
  const cacheStatus = asString(research.cache_status);
  const liveAttempted = research.live_research_attempted === true;
  const liveSucceeded =
    research.live_research_succeeded === true && research.internet_available === true;
  const hasResearch = Object.keys(research).length > 0;
  const researchStatus = !hasResearch
    ? "Not available"
    : cacheStatus === "stale" || cacheStatus === "stale_fallback"
      ? "Stale"
      : cacheStatus === "cached"
        ? "Cached"
        : liveSucceeded
          ? "Live"
          : fallbackUsed
            ? "Fallback"
            : "Unavailable";
  const researchWarnings = asArray(research.warnings)
    .map((warning) => asString(warning))
    .filter(Boolean);
  return {
    score: asNumber(score.overall) ?? asNumber(plan?.quality_score),
    niche:
      asString(detectedNiche.primary) ||
      asString(niche.primary) ||
      asString(metadataNiche.primary) ||
      "unknown mixed",
    hookCategory:
      asString(hook.category) || asString(hookFallback.category) || "context",
    faithfulHook:
      asString(hook.faithful_hook_line) ||
      asString(hookFallback.hook_line) ||
      asString(hookFallback.overlay_text),
    clickbaitRisk: hook.clickbait_risk === true,
    storyShape: asString(story.story_shape) || "unknown",
    endingType: asString(ending.ending_type) || "unknown",
    endingLine: asString(ending.ending_line),
    trendFit: asNumber(trend.trend_fit_score) ?? asNumber(trend.score),
    trendPatterns: matches.length > 0 ? matches.join(", ") : "no strong pattern",
    researchStatus,
    researchConfidence: asNumber(research.confidence),
    researchSourceCount:
      asNumber(research.source_count) ?? asArray(research.sources).length,
    researchProvider: asString(research.provider_used) || "not available",
    researchDomains: asArray(research.source_domains)
      .map((domain) => asString(domain))
      .filter(Boolean),
    liveAttempted,
    liveSucceeded,
    researchWarning:
      researchWarnings[0] ||
      (fallbackUsed ? "Fresh runtime internet research was not used." : ""),
    fallbackUsed,
    hasResearch,
    boundaryReason: asString(boundary.reason) || "transcript boundaries",
  };
}

function unifiedSummary(
  render: RenderedVideo,
  plan: ClipPlan | undefined,
  effects: ReturnType<typeof effectSummary>,
  viral: ReturnType<typeof viralSummary>,
) {
  const unified = asRecord(asRecord(render.metadata).unified_clip_intelligence);
  const story = asRecord(unified.story);
  const virality = asRecord(unified.virality);
  const planning = asRecord(unified.planning);
  const editing = asRecord(unified.editing);
  const rendering = asRecord(unified.rendering);
  const trendResearch = asRecord(unified.trend_research);
  const musicIntelligence = asRecord(unified.music_intelligence);
  const multiSpeakerLayout = asRecord(unified.multi_speaker_layout);
  const captionIntelligence = asRecord(unified.caption_intelligence);
  const motionGraphics = asRecord(unified.motion_graphics);
  const uploadMetadata = asRecord(unified.upload_metadata);
  const hook = asString(virality.hook_line) || hookLine(plan);
  const storyShape = asString(story.story_shape) || viral.storyShape;
  const tension = asString(story.tension);
  const payoff = asString(story.payoff) || viral.endingLine;
  const editStyle = asString(editing.edit_style);
  const selectedReason = asString(planning.selected_reason) || reasonSelected(plan);
  const unifiedTrendPatterns = asArray(trendResearch.matched_patterns)
    .map((pattern) => asString(asRecord(pattern).label))
    .filter(Boolean);
  const trendLine = unifiedTrendPatterns[0] || viral.trendPatterns;
  const validation =
    effects.syncStatus === "Passed" && effects.durationStatus === "Passed"
      ? "synced and full duration"
      : "render validation warning";
  const bullets = [
    hook && `Hook: ${hook}`,
    storyShape && `Story: ${storyShape.replace(/_/g, " ")}`,
    tension && `Tension: ${tension}`,
    payoff && `Payoff: ${payoff}`,
    trendLine &&
      `Trend: ${viral.researchStatus.toLowerCase()} ${trendLine.replace(/_/g, " ")} pattern`,
    selectedReason && `Selection: ${selectedReason}`,
    asString(musicIntelligence.reason) &&
      `Music: ${asString(musicIntelligence.reason)}`,
    asString(multiSpeakerLayout.reason) &&
      `Layout: ${asString(multiSpeakerLayout.reason)}`,
    asString(captionIntelligence.reason) &&
      `Captions: ${asString(captionIntelligence.reason)}`,
    asString(motionGraphics.reason) &&
      `Motion: ${asString(motionGraphics.reason)}`,
    Object.keys(uploadMetadata).length > 0 &&
      `Upload metadata: ${
        uploadMetadata.manual_review_required === true
          ? "generated, but manual review is required"
          : uploadMetadata.validation_passed === true
            ? "ready with focused platform hashtags"
            : "generated with a validation warning"
      }`,
    `Editing: ${editStyle || effects.hookTreatment.replace(/_/g, " ")}`,
    `Validation: ${validation}`,
  ].filter(Boolean) as string[];
  return {
    available: Object.keys(unified).length > 0,
    bullets,
    renderWarnings: asArray(rendering.warnings)
      .map((warning) => asString(warning))
      .filter(Boolean),
  };
}

function uploadMetadataSummary(render: RenderedVideo) {
  const metadata = asRecord(render.metadata);
  const full = asRecord(metadata.upload_metadata_v2);
  const compact = asRecord(asRecord(metadata.unified_clip_intelligence).upload_metadata);
  const youtube = asRecord(full.youtube_shorts);
  const instagram = asRecord(full.instagram_reels);
  const tiktok = asRecord(full.tiktok);
  const universal = asRecord(full.universal);
  const validation = asRecord(full.validation);
  const titleVariants = asArray(youtube.title_variants)
    .map((item) => asString(asRecord(item).text) || asString(item))
    .filter(Boolean);
  const youtubeHashtags = asArray(youtube.hashtags)
    .map((tag) => asString(tag))
    .filter(Boolean);
  const instagramHashtags = asArray(instagram.hashtags)
    .map((tag) => asString(tag))
    .filter(Boolean);
  const tiktokHashtags = asArray(tiktok.hashtags)
    .map((tag) => asString(tag))
    .filter(Boolean);
  const warnings = [
    ...asArray(universal.warnings),
    ...asArray(validation.warnings),
    ...asArray(compact.warnings),
  ]
    .map((warning) => asString(warning))
    .filter(Boolean)
    .filter((warning, index, items) => items.indexOf(warning) === index);
  const youtubeTitle =
    asString(youtube.title) || asString(compact.youtube_title) || asString(universal.best_title);
  const youtubeDescription =
    asString(youtube.description) || asString(compact.youtube_description);
  const instagramCaption =
    asString(instagram.caption) || asString(compact.instagram_caption);
  const tiktokCaption = asString(tiktok.caption) || asString(compact.tiktok_caption);
  const bestTitle =
    asString(universal.best_title) || asString(compact.best_title) || youtubeTitle;
  const manualReviewRequired =
    universal.manual_review_required === true || compact.manual_review_required === true;
  const validationPassed = validation.passed === true || compact.validation_passed === true;
  const status = asString(full.status) || asString(compact.status) || "unavailable";
  const available = Boolean(
    youtubeTitle || youtubeDescription || instagramCaption || tiktokCaption,
  );
  const youtubeCopy = [youtubeTitle, youtubeDescription, youtubeHashtags.join(" ")]
    .filter(Boolean)
    .join("\n\n");
  const instagramCopy = [instagramCaption, instagramHashtags.join(" ")]
    .filter(Boolean)
    .join("\n\n");
  const tiktokCopy = [tiktokCaption, tiktokHashtags.join(" ")]
    .filter(Boolean)
    .join("\n\n");
  return {
    available,
    status,
    bestTitle,
    youtubeTitle,
    titleVariants,
    youtubeDescription,
    youtubeHashtags,
    instagramCaption,
    instagramHashtags,
    tiktokCaption,
    tiktokHashtags,
    manualReviewRequired,
    validationPassed,
    warnings,
    youtubeCopy,
    instagramCopy,
    tiktokCopy,
  };
}

function copyrightSafetySummary(render: RenderedVideo) {
  const metadata = asRecord(render.metadata);
  const unified = asRecord(metadata.unified_clip_intelligence);
  const compact = asRecord(unified.copyright_safety);
  const report = asRecord(metadata.copyright_safety_v2);
  const overall = asRecord(report.overall);
  const source = asRecord(report.source_video);
  const music = asRecord(report.music);
  const sfx = asRecord(report.sfx);
  const manualReview = asRecord(report.manual_review);
  const result = asRecord(report.result);
  const riskLevel = asString(overall.risk_level) || asString(compact.risk_level) || "unknown";
  const uploadReadiness =
    asString(overall.upload_readiness) || asString(compact.upload_readiness) || "unknown";
  const warnings = asArray(result.warnings ?? compact.warnings)
    .map((warning) => asString(warning))
    .filter(Boolean);
  const blockedReasons = asArray(result.errors ?? compact.blocked_reasons)
    .map((reason) => asString(reason))
    .filter(Boolean);
  return {
    available: Object.keys(report).length > 0 || Object.keys(compact).length > 0,
    riskLevel,
    uploadReadiness,
    manualReviewRequired:
      manualReview.required === true || compact.manual_review_required === true,
    sourceRightsConfirmed:
      source.rights_confirmed === true || compact.source_rights_confirmed === true,
    sourceRightsAvailable:
      typeof source.rights_confirmed === "boolean" ||
      typeof compact.source_rights_confirmed === "boolean",
    musicLicenseVerified:
      music.used === false ||
      music.license_verified === true ||
      compact.music_license_verified === true,
    musicUsed: music.used === true,
    sfxLicenseVerified:
      sfx.used === false ||
      sfx.all_license_verified === true ||
      compact.sfx_license_verified === true,
    sfxUsed: sfx.used === true,
    warnings,
    blockedReasons,
    checklist: asArray(manualReview.checklist)
      .map((item) => asString(item))
      .filter(Boolean),
    disclaimer:
      asString(overall.disclaimer) ||
      asString(compact.disclaimer) ||
      "This is a technical risk assessment, not legal advice.",
  };
}

function readableName(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

function PersonalizationPanel() {
  const profilesQuery = useCreatorProfiles();
  const createProfile = useCreateCreatorProfile();
  const activateProfile = useActivateCreatorProfile();
  const updateProfile = useUpdateCreatorProfile();
  const resetProfile = useResetCreatorProfile();
  const exportProfile = useExportCreatorProfile();
  const [selectedPreset, setSelectedPreset] = useState("balanced_default");
  const [status, setStatus] = useState("");
  const data = profilesQuery.data;
  const activeProfile = data?.profiles.find(
    (profile) => profile.profile_id === data.active_profile_id,
  );
  const mutationPending =
    createProfile.isPending ||
    activateProfile.isPending ||
    updateProfile.isPending ||
    resetProfile.isPending ||
    exportProfile.isPending;

  function updateActive(updates: Record<string, unknown>, message: string) {
    if (!activeProfile) return;
    setStatus("");
    updateProfile.mutate(
      { profileId: activeProfile.profile_id, updates },
      {
        onSuccess: () => setStatus(message),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  if (profilesQuery.isLoading) {
    return (
      <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4 text-sm text-muted">
        Loading local creator profile…
      </section>
    );
  }

  if (profilesQuery.isError || !data || !activeProfile) {
    return (
      <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4 text-sm text-muted">
        Creator personalization is not available. Existing clip output remains usable.
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-cyan-300/15 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">Creator Personalization V2</p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            Personalization is local and based only on your feedback. You can reset this anytime.
          </p>
        </div>
        <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-300">
          Local only · No cloud sync
        </span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <label className="text-xs text-muted">
          Active profile
          <select
            value={activeProfile.profile_id}
            disabled={mutationPending}
            onChange={(event) => {
              setStatus("");
              activateProfile.mutate(event.target.value, {
                onSuccess: (profile) => setStatus(`${profile.profile_name} is now active.`),
                onError: (error) => setStatus(error.message),
              });
            }}
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-white"
          >
            {data.profiles.map((profile) => (
              <option key={profile.profile_id} value={profile.profile_id}>
                {profile.profile_name}
              </option>
            ))}
          </select>
        </label>

        <label className="text-xs text-muted">
          Create from preset
          <div className="mt-1 flex gap-2">
            <select
              value={selectedPreset}
              disabled={mutationPending}
              onChange={(event) => setSelectedPreset(event.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-white"
            >
              {data.presets.map((preset) => (
                <option key={preset} value={preset}>
                  {readableName(preset)}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={mutationPending}
              onClick={() => {
                setStatus("");
                createProfile.mutate(
                  { preset_id: selectedPreset, activate: true },
                  {
                    onSuccess: (profile) => setStatus(`${profile.profile_name} was created.`),
                    onError: (error) => setStatus(error.message),
                  },
                );
              }}
              className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white hover:border-white/30 disabled:opacity-50"
            >
              Create
            </button>
          </div>
        </label>

        <label className="text-xs text-muted">
          Title style
          <select
            value={activeProfile.upload_metadata_preferences.title_style ?? "clear"}
            disabled={mutationPending}
            onChange={(event) =>
              updateActive(
                { upload_metadata_preferences: { title_style: event.target.value } },
                "Title preference saved.",
              )
            }
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-white"
          >
            <option value="clear">Clear</option>
            <option value="curiosity">Curiosity</option>
            <option value="emotional">Emotional</option>
            <option value="reaction">Reaction</option>
            <option value="performance">Performance</option>
          </select>
        </label>

        <label className="text-xs text-muted">
          Caption style
          <select
            value={activeProfile.caption_preferences.style ?? "default_clean"}
            disabled={mutationPending}
            onChange={(event) =>
              updateActive(
                { caption_preferences: { style: event.target.value } },
                "Caption preference saved.",
              )
            }
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-white"
          >
            <option value="default_clean">Default clean</option>
            <option value="bold_hook">Bold hook</option>
            <option value="podcast_clean">Podcast clean</option>
            <option value="motivational_impact">Motivational impact</option>
            <option value="music_minimal">Music minimal</option>
            <option value="gaming_energy">Gaming energy</option>
            <option value="education_clear">Education clear</option>
          </select>
        </label>

        <label className="text-xs text-muted">
          Music presence
          <select
            value={activeProfile.music_preferences.music_presence ?? "balanced"}
            disabled={mutationPending}
            onChange={(event) =>
              updateActive(
                { music_preferences: { music_presence: event.target.value } },
                "Music preference saved.",
              )
            }
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 text-sm text-white"
          >
            <option value="none">None</option>
            <option value="low">Low</option>
            <option value="balanced">Balanced</option>
            <option value="high">High</option>
          </select>
        </label>

        <label className="text-xs text-muted">
          Motion intensity: {Math.round((activeProfile.motion_preferences.intensity ?? 0.5) * 100)}%
          <input
            key={`${activeProfile.profile_id}-motion`}
            type="range"
            min="0"
            max="1"
            step="0.1"
            defaultValue={activeProfile.motion_preferences.intensity ?? 0.5}
            disabled={mutationPending}
            onChange={(event) =>
              updateActive(
                { motion_preferences: { intensity: Number(event.target.value) } },
                "Motion preference saved.",
              )
            }
            className="mt-3 w-full accent-cyan-300"
          />
        </label>

        <label className="text-xs text-muted">
          Caption emphasis: {Math.round((activeProfile.caption_preferences.highlight_density ?? 0.4) * 100)}%
          <input
            key={`${activeProfile.profile_id}-captions`}
            type="range"
            min="0"
            max="1"
            step="0.1"
            defaultValue={activeProfile.caption_preferences.highlight_density ?? 0.4}
            disabled={mutationPending}
            onChange={(event) =>
              updateActive(
                { caption_preferences: { highlight_density: Number(event.target.value) } },
                "Caption emphasis saved.",
              )
            }
            className="mt-3 w-full accent-cyan-300"
          />
        </label>

        <label className="flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={activeProfile.learning.enabled}
            disabled={mutationPending}
            onChange={(event) =>
              updateActive(
                { learning: { enabled: event.target.checked } },
                event.target.checked
                  ? "Explicit-feedback learning enabled."
                  : "Learning disabled; existing preferences remain editable.",
              )
            }
            className="accent-cyan-300"
          />
          Learn only from feedback I submit
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={mutationPending}
          onClick={() =>
            exportProfile.mutate(activeProfile.profile_id, {
              onSuccess: (result) => {
                downloadJson(result.filename, result.profile);
                setStatus("Profile exported locally.");
              },
              onError: (error) => setStatus(error.message),
            })
          }
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white hover:border-white/30 disabled:opacity-50"
        >
          Export profile
        </button>
        <button
          type="button"
          disabled={mutationPending}
          onClick={() => {
            if (!window.confirm(`Reset ${activeProfile.profile_name} and clear its feedback?`)) {
              return;
            }
            resetProfile.mutate(activeProfile.profile_id, {
              onSuccess: () => setStatus("Profile reset to its safe preset defaults."),
              onError: (error) => setStatus(error.message),
            });
          }}
          className="rounded-lg border border-red-300/20 px-3 py-1.5 text-xs text-red-200 hover:border-red-300/40 disabled:opacity-50"
        >
          Reset profile
        </button>
        <span className="text-[11px] text-muted">
          {activeProfile.learning.enabled
            ? `${activeProfile.learning.total_feedback_count} explicit feedback item(s) · ${Math.round(activeProfile.learning.confidence * 100)}% confidence`
            : "Learning is off by default."}
        </span>
      </div>
      {status && <p className="mt-2 text-xs text-cyan-100">{status}</p>}
    </section>
  );
}

function personalizationSummary(render: RenderedVideo) {
  const metadata = asRecord(render.metadata);
  const unified = asRecord(metadata.unified_clip_intelligence);
  const editing = asRecord(metadata.editing_v2);
  const compact = asRecord(unified.personalization);
  const direct = asRecord(
    metadata.personalization_applied_v2 ?? editing.personalization_applied_v2,
  );
  const source = Object.keys(compact).length > 0 ? compact : direct;
  const rawAdjustments = asArray(source.key_adjustments ?? source.adjustments);
  const adjustments = rawAdjustments
    .map((item) => {
      const adjustment = asRecord(item);
      const system = asString(adjustment.system);
      const field = asString(adjustment.field);
      const reason = asString(adjustment.reason);
      return [system, field, reason].filter(Boolean).join(": ");
    })
    .filter(Boolean);
  return {
    available: Object.keys(source).length > 0,
    applied: source.applied === true,
    profileId: asString(source.profile_id),
    profileName: asString(source.profile_name),
    confidence: asNumber(source.confidence),
    affectedSystems: asArray(source.affected_systems)
      .map((item) => asString(item))
      .filter(Boolean),
    adjustments,
    warnings: asArray(source.warnings)
      .map((item) => asString(item))
      .filter(Boolean),
    reasons: asArray(source.reasons)
      .map((item) => asString(item))
      .filter(Boolean),
  };
}

function bobaClipSummary(render: RenderedVideo) {
  const unified = asRecord(asRecord(render.metadata).unified_clip_intelligence);
  const boba = asRecord(unified.boba);
  return {
    available: Object.keys(boba).length > 0,
    mode: asString(boba.mode) || "advise",
    confidence: asNumber(boba.confidence),
    rankingExplanation: asString(boba.ranking_explanation),
    editorialPolicy: asString(boba.editorial_policy_summary),
    missingSignals: asArray(boba.missing_signals).map(asString).filter(Boolean),
    warnings: asArray(boba.warnings).map(asString).filter(Boolean),
    memoryUsed: asArray(boba.memory_used).map(asString).filter(Boolean),
    applied: boba.applied === true,
  };
}

function BobaWholeVideoPanel({
  understanding,
  building,
  onBuild,
}: {
  understanding: BobaWholeVideoUnderstandingV1 | null | undefined;
  building: boolean;
  onBuild: () => void;
}) {
  const bestSections = understanding
    ? understanding.section_scores
        .slice()
        .sort((left, right) => right.shortability_score - left.shortability_score)
        .slice(0, 3)
    : [];
  const weakSections = understanding
    ? understanding.section_scores
        .filter((section) => section.filler_score >= 0.35 || section.clarity_score < 0.5)
        .sort((left, right) => right.filler_score - left.filler_score)
        .slice(0, 3)
    : [];

  return (
    <section className="rounded-xl border border-sky-300/20 bg-sky-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Whole Video Understanding</p>
          <p className="text-xs text-muted">
            Local transcript and Olympus-signal heuristics; no cloud AI or audience-performance proof.
          </p>
        </div>
        <button
          type="button"
          disabled={building}
          onClick={onBuild}
          className="rounded border border-sky-200/30 px-2 py-1 text-[11px] text-sky-100 hover:border-sky-100 disabled:opacity-50"
        >
          {building ? "Building…" : understanding ? "Refresh understanding" : "Build understanding"}
        </button>
      </div>
      {understanding ? (
        <div className="mt-3 grid gap-3 text-xs text-muted lg:grid-cols-2">
          <div className="space-y-1 lg:col-span-2">
            <p className="font-semibold text-white">Overall summary</p>
            <p>{understanding.overall_summary}</p>
            <p>
              {understanding.video_type.replace(/_/g, " ")} · Topic: {understanding.primary_topic} · Tone: {understanding.tone.replace(/_/g, " ")}
            </p>
            <p>Intent: {understanding.creator_intent} · Value: {understanding.audience_value}</p>
          </div>
          <div>
            <p className="font-semibold text-white">Topic timeline</p>
            {understanding.topic_timeline.slice(0, 5).map((topic) => (
              <p key={topic.segment_id}>
                {formatDuration(topic.start_seconds)}–{formatDuration(topic.end_seconds)}: {topic.topic}
              </p>
            ))}
          </div>
          <div>
            <p className="font-semibold text-white">Story arc</p>
            <p>Setup: {understanding.story_arc.setup[0]?.summary ?? "Not available"}</p>
            <p>Payoff: {understanding.story_arc.payoff[0]?.summary ?? "Not confirmed"}</p>
            <p>
              Unresolved: {understanding.story_arc.unresolved_threads.slice(0, 2).join("; ") || "None reported"}
            </p>
          </div>
          <div>
            <p className="font-semibold text-white">Emotional beats</p>
            <p>
              {understanding.emotional_beats
                .slice(0, 5)
                .map((beat) => `${formatDuration(beat.start_seconds)} ${beat.emotion_label.replace(/_/g, " ")}`)
                .join("; ") || "Not available"}
            </p>
          </div>
          <div>
            <p className="font-semibold text-white">Best sections</p>
            {bestSections.map((section) => (
              <p key={section.section_id}>
                {formatDuration(section.start_seconds)}–{formatDuration(section.end_seconds)} · shortability {formatPercent(section.shortability_score)}
              </p>
            ))}
          </div>
          <div>
            <p className="font-semibold text-white">Weak / filler sections</p>
            <p>
              {weakSections
                .map((section) => `${formatDuration(section.start_seconds)} filler ${formatPercent(section.filler_score)}`)
                .join("; ") || "None reported"}
            </p>
          </div>
          <div>
            <p className="font-semibold text-white">Shortability hints</p>
            <p>
              {understanding.shortability_hints
                .slice(0, 4)
                .map((hint) => `${hint.suggested_clip_type.replace(/_/g, " ")}: ${hint.reason}`)
                .join("; ") || "Not available"}
            </p>
          </div>
          <div className="lg:col-span-2">
            <p className="font-semibold text-white">Signal limitations</p>
            <p>
              {understanding.signal_usage.unavailable_signals.join(", ") || "No optional signal gap reported"}
            </p>
            {(understanding.warnings.length > 0 || understanding.limitations.length > 0) && (
              <p className="mt-1 text-amber-100">
                Warning: {[...understanding.warnings, ...understanding.limitations].slice(0, 3).join("; ")}
              </p>
            )}
          </div>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          Whole-video understanding is not available. Build it after transcript analysis completes.
        </p>
      )}
    </section>
  );
}

function BobaCandidateDiscoveryPanel({
  discovery,
  discovering,
  onDiscover,
}: {
  discovery: BobaCandidateClipDiscoveryV1 | null | undefined;
  discovering: boolean;
  onDiscover: () => void;
}) {
  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Candidate Clip Discovery</p>
          <p className="text-xs text-muted">
            Advisory local windows only; discovery does not rank, plan, edit, or render clips.
          </p>
        </div>
        <button
          type="button"
          disabled={discovering}
          onClick={onDiscover}
          className="rounded border border-violet-200/30 px-2 py-1 text-[11px] text-violet-100 hover:border-violet-100 disabled:opacity-50"
        >
          {discovering ? "Discovering..." : discovery ? "Refresh candidates" : "Discover candidates"}
        </button>
      </div>
      {discovery ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <p>
            {discovery.candidates.length} candidate(s) - {discovery.diversity_summary.topic_count} topic(s) - {discovery.rejected_windows.length} rejected window(s)
          </p>
          <div className="grid gap-3 lg:grid-cols-2">
            {discovery.candidates.slice(0, 10).map((candidate) => (
              <article key={candidate.candidate_id} className="rounded border border-white/10 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-white">{candidate.suggested_title}</p>
                    <p>
                      {formatDuration(candidate.start_seconds)}-{formatDuration(candidate.end_seconds)} ({formatDuration(candidate.duration_seconds)})
                    </p>
                  </div>
                  <span className="rounded bg-violet-300/10 px-2 py-1 text-violet-100">
                    {formatPercent(candidate.confidence)} confidence
                  </span>
                </div>
                <p className="mt-2">Hook: {candidate.hook_idea}</p>
                <p>Story angle: {candidate.story_angle}</p>
                <p>
                  Standalone {formatPercent(candidate.standalone_score)} - Setup {candidate.setup_required ? "needed" : "not flagged"} - Payoff {candidate.payoff_present ? "present" : "not confirmed"}
                </p>
                <p>Why discovered: {candidate.discovery_reason}</p>
                {candidate.warnings.length > 0 && (
                  <p className="mt-1 text-amber-100">Warning: {candidate.warnings.slice(0, 2).join("; ")}</p>
                )}
              </article>
            ))}
          </div>
          <p>
            Signals unavailable: {discovery.signal_usage.unavailable_signals.join(", ") || "None reported"}
          </p>
          {(discovery.warnings.length > 0 || discovery.diversity_summary.warnings.length > 0) && (
            <p className="text-amber-100">
              Warning: {[...discovery.warnings, ...discovery.diversity_summary.warnings].slice(0, 3).join("; ")}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          No saved discovery artifact. Run discovery after timed transcript or analysis signals exist.
        </p>
      )}
    </section>
  );
}

function BobaClipRankingPanel({
  ranking,
  rankingCandidates,
  canRank,
  onRank,
}: {
  ranking: BobaClipRankingV1 | null | undefined;
  rankingCandidates: boolean;
  canRank: boolean;
  onRank: () => void;
}) {
  return (
    <section className="rounded-xl border border-fuchsia-300/20 bg-fuchsia-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Clip Ranking Brain</p>
          <p className="text-xs text-muted">
            Advisory ranking only; BOBA does not plan, edit, render, or predict audience results.
          </p>
        </div>
        <button
          type="button"
          disabled={rankingCandidates || !canRank}
          onClick={onRank}
          className="rounded border border-fuchsia-200/30 px-2 py-1 text-[11px] text-fuchsia-100 hover:border-fuchsia-100 disabled:opacity-50"
        >
          {rankingCandidates ? "Ranking..." : ranking ? "Refresh ranking" : "Rank candidates"}
        </button>
      </div>
      {ranking ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <p>{ranking.summary}</p>
          <p>
            Recommended {ranking.recommended_clip_ids.length} · Backups {ranking.backup_clip_ids.length} · Rejected {ranking.rejected_clip_ids.length}
          </p>
          <div className="grid gap-3 lg:grid-cols-2">
            {ranking.ranked_candidates.slice(0, 10).map((candidate) => (
              <article key={candidate.candidate_id} className="rounded border border-white/10 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-white">
                      #{candidate.rank} {candidate.suggested_title}
                    </p>
                    <p>
                      {formatDuration(candidate.source_window.start_seconds)}-{formatDuration(candidate.source_window.end_seconds)} · {candidate.candidate_type.replace(/_/g, " ")}
                    </p>
                  </div>
                  <span className="rounded bg-fuchsia-300/10 px-2 py-1 text-fuchsia-100">
                    {candidate.total_score.toFixed(1)}/100 · {candidate.tier.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="mt-2">
                  Priority {candidate.production_priority.replace(/_/g, " ")} · Confidence {formatPercent(candidate.confidence)}
                </p>
                <p>Hook: {candidate.hook_idea}</p>
                <p>Why: {candidate.ranking_reasons.join("; ") || "No ranking reason available"}</p>
                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer text-white">Score breakdown and risks</summary>
                  <div className="mt-2 grid grid-cols-2 gap-1">
                    {Object.entries(candidate.score_breakdown).map(([label, score]) => (
                      <p key={label}>{label.replace(/_/g, " ")}: {score.toFixed(1)}</p>
                    ))}
                  </div>
                  {candidate.risk_warnings.length > 0 && (
                    <p className="mt-2 text-amber-100">Warnings: {candidate.risk_warnings.join("; ")}</p>
                  )}
                  {candidate.improvement_suggestions.length > 0 && (
                    <p className="mt-1">Improve: {candidate.improvement_suggestions.join("; ")}</p>
                  )}
                </details>
              </article>
            ))}
          </div>
          <p>
            Diversity: {ranking.diversity_summary.topic_count} topic(s), {ranking.diversity_summary.emotion_count} emotion(s), {ranking.diversity_summary.candidate_type_count} type(s); {ranking.diversity_summary.overlap_penalties_applied} overlap penalty(s).
          </p>
          <p>Signals unavailable: {ranking.signal_usage.unavailable_signals.join(", ") || "None reported"}</p>
          {(ranking.warnings.length > 0 || ranking.diversity_summary.diversity_warnings.length > 0) && (
            <p className="text-amber-100">
              Warning: {[...ranking.warnings, ...ranking.diversity_summary.diversity_warnings].slice(0, 3).join("; ")}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canRank
            ? "No saved ranking artifact. Rank the saved candidate discovery locally."
            : "Run Candidate Clip Discovery before ranking."}
        </p>
      )}
    </section>
  );
}

function BobaEditorialDecisionPanel({
  decisions,
  deciding,
  canDecide,
  onDecide,
}: {
  decisions: BobaEditorialDecisionSetV1 | null | undefined;
  deciding: boolean;
  canDecide: boolean;
  onDecide: () => void;
}) {
  const orderedDecisions = decisions
    ? [...decisions.decisions].sort(
        (left, right) => Number(right.selected) - Number(left.selected) || left.rank - right.rank,
      )
    : [];

  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Editorial Decision Engine</p>
          <p className="text-xs text-muted">
            Local advisory instructions only; Olympus planning, editing, and rendering remain authoritative.
          </p>
        </div>
        <button
          type="button"
          disabled={deciding || !canDecide}
          onClick={onDecide}
          className="rounded border border-violet-200/30 px-2 py-1 text-[11px] text-violet-100 hover:border-violet-100 disabled:opacity-50"
        >
          {deciding
            ? "Deciding..."
            : decisions
              ? "Refresh editorial decisions"
              : "Create editorial decisions"}
        </button>
      </div>
      {decisions ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <p>{decisions.summary}</p>
          <div className="flex flex-wrap gap-2">
            <span className="rounded bg-emerald-300/10 px-2 py-1 text-emerald-100">
              Ready {decisions.risk_summary.ready_for_render_count}
            </span>
            <span className="rounded bg-amber-300/10 px-2 py-1 text-amber-100">
              Needs revision {decisions.risk_summary.needs_revision_count}
            </span>
            <span className="rounded bg-rose-300/10 px-2 py-1 text-rose-100">
              Blocked {decisions.risk_summary.blocked_count}
            </span>
            <span className="rounded bg-white/5 px-2 py-1 text-white">
              Selected {decisions.selected_clip_ids.length}
            </span>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {orderedDecisions.slice(0, 10).map((decision) => (
              <article
                key={decision.candidate_id}
                className={`rounded border p-3 ${
                  decision.selected ? "border-violet-200/30" : "border-white/10"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-white">
                      #{decision.rank} {decision.suggested_title}
                    </p>
                    <p>
                      {formatDuration(decision.source_window.start_seconds)}-
                      {formatDuration(decision.source_window.end_seconds)} · {decision.candidate_type.replace(/_/g, " ")}
                    </p>
                  </div>
                  <span
                    className={`rounded px-2 py-1 ${
                      decision.render_readiness === "ready_for_render"
                        ? "bg-emerald-300/10 text-emerald-100"
                        : decision.render_readiness === "blocked"
                          ? "bg-rose-300/10 text-rose-100"
                          : "bg-amber-300/10 text-amber-100"
                    }`}
                  >
                    {decision.selected ? "Selected" : "Not selected"} · {decision.render_readiness.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="mt-2">
                  Ranking {decision.ranking_score.toFixed(1)}/100 · Confidence {formatPercent(decision.confidence)}
                </p>
                <p>Story angle: {decision.final_story_angle}</p>
                <p>Hook strategy: {decision.final_hook_strategy.replace(/_/g, " ")}</p>
                <p>Opening direction: {decision.opening_line_direction}</p>
                <p>
                  Pacing {decision.pacing_intensity} · Captions {decision.caption_style.replace(/_/g, " ")} · Motion {decision.motion_style.replace(/_/g, " ")}
                </p>
                <p>
                  Music mood {decision.music_mood} · SFX intensity {decision.sfx_intensity} (instructions only)
                </p>
                <p>Readiness reason: {decision.render_readiness_reason}</p>
                <p>Why selected: {decision.decision_reasons.join("; ") || "No decision reason available"}</p>
                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer text-white">
                    Editing instructions, risks, and improvements
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>Hook: {decision.editing_instruction_packet.hook_instruction}</p>
                    <p>Cut: {decision.editing_instruction_packet.cut_instruction}</p>
                    <p>Captions: {decision.editing_instruction_packet.caption_instruction}</p>
                    <p>Motion: {decision.editing_instruction_packet.motion_instruction}</p>
                    <p>Audio: {decision.editing_instruction_packet.audio_instruction}</p>
                    <p>Retention: {decision.editing_instruction_packet.retention_instruction}</p>
                    {(decision.risk_review.blockers.length > 0 ||
                      decision.risk_review.warnings.length > 0) && (
                      <p className="text-amber-100">
                        Risks: {[...decision.risk_review.blockers, ...decision.risk_review.warnings].join("; ")}
                      </p>
                    )}
                    <p>
                      Improve: {decision.improvement_notes.join("; ") || "No additional improvement note"}
                    </p>
                  </div>
                </details>
              </article>
            ))}
          </div>
          <p>
            Production order: {decisions.production_order.join(" → ") || "No clips are ready for production"}
          </p>
          <p>
            Signals unavailable: {decisions.signal_usage.unavailable_signals.join(", ") || "None reported"}
          </p>
          {(decisions.risk_summary.top_risks.length > 0 || decisions.warnings.length > 0) && (
            <p className="text-amber-100">
              Editorial risks: {[...decisions.risk_summary.top_risks, ...decisions.warnings]
                .slice(0, 4)
                .join("; ")}
            </p>
          )}
          <p>
            These are advisory instructions, not proof that any edit or render effect was applied.
          </p>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canDecide
            ? "No saved editorial decision artifact. Create decisions from the saved ranking."
            : "Rank candidate clips before creating editorial decisions."}
        </p>
      )}
    </section>
  );
}

function BobaExplanationPanel({
  explanations,
  explaining,
  canExplain,
  onExplain,
}: {
  explanations: BobaExplanationSetV1 | null | undefined;
  explaining: boolean;
  canExplain: boolean;
  onExplain: () => void;
}) {
  const groups = explanations
    ? [
        ["Discovery explanations", explanations.candidate_explanations],
        ["Ranking explanations", explanations.ranking_explanations],
        ["Editorial and readiness explanations", explanations.editorial_explanations],
      ] as const
    : [];
  const uncertaintyClass =
    explanations?.uncertainty_summary.uncertainty_level === "low"
      ? "bg-emerald-300/10 text-emerald-100"
      : explanations?.uncertainty_summary.uncertainty_level === "high"
        ? "bg-rose-300/10 text-rose-100"
        : "bg-amber-300/10 text-amber-100";

  return (
    <section className="rounded-xl border border-sky-300/20 bg-sky-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Explanation Engine</p>
          <p className="text-xs text-muted">
            Evidence-bound explanations from saved metadata only; no rendered proof or audience-performance prediction.
          </p>
        </div>
        <button
          type="button"
          disabled={explaining || !canExplain}
          onClick={onExplain}
          className="rounded border border-sky-200/30 px-2 py-1 text-[11px] text-sky-100 hover:border-sky-100 disabled:opacity-50"
        >
          {explaining
            ? "Explaining..."
            : explanations
              ? "Refresh explanations"
              : "Create explanations"}
        </button>
      </div>
      {explanations ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="max-w-4xl">{explanations.project_summary.overall_summary}</p>
            <span className={`rounded px-2 py-1 ${uncertaintyClass}`}>
              Uncertainty {explanations.uncertainty_summary.uncertainty_level}
            </span>
          </div>
          <p>
            <span className="font-semibold text-white">Top recommendation:</span>{" "}
            {explanations.project_summary.top_recommendation_reason}
          </p>
          <div className="grid gap-2 md:grid-cols-2">
            <p>
              Strongest clip types: {explanations.project_summary.strongest_clip_types.join(", ") || "Not available"}
            </p>
            <p>
              Weakest clip types: {explanations.project_summary.weakest_clip_types.join(", ") || "Not available"}
            </p>
            <p>
              Signals used: {explanations.signal_explanation.signals_used.join(", ") || "None reported"}
            </p>
            <p>
              Signals missing: {explanations.signal_explanation.signals_missing.join(", ") || "None reported"}
            </p>
          </div>
          {groups.map(([label, items]) =>
            items.length > 0 ? (
              <details key={label} className="rounded border border-white/10 p-3">
                <summary className="cursor-pointer font-semibold text-white">
                  {label} ({items.length})
                </summary>
                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  {items.slice(0, 12).map((item) => (
                    <article
                      key={`${item.explanation_type}-${item.candidate_id}`}
                      className="rounded border border-white/10 p-3"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="font-semibold text-white">{item.short_summary}</p>
                        <span className="rounded bg-white/5 px-2 py-1 text-white">
                          {item.explanation_type.replace(/_/g, " ")} · {formatPercent(item.confidence)}
                        </span>
                      </div>
                      <p className="mt-2">{item.detailed_explanation}</p>
                      <p className="mt-1">
                        Key reasons: {item.key_reasons.join("; ") || "No reasons available"}
                      </p>
                      {item.evidence.length > 0 && (
                        <details className="mt-2 rounded border border-white/10 p-2">
                          <summary className="cursor-pointer text-white">Evidence and source fields</summary>
                          <ul className="mt-2 space-y-1">
                            {item.evidence.slice(0, 12).map((evidence, index) => (
                              <li key={`${evidence.source_artifact}-${evidence.source_field}-${index}`}>
                                <span className="text-sky-100">
                                  {evidence.source_artifact}.{evidence.source_field}:
                                </span>{" "}
                                {evidence.snippet}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                      {(item.warnings.length > 0 || item.limitations.length > 0) && (
                        <p className="mt-2 text-amber-100">
                          Limits: {[...item.warnings, ...item.limitations].slice(0, 4).join("; ")}
                        </p>
                      )}
                    </article>
                  ))}
                </div>
              </details>
            ) : null,
          )}
          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Uncertainty, fallbacks, and human review
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Main uncertainties: {explanations.project_summary.main_uncertainties.join("; ") || "None reported"}
              </p>
              <p>
                Fallback signals: {explanations.signal_explanation.fallback_signals.join(", ") || "None reported"}
              </p>
              <p>
                Human checks: {explanations.uncertainty_summary.recommended_human_checks.join("; ") || "None reported"}
              </p>
              <p>
                Human review notes: {explanations.project_summary.human_review_notes.join("; ") || "None reported"}
              </p>
              {(explanations.warnings.length > 0 || explanations.limitations.length > 0) && (
                <p className="text-amber-100">
                  Warnings and limitations: {[...explanations.warnings, ...explanations.limitations]
                    .slice(0, 6)
                    .join("; ")}
                </p>
              )}
            </div>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canExplain
            ? "No saved explanation artifact. Create explanations from the available BOBA evidence."
            : "Create at least one BOBA understanding, discovery, ranking, or editorial artifact first."}
        </p>
      )}
    </section>
  );
}

function BobaCreativeDirectionV2Panel({
  direction,
  directing,
  canDirect,
  onDirect,
}: {
  direction: BobaCreativeDirectionSetV2 | null | undefined;
  directing: boolean;
  canDirect: boolean;
  onDirect: () => void;
}) {
  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Creative Director V2</p>
          <p className="text-xs text-muted">
            Senior-editor guidance from saved BOBA decisions. Advisory only; it does not edit or render media.
          </p>
        </div>
        <button
          type="button"
          disabled={!canDirect || directing}
          onClick={onDirect}
          className="rounded border border-violet-200/30 px-2 py-1 text-[11px] text-violet-100 hover:border-violet-100 disabled:opacity-50"
        >
          {directing
            ? "Creating…"
            : direction
              ? "Refresh creative direction"
              : "Create creative direction"}
        </button>
      </div>

      {direction ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="rounded border border-white/10 p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-semibold text-white">
                  {direction.project_direction.overall_style}
                </p>
                <p className="mt-1">Tone: {direction.project_direction.tone}</p>
              </div>
              <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-white">
                {Math.round(direction.creative_quality_summary.overall_confidence)}/100 confidence
              </span>
            </div>
            <p className="mt-2">
              Target feeling: {direction.project_direction.target_viewer_feeling}
            </p>
            <details className="mt-2 rounded border border-white/10 p-2">
              <summary className="cursor-pointer font-semibold text-white">
                Project creative philosophy
              </summary>
              <div className="mt-2 space-y-1">
                <p>Pacing: {direction.project_direction.pacing_philosophy}</p>
                <p>Captions: {direction.project_direction.caption_philosophy}</p>
                <p>Motion: {direction.project_direction.motion_philosophy}</p>
                <p>Audio: {direction.project_direction.audio_philosophy}</p>
                <p>
                  Human review: {direction.project_direction.human_review_notes.join("; ") || "Not available"}
                </p>
              </div>
            </details>
          </div>

          {direction.clip_directions.map((clip) => (
            <article
              key={clip.candidate_id}
              className="rounded border border-white/10 p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-semibold text-white">{clip.candidate_id}</p>
                  <p>
                    {clip.render_readiness.replace(/_/g, " ")} · {formatPercent(clip.confidence)} evidence confidence
                  </p>
                </div>
                <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-white">
                  {Math.round(clip.creative_quality_score.overall_confidence)}/100 creative quality
                </span>
              </div>
              <p className="mt-2">Angle: {clip.final_clip_angle}</p>
              <p className="mt-1">
                Hook: {clip.hook_treatment.hook_type.replace(/_/g, " ")} · {clip.hook_treatment.opening_line_direction}
              </p>
              <div className="mt-2 rounded border border-violet-200/10 bg-violet-200/[0.03] p-2">
                <p className="font-semibold text-violet-100">Opening three seconds</p>
                <p className="mt-1">Visual: {clip.opening_three_second_plan.what_viewer_sees_first}</p>
                <p>Caption: {clip.opening_three_second_plan.caption_implication}</p>
                <p>Curiosity: {clip.opening_three_second_plan.curiosity_gap}</p>
                <p>Motion: {clip.opening_three_second_plan.motion_choice}</p>
              </div>

              <details className="mt-2 rounded border border-white/10 p-2">
                <summary className="cursor-pointer font-semibold text-white">
                  Pacing, captions, and motion
                </summary>
                <div className="mt-2 space-y-1">
                  <p>0–3s: {clip.pacing_map.first_3_seconds}</p>
                  <p>3–10s: {clip.pacing_map.seconds_3_to_10}</p>
                  <p>Middle: {clip.pacing_map.middle_section}</p>
                  <p>Payoff: {clip.pacing_map.payoff_section}</p>
                  <p>Ending: {clip.pacing_map.ending}</p>
                  <p>
                    Caption style: {clip.caption_direction.style.replace(/_/g, " ")} · Emphasis: {clip.caption_direction.emphasis_words.join(", ") || "Not available"}
                  </p>
                  <p>Caption rhythm: {clip.caption_direction.rhythm}</p>
                  <p>
                    Motion: {clip.motion_direction.style.replace(/_/g, " ")} · Stable moments: {clip.motion_direction.stable_moments.join("; ")}
                  </p>
                  {clip.motion_direction.safety_warnings.length > 0 && (
                    <p className="text-amber-100">
                      Motion safety: {clip.motion_direction.safety_warnings.join("; ")}
                    </p>
                  )}
                </div>
              </details>

              <details className="mt-2 rounded border border-white/10 p-2">
                <summary className="cursor-pointer font-semibold text-white">
                  Audio, retention, and emotional arc
                </summary>
                <div className="mt-2 space-y-1">
                  <p>
                    Music mood: {clip.audio_direction.music_mood.replace(/_/g, " ")} (metadata only; no track selected)
                  </p>
                  <p>SFX intensity: {clip.audio_direction.sfx_intensity}</p>
                  <p>Ducking: {clip.audio_direction.ducking_guidance}</p>
                  <p>Speech: {clip.audio_direction.speech_clarity_notes}</p>
                  <p>Retention opening: {clip.retention_plan.opening_hook}</p>
                  <p>Mid-clip hold: {clip.retention_plan.mid_clip_hold}</p>
                  <p>Payoff: {clip.retention_plan.payoff_delivery}</p>
                  <p>Replay trigger: {clip.retention_plan.replay_trigger}</p>
                  <p>
                    Emotional arc: {clip.emotional_arc.starting_emotion} → {clip.emotional_arc.build_emotion} → {clip.emotional_arc.payoff_emotion}
                  </p>
                </div>
              </details>

              {(clip.risk_fixes.length > 0 || clip.warnings.length > 0) && (
                <p className="mt-2 text-amber-100">
                  Review: {[...clip.risk_fixes, ...clip.warnings].slice(0, 8).join("; ")}
                </p>
              )}
            </article>
          ))}

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Signal usage and limitations
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Fallback used: {direction.signal_usage.fallback_used ? "Yes" : "No"} · Missing: {direction.signal_usage.unavailable_signals.join(", ") || "None reported"}
              </p>
              <p>
                Warnings: {[...direction.warnings, ...direction.signal_usage.warnings].join("; ") || "None reported"}
              </p>
              <p>Limitations: {direction.limitations.join("; ")}</p>
            </div>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canDirect
            ? "No saved V2 creative direction. Create it from the saved editorial decisions."
            : "Create editorial decisions before generating V2 creative direction."}
        </p>
      )}
    </section>
  );
}

function BobaClipBriefPanel({
  briefs,
  generating,
  canGenerate,
  onGenerate,
}: {
  briefs: BobaClipBriefSetV1 | null | undefined;
  generating: boolean;
  canGenerate: boolean;
  onGenerate: () => void;
}) {
  const groups = briefs
    ? [
        { label: "Selected clip briefs", items: briefs.selected_briefs, open: true },
        { label: "Backup clip briefs", items: briefs.backup_briefs, open: false },
        { label: "Blocked clip briefs", items: briefs.blocked_briefs, open: false },
      ]
    : [];

  return (
    <section className="rounded-xl border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Clip Brief Generator V1</p>
          <p className="text-xs text-muted">
            Compact editor packets from saved BOBA artifacts. Advisory only; generation does not edit or render media.
          </p>
        </div>
        <button
          type="button"
          disabled={!canGenerate || generating}
          onClick={onGenerate}
          className="rounded border border-cyan-200/30 px-2 py-1 text-[11px] text-cyan-100 hover:border-cyan-100 disabled:opacity-50"
        >
          {generating ? "Creating…" : briefs ? "Refresh clip briefs" : "Create clip briefs"}
        </button>
      </div>

      {briefs ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="rounded border border-white/10 p-3">
            <p className="font-semibold text-white">One-page editor packet</p>
            <p className="mt-1">{briefs.project_summary}</p>
            <p className="mt-2">
              Production order: {briefs.production_order.join(" → ") || "No selected clips ready"}
            </p>
            <p>
              Selected {briefs.selected_briefs.length} · Backup {briefs.backup_briefs.length} · Blocked {briefs.blocked_briefs.length}
            </p>
          </div>

          {groups.map((group) => (
            <details
              key={group.label}
              open={group.open}
              className="rounded border border-white/10 p-3"
            >
              <summary className="cursor-pointer font-semibold text-white">
                {group.label} ({group.items.length})
              </summary>
              {group.items.length > 0 ? (
                <div className="mt-3 space-y-3">
                  {group.items.map((brief) => {
                    const instructions = [
                      ["Hook", brief.hook_instruction],
                      ["Opening three seconds", brief.opening_three_second_instruction],
                      ["Story", brief.story_instruction],
                      ["Cut", brief.cut_instruction],
                      ["Captions", brief.caption_instruction],
                      ["Motion", brief.motion_instruction],
                      ["Audio / music mood", brief.audio_instruction],
                      ["SFX", brief.sfx_instruction],
                      ["Retention", brief.retention_instruction],
                    ] as const;
                    return (
                      <article key={brief.brief_id} className="rounded border border-white/10 p-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <p className="font-semibold text-white">{brief.brief_title}</p>
                            <p>
                              {brief.candidate_id} · {brief.production_priority.replace(/_/g, " ")} · {brief.render_readiness.replace(/_/g, " ")}
                            </p>
                          </div>
                          <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-white">
                            {formatPercent(brief.confidence)} evidence confidence
                          </span>
                        </div>
                        <p className="mt-2">
                          Source: {brief.source_window.start_seconds.toFixed(2)}s–{brief.source_window.end_seconds.toFixed(2)}s ({brief.source_window.duration_seconds.toFixed(2)}s)
                        </p>
                        <p className="mt-1">Angle: {brief.final_clip_angle}</p>
                        <p className="mt-1">Target feeling: {brief.target_viewer_feeling}</p>

                        <div className="mt-2 rounded border border-cyan-200/10 bg-cyan-200/[0.03] p-2">
                          <p className="font-semibold text-cyan-100">Opening handoff</p>
                          <p className="mt-1">{brief.opening_three_second_instruction.summary}</p>
                          <p>Hook: {brief.hook_instruction.summary}</p>
                          <p>Do: {brief.opening_three_second_instruction.do_this}</p>
                          <p>Avoid: {brief.opening_three_second_instruction.avoid_this}</p>
                        </div>

                        <details className="mt-2 rounded border border-white/10 p-2">
                          <summary className="cursor-pointer font-semibold text-white">
                            Full instruction packet
                          </summary>
                          <div className="mt-2 space-y-2">
                            {instructions.map(([label, instruction]) => (
                              <div key={instruction.instruction_type}>
                                <p className="font-semibold text-white">
                                  {label} · {instruction.priority.replace(/_/g, " ")}
                                </p>
                                <p>{instruction.summary}</p>
                                <p>Do: {instruction.do_this}</p>
                                <p>Avoid: {instruction.avoid_this}</p>
                                <p>Why: {instruction.reason}</p>
                              </div>
                            ))}
                          </div>
                        </details>

                        <details className="mt-2 rounded border border-white/10 p-2">
                          <summary className="cursor-pointer font-semibold text-white">
                            Risks and editor checklist
                          </summary>
                          <div className="mt-2 space-y-2">
                            <p>Risk fixes: {brief.risk_fixes.join("; ")}</p>
                            {brief.editor_checklist.map((item) => (
                              <div key={item.item_id} className="rounded border border-white/5 p-2">
                                <p className="font-semibold text-white">
                                  {item.label} · {item.status}
                                </p>
                                <p>{item.reason}</p>
                              </div>
                            ))}
                            <p>
                              Human review: {brief.human_review_notes.join("; ") || "Required before production"}
                            </p>
                          </div>
                        </details>

                        {(brief.warnings.length > 0 || brief.limitations.length > 0) && (
                          <p className="mt-2 text-amber-100">
                            Review: {[...brief.warnings, ...brief.limitations].slice(0, 8).join("; ")}
                          </p>
                        )}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <p className="mt-2">No briefs in this category.</p>
              )}
            </details>
          ))}

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Signal usage and limitations
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Fallback used: {briefs.signal_usage.fallback_used ? "Yes" : "No"} · Missing: {briefs.signal_usage.unavailable_signals.join(", ") || "None reported"}
              </p>
              <p>
                Warnings: {[...briefs.warnings, ...briefs.signal_usage.warnings].join("; ") || "None reported"}
              </p>
              <p>Limitations: {briefs.limitations.join("; ")}</p>
            </div>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canGenerate
            ? "No saved clip brief packet. Generate it from Creative Director V2 and Editorial Decision artifacts."
            : "Create Creative Director V2 direction and editorial decisions before generating clip briefs."}
        </p>
      )}
    </section>
  );
}

function BobaHookRetentionPanel({
  analysis,
  generating,
  canGenerate,
  onGenerate,
}: {
  analysis: BobaHookRetentionSetV1 | null | undefined;
  generating: boolean;
  canGenerate: boolean;
  onGenerate: () => void;
}) {
  return (
    <section className="rounded-xl border border-fuchsia-300/20 bg-fuchsia-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Hook + Retention Brain V1
          </p>
          <p className="text-xs text-muted">
            Bounded hook alternatives and retention guidance from saved BOBA artifacts.
            Advisory only; it does not edit or render media.
          </p>
        </div>
        <button
          type="button"
          disabled={!canGenerate || generating}
          onClick={onGenerate}
          className="rounded border border-fuchsia-200/30 px-2 py-1 text-[11px] text-fuchsia-100 hover:border-fuchsia-100 disabled:opacity-50"
        >
          {generating
            ? "Analyzingâ€¦"
            : analysis
              ? "Refresh hook analysis"
              : "Analyze hooks"}
        </button>
      </div>

      {analysis ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="rounded border border-white/10 p-3">
            <p className="font-semibold text-white">Project retention summary</p>
            <p className="mt-1">{analysis.project_retention_summary}</p>
          </div>

          {analysis.analyses.map((item) => {
            const featuredAlternatives = item.hook_alternatives.filter((alternative) =>
              ["best", "safest", "boldest"].includes(alternative.recommendation_label),
            );
            const activeRisks = [
              [item.retention_risk_review.slow_start_risk, "Slow start"],
              [item.retention_risk_review.unclear_context_risk, "Unclear context"],
              [item.retention_risk_review.weak_payoff_risk, "Weak payoff"],
              [item.retention_risk_review.filler_risk, "Filler"],
              [item.retention_risk_review.over_editing_risk, "Over-editing"],
              [item.retention_risk_review.under_editing_risk, "Under-editing"],
              [item.retention_risk_review.caption_overload_risk, "Caption overload"],
              [item.retention_risk_review.audio_distraction_risk, "Audio distraction"],
            ]
              .filter(([enabled]) => enabled)
              .map(([, label]) => label);
            return (
              <article
                key={item.analysis_id}
                className="rounded border border-white/10 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-white">{item.candidate_id}</p>
                    <p>
                      {item.hook_analysis.hook_type.replace(/_/g, " ")} Â·{" "}
                      {formatPercent(item.confidence)} evidence confidence
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded bg-fuchsia-200/10 px-2 py-1 text-fuchsia-100">
                      Hook {Math.round(item.retention_score.hook_score)}/100
                    </span>
                    <span className="rounded bg-white/5 px-2 py-1 text-white">
                      Retention{" "}
                      {Math.round(item.retention_score.overall_retention_score)}/100
                    </span>
                  </div>
                </div>

                <div className="mt-2 rounded border border-fuchsia-200/10 bg-fuchsia-200/[0.03] p-2">
                  <p className="font-semibold text-fuchsia-100">Opening three seconds</p>
                  <p className="mt-1">{item.retention_plan.seconds_0_to_3}</p>
                  <p>Improved hook: {item.hook_analysis.improved_hook_direction}</p>
                  <p>Pattern interrupt: {item.hook_analysis.pattern_interrupt}</p>
                </div>

                <div className="mt-2 grid gap-2 lg:grid-cols-3">
                  {featuredAlternatives.map((alternative) => (
                    <div
                      key={alternative.alternative_id}
                      className="rounded border border-white/10 p-2"
                    >
                      <p className="font-semibold text-white">
                        {alternative.recommendation_label} Â·{" "}
                        {alternative.hook_type.replace(/_/g, " ")}
                      </p>
                      <p className="mt-1">{alternative.opening_line_direction}</p>
                      <p className="mt-1">
                        Strength {Math.round(alternative.strength_score)}/100 Â· Risk{" "}
                        {Math.round(alternative.risk_score)}/100
                      </p>
                      <p className="mt-1">May work: {alternative.why_it_may_work}</p>
                      <p>May fail: {alternative.why_it_may_fail}</p>
                    </div>
                  ))}
                </div>

                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer font-semibold text-white">
                    Retention plan and drop-off review
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>0â€“3s: {item.retention_plan.seconds_0_to_3}</p>
                    <p>3â€“10s: {item.retention_plan.seconds_3_to_10}</p>
                    <p>Middle: {item.retention_plan.middle_hold_strategy}</p>
                    <p>Payoff: {item.retention_plan.payoff_timing_strategy}</p>
                    <p>Ending / replay: {item.retention_plan.ending_replay_trigger}</p>
                    <p>
                      Drop-off risks: {activeRisks.join(", ") || "None detected from saved metadata"}
                    </p>
                    <p>
                      Risk fixes: {item.retention_risk_review.risk_fixes.join("; ") || "Human source review only"}
                    </p>
                  </div>
                </details>

                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer font-semibold text-white">
                    Clip brief enhancement suggestions
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>
                      Opening:{" "}
                      {item.brief_enhancements.enhanced_opening_line_direction}
                    </p>
                    <p>
                      Caption: {item.brief_enhancements.enhanced_caption_hook}
                    </p>
                    <p>
                      Payoff: {item.brief_enhancements.enhanced_payoff_timing}
                    </p>
                    <p>
                      Replay: {item.brief_enhancements.enhanced_replay_trigger}
                    </p>
                    <p className="text-amber-100">
                      Not applied automatically:{" "}
                      {item.brief_enhancements.retention_warning}
                    </p>
                  </div>
                </details>

                {(item.warnings.length > 0 || item.limitations.length > 0) && (
                  <p className="mt-2 text-amber-100">
                    Human review: {[...item.warnings, ...item.limitations]
                      .slice(0, 8)
                      .join("; ")}
                  </p>
                )}
              </article>
            );
          })}

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Signal usage and limitations
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Fallback used: {analysis.signal_usage.fallback_used ? "Yes" : "No"} Â·
                Missing:{" "}
                {analysis.signal_usage.unavailable_signals.join(", ") ||
                  "None reported"}
              </p>
              <p>
                Warnings:{" "}
                {[...analysis.warnings, ...analysis.signal_usage.warnings].join("; ") ||
                  "None reported"}
              </p>
              <p>Limitations: {analysis.limitations.join("; ")}</p>
            </div>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canGenerate
            ? "No saved hook-retention artifact. Analyze the selected clip briefs."
            : "Create selected clip briefs before running Hook + Retention Brain V1."}
        </p>
      )}
    </section>
  );
}

function BobaCaptionMotionPanel({
  recommendations,
  generating,
  canGenerate,
  onGenerate,
}: {
  recommendations: BobaCaptionMotionRecommendationSetV1 | null | undefined;
  generating: boolean;
  canGenerate: boolean;
  onGenerate: () => void;
}) {
  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Caption + Motion Recommendation Brain V1
          </p>
          <p className="text-xs text-muted">
            Advisory caption, timing, and motion guidance. It does not alter or render
            media.
          </p>
        </div>
        <button
          type="button"
          disabled={!canGenerate || generating}
          onClick={onGenerate}
          className="rounded border border-violet-200/30 px-2 py-1 text-[11px] text-violet-100 hover:border-violet-100 disabled:opacity-50"
        >
          {generating
            ? "Recommending..."
            : recommendations
              ? "Refresh recommendations"
              : "Recommend captions + motion"}
        </button>
      </div>

      {recommendations ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="rounded border border-white/10 p-3">
            <p className="font-semibold text-white">Project recommendation summary</p>
            <p className="mt-1">{recommendations.project_caption_motion_summary}</p>
          </div>

          {recommendations.recommendations.map((item) => {
            const safetyRisks = [
              [item.safety_review.face_cutoff_risk, "Face cutoff"],
              [item.safety_review.multi_speaker_layout_risk, "Multi-speaker layout"],
              [item.safety_review.unavailable_face_signal_risk, "Face signals unavailable"],
              [item.safety_review.unavailable_layout_signal_risk, "Layout signals unavailable"],
              [item.safety_review.caption_overload_risk, "Caption overload"],
              [item.safety_review.readability_risk, "Readability"],
              [item.safety_review.over_motion_risk, "Over-motion"],
              [item.safety_review.under_motion_risk, "Under-motion"],
              [item.safety_review.hook_distraction_risk, "Hook distraction"],
            ]
              .filter(([enabled]) => enabled)
              .map(([, label]) => label);
            const caption = item.caption_recommendation;
            const motion = item.motion_recommendation;
            return (
              <article
                key={item.recommendation_id}
                className="rounded border border-white/10 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-white">{item.candidate_id}</p>
                    <p>
                      Caption {caption.caption_style.replace(/_/g, " ")} -{" "}
                      {caption.caption_density} density - {caption.caption_rhythm} rhythm
                    </p>
                    <p>
                      Motion {motion.motion_style.replace(/_/g, " ")} -{" "}
                      {motion.motion_intensity} intensity
                    </p>
                  </div>
                  <span className="rounded bg-violet-200/10 px-2 py-1 text-violet-100">
                    Overall{" "}
                    {Math.round(item.recommendation_score.overall_recommendation_score)}
                    /100
                  </span>
                </div>

                <div className="mt-2 grid gap-2 lg:grid-cols-2">
                  <div className="rounded border border-violet-200/10 p-2">
                    <p className="font-semibold text-violet-100">Caption guidance</p>
                    <p className="mt-1">{caption.hook_caption_instruction}</p>
                    <p>
                      Keywords: {caption.keyword_highlights.join(", ") || "Not available"}
                    </p>
                    <p>Payoff: {caption.payoff_caption_instruction}</p>
                    <p>
                      Readability:{" "}
                      {caption.readability_notes.join("; ") || "Human review required"}
                    </p>
                  </div>
                  <div className="rounded border border-violet-200/10 p-2">
                    <p className="font-semibold text-violet-100">Motion guidance</p>
                    <p className="mt-1">{motion.reason}</p>
                    <p>
                      Zoom: {motion.zoom_moments.join("; ") || "No zoom recommended"}
                    </p>
                    <p>
                      Punch-in:{" "}
                      {motion.punch_in_moments.join("; ") || "No punch-in recommended"}
                    </p>
                    <p>Stable: {motion.stable_moments.join("; ")}</p>
                  </div>
                </div>

                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer font-semibold text-white">
                    Timing map and safety review
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>0-3s: {item.timing_map.seconds_0_to_3}</p>
                    <p>3-10s: {item.timing_map.seconds_3_to_10}</p>
                    <p>Middle: {item.timing_map.middle_section}</p>
                    <p>Payoff: {item.timing_map.payoff_section}</p>
                    <p>Ending: {item.timing_map.ending_section}</p>
                    <p>
                      Safety risks: {safetyRisks.join(", ") || "None in supplied metadata"}
                    </p>
                    <p>
                      Fixes:{" "}
                      {item.safety_review.fixes.join("; ") || "Verify against source"}
                    </p>
                  </div>
                </details>

                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer font-semibold text-white">
                    Advisory clip-brief enhancements
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>Caption: {item.brief_enhancement.improved_caption_instruction}</p>
                    <p>Motion: {item.brief_enhancement.improved_motion_instruction}</p>
                    <p className="text-amber-100">
                      Not applied automatically.{" "}
                      {item.brief_enhancement.layout_safe_warning}
                    </p>
                  </div>
                </details>
              </article>
            );
          })}

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Signal usage and limitations
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Fallback used: {recommendations.signal_usage.fallback_used ? "Yes" : "No"}
                {" - "}Missing:{" "}
                {recommendations.signal_usage.unavailable_signals.join(", ") ||
                  "None reported"}
              </p>
              <p>
                Warnings:{" "}
                {[...recommendations.warnings, ...recommendations.signal_usage.warnings]
                  .join("; ") || "None reported"}
              </p>
              <p>Limitations: {recommendations.limitations.join("; ")}</p>
            </div>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canGenerate
            ? "No saved caption-motion artifact. Generate advisory recommendations from the clip briefs."
            : "Create selected or backup clip briefs before running Caption + Motion Brain V1."}
        </p>
      )}
    </section>
  );
}

function BobaMusicMoodPanel({
  recommendations,
  generating,
  canGenerate,
  onGenerate,
}: {
  recommendations: BobaMusicMoodRecommendationSetV1 | null | undefined;
  generating: boolean;
  canGenerate: boolean;
  onGenerate: () => void;
}) {
  return (
    <section className="rounded-xl border border-emerald-300/20 bg-emerald-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Music Mood Brain V1
          </p>
          <p className="text-xs text-muted">
            Advisory mood, speech-clarity, ducking, and SFX guidance. No music is
            selected or applied.
          </p>
        </div>
        <button
          type="button"
          disabled={!canGenerate || generating}
          onClick={onGenerate}
          className="rounded border border-emerald-200/30 px-2 py-1 text-[11px] text-emerald-100 hover:border-emerald-100 disabled:opacity-50"
        >
          {generating
            ? "Recommending..."
            : recommendations
              ? "Refresh audio guidance"
              : "Recommend audio mood"}
        </button>
      </div>

      {recommendations ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="rounded border border-white/10 p-3">
            <p className="font-semibold text-white">Project audio summary</p>
            <p className="mt-1">{recommendations.project_audio_summary}</p>
          </div>

          {recommendations.recommendations.map((item) => {
            const risks = [
              [item.audio_risk_review.music_overpowering_risk, "Music overpowering"],
              [item.audio_risk_review.wrong_mood_risk, "Wrong mood"],
              [item.audio_risk_review.speech_clarity_risk, "Speech clarity"],
              [item.audio_risk_review.sfx_overload_risk, "SFX overload"],
              [item.audio_risk_review.silence_damage_risk, "Silence damage"],
              [item.audio_risk_review.emotional_mismatch_risk, "Emotional mismatch"],
            ]
              .filter(([enabled]) => enabled)
              .map(([, label]) => label);
            return (
              <article
                key={item.recommendation_id}
                className="rounded border border-white/10 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-white">{item.candidate_id}</p>
                    <p>
                      {item.music_mood.primary_mood.replace(/_/g, " ")} /{" "}
                      {item.music_mood.secondary_mood.replace(/_/g, " ")} -{" "}
                      {item.music_mood.energy_level} energy
                    </p>
                    <p>
                      Role {item.music_mood.music_role.replace(/_/g, " ")} - speech{" "}
                      {item.speech_clarity_plan.speech_priority}
                    </p>
                  </div>
                  <span className="rounded bg-emerald-200/10 px-2 py-1 text-emerald-100">
                    Audio {Math.round(item.recommendation_score.overall_audio_score)}/100
                  </span>
                </div>

                <div className="mt-2 grid gap-2 lg:grid-cols-2">
                  <div className="rounded border border-emerald-200/10 p-2">
                    <p className="font-semibold text-emerald-100">Speech + ducking</p>
                    <p className="mt-1">{item.speech_clarity_plan.ducking_guidance}</p>
                    <p>{item.speech_clarity_plan.music_volume_guidance}</p>
                    <p>{item.speech_clarity_plan.silence_guidance}</p>
                  </div>
                  <div className="rounded border border-emerald-200/10 p-2">
                    <p className="font-semibold text-emerald-100">SFX recommendation</p>
                    <p className="mt-1">
                      Intensity: {item.sfx_recommendation.sfx_intensity}
                    </p>
                    <p>{item.sfx_recommendation.hook_sfx_guidance}</p>
                    <p>{item.sfx_recommendation.payoff_sfx_guidance}</p>
                  </div>
                </div>

                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer font-semibold text-white">
                    Audio energy map and risks
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>0-3s: {item.audio_energy_map.seconds_0_to_3}</p>
                    <p>3-10s: {item.audio_energy_map.seconds_3_to_10}</p>
                    <p>Middle: {item.audio_energy_map.middle_section}</p>
                    <p>Payoff: {item.audio_energy_map.payoff_section}</p>
                    <p>Ending: {item.audio_energy_map.ending_section}</p>
                    <p>
                      Protected silence:{" "}
                      {item.audio_energy_map.silence_moments.join("; ") ||
                        "None identified"}
                    </p>
                    <p>Risks: {risks.join(", ") || "None in supplied metadata"}</p>
                  </div>
                </details>

                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer font-semibold text-white">
                    Advisory clip-brief audio enhancement
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>{item.brief_enhancement.improved_audio_instruction}</p>
                    <p>{item.brief_enhancement.improved_sfx_instruction}</p>
                    <p className="text-amber-100">
                      Not applied automatically.{" "}
                      {item.brief_enhancement.rights_review_warning}
                    </p>
                  </div>
                </details>
              </article>
            );
          })}

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Signal usage and limitations
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Audio signals:{" "}
                {recommendations.signal_usage.audio_signals_used ? "Used" : "Unavailable"}
                {" - "}Silence signals:{" "}
                {recommendations.signal_usage.silence_signals_used
                  ? "Used"
                  : "Unavailable"}
              </p>
              <p>
                Missing:{" "}
                {recommendations.signal_usage.unavailable_signals.join(", ") ||
                  "None reported"}
              </p>
              <p>Limitations: {recommendations.limitations.join("; ")}</p>
            </div>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canGenerate
            ? "No saved music-mood artifact. Generate advisory audio guidance from the clip briefs."
            : "Create selected or backup clip briefs before running Music Mood Brain V1."}
        </p>
      )}
    </section>
  );
}

function BobaExperimentationPanel({
  projectId,
  canGenerate,
}: {
  projectId: string;
  canGenerate: boolean;
}) {
  const experimentationQuery = useBobaExperimentation(projectId);
  const generateExperimentation = useGenerateBobaExperimentation(projectId);
  const exportExperimentation = useExportBobaExperimentation(projectId);
  const resetExperimentation = useResetBobaExperimentation(projectId);
  const [status, setStatus] = useState("");
  const experimentation: BobaExperimentationSetV1 | null | undefined =
    experimentationQuery.data;
  const busy =
    generateExperimentation.isPending ||
    exportExperimentation.isPending ||
    resetExperimentation.isPending;

  function generate() {
    setStatus("");
    generateExperimentation.mutate(
      { dry_run: false },
      {
        onSuccess: (result) => {
          setStatus(
            `Generated ${result.experiment_plans.length} advisory experiment plan(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportPlan() {
    exportExperimentation.mutate(undefined, {
      onSuccess: (payload) => {
        const blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `boba_experimentation_${projectId}.json`;
        link.click();
        URL.revokeObjectURL(link.href);
        setStatus("Safe experimentation export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's experiment plans and manual results only?",
      )
    ) {
      return;
    }
    resetExperimentation.mutate(undefined, {
      onSuccess: () => setStatus("Experimentation reset; other BOBA artifacts remain."),
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-fuchsia-300/20 bg-fuchsia-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Experimentation System V1
          </p>
          <p className="text-xs text-muted">
            Experiments are plans only. BOBA does not upload, render, or collect
            analytics.
          </p>
          <p className="text-xs text-amber-100">
            Creator approval is required before treating any experiment as active.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!canGenerate || busy}
            onClick={generate}
            className="rounded border border-fuchsia-200/30 px-2 py-1 text-[11px] text-fuchsia-100 hover:border-fuchsia-100 disabled:opacity-50"
          >
            {generateExperimentation.isPending
              ? "Planning..."
              : experimentation
                ? "Refresh experiments"
                : "Plan experiments"}
          </button>
          <button
            type="button"
            disabled={!experimentation || busy}
            onClick={exportPlan}
            className="rounded border border-white/20 px-2 py-1 text-[11px] text-white disabled:opacity-50"
          >
            Export
          </button>
          <button
            type="button"
            disabled={!experimentation || busy}
            onClick={reset}
            className="rounded border border-rose-300/20 px-2 py-1 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset
          </button>
        </div>
      </div>

      {status && <p className="mt-2 text-xs text-muted">{status}</p>}

      {experimentation ? (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="rounded border border-white/10 p-3">
            <p className="font-semibold text-white">Experiment summary</p>
            <p className="mt-1">{experimentation.experiment_summary}</p>
            <p className="mt-1">
              {experimentation.experiment_plans.length} plan(s) ·{" "}
              {experimentation.rejected_experiment_ideas.length} rejected idea(s) ·{" "}
              {experimentation.approval_requirements.length} approval requirement(s)
            </p>
          </div>

          {experimentation.experiment_plans.map((plan) => {
            const riskLabels = Object.entries(plan.risk_review)
              .filter(([, value]) => value === true)
              .map(([name]) => name.replace(/_/g, " "));
            const approvals = experimentation.approval_requirements.filter(
              (item) => item.experiment_id === plan.experiment_id,
            );
            return (
              <article
                key={plan.experiment_id}
                className="rounded border border-white/10 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold text-white">{plan.title}</p>
                    <p>
                      {plan.experiment_type.replace(/_/g, " ")} · Target{" "}
                      {plan.target_id}
                    </p>
                  </div>
                  <span className="rounded bg-fuchsia-200/10 px-2 py-1 text-fuchsia-100">
                    {plan.status.replace(/_/g, " ")} ·{" "}
                    {formatPercent(plan.confidence)}
                  </span>
                </div>

                <div className="mt-2 rounded border border-fuchsia-200/10 p-2">
                  <p className="font-semibold text-fuchsia-100">Baseline</p>
                  <p>{plan.baseline.summary}</p>
                  <p>{plan.baseline.current_instruction}</p>
                  <p>
                    Source: {plan.baseline.source_artifact}.
                    {plan.baseline.source_field}
                  </p>
                </div>

                <div className="mt-2 grid gap-2 lg:grid-cols-2">
                  {plan.variants.map((variant) => (
                    <div
                      key={variant.variant_id}
                      className="rounded border border-white/10 p-2"
                    >
                      <p className="font-semibold text-white">{variant.label}</p>
                      <p>{variant.instruction}</p>
                      <p>Changed variable: {variant.changed_variable}</p>
                      <p>Expected: {variant.expected_effect}</p>
                      <p className={variant.should_test ? "" : "text-amber-100"}>
                        {variant.should_test ? "Eligible for review" : "Do not test"}:{" "}
                        {variant.reason}
                      </p>
                    </div>
                  ))}
                </div>

                <div className="mt-2 grid gap-2 lg:grid-cols-2">
                  <div className="rounded border border-white/10 p-2">
                    <p className="font-semibold text-white">Hypothesis</p>
                    <p>{plan.hypothesis.statement}</p>
                    <p>Manual metric: {plan.metric_plan.primary_metric}</p>
                    <p>
                      Future analytics required:{" "}
                      {plan.metric_plan.analytics_required_later ? "Yes, later" : "No"}
                    </p>
                  </div>
                  <div className="rounded border border-white/10 p-2">
                    <p className="font-semibold text-white">Success + risk</p>
                    <p>{plan.success_criteria.success_definition}</p>
                    <p>
                      Risks: {riskLabels.join(", ") || "No elevated flag reported"}
                    </p>
                    <p>
                      Approval:{" "}
                      {approvals.map((item) => item.approval_type).join(", ") ||
                        "Creator approval"}
                    </p>
                  </div>
                </div>

                <details className="mt-2 rounded border border-white/10 p-2">
                  <summary className="cursor-pointer font-semibold text-white">
                    Learning handoff and limitations
                  </summary>
                  <div className="mt-2 space-y-1">
                    <p>{plan.learning_handoff.expected_learning_update}</p>
                    <p>
                      Automatic application:{" "}
                      {plan.learning_handoff.apply_automatically ? "Yes" : "No"}
                    </p>
                    <p>
                      Warnings:{" "}
                      {[...plan.warnings, ...plan.risk_review.warnings].join("; ") ||
                        "None reported"}
                    </p>
                    <p>Limitations: {plan.limitations.join("; ")}</p>
                  </div>
                </details>
              </article>
            );
          })}

          {experimentation.rejected_experiment_ideas.length > 0 && (
            <details className="rounded border border-rose-300/20 p-3">
              <summary className="cursor-pointer font-semibold text-rose-100">
                Rejected unsafe or unsupported ideas
              </summary>
              <div className="mt-2 space-y-2">
                {experimentation.rejected_experiment_ideas.map((idea) => (
                  <div key={idea.idea_id}>
                    <p className="font-semibold text-white">
                      {idea.experiment_type.replace(/_/g, " ")} · {idea.target_id}
                    </p>
                    <p>{idea.reason_rejected}</p>
                    <p>Risk: {idea.risk}</p>
                  </div>
                ))}
              </div>
            </details>
          )}

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Signal usage and system limits
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Missing:{" "}
                {experimentation.signal_usage.unavailable_signals.join(", ") ||
                  "None reported"}
              </p>
              <p>Warnings: {experimentation.warnings.join("; ")}</p>
              <p>Limitations: {experimentation.limitations.join("; ")}</p>
            </div>
          </details>
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {canGenerate
            ? "No saved experimentation artifact. Generate advisory plans from existing BOBA recommendations."
            : "Create clip briefs or downstream BOBA recommendations before planning experiments."}
        </p>
      )}
    </section>
  );
}

type PerformanceMetricField = Exclude<
  keyof BobaManualPerformanceMetricsV1,
  "custom_metrics"
>;

const performanceEventTypes: BobaPerformanceEventType[] = [
  "manual_clip_result",
  "manual_experiment_result",
  "manual_rating",
  "manual_note",
  "creator_interpretation",
];

const performanceTargetTypes: BobaPerformanceTargetType[] = [
  "clip",
  "candidate",
  "clip_brief",
  "experiment",
  "experiment_variant",
  "project",
];

const performanceOutcomeLabels: BobaPerformanceOutcomeLabel[] = [
  "variant_won",
  "baseline_won",
  "no_clear_winner",
  "rejected_all",
  "inconclusive",
  "not_enough_data",
];

const performanceMetricFields: Array<{
  key: PerformanceMetricField;
  label: string;
  maximum?: number;
  minimum?: number;
}> = [
  { key: "views", label: "Views", minimum: 0 },
  { key: "likes", label: "Likes", minimum: 0 },
  { key: "comments", label: "Comments", minimum: 0 },
  { key: "shares", label: "Shares", minimum: 0 },
  { key: "saves", label: "Saves", minimum: 0 },
  {
    key: "average_watch_time_seconds",
    label: "Average watch time (seconds)",
    minimum: 0,
  },
  {
    key: "average_view_duration_seconds",
    label: "Average view duration (seconds)",
    minimum: 0,
  },
  {
    key: "retention_percent",
    label: "Retention percent",
    minimum: 0,
    maximum: 100,
  },
  {
    key: "click_through_rate_percent",
    label: "Click-through rate percent",
    minimum: 0,
    maximum: 100,
  },
  {
    key: "completion_rate_percent",
    label: "Completion rate percent",
    minimum: 0,
    maximum: 100,
  },
  { key: "follower_gain", label: "Follower gain", minimum: 0 },
  { key: "manual_rank", label: "Manual rank", minimum: 1 },
];

function emptyPerformanceMetrics(): Record<PerformanceMetricField, string> {
  return {
    views: "",
    likes: "",
    comments: "",
    shares: "",
    saves: "",
    average_watch_time_seconds: "",
    average_view_duration_seconds: "",
    retention_percent: "",
    click_through_rate_percent: "",
    completion_rate_percent: "",
    follower_gain: "",
    manual_rank: "",
  };
}

function formatPerformanceMetrics(
  metrics: BobaManualPerformanceMetricsV1,
): string {
  const standard = Object.entries(metrics)
    .filter(
      ([key, value]) => key !== "custom_metrics" && typeof value === "number",
    )
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`);
  const custom = Object.entries(metrics.custom_metrics).map(
    ([key, value]) => `${key}: ${value}`,
  );
  return [...standard, ...custom].join(" · ") || "No numeric metrics entered";
}

function BobaPerformanceFeedbackPanel({
  projectId,
}: {
  projectId: string;
}) {
  const feedbackQuery = useBobaPerformanceFeedback(projectId);
  const recordEvent = useRecordBobaPerformanceFeedbackEvent(projectId);
  const generateFeedback = useGenerateBobaPerformanceFeedback(projectId);
  const exportFeedback = useExportBobaPerformanceFeedback(projectId);
  const resetFeedback = useResetBobaPerformanceFeedback(projectId);
  const [eventType, setEventType] =
    useState<BobaPerformanceEventType>("manual_clip_result");
  const [targetType, setTargetType] =
    useState<BobaPerformanceTargetType>("clip");
  const [targetId, setTargetId] = useState(projectId);
  const [experimentId, setExperimentId] = useState("");
  const [selectedVariantId, setSelectedVariantId] = useState("");
  const [outcomeLabel, setOutcomeLabel] =
    useState<BobaPerformanceOutcomeLabel>("inconclusive");
  const [platform, setPlatform] = useState("");
  const [manualRating, setManualRating] = useState("");
  const [creatorNote, setCreatorNote] = useState("");
  const [retentionNotes, setRetentionNotes] = useState("");
  const [metrics, setMetrics] = useState(emptyPerformanceMetrics);
  const [shouldFeedLearning, setShouldFeedLearning] = useState(false);
  const [status, setStatus] = useState("");
  const feedback = feedbackQuery.data;
  const busy =
    recordEvent.isPending ||
    generateFeedback.isPending ||
    exportFeedback.isPending ||
    resetFeedback.isPending;

  function parsedMetrics(): Partial<BobaManualPerformanceMetricsV1> | null {
    const entries: Array<[string, number]> = [];
    for (const field of performanceMetricFields) {
      const raw = metrics[field.key].trim();
      if (!raw) continue;
      const value = Number(raw);
      if (
        !Number.isFinite(value) ||
        value < (field.minimum ?? 0) ||
        (field.maximum !== undefined && value > field.maximum)
      ) {
        setStatus(`${field.label} is outside the supported range.`);
        return null;
      }
      entries.push([field.key, value]);
    }
    return Object.fromEntries(entries) as Partial<BobaManualPerformanceMetricsV1>;
  }

  function submitEvent() {
    const metricPayload = parsedMetrics();
    if (metricPayload === null) return;
    const rating = manualRating.trim() ? Number(manualRating) : undefined;
    if (
      rating !== undefined &&
      (!Number.isFinite(rating) || rating < 0 || rating > 5)
    ) {
      setStatus("Manual rating must be between 0 and 5.");
      return;
    }
    if (eventType === "manual_rating" && rating === undefined) {
      setStatus("Enter a manual rating before recording this event.");
      return;
    }
    if (
      eventType === "manual_experiment_result" &&
      !experimentId.trim()
    ) {
      setStatus("Choose an experiment ID before recording its outcome.");
      return;
    }
    if (
      eventType === "manual_experiment_result" &&
      outcomeLabel === "variant_won" &&
      !selectedVariantId.trim()
    ) {
      setStatus("Enter the winning variant ID.");
      return;
    }
    const effectiveTargetId =
      eventType === "manual_experiment_result"
        ? experimentId.trim()
        : targetId.trim();
    if (!effectiveTargetId) {
      setStatus("Choose a target ID before recording feedback.");
      return;
    }
    if (
      Object.keys(metricPayload).length === 0 &&
      rating === undefined &&
      !creatorNote.trim() &&
      !retentionNotes.trim()
    ) {
      setStatus("Enter at least one metric, rating, or explicit note.");
      return;
    }

    const input: BobaPerformanceFeedbackEventInput = {
      event_type: eventType,
      target_type:
        eventType === "manual_experiment_result" ? "experiment" : targetType,
      target_id: effectiveTargetId,
      experiment_id:
        eventType === "manual_experiment_result"
          ? experimentId.trim()
          : undefined,
      selected_variant_id:
        eventType === "manual_experiment_result"
          ? selectedVariantId.trim()
          : undefined,
      outcome_label:
        eventType === "manual_experiment_result" ? outcomeLabel : undefined,
      manual_rating: rating,
      creator_note: creatorNote.trim(),
      creator_interpretation:
        eventType === "creator_interpretation"
          ? creatorNote.trim()
          : undefined,
      platform: platform.trim(),
      source_label: "frontend_manual_entry",
      metrics: metricPayload,
      retention_notes: retentionNotes.trim(),
      should_feed_learning: shouldFeedLearning,
    };

    setStatus("");
    recordEvent.mutate(input, {
      onSuccess: (result) => {
        setStatus(
          `Recorded ${result.event.event_type.replace(/_/g, " ")} as explicit manual data. No analytics were collected.`,
        );
        setCreatorNote("");
        setRetentionNotes("");
        setManualRating("");
        setMetrics(emptyPerformanceMetrics());
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function generate(dryRun: boolean) {
    setStatus("");
    generateFeedback.mutate(
      { dry_run: dryRun },
      {
        onSuccess: (result) =>
          setStatus(
            dryRun
              ? `Dry run reviewed ${result.audit_summary.total_events} manual event(s); nothing was saved.`
              : `Performance summary updated from ${result.audit_summary.total_events} manual event(s).`,
          ),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function downloadExport() {
    setStatus("");
    exportFeedback.mutate(undefined, {
      onSuccess: (payload) => {
        const blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `boba_performance_feedback_${projectId}.json`;
        link.click();
        URL.revokeObjectURL(url);
        setStatus("Safe performance-feedback export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's manual performance events and summary only? Experimentation, Creator Learning, Approval/Rejection Learning, and Memory remain.",
      )
    ) {
      return;
    }
    setStatus("");
    resetFeedback.mutate(undefined, {
      onSuccess: () =>
        setStatus(
          "Performance feedback reset; Experimentation and learning artifacts remain.",
        ),
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-emerald-300/20 bg-emerald-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Performance Feedback Brain V1
          </p>
          <p className="text-xs text-emerald-100">
            Performance data is manual in V1. BOBA does not connect to platforms
            or collect analytics.
          </p>
          <p className="text-[11px] text-amber-100">
            Learning guidance is advisory unless you explicitly approve applying
            it.
          </p>
        </div>
        <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted">
          {feedback
            ? `${feedback.audit_summary.total_events} manual event(s) · ${formatPercent(feedback.pattern_summary.confidence)} pattern confidence`
            : "No saved summary"}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <select
          value={eventType}
          onChange={(event) =>
            setEventType(event.target.value as BobaPerformanceEventType)
          }
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white"
        >
          {performanceEventTypes.map((value) => (
            <option key={value} value={value}>
              {value.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <select
          value={targetType}
          disabled={eventType === "manual_experiment_result"}
          onChange={(event) =>
            setTargetType(event.target.value as BobaPerformanceTargetType)
          }
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white disabled:opacity-50"
        >
          {performanceTargetTypes.map((value) => (
            <option key={value} value={value}>
              {value.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <input
          value={targetId}
          disabled={eventType === "manual_experiment_result"}
          maxLength={180}
          onChange={(event) => setTargetId(event.target.value)}
          placeholder="Clip, candidate, brief, or project ID"
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30 disabled:opacity-50"
        />
        <input
          value={platform}
          maxLength={80}
          onChange={(event) => setPlatform(event.target.value)}
          placeholder="Platform (optional user text)"
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
        />
      </div>

      {eventType === "manual_experiment_result" && (
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <input
            value={experimentId}
            maxLength={128}
            onChange={(event) => setExperimentId(event.target.value)}
            placeholder="Saved experiment ID"
            className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
          />
          <input
            value={selectedVariantId}
            maxLength={128}
            onChange={(event) => setSelectedVariantId(event.target.value)}
            placeholder="Selected baseline or variant ID"
            className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
          />
          <select
            value={outcomeLabel}
            onChange={(event) =>
              setOutcomeLabel(
                event.target.value as BobaPerformanceOutcomeLabel,
              )
            }
            className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white"
          >
            {performanceOutcomeLabels.map((value) => (
              <option key={value} value={value}>
                {value.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
      )}

      <details className="mt-2 rounded border border-white/10 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-white">
          Optional creator-entered metrics
        </summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {performanceMetricFields.map((field) => (
            <label key={field.key} className="text-[11px] text-muted">
              {field.label}
              <input
                type="number"
                min={field.minimum}
                max={field.maximum}
                step={field.key === "manual_rank" ? 1 : "any"}
                value={metrics[field.key]}
                onChange={(event) =>
                  setMetrics((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white"
              />
            </label>
          ))}
        </div>
      </details>

      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <label className="text-[11px] text-muted">
          Manual quality rating (0–5)
          <input
            type="number"
            min={0}
            max={5}
            step="any"
            value={manualRating}
            onChange={(event) => setManualRating(event.target.value)}
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white"
          />
        </label>
        <label className="text-[11px] text-muted">
          Creator note
          <input
            value={creatorNote}
            maxLength={500}
            onChange={(event) => setCreatorNote(event.target.value)}
            placeholder="What worked or failed?"
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
          />
        </label>
        <label className="text-[11px] text-muted">
          Retention note
          <input
            value={retentionNotes}
            maxLength={500}
            onChange={(event) => setRetentionNotes(event.target.value)}
            placeholder="Example: people dropped before payoff"
            className="mt-1 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
          />
        </label>
      </div>

      <label className="mt-2 flex items-center gap-2 text-[11px] text-muted">
        <input
          type="checkbox"
          checked={shouldFeedLearning}
          onChange={(event) => setShouldFeedLearning(event.target.checked)}
        />
        Include this result in the advisory learning handoff; never apply it
        automatically.
      </label>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={submitEvent}
          className="rounded bg-emerald-300/15 px-2.5 py-1.5 text-[11px] text-emerald-100 disabled:opacity-50"
        >
          Record manual feedback
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => generate(false)}
          className="rounded border border-white/10 px-2.5 py-1.5 text-[11px] text-white disabled:opacity-50"
        >
          Generate summary
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => generate(true)}
          className="rounded border border-white/10 px-2.5 py-1.5 text-[11px] text-muted disabled:opacity-50"
        >
          Dry run
        </button>
        <button
          type="button"
          disabled={busy || !feedback}
          onClick={downloadExport}
          className="rounded border border-white/10 px-2.5 py-1.5 text-[11px] text-muted disabled:opacity-50"
        >
          Export
        </button>
        <button
          type="button"
          disabled={busy || !feedback}
          onClick={reset}
          className="rounded border border-rose-300/20 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
        >
          Reset feedback
        </button>
      </div>

      {status && <p className="mt-2 text-[11px] text-emerald-100">{status}</p>}

      {feedback && (
        <div className="mt-3 space-y-3 text-xs text-muted">
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded border border-white/10 p-2">
              <p className="font-semibold text-white">Manual audit</p>
              <p>{feedback.audit_summary.user_entered_count} user-entered event(s)</p>
              <p>{feedback.audit_summary.auto_collected_count} auto-collected event(s)</p>
              <p>
                Analytics API used:{" "}
                {feedback.signal_usage.analytics_api_used ? "Yes" : "No"}
              </p>
            </div>
            <div className="rounded border border-white/10 p-2">
              <p className="font-semibold text-white">Snapshots</p>
              <p>{feedback.performance_snapshots.length} snapshot(s)</p>
              <p>{feedback.experiment_outcomes.length} experiment review(s)</p>
            </div>
            <div className="rounded border border-white/10 p-2">
              <p className="font-semibold text-white">Advisory learning</p>
              <p>
                Automatic application:{" "}
                {feedback.learning_handoff.apply_automatically
                  ? "Enabled"
                  : "Disabled"}
              </p>
              <p>
                Confidence: {formatPercent(feedback.pattern_summary.confidence)}
              </p>
            </div>
          </div>

          {feedback.performance_snapshots.length > 0 && (
            <details className="rounded border border-white/10 p-3">
              <summary className="cursor-pointer font-semibold text-white">
                Performance snapshots
              </summary>
              <div className="mt-2 space-y-2">
                {feedback.performance_snapshots.slice(-8).map((snapshot) => (
                  <div key={snapshot.snapshot_id}>
                    <p className="font-semibold text-emerald-100">
                      {snapshot.target_id} ·{" "}
                      {formatPercent(snapshot.data_confidence)} confidence
                    </p>
                    <p>{formatPerformanceMetrics(snapshot.metrics)}</p>
                    <p>
                      Rating: {snapshot.manual_quality_rating ?? "Not entered"} ·
                      Platform: {snapshot.platform || "Not entered"}
                    </p>
                    {(snapshot.creator_notes || snapshot.retention_notes) && (
                      <p>
                        Notes:{" "}
                        {[snapshot.creator_notes, snapshot.retention_notes]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}

          {feedback.experiment_outcomes.length > 0 && (
            <details className="rounded border border-white/10 p-3">
              <summary className="cursor-pointer font-semibold text-white">
                Experiment outcome reviews
              </summary>
              <div className="mt-2 space-y-2">
                {feedback.experiment_outcomes.map((outcome) => (
                  <div key={outcome.outcome_id}>
                    <p className="font-semibold text-emerald-100">
                      {outcome.experiment_id} ·{" "}
                      {outcome.outcome_label.replace(/_/g, " ")} ·{" "}
                      {formatPercent(outcome.confidence)}
                    </p>
                    <p>
                      Worked: {outcome.what_worked.join("; ") || "Not established"}
                    </p>
                    <p>
                      Failed: {outcome.what_failed.join("; ") || "Not established"}
                    </p>
                    <p>
                      Learning targets:{" "}
                      {outcome.learning_targets.join(", ") || "None"}
                    </p>
                  </div>
                ))}
              </div>
            </details>
          )}

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Pattern summary and uncertainty
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Repeated winners:{" "}
                {feedback.pattern_summary.repeated_winners.join("; ") ||
                  "Not enough repeated evidence"}
              </p>
              <p>
                Repeated failures:{" "}
                {feedback.pattern_summary.repeated_failures.join("; ") ||
                  "Not enough repeated evidence"}
              </p>
              <p>
                Positive patterns:{" "}
                {feedback.pattern_summary.strongest_positive_patterns
                  .map((factor) => factor.summary)
                  .join("; ") || "Not established"}
              </p>
              <p>
                Negative patterns:{" "}
                {feedback.pattern_summary.strongest_negative_patterns
                  .map((factor) => factor.summary)
                  .join("; ") || "Not established"}
              </p>
              <p>
                Contradictions:{" "}
                {feedback.pattern_summary.contradictions.join("; ") || "None"}
              </p>
              <p>
                Risky conclusions:{" "}
                {feedback.pattern_summary.risky_conclusions.join("; ") || "None"}
              </p>
            </div>
          </details>

          <details className="rounded border border-white/10 p-3">
            <summary className="cursor-pointer font-semibold text-white">
              Advisory learning handoff
            </summary>
            <div className="mt-2 space-y-1">
              <p>
                Creator learning:{" "}
                {feedback.learning_handoff.creator_learning_updates.join("; ") ||
                  "No update proposed"}
              </p>
              <p>
                Approval/rejection:{" "}
                {feedback.learning_handoff.approval_rejection_updates.join(
                  "; ",
                ) || "No update proposed"}
              </p>
              <p>
                Ranking:{" "}
                {feedback.learning_handoff.ranking_guidance.join("; ") ||
                  "No guidance proposed"}
              </p>
              <p>
                Editorial:{" "}
                {feedback.learning_handoff.editorial_guidance.join("; ") ||
                  "No guidance proposed"}
              </p>
              <p>
                Hook/retention:{" "}
                {feedback.learning_handoff.hook_retention_guidance.join("; ") ||
                  "No guidance proposed"}
              </p>
              <p>
                Caption/motion:{" "}
                {feedback.learning_handoff.caption_motion_guidance.join("; ") ||
                  "No guidance proposed"}
              </p>
              <p>
                Music mood:{" "}
                {feedback.learning_handoff.music_mood_guidance.join("; ") ||
                  "No guidance proposed"}
              </p>
            </div>
          </details>

          {(feedback.warnings.length > 0 ||
            feedback.limitations.length > 0) && (
            <p className="text-amber-100">
              Review:{" "}
              {[...feedback.warnings, ...feedback.limitations]
                .slice(0, 6)
                .join("; ")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

const creatorLearningTargetTypes: BobaCreatorFeedbackTargetType[] = [
  "project",
  "clip",
  "candidate",
  "ranked_clip",
  "editorial_decision",
  "explanation",
  "creative_direction",
  "clip_brief",
  "hook_alternative",
  "caption_motion",
  "music_mood",
];

function BobaCreatorLearningPanel({
  projectId,
  creatorId,
}: {
  projectId: string;
  creatorId?: string;
}) {
  const learningQuery = useBobaCreatorLearning(projectId);
  const recordEvent = useRecordBobaCreatorLearningEvent(projectId);
  const generateLearning = useGenerateBobaCreatorLearning(projectId);
  const exportLearning = useExportBobaCreatorLearning(projectId);
  const resetLearning = useResetBobaCreatorLearning(projectId);
  const [targetType, setTargetType] =
    useState<BobaCreatorFeedbackTargetType>("project");
  const [targetId, setTargetId] = useState(projectId);
  const [note, setNote] = useState("");
  const [tags, setTags] = useState("");
  const [rating, setRating] = useState("5");
  const [status, setStatus] = useState("");
  const learning = learningQuery.data;
  const busy =
    recordEvent.isPending ||
    generateLearning.isPending ||
    exportLearning.isPending ||
    resetLearning.isPending;

  function parsedTags() {
    return tags
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean)
      .slice(0, 24);
  }

  function submitEvent(
    eventType: BobaCreatorFeedbackEventInput["event_type"],
    userAction: BobaCreatorFeedbackEventInput["user_action"],
    eventRating?: number,
  ) {
    if (!targetId.trim()) {
      setStatus("Choose a target ID before recording feedback.");
      return;
    }
    if (
      (eventType === "preference_note" || eventType === "correction") &&
      !note.trim()
    ) {
      setStatus("Add a short explicit note first.");
      return;
    }
    if (eventType === "manual_tag" && parsedTags().length === 0) {
      setStatus("Add at least one explicit preference tag first.");
      return;
    }
    setStatus("");
    recordEvent.mutate(
      {
        event_type: eventType,
        target_type: targetType,
        target_id: targetId.trim(),
        user_action: userAction,
        rating: eventRating,
        note: note.trim(),
        tags: parsedTags(),
        reversible: true,
      },
      {
        onSuccess: (event) => {
          setStatus(
            `Recorded ${event.event_type.replace(/_/g, " ")} feedback. Generate the profile when ready.`,
          );
          setNote("");
          setTags("");
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function generate(dryRun: boolean) {
    setStatus("");
    generateLearning.mutate(
      {
        creator_id: creatorId ?? "local_creator",
        dry_run: dryRun,
      },
      {
        onSuccess: (result) =>
          setStatus(
            dryRun
              ? `Dry run complete at ${formatPercent(result.learning_profile.confidence)} confidence; nothing was saved.`
              : `Creator learning updated from ${result.audit_summary.total_events} explicit event(s).`,
          ),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function downloadExport() {
    setStatus("");
    exportLearning.mutate(undefined, {
      onSuccess: (payload) => {
        const blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `boba_creator_learning_${projectId}.json`;
        link.click();
        URL.revokeObjectURL(url);
        setStatus("Safe creator-learning export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's creator-learning profile and explicit event log? Other BOBA memory is preserved.",
      )
    ) {
      return;
    }
    setStatus("");
    resetLearning.mutate(undefined, {
      onSuccess: () => setStatus("Project creator learning reset; other BOBA memory remains."),
      onError: (error) => setStatus(error.message),
    });
  }

  const preferred = learning
    ? [
        ...learning.learning_profile.preferred_clip_types,
        ...learning.learning_profile.preferred_hook_styles,
        ...learning.learning_profile.preferred_caption_styles,
        ...learning.learning_profile.preferred_motion_styles,
        ...learning.learning_profile.preferred_music_moods,
      ]
    : [];
  const avoided = learning
    ? [
        ...learning.learning_profile.avoided_clip_types,
        ...learning.learning_profile.avoided_hook_styles,
        ...learning.learning_profile.avoided_caption_styles,
        ...learning.learning_profile.avoided_motion_styles,
        ...learning.learning_profile.avoided_music_moods,
      ]
    : [];

  return (
    <div className="mt-4 border-t border-cyan-300/15 pt-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">Creator Learning Loop</p>
          <p className="text-xs text-cyan-100">
            BOBA learns only from feedback you submit.
          </p>
          <p className="text-[11px] text-muted">
            Guidance remains advisory and is never applied automatically.
          </p>
        </div>
        <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted">
          {learning
            ? `${learning.audit_summary.total_events} event(s) · ${formatPercent(learning.learning_profile.confidence)} confidence`
            : "Not generated"}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <select
          value={targetType}
          onChange={(event) =>
            setTargetType(event.target.value as BobaCreatorFeedbackTargetType)
          }
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white"
        >
          {creatorLearningTargetTypes.map((value) => (
            <option key={value} value={value}>
              {value.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <input
          value={targetId}
          maxLength={180}
          onChange={(event) => setTargetId(event.target.value)}
          placeholder="Target ID"
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
        />
        <select
          value={rating}
          onChange={(event) => setRating(event.target.value)}
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white"
        >
          {[5, 4, 3, 2, 1].map((value) => (
            <option key={value} value={value}>
              Rating {value}/5
            </option>
          ))}
        </select>
        <input
          value={note}
          maxLength={500}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Explicit preference note or correction"
          className="sm:col-span-2 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
        />
        <input
          value={tags}
          maxLength={500}
          onChange={(event) => setTags(event.target.value)}
          placeholder="Tags, e.g. hook_style:curiosity_gap"
          className="rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
        />
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        <button type="button" disabled={busy} onClick={() => submitEvent("approval", "approved")} className="rounded border border-emerald-300/30 px-2 py-1 text-[11px] text-emerald-100 disabled:opacity-50">Record approval</button>
        <button type="button" disabled={busy} onClick={() => submitEvent("rejection", "rejected")} className="rounded border border-rose-300/30 px-2 py-1 text-[11px] text-rose-100 disabled:opacity-50">Record rejection</button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            const numericRating = Number(rating);
            submitEvent(
              "rating",
              numericRating >= 4 ? "liked" : numericRating <= 2 ? "disliked" : "noted",
              numericRating,
            );
          }}
          className="rounded border border-white/10 px-2 py-1 text-[11px] text-white disabled:opacity-50"
        >
          Record rating
        </button>
        <button type="button" disabled={busy || !note.trim()} onClick={() => submitEvent("preference_note", "noted")} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white disabled:opacity-50">Save note</button>
        <button type="button" disabled={busy || !note.trim()} onClick={() => submitEvent("correction", "corrected")} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white disabled:opacity-50">Save correction</button>
        <button type="button" disabled={busy || parsedTags().length === 0} onClick={() => submitEvent("manual_tag", "tagged")} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white disabled:opacity-50">Save tags</button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <button type="button" disabled={busy} onClick={() => generate(false)} className="rounded bg-cyan-300/15 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50">Update learning profile</button>
        <button type="button" disabled={busy} onClick={() => generate(true)} className="rounded border border-white/10 px-2.5 py-1.5 text-[11px] text-muted disabled:opacity-50">Dry run</button>
        <button type="button" disabled={busy || !learning} onClick={downloadExport} className="rounded border border-white/10 px-2.5 py-1.5 text-[11px] text-muted disabled:opacity-50">Export</button>
        <button type="button" disabled={busy || !learning} onClick={reset} className="rounded border border-rose-300/20 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50">Reset project learning</button>
      </div>

      {learning && (
        <details className="mt-3 rounded-lg border border-white/10 bg-black/10 p-3 text-xs text-muted">
          <summary className="cursor-pointer font-semibold text-white">
            Learned preferences and advisory guidance
          </summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <p>Preferred: {preferred.slice(0, 8).join(", ") || "Not enough evidence"}</p>
            <p>Avoided: {avoided.slice(0, 8).join(", ") || "Not enough evidence"}</p>
            <p className="sm:col-span-2">
              Repeated feedback: {learning.learning_profile.repeated_feedback.slice(0, 4).join("; ") || "None yet"}
            </p>
            <p className="sm:col-span-2">
              Guidance: {learning.recommendation_guidance.general_guidance.slice(0, 4).join("; ")}
            </p>
            <p>
              Audit: {learning.audit_summary.approval_count} approval(s), {learning.audit_summary.rejection_count} rejection(s), {learning.audit_summary.correction_count} correction(s)
            </p>
            <p>
              Automatic application: {learning.recommendation_guidance.apply_automatically ? "Enabled" : "Disabled"}
            </p>
            {(learning.warnings.length > 0 || learning.learning_profile.warnings.length > 0) && (
              <p className="sm:col-span-2 text-amber-100">
                Review: {[...learning.warnings, ...learning.learning_profile.warnings].slice(0, 4).join("; ")}
              </p>
            )}
          </div>
        </details>
      )}
      {status && <p className="mt-2 text-[11px] text-cyan-100">{status}</p>}
    </div>
  );
}

function BobaApprovalRejectionLearningPanel({
  projectId,
  creatorId,
}: {
  projectId: string;
  creatorId?: string;
}) {
  const learningQuery = useBobaApprovalRejectionLearning(projectId);
  const generateLearning = useGenerateBobaApprovalRejectionLearning(projectId);
  const exportLearning = useExportBobaApprovalRejectionLearning(projectId);
  const resetLearning = useResetBobaApprovalRejectionLearning(projectId);
  const [status, setStatus] = useState("");
  const learning = learningQuery.data;
  const busy =
    generateLearning.isPending ||
    exportLearning.isPending ||
    resetLearning.isPending;

  function generate(dryRun: boolean) {
    setStatus("");
    generateLearning.mutate(
      {
        creator_id: creatorId ?? "local_creator",
        dry_run: dryRun,
      },
      {
        onSuccess: (result) =>
          setStatus(
            dryRun
              ? `Dry run analyzed ${result.audit_summary.total_feedback_events_used} explicit event(s); nothing was saved.`
              : `Decision learning updated with ${result.approval_cases.length} approval and ${result.rejection_cases.length} rejection case(s).`,
          ),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function downloadExport() {
    setStatus("");
    exportLearning.mutate(undefined, {
      onSuccess: (payload) => {
        const blob = new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `boba_approval_rejection_learning_${projectId}.json`;
        link.click();
        URL.revokeObjectURL(url);
        setStatus("Safe approval/rejection learning export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset approval/rejection analysis only? Creator Learning events, profiles, and BOBA Memory are preserved.",
      )
    ) {
      return;
    }
    setStatus("");
    resetLearning.mutate(undefined, {
      onSuccess: () =>
        setStatus(
          "Approval/rejection analysis reset; Creator Learning and Memory remain.",
        ),
      onError: (error) => setStatus(error.message),
    });
  }

  const moduleGuidance = learning
    ? [
        ...learning.module_guidance.ranking_guidance,
        ...learning.module_guidance.editorial_guidance,
        ...learning.module_guidance.creative_director_guidance,
        ...learning.module_guidance.clip_brief_guidance,
        ...learning.module_guidance.hook_retention_guidance,
        ...learning.module_guidance.caption_motion_guidance,
        ...learning.module_guidance.music_mood_guidance,
        ...learning.module_guidance.explanation_guidance,
        ...learning.module_guidance.general_guidance,
      ]
    : [];

  return (
    <div className="mt-4 border-t border-cyan-300/15 pt-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">
            Approval / Rejection Learning
          </p>
          <p className="text-xs text-cyan-100">
            BOBA learns only from feedback you submit. Guidance is advisory unless
            you approve applying it.
          </p>
          <p className="text-[11px] text-muted">
            This analyzes saved explicit events; it does not collect hidden behavior.
          </p>
        </div>
        <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted">
          {learning
            ? `${learning.approval_cases.length} approved · ${learning.rejection_cases.length} rejected`
            : "Not generated"}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={() => generate(false)}
          className="rounded bg-cyan-300/15 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50"
        >
          Analyze decisions
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => generate(true)}
          className="rounded border border-white/10 px-2.5 py-1.5 text-[11px] text-muted disabled:opacity-50"
        >
          Dry run
        </button>
        <button
          type="button"
          disabled={busy || !learning}
          onClick={downloadExport}
          className="rounded border border-white/10 px-2.5 py-1.5 text-[11px] text-muted disabled:opacity-50"
        >
          Export
        </button>
        <button
          type="button"
          disabled={busy || !learning}
          onClick={reset}
          className="rounded border border-rose-300/20 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
        >
          Reset analysis
        </button>
      </div>

      {learning && (
        <details className="mt-3 rounded-lg border border-white/10 bg-black/10 p-3 text-xs text-muted">
          <summary className="cursor-pointer font-semibold text-white">
            Decision cases, patterns, and advisory guidance
          </summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <p>
              What BOBA got right:{" "}
              {learning.approval_cases
                .flatMap((item) => item.what_boba_got_right)
                .slice(0, 3)
                .join("; ") || "Not enough evidence"}
            </p>
            <p>
              What BOBA got wrong:{" "}
              {learning.rejection_cases
                .flatMap((item) => item.what_boba_got_wrong)
                .slice(0, 3)
                .join("; ") || "Not enough evidence"}
            </p>
            <p>
              Attribution:{" "}
              {learning.decision_attributions
                .slice(0, 4)
                .map(
                  (item) =>
                    `${item.primary_module.replace(/_/g, " ")} (${formatPercent(item.confidence)})`,
                )
                .join("; ") || "Not available"}
            </p>
            <p>
              Corrections:{" "}
              {learning.rejection_cases
                .flatMap((item) => item.correction_mapping)
                .slice(0, 3)
                .map((item) => item.suggested_correction)
                .join("; ") || "None"}
            </p>
            <p className="sm:col-span-2">
              Patterns:{" "}
              {learning.pattern_scores
                .slice(0, 5)
                .map(
                  (item) =>
                    `${item.pattern_type.replace(/_/g, " ")}: ${item.summary}`,
                )
                .join("; ") || "Not enough repeated evidence"}
            </p>
            <p className="sm:col-span-2">
              Module guidance: {moduleGuidance.slice(0, 5).join("; ") || "None yet"}
            </p>
            <p>
              Attributed / unknown: {learning.audit_summary.attributed_cases} /{" "}
              {learning.audit_summary.unattributed_cases}
            </p>
            <p>
              Automatic application:{" "}
              {learning.module_guidance.apply_automatically
                ? "Enabled"
                : "Disabled"}
            </p>
            {(learning.warnings.length > 0 ||
              learning.audit_summary.warnings.length > 0) && (
              <p className="sm:col-span-2 text-amber-100">
                Review:{" "}
                {[
                  ...learning.warnings,
                  ...learning.audit_summary.warnings,
                ]
                  .slice(0, 4)
                  .join("; ")}
              </p>
            )}
          </div>
        </details>
      )}
      {status && <p className="mt-2 text-[11px] text-cyan-100">{status}</p>}
    </div>
  );
}

function BobaMemoryPanel({
  projectId,
  creatorId,
  projectMemory,
  creatorMemory,
}: {
  projectId: string;
  creatorId?: string;
  projectMemory: BobaProjectMemoryV1 | null | undefined;
  creatorMemory: BobaCreatorMemoryV1 | null | undefined;
}) {
  return (
    <section className="rounded-xl border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Memory</p>
          <p className="text-xs text-muted">
            Local, explicit, bounded memory. No cloud sync or passive learning.
          </p>
        </div>
        <span className="rounded bg-cyan-300/10 px-2 py-1 text-[11px] text-cyan-100">
          {projectMemory ? `${projectMemory.memory_records.length} project record(s)` : "Not available"}
        </span>
      </div>
      {projectMemory ? (
        <div className="mt-3 grid gap-2 text-xs text-muted sm:grid-cols-2">
          <p className="sm:col-span-2">What BOBA remembers: {projectMemory.source_summary || "Not available"}</p>
          <p>Selected / rejected: {projectMemory.selected_clip_ids.length} / {projectMemory.rejected_clip_ids.length}</p>
          <p>Used source ranges: {projectMemory.used_source_ranges.length}</p>
          <p className="sm:col-span-2">
            Unused opportunities: {projectMemory.unused_opportunities.slice(0, 3).join("; ") || "Not available"}
          </p>
          {projectMemory.known_limitations.length > 0 && (
            <p className="sm:col-span-2 text-amber-100">
              Known limitations: {projectMemory.known_limitations.slice(0, 3).join("; ")}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">Project Memory Summary is not available.</p>
      )}
      <div className="mt-3 border-t border-white/10 pt-3 text-xs text-muted">
        <p className="font-semibold text-white">Creator memory</p>
        {creatorMemory ? (
          <>
            <p className="mt-1">{creatorMemory.style_summary || "No style summary is available."}</p>
            <p className="mt-1">
              Learned preferences: {creatorMemory.preferred_clip_traits.slice(0, 4).join(", ") || "Not available"}
            </p>
            <p>
              Avoided patterns: {creatorMemory.known_bad_patterns.slice(0, 4).join(", ") || "Not available"}
            </p>
            <p>
              {creatorMemory.feedback_count} explicit feedback item(s) · {formatPercent(creatorMemory.confidence)} confidence · Reset/export available through local memory API
            </p>
          </>
        ) : (
          <p className="mt-1">Creator memory is not available.</p>
        )}
      </div>
      <BobaCreatorLearningPanel projectId={projectId} creatorId={creatorId} />
      <BobaApprovalRejectionLearningPanel
        projectId={projectId}
        creatorId={creatorId}
      />
    </section>
  );
}

function BobaBrainPanel({ brain }: { brain: BobaBrainStateV1 | null | undefined }) {
  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Brain Summary</p>
          <p className="text-xs text-muted">
            BOBA observes and advises; existing Olympus engines still make and execute decisions.
          </p>
        </div>
        <span className="rounded bg-violet-300/10 px-2 py-1 text-[11px] text-violet-100">
          Mode: {brain?.mode?.replace(/_/g, " ") ?? "Not available"}
        </span>
      </div>
      {brain ? (
        <div className="mt-3 grid gap-2 text-xs text-muted sm:grid-cols-2">
          <p>
            BOBA confidence: {formatPercent(brain.confidence)} · Niche: {brain.decision_context.content_niche}
          </p>
          <p>
            Ready: planning {brain.result.ready_for_planning ? "yes" : "no"}, editing {brain.result.ready_for_editing ? "yes" : "no"}, rendering {brain.result.ready_for_rendering ? "yes" : "no"}
          </p>
          <p className="sm:col-span-2">
            BOBA noticed: {brain.project_memory_summary.main_topics.slice(0, 4).join(", ") || "No bounded topic summary is available."}
          </p>
          <p className="sm:col-span-2">
            Missing signals: {brain.source_understanding.missing_signals.join(", ") || "None reported"}
          </p>
          {(brain.result.blockers.length > 0 || brain.result.warnings.length > 0) && (
            <p className="sm:col-span-2 text-amber-100">
              Warning: {[...brain.result.blockers, ...brain.result.warnings].slice(0, 3).join("; ")}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted">BOBA project reasoning is not available.</p>
      )}
    </section>
  );
}

function BobaScoutCreativePanel({ projectId }: { projectId: string }) {
  const candidatesQuery = useBobaCandidates();
  const briefsQuery = useBobaCreativeBriefs(projectId);
  const scoreCandidate = useScoreBobaCandidate();
  const decideCandidate = useDecideBobaCandidate();
  const generateBriefs = useGenerateBobaCreativeBriefs(projectId);
  const decideBrief = useDecideBobaCreativeBrief(projectId);
  const candidates = candidatesQuery.data?.candidates ?? [];
  const scores = candidatesQuery.data?.scores ?? {};
  const briefs = briefsQuery.data?.briefs ?? [];
  const candidateBusy = scoreCandidate.isPending || decideCandidate.isPending;

  return (
    <section className="rounded-xl border border-fuchsia-300/20 bg-fuchsia-300/[0.04] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Scout + Creative Director</p>
          <p className="text-xs text-muted">
            Metadata-only ideas, explicit approvals, and advisory clip briefs. No download or processing is triggered here.
          </p>
        </div>
        <button
          type="button"
          disabled={generateBriefs.isPending}
          onClick={() => generateBriefs.mutate()}
          className="rounded border border-fuchsia-200/30 px-2 py-1 text-[11px] text-fuchsia-100 hover:border-fuchsia-100 disabled:opacity-50"
        >
          {generateBriefs.isPending ? "Generating…" : "Generate clip briefs"}
        </button>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-fuchsia-100">Scout candidates</p>
          {candidates.length === 0 ? (
            <p className="mt-2 text-xs text-muted">No manually supplied candidate ideas are available.</p>
          ) : (
            <div className="mt-2 space-y-2">
              {candidates.slice(0, 6).map((candidate) => {
                const score = scores[candidate.candidate_id];
                return (
                  <article key={candidate.candidate_id} className="rounded border border-white/10 p-3 text-xs text-muted">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold text-white">{candidate.title}</p>
                        <p>
                          {candidate.status.replace(/_/g, " ")} · rights {candidate.rights_status.replace(/_/g, " ")}
                        </p>
                      </div>
                      <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-white">
                        {score ? `${Math.round(score.overall_score * 100)}/100` : "Not scored"}
                      </span>
                    </div>
                    {score && (
                      <div className="mt-2 space-y-1">
                        <p>Recommendation: {score.recommended_action.replace(/_/g, " ")}</p>
                        <p>{score.reasons.slice(0, 2).join(" ")}</p>
                        {score.warnings.length > 0 && (
                          <p className="text-amber-100">Warning: {score.warnings.slice(0, 2).join("; ")}</p>
                        )}
                      </div>
                    )}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button type="button" disabled={candidateBusy} onClick={() => scoreCandidate.mutate(candidate.candidate_id)} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white hover:border-white/30 disabled:opacity-50">Score</button>
                      <button type="button" disabled={candidateBusy} onClick={() => decideCandidate.mutate({ candidateId: candidate.candidate_id, decision: "approve" })} className="rounded border border-emerald-300/30 px-2 py-1 text-[11px] text-emerald-100 hover:border-emerald-200 disabled:opacity-50">Approve review</button>
                      <button type="button" disabled={candidateBusy} onClick={() => decideCandidate.mutate({ candidateId: candidate.candidate_id, decision: "reject" })} className="rounded border border-rose-300/30 px-2 py-1 text-[11px] text-rose-100 hover:border-rose-200 disabled:opacity-50">Reject</button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-fuchsia-100">Clip creative briefs</p>
          {briefs.length === 0 ? (
            <p className="mt-2 text-xs text-muted">No advisory clip briefs have been generated.</p>
          ) : (
            <div className="mt-2 space-y-2">
              {briefs.slice(0, 6).map((brief) => (
                <article key={brief.clip_id} className="rounded border border-white/10 p-3 text-xs text-muted">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="font-semibold text-white">{brief.clip_id}</p>
                    <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-white">
                      {brief.pacing_level} · {brief.recommended_duration_seconds.toFixed(1)}s
                    </span>
                  </div>
                  <p className="mt-1">Hook: {brief.hook_type.replace(/_/g, " ")} · {brief.curiosity_trigger}</p>
                  <p>Angle: {brief.story_angle}</p>
                  <p>Captions: {brief.caption_style.replace(/_/g, " ")} · Motion: {brief.motion_style.replace(/_/g, " ")}</p>
                  <p>Music mood: {brief.music_mood.replace(/_/g, " ")} (metadata only)</p>
                  <p className="mt-1">Why it may work: {brief.why_it_may_work}</p>
                  {brief.risk_warnings.length > 0 && (
                    <p className="mt-1 text-amber-100">Warning: {brief.risk_warnings.slice(0, 2).join("; ")}</p>
                  )}
                  <div className="mt-2 flex gap-2">
                    <button type="button" disabled={decideBrief.isPending} onClick={() => decideBrief.mutate({ clipId: brief.clip_id, decision: "approve" })} className="rounded border border-emerald-300/30 px-2 py-1 text-[11px] text-emerald-100 hover:border-emerald-200 disabled:opacity-50">Approve idea</button>
                    <button type="button" disabled={decideBrief.isPending} onClick={() => decideBrief.mutate({ clipId: brief.clip_id, decision: "reject" })} className="rounded border border-rose-300/30 px-2 py-1 text-[11px] text-rose-100 hover:border-rose-200 disabled:opacity-50">Reject idea</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function BobaContentScoutV2Panel({ projectId }: { projectId: string }) {
  const scoutQuery = useBobaContentScoutV2(projectId);
  const generateScout = useGenerateBobaContentScoutV2(projectId);
  const exportScout = useExportBobaContentScoutV2(projectId);
  const resetScout = useResetBobaContentScoutV2(projectId);
  const [manualJson, setManualJson] = useState("");
  const [sourceLabel, setSourceLabel] = useState("manual");
  const [status, setStatus] = useState("");
  const scout = scoutQuery.data;
  const busy =
    generateScout.isPending || exportScout.isPending || resetScout.isPending;
  const itemById = new Map(
    (scout?.scout_items ?? []).map((item) => [item.item_id, item]),
  );
  const scoreById = new Map(
    (scout?.scored_items ?? []).map((score) => [score.item_id, score]),
  );
  const queueGroups: {
    label: string;
    items: BobaScoutRecommendationV2[];
  }[] = scout
    ? [
        { label: "Review now", items: scout.review_queue.top_items },
        { label: "Backups", items: scout.review_queue.backup_items },
        {
          label: "Permission review",
          items: scout.review_queue.permission_needed_items,
        },
        { label: "Blocked", items: scout.review_queue.blocked_items },
        {
          label: "Duplicate or similar",
          items: scout.review_queue.duplicate_or_similar_items,
        },
      ]
    : [];

  function generate() {
    let manualItems: Record<string, unknown>[] = [];
    if (manualJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(manualJson);
        if (
          !Array.isArray(parsed) ||
          parsed.some(
            (item) =>
              !item || typeof item !== "object" || Array.isArray(item),
          )
        ) {
          setStatus("Manual metadata must be a JSON array of objects.");
          return;
        }
        manualItems = parsed as Record<string, unknown>[];
      } catch {
        setStatus("Manual metadata is not valid JSON.");
        return;
      }
    }
    setStatus("");
    generateScout.mutate(
      {
        manual_items: manualItems,
        source_label: sourceLabel.trim() || "manual",
      },
      {
        onSuccess: (result) => {
          setStatus(
            `Scout review saved for ${result.scout_summary.total_items} metadata item(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportScout.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-content-scout-v2-${projectId}.json`, payload);
        setStatus("Safe metadata-only scout export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's Content Scout V2 artifact only? Scout V1, learning, performance feedback, and memory remain.",
      )
    ) {
      return;
    }
    resetScout.mutate(undefined, {
      onSuccess: () => {
        setStatus("Content Scout V2 reset; other BOBA artifacts remain.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Content Scout V2
          </p>
          <p className="text-xs text-muted">
            Content Scout V2 uses local/user-provided metadata only.
          </p>
          <p className="text-xs text-muted">
            BOBA does not fetch URLs, scrape platforms, download videos, or
            confirm copyright safety.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !scout}
            onClick={exportArtifact}
            className="rounded border border-cyan-200/30 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50"
          >
            Export safe metadata
          </button>
          <button
            type="button"
            disabled={busy || !scout}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Scout V2
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[12rem_1fr_auto]">
        <label className="text-xs text-muted">
          Source label
          <input
            value={sourceLabel}
            onChange={(event) => setSourceLabel(event.target.value)}
            maxLength={160}
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <label className="text-xs text-muted">
          Manual metadata JSON array
          <textarea
            value={manualJson}
            onChange={(event) => setManualJson(event.target.value)}
            rows={3}
            placeholder='[{"title":"Possible story","description":"User-provided summary","rights_status":"unknown"}]'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="self-end rounded border border-cyan-200/30 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50"
        >
          {generateScout.isPending ? "Scoring metadata…" : "Build review queue"}
        </button>
      </div>

      {status && <p className="mt-2 text-xs text-cyan-100">{status}</p>}
      {scoutQuery.isError && (
        <p className="mt-2 text-xs text-amber-100">
          Content Scout V2 could not be loaded.
        </p>
      )}

      {!scout ? (
        <p className="mt-4 text-xs text-muted">
          No saved Content Scout V2 review is available. Add manual metadata or
          build from compatible local Scout V1 records.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 text-xs text-muted sm:grid-cols-2 lg:grid-cols-4">
            <p className="rounded border border-white/10 p-2">
              Imported: {scout.scout_summary.total_items}
            </p>
            <p className="rounded border border-white/10 p-2">
              Review now: {scout.scout_summary.review_now_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Permission review: {scout.scout_summary.permission_needed_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Blocked: {scout.scout_summary.blocked_count}
            </p>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-cyan-100">
              Imported sources
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {scout.imported_sources.map((source) => (
                <span
                  key={source.import_id}
                  className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted"
                >
                  {source.source_label} · {readableName(source.source_type)} ·{" "}
                  {source.accepted_count} accepted / {source.rejected_count} rejected
                </span>
              ))}
              {scout.imported_sources.length === 0 && (
                <span className="text-xs text-muted">
                  No local metadata source was imported.
                </span>
              )}
            </div>
          </div>

          <p className="mt-4 text-xs text-muted">
            {scout.review_queue.queue_summary}
          </p>
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            {queueGroups.map((group) => (
              <div key={group.label}>
                <p className="text-xs font-semibold uppercase tracking-wide text-cyan-100">
                  {group.label}
                </p>
                {group.items.length === 0 ? (
                  <p className="mt-2 text-xs text-muted">No items.</p>
                ) : (
                  <div className="mt-2 space-y-2">
                    {group.items.slice(0, 8).map((recommendation) => {
                      const item = itemById.get(recommendation.item_id);
                      const score = scoreById.get(recommendation.item_id);
                      return (
                        <article
                          key={`${group.label}-${recommendation.item_id}`}
                          className="rounded border border-white/10 p-3 text-xs text-muted"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div>
                              <p className="font-semibold text-white">
                                {item?.title ||
                                  item?.description ||
                                  recommendation.item_id}
                              </p>
                              <p>
                                Rights:{" "}
                                {readableName(item?.rights_status ?? "unknown")} ·{" "}
                                {readableName(recommendation.recommendation)} ·{" "}
                                {recommendation.priority}
                              </p>
                            </div>
                            <span className="rounded bg-white/5 px-2 py-1 text-white">
                              {formatPercent(
                                score?.review_priority_score ?? null,
                              )}
                            </span>
                          </div>
                          <p className="mt-1">{recommendation.reason}</p>
                          {score && (
                            <p className="mt-1">
                              Creator fit {formatPercent(score.creator_fit_score)} ·
                              hook {formatPercent(score.hook_potential_score)} ·
                              story {formatPercent(score.emotional_story_score)} ·
                              novelty {formatPercent(score.novelty_score)}
                            </p>
                          )}
                          {recommendation.suggested_short_angles.length > 0 && (
                            <div className="mt-2">
                              <p className="font-medium text-cyan-100">
                                Possible short angles
                              </p>
                              {recommendation.suggested_short_angles.map(
                                (angle) => (
                                  <p key={angle.angle_id} className="mt-1">
                                    {angle.title}: {angle.hook_direction}
                                  </p>
                                ),
                              )}
                            </div>
                          )}
                          {recommendation.warnings.length > 0 && (
                            <p className="mt-2 text-amber-100">
                              Warning:{" "}
                              {recommendation.warnings.slice(0, 2).join("; ")}
                            </p>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>

          {(scout.warnings.length > 0 || scout.limitations.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Review notes:{" "}
              {[...scout.warnings, ...scout.limitations]
                .slice(0, 4)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaResearchBrainPanel({ projectId }: { projectId: string }) {
  const researchQuery = useBobaResearchBrain(projectId);
  const generateResearch = useGenerateBobaResearchBrain(projectId);
  const exportResearch = useExportBobaResearchBrain(projectId);
  const resetResearch = useResetBobaResearchBrain(projectId);
  const [manualJson, setManualJson] = useState("");
  const [pastedText, setPastedText] = useState("");
  const [sourceLabel, setSourceLabel] = useState("manual");
  const [status, setStatus] = useState("");
  const research = researchQuery.data;
  const busy =
    generateResearch.isPending ||
    exportResearch.isPending ||
    resetResearch.isPending;
  const safetyNotes = research
    ? [
        ...research.safety_review.weak_evidence_warnings,
        ...research.safety_review.unverifiable_claim_warnings,
        ...research.safety_review.copyrighted_content_warnings,
        ...research.safety_review.sensitive_topic_warnings,
        ...research.safety_review.rights_usage_warnings,
        ...research.safety_review.blockers,
      ]
    : [];

  function generate() {
    let manualSources: Record<string, unknown>[] = [];
    if (manualJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(manualJson);
        if (
          !Array.isArray(parsed) ||
          parsed.some(
            (item) =>
              !item || typeof item !== "object" || Array.isArray(item),
          )
        ) {
          setStatus("Manual research must be a JSON array of objects.");
          return;
        }
        manualSources = parsed as Record<string, unknown>[];
      } catch {
        setStatus("Manual research is not valid JSON.");
        return;
      }
    }
    setStatus("");
    generateResearch.mutate(
      {
        manual_sources: manualSources,
        pasted_text_entries: pastedText.trim() ? [pastedText.trim()] : [],
        source_label: sourceLabel.trim() || "manual",
      },
      {
        onSuccess: (result) => {
          setStatus(
            `Research saved from ${result.research_summary.total_sources} accepted source(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportResearch.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-research-brain-v1-${projectId}.json`, payload);
        setStatus("Safe compact research export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's Research Brain V1 artifact only? Content Scout, learning, performance feedback, and memory remain.",
      )
    ) {
      return;
    }
    resetResearch.mutate(undefined, {
      onSuccess: () => {
        setStatus("Research Brain V1 reset; other BOBA artifacts remain.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Research Brain V1
          </p>
          <p className="text-xs text-muted">
            Research Brain V1 uses local/user-provided material only.
          </p>
          <p className="text-xs text-muted">
            BOBA does not fetch URLs, scrape websites, call external APIs, or
            verify real-time trends.
          </p>
          <p className="text-xs text-muted">
            Evidence snippets are bounded; human verification may still be
            required.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !research}
            onClick={exportArtifact}
            className="rounded border border-violet-200/30 px-2.5 py-1.5 text-[11px] text-violet-100 disabled:opacity-50"
          >
            Export safe research
          </button>
          <button
            type="button"
            disabled={busy || !research}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Research V1
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[10rem_1fr_1fr_auto]">
        <label className="text-xs text-muted">
          Source label
          <input
            value={sourceLabel}
            onChange={(event) => setSourceLabel(event.target.value)}
            maxLength={160}
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <label className="text-xs text-muted">
          Manual research JSON array
          <textarea
            value={manualJson}
            onChange={(event) => setManualJson(event.target.value)}
            rows={4}
            placeholder='[{"title":"Audience notes","text":"Users struggle with consistency and want a practical routine.","rights_usage_notes":"Owned notes"}]'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <label className="text-xs text-muted">
          Pasted research text
          <textarea
            value={pastedText}
            onChange={(event) => setPastedText(event.target.value)}
            rows={4}
            placeholder="Paste user-provided notes or a compact research summary."
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="self-end rounded border border-violet-200/30 px-3 py-2 text-xs text-violet-100 disabled:opacity-50"
        >
          {generateResearch.isPending
            ? "Analyzing research…"
            : "Build research brief"}
        </button>
      </div>

      {status && <p className="mt-2 text-xs text-violet-100">{status}</p>}
      {researchQuery.isError && (
        <p className="mt-2 text-xs text-amber-100">
          Research Brain V1 could not be loaded.
        </p>
      )}

      {!research ? (
        <p className="mt-4 text-xs text-muted">
          No saved Research Brain V1 artifact is available. Add local or
          user-provided research material to build one.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 text-xs text-muted sm:grid-cols-2 lg:grid-cols-4">
            <p className="rounded border border-white/10 p-2">
              Sources: {research.research_summary.total_sources}
            </p>
            <p className="rounded border border-white/10 p-2">
              Insights: {research.research_summary.total_insights}
            </p>
            <p className="rounded border border-white/10 p-2">
              Shorts ideas: {research.research_summary.total_shorts_ideas}
            </p>
            <p className="rounded border border-white/10 p-2">
              Scout auto-apply:{" "}
              {research.content_scout_handoff.apply_automatically
                ? "Enabled"
                : "No"}
            </p>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
              Imported source summary
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {research.imported_sources.map((source) => (
                <span
                  key={source.import_id}
                  className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted"
                >
                  {source.source_label} · {readableName(source.source_type)} ·{" "}
                  {source.accepted_count} accepted / {source.rejected_count}{" "}
                  rejected
                </span>
              ))}
              {research.imported_sources.length === 0 && (
                <span className="text-xs text-muted">
                  No source was accepted.
                </span>
              )}
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
                Research sources and bounded evidence
              </p>
              <div className="mt-2 space-y-2">
                {research.research_sources.slice(0, 10).map((source) => (
                  <article
                    key={source.research_source_id}
                    className="rounded border border-white/10 p-3 text-xs text-muted"
                  >
                    <p className="font-semibold text-white">{source.title}</p>
                    <p className="mt-1">{source.content_summary}</p>
                    {source.topic_tags.length > 0 && (
                      <p className="mt-1">
                        Topics: {source.topic_tags.slice(0, 6).join(", ")}
                      </p>
                    )}
                    {source.evidence_snippets.slice(0, 2).map((evidence) => (
                      <p
                        key={evidence.snippet_id}
                        className="mt-2 rounded bg-white/[0.04] p-2"
                      >
                        Evidence: {evidence.snippet}
                      </p>
                    ))}
                  </article>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
                Key insights
              </p>
              <div className="mt-2 space-y-2">
                {research.research_insights.slice(0, 12).map((insight) => (
                  <article
                    key={insight.insight_id}
                    className="rounded border border-white/10 p-3 text-xs text-muted"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-semibold text-white">
                        {readableName(insight.insight_type)}
                      </p>
                      <span>{formatPercent(insight.confidence)}</span>
                    </div>
                    <p className="mt-1">{insight.summary}</p>
                    <p className="mt-1">
                      Opportunity: {insight.content_opportunity}
                    </p>
                    {insight.human_verification_required && (
                      <p className="mt-1 text-amber-100">
                        Human verification required.
                      </p>
                    )}
                  </article>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
              Possible Shorts ideas
            </p>
            <div className="mt-2 grid gap-2 lg:grid-cols-2">
              {research.shorts_ideas.slice(0, 12).map((idea) => (
                <article
                  key={idea.idea_id}
                  className="rounded border border-white/10 p-3 text-xs text-muted"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-semibold text-white">{idea.title}</p>
                    <span>{formatPercent(idea.confidence)}</span>
                  </div>
                  <p className="mt-1">
                    {readableName(idea.format_style)} · {idea.target_viewer}
                  </p>
                  <p className="mt-1">Hook: {idea.hook_direction}</p>
                  <p className="mt-1">Why: {idea.why_it_might_work}</p>
                  <p className="mt-1 text-amber-100">Risk: {idea.risk}</p>
                </article>
              ))}
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
                Safety review
              </p>
              {safetyNotes.length > 0 ? (
                <ul className="mt-2 space-y-1 text-xs text-amber-100">
                  {safetyNotes.slice(0, 12).map((note) => (
                    <li key={note}>• {note}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-muted">
                  No specific warning was detected; human review still applies.
                </p>
              )}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
                Content Scout handoff
              </p>
              <p className="mt-2 text-xs text-muted">
                Topics:{" "}
                {research.content_scout_handoff.recommended_topics.join(", ") ||
                  "Not available"}
              </p>
              <p className="mt-1 text-xs text-muted">
                Keywords:{" "}
                {research.content_scout_handoff.recommended_keywords.join(
                  ", ",
                ) || "Not available"}
              </p>
              {research.content_scout_handoff.suggested_review_questions
                .slice(0, 4)
                .map((question) => (
                  <p key={question} className="mt-1 text-xs text-muted">
                    Review: {question}
                  </p>
                ))}
            </div>
          </div>

          {(research.warnings.length > 0 ||
            research.limitations.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Research notes:{" "}
              {[...research.warnings, ...research.limitations]
                .slice(0, 6)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaTrendTopicWatcherPanel({ projectId }: { projectId: string }) {
  const watcherQuery = useBobaTrendTopicWatcher(projectId);
  const generateWatcher = useGenerateBobaTrendTopicWatcher(projectId);
  const exportWatcher = useExportBobaTrendTopicWatcher(projectId);
  const resetWatcher = useResetBobaTrendTopicWatcher(projectId);
  const [manualJson, setManualJson] = useState("");
  const [pastedTopics, setPastedTopics] = useState("");
  const [sourceLabel, setSourceLabel] = useState("manual");
  const [status, setStatus] = useState("");
  const watcher = watcherQuery.data;
  const busy =
    generateWatcher.isPending ||
    exportWatcher.isPending ||
    resetWatcher.isPending;
  const movementGroups = watcher
    ? [
        {
          label: "Repeated topics",
          items: watcher.movement_analysis.repeated_topics,
        },
        {
          label: "New topics",
          items: watcher.movement_analysis.newly_appearing_topics,
        },
        {
          label: "Rising within provided data",
          items:
            watcher.movement_analysis.rising_topics_within_provided_data,
        },
        {
          label: "Fading within provided data",
          items:
            watcher.movement_analysis.fading_topics_within_provided_data,
        },
        {
          label: "Stable topics",
          items: watcher.movement_analysis.stable_topics,
        },
        {
          label: "Uncertain topics",
          items: watcher.movement_analysis.uncertain_topics,
        },
      ]
    : [];

  function generate() {
    let manualSnapshots: Record<string, unknown>[] = [];
    if (manualJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(manualJson);
        if (
          !Array.isArray(parsed) ||
          parsed.some(
            (item) =>
              !item || typeof item !== "object" || Array.isArray(item),
          )
        ) {
          setStatus("Manual snapshots must be a JSON array of objects.");
          return;
        }
        manualSnapshots = parsed as Record<string, unknown>[];
      } catch {
        setStatus("Manual topic snapshots are not valid JSON.");
        return;
      }
    }
    setStatus("");
    generateWatcher.mutate(
      {
        manual_snapshots: manualSnapshots,
        pasted_topic_lists: pastedTopics.trim()
          ? [pastedTopics.trim()]
          : [],
        source_label: sourceLabel.trim() || "manual",
      },
      {
        onSuccess: (result) => {
          setStatus(
            `Watcher saved ${result.watcher_summary.total_snapshots} snapshot(s) and ${result.watcher_summary.watched_topic_count} watched topic(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportWatcher.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-trend-topic-watcher-v1-${projectId}.json`, payload);
        setStatus("Safe compact topic watcher export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's Trend / Topic Watcher V1 artifact only? Research Brain, Content Scout, learning, performance feedback, and memory remain.",
      )
    ) {
      return;
    }
    resetWatcher.mutate(undefined, {
      onSuccess: () => {
        setStatus(
          "Trend / Topic Watcher V1 reset; other BOBA artifacts remain.",
        );
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-sky-300/20 bg-sky-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Trend / Topic Watcher V1
          </p>
          <p className="text-xs text-muted">
            Trend / Topic Watcher V1 uses local/user-provided topic data only.
          </p>
          <p className="text-xs text-muted">
            Movement is measured only within provided data.
          </p>
          <p className="text-xs text-muted">
            BOBA does not scrape platforms, fetch URLs, call external APIs, or verify real-time trends.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !watcher}
            onClick={exportArtifact}
            className="rounded border border-sky-200/30 px-2.5 py-1.5 text-[11px] text-sky-100 disabled:opacity-50"
          >
            Export safe watcher
          </button>
          <button
            type="button"
            disabled={busy || !watcher}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Watcher V1
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[10rem_1fr_1fr_auto]">
        <label className="text-xs text-muted">
          Source label
          <input
            value={sourceLabel}
            onChange={(event) => setSourceLabel(event.target.value)}
            maxLength={160}
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <label className="text-xs text-muted">
          Manual snapshot JSON array
          <textarea
            value={manualJson}
            onChange={(event) => setManualJson(event.target.value)}
            rows={5}
            placeholder='[{"source_label":"January","captured_at":"2026-01-01","topics":[{"topic":"creator workflow","frequency":10}]},{"source_label":"February","captured_at":"2026-02-01","topics":[{"topic":"creator workflow","frequency":18},{"topic":"story hooks"}]}]'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <label className="text-xs text-muted">
          Pasted compact topic list
          <textarea
            value={pastedTopics}
            onChange={(event) => setPastedTopics(event.target.value)}
            rows={5}
            placeholder="creator workflow, story hooks, editing tutorial"
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="self-end rounded border border-sky-200/30 px-3 py-2 text-xs text-sky-100 disabled:opacity-50"
        >
          {generateWatcher.isPending
            ? "Comparing snapshots…"
            : "Build topic watchlist"}
        </button>
      </div>

      {status && <p className="mt-2 text-xs text-sky-100">{status}</p>}
      {watcherQuery.isError && (
        <p className="mt-2 text-xs text-amber-100">
          Trend / Topic Watcher V1 could not be loaded.
        </p>
      )}

      {!watcher ? (
        <p className="mt-4 text-xs text-muted">
          No saved Trend / Topic Watcher V1 artifact is available. Add dated
          local snapshots or a compact topic list to build one.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 text-xs text-muted sm:grid-cols-2 lg:grid-cols-5">
            <p className="rounded border border-white/10 p-2">
              Snapshots: {watcher.watcher_summary.total_snapshots}
            </p>
            <p className="rounded border border-white/10 p-2">
              Topics: {watcher.watcher_summary.total_topics}
            </p>
            <p className="rounded border border-white/10 p-2">
              Watched: {watcher.watcher_summary.watched_topic_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Rising: {watcher.watcher_summary.rising_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Confidence:{" "}
              {formatPercent(watcher.confidence_review.overall_confidence)}
            </p>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
              Imported source summary
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {watcher.imported_sources.map((source) => (
                <span
                  key={source.import_id}
                  className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted"
                >
                  {source.source_label} · {readableName(source.source_type)} ·{" "}
                  {source.accepted_count} accepted / {source.rejected_count}{" "}
                  rejected
                </span>
              ))}
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                Topic snapshots
              </p>
              <div className="mt-2 space-y-2">
                {watcher.topic_snapshots.slice(0, 12).map((snapshot) => (
                  <article
                    key={snapshot.snapshot_id}
                    className="rounded border border-white/10 p-3 text-xs text-muted"
                  >
                    <p className="font-semibold text-white">
                      {snapshot.source_label} · {snapshot.captured_at}
                    </p>
                    {snapshot.platform_label && (
                      <p>Provided platform label: {snapshot.platform_label}</p>
                    )}
                    <p className="mt-1">
                      {snapshot.topics
                        .slice(0, 12)
                        .map((topic) => topic.topic)
                        .join(", ") || "No accepted topics"}
                    </p>
                  </article>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                Topic watchlist
              </p>
              <div className="mt-2 space-y-2">
                {watcher.watched_topics.slice(0, 12).map((topic) => (
                  <article
                    key={topic.watched_topic_id}
                    className="rounded border border-white/10 p-3 text-xs text-muted"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-semibold text-white">{topic.topic}</p>
                      <span>{formatPercent(topic.confidence)}</span>
                    </div>
                    <p className="mt-1">{topic.reason_for_watch}</p>
                    <p className="mt-1">
                      Creator {formatPercent(topic.creator_fit)} · Research{" "}
                      {formatPercent(topic.research_fit)} · Scout{" "}
                      {formatPercent(topic.scout_fit)}
                    </p>
                    {topic.suggested_angles.slice(0, 2).map((angle) => (
                      <p key={angle} className="mt-1">
                        Angle: {angle}
                      </p>
                    ))}
                  </article>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            {movementGroups.map((group) => (
              <div key={group.label}>
                <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                  {group.label}
                </p>
                {group.items.length === 0 ? (
                  <p className="mt-2 text-xs text-muted">No topics.</p>
                ) : (
                  <div className="mt-2 space-y-2">
                    {group.items.slice(0, 8).map((item) => (
                      <article
                        key={`${group.label}-${item.normalized_topic}`}
                        className="rounded border border-white/10 p-2 text-xs text-muted"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="font-semibold text-white">{item.topic}</p>
                          <span>{formatPercent(item.confidence)}</span>
                        </div>
                        <p className="mt-1">{item.reason}</p>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
              Topic opportunity scores
            </p>
            <div className="mt-2 grid gap-2 lg:grid-cols-2">
              {watcher.opportunity_scores.slice(0, 12).map((score) => (
                <article
                  key={score.normalized_topic}
                  className="rounded border border-white/10 p-3 text-xs text-muted"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-semibold text-white">{score.topic}</p>
                    <span>
                      {formatPercent(score.overall_topic_priority_score)}
                    </span>
                  </div>
                  <p className="mt-1">
                    Creator {formatPercent(score.creator_fit_score)} · Research{" "}
                    {formatPercent(score.research_support_score)} · Scout{" "}
                    {formatPercent(score.scout_support_score)}
                  </p>
                  <p className="mt-1">
                    Shortability {formatPercent(score.shortability_score)} · Hook{" "}
                    {formatPercent(score.hook_potential_score)} · Risk{" "}
                    {formatPercent(score.risk_score)}
                  </p>
                </article>
              ))}
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                Confidence review
              </p>
              <p className="mt-2 text-xs text-muted">
                Not real-time verified:{" "}
                {watcher.confidence_review.not_real_time_verified
                  ? "Yes"
                  : "No"}
              </p>
              {watcher.confidence_review.weak_data_warnings
                .slice(0, 6)
                .map((warning) => (
                  <p key={warning} className="mt-1 text-xs text-amber-100">
                    {warning}
                  </p>
                ))}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                Content Scout handoff
              </p>
              <p className="mt-2 text-xs text-muted">
                Topics:{" "}
                {watcher.content_scout_handoff.recommended_scout_topics.join(
                  ", ",
                ) || "Not available"}
              </p>
              <p className="mt-1 text-xs text-muted">
                Auto-apply:{" "}
                {watcher.content_scout_handoff.apply_automatically
                  ? "Enabled"
                  : "No"}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-sky-100">
                Research Brain handoff
              </p>
              <p className="mt-2 text-xs text-muted">
                Topics:{" "}
                {watcher.research_brain_handoff.recommended_research_topics.join(
                  ", ",
                ) || "Not available"}
              </p>
              {watcher.research_brain_handoff.claims_to_verify
                .slice(0, 4)
                .map((claim) => (
                  <p key={claim} className="mt-1 text-xs text-muted">
                    Verify: {claim}
                  </p>
                ))}
            </div>
          </div>

          {(watcher.warnings.length > 0 ||
            watcher.limitations.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Watcher notes:{" "}
              {[...watcher.warnings, ...watcher.limitations]
                .slice(0, 6)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaCandidateVideoScorerPanel({
  projectId,
}: {
  projectId: string;
}) {
  const scorerQuery = useBobaCandidateVideoScorer(projectId);
  const generateScorer = useGenerateBobaCandidateVideoScorer(projectId);
  const exportScorer = useExportBobaCandidateVideoScorer(projectId);
  const resetScorer = useResetBobaCandidateVideoScorer(projectId);
  const [manualJson, setManualJson] = useState("");
  const [sourceLabel, setSourceLabel] = useState("manual");
  const [status, setStatus] = useState("");
  const scorer = scorerQuery.data;
  const busy =
    generateScorer.isPending ||
    exportScorer.isPending ||
    resetScorer.isPending;
  const queueGroups = scorer
    ? [
        {
          label: "Top candidates",
          items: scorer.review_queue.top_candidates,
        },
        {
          label: "Backup candidates",
          items: scorer.review_queue.backup_candidates,
        },
        {
          label: "Permission needed",
          items: scorer.review_queue.permission_needed_candidates,
        },
        {
          label: "Blocked candidates",
          items: scorer.review_queue.blocked_candidates,
        },
        {
          label: "Duplicate / similar",
          items: scorer.review_queue.duplicate_or_similar_candidates,
        },
        {
          label: "Rejected candidates",
          items: scorer.review_queue.rejected_candidates,
        },
      ]
    : [];
  const handoffGroups = scorer
    ? [
        {
          label: "Content Scout handoff",
          handoff: scorer.source_handoffs.content_scout_handoff,
        },
        {
          label: "Research Brain handoff",
          handoff: scorer.source_handoffs.research_brain_handoff,
        },
        {
          label: "Trend Watcher handoff",
          handoff: scorer.source_handoffs.trend_topic_handoff,
        },
        {
          label: "Rights + Permission Gate handoff",
          handoff: scorer.source_handoffs.rights_permission_gate_handoff,
        },
        {
          label: "Future ingestion handoff",
          handoff: scorer.source_handoffs.future_ingestion_handoff,
        },
      ]
    : [];

  function generate() {
    let manualCandidates: Record<string, unknown>[] = [];
    if (manualJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(manualJson);
        if (
          !Array.isArray(parsed) ||
          parsed.some(
            (item) =>
              !item || typeof item !== "object" || Array.isArray(item),
          )
        ) {
          setStatus("Manual candidates must be a JSON array of objects.");
          return;
        }
        manualCandidates = parsed as Record<string, unknown>[];
      } catch {
        setStatus("Manual candidate metadata is not valid JSON.");
        return;
      }
    }
    setStatus("");
    generateScorer.mutate(
      {
        manual_candidates: manualCandidates,
        source_label: sourceLabel.trim() || "manual",
      },
      {
        onSuccess: (result) => {
          setStatus(
            `Scorer saved ${result.scorer_summary.total_candidates} candidate(s) for human review.`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportScorer.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(
          `boba-candidate-video-scorer-v1-${projectId}.json`,
          payload,
        );
        setStatus("Safe compact candidate scorer export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's Candidate Video Scorer V1 artifact only? Scout, research, trend, learning, performance, memory, and media remain untouched.",
      )
    ) {
      return;
    }
    resetScorer.mutate(undefined, {
      onSuccess: () => {
        setStatus(
          "Candidate Video Scorer V1 reset; other BOBA artifacts and media remain untouched.",
        );
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Candidate Video Scorer V1
          </p>
          <p className="text-xs text-muted">
            Candidate Video Scorer V1 uses local/user-provided metadata only.
          </p>
          <p className="text-xs text-muted">
            BOBA does not fetch URLs, scrape platforms, download videos, or confirm copyright safety.
          </p>
          <p className="text-xs text-muted">
            Human approval and rights review are required before any future ingestion.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !scorer}
            onClick={exportArtifact}
            className="rounded border border-violet-200/30 px-2.5 py-1.5 text-[11px] text-violet-100 disabled:opacity-50"
          >
            Export safe scorer
          </button>
          <button
            type="button"
            disabled={busy || !scorer}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Scorer V1
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[10rem_1fr_auto]">
        <label className="text-xs text-muted">
          Source label
          <input
            value={sourceLabel}
            onChange={(event) => setSourceLabel(event.target.value)}
            maxLength={160}
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <label className="text-xs text-muted">
          Manual candidate metadata JSON array
          <textarea
            value={manualJson}
            onChange={(event) => setManualJson(event.target.value)}
            rows={6}
            placeholder='[{"title":"How I rebuilt after failure","description":"A story with struggle, turning point, and lesson","creator":"Example creator","duration":900,"tags":["comeback","story"],"rights_status":"owned"}]'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="self-end rounded border border-violet-200/30 px-3 py-2 text-xs text-violet-100 disabled:opacity-50"
        >
          {generateScorer.isPending
            ? "Scoring candidates..."
            : "Build candidate review queue"}
        </button>
      </div>

      {status && <p className="mt-2 text-xs text-violet-100">{status}</p>}
      {scorerQuery.isError && (
        <p className="mt-2 text-xs text-amber-100">
          Candidate Video Scorer V1 could not be loaded.
        </p>
      )}

      {!scorer ? (
        <p className="mt-4 text-xs text-muted">
          No saved Candidate Video Scorer V1 artifact is available. Add local
          metadata, or build from available Scout, Research, and Trend artifacts.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 text-xs text-muted sm:grid-cols-2 lg:grid-cols-6">
            <p className="rounded border border-white/10 p-2">
              Candidates: {scorer.scorer_summary.total_candidates}
            </p>
            <p className="rounded border border-white/10 p-2">
              Review now: {scorer.scorer_summary.review_now_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Save: {scorer.scorer_summary.save_for_later_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Permission: {scorer.scorer_summary.seek_permission_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Blocked: {scorer.scorer_summary.blocked_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Rejected: {scorer.scorer_summary.rejected_count}
            </p>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
              Imported candidate sources
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {scorer.imported_sources.map((source) => (
                <span
                  key={source.import_id}
                  className="rounded bg-white/5 px-2 py-1 text-[11px] text-muted"
                >
                  {source.source_label} / {readableName(source.source_type)} /{" "}
                  {source.accepted_count} accepted / {source.rejected_count}{" "}
                  rejected
                </span>
              ))}
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
              Scored candidates
            </p>
            <div className="mt-2 grid gap-3 lg:grid-cols-2">
              {scorer.scored_candidates.slice(0, 20).map((scored) => {
                const candidate = scored.candidate_video;
                const score = scored.score;
                return (
                  <article
                    key={candidate.candidate_video_id}
                    className="rounded border border-white/10 p-3 text-xs text-muted"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-white">
                          {candidate.title || "Untitled candidate"}
                        </p>
                        <p className="mt-1">
                          {candidate.creator_or_channel || candidate.source_label}
                          {candidate.duration_seconds === null
                            ? ""
                            : ` / ${formatDuration(candidate.duration_seconds)}`}
                        </p>
                      </div>
                      <span className="rounded bg-violet-400/10 px-2 py-1 text-violet-100">
                        {formatPercent(score.overall_candidate_score)}
                      </span>
                    </div>
                    <p className="mt-2">{candidate.description}</p>
                    <p className="mt-2">
                      Creator {formatPercent(score.creator_fit_score)} / Topic{" "}
                      {formatPercent(score.topic_opportunity_score)} / Research{" "}
                      {formatPercent(score.research_support_score)} / Trend{" "}
                      {formatPercent(score.trend_support_score)}
                    </p>
                    <p className="mt-1">
                      Shortability {formatPercent(score.shortability_score)} /
                      Hook {formatPercent(score.hook_potential_score)} / Story{" "}
                      {formatPercent(score.story_potential_score)} / Format{" "}
                      {formatPercent(score.format_fit_score)}
                    </p>
                    <p className="mt-1">
                      Rights {formatPercent(score.rights_readiness_score)} / Risk{" "}
                      {formatPercent(score.risk_score)} / Review priority{" "}
                      {formatPercent(score.review_priority_score)} / Confidence{" "}
                      {formatPercent(score.confidence)}
                    </p>
                    <div className="mt-3 rounded bg-white/[0.03] p-2">
                      <p className="font-semibold text-white">
                        Recommendation:{" "}
                        {readableName(scored.recommendation.recommendation)} /{" "}
                        {readableName(scored.recommendation.priority)}
                      </p>
                      <p className="mt-1">{scored.recommendation.reason}</p>
                      <p className="mt-1">
                        Next human action:{" "}
                        {scored.recommendation.next_human_action}
                      </p>
                    </div>
                    <div className="mt-3 rounded bg-white/[0.03] p-2">
                      <p className="font-semibold text-white">
                        Shorts potential review
                      </p>
                      <p className="mt-1">
                        Possible clip types:{" "}
                        {scored.shorts_potential.possible_clip_types.join(", ") ||
                          "Not available"}
                      </p>
                      <p className="mt-1">
                        Possible hooks:{" "}
                        {scored.shorts_potential.possible_hook_directions.join(
                          ", ",
                        ) || "Not available"}
                      </p>
                      <p className="mt-1">
                        Possible story angles:{" "}
                        {scored.shorts_potential.possible_story_angles.join(
                          ", ",
                        ) || "Not available"}
                      </p>
                      <p className="mt-1">
                        Possible formats:{" "}
                        {scored.shorts_potential.possible_format_styles.join(
                          ", ",
                        ) || "Not available"}
                      </p>
                      <p className="mt-1">
                        {scored.shorts_potential.emotional_story_promise}
                      </p>
                    </div>
                    <div className="mt-3 rounded bg-white/[0.03] p-2">
                      <p className="font-semibold text-white">
                        Rights review:{" "}
                        {readableName(scored.rights_review.rights_readiness)}
                      </p>
                      <p className="mt-1">{scored.rights_review.reason}</p>
                      <p className="mt-1">
                        Review required:{" "}
                        {scored.rights_review.rights_review_required
                          ? "Yes"
                          : "No"}{" "}
                        / Permission required:{" "}
                        {scored.rights_review.permission_required ? "Yes" : "No"}
                      </p>
                    </div>
                    {scored.duplicate_of_candidate_video_id && (
                      <p className="mt-2 text-amber-100">
                        Similar to: {scored.duplicate_of_candidate_video_id}
                      </p>
                    )}
                    {[
                      ...candidate.warnings,
                      ...score.warnings,
                      ...scored.recommendation.warnings,
                    ]
                      .slice(0, 4)
                      .map((warning) => (
                        <p key={warning} className="mt-1 text-amber-100">
                          {warning}
                        </p>
                      ))}
                  </article>
                );
              })}
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
              Human review queue
            </p>
            <p className="mt-1 text-xs text-muted">
              {scorer.review_queue.queue_summary}
            </p>
            <div className="mt-2 grid gap-3 lg:grid-cols-3">
              {queueGroups.map((group) => (
                <div
                  key={group.label}
                  className="rounded border border-white/10 p-3"
                >
                  <p className="text-xs font-semibold text-white">
                    {group.label} ({group.items.length})
                  </p>
                  {group.items.length === 0 ? (
                    <p className="mt-2 text-xs text-muted">No candidates.</p>
                  ) : (
                    group.items.slice(0, 8).map((item) => (
                      <div
                        key={`${group.label}-${item.candidate_video_id}`}
                        className="mt-2 border-t border-white/10 pt-2 text-xs text-muted"
                      >
                        <p className="font-semibold text-white">
                          {item.candidate_video_id} /{" "}
                          {readableName(item.recommendation)}
                        </p>
                        <p className="mt-1">{item.reason}</p>
                        <p className="mt-1">
                          Next: {item.next_human_action}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-100">
              Advisory source handoffs
            </p>
            <div className="mt-2 grid gap-3 lg:grid-cols-3">
              {handoffGroups.map(({ label, handoff }) => (
                <div
                  key={label}
                  className="rounded border border-white/10 p-3 text-xs text-muted"
                >
                  <p className="font-semibold text-white">{label}</p>
                  <p className="mt-1">
                    Candidate IDs:{" "}
                    {handoff.candidate_video_ids.join(", ") || "Not available"}
                  </p>
                  <p className="mt-1">
                    Topics: {handoff.topics.join(", ") || "Not available"}
                  </p>
                  {handoff.recommended_actions.slice(0, 4).map((action) => (
                    <p key={action} className="mt-1">
                      Action: {action}
                    </p>
                  ))}
                  {handoff.prerequisites.slice(0, 4).map((prerequisite) => (
                    <p key={prerequisite} className="mt-1">
                      Prerequisite: {prerequisite}
                    </p>
                  ))}
                  <p className="mt-1">
                    Auto-apply:{" "}
                    {handoff.apply_automatically ? "Enabled" : "No"}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {(scorer.warnings.length > 0 ||
            scorer.limitations.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Scorer notes:{" "}
              {[...scorer.warnings, ...scorer.limitations]
                .slice(0, 8)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaRightsPermissionGatePanel({
  projectId,
}: {
  projectId: string;
}) {
  const gateQuery = useBobaRightsPermissionGate(projectId);
  const generateGate = useGenerateBobaRightsPermissionGate(projectId);
  const exportGate = useExportBobaRightsPermissionGate(projectId);
  const resetGate = useResetBobaRightsPermissionGate(projectId);
  const [manualJson, setManualJson] = useState("");
  const [sourceLabel, setSourceLabel] = useState("manual");
  const [status, setStatus] = useState("");
  const gate = gateQuery.data;
  const busy =
    generateGate.isPending || exportGate.isPending || resetGate.isPending;
  const decisionByItem = new Map(
    (gate?.gate_decisions ?? []).map((decision) => [
      decision.review_item_id,
      decision,
    ]),
  );
  const checklistByItem = new Map(
    (gate?.permission_checklists ?? []).map((checklist) => [
      checklist.review_item_id,
      checklist,
    ]),
  );
  const riskByItem = new Map(
    (gate?.risk_reviews ?? []).map((risk) => [risk.review_item_id, risk]),
  );
  const handoffByItem = new Map(
    (gate?.future_ingestion_handoffs ?? []).map((handoff) => [
      handoff.review_item_id,
      handoff,
    ]),
  );
  const reviewGroups = gate
    ? [
        {
          label: "Ready for human review",
          items: gate.reviewed_items.filter(
            (item) =>
              decisionByItem.get(item.review_item_id)?.gate_status ===
              "ready_for_human_review",
          ),
        },
        {
          label: "Permission needed",
          items: gate.reviewed_items.filter(
            (item) =>
              decisionByItem.get(item.review_item_id)?.gate_status ===
              "needs_permission",
          ),
        },
        {
          label: "Unknown rights / review needed",
          items: gate.reviewed_items.filter((item) =>
            ["needs_rights_review", "insufficient_information"].includes(
              decisionByItem.get(item.review_item_id)?.gate_status ?? "",
            ),
          ),
        },
        {
          label: "Blocked items",
          items: gate.reviewed_items.filter(
            (item) =>
              decisionByItem.get(item.review_item_id)?.gate_status ===
              "blocked",
          ),
        },
      ]
    : [];

  function generate() {
    let manualItems: Record<string, unknown>[] = [];
    if (manualJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(manualJson);
        if (
          !Array.isArray(parsed) ||
          parsed.some(
            (item) =>
              !item || typeof item !== "object" || Array.isArray(item),
          )
        ) {
          setStatus("Manual rights items must be a JSON array of objects.");
          return;
        }
        manualItems = parsed as Record<string, unknown>[];
      } catch {
        setStatus("Manual rights metadata is not valid JSON.");
        return;
      }
    }
    setStatus("");
    generateGate.mutate(
      {
        manual_items: manualItems,
        source_label: sourceLabel.trim() || "manual",
      },
      {
        onSuccess: (result) => {
          setStatus(
            `Rights Gate saved ${result.rights_summary.total_reviewed} item(s) for human review.`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportGate.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(
          `boba-rights-permission-gate-v1-${projectId}.json`,
          payload,
        );
        setStatus("Safe compact Rights Gate export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's Rights + Permission Gate V1 artifact only? Candidate Scorer, Scout, Research, Trend, Clip Briefs, Music Mood, memory, and media remain untouched.",
      )
    ) {
      return;
    }
    resetGate.mutate(undefined, {
      onSuccess: () => {
        setStatus(
          "Rights + Permission Gate V1 reset; other BOBA artifacts and media remain untouched.",
        );
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-amber-300/20 bg-amber-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">
            BOBA Rights + Permission Gate V1
          </p>
          <p className="text-xs text-muted">
            Rights + Permission Gate V1 is not legal advice.
          </p>
          <p className="text-xs text-muted">
            BOBA does not verify copyright ownership, validate licenses, fetch
            URLs, scrape platforms, or download media.
          </p>
          <p className="text-xs text-muted">
            Unknown rights are never treated as safe.
          </p>
          <p className="text-xs text-muted">
            Future ingestion requires human approval and acceptable rights
            status.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !gate}
            onClick={exportArtifact}
            className="rounded border border-amber-200/30 px-2.5 py-1.5 text-[11px] text-amber-100 disabled:opacity-50"
          >
            Export safe Rights Gate
          </button>
          <button
            type="button"
            disabled={busy || !gate}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Rights Gate V1
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[10rem_1fr_auto]">
        <label className="text-xs text-muted">
          Source label
          <input
            value={sourceLabel}
            onChange={(event) => setSourceLabel(event.target.value)}
            maxLength={160}
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <label className="text-xs text-muted">
          Manual rights metadata JSON array
          <textarea
            value={manualJson}
            onChange={(event) => setManualJson(event.target.value)}
            rows={6}
            placeholder='[{"title":"Creator-owned interview","rights_status":"owned","ownership_notes":"Recorded and owned by creator; project note ref OWN-001","platform_source_notes":"Review any guest release before processing"}]'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="self-end rounded border border-amber-200/30 px-3 py-2 text-xs text-amber-100 disabled:opacity-50"
        >
          {generateGate.isPending
            ? "Building rights review..."
            : "Build rights review gate"}
        </button>
      </div>

      {status && <p className="mt-2 text-xs text-amber-100">{status}</p>}
      {gateQuery.isError && (
        <p className="mt-2 text-xs text-amber-100">
          Rights + Permission Gate V1 could not be loaded.
        </p>
      )}

      {!gate ? (
        <p className="mt-4 text-xs text-muted">
          No saved Rights + Permission Gate V1 artifact is available. Add local
          rights metadata, or build from available Candidate Scorer, Scout,
          Research, Trend, Clip Brief, and Music Mood artifacts.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 text-xs text-muted sm:grid-cols-2 lg:grid-cols-6">
            <p className="rounded border border-white/10 p-2">
              Reviewed: {gate.rights_summary.total_reviewed}
            </p>
            <p className="rounded border border-white/10 p-2">
              Ready: {gate.rights_summary.ready_for_human_review_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Permission: {gate.rights_summary.needs_permission_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Rights review: {gate.rights_summary.needs_rights_review_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Blocked: {gate.rights_summary.blocked_count}
            </p>
            <p className="rounded border border-white/10 p-2">
              Insufficient:{" "}
              {gate.rights_summary.insufficient_information_count}
            </p>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-100">
              Rights review groups
            </p>
            <div className="mt-2 grid gap-3 lg:grid-cols-4">
              {reviewGroups.map((group) => (
                <div
                  key={group.label}
                  className="rounded border border-white/10 p-3"
                >
                  <p className="text-xs font-semibold text-white">
                    {group.label} ({group.items.length})
                  </p>
                  {group.items.length === 0 ? (
                    <p className="mt-2 text-xs text-muted">No items.</p>
                  ) : (
                    group.items.slice(0, 10).map((item) => (
                      <p
                        key={`${group.label}-${item.review_item_id}`}
                        className="mt-2 border-t border-white/10 pt-2 text-xs text-muted"
                      >
                        {item.title || item.source_label || item.review_item_id} /{" "}
                        {readableName(item.declared_rights_status)}
                      </p>
                    ))
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-100">
              Reviewed items, decisions, and advisory handoffs
            </p>
            <div className="mt-2 grid gap-3 lg:grid-cols-2">
              {gate.reviewed_items.slice(0, 30).map((item) => {
                const decision = decisionByItem.get(item.review_item_id);
                const checklist = checklistByItem.get(item.review_item_id);
                const risk = riskByItem.get(item.review_item_id);
                const handoff = handoffByItem.get(item.review_item_id);
                const activeRisks = risk
                  ? [
                      {
                        label: "Unknown rights",
                        active: risk.unknown_rights_risk,
                      },
                      {
                        label: "Third-party media",
                        active: risk.third_party_media_risk,
                      },
                      {
                        label: "Music/audio",
                        active: risk.music_audio_rights_risk,
                      },
                      {
                        label: "Platform terms",
                        active: risk.platform_terms_risk,
                      },
                      {
                        label: "People/privacy",
                        active: risk.privacy_release_risk,
                      },
                      {
                        label: "Source ambiguity",
                        active: risk.source_ambiguity_risk,
                      },
                      {
                        label: "Copyrighted source",
                        active: risk.copyrighted_source_material_risk,
                      },
                      {
                        label: "Permission evidence missing",
                        active: risk.permission_evidence_missing_risk,
                      },
                    ]
                      .filter((entry) => entry.active)
                      .map((entry) => entry.label)
                  : [];
                return (
                  <article
                    key={item.review_item_id}
                    className="rounded border border-white/10 p-3 text-xs text-muted"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-white">
                          {item.title || "Untitled rights review item"}
                        </p>
                        <p className="mt-1">
                          {item.source_label || "Unknown source"} /{" "}
                          {readableName(item.declared_rights_status)}
                        </p>
                      </div>
                      <span className="rounded bg-amber-400/10 px-2 py-1 text-amber-100">
                        {decision
                          ? readableName(decision.gate_status)
                          : "Decision unavailable"}
                      </span>
                    </div>

                    {decision && (
                      <div className="mt-3 rounded bg-white/[0.03] p-2">
                        <p className="font-semibold text-white">Gate decision</p>
                        <p className="mt-1">{decision.decision_reason}</p>
                        <p className="mt-1">
                          Human review:{" "}
                          {decision.allow_human_review ? "Allowed" : "Blocked"} /
                          Future ingestion precheck:{" "}
                          {decision.allow_future_ingestion_precheck
                            ? "Eligible"
                            : "Blocked"}{" "}
                          / Confidence: {formatPercent(decision.confidence)}
                        </p>
                        {decision.required_human_checks
                          .slice(0, 4)
                          .map((check) => (
                            <p key={check} className="mt-1">
                              Human check: {check}
                            </p>
                          ))}
                      </div>
                    )}

                    {checklist && (
                      <div className="mt-3 rounded bg-white/[0.03] p-2">
                        <p className="font-semibold text-white">
                          Permission checklist
                        </p>
                        {checklist.checklist_items.map((check) => (
                          <p key={check.item_id} className="mt-1">
                            {check.label}: {readableName(check.status)}
                            {check.required ? " / Required" : ""}
                          </p>
                        ))}
                        <p className="mt-1 text-amber-100">
                          Final human approval:{" "}
                          {checklist.final_human_approval_required
                            ? "Required"
                            : "Not required"}
                        </p>
                      </div>
                    )}

                    {risk && (
                      <div className="mt-3 rounded bg-white/[0.03] p-2">
                        <p className="font-semibold text-white">
                          Risk review:{" "}
                          {readableName(risk.overall_rights_risk)}
                        </p>
                        <p className="mt-1">
                          Active risks:{" "}
                          {activeRisks.join(", ") || "No flagged risk signals"}
                        </p>
                        {risk.blockers.slice(0, 3).map((blocker) => (
                          <p key={blocker} className="mt-1 text-rose-100">
                            Blocker: {blocker}
                          </p>
                        ))}
                        {risk.fixes.slice(0, 3).map((fix) => (
                          <p key={fix} className="mt-1">
                            Human action: {fix}
                          </p>
                        ))}
                      </div>
                    )}

                    {handoff && (
                      <div className="mt-3 rounded bg-white/[0.03] p-2">
                        <p className="font-semibold text-white">
                          Future ingestion handoff
                        </p>
                        <p className="mt-1">
                          {readableName(handoff.ingestion_precheck_status)} /
                          Next: {readableName(handoff.allowed_next_step)}
                        </p>
                        <p className="mt-1">
                          Apply automatically:{" "}
                          {handoff.apply_automatically ? "Enabled" : "No"}
                        </p>
                        {handoff.blocked_reason && (
                          <p className="mt-1 text-rose-100">
                            {handoff.blocked_reason}
                          </p>
                        )}
                        {handoff.required_before_ingestion
                          .slice(0, 4)
                          .map((requirement) => (
                            <p key={requirement} className="mt-1">
                              Required: {requirement}
                            </p>
                          ))}
                      </div>
                    )}

                    {item.evidence_snippets.length > 0 && (
                      <div className="mt-3">
                        <p className="font-semibold text-white">
                          Compact evidence notes
                        </p>
                        {item.evidence_snippets.slice(0, 4).map((evidence) => (
                          <p key={evidence.evidence_id} className="mt-1">
                            {evidence.source_artifact}.{evidence.source_field}:{" "}
                            {evidence.snippet}
                          </p>
                        ))}
                      </div>
                    )}
                    {item.missing_evidence.length > 0 && (
                      <p className="mt-2 text-amber-100">
                        Missing evidence: {item.missing_evidence.join(", ")}
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">
                Rights status breakdown
              </p>
              {Object.entries(gate.rights_summary.rights_status_breakdown).map(
                ([rightsStatus, count]) => (
                  <p key={rightsStatus} className="mt-1">
                    {readableName(rightsStatus)}: {count}
                  </p>
                ),
              )}
              <p className="mt-2">
                Common risks:{" "}
                {gate.rights_summary.common_risks.join(", ") ||
                  "No common risk summary"}
              </p>
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">
                Local signal and safety boundary
              </p>
              <p className="mt-1">
                Candidate Scorer:{" "}
                {gate.signal_usage.candidate_video_scorer_used ? "Used" : "No"} /
                Content Scout:{" "}
                {gate.signal_usage.content_scout_used ? "Used" : "No"} /
                Research:{" "}
                {gate.signal_usage.research_brain_used ? "Used" : "No"} / Trend:{" "}
                {gate.signal_usage.trend_topic_watcher_used ? "Used" : "No"}
              </p>
              <p className="mt-1">
                External API, URL fetching, scraping, downloading, media
                ingestion, and legal validation: Not used
              </p>
            </div>
          </div>

          {(gate.warnings.length > 0 || gate.limitations.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Rights Gate notes:{" "}
              {[...gate.warnings, ...gate.limitations]
                .slice(0, 10)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaAutopilotPanel({ projectId }: { projectId: string }) {
  const autopilotQuery = useBobaAutopilot(projectId);
  const createRun = useCreateBobaAutopilotRun(projectId);
  const exportController = useExportBobaAutopilot(projectId);
  const resetController = useResetBobaAutopilot(projectId);
  const controller = autopilotQuery.data;
  const run =
    controller?.runs.find((item) => item.run_id === controller.active_run_id) ??
    controller?.runs.at(-1);
  const runId = run?.run_id ?? "";
  const planNext = usePlanBobaAutopilotNext(projectId, runId);
  const advanceSafe = useAdvanceBobaAutopilotSafe(projectId, runId);
  const coordinateApproved = useCoordinateBobaAutopilotApproved(
    projectId,
    runId,
  );
  const pauseRun = usePauseBobaAutopilot(projectId, runId);
  const continueRun = useContinueBobaAutopilot(projectId, runId);
  const cancelRun = useCancelBobaAutopilot(projectId, runId);
  const humanDecision = useRecordBobaAutopilotHumanDecision(projectId, runId);
  const budgetReset = useRequestBobaAutopilotBudgetReset(projectId, runId);
  const [controlMode, setControlMode] = useState<
    "advisory_only" | "safe_read_only_automatic" | "approved_execution_coordination"
  >("safe_read_only_automatic");
  const [approvalJson, setApprovalJson] = useState("");
  const [reviewerIdentity, setReviewerIdentity] = useState("local_operator");
  const [decisionReason, setDecisionReason] = useState("");
  const [status, setStatus] = useState("");
  const actions =
    controller?.planned_actions.filter((item) => item.run_id === runId) ?? [];
  const activeAction =
    actions.find((item) => item.action_id === run?.active_action_id) ??
    [...actions]
      .reverse()
      .find((item) =>
        ["planned", "ready", "running", "awaiting_approval"].includes(
          item.status,
        ),
      );
  const budget = controller?.recovery_budgets.find(
    (item) => item.budget_id === run?.budget_id,
  );
  const usage = controller?.budget_usages.find(
    (item) => item.budget_id === run?.budget_id,
  );
  const checkpoint = controller?.checkpoint_requirements
    .filter((item) => item.run_id === runId)
    .at(-1);
  const latestDecision = controller?.decisions
    .filter((item) => item.run_id === runId)
    .at(-1);
  const nextHandoff = controller?.handoffs
    .filter((item) => item.run_id === runId)
    .at(-1);
  const incidents =
    controller?.incidents.filter((item) => item.run_id === runId).slice(-4) ??
    [];
  const events =
    controller?.event_stream.filter((item) => item.run_id === runId).slice(-8) ??
    [];
  const transitions =
    controller?.state_transitions.filter((item) => item.run_id === runId) ?? [];
  const safeActions = actions.filter(
    (item) => item.action_class === "automatic_read_only",
  );
  const approvalActions = actions.filter((item) =>
    item.action_class.startsWith("approval_required"),
  );
  const busy = [
    createRun,
    planNext,
    advanceSafe,
    coordinateApproved,
    pauseRun,
    continueRun,
    cancelRun,
    humanDecision,
    budgetReset,
    exportController,
    resetController,
  ].some((mutation) => mutation.isPending);

  function startRun() {
    setStatus("");
    createRun.mutate(
      {
        control_mode: controlMode,
        trigger: "manual",
      },
      {
        onSuccess: () =>
          setStatus("Controlled Autopilot run created. No repair was executed."),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function plan() {
    if (!runId) return;
    setStatus("");
    planNext.mutate(undefined, {
      onSuccess: () => setStatus("Next bounded controller action planned."),
      onError: (error) => setStatus(error.message),
    });
  }

  function advance() {
    if (!runId) return;
    setStatus("");
    advanceSafe.mutate(12, {
      onSuccess: () =>
        setStatus("Safe read-only steps advanced until the next required stop."),
      onError: (error) => setStatus(error.message),
    });
  }

  function coordinate() {
    if (!runId || !activeAction) return;
    let approvalRecord: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(approvalJson);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setStatus("The exact target-module approval must be one JSON object.");
        return;
      }
      approvalRecord = parsed as Record<string, unknown>;
    } catch {
      setStatus("The exact target-module approval JSON is invalid.");
      return;
    }
    setStatus("");
    coordinateApproved.mutate(
      {
        action_id: activeAction.action_id,
        approval_record: approvalRecord,
      },
      {
        onSuccess: () =>
          setStatus("Exact approved target-module action coordinated."),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportController.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-autopilot-controller-v1-${projectId}.json`, payload);
        setStatus("Safe Autopilot export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset Autopilot metadata only? Active runs must be cancelled first; upstream BOBA artifacts and outputs remain untouched.",
      )
    ) {
      return;
    }
    resetController.mutate(undefined, {
      onSuccess: () => setStatus("Autopilot metadata reset safely."),
      onError: (error) => setStatus(error.message),
    });
  }

  function decide(decision: "request_more_evidence" | "reject_proposed_action") {
    if (!runId || !reviewerIdentity.trim() || !decisionReason.trim()) {
      setStatus("Reviewer identity and a bounded decision reason are required.");
      return;
    }
    humanDecision.mutate(
      {
        decision,
        reason: decisionReason.trim(),
        reviewer_identity: reviewerIdentity.trim(),
        action_id: activeAction?.action_id,
      },
      {
        onSuccess: () => setStatus("Bounded human decision recorded."),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  return (
    <section className="rounded-xl border border-indigo-300/20 bg-indigo-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">
            BOBA Autopilot Controller V1
          </p>
          <p className="text-xs text-muted">
            BOBA Autopilot coordinates approved self-healing actions. It does
            not have unrestricted control.
          </p>
          <p className="text-xs text-muted">
            BOBA will stop for rights, safety, approval, checkpoint, budget or
            quality blocks.
          </p>
          <p className="text-xs text-amber-100">
            Autopilot completion does not mean Olympus resumed, uploaded content
            or published anything.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !controller}
            onClick={exportArtifact}
            className="rounded border border-indigo-200/30 px-2.5 py-1.5 text-[11px] text-indigo-100 disabled:opacity-50"
          >
            Export safe controller record
          </button>
          <button
            type="button"
            disabled={busy || !controller}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Autopilot metadata
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto]">
        <label className="text-xs text-muted">
          Controller mode
          <select
            value={controlMode}
            onChange={(event) =>
              setControlMode(
                event.target.value as
                  | "advisory_only"
                  | "safe_read_only_automatic"
                  | "approved_execution_coordination",
              )
            }
            disabled={Boolean(controller?.active_run_id)}
            className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
          >
            <option value="safe_read_only_automatic">
              Safe read-only automatic
            </option>
            <option value="approved_execution_coordination">
              Approved execution coordination
            </option>
            <option value="advisory_only">Advisory inspection only</option>
          </select>
        </label>
        <button
          type="button"
          disabled={busy || Boolean(controller?.active_run_id)}
          onClick={startRun}
          className="self-end rounded border border-indigo-200/30 px-3 py-2 text-xs text-indigo-100 disabled:opacity-50"
        >
          Start safe analysis
        </button>
      </div>

      {status && <p className="mt-3 text-xs text-indigo-100">{status}</p>}
      {autopilotQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Autopilot controller state could not be loaded.
        </p>
      )}

      {!run ? (
        <p className="mt-4 text-xs text-muted">
          No Autopilot run exists. Starting safe analysis creates a bounded
          snapshot and does not execute a repair.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                CURRENT STATE
              </p>
              <p className="mt-2 text-sm font-semibold text-white">
                {run.current_state.replace(/_/g, " ")}
              </p>
              <p>Status: {run.run_status.replace(/_/g, " ")}</p>
              <p>Rights: {run.rights_status.replace(/_/g, " ")}</p>
              <p>Safety: {run.safety_status.replace(/_/g, " ")}</p>
              <p>
                Snapshot:{" "}
                {controller?.project_snapshots
                  .find(
                    (item) =>
                      item.project_snapshot_id === run.project_snapshot_id,
                  )
                  ?.captured_at.slice(0, 19) ?? "Not available"}
              </p>
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                WHAT BOBA IS DOING
              </p>
              <p className="mt-2 text-white">
                {activeAction?.description ?? "No active controller action."}
              </p>
              <p>
                Module:{" "}
                {run.active_module_invocation_id
                  ? activeAction?.target_module.replace(/_/g, " ")
                  : "None"}
              </p>
              <p>
                Safe automatic actions: {safeActions.length} · Approval-required
                actions: {approvalActions.length}
              </p>
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                WHAT BOBA FINISHED
              </p>
              <p className="mt-2">
                Completed actions: {run.completed_action_ids.length}
              </p>
              <p>
                Completed states:{" "}
                {transitions
                  .filter((item) => item.transition_status === "applied")
                  .map((item) => item.to_state.replace(/_/g, " "))
                  .slice(-6)
                  .join(" → ") || "None"}
              </p>
              <p>
                Pending states/actions:{" "}
                {actions
                  .filter((item) =>
                    ["planned", "ready", "awaiting_approval"].includes(
                      item.status,
                    ),
                  )
                  .map((item) => item.action_type.replace(/_/g, " "))
                  .slice(0, 5)
                  .join(", ") || "None"}
              </p>
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                WHAT BOBA FOUND
              </p>
              <p className="mt-2">
                Incidents: {incidents.length} recent · Failed actions:{" "}
                {run.failed_action_ids.length}
              </p>
              {incidents.map((incident) => (
                <p
                  key={incident.incident_id}
                  className={incident.loop_risk ? "text-amber-100" : ""}
                >
                  {incident.title}: {incident.summary}
                </p>
              ))}
            </div>
            <div className="rounded border border-amber-300/20 bg-amber-300/[0.03] p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-amber-100/80">
                APPROVAL REQUIRED
              </p>
              <p className="mt-2">
                {activeAction?.human_approval_required
                  ? `${activeAction.target_module.replace(/_/g, " ")} · ${activeAction.target_operation.replace(/_/g, " ")}`
                  : "No exact approval is pending."}
              </p>
              <p>
                Plan:{" "}
                {String(
                  activeAction?.parameters.recovery_plan_id ??
                    activeAction?.parameters.patch_proposal_id ??
                    "Not available",
                )}
              </p>
              <p>
                Strategy:{" "}
                {String(
                  activeAction?.parameters.recovery_strategy_id ??
                    activeAction?.parameters.repair_strategy_id ??
                    "Not available",
                )}
              </p>
              <p className="mt-2 text-amber-100">
                Autopilot cannot approve this action. Complete the exact approval
                inside the target BOBA module first.
              </p>
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                RECOVERY BUDGET
              </p>
              <p className="mt-2">
                Actions: {usage?.actions_used ?? 0}/{budget?.maximum_total_actions ?? "?"}
              </p>
              <p>
                Execution: {usage?.execution_actions_used ?? 0}/
                {budget?.maximum_execution_actions ?? "?"}
              </p>
              <p>
                Retries: {usage?.retries_used ?? 0}/
                {budget?.maximum_total_retries ?? "?"}
              </p>
              <p>
                Time: {Math.round(usage?.total_duration_seconds ?? 0)}s/
                {budget?.maximum_total_duration_seconds ?? "?"}s
              </p>
              {usage?.budget_exhausted && (
                <p className="text-rose-100">
                  Exhausted: {usage.exhausted_dimensions.join(", ")}
                </p>
              )}
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                CHECKPOINT AND ROLLBACK
              </p>
              <p className="mt-2">
                Checkpoint: {checkpoint?.checkpoint_status ?? "Not available"}
              </p>
              <p>
                Validated: {checkpoint?.checkpoint_validated ? "Yes" : "No"}
              </p>
              <p>Rollback ready: {checkpoint?.rollback_ready ? "Yes" : "No"}</p>
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                QUALITY REVIEW
              </p>
              <p className="mt-2">
                {latestDecision?.decision.replace(/_/g, " ") ?? "Not available"}
              </p>
              <p>{latestDecision?.reason ?? "No quality decision is recorded."}</p>
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                WHAT HAPPENS NEXT
              </p>
              <p className="mt-2">
                {nextHandoff
                  ? `${nextHandoff.target_module.replace(/_/g, " ")}: ${nextHandoff.reason}`
                  : controller?.controller_summary.safest_next_action ||
                    "No handoff is prepared."}
              </p>
              <p>
                Human action:{" "}
                {controller?.controller_summary.next_required_human_action ||
                  "None"}
              </p>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy || !runId || run.current_state === "paused"}
              onClick={plan}
              className="rounded border border-indigo-200/30 px-3 py-2 text-xs text-indigo-100 disabled:opacity-50"
            >
              Plan next action
            </button>
            <button
              type="button"
              disabled={busy || !runId || run.current_state === "paused"}
              onClick={advance}
              className="rounded border border-sky-200/30 px-3 py-2 text-xs text-sky-100 disabled:opacity-50"
            >
              Continue safe read-only steps
            </button>
            <button
              type="button"
              disabled={busy || !runId || run.current_state === "paused"}
              onClick={() =>
                pauseRun.mutate("Human paused BOBA controller coordination.")
              }
              className="rounded border border-amber-200/30 px-3 py-2 text-xs text-amber-100 disabled:opacity-50"
            >
              Pause BOBA
            </button>
            <button
              type="button"
              disabled={busy || run.current_state !== "paused"}
              onClick={() => continueRun.mutate()}
              className="rounded border border-emerald-200/30 px-3 py-2 text-xs text-emerald-100 disabled:opacity-50"
            >
              Continue BOBA controller
            </button>
            <button
              type="button"
              disabled={busy || ["cancelled", "failed", "blocked"].includes(run.current_state)}
              onClick={() =>
                cancelRun.mutate("Human cancelled future Autopilot actions.")
              }
              className="rounded border border-rose-300/30 px-3 py-2 text-xs text-rose-100 disabled:opacity-50"
            >
              Cancel BOBA run
            </button>
          </div>

          {activeAction?.human_approval_required && (
            <details className="mt-4 rounded border border-amber-300/20 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-amber-100">
                Review required approval
              </summary>
              <textarea
                value={approvalJson}
                onChange={(event) => setApprovalJson(event.target.value)}
                rows={6}
                placeholder="Paste the exact approval record exported by Code Surgeon or Tool Recovery."
                className="mt-3 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-xs text-white"
              />
              <button
                type="button"
                disabled={busy || !approvalJson.trim()}
                onClick={coordinate}
                className="mt-2 rounded border border-amber-200/30 px-3 py-2 text-xs text-amber-100 disabled:opacity-50"
              >
                Coordinate exact approved action
              </button>
            </details>
          )}

          {run.human_review_required && (
            <details className="mt-4 rounded border border-white/10 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-white">
                Record bounded human decision
              </summary>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <input
                  value={reviewerIdentity}
                  onChange={(event) => setReviewerIdentity(event.target.value)}
                  placeholder="Reviewer identity"
                  className="rounded border border-white/10 bg-black/30 px-2.5 py-2 text-xs text-white"
                />
                <input
                  value={decisionReason}
                  onChange={(event) => setDecisionReason(event.target.value)}
                  placeholder="Bounded decision reason"
                  className="rounded border border-white/10 bg-black/30 px-2.5 py-2 text-xs text-white"
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => decide("request_more_evidence")}
                  className="rounded border border-sky-200/30 px-3 py-2 text-xs text-sky-100 disabled:opacity-50"
                >
                  Request more evidence
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => decide("reject_proposed_action")}
                  className="rounded border border-rose-300/30 px-3 py-2 text-xs text-rose-100 disabled:opacity-50"
                >
                  Reject proposed action
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    budgetReset.mutate(
                      decisionReason.trim() ||
                        "Additional bounded attempts require explicit review.",
                    )
                  }
                  className="rounded border border-amber-200/30 px-3 py-2 text-xs text-amber-100 disabled:opacity-50"
                >
                  Request budget reset review
                </button>
              </div>
            </details>
          )}

          <details className="mt-4 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              LIVE BOBA FEED
            </summary>
            <div className="mt-3 space-y-2">
              {events.length === 0 ? (
                <p className="text-xs text-muted">No controller events yet.</p>
              ) : (
                events.map((event) => (
                  <div
                    key={event.event_id}
                    className="rounded border border-white/10 p-2 text-xs text-muted"
                  >
                    <p className="text-white">{event.easy_message}</p>
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[11px] text-white/60">
                        Technical event details
                      </summary>
                      <p className="mt-1 font-mono text-[11px]">
                        #{event.sequence} · {event.event_type} ·{" "}
                        {event.technical_message}
                      </p>
                    </details>
                  </div>
                ))
              )}
            </div>
          </details>
        </>
      )}
    </section>
  );
}

function BobaObserverPanel({ projectId }: { projectId: string }) {
  const observerQuery = useBobaObserver(projectId);
  const generateObserver = useGenerateBobaObserver(projectId);
  const exportObserver = useExportBobaObserver(projectId);
  const resetObserver = useResetBobaObserver(projectId);
  const [workflowContextJson, setWorkflowContextJson] = useState("");
  const [status, setStatus] = useState("");
  const observer = observerQuery.data;
  const busy =
    generateObserver.isPending ||
    exportObserver.isPending ||
    resetObserver.isPending;

  const artifactCounts = observer
    ? {
        readable: observer.artifact_observations.filter(
          (artifact) => artifact.exists && artifact.readable,
        ).length,
        missing: observer.artifact_observations.filter(
          (artifact) => !artifact.exists,
        ).length,
        stale: observer.artifact_observations.filter(
          (artifact) => artifact.freshness_status === "stale",
        ).length,
        unreadable: observer.artifact_observations.filter(
          (artifact) => artifact.exists && !artifact.readable,
        ).length,
      }
    : null;
  const dependencyIssues =
    observer?.dependency_observations.filter(
      (dependency) => dependency.status !== "satisfied",
    ) ?? [];
  const validationGaps =
    observer?.validation_observations.filter(
      (validation) =>
        validation.latest_status !== "passed" ||
        validation.freshness_status === "stale",
    ) ?? [];
  const safeRecommendations =
    observer?.next_action_recommendations.filter(
      (recommendation) => recommendation.safe,
    ) ?? [];
  const unsafeRecommendations =
    observer?.next_action_recommendations.filter(
      (recommendation) => !recommendation.safe,
    ) ?? [];

  function generate() {
    let workflowContext: Record<string, unknown> = {};
    if (workflowContextJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(workflowContextJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setStatus("Workflow context must be a JSON object.");
          return;
        }
        workflowContext = parsed as Record<string, unknown>;
      } catch {
        setStatus("Workflow context is not valid JSON.");
        return;
      }
    }
    setStatus("");
    generateObserver.mutate(
      { workflow_context: workflowContext },
      {
        onSuccess: (result) => {
          setStatus(
            `Observer saved ${result.observer_summary.total_modules_observed} module observation(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportObserver.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-observer-v1-${projectId}.json`, payload);
        setStatus("Safe compact Observer export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's BOBA Observer V1 artifact only? All observed BOBA artifacts remain untouched.",
      )
    ) {
      return;
    }
    resetObserver.mutate(undefined, {
      onSuccess: () => {
        setStatus(
          "BOBA Observer V1 reset; all other BOBA artifacts remain untouched.",
        );
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-sky-300/20 bg-sky-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">BOBA Observer V1</p>
          <p className="text-xs text-muted">
            {
              "BOBA Observer V1 observes only. It does not fix, edit code, run validators, delete files, download media, or render."
            }
          </p>
          <p className="text-xs text-muted">
            {
              "Unsafe next actions require human review or future safety modules."
            }
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !observer}
            onClick={exportArtifact}
            className="rounded border border-sky-200/30 px-2.5 py-1.5 text-[11px] text-sky-100 disabled:opacity-50"
          >
            Export safe Observer report
          </button>
          <button
            type="button"
            disabled={busy || !observer}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Observer V1
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_auto]">
        <label className="text-xs text-muted">
          Optional current workflow context JSON
          <textarea
            value={workflowContextJson}
            onChange={(event) => setWorkflowContextJson(event.target.value)}
            rows={3}
            placeholder='{"workflow_stage":"planning","note":"Human-provided local context"}'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="self-end rounded border border-sky-200/30 px-3 py-2 text-xs text-sky-100 disabled:opacity-50"
        >
          {generateObserver.isPending
            ? "Observing saved state..."
            : "Observe saved project state"}
        </button>
      </div>

      {status && <p className="mt-3 text-xs text-sky-100">{status}</p>}

      {!observer ? (
        <p className="mt-4 text-xs text-muted">
          Observer report is not available. Generate one from saved local BOBA
          artifacts; no validator or workflow action runs automatically.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Healthy", observer.observer_summary.healthy_count],
              ["Partial", observer.observer_summary.partial_count],
              ["Missing", observer.observer_summary.missing_count],
              ["Blocked", observer.observer_summary.blocked_count],
              ["Stale", observer.observer_summary.stale_count],
              ["Warnings", observer.observer_summary.warning_count],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded border border-white/10 p-2 text-xs text-muted"
              >
                <p>{label}</p>
                <p className="mt-1 text-lg font-semibold text-white">{value}</p>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">Safest next step</p>
              <p className="mt-1">
                {observer.observer_summary.safest_next_step ||
                  "No safe next step stated"}
              </p>
            </div>
            <div className="rounded border border-rose-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-rose-100">
                Riskiest next step
              </p>
              <p className="mt-1">
                {observer.observer_summary.riskiest_next_step ||
                  "No risky next step stated"}
              </p>
            </div>
          </div>

          <details className="mt-4 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Workflow health
            </summary>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {observer.workflow_observations.map((workflow) => (
                <article
                  key={workflow.workflow_stage}
                  className="rounded border border-white/10 p-3 text-xs text-muted"
                >
                  <p className="font-semibold text-white">
                    {readableName(workflow.workflow_stage)}
                  </p>
                  <p className="mt-1">
                    Completed:{" "}
                    {workflow.completed_modules.join(", ") || "None observed"}
                  </p>
                  <p className="mt-1">
                    Ready: {workflow.ready_modules.join(", ") || "None"}
                  </p>
                  <p className="mt-1">
                    Incomplete:{" "}
                    {workflow.incomplete_modules.join(", ") || "None"}
                  </p>
                  <p className="mt-1">
                    Blocked: {workflow.blocked_modules.join(", ") || "None"}
                  </p>
                  {workflow.safe_next_actions.slice(0, 3).map((action) => (
                    <p key={action} className="mt-1 text-emerald-100">
                      Safe: {action}
                    </p>
                  ))}
                  {workflow.unsafe_next_actions.slice(0, 3).map((action) => (
                    <p key={action} className="mt-1 text-rose-100">
                      Unsafe: {action}
                    </p>
                  ))}
                </article>
              ))}
            </div>
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Module health
            </summary>
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {observer.module_health_observations.map((module) => (
                <div
                  key={module.module_name}
                  className="rounded border border-white/10 p-3 text-xs text-muted"
                >
                  <p className="font-semibold text-white">
                    {readableName(module.module_name)} /{" "}
                    {readableName(module.health_status)}
                  </p>
                  <p className="mt-1">
                    Category: {readableName(module.module_category)} /
                    Confidence:{" "}
                    {Math.round(module.confidence * 100)}%
                  </p>
                  {module.missing_inputs.length > 0 && (
                    <p className="mt-1 text-rose-100">
                      Missing inputs: {module.missing_inputs.join(", ")}
                    </p>
                  )}
                  {module.missing_outputs.length > 0 && (
                    <p className="mt-1 text-amber-100">
                      Missing outputs: {module.missing_outputs.join(", ")}
                    </p>
                  )}
                  {module.stale_outputs.length > 0 && (
                    <p className="mt-1 text-amber-100">
                      Stale outputs: {module.stale_outputs.join(", ")}
                    </p>
                  )}
                  {module.blocked_reason && (
                    <p className="mt-1 text-rose-100">
                      Blocked reason: {module.blocked_reason}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Artifact observations
            </summary>
            {artifactCounts && (
              <p className="mt-2 text-xs text-muted">
                Readable: {artifactCounts.readable} / Missing:{" "}
                {artifactCounts.missing} / Stale: {artifactCounts.stale} /
                Unreadable: {artifactCounts.unreadable}
              </p>
            )}
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {observer.artifact_observations.map((artifact) => (
                <div
                  key={artifact.artifact_id}
                  className="rounded border border-white/10 p-3 text-xs text-muted"
                >
                  <p className="font-semibold text-white">
                    {readableName(artifact.artifact_id)}
                  </p>
                  <p className="mt-1">
                    {artifact.exists ? "Exists" : "Missing"} /{" "}
                    {artifact.readable ? "Readable" : "Unreadable"} /{" "}
                    {readableName(artifact.freshness_status)} /{" "}
                    {readableName(artifact.dependency_status)}
                  </p>
                  <p className="mt-1">
                    Schema: {artifact.schema_version || "Unknown"} / Size:{" "}
                    {formatBytes(artifact.size_bytes)}
                  </p>
                  {artifact.findings.slice(0, 2).map((finding) => (
                    <p key={finding.finding_id} className="mt-1 text-amber-100">
                      {finding.message}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          </details>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <details className="rounded border border-white/10 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-white">
                Broken or stale dependencies ({dependencyIssues.length})
              </summary>
              <div className="mt-2 space-y-2 text-xs text-muted">
                {dependencyIssues.length === 0 && (
                  <p>No dependency issue observed.</p>
                )}
                {dependencyIssues.map((dependency) => (
                  <div
                    key={dependency.dependency_id}
                    className="rounded border border-white/10 p-2"
                  >
                    <p className="font-semibold text-white">
                      {readableName(dependency.upstream_module)} →{" "}
                      {readableName(dependency.downstream_module)} /{" "}
                      {readableName(dependency.status)}
                    </p>
                    <p className="mt-1">{dependency.reason}</p>
                    <p className="mt-1">
                      Inspect: {dependency.recommended_inspection}
                    </p>
                  </div>
                ))}
              </div>
            </details>

            <details className="rounded border border-white/10 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-white">
                Validation gaps ({validationGaps.length})
              </summary>
              <div className="mt-2 space-y-2 text-xs text-muted">
                {validationGaps.length === 0 && (
                  <p>No missing, stale, failed, or unknown report observed.</p>
                )}
                {validationGaps.map((validation) => (
                  <div
                    key={validation.validator_name}
                    className="rounded border border-white/10 p-2"
                  >
                    <p className="font-semibold text-white">
                      {validation.validator_name} /{" "}
                      {readableName(validation.latest_status)}
                    </p>
                    <p className="mt-1">
                      Freshness: {readableName(validation.freshness_status)}
                    </p>
                    {validation.missing_reason && (
                      <p className="mt-1 text-amber-100">
                        {validation.missing_reason}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          </div>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Safety observations
            </summary>
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {observer.safety_observations.map((safety) => (
                <div
                  key={safety.safety_id}
                  className="rounded border border-white/10 p-3 text-xs text-muted"
                >
                  <p className="font-semibold text-white">
                    {readableName(safety.safety_area)} /{" "}
                    {readableName(safety.status)}
                  </p>
                  <p className="mt-1">{safety.reason}</p>
                  {safety.required_human_checks.slice(0, 3).map((check) => (
                    <p key={check} className="mt-1 text-amber-100">
                      Human check: {check}
                    </p>
                  ))}
                  {safety.unsafe_next_actions.slice(0, 3).map((action) => (
                    <p key={action} className="mt-1 text-rose-100">
                      Unsafe: {action}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          </details>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-emerald-300/20 p-3">
              <p className="text-xs font-semibold text-emerald-100">
                Safe next actions
              </p>
              <div className="mt-2 space-y-2 text-xs text-muted">
                {safeRecommendations.length === 0 && (
                  <p>No safe recommendation stated.</p>
                )}
                {safeRecommendations.slice(0, 12).map((recommendation) => (
                  <p key={recommendation.recommendation_id}>
                    {readableName(recommendation.priority)} /{" "}
                    {recommendation.action}
                  </p>
                ))}
              </div>
            </div>
            <div className="rounded border border-rose-300/20 p-3">
              <p className="text-xs font-semibold text-rose-100">
                Unsafe next actions
              </p>
              <div className="mt-2 space-y-2 text-xs text-muted">
                {unsafeRecommendations.length === 0 && (
                  <p>No unsafe recommendation stated.</p>
                )}
                {unsafeRecommendations.slice(0, 12).map((recommendation) => (
                  <p key={recommendation.recommendation_id}>
                    {readableName(recommendation.priority)} /{" "}
                    {recommendation.action} / Human review:{" "}
                    {recommendation.human_review_required ? "Required" : "No"}
                  </p>
                ))}
              </div>
            </div>
          </div>

          {(observer.warnings.length > 0 ||
            observer.limitations.length > 0 ||
            observer.observer_summary.human_review_notes.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Observer warnings and limitations:{" "}
              {[
                ...observer.warnings,
                ...observer.limitations,
                ...observer.observer_summary.human_review_notes,
              ]
                .slice(0, 12)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaErrorDoctorPanel({ projectId }: { projectId: string }) {
  const doctorQuery = useBobaErrorDoctor(projectId);
  const generateDoctor = useGenerateBobaErrorDoctor(projectId);
  const exportDoctor = useExportBobaErrorDoctor(projectId);
  const resetDoctor = useResetBobaErrorDoctor(projectId);
  const [diagnosticContextJson, setDiagnosticContextJson] = useState("");
  const [errorSummariesText, setErrorSummariesText] = useState("");
  const [status, setStatus] = useState("");
  const doctor = doctorQuery.data;
  const busy =
    generateDoctor.isPending ||
    exportDoctor.isPending ||
    resetDoctor.isPending;

  function generate() {
    let diagnosticContext: Record<string, unknown> = {};
    if (diagnosticContextJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(diagnosticContextJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setStatus("Diagnostic context must be a JSON object.");
          return;
        }
        diagnosticContext = parsed as Record<string, unknown>;
      } catch {
        setStatus("Diagnostic context is not valid JSON.");
        return;
      }
    }
    const errorSummaries = errorSummariesText
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean)
      .slice(0, 32);
    setStatus("");
    generateDoctor.mutate(
      {
        diagnostic_context: diagnosticContext,
        error_summaries: errorSummaries,
      },
      {
        onSuccess: (result) => {
          setStatus(
            `Error Doctor saved ${result.doctor_summary.total_diagnostic_cases} diagnostic case(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportDoctor.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-error-doctor-v1-${projectId}.json`, payload);
        setStatus("Safe compact Error Doctor export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's BOBA Error Doctor V1 artifact only? Observer and all other BOBA artifacts remain untouched.",
      )
    ) {
      return;
    }
    resetDoctor.mutate(undefined, {
      onSuccess: () => {
        setStatus(
          "BOBA Error Doctor V1 reset; Observer and all other BOBA artifacts remain untouched.",
        );
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">
            BOBA Error Doctor V1
          </p>
          <p className="text-xs text-muted">
            {
              "BOBA Error Doctor V1 diagnoses Observer findings but does not fix files, edit code, run commands, run validators, or perform repairs."
            }
          </p>
          <p className="text-xs text-amber-100">
            {"A probable cause is not a proven root cause."}
          </p>
          <p className="text-xs text-amber-100">
            {
              "Human review is required before repair or destructive action."
            }
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !doctor}
            onClick={exportArtifact}
            className="rounded border border-violet-200/30 px-2.5 py-1.5 text-[11px] text-violet-100 disabled:opacity-50"
          >
            Export safe diagnosis
          </button>
          <button
            type="button"
            disabled={busy || !doctor}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Error Doctor V1
          </button>
        </div>
      </div>

      <details className="mt-4 rounded border border-white/10 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-white">
          Optional bounded diagnostic context
        </summary>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <label className="text-xs text-muted">
            Diagnostic context JSON
            <textarea
              value={diagnosticContextJson}
              onChange={(event) =>
                setDiagnosticContextJson(event.target.value)
              }
              rows={3}
              placeholder='{"module_name":"rendering","environment_issue":"Bounded local summary"}'
              className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
            />
          </label>
          <label className="text-xs text-muted">
            Bounded error summaries, one per line
            <textarea
              value={errorSummariesText}
              onChange={(event) => setErrorSummariesText(event.target.value)}
              rows={3}
              placeholder="FFmpeg returned a bounded resource error summary"
              className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
            />
          </label>
        </div>
      </details>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="rounded border border-violet-200/30 px-3 py-2 text-xs text-violet-100 disabled:opacity-50"
        >
          {generateDoctor.isPending
            ? "Diagnosing saved findings..."
            : "Diagnose saved Observer findings"}
        </button>
        <p className="text-[11px] text-muted">
          This reads a saved Observer report only. It does not generate Observer
          or run any workflow.
        </p>
      </div>

      {status && <p className="mt-3 text-xs text-violet-100">{status}</p>}
      {doctorQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Error Doctor report could not be loaded.
        </p>
      )}

      {!doctor ? (
        <p className="mt-4 text-xs text-muted">
          Error Doctor report is not available. Generate one from a saved
          Observer report; missing Observer evidence produces an honest
          insufficient-evidence diagnosis.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Cases", doctor.doctor_summary.total_diagnostic_cases],
              ["Blockers", doctor.doctor_summary.blocker_count],
              ["Critical", doctor.doctor_summary.critical_count],
              ["High", doctor.doctor_summary.high_count],
              ["Cascades", doctor.doctor_summary.cascading_problem_count],
              ["Blocked workflows", doctor.doctor_summary.blocked_workflow_count],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded border border-white/10 p-2 text-xs text-muted"
              >
                <p className="font-semibold text-white">{value}</p>
                <p>{label}</p>
              </div>
            ))}
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-violet-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">Highest priority case</p>
              <p className="mt-1">
                {doctor.doctor_summary.highest_priority_case ||
                  "No priority case stated"}
              </p>
            </div>
            <div className="rounded border border-emerald-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">
                Safest next investigation
              </p>
              <p className="mt-1">
                {doctor.doctor_summary.safest_next_investigation ||
                  "No safe investigation stated"}
              </p>
            </div>
          </div>

          <details className="mt-4 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Diagnostic cases ({doctor.diagnostic_cases.length})
            </summary>
            <div className="mt-3 space-y-3">
              {doctor.diagnostic_cases.map((diagnosticCase) => {
                const recommendations =
                  doctor.investigation_recommendations.filter(
                    (item) =>
                      item.diagnostic_case_id ===
                      diagnosticCase.diagnostic_case_id,
                  );
                const handoffs = doctor.escalation_handoffs.filter(
                  (item) =>
                    item.diagnostic_case_id ===
                    diagnosticCase.diagnostic_case_id,
                );
                return (
                  <article
                    key={diagnosticCase.diagnostic_case_id}
                    className="rounded border border-white/10 bg-black/10 p-3 text-xs text-muted"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold text-white">
                          {diagnosticCase.title}
                        </p>
                        <p className="mt-1">
                          {diagnosticCase.error_category} ·{" "}
                          {diagnosticCase.primary_module || "unknown module"} ·{" "}
                          {diagnosticCase.workflow_stage}
                        </p>
                      </div>
                      <span className="rounded border border-amber-200/30 px-2 py-1 text-[10px] uppercase text-amber-100">
                        {diagnosticCase.severity} / {diagnosticCase.urgency} /{" "}
                        {diagnosticCase.diagnosis_status}
                      </span>
                    </div>

                    <p className="mt-3">{diagnosticCase.symptom_summary}</p>
                    <p className="mt-2">
                      Affected modules:{" "}
                      <span className="text-white">
                        {diagnosticCase.affected_modules.join(", ") ||
                          "Not available"}
                      </span>
                    </p>
                    <p className="mt-1">
                      Affected artifacts:{" "}
                      <span className="text-white">
                        {diagnosticCase.affected_artifacts.join(", ") ||
                          "Not available"}
                      </span>
                    </p>
                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      <div className="rounded border border-emerald-300/15 p-2">
                        <p className="font-semibold text-emerald-100">
                          CONFIRMED FACTS
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(diagnosticCase.confirmed_facts.length
                            ? diagnosticCase.confirmed_facts
                            : ["No confirmed facts available."]).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="rounded border border-sky-300/15 p-2">
                        <p className="font-semibold text-sky-100">
                          PROBABLE EXPLANATIONS
                        </p>
                        <p className="mt-1">
                          {diagnosticCase.probable_cause_summary}
                        </p>
                      </div>
                      <div className="rounded border border-violet-300/15 p-2">
                        <p className="font-semibold text-violet-100">
                          POSSIBLE HYPOTHESES
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(diagnosticCase.hypotheses.length
                            ? diagnosticCase.hypotheses.map(
                                (item) =>
                                  `${item.hypothesis} (${formatPercent(item.confidence)})`,
                              )
                            : ["No bounded hypothesis available."]).map(
                            (item) => (
                              <li key={item}>{item}</li>
                            ),
                          )}
                        </ul>
                      </div>
                      <div className="rounded border border-amber-300/15 p-2">
                        <p className="font-semibold text-amber-100">
                          MISSING INFORMATION
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(diagnosticCase.missing_information.length
                            ? diagnosticCase.missing_information
                            : ["No additional missing information stated."]).map(
                            (item) => (
                              <li key={item}>{item}</li>
                            ),
                          )}
                        </ul>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-2 lg:grid-cols-3">
                      <p>
                        Processing impact:{" "}
                        <span className="text-white">
                          {diagnosticCase.processing_impact}
                        </span>
                      </p>
                      <p>
                        Safety impact:{" "}
                        <span className="text-white">
                          {diagnosticCase.safety_impact}
                        </span>
                      </p>
                      <p>
                        Confidence:{" "}
                        <span className="text-white">
                          {formatPercent(diagnosticCase.confidence)}
                        </span>
                      </p>
                    </div>

                    {recommendations.length > 0 && (
                      <div className="mt-3">
                        <p className="font-semibold text-white">
                          Read-only investigation recommendations
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {recommendations.map((recommendation) => (
                            <li key={recommendation.recommendation_id}>
                              {recommendation.action} ·{" "}
                              {recommendation.requires_command_execution
                                ? "future manual command may be required"
                                : "no command required by this recommendation"}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {diagnosticCase.recommended_investigation.length > 0 && (
                      <p className="mt-3">
                        Case investigation guidance:{" "}
                        {diagnosticCase.recommended_investigation.join("; ")}
                      </p>
                    )}

                    {handoffs.length > 0 && (
                      <p className="mt-3 text-amber-100">
                        Escalation target: {diagnosticCase.escalation_target}.
                        Structured handoffs:{" "}
                        {handoffs
                          .map((handoff) => handoff.target_module)
                          .join(", ")}
                        . Automatic application: No. Human approval: Required.
                      </p>
                    )}

                    {(diagnosticCase.warnings.length > 0 ||
                      diagnosticCase.limitations.length > 0) && (
                      <p className="mt-3 text-amber-100">
                        Case warnings and limitations:{" "}
                        {[
                          ...diagnosticCase.warnings,
                          ...diagnosticCase.limitations,
                        ]
                          .filter(Boolean)
                          .join("; ")}
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Cascades, evidence, and signal truth
            </summary>
            <div className="mt-3 space-y-3 text-xs text-muted">
              <div>
                <p className="font-semibold text-white">
                  Cascading impacts ({doctor.cascading_impacts.length})
                </p>
                {doctor.cascading_impacts.length > 0 ? (
                  <ul className="mt-1 list-disc space-y-1 pl-4">
                    {doctor.cascading_impacts.map((impact) => (
                      <li key={impact.cascade_id}>
                        {impact.explanation} Chain:{" "}
                        {impact.impact_chain.join(" → ") || "Not available"}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1">No cascade inferred from known chains.</p>
                )}
              </div>
              <p>
                Classified Observer findings:{" "}
                {doctor.classified_findings.length}. Observer used:{" "}
                {doctor.signal_usage.observer_used ? "Yes" : "No"}. Raw logs
                read: {doctor.signal_usage.raw_logs_read ? "Yes" : "No"}.
              </p>
              <p>
                Commands, validators, code changes, artifact changes, downloads,
                external APIs, and destructive actions: Not performed.
              </p>
            </div>
          </details>

          {(doctor.warnings.length > 0 ||
            doctor.limitations.length > 0 ||
            doctor.doctor_summary.human_review_notes.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Error Doctor warnings and limitations:{" "}
              {[
                ...doctor.warnings,
                ...doctor.limitations,
                ...doctor.doctor_summary.human_review_notes,
              ]
                .filter(Boolean)
                .slice(0, 16)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaRootCauseAnalyzerPanel({ projectId }: { projectId: string }) {
  const analyzerQuery = useBobaRootCauseAnalyzer(projectId);
  const generateAnalyzer = useGenerateBobaRootCauseAnalyzer(projectId);
  const exportAnalyzer = useExportBobaRootCauseAnalyzer(projectId);
  const resetAnalyzer = useResetBobaRootCauseAnalyzer(projectId);
  const [diagnosticContextJson, setDiagnosticContextJson] = useState("");
  const [status, setStatus] = useState("");
  const analyzer = analyzerQuery.data;
  const busy =
    generateAnalyzer.isPending ||
    exportAnalyzer.isPending ||
    resetAnalyzer.isPending;

  function generate() {
    let diagnosticContext: Record<string, unknown> = {};
    if (diagnosticContextJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(diagnosticContextJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setStatus("Diagnostic context must be a JSON object.");
          return;
        }
        diagnosticContext = parsed as Record<string, unknown>;
      } catch {
        setStatus("Diagnostic context is not valid JSON.");
        return;
      }
    }
    setStatus("");
    generateAnalyzer.mutate(
      { diagnostic_context: diagnosticContext },
      {
        onSuccess: (result) => {
          setStatus(
            `Root Cause Analyzer saved ${result.analyzer_summary.total_analysis_cases} analysis case(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportAnalyzer.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-root-cause-analyzer-v1-${projectId}.json`, payload);
        setStatus("Safe compact Root Cause Analyzer export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's BOBA Root Cause Analyzer V1 artifact only? Error Doctor, Observer, and all other BOBA artifacts remain untouched.",
      )
    ) {
      return;
    }
    resetAnalyzer.mutate(undefined, {
      onSuccess: () => {
        setStatus(
          "BOBA Root Cause Analyzer V1 reset; Error Doctor, Observer, and all other BOBA artifacts remain untouched.",
        );
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">
            BOBA Root Cause Analyzer V1
          </p>
          <p className="text-xs text-muted">
            {
              "BOBA Root Cause Analyzer V1 ranks evidence-supported causes but does not guarantee that the highest-ranked candidate is proven."
            }
          </p>
          <p className="text-xs text-amber-100">
            {
              "It does not repair files, edit code, run commands, run validators, or activate fallback tools."
            }
          </p>
          <p className="text-xs text-amber-100">
            {
              "Human approval is required before verification or repair actions."
            }
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !analyzer}
            onClick={exportArtifact}
            className="rounded border border-cyan-200/30 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50"
          >
            Export safe analysis
          </button>
          <button
            type="button"
            disabled={busy || !analyzer}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Root Cause Analyzer V1
          </button>
        </div>
      </div>

      <details className="mt-4 rounded border border-white/10 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-white">
          Optional bounded diagnostic context
        </summary>
        <label className="mt-3 block text-xs text-muted">
          Diagnostic context JSON
          <textarea
            value={diagnosticContextJson}
            onChange={(event) =>
              setDiagnosticContextJson(event.target.value)
            }
            rows={3}
            placeholder='{"conflicting_timestamps":true,"environment_issue":"Bounded local summary"}'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
      </details>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="rounded border border-cyan-200/30 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50"
        >
          {generateAnalyzer.isPending
            ? "Analyzing saved diagnoses..."
            : "Analyze saved Error Doctor report"}
        </button>
        <p className="text-[11px] text-muted">
          This reads the saved Error Doctor artifact only. It does not regenerate
          Error Doctor or Observer and does not execute verification.
        </p>
      </div>

      {status && <p className="mt-3 text-xs text-cyan-100">{status}</p>}
      {analyzerQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Root Cause Analyzer report could not be loaded.
        </p>
      )}

      {!analyzer ? (
        <p className="mt-4 text-xs text-muted">
          Root Cause Analyzer report is not available. Generate one from a saved
          Error Doctor report; missing Error Doctor evidence produces an honest
          insufficient-evidence result.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Cases", analyzer.analyzer_summary.total_analysis_cases],
              [
                "Supported",
                analyzer.analyzer_summary.supported_root_cause_count,
              ],
              [
                "Probable",
                analyzer.analyzer_summary.probable_root_cause_count,
              ],
              [
                "Competing",
                analyzer.analyzer_summary.competing_cause_count,
              ],
              [
                "Safety blocks",
                analyzer.analyzer_summary.intentional_safety_block_count,
              ],
              [
                "Blocked workflows",
                analyzer.analyzer_summary.blocked_workflow_count,
              ],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded border border-white/10 p-2 text-xs text-muted"
              >
                <p className="font-semibold text-white">{value}</p>
                <p>{label}</p>
              </div>
            ))}
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-3">
            <div className="rounded border border-cyan-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">
                Strongest ranked candidate
              </p>
              <p className="mt-1">
                {analyzer.analyzer_summary.strongest_root_cause_candidate ||
                  "Not available"}
              </p>
            </div>
            <div className="rounded border border-amber-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">Weakest evidence area</p>
              <p className="mt-1">
                {analyzer.analyzer_summary.weakest_evidence_area ||
                  "Not available"}
              </p>
            </div>
            <div className="rounded border border-emerald-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">
                Safest next verification
              </p>
              <p className="mt-1">
                {analyzer.analyzer_summary.safest_next_verification ||
                  "Not available"}
              </p>
            </div>
          </div>

          <details className="mt-4 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Root-cause analysis cases ({analyzer.analysis_cases.length})
            </summary>
            <div className="mt-3 space-y-3">
              {analyzer.analysis_cases.map((analysisCase) => {
                const candidates = analyzer.root_cause_candidates.filter(
                  (item) =>
                    item.analysis_case_id === analysisCase.analysis_case_id,
                );
                const strongest = candidates[0];
                const factors = analyzer.contributing_factors.filter(
                  (item) =>
                    item.analysis_case_id === analysisCase.analysis_case_id,
                );
                const symptoms = analyzer.downstream_symptoms.filter(
                  (item) =>
                    item.analysis_case_id === analysisCase.analysis_case_id,
                );
                const gaps = analyzer.evidence_gaps.filter(
                  (item) =>
                    item.analysis_case_id === analysisCase.analysis_case_id,
                );
                const plans = analyzer.verification_plans.filter(
                  (item) =>
                    item.analysis_case_id === analysisCase.analysis_case_id,
                );
                const timeline = analyzer.failure_timelines.find(
                  (item) =>
                    item.timeline_id === analysisCase.failure_timeline_id,
                );
                const graph = analyzer.causal_graphs.find(
                  (item) => item.causal_graph_id === analysisCase.causal_graph_id,
                );
                const impact = analyzer.workflow_impacts.find(
                  (item) =>
                    item.analysis_case_id === analysisCase.analysis_case_id,
                );
                const handoffs = analyzer.escalation_handoffs.filter(
                  (item) =>
                    item.analysis_case_id === analysisCase.analysis_case_id,
                );
                const nextCheck = plans
                  .flatMap((plan) => plan.checks)
                  .find((check) => check.safe && check.read_only);
                const nodeLabels = new Map(
                  (graph?.nodes || []).map((node) => [
                    node.node_id,
                    node.label,
                  ]),
                );
                return (
                  <article
                    key={analysisCase.analysis_case_id}
                    className="rounded border border-white/10 bg-black/10 p-3 text-xs text-muted"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold text-white">
                          {analysisCase.title}
                        </p>
                        <p className="mt-1">
                          {analysisCase.primary_module || "unknown module"} ·{" "}
                          {analysisCase.workflow_stage}
                        </p>
                      </div>
                      <span className="rounded border border-cyan-200/30 px-2 py-1 text-[10px] uppercase text-cyan-100">
                        {analysisCase.analysis_status} ·{" "}
                        {formatPercent(analysisCase.root_cause_confidence)}
                      </span>
                    </div>

                    <p className="mt-3">
                      Earliest known failure:{" "}
                      <span className="text-white">
                        {analysisCase.earliest_known_failure}
                      </span>
                    </p>
                    <p className="mt-2 rounded border border-sky-300/15 p-2">
                      Easy explanation:{" "}
                      {strongest
                        ? `The saved evidence points most strongly to ${strongest.title.toLowerCase()}, but BOBA still needs human-reviewed verification before treating it as proven.`
                        : "BOBA does not have enough saved diagnostic evidence to rank a cause yet."}
                    </p>

                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      <div className="rounded border border-emerald-300/15 p-2">
                        <p className="font-semibold text-emerald-100">
                          CONFIRMED FACTS
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(analysisCase.confirmed_facts.length
                            ? analysisCase.confirmed_facts
                            : ["No confirmed facts available."]).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="rounded border border-cyan-300/15 p-2">
                        <p className="font-semibold text-cyan-100">
                          MOST LIKELY CAUSE
                        </p>
                        <p className="mt-1">
                          {strongest?.candidate_summary ||
                            analysisCase.most_likely_root_cause}
                        </p>
                        {strongest && (
                          <p className="mt-1">
                            Likelihood {formatPercent(strongest.likelihood_score)}
                            {" · "}confidence{" "}
                            {formatPercent(strongest.confidence)}
                            {" · "}evidence {strongest.evidence_quality}
                          </p>
                        )}
                      </div>
                      <div className="rounded border border-violet-300/15 p-2">
                        <p className="font-semibold text-violet-100">
                          COMPETING EXPLANATIONS
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(candidates.length > 1
                            ? candidates
                                .slice(1)
                                .map(
                                  (item) =>
                                    `${item.candidate_summary} (${formatPercent(item.likelihood_score)})`,
                                )
                            : analysisCase.unresolved_hypotheses.length
                              ? analysisCase.unresolved_hypotheses
                              : ["No competing explanation available."]).map(
                            (item) => (
                              <li key={item}>{item}</li>
                            ),
                          )}
                        </ul>
                      </div>
                      <div className="rounded border border-indigo-300/15 p-2">
                        <p className="font-semibold text-indigo-100">
                          CONTRIBUTING FACTORS
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(factors.length
                            ? factors.map(
                                (item) =>
                                  `${item.factor_summary} Necessary: ${item.necessary_for_failure ? "Yes" : "Not established"}. Sufficient: ${item.sufficient_for_failure ? "Yes" : "Not established"}.`,
                              )
                            : ["No contributing factor established."]).map(
                            (item) => (
                              <li key={item}>{item}</li>
                            ),
                          )}
                        </ul>
                      </div>
                      <div className="rounded border border-rose-300/15 p-2">
                        <p className="font-semibold text-rose-100">
                          DOWNSTREAM EFFECTS
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(symptoms.length
                            ? symptoms.map(
                                (item) =>
                                  `${item.symptom_summary} (depth ${item.cascade_depth})`,
                              )
                            : ["No downstream effect mapped."]).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="rounded border border-amber-300/15 p-2">
                        <p className="font-semibold text-amber-100">
                          MISSING EVIDENCE
                        </p>
                        <ul className="mt-1 list-disc space-y-1 pl-4">
                          {(gaps.length
                            ? gaps.map(
                                (item) =>
                                  `${item.missing_information} — ${item.why_needed}`,
                              )
                            : ["No additional evidence gap stated."]).map(
                            (item) => (
                              <li key={item}>{item}</li>
                            ),
                          )}
                        </ul>
                      </div>
                    </div>

                    <div className="mt-3 rounded border border-emerald-300/15 p-2">
                      <p className="font-semibold text-emerald-100">
                        NEXT SAFE CHECK
                      </p>
                      <p className="mt-1">
                        {nextCheck?.description ||
                          "No safe read-only check is currently available."}
                      </p>
                      <p className="mt-1">
                        Planned only; executed: No. Human review: Required.
                      </p>
                    </div>

                    <details className="mt-3 rounded border border-white/10 p-2">
                      <summary className="cursor-pointer font-semibold text-white">
                        Failure timeline and causal chain
                      </summary>
                      <div className="mt-2 space-y-3">
                        <div>
                          <p className="font-semibold text-white">
                            Failure timeline
                          </p>
                          {timeline?.events.length ? (
                            <ol className="mt-1 list-decimal space-y-1 pl-4">
                              {timeline.events.map((event) => (
                                <li key={event.event_id}>
                                  {event.observed_at || "time unavailable"} ·{" "}
                                  {event.event_type} · {event.event_summary}
                                  {event.confirmed ? " · confirmed" : ""}
                                </li>
                              ))}
                            </ol>
                          ) : (
                            <p className="mt-1">
                              No reliable failure timeline is available.
                            </p>
                          )}
                          {timeline && (
                            <p className="mt-1">
                              Ordering confidence{" "}
                              {formatPercent(timeline.ordering_confidence)} ·
                              conflicting timestamps{" "}
                              {timeline.conflicting_timestamps ? "Yes" : "No"} ·
                              missing time information{" "}
                              {timeline.missing_time_information ? "Yes" : "No"}
                            </p>
                          )}
                        </div>
                        <div>
                          <p className="font-semibold text-white">
                            Causal chain
                          </p>
                          {graph?.edges.length ? (
                            <ul className="mt-1 list-disc space-y-1 pl-4">
                              {graph.edges.slice(0, 24).map((edge) => (
                                <li key={edge.edge_id}>
                                  {nodeLabels.get(edge.from_node_id) ||
                                    edge.from_node_id}{" "}
                                  → {edge.relationship} →{" "}
                                  {nodeLabels.get(edge.to_node_id) ||
                                    edge.to_node_id}
                                  {" · "}
                                  {formatPercent(edge.confidence)}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="mt-1">
                              No evidence-supported causal edge is available.
                            </p>
                          )}
                          {graph?.cycles_detected && (
                            <p className="mt-1 text-rose-100">
                              Graph cycle detected; human review is required.
                            </p>
                          )}
                        </div>
                      </div>
                    </details>

                    <details className="mt-3 rounded border border-white/10 p-2">
                      <summary className="cursor-pointer font-semibold text-white">
                        Workflow impact and handoffs
                      </summary>
                      <div className="mt-2 space-y-2">
                        <p>
                          Processing impact:{" "}
                          <span className="text-white">
                            {analysisCase.processing_impact}
                          </span>
                          {" · "}Safety impact:{" "}
                          <span className="text-white">
                            {analysisCase.safety_impact}
                          </span>
                        </p>
                        <p>
                          Blocked stages:{" "}
                          {impact?.blocked_stages.join(", ") || "Not available"}.
                        </p>
                        <p>
                          Unsafe next actions:{" "}
                          {impact?.unsafe_next_actions.join("; ") ||
                            "Not available"}
                          .
                        </p>
                        <p>
                          Safe-resume requirements:{" "}
                          {impact?.resume_requirements.join("; ") ||
                            "Not available"}
                          . Resume authorized by this analyzer: No.
                        </p>
                        <p className="text-amber-100">
                          Recommended handoff:{" "}
                          {analysisCase.recommended_handoff}. Structured
                          handoffs:{" "}
                          {handoffs
                            .map((handoff) => handoff.target_module)
                            .join(", ") || "human_operator"}
                          . Automatic application: No. Human approval: Required.
                        </p>
                      </div>
                    </details>

                    {(analysisCase.warnings.length > 0 ||
                      analysisCase.limitations.length > 0) && (
                      <p className="mt-3 text-amber-100">
                        Case warnings and limitations:{" "}
                        {[
                          ...analysisCase.warnings,
                          ...analysisCase.limitations,
                        ].join("; ")}
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Evidence and execution truth
            </summary>
            <div className="mt-3 space-y-2 text-xs text-muted">
              <p>
                Evidence records: {analyzer.evidence.length}. Error Doctor used:{" "}
                {analyzer.signal_usage.error_doctor_used ? "Yes" : "No"}.
                Observer references used:{" "}
                {analyzer.signal_usage.observer_references_used ? "Yes" : "No"}.
                Raw logs read:{" "}
                {analyzer.signal_usage.raw_logs_read ? "Yes" : "No"}.
              </p>
              <p>
                Commands, validators, code changes, source-artifact changes,
                repairs, fallback tools, downloads, external APIs, rendering,
                workflow resume, and destructive actions: Not performed.
              </p>
            </div>
          </details>

          {(analyzer.warnings.length > 0 ||
            analyzer.limitations.length > 0 ||
            analyzer.analyzer_summary.human_review_notes.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Root Cause Analyzer warnings and limitations:{" "}
              {[
                ...analyzer.warnings,
                ...analyzer.limitations,
                ...analyzer.analyzer_summary.human_review_notes,
              ]
                .filter(Boolean)
                .slice(0, 20)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function RepairPlannerList({
  items,
  empty = "Not available",
}: {
  items: string[];
  empty?: string;
}) {
  const visible = items.filter(Boolean).slice(0, 16);
  if (visible.length === 0) {
    return <p className="mt-1 text-muted">{empty}</p>;
  }
  return (
    <ul className="mt-1 list-disc space-y-1 pl-4 text-muted">
      {visible.map((item, index) => (
        <li key={`${index}-${item}`}>{item}</li>
      ))}
    </ul>
  );
}

function BobaRepairPlannerPanel({ projectId }: { projectId: string }) {
  const plannerQuery = useBobaRepairPlanner(projectId);
  const generatePlanner = useGenerateBobaRepairPlanner(projectId);
  const exportPlanner = useExportBobaRepairPlanner(projectId);
  const resetPlanner = useResetBobaRepairPlanner(projectId);
  const [planningContextJson, setPlanningContextJson] = useState("");
  const [status, setStatus] = useState("");
  const planner = plannerQuery.data;
  const busy =
    generatePlanner.isPending ||
    exportPlanner.isPending ||
    resetPlanner.isPending;

  function generate() {
    let planningContext: Record<string, unknown> = {};
    if (planningContextJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(planningContextJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setStatus("Planning context must be a JSON object.");
          return;
        }
        planningContext = parsed as Record<string, unknown>;
      } catch {
        setStatus("Planning context is not valid JSON.");
        return;
      }
    }
    setStatus("");
    generatePlanner.mutate(
      { planning_context: planningContext },
      {
        onSuccess: (result) => {
          setStatus(
            `Repair Planner saved ${result.planner_summary.total_repair_cases} advisory case(s).`,
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportPlanner.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-repair-planner-v1-${projectId}.json`, payload);
        setStatus("Safe compact Repair Planner export downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset this project's BOBA Repair Planner V1 artifact only? Root Cause Analyzer, Error Doctor, Observer, and all other BOBA artifacts remain untouched.",
      )
    ) {
      return;
    }
    resetPlanner.mutate(undefined, {
      onSuccess: () => {
        setStatus(
          "BOBA Repair Planner V1 reset; Root Cause Analyzer, Error Doctor, Observer, and all other BOBA artifacts remain untouched.",
        );
      },
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-violet-300/20 bg-violet-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">
            BOBA Repair Planner V1
          </p>
          <p className="text-xs text-muted">
            {
              "BOBA Repair Planner V1 creates repair plans only. It does not execute commands, edit code, modify files, install tools, restart services, activate fallback tools, or resume workflows."
            }
          </p>
          <p className="text-xs text-amber-100">
            {"A repair plan is not proof that the repair will succeed."}
          </p>
          <p className="text-xs text-amber-100">
            {
              "Approved repairs must pass validation and output-quality review before Olympus continues."
            }
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !planner}
            onClick={exportArtifact}
            className="rounded border border-violet-200/30 px-2.5 py-1.5 text-[11px] text-violet-100 disabled:opacity-50"
          >
            Export safe repair plan
          </button>
          <button
            type="button"
            disabled={busy || !planner}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Repair Planner V1
          </button>
        </div>
      </div>

      <details className="mt-4 rounded border border-white/10 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-white">
          Optional bounded planning context
        </summary>
        <label className="mt-3 block text-xs text-muted">
          Planning context JSON
          <textarea
            value={planningContextJson}
            onChange={(event) => setPlanningContextJson(event.target.value)}
            rows={3}
            placeholder='{"cases":{"analysis_case_id":{"valid_checkpoint_available":true}}}'
            className="mt-1 w-full rounded border border-white/10 bg-black/20 px-2.5 py-2 text-xs text-white"
          />
        </label>
      </details>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={generate}
          className="rounded border border-violet-200/30 px-3 py-2 text-xs text-violet-100 disabled:opacity-50"
        >
          {generatePlanner.isPending
            ? "Planning from saved root causes..."
            : "Create plans from saved Root Cause Analyzer"}
        </button>
        <p className="text-[11px] text-muted">
          This reads the saved Root Cause Analyzer artifact only. It does not
          regenerate diagnostics or execute any proposed step.
        </p>
      </div>

      {status && <p className="mt-3 text-xs text-violet-100">{status}</p>}
      {plannerQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Repair Planner report could not be loaded.
        </p>
      )}

      {!planner ? (
        <p className="mt-4 text-xs text-muted">
          Repair Planner report is not available. Create it from the saved Root
          Cause Analyzer report; missing analyzer data produces an honest
          needs-more-evidence result.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Cases", planner.planner_summary.total_repair_cases],
              ["Plan ready", planner.planner_summary.plan_ready_count],
              ["Conditional", planner.planner_summary.conditional_plan_count],
              [
                "More evidence",
                planner.planner_summary.needs_more_evidence_count,
              ],
              ["Safety blocked", planner.planner_summary.safety_block_count],
              ["Human decision", planner.planner_summary.human_decision_count],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded border border-white/10 p-2 text-xs text-muted"
              >
                <p className="font-semibold text-white">{value}</p>
                <p>{label}</p>
              </div>
            ))}
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-3">
            <div className="rounded border border-emerald-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">Safest strategy</p>
              <p className="mt-1">
                {planner.planner_summary.safest_repair_strategy ||
                  "Not available"}
              </p>
            </div>
            <div className="rounded border border-cyan-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">Most reversible</p>
              <p className="mt-1">
                {planner.planner_summary.most_reversible_strategy ||
                  "Not available"}
              </p>
            </div>
            <div className="rounded border border-rose-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-white">Highest risk case</p>
              <p className="mt-1">
                {planner.planner_summary.highest_risk_case || "Not available"}
              </p>
            </div>
          </div>

          <details className="mt-4 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Advisory repair planning cases ({planner.repair_cases.length})
            </summary>
            <div className="mt-3 space-y-4">
              {planner.repair_cases.map((repairCase) => {
                const strategies = planner.repair_strategies.filter(
                  (item) => item.repair_case_id === repairCase.repair_case_id,
                );
                const recommended = strategies.find(
                  (item) =>
                    item.repair_strategy_id ===
                    repairCase.recommended_strategy_id,
                );
                const alternatives = strategies.filter((item) =>
                  repairCase.alternative_strategy_ids.includes(
                    item.repair_strategy_id,
                  ),
                );
                const rejected = planner.rejected_strategies.filter(
                  (item) => item.repair_case_id === repairCase.repair_case_id,
                );
                const risk = planner.risk_assessments.find(
                  (item) =>
                    item.risk_assessment_id === repairCase.risk_assessment_id,
                );
                const checkpoint = planner.checkpoint_plans.find(
                  (item) =>
                    item.checkpoint_plan_id === repairCase.checkpoint_plan_id,
                );
                const rollback = planner.rollback_plans.find(
                  (item) =>
                    item.rollback_plan_id === repairCase.rollback_plan_id,
                );
                const validation = planner.validation_plans.find(
                  (item) =>
                    item.validation_plan_id === repairCase.validation_plan_id,
                );
                const quality = planner.quality_preservation_plans.find(
                  (item) =>
                    item.quality_preservation_plan_id ===
                    repairCase.quality_preservation_plan_id,
                );
                const approval = planner.approval_gates.find(
                  (item) =>
                    item.approval_gate_id === repairCase.approval_gate_id,
                );
                const handoffs = planner.execution_handoffs.filter((item) =>
                  repairCase.execution_handoff_ids.includes(item.handoff_id),
                );
                const blockedActions = [
                  ...(recommended?.prohibited_actions ?? []),
                  ...(approval?.prohibited_actions ?? []),
                  ...handoffs.flatMap((item) => item.prohibited_actions),
                ].filter(
                  (item, index, items) => item && items.indexOf(item) === index,
                );

                return (
                  <article
                    key={repairCase.repair_case_id}
                    className="rounded border border-violet-300/20 bg-black/10 p-3 text-xs text-muted"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-semibold text-white">
                          {repairCase.title}
                        </p>
                        <p>
                          Status:{" "}
                          {repairCase.planning_status.replace(/_/g, " ")} ·
                          Repair needed: {repairCase.repair_needed ? "Yes" : "No"}{" "}
                          · Scope: {repairCase.repair_scope.replace(/_/g, " ")}
                        </p>
                      </div>
                      <span className="rounded bg-white/5 px-2 py-1 text-[11px] text-white">
                        Confidence {formatPercent(repairCase.confidence)}
                      </span>
                    </div>
                    <p className="mt-2">
                      <span className="font-semibold text-white">
                        Strongest supported root cause:
                      </span>{" "}
                      {repairCase.selected_root_cause_summary ||
                        "More evidence is required."}
                    </p>
                    {repairCase.blocked_reason && (
                      <p className="mt-1 text-rose-100">
                        Blocked: {repairCase.blocked_reason}
                      </p>
                    )}

                    <div className="mt-3 rounded border border-emerald-300/20 p-3">
                      <p className="font-semibold text-emerald-100">
                        RECOMMENDED PLAN
                      </p>
                      {recommended ? (
                        <>
                          <p className="mt-1 font-semibold text-white">
                            {recommended.title}
                          </p>
                          <p>
                            {recommended.strategy_type.replace(/_/g, " ")} ·
                            Risk {recommended.estimated_risk.replace(/_/g, " ")}{" "}
                            · Complexity{" "}
                            {recommended.estimated_complexity.replace(/_/g, " ")}{" "}
                            · Reversibility{" "}
                            {recommended.reversibility.replace(/_/g, " ")}
                          </p>
                          <p className="mt-2">
                            Technical: {recommended.description}
                          </p>
                          <p className="mt-1 text-cyan-100">
                            Easy explanation: {recommended.easy_explanation}
                          </p>
                          <p className="mt-2 font-semibold text-white">
                            Proposed future steps
                          </p>
                          {recommended.proposed_steps.length > 0 ? (
                            <ol className="mt-1 list-decimal space-y-1 pl-4">
                              {recommended.proposed_steps.map((step) => (
                                <li key={step.repair_step_id}>
                                  {step.description} Owner:{" "}
                                  {step.suggested_owner_module || "human_operator"}
                                  . Approval required: Yes.
                                </li>
                              ))}
                            </ol>
                          ) : (
                            <p className="mt-1">No executable step is proposed.</p>
                          )}
                          <p className="mt-2">
                            Expected result: {recommended.expected_result}
                          </p>
                          <p>
                            Expected quality effect:{" "}
                            {recommended.expected_quality_effect}
                          </p>
                          <p>
                            Expected workflow effect:{" "}
                            {recommended.expected_workflow_effect}
                          </p>
                          {(recommended.maximum_attempts ||
                            recommended.maximum_recovery_duration_seconds) && (
                            <p className="mt-1">
                              Recovery budget: maximum{" "}
                              {recommended.maximum_attempts ?? "bounded"} attempt(s)
                              and{" "}
                              {recommended.maximum_recovery_duration_seconds ??
                                "bounded"}{" "}
                              seconds.
                            </p>
                          )}
                        </>
                      ) : (
                        <p className="mt-1">
                          No strategy is recommended until more evidence or human
                          review is available.
                        </p>
                      )}
                    </div>

                    <div className="mt-3 rounded border border-cyan-300/20 p-3">
                      <p className="font-semibold text-cyan-100">
                        ALTERNATIVE PLANS
                      </p>
                      {alternatives.length > 0 ? (
                        <div className="mt-2 space-y-2">
                          {alternatives.map((strategy) => (
                            <div
                              key={strategy.repair_strategy_id}
                              className="rounded border border-white/10 p-2"
                            >
                              <p className="font-semibold text-white">
                                {strategy.title}
                              </p>
                              <p>{strategy.description}</p>
                              <p>
                                {strategy.strategy_type.replace(/_/g, " ")} ·
                                Risk {strategy.estimated_risk.replace(/_/g, " ")}{" "}
                                · Reversibility{" "}
                                {strategy.reversibility.replace(/_/g, " ")}
                              </p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="mt-1">
                          No safe alternative is supported by current evidence.
                        </p>
                      )}
                    </div>

                    <div className="mt-3 rounded border border-white/10 p-3">
                      <p className="font-semibold text-white">WHY THIS PLAN</p>
                      <p className="mt-1">
                        {recommended?.rationale ||
                          "No plan is selected because current evidence is insufficient or blocked."}
                      </p>
                      <p className="mt-1">
                        Workflow impact: {repairCase.expected_workflow_impact}
                      </p>
                    </div>

                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      <div className="rounded border border-rose-300/20 p-3">
                        <p className="font-semibold text-rose-100">RISKS</p>
                        <p className="mt-1">
                          Overall: {risk?.overall_risk.replace(/_/g, " ") ?? "unknown"}
                          . Output quality:{" "}
                          {risk?.output_quality_risk.replace(/_/g, " ") ??
                            "unknown"}
                          . Source data:{" "}
                          {risk?.source_data_risk.replace(/_/g, " ") ?? "unknown"}.
                        </p>
                        <RepairPlannerList
                          items={[
                            ...(risk?.blockers ?? []),
                            ...(risk?.residual_risks ?? []),
                          ]}
                          empty="No additional risk detail is available."
                        />
                      </div>
                      <div className="rounded border border-amber-300/20 p-3">
                        <p className="font-semibold text-amber-100">CHECKPOINT</p>
                        <p className="mt-1">
                          Required: {checkpoint?.checkpoint_required ? "Yes" : "No"}
                          . Type:{" "}
                          {checkpoint?.checkpoint_type.replace(/_/g, " ") ??
                            "unknown"}
                          . Source media untouched:{" "}
                          {checkpoint?.source_media_must_remain_untouched
                            ? "Required"
                            : "Not confirmed"}
                          .
                        </p>
                        <RepairPlannerList
                          items={[
                            ...(checkpoint?.artifacts_to_preserve ?? []),
                            ...(checkpoint?.state_to_preserve ?? []),
                          ]}
                          empty="No checkpoint state is required for this no-action plan."
                        />
                      </div>
                      <div className="rounded border border-sky-300/20 p-3">
                        <p className="font-semibold text-sky-100">ROLLBACK</p>
                        <p className="mt-1">
                          Required: {rollback?.rollback_required ? "Yes" : "No"}.
                          Scope:{" "}
                          {rollback?.rollback_scope.replace(/_/g, " ") ??
                            "unknown"}
                          . Destructive rollback blocked:{" "}
                          {rollback?.destructive_rollback_blocked ? "Yes" : "No"}.
                        </p>
                        <RepairPlannerList
                          items={[
                            ...(rollback?.rollback_trigger_conditions ?? []),
                            ...(rollback?.rollback_steps ?? []),
                            ...(rollback?.rollback_validation ?? []),
                          ]}
                          empty="No rollback operation is required for this no-action plan."
                        />
                      </div>
                      <div className="rounded border border-emerald-300/20 p-3">
                        <p className="font-semibold text-emerald-100">
                          VALIDATION REQUIRED
                        </p>
                        <p className="mt-1">
                          Validator Runner:{" "}
                          {validation?.requires_validator_runner ? "Required" : "No"}
                          . Validators:{" "}
                          {validation?.required_validators.join(", ") ||
                            "Not available"}
                          .
                        </p>
                        <RepairPlannerList
                          items={[
                            ...(validation?.acceptance_criteria ?? []),
                            ...(validation?.rejection_criteria ?? []),
                          ]}
                        />
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      <div className="rounded border border-fuchsia-300/20 p-3">
                        <p className="font-semibold text-fuchsia-100">
                          QUALITY REQUIREMENTS
                        </p>
                        <RepairPlannerList
                          items={[
                            ...(quality?.non_negotiable_requirements ?? []),
                            ...(quality?.unacceptable_degradations ?? []),
                            ...(quality?.fallback_acceptance_rules ?? []),
                          ]}
                        />
                      </div>
                      <div className="rounded border border-orange-300/20 p-3">
                        <p className="font-semibold text-orange-100">
                          APPROVAL REQUIRED
                        </p>
                        <p className="mt-1">
                          Status:{" "}
                          {approval?.approval_status.replace(/_/g, " ") ??
                            "unknown"}
                          . Final human approval:{" "}
                          {approval?.final_human_approval_required
                            ? "Required"
                            : "Not required"}
                          . Safety gate:{" "}
                          {approval?.safety_gate_required ? "Required" : "No"}.
                          Rights gate:{" "}
                          {approval?.rights_gate_required ? "Required" : "No"}.
                        </p>
                        <RepairPlannerList
                          items={[
                            ...(approval?.required_approvals ?? []),
                            ...(approval?.actions_requiring_approval ?? []),
                          ]}
                        />
                      </div>
                    </div>

                    <details className="mt-3 rounded border border-white/10 p-3">
                      <summary className="cursor-pointer font-semibold text-white">
                        Execution handoffs ({handoffs.length})
                      </summary>
                      <div className="mt-2 space-y-2">
                        {handoffs.length > 0 ? (
                          handoffs.map((handoff) => (
                            <div
                              key={handoff.handoff_id}
                              className="rounded border border-white/10 p-2"
                            >
                              <p className="font-semibold text-white">
                                {handoff.target_module.replace(/_/g, " ")}
                              </p>
                              <p>{handoff.reason}</p>
                              <p>
                                Capability: {handoff.required_capability}.
                                Automatic application: No. Human approval:
                                Required.
                              </p>
                            </div>
                          ))
                        ) : (
                          <p>No future execution handoff is available.</p>
                        )}
                      </div>
                    </details>

                    <div className="mt-3 rounded border border-rose-300/20 p-3">
                      <p className="font-semibold text-rose-100">
                        BLOCKED ACTIONS
                      </p>
                      <RepairPlannerList
                        items={blockedActions}
                        empty="No case-specific action is listed; global V1 non-execution boundaries still apply."
                      />
                      {rejected.length > 0 && (
                        <div className="mt-3 space-y-2">
                          <p className="font-semibold text-white">
                            Rejected unsafe strategies
                          </p>
                          {rejected.slice(0, 12).map((item) => (
                            <p key={item.rejected_strategy_id}>
                              {item.title}: {item.rejection_reason}
                            </p>
                          ))}
                        </div>
                      )}
                    </div>

                    {(repairCase.warnings.length > 0 ||
                      repairCase.limitations.length > 0 ||
                      recommended?.warnings.length) && (
                      <p className="mt-3 text-amber-100">
                        Warnings and limitations:{" "}
                        {[
                          ...repairCase.warnings,
                          ...repairCase.limitations,
                          ...(recommended?.warnings ?? []),
                        ]
                          .filter(Boolean)
                          .slice(0, 20)
                          .join("; ")}
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              Planning and execution truth
            </summary>
            <div className="mt-3 space-y-2 text-xs text-muted">
              <p>
                Root Cause Analyzer artifact read:{" "}
                {planner.signal_usage.root_cause_artifact_read ? "Yes" : "No"}.
                Checkpoint registry inspected:{" "}
                {planner.signal_usage.checkpoint_system_inspected ? "Yes" : "No"}.
                Validator registry inspected:{" "}
                {planner.signal_usage.validation_registry_inspected ? "Yes" : "No"}.
              </p>
              <p>
                Commands, validators, code changes, source-artifact changes,
                repairs, fallback tools, workflow resume, service restarts,
                package installation, downloads, external APIs, rendering, and
                destructive actions: Not performed.
              </p>
            </div>
          </details>

          {(planner.warnings.length > 0 ||
            planner.limitations.length > 0 ||
            planner.planner_summary.human_review_notes.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Repair Planner warnings and limitations:{" "}
              {[
                ...planner.warnings,
                ...planner.limitations,
                ...planner.planner_summary.human_review_notes,
              ]
                .filter(Boolean)
                .slice(0, 20)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaCodeSurgeonPanel({ projectId }: { projectId: string }) {
  const plannerQuery = useBobaRepairPlanner(projectId);
  const surgeonQuery = useBobaCodeSurgeon(projectId);
  const proposePatch = useProposeBobaCodeSurgeon(projectId);
  const validatePatch = useValidateBobaCodeSurgeonPatch(projectId);
  const executePatch = useExecuteBobaCodeSurgeonPatch(projectId);
  const prepareCommit = usePrepareBobaCodeSurgeonCommit(projectId);
  const exportSurgeon = useExportBobaCodeSurgeon(projectId);
  const resetSurgeon = useResetBobaCodeSurgeon(projectId);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [unifiedDiff, setUnifiedDiff] = useState("");
  const [affectedPaths, setAffectedPaths] = useState("");
  const [validationCommands, setValidationCommands] =
    useState("git_diff_check");
  const [reviewer, setReviewer] = useState("local-human-reviewer");
  const [executionApproved, setExecutionApproved] = useState(false);
  const [commitApproved, setCommitApproved] = useState(false);
  const [status, setStatus] = useState("");
  const planner = plannerQuery.data;
  const report = surgeonQuery.data;
  const codeCases =
    planner?.repair_cases.filter((repairCase) =>
      planner.execution_handoffs.some(
        (handoff) =>
          handoff.repair_case_id === repairCase.repair_case_id &&
          handoff.target_module === "code_surgeon",
      ),
    ) ?? [];
  const effectiveCaseId = selectedCaseId || codeCases[0]?.repair_case_id || "";
  const proposal =
    report?.patch_proposals[(report?.patch_proposals.length ?? 0) - 1];
  const repairCase = proposal
    ? report?.repair_cases.find(
        (item) => item.code_repair_case_id === proposal.code_repair_case_id,
      )
    : report?.repair_cases[0];
  const isolatedRun =
    report?.isolated_runs[(report?.isolated_runs.length ?? 0) - 1];
  const validationRun = isolatedRun
    ? report?.validation_runs.find(
        (item) => item.isolated_run_id === isolatedRun.isolated_run_id,
      )
    : undefined;
  const rollback = isolatedRun
    ? report?.rollback_records.find(
        (item) => item.isolated_run_id === isolatedRun.isolated_run_id,
      )
    : undefined;
  const reviewPackage = proposal
    ? report?.review_packages.find(
        (item) => item.patch_proposal_id === proposal.patch_proposal_id,
      )
    : undefined;
  const busy =
    proposePatch.isPending ||
    validatePatch.isPending ||
    executePatch.isPending ||
    prepareCommit.isPending ||
    exportSurgeon.isPending ||
    resetSurgeon.isPending;
  const companionMessage =
    rollback || isolatedRun?.run_status === "rolled_back"
      ? "The patch did not pass a required test. BOBA rejected it and rolled back the isolated attempt. Your main project was not changed."
      : executePatch.isPending ||
          isolatedRun?.run_status === "worktree_ready" ||
          isolatedRun?.run_status === "patch_applied" ||
          isolatedRun?.run_status === "validation_running"
        ? "BOBA is testing the patch in a separate workspace. Your main project and source files remain untouched."
        : isolatedRun?.run_status === "validation_passed" ||
            isolatedRun?.run_status === "local_commit_prepared"
          ? "The isolated patch passed its required checks. Human review is still required before any manual push or merge."
          : proposal
            ? `The problem appears to be inside the code. BOBA prepared a small patch that changes ${proposal.changed_file_count} file(s). Nothing has been modified yet. You can review the exact changes before allowing BOBA to test them in an isolated branch.`
            : "Nothing has been modified. Code Surgeon needs an eligible Repair Planner handoff and an exact bounded patch before isolated testing can be approved.";

  function parsedPaths() {
    return affectedPaths
      .split(/[\n,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function parsedCommands() {
    return validationCommands
      .split(/[\n,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function submitProposal(validateOnly: boolean) {
    if (!effectiveCaseId) {
      setStatus("Create a Repair Planner Code Surgeon handoff first.");
      return;
    }
    if (!unifiedDiff.trim()) {
      setStatus("Paste the exact bounded unified diff to review.");
      return;
    }
    const mutation = validateOnly ? validatePatch : proposePatch;
    setStatus("");
    mutation.mutate(
      {
        repair_case_id: effectiveCaseId,
        unified_diff: unifiedDiff,
        proposal_source: "user_provided_diff",
        base_branch: "main",
        affected_paths: parsedPaths(),
      },
      {
        onSuccess: (result) => {
          const latest =
            result.patch_proposals[result.patch_proposals.length - 1];
          setExecutionApproved(false);
          setCommitApproved(false);
          setStatus(
            latest
              ? `Patch ${latest.execution_status.replace(/_/g, " ")}; ${latest.changed_file_count} file(s), +${latest.additions}/-${latest.deletions}.`
              : "No patch was produced because the handoff remains blocked.",
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function approvalRecord(
    approvalType: "isolated_patch_execution" | "local_commit_creation",
  ): BobaCodeApprovalRecordV1 | null {
    if (!proposal) return null;
    const commands = parsedCommands();
    return {
      approval_id: `approval_${approvalType}_${Date.now()}`,
      code_repair_case_id: proposal.code_repair_case_id,
      patch_proposal_id: proposal.patch_proposal_id,
      approval_type: approvalType,
      approved: true,
      approved_by: reviewer.trim() || "local-human-reviewer",
      approved_base_commit_sha: proposal.base_commit_sha,
      approved_diff_sha256: proposal.diff_sha256,
      approved_scope: proposal.files.map((item) => item.path),
      approved_validation_commands: commands,
      approved_special_paths: proposal.files
        .filter((item) => item.special_approval_required)
        .map((item) => item.path),
      approval_expires_at: null,
      explicit_confirmation: true,
      warnings: [],
    };
  }

  function executeApprovedPatch() {
    const approval = approvalRecord("isolated_patch_execution");
    const commands = parsedCommands();
    if (!proposal || !approval || !executionApproved) {
      setStatus("Exact isolated-patch approval is required.");
      return;
    }
    if (commands.length === 0) {
      setStatus("At least one approved validation command is required.");
      return;
    }
    executePatch.mutate(
      {
        patch_proposal_id: proposal.patch_proposal_id,
        approval,
        approved_validation_commands: commands,
      },
      {
        onSuccess: (result) => {
          const latest = result.isolated_runs[result.isolated_runs.length - 1];
          setCommitApproved(false);
          setStatus(
            latest
              ? `Isolated execution status: ${latest.run_status.replace(/_/g, " ")}.`
              : "Execution remained blocked.",
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function createLocalReviewCommit() {
    const approval = approvalRecord("local_commit_creation");
    if (!isolatedRun || !approval || !commitApproved) {
      setStatus("Separate local-commit approval is required.");
      return;
    }
    prepareCommit.mutate(
      {
        isolated_run_id: isolatedRun.isolated_run_id,
        approval,
      },
      {
        onSuccess: (result) => {
          const latest =
            result.review_packages[result.review_packages.length - 1];
          setStatus(
            latest?.commit_created
              ? `Local review commit prepared: ${latest.local_commit_sha.slice(0, 12)}. Nothing was pushed.`
              : "No local commit was created.",
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportSurgeon.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-code-surgeon-v1-${projectId}.json`, payload);
        setStatus("Sanitized Code Surgeon review package downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset Code Surgeon metadata only? Active isolated worktrees block reset and must be reviewed separately.",
      )
    ) {
      return;
    }
    resetSurgeon.mutate(undefined, {
      onSuccess: () => setStatus("Code Surgeon metadata reset. Source code was not deleted."),
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">
            BOBA Code Surgeon V1
          </p>
          <p className="text-xs text-muted">
            Code Surgeon never edits main directly.
          </p>
          <p className="text-xs text-muted">
            Code Surgeon does not push, merge, deploy, install packages, or
            restart services.
          </p>
          <p className="text-xs text-amber-100">
            A passing patch still requires human review.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !report}
            onClick={exportArtifact}
            className="rounded border border-cyan-200/30 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50"
          >
            Export safe review package
          </button>
          <button
            type="button"
            disabled={busy || !report}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset Code Surgeon metadata
          </button>
        </div>
      </div>
      <p className="mt-3 rounded border border-sky-300/20 bg-sky-300/[0.04] p-3 text-xs text-sky-100">
        {companionMessage}
      </p>

      <details className="mt-4 rounded border border-white/10 p-3" open={!report}>
        <summary className="cursor-pointer text-xs font-semibold text-white">
          PROPOSAL
        </summary>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <label className="text-xs text-muted">
            Saved Repair Planner code case
            <select
              value={effectiveCaseId}
              onChange={(event) => setSelectedCaseId(event.target.value)}
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
            >
              {codeCases.length === 0 && (
                <option value="">No Code Surgeon handoff available</option>
              )}
              {codeCases.map((item) => (
                <option key={item.repair_case_id} value={item.repair_case_id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted">
            Exact affected paths, comma or line separated
            <textarea
              value={affectedPaths}
              onChange={(event) => setAffectedPaths(event.target.value)}
              rows={3}
              placeholder="src/olympus/example.py"
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-white"
            />
          </label>
        </div>
        <label className="mt-3 block text-xs text-muted">
          Reviewed unified diff
          <textarea
            value={unifiedDiff}
            onChange={(event) => setUnifiedDiff(event.target.value)}
            rows={10}
            placeholder={"diff --git a/path b/path\n--- a/path\n+++ b/path\n@@ ..."}
            className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-[11px] text-white"
          />
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => submitProposal(false)}
            className="rounded border border-cyan-200/30 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50"
          >
            Prepare proposal only
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => submitProposal(true)}
            className="rounded border border-violet-200/30 px-3 py-2 text-xs text-violet-100 disabled:opacity-50"
          >
            Validate patch without applying
          </button>
        </div>
      </details>

      {status && <p className="mt-3 text-xs text-cyan-100">{status}</p>}
      {surgeonQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Code Surgeon report could not be loaded.
        </p>
      )}

      {!report ? (
        <p className="mt-4 text-xs text-muted">
          Nothing has been modified. Select a saved Code Surgeon handoff and
          review the exact bounded diff before requesting isolated validation.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Cases", report.surgeon_summary.total_repair_cases],
              ["Eligible", report.surgeon_summary.eligible_case_count],
              ["Proposals", report.surgeon_summary.proposal_count],
              ["Executions", report.surgeon_summary.isolated_execution_count],
              ["Validation pass", report.surgeon_summary.validation_pass_count],
              ["Rollbacks", report.surgeon_summary.rollback_count],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded border border-white/10 p-2 text-xs text-muted"
              >
                <p className="font-semibold text-white">{value}</p>
                <p>{label}</p>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">WHY THIS CHANGE</p>
              <p className="mt-1">
                {repairCase?.justification || "No justified code change is available."}
              </p>
              <p className="mt-1">
                Evidence: {repairCase?.evidence_strength ?? "unknown"} ·
                Confidence {formatPercent(repairCase?.confidence ?? null)} ·
                Eligible: {repairCase?.execution_eligible ? "Yes" : "No"}
              </p>
              {repairCase?.blocked_reason && (
                <p className="mt-1 text-rose-100">
                  Blocked: {repairCase.blocked_reason}
                </p>
              )}
            </div>
            <div className="rounded border border-rose-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-rose-100">RISKS</p>
              <p className="mt-1">
                Patch risk: {proposal?.risk_level ?? "not available"} · Apply
                check: {proposal?.applies_cleanly ? "Passed" : "Not passed"} ·
                Scope: {proposal?.scope_check_passed ? "Passed" : "Blocked"} ·
                Secret scan:{" "}
                {proposal?.secret_scan_passed ? "Passed" : "Blocked"}
              </p>
              <RepairPlannerList
                items={[
                  ...(proposal?.warnings ?? []),
                  ...(repairCase?.warnings ?? []),
                ]}
                empty="No additional bounded warning is recorded."
              />
            </div>
          </div>

          <details className="mt-3 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              FILES THAT WILL CHANGE ({proposal?.changed_file_count ?? 0})
            </summary>
            {proposal ? (
              <div className="mt-3 space-y-2 text-xs text-muted">
                <p>
                  Base: {proposal.base_branch} @{" "}
                  {proposal.base_commit_sha.slice(0, 12)} · Diff:{" "}
                  {proposal.diff_sha256.slice(0, 12)} · Branch:{" "}
                  {proposal.proposed_branch}
                </p>
                <p>
                  +{proposal.additions}/-{proposal.deletions} ·{" "}
                  {formatBytes(proposal.patch_size_bytes)}
                </p>
                {proposal.files.map((file) => (
                  <div
                    key={file.path}
                    className="rounded border border-white/10 p-2"
                  >
                    <p className="font-mono text-white">{file.path}</p>
                    <p>
                      {file.operation} · +{file.additions}/-{file.deletions} ·{" "}
                      {file.special_approval_required
                        ? "Special approval required"
                        : "Standard bounded path"}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-muted">No patch is available.</p>
            )}
          </details>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-emerald-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-emerald-100">
                VALIDATION REQUIRED
              </p>
              <RepairPlannerList
                items={repairCase?.validation_requirements ?? []}
              />
              <label className="mt-3 block">
                Exact allowlisted command names
                <input
                  value={validationCommands}
                  onChange={(event) => setValidationCommands(event.target.value)}
                  placeholder="git_diff_check, ruff, pytest, mypy"
                  className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-white"
                />
              </label>
              <p className="mt-2 text-[11px]">
                Unknown, unavailable, skipped, timed-out, or failed required
                checks reject the patch.
              </p>
            </div>
            <div className="rounded border border-sky-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-sky-100">ROLLBACK STATUS</p>
              <p className="mt-1">
                {rollback
                  ? `${rollback.rollback_status.replace(/_/g, " ")} · Patch removed: ${rollback.patch_removed ? "Yes" : "No"} · Original worktree unchanged: ${rollback.source_worktree_unchanged ? "Yes" : "No"}`
                  : "No rollback has been required."}
              </p>
              <RepairPlannerList
                items={repairCase?.rollback_requirements ?? []}
              />
            </div>
          </div>

          <div className="mt-3 rounded border border-orange-300/20 p-3 text-xs text-muted">
            <p className="font-semibold text-orange-100">APPROVAL REQUIRED</p>
            <label className="mt-2 block">
              Reviewer identifier
              <input
                value={reviewer}
                onChange={(event) => setReviewer(event.target.value)}
                className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
              />
            </label>
            <label className="mt-3 flex items-start gap-2">
              <input
                type="checkbox"
                checked={executionApproved}
                onChange={(event) => setExecutionApproved(event.target.checked)}
              />
              <span>
                I approve applying this exact patch to an isolated repair branch
                based on the displayed base commit and diff hash.
              </span>
            </label>
            <button
              type="button"
              disabled={
                busy ||
                !proposal ||
                proposal.execution_status === "blocked" ||
                !executionApproved
              }
              onClick={executeApprovedPatch}
              className="mt-3 rounded border border-orange-200/30 px-3 py-2 text-xs text-orange-100 disabled:opacity-50"
            >
              Apply and validate in isolated branch
            </button>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">EXECUTION STATUS</p>
              <p className="mt-1">
                {isolatedRun
                  ? `${isolatedRun.run_status.replace(/_/g, " ")} · Worktree: ${isolatedRun.worktree_created ? "Created" : "Not created"} · Patch applied: ${isolatedRun.patch_applied ? "Yes" : "No"}`
                  : "Proposal only; no isolated code modification has occurred."}
              </p>
              {isolatedRun?.stop_reason && (
                <p className="mt-1 text-rose-100">
                  Stop reason: {isolatedRun.stop_reason}
                </p>
              )}
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">VALIDATION RESULTS</p>
              <p className="mt-1">
                {validationRun
                  ? `Required checks: ${validationRun.required_checks_passed ? "Passed" : "Failed"} · Acceptance: ${validationRun.acceptance_criteria_met ? "Met" : "Not met"}`
                  : "Validation has not run."}
              </p>
              {validationRun?.results.map((result) => (
                <p key={result.validation_result_id}>
                  {result.name}: {result.status.replace(/_/g, " ")}
                  {result.exit_code === null ? "" : ` (${result.exit_code})`}
                </p>
              ))}
            </div>
          </div>

          <div className="mt-3 rounded border border-fuchsia-300/20 p-3 text-xs text-muted">
            <p className="font-semibold text-fuchsia-100">HUMAN REVIEW</p>
            <p className="mt-1">
              {reviewPackage?.validation_summary ??
                "Review package is not available yet."}
            </p>
            <RepairPlannerList
              items={reviewPackage?.reviewer_checklist ?? []}
            />
            {reviewPackage && (
              <details className="mt-3 rounded border border-white/10 p-2">
                <summary className="cursor-pointer font-semibold text-white">
                  PR title and body preview
                </summary>
                <p className="mt-2 font-semibold text-white">
                  {reviewPackage.PR_title}
                </p>
                <pre className="mt-2 whitespace-pre-wrap text-[11px]">
                  {reviewPackage.PR_body}
                </pre>
              </details>
            )}
            <label className="mt-3 flex items-start gap-2">
              <input
                type="checkbox"
                checked={commitApproved}
                onChange={(event) => setCommitApproved(event.target.checked)}
              />
              <span>
                Create a local review commit on the isolated repair branch.
              </span>
            </label>
            <button
              type="button"
              disabled={
                busy ||
                isolatedRun?.run_status !== "validation_passed" ||
                !commitApproved
              }
              onClick={createLocalReviewCommit}
              className="mt-3 rounded border border-fuchsia-200/30 px-3 py-2 text-xs text-fuchsia-100 disabled:opacity-50"
            >
              Prepare local review commit
            </button>
            <p className="mt-2 text-[11px] text-amber-100">
              No push, remote PR, merge, deployment, or release occurs here.
            </p>
          </div>

          {(report.warnings.length > 0 || report.limitations.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Code Surgeon warnings and limitations:{" "}
              {[...report.warnings, ...report.limitations]
                .filter(Boolean)
                .slice(0, 24)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

const TOOL_RECOVERY_APPROVAL_TEXT =
  "I approve this exact recovery strategy, registered tool, settings, retry budget, time budget, checkpoint reference, and quality requirements.";

function BobaToolRecoveryPanel({ projectId }: { projectId: string }) {
  const plannerQuery = useBobaRepairPlanner(projectId);
  const recoveryQuery = useBobaToolRecovery(projectId);
  const generateRecovery = useGenerateBobaToolRecoveryPlan(projectId);
  const runHealthChecks = useRunBobaToolRecoveryHealthChecks(projectId);
  const executeRecovery = useExecuteBobaToolRecovery(projectId);
  const validateOutput = useValidateBobaToolRecoveryOutput(projectId);
  const rollbackRecovery = useRollbackBobaToolRecovery(projectId);
  const exportRecovery = useExportBobaToolRecovery(projectId);
  const resetRecovery = useResetBobaToolRecovery(projectId);
  const [selectedHandoffId, setSelectedHandoffId] = useState("");
  const [selectedStrategyId, setSelectedStrategyId] = useState("");
  const [rightsStatus, setRightsStatus] = useState("unknown");
  const [safetyStatus, setSafetyStatus] = useState("review_required");
  const [checkpointReady, setCheckpointReady] = useState(false);
  const [inputArtifactRef, setInputArtifactRef] = useState("");
  const [outputFilename, setOutputFilename] = useState("recovered.mp4");
  const [expectedDuration, setExpectedDuration] = useState("1");
  const [expectedWidth, setExpectedWidth] = useState("1080");
  const [expectedHeight, setExpectedHeight] = useState("1920");
  const [expectedFps, setExpectedFps] = useState("30");
  const [reviewer, setReviewer] = useState("local-human-reviewer");
  const [approvalChecked, setApprovalChecked] = useState(false);
  const [status, setStatus] = useState("");
  const planner = plannerQuery.data;
  const report = recoveryQuery.data;
  const plannerHandoffs =
    planner?.execution_handoffs.filter(
      (handoff) => handoff.target_module === "tool_recovery_brain",
    ) ?? [];
  const effectiveHandoffId =
    selectedHandoffId || plannerHandoffs[0]?.handoff_id || "";
  const plan =
    report?.recovery_plans.find((item) =>
      item.ordered_strategies.some(
        (strategy) => strategy.recovery_strategy_id === selectedStrategyId,
      ),
    ) ?? report?.recovery_plans[0];
  const recoveryCase = plan
    ? report?.recovery_cases.find(
        (item) => item.recovery_case_id === plan.recovery_case_id,
      )
    : report?.recovery_cases[0];
  const strategy =
    plan?.ordered_strategies.find(
      (item) => item.recovery_strategy_id === selectedStrategyId,
    ) ??
    plan?.ordered_strategies.find((item) => item.execution_allowed) ??
    plan?.ordered_strategies.find(
      (item) =>
        !["health_check", "stop_processing", "human_manual_action"].includes(
          item.strategy_type,
        ),
    );
  const attempt =
    report?.recovery_attempts[(report?.recovery_attempts.length ?? 0) - 1];
  const validation = attempt
    ? report?.output_validations.find(
        (item) => item.recovery_attempt_id === attempt.recovery_attempt_id,
      )
    : undefined;
  const rollback = attempt
    ? report?.rollback_records.find(
        (item) => item.recovery_attempt_id === attempt.recovery_attempt_id,
      )
    : undefined;
  const nextHandoffs =
    report?.recovery_handoffs.filter(
      (item) =>
        !attempt ||
        !item.recovery_attempt_id ||
        item.recovery_attempt_id === attempt.recovery_attempt_id,
    ) ?? [];
  const busy =
    generateRecovery.isPending ||
    runHealthChecks.isPending ||
    executeRecovery.isPending ||
    validateOutput.isPending ||
    rollbackRecovery.isPending ||
    exportRecovery.isPending ||
    resetRecovery.isPending;
  const companionMessage =
    validation?.accepted_for_quality_review
      ? "The recovered file passed its technical checks. BOBA has not accepted it as final yet. It is now ready for Output Quality Reviewer."
      : rollback || attempt?.status === "rolled_back"
        ? "The recovery attempt failed a required check. BOBA rejected the generated output and rolled back recovery-owned state. Olympus remains paused."
        : executeRecovery.isPending || attempt?.status === "running"
          ? "BOBA is retrying only the approved local capability. Your original video and completed clips remain untouched."
          : report
            ? `${recoveryCase?.failure_class.replace(/_/g, " ") ?? "A local tool failure"} was identified. BOBA found ${plan?.ordered_strategies.length ?? 0} bounded option(s). Nothing will execute without exact approval.`
            : "Tool Recovery needs a saved Repair Planner handoff. It can plan and run harmless local health checks before any recovery approval.";

  function numberOrDefault(value: string, fallback: number) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  }

  function createPlan() {
    const handoff = plannerHandoffs.find(
      (item) => item.handoff_id === effectiveHandoffId,
    );
    if (!handoff) {
      setStatus("Create a Repair Planner Tool Recovery handoff first.");
      return;
    }
    const configurationOverrides: Record<string, unknown> = {
      output_filename: outputFilename.trim() || "recovered.mp4",
      expected_duration_seconds: numberOrDefault(expectedDuration, 1),
      expected_width: numberOrDefault(expectedWidth, 1080),
      expected_height: numberOrDefault(expectedHeight, 1920),
      expected_fps: numberOrDefault(expectedFps, 30),
      require_audio: true,
      encoder_threads: 1,
      filter_threads: 1,
      parallel_tasks: 1,
    };
    if (inputArtifactRef.trim()) {
      configurationOverrides.input_artifact_ref = inputArtifactRef.trim();
    }
    setStatus("");
    generateRecovery.mutate(
      {
        selected_handoff_id: handoff.handoff_id,
        selected_repair_strategy_id: handoff.repair_strategy_id,
        failure_context: {
          rights_status: rightsStatus,
          safety_status: safetyStatus,
          checkpoint_ready: checkpointReady,
          configuration_overrides: configurationOverrides,
        },
        run_health_checks: true,
      },
      {
        onSuccess: (result) => {
          const firstPlan = result.recovery_plans[0];
          const firstStrategy =
            firstPlan?.ordered_strategies.find(
              (item) => item.execution_allowed,
            ) ??
            firstPlan?.ordered_strategies.find(
              (item) =>
                ![
                  "health_check",
                  "stop_processing",
                  "human_manual_action",
                ].includes(item.strategy_type),
            );
          setSelectedStrategyId(
            firstStrategy?.recovery_strategy_id ?? "",
          );
          setApprovalChecked(false);
          setStatus(
            result.recovery_summary.eligible_case_count > 0
              ? "Recovery plan saved. Review one exact strategy before approval."
              : "Recovery remains blocked. Review the displayed reason.",
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function runHealth() {
    runHealthChecks.mutate(
      {},
      {
        onSuccess: (result) =>
          setStatus(
            `Health checks completed: ${result.recovery_summary.healthy_tool_count} healthy, ${result.recovery_summary.unavailable_tool_count} unavailable or blocked.`,
          ),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function approvalRecord(): BobaToolRecoveryApprovalV1 | null {
    if (!plan || !strategy) return null;
    const now = new Date();
    const expires = new Date(now.getTime() + 15 * 60 * 1000);
    return {
      approval_id: `tool_recovery_approval_${Date.now()}`,
      recovery_case_id: plan.recovery_case_id,
      recovery_plan_id: plan.recovery_plan_id,
      approved: true,
      approved_at: now.toISOString(),
      approved_by: reviewer.trim() || "local-human-reviewer",
      approved_strategy_ids: [strategy.recovery_strategy_id],
      approved_tool_ids: [strategy.tool_id],
      approved_configuration_overrides: strategy.configuration_overrides,
      approved_retry_budget: plan.retry_budget,
      approved_time_budget_seconds: plan.time_budget_seconds,
      approved_quality_requirements: plan.quality_requirements,
      approved_checkpoint_reference: String(
        plan.checkpoint_requirements.reference ?? "",
      ),
      approval_expires_at: expires.toISOString(),
      explicit_confirmation: TOOL_RECOVERY_APPROVAL_TEXT,
      warnings: [],
    };
  }

  function executeApproved() {
    const approval = approvalRecord();
    if (!plan || !strategy || !approval || !approvalChecked) {
      setStatus("Exact recovery approval is required.");
      return;
    }
    executeRecovery.mutate(
      {
        recovery_plan_id: plan.recovery_plan_id,
        recovery_strategy_id: strategy.recovery_strategy_id,
        approval,
      },
      {
        onSuccess: (result) => {
          const latest =
            result.recovery_attempts[result.recovery_attempts.length - 1];
          setApprovalChecked(false);
          setStatus(
            latest
              ? `Recovery attempt: ${latest.status.replace(/_/g, " ")}. Olympus remains paused.`
              : "Recovery did not start.",
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function revalidate() {
    if (!attempt) return;
    validateOutput.mutate(
      { recovery_attempt_id: attempt.recovery_attempt_id },
      {
        onSuccess: (result) => {
          const latest =
            result.output_validations[
              result.output_validations.length - 1
            ];
          setStatus(
            latest?.accepted_for_quality_review
              ? "Technical validation passed; final quality review is still required."
              : "Technical validation rejected the generated recovery output.",
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function rollbackAttempt() {
    if (!attempt) return;
    if (
      !window.confirm(
        "Rollback recovery-owned generated output only? Source media, accepted outputs, and checkpoints remain untouched.",
      )
    ) {
      return;
    }
    rollbackRecovery.mutate(
      {
        recovery_attempt_id: attempt.recovery_attempt_id,
        trigger: "Explicit human-requested Tool Recovery rollback.",
      },
      {
        onSuccess: () =>
          setStatus(
            "Recovery-owned generated output rolled back. Olympus remains paused.",
          ),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportRecovery.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(`boba-tool-recovery-v1-${projectId}.json`, payload);
        setStatus("Sanitized Tool Recovery report downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset Tool Recovery metadata only? Recovery workspaces, source media, accepted outputs, Repair Planner, and Code Surgeon remain untouched.",
      )
    ) {
      return;
    }
    resetRecovery.mutate(undefined, {
      onSuccess: () =>
        setStatus(
          "Tool Recovery metadata reset. No media or accepted output was deleted.",
        ),
      onError: (error) => setStatus(error.message),
    });
  }

  return (
    <section className="rounded-xl border border-orange-300/20 bg-orange-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">
            BOBA Tool Recovery Brain V1
          </p>
          <p className="text-xs text-muted">
            Tool Recovery Brain can execute only approved local recovery
            actions.
          </p>
          <p className="text-xs text-muted">
            It does not install software, use paid services, access external
            media, edit code, or resume Olympus automatically.
          </p>
          <p className="text-xs text-amber-100">
            A recovered output is not accepted until required validation and
            output quality review pass.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !report}
            onClick={exportArtifact}
            className="rounded border border-orange-200/30 px-2.5 py-1.5 text-[11px] text-orange-100 disabled:opacity-50"
          >
            Export safe report
          </button>
          <button
            type="button"
            disabled={busy || !report}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset recovery metadata
          </button>
        </div>
      </div>

      <p className="mt-3 rounded border border-sky-300/20 bg-sky-300/[0.04] p-3 text-xs text-sky-100">
        {companionMessage}
      </p>

      <details className="mt-4 rounded border border-white/10 p-3" open={!report}>
        <summary className="cursor-pointer text-xs font-semibold text-white">
          PLAN AND HEALTH CHECK
        </summary>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <label className="text-xs text-muted">
            Saved Repair Planner Tool Recovery handoff
            <select
              value={effectiveHandoffId}
              onChange={(event) => setSelectedHandoffId(event.target.value)}
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
            >
              {plannerHandoffs.length === 0 && (
                <option value="">No Tool Recovery handoff available</option>
              )}
              {plannerHandoffs.map((handoff) => (
                <option key={handoff.handoff_id} value={handoff.handoff_id}>
                  {handoff.reason}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted">
            Repository-relative approved local input reference
            <input
              value={inputArtifactRef}
              onChange={(event) => setInputArtifactRef(event.target.value)}
              placeholder="storage_data/.../generated-input.mp4"
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-white"
            />
          </label>
          <label className="text-xs text-muted">
            Rights status
            <select
              value={rightsStatus}
              onChange={(event) => setRightsStatus(event.target.value)}
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
            >
              <option value="unknown">Unknown — block recovery</option>
              <option value="not_required">Not required by saved gate</option>
              <option value="clear">Cleared</option>
              <option value="blocked">Blocked</option>
            </select>
          </label>
          <label className="text-xs text-muted">
            Safety status
            <select
              value={safetyStatus}
              onChange={(event) => setSafetyStatus(event.target.value)}
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
            >
              <option value="review_required">Review required</option>
              <option value="clear">Cleared</option>
              <option value="blocked">Blocked</option>
            </select>
          </label>
        </div>
        <label className="mt-3 flex items-start gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={checkpointReady}
            onChange={(event) => setCheckpointReady(event.target.checked)}
          />
          Required checkpoint exists and has been validated. Leave unchecked
          when unknown.
        </label>
        <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Output", outputFilename, setOutputFilename],
            ["Seconds", expectedDuration, setExpectedDuration],
            ["Width", expectedWidth, setExpectedWidth],
            ["Height", expectedHeight, setExpectedHeight],
            ["FPS", expectedFps, setExpectedFps],
          ].map(([label, value, setter]) => (
            <label key={String(label)} className="text-[11px] text-muted">
              {String(label)}
              <input
                value={String(value)}
                onChange={(event) =>
                  (setter as (value: string) => void)(event.target.value)
                }
                className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-white"
              />
            </label>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !effectiveHandoffId}
            onClick={createPlan}
            className="rounded border border-orange-200/30 px-3 py-2 text-xs text-orange-100 disabled:opacity-50"
          >
            Create bounded recovery plan
          </button>
          <button
            type="button"
            disabled={busy || !report}
            onClick={runHealth}
            className="rounded border border-sky-200/30 px-3 py-2 text-xs text-sky-100 disabled:opacity-50"
          >
            Run local read-only health checks
          </button>
        </div>
      </details>

      {status && <p className="mt-3 text-xs text-orange-100">{status}</p>}
      {recoveryQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Tool Recovery report could not be loaded.
        </p>
      )}

      {report && (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Cases", report.recovery_summary.total_recovery_cases],
              ["Eligible", report.recovery_summary.eligible_case_count],
              ["Healthy tools", report.recovery_summary.healthy_tool_count],
              ["Attempts", report.recovery_summary.recovery_attempt_count],
              [
                "Quality review",
                report.recovery_summary.successful_pending_quality_count,
              ],
              ["Rollbacks", report.recovery_summary.rollback_count],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded border border-white/10 p-2 text-xs text-muted"
              >
                <p className="font-semibold text-white">{value}</p>
                <p>{label}</p>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-rose-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-rose-100">WHAT FAILED</p>
              <p className="mt-1 text-white">
                {recoveryCase?.title ?? "Not available"}
              </p>
              <p className="mt-1">
                Class:{" "}
                {recoveryCase?.failure_class.replace(/_/g, " ") ?? "unknown"}{" "}
                · Tool: {recoveryCase?.failing_tool_id || "unknown"} · Stage:{" "}
                {recoveryCase?.workflow_stage || "unknown"}
              </p>
              {recoveryCase?.blocked_reason && (
                <p className="mt-2 text-rose-100">
                  Blocked: {recoveryCase.blocked_reason}
                </p>
              )}
              <RepairPlannerList
                items={recoveryCase?.failure_evidence ?? []}
                empty="No bounded failure evidence is available."
              />
            </div>
            <div className="rounded border border-sky-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-sky-100">
                WHAT CAPABILITY IS NEEDED
              </p>
              <p className="mt-1 text-white">
                {recoveryCase?.required_capability || "Not available"}
              </p>
              <p className="mt-1">
                Rights: {recoveryCase?.rights_status ?? "unknown"} · Safety:{" "}
                {recoveryCase?.safety_status ?? "unknown"} · Checkpoint:{" "}
                {recoveryCase?.checkpoint_required
                  ? recoveryCase.checkpoint_ready
                    ? "Ready"
                    : "Blocked"
                  : "Not required"}
              </p>
              {report.registered_tools
                .filter((tool) =>
                  tool.capability_ids.includes(
                    recoveryCase?.required_capability ?? "",
                  ),
                )
                .map((tool) => (
                  <p key={tool.tool_id}>
                    {tool.display_name}: {tool.health_status.replace(/_/g, " ")}
                    {tool.installed ? "" : " · not installed"}
                  </p>
                ))}
            </div>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">RECOVERY OPTIONS</p>
              <select
                value={strategy?.recovery_strategy_id ?? ""}
                onChange={(event) => {
                  setSelectedStrategyId(event.target.value);
                  setApprovalChecked(false);
                }}
                className="mt-2 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
              >
                {plan?.ordered_strategies.map((item) => (
                  <option
                    key={item.recovery_strategy_id}
                    value={item.recovery_strategy_id}
                  >
                    {item.strategy_type.replace(/_/g, " ")} · {item.tool_id} ·{" "}
                    {item.execution_allowed ? "ready" : "not executable"}
                  </option>
                ))}
              </select>
              <p className="mt-2">
                Retry budget:{" "}
                {plan
                  ? JSON.stringify(plan.retry_budget)
                  : "Not available"}{" "}
                · Total time: {plan?.time_budget_seconds ?? 0}s
              </p>
            </div>
            <div className="rounded border border-violet-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-violet-100">WHY THIS OPTION</p>
              <p className="mt-1">
                {strategy?.rationale ?? "No strategy selected."}
              </p>
              <p className="mt-2">
                Quality: {strategy?.expected_quality_effect ?? "Not available"}
              </p>
              <p className="mt-1">
                Resources:{" "}
                {strategy?.expected_resource_effect ?? "Not available"}
              </p>
            </div>
          </div>

          <div className="mt-3 rounded border border-emerald-300/20 p-3 text-xs text-muted">
            <p className="font-semibold text-emerald-100">
              QUALITY REQUIREMENTS
            </p>
            <RepairPlannerList items={plan?.quality_requirements ?? []} />
            <p className="mt-2 text-[11px] text-amber-100">
              Required unavailable checks reject the generated output. A
              technical pass is only pending quality review.
            </p>
          </div>

          <div className="mt-3 rounded border border-orange-300/20 p-3 text-xs text-muted">
            <p className="font-semibold text-orange-100">APPROVAL REQUIRED</p>
            <label className="mt-2 block">
              Reviewer identifier
              <input
                value={reviewer}
                onChange={(event) => setReviewer(event.target.value)}
                className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
              />
            </label>
            <label className="mt-3 flex items-start gap-2">
              <input
                type="checkbox"
                checked={approvalChecked}
                onChange={(event) => setApprovalChecked(event.target.checked)}
              />
              <span>{TOOL_RECOVERY_APPROVAL_TEXT}</span>
            </label>
            <button
              type="button"
              disabled={
                busy ||
                !strategy?.execution_allowed ||
                !approvalChecked ||
                !plan
              }
              onClick={executeApproved}
              className="mt-3 rounded border border-orange-200/30 px-3 py-2 text-xs text-orange-100 disabled:opacity-50"
            >
              Execute this exact approved local strategy
            </button>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">CURRENT ATTEMPT</p>
              <p className="mt-1">
                {attempt
                  ? `${attempt.status.replace(/_/g, " ")} · Attempt ${attempt.attempt_number} · ${attempt.tool_id}`
                  : "No recovery attempt has run."}
              </p>
              {attempt && (
                <p className="mt-1">
                  Source untouched:{" "}
                  {attempt.source_media_untouched ? "Yes" : "No"} · Completed
                  outputs untouched:{" "}
                  {attempt.completed_outputs_untouched ? "Yes" : "No"} ·
                  Workflow resumed: No
                </p>
              )}
              {attempt?.stop_reason && (
                <p className="mt-1 text-amber-100">
                  Stop reason: {attempt.stop_reason}
                </p>
              )}
            </div>
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">VALIDATION</p>
              <p className="mt-1">
                {validation
                  ? `Required checks: ${validation.required_checks_passed ? "Passed" : "Failed"} · Quality-review handoff: ${validation.accepted_for_quality_review ? "Ready" : "No"}`
                  : "Technical validation has not run."}
              </p>
              <RepairPlannerList
                items={[
                  ...(validation?.failed_required_checks ?? []),
                  ...(validation?.unavailable_required_checks ?? []),
                ]}
                empty="No failed or unavailable required checks are recorded."
              />
              <button
                type="button"
                disabled={busy || !attempt}
                onClick={revalidate}
                className="mt-2 rounded border border-sky-200/30 px-2.5 py-1.5 text-[11px] text-sky-100 disabled:opacity-50"
              >
                Re-run technical output validation
              </button>
            </div>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-white/10 p-3 text-xs text-muted">
              <p className="font-semibold text-white">ROLLBACK</p>
              <p className="mt-1">
                {rollback
                  ? `${rollback.status.replace(/_/g, " ")} · Temporary output removed: ${rollback.temporary_outputs_removed ? "Yes" : "No"} · Source preserved: ${rollback.source_media_preserved ? "Yes" : "No"}`
                  : "No rollback has been required."}
              </p>
              <button
                type="button"
                disabled={busy || !attempt}
                onClick={rollbackAttempt}
                className="mt-2 rounded border border-rose-200/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
              >
                Roll back recovery-owned output
              </button>
            </div>
            <div className="rounded border border-fuchsia-300/20 p-3 text-xs text-muted">
              <p className="font-semibold text-fuchsia-100">
                WHAT HAPPENS NEXT
              </p>
              {nextHandoffs.length > 0 ? (
                nextHandoffs.slice(-6).map((handoff) => (
                  <p key={handoff.handoff_id} className="mt-1">
                    {handoff.target_module.replace(/_/g, " ")}: {handoff.reason}
                  </p>
                ))
              ) : (
                <p className="mt-1">
                  Human approval or a safe downstream review is required.
                </p>
              )}
              <p className="mt-2 text-[11px] text-amber-100">
                Tool Recovery never resumes Olympus directly.
              </p>
            </div>
          </div>

          {(report.warnings.length > 0 || report.limitations.length > 0) && (
            <p className="mt-4 text-xs text-amber-100">
              Tool Recovery warnings and limitations:{" "}
              {[...report.warnings, ...report.limitations]
                .filter(Boolean)
                .slice(0, 24)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function BobaOutputQualityReviewerPanel({
  projectId,
  renders,
}: {
  projectId: string;
  renders: RenderedVideo[];
}) {
  const reviewerQuery = useBobaOutputQualityReviewer(projectId);
  const reviewOutput = useReviewBobaOutputQuality(projectId);
  const compareOutput = useCompareBobaOutputQuality(projectId);
  const recordHumanReview = useRecordBobaOutputHumanReview(projectId);
  const exportReviewer = useExportBobaOutputQualityReviewer(projectId);
  const resetReviewer = useResetBobaOutputQualityReviewer(projectId);
  const [outputReference, setOutputReference] = useState("");
  const [baselineReference, setBaselineReference] = useState("");
  const [reviewMode, setReviewMode] =
    useState<BobaOutputReviewModeV1>("full_available_evidence_review");
  const [rightsStatus, setRightsStatus] = useState("unknown");
  const [safetyStatus, setSafetyStatus] = useState("unknown");
  const [reviewerIdentity, setReviewerIdentity] = useState(
    "local-human-reviewer",
  );
  const [reviewDecision, setReviewDecision] = useState<
    | "accept_for_next_internal_stage"
    | "accept_with_disclosed_limitation"
    | "reject_output"
    | "send_back_to_tool_recovery"
    | "send_back_to_repair_planner"
    | "request_more_evidence"
  >("request_more_evidence");
  const [reviewNotes, setReviewNotes] = useState("");
  const [status, setStatus] = useState("");
  const report = reviewerQuery.data;
  const latestCase =
    report?.review_cases[(report?.review_cases.length ?? 1) - 1];
  const artifact = report?.output_artifacts.find(
    (item) => item.output_artifact_id === latestCase?.output_artifact_id,
  );
  const technical = report?.technical_assessments.find(
    (item) =>
      item.technical_assessment_id === latestCase?.technical_assessment_id,
  );
  const creative = report?.creative_assessments.find(
    (item) =>
      item.creative_assessment_id === latestCase?.creative_assessment_id,
  );
  const comparison = report?.baseline_comparisons.find(
    (item) =>
      item.baseline_comparison_id === latestCase?.baseline_comparison_id,
  );
  const decision = report?.acceptance_decisions.find(
    (item) =>
      item.acceptance_decision_id === latestCase?.acceptance_decision_id,
  );
  const humanPackage = report?.human_review_packages.find(
    (item) =>
      item.human_review_package_id === latestCase?.human_review_package_id,
  );
  const regressions =
    report?.quality_regressions.filter(
      (item) => item.review_case_id === latestCase?.review_case_id,
    ) ?? [];
  const issues =
    report?.quality_issues.filter(
      (item) => item.review_case_id === latestCase?.review_case_id,
    ) ?? [];
  const handoffs =
    report?.review_handoffs.filter(
      (item) => item.review_case_id === latestCase?.review_case_id,
    ) ?? [];
  const effectiveOutputReference =
    outputReference || renders[0]?.storage_key || "";
  const busy =
    reviewOutput.isPending ||
    compareOutput.isPending ||
    recordHumanReview.isPending ||
    exportReviewer.isPending ||
    resetReviewer.isPending;

  function runReview() {
    if (!effectiveOutputReference) {
      setStatus("Choose one exact known generated output reference.");
      return;
    }
    if (reviewMode === "baseline_comparison") {
      if (!baselineReference.trim()) {
        setStatus("Baseline comparison requires one exact known baseline.");
        return;
      }
      compareOutput.mutate(
        {
          output_reference: effectiveOutputReference,
          baseline_reference: baselineReference.trim(),
          rights_status: rightsStatus,
          safety_status: safetyStatus,
          comparison_basis: "manual_baseline",
        },
        {
          onSuccess: () =>
            setStatus(
              "Read-only baseline comparison saved. Olympus remains paused.",
            ),
          onError: (error) => setStatus(error.message),
        },
      );
      return;
    }
    reviewOutput.mutate(
      {
        output_reference: effectiveOutputReference,
        baseline_reference: baselineReference.trim() || undefined,
        review_mode: reviewMode,
        rights_status: rightsStatus,
        safety_status: safetyStatus,
        workflow_stage: "quality_review",
      },
      {
        onSuccess: () =>
          setStatus("Read-only output review saved. Olympus remains paused."),
        onError: (error) => setStatus(error.message),
      },
    );
  }

  function exportArtifact() {
    exportReviewer.mutate(undefined, {
      onSuccess: (payload) => {
        downloadJson(
          `boba-output-quality-reviewer-v1-${projectId}.json`,
          payload,
        );
        setStatus("Sanitized quality-review report downloaded.");
      },
      onError: (error) => setStatus(error.message),
    });
  }

  function reset() {
    if (
      !window.confirm(
        "Reset Output Quality Reviewer metadata only? Reviewed outputs, source media, render manifests, and upstream BOBA artifacts remain untouched.",
      )
    ) {
      return;
    }
    resetReviewer.mutate(undefined, {
      onSuccess: () =>
        setStatus(
          "Reviewer metadata reset. No output, source media, or manifest was deleted.",
        ),
      onError: (error) => setStatus(error.message),
    });
  }

  function submitHumanReview() {
    if (!latestCase) return;
    recordHumanReview.mutate(
      {
        review_case_id: latestCase.review_case_id,
        reviewer_identity: reviewerIdentity,
        review_decision: reviewDecision,
        notes: reviewNotes,
      },
      {
        onSuccess: () => {
          setReviewNotes("");
          setStatus(
            "Bounded human review recorded. Publication and workflow resume remain unauthorized.",
          );
        },
        onError: (error) => setStatus(error.message),
      },
    );
  }

  return (
    <section className="rounded-xl border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-4xl">
          <p className="text-sm font-semibold text-white">
            BOBA Output Quality Reviewer V1
          </p>
          <p className="text-xs text-muted">
            BOBA Output Quality Reviewer does not repair or rerender files.
          </p>
          <p className="text-xs text-muted">
            A technically valid output can still be rejected for quality loss,
            missing story meaning, or unacceptable regression.
          </p>
          <p className="text-xs text-muted">
            Automated creative review is evidence-based but cannot replace
            every human visual judgment.
          </p>
          <p className="text-xs text-amber-100">
            Acceptance here does not authorize upload, publication, or workflow
            resume.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !report}
            onClick={exportArtifact}
            className="rounded border border-cyan-200/30 px-2.5 py-1.5 text-[11px] text-cyan-100 disabled:opacity-50"
          >
            Export safe report
          </button>
          <button
            type="button"
            disabled={busy || !report}
            onClick={reset}
            className="rounded border border-rose-300/30 px-2.5 py-1.5 text-[11px] text-rose-100 disabled:opacity-50"
          >
            Reset reviewer metadata
          </button>
        </div>
      </div>

      <details className="mt-4 rounded border border-white/10 p-3" open={!report}>
        <summary className="cursor-pointer text-xs font-semibold text-white">
          START READ-ONLY REVIEW
        </summary>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <label className="text-xs text-muted">
            Exact known output reference
            <input
              value={effectiveOutputReference}
              onChange={(event) => setOutputReference(event.target.value)}
              placeholder="render/project/clips/clip.mp4"
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-white"
            />
          </label>
          <label className="text-xs text-muted">
            Exact baseline reference, when required
            <input
              value={baselineReference}
              onChange={(event) => setBaselineReference(event.target.value)}
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-white"
            />
          </label>
          <label className="text-xs text-muted">
            Review mode
            <select
              value={reviewMode}
              onChange={(event) =>
                setReviewMode(event.target.value as BobaOutputReviewModeV1)
              }
              className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
            >
              <option value="full_available_evidence_review">
                Full available evidence
              </option>
              <option value="local_technical_review">
                Local technical review
              </option>
              <option value="artifact_only">Artifact only</option>
              <option value="baseline_comparison">Baseline comparison</option>
              <option value="human_review_preparation">
                Human review preparation
              </option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-muted">
              Rights
              <select
                value={rightsStatus}
                onChange={(event) => setRightsStatus(event.target.value)}
                className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
              >
                <option value="unknown">Unknown — block</option>
                <option value="owned">Owned</option>
                <option value="licensed">Licensed</option>
                <option value="permission_granted">Permission granted</option>
                <option value="blocked">Blocked</option>
              </select>
            </label>
            <label className="text-xs text-muted">
              Safety
              <select
                value={safetyStatus}
                onChange={(event) => setSafetyStatus(event.target.value)}
                className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
              >
                <option value="unknown">Unknown — block</option>
                <option value="passed">Passed</option>
                <option value="approved">Approved</option>
                <option value="blocked">Blocked</option>
              </select>
            </label>
          </div>
        </div>
        <button
          type="button"
          disabled={busy || !effectiveOutputReference}
          onClick={runReview}
          className="mt-3 rounded border border-cyan-200/30 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50"
        >
          Run registered read-only review
        </button>
      </details>

      {status && <p className="mt-3 text-xs text-cyan-100">{status}</p>}
      {reviewerQuery.isError && (
        <p className="mt-3 text-xs text-rose-100">
          Output Quality Reviewer report could not be loaded.
        </p>
      )}

      {report && latestCase && (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Decision", decision?.decision.replace(/_/g, " ") ?? "unknown"],
              [
                "Technical",
                technical?.technical_acceptance_eligible ? "Eligible" : "Blocked",
              ],
              [
                "Creative",
                creative?.creative_acceptance_eligible ? "Eligible" : "Uncertain",
              ],
              ["Confidence", `${Math.round(latestCase.confidence * 100)}%`],
              ["Rights", latestCase.rights_status],
              ["Safety", latestCase.safety_status],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded border border-white/10 p-2 text-xs text-muted"
              >
                <p className="font-semibold capitalize text-white">{value}</p>
                <p>{label}</p>
              </div>
            ))}
          </div>

          <div className="mt-3 rounded border border-white/10 p-3 text-xs text-muted">
            <p className="font-semibold text-white">REVIEW CASE</p>
            <p className="mt-1 text-white">{latestCase.title}</p>
            <p className="mt-1">
              Output:{" "}
              <span className="font-mono">
                {artifact?.sanitized_artifact_reference ?? "Not available"}
              </span>
            </p>
            <p>
              Origin: {latestCase.source_type.replace(/_/g, " ")} ·{" "}
              {latestCase.source_module || "unknown"} · Mode:{" "}
              {latestCase.review_mode.replace(/_/g, " ")}
            </p>
          </div>

          <details className="mt-3 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              TECHNICAL CHECKS
            </summary>
            <p className="mt-2 text-xs text-muted">
              Required checks:{" "}
              {technical?.required_checks_passed ? "Passed" : "Incomplete or failed"} ·
              Score: {Math.round((technical?.technical_score ?? 0) * 100)}%
            </p>
            <div className="mt-2 space-y-1">
              {technical?.checks.map((check) => (
                <div
                  key={check.technical_check_id}
                  className="flex flex-wrap justify-between gap-2 rounded border border-white/5 px-2 py-1 text-[11px] text-muted"
                >
                  <span>
                    {check.name}
                    {check.required ? " · required" : " · optional"}
                  </span>
                  <span
                    className={
                      check.status === "failed" ||
                      check.status === "unavailable"
                        ? "text-rose-100"
                        : check.status === "passed"
                          ? "text-emerald-100"
                          : "text-amber-100"
                    }
                  >
                    {check.status.replace(/_/g, " ")}
                  </span>
                </div>
              ))}
            </div>
            <RepairPlannerList
              items={technical?.failed_required_checks ?? []}
              empty="No failed required technical checks are recorded."
            />
            <RepairPlannerList
              items={technical?.unavailable_required_checks ?? []}
              empty="No unavailable required technical checks are recorded."
            />
          </details>

          <details className="mt-3 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              CREATIVE REVIEW
            </summary>
            <p className="mt-2 text-xs text-muted">
              Evidence coverage:{" "}
              {Math.round((creative?.evidence_coverage ?? 0) * 100)}% ·
              Creative score is advisory:{" "}
              {Math.round((creative?.creative_score ?? 0) * 100)}%
            </p>
            <div className="mt-2 grid gap-2 lg:grid-cols-2">
              {creative?.dimensions.map((dimension) => (
                <div
                  key={dimension.creative_dimension_id}
                  className="rounded border border-white/10 p-2 text-xs text-muted"
                >
                  <p className="font-semibold capitalize text-white">
                    {dimension.dimension.replace(/_/g, " ")} ·{" "}
                    {dimension.status.replace(/_/g, " ")}
                  </p>
                  <RepairPlannerList
                    items={dimension.positive_findings}
                    empty="No positive finding was proven."
                  />
                  <RepairPlannerList
                    items={dimension.negative_findings}
                    empty="No negative finding was recorded."
                  />
                  {dimension.uncertainty && (
                    <p className="mt-1 text-amber-100">
                      Uncertainty: {dimension.uncertainty}
                    </p>
                  )}
                </div>
              ))}
            </div>
            <RepairPlannerList
              items={creative?.subjective_uncertainty ?? []}
              empty="No additional subjective uncertainty is recorded."
            />
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              BASELINE COMPARISON
            </summary>
            {comparison ? (
              <div className="mt-2 grid gap-2 text-xs text-muted lg:grid-cols-2">
                <div>
                  <p>
                    Equivalent for required capability:{" "}
                    {comparison.equivalent_for_required_capability ? "Yes" : "No"}
                  </p>
                  <RepairPlannerList
                    items={comparison.preserved_properties}
                    empty="No preserved property is recorded."
                  />
                  <RepairPlannerList
                    items={comparison.improved_properties}
                    empty="No improved property is recorded."
                  />
                </div>
                <div>
                  <RepairPlannerList
                    items={comparison.degraded_properties}
                    empty="No degraded property is recorded."
                  />
                  <RepairPlannerList
                    items={comparison.non_negotiable_regressions}
                    empty="No non-negotiable regression is recorded."
                  />
                  <RepairPlannerList
                    items={comparison.unknown_properties}
                    empty="No comparison property remains unknown."
                  />
                </div>
              </div>
            ) : (
              <p className="mt-2 text-xs text-muted">Not available.</p>
            )}
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              QUALITY REGRESSIONS
            </summary>
            <div className="mt-2 space-y-2 text-xs text-muted">
              {regressions.map((regression) => (
                <p
                  key={regression.quality_regression_id}
                  className="rounded border border-rose-300/20 p-2"
                >
                  {regression.category.replace(/_/g, " ")} ·{" "}
                  {regression.severity} · {regression.acceptance_impact}
                  {regression.non_negotiable ? " · non-negotiable" : ""}
                </p>
              ))}
              {issues.map((issue) => (
                <p
                  key={issue.quality_issue_id}
                  className="rounded border border-amber-300/20 p-2"
                >
                  <span className="font-semibold text-white">{issue.title}</span>
                  : {issue.summary}
                </p>
              ))}
              {regressions.length === 0 && issues.length === 0 && (
                <p>No quality regression or issue is recorded.</p>
              )}
            </div>
          </details>

          <details className="mt-3 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              DECISION
            </summary>
            <p className="mt-2 text-sm font-semibold capitalize text-cyan-100">
              {decision?.decision.replace(/_/g, " ") ?? "Not available"}
            </p>
            <p className="mt-1 text-xs text-muted">
              {decision?.decision_summary ?? "No decision is available."}
            </p>
            <RepairPlannerList
              items={decision?.rejection_reasons ?? []}
              empty="No rejection reason is recorded."
            />
            <RepairPlannerList
              items={decision?.disclosed_limitations ?? []}
              empty="No decision limitation is recorded."
            />
          </details>

          <details className="mt-3 rounded border border-white/10 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-white">
              HUMAN REVIEW
            </summary>
            <p className="mt-2 text-xs text-muted">
              {humanPackage?.reason ??
                "A bounded human-review package is not required for this case."}
            </p>
            <RepairPlannerList
              items={humanPackage?.reviewer_questions ?? []}
              empty="No reviewer question is recorded."
            />
            {humanPackage && (
              <div className="mt-3 grid gap-2 lg:grid-cols-2">
                <label className="text-xs text-muted">
                  Reviewer identifier
                  <input
                    value={reviewerIdentity}
                    onChange={(event) => setReviewerIdentity(event.target.value)}
                    className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
                  />
                </label>
                <label className="text-xs text-muted">
                  Internal decision
                  <select
                    value={reviewDecision}
                    onChange={(event) =>
                      setReviewDecision(
                        event.target.value as typeof reviewDecision,
                      )
                    }
                    className="mt-1 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
                  >
                    <option value="request_more_evidence">
                      Request more evidence
                    </option>
                    <option value="accept_for_next_internal_stage">
                      Accept for next internal stage
                    </option>
                    <option value="accept_with_disclosed_limitation">
                      Accept with disclosed limitation
                    </option>
                    <option value="reject_output">Reject output</option>
                    <option value="send_back_to_tool_recovery">
                      Send back to Tool Recovery
                    </option>
                    <option value="send_back_to_repair_planner">
                      Send back to Repair Planner
                    </option>
                  </select>
                </label>
                <label className="text-xs text-muted lg:col-span-2">
                  Bounded notes
                  <textarea
                    value={reviewNotes}
                    onChange={(event) => setReviewNotes(event.target.value)}
                    maxLength={1000}
                    className="mt-1 min-h-20 w-full rounded border border-white/10 bg-black/30 px-2.5 py-2 text-white"
                  />
                </label>
                <button
                  type="button"
                  disabled={busy || !reviewerIdentity.trim()}
                  onClick={submitHumanReview}
                  className="rounded border border-cyan-200/30 px-3 py-2 text-xs text-cyan-100 disabled:opacity-50"
                >
                  Record internal human review
                </button>
              </div>
            )}
          </details>

          <details className="mt-3 rounded border border-white/10 p-3" open>
            <summary className="cursor-pointer text-xs font-semibold text-white">
              WHAT HAPPENS NEXT
            </summary>
            <div className="mt-2 space-y-2 text-xs text-muted">
              {handoffs.map((handoff) => (
                <div
                  key={handoff.handoff_id}
                  className="rounded border border-white/10 p-2"
                >
                  <p className="font-semibold capitalize text-white">
                    {handoff.target_module.replace(/_/g, " ")}
                  </p>
                  <p>{handoff.reason}</p>
                  <RepairPlannerList
                    items={handoff.blocked_actions}
                    empty="No extra blocked action is recorded."
                  />
                </div>
              ))}
              {handoffs.length === 0 && <p>No downstream handoff is available.</p>}
            </div>
          </details>

          {(latestCase.limitations.length > 0 ||
            report.limitations.length > 0) && (
            <p className="mt-3 text-xs text-amber-100">
              Limitations:{" "}
              {[...latestCase.limitations, ...report.limitations]
                .filter(Boolean)
                .slice(0, 24)
                .join("; ")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function ClipCard({
  projectId,
  render,
  plan,
  activeProfile,
}: {
  projectId: string;
  render: RenderedVideo;
  plan: ClipPlan | undefined;
  activeProfile: CreatorProfileV2 | undefined;
}) {
  const submitFeedback = useSubmitClipFeedback();
  const [feedbackNote, setFeedbackNote] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const url = mediaUrls.renderClip(projectId, render.clip_id);
  const uploadMetadata = uploadMetadataSummary(render);
  const title = uploadMetadata.bestTitle || planTitle(plan, render);
  const hook = hookLine(plan);
  const reason = reasonSelected(plan);
  const description = uploadMetadata.youtubeDescription || `${title}\n\n${reason}`;
  const tagText =
    uploadMetadata.youtubeHashtags.join(" ") || hashtags(plan);
  const effects = effectSummary(render);
  const viral = viralSummary(plan);
  const unified = unifiedSummary(render, plan, effects, viral);
  const safety = copyrightSafetySummary(render);
  const personalization = personalizationSummary(render);
  const boba = bobaClipSummary(render);
  const safetyBadgeClass =
    safety.riskLevel === "blocked" || safety.riskLevel === "high"
      ? "bg-red-500/10 text-red-300"
      : safety.riskLevel === "low"
        ? "bg-emerald-500/10 text-emerald-300"
        : "bg-amber-500/10 text-amber-200";
  const metadataBadgeClass = uploadMetadata.manualReviewRequired
    ? "bg-amber-500/10 text-amber-200"
    : uploadMetadata.validationPassed
      ? "bg-emerald-500/10 text-emerald-300"
      : "bg-white/5 text-muted";

  function sendFeedback(
    rating: ClipFeedbackInput["rating"],
    labels: string[] = [],
  ) {
    if (!activeProfile) {
      setFeedbackStatus("Choose an active local profile before submitting feedback.");
      return;
    }
    setFeedbackStatus("");
    submitFeedback.mutate(
      {
        profile_id: activeProfile.profile_id,
        project_id: projectId,
        clip_id: render.clip_id,
        rating,
        labels,
        notes: feedbackNote.trim(),
        clip_traits: {
          hook_category: viral.hookCategory || undefined,
          caption_style: effects.captionStyle || undefined,
          music_mood: effects.musicMood || undefined,
          motion_style: effects.motionStyle || undefined,
          clip_traits: [viral.storyShape, viral.niche].filter(Boolean),
        },
      },
      {
        onSuccess: (feedback) => {
          setFeedbackNote("");
          setFeedbackStatus(
            feedback.applied_to_profile
              ? "Feedback saved and applied gradually to this profile."
              : "Feedback saved. Profile learning remains off.",
          );
        },
        onError: (error) => setFeedbackStatus(error.message),
      },
    );
  }

  return (
    <article className="overflow-hidden rounded-xl border border-white/10 bg-surface">
      <div className="grid gap-4 p-4 sm:grid-cols-[160px_1fr]">
        <video
          controls
          preload="metadata"
          className="aspect-[9/16] w-full rounded-lg border border-white/10 bg-black object-cover"
          src={url}
        >
          <track kind="captions" />
        </video>
        <div className="min-w-0 space-y-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
                Rendered
              </span>
              <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${safetyBadgeClass}`}>
                Risk: {safety.riskLevel.replace(/_/g, " ")}
              </span>
              {plan?.rank && (
                <span className="rounded bg-white/5 px-2 py-0.5 text-[11px] text-muted">
                  Rank #{plan.rank}
                </span>
              )}
            </div>
            <h3 className="mt-2 line-clamp-2 text-sm font-semibold text-white">{title}</h3>
            <p className="mt-1 text-xs text-muted">
              {formatDuration(render.duration)} · {render.width ?? "?"}x{render.height ?? "?"} ·{" "}
              {formatBytes(render.size_bytes)}
            </p>
          </div>

          {hook && (
            <p className="rounded-lg bg-white/[0.04] px-3 py-2 text-xs leading-relaxed text-white/85">
              {hook}
            </p>
          )}
          <p className="line-clamp-3 text-xs leading-relaxed text-muted">{reason}</p>
          <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-white/70">
              Why this clip works
            </p>
            {unified.bullets.length > 0 ? (
              <ul className="mt-1 space-y-1 text-xs leading-relaxed text-muted">
                {unified.bullets.slice(0, 8).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-xs text-muted">Unified clip reasoning is not available.</p>
            )}
            {!unified.available && (
              <p className="mt-1 text-[11px] text-muted">
                Showing fallback Story/Virality/Render fields from older metadata.
              </p>
            )}
          </div>
          <div className="rounded-lg border border-violet-300/20 bg-violet-300/[0.04] px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-violet-100/80">
              BOBA reasoning
            </p>
            {boba.available ? (
              <div className="mt-1 space-y-1 text-xs leading-relaxed text-muted">
                <p>
                  BOBA recommends: {boba.rankingExplanation || boba.editorialPolicy || "Review the advisory project reasoning."}
                </p>
                <p>
                  BOBA confidence: {formatPercent(boba.confidence)} · Mode: {boba.mode.replace(/_/g, " ")}
                </p>
                <p>Applied to editing: {boba.applied ? "Yes" : "No, advisory only"}</p>
                <p>
                  Memory used: {boba.memoryUsed.length > 0 ? `${boba.memoryUsed.length} bounded record(s)` : "Not available"}
                </p>
                {boba.missingSignals.length > 0 && (
                  <p>Missing signals: {boba.missingSignals.slice(0, 5).join(", ")}</p>
                )}
                {boba.warnings.length > 0 && (
                  <p className="text-amber-100">Warning: {boba.warnings.slice(0, 2).join("; ")}</p>
                )}
              </div>
            ) : (
              <p className="mt-1 text-xs text-muted">
                BOBA reasoning is not available for this older render.
              </p>
            )}
          </div>
          <div className="rounded-lg border border-cyan-300/15 bg-cyan-300/[0.04] px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-cyan-100/80">
              Personalization truth
            </p>
            {personalization.available ? (
              <div className="mt-1 space-y-1 text-xs leading-relaxed text-muted">
                <p>
                  {personalization.applied ? "Personalized with" : "Profile evaluated"}: {" "}
                  {personalization.profileName || personalization.profileId || "Local profile"}
                  {personalization.confidence !== null &&
                    ` · ${formatPercent(personalization.confidence)} confidence`}
                </p>
                <p>
                  Affected systems: {" "}
                  {personalization.affectedSystems.length > 0
                    ? personalization.affectedSystems.join(", ")
                    : "None applied"}
                </p>
                {personalization.adjustments.length > 0 && (
                  <p>Adjusted: {personalization.adjustments.slice(0, 4).join("; ")}</p>
                )}
                {!personalization.applied && personalization.reasons.length > 0 && (
                  <p>Not applied: {personalization.reasons.slice(0, 2).join("; ")}</p>
                )}
                {personalization.warnings.length > 0 && (
                  <p className="text-amber-100">
                    Warning: {personalization.warnings.slice(0, 2).join("; ")}
                  </p>
                )}
              </div>
            ) : (
              <p className="mt-1 text-xs text-muted">
                Personalization metadata is not available for this render.
              </p>
            )}
          </div>
          <details className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-muted">
            <summary className="cursor-pointer font-medium text-white/80">
              Copyright and upload readiness
            </summary>
            <div className="mt-2 grid gap-1 sm:grid-cols-2">
              <span>Risk: {safety.riskLevel.replace(/_/g, " ")}</span>
              <span>Upload readiness: {safety.uploadReadiness.replace(/_/g, " ")}</span>
              <span>
                Manual review: {safety.manualReviewRequired ? "Required" : "Not required"}
              </span>
              <span>
                Source rights:{" "}
                {safety.sourceRightsAvailable
                  ? safety.sourceRightsConfirmed
                    ? "User confirmed"
                    : "Not confirmed"
                  : "Not available"}
              </span>
              <span>
                Music license:{" "}
                {safety.musicUsed
                  ? safety.musicLicenseVerified
                    ? "Verified metadata"
                    : "Needs review"
                  : "Not used"}
              </span>
              <span>
                SFX license:{" "}
                {safety.sfxUsed
                  ? safety.sfxLicenseVerified
                    ? "Verified metadata"
                    : "Needs review"
                  : "Not used"}
              </span>
            </div>
            {!safety.available && (
              <p className="mt-2 leading-relaxed">
                Copyright and safety metadata is not available for this older render.
              </p>
            )}
            {safety.checklist.length > 0 && (
              <ul className="mt-2 space-y-1 leading-relaxed">
                {safety.checklist.slice(0, 6).map((item) => (
                  <li key={item}>- {item}</li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[11px] leading-relaxed text-white/50">{safety.disclaimer}</p>
          </details>

          <section className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-3 text-xs text-muted">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold uppercase tracking-wide text-white/70">
                Upload Metadata
              </p>
              <span className={`rounded px-2 py-0.5 text-[11px] ${metadataBadgeClass}`}>
                {uploadMetadata.manualReviewRequired
                  ? "Manual review required"
                  : uploadMetadata.validationPassed
                    ? "Validated"
                    : uploadMetadata.status.replace(/_/g, " ")}
              </span>
            </div>
            {uploadMetadata.available ? (
              <>
                <p className="mt-2 font-medium leading-relaxed text-white/90">
                  {uploadMetadata.bestTitle}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => copyText(uploadMetadata.bestTitle)}
                    className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[11px] hover:border-white/30 hover:text-white"
                  >
                    <CopyIcon className="h-3 w-3" />
                    Copy title
                  </button>
                  <button
                    type="button"
                    onClick={() => copyText(uploadMetadata.youtubeCopy)}
                    className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[11px] hover:border-white/30 hover:text-white"
                  >
                    <CopyIcon className="h-3 w-3" />
                    Copy YouTube
                  </button>
                  <button
                    type="button"
                    onClick={() => copyText(uploadMetadata.instagramCopy)}
                    className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[11px] hover:border-white/30 hover:text-white"
                  >
                    <CopyIcon className="h-3 w-3" />
                    Copy Instagram
                  </button>
                  <button
                    type="button"
                    onClick={() => copyText(uploadMetadata.tiktokCopy)}
                    className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[11px] hover:border-white/30 hover:text-white"
                  >
                    <CopyIcon className="h-3 w-3" />
                    Copy TikTok
                  </button>
                  <button
                    type="button"
                    onClick={() => copyText(uploadMetadata.youtubeHashtags.join(" "))}
                    className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 text-[11px] hover:border-white/30 hover:text-white"
                  >
                    <CopyIcon className="h-3 w-3" />
                    Copy hashtags
                  </button>
                </div>
                <details className="mt-3 border-t border-white/10 pt-2">
                  <summary className="cursor-pointer font-medium text-white/80">
                    Platform copy
                  </summary>
                  <div className="mt-2 space-y-3 leading-relaxed">
                    <div>
                      <p className="font-medium text-white/80">YouTube Shorts</p>
                      <p className="mt-1 whitespace-pre-line">{uploadMetadata.youtubeDescription}</p>
                      <p className="mt-1 text-white/60">
                        {uploadMetadata.youtubeHashtags.join(" ") || "No focused hashtags available"}
                      </p>
                      {uploadMetadata.titleVariants.length > 1 && (
                        <p className="mt-1 text-[11px] text-white/50">
                          Title variants: {uploadMetadata.titleVariants.slice(1).join(" | ")}
                        </p>
                      )}
                    </div>
                    <div>
                      <p className="font-medium text-white/80">Instagram Reels</p>
                      <p className="mt-1 whitespace-pre-line">{uploadMetadata.instagramCaption}</p>
                      <p className="mt-1 text-white/60">
                        {uploadMetadata.instagramHashtags.join(" ") || "No focused hashtags available"}
                      </p>
                    </div>
                    <div>
                      <p className="font-medium text-white/80">TikTok</p>
                      <p className="mt-1 whitespace-pre-line">{uploadMetadata.tiktokCaption}</p>
                      <p className="mt-1 text-white/60">
                        {uploadMetadata.tiktokHashtags.join(" ") || "No focused hashtags available"}
                      </p>
                    </div>
                  </div>
                </details>
              </>
            ) : (
              <p className="mt-2 leading-relaxed">
                Upload metadata is not available for this older render.
              </p>
            )}
            {uploadMetadata.warnings.length > 0 && (
              <div className="mt-2 rounded border border-amber-400/20 bg-amber-400/10 px-2 py-1.5 text-amber-100">
                Metadata warning: {uploadMetadata.warnings.slice(0, 2).join("; ")}
              </div>
            )}
          </section>
          <p className="text-xs text-muted">
            Source {Math.round(plan?.start ?? 0)}s-{Math.round(plan?.end ?? 0)}s
            {typeof plan?.quality_score === "number" && (
              <> · Score {Math.round(plan.quality_score * 100)}</>
            )}
          </p>

          <div className="grid gap-2 text-[11px] text-muted sm:grid-cols-2">
            <span>Viral score: {formatPercent(viral.score)}</span>
            <span>Niche: {viral.niche.replace(/_/g, " ")}</span>
            <span>Hook type: {viral.hookCategory.replace(/_/g, " ")}</span>
            <span>Story: {viral.storyShape.replace(/_/g, " ")}</span>
            <span>Payoff ending: {viral.endingType.replace(/_/g, " ")}</span>
            <span>
              Trend fit: {formatPercent(viral.trendFit)} ({viral.trendPatterns})
            </span>
            <span>
              Research: {viral.researchStatus} ({viral.researchSourceCount} sources, {" "}
              {formatPercent(viral.researchConfidence)} confidence)
            </span>
            <span>Trend provider: {viral.researchProvider.replace(/_/g, " ")}</span>
            <span>
              Trend domains: {viral.researchDomains.length > 0 ? viral.researchDomains.join(", ") : "not available"}
            </span>
            <span>Boundary: {viral.boundaryReason}</span>
            <span>
              Captions: {effects.captionStatus} ({effects.captionStyle.replace(/_/g, " ")})
            </span>
            <span>
              Caption timing: {effects.captionTiming}
              {effects.captionTimingEstimated ? " (estimated)" : ""}
            </span>
            <span>
              Hook treatment: {effects.captionHookTreatment ? "Applied" : "Not applied"} (
              {effects.captionHookStyle.replace(/_/g, " ")})
            </span>
            <span>Highlighted words: {effects.captionHighlightedWords}</span>
            <span>
              Speaker-aware captions: {effects.captionSpeakerAware ? "Applied" : "Not applied"}
            </span>
            <span>Caption safe zone: {effects.captionSafeZone.replace(/_/g, " ")}</span>
            <span>
              Caption validation: {effects.captionValidationStatus} · Readability {effects.captionReadabilityStatus}
            </span>
            <span>
              Music: {effects.musicMixed ? "Used" : "Not used"} · {formatDb(effects.musicGain)}
            </span>
            <span>
              SFX: {effects.sfxCount} mixed, {effects.sfxSkipped} skipped
            </span>
            <span>
              Motion: {effects.motionStatus} ({effects.motionCount}/{effects.motionPlannedCount} effects)
            </span>
            <span>Motion style: {effects.motionStyle.replace(/_/g, " ")}</span>
            <span>
              Face tracking: {effects.faceStatus} ({effects.faceMode.replace(/_/g, " ")})
            </span>
            <span>
              Layout: {effects.layoutStatus} ({effects.layoutMode.replace(/_/g, " ")})
            </span>
            <span>
              Participants: {effects.layoutParticipants} tracked · {effects.layoutSpeakerCount} speakers
            </span>
            <span>
              Speaker association: {effects.layoutAssociation ? "available" : "unavailable"}
            </span>
            <span>
              Active-speaker switching: {effects.layoutActiveSpeaker ? "used" : "not used"}
            </span>
            <span>
              Layout regions/switches: {effects.layoutRegions}/{effects.layoutSwitches}
            </span>
            <span>
              Layout confidence: {formatPercent(effects.layoutConfidence)} · {effects.layoutValidationStatus}
            </span>
            <span>SFX safety: {effects.sfxSafety ? "applied" : "not applied"}</span>
            <span>
              Sync: {effects.syncStatus} ({formatDelta(effects.syncDelta)})
            </span>
            <span>
              Duration: {formatDelta(effects.expectedDuration)} vs{" "}
              {formatDelta(effects.actualDuration)}
            </span>
            <span>Hook: {effects.hookTreatment.replace(/_/g, " ")}</span>
            <span>Voice: {effects.voiceApplied ? "enhanced" : "not applied"}</span>
            <span>Video: {effects.videoApplied ? "enhanced" : "not applied"}</span>
          </div>

          <details className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-muted">
            <summary className="cursor-pointer font-medium text-white/80">
              Motion graphics
            </summary>
            <div className="mt-2 grid gap-1 sm:grid-cols-2">
              <span>Status: {effects.motionStatus}</span>
              <span>Style: {effects.motionStyle.replace(/_/g, " ")}</span>
              <span>Intensity: {effects.motionIntensity.replace(/_/g, " ")}</span>
              <span>Effects: {effects.motionCount}/{effects.motionPlannedCount} rendered</span>
              <span>Hook: {effects.motionHookEffect.replace(/_/g, " ")}</span>
              <span>Payoff: {effects.motionPayoffEffect.replace(/_/g, " ")}</span>
              <span>Safety: {effects.motionSafetyStatus}</span>
              <span>Validation: {effects.motionValidationStatus}</span>
            </div>
            <p className="mt-2 leading-relaxed">
              {effects.motionReason ||
                effects.motionDisabledReason.replace(/_/g, " ") ||
                "Motion reasoning is not available for this older render."}
            </p>
          </details>

          <details className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-muted">
            <summary className="cursor-pointer font-medium text-white/80">
              Caption intelligence
            </summary>
            <div className="mt-2 grid gap-1 sm:grid-cols-2">
              <span>Style: {effects.captionStyle.replace(/_/g, " ")}</span>
              <span>Timing: {effects.captionTiming}</span>
              <span>Safe zone: {effects.captionSafeZone.replace(/_/g, " ")}</span>
              <span>Speaker strategy: {effects.captionSpeakerStrategy.replace(/_/g, " ")}</span>
              <span>Highlighted words: {effects.captionHighlightedWords}</span>
              <span>Validation: {effects.captionValidationStatus}</span>
            </div>
            <p className="mt-2 leading-relaxed">
              {effects.captionReason ||
                "Caption reasoning is not available for this older render."}
            </p>
          </details>

          <details className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-muted">
            <summary className="cursor-pointer font-medium text-white/80">
              Music intelligence
            </summary>
            <div className="mt-2 grid gap-1 sm:grid-cols-2">
              <span>Mood: {effects.musicMood.replace(/_/g, " ") || "Not available"}</span>
              <span>Role: {effects.musicRole.replace(/_/g, " ") || "None"}</span>
              <span>Track: {effects.musicTrack || "No safe asset selected"}</span>
              <span>
                Source: {effects.musicSourceType.replace(/_/g, " ") || "Not available"}
              </span>
              <span>
                Quality: {effects.musicQuality.replace(/_/g, " ") || "Not available"}
              </span>
              <span>Ducking: {effects.musicDucking ? "Applied" : "Not applied"}</span>
              <span>
                License: {effects.musicLicense || "Not available"} (
                {effects.musicLicenseSafe ? "verified" : "not verified"})
              </span>
              <span>Validation: {effects.musicValidationStatus}</span>
            </div>
            <p className="mt-2 leading-relaxed">
              {effects.musicReason ||
                effects.musicDisabledReason.replace(/_/g, " ") ||
                "Music reasoning is not available for this older render."}
              {effects.musicLibraryReason && " " + effects.musicLibraryReason}
            </p>
          </details>

          {viral.clickbaitRisk && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Hook warning: clickbait-like wording detected; keep captions faithful to the transcript.
            </div>
          )}

          {(!viral.hasResearch ||
            viral.fallbackUsed ||
            viral.researchStatus === "Stale" ||
            viral.researchStatus === "Unavailable") && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Trend research warning: {viral.researchWarning || "Trend research is not available."}
            </div>
          )}

          {effects.hasWarning && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Render validation warning: caption, sync, or duration validation needs review.
            </div>
          )}

          {effects.captionWarning && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Caption warning: {effects.captionWarning}
            </div>
          )}

          {effects.musicWarning && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Music warning: {effects.musicWarning}
            </div>
          )}

          {effects.motionWarning && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Motion warning: {effects.motionWarning}
            </div>
          )}

          {(effects.layoutFallback || effects.layoutWarning) && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Layout warning: {effects.layoutFallback.replace(/_/g, " ") || effects.layoutWarning}
            </div>
          )}

          {(safety.manualReviewRequired || safety.blockedReasons.length > 0) && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Copyright review required:{" "}
              {safety.blockedReasons[0] ||
                safety.warnings[0] ||
                "Confirm source and asset permissions before publishing."}
            </div>
          )}

          {unified.renderWarnings.length > 0 && (
            <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
              Render warning: {unified.renderWarnings.slice(0, 2).join("; ")}
            </div>
          )}

          <section className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold text-white">Explicit clip feedback</p>
              <span className="text-[11px] text-muted">
                {activeProfile
                  ? `Saving to ${activeProfile.profile_name}`
                  : "No active profile available"}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "like" }, ["liked"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white hover:border-white/30 disabled:opacity-50">Like</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "dislike" }, ["disliked"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white hover:border-white/30 disabled:opacity-50">Dislike</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "like" }, ["make_more_like_this"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white hover:border-white/30 disabled:opacity-50">More like this</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "dislike" }, ["avoid_in_future"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-white hover:border-white/30 disabled:opacity-50">Avoid this</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "neutral", hook: "like" })} className="rounded border border-white/10 px-2 py-1 text-[11px] text-muted hover:border-white/30 hover:text-white disabled:opacity-50">Hook good</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "neutral", captions: "like" }, ["captions_good"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-muted hover:border-white/30 hover:text-white disabled:opacity-50">Captions good</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "neutral", music: "like" }, ["music_good"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-muted hover:border-white/30 hover:text-white disabled:opacity-50">Music good</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "neutral", motion: "dislike" }, ["too_much_motion"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-muted hover:border-white/30 hover:text-white disabled:opacity-50">Too much motion</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "neutral", title_metadata: "like" }, ["title_good"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-muted hover:border-white/30 hover:text-white disabled:opacity-50">Title good</button>
              <button type="button" disabled={submitFeedback.isPending} onClick={() => sendFeedback({ overall: "neutral", title_metadata: "dislike" }, ["title_bad"])} className="rounded border border-white/10 px-2 py-1 text-[11px] text-muted hover:border-white/30 hover:text-white disabled:opacity-50">Title bad</button>
            </div>
            <div className="mt-2 flex gap-2">
              <input
                value={feedbackNote}
                maxLength={500}
                onChange={(event) => setFeedbackNote(event.target.value)}
                placeholder="Optional short note (never learned unless you submit)"
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/30"
              />
              <button
                type="button"
                disabled={submitFeedback.isPending || !feedbackNote.trim()}
                onClick={() => sendFeedback({ overall: "neutral" })}
                className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-white hover:border-white/30 disabled:opacity-50"
              >
                Submit note
              </button>
            </div>
            {feedbackStatus && (
              <p className="mt-2 text-[11px] text-cyan-100">{feedbackStatus}</p>
            )}
          </section>

          <div className="flex flex-wrap gap-2">
            <a
              href={url}
              download
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-white transition-colors hover:border-white/30"
            >
              <DownloadIcon className="h-3.5 w-3.5" />
              Download MP4
            </a>
            {!uploadMetadata.available && (
              <>
                <button
                  type="button"
                  onClick={() => copyText(title)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-white/30 hover:text-white"
                >
                  <CopyIcon className="h-3.5 w-3.5" />
                  Title
                </button>
                <button
                  type="button"
                  onClick={() => copyText(description)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-white/30 hover:text-white"
                >
                  <CopyIcon className="h-3.5 w-3.5" />
                  Description
                </button>
                <button
                  type="button"
                  onClick={() => copyText(tagText)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-white/30 hover:text-white"
                >
                  <CopyIcon className="h-3.5 w-3.5" />
                  Hashtags
                </button>
              </>
            )}
          </div>

          {render.subtitles_included ? (
            <p className="text-[11px] text-muted">Captions are burned into this MP4.</p>
          ) : (
            <p className="text-[11px] text-muted">Caption sidecar is not available for this render.</p>
          )}
        </div>
      </div>
    </article>
  );
}

export function ResultsSection({
  projectId,
  render,
}: {
  projectId: string;
  render: RenderRun | null | undefined;
}) {
  const terminal = render ? isTerminal(render) : false;
  const manifestQuery = useRenderManifest(projectId, terminal);
  const plansQuery = usePlans(projectId, terminal);
  const profilesQuery = useCreatorProfiles();
  const bobaQuery = useBobaBrain(projectId);
  const wholeVideoQuery = useBobaWholeVideoUnderstanding(projectId);
  const generateWholeVideo = useGenerateBobaWholeVideoUnderstanding(projectId);
  const candidateDiscoveryQuery = useBobaCandidateClipDiscovery(projectId);
  const discoverCandidates = useDiscoverBobaCandidateClips(projectId);
  const clipRankingQuery = useBobaClipRanking(projectId);
  const rankCandidates = useRankBobaCandidateClips(projectId);
  const editorialDecisionsQuery = useBobaEditorialDecisions(projectId);
  const createEditorialDecisions = useCreateBobaEditorialDecisions(projectId);
  const explanationsQuery = useBobaExplanations(projectId);
  const createExplanations = useCreateBobaExplanations(projectId);
  const creativeDirectionV2Query = useBobaCreativeDirectionV2(projectId);
  const createCreativeDirectionV2 = useCreateBobaCreativeDirectionV2(projectId);
  const clipBriefsQuery = useBobaClipBriefs(projectId);
  const createClipBriefs = useCreateBobaClipBriefs(projectId);
  const hookRetentionQuery = useBobaHookRetention(projectId);
  const createHookRetention = useCreateBobaHookRetention(projectId);
  const captionMotionQuery = useBobaCaptionMotion(projectId);
  const createCaptionMotion = useCreateBobaCaptionMotion(projectId);
  const musicMoodQuery = useBobaMusicMood(projectId);
  const createMusicMood = useCreateBobaMusicMood(projectId);
  const renders = manifestQuery.data?.manifest.renders ?? [];
  const plans = plansQuery.data?.plans ?? [];
  const activeProfile = profilesQuery.data?.profiles.find(
    (profile) => profile.profile_id === profilesQuery.data.active_profile_id,
  );
  const projectMemoryQuery = useBobaProjectMemory(projectId);
  const creatorMemoryQuery = useBobaCreatorMemory(activeProfile?.profile_id);
  const memoryPanel = (
    <BobaMemoryPanel
      projectId={projectId}
      creatorId={activeProfile?.profile_id}
      projectMemory={projectMemoryQuery.data}
      creatorMemory={creatorMemoryQuery.data}
    />
  );
  const wholeVideoPanel = (
    <BobaWholeVideoPanel
      understanding={wholeVideoQuery.data}
      building={generateWholeVideo.isPending}
      onBuild={() => generateWholeVideo.mutate()}
    />
  );
  const candidateDiscoveryPanel = (
    <BobaCandidateDiscoveryPanel
      discovery={candidateDiscoveryQuery.data}
      discovering={discoverCandidates.isPending}
      onDiscover={() => discoverCandidates.mutate()}
    />
  );
  const clipRankingPanel = (
    <BobaClipRankingPanel
      ranking={clipRankingQuery.data}
      rankingCandidates={rankCandidates.isPending}
      canRank={Boolean(candidateDiscoveryQuery.data?.candidates.length)}
      onRank={() => rankCandidates.mutate()}
    />
  );
  const editorialDecisionPanel = (
    <BobaEditorialDecisionPanel
      decisions={editorialDecisionsQuery.data}
      deciding={createEditorialDecisions.isPending}
      canDecide={Boolean(clipRankingQuery.data?.ranked_candidates.length)}
      onDecide={() => createEditorialDecisions.mutate()}
    />
  );
  const explanationPanel = (
    <BobaExplanationPanel
      explanations={explanationsQuery.data}
      explaining={createExplanations.isPending}
      canExplain={Boolean(
        wholeVideoQuery.data ||
          candidateDiscoveryQuery.data ||
          clipRankingQuery.data ||
          editorialDecisionsQuery.data,
      )}
      onExplain={() => createExplanations.mutate()}
    />
  );
  const creativeDirectionV2Panel = (
    <BobaCreativeDirectionV2Panel
      direction={creativeDirectionV2Query.data}
      directing={createCreativeDirectionV2.isPending}
      canDirect={Boolean(editorialDecisionsQuery.data)}
      onDirect={() => createCreativeDirectionV2.mutate()}
    />
  );
  const clipBriefPanel = (
    <BobaClipBriefPanel
      briefs={clipBriefsQuery.data}
      generating={createClipBriefs.isPending}
      canGenerate={Boolean(
        creativeDirectionV2Query.data && editorialDecisionsQuery.data,
      )}
      onGenerate={() => createClipBriefs.mutate()}
    />
  );
  const hookRetentionPanel = (
    <BobaHookRetentionPanel
      analysis={hookRetentionQuery.data}
      generating={createHookRetention.isPending}
      canGenerate={Boolean(clipBriefsQuery.data?.selected_briefs.length)}
      onGenerate={() => createHookRetention.mutate()}
    />
  );
  const captionMotionPanel = (
    <BobaCaptionMotionPanel
      recommendations={captionMotionQuery.data}
      generating={createCaptionMotion.isPending}
      canGenerate={Boolean(
        clipBriefsQuery.data?.selected_briefs.length ||
          clipBriefsQuery.data?.backup_briefs.length,
      )}
      onGenerate={() => createCaptionMotion.mutate()}
    />
  );
  const musicMoodPanel = (
    <BobaMusicMoodPanel
      recommendations={musicMoodQuery.data}
      generating={createMusicMood.isPending}
      canGenerate={Boolean(
        clipBriefsQuery.data?.selected_briefs.length ||
          clipBriefsQuery.data?.backup_briefs.length,
      )}
      onGenerate={() => createMusicMood.mutate()}
    />
  );
  const experimentationPanel = (
    <BobaExperimentationPanel
      projectId={projectId}
      canGenerate={Boolean(
        clipBriefsQuery.data ||
          hookRetentionQuery.data ||
          captionMotionQuery.data ||
          musicMoodQuery.data,
      )}
    />
  );
  const performanceFeedbackPanel = (
    <BobaPerformanceFeedbackPanel projectId={projectId} />
  );
  const contentScoutV2Panel = (
    <BobaContentScoutV2Panel projectId={projectId} />
  );
  const researchBrainPanel = (
    <BobaResearchBrainPanel projectId={projectId} />
  );
  const trendTopicWatcherPanel = (
    <BobaTrendTopicWatcherPanel projectId={projectId} />
  );
  const candidateVideoScorerPanel = (
    <BobaCandidateVideoScorerPanel projectId={projectId} />
  );
  const rightsPermissionGatePanel = (
    <BobaRightsPermissionGatePanel projectId={projectId} />
  );
  const observerPanel = <BobaObserverPanel projectId={projectId} />;
  const errorDoctorPanel = <BobaErrorDoctorPanel projectId={projectId} />;
  const rootCauseAnalyzerPanel = (
    <BobaRootCauseAnalyzerPanel projectId={projectId} />
  );
  const repairPlannerPanel = <BobaRepairPlannerPanel projectId={projectId} />;
  const codeSurgeonPanel = <BobaCodeSurgeonPanel projectId={projectId} />;
  const toolRecoveryPanel = <BobaToolRecoveryPanel projectId={projectId} />;
  const outputQualityReviewerPanel = (
    <BobaOutputQualityReviewerPanel projectId={projectId} renders={renders} />
  );
  const autopilotPanel = <BobaAutopilotPanel projectId={projectId} />;
  const scoutCreativePanel = <BobaScoutCreativePanel projectId={projectId} />;

  if (renders.length > 0) {
    return (
      <div className="space-y-4">
        <PersonalizationPanel />
        <BobaBrainPanel brain={bobaQuery.data} />
        {wholeVideoPanel}
        {candidateDiscoveryPanel}
        {clipRankingPanel}
        {editorialDecisionPanel}
        {explanationPanel}
        {creativeDirectionV2Panel}
        {clipBriefPanel}
        {hookRetentionPanel}
        {captionMotionPanel}
        {musicMoodPanel}
        {experimentationPanel}
        {performanceFeedbackPanel}
        {memoryPanel}
        {contentScoutV2Panel}
        {researchBrainPanel}
        {trendTopicWatcherPanel}
        {candidateVideoScorerPanel}
        {rightsPermissionGatePanel}
        {observerPanel}
        {errorDoctorPanel}
        {rootCauseAnalyzerPanel}
        {repairPlannerPanel}
        {codeSurgeonPanel}
        {toolRecoveryPanel}
        {outputQualityReviewerPanel}
        {autopilotPanel}
        {scoutCreativePanel}
        {renders.map((rendered) => (
          <ClipCard
            key={rendered.clip_id}
            projectId={projectId}
            render={rendered}
            plan={findPlan(plans, rendered)}
            activeProfile={activeProfile}
          />
        ))}
      </div>
    );
  }

  if (!render) {
    return (
      <div className="space-y-4">
        <PersonalizationPanel />
        <BobaBrainPanel brain={bobaQuery.data} />
        {wholeVideoPanel}
        {candidateDiscoveryPanel}
        {clipRankingPanel}
        {editorialDecisionPanel}
        {explanationPanel}
        {creativeDirectionV2Panel}
        {clipBriefPanel}
        {hookRetentionPanel}
        {captionMotionPanel}
        {musicMoodPanel}
        {experimentationPanel}
        {performanceFeedbackPanel}
        {memoryPanel}
        {contentScoutV2Panel}
        {researchBrainPanel}
        {trendTopicWatcherPanel}
        {candidateVideoScorerPanel}
        {rightsPermissionGatePanel}
        {observerPanel}
        {errorDoctorPanel}
        {rootCauseAnalyzerPanel}
        {repairPlannerPanel}
        {codeSurgeonPanel}
        {toolRecoveryPanel}
        {outputQualityReviewerPanel}
        {autopilotPanel}
        {scoutCreativePanel}
        <EmptyState
          icon={<SparklesIcon className="h-6 w-6" />}
          title="Generating clips from the full video"
          description="Olympus is analyzing, planning, editing, and rendering real Shorts. Finished clips will replace this message automatically."
        />
      </div>
    );
  }

  if (!terminal) {
    return (
      <div className="space-y-4">
        <PersonalizationPanel />
        <BobaBrainPanel brain={bobaQuery.data} />
        {wholeVideoPanel}
        {candidateDiscoveryPanel}
        {clipRankingPanel}
        {editorialDecisionPanel}
        {explanationPanel}
        {creativeDirectionV2Panel}
        {clipBriefPanel}
        {hookRetentionPanel}
        {captionMotionPanel}
        {musicMoodPanel}
        {experimentationPanel}
        {performanceFeedbackPanel}
        {memoryPanel}
        {contentScoutV2Panel}
        {researchBrainPanel}
        {trendTopicWatcherPanel}
        {candidateVideoScorerPanel}
        {rightsPermissionGatePanel}
        {observerPanel}
        {errorDoctorPanel}
        {rootCauseAnalyzerPanel}
        {repairPlannerPanel}
        {codeSurgeonPanel}
        {toolRecoveryPanel}
        {outputQualityReviewerPanel}
        {autopilotPanel}
        {scoutCreativePanel}
        <EmptyState
          icon={<ServerIcon className="h-6 w-6" />}
          title="Rendering selected clips"
          description="The output gallery will appear here as soon as the render manifest contains real MP4 files."
        />
      </div>
    );
  }

  const manifestStage = render.stages.find((stage) => stage.stage === "generate_render_manifest");
  return (
    <div className="space-y-4">
      <PersonalizationPanel />
      <BobaBrainPanel brain={bobaQuery.data} />
      {wholeVideoPanel}
      {candidateDiscoveryPanel}
      {clipRankingPanel}
      {editorialDecisionPanel}
      {explanationPanel}
      {creativeDirectionV2Panel}
      {clipBriefPanel}
      {hookRetentionPanel}
      {captionMotionPanel}
      {musicMoodPanel}
      {experimentationPanel}
      {performanceFeedbackPanel}
      {memoryPanel}
      {contentScoutV2Panel}
      {researchBrainPanel}
      {trendTopicWatcherPanel}
      {candidateVideoScorerPanel}
      {rightsPermissionGatePanel}
      {observerPanel}
      {errorDoctorPanel}
      {rootCauseAnalyzerPanel}
      {repairPlannerPanel}
      {codeSurgeonPanel}
      {toolRecoveryPanel}
      {outputQualityReviewerPanel}
      {autopilotPanel}
      {scoutCreativePanel}
      <EmptyState
        icon={<ServerIcon className="h-6 w-6" />}
        title="No rendered clips yet"
        description={
          manifestStage?.reason ??
          "Rendering finished without a published MP4 manifest. Check the Rendering tab for exact stage logs."
        }
      />
    </div>
  );
}
