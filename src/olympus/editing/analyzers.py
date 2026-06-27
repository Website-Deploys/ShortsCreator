"""The sixteen Editing Engine stages.

Each stage is an isolated, replaceable module behind the :class:`EditingAnalyzer`
contract. None imports another; they communicate only through the structured
:class:`EditingStageContext`. Together they transform the Clip Planner's approved
blueprints into real, professional, non-destructive edit timelines (one per
clip), then validate them.

Honesty rules (enforced by construction):
- When the inputs needed to build a timeline are missing (no approved clips / no
  transcript), a stage returns ``UNAVAILABLE`` with a detailed reason.
- A single decision that cannot be determined (e.g. pans without subject
  tracking, audio beats without an audio model) is recorded as ``UNKNOWN`` -
  never guessed.
- Every event is clip-relative, timestamped, and carries a reason, a confidence
  (``None`` = UNKNOWN), and supporting evidence. Nothing is rendered or applied.
"""

from __future__ import annotations

from typing import Any

from olympus.domain.contracts.editing import (
    EditingAnalyzer,
    EditingOutcome,
    EditingProgressReporter,
    EditingStageContext,
)
from olympus.editing import timeline as T  # noqa: N812 (module alias is intentional)

_NO_CLIPS = (
    "There are no approved clip plans to build a timeline for. The Clip Planner "
    "produced zero clips (or has not completed), so there is nothing to edit. No "
    "timeline is fabricated without an approved clip."
)
_NO_TRANSCRIPT = (
    "Requires a transcript from the Cognitive Engine, which is not available for "
    "this video. Speech-derived edits cannot be determined without it."
)
_LONG_PAUSE = 0.6
_DEAD_AIR = 1.5
_SILENCE_GAP = 0.35


# --------------------------------------------------------------------------- #
# Shared, pure helpers
# --------------------------------------------------------------------------- #
def _clips(ctx: EditingStageContext) -> list[dict[str, Any]] | None:
    """The base clips from timeline initialization, or ``None`` if unavailable."""

    init = ctx.editing_data("timeline_initialization")
    if init is None:
        return None
    return T.as_list(init.get("clips"))


def _plans_by_id(ctx: EditingStageContext) -> dict[str, dict[str, Any]]:
    return {T.as_str(p.get("id")): p for p in ctx.approved_plans()}


def _window(clip: dict[str, Any]) -> tuple[float, float, float]:
    start = T.as_float(clip.get("source_start"))
    end = T.as_float(clip.get("source_end"))
    return start, end, T.as_float(clip.get("duration"), end - start)


def _blueprint(plans: dict[str, dict[str, Any]], clip_id: str) -> dict[str, Any]:
    return T.as_dict(T.as_dict(plans.get(clip_id)).get("blueprint"))


def _per_clip(
    ctx: EditingStageContext,
) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Any]]]:
    return _clips(ctx), _plans_by_id(ctx)


# --------------------------------------------------------------------------- #
# 1. Timeline Initialization - one base timeline per approved clip.
# --------------------------------------------------------------------------- #
class TimelineInitializationAnalyzer(EditingAnalyzer):
    name = "timeline_initialization"
    version = "1"

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        plans = ctx.approved_plans()
        if not plans:
            return EditingOutcome.unavailable(_NO_CLIPS)
        fps = ctx.fps()
        clips: list[dict[str, Any]] = []
        for plan in plans:
            start = T.as_float(plan.get("start"))
            end = T.as_float(plan.get("end"))
            duration = T.as_float(plan.get("duration"), end - start)
            confidence = T.as_float(plan.get("confidence"))
            clips.append(
                {
                    "clip_id": T.as_str(plan.get("id")),
                    "plan_id": T.as_str(plan.get("id")),
                    "rank": plan.get("rank"),
                    "source_video": T.as_dict(plan.get("source_video")),
                    "source_start": T.round3(start),
                    "source_end": T.round3(end),
                    "duration": T.round3(duration),
                    "fps": fps,
                    "start_frame": plan.get("start_frame"),
                    "end_frame": plan.get("end_frame"),
                    "quality_score": T.as_float(plan.get("quality_score")),
                    "confidence": confidence,
                    "base_video_event": T.event(
                        "source_clip",
                        0.0,
                        duration,
                        reason="base clip spanning the approved plan window",
                        confidence=confidence,
                        evidence=[{"type": "plan", "detail": T.as_str(plan.get("explanation"))}],
                        source_start=T.round3(start),
                        source_end=T.round3(end),
                    ),
                    "base_audio_event": T.event(
                        "source_audio",
                        0.0,
                        duration,
                        reason="clip audio, co-extensive with the base video clip",
                        confidence=confidence,
                        source_start=T.round3(start),
                        source_end=T.round3(end),
                    ),
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clip_count": len(clips),
                "clips": clips,
                "fps": fps,
                "note": "One base, non-destructive timeline per approved clip. "
                "All later events are clip-relative; source_start/source_end map "
                "each clip back to the original video for exact reproduction.",
            }
        )


