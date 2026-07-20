"use client";

import { useState } from "react";

import { CopyIcon, DownloadIcon, ServerIcon, SparklesIcon } from "@/components/icons";
import { EmptyState } from "@/components/ui/EmptyState";
import { mediaUrls } from "@/lib/apiClient";
import {
  useActivateCreatorProfile,
  useBobaBrain,
  useBobaCandidateClipDiscovery,
  useBobaCandidates,
  useBobaClipRanking,
  useBobaCreatorMemory,
  useBobaCreativeBriefs,
  useBobaProjectMemory,
  useBobaWholeVideoUnderstanding,
  useCreateCreatorProfile,
  useCreatorProfiles,
  useExportCreatorProfile,
  useDecideBobaCandidate,
  useDecideBobaCreativeBrief,
  useDiscoverBobaCandidateClips,
  useGenerateBobaCreativeBriefs,
  useGenerateBobaWholeVideoUnderstanding,
  usePlans,
  useRenderManifest,
  useResetCreatorProfile,
  useRankBobaCandidateClips,
  useScoreBobaCandidate,
  useSubmitClipFeedback,
  useUpdateCreatorProfile,
} from "@/lib/queries";
import { formatBytes, formatDuration, isTerminal } from "@/lib/rendering";
import type {
  ClipFeedbackInput,
  BobaBrainStateV1,
  BobaCandidateClipDiscoveryV1,
  BobaClipRankingV1,
  BobaCreatorMemoryV1,
  BobaProjectMemoryV1,
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

function BobaMemoryPanel({
  projectMemory,
  creatorMemory,
}: {
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
  const renders = manifestQuery.data?.manifest.renders ?? [];
  const plans = plansQuery.data?.plans ?? [];
  const activeProfile = profilesQuery.data?.profiles.find(
    (profile) => profile.profile_id === profilesQuery.data.active_profile_id,
  );
  const projectMemoryQuery = useBobaProjectMemory(projectId);
  const creatorMemoryQuery = useBobaCreatorMemory(activeProfile?.profile_id);
  const memoryPanel = (
    <BobaMemoryPanel
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
  const scoutCreativePanel = <BobaScoutCreativePanel projectId={projectId} />;

  if (renders.length > 0) {
    return (
      <div className="space-y-4">
        <PersonalizationPanel />
        <BobaBrainPanel brain={bobaQuery.data} />
        {wholeVideoPanel}
        {candidateDiscoveryPanel}
        {clipRankingPanel}
        {memoryPanel}
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
        {memoryPanel}
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
        {memoryPanel}
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
      {memoryPanel}
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
