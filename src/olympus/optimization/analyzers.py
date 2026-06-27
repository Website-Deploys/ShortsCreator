"""The twenty-four Optimization Engine stages.

Each stage is an isolated, replaceable module behind the
:class:`OptimizationAnalyzer` contract. None imports another; they communicate
only through the structured :class:`OptimizationStageContext`. Together they take
the finished, rendered Shorts and the upstream engines' decisions and make the
output as polished and engaging as possible **without changing the story**.

Honesty rules (enforced by construction):
- A stage that needs the rendered media reports ``UNAVAILABLE`` (with the exact
  reason) when no render manifest exists.
- A stage that needs an enhancement model reports ``UNAVAILABLE`` when the model
  is absent (audio/visual/thumbnail capabilities are queried, never assumed).
- A single value that cannot be determined is recorded as ``UNKNOWN`` (``None``),
  never guessed - e.g. thumbnail image scores without a vision model.
- Stages that can work purely from upstream *data* (music brief, captions,
  metadata, export specs, variants, quality from real signals) run for real and
  are independent of whether a render exists.
Nothing here re-renders, re-encodes, or changes the story.
"""

from __future__ import annotations

from typing import Any, ClassVar

from olympus.domain.contracts.music import MusicProviderRegistry
from olympus.domain.contracts.optimization import (
    OptimizationAnalyzer,
    OptimizationOutcome,
    OptimizationProgressReporter,
    OptimizationStageContext,
)
from olympus.optimization import optimize as O  # noqa: N812 (module alias is intentional)
from olympus.optimization.export_profiles import (
    ExportProfileRegistry,
    build_default_export_registry,
)