# --------------------------------------------------------------------------- #
# 2. Speech Cleanup - IDENTIFY fillers / pauses / dead air (never remove).
# --------------------------------------------------------------------------- #
class SpeechCleanupAnalyzer(EditingAnalyzer):
    name = "speech_cleanup"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, duration = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            items: list[dict[str, Any]] = []
            for seg in segs:
                for word in T.find_fillers(seg["text"]):
                    items.append(
                        T.marker(
                            "filler_word",
                            seg["start"],
                            reason=f"filler/hedge '{word}' identified for optional tightening",
                            confidence=0.5,
                            evidence=[{"type": "transcript", "detail": seg["text"][:80]}],
                            word=word,
                        )
                    )
                for word in T.find_repeated_words(seg["text"]):
                    items.append(
                        T.marker(
                            "repeated_word",
                            seg["start"],
                            reason=f"immediate repetition of '{word}'",
                            confidence=0.5,
                            evidence=[{"type": "transcript", "detail": seg["text"][:80]}],
                            word=word,
                        )
                    )
            for gap in T.gaps_between(segs, duration, min_gap=_LONG_PAUSE):
                kind = "dead_air" if gap["end"] - gap["start"] >= _DEAD_AIR else "long_pause"
                items.append(
                    T.event(
                        kind,
                        gap["start"],
                        gap["end"],
                        reason="silence between speech, inferred from transcript timing",
                        confidence=0.5,
                        evidence=[{"type": "transcript_gap", "detail": "no speech in interval"}],
                    )
                )
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "items": items,
                    "breathing": {
                        "status": "unknown",
                        "reason": "breath detection requires audio-waveform analysis, "
                        "which is unavailable; not guessed.",
                    },
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Identification only - nothing is removed. Fillers, repeats, "
                "long pauses and dead air are flagged for an editor/future engine.",
            }
        )


# --------------------------------------------------------------------------- #
# 3. Jump Cut Detection - natural cut points at sentence boundaries.
# --------------------------------------------------------------------------- #
class JumpCutDetectionAnalyzer(EditingAnalyzer):
    name = "jump_cut_detection"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, _ = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            cuts: list[dict[str, Any]] = []
            for i, seg in enumerate(segs[:-1]):
                gap = segs[i + 1]["start"] - seg["end"]
                cuts.append(
                    T.marker(
                        "jump_cut_point",
                        seg["end"],
                        reason="natural sentence boundary"
                        + (" followed by a pause" if gap >= _LONG_PAUSE else ""),
                        confidence=T.round3(min(0.9, 0.55 + gap)),
                        evidence=[{"type": "transcript", "detail": seg["text"][:80]}],
                    )
                )
            out.append({"clip_id": clip["clip_id"], "cut_points": cuts})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Candidate jump-cut points at real sentence boundaries; "
                "pauses raise confidence. Cuts are proposed, never applied.",
            }
        )


# --------------------------------------------------------------------------- #
# 4. Silence Detection - real silence intervals (inferred from transcript).
# --------------------------------------------------------------------------- #
class SilenceDetectionAnalyzer(EditingAnalyzer):
    name = "silence_detection"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, duration = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            intervals = [
                T.event(
                    "silence",
                    gap["start"],
                    gap["end"],
                    reason="no speech in interval (inferred from transcript timing, "
                    "not measured from the audio waveform)",
                    confidence=0.5,
                    evidence=[{"type": "transcript_gap", "detail": "gap between segments"}],
                )
                for gap in T.gaps_between(segs, duration, min_gap=_SILENCE_GAP)
            ]
            out.append({"clip_id": clip["clip_id"], "silences": intervals})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Silence is inferred from transcript gaps; true waveform "
                "silence requires an audio model (unavailable) - confidence kept modest.",
            }
        )


# --------------------------------------------------------------------------- #
# 5. Subtitle Segmentation - split captions at linguistic boundaries.
# --------------------------------------------------------------------------- #
class SubtitleSegmentationAnalyzer(EditingAnalyzer):
    name = "subtitle_segmentation"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        segments = ctx.transcript_segments()
        if not segments:
            return EditingOutcome.unavailable(_NO_TRANSCRIPT)

        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, ce, _ = _window(clip)
            segs = T.clip_segments(segments, cs, ce)
            chunks: list[dict[str, Any]] = []
            for i, seg in enumerate(segs):
                for piece in T.split_caption(seg["text"]):
                    chunks.append(
                        {
                            "text": piece,
                            "segment_index": i,
                            "segment_start": seg["start"],
                            "segment_end": seg["end"],
                        }
                    )
            out.append({"clip_id": clip["clip_id"], "caption_chunks": chunks})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Captions split at clause/punctuation boundaries and packed "
                "to a readable length - not at fixed time intervals.",
            }
        )


# --------------------------------------------------------------------------- #
# 6. Caption Timing - assign timing to each caption chunk.
# --------------------------------------------------------------------------- #
class CaptionTimingAnalyzer(EditingAnalyzer):
    name = "caption_timing"
    version = "1"
    depends_on = ("subtitle_segmentation",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        seg_stage = ctx.editing_data("subtitle_segmentation")
        if seg_stage is None:
            return EditingOutcome.unavailable(
                "Requires subtitle segmentation, which is unavailable."
            )
        out: list[dict[str, Any]] = []
        for clip in T.as_list(seg_stage.get("clips")):
            captions: list[dict[str, Any]] = []
            # Group chunks by their source segment so timing is distributed within it.
            by_segment: dict[int, list[dict[str, Any]]] = {}
            for chunk in T.as_list(clip.get("caption_chunks")):
                by_segment.setdefault(int(T.as_float(chunk.get("segment_index"))), []).append(chunk)
            for chunk_group in by_segment.values():
                seg_start = T.as_float(chunk_group[0].get("segment_start"))
                seg_end = T.as_float(chunk_group[0].get("segment_end"))
                texts = [T.as_str(c.get("text")) for c in chunk_group]
                for timed in T.distribute_timing(texts, seg_start, seg_end):
                    captions.append(
                        T.event(
                            "caption",
                            timed["start"],
                            timed["end"],
                            reason="caption timed within its transcript segment by word count",
                            confidence=0.7,
                            evidence=[{"type": "transcript", "detail": timed["text"][:80]}],
                            text=timed["text"],
                        )
                    )
            captions.sort(key=lambda c: c["start"])
            out.append({"clip_id": T.as_str(clip.get("clip_id")), "captions": captions})
        report(1.0)
        return EditingOutcome.completed(
            {"clips": out, "note": "Each caption gets a real start/end within its segment."}
        )


# --------------------------------------------------------------------------- #
# 7. Caption Layout - placement (face/OCR-aware where possible, else UNKNOWN).
# --------------------------------------------------------------------------- #
class CaptionLayoutAnalyzer(EditingAnalyzer):
    name = "caption_layout"
    version = "1"
    depends_on = ("caption_timing",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        timing = ctx.editing_data("caption_timing")
        if timing is None:
            return EditingOutcome.unavailable("Requires caption timing, which is unavailable.")
        faces = ctx.cognitive_data("face_detection")
        ocr = ctx.cognitive_data("ocr")
        unknowns: list[str] = []
        if faces is None:
            unknowns.append(
                "face regions (no face-detection model) - cannot verify captions avoid faces"
            )
        if ocr is None:
            unknowns.append(
                "on-screen text regions (no OCR) - cannot verify captions avoid burned-in text"
            )
        out = [
            {
                "clip_id": T.as_str(clip.get("clip_id")),
                "caption_count": len(T.as_list(clip.get("captions"))),
                "layout": {
                    "position": "lower_third",
                    "safe_margins": {"x_pct": 8, "bottom_pct": 14, "top_pct": 8},
                    "face_aware": faces is not None,
                    "ocr_aware": ocr is not None,
                    "reason": "default lower-third safe area"
                    + (
                        ""
                        if not unknowns
                        else "; UNKNOWN whether it overlaps " + "; ".join(unknowns)
                    ),
                },
            }
            for clip in T.as_list(timing.get("clips"))
        ]
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "unknowns": unknowns,
                "note": "Placement defaults to a lower-third safe area. Avoidance of "
                "faces/OCR/objects is UNKNOWN without the corresponding models.",
            }
        )