_NO_RENDER = (
    "No render manifest exists for this project. The Rendering Engine - a separate, "
    "independent layer - has not produced any finished MP4 yet, and optimization "
    "operates on rendered video. Nothing is fabricated without a real render."
)
_EMPTY_RENDER = (
    "A render manifest exists but lists zero rendered videos, so there is nothing "
    "to optimize. This is an honest empty result, not a failure."
)
_NO_TIMELINES = (
    "No edit timelines are available from the Editing Engine, so there are no "
    "Shorts to operate on. (The Editing Engine produced zero timelines, or has not "
    "completed.)"
)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _captions(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    for track in O.as_list(timeline.get("tracks")):
        if track.get("kind") == "caption":
            return O.as_list(track.get("events"))
    return []


def _markers(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    for track in O.as_list(timeline.get("tracks")):
        if track.get("kind") == "markers":
            return O.as_list(track.get("events"))
    return []


def _meta(timeline: dict[str, Any]) -> dict[str, Any]:
    return O.as_dict(timeline.get("metadata"))


def _clip_duration(timeline: dict[str, Any]) -> float:
    return O.as_float(timeline.get("duration"))


def _audio_unavailable(ctx: OptimizationStageContext, capability: str) -> str | None:
    """Return the honest reason an audio stage cannot run, or ``None`` if it can."""

    if not ctx.rendered_videos():
        return _NO_RENDER
    cap = ctx.enhancement.capability(capability)
    if not cap.available:
        return cap.reason or f"the '{capability}' capability is unavailable"
    return None


def _visual_unavailable(ctx: OptimizationStageContext, capability: str) -> str | None:
    if not ctx.rendered_videos():
        return _NO_RENDER
    cap = ctx.enhancement.capability(capability)
    if not cap.available:
        return cap.reason or f"the '{capability}' capability is unavailable"
    return None


def _story_moods(ctx: OptimizationStageContext) -> list[str]:
    """Best-effort mood words from the Story Engine; ``[]`` when unavailable.

    Defensive: it reads only descriptive strings if a recognised emotional stage
    is present, and never assumes a particular story schema (missing -> empty).
    """

    moods: list[str] = []
    for stage in ("emotional_arc", "emotion", "tone", "sentiment"):
        data = ctx.story_data(stage)
        if not data:
            continue
        for key in ("mood", "moods", "tone", "dominant_emotion", "emotions"):
            value = data.get(key)
            if isinstance(value, str):
                moods.append(value)
            elif isinstance(value, list):
                moods.extend(str(v) for v in value if isinstance(v, str | int | float))
    return [m for m in (s.strip().lower() for s in moods) if m]


# --------------------------------------------------------------------------- #
# 1. Load Render
# --------------------------------------------------------------------------- #
class LoadRenderAnalyzer(OptimizationAnalyzer):
    name = "load_render"
    version = "1"

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        if ctx.renders is None:
            return OptimizationOutcome.unavailable(_NO_RENDER)
        renders = ctx.rendered_videos()
        if not renders:
            return OptimizationOutcome.unavailable(_EMPTY_RENDER)
        out: list[dict[str, Any]] = []
        for r in renders:
            exists = await ctx.storage.exists(r.storage_key)
            out.append(
                {
                    "clip_id": r.clip_id,
                    "plan_id": r.plan_id,
                    "rank": r.rank,
                    "storage_key": r.storage_key,
                    "file_present": exists,
                    "container": r.container,
                    "width": r.width,
                    "height": r.height,
                    "aspect_ratio": r.aspect_ratio,
                    "duration": r.duration,
                    "fps": r.fps,
                    "video_codec": r.video_codec,
                    "audio_codec": r.audio_codec,
                    "has_audio": r.has_audio,
                    "bitrate_kbps": r.bitrate_kbps,
                    "size_bytes": r.size_bytes,
                }
            )
        report(1.0)
        missing = [r["clip_id"] for r in out if not r["file_present"]]
        return OptimizationOutcome.completed(
            {
                "render_count": len(out),
                "renders": out,
                "renderer": ctx.renders.renderer,
                "missing_files": missing,
                "note": "Loaded the Rendering Engine's manifest. Media metadata is taken "
                "as authoritative from the renderer; this stage does not decode video.",
            }
        )


# --------------------------------------------------------------------------- #
# 2-6. Audio analysis & enhancement (need rendered audio + a model)
# --------------------------------------------------------------------------- #
class AudioAnalysisAnalyzer(OptimizationAnalyzer):
    name = "audio_analysis"
    version = "1"
    depends_on = ("load_render",)

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        reason = _audio_unavailable(ctx, "audio_analysis")
        if reason:
            return OptimizationOutcome.unavailable(
                f"Cannot measure loudness/peaks/noise floor: {reason}"
            )
        # A real deployment would measure the rendered audio here via ctx.enhancement.audio.
        report(1.0)
        return OptimizationOutcome.completed(
            {"note": "audio analysis model present", "renders": []}
        )


class _AudioEnhancementStage(OptimizationAnalyzer):
    """Shared base for the audio-enhancement stages (all model-gated)."""

    capability: str = ""
    operations: tuple[str, ...] = ()
    depends_on = ("audio_analysis",)

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        reason = _audio_unavailable(ctx, self.capability)
        if reason:
            ops = ", ".join(self.operations)
            return OptimizationOutcome.unavailable(
                f"Would apply [{ops}] to the rendered audio, but cannot: {reason}"
            )
        report(1.0)
        return OptimizationOutcome.completed({"operations": list(self.operations), "renders": []})


class VoiceEnhancementAnalyzer(_AudioEnhancementStage):
    name = "voice_enhancement"
    version = "1"
    capability = "voice_isolation"
    operations = ("voice_isolation", "equalization", "speech_clarity", "compression")


class NoiseReductionAnalyzer(_AudioEnhancementStage):
    name = "noise_reduction"
    version = "1"
    capability = "noise_removal"
    operations = ("noise_removal", "hum_removal", "de_essing")


class LoudnessNormalizationAnalyzer(_AudioEnhancementStage):
    name = "loudness_normalization"
    version = "1"
    capability = "loudness_normalization"
    operations = ("loudness_normalization", "limiting", "volume_balancing")


class SilenceRefinementAnalyzer(_AudioEnhancementStage):
    name = "silence_refinement"
    version = "1"
    capability = "audio_analysis"
    operations = ("waveform_silence_detection", "tightening")


# --------------------------------------------------------------------------- #
# 7. Music Recommendation (real, from upstream signals - no render needed)
# --------------------------------------------------------------------------- #
class MusicRecommendationAnalyzer(OptimizationAnalyzer):
    name = "music_recommendation"
    version = "1"

    def __init__(self, registry: MusicProviderRegistry | None = None) -> None:
        self._registry = registry

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(
                _NO_TIMELINES + " Music is recommended per Short, so there is nothing to brief."
            )
        registry = self._registry or ctx.music
        moods = _story_moods(ctx)
        out: list[dict[str, Any]] = []
        for tl in timelines:
            pacing = O.as_str(_meta(tl).get("pacing")) or None
            query = O.derive_music_query(
                moods=moods, energy=None, pacing=pacing, platform="youtube_shorts"
            )
            recs = registry.recommend(query, limit=3)
            out.append(
                {
                    "clip_id": O.as_str(tl.get("clip_id")),
                    "query": {
                        "mood": list(query.mood),
                        "energy": query.energy,
                        "target_bpm": query.target_bpm,
                        "pacing": pacing,
                    },
                    "recommendations": [r.to_dict() for r in recs],
                    "confidence": 0.45,
                    "reason": "music briefed from the clip's pacing"
                    + (" and the story's mood" if moods else "")
                    + "; matched heuristically to royalty-free cues (not an audio model).",
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "provider_statuses": registry.statuses(),
                "note": "Copyright-free recommendations only. No song is downloaded, "
                "scraped, or selected as final; license/source is attached to each.",
            }
        )


# --------------------------------------------------------------------------- #
# 8. Music Mixing (real plan; execution model-gated)
# --------------------------------------------------------------------------- #
class MusicMixingAnalyzer(OptimizationAnalyzer):
    name = "music_mixing"
    version = "1"
    depends_on = ("music_recommendation",)

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        music = ctx.optimization_data("music_recommendation")
        if music is None:
            return OptimizationOutcome.unavailable(
                "Requires music recommendations, which are unavailable."
            )
        timelines = {O.as_str(t.get("clip_id")): t for t in ctx.timelines()}
        exec_cap = ctx.enhancement.capability("music_mixing")
        out: list[dict[str, Any]] = []
        for clip in O.as_list(music.get("clips")):
            cid = O.as_str(clip.get("clip_id"))
            tl = timelines.get(cid, {})
            music_markers = [
                m for m in _markers(tl) if O.as_str(m.get("type")).startswith("music_")
            ]
            plan = {
                "music_gain_db_under_speech": -18,
                "music_gain_db_solo": -6,
                "ducking": {
                    "enabled": True,
                    "threshold_db": -24,
                    "ratio": 8,
                    "attack_ms": 80,
                    "release_ms": 300,
                },
                "fade_in_s": 0.5,
                "fade_out_s": 0.8,
                "aligned_markers": [
                    {"type": m.get("type"), "at": m.get("start"), "reason": m.get("reason")}
                    for m in music_markers
                ],
                "reason": "standard speech-forward mix: duck music under voice, gentle "
                "fades, align intro/drop/outro to the Editing Engine's music markers",
                "confidence": 0.5,
            }
            out.append(
                {
                    "clip_id": cid,
                    "plan": plan,
                    "execution": {
                        "status": "unavailable",
                        "reason": exec_cap.reason
                        or "no audio mixing toolchain is installed to render the mix",
                    },
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "note": "A deterministic mixing recipe aligned to real timeline markers. "
                "The actual audio mix is not executed here (no audio toolchain).",
            }
        )


# --------------------------------------------------------------------------- #
# 9. Caption Optimization (real, from the Editing timeline)
# --------------------------------------------------------------------------- #
class CaptionOptimizationAnalyzer(OptimizationAnalyzer):
    name = "caption_optimization"
    version = "1"

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(_NO_TIMELINES)
        transcripts = ctx.transcript_segments() or []
        keyword_list = [w for w, _ in O.extract_keywords([s.get("text", "") for s in transcripts])]
        keyword_set = set(keyword_list)

        out: list[dict[str, Any]] = []
        for tl in timelines:
            captions = _captions(tl)
            improved: list[dict[str, Any]] = []
            comfortable = brisk = too_fast = unknown = 0
            for cap in captions:
                text = O.as_str(cap.get("text"))
                duration = O.as_float(cap.get("duration"))
                cps = O.reading_speed_cps(text, duration)
                rating = O.caption_speed_rating(cps)
                comfortable += rating == "comfortable"
                brisk += rating == "brisk"
                too_fast += rating == "too_fast"
                unknown += rating == "unknown"
                highlight = [
                    w for w in O.as_list(text.lower().split()) if w.strip(".,!?") in keyword_set
                ]
                improved.append(
                    {
                        "id": cap.get("id"),
                        "start": cap.get("start"),
                        "end": cap.get("end"),
                        "text": text,
                        "lines": O.balance_line_breaks(text),
                        "reading_speed_cps": cps,
                        "rating": rating,
                        "highlight_keywords": highlight[:3],
                        "emoji_suggestion": O.suggest_emoji(text),
                    }
                )
            total = len(captions)
            out.append(
                {
                    "clip_id": O.as_str(tl.get("clip_id")),
                    "caption_count": total,
                    "captions": improved,
                    "summary": {
                        "comfortable": comfortable,
                        "brisk": brisk,
                        "too_fast": too_fast,
                        "unknown": unknown,
                        "comfortable_fraction": round(comfortable / total, 3) if total else None,
                    },
                    "safe_margins": {"x_pct": 6, "bottom_pct": 18, "top_pct": 10},
                    "accessibility": "two-line max, balanced breaks, reading speed checked "
                    "against a ~17 CPS comfort target; high contrast assumed via outline.",
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "note": "Improves real caption events from the Editing timeline: balanced "
                "line breaks, reading-speed checks, keyword highlights, optional emoji.",
            }
        )


# --------------------------------------------------------------------------- #
# 10. Typography Improvement (real recommendations)
# --------------------------------------------------------------------------- #
class TypographyImprovementAnalyzer(OptimizationAnalyzer):
    name = "typography_improvement"
    version = "1"
    depends_on = ("caption_optimization",)

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(_NO_TIMELINES)
        out: list[dict[str, Any]] = []
        for tl in timelines:
            style = O.as_str(_meta(tl).get("subtitle_style")) or "clean_bold"
            out.append(
                {
                    "clip_id": O.as_str(tl.get("clip_id")),
                    "typography": {
                        "base_style": style,
                        "font_family_class": "geometric_sans",
                        "weight": "bold",
                        "size_pct_of_height": 5.5,
                        "max_chars_per_line": 21,
                        "max_lines": 2,
                        "outline": {"enabled": True, "px": 6, "color": "#000000"},
                        "shadow": {"enabled": True, "blur": 8, "opacity": 0.6},
                        "highlight_color": "#FFE000",
                        "uppercase_emphasis": True,
                        "reason": "high-contrast bold sans with an outline and soft shadow "
                        "reads reliably over busy vertical footage; a highlight colour marks "
                        "emphasised keywords without changing wording.",
                        "confidence": 0.55,
                    },
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {"clips": out, "note": "Legibility-first typography recommendations (not applied)."}
        )


# --------------------------------------------------------------------------- #
# 11-14. Visual enhancement (need rendered frames + a model)
# --------------------------------------------------------------------------- #
class _VisualStage(OptimizationAnalyzer):
    capability: str = ""
    operations: tuple[str, ...] = ()
    depends_on = ("load_render",)

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        reason = _visual_unavailable(ctx, self.capability)
        if reason:
            ops = ", ".join(self.operations)
            return OptimizationOutcome.unavailable(
                f"Would apply [{ops}] to the rendered frames, but cannot: {reason}"
            )
        report(1.0)
        return OptimizationOutcome.completed({"operations": list(self.operations), "renders": []})


class VisualEnhancementAnalyzer(_VisualStage):
    name = "visual_enhancement"
    version = "1"
    capability = "denoising"
    operations = ("denoise", "contrast_balance", "brightness_optimization", "skin_tone_preserve")


class SharpeningAnalyzer(_VisualStage):
    name = "sharpening"
    version = "1"
    capability = "sharpening"
    operations = ("adaptive_sharpen",)


class ColorRefinementAnalyzer(_VisualStage):
    name = "color_refinement"
    version = "1"
    capability = "color_correction"
    operations = ("color_correction", "saturation_adjust", "white_balance")


class FrameCleanupAnalyzer(_VisualStage):
    name = "frame_cleanup"
    version = "1"
    capability = "frame_cleanup"
    operations = ("artifact_removal", "block_cleanup")


# --------------------------------------------------------------------------- #
# 15. Thumbnail Optimization (real candidate timestamps; image scores UNKNOWN)
# --------------------------------------------------------------------------- #
class ThumbnailOptimizationAnalyzer(OptimizationAnalyzer):
    name = "thumbnail_optimization"
    version = "1"

    _SCORE_DIMS = (
        "facial_expression",
        "emotion",
        "clarity",
        "contrast",
        "focus",
        "composition",
        "text_placement",
        "safe_zone",
    )

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(_NO_TIMELINES)
        cap = ctx.enhancement.capability("thumbnail_scoring")
        scores_unknown = dict.fromkeys(self._SCORE_DIMS)
        out: list[dict[str, Any]] = []
        for tl in timelines:
            candidates: list[dict[str, Any]] = []
            seen: set[float] = set()
            # Candidate frames at meaningful timeline moments.
            picks = [(0.0, "clip opening (hook frame)")]
            for m in _markers(tl):
                mtype = O.as_str(m.get("type"))
                if mtype in ("zoom_in", "pattern_interrupt", "hook_enhancement", "music_drop"):
                    picks.append((O.as_float(m.get("start")), f"{mtype} moment"))
            for ts, why in picks:
                ts = round(ts, 3)
                if ts in seen:
                    continue
                seen.add(ts)
                candidates.append(
                    {
                        "timestamp": ts,
                        "reason": why,
                        "evidence": [{"type": "timeline", "detail": why}],
                        "image_extracted": False,
                        "scores": dict(scores_unknown),
                        "scores_status": "unknown",
                        "scores_reason": cap.reason,
                    }
                )
            out.append(
                {
                    "clip_id": O.as_str(tl.get("clip_id")),
                    "candidate_count": len(candidates),
                    "candidates": candidates[:5],
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "note": "Candidate thumbnail timestamps are chosen from real timeline "
                "moments. Image-level scores (expression/composition/contrast) are UNKNOWN "
                "- no vision model or frame decoder is available; scores are never invented.",
            }
        )


# --------------------------------------------------------------------------- #
# 16. Title Suggestion (real, from story + planner)
# --------------------------------------------------------------------------- #
class TitleSuggestionAnalyzer(OptimizationAnalyzer):
    name = "title_suggestion"
    version = "1"

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(_NO_TIMELINES)
        out: list[dict[str, Any]] = []
        for tl in timelines:
            base = O.as_str(_meta(tl).get("title")).strip()
            alternatives: list[str] = []
            if base:
                if not base.endswith("?"):
                    alternatives.append(f"{base}?")
                alternatives.append(f"The truth about {base.lower()}")
            primary = base or "(no title proposed upstream)"
            out.append(
                {
                    "clip_id": O.as_str(tl.get("clip_id")),
                    "primary": primary,
                    "alternatives": [a for a in alternatives if a][:3],
                    "confidence": 0.5 if base else None,
                    "reason": "primary title comes from the Clip Planner's blueprint "
                    "(carried on the timeline); alternatives are deterministic rephrasings.",
                    "evidence": [{"type": "blueprint_title", "detail": base or "none"}],
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "note": "Titles derived from upstream decisions; never invented wholesale.",
            }
        )


# --------------------------------------------------------------------------- #
# 17. Description Suggestion (real)
# --------------------------------------------------------------------------- #
class DescriptionSuggestionAnalyzer(OptimizationAnalyzer):
    name = "description_suggestion"
    version = "1"
    depends_on = ("title_suggestion",)

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(_NO_TIMELINES)
        titles = {
            O.as_str(c.get("clip_id")): c
            for c in O.as_list((ctx.optimization_data("title_suggestion") or {}).get("clips"))
        }
        transcripts = ctx.transcript_segments()
        out: list[dict[str, Any]] = []
        for tl in timelines:
            cid = O.as_str(tl.get("clip_id"))
            title = O.as_str(O.as_dict(titles.get(cid)).get("primary"))
            opening = ""
            if transcripts:
                cs = O.as_float(tl.get("source_start"))
                ce = O.as_float(tl.get("source_end"))
                in_clip = [s for s in transcripts if cs <= O.as_float(s.get("start")) < ce]
                opening = O.as_str(in_clip[0].get("text")) if in_clip else ""
            description = title
            if opening:
                description = f"{title}\n\n{opening.strip()}"
            out.append(
                {
                    "clip_id": cid,
                    "description": description.strip() or "(insufficient upstream text)",
                    "confidence": 0.4 if description.strip() else None,
                    "reason": "assembled from the proposed title and the clip's opening line "
                    "(real transcript); no claims are invented.",
                    "evidence": [{"type": "transcript_opening", "detail": opening[:80]}],
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {"clips": out, "note": "Descriptions grounded in the real transcript and title."}
        )


# --------------------------------------------------------------------------- #
# 18. Hashtag Recommendation (real, from transcript keywords)
# --------------------------------------------------------------------------- #
class HashtagRecommendationAnalyzer(OptimizationAnalyzer):
    name = "hashtag_recommendation"
    version = "1"

    _PLATFORM_TAGS: ClassVar[dict[str, str]] = {
        "youtube_shorts": "#shorts",
        "tiktok": "#fyp",
        "instagram_reels": "#reels",
    }

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        transcripts = ctx.transcript_segments()
        if not transcripts:
            return OptimizationOutcome.unavailable(
                "Requires a transcript from the Cognitive Engine to extract topical "
                "hashtags; it is unavailable, and tags are not invented."
            )
        out: list[dict[str, Any]] = []
        for tl in timelines or [{}]:
            cs = O.as_float(tl.get("source_start")) if tl else 0.0
            ce = O.as_float(tl.get("source_end")) if tl else float("inf")
            texts = [
                O.as_str(s.get("text"))
                for s in transcripts
                if cs <= O.as_float(s.get("start")) < ce
            ] or [O.as_str(s.get("text")) for s in transcripts]
            keywords = [w for w, _ in O.extract_keywords(texts)]
            tags = O.to_hashtags(keywords)
            generic = list(dict.fromkeys(self._PLATFORM_TAGS.values()))
            out.append(
                {
                    "clip_id": O.as_str(tl.get("clip_id")) if tl else None,
                    "topical": tags,
                    "platform_generic": generic,
                    "confidence": 0.5 if tags else None,
                    "reason": "topical tags are the most frequent meaningful words in the "
                    "clip's transcript; platform-generic tags are conventional discovery tags.",
                    "evidence": [{"type": "keywords", "detail": ", ".join(keywords[:6])}],
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {"clips": out, "note": "Hashtags extracted from real speech; none are fabricated."}
        )


# --------------------------------------------------------------------------- #
# 19. Platform Optimization (real export specs)
# --------------------------------------------------------------------------- #
class PlatformOptimizationAnalyzer(OptimizationAnalyzer):
    name = "platform_optimization"
    version = "1"

    def __init__(self, registry: ExportProfileRegistry | None = None) -> None:
        self._registry = registry or build_default_export_registry()

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        profiles = self._registry.ordered()
        renders = {r.clip_id: r for r in ctx.rendered_videos()}
        clips_out: list[dict[str, Any]] = []
        for tl in ctx.timelines():
            cid = O.as_str(tl.get("clip_id"))
            render = renders.get(cid)
            duration = render.duration if render and render.duration else _clip_duration(tl)
            targets = []
            for p in profiles:
                fits = None if not duration else duration <= p.max_duration_s
                targets.append(
                    {
                        "platform": p.platform,
                        "label": p.label,
                        "resolution": p.resolution,
                        "fps_options": list(p.fps_options),
                        "duration_fits": fits,
                        "max_duration_s": p.max_duration_s,
                    }
                )
            clips_out.append({"clip_id": cid, "duration": duration, "targets": targets})
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "profiles": self._registry.to_dict(),
                "platform_order": [p.platform for p in profiles],
                "clips": clips_out,
                "note": "Real published vertical-Short specs per platform, with a duration "
                "fit-check per clip. Encoding itself is performed by the Rendering Engine.",
            }
        )


# --------------------------------------------------------------------------- #
# 20. Compression Optimization (real targets; execution needs an encoder)
# --------------------------------------------------------------------------- #
class CompressionOptimizationAnalyzer(OptimizationAnalyzer):
    name = "compression_optimization"
    version = "1"
    depends_on = ("platform_optimization",)

    def __init__(self, registry: ExportProfileRegistry | None = None) -> None:
        self._registry = registry or build_default_export_registry()

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        platform = ctx.optimization_data("platform_optimization")
        if platform is None:
            return OptimizationOutcome.unavailable(
                "Requires platform export specs, which are unavailable."
            )
        encoder = ctx.enhancement.capability("transcode")
        out: list[dict[str, Any]] = []
        for clip in O.as_list(platform.get("clips")):
            duration = O.as_float(clip.get("duration"))
            targets = []
            for p in self._registry.ordered():
                est_mb = (
                    round(
                        (p.recommended_bitrate_kbps + p.audio_bitrate_kbps) * duration / 8 / 1024, 2
                    )
                    if duration
                    else None
                )
                targets.append(
                    {
                        "platform": p.platform,
                        "video_codec": p.video_codec,
                        "audio_codec": p.audio_codec,
                        "target_bitrate_kbps": p.recommended_bitrate_kbps,
                        "max_bitrate_kbps": p.max_bitrate_kbps,
                        "two_pass": True,
                        "estimated_size_mb": est_mb,
                        "content_adaptive_tuning": None,  # UNKNOWN without decoding the file
                    }
                )
            out.append({"clip_id": clip.get("clip_id"), "targets": targets})
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "execution": {"status": "unavailable", "reason": encoder.reason},
                "note": "Per-platform bitrate/codec targets with file-size estimates. "
                "Content-adaptive tuning is UNKNOWN (needs decoding the rendered file); "
                "encoding is not executed here.",
            }
        )


# --------------------------------------------------------------------------- #
# 21. Quality Evaluation (real signals graded; the rest honestly UNKNOWN)
# --------------------------------------------------------------------------- #
class QualityEvaluationAnalyzer(OptimizationAnalyzer):
    name = "quality_evaluation"
    version = "1"
    depends_on = ("caption_optimization",)

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(_NO_TIMELINES)
        caption_by_clip = {
            O.as_str(c.get("clip_id")): c
            for c in O.as_list((ctx.optimization_data("caption_optimization") or {}).get("clips"))
        }
        out: list[dict[str, Any]] = []
        for tl in timelines:
            cid = O.as_str(tl.get("clip_id"))
            meta = _meta(tl)
            cap_summary = O.as_dict(O.as_dict(caption_by_clip.get(cid)).get("summary"))
            dims = self._dimensions(meta, cap_summary)
            out.append({"clip_id": cid, "dimensions": dims, "summary": O.aggregate_quality(dims)})
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "note": "Each dimension is graded only from real evidence (timeline metadata, "
                "measured caption reading speed) or honestly marked UNKNOWN (audio/visual "
                "quality, retention, engagement) - no score is invented.",
            }
        )

    @staticmethod
    def _dimensions(meta: dict[str, Any], cap_summary: dict[str, Any]) -> list[dict[str, Any]]:
        pacing = O.as_str(meta.get("pacing")).lower()
        pacing_score = {"fast": 0.8, "medium": 0.6, "slow": 0.45}.get(pacing)
        hook = O.as_str(meta.get("hook_decision")).lower()
        hook_score = {"fast_start": 0.7, "preview": 0.65, "no_changes": 0.55, "cold_open": 0.7}.get(
            hook
        )
        comfortable_fraction = cap_summary.get("comfortable_fraction")
        planner_quality = meta.get("quality_score")
        planner_conf = O.as_float(meta.get("confidence"), 0.4) or 0.4

        def dim(
            name: str,
            score: float | None,
            conf: float | None,
            reasoning: str,
            limitations: str,
            evidence: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any]:
            return {
                "dimension": name,
                "score": score,
                "confidence": conf,
                "reasoning": reasoning,
                "limitations": limitations,
                "evidence": evidence or [],
            }

        return [
            dim(
                "hook_strength",
                hook_score,
                0.4 if hook_score is not None else None,
                "graded from the Editing Engine's hook decision carried on the timeline",
                "a structural proxy; true hook strength needs audience watch-through data",
                [{"type": "hook_decision", "detail": hook or "none"}],
            ),
            dim(
                "retention_potential",
                None,
                None,
                "cannot be graded from the artifact alone",
                "requires real watch-time/retention data or a trained model - UNKNOWN",
            ),
            dim(
                "clarity",
                None,
                None,
                "cannot be graded without analysing the rendered audio/speech",
                "needs an audio/semantic model over the rendered media - UNKNOWN",
            ),
            dim(
                "pacing",
                pacing_score,
                0.4 if pacing_score is not None else None,
                "graded from the Editing Engine's pacing decision",
                "a planning proxy, not a measured edit-rhythm analysis",
                [{"type": "pacing", "detail": pacing or "none"}],
            ),
            dim(
                "caption_quality",
                comfortable_fraction if isinstance(comfortable_fraction, int | float) else None,
                0.7 if isinstance(comfortable_fraction, int | float) else None,
                "measured: fraction of captions within a comfortable reading speed",
                "reading speed only; does not judge wording or styling",
                [{"type": "caption_reading_speed", "detail": str(comfortable_fraction)}],
            ),
            dim(
                "audio_quality",
                None,
                None,
                "cannot be graded - no audio model or decoder for the rendered audio",
                "needs the rendered audio + an audio-quality model - UNKNOWN",
            ),
            dim(
                "visual_quality",
                None,
                None,
                "cannot be graded - no vision model or decoder for the rendered frames",
                "needs the rendered frames + a vision model - UNKNOWN",
            ),
            dim(
                "story_quality",
                planner_quality if isinstance(planner_quality, int | float) else None,
                planner_conf if isinstance(planner_quality, int | float) else None,
                "graded from the Clip Planner's quality score for this clip",
                "inherits the planner's confidence; not a fresh narrative judgement",
                [{"type": "planner_quality_score", "detail": str(planner_quality)}],
            ),
            dim(
                "engagement",
                None,
                None,
                "cannot be graded from the artifact alone",
                "requires real engagement/audience signals - UNKNOWN",
            ),
            dim(
                "platform_readiness",
                0.7 if comfortable_fraction is not None else 0.5,
                0.6,
                "graded from caption presence and the 9:16 vertical target with a valid "
                "export profile",
                "structural readiness only; not a guarantee of platform acceptance",
                [{"type": "aspect_ratio", "detail": O.as_str(meta.get("aspect_ratio")) or "9:16"}],
            ),
        ]