# --------------------------------------------------------------------------- #
# 8. Zoom Planner - punch-ins on emphasis moments.
# --------------------------------------------------------------------------- #
class ZoomPlannerAnalyzer(EditingAnalyzer):
    name = "zoom_planner"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            zooms: list[dict[str, Any]] = []
            for sug in T.as_list(bp.get("zoom_suggestions")):
                rel = T.to_clip_relative(T.as_float(sug.get("timestamp")), cs, duration)
                if rel is None:
                    continue
                zooms.append(
                    T.event(
                        "zoom_in",
                        rel,
                        min(duration, rel + 1.5),
                        reason=T.as_str(sug.get("reason")) or "emphasize this moment",
                        confidence=0.55,
                        evidence=[
                            {"type": "planner_emphasis", "detail": T.as_str(sug.get("reason"))}
                        ],
                        scale=1.15,
                    )
                )
            out.append({"clip_id": clip["clip_id"], "zooms": zooms})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Subtle punch-ins (~1.15x) on emphasis moments identified "
                "upstream. Magnitudes are recommendations, not applied effects.",
            }
        )


# --------------------------------------------------------------------------- #
# 9. Pan Planner - requires subject tracking; UNKNOWN without it.
# --------------------------------------------------------------------------- #
class PanPlannerAnalyzer(EditingAnalyzer):
    name = "pan_planner"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            switches = T.as_list(T.as_dict(bp.get("speaker_switches")).get("switches"))
            pans: list[dict[str, Any]] = []
            for sw in switches:
                rel = T.to_clip_relative(T.as_float(sw.get("timestamp")), cs, duration)
                if rel is None:
                    continue
                pans.append(
                    T.marker(
                        "pan_to_speaker",
                        rel,
                        reason=f"reframe toward speaker {T.as_str(sw.get('speaker'))}",
                        confidence=0.5,
                        evidence=[
                            {"type": "speaker_switch", "detail": T.as_str(sw.get("speaker"))}
                        ],
                    )
                )
            unknown = not pans
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "pans": pans,
                    "status": "unknown" if unknown else "planned",
                    "reason": None
                    if pans
                    else "pan planning needs subject/face tracking, which is "
                    "unavailable; returning UNKNOWN rather than guessing pan targets.",
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Pans are only planned where speaker-switch evidence exists; "
                "otherwise UNKNOWN (no subject-tracking model).",
            }
        )


# --------------------------------------------------------------------------- #
# 10. Crop Planner - 9:16 safe area from the source dimensions.
# --------------------------------------------------------------------------- #
class CropPlannerAnalyzer(EditingAnalyzer):
    name = "crop_planner"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        inspection = ctx.cognitive_data("video_inspection") or {}
        width = T.as_float(inspection.get("width"))
        height = T.as_float(inspection.get("height"))
        vertical = bool(height and width and height >= width)

        if not (width and height):
            crop = {
                "target_aspect": "9:16",
                "status": "unknown",
                "reason": "source dimensions are unavailable (no video inspection); "
                "the exact crop region is UNKNOWN and must be computed at render time.",
            }
        elif vertical:
            crop = {
                "target_aspect": "9:16",
                "x_offset": 0,
                "width": int(width),
                "height": int(height),
                "subject_aware": False,
                "reason": "source is already vertical; no horizontal crop needed. "
                "Subject-aware reframing is UNKNOWN (no face/object model).",
            }
        else:
            target_w = round(height * 9 / 16)
            crop = {
                "target_aspect": "9:16",
                "x_offset": max(0, round((width - target_w) / 2)),
                "width": int(target_w),
                "height": int(height),
                "subject_aware": False,
                "reason": "center 9:16 crop of a horizontal source; subject-aware "
                "reframing is UNKNOWN without a face/object model.",
            }
        out = [{"clip_id": clip["clip_id"], "crop": crop} for clip in clips]
        report(1.0)
        return EditingOutcome.completed(
            {"clips": out, "note": "9:16 safe-area crop derived from real source dimensions."}
        )


# --------------------------------------------------------------------------- #
# 11. Hook Enhancement - cold open / preview / fast start / no changes.
# --------------------------------------------------------------------------- #
class HookEnhancementAnalyzer(EditingAnalyzer):
    name = "hook_enhancement"
    version = "1"
    depends_on = ("timeline_initialization", "silence_detection")

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        silences = {
            T.as_str(c.get("clip_id")): T.as_list(c.get("silences"))
            for c in T.as_list((ctx.editing_data("silence_detection") or {}).get("clips"))
        }
        out: list[dict[str, Any]] = []
        for clip in clips:
            bp = _blueprint(plans, clip["clip_id"])
            opening = T.as_dict(bp.get("opening_hook"))
            pacing = T.as_str(T.as_dict(bp.get("pacing")).get("value"))
            payoffs = T.as_list(bp.get("replay_moments"))
            lead_silence = next(
                (s for s in silences.get(clip["clip_id"], []) if T.as_float(s.get("start")) < 0.5),
                None,
            )

            if lead_silence and T.as_float(lead_silence.get("end")) >= 1.0:
                decision = {
                    "type": "fast_start",
                    "reason": "trim the silent lead-in so the clip opens on speech",
                    "suggested_trim_seconds": T.round3(T.as_float(lead_silence.get("end"))),
                    "confidence": 0.6,
                }
            elif opening.get("text") and pacing == "fast":
                decision = {
                    "type": "no_changes",
                    "reason": "the clip already opens on a strong, fast hook",
                    "confidence": 0.6,
                }
            elif payoffs and not opening.get("text"):
                decision = {
                    "type": "preview",
                    "reason": "cold-open with a teaser of the later payoff to set a curiosity gap",
                    "confidence": 0.45,
                }
            elif opening.get("text"):
                decision = {
                    "type": "no_changes",
                    "reason": "opening line is a serviceable hook",
                    "confidence": 0.5,
                }
            else:
                decision = {
                    "type": "unknown",
                    "reason": "insufficient hook/pacing evidence to recommend an enhancement",
                    "confidence": None,
                }
            decision["evidence"] = [
                {"type": "opening_hook", "detail": T.as_str(opening.get("text"))[:80]},
                {"type": "pacing", "detail": pacing},
            ]
            out.append({"clip_id": clip["clip_id"], "decision": decision})
        report(1.0)
        return EditingOutcome.completed(
            {"clips": out, "note": "Hook enhancement decided per clip, with reasoning."}
        )


# --------------------------------------------------------------------------- #
# 12. Retention Planner - pattern-interrupt MARKERS (not effects).
# --------------------------------------------------------------------------- #
class RetentionPlannerAnalyzer(EditingAnalyzer):
    name = "retention_planner"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            markers: list[dict[str, Any]] = []
            for risk in T.as_list(bp.get("retention_risks")):
                rel = T.to_clip_relative(T.as_float(risk.get("timestamp")), cs, duration)
                if rel is None:
                    continue
                markers.append(
                    T.marker(
                        "pattern_interrupt",
                        rel,
                        reason="retention risk here - insert a pattern interrupt (cut/zoom/broll)",
                        confidence=0.5,
                        evidence=[
                            {"type": "retention_risk", "detail": T.as_str(risk.get("reason"))}
                        ],
                    )
                )
            out.append({"clip_id": clip["clip_id"], "checkpoints": markers})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Timeline markers only - where attention may dip. No effects "
                "are inserted; an editor/future engine decides the interrupt.",
            }
        )