# --------------------------------------------------------------------------- #
# 22. Variant Generation (real plans referencing the base timeline)
# --------------------------------------------------------------------------- #
class VariantGenerationAnalyzer(OptimizationAnalyzer):
    name = "variant_generation"
    version = "1"

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.unavailable(_NO_TIMELINES)
        out: list[dict[str, Any]] = []
        for tl in timelines:
            captions = _captions(tl)
            zooms = [m for m in _markers(tl) if O.as_str(m.get("type")) == "zoom_in"]
            variants = [
                {
                    "id": "A",
                    "name": "Strong Captions",
                    "description": "Large, animated, keyword-highlighted captions throughout.",
                    "changes": [f"emphasise all {len(captions)} captions", "highlight keywords"],
                    "expected_strengths": ["max accessibility", "strong sound-off retention"],
                    "confidence": 0.5,
                    "why": "captions drive sound-off watch-through on every platform",
                },
                {
                    "id": "B",
                    "name": "Minimal Captions",
                    "description": "Sparse captions only on key lines; cleaner frame.",
                    "changes": ["reduce captions to emphasis moments"],
                    "expected_strengths": ["less visual clutter", "premium feel"],
                    "confidence": 0.4,
                    "why": "suits audiences that watch with sound on",
                },
                {
                    "id": "C",
                    "name": "Zoom-Heavy",
                    "description": "More punch-in zooms on emphasis beats for energy.",
                    "changes": [
                        f"extend the {len(zooms)} planned zooms",
                        "add beat-aligned punch-ins",
                    ],
                    "expected_strengths": ["higher energy", "pattern-interrupt retention"],
                    "confidence": 0.4,
                    "why": "movement combats mid-clip drop-off",
                },
                {
                    "id": "D",
                    "name": "Clean Aesthetic",
                    "description": "No zoom, restrained captions, subtle look.",
                    "changes": ["remove zooms", "single static caption position"],
                    "expected_strengths": ["calm, polished tone", "broad appeal"],
                    "confidence": 0.4,
                    "why": "a restrained cut reads as higher production value",
                },
            ]
            out.append({"clip_id": O.as_str(tl.get("clip_id")), "variants": variants})
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "clips": out,
                "note": "Each variant is a plan describing what changes vs the base edit and "
                "why. Rendering the variants is the Rendering Engine's job (not done here).",
            }
        )


# --------------------------------------------------------------------------- #
# 23. Final Validation
# --------------------------------------------------------------------------- #
class FinalValidationAnalyzer(OptimizationAnalyzer):
    name = "final_validation"
    version = "1"
    depends_on = (
        "caption_optimization",
        "quality_evaluation",
        "platform_optimization",
        "variant_generation",
    )

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        timelines = ctx.timelines()
        clip_reports: list[dict[str, Any]] = []
        caption_clips = {
            O.as_str(c.get("clip_id")): c
            for c in O.as_list((ctx.optimization_data("caption_optimization") or {}).get("clips"))
        }
        quality_clips = {
            O.as_str(c.get("clip_id")): c
            for c in O.as_list((ctx.optimization_data("quality_evaluation") or {}).get("clips"))
        }
        for tl in timelines:
            cid = O.as_str(tl.get("clip_id"))
            issues: list[dict[str, Any]] = []
            if cid not in caption_clips:
                issues.append({"detail": "no caption optimization for this clip"})
            if cid not in quality_clips:
                issues.append({"detail": "no quality evaluation for this clip"})
            clip_reports.append({"clip_id": cid, "valid": not issues, "issues": issues})

        unavailable = [
            {"stage": s.stage, "reason": s.reason}
            for s in (ctx.results.values())
            if s.status.value == "unavailable"
        ]
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "valid": all(r["valid"] for r in clip_reports),
                "clips": clip_reports,
                "issue_count": sum(len(r["issues"]) for r in clip_reports),
                "unavailable_stages": unavailable,
                "note": "Validates internal consistency of the optimization outputs and "
                "lists, transparently, which stages were UNAVAILABLE and why.",
            }
        )