# --------------------------------------------------------------------------- #
# 13. Music Planner - intro / drop / ending timestamps (NO selection).
# --------------------------------------------------------------------------- #
class MusicPlannerAnalyzer(EditingAnalyzer):
    name = "music_planner"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            bp = _blueprint(plans, clip["clip_id"])
            markers = [
                T.marker(
                    "music_intro",
                    0.0,
                    reason="music in at clip start",
                    confidence=0.6,
                    evidence=[{"type": "clip_boundary", "detail": "start"}],
                ),
                T.marker(
                    "music_ending",
                    duration,
                    reason="music out at clip end",
                    confidence=0.6,
                    evidence=[{"type": "clip_boundary", "detail": "end"}],
                ),
            ]
            emphasis = T.as_list(bp.get("emphasis_moments")) or T.as_list(bp.get("replay_moments"))
            if emphasis:
                rel = T.to_clip_relative(T.as_float(emphasis[0].get("timestamp")), cs, duration)
                if rel is not None:
                    markers.append(
                        T.marker(
                            "music_drop",
                            rel,
                            reason="align a musical drop with the strongest moment",
                            confidence=0.45,
                            evidence=[{"type": "emphasis", "detail": "peak emphasis/payoff"}],
                        )
                    )
            out.append(
                {
                    "clip_id": clip["clip_id"],
                    "markers": markers,
                    "beats": {
                        "status": "unknown",
                        "reason": "beat detection requires audio analysis (unavailable); "
                        "only structural music timestamps are provided. No track is selected.",
                    },
                }
            )
        report(1.0)
        return EditingOutcome.completed(
            {"clips": out, "note": "Structural music timestamps only - no music is chosen."}
        )


# --------------------------------------------------------------------------- #
# 14. Transition Planner - recommend transition TYPES at cut points.
# --------------------------------------------------------------------------- #
class TransitionPlannerAnalyzer(EditingAnalyzer):
    name = "transition_planner"
    version = "1"
    depends_on = ("jump_cut_detection",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        jump = ctx.editing_data("jump_cut_detection")
        if jump is None:
            return EditingOutcome.unavailable("Requires jump-cut detection, which is unavailable.")
        clips, _ = _per_clip(ctx)
        topic_shifts = T.as_list((ctx.story_data("topic_segmentation") or {}).get("shifts"))
        cuts_by_clip = {
            T.as_str(c.get("clip_id")): T.as_list(c.get("cut_points"))
            for c in T.as_list(jump.get("clips"))
        }
        out: list[dict[str, Any]] = []
        for clip in clips or []:
            cs, _, duration = _window(clip)
            shift_times = {
                T.to_clip_relative(T.as_float(s.get("timestamp")), cs, duration)
                for s in topic_shifts
            }
            shift_times.discard(None)
            transitions: list[dict[str, Any]] = []
            for cut in cuts_by_clip.get(clip["clip_id"], []):
                at = T.as_float(cut.get("start"))
                near_shift = any(abs(at - st) < 1.0 for st in shift_times if st is not None)
                ttype = "cross_dissolve" if near_shift else "hard_cut"
                transitions.append(
                    T.marker(
                        "transition",
                        at,
                        reason="topic shift - a soft transition reads better"
                        if near_shift
                        else "same-topic sentence boundary - a hard cut keeps pace",
                        confidence=0.5,
                        evidence=[{"type": "cut_point", "detail": T.as_str(cut.get("reason"))}],
                        transition_type=ttype,
                    )
                )
            out.append({"clip_id": clip["clip_id"], "transitions": transitions})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Transition TYPES are recommended at cut points (hard cut / "
                "cross dissolve). Nothing is rendered or applied.",
            }
        )


# --------------------------------------------------------------------------- #
# 15. B-roll Planner - describe needed footage (never invent it).
# --------------------------------------------------------------------------- #
class BrollPlannerAnalyzer(EditingAnalyzer):
    name = "broll_planner"
    version = "1"
    depends_on = ("timeline_initialization",)

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips = _clips(ctx)
        if clips is None:
            return EditingOutcome.unavailable(_NO_CLIPS)
        density = T.as_list((ctx.story_data("information_density") or {}).get("windows"))
        out: list[dict[str, Any]] = []
        for clip in clips:
            cs, _, duration = _window(clip)
            suggestions: list[dict[str, Any]] = []
            for window in density:
                if T.as_str(window.get("classification")) != "dense":
                    continue
                rel = T.to_clip_relative(T.as_float(window.get("start")), cs, duration)
                if rel is None:
                    continue
                suggestions.append(
                    T.event(
                        "broll_suggestion",
                        rel,
                        min(duration, rel + 3.0),
                        reason="information-dense passage - B-roll would aid understanding",
                        confidence=0.4,
                        evidence=[
                            {
                                "type": "information_density",
                                "detail": T.as_str(window.get("reason")),
                            }
                        ],
                        description="B-roll needed here; footage is described, never invented",
                    )
                )
            out.append({"clip_id": clip["clip_id"], "suggestions": suggestions})
        report(1.0)
        return EditingOutcome.completed(
            {
                "clips": out,
                "note": "Identifies WHERE B-roll would help and describes the need; "
                "no B-roll footage is invented or selected.",
            }
        )


# --------------------------------------------------------------------------- #
# 16. Timeline Validation - assemble tracks + validate continuity.
# --------------------------------------------------------------------------- #
class TimelineValidationAnalyzer(EditingAnalyzer):
    name = "timeline_validation"
    version = "1"
    depends_on = (
        "timeline_initialization",
        "speech_cleanup",
        "jump_cut_detection",
        "silence_detection",
        "caption_timing",
        "caption_layout",
        "zoom_planner",
        "pan_planner",
        "crop_planner",
        "hook_enhancement",
        "retention_planner",
        "music_planner",
        "transition_planner",
        "broll_planner",
    )

    async def analyze(
        self, ctx: EditingStageContext, report: EditingProgressReporter
    ) -> EditingOutcome:
        clips, plans = _per_clip(ctx)
        if clips is None:
            return EditingOutcome.completed(
                {
                    "timeline_count": 0,
                    "timelines": [],
                    "report": {"valid": True, "clips": [], "issues": []},
                    "note": "No approved clips, so there are no timelines to assemble - "
                    "an honest, valid empty result.",
                }
            )

        by_clip = _index_stages(ctx)
        timelines: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        for clip in clips:
            cid = clip["clip_id"]
            duration = T.as_float(clip.get("duration"))
            bundle = by_clip.get(cid, {})
            timeline = _assemble_timeline(clip, bundle, _blueprint(plans, cid))
            report_entry = _validate_timeline(timeline, duration)
            timelines.append(timeline)
            reports.append(report_entry)

        overall_valid = all(r["valid"] for r in reports)
        report(1.0)
        return EditingOutcome.completed(
            {
                "timeline_count": len(timelines),
                "timelines": timelines,
                "report": {
                    "valid": overall_valid,
                    "clips": reports,
                    "issue_count": sum(len(r["issues"]) for r in reports),
                },
                "note": "Each clip is assembled into video/audio/caption/marker tracks "
                "and checked for broken timestamps, out-of-bounds events, caption "
                "overlaps, and video continuity.",
            }
        )


# --------------------------------------------------------------------------- #
# Assembly + validation helpers (pure).
# --------------------------------------------------------------------------- #
def _index_stages(ctx: EditingStageContext) -> dict[str, dict[str, Any]]:
    """Index every per-clip stage output by clip id for assembly."""

    stages = (
        "speech_cleanup",
        "jump_cut_detection",
        "silence_detection",
        "caption_timing",
        "caption_layout",
        "zoom_planner",
        "pan_planner",
        "crop_planner",
        "hook_enhancement",
        "retention_planner",
        "music_planner",
        "transition_planner",
        "broll_planner",
    )
    out: dict[str, dict[str, Any]] = {}
    for stage in stages:
        data = ctx.editing_data(stage)
        if data is None:
            continue
        for clip in T.as_list(data.get("clips")):
            cid = T.as_str(clip.get("clip_id"))
            out.setdefault(cid, {})[stage] = clip
    return out