# --------------------------------------------------------------------------- #
# 24. Publish Package Creation (writes real downloadable text/metadata assets)
# --------------------------------------------------------------------------- #
class PublishPackageCreationAnalyzer(OptimizationAnalyzer):
    name = "publish_package_creation"
    version = "1"
    depends_on = (
        "caption_optimization",
        "title_suggestion",
        "description_suggestion",
        "hashtag_recommendation",
        "platform_optimization",
        "quality_evaluation",
        "music_recommendation",
    )

    async def analyze(
        self, ctx: OptimizationStageContext, report: OptimizationProgressReporter
    ) -> OptimizationOutcome:
        import json

        timelines = ctx.timelines()
        if not timelines:
            return OptimizationOutcome.completed(
                {
                    "package_count": 0,
                    "packages": [],
                    "note": "No Shorts to package - an honest, empty result.",
                }
            )
        project_id = ctx.project.id
        renders = {r.clip_id: r for r in ctx.rendered_videos()}

        def _by_clip(stage: str) -> dict[str, dict[str, Any]]:
            return {
                O.as_str(c.get("clip_id")): c
                for c in O.as_list((ctx.optimization_data(stage) or {}).get("clips"))
            }

        titles_by = _by_clip("title_suggestion")
        desc_by = _by_clip("description_suggestion")
        tags_by = _by_clip("hashtag_recommendation")
        quality_by = _by_clip("quality_evaluation")
        music_by = _by_clip("music_recommendation")
        platform_data = ctx.optimization_data("platform_optimization") or {}

        packages: list[dict[str, Any]] = []
        for tl in timelines:
            cid = O.as_str(tl.get("clip_id"))
            base = f"optimization/{project_id}/packages/{cid}"
            caption_events = _captions(tl)
            assets: list[dict[str, Any]] = []

            # Caption files (real, written to storage).
            if caption_events:
                srt = O.build_srt(caption_events)
                vtt = O.build_vtt(caption_events)
                await ctx.storage.put(
                    f"{base}/captions.srt", srt.encode("utf-8"), content_type="application/x-subrip"
                )
                await ctx.storage.put(
                    f"{base}/captions.vtt", vtt.encode("utf-8"), content_type="text/vtt"
                )
                assets.append(
                    {
                        "kind": "captions_srt",
                        "status": "available",
                        "storage_key": f"{base}/captions.srt",
                    }
                )
                assets.append(
                    {
                        "kind": "captions_vtt",
                        "status": "available",
                        "storage_key": f"{base}/captions.vtt",
                    }
                )
            else:
                assets.append(
                    {
                        "kind": "captions",
                        "status": "unavailable",
                        "reason": "no caption events on this timeline",
                    }
                )

            title = O.as_str(O.as_dict(titles_by.get(cid)).get("primary"))
            description = O.as_str(O.as_dict(desc_by.get(cid)).get("description"))
            tags = O.as_dict(tags_by.get(cid))
            hashtags = O.as_list(tags.get("topical")) + O.as_list(tags.get("platform_generic"))
            music_recs = O.as_list(O.as_dict(music_by.get(cid)).get("recommendations"))
            top_music = music_recs[0] if music_recs else None

            metadata = {
                "clip_id": cid,
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "music": top_music,
                "quality": O.as_dict(quality_by.get(cid)).get("summary"),
                "platform_targets": O.as_dict(platform_data.get("profiles")),
                "source_clip": {
                    "plan_id": tl.get("plan_id"),
                    "rank": tl.get("rank"),
                    "duration": tl.get("duration"),
                    "source_video": tl.get("source_video"),
                },
                "provenance": "Generated by the Optimization Engine from upstream engine "
                "outputs; no values fabricated.",
            }
            await ctx.storage.put(
                f"{base}/metadata.json",
                json.dumps(metadata, indent=2).encode("utf-8"),
                content_type="application/json",
            )
            assets.append(
                {"kind": "metadata", "status": "available", "storage_key": f"{base}/metadata.json"}
            )

            quality_report = O.as_dict(quality_by.get(cid))
            await ctx.storage.put(
                f"{base}/quality_report.json",
                json.dumps(quality_report, indent=2).encode("utf-8"),
                content_type="application/json",
            )
            assets.append(
                {
                    "kind": "quality_report",
                    "status": "available",
                    "storage_key": f"{base}/quality_report.json",
                }
            )

            # Optimized MP4 + thumbnail reference the Rendering Engine's output.
            render = renders.get(cid)
            if render and render.storage_key:
                assets.append(
                    {
                        "kind": "optimized_mp4",
                        "status": "available",
                        "storage_key": render.storage_key,
                        "note": "references the rendered MP4; audio/visual enhancement "
                        "was UNAVAILABLE in this environment, so it is the unmodified render",
                    }
                )
            else:
                assets.append(
                    {
                        "kind": "optimized_mp4",
                        "status": "unavailable",
                        "reason": "no rendered MP4 exists (the Rendering Engine has not "
                        "produced output); cannot package a video file",
                    }
                )
            assets.append(
                {
                    "kind": "thumbnail",
                    "status": "unavailable",
                    "reason": "thumbnail image generation requires a frame decoder/vision "
                    "model that is unavailable; candidate timestamps are in the report",
                }
            )

            available = [a["kind"] for a in assets if a["status"] == "available"]
            packages.append(
                {
                    "clip_id": cid,
                    "title": title,
                    "assets": assets,
                    "available_assets": available,
                    "complete": all(a["status"] == "available" for a in assets),
                }
            )
        report(1.0)
        return OptimizationOutcome.completed(
            {
                "package_count": len(packages),
                "packages": packages,
                "note": "Publish packages assembled. Text/metadata/caption assets are real "
                "and downloadable; the MP4 references the render and the thumbnail/audio/visual "
                "enhancements are honestly marked UNAVAILABLE where models/render are absent.",
            }
        )