def _assemble_timeline(
    clip: dict[str, Any], bundle: dict[str, Any], blueprint: dict[str, Any]
) -> dict[str, Any]:
    duration = T.as_float(clip.get("duration"))
    crop = T.as_dict(T.as_dict(bundle.get("crop_planner")).get("crop"))

    video_events = [clip["base_video_event"]]
    video_events += T.as_list(T.as_dict(bundle.get("zoom_planner")).get("zooms"))
    video_events += T.as_list(T.as_dict(bundle.get("pan_planner")).get("pans"))

    audio_events = [clip["base_audio_event"]]
    audio_events += T.as_list(T.as_dict(bundle.get("silence_detection")).get("silences"))
    audio_events += T.as_list(T.as_dict(bundle.get("speech_cleanup")).get("items"))

    caption_events = T.as_list(T.as_dict(bundle.get("caption_timing")).get("captions"))

    markers: list[dict[str, Any]] = []
    markers += T.as_list(T.as_dict(bundle.get("jump_cut_detection")).get("cut_points"))
    markers += T.as_list(T.as_dict(bundle.get("retention_planner")).get("checkpoints"))
    markers += T.as_list(T.as_dict(bundle.get("music_planner")).get("markers"))
    markers += T.as_list(T.as_dict(bundle.get("transition_planner")).get("transitions"))
    markers += T.as_list(T.as_dict(bundle.get("broll_planner")).get("suggestions"))
    decision = T.as_dict(T.as_dict(bundle.get("hook_enhancement")).get("decision"))
    if decision:
        markers.append(
            T.marker(
                "hook_enhancement",
                0.0,
                reason=T.as_str(decision.get("reason")),
                confidence=decision.get("confidence"),
                evidence=T.as_list(decision.get("evidence")),
                decision=T.as_str(decision.get("type")),
            )
        )
    markers.sort(key=lambda m: T.as_float(m.get("start")))

    layout = T.as_dict(T.as_dict(bundle.get("caption_layout")).get("layout"))
    return {
        "clip_id": clip["clip_id"],
        "plan_id": clip.get("plan_id"),
        "rank": clip.get("rank"),
        "source_video": clip.get("source_video"),
        "source_start": clip.get("source_start"),
        "source_end": clip.get("source_end"),
        "duration": duration,
        "fps": clip.get("fps"),
        "tracks": [
            {"kind": "video", "events": video_events},
            {"kind": "audio", "events": audio_events},
            {"kind": "caption", "events": caption_events},
            {"kind": "markers", "events": markers},
        ],
        "metadata": {
            "aspect_ratio": T.as_str(T.as_dict(blueprint.get("aspect_ratio")).get("value"))
            or "9:16",
            "pacing": T.as_str(T.as_dict(blueprint.get("pacing")).get("value")),
            "title": T.as_str(T.as_dict(blueprint.get("title_suggestion")).get("text")),
            "subtitle_style": T.as_str(T.as_dict(blueprint.get("subtitle_style")).get("style")),
            "caption_layout": layout,
            "crop": crop,
            "hook_decision": T.as_str(decision.get("type")),
            "quality_score": clip.get("quality_score"),
            "confidence": clip.get("confidence"),
        },
    }


def _validate_timeline(timeline: dict[str, Any], duration: float) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    video_events: list[dict[str, Any]] = []
    for track in T.as_list(timeline.get("tracks")):
        events = T.as_list(track.get("events"))
        issues.extend(T.validate_event_bounds(events, duration))
        if track.get("kind") == "caption":
            captions = events
        elif track.get("kind") == "video":
            video_events = events
    issues.extend(T.find_overlaps(captions))
    # Continuity: the base video clip must cover the full clip duration.
    base = next((e for e in video_events if e.get("type") == "source_clip"), None)
    if base is None:
        issues.append({"detail": "missing base video clip (no continuity)"})
    elif abs(T.as_float(base.get("end")) - duration) > 0.05:
        issues.append({"detail": "base video clip does not span the full clip duration"})
    return {"clip_id": timeline.get("clip_id"), "valid": not issues, "issues": issues}
